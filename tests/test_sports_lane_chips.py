"""The lane chips carry their own counts, and the count is the list's own number.

Mockup Q7: fold the count into the lane chips and drop the standalone
"183 channels" line. The risk that makes this worth testing is not the label —
it is that a count computed by a second, slightly different query lets a chip
claim a number the list never shows. Both go through
``_apply_sports_facets`` and ``_sports_lane_rank``, and the test below proves
they agree for every lane under a filter.

Nothing new was built for the chip itself: ``ToggleChip`` already rendered
"Label (N)" via ``set_count`` and already supported a segmented track.
"""

from __future__ import annotations

import datetime

import pytest

from metatv.core.channel_visibility import VisibilityScope
from metatv.core.database import Database, ChannelDB, ProviderDB
from metatv.core.repositories import RepositoryFactory


NOW = datetime.datetime(2026, 8, 31, 12, 0)
_D = datetime.timedelta


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'lanes.db'}")
    database.create_tables()
    with database.session_scope() as session:
        session.add(ProviderDB(id="p", name="P", type="xtream", url="http://x",
                               username="u", password="p", is_active=True))
        rows = [
            ("live1", NOW - _D(hours=1), "tennis"),
            ("up1", NOW + _D(hours=2), "tennis"),
            ("up2", NOW + _D(days=2), "soccer"),
            ("fin1", NOW - _D(days=4), "tennis"),
            ("fin2", NOW - _D(hours=20), "soccer"),
            ("ch1", None, "tennis"),
            ("ch2", None, None),
        ]
        for i, (name, start, sport) in enumerate(rows):
            session.add(ChannelDB(
                id=f"c{i}", source_id=str(i), provider_id="p", name=name,
                stream_url="u", media_type="live", special_view="sports",
                sport_type=sport, event_start_time=start))
    return database


def _counts(db, **kw):
    with db.session_scope(commit=False) as session:
        return RepositoryFactory(session).channels.get_sports_lane_counts(
            VisibilityScope(), now=NOW, **kw)


def _rows(db, lane, **kw):
    with db.session_scope(commit=False) as session:
        return RepositoryFactory(session).channels.get_sports_channels(
            VisibilityScope(), now=NOW, lane=lane, **kw)


def test_every_lane_is_present_even_at_zero(db):
    """A missing key would make a caller guess whether absence means zero."""
    counts = _counts(db, sport_types=["golf"])   # nothing matches
    assert set(counts) == {"live", "upcoming", "channels", "finished", "placeholders"}
    assert all(v == 0 for v in counts.values())


def test_the_counts_are_correct(db):
    assert _counts(db) == {"live": 1, "upcoming": 2, "channels": 2,
                           "finished": 2, "placeholders": 0}


@pytest.mark.parametrize("facets", [
    {},
    {"sport_types": ["tennis"]},
    {"sport_types": ["soccer"]},
    {"sport_types": ["unknown"]},
])
def test_each_chips_number_equals_the_rows_its_lane_returns(db, facets):
    """The invariant the shared helpers exist to guarantee.

    A count query that drifts from the list query is how a chip comes to
    promise five fixtures and open onto three.
    """
    counts = _counts(db, **facets)
    for lane, promised in counts.items():
        actual = len(_rows(db, lane, **facets))
        assert promised == actual, (
            f"lane {lane!r} under {facets}: chip says {promised}, list has {actual}"
        )


def test_the_counts_total_every_row(db):
    """The lanes partition the set — no row uncounted, none counted twice."""
    counts = _counts(db)
    with db.session_scope(commit=False) as session:
        total = len(RepositoryFactory(session).channels.get_sports_channels(
            VisibilityScope(), now=NOW))
    assert sum(counts.values()) == total


def test_unknown_matches_null_so_general_rows_are_not_lost(db):
    """'unknown' must also match NULL — the General population is 15,944 rows."""
    assert _counts(db, sport_types=["unknown"])["channels"] == 1


# ── the view ────────────────────────────────────────────────────────────────

