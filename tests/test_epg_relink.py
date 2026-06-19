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


# ---------------------------------------------------------------------------
# D. _relink_provider — DB-only re-match (the key new behavior)
# ---------------------------------------------------------------------------

def _add_channel(session, provider_id: str, *, epg_channel_id: str | None = None,
                 name: str = "Test Channel") -> ChannelDB:
    """Seed a live ChannelDB row for matching."""
    ch = ChannelDB(
        id=f"ch-{uuid.uuid4().hex[:8]}",
        source_id=f"src-{uuid.uuid4().hex[:6]}",
        provider_id=provider_id,
        name=name,
        media_type="live",
        epg_channel_id=epg_channel_id,
    )
    session.add(ch)
    session.flush()
    return ch


def _add_programme_with_epg_id(
    session,
    provider_id: str,
    *,
    channel_epg_id: str,
    channel_db_id: str | None = None,
    channel_name: str = "",
) -> EpgProgramDB:
    """Seed an EpgProgramDB row with a known channel_epg_id (+ optional channel_name)."""
    now = now_utc()
    row = EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=channel_epg_id,
        channel_db_id=channel_db_id,
        channel_name=channel_name,
        title="Test Show",
        start_time=now - timedelta(minutes=30),
        stop_time=now + timedelta(minutes=30),
    )
    session.add(row)
    session.flush()
    return row


def test_relink_provider_links_via_epg_channel_id(db):
    """_relink_provider links rows whose channel has a matching epg_channel_id (tier 1).

    This exercises the core regression: EPG rows stored with channel_db_id=NULL
    because the channel list wasn't loaded at XMLTV fetch time.  After relink, the
    rows are matched and get_current_programs returns them.
    """
    pid = "prov-relink-tier1"
    epg_id = "cnn.us"

    with db.session_scope() as session:
        _add_provider(session, pid)
        ch = _add_channel(session, pid, epg_channel_id=epg_id, name="CNN US")
        prog = _add_programme_with_epg_id(
            session, pid,
            channel_epg_id=epg_id,
            channel_db_id=None,  # unmatched — the bug state
        )
        prog_id = prog.id
        ch_id = ch.id

    manager = _make_manager(db)
    with db.session_scope() as session:
        updated = manager._relink_provider(session, pid)

    assert updated == 1, f"Expected 1 row relinked, got {updated}"

    # Verify the row is now linked
    with db.session_scope(commit=False) as session:
        prog = session.query(EpgProgramDB).filter_by(id=prog_id).first()
        assert prog.channel_db_id == ch_id, (
            "channel_db_id must be set to the matched channel's id after relink"
        )

    manager._executor.shutdown(wait=False)


def test_relink_provider_partial_match_case(db):
    """The critical partial-match bug: has_unmatched_epg returns False but a NULL row exists.

    has_unmatched_epg only returns True when ALL rows are NULL (the 100% unmatched
    case).  The old code gated the re-fetch on has_unmatched_epg → it never triggered
    for providers where some channels matched but others didn't (the common case).

    This test proves that _relink_provider links the NULL row even though
    has_unmatched_epg returns False — the relink does NOT use that predicate.
    """
    pid = "prov-partial"
    epg_matched = "bbc.one"
    epg_unmatched = "cbs.east"

    with db.session_scope() as session:
        _add_provider(session, pid)
        # Two channels — only the first has a matching epg_channel_id
        ch_matched = _add_channel(session, pid, epg_channel_id=epg_matched, name="BBC One")
        ch_unmatched = _add_channel(session, pid, epg_channel_id=epg_unmatched, name="CBS East")
        # One already-linked row + one unmatched row
        _add_programme_with_epg_id(
            session, pid,
            channel_epg_id=epg_matched,
            channel_db_id=ch_matched.id,  # already linked
        )
        unmatched_prog = _add_programme_with_epg_id(
            session, pid,
            channel_epg_id=epg_unmatched,
            channel_db_id=None,  # the partially-unmatched row
        )
        unmatched_prog_id = unmatched_prog.id
        ch_unmatched_id = ch_unmatched.id

    # Verify has_unmatched_epg returns False (proving the old guard would NOT fire)
    with db.session_scope(commit=False) as session:
        repo = EpgRepository(session)
        assert repo.has_unmatched_epg(pid) is False, (
            "Partial match → has_unmatched_epg must return False "
            "(this is exactly why the old re-fetch gate missed this case)"
        )

    # Now relink — must fix the unmatched row despite has_unmatched_epg being False
    manager = _make_manager(db)
    with db.session_scope() as session:
        updated = manager._relink_provider(session, pid)

    assert updated == 1, (
        f"Expected 1 row relinked (the partial NULL); got {updated}"
    )

    # The previously-unmatched row is now linked
    with db.session_scope(commit=False) as session:
        prog = session.query(EpgProgramDB).filter_by(id=unmatched_prog_id).first()
        assert prog.channel_db_id == ch_unmatched_id, (
            "The partial-match NULL row must be linked after _relink_provider"
        )

    manager._executor.shutdown(wait=False)


