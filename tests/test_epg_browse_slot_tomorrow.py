"""Regression tests for EPG Browse slot + tomorrow date-window correctness.

Root cause (original bug — now fixed)
--------------------------------------
``EpgRepository.get_schedule`` originally built the day boundary as::

    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)

This treated the *local* calendar date as UTC midnight. For users west of UTC
(e.g. CST = UTC-6) the "today" window opened six hours late — cutting off
evening programmes that aired after 6 PM local time (which fall on the *next*
UTC date) — and the "tomorrow" window didn't cover the correct local date at
all. "All Day" for tomorrow and "Prime Time" / "Late Night" for today both
returned empty even though data existed.

The fix replaced that block with ``local_day_window(target_date, tz=_local_tz())``,
which converts the local midnight to a UTC-naive value and uses that as the
anchor for both the day boundary and the slot hour offsets.

These tests pin the corrected behaviour. They seed programmes at known UTC
times that correspond to specific local CST (UTC-6) slots, then assert each
slot and the "tomorrow" date window return the expected rows. They would FAIL
against the original hand-rolled-UTC-midnight code.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB
from metatv.core.repositories.epg import EpgRepository


# ---------------------------------------------------------------------------
# UTC-6 fixture (CST — no DST ambiguity)
# ---------------------------------------------------------------------------

_CST = timezone(timedelta(hours=-6))


def _cst():
    return _CST


# ---------------------------------------------------------------------------
# File-backed DB seeded with programmes at known local CST times.
#
# Local date: 2026-06-24 (CST)
# UTC anchor: 2026-06-24T06:00Z = 2026-06-24T00:00 CST
#
# Slot layout (CST local -> UTC-naive stored):
#   Morning    06:00 CST = 2026-06-24T12:00Z
#   Afternoon  14:00 CST = 2026-06-24T20:00Z
#   Prime Time 19:00 CST = 2026-06-25T01:00Z   <- crosses UTC date boundary
#   Late Night 23:30 CST = 2026-06-25T05:30Z   <- crosses UTC date boundary
#   Tomorrow   08:00 CST on June 25 = 2026-06-25T14:00Z
# ---------------------------------------------------------------------------

_LOCAL_DATE    = date(2026, 6, 24)
_TOMORROW_DATE = date(2026, 6, 25)

_PROGS = [
    # (title, UTC start, UTC stop)
    ("Morning Show",     datetime(2026, 6, 24, 12, 0),  datetime(2026, 6, 24, 13, 0)),  # 06:00 CST
    ("Afternoon Show",   datetime(2026, 6, 24, 20, 0),  datetime(2026, 6, 24, 21, 0)),  # 14:00 CST
    ("Prime Time Show",  datetime(2026, 6, 25,  1, 0),  datetime(2026, 6, 25,  2, 0)),  # 19:00 CST
    ("Late Night Show",  datetime(2026, 6, 25,  5, 30), datetime(2026, 6, 25,  6, 0)),  # 23:30 CST
    ("Tomorrow Morning", datetime(2026, 6, 25, 14, 0),  datetime(2026, 6, 25, 15, 0)),  # 08:00 CST June 25
]

_PROVIDER_ID = "p1"
_CHANNEL_ID  = "ch1"


@pytest.fixture()
def slot_db(tmp_path):
    """File-backed DB seeded with programmes covering each time slot and tomorrow."""
    db = Database(f"sqlite:///{tmp_path / 'slot_test.db'}")
    db.create_tables()
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=_CHANNEL_ID, source_id="s1", provider_id=_PROVIDER_ID, name="Test Channel"
        ))
        for title, start, stop in _PROGS:
            session.add(EpgProgramDB(
                provider_id=_PROVIDER_ID,
                channel_epg_id="ch1.epg",
                channel_db_id=_CHANNEL_ID,
                channel_name="Test Channel",
                title=title,
                description="",
                start_time=start,
                stop_time=stop,
                is_live=False,
                is_new=False,
            ))
    return db


def _get_schedule(db: Database, target_date: date, time_slot: str) -> list[str]:
    """Run get_schedule with a frozen CST timezone and return programme titles."""
    session = db.get_session()
    try:
        repo = EpgRepository(session)
        with patch("metatv.core.repositories.epg._local_tz", _cst):
            progs = repo.get_schedule(
                target_date=target_date,
                provider_ids=[_PROVIDER_ID],
                time_slot=time_slot,
            )
        return [p.title for p in progs]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tests for today's slots
# ---------------------------------------------------------------------------

def test_all_day_today_returns_all_four_slots(slot_db):
    """All Day for today returns every programme on the local calendar day."""
    titles = _get_schedule(slot_db, _LOCAL_DATE, "all")
    assert "Morning Show"    in titles, f"Morning missing from All Day; got {titles}"
    assert "Afternoon Show"  in titles, f"Afternoon missing from All Day; got {titles}"
    assert "Prime Time Show" in titles, f"Prime Time missing from All Day; got {titles}"
    assert "Late Night Show" in titles, f"Late Night missing from All Day; got {titles}"
    # Tomorrow's programme must NOT bleed into today.
    assert "Tomorrow Morning" not in titles, f"Tomorrow bled into today; got {titles}"


def test_morning_slot_today(slot_db):
    titles = _get_schedule(slot_db, _LOCAL_DATE, "morning")
    assert titles == ["Morning Show"], f"Expected only Morning Show; got {titles}"


def test_afternoon_slot_today(slot_db):
    titles = _get_schedule(slot_db, _LOCAL_DATE, "afternoon")
    assert titles == ["Afternoon Show"], f"Expected only Afternoon Show; got {titles}"


def test_primetime_slot_today(slot_db):
    """Prime time (6 PM to 11 PM local) must include evening shows that cross the UTC date.

    This is the PRIMARY regression guard. The original bug built the day window as
    ``datetime(target_date.year, ..., 0, 0, 0)`` (local date as UTC midnight), so
    prime-time shows falling on the *next* UTC date were silently excluded.
    """
    titles = _get_schedule(slot_db, _LOCAL_DATE, "primetime")
    assert "Prime Time Show" in titles, (
        f"Prime Time Show missing from primetime slot. "
        f"Bug: day/slot window treats local date as UTC midnight. Got: {titles}"
    )


def test_latenight_slot_today(slot_db):
    """Late night (11 PM to 3 AM local) must include shows that cross the UTC date."""
    titles = _get_schedule(slot_db, _LOCAL_DATE, "latenight")
    assert "Late Night Show" in titles, (
        f"Late Night Show missing from latenight slot. "
        f"Bug: day/slot window treats local date as UTC midnight. Got: {titles}"
    )


# ---------------------------------------------------------------------------
# Tests for tomorrow's date window
# ---------------------------------------------------------------------------

def test_tomorrow_all_day_returns_tomorrows_shows(slot_db):
    """'Tomorrow' must return only tomorrow's programmes, not bleed into today.

    The original bug: local June 25 was treated as UTC midnight June 25, so
    the window was [June 25 00:00Z, June 26 00:00Z). For CST (UTC-6), the
    correct window is [June 25 06:00Z, June 26 06:00Z). The original window
    excluded 00:00-06:00 CST on June 25 (early morning local) and included
    programming from 18:00-00:00 CST on June 24 (today evening local).
    """
    titles = _get_schedule(slot_db, _TOMORROW_DATE, "all")
    assert "Tomorrow Morning" in titles, (
        f"Tomorrow Morning missing for tomorrow date. "
        f"Bug: tomorrow date window doesn't cover the correct local day. Got: {titles}"
    )
    # Today's prime-time / late-night must NOT bleed into tomorrow.
    assert "Prime Time Show"  not in titles, f"Today's prime time bled into tomorrow; got {titles}"
    assert "Late Night Show"  not in titles, f"Today's late night bled into tomorrow; got {titles}"


def test_tomorrow_morning_slot(slot_db):
    """Morning slot for tomorrow returns only tomorrow's morning programme."""
    titles = _get_schedule(slot_db, _TOMORROW_DATE, "morning")
    assert "Tomorrow Morning" in titles, (
        f"Tomorrow Morning missing in tomorrow morning slot; got {titles}"
    )
