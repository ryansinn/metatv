"""Behavior tests for EPG unmatched-guide re-link fix (bug #13).

The bug: EPG rows are stored with channel_db_id=NULL when the XMLTV fetch runs
before the channel list is fully loaded.  On subsequent launches the guide is
still time-"fresh" so needs_refresh() returns False and the NULL links are never
rebuilt.  Opening the EPG view shows empty On Now / Watchlist until the user
manually clicks Refresh.

The fix adds:
  - EpgRepository.has_unmatched_epg(provider_id) — detects the unmatched state
  - EpgManager._unmatched_refresh_attempted: set[str] — per-session guard
  - refresh_all_if_needed() — triggers a one-time re-fetch when the predicate fires

All tests use a file-backed Database (NOT :memory: — pooled connections each get
an empty schema there).  Tests that exercise refresh_all_if_needed monkeypatch
_start_refresh to prevent real network calls.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc
from metatv.core.repositories.epg import EpgRepository


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """File-backed Database with tables created (avoids :memory: pool isolation)."""
    path = tmp_path / "test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _add_provider(session, pid: str, *, epg_url: str = "http://e/xmltv.php",
                  epg_last_fetched=None, epg_data_end=None) -> ProviderDB:
    """Seed an active, EPG-enabled ProviderDB row that is time-fresh (won't need_refresh)."""
    if epg_last_fetched is None:
        # Fetched 1 hour ago; interval default 3d → time-fresh
        epg_last_fetched = now_utc() - timedelta(hours=1)
    if epg_data_end is None:
        # Guide valid for another 6 days
        epg_data_end = now_utc() + timedelta(days=6)
    p = ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p",
        is_active=True,
        epg_url=epg_url,
        epg_enabled=True,
        epg_last_fetched=epg_last_fetched,
        epg_data_end=epg_data_end,
        epg_refresh_interval="default",
    )
    session.add(p)
    session.flush()
    return p


def _add_programme(session, provider_id: str, *, channel_db_id: str | None) -> EpgProgramDB:
    """Seed one EpgProgramDB row, matched or unmatched as directed."""
    now = now_utc()
    row = EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=f"epgch.{uuid.uuid4().hex[:6]}",
        channel_db_id=channel_db_id,
        title="Test Show",
        start_time=now - timedelta(minutes=30),
        stop_time=now + timedelta(minutes=30),
    )
    session.add(row)
    session.flush()
    return row


def _make_manager(db: Database, *, epg_default: str = "3d") -> EpgManager:
    """Create an EpgManager with a mock config; auto_refresh=True."""
    cfg = MagicMock()
    cfg.epg_auto_refresh = True
    cfg.epg_default_refresh_interval = epg_default
    return EpgManager(db, cfg, notifications=None)


# ---------------------------------------------------------------------------
# A. Predicate — has_unmatched_epg
# ---------------------------------------------------------------------------

def test_has_unmatched_epg_true_when_all_rows_null(db):
    """Provider P with rows all having channel_db_id=NULL → True."""
    with db.session_scope() as session:
        _add_provider(session, "P")
        _add_programme(session, "P", channel_db_id=None)
        _add_programme(session, "P", channel_db_id=None)

    with db.session_scope(commit=False) as session:
        repo = EpgRepository(session)
        assert repo.has_unmatched_epg("P") is True, (
            "All NULL channel_db_id rows → unmatched guide must return True"
        )


def test_has_unmatched_epg_false_when_at_least_one_matched(db):
    """Provider Q with ≥1 matched row → False (guide is (partially) linked)."""
    with db.session_scope() as session:
        _add_provider(session, "Q")
        _add_programme(session, "Q", channel_db_id=None)       # unmatched
        _add_programme(session, "Q", channel_db_id="cdb-Q1")  # matched

    with db.session_scope(commit=False) as session:
        repo = EpgRepository(session)
        assert repo.has_unmatched_epg("Q") is False, (
            "At least one matched row → not fully unmatched → must return False"
        )


def test_has_unmatched_epg_false_when_all_rows_matched(db):
    """Provider with all rows matched → False."""
    with db.session_scope() as session:
        _add_provider(session, "Qfull")
        _add_programme(session, "Qfull", channel_db_id="cdb-A")
        _add_programme(session, "Qfull", channel_db_id="cdb-B")

    with db.session_scope(commit=False) as session:
        repo = EpgRepository(session)
        assert repo.has_unmatched_epg("Qfull") is False


def test_has_unmatched_epg_false_when_no_rows(db):
    """Provider R with NO programme rows → False (never-fetched ≠ unmatched)."""
    with db.session_scope() as session:
        _add_provider(session, "R")
        # no programmes seeded

    with db.session_scope(commit=False) as session:
        repo = EpgRepository(session)
        assert repo.has_unmatched_epg("R") is False, (
            "No rows at all → False (the never-fetched branch handles this separately)"
        )


def test_has_unmatched_epg_ignores_other_providers(db):
    """The predicate is scoped to the given provider_id and ignores others."""
    with db.session_scope() as session:
        _add_provider(session, "target")
        _add_provider(session, "other")
        _add_programme(session, "target", channel_db_id=None)   # target: unmatched
        _add_programme(session, "other",  channel_db_id="cdb")  # other: matched

    with db.session_scope(commit=False) as session:
        repo = EpgRepository(session)
        assert repo.has_unmatched_epg("target") is True
        assert repo.has_unmatched_epg("other") is False


# ---------------------------------------------------------------------------
# B. Trigger — refresh_all_if_needed fires for the unmatched provider
# ---------------------------------------------------------------------------