def test_relink_provider_no_match_stays_null(db):
    """A row whose channel has no match in ChannelDB stays NULL after relink."""
    pid = "prov-nomatch"
    with db.session_scope() as session:
        _add_provider(session, pid)
        # Seed a programme with an EPG ID that has NO matching ChannelDB row
        prog = _add_programme_with_epg_id(
            session, pid,
            channel_epg_id="nomatching.epg.id",
            channel_db_id=None,
        )
        prog_id = prog.id
        # No ChannelDB row with this epg_channel_id or name

    manager = _make_manager(db)
    with db.session_scope() as session:
        updated = manager._relink_provider(session, pid)

    assert updated == 0, (
        f"No matching channel → 0 rows should be updated; got {updated}"
    )

    with db.session_scope(commit=False) as session:
        prog = session.query(EpgProgramDB).filter_by(id=prog_id).first()
        assert prog.channel_db_id is None, (
            "Unmatched row must remain NULL when no ChannelDB row matches"
        )

    manager._executor.shutdown(wait=False)


def test_relink_provider_idempotent(db):
    """Running relink twice changes 0 rows the second time."""
    pid = "prov-idempotent"
    epg_id = "hbo.max"

    with db.session_scope() as session:
        _add_provider(session, pid)
        ch = _add_channel(session, pid, epg_channel_id=epg_id, name="HBO Max")
        _add_programme_with_epg_id(
            session, pid,
            channel_epg_id=epg_id,
            channel_db_id=None,
        )

    manager = _make_manager(db)

    # First run links the row
    with db.session_scope() as session:
        first_updated = manager._relink_provider(session, pid)
    assert first_updated == 1, f"First run must link 1 row; got {first_updated}"

    # Second run finds nothing to change
    with db.session_scope() as session:
        second_updated = manager._relink_provider(session, pid)
    assert second_updated == 0, (
        f"Second run must update 0 rows (idempotent); got {second_updated}"
    )

    manager._executor.shutdown(wait=False)


def test_relink_provider_already_linked_rows_not_changed(db):
    """Rows already carrying the correct channel_db_id are not counted as updated."""
    pid = "prov-already-linked"
    epg_id = "already.linked"

    with db.session_scope() as session:
        _add_provider(session, pid)
        ch = _add_channel(session, pid, epg_channel_id=epg_id, name="Already Linked")
        prog = _add_programme_with_epg_id(
            session, pid,
            channel_epg_id=epg_id,
            channel_db_id=ch.id,  # already correctly linked
        )
        prog_id = prog.id
        expected_ch_id = ch.id

    manager = _make_manager(db)
    with db.session_scope() as session:
        updated = manager._relink_provider(session, pid)

    assert updated == 0, (
        f"Already-linked rows must not be counted as updated; got {updated}"
    )

    # channel_db_id is unchanged
    with db.session_scope(commit=False) as session:
        prog = session.query(EpgProgramDB).filter_by(id=prog_id).first()
        assert prog.channel_db_id == expected_ch_id

    manager._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# E. Fuzzy-name relink + legacy channel_name handling
