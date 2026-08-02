"""Behavioral tests for restricted-content isolation (owner-reported gap).

Owner report: the restricted-content hide/only filter (``filter_adult_mode``)
keyed only off the provider's ``is_adult`` API flag. A channel whose NAME/prefix
marks it restricted (XXX / ADULT / X-prefix naming convention — the "Adult"
content-descriptor group) was NOT caught when the provider failed to flag it, so
it leaked into general surfaces (Discover shelves, recommendations, browse).

Coverage:
1. ``is_restricted_prefix`` (channel_name_utils.py) — PREFIX-ONLY match; titles are never
   word-boundary scan, and the false-positive guards (must not match "Essex",
   "Maxx Sports").
2. Ingestion (``update_detected_prefixes``) writes ``ChannelDB.detected_restricted``.
3. ``RestrictedBackfillTask`` populates pre-existing rows and is idempotent/
   version-gated; a crashed ``run()`` does NOT bump the version (#364 semantics).
4. The shared adult-mode gate (``ChannelRepository.get_all`` /
   ``discovery_engine.get_by_genre``) now excludes/includes a name-flagged-but-
   provider-unflagged channel under ``adult_mode="hide"``/``"only"``.
"""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def file_db(tmp_path):
    """File-backed SQLite Database (not :memory: — see CLAUDE.md tests rule)."""
    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path / 'restricted_backfill.db'}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def cfg(tmp_path):
    """Isolated Config instance — never touches the real ~/.config/metatv."""
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


def _add_provider(db, provider_id: str = "p1", force_adult: bool = False) -> None:
    from metatv.core.database import ProviderDB

    session = db.get_session()
    try:
        session.add(ProviderDB(
            id=provider_id, name=provider_id, type="xtream",
            url="http://x.example.com", is_active=True, force_adult=force_adult,
        ))
        session.commit()
    finally:
        session.close()


