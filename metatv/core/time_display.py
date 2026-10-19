"""How times and dates read on screen: one place, in the user's chosen style.

Nothing is stored formatted. Programme times are UTC-naive datetimes and other
timestamps local-naive ones; turning one into text is the last step before the
screen, so the style is a preference, not data. Every surface that shows a
clock time or a date calls a function here, never ``strftime`` with its own
pattern, so a change of style reaches all of them at once.

The style defaults to the operating system's regional format. The UI layer
(``gui/time_display_settings.py``) reads that through ``QLocale`` and calls
:func:`set_styles` with a concrete style, at startup and after Settings → OK —
this module holds no Qt and no ``Config``, the same split as ``url_policy``.
Until then (tests, scripts) it uses :data:`DEFAULT_CLOCK` / :data:`DEFAULT_DATE`.

Log lines and file names are not display text and keep their sortable ISO
formats.
"""

from __future__ import annotations

import re
from datetime import datetime

_UNPADDED = re.compile(r"%-([a-zA-Z])")

#: style -> (clock, hour only)
CLOCK_FORMATS: dict[str, tuple[str, str]] = {
    "12h": ("%-I:%M %p", "%-I %p"),     # 9:05 PM · 6 PM
    "24h": ("%H:%M", "%H:00"),          # 21:05 · 18:00
}
#: style -> (full date, without year, with weekday and no year)
DATE_FORMATS: dict[str, tuple[str, str, str]] = {
    "day_month": ("%-d %b %Y", "%-d %b", "%a %-d %b"),        # 4 Aug 2026 · 4 Aug · Tue 4 Aug
    "month_day": ("%b %-d, %Y", "%b %-d", "%a %b %-d"),       # Aug 4, 2026 · Aug 4 · Tue Aug 4
    "iso": ("%Y-%m-%d", "%m-%d", "%a %m-%d"),                 # 2026-08-04 · 08-04 · Tue 08-04
}
DEFAULT_CLOCK = "12h"
DEFAULT_DATE = "day_month"

_style = {"clock": DEFAULT_CLOCK, "date": DEFAULT_DATE}


def set_styles(clock: str, date: str) -> bool:
    """Use *clock* (a :data:`CLOCK_FORMATS` key) and *date* (a :data:`DATE_FORMATS` key).

    An unknown key falls back to the default rather than raising: a stored
    preference from a future version must not stop the app drawing.

    Returns:
        True when either style changed, so the caller knows whether visible
        labels need re-rendering.
    """
    new = {"clock": clock if clock in CLOCK_FORMATS else DEFAULT_CLOCK,
           "date": date if date in DATE_FORMATS else DEFAULT_DATE}
    changed = new != _style
    _style.update(new)
    return changed


def local_strftime(dt: datetime, fmt: str) -> str:
    """``dt.strftime(fmt)``, where ``%-X`` means field X without its leading zero.

    ``%-I`` / ``%-d`` are a glibc/BSD extension: Windows' C library raises
    ``ValueError: Invalid format string`` on them. Every pattern here goes
    through this, so the zero is stripped once, the same way on every platform.
    Guard: ``tests/test_no_platform_strftime.py``.
    """
    def unpadded(match: "re.Match[str]") -> str:
        return dt.strftime("%" + match.group(1)).lstrip("0") or "0"
    return dt.strftime(_UNPADDED.sub(unpadded, fmt))


def clock_text(dt: datetime) -> str:
    """A clock time: ``9:05 PM`` / ``21:05``. *dt* is already local."""
    return local_strftime(dt, CLOCK_FORMATS[_style["clock"]][0])


def hour_text(dt: datetime) -> str:
    """An on-the-hour time: ``6 PM`` / ``18:00``. *dt* is already local."""
    return local_strftime(dt, CLOCK_FORMATS[_style["clock"]][1])


def date_text(dt: datetime) -> str:
    """A date with its year: ``4 Aug 2026`` / ``Aug 4, 2026`` / ``2026-08-04``."""
    return local_strftime(dt, DATE_FORMATS[_style["date"]][0])


def iso_date_text(value: "str | None") -> str:
    """A STORED ISO date or timestamp, in the user's date style.

    Providers and our own records keep dates as text (``"2025-06-05"``,
    ``"2026-10-19T07:58:01+00:00"``); shown raw, they ignore the Date Format
    setting. A timestamp with a zone is converted to local time first, so the
    day is the user's day. A value that is not ISO is returned as it came.

    Args:
        value: The stored text, or ``None``.

    Returns:
        The formatted date, the original text, or ``""`` for nothing.
    """
    text = (value or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return date_text(dt)


def short_date_text(dt: datetime) -> str:
    """A date in the current year: ``4 Aug`` / ``Aug 4`` / ``08-04``."""
    return local_strftime(dt, DATE_FORMATS[_style["date"]][1])


def weekday_date_text(dt: datetime) -> str:
    """A date in the coming weeks: ``Tue 4 Aug`` / ``Tue Aug 4`` / ``Tue 08-04``."""
    return local_strftime(dt, DATE_FORMATS[_style["date"]][2])
