"""Behavioral tests for the ID-based chunking in _categorize_special_content (B4).

Guards against the OOM bug where _categorize_special_content materialised all
provider channels (including the large raw_data JSON column) as full ORM objects
at once.  The fix fetches IDs first, then processes in _CATEGORIZE_BATCH-sized
chunks with commit + expunge_all between batches.

Tests verify:
  1. All matching channels across a > _CATEGORIZE_BATCH boundary get processed.
  2. Channels with special_view already set are not re-processed.
  3. The final partial batch is not dropped (off-by-one / fencepost guard).
  4. Channels from a different provider are not touched.
"""

from __future__ import annotations

import uuid
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ChannelDB, ProviderDB
from metatv.core.provider_loader import ProviderLoadThread
from metatv.core.models import Provider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CATEGORIZE_BATCH = 2000  # must match the constant inside _categorize_special_content


@pytest.fixture
def tmp_db(tmp_path):
    """File-backed SQLite Database — isolated per test, not :memory:."""
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def fake_provider():
    """Minimal Provider (not ProviderDB) for ProviderLoadThread."""
    p = Provider.__new__(Provider)
    p.id = "prov-main"
    p.name = "Main Provider"
    p.type = "xtream"
    p.url = "http://example.com"
    p.username = "user"
    p.password = "pass"
    p.urls = []
    return p


def _make_thread(fake_provider, tmp_db) -> ProviderLoadThread:
    """Return a ProviderLoadThread with a no-op progress signal."""
    thread = ProviderLoadThread(fake_provider, tmp_db)
    # Disconnect the real Qt signal so no event loop is needed
    try:
        thread.progress.disconnect()
    except Exception:
        pass
    return thread


def _seed_channels(
    db: Database,
    provider_id: str,
    count: int,
    name_template: str = "ESPN Sports Channel {i}",  # "sport" → triggers sports view
    special_view: str | None = None,
    stream_url: str = "http://example.com/stream",
    media_type: str = "live",
) -> list[str]:
    """Seed *count* channels for *provider_id* and return their ids."""
    ids = []
    with db.session_scope() as session:
        # Ensure ProviderDB row exists (FK-free but satisfies explicit queries)
        if not session.query(ProviderDB).filter_by(id=provider_id).first():
            session.add(ProviderDB(
                id=provider_id, name=provider_id, type="xtream",
                url="http://example.com", username="u", password="p",
            ))
            session.flush()

        for i in range(count):
            cid = str(uuid.uuid4())
            session.add(ChannelDB(
                id=cid,
                source_id=cid,
                provider_id=provider_id,
                name=name_template.format(i=i),
                media_type=media_type,
                stream_url=stream_url,
                special_view=special_view,
                category="Sports",
            ))
            ids.append(cid)
    return ids


# ---------------------------------------------------------------------------
# Test 1: all channels processed across the batch boundary
# ---------------------------------------------------------------------------

