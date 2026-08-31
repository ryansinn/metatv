"""When something happened or will happen, in words — ``"2 hours ago"``, ``"in 13m"``.

The V3 sidebar render puts a *time* on the second line of every History row
("It's Always Sunny… / S18E01 · 2 hours ago"), which is the single most useful
fact about a history entry and the one a raw timestamp communicates worst. One
module so the ladder is defined once: History is the first caller, but Queue's
"last watched" and the details pane want the same words, and three hand-rolled
ladders would disagree about where "last week" starts.

The forward-looking half (:func:`humanize_until`, :func:`humanize_remaining`)
lives here for the same reason. Watch Alerts, ``epg_watchlist_mixin`` and
``epg_widgets`` each grew their own "in N minutes" / "Nm left" string, and they
already disagree — one says ``"in 13m"`` and another ``"in 13 min"`` for the
same fact. Unlike the elapsed ladder these are ALSO recomputed on a timer
(a programme's remaining time is wrong the moment it is rendered), so the
formatter has to be callable with an explicit ``now`` from a repaint tick.

Elapsed-time, not calendar-aware, and deliberately so: "yesterday" here means
"between 24 and 48 hours ago", not "on the previous calendar date". A calendar
rule reads better at 00:30 and worse at every other hour (something watched at
23:00 becomes "yesterday" sixty minutes later), and the sidebar's job is
recency, not dates.
"""

from __future__ import annotations

from datetime import datetime

# The ladder, coarsest-last. Each rung is (upper bound in seconds, formatter).
_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR


def humanize_remaining(stop: datetime | None, now: datetime) -> str:
    """How much of a programme is left — ``"13m left"``, ``"ending"``.

    Both arguments are UTC-naive, the form EPG stores (see
    ``core/epg_utils.py``); ``now`` is required rather than defaulted because
    every caller is either an off-thread load or a repaint tick, and both
    already hold the ``now`` they are working against. Letting it default would
    invite a row and the tick that refreshes it to disagree by a second.

    Args:
        stop: The programme's ``stop_time`` (UTC-naive), or ``None``.
        now: The instant to measure from (UTC-naive).

    Returns:
        ``"Nm left"``, or ``"ending"`` inside the final minute, or ``""`` when
        ``stop`` is ``None``.
    """
    if stop is None:
        return ""
    mins_left = max(0, int((stop - now).total_seconds() / _MINUTE))
    return f"{mins_left}m left" if mins_left >= 1 else "ending"


def humanize_until(start: datetime | None, now: datetime, *,
                   to_local=None, is_local_today=None) -> str:
    """When a programme starts — ``"in 13m"``, ``"2:44 PM"``, ``"Wed 2:44 PM"``.

    Inside the hour a countdown is what you want; past that a countdown stops
    being readable ("in 143m") and a clock time is the more useful fact, which
    is why the ladder switches rather than scaling the unit.

    The two localisation helpers are injected rather than imported so this
    module stays free of the EPG layer; callers pass
    ``epg_utils.to_local`` / ``epg_utils.is_local_today``. Omitting them keeps
    the countdown form at every distance, which is what a caller with no EPG
    context should get.

    Args:
        start: The programme's ``start_time`` (UTC-naive), or ``None``.
        now: The instant to measure from (UTC-naive).
        to_local: ``epg_utils.to_local``, or ``None``.
        is_local_today: ``epg_utils.is_local_today``, or ``None``.

    Returns:
        A countdown under an hour, else a local clock time (with the weekday
        when it is not today); ``""`` when ``start`` is ``None``.
    """
    if start is None:
        return ""
    mins = int((start - now).total_seconds() / _MINUTE)
    if mins < 60 or to_local is None:
        return f"in {mins}m"
    local = to_local(start)
    if is_local_today is not None and is_local_today(start):
        return local.strftime("%-I:%M %p")
    return local.strftime("%a %-I:%M %p")


