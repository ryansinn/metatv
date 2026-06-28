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


# A provider whose guide ends within this window is "ending soon" (about to run out).
EPG_ENDING_SOON_HOURS = 24

# A programme longer than this is treated as a multi-day placeholder ("filler")
# rather than a real broadcast, so it never inflates guide-depth / coverage
# calculations. 12 h covers all realistic broadcasts. Single source of truth —
# imported by both epg_manager (provider-wide honest end) and the EPG repository
# (per-scope contiguous coverage).
EPG_FILLER_THRESHOLD = timedelta(hours=12)


def epg_status(epg_url: str | None, epg_data_end: datetime | None,
               _now: datetime | None = None) -> str:
    """Classify a provider's EPG freshness as a single state string.

    - ``"none"``    — no EPG configured, or nothing fetched yet
    - ``"stale"``   — guide data already ended (feed is out of date)
    - ``"soon"``    — guide ends within ``EPG_ENDING_SOON_HOURS`` (about to run out)
    - ``"current"`` — guide extends comfortably into the future

    Canonical classifier for the sidebar EPG indicator, the EPG view, and the editor.
    Compared UTC-naive against :func:`now_utc` (``epg_data_end`` storage format).
    """
    if not epg_url or epg_data_end is None:
        return "none"
    now = _now or now_utc()
    if epg_data_end < now:
        return "stale"
    if epg_data_end < now + timedelta(hours=EPG_ENDING_SOON_HOURS):
        return "soon"
    return "current"


def epg_is_stale(epg_data_end: datetime | None, _now: datetime | None = None) -> bool:
    """Return True if a provider's fetched EPG guide already ended (data is stale).

    ``epg_data_end`` is the latest programme stop_time, stored UTC-naive, so it is
    compared against :func:`now_utc`. A provider with no EPG data (``None``) is not
    "stale" — it simply has no guide; callers distinguish that separately. This is the
    single source of truth for EPG staleness (EPG view notice, provider editor, fetch
    warning).
    """
    if epg_data_end is None:
        return False
    return epg_data_end < (_now or now_utc())


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


def contiguous_guide_end(
    spans: list[tuple[datetime, datetime]],
    _now: datetime | None = None,
    gap_threshold: timedelta = timedelta(hours=1),
) -> datetime | None:
    """Last guide time reachable from now without a coverage hole.

    Given ``(start, stop)`` spans for the selected sources/scope (UTC-naive),
    walk them in start order from ``_now`` and return the running-maximum
    ``stop`` at the point where the next programme would open a gap wider than
    ``gap_threshold``. This reflects the guide's *real contiguous* depth: a feed
    missing tonight's late-night block reports coverage ending at the hole, never
    the far-future max stop somewhere past it (the dishonest "reaches tomorrow").

    Multi-day filler spans (> :data:`EPG_FILLER_THRESHOLD`) are ignored so a
    placeholder "Program" entry can't bridge a real hole and fake full coverage.

    Args:
        spans: ``(start_time, stop_time)`` pairs, UTC-naive (order irrelevant).
        _now: Reference "now" (UTC-naive); defaults to :func:`now_utc`.
        gap_threshold: A gap larger than this between the running contiguous
            coverage and the next programme's start ends the contiguous run.

    Returns:
        The last contiguous ``stop`` datetime, or ``None`` when no non-filler
        programme ends after ``_now``.
    """
    now = _now or now_utc()
    future = sorted(
        (
            (start, stop)
            for start, stop in spans
            if stop > now and (stop - start) <= EPG_FILLER_THRESHOLD
        ),
        key=lambda s: s[0],
    )
    if not future:
        return None
    coverage_end: datetime | None = None
    for start, stop in future:
        if coverage_end is None:
            coverage_end = stop
            continue
        if start > coverage_end + gap_threshold:
            break  # hole detected — contiguous coverage ends here
        if stop > coverage_end:
            coverage_end = stop
    return coverage_end


# ---------------------------------------------------------------------------
# EPG refresh interval — single source of truth for enum values + labels.
# Used by EpgManager.needs_refresh(), the provider editor dropdown, and the
# global settings dropdown. All label/enum data lives here (one place).
# ---------------------------------------------------------------------------

# Ordered (value, human_label) pairs. "auto" self-tunes from guide depth;
# "every_open" and "when_stale" are sentinels; all others map to a timedelta
# via epg_interval_delta().
EPG_INTERVAL_CHOICES: list[tuple[str, str]] = [
    ("auto",       "Auto (recommended)"),
    ("every_open", "Every time EPG opens"),
    ("4h",         "Every 4 hours"),
    ("8h",         "Every 8 hours"),
    ("12h",        "Every 12 hours"),
    ("1d",         "Daily"),
    ("2d",         "Every 2 days"),
    ("3d",         "Every 3 days"),
    ("7d",         "Weekly"),
    ("when_stale", "Only when data is stale"),
]

_EPG_INTERVAL_DELTA_MAP: dict[str, timedelta] = {
    "4h":  timedelta(hours=4),
    "8h":  timedelta(hours=8),
    "12h": timedelta(hours=12),
    "1d":  timedelta(days=1),
    "2d":  timedelta(days=2),
    "3d":  timedelta(days=3),
    "7d":  timedelta(days=7),
}

# Auto-interval clamp bounds: never refresh more often than 6 h or less often
# than 7 d, regardless of feed depth.
EPG_AUTO_MIN_DELTA = timedelta(hours=6)
EPG_AUTO_MAX_DELTA = timedelta(days=7)


def epg_auto_delta(epg_data_start: "datetime | None",
                   epg_data_end: "datetime | None") -> timedelta:
    """Compute the Auto refresh interval from guide depth (half-depth, clamped).

    Fetches at half the guide's depth so there is always ~50 % headroom
    before the data runs out.  Clamped to [6 hours, 7 days] so a 1-hour toy
    feed does not hammer the server and a month-long mega-feed still refreshes
    at least weekly.

    Args:
        epg_data_start: Earliest programme start stored on the provider (UTC-naive).
        epg_data_end:   Latest non-filler programme stop stored (UTC-naive).

    Returns:
        A :class:`~datetime.timedelta` — the computed refresh delta.
    """
    if epg_data_start is None or epg_data_end is None:
        # No depth information yet — fall back to daily so a fresh provider
        # does not wait a week before its first scheduled re-fetch.
        return timedelta(days=1)
    depth = epg_data_end - epg_data_start
    half = depth / 2
    if half < EPG_AUTO_MIN_DELTA:
        return EPG_AUTO_MIN_DELTA
    if half > EPG_AUTO_MAX_DELTA:
        return EPG_AUTO_MAX_DELTA
    return half


def epg_interval_delta(value: str) -> timedelta | None:
    """Map an interval enum value to a timedelta.

    Returns ``None`` for the non-time sentinels (``"every_open"``,
    ``"when_stale"``, and ``"auto"``).  Callers must handle those branches
    explicitly before calling this helper (``"auto"`` → call
    :func:`epg_auto_delta` instead).

    Args:
        value: One of the :data:`EPG_INTERVAL_CHOICES` values.

    Returns:
        A :class:`~datetime.timedelta` for time-based intervals, or ``None``
        for ``"every_open"`` / ``"when_stale"`` / ``"auto"``.
    """
    return _EPG_INTERVAL_DELTA_MAP.get(value)
