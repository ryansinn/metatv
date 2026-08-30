"""Time buckets for the History list — the groups, and what each one purges.

History is a list ordered by exactly one thing: when you watched something. It
spent a slot on every row saying that again ("2h", "yesterday"), which is the
one fact the ORDER already tells you — while two rows for the same film at
different qualities looked identical, because the chip that would tell them
apart had nowhere to go.

Owner: *"rather than having the time on the same line as the history entries,
why not just have subdivisions … does it really matter when someone watched
something? it's already in chronological order"*, and *"it would make sense for
the subdivisions to be tied to the purge options for history"*.

So the buckets are not decoration: **each one is a purge range.** The heading
that says "THIS MONTH · 42" is also the control that forgets those 42, which
makes tidying up granular where it used to be "30 days or everything".

Deliberately in ``core/`` rather than beside the widget: the repository needs
the same boundaries to delete by, and a bucket whose label and whose DELETE
disagree is the worst possible bug in this feature.

**Local time throughout.** ``ChannelDB.last_played`` is written with
``datetime.now()``, so every boundary here is local too. ``clear_history_older_than``
used to compare against ``datetime.utcnow()`` — six hours adrift on the owner's
machine, which made "clear older than 30 days" quietly clear 29.75 days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class HistoryBucket:
    """One time group, and the age range it covers.

    Attributes:
        key: Stable identifier — used by the purge signal, never displayed.
        label: The heading text. Rendered uppercase by ``GroupHeading``.
        purge_prompt: What the confirmation asks before forgetting this group.
            Written per bucket because "Forget everything from today?" and
            "Forget everything older than a month?" are different questions.
    """

    key: str
    label: str
    purge_prompt: str


#: Newest first, matching the list's own order. ``older`` is the catch-all and
#: must stay last — :func:`bucket_for` falls through to it.
BUCKETS: tuple[HistoryBucket, ...] = (
    HistoryBucket("hour", "Last hour",
                  "Forget everything you played in the last hour?"),
    HistoryBucket("today", "Today",
                  "Forget everything you played today?"),
    HistoryBucket("yesterday", "Yesterday",
                  "Forget everything you played yesterday?"),
    HistoryBucket("week", "Earlier this week",
                  "Forget everything you played earlier this week?"),
    HistoryBucket("month", "Earlier this month",
                  "Forget everything you played earlier this month?"),
    HistoryBucket("older", "Older",
                  "Forget everything older than a month?"),
)

BUCKETS_BY_KEY: dict[str, HistoryBucket] = {b.key: b for b in BUCKETS}


def bucket_for(when: datetime | None, *, now: datetime | None = None) -> str:
    """Return the bucket key *when* belongs to.

    Calendar days for "today" and "yesterday" (which is what those words mean —
    something watched at 00:30 was watched *today*, not "23 hours ago"), and
    elapsed days beyond that.

    Args:
        when: When the channel was last played, in LOCAL time. ``None`` sorts to
            ``"older"`` so a row with no timestamp still lands somewhere.
        now: Reference point; defaults to ``datetime.now()``. Injectable so a
            test states an age instead of sleeping.

    Returns:
        One of the keys in :data:`BUCKETS`.
    """
    if when is None:
        return "older"
    now = now or datetime.now()
    if when > now:
        # Clock skew, or a provider's optimistic stamp. It has not happened
        # "an hour ago"; the newest bucket is the honest home for it.
        return "hour"

    # ``<=``, not ``<``: :func:`bucket_range` yields half-open windows
    # ``[not_before, not_after)`` with the LOWER bound inclusive, so a row
    # exactly one hour old belongs to "hour". With ``<`` it was shown under
    # "today" while sitting outside today's purge range — a heading that could
    # not delete its own row. The round-trip test caught this at all three
    # boundaries (1 hour, 7 days, 30 days).
    if now - when <= timedelta(hours=1):
        return "hour"

    today = now.date()
    played = when.date()
    if played == today:
        return "today"
    if played == today - timedelta(days=1):
        return "yesterday"
    if now - when <= timedelta(days=7):
        return "week"
    if now - when <= timedelta(days=30):
        return "month"
    return "older"


def bucket_range(key: str, *, now: datetime | None = None
                 ) -> "tuple[datetime | None, datetime | None]":
    """Return ``(not_before, not_after)`` bounding the rows in *key*.

    The DELETE counterpart to :func:`bucket_for`: purging a group removes rows
    whose ``last_played`` falls in this half-open window. ``None`` on either end
    means unbounded.

    The two functions must agree, or a heading deletes rows it never listed —
    ``tests/test_history_buckets.py`` asserts that by round-tripping every
    bucket rather than trusting the arithmetic twice.

    Args:
        key: A bucket key from :data:`BUCKETS`.
        now: Reference point; defaults to ``datetime.now()``.

    Returns:
        ``(not_before, not_after)``: rows with ``not_before <= last_played``
        and ``last_played < not_after`` are in the bucket.

    Raises:
        KeyError: If *key* is not a known bucket.
    """
    if key not in BUCKETS_BY_KEY:
        raise KeyError(f"unknown history bucket: {key!r}")
    now = now or datetime.now()
    today = now.date()
    start_of_today = datetime.combine(today, datetime.min.time())
    start_of_yesterday = start_of_today - timedelta(days=1)
    one_hour_ago = now - timedelta(hours=1)

    if key == "hour":
        # Open-ended at the top so a future-stamped row is included, matching
        # bucket_for's handling of clock skew.
        return (one_hour_ago, None)
    if key == "today":
        return (start_of_today, one_hour_ago)
    if key == "yesterday":
        return (start_of_yesterday, start_of_today)
    if key == "week":
        return (now - timedelta(days=7), start_of_yesterday)
    if key == "month":
        return (now - timedelta(days=30), now - timedelta(days=7))
    return (None, now - timedelta(days=30))