def test_all_channels_processed_across_batch_boundary(tmp_db, fake_provider):
    """Seed more than _CATEGORIZE_BATCH channels; every one must be categorised.

    This is the primary regression guard: if the old all-at-once code OOMed
    or the new chunked code dropped the final batch, some channels would have
    special_view=None after the call.
    """
    total = _CATEGORIZE_BATCH + 500  # spans two batches; second is a partial

    # "sport" keyword in name → detect_sports_channel returns True → special_view="sports"
    ids = _seed_channels(tmp_db, fake_provider.id, total, name_template="ESPN Sport {i}")

    thread = _make_thread(fake_provider, tmp_db)
    thread._categorize_special_content()

    session = tmp_db.get_session()
    try:
        # Every seeded channel should now have special_view set
        uncategorized = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.provider_id == fake_provider.id,
                ChannelDB.special_view.is_(None),
            )
            .count()
        )
        assert uncategorized == 0, (
            f"{uncategorized} channel(s) still have special_view=None after categorisation "
            f"(total={total}); the final partial batch may have been dropped"
        )

        # Spot-check channels spanning the batch boundary
        sports_count = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.provider_id == fake_provider.id,
                ChannelDB.special_view == "sports",
            )
            .count()
        )
        assert sports_count == total, (
            f"Expected {total} sports channels, got {sports_count}"
        )

        # Spot-check one channel near the batch boundary (index ~_CATEGORIZE_BATCH - 1)
        boundary_id = ids[_CATEGORIZE_BATCH - 1]
        boundary_ch = session.query(ChannelDB).filter_by(id=boundary_id).one()
        assert boundary_ch.special_view == "sports", (
            f"Channel at batch boundary (idx={_CATEGORIZE_BATCH-1}) has "
            f"special_view={boundary_ch.special_view!r}; expected 'sports'"
        )

        # Spot-check one channel in the second (partial) batch
        second_batch_id = ids[_CATEGORIZE_BATCH + 100]
        second_ch = session.query(ChannelDB).filter_by(id=second_batch_id).one()
        assert second_ch.special_view == "sports", (
            f"Channel in partial second batch has special_view={second_ch.special_view!r}; "
            "the final batch appears to have been dropped"
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Test 2: already-categorised channels are skipped
# ---------------------------------------------------------------------------

def test_already_categorized_channels_are_skipped(tmp_db, fake_provider):
    """Channels with special_view already set must not be re-processed.

    The query filters special_view IS NULL, so pre-set channels are outside
    the id list entirely — their values must be unchanged after the call.
    """
    # Seed 5 channels already marked as "ppv" (should be skipped)
    pre_categorized_ids = _seed_channels(
        tmp_db, fake_provider.id, 5,
        name_template="PPV Event {i}",
        special_view="ppv",
    )
    # Seed 10 uncategorized sports channels (should be processed)
    new_ids = _seed_channels(
        tmp_db, fake_provider.id, 10, name_template="ESPN Sport {i}"
    )

    thread = _make_thread(fake_provider, tmp_db)
    thread._categorize_special_content()

    session = tmp_db.get_session()
    try:
        # Pre-categorised channels must still be "ppv" (not overwritten)
        for cid in pre_categorized_ids:
            ch = session.query(ChannelDB).filter_by(id=cid).one()
            assert ch.special_view == "ppv", (
                f"Pre-categorised channel {cid} had special_view overwritten; "
                f"got {ch.special_view!r}"
            )

        # Newly seeded channels must now be categorised
        for cid in new_ids:
            ch = session.query(ChannelDB).filter_by(id=cid).one()
            assert ch.special_view is not None, (
                f"Uncategorised channel {cid} still has special_view=None after call"
            )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Test 3: channels from a different provider are not touched
# ---------------------------------------------------------------------------

def test_other_provider_channels_not_touched(tmp_db, fake_provider):
    """_categorize_special_content must scope to self.provider.id only."""
    other_provider_id = "prov-other"

    # Seed channels on the target provider
    _seed_channels(tmp_db, fake_provider.id, 5, name_template="ESPN Sport {i}")
    # Seed channels on a different provider that would match if queried
    other_ids = _seed_channels(
        tmp_db, other_provider_id, 5,
        name_template="ESPN Sport Other {i}",
    )

    thread = _make_thread(fake_provider, tmp_db)
    thread._categorize_special_content()

    session = tmp_db.get_session()
    try:
        for cid in other_ids:
            ch = session.query(ChannelDB).filter_by(id=cid).one()
            assert ch.special_view is None, (
                f"Channel {cid} on other provider was incorrectly categorised: "
                f"special_view={ch.special_view!r}"
            )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Test 4: no channels → early return, no error
# ---------------------------------------------------------------------------

def test_no_uncategorized_channels_is_no_op(tmp_db, fake_provider):
    """If all channels are already categorised (or there are none), the
    method must return cleanly without error."""
    # Seed a few pre-categorised channels
    _seed_channels(
        tmp_db, fake_provider.id, 3,
        name_template="Already Done {i}",
        special_view="sports",
    )

    thread = _make_thread(fake_provider, tmp_db)
    # Should not raise
    thread._categorize_special_content()

    session = tmp_db.get_session()
    try:
        count = session.query(ChannelDB).filter(
            ChannelDB.provider_id == fake_provider.id,
            ChannelDB.special_view.is_(None),
        ).count()
        assert count == 0
    finally:
        session.close()