def _view(db, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.sports_view import SportsView

    def run_query(fn, on_done, token_ref=None, on_error=None):
        with db.session_scope(commit=False) as session:
            on_done(fn(RepositoryFactory(session)))

    return SportsView(db, Config(config_dir=tmp_path), run_query)


def test_exactly_one_lane_is_active_and_it_cannot_be_turned_off(qapp, db, tmp_path):
    """A rundown with no lane selected is a dead end, not a state."""
    view = _view(db, tmp_path)
    view._on_lane_clicked("finished")
    assert sum(c.isChecked() for c in view._lane_chips.values()) == 1

    view._on_lane_clicked("finished")   # click the active one again
    assert view._lane_chips["finished"].isChecked()
    assert sum(c.isChecked() for c in view._lane_chips.values()) == 1


def test_the_chosen_lane_is_remembered(qapp, db, tmp_path):
    """Every UI section remembers its state (DESIGN.md)."""
    view = _view(db, tmp_path)
    view._on_lane_clicked("channels")
    assert view.config.sports_lane == "channels"


def test_a_bad_stored_lane_falls_back_instead_of_breaking(qapp, db, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.sports_view import SportsView

    config = Config(config_dir=tmp_path)
    config.sports_lane = "nonsense"
    view = SportsView(db, config, lambda *a, **k: None)
    assert view._lane == SportsView.DEFAULT_LANE


def test_the_default_lane_is_upcoming_not_live(qapp, db, tmp_path):
    """"On now" is empty most of the day and would read as a broken view."""
    from metatv.gui.sports_view import SportsView
    assert SportsView.DEFAULT_LANE == "upcoming"


def test_a_failed_count_query_leaves_the_labels_bare_rather_than_wrong(qapp, db, tmp_path):
    """A chip is a promise about the list; a stale number is worse than none."""
    view = _view(db, tmp_path)
    view._on_lane_counts_loaded({"live": 3, "upcoming": 4, "channels": 1, "finished": 2})
    assert "(3)" in view._lane_chips["live"].text()
    view._on_lane_counts_loaded(None)          # the error branch
    assert "(3)" in view._lane_chips["live"].text(), "must not blank out to a wrong 0"


# ── placeholders: the fifth lane ────────────────────────────────────────────

def test_a_placeholder_row_gets_its_own_lane(db):
    """5,565 of 28,323 sports rows are literally "NO EVENT STREAMING NOW".

    A lane rather than a filter, because "collapse, never hide" means the count
    is stated and the rows stay one click away — the provider's empty slots are
    not hidden content, but they are not fixtures either.
    """
    with db.session_scope() as session:
        session.add(ChannelDB(
            id="ph", source_id="ph", provider_id="p",
            name="NO EVENT STREAMING NOW - | 8K EXCLUSIVE | US: SOCCER PPV 69",
            stream_url="u", media_type="live", special_view="sports",
            sport_type="soccer", event_start_time=None))

    assert _counts(db)["placeholders"] == 1
    assert [r.name for r in _rows(db, "placeholders")][0].startswith("NO EVENT")


def test_a_placeholder_is_never_counted_as_a_channel(db):
    """It has no start time, so without its own lane it would land in Channels
    and bury the always-on sports networks under the provider's empty slots."""
    before = _counts(db)["channels"]
    with db.session_scope() as session:
        session.add(ChannelDB(
            id="ph", source_id="ph", provider_id="p",
            name="NO EVENT STREAMING NOW - | 8K | US: SOCCER PPV 1",
            stream_url="u", media_type="live", special_view="sports",
            sport_type=None, event_start_time=None))
    assert _counts(db)["channels"] == before


def test_a_placeholder_that_somehow_has_a_start_time_is_still_a_placeholder(db):
    """The marker is checked FIRST — a placeholder is never a fixture."""
    with db.session_scope() as session:
        session.add(ChannelDB(
            id="ph", source_id="ph", provider_id="p",
            name="NO EVENT STREAMING NOW - | 8K | US: SOCCER PPV 2",
            stream_url="u", media_type="live", special_view="sports",
            sport_type="soccer", event_start_time=NOW + _D(hours=1)))
    counts = _counts(db)
    assert counts["placeholders"] == 1
    assert counts["upcoming"] == 2, "must not also be counted as upcoming"
