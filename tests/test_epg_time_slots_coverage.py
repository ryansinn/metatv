"""Behavioral tests for EPG Browse time-slot windows + honest contiguous coverage.

Covers two tester-logged failures (entry 0098, addresses e52_s1 + e54_s0):

e52_s1 — Date-change reload + slot ranges
-----------------------------------------
The old ``get_schedule`` applied BOTH the full-day cap (``start_time < day_end``)
AND the slot window, so Late Night (23–27) was clipped to 11 PM–midnight: the
post-midnight programmes never showed and the list looked empty regardless of the
selected date (so date changes appeared not to reload). The slots are redefined:

    Morning   5 AM – 12 PM   (closes the old 3–6 AM gap)
    Afternoon 12 PM – 6 PM
    Prime     6 PM – 11 PM
    Late Night 11 PM – 5 AM  (spans past midnight into the next calendar day)

These tests pin: Late Night includes an early-AM programme of the NEXT day; the
3–6 AM band is now covered; and the Browse reload trigger forwards the selected
date into the fetch (so changing the date reloads that day's window).

e54_s0 — Honest coverage
------------------------
The empty-state used ``min(ProviderDB.epg_data_end)`` — the max stop anywhere —
which a single deep channel inflates, so it claimed the guide "reaches tomorrow"
while tonight's late-night block was missing. ``contiguous_guide_end`` walks the
real spans and stops at the first hole; filler (>12 h) can't bridge it.
"""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB
from metatv.core.epg_utils import (
    EPG_FILLER_THRESHOLD,
    contiguous_guide_end,
    to_local,
)
from metatv.core.repositories.epg import (
    SCHEDULE_SLOT_RANGES,
    SCHEDULE_TIME_SLOTS,
    EpgRepository,
)
from metatv.gui.epg_browse_mixin import _EpgBrowseMixin


_TZ_UTC = zoneinfo.ZoneInfo("UTC")


def _with_utc_tz():
    """Patch the repo's _local_tz to UTC so slot windows are deterministic in CI."""
    return patch("metatv.core.repositories.epg._local_tz", side_effect=lambda: _TZ_UTC)


# ---------------------------------------------------------------------------
# A. Slot range definitions — single source of truth
# ---------------------------------------------------------------------------

def test_slot_ranges_match_requested_spec():
    """Late Night 11 PM–5 AM, Morning 5 AM–12 PM, others contiguous."""
    assert SCHEDULE_SLOT_RANGES["latenight"] == (23, 29)  # 5 AM next day
    assert SCHEDULE_SLOT_RANGES["morning"] == (5, 12)
    assert SCHEDULE_SLOT_RANGES["afternoon"] == (12, 18)
    assert SCHEDULE_SLOT_RANGES["primetime"] == (18, 23)


def test_slots_are_contiguous_no_gap():
    """5 → 12 → 18 → 23 → 29(=5 next day): every hour of the day lands in a slot."""
    ordered = [
        SCHEDULE_SLOT_RANGES["morning"],
        SCHEDULE_SLOT_RANGES["afternoon"],
        SCHEDULE_SLOT_RANGES["primetime"],
        SCHEDULE_SLOT_RANGES["latenight"],
    ]
    for (_a_start, a_end), (b_start, _b_end) in zip(ordered, ordered[1:]):
        assert a_end == b_start, "adjacent slots must touch with no gap"
    # Late Night wraps to 5 AM (29 % 24), the same hour Morning starts → full cover.
    assert SCHEDULE_SLOT_RANGES["latenight"][1] % 24 == SCHEDULE_SLOT_RANGES["morning"][0]


def test_time_slot_labels_drive_dropdown():
    """The dropdown labels come from the shared definition (no drift)."""
    labels = {key: label for key, label, _s, _e in SCHEDULE_TIME_SLOTS}
    assert labels["latenight"] == "Late Night 11–5"
    assert labels["morning"] == "Morning 5–12"
    assert labels["all"] == "All Day"


