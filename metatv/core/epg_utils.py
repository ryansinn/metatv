"""Shared EPG time utilities — single source of truth.

All EPG datetimes are stored as UTC-naive. Display functions convert to local time.
Arithmetic functions compare UTC-naive against now_utc() — no conversion needed.
"""
from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return current UTC time as a naive datetime (matching EPG storage format)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
