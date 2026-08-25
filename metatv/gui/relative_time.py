"""How long ago something happened, in words — ``"2 hours ago"``, ``"yesterday"``.

The V3 sidebar render puts a *time* on the second line of every History row
("It's Always Sunny… / S18E01 · 2 hours ago"), which is the single most useful
fact about a history entry and the one a raw timestamp communicates worst. One
module so the ladder is defined once: History is the first caller, but Queue's
"last watched" and the details pane want the same words, and three hand-rolled
ladders would disagree about where "last week" starts.

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
