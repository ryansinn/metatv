"""EPGF-1 / ledger F8: the refresh floor fires when programmes RUN OUT.

``needs_refresh``'s expiry floor keyed on ``ProviderDB.epg_data_end``, the max
``stop_time`` of non-filler programmes. A guide whose last entries merely run
LONG therefore reported coverage well past the point where anything new can
start. Measured on the owner's database 2026-08-26: the last programme *started*
10:38, ``epg_data_end`` read 22:00, and under ``auto`` no refresh was due for
six hours — six hours in which no watch alert could possibly fire, because there
was nothing left to fire about.

The floor now asks the honest question, ``EpgRepository.has_future_programmes``:
does anything START after now? It keeps the ``guide_stale_at_source`` throttle
untouched (the heuristic repaired twice for re-fetch loops, #285 and #320) and
adds its own: the floor only fires if the LAST FETCH actually produced a start
after itself. A feed lagging real time never does, so it is throttled instead of
re-fetched forever — while a provider with nothing stored at all is not
"lagging", it is empty, which is precisely what the floor exists to refill.

``epg_data_end`` is untouched and stays informational (it is what the freshness
line reads).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import EpgProgramDB, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc
from metatv.core.repositories.epg import EpgRepository

#: Depth/lag numbers that make the INTERVAL throttle say "not yet" on its own,
#: so every assertion below is about the floor and nothing else.
_DATA_START_AGO = timedelta(days=2)      # depth ~58h -> auto delta ~29h
_DATA_END_AHEAD = timedelta(hours=10)    # guide "runs long": epg_data_end is FUTURE
_FETCHED_AGO = timedelta(hours=25)       # 25h elapsed < 29h delta -> interval says no


def _manager(db, *, default_interval="auto") -> EpgManager:
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = default_interval
    config.epg_retention_hours = 24
    return EpgManager(db, config, notifications=None)


def _seed_provider(db, pid, *, fetched_ago=_FETCHED_AGO, interval="auto"):
    now = now_utc()
    with db.session_scope() as session:
        session.add(ProviderDB(
            id=pid, name=pid, type="xtream", url="http://e.com",
            username="u", password="pw", is_active=True,
            urls=[{"url": "http://e.com", "priority": 0}],
            epg_enabled=True,
            epg_last_fetched=now - fetched_ago,
            epg_data_start=now - _DATA_START_AGO,
            epg_data_end=now + _DATA_END_AHEAD,
            epg_refresh_interval=interval,
        ))


def _add_programme(db, pid, *, starts_in, runs_for=timedelta(hours=1), matched=True):
    now = now_utc()
    with db.session_scope() as session:
        session.add(EpgProgramDB(
            provider_id=pid,
            channel_epg_id=f"epgch.{uuid.uuid4().hex[:6]}",
            channel_db_id=f"cdb-{uuid.uuid4().hex[:6]}" if matched else None,
            channel_name="Chan One",
            title="Test Show",
            start_time=now + starts_in,
            stop_time=now + starts_in + runs_for,
        ))


def _needs_refresh(db, mgr, pid) -> bool:
    with db.session_scope(commit=False) as s:
        return mgr.needs_refresh(s.query(ProviderDB).filter_by(id=pid).first())


# ---------------------------------------------------------------------------
# The three cases the floor has to get right
# ---------------------------------------------------------------------------

def test_a_long_running_last_programme_no_longer_hides_an_exhausted_guide(db):
    """THE F8 CASE. Last programme STARTED an hour ago, stops in nine — nothing
    new can start, so a refresh is due.

    Fails on the pre-fix code: ``epg_data_end`` is ten hours in the future, so
    ``epg_is_stale`` is False, the floor never fires, and the auto interval has
    four hours left to run.
    """
    _seed_provider(db, "runs-long")
    _add_programme(db, "runs-long", starts_in=-timedelta(hours=1),
                   runs_for=timedelta(hours=11))
    mgr = _manager(db)
    try:
        assert _needs_refresh(db, mgr, "runs-long") is True, (
            "the last programme started an hour ago and nothing else can start "
            "— the guide is exhausted whatever epg_data_end says"
        )
    finally:
        mgr._executor.shutdown(wait=False)


def test_a_guide_with_a_future_start_is_not_due(db):
    """Non-degeneracy: the floor must not fire on a guide that still has content.

    Same row as above plus one programme that has yet to start — if this passed
    too, the test above would be proving nothing.
    """
    _seed_provider(db, "has-future")
    _add_programme(db, "has-future", starts_in=-timedelta(hours=1),
                   runs_for=timedelta(hours=11))
    _add_programme(db, "has-future", starts_in=timedelta(hours=2))
    mgr = _manager(db)
    try:
        assert _needs_refresh(db, mgr, "has-future") is False
    finally:
        mgr._executor.shutdown(wait=False)


def test_a_feed_lagging_real_time_is_throttled_not_re_fetched_forever(db):
    """The new trigger's own guard: the last fetch produced no future start, so
    fetching again would produce none either. Sibling of #285/#320."""
    _seed_provider(db, "lagging", fetched_ago=timedelta(minutes=1))
    # Everything this feed serves was already in the past when we fetched it.
    _add_programme(db, "lagging", starts_in=-timedelta(hours=3),
                   runs_for=timedelta(hours=13))
    mgr = _manager(db)
    try:
        assert _needs_refresh(db, mgr, "lagging") is False, (
            "a feed that lags real time would re-fetch on every scheduler tick "
            "forever — the floor must stand down and let the throttle govern"
        )
    finally:
        mgr._executor.shutdown(wait=False)


