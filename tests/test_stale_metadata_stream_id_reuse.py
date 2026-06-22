"""Behavioral tests for the stale-metadata / stream-ID-reuse fix.

Two regression groups:

1. **Prevent** — ``_flush_batch`` clears ``metadata_id`` when the channel name
   changes on upsert (stream-ID reuse).  The critical invariant: a stale
   metadata link is severed atomically in the same bulk upsert that carries
   the new channel name, so the next ``get_metadata`` call re-derives from the
   current ``raw_data``.

2. **Backfill migration** — ``MetadataRescanTask`` finds channels whose linked
   ``MetadataDB.title`` has zero token overlap with the current channel name and
   re-derives metadata for them via ``MetadataManager.get_metadata``.  The
   critical invariant: after the migration runs, every previously-stale channel
   has an up-to-date ``MetadataDB`` row derived from its current ``raw_data``.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatv.core.database import ChannelDB, Database, MetadataDB
from metatv.core.provider_loader import ProviderLoadThread
from metatv.core.models import Provider


# ---------------------------------------------------------------------------
# Fixtures
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
def store_thread(tmp_db):
    """ProviderLoadThread pointing at *tmp_db*, no Qt event loop needed."""
    p = Provider.__new__(Provider)
    p.id = "prov1"
    p.name = "Test Provider"
    p.type = "xtream"
    p.url = "http://example.com"
    p.username = "u"
    p.password = "p"
    p.urls = []
    return ProviderLoadThread(p, tmp_db)


def _fake_channel(ch_id: str, name: str, raw_data: dict | None = None) -> MagicMock:
    """Return a duck-typed Channel-like object for use with _store_channels."""
    ch = MagicMock()
    ch.id = ch_id
    ch.source_id = ch_id
    ch.provider_id = "prov1"
    ch.name = name
    ch.stream_url = "http://example.com/stream"
    ch.category = "General"
    ch.category_id = "cat1"
    ch.logo_url = ""
    ch.media_type = "movie"
    ch.quality = MagicMock()
    ch.quality.value = "hd"
    ch.raw_data = raw_data if raw_data is not None else {"info": {"name": name}}
    return ch


def _store(thread: ProviderLoadThread, db: Database, channels: list) -> None:
    """Drive _store_channels with a fresh session."""
    session = db.get_session()
    try:
        thread._store_channels(session, channels, total=len(channels))
    finally:
        session.close()


def _read_channel_metadata_id(db: Database, ch_id: str) -> str | None:
    """Return the metadata_id of a channel row, or None if not found."""
    session = db.get_session()
    try:
        row = session.query(ChannelDB).filter_by(id=ch_id).one_or_none()
        return row.metadata_id if row else None
    finally:
        session.close()


def _set_metadata_id(db: Database, ch_id: str, metadata_id: str, meta_title: str) -> None:
    """Write a MetadataDB row and link it to the channel (simulates a prior derivation)."""
    with db.session_scope() as session:
        meta = MetadataDB(id=metadata_id, title=meta_title, source="provider")
        session.add(meta)
        ch = session.query(ChannelDB).filter_by(id=ch_id).one()
        ch.metadata_id = metadata_id


def _read_metadata_title(db: Database, metadata_id: str) -> str | None:
    """Return the title of a MetadataDB row, or None."""
    session = db.get_session()
    try:
        row = session.query(MetadataDB).filter_by(id=metadata_id).one_or_none()
        return row.title if row else None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 1. Prevent: _flush_batch clears metadata_id on name change
# ---------------------------------------------------------------------------


class TestFlushBatchClearsStaleMetadata:
    """_flush_batch must sever the metadata link when the channel name changes."""

    def test_metadata_id_cleared_when_name_changes(self, store_thread, tmp_db):
        """The core regression: a stream-ID reuse must invalidate the stale metadata link.

        Sequence:
        1. Insert channel "ch1" with name "Old Content".
        2. Attach a MetadataDB row (simulates prior derivation for "Old Content").
        3. Re-store "ch1" with name "New Content" (stream-ID reuse).
        4. Assert metadata_id is now NULL (stale link severed).
        """
        # Step 1: initial insert
        _store(store_thread, tmp_db, [_fake_channel("ch1", "Old Content")])
        assert _read_channel_metadata_id(tmp_db, "ch1") is None

        # Step 2: attach metadata (simulates MetadataManager having cached it)
        _set_metadata_id(tmp_db, "ch1", "meta_ch1", "Old Content Movie")

        assert _read_channel_metadata_id(tmp_db, "ch1") == "meta_ch1", (
            "pre-condition: metadata_id must be set before the name-change upsert"
        )

        # Step 3: re-store with a CHANGED name (stream-ID reuse scenario)
        _store(store_thread, tmp_db, [_fake_channel("ch1", "New Content")])

        # Step 4: metadata_id must be cleared
        result = _read_channel_metadata_id(tmp_db, "ch1")
        assert result is None, (
            f"metadata_id should be NULL after a name change (stream-ID reuse); "
            f"got {result!r}"
        )

    def test_metadata_id_preserved_when_name_unchanged(self, store_thread, tmp_db):
        """A refresh that does NOT change the name must preserve the metadata link.

        Regression guard: the fix must only fire when names actually differ.
        """
        # Insert and attach metadata
        _store(store_thread, tmp_db, [_fake_channel("ch2", "Same Content")])
        _set_metadata_id(tmp_db, "ch2", "meta_ch2", "Same Content Movie")

        # Re-store with the SAME name (ordinary refresh — stream URL may change, name stays)
        _store(store_thread, tmp_db, [
            _fake_channel("ch2", "Same Content", raw_data={"info": {"name": "Same Content"}, "stream": "new_url"})
        ])

        result = _read_channel_metadata_id(tmp_db, "ch2")
        assert result == "meta_ch2", (
            f"metadata_id must be preserved when the channel name is unchanged; "
            f"got {result!r}"
        )

    def test_new_channels_start_with_null_metadata_id(self, store_thread, tmp_db):
        """A brand-new channel (first-ever insert) must not get a spurious metadata_id."""
        _store(store_thread, tmp_db, [_fake_channel("ch3", "Fresh Channel")])
        assert _read_channel_metadata_id(tmp_db, "ch3") is None, (
            "brand-new channel must start with metadata_id=NULL"
        )

    def test_catalog_fields_still_update_on_name_change(self, store_thread, tmp_db):
        """Clearing metadata_id must not prevent other catalog fields from updating."""
        _store(store_thread, tmp_db, [_fake_channel("ch4", "Old Name")])
        _set_metadata_id(tmp_db, "ch4", "meta_ch4", "Old Name Movie")

        new_ch = _fake_channel("ch4", "New Name")
        new_ch.stream_url = "http://example.com/new-stream"
        _store(store_thread, tmp_db, [new_ch])

        # Name must be updated
        session = tmp_db.get_session()
        try:
            row = session.query(ChannelDB).filter_by(id="ch4").one()
            assert row.name == "New Name", f"name must update to 'New Name'; got {row.name!r}"
            assert row.metadata_id is None, "metadata_id must be cleared after name change"
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 2. Backfill: MetadataRescanTask re-derives stale links
# ---------------------------------------------------------------------------


def _make_minimal_metadata_manager(db: Database):
    """Build a real MetadataManager wired to a real ProviderMetadataProvider."""
    from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
    from metatv.metadata_providers.provider_metadata import ProviderMetadataProvider

    registry = MetadataProviderRegistry()
    registry.register(ProviderMetadataProvider(db))
    return MetadataManager(registry, db)


def _insert_channel_with_stale_metadata(
    db: Database,
    *,
    ch_id: str,
    current_name: str,
    current_raw_data: dict,
    stale_meta_title: str,
) -> None:
    """Insert a ChannelDB row + MetadataDB row that simulates the stale-link scenario.

    The channel now has *current_name* / *current_raw_data* (fresh from a provider
    refresh), but the linked MetadataDB.title belongs to a previous occupant.
    """
    with db.session_scope() as session:
        meta_id = f"meta_{ch_id}"
        session.add(MetadataDB(id=meta_id, title=stale_meta_title, source="provider"))
        session.add(ChannelDB(
            id=ch_id,
            source_id=ch_id,
            provider_id="prov1",
            name=current_name,
            media_type="movie",
            metadata_id=meta_id,
            raw_data=current_raw_data,
        ))


class TestMetadataRescanTask:
    """MetadataRescanTask must re-derive stale metadata links."""

    def test_needs_run_true_when_version_is_zero(self, tmp_db):
        """needs_run returns True for a fresh config (version=0)."""
        from metatv.core.migrations.metadata_rescan import (
            CURRENT_METADATA_RESCAN_VERSION,
            MetadataRescanTask,
        )
        mm = _make_minimal_metadata_manager(tmp_db)
        task = MetadataRescanTask(tmp_db, mm)

        config = MagicMock()
        config.metadata_rescan_version = 0
        assert task.needs_run(config) is True

    def test_needs_run_false_when_version_current(self, tmp_db):
        """needs_run returns False once the version is up to date."""
        from metatv.core.migrations.metadata_rescan import (
            CURRENT_METADATA_RESCAN_VERSION,
            MetadataRescanTask,
        )
        mm = _make_minimal_metadata_manager(tmp_db)
        task = MetadataRescanTask(tmp_db, mm)

        config = MagicMock()
        config.metadata_rescan_version = CURRENT_METADATA_RESCAN_VERSION
        assert task.needs_run(config) is False

    def test_on_completed_bumps_version_and_saves(self, tmp_db):
        """on_completed sets metadata_rescan_version and calls config.save()."""
        from metatv.core.migrations.metadata_rescan import (
            CURRENT_METADATA_RESCAN_VERSION,
            MetadataRescanTask,
        )
        mm = _make_minimal_metadata_manager(tmp_db)
        task = MetadataRescanTask(tmp_db, mm)

        config = MagicMock()
        task.on_completed(config)

        assert config.metadata_rescan_version == CURRENT_METADATA_RESCAN_VERSION, (
            "on_completed must set metadata_rescan_version to the current version"
        )
        config.save.assert_called_once()

    def test_stale_link_is_re_derived_after_migration(self, tmp_db):
        """The migration re-derives metadata for a stale channel.

        The channel "|NL| Bloodlands" has a stale link to metadata titled
        "Dan Da Dan" (zero token overlap → detected as stale).  After the
        migration the MetadataDB row reflects the *current* raw_data
        (which has title "Bloodlands").
        """
        from metatv.core.migrations.metadata_rescan import MetadataRescanTask

        # Seed a channel with raw_data whose title is "Bloodlands" but the
        # linked MetadataDB.title belongs to the old occupant ("Dan Da Dan").
        ch_id = str(uuid.uuid4())
        _insert_channel_with_stale_metadata(
            tmp_db,
            ch_id=ch_id,
            current_name="|NL| Bloodlands",
            current_raw_data={"info": {"name": "Bloodlands", "plot": "A detective story"}},
            stale_meta_title="Dan Da Dan",
        )

        mm = _make_minimal_metadata_manager(tmp_db)
        task = MetadataRescanTask(tmp_db, mm)

        progress_calls: list[tuple[int, int]] = []
        task.run(
            progress_cb=lambda d, t: progress_calls.append((d, t)),
            is_cancelled=lambda: False,
        )

        # The MetadataDB row for this channel must now reflect the current raw_data.
        session = tmp_db.get_session()
        try:
            ch = session.query(ChannelDB).filter_by(id=ch_id).one()
            assert ch.metadata_id is not None, (
                "channel must still have a metadata_id after re-derivation"
            )
            meta = session.query(MetadataDB).filter_by(id=ch.metadata_id).one()
            assert meta.title == "Bloodlands", (
                f"MetadataDB.title should be 'Bloodlands' after re-derivation; "
                f"got {meta.title!r}"
            )
        finally:
            session.close()

        assert len(progress_calls) >= 1, "progress_cb must be called at least once"

    def test_fresh_channel_with_correct_metadata_is_not_re_derived(self, tmp_db):
        """A channel whose metadata title matches the channel name is left alone.

        If "Bloodlands" has metadata title "Bloodlands" (matching) the migration
        must NOT re-derive it — the link is fresh.
        """
        from metatv.core.migrations.metadata_rescan import MetadataRescanTask

        ch_id = str(uuid.uuid4())
        # Insert a channel with MATCHING metadata title — not stale.
        with tmp_db.session_scope() as session:
            meta_id = f"meta_{ch_id}"
            session.add(MetadataDB(
                id=meta_id,
                title="Bloodlands",  # Correct title — matches channel
                source="provider",
            ))
            session.add(ChannelDB(
                id=ch_id,
                source_id=ch_id,
                provider_id="prov1",
                name="|NL| Bloodlands",
                detected_title="Bloodlands",  # stored at ingestion
                media_type="movie",
                metadata_id=meta_id,
                raw_data={"info": {"name": "Bloodlands"}},
            ))

        mm = _make_minimal_metadata_manager(tmp_db)
        # Spy on get_metadata to verify it is NOT called for this channel
        original_get = mm.get_metadata
        calls = []

        async def _spy(channel_id, force_refresh=False):
            calls.append(channel_id)
            return await original_get(channel_id, force_refresh=force_refresh)

        mm.get_metadata = _spy

        task = MetadataRescanTask(tmp_db, mm)
        task.run(progress_cb=lambda d, t: None, is_cancelled=lambda: False)

        assert ch_id not in calls, (
            "MetadataManager.get_metadata must NOT be called for a channel whose "
            "metadata title already matches the channel name"
        )

    def test_run_with_no_stale_channels_is_a_noop(self, tmp_db):
        """run() with no stale channels calls progress_cb(0, 0) and returns cleanly."""
        from metatv.core.migrations.metadata_rescan import MetadataRescanTask

        mm = _make_minimal_metadata_manager(tmp_db)
        task = MetadataRescanTask(tmp_db, mm)

        calls: list[tuple[int, int]] = []
        task.run(
            progress_cb=lambda d, t: calls.append((d, t)),
            is_cancelled=lambda: False,
        )

        assert calls == [(0, 0)], f"expected [(0, 0)], got {calls!r}"

    def test_cancellation_stops_after_first_batch(self, tmp_db):
        """Cancellation mid-run leaves work done so far durable but exits early."""
        from metatv.core.migrations.metadata_rescan import MetadataRescanTask, _BATCH_SIZE

        # Seed 2 stale channels (two separate batches if _BATCH_SIZE == 1,
        # but _BATCH_SIZE is 500 so they'll be in one batch — cancel before it
        # by returning True on the very first is_cancelled call).
        for i in range(2):
            ch_id = f"ch_cancel_{i}"
            _insert_channel_with_stale_metadata(
                tmp_db,
                ch_id=ch_id,
                current_name=f"|NL| SomeMovie{i}",
                current_raw_data={"info": {"name": f"SomeMovie{i}"}},
                stale_meta_title=f"UnrelatedTitle{i}",
            )

        mm = _make_minimal_metadata_manager(tmp_db)
        task = MetadataRescanTask(tmp_db, mm)

        # Cancel immediately on the very first is_cancelled check.
        task.run(
            progress_cb=lambda d, t: None,
            is_cancelled=lambda: True,  # cancel before any batch runs
        )

        # Both channels should still have the stale metadata_id (no re-derivation).
        for i in range(2):
            ch_id = f"ch_cancel_{i}"
            session = tmp_db.get_session()
            try:
                ch = session.query(ChannelDB).filter_by(id=ch_id).one()
                meta = session.query(MetadataDB).filter_by(id=ch.metadata_id).one()
                assert meta.title == f"UnrelatedTitle{i}", (
                    f"Metadata must be unchanged for channel {ch_id} when cancelled "
                    f"before any batch runs; got {meta.title!r}"
                )
            finally:
                session.close()


# ---------------------------------------------------------------------------
# 3. Staleness-detection unit tests
# ---------------------------------------------------------------------------


class TestStalenessDetection:
    """Unit tests for the _is_stale_link helper."""

    def test_completely_unrelated_titles_are_stale(self):
        """Zero token overlap → stale."""
        from metatv.core.migrations.metadata_rescan import _is_stale_link

        assert _is_stale_link(
            channel_name="|NL| Bloodlands",
            detected_title=None,
            metadata_title="Dan Da Dan",
        ) is True

    def test_matching_detected_title_is_not_stale(self):
        """Shared token between detected_title and metadata_title → not stale."""
        from metatv.core.migrations.metadata_rescan import _is_stale_link

        assert _is_stale_link(
            channel_name="|NL| Bloodlands",
            detected_title="Bloodlands",
            metadata_title="Bloodlands",
        ) is False

    def test_partial_token_overlap_is_not_stale(self):
        """Even a single shared token is enough to consider the link valid."""
        from metatv.core.migrations.metadata_rescan import _is_stale_link

        assert _is_stale_link(
            channel_name="EN - The Village (2004)",
            detected_title=None,
            metadata_title="The Village",
        ) is False

    def test_short_tokens_ignored(self):
        """Tokens shorter than _MIN_TOKEN_LEN are not counted as overlap.

        "HD" is 2 chars — below the 3-char minimum — so two titles sharing only
        "HD" must be flagged as stale (zero qualifying tokens in common).
        """
        from metatv.core.migrations.metadata_rescan import _is_stale_link

        # "HD" is the only shared substring but it's too short to count.
        # "Channel" vs "Movie" → no overlap → stale.
        assert _is_stale_link(
            channel_name="HD Channel",
            detected_title=None,
            metadata_title="HD Movie",
        ) is True, "sharing only short tokens like 'HD' must be treated as stale"

    def test_empty_metadata_title_is_not_stale(self):
        """Empty metadata title → can't determine → not stale (conservative)."""
        from metatv.core.migrations.metadata_rescan import _is_stale_link

        assert _is_stale_link(
            channel_name="|NL| SomeChannel",
            detected_title=None,
            metadata_title="",
        ) is False

    def test_alpha_tokens_extracts_long_words(self):
        """_alpha_tokens returns words ≥ _MIN_TOKEN_LEN, lower-cased."""
        from metatv.core.migrations.metadata_rescan import _alpha_tokens, _MIN_TOKEN_LEN

        result = _alpha_tokens("|NL| Bloodlands HD")
        assert "bloodlands" in result
        assert "hd" not in result, "short token 'hd' must be excluded"
        assert "nl" not in result, "short token 'nl' must be excluded"
