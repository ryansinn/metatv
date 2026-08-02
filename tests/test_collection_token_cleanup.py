"""Behavioral tests for the redundant-collection-token cleanup
(wave7/collection-token-cleanup).

Owner report (side-by-side preview): the comfy row's line-2 collection chip
(``detected_collection``) repeats tokens the row already shows via its own
line-1 chips/icon — a quality tier duplicating the quality chip, a
media-type word duplicating the media-type icon, or a multi/sub marker
duplicating the subtitle-marker chip. Real examples: "MULTISUB SERIES 4K"
(every token redundant -> no chip at all) and "|MULTI| APPLE+ KIDS" (->
"APPLE+ KIDS").

Coverage:
1. ``strip_collection_noise_tokens`` — the pure function (channel_name_utils.py):
   both real examples, token-boundary safety (24K / SERIES MANIA survive
   intact), a byte-identical passthrough for a clean collection, and
   None/empty passthrough.
2. Ingestion routing (``update_detected_prefixes``, real Database on
   tmp_path) — asserts against the STORED ``detected_collection`` field,
   proving the cleanup is resolved at ingestion, not at render time.
3. ``CollectionTokenCleanupBackfillTask`` — version gate, rewrites
   pre-existing rows, leaves already-clean rows untouched, and the
   crash-retry contract (a run() that raises must NOT bump the version),
   modeled on test_category_marker_row_layout.py.
"""

from __future__ import annotations

import threading
import uuid
from unittest.mock import MagicMock

import pytest

from metatv.core.channel_name_utils import strip_collection_noise_tokens


# ---------------------------------------------------------------------------
# 1. strip_collection_noise_tokens — pure function
# ---------------------------------------------------------------------------

class TestStripCollectionNoiseTokens:

    def test_all_noise_tokens_collapse_to_empty(self):
        # Real owner example: quality (4K) + media-type (SERIES) + multi-sub
        # (MULTISUB) — every token is a duplicate of a chip/icon already on
        # the row, so nothing should be left.
        assert strip_collection_noise_tokens("MULTISUB SERIES 4K") == ""

    def test_leading_bracket_marker_stripped_rest_kept(self):
        # Real owner example: "|MULTI|" is a leading bracket marker
        # parse_category_marker() left alone (its code is 5 chars, past that
        # regex's 2-4 char slot) — stripped here because every token inside
        # the brackets is noise; the meaningful rest survives.
        assert strip_collection_noise_tokens("|MULTI| APPLE+ KIDS") == "APPLE+ KIDS"

    def test_quality_token_boundary_safety(self):
        # "4K" must not damage a collection legitimately named "24K" —
        # whole-token match only, never a substring.
        assert strip_collection_noise_tokens("24K") == "24K"

    def test_media_type_token_boundary_safety(self):
        # "SERIES" must not touch "SERIES MANIA" — MANIA is not noise, so
        # the whole free-text body is left untouched (the all-tokens-noise
        # gate only fires when EVERY leaf is redundant).
        assert strip_collection_noise_tokens("SERIES MANIA") == "SERIES MANIA"

    def test_clean_collection_byte_identical(self):
        # No redundant tokens at all — must come back unchanged.
        assert strip_collection_noise_tokens("APPLE+ KIDS") == "APPLE+ KIDS"
        assert strip_collection_noise_tokens("NETFLIX") == "NETFLIX"

    def test_none_and_empty_passthrough(self):
        assert strip_collection_noise_tokens(None) is None
        assert strip_collection_noise_tokens("") == ""


# ---------------------------------------------------------------------------
# Shared DB fixtures/helpers (real file-backed Database — CLAUDE.md tests rule)
# ---------------------------------------------------------------------------

@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path / 'collection_token_cleanup.db'}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def cfg(tmp_path):
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


def _add_provider(db) -> None:
    from metatv.core.database import ProviderDB

    session = db.get_session()
    try:
        session.add(ProviderDB(
            id="p1", name="P", type="xtream", url="http://x.example.com", is_active=True,
        ))
        session.commit()
    finally:
        session.close()