# ---------------------------------------------------------------------------
# B. get_schedule slot windows against a seeded DB (the real bug surface)
# ---------------------------------------------------------------------------

@pytest.fixture()
def slot_db(tmp_path):
    """File-backed DB seeded with programmes around the midnight boundary."""
    db = Database(f"sqlite:///{tmp_path / 'slots.db'}")
    db.create_tables()
    with db.session_scope() as session:
        session.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN"))

        def _prog(title, start, stop):
            session.add(EpgProgramDB(
                provider_id="p1", channel_epg_id="espn", channel_db_id="c1",
                channel_name="ESPN", title=title, description="",
                start_time=start, stop_time=stop,
            ))

        # Today (UTC) = 2026-06-28. Seed across the day boundary.
        _prog("Dawn Patrol",      datetime(2026, 6, 28, 5, 30), datetime(2026, 6, 28, 6, 30))   # morning 5:30
        _prog("Evening News",     datetime(2026, 6, 28, 19, 0), datetime(2026, 6, 28, 20, 0))   # primetime
        _prog("Late Show",        datetime(2026, 6, 28, 23, 30), datetime(2026, 6, 29, 0, 30))  # latenight (pre-midnight)
        _prog("After Midnight",   datetime(2026, 6, 29, 2, 0), datetime(2026, 6, 29, 3, 0))     # latenight (post-midnight!)
        _prog("Almost Dawn",      datetime(2026, 6, 29, 4, 30), datetime(2026, 6, 29, 5, 0))    # latenight (was the 3-6 gap)
    return db


def _titles(db, target_date, time_slot):
    with _with_utc_tz():
        session = db.get_session()
        try:
            progs = EpgRepository(session).get_schedule(
                target_date=target_date, provider_ids=["p1"], time_slot=time_slot,
            )
            return [p.title for p in progs]
        finally:
            session.close()


def test_latenight_includes_post_midnight_programme(slot_db):
    """REGRESSION (e52_s1): Late Night must include next-day early-AM programmes.

    The old (23, 27) range + the day-end cap clipped this to 11 PM–midnight, so
    'After Midnight' (02:00 next day) and 'Almost Dawn' (04:30) were missing.
    """
    titles = _titles(slot_db, date(2026, 6, 28), "latenight")
    assert "Late Show" in titles          # pre-midnight portion still works
    assert "After Midnight" in titles     # post-midnight portion now included
    assert "Almost Dawn" in titles        # the old 3-6 AM gap is now covered
    assert "Evening News" not in titles   # prime time is not late night


def test_morning_starts_at_5am(slot_db):
    """REGRESSION (e52_s1): Morning now starts at 5 AM (was 6 AM)."""
    titles = _titles(slot_db, date(2026, 6, 28), "morning")
    assert "Dawn Patrol" in titles  # 05:30 — excluded by the old 6 AM start


def test_three_to_six_am_band_fully_covered(slot_db):
    """No programme between 3 and 6 AM falls outside every slot.

    'Almost Dawn' (04:30 on Jun 29) is Late Night of Jun 28; a 05:30 programme is
    Morning of Jun 29 — together they close the old 3–6 AM hole.
    """
    # 04:30 belongs to Jun-28 Late Night (not Jun-29 morning which starts 05:00).
    assert "Almost Dawn" in _titles(slot_db, date(2026, 6, 28), "latenight")
    # And it is NOT double-counted in Jun-29 morning.
    assert "Almost Dawn" not in _titles(slot_db, date(2026, 6, 29), "morning")


def test_all_day_unaffected_by_slot_change(slot_db):
    """'All Day' still windows by the full local day (no slot clipping)."""
    titles = _titles(slot_db, date(2026, 6, 28), "all")
    assert "Dawn Patrol" in titles
    assert "Evening News" in titles
    assert "Late Show" in titles
    # post-midnight programmes belong to Jun 29's All Day, not Jun 28's.
    assert "After Midnight" not in titles


