"""Shared EPG time utilities — single source of truth.

All EPG datetimes are stored as UTC-naive. Display functions convert to local time
via the helpers below (to_local, local_date, is_local_today, local_weekday).
Arithmetic functions compare UTC-naive against now_utc() — no conversion needed.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def _local_tz():
    """Return machine's local tzinfo. Module-level callable for testability via patch."""
    return datetime.now().astimezone().tzinfo


def now_utc() -> datetime:
    """Return current UTC time as a naive datetime (matching EPG storage format)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# UTC-naive → local conversion helpers
# Use these everywhere a UTC-naive EPG datetime needs local display or comparison.
# Never open-code .replace(tzinfo=timezone.utc).astimezone() inline.
# ---------------------------------------------------------------------------

def to_local(dt: datetime) -> datetime:
    """Convert a UTC-naive EPG datetime to a tz-aware local datetime.

    Args:
        dt: UTC-naive datetime as stored in EpgProgramDB.
    Returns:
        The same instant expressed in the machine's local timezone.
    """
    return dt.replace(tzinfo=timezone.utc).astimezone(_local_tz())


def local_date(dt: datetime) -> date:
    """Return the local calendar date for a UTC-naive EPG datetime.

    Args:
        dt: UTC-naive datetime as stored in EpgProgramDB.
    Returns:
        The local calendar date (not the UTC date).
    """
    return to_local(dt).date()


def is_local_today(dt: datetime) -> bool:
    """True if a UTC-naive EPG datetime falls on today's local calendar date.

    Use instead of ``dt.date() == date.today()`` — the latter compares UTC dates
    and is wrong for non-UTC users near local midnight.

    Args:
        dt: UTC-naive datetime as stored in EpgProgramDB.
    """
    return local_date(dt) == date.today()


def local_weekday(dt: datetime) -> str:
    """Return the abbreviated weekday name (e.g. 'Mon') in the local timezone.

    Use instead of ``dt.strftime('%a')`` — the latter formats the UTC weekday.

    Args:
        dt: UTC-naive datetime as stored in EpgProgramDB.
    """
    return to_local(dt).strftime("%a")


def local_day_window(d: date, tz=None) -> tuple[datetime, datetime]:
    """Return UTC-naive (day_start, day_end) bounds for local calendar day d.

    Args:
        d:   Local calendar date chosen by the user (e.g. from a date picker).
        tz:  Local tzinfo to use; defaults to the machine's local timezone.
             Pass explicitly in tests to freeze the timezone.
    Returns:
        (day_start, day_end): UTC-naive datetimes spanning the full local day d.
    """
    _tz = tz if tz is not None else _local_tz()
    local_start = datetime(d.year, d.month, d.day, tzinfo=_tz)
    day_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    day_end   = (local_start + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
    return day_start, day_end


def fmt_time(dt: datetime) -> str:
    """UTC-naive EPG datetime → local time string like '5:30 PM'."""
    return dt.replace(tzinfo=timezone.utc).astimezone().strftime("%-I:%M %p").lstrip("0") or "12:00 AM"


def fmt_duration(start: datetime, stop: datetime) -> str:
    """Duration between two UTC-naive datetimes as a human string like '30m' or '1h 30m'."""
    mins = max(0, int((stop - start).total_seconds() / 60))
    if mins >= 60:
        h, m = divmod(mins, 60)
        return f"{h}h {m}m" if m else f"{h}h"
    return f"{mins}m"


def remaining_str(stop: datetime, _now: datetime | None = None) -> str:
    """Remaining time until stop as a human string like '19m left' or 'ending'."""
    _now = _now or now_utc()
    mins = max(0, int((stop - _now).total_seconds() / 60))
    if mins == 0:
        return "ending"
    if mins >= 60:
        h, m = divmod(mins, 60)
        return f"{h}h {m}m left" if m else f"{h}h left"
    return f"{mins}m left"


def minutes_away(dt: datetime, _now: datetime | None = None) -> int:
    """Minutes until dt (UTC-naive). Returns 0 if dt is in the past."""
    _now = _now or now_utc()
    return max(0, int((dt - _now).total_seconds() / 60))


def progress_pct(start: datetime, stop: datetime, _now: datetime | None = None) -> int:
    """Percentage of show elapsed (0–100)."""
    _now = _now or now_utc()
    total = (stop - start).total_seconds()
    if total <= 0:
        return 100
    elapsed = (_now - start).total_seconds()
    return max(0, min(100, int(elapsed / total * 100)))
