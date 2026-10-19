"""Settings → Appearance → Time / Date: the system's style unless the user picks one.

``core/time_display`` formats; this module decides WHICH style, because "the
system's" is only knowable through Qt. ``QLocale.system()`` reads the regional
format the user set in the OS (Windows Region settings, macOS Language &
Region, the Linux locale), and its short formats say whether the clock is
12- or 24-hour and which comes first, day or month. That answer is mapped onto
one of the core styles, so every surface still formats through one function.

Its own module, like ``settings_text_size``, so the settings tabs file (pinned
at its size) gains one call rather than a block.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QLocale
from PyQt6.QtWidgets import QComboBox, QFormLayout

from metatv.core import time_display

SYSTEM = "system"

#: (label, stored value). The label's example is filled in when the row is built.
TIME_CHOICES: tuple[tuple[str, str], ...] = (
    ("System", SYSTEM), ("12-hour", "12h"), ("24-hour", "24h"))
DATE_CHOICES: tuple[tuple[str, str], ...] = (
    ("System", SYSTEM), ("Day Month Year", "day_month"),
    ("Month Day, Year", "month_day"), ("Year-Month-Day", "iso"))

#: The instant every label example shows: a PM hour and a day above 12, so
#: 12/24-hour and day/month order are both visible.
_EXAMPLE = datetime(2026, 8, 14, 21, 5)


def clock_style_for(pattern: str) -> str:
    """``"12h"`` when a Qt time pattern has an AM/PM marker (``AP``/``ap``), else ``"24h"``."""
    return "12h" if "a" in pattern.lower() else "24h"


def date_style_for(pattern: str) -> str:
    """The core date style whose field order matches a Qt date pattern."""
    year, month, day = (pattern.lower().find(c) for c in "ymd")
    if 0 <= year < month:
        return "iso"
    return "day_month" if 0 <= day < month else "month_day"


def system_clock_style() -> str:
    """The clock style of the OS's regional format."""
    return clock_style_for(QLocale.system().timeFormat(QLocale.FormatType.ShortFormat))


def system_date_style() -> str:
    """The date style of the OS's regional format."""
    return date_style_for(QLocale.system().dateFormat(QLocale.FormatType.ShortFormat))


def resolved_styles(config) -> tuple[str, str]:
    """``(clock, date)`` for *config*, with ``"system"`` resolved."""
    clock = getattr(config, "time_format", SYSTEM) or SYSTEM
    date = getattr(config, "date_format", SYSTEM) or SYSTEM
    return (system_clock_style() if clock == SYSTEM else clock,
            system_date_style() if date == SYSTEM else date)


def apply_time_display(config) -> bool:
    """Hand the resolved styles to ``core/time_display``; True when they changed."""
    return time_display.set_styles(*resolved_styles(config))


def _example(kind: str, style: str) -> str:
    if kind == "time":
        return time_display.local_strftime(_EXAMPLE, time_display.CLOCK_FORMATS[style][0])
    return time_display.local_strftime(_EXAMPLE, time_display.DATE_FORMATS[style][0])


def add_time_format_rows(form: QFormLayout) -> tuple[QComboBox, QComboBox]:
    """Add the "Time:" and "Date:" rows to *form*; return their combos."""
    combos = []
    for kind, choices, system in (("time", TIME_CHOICES, system_clock_style()),
                                  ("date", DATE_CHOICES, system_date_style())):
        combo = QComboBox()
        for label, value in choices:
            combo.addItem(f"{label} ({_example(kind, system if value == SYSTEM else value)})",
                          value)
        combo.setToolTip(
            f"How {kind}s are written throughout MetaTV. System follows the\n"
            "regional format set in your operating system. Applies when you\n"
            "click OK or Apply.")
        form.addRow(f"{kind.capitalize()}:", combo)
        combos.append(combo)
    return combos[0], combos[1]


def load_time_format(time_combo: QComboBox, date_combo: QComboBox, config) -> None:
    """Select the stored styles (``"system"`` when unset or unknown)."""
    for combo, field in ((time_combo, "time_format"), (date_combo, "date_format")):
        idx = combo.findData(getattr(config, field, SYSTEM))
        combo.setCurrentIndex(idx if idx >= 0 else combo.findData(SYSTEM))


def save_time_format(time_combo: QComboBox, date_combo: QComboBox, config) -> None:
    """Write the selected styles back to ``config``."""
    config.time_format = time_combo.currentData() or SYSTEM
    config.date_format = date_combo.currentData() or SYSTEM