# ---------------------------------------------------------------------------
# C. Anchor reload — the forward Browse trigger forwards the selected anchor.
#
# The bounded calendar-day + time-slot model retired in favour of a forward
# start anchor; this pins that a reload forwards the chosen anchor and starts a
# fresh keyset page (after=None) rather than re-deriving a day window.
# ---------------------------------------------------------------------------

def _make_anchor_trigger_host(*, anchor, provider_ids=("p1",)):
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._provider_ids = list(provider_ids)
    host._filtered_provider_ids = lambda: host._provider_ids
    host.search_input = SimpleNamespace(text=lambda: "")
    host.anchor_combo = SimpleNamespace(currentData=lambda: anchor)
    host.hide_filler_btn = SimpleNamespace(isChecked=lambda: False)
    host.submitted = []
    host._executor = SimpleNamespace(submit=lambda fn, *a: host.submitted.append((fn, a)))
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda payload: host.emitted.append(payload))
    return host


def test_reload_forwards_selected_anchor_to_fetch():
    """Changing the start anchor reloads forward from THAT anchor (page 1)."""
    for chosen in (
        datetime(2026, 6, 28, 18, 0),
        datetime(2026, 6, 29, 0, 0),
        datetime(2026, 7, 1, 18, 0),
    ):
        host = _make_anchor_trigger_host(anchor=chosen)
        _EpgBrowseMixin._reload_browse(host)
        assert len(host.submitted) == 1
        fn, args = host.submitted[0]
        assert fn == host._fetch_browse
        _provider_ids, anchor, _search, _hide, after, append, _gen = args
        assert anchor == chosen, "reload must use the freshly selected anchor"
        assert after is None and append is False, "fresh reload starts at page 1"


# ---------------------------------------------------------------------------
# D. Honest contiguous coverage — pure helper (epg_utils.contiguous_guide_end)
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 28, 20, 0)  # UTC-naive reference "now"


def test_contiguous_end_stops_at_hole():
    """Coverage ends at the last stop before a >1 h gap, not the far-future max."""
    spans = [
        (datetime(2026, 6, 28, 20, 0), datetime(2026, 6, 28, 21, 0)),  # airing
        (datetime(2026, 6, 28, 21, 0), datetime(2026, 6, 28, 22, 0)),
        (datetime(2026, 6, 28, 22, 0), datetime(2026, 6, 28, 23, 0)),
        # ---- HOLE: nothing 23:00 → 03:00 next day ----
        (datetime(2026, 6, 29, 3, 0), datetime(2026, 6, 29, 4, 0)),    # after the gap
    ]
    assert contiguous_guide_end(spans, _now=_NOW) == datetime(2026, 6, 28, 23, 0)


def test_contiguous_end_filler_does_not_bridge_hole():
    """A multi-day filler span must NOT extend coverage across a real hole."""
    filler_stop = _NOW + EPG_FILLER_THRESHOLD + timedelta(hours=1)  # > 12 h → filler
    spans = [
        (datetime(2026, 6, 28, 20, 0), datetime(2026, 6, 28, 23, 0)),
        (datetime(2026, 6, 28, 18, 0), filler_stop),                  # filler bridging the gap
        (datetime(2026, 6, 29, 3, 0), datetime(2026, 6, 29, 4, 0)),
    ]
    # Without filler exclusion this would report filler_stop (dishonest).
    assert contiguous_guide_end(spans, _now=_NOW) == datetime(2026, 6, 28, 23, 0)


def test_contiguous_end_none_when_no_future_data():
    """All spans already ended → no contiguous coverage."""
    spans = [
        (datetime(2026, 6, 28, 10, 0), datetime(2026, 6, 28, 11, 0)),
        (datetime(2026, 6, 28, 12, 0), datetime(2026, 6, 28, 13, 0)),
    ]
    assert contiguous_guide_end(spans, _now=_NOW) is None