# ---------------------------------------------------------------------------

def test_relink_provider_links_via_fuzzy_name(db):
    """_relink_provider links a row by FUZZY channel name (no epg_channel_id match).

    This is the real-world case: the channel has no epg_channel_id, matching relies
    on display-name normalization, and the EPG row carries the stored channel_name.
    Would FAIL if relink fed channel_epg_id (not channel_name) as the fuzzy name.
    """
    pid = "prov-relink-fuzzy"
    epg_id = "bbc1.uk"

    with db.session_scope() as session:
        _add_provider(session, pid)
        ch = _add_channel(session, pid, epg_channel_id=None, name="BBC One")
        prog = _add_programme_with_epg_id(
            session, pid,
            channel_epg_id=epg_id,
            channel_db_id=None,        # unmatched
            channel_name="BBC One",    # stored display-name → enables fuzzy relink
        )
        prog_id = prog.id
        ch_id = ch.id

    manager = _make_manager(db)
    with db.session_scope() as session:
        updated = manager._relink_provider(session, pid)

    assert updated == 1, f"Expected 1 fuzzy-linked row, got {updated}"
    with db.session_scope(commit=False) as session:
        prog = session.query(EpgProgramDB).filter_by(id=prog_id).first()
        assert prog.channel_db_id == ch_id, (
            "Fuzzy relink must link the row via stored channel_name"
        )
    manager._executor.shutdown(wait=False)


def test_relink_legacy_row_without_name_still_links_via_epg_id(db):
    """A legacy row (channel_name='') still links via tier-1 epg_channel_id fallback."""
    pid = "prov-relink-legacy"
    epg_id = "espn.us"

    with db.session_scope() as session:
        _add_provider(session, pid)
        ch = _add_channel(session, pid, epg_channel_id=epg_id, name="ESPN")
        prog = _add_programme_with_epg_id(
            session, pid,
            channel_epg_id=epg_id,
            channel_db_id=None,
            channel_name="",           # legacy: no stored name
        )
        prog_id = prog.id
        ch_id = ch.id

    manager = _make_manager(db)
    with db.session_scope() as session:
        updated = manager._relink_provider(session, pid)

    assert updated == 1
    with db.session_scope(commit=False) as session:
        prog = session.query(EpgProgramDB).filter_by(id=prog_id).first()
        assert prog.channel_db_id == ch_id
    manager._executor.shutdown(wait=False)


def test_has_unmatched_unnamed_epg_true_when_unmatched_and_empty(db):
    """has_unmatched_unnamed_epg detects legacy rows (NULL + empty name) needing a re-fetch."""
    pid = "prov-unnamed"
    with db.session_scope() as session:
        _add_provider(session, pid)
        _add_programme_with_epg_id(
            session, pid, channel_epg_id="x.1", channel_db_id=None, channel_name="",
        )
        repo = EpgRepository(session)
        assert repo.has_unmatched_unnamed_epg(pid) is True


def test_has_unmatched_unnamed_epg_false_when_named(db):
    """False when the unmatched row HAS a stored channel_name (relink can fuzzy it)."""
    pid = "prov-named"
    with db.session_scope() as session:
        _add_provider(session, pid)
        _add_programme_with_epg_id(
            session, pid, channel_epg_id="x.1", channel_db_id=None, channel_name="Some Channel",
        )
        repo = EpgRepository(session)
        assert repo.has_unmatched_unnamed_epg(pid) is False


def test_has_unmatched_unnamed_epg_false_when_matched(db):
    """False when rows are matched (channel_db_id set) even if name is empty — no re-fetch needed."""
    pid = "prov-matched-unnamed"
    with db.session_scope() as session:
        _add_provider(session, pid)
        _add_programme_with_epg_id(
            session, pid, channel_epg_id="x.1", channel_db_id="cdb-1", channel_name="",
        )
        repo = EpgRepository(session)
        assert repo.has_unmatched_unnamed_epg(pid) is False
