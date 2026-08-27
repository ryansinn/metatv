"""Behavioral tests for stream-ID reuse detection/logging in ``ProviderLoadThread``.

Detection-only: proves ``_snapshot_engaged_names`` / ``_report_recycled_ids``
correctly flag engaged channels (favorite/hidden/suppressed/played/completed/
rated/queued) whose title changed during a refresh, and stay silent for
everyone else. No favorite is dropped, moved, or re-pointed by this code —
it only warns, via loguru, so the evidence is recoverable from the log
instead of being silently overwritten by the next refresh.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from loguru import logger

from metatv.core.database import ChannelDB, Database, UserRatingDB, WatchQueueDB
from metatv.core.models import Provider
from metatv.core.provider_loader import ProviderLoadThread


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path):
    """File-backed SQLite Database — isolated per test, not :memory:."""
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def captured_warnings():
    """Capture loguru WARNING+ records emitted during a test via a list sink."""
    captured: list[str] = []
    sink_id = logger.add(captured.append, level="WARNING")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


def _make_provider(provider_id: str = "p1") -> Provider:
    """Duck-typed Provider — mirrors the pattern in test_stale_metadata_stream_id_reuse.py."""
    p = Provider.__new__(Provider)
    p.id = provider_id
    p.name = f"Provider {provider_id}"
    p.type = "xtream"
    p.url = "http://example.com"
    p.username = "u"
    p.password = "p"
    p.urls = []
    return p


def _make_thread(db: Database, provider_id: str = "p1") -> ProviderLoadThread:
    """Real ProviderLoadThread — constructed but never .start()/.run(), so no thread starts."""
    return ProviderLoadThread(_make_provider(provider_id), db)


def _seed_channel(db: Database, **kwargs) -> None:
    """Insert a ChannelDB row with sane defaults for fields the test doesn't care about."""
    defaults = {
        "source_id": kwargs.get("id", ""),
        "provider_id": "p1",
        "name": "Unnamed",
        "media_type": "movie",
    }
    defaults.update(kwargs)
    with db.session_scope() as session:
        session.add(ChannelDB(**defaults))


def _fake_channel(ch_id: str, name: str, provider_id: str = "p1") -> MagicMock:
    """Duck-typed Channel-like object accepted by ProviderLoadThread._store_channels."""
    ch = MagicMock()
    ch.id = ch_id
    ch.source_id = ch_id
    ch.provider_id = provider_id
    ch.name = name
    ch.stream_url = "http://example.com/stream"
    ch.category = "General"
    ch.category_id = "cat1"
    ch.logo_url = ""
    ch.media_type = "movie"
    ch.quality = MagicMock()
    ch.quality.value = "hd"
    ch.raw_data = {"info": {"name": name}}
    ch.detected_tmdb_id = None
    return ch


def _warned_about(lines: list[str], *needles: str) -> bool:
    """True if some captured line contains STREAM-ID REUSE and every needle."""
    return any(
        "STREAM-ID REUSE" in line and all(n in line for n in needles)
        for line in lines
    )


# ---------------------------------------------------------------------------
# 1. Favorited channel whose name changed -> warned
# ---------------------------------------------------------------------------


def test_favorited_channel_name_change_is_warned(tmp_db, captured_warnings):
    thread = _make_thread(tmp_db)
    _seed_channel(tmp_db, id="p1_5544", source_id="5544", name="Old Movie", is_favorite=True)

    session = tmp_db.get_session()
    try:
        before = thread._snapshot_engaged_names(session)
        assert before == {"p1_5544": "Old Movie"}

        row = session.query(ChannelDB).filter_by(id="p1_5544").one()
        row.name = "New Movie"
        session.commit()

        thread._report_recycled_ids(session, before)
    finally:
        session.close()

    assert _warned_about(captured_warnings, "p1_5544", "Old Movie", "New Movie"), (
        f"expected a STREAM-ID REUSE warning naming the channel id and BOTH the "
        f"old and new titles; got {captured_warnings!r}"
    )


# ---------------------------------------------------------------------------
# 2. Engaged only via the watch queue -> warned
# ---------------------------------------------------------------------------


def test_watch_queue_only_engagement_is_warned(tmp_db, captured_warnings):
    thread = _make_thread(tmp_db)
    _seed_channel(tmp_db, id="p1_100", source_id="100", name="Old Show")
    with tmp_db.session_scope() as session:
        session.add(WatchQueueDB(
            channel_id="p1_100", channel_name="Old Show", media_type="series", source_id="100",
        ))

    session = tmp_db.get_session()
    try:
        before = thread._snapshot_engaged_names(session)
        assert before == {"p1_100": "Old Show"}, (
            "a channel with no flags set but a WatchQueueDB row must still be 'engaged'"
        )

        row = session.query(ChannelDB).filter_by(id="p1_100").one()
        row.name = "New Show"
        session.commit()

        thread._report_recycled_ids(session, before)
    finally:
        session.close()

    assert _warned_about(captured_warnings, "p1_100", "Old Show", "New Show")


