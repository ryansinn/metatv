"""Local-time conversions use each date's own DST offset, not today's.

``_local_tz()`` used to return today's fixed offset, so the day DST ended
(2026-11-01) CI went red on a September recording window converting an hour
off, and every stored time from before the change displayed an hour off too.
A summer AND a winter date are checked in one run, so whichever season "today"
is, one of them has a different offset from now — the old code fails here on
any date of the year.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime

import pytest

from metatv.core.epg_utils import local_day_window, to_local, to_utc_naive


@pytest.fixture()
def denver():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/Denver"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


@pytest.mark.parametrize("local, utc", [
    (datetime(2026, 9, 4, 14, 0), datetime(2026, 9, 4, 20, 0)),    # MDT, UTC-6
    (datetime(2026, 1, 15, 14, 0), datetime(2026, 1, 15, 21, 0)),  # MST, UTC-7
])
def test_local_to_utc_uses_that_dates_offset(denver, local, utc):
    assert to_utc_naive(local) == utc


@pytest.mark.parametrize("utc, local", [
    (datetime(2026, 9, 4, 20, 0), datetime(2026, 9, 4, 14, 0)),
    (datetime(2026, 1, 15, 21, 0), datetime(2026, 1, 15, 14, 0)),
])
def test_utc_to_local_uses_that_dates_offset(denver, utc, local):
    assert to_local(utc).replace(tzinfo=None) == local


def test_the_day_dst_ends_is_25_hours(denver):
    start, end = local_day_window(date(2026, 11, 1))
    assert start == datetime(2026, 11, 1, 6, 0)       # midnight MDT
    assert end == datetime(2026, 11, 2, 7, 0)         # midnight MST
    assert (end - start).total_seconds() == 25 * 3600