def humanize_ago(when: datetime | None, *, now: datetime | None = None) -> str:
    """Render ``when`` as an age relative to ``now`` — ``"3 days ago"``.

    Args:
        when: The moment in the past. ``None`` yields ``""`` so a caller can
            drop it straight into :func:`~metatv.gui.chip_row.sidebar_meta_line`
            without a guard — a missing timestamp contributes nothing rather
            than the string "None".
        now: The reference point; defaults to ``datetime.now()``. Injectable so
            tests state an age instead of sleeping.

    Returns:
        A lower-case phrase suitable for a meta line, or ``""`` when ``when`` is
        ``None``. A future timestamp (clock skew, a provider's optimistic
        stamp) reads "just now" rather than a negative age.
    """
    if when is None:
        return ""
    now = now or datetime.now()
    secs = (now - when).total_seconds()

    if secs < _MINUTE:
        return "just now"
    if secs < _HOUR:
        return f"{int(secs // _MINUTE)} min ago"
    if secs < _DAY:
        hours = int(secs // _HOUR)
        return "an hour ago" if hours == 1 else f"{hours} hours ago"

    days = int(secs // _DAY)
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    if days < 30:
        return f"{days // 7} weeks ago"
    if days < 365:
        months = days // 30
        return "last month" if months == 1 else f"{months} months ago"
    years = days // 365
    return "last year" if years == 1 else f"{years} years ago"


def humanize_ago_terse(when: datetime | None, *, now: datetime | None = None) -> str:
    """The same age in as few characters as possible — ``"2h"``, ``"3d"``, ``"2w"``.

    The COMPACT sidebar row has room for a chip-sized fact at its right edge, not
    for "2 hours ago". History spends that slot on when you watched something,
    because in a list ordered by recency that is the fact that tells one row from
    the next — so it has to fit in the space a language chip would have taken.

    Same ladder and same rungs as :func:`humanize_ago`, so a row and its tooltip
    can never disagree about which bucket something falls in.
    """
    if when is None:
        return ""
    now = now or datetime.now()
    secs = (now - when).total_seconds()

    if secs < _MINUTE:
        return "now"
    if secs < _HOUR:
        return f"{int(secs // _MINUTE)}m"
    if secs < _DAY:
        return f"{int(secs // _HOUR)}h"

    days = int(secs // _DAY)
    if days < 7:
        return f"{days}d"
    if days < 30:
        return f"{days // 7}w"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def humanize_countdown(start: "datetime | None", now: "datetime") -> str:
    """How long until a dated EVENT — ``"in 3d 4h"``, ``"in 47s"``, ``"ended"``.

    A policy sibling of :func:`humanize_until`, not a duplicate of it, and the
    difference is the subject rather than the wording. ``humanize_until`` serves
    EPG programmes, where past an hour a countdown stops being readable ("in
    143m") and a clock time is the more useful fact. A pay-per-view fight is
    announced *days* out, and "Sat 9:00 PM" answers a different question than
    "in 3d 4h" — the second is what a viewer deciding whether to wait around
    actually wants.

    So the ladder here goes UP into days rather than switching to a clock, and
    it goes DOWN to seconds, because the last minute before a live event is the
    one where a ticking number means something.

    ``now`` is passed in and is never re-read from the clock inside — the whole
    point is that a repaint tick supplies it, and a function that quietly asks
    the real clock cannot be tested and drifts from its caller's frame.

    Args:
        start: When the event begins. ``None`` yields ``""`` so a caller can
            render it without a guard.
        now: The instant to measure from. Same naivety as *start*.

    Returns:
        ``"in 3d 4h"`` / ``"in 4h 12m"`` / ``"in 12m 30s"`` / ``"in 47s"`` for
        the future; ``"ended"`` or ``"ended 3d ago"`` for the past; ``""`` when
        *start* is None.
    """
    if start is None:
        return ""
    delta = int((start - now).total_seconds())
    if delta < 0:
        days = -delta // _DAY
        return "ended" if days == 0 else f"ended {days}d ago"
    days, rem = divmod(delta, _DAY)
    hours, rem = divmod(rem, _HOUR)
    minutes, seconds = divmod(rem, _MINUTE)
    if days:
        return f"in {days}d {hours}h"
    if hours:
        return f"in {hours}h {minutes}m"
    if minutes:
        return f"in {minutes}m {seconds}s"
    return f"in {seconds}s"


def is_countdown_live(start: "datetime | None", now: "datetime") -> bool:
    """Whether :func:`humanize_countdown` would change within the next second.

    The Events view repaints on a 1 Hz timer, and a grid of 2,800 cards that
    all read ``"in 3d 4h"`` gains nothing from ticking — the string is stable
    for the next hour. Only cards under a day are worth repainting per second.

    Args:
        start: The event's start, or None.
        now: The instant to measure from.

    Returns:
        True when *start* is in the future and less than a day away.
    """
    if start is None:
        return False
    delta = (start - now).total_seconds()
    return 0 <= delta < _DAY