def test_refresh_all_triggers_for_unmatched_provider(db):
    """refresh_all_if_needed calls _start_refresh for a time-fresh but unmatched provider."""
    with db.session_scope() as session:
        _add_provider(session, "unmatched-p")          # time-fresh
        _add_programme(session, "unmatched-p", channel_db_id=None)  # all NULL

    manager = _make_manager(db)
    manager._start_refresh = MagicMock()

    manager.refresh_all_if_needed()

    called_ids = [c.args[0] for c in manager._start_refresh.call_args_list]
    assert "unmatched-p" in called_ids, (
        "refresh_all_if_needed must invoke _start_refresh for an unmatched-guide provider"
    )
    manager._executor.shutdown(wait=False)


def test_refresh_all_does_not_trigger_for_matched_provider(db):
    """refresh_all_if_needed must NOT trigger for a time-fresh, fully matched provider."""
    with db.session_scope() as session:
        _add_provider(session, "matched-p")
        _add_programme(session, "matched-p", channel_db_id="cdb-1")  # matched

    manager = _make_manager(db)
    manager._start_refresh = MagicMock()

    manager.refresh_all_if_needed()

    called_ids = [c.args[0] for c in manager._start_refresh.call_args_list]
    assert "matched-p" not in called_ids, (
        "A matched, time-fresh provider must NOT be re-fetched"
    )
    manager._executor.shutdown(wait=False)


def test_refresh_all_does_not_trigger_for_no_rows_provider(db):
    """A time-fresh provider with NO programme rows is a never-fetched case, not unmatched.

    needs_refresh() returns True for never-fetched (epg_last_fetched=None) so
    the provider would be triggered by the normal staleness branch.  But a fresh
    provider that somehow has no rows AND is time-stamped fresh is a degenerate
    case; has_unmatched_epg returns False → the unmatched branch does not fire.
    This test forces epg_last_fetched to something truthy so needs_refresh=False,
    ensuring the unmatched branch is the only possible trigger — and verifies it
    does NOT fire.
    """
    with db.session_scope() as session:
        _add_provider(session, "norows-p")
        # No programme rows seeded

    manager = _make_manager(db)
    manager._start_refresh = MagicMock()

    manager.refresh_all_if_needed()

    called_ids = [c.args[0] for c in manager._start_refresh.call_args_list]
    assert "norows-p" not in called_ids, (
        "No rows → has_unmatched_epg=False → unmatched branch must NOT trigger"
    )
    manager._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# C. Per-session guard — unmatched provider re-fetched at most once
# ---------------------------------------------------------------------------

def test_unmatched_guard_prevents_second_trigger(db):
    """A second call to refresh_all_if_needed must NOT re-trigger the unmatched provider.

    The guide remains unmatched between calls (we don't run the real fetch).
    The guard _unmatched_refresh_attempted prevents a second re-fetch per session,
    which matters for unmatchable feeds (e.g. provider with zero live channels).
    """
    with db.session_scope() as session:
        _add_provider(session, "guard-p")
        _add_programme(session, "guard-p", channel_db_id=None)

    manager = _make_manager(db)
    manager._start_refresh = MagicMock()

    # First call — should trigger
    manager.refresh_all_if_needed()
    first_count = manager._start_refresh.call_count
    assert first_count == 1, (
        f"First call must trigger exactly once; got {first_count}"
    )

    # Second call — guard must prevent re-trigger
    manager.refresh_all_if_needed()
    second_count = manager._start_refresh.call_count
    assert second_count == 1, (
        f"Second call must not add another trigger; total calls={second_count}"
    )
    manager._executor.shutdown(wait=False)


def test_unmatched_guard_init_is_empty_set(db):
    """_unmatched_refresh_attempted is initialized as an empty set in __init__."""
    manager = _make_manager(db)
    assert isinstance(manager._unmatched_refresh_attempted, set)
    assert len(manager._unmatched_refresh_attempted) == 0
    manager._executor.shutdown(wait=False)


def test_unmatched_guard_does_not_suppress_needs_refresh_on_second_call(db):
    """The guard only prevents the unmatched branch; time-stale providers can still re-trigger.

    Seed one provider whose guide expires between the two calls to refresh_all_if_needed
    so that needs_refresh() transitions from False to True.  Verify the second call
    does trigger a refresh via the normal staleness branch (not the unmatched branch).
    """
    now = now_utc()
    with db.session_scope() as session:
        # Guide just expired (epg_data_end is in the past) but fetched recently
        # needs_refresh = True because guide_expired=True (expiry floor rule)
        # but we make needs_refresh False for first call by having guide still valid
        # then manually expire epg_data_end between calls.
        p = ProviderDB(
            id="stale-between", name="stale-between", type="xtream",
            url="http://e.com", username="u", password="p",
            is_active=True, epg_url="http://e/xmltv.php", epg_enabled=True,
            epg_last_fetched=now - timedelta(hours=1),
            epg_data_end=now + timedelta(hours=2),   # still valid initially
            epg_refresh_interval="default",
        )
        session.add(p)
        _add_programme(session, "stale-between", channel_db_id="cdb-matched")  # matched → no unmatched branch

    manager = _make_manager(db, epg_default="3d")
    manager._start_refresh = MagicMock()

    # First call — needs_refresh=False, unmatched=False → nothing triggered
    manager.refresh_all_if_needed()
    assert manager._start_refresh.call_count == 0

    # Expire the guide between calls so needs_refresh returns True
    with db.session_scope() as session:
        p = session.query(ProviderDB).filter_by(id="stale-between").first()
        p.epg_data_end = now - timedelta(hours=1)  # now expired

    # Second call — staleness branch fires
    manager.refresh_all_if_needed()
    called_ids = [c.args[0] for c in manager._start_refresh.call_args_list]
    assert "stale-between" in called_ids, (
        "Staleness branch must still trigger even after the unmatched guard is set"
    )
    manager._executor.shutdown(wait=False)