def _add_channel(db, *, name: str, category: str | None,
                  media_type: str = "movie") -> str:
    """Insert a bare (pre-ingestion) ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    channel_id = str(uuid.uuid4())
    session = db.get_session()
    try:
        session.add(ChannelDB(
            id=channel_id, source_id=channel_id, provider_id="p1",
            name=name, media_type=media_type, category=category,
        ))
        session.commit()
    finally:
        session.close()
    return channel_id


def _run_ingestion(db) -> None:
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        RepositoryFactory(session).channels.update_detected_prefixes(provider_id=None)


def _get(db, channel_id: str):
    from metatv.core.database import ChannelDB

    session = db.get_session()
    try:
        return session.query(ChannelDB).filter(ChannelDB.id == channel_id).one()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 2. Ingestion routing — asserts the STORED field
# ---------------------------------------------------------------------------

class TestIngestionStripsCollectionNoise:

    def test_fully_redundant_category_yields_no_chip(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(
            file_db, name="Some Channel", category="MULTISUB SERIES 4K",
            media_type="series",
        )
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_collection is None, (
            "every token duplicated a chip/icon already on the row — "
            "the stored field must be empty so no chip renders"
        )

    def test_leading_bracket_marker_stripped_rest_stored(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(
            file_db, name="Kids Show", category="|MULTI| APPLE+ KIDS",
        )
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_collection == "APPLE+ KIDS"

    def test_quality_boundary_safety_stored(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="Some Channel", category="24K")
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_collection == "24K"

    def test_media_type_boundary_safety_stored(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(
            file_db, name="Some Channel", category="SERIES MANIA",
            media_type="live",
        )
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_collection == "SERIES MANIA"

    def test_clean_collection_stored_unchanged(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="Some Channel", category="NETFLIX")
        _run_ingestion(file_db)

        ch = _get(file_db, cid)
        assert ch.detected_collection == "NETFLIX"


# ---------------------------------------------------------------------------
# 3. CollectionTokenCleanupBackfillTask
# ---------------------------------------------------------------------------

class TestCollectionTokenCleanupBackfillTask:

    def test_needs_run_true_when_version_behind(self, file_db, cfg):
        from metatv.core.migrations.collection_token_cleanup_backfill import (
            CURRENT_VERSION, CollectionTokenCleanupBackfillTask,
        )

        task = CollectionTokenCleanupBackfillTask(file_db)
        assert cfg.collection_token_cleanup_backfill_version == 0
        assert task.needs_run(cfg) is True
        cfg.collection_token_cleanup_backfill_version = CURRENT_VERSION
        assert task.needs_run(cfg) is False

    def test_run_rewrites_pre_existing_rows(self, file_db, cfg):
        from metatv.core.migrations.collection_token_cleanup_backfill import (
            CollectionTokenCleanupBackfillTask,
        )

        _add_provider(file_db)
        noisy_id = _add_channel(
            file_db, name="Some Channel", category="MULTISUB SERIES 4K",
            media_type="series",
        )
        bracket_id = _add_channel(
            file_db, name="Kids Show", category="|MULTI| APPLE+ KIDS",
        )

        assert _get(file_db, noisy_id).detected_collection is None, (
            "pre-condition: not yet backfilled"
        )

        task = CollectionTokenCleanupBackfillTask(file_db)
        progress: list[tuple[int, int]] = []
        task.run(lambda d, t: progress.append((d, t)), lambda: False)

        assert _get(file_db, noisy_id).detected_collection is None
        assert _get(file_db, bracket_id).detected_collection == "APPLE+ KIDS"

    def test_run_leaves_already_clean_rows_untouched(self, file_db, cfg):
        from metatv.core.migrations.collection_token_cleanup_backfill import (
            CollectionTokenCleanupBackfillTask,
        )

        _add_provider(file_db)
        clean_id = _add_channel(file_db, name="Some Channel", category="NETFLIX")

        task = CollectionTokenCleanupBackfillTask(file_db)
        task.run(lambda d, t: None, lambda: False)

        assert _get(file_db, clean_id).detected_collection == "NETFLIX"

    def test_on_completed_bumps_version(self, file_db, cfg):
        from metatv.core.migrations.collection_token_cleanup_backfill import (
            CURRENT_VERSION, CollectionTokenCleanupBackfillTask,
        )

        task = CollectionTokenCleanupBackfillTask(file_db)
        task.on_completed(cfg)
        assert cfg.collection_token_cleanup_backfill_version == CURRENT_VERSION

    def test_crashed_run_does_not_bump_version(self, file_db, cfg, monkeypatch):
        """A run() that raises must leave collection_token_cleanup_backfill_version
        unbumped so the task retries next launch — the real MigrationManager
        wiring guarantees this (#364)."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.collection_token_cleanup_backfill import (
            CollectionTokenCleanupBackfillTask,
        )

        task = CollectionTokenCleanupBackfillTask(file_db)

        def _boom(progress_cb, is_cancelled, config=None):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(task, "run", _boom)

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        mgr._cancel_event = threading.Event()
        finished: list[str] = []
        mgr._task_finished = MagicMock(emit=lambda tid: finished.append(tid))
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.collection_token_cleanup_backfill_version == 0, (
            "a crashed run() must NOT bump the version — it must retry next launch"
        )
        assert finished == ["collection_token_cleanup_backfill"]

    def test_successful_run_bumps_version_after_crash_retry(self, file_db, cfg):
        """A real successful run (simulating a retry after a prior crash)
        completes normally and bumps the version."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.collection_token_cleanup_backfill import (
            CURRENT_VERSION, CollectionTokenCleanupBackfillTask,
        )

        _add_provider(file_db)
        _add_channel(file_db, name="Some Channel", category="MULTISUB SERIES 4K")

        task = CollectionTokenCleanupBackfillTask(file_db)
        assert cfg.collection_token_cleanup_backfill_version == 0

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        mgr._cancel_event = threading.Event()
        mgr._task_finished = MagicMock(emit=lambda tid: None)
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.collection_token_cleanup_backfill_version == CURRENT_VERSION
