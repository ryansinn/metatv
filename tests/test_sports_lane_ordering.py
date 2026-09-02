"""A schedule is ordered by TIME, not alphabetically.

The owner filtered Sports to Tennis and saw a four-day-old US Open qualifying
round at the top with nothing from today. The cause was not the filter: the
query ordered by ``(sport_type, league_name, name)``, and "US Open: Court 5 …"
simply sorts early. Every finished fixture outranked every upcoming one.

Measured on the owner's library at the time: of 309 US Open rows, **219 were
finished**, 82 upcoming and 8 live. Alphabetical order put the 219 first.

Four lanes, in this order — live (started within ``LIVE_WINDOW``), upcoming
(soonest first), channels (no start time: the 24/7 racks, which correctly have
no schedule), finished (most recent first, and always last).
"""

from __future__ import annotations

import datetime

import pytest

from metatv.core.channel_visibility import VisibilityScope
from metatv.core.database import Database, ChannelDB
from metatv.core.repositories import RepositoryFactory


NOW = datetime.datetime(2026, 8, 31, 12, 0)


@pytest.fixture
def db(tmp_path):
    """A real on-disk Database — DB-session work is never tested on :memory:."""
    database = Database(f"sqlite:///{tmp_path / 'sports.db'}")
    database.create_tables()
    return database


def _seed(database, rows):
    """rows: [(name, start_or_None)] or [(name, start, stop)]"""
    with database.session_scope() as session:
        for i, row in enumerate(rows):
            name, start = row[0], row[1]
            stop = row[2] if len(row) > 2 else None
            session.add(ChannelDB(
                id=f"c{i}", source_id=str(i), provider_id="p", name=name,
                stream_url="u", media_type="live", special_view="sports",
                sport_type="tennis", event_start_time=start,
                event_stop_time=stop,
            ))


def _names(database, **kwargs):
    with database.session_scope(commit=False) as session:
        rows = RepositoryFactory(session).channels.get_sports_channels(
            VisibilityScope(), now=NOW, **kwargs)
    return [r.name for r in rows]


_MIXED = [
    # Deliberately named so ALPHABETICAL order is the exact opposite of correct:
    # the finished one sorts first by name and must sort last by time.
    ("AAA finished four days ago", NOW - datetime.timedelta(days=4)),
    ("BBB finished last night",    NOW - datetime.timedelta(hours=20)),
    ("CCC on now",                 NOW - datetime.timedelta(hours=1)),
    ("DDD starts in two hours",    NOW + datetime.timedelta(hours=2)),
    ("EEE starts in two days",     NOW + datetime.timedelta(days=2)),
    ("FFF 24/7 channel",           None),
]


def test_a_finished_fixture_never_outranks_one_that_has_not_happened(db):
    """The owner's bug, stated as an invariant.

    Under the old ``ORDER BY name`` this fails immediately: "AAA finished four
    days ago" is first.
    """
    _seed(db, _MIXED)
    order = _names(db)
    assert order.index("CCC on now") < order.index("AAA finished four days ago")
    assert order.index("DDD starts in two hours") < order.index("BBB finished last night")
    # And the first thing on screen is something you can actually watch.
    assert order[0] == "CCC on now"


def test_the_four_lanes_come_in_order(db):
    _seed(db, _MIXED)
    assert _names(db) == [
        "CCC on now",                 # live
        "DDD starts in two hours",    # upcoming, soonest first
        "EEE starts in two days",
        "FFF 24/7 channel",           # channels
        "BBB finished last night",    # finished, most recent first
        "AAA finished four days ago",
    ]


@pytest.mark.parametrize("lane,expected", [
    ("live",     ["CCC on now"]),
    ("upcoming", ["DDD starts in two hours", "EEE starts in two days"]),
    ("channels", ["FFF 24/7 channel"]),
    ("finished", ["BBB finished last night", "AAA finished four days ago"]),
])
def test_each_lane_returns_only_its_own_rows(db, lane, expected):
    _seed(db, _MIXED)
    assert _names(db, lane=lane) == expected


def test_the_lanes_partition_the_rows_exactly(db):
    """No row is dropped and none is counted twice — the chips must total."""
    _seed(db, _MIXED)
    everything = _names(db)
    from_lanes = []
    for lane in ("live", "upcoming", "channels", "finished"):
        from_lanes += _names(db, lane=lane)
    assert sorted(from_lanes) == sorted(everything)
    assert len(from_lanes) == len(_MIXED)


def test_an_unknown_lane_is_an_error_not_an_empty_list(db):
    """A typo must not look like "no fixtures" — that is indistinguishable."""
    _seed(db, _MIXED)
    with pytest.raises(ValueError, match="unknown lane"):
        _names(db, lane="upcomming")


def test_a_row_with_no_start_time_is_a_channel_not_a_finished_fixture(db):
    """The 24/7 racks have no schedule; filing them under finished would bury
    every always-on sports channel below yesterday's results."""
    _seed(db, [("rack", None)])
    assert _names(db, lane="channels") == ["rack"]
    assert _names(db, lane="finished") == []