def test_contiguous_end_full_run_when_no_hole():
    """Back-to-back programmes → coverage reaches the final stop."""
    spans = [
        (datetime(2026, 6, 28, 20, 0), datetime(2026, 6, 28, 21, 0)),
        (datetime(2026, 6, 28, 21, 0), datetime(2026, 6, 28, 22, 30)),
        (datetime(2026, 6, 28, 22, 30), datetime(2026, 6, 29, 0, 30)),
    ]
    assert contiguous_guide_end(spans, _now=_NOW) == datetime(2026, 6, 29, 0, 30)


# ---------------------------------------------------------------------------
# E. Honest contiguous coverage — repository method against a seeded DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def coverage_db(tmp_path):
    """DB where ONE channel runs deep but the guide has a hole tonight.

    epg_data_end (max stop anywhere) would be far in the future, but the honest
    contiguous reach stops at the hole.
    """
    db = Database(f"sqlite:///{tmp_path / 'coverage.db'}")
    db.create_tables()
    now = datetime(2026, 6, 28, 20, 0)
    with db.session_scope() as session:
        session.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN"))

        def _prog(title, start, stop):
            session.add(EpgProgramDB(
                provider_id="p1", channel_epg_id="espn", channel_db_id="c1",
                channel_name="ESPN", title=title, description="",
                start_time=start, stop_time=stop,
            ))

        # Contiguous from now until 23:00 tonight, then a hole, then far-future data.
        _prog("A", datetime(2026, 6, 28, 20, 0), datetime(2026, 6, 28, 21, 0))
        _prog("B", datetime(2026, 6, 28, 21, 0), datetime(2026, 6, 28, 23, 0))
        # ---- hole: nothing 23:00 tonight → 18:00 two days out ----
        _prog("Far", datetime(2026, 6, 30, 18, 0), datetime(2026, 6, 30, 20, 0))
    return db, now


def test_repo_contiguous_guide_end_reports_real_reach(coverage_db):
    """e54_s0: coverage reflects the contiguous reach (23:00 tonight), not the far max."""
    db, now = coverage_db
    session = db.get_session()
    try:
        repo = EpgRepository(session)
        contiguous = repo.get_contiguous_guide_end(["p1"], _now=now)
        # The naive max stop (old dishonest value) is two days out.
        max_stop = max(p.stop_time for p in
                       session.query(EpgProgramDB).filter_by(provider_id="p1").all())
    finally:
        session.close()

    assert contiguous == datetime(2026, 6, 28, 23, 0), "must stop at tonight's hole"
    assert max_stop == datetime(2026, 6, 30, 20, 0)
    assert contiguous != max_stop, "honest reach must differ from the inflated max"


# ---------------------------------------------------------------------------
# F. Empty-state placeholder reports the honest reach (not 'tomorrow').
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_placeholder_host(*, provider_ids, search_text=""):
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._provider_ids = list(provider_ids)
    host._filtered_provider_ids = lambda: host._provider_ids
    host.search_input = SimpleNamespace(text=lambda: search_text)
    return host


def test_placeholder_names_contiguous_reach(qapp):
    """e54_s0: the empty-state names the real last-contiguous time, honestly."""
    guide_end = datetime(2026, 6, 28, 23, 0)  # tonight 11 PM (UTC-naive)
    host = _make_placeholder_host(provider_ids=["p1"])
    text = _EpgBrowseMixin._browse_placeholder_text(host, guide_end=guide_end)
    assert "guide currently reaches" in text
    # The displayed time is the contiguous end, localized — proving it is honest.
    expected = to_local(guide_end).strftime("%a %b %-d at %-I:%M %p")
    assert expected in text


def test_placeholder_generic_when_no_contiguous_reach(qapp):
    """When contiguous coverage is None, fall back to the generic message."""
    host = _make_placeholder_host(provider_ids=["p1"])
    text = _EpgBrowseMixin._browse_placeholder_text(host, guide_end=None)
    assert text == "No upcoming programmes in the guide."