# ---------------------------------------------------------------------------
# 3. Engaged only via a rating -> warned
# ---------------------------------------------------------------------------


def test_rating_only_engagement_is_warned(tmp_db, captured_warnings):
    thread = _make_thread(tmp_db)
    _seed_channel(tmp_db, id="p1_200", source_id="200", name="Old Doc")
    with tmp_db.session_scope() as session:
        session.add(UserRatingDB(channel_id="p1_200", rating=1))

    session = tmp_db.get_session()
    try:
        before = thread._snapshot_engaged_names(session)
        assert before == {"p1_200": "Old Doc"}, (
            "a channel with no flags set but a UserRatingDB row must still be 'engaged'"
        )

        row = session.query(ChannelDB).filter_by(id="p1_200").one()
        row.name = "New Doc"
        session.commit()

        thread._report_recycled_ids(session, before)
    finally:
        session.close()

    assert _warned_about(captured_warnings, "p1_200", "Old Doc", "New Doc")


# ---------------------------------------------------------------------------
# 4. Un-engaged channel whose name changed -> NOT warned (anti-noise)
# ---------------------------------------------------------------------------


def test_unengaged_channel_name_change_is_silent(tmp_db, captured_warnings):
    thread = _make_thread(tmp_db)
    _seed_channel(tmp_db, id="p1_300", source_id="300", name="Old Series")

    session = tmp_db.get_session()
    try:
        before = thread._snapshot_engaged_names(session)
        assert before == {}, "an un-engaged channel must never enter the snapshot"

        row = session.query(ChannelDB).filter_by(id="p1_300").one()
        row.name = "New Series"
        session.commit()

        thread._report_recycled_ids(session, before)
    finally:
        session.close()

    assert captured_warnings == [], (
        "ordinary provider re-titles for un-engaged channels must stay silent — "
        f"this is the anti-noise guarantee across a 240k-row catalog; got {captured_warnings!r}"
    )


# ---------------------------------------------------------------------------
# 5. Engaged channel whose name is unchanged -> NOT warned
# ---------------------------------------------------------------------------


def test_engaged_channel_name_unchanged_is_silent(tmp_db, captured_warnings):
    thread = _make_thread(tmp_db)
    _seed_channel(tmp_db, id="p1_400", source_id="400", name="Steady Title", is_favorite=True)

    session = tmp_db.get_session()
    try:
        before = thread._snapshot_engaged_names(session)
        assert before == {"p1_400": "Steady Title"}

        thread._report_recycled_ids(session, before)
    finally:
        session.close()

    assert captured_warnings == [], (
        f"a name that did not change must never be reported; got {captured_warnings!r}"
    )


# ---------------------------------------------------------------------------
# 6. Scoping: a different provider_id's engaged channel is excluded
# ---------------------------------------------------------------------------


def test_snapshot_scoped_to_provider(tmp_db):
    thread = _make_thread(tmp_db, provider_id="p1")
    _seed_channel(
        tmp_db, id="p2_999", source_id="999", provider_id="p2",
        name="Other Provider Favorite", is_favorite=True,
    )

    session = tmp_db.get_session()
    try:
        before = thread._snapshot_engaged_names(session)
    finally:
        session.close()

    assert before == {}, (
        f"an engaged channel belonging to a DIFFERENT provider_id must not appear "
        f"in this provider's snapshot at all; got {before!r}"
    )


# ---------------------------------------------------------------------------
# 7. Wiring: _store_channels snapshots BEFORE the upsert, reports AFTER
# ---------------------------------------------------------------------------


def test_store_channels_wiring_reports_reuse_for_favorited_channel(tmp_db, captured_warnings):
    """End-to-end through the real _store_channels wiring.

    The snapshot must be taken before the batch upsert runs; the report must
    run after the final flush. If the snapshot were taken AFTER the upsert
    loop instead, ``before`` would already read the new name and this test
    would go silent — this is the ordering the mutation check specifically
    targets.
    """
    thread = _make_thread(tmp_db)
    _seed_channel(tmp_db, id="p1_5544", source_id="5544", name="Old Movie", is_favorite=True)

    session = tmp_db.get_session()
    try:
        thread._store_channels(session, [_fake_channel("p1_5544", "New Movie")], total=1)
    finally:
        session.close()

    assert _warned_about(captured_warnings, "p1_5544", "Old Movie", "New Movie"), (
        f"expected a STREAM-ID REUSE warning to surface through the real "
        f"_store_channels wiring; got {captured_warnings!r}"
    )
