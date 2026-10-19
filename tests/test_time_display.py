"""Times and dates: one formatter, the user's style, the system's by default.

Storage holds datetimes, never text; ``core/time_display`` turns them into text
in the chosen style, and ``gui/time_display_settings`` resolves "System" from
the OS regional format (pinned to the defaults by ``conftest`` so the suite
reads the same on every machine).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from metatv.core import time_display as td
from metatv.gui import time_display_settings as tds

_AT = datetime(2026, 8, 4, 21, 5)   # a Tuesday, PM, day < 12


@pytest.mark.parametrize("clock, date, expected", [
    ("12h", "day_month", ("9:05 PM", "9 PM", "4 Aug 2026", "4 Aug", "Tue 4 Aug")),
    ("24h", "month_day", ("21:05", "21:00", "Aug 4, 2026", "Aug 4", "Tue Aug 4")),
    ("24h", "iso", ("21:05", "21:00", "2026-08-04", "08-04", "Tue 08-04")),
])
def test_every_formatter_follows_the_chosen_style(clock, date, expected):
    td.set_styles(clock, date)
    assert (td.clock_text(_AT), td.hour_text(_AT), td.date_text(_AT),
            td.short_date_text(_AT), td.weekday_date_text(_AT)) == expected


def test_set_styles_reports_a_change_and_falls_back_on_an_unknown_style():
    assert td.set_styles("12h", "day_month") is False, "already the default"
    assert td.set_styles("24h", "day_month") is True
    assert td.set_styles("from-a-newer-version", "nope") is True
    assert td.clock_text(_AT) == "9:05 PM" and td.date_text(_AT) == "4 Aug 2026"


@pytest.mark.parametrize("pattern, style", [
    ("h:mm AP", "12h"), ("h:mm ap", "12h"), ("HH:mm", "24h"), ("H.mm", "24h")])
def test_the_system_clock_style_is_read_from_the_am_pm_marker(pattern, style):
    assert tds.clock_style_for(pattern) == style


@pytest.mark.parametrize("pattern, style", [
    ("M/d/yy", "month_day"), ("dd/MM/yyyy", "day_month"), ("dd.MM.yy", "day_month"),
    ("yyyy-MM-dd", "iso"), ("yyyy/MM/dd", "iso")])
def test_the_system_date_style_is_read_from_the_field_order(pattern, style):
    assert tds.date_style_for(pattern) == style


def test_an_override_wins_and_system_resolves(monkeypatch):
    monkeypatch.setattr(tds, "system_clock_style", lambda: "24h")
    monkeypatch.setattr(tds, "system_date_style", lambda: "iso")
    assert tds.resolved_styles(SimpleNamespace(time_format="system", date_format="system")) \
        == ("24h", "iso")
    assert tds.resolved_styles(SimpleNamespace(time_format="12h", date_format="month_day")) \
        == ("12h", "month_day")
    assert tds.apply_time_display(SimpleNamespace(time_format="system", date_format="system"))
    assert td.date_text(_AT) == "2026-08-04", "the resolved style reached the formatter"


def test_the_settings_rows_round_trip(qapp):
    from PyQt6.QtWidgets import QFormLayout, QWidget

    host = QWidget()  # held: a layout on a temporary widget is deleted with it
    form = QFormLayout(host)
    time_combo, date_combo = tds.add_time_format_rows(form)
    assert time_combo.itemText(0) == "System (9:05 PM)", "System shows what it resolves to"
    assert date_combo.itemText(1) == "Day Month Year (14 Aug 2026)"
    config = SimpleNamespace(time_format="24h", date_format="iso")
    tds.load_time_format(time_combo, date_combo, config)
    assert (time_combo.currentData(), date_combo.currentData()) == ("24h", "iso")
    date_combo.setCurrentIndex(date_combo.findData("system"))
    tds.save_time_format(time_combo, date_combo, config)
    assert (config.time_format, config.date_format) == ("24h", "system")