def test_the_lagging_guard_releases_once_the_throttle_window_elapses(db):
    """Throttled is not never: the interval still re-checks a lagging feed."""
    _seed_provider(db, "lagging-old", fetched_ago=timedelta(days=4))
    _add_programme(db, "lagging-old", starts_in=-timedelta(hours=3),
                   runs_for=timedelta(hours=13))
    mgr = _manager(db)
    try:
        assert _needs_refresh(db, mgr, "lagging-old") is True
    finally:
        mgr._executor.shutdown(wait=False)


def test_a_provider_with_nothing_stored_is_empty_not_lagging(db):
    """Regression guard for the new guard: "no rows" is not evidence of lag.

    A provider whose guide ran out AND stored nothing must still hit the floor —
    that is the "On Now is empty, refill it" case the floor exists for.
    """
    now = now_utc()
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="empty", name="empty", type="xtream", url="http://e.com",
            username="u", password="pw", is_active=True,
            urls=[{"url": "http://e.com", "priority": 0}],
            epg_enabled=True,
            epg_last_fetched=now - timedelta(hours=2),
            epg_data_start=now - timedelta(days=4),
            epg_data_end=now - timedelta(hours=1),   # ran out AFTER the fetch
            epg_refresh_interval="12h",
        ))
    mgr = _manager(db)
    try:
        assert _needs_refresh(db, mgr, "empty") is True
    finally:
        mgr._executor.shutdown(wait=False)


def test_the_stale_at_source_throttle_still_wins_over_the_new_floor(db):
    """#285/#320 must not be re-opened: the new trigger INHERITS that throttle."""
    now = now_utc()
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="biggy", name="biggy", type="xtream", url="http://e.com",
            username="u", password="pw", is_active=True,
            urls=[{"url": "http://e.com", "priority": 0}],
            epg_enabled=True,
            epg_last_fetched=now,                       # fetched this launch
            epg_data_start=now - timedelta(days=2),
            epg_data_end=now - timedelta(hours=4),      # expired at fetch time
            epg_refresh_interval="auto",
        ))
    _add_programme(db, "biggy", starts_in=-timedelta(hours=5))
    mgr = _manager(db)
    try:
        assert _needs_refresh(db, mgr, "biggy") is False
    finally:
        mgr._executor.shutdown(wait=False)


def test_the_floor_reaches_the_scheduler_not_just_the_predicate(db):
    """End to end: refresh_all_if_needed actually starts a refresh for the F8 row."""
    _seed_provider(db, "runs-long")
    _add_programme(db, "runs-long", starts_in=-timedelta(hours=1),
                   runs_for=timedelta(hours=11))
    mgr = _manager(db)
    started: list[str] = []
    mgr._start_refresh = lambda pid, name, force: started.append(pid)
    try:
        mgr.refresh_all_if_needed()
        assert started == ["runs-long"]
    finally:
        mgr._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# The repository helpers the floor is built on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("matched,expected", [(True, True), (False, False)])
def test_has_future_programmes_takes_an_after_instant(db, matched, expected):
    """The ``after`` parameter is the whole of what the new guard needed — one
    shared query, not a second one that can drift from it."""
    _add_programme(db, "P", starts_in=timedelta(hours=3), matched=matched)
    with db.session_scope(commit=False) as s:
        repo = EpgRepository(s)
        assert repo.has_future_programmes(["P"]) is expected
        # Two hours from now is BEFORE the programme, four hours is after it.
        assert repo.has_future_programmes(
            ["P"], after=now_utc() + timedelta(hours=2)) is expected
        assert repo.has_future_programmes(
            ["P"], after=now_utc() + timedelta(hours=4)) is False


def test_has_stored_programmes_separates_empty_from_all_in_the_past(db):
    """"Nothing stored" and "stored, but all past" must not answer the same."""
    _add_programme(db, "past", starts_in=-timedelta(hours=6))
    with db.session_scope(commit=False) as s:
        repo = EpgRepository(s)
        assert repo.has_stored_programmes("past") is True
        assert repo.has_future_programmes(["past"]) is False
        assert repo.has_stored_programmes("never-fetched") is False
