"""Stored ISO dates follow the user's Date Format setting (owner, 2026-10-19).

The Released row, the What's New header and the QA checklist printed the stored
text ("2024-05-23"), so they ignored Settings -> Appearance -> Date.
"""

from datetime import datetime, timezone

from metatv.core import time_display
from metatv.core.time_display import date_text, iso_date_text


def test_a_date_uses_the_chosen_style(monkeypatch):
    time_display.set_styles("12h", "iso")
    try:
        assert iso_date_text("2024-05-23") == "2024-05-23"
        time_display.set_styles("12h", "day_month")
        assert iso_date_text("2024-05-23") == date_text(datetime(2024, 5, 23))
        assert iso_date_text("2024-05-23") != "2024-05-23"
    finally:
        time_display.set_styles(time_display.DEFAULT_CLOCK, time_display.DEFAULT_DATE)


def test_a_zoned_timestamp_is_shown_on_the_local_day():
    stamp = datetime(2026, 10, 19, 7, 58, tzinfo=timezone.utc)
    assert iso_date_text(stamp.isoformat()) == date_text(stamp.astimezone())


def test_non_iso_and_empty_values():
    assert iso_date_text("June 2025") == "June 2025"
    assert iso_date_text(None) == ""
    assert iso_date_text("  ") == ""