def test_the_live_window_has_an_end(db):
    """Without a provider end time "on now" is a window, so it must expire."""
    from metatv.core.repositories.channel_stats import _ChannelStatsMixin as _M
    window = _M.LIVE_WINDOW
    _seed(db, [
        ("just inside",  NOW - window + datetime.timedelta(minutes=1)),
        ("just outside", NOW - window - datetime.timedelta(minutes=1)),
    ])
    assert _names(db, lane="live") == ["just inside"]
    assert _names(db, lane="finished") == ["just outside"]


def test_now_is_taken_from_the_caller_not_the_clock(db):
    """A ranking handed a `now` must not re-read the real clock underneath.

    Seeded relative to NOW (2026-08-31); asked to rank as if it were a year
    later, everything must have finished.
    """
    _seed(db, _MIXED)
    later = NOW + datetime.timedelta(days=365)
    with db.session_scope(commit=False) as session:
        rows = RepositoryFactory(session).channels.get_sports_channels(
            VisibilityScope(), now=later, lane="finished")
    # Five dated rows; the 24/7 channel stays a channel.
    assert len(rows) == 5


# ── the provider's own end time ──────────────────────────────────────────────
#
# ``LIVE_WINDOW`` is an assumed duration, and the slot form makes it unnecessary
# for the rows that carry one. Measured on the owner's 56 slot rows 2026-09-02:
# windows run 3.00h to 7.22h, so the fixed 4h was wrong in BOTH directions.

#: The real MLB slot length on the owner's library — every long row is this.
_SLOT = datetime.timedelta(hours=7, minutes=13)


def test_a_long_slot_is_still_live_past_the_assumed_duration(db):
    """The owner's "Nothing is ever On Now", as an invariant.

    32 of the 56 rows run longer than ``LIVE_WINDOW`` — median 7.22h — so the
    assumed duration expired a median 3.22h before the game did, and ~45% of
    every slot read "Finished" while it was being watched.

    Fails against the pre-fix CASE, which files this row under ``finished``.
    """
    started = NOW - datetime.timedelta(hours=5)      # 5h into a 7h13m slot
    _seed(db, [("MLB 04 | Mariners x Red Sox", started, started + _SLOT)])
    assert _names(db, lane="live") == ["MLB 04 | Mariners x Red Sox"]
    assert _names(db, lane="finished") == []


def test_a_short_slot_is_finished_before_the_assumed_duration(db):
    """The other direction — the one that plays a different game.

    24 of the 56 run SHORTER than ``LIVE_WINDOW`` (min 3.00h). Listing a
    finished fixture as on-now is worse than clutter: the provider recycles the
    stream id, so opening it serves whatever occupies that slot now — the user
    is shown one title and served another.

    Fails against the pre-fix CASE, which files this row under ``live``.
    """
    started = NOW - datetime.timedelta(hours=3, minutes=30)
    _seed(db, [("MLB 01 | Rays x Tigers", started,
                started + datetime.timedelta(hours=3))])
    assert _names(db, lane="live") == []
    assert _names(db, lane="finished") == ["MLB 01 | Rays x Tigers"]


def test_a_row_with_no_end_time_still_uses_the_assumed_duration(db):
    """The fallback must survive: 56 rows of 31,296 carry an end time.

    Reading the new column must not quietly make every OTHER dated fixture
    un-classifiable — that would trade one empty lane for a much larger one.
    """
    from metatv.core.repositories.channel_stats import _ChannelStatsMixin as _M
    window = _M.LIVE_WINDOW
    _seed(db, [
        ("no end, just inside",  NOW - window + datetime.timedelta(minutes=1)),
        ("no end, just outside", NOW - window - datetime.timedelta(minutes=1)),
    ])
    assert _names(db, lane="live") == ["no end, just inside"]
    assert _names(db, lane="finished") == ["no end, just outside"]


def test_sql_lane_agrees_with_the_python_predicate(db):
    """The lane CASE and ``event_is_on_now`` are one rule in two languages.

    SQL cannot call the Python predicate, so nothing but this stops them
    drifting — and a drift shows up as the Sports view and the Events view
    disagreeing about the same fixture, which is unfalsifiable from either one
    on its own.
    """
    from metatv.core.event_datetime import event_is_on_now

    hours = datetime.timedelta(hours=1)
    cases = []
    for start_h in (-9, -7, -5, -4, -3, -1, 0, 1):
        for dur_h in (None, 3, 4, 7):
            start = NOW + start_h * hours
            stop = None if dur_h is None else start + dur_h * hours
            cases.append((f"s{start_h}_d{dur_h}", start, stop))
    _seed(db, cases)

    from_sql = set(_names(db, lane="live"))
    from_python = {n for n, start, stop in cases
                   if event_is_on_now(start, stop, NOW)}
    assert from_sql == from_python
