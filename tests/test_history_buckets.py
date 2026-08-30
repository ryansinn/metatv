"""A History heading must delete exactly the rows it listed.

The buckets do double duty: they group the list, and each one is a purge range
("Forget everything you played yesterday?"). That means two functions describe
the same boundaries — ``bucket_for`` decides which heading a row appears under,
``bucket_range`` decides which rows a purge removes.

If they disagree by so much as a second, a heading deletes something it never
showed, or leaves behind something it did. On an irreversible action that is the
worst bug this feature can have, so it is tested by ROUND-TRIP rather than by
asserting the arithmetic twice in slightly different words.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from metatv.core.history_buckets import (
    BUCKETS, BUCKETS_BY_KEY, bucket_for, bucket_range,
)

#: A fixed "now" with an awkward wall-clock time — late evening, so "today"
#: and "24 hours ago" are genuinely different answers and a bug that conflates
#: them cannot hide behind a midday reference point.
NOW = datetime(2026, 8, 29, 22, 40, 0)

#: Ages spanning every boundary and both sides of each, in minutes.
_OFFSETS_MIN = [
    -120, -1, 0, 1, 30, 59, 60, 61, 120,
    # earlier today (NOW is 22:40, so 900 min ago is 07:40 today)
    900, 1000,
    # yesterday and its edges
    1361, 1400, 2000, 2800,
    # 2-7 days
    2881, 4320, 10079, 10080, 10081,
    # 7-30 days
    20000, 43199, 43200, 43201,
    # older
    50000, 200000,
]


def _at(minutes_ago: int) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


@pytest.mark.parametrize("minutes", _OFFSETS_MIN)
def test_a_row_falls_inside_the_range_of_the_bucket_it_is_shown_under(minutes):
    """The round trip: bucket_for(d) -> k, and bucket_range(k) must contain d."""
    when = _at(minutes)
    key = bucket_for(when, now=NOW)
    not_before, not_after = bucket_range(key, now=NOW)

    if not_before is not None:
        assert when >= not_before, (
            f"{when} is shown under {key!r} but the purge range starts at "
            f"{not_before} — the heading would not delete its own row"
        )
    if not_after is not None:
        assert when < not_after, (
            f"{when} is shown under {key!r} but the purge range ends at "
            f"{not_after} — the heading would not delete its own row"
        )


@pytest.mark.parametrize("minutes", _OFFSETS_MIN)
def test_a_row_falls_inside_exactly_one_bucket_range(minutes):
    """No overlaps and no gaps — a row must be purgeable by exactly one heading.

    An overlap means two headings both claim to delete it (and the second finds
    it already gone); a gap means no heading can, so it is unreachable.
    """
    when = _at(minutes)
    containing = []
    for bucket in BUCKETS:
        not_before, not_after = bucket_range(bucket.key, now=NOW)
        if (not_before is None or when >= not_before) and \
           (not_after is None or when < not_after):
            containing.append(bucket.key)
    assert len(containing) == 1, (
        f"{when} falls in {containing or 'NO'} bucket range(s); expected exactly one"
    )


def test_the_ranges_tile_the_whole_timeline_without_gaps():
    """Walk the boundaries: each range must start where the next one ends."""
    ordered = [bucket_range(b.key, now=NOW) for b in BUCKETS]
    # BUCKETS is newest-first, so each range's lower bound is the next's upper.
    for (lo, _hi), (_next_lo, next_hi) in zip(ordered, ordered[1:]):
        assert lo == next_hi, (
            f"gap or overlap: a range starts at {lo} but the next ends at {next_hi}"
        )
    assert ordered[0][1] is None, "the newest bucket must be open-ended at the top"
    assert ordered[-1][0] is None, "the oldest bucket must be open-ended at the bottom"


# --------------------------------------------------------------------------- #
# The labels mean what they say.
# --------------------------------------------------------------------------- #

def test_something_played_after_midnight_is_today_not_hours_ago():
    """Calendar days, because that is what "today" means.

    Played at 00:30, read at 22:40 the same day: 22 hours elapsed, but a person
    would say they watched it today.
    """
    assert bucket_for(datetime(2026, 8, 29, 0, 30), now=NOW) == "today"


def test_something_played_late_last_night_is_yesterday_not_today():
    assert bucket_for(datetime(2026, 8, 28, 23, 50), now=NOW) == "yesterday"


def test_the_last_hour_wins_over_the_calendar_day():
    """A row 20 minutes old is "last hour", not merely "today"."""
    assert bucket_for(NOW - timedelta(minutes=20), now=NOW) == "hour"


def test_just_after_midnight_the_previous_evening_is_yesterday():
    """The nastiest case: 00:10, so "an hour ago" was yesterday."""
    midnight_ish = datetime(2026, 8, 29, 0, 10)
    assert bucket_for(datetime(2026, 8, 28, 23, 55), now=midnight_ish) == "hour"
    assert bucket_for(datetime(2026, 8, 28, 20, 0), now=midnight_ish) == "yesterday"


def test_a_future_timestamp_lands_in_the_newest_bucket():
    """Clock skew must not make a row unreachable."""
    assert bucket_for(NOW + timedelta(hours=3), now=NOW) == "hour"
    lo, hi = bucket_range("hour", now=NOW)
    assert hi is None, "the newest range must be open-ended or skew escapes it"


def test_a_missing_timestamp_still_lands_somewhere():
    assert bucket_for(None, now=NOW) in BUCKETS_BY_KEY


def test_every_bucket_is_fully_described():
    for bucket in BUCKETS:
        assert bucket.label, f"{bucket.key} has no heading label"
        assert bucket.purge_prompt.endswith("?"), (
            f"{bucket.key}'s prompt is not a question: {bucket.purge_prompt!r}"
        )
    keys = [b.key for b in BUCKETS]
    assert len(set(keys)) == len(keys), f"duplicate bucket key in {keys}"
    assert keys[-1] == "older", "the catch-all must stay last"


def test_an_unknown_bucket_raises_rather_than_deleting_everything():
    """A typo'd key must not silently return an unbounded range."""
    with pytest.raises(KeyError):
        bucket_range("last-tuesday", now=NOW)
