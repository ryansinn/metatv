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
    """rows: [(name, start_or_None)]"""
    with database.session_scope() as session:
        for i, (name, start) in enumerate(rows):
            session.add(ChannelDB(
                id=f"c{i}", source_id=str(i), provider_id="p", name=name,
                stream_url="u", media_type="live", special_view="sports",
                sport_type="tennis", event_start_time=start,
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
