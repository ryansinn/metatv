"""Purging a History group removes exactly the rows shown under it.

``test_history_buckets.py`` proves the two boundary functions agree in the
abstract. This proves the DATABASE agrees with them: rows are seeded at real
timestamps, grouped the way the widget groups them, and then one group is
purged through the real repository against a real SQLite file.

Also pins the clock. ``last_played`` is written with ``datetime.now()``, and
``clear_history_older_than`` compared it against ``datetime.utcnow()`` — six
hours adrift on the owner's machine, so "clear older than 30 days" silently
cleared 29.75 days. Irreversible, and invisible.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.history_buckets import BUCKETS, bucket_for, bucket_range
from metatv.core.repositories.channel import ChannelRepository


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'history.db'}")
    d.create_tables()
    with d.session_scope() as s:
        s.add(ProviderDB(id="p", name="P", type="xtream",
                         url="http://example.invalid", is_active=True))
    yield d
    d.close()


#: A fixed reference point with a late-evening wall clock. NOT ``datetime.now()``:
#: the seed below places a row "4 hours ago" and expects it under "Today", which
#: is only true if the current time is at least 4 hours past midnight. Run at
#: 00:40 — which is exactly when CI runs in UTC — that row is YESTERDAY and four
#: tests fail for reasons that have nothing to do with the code under test.
NOW = datetime(2026, 8, 29, 22, 40, 0)

#: One row per bucket, at an age unambiguously inside it.
_SEED = {
    "hour":      timedelta(minutes=20),
    "today":     timedelta(hours=4),
    "yesterday": timedelta(days=1, hours=6),
    "week":      timedelta(days=4),
    "month":     timedelta(days=15),
    "older":     timedelta(days=90),
}


def _seed(db, now: datetime) -> dict:
    """Insert one channel per bucket; return {channel_id: bucket_key}."""
    expected = {}
    with db.session_scope() as s:
        for key, age in _SEED.items():
            played = now - age
            cid = f"ch_{key}"
            s.add(ChannelDB(
                id=cid, source_id=cid, provider_id="p", name=f"Film {key}",
                media_type="movie", detected_title=f"Film {key}",
                last_played=played, play_count=3,
            ))
            expected[cid] = key
    return expected


def _remaining(db) -> set:
    with db.session_scope(commit=False) as s:
        return {
            c.id for c in s.query(ChannelDB)
            .filter(ChannelDB.last_played.isnot(None)).all()
        }


def test_the_seed_lands_where_the_widget_would_group_it(db):
    """Guard the fixture itself — a mis-seeded row would fake a passing purge."""
    now = NOW
    expected = _seed(db, now)
    with db.session_scope(commit=False) as s:
        for cid, key in expected.items():
            row = s.query(ChannelDB).filter_by(id=cid).one()
            assert bucket_for(row.last_played, now=now) == key


@pytest.mark.parametrize("bucket", BUCKETS, ids=lambda b: b.key)
def test_purging_one_group_clears_only_that_group(db, bucket):
    now = NOW
    expected = _seed(db, now)

    not_before, not_after = bucket_range(bucket.key, now=now)
    with db.session_scope() as s:
        cleared, _snapshot = ChannelRepository(s).clear_history_in_range(not_before, not_after)

    assert cleared == 1, (
        f"purging {bucket.key!r} cleared {cleared} rows; exactly one was seeded there"
    )
    survivors = _remaining(db)
    assert f"ch_{bucket.key}" not in survivors, "the group's own row survived"
    assert survivors == {cid for cid, k in expected.items() if k != bucket.key}, (
        "purging one group touched another group's rows"
    )


def test_purging_every_group_in_turn_empties_the_history(db):
    """No row is unreachable — the ranges must cover the whole timeline."""
    now = NOW
    _seed(db, now)
    for bucket in BUCKETS:
        not_before, not_after = bucket_range(bucket.key, now=now)
        with db.session_scope() as s:
            ChannelRepository(s).clear_history_in_range(not_before, not_after)
    assert _remaining(db) == set(), "a row survived every group's purge"


def test_a_purge_also_resets_the_play_count(db):
    """Forgetting means forgetting — a leftover count is a ghost of the row."""
    now = NOW
    _seed(db, now)
    not_before, not_after = bucket_range("older", now=now)
    with db.session_scope() as s:
        ChannelRepository(s).clear_history_in_range(not_before, not_after)
    with db.session_scope(commit=False) as s:
        row = s.query(ChannelDB).filter_by(id="ch_older").one()
        assert row.last_played is None
        assert row.play_count == 0


def test_clear_older_than_cuts_exactly_at_the_boundary(db):
    """The clock bug, pinned deterministically rather than by luck.

    ``last_played`` is written with ``datetime.now()``; the cutoff used
    ``datetime.utcnow()``. Whether that deletes too much or too little depends
    on which side of UTC the machine sits, and CI runs in UTC — where the bug
    vanishes entirely. So the reference point is INJECTED and the two rows sit
    one second either side of the boundary, which fails for a cutoff on any
    other clock, in either direction.
    """
    now = datetime(2026, 8, 29, 22, 40, 0)
    boundary = now - timedelta(days=30)
    with db.session_scope() as s:
        for cid, played in (
            ("just_inside", boundary + timedelta(seconds=1)),
            ("just_outside", boundary - timedelta(seconds=1)),
        ):
            s.add(ChannelDB(
                id=cid, source_id=cid, provider_id="p", name=cid,
                media_type="movie", detected_title=cid,
                last_played=played, play_count=1,
            ))

    with db.session_scope() as s:
        cleared = ChannelRepository(s).clear_history_older_than(30, now=now)

    survivors = _remaining(db)
    assert cleared == 1, f"expected exactly the older row to go, cleared {cleared}"
    assert "just_inside" in survivors, (
        "a row one second INSIDE 'keep the last 30 days' was cleared — the "
        "cutoff is on a different clock from the column it compares"
    )
    assert "just_outside" not in survivors, (
        "a row one second OLDER than 30 days survived — the cutoff drifted the "
        "other way"
    )


def test_clear_older_than_still_clears_what_it_should(db):
    """The other half: the fix must not make the purge a no-op."""
    now = NOW
    with db.session_scope() as s:
        s.add(ChannelDB(
            id="c31", source_id="c31", provider_id="p", name="Thirty-one days",
            media_type="movie", detected_title="Thirty-one days",
            last_played=now - timedelta(days=31), play_count=1,
        ))
    with db.session_scope() as s:
        cleared = ChannelRepository(s).clear_history_older_than(30)
    assert cleared == 1
    assert "c31" not in _remaining(db)
