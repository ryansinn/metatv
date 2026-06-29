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


def browse_anchors(_now: datetime | None = None, tz=None) -> list[tuple[str, datetime]]:
    """Forward-looking start anchors for the EPG Browse tab.

    Replaces the old calendar-day × bounded-time-slot model: Browse now runs
    chronologically forward from a chosen *start anchor* and never shows the past.
    Each returned pair is ``(label, anchor)`` where ``anchor`` is a UTC-naive
    datetime (matching EPG storage) and ``label`` shows the resolved LOCAL time
    (e.g. ``"Tonight · 6 PM"``). "Now" is always first.

    Anchors that fall in the past (e.g. "Tonight" selected at 9 PM) are still
    returned; the forward query floors any anchor to ``now`` so such a selection
    simply behaves like "Now". "This Weekend" is omitted when today is already
    the weekend (it would resolve to the past and duplicate "Now").

    Args:
        _now: Reference "now" (UTC-naive); defaults to :func:`now_utc`.
        tz:   Local tzinfo; defaults to the machine's local timezone. Pass
              explicitly in tests to freeze the timezone.

    Returns:
        Ordered ``(label, anchor_utc_naive)`` pairs for the anchor dropdown.
    """
    _tz = tz if tz is not None else _local_tz()
    now = _now or now_utc()
    local_now = now.replace(tzinfo=timezone.utc).astimezone(_tz)

    def _utc_naive(local_dt: datetime) -> datetime:
        return local_dt.astimezone(timezone.utc).replace(tzinfo=None)

    tonight = local_now.replace(hour=18, minute=0, second=0, microsecond=0)
    tomorrow = local_now + timedelta(days=1)
    tomorrow_midnight = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_night = tomorrow.replace(hour=18, minute=0, second=0, microsecond=0)

    anchors: list[tuple[str, datetime]] = [
        ("Now", now),
        (f"Tonight · {tonight.strftime('%-I %p')}", _utc_naive(tonight)),
        (f"Tomorrow · {tomorrow_midnight.strftime('%a')}", _utc_naive(tomorrow_midnight)),
        (f"Tomorrow Night · {tomorrow_night.strftime('%-I %p')}", _utc_naive(tomorrow_night)),
    ]

    # "This Weekend" = upcoming Saturday 00:00 local. Skip when today is already
    # the weekend (Sat=5 / Sun=6) so the anchor never points to the past or to
    # "next" weekend.
    if local_now.weekday() < 5:  # Mon–Fri only
        days_to_sat = 5 - local_now.weekday()
        weekend = (local_now + timedelta(days=days_to_sat)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        anchors.append((f"This Weekend · {weekend.strftime('%a')}", _utc_naive(weekend)))

    return anchors


# ---------------------------------------------------------------------------
# Timeline scrubber (Browse Phase 2) — single source of truth for the snap
# granularity choices and the pure position↔time math + label formatting.
# The slider's integer value is in *increment units*: value 0 = the track's
# left bound, value v = left_bound + v * increment. Snapping is therefore
# inherent (every integer value lands on an increment boundary); both the
# drag-seek and the scroll→handle mapping round through these helpers so the
# snap rule lives in exactly one place.
# ---------------------------------------------------------------------------

# Allowed scrubber snap granularities (minutes) — the Settings dropdown choices
# and the default. Single source of truth shared by config validation tests and
# the settings dialog.
EPG_SCRUBBER_INCREMENTS: list[int] = [15, 30, 60]


def scrubber_value_for(left_bound: datetime, dt: datetime,
                       increment_minutes: int) -> int:
    """Map a UTC-naive datetime to the nearest scrubber slider value (snapped).

    The value is the count of ``increment_minutes`` steps from ``left_bound`` to
    ``dt``, rounded to the nearest step — this is the snap chokepoint for both a
    drag (time → value) and the scroll→handle sync (topmost-row time → value).

    Args:
        left_bound: The track's left edge (UTC-naive); slider value 0.
        dt: The target datetime (UTC-naive) to convert.
        increment_minutes: Snap granularity (one of :data:`EPG_SCRUBBER_INCREMENTS`).

    Returns:
        The (possibly clamped by the caller) integer slider value. May be negative
        if ``dt`` precedes ``left_bound``; callers clamp to the slider range.
    """
    step = max(1, increment_minutes)
    minutes = (dt - left_bound).total_seconds() / 60.0
    return int(round(minutes / step))


def scrubber_time_for(left_bound: datetime, value: int,
                      increment_minutes: int) -> datetime:
    """Map a scrubber slider value back to its (snapped) UTC-naive datetime.

    Inverse of :func:`scrubber_value_for`. Because ``value`` is an integer count
    of increments, the result always lands on the increment grid.

    Args:
        left_bound: The track's left edge (UTC-naive); slider value 0.
        value: The integer slider value.
        increment_minutes: Snap granularity (one of :data:`EPG_SCRUBBER_INCREMENTS`).

    Returns:
        ``left_bound + value * increment_minutes`` as a UTC-naive datetime.
    """
    step = max(1, increment_minutes)
    return left_bound + timedelta(minutes=value * step)


def scrubber_bounds(min_start: datetime | None, max_start: datetime | None,
                    hide_older_hours: int,
                    oldest_airing_start: datetime | None = None,
                    _now: datetime | None = None,
                    ) -> tuple[datetime, datetime]:
    """Compute the scrubber track's (left, right) bounds in UTC-naive time.

    LEFT  defaults to ``oldest_airing_start`` — the start of the oldest show that is
          still on right now — so the track reaches back just far enough to show the
          BEGINNING of everything currently airing, but no further by default. When
          nothing is airing it falls back to ``now``. A non-zero ``hide_older_hours``
          ("Allow browsing back") extends the left edge further into the past
          (``now - hide_older_hours``). The result is clamped UP to the guide's
          earliest start (never before real data) and DOWN to ``now`` (so the default
          handle at "now" is always within range).
    RIGHT = the guide's latest start, clamped to be at least ``now`` (and at least
            ``left``) so the track is always non-empty.

    Args:
        min_start: Earliest programme start for the scoped sources, or ``None``.
        max_start: Latest programme start for the scoped sources, or ``None``.
        hide_older_hours: "Allow browsing back" window
            (``epg_browse_hide_older_than_hours``); ``0`` = no extra trim beyond the
            oldest currently-airing show.
        oldest_airing_start: Start of the oldest currently-airing show for the scope
            (``EpgRepository.get_oldest_airing_start``); the DEFAULT left edge.
            ``None`` ⇒ nothing airing ⇒ fall back to ``now``.
        _now: Reference "now" (UTC-naive); defaults to :func:`now_utc`.

    Returns:
        ``(left_bound, right_bound)`` UTC-naive datetimes with ``left <= right``.
    """
    now = _now or now_utc()
    if min_start is None or max_start is None:
        # No guide data for the scope → collapse to a point at "now" (the scrubber
        # is disabled in this state anyway).
        return now, now
    right = max(max_start, now)
    # Default left = the oldest currently-airing show's start (fall back to now).
    left = oldest_airing_start if oldest_airing_start is not None else now
    # "Allow browsing back" extends the left edge further into the past from now.
    if hide_older_hours > 0:
        left = min(left, now - timedelta(hours=hide_older_hours))
    left = max(left, min_start)    # never before the guide's earliest real data
    left = min(left, now)          # never start the track after "now"
    if left > right:               # degenerate guide → collapse to a point at now
        left = right = now
    return left, right


def scrubber_label(dt: datetime, _now: datetime | None = None) -> str:
    """Format a UTC-naive scrubber position as a local day-context tick label.

    Day boundaries become words — "Today"/"Tonight" (today, evening), "Tomorrow",
    "Yesterday", a weekday name within the coming week, else "Mon Jul 6" — followed
    by the local clock time (e.g. "Tomorrow 6:00 PM"). All conversion goes through
    :func:`to_local` (never inline tz math).

    Args:
        dt: The scrubber position (UTC-naive).
        _now: Reference "now" (UTC-naive); defaults to :func:`now_utc`.

    Returns:
        A short local label like "Tonight 9:30 PM" / "Wed 8:00 AM".
    """
    now = _now or now_utc()
    local = to_local(dt)
    local_now = to_local(now)
    day_delta = (local.date() - local_now.date()).days
    time_str = local.strftime("%-I:%M %p")
    if day_delta == 0:
        prefix = "Tonight" if local.hour >= 18 else "Today"
    elif day_delta == 1:
        prefix = "Tomorrow"
    elif day_delta == -1:
        prefix = "Yesterday"
    elif 1 < day_delta < 7:
        prefix = local.strftime("%A")
    else:
        prefix = local.strftime("%a %b %-d")
    return f"{prefix} {time_str}"


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