def _add_channel(db, *, name: str, provider_id: str = "p1",
                  media_type: str = "live", is_adult: bool = False,
                  raw_genre: str | None = None) -> str:
    """Insert a bare (pre-ingestion) ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    channel_id = str(uuid.uuid4())
    session = db.get_session()
    try:
        raw_data = {"rating": "7.0"}
        if raw_genre is not None:
            raw_data["genre"] = raw_genre
        session.add(ChannelDB(
            id=channel_id, source_id=channel_id, provider_id=provider_id,
            name=name, media_type=media_type, is_adult=is_adult, raw_data=raw_data,
        ))
        session.commit()
    finally:
        session.close()
    return channel_id


def _run_ingestion(db) -> None:
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        RepositoryFactory(session).channels.update_detected_prefixes(provider_id=None)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 1. is_restricted — detection is the USER's configuration, never our guess
# ---------------------------------------------------------------------------


class _Cfg:
    """Minimal config double exposing the two knobs detection reads."""

    def __init__(self, adult_codes=("X", "XXX", "ADULT"), keywords=()):
        self._adult = list(adult_codes)
        self.restricted_keywords = list(keywords)

    @property
    def filter_language_groups(self):
        return {"Adult": self._adult, "English": ["EN"]}


class TestIsRestricted:
    """The app ships NO opinion about which names/codes mean restricted."""

    def test_prefix_in_the_users_adult_group_is_restricted(self):
        from metatv.core.channel_name_utils import is_restricted
        assert is_restricted("ADULT", "Anything", _Cfg()) is True
        assert is_restricted("xxx", "Anything", _Cfg()) is True

    def test_unmapped_code_is_not_guessed(self):
        """A real library used the code PORNBOX — unguessable, so we don't try.

        It becomes restricted only once the USER puts it in their Adult group.
        """
        from metatv.core.channel_name_utils import is_restricted
        assert is_restricted("PORNBOX", "Whatever", _Cfg()) is False
        widened = _Cfg(adult_codes=("X", "XXX", "ADULT", "PORNBOX"))
        assert is_restricted("PORNBOX", "Whatever", widened) is True

    def test_titles_are_never_scanned_without_user_keywords(self):
        """Real titles in this library that a keyword scan would have hidden."""
        from metatv.core.channel_name_utils import is_restricted
        cfg = _Cfg()  # no restricted_keywords configured — the default
        assert is_restricted("SE", "Appropriate Adult", cfg) is False
        assert is_restricted("EN", "xXx: Return of Xander Cage", cfg) is False
        assert is_restricted("EN", "Sex Education", cfg) is False

    def test_user_supplied_keywords_are_honoured(self):
        from metatv.core.channel_name_utils import is_restricted
        cfg = _Cfg(keywords=["late night xxx"])
        assert is_restricted("EN", "Late Night XXX Hour", cfg) is True
        assert is_restricted("EN", "Sex Education", cfg) is False

    def test_no_config_falls_back_to_base_groups_and_no_keywords(self):
        from metatv.core.channel_name_utils import is_restricted
        assert is_restricted("ADULT", "Anything") is True
        assert is_restricted("EN", "Appropriate Adult") is False


# ---------------------------------------------------------------------------
# 2. Ingestion writes detected_restricted
# ---------------------------------------------------------------------------

class TestIngestionWritesRestricted:

    def test_xxx_prefix_name_sets_detected_restricted(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="XXX - Late Night")
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_restricted is True
        finally:
            session.close()

    def test_ordinary_name_leaves_detected_restricted_false(self, file_db):
        _add_provider(file_db)
        cid = _add_channel(file_db, name="BBC One HD")
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_restricted is False
        finally:
            session.close()

    def test_provider_is_adult_flag_not_overwritten(self, file_db):
        """detected_restricted has separate provenance from is_adult — ingestion
        must not touch is_adult, and a name-unflagged/provider-flagged channel
        keeps is_adult=True with detected_restricted=False."""
        _add_provider(file_db)
        cid = _add_channel(file_db, name="Provider Flagged Channel", is_adult=True)
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.is_adult is True
            assert ch.detected_restricted is False
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 3. RestrictedBackfillTask
# ---------------------------------------------------------------------------

class TestRestrictedBackfillTask:

    def test_needs_run_true_when_version_behind(self, file_db, cfg):
        from metatv.core.migrations.restricted_backfill import (
            CURRENT_VERSION, RestrictedBackfillTask,
        )

        task = RestrictedBackfillTask(file_db)
        assert cfg.restricted_backfill_version == 0
        assert task.needs_run(cfg) is True
        cfg.restricted_backfill_version = CURRENT_VERSION
        assert task.needs_run(cfg) is False

    def test_run_populates_pre_existing_rows(self, file_db, cfg):
        """Rows inserted BEFORE the fix (no detected_restricted) get backfilled."""
        from metatv.core.database import ChannelDB
        from metatv.core.migrations.restricted_backfill import RestrictedBackfillTask

        _add_provider(file_db)
        cid = _add_channel(file_db, name="ADULT - Peep Show")

        session = file_db.get_session()
        try:
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_restricted in (None, False), "pre-condition: not yet backfilled"
        finally:
            session.close()

        task = RestrictedBackfillTask(file_db)
        progress: list[tuple[int, int]] = []
        task.run(lambda d, t: progress.append((d, t)), lambda: False)

        session = file_db.get_session()
        try:
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_restricted is True
        finally:
            session.close()

    def test_on_completed_bumps_version(self, file_db, cfg):
        from metatv.core.migrations.restricted_backfill import (
            CURRENT_VERSION, RestrictedBackfillTask,
        )

        task = RestrictedBackfillTask(file_db)
        task.on_completed(cfg)
        assert cfg.restricted_backfill_version == CURRENT_VERSION


class TestRestrictedBackfillCrashRetry:

    def test_crashed_run_does_not_bump_version(self, file_db, cfg, monkeypatch):
        """A run() that raises must leave restricted_backfill_version unbumped so
        the task retries on the next launch — the real MigrationManager wiring
        is what guarantees this (#364): it skips on_completed for any task
        whose run() raised."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.restricted_backfill import RestrictedBackfillTask

        task = RestrictedBackfillTask(file_db)

        def _boom(progress_cb, is_cancelled, config=None):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(task, "run", _boom)

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        import threading
        mgr._cancel_event = threading.Event()
        finished: list[str] = []
        from unittest.mock import MagicMock
        mgr._task_finished = MagicMock(emit=lambda tid: finished.append(tid))
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.restricted_backfill_version == 0, (
            "a crashed run() must NOT bump the version — it must retry next launch"
        )
        assert finished == ["restricted_backfill"], "widget must still get the finish signal"

    def test_successful_run_bumps_version_after_crash_retry(self, file_db, cfg):
        """After a (simulated) prior crash, a real successful run completes
        normally and bumps the version — proving the task isn't permanently
        broken by the crash path."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.restricted_backfill import (
            CURRENT_VERSION, RestrictedBackfillTask,
        )

        _add_provider(file_db)
        _add_channel(file_db, name="XXX - Uncensored")

        task = RestrictedBackfillTask(file_db)
        assert cfg.restricted_backfill_version == 0

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        import threading
        mgr._cancel_event = threading.Event()
        from unittest.mock import MagicMock
        mgr._task_finished = MagicMock(emit=lambda tid: None)
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.restricted_backfill_version == CURRENT_VERSION


# ---------------------------------------------------------------------------
# 4. The shared adult-mode gate reads detected_restricted
# ---------------------------------------------------------------------------

class TestAdultModeGateReadsDetectedRestricted:
    """A channel that is name-flagged (XXX/ADULT naming) but the PROVIDER never
    set is_adult=True must now be caught by 'hide'/'only' on every surface that
    routes through the shared filter — the channel-list query
    (ChannelRepository.get_all) and Discover's genre query
    (discovery_engine.get_by_genre)."""

    @pytest.fixture()
    def seeded(self, file_db):
        _add_provider(file_db)
        # Name-flagged, provider-UNflagged — the owner-reported gap case.
        _add_channel(
            file_db, name="XXX - Uncensored Movie", media_type="movie",
            is_adult=False, raw_genre="Drama",
        )
        # An ordinary, unrelated channel that must always stay visible.
        _add_channel(
            file_db, name="Regular Drama Movie", media_type="movie",
            is_adult=False, raw_genre="Drama",
        )
        _run_ingestion(file_db)
        return file_db

    def test_hide_excludes_name_flagged_channel_from_list_query(self, seeded):
        from metatv.core.repositories import RepositoryFactory

        with seeded.session_scope() as session:
            repos = RepositoryFactory(session)
            names = {
                ch.name for ch in repos.channels.get_all(adult_mode="hide")
            }
        assert "XXX - Uncensored Movie" not in names
        assert "Regular Drama Movie" in names

    def test_only_includes_name_flagged_channel_in_list_query(self, seeded):
        from metatv.core.repositories import RepositoryFactory

        with seeded.session_scope() as session:
            repos = RepositoryFactory(session)
            names = {
                ch.name for ch in repos.channels.get_all(adult_mode="only")
            }
        assert "XXX - Uncensored Movie" in names
        assert "Regular Drama Movie" not in names

    def test_hide_excludes_name_flagged_channel_from_discover_genre_query(self, seeded):
        from metatv.core.discovery_engine import get_by_genre

        session = seeded.get_session()
        try:
            titles = {c.title for c in get_by_genre(session, "Drama", limit=50,
                                                      adult_mode="hide")}
        finally:
            session.close()
        assert "Uncensored Movie" not in titles
        assert "Regular Drama Movie" in titles

    def test_only_includes_name_flagged_channel_in_discover_genre_query(self, seeded):
        from metatv.core.discovery_engine import get_by_genre

        session = seeded.get_session()
        try:
            titles = {c.title for c in get_by_genre(session, "Drama", limit=50,
                                                      adult_mode="only")}
        finally:
            session.close()
        assert "Uncensored Movie" in titles
        assert "Regular Drama Movie" not in titles

    def test_all_mode_shows_everything(self, seeded):
        from metatv.core.repositories import RepositoryFactory

        with seeded.session_scope() as session:
            repos = RepositoryFactory(session)
            names = {
                ch.name for ch in repos.channels.get_all(adult_mode="all")
            }
        assert "XXX - Uncensored Movie" in names
        assert "Regular Drama Movie" in names


