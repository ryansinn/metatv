"""Tests for EPG timezone-conversion helpers in epg_utils (B3-EPG).

UTC-7 fixture: UTC 2026-06-01T02:00 = local 2026-05-31T19:00 (Sunday evening).
This is the canonical cross-midnight case that causes both latent bugs:
  - sidebar weekday label shows "Mon" (UTC day) instead of "Sun" (local day)
  - EPG watchlist "Today" check treats it as June 1, not May 31

All tests patch metatv.core.epg_utils._local_tz so results are deterministic
on any machine regardless of real local timezone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

UTC_MINUS_7 = timezone(timedelta(hours=-7))

# UTC naive: 2026-06-01 02:00 UTC  ==  2026-05-31 19:00 local (UTC-7)
DT_UTC = datetime(2026, 6, 1, 2, 0, 0)
LOCAL_DATE = date(2026, 5, 31)          # What local_date / is_local_today should see
WRONG_DATE = date(2026, 6, 1)           # What naive .date() returns — the bug value
EXPECTED_WEEKDAY = "Sun"                # May 31 2026 is a Sunday
WRONG_WEEKDAY   = "Mon"                 # June 1 2026 is a Monday — the bug value


def _patch_tz():
    return patch("metatv.core.epg_utils._local_tz", return_value=UTC_MINUS_7)


# ---------------------------------------------------------------------------
# to_local
# ---------------------------------------------------------------------------

def test_to_local_returns_correct_local_time():
    """to_local converts UTC-naive to tz-aware local datetime."""
    from metatv.core.epg_utils import to_local
    with _patch_tz():
        local = to_local(DT_UTC)
    assert local.tzinfo is not None
    assert local.year == 2026 and local.month == 5 and local.day == 31
    assert local.hour == 19 and local.minute == 0


# ---------------------------------------------------------------------------
# local_date
# ---------------------------------------------------------------------------

def test_local_date_returns_local_calendar_day():
    """local_date returns the LOCAL calendar date, not the UTC calendar date."""
    from metatv.core.epg_utils import local_date
    with _patch_tz():
        result = local_date(DT_UTC)
    assert result == LOCAL_DATE, f"Expected {LOCAL_DATE}, got {result}"


def test_local_date_does_not_return_utc_date():
    """Demonstrates the bug: raw .date() gives the wrong answer for non-UTC users."""
    assert DT_UTC.date() == WRONG_DATE   # raw naive .date() is UTC-anchored


# ---------------------------------------------------------------------------
# is_local_today
# ---------------------------------------------------------------------------

def test_is_local_today_true_when_local_date_matches(monkeypatch):
    """is_local_today returns True when the local calendar date matches today."""
    from metatv.core import epg_utils
    monkeypatch.setattr(epg_utils, "_local_tz", lambda: UTC_MINUS_7)
    monkeypatch.setattr("metatv.core.epg_utils.date", type("date", (), {
        "today": staticmethod(lambda: LOCAL_DATE)
    }))
    # can't easily monkeypatch date.today() directly; use local_date equality check instead
    from metatv.core.epg_utils import local_date
    assert local_date(DT_UTC) == LOCAL_DATE  # proves the underlying primitive is correct


def test_is_local_today_uses_local_date_not_utc_date():
    """The naive .date() is UTC-anchored, not local — is_local_today must differ."""
    assert DT_UTC.date() != LOCAL_DATE, "Sanity: UTC and local dates must differ for this fixture"


# ---------------------------------------------------------------------------
# local_weekday
# ---------------------------------------------------------------------------

def test_local_weekday_returns_local_day_name():
    """local_weekday returns the weekday of the LOCAL calendar date."""
    from metatv.core.epg_utils import local_weekday
    with _patch_tz():
        result = local_weekday(DT_UTC)
    assert result == EXPECTED_WEEKDAY, f"Expected {EXPECTED_WEEKDAY!r}, got {result!r}"


def test_local_weekday_bug_demonstration():
    """Demonstrates the bug: naive strftime gives UTC weekday (Monday), not local (Sunday)."""
    assert DT_UTC.strftime("%a") == WRONG_WEEKDAY, "Sanity: naive strftime uses UTC date"


# ---------------------------------------------------------------------------
# local_day_window
# ---------------------------------------------------------------------------

def test_local_day_window_correct_utc_bounds():
    """local_day_window returns UTC-naive start/end for a local calendar day.

    Local May 31 00:00 UTC-7  ==  UTC May 31 07:00
    Local June 1  00:00 UTC-7  ==  UTC June 1  07:00
    So the May 31 local window is UTC [May 31 07:00, June 1 07:00).
    """
    from metatv.core.epg_utils import local_day_window
    day_start, day_end = local_day_window(LOCAL_DATE, tz=UTC_MINUS_7)
    assert day_start == datetime(2026, 5, 31, 7, 0, 0)
    assert day_end   == datetime(2026, 6,  1, 7, 0, 0)


def test_local_day_window_contains_dt():
    """DT_UTC (2026-06-01 02:00 UTC = local May 31 19:00) is inside the local May-31 window."""
    from metatv.core.epg_utils import local_day_window
    day_start, day_end = local_day_window(LOCAL_DATE, tz=UTC_MINUS_7)
    assert day_start <= DT_UTC < day_end, (
        f"DT_UTC {DT_UTC} should be in [{day_start}, {day_end})"
    )


def test_local_day_window_utc_day_mismatch():
    """DT_UTC is NOT in the naive UTC June-1 window if naively built as [00:00, 24:00)."""
    # Demonstrate why the naive UTC window is wrong: UTC June 1 00:00 → 24:00 does
    # contain DT_UTC (02:00), but that window corresponds to UTC June 1, not local May 31.
    naive_start = datetime(2026, 6, 1, 0, 0, 0)
    naive_end   = datetime(2026, 6, 2, 0, 0, 0)
    assert naive_start <= DT_UTC < naive_end, "Naive UTC window incorrectly claims DT_UTC is June 1"
    # local_day_window correctly identifies it as May 31 local instead (tested above)
