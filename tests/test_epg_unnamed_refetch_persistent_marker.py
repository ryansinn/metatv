"""Regression: the unnamed-guide re-fetch must persist its "attempted" marker across
launches, not just within one session.

Background (sibling of #285): a time-fresh provider whose guide rows are unmatched AND
unnamed triggers a ONE-TIME re-fetch to populate ``channel_name`` so the cheap DB-only
relink can then work.  #285 guarded that with the in-memory ``_unmatched_refresh_attempted``
set — which RESETS every launch.  A feed that genuinely serves nameless programme rows
(a ``channel_epg_id`` with no ``<channel>`` display-name in the XMLTV → stored with an
empty ``channel_name`` that no re-fetch can fill, e.g. TREX) keeps
``has_unmatched_unnamed_epg`` permanently True, so the branch fired the FULL-guide
re-fetch on EVERY launch, ignoring ``epg_refresh_interval``.

Fix: a persistent ``ProviderDB.epg_unnamed_refetch_attempted`` marker (set + committed
when the branch fires) stops the cross-launch loop.  The marker is cleared when the source
is content-refreshed so a genuinely-improved feed re-attempts exactly once.  The normal
``needs_refresh`` interval still governs periodic refreshes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.database import Database, ProviderDB, EpgProgramDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc
from metatv.core.provider_loader import ProviderLoadThread


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _make_manager(db):
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = "auto"
    return EpgManager(db, config, notifications=None)


def _add_provider(session, pid, *, last_fetched_offset=timedelta(0),
                  marker=False):
    """A time-FRESH provider (needs_refresh False under auto) unless the caller ages
    ``last_fetched_offset`` far enough back to elapse the auto delta.

    Guide depth is 2 days (start = -1d, end = +1d) → auto delta = 1 day.

    ``urls`` is populated so ``effective_epg_url`` (derives from credentials +
    urls, never the cached ``epg_url`` column) resolves non-empty.
    """
    now = now_utc()
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com", username="u", password="p",
        urls=[{"url": "http://e.com", "priority": 0}],
        is_active=True, epg_url="http://e/xmltv.php", epg_enabled=True,
        epg_last_fetched=now - last_fetched_offset,
        epg_data_start=now - timedelta(days=1),
        epg_data_end=now + timedelta(days=1),
        epg_refresh_interval="auto",
        epg_unnamed_refetch_attempted=marker,
    ))


def _add_epg_row(session, pid, *, channel_name, channel_db_id=None):
    """An EPG row; ``channel_name=""`` + ``channel_db_id=None`` is the unnamed/unmatched
    legacy case that keeps ``has_unmatched_unnamed_epg`` True."""
    now = datetime.utcnow()
    session.add(EpgProgramDB(
        provider_id=pid, channel_epg_id="x.tv", channel_db_id=channel_db_id,
        channel_name=channel_name, title="Show",
        start_time=now, stop_time=now + timedelta(hours=1),
    ))


def _read_marker(db, pid) -> bool:
    with db.session_scope(commit=False) as s:
        prov = s.query(ProviderDB).filter_by(id=pid).first()
        return bool(prov.epg_unnamed_refetch_attempted)


# ---------------------------------------------------------------------------
# The core loop-fix: a persisted marker blocks the every-launch re-fetch.
# ---------------------------------------------------------------------------

def test_persistent_marker_blocks_refetch_across_launch(db):
    """Marker SET + nameless-forever rows + interval NOT elapsed → a FRESH manager
    (empty in-memory guard, i.e. a new app launch) must NOT re-fetch. This is the loop
    the in-memory-only guard failed to stop."""
    with db.session_scope() as s:
        _add_provider(s, "trex", marker=True)          # prior launch already attempted
        _add_epg_row(s, "trex", channel_name="")       # unnamed + unmatched, forever

    manager = _make_manager(db)                          # fresh in-memory set == new launch
    with patch.object(manager, "_start_refresh") as mock_refresh:
        manager.refresh_all_if_needed()
        mock_refresh.assert_not_called()
    manager._executor.shutdown(wait=False)


def test_first_attempt_refetches_once_and_persists_marker(db):
    """Marker UNSET + nameless rows → re-fetch fires exactly once AND the persistent
    marker is committed to the DB (so the next launch is blocked)."""
    with db.session_scope() as s:
        _add_provider(s, "trex", marker=False)
        _add_epg_row(s, "trex", channel_name="")

    assert _read_marker(db, "trex") is False, "precondition: marker starts unset"

    manager = _make_manager(db)
    with patch.object(manager, "_start_refresh") as mock_refresh:
        manager.refresh_all_if_needed()
        assert mock_refresh.call_count == 1, "unnamed guide should re-fetch once"
    manager._executor.shutdown(wait=False)

    assert _read_marker(db, "trex") is True, "marker must persist after the attempt"


def test_marker_persists_stops_next_launch_end_to_end(db):
    """End-to-end: attempt once (marker committed), then a brand-new manager does NOT
    re-fetch — the interval throttle, not the branch, now governs."""
    with db.session_scope() as s:
        _add_provider(s, "trex", marker=False)
        _add_epg_row(s, "trex", channel_name="")

    m1 = _make_manager(db)
    with patch.object(m1, "_start_refresh") as r1:
        m1.refresh_all_if_needed()
        assert r1.call_count == 1
    m1._executor.shutdown(wait=False)

    m2 = _make_manager(db)  # simulates the next app launch
    with patch.object(m2, "_start_refresh") as r2:
        m2.refresh_all_if_needed()
        r2.assert_not_called()
    m2._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Content refresh resets the marker → one re-attempt.
# ---------------------------------------------------------------------------

def test_content_refresh_resets_marker(db):
    """The provider-load reset path clears the persistent marker."""
    with db.session_scope() as s:
        _add_provider(s, "trex", marker=True)

    loader = ProviderLoadThread.__new__(ProviderLoadThread)  # skip QThread init
    loader.provider = SimpleNamespace(id="trex")
    with db.session_scope() as s:
        loader._reset_epg_unnamed_refetch_marker(s)

    assert _read_marker(db, "trex") is False, "content refresh must clear the marker"


def test_content_refresh_reenables_exactly_one_reattempt(db):
    """After a content refresh clears the marker, a fresh launch re-attempts the names
    re-fetch exactly once (then re-sets the marker)."""
    with db.session_scope() as s:
        _add_provider(s, "trex", marker=True)          # already attempted before
        _add_epg_row(s, "trex", channel_name="")       # still nameless

    # Content refresh clears the marker.
    loader = ProviderLoadThread.__new__(ProviderLoadThread)
    loader.provider = SimpleNamespace(id="trex")
    with db.session_scope() as s:
        loader._reset_epg_unnamed_refetch_marker(s)

    manager = _make_manager(db)
    with patch.object(manager, "_start_refresh") as mock_refresh:
        manager.refresh_all_if_needed()
        assert mock_refresh.call_count == 1, "reset marker → one re-attempt"
    manager._executor.shutdown(wait=False)
    assert _read_marker(db, "trex") is True, "re-attempt re-sets the persistent marker"


# ---------------------------------------------------------------------------
# The intended #285 convergence still holds: a feed whose names DO populate stops
# on its own (the DB condition clears) — independent of the marker.
# ---------------------------------------------------------------------------

def test_populated_names_converge_and_stop(db):
    """A converging feed whose re-fetch DID populate names stops even after the marker
    is reset: ``has_unmatched_unnamed_epg`` is False, so the branch never fires."""
    with db.session_scope() as s:
        _add_provider(s, "good", marker=True)
        # Re-fetch populated the name (and matched it) — the converging case.
        _add_epg_row(s, "good", channel_name="Good Channel 1", channel_db_id=None)

    # Even a content refresh (marker reset) must NOT re-fetch, because the rows are named.
    loader = ProviderLoadThread.__new__(ProviderLoadThread)
    loader.provider = SimpleNamespace(id="good")
    with db.session_scope() as s:
        loader._reset_epg_unnamed_refetch_marker(s)

    manager = _make_manager(db)
    with patch.object(manager, "_start_refresh") as mock_refresh:
        manager.refresh_all_if_needed()
        mock_refresh.assert_not_called()
    manager._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# The normal interval throttle is unchanged by the marker.
# ---------------------------------------------------------------------------

def test_interval_elapsed_still_refreshes_despite_marker(db):
    """The persistent marker only gates the unnamed-legacy branch; when the normal
    interval has elapsed, ``needs_refresh`` fires the refresh regardless of the marker."""
    with db.session_scope() as s:
        # auto delta = half of 2-day depth = 1 day; last fetch 2 days ago → elapsed.
        _add_provider(s, "trex", last_fetched_offset=timedelta(days=2), marker=True)
        _add_epg_row(s, "trex", channel_name="")

    manager = _make_manager(db)
    with patch.object(manager, "_start_refresh") as mock_refresh:
        manager.refresh_all_if_needed()
        assert mock_refresh.call_count == 1, "interval elapsed → normal refresh still fires"
    manager._executor.shutdown(wait=False)


def test_interval_not_elapsed_and_no_unnamed_rows_no_refresh(db):
    """Interval not elapsed + no nameless rows + marker unset → nothing refreshes
    (baseline: the marker change didn't perturb the quiet path)."""
    with db.session_scope() as s:
        _add_provider(s, "trex", marker=False)
        _add_epg_row(s, "trex", channel_name="Named", channel_db_id="c1")  # matched

    manager = _make_manager(db)
    with patch.object(manager, "_start_refresh") as mock_refresh:
        manager.refresh_all_if_needed()
        mock_refresh.assert_not_called()
    manager._executor.shutdown(wait=False)
