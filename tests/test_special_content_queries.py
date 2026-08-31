"""16,715 of the 35,181 sports rows belong to a source the owner switched off.

The four sports/events queries in ``ChannelStatsRepository`` each hand-wrote the
same four clauses — ``special_view == X``, ``is_hidden == False``, a non-NULL
stream_url, ``NOT LIKE '#%'`` — and **not one of them excluded a hidden
provider**. TREX Shared is ``is_active = 0`` on the owner's install and carries
16,715 sports channels; a Sports view built on those queries would have shown
every one of them.

That is the rule the project treats as absolute rather than soft: content from a
disabled or expired source is never shown, counted, or revealed. So the filter
now has ONE definition (``_special_content_query``) and its exclusions come from
:class:`VisibilityScope`, per CLAUDE.md's "never hand-thread an exclusion axis
onto a channel query".

``scope`` is a REQUIRED argument. There were no callers, so making it impossible
to forget cost nothing — and forgetting is precisely how the gap existed.

The queries also returned raw ``ChannelDB`` rows, which would raise
``DetachedInstanceError`` on the main thread the moment the session closed.
They return ``SpecialContentDTO`` now.
"""

import pytest

from metatv.core.channel_visibility import VisibilityScope
from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import SpecialContentDTO


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'sc.db'}")
    database.create_tables()
    return database


def _seed(db, rows):
    """rows: (id, name, provider, special_view, sport, league, team, hidden, url)."""
    with db.session_scope() as session:
        for (cid, name, prov, sv, sport, league, team, hidden, url) in rows:
            session.add(ChannelDB(
                id=cid, source_id=cid, provider_id=prov, name=name,
                media_type="live", special_view=sv, sport_type=sport,
                league_name=league, team_name=team, is_hidden=hidden,
                stream_url=url))


_ROWS = [
    ("a", "US| NFL NETWORK",    "live",     "sports", "football", "NFL", None, False, "http://x"),
    ("b", "US| NBA TV",         "live",     "sports", "basketball", "NBA", None, False, "http://x"),
    ("c", "TREX| ESPN",         "disabled", "sports", "football", "NFL", None, False, "http://x"),
    ("d", "US| HIDDEN SPORT",   "live",     "sports", "football", "NFL", None, True,  "http://x"),
    ("e", "##### SPORTS #####", "live",     "sports", None, None, None, False, "http://x"),
    ("f", "US| NO URL SPORT",   "live",     "sports", "football", "NFL", None, False, None),
    ("g", "Big Fight Tonight",  "live",     "ppv",    "boxing", None, None, False, "http://x"),
    ("h", "Some Event",         "live",     "live_event", None, None, None, False, "http://x"),
]

_ALL = VisibilityScope()
_NO_DISABLED = VisibilityScope(excluded_provider_ids=["disabled"])


def _repo(session):
    return RepositoryFactory(session).channels


# --------------------------------------------------------------------------
# The gap this closes
# --------------------------------------------------------------------------

def test_a_disabled_source_is_excluded(db):
    """The whole reason for the change: 16,715 rows from an off source."""
    _seed(db, _ROWS)
    with db.session_scope(commit=False) as session:
        names = {c.name for c in _repo(session).get_sports_channels(_NO_DISABLED)}
    assert "TREX| ESPN" not in names, (
        "a channel from a disabled provider reached the sports view")
    assert "US| NFL NETWORK" in names


def test_the_exclusion_reaches_every_query_not_just_the_list(db):
    """The taxonomy and the counts feed the FILTER DROPDOWNS.

    Excluding a provider from the list but not from the counts gives a dropdown
    promising 40 channels that shows 24 — which is how a hand-listed axis on one
    of four call sites fails.
    """
    _seed(db, [
        ("a", "US| NFL NETWORK", "live",     "sports", "football", "NFL", None, False, "http://x"),
        ("c", "TREX| CURLING",   "disabled", "sports", "curling",  "WCF", "Team A", False, "http://x"),
    ])
    with db.session_scope(commit=False) as session:
        repo = _repo(session)
        assert "curling" not in repo.get_sports_counts(_NO_DISABLED)
        assert "curling" not in repo.get_sports_taxonomy(_NO_DISABLED)
        assert repo.get_sports_counts(_NO_DISABLED) == {"football": 1}


def test_without_the_exclusion_it_is_still_there(db):
    """Proves the previous two tests measure the SCOPE and not something else."""
    _seed(db, _ROWS)
    with db.session_scope(commit=False) as session:
        names = {c.name for c in _repo(session).get_sports_channels(_ALL)}
    assert "TREX| ESPN" in names


def test_scope_is_required(db):
    """Not an optional keyword: forgetting it is the bug, so it cannot compile
    away silently."""
    import inspect

    from metatv.core.repositories.channel_stats import _ChannelStatsMixin

    for name in ("get_sports_channels", "get_events_channels",
                 "get_sports_taxonomy", "get_sports_counts"):
        sig = inspect.signature(getattr(_ChannelStatsMixin, name))
        param = sig.parameters["scope"]
        assert param.default is inspect.Parameter.empty, (
            f"{name}(scope=...) has a default — a caller can forget it")


# --------------------------------------------------------------------------
# The clauses that were already right, kept right
# --------------------------------------------------------------------------

@pytest.mark.parametrize("excluded", [
    "US| HIDDEN SPORT",     # is_hidden
    "##### SPORTS #####",   # a TREX section header, not a channel
    "US| NO URL SPORT",     # nothing to play
])
def test_the_existing_gates_still_hold(db, excluded):
    _seed(db, _ROWS)
    with db.session_scope(commit=False) as session:
        names = {c.name for c in _repo(session).get_sports_channels(_ALL)}
    assert excluded not in names


def test_sport_and_league_filters_still_narrow(db):
    _seed(db, _ROWS)
    with db.session_scope(commit=False) as session:
        repo = _repo(session)
        assert {c.name for c in repo.get_sports_channels(_ALL, sport_types=["football"])} == {
            "US| NFL NETWORK", "TREX| ESPN"}
        assert {c.name for c in repo.get_sports_channels(_ALL, league_names=["NBA"])} == {
            "US| NBA TV"}


# --------------------------------------------------------------------------
# Crossing the session boundary
# --------------------------------------------------------------------------

def test_rows_survive_their_session(db):
    """An ORM object here raises DetachedInstanceError on the main thread —
    which is exactly where these rows are read."""
    _seed(db, _ROWS)
    with db.session_scope(commit=False) as session:
        rows = _repo(session).get_sports_channels(_ALL)
        events = _repo(session).get_events_channels(_ALL)
    # Session closed. Every attribute must still be readable.
    assert all(isinstance(r, SpecialContentDTO) for r in rows)
    for row in rows + events:
        assert row.id and row.name
        _ = (row.sport_type, row.league_name, row.team_name,
             row.detected_quality, row.is_favorite, row.event_start_time)


def test_the_events_bucket_is_a_parameter_not_a_second_method(db):
    """Settled by the mockup: ONE Events view with a scope switch over
    live_event and ppv, because the rows are the same shape and the difference
    is a stored enum."""
    _seed(db, _ROWS)
    with db.session_scope(commit=False) as session:
        repo = _repo(session)
        assert {c.name for c in repo.get_events_channels(_ALL)} == {"Some Event"}
        assert {c.name for c in repo.get_events_channels(_ALL, "ppv")} == {
            "Big Fight Tonight"}


def test_the_filter_has_exactly_one_definition():
    """Four copies is how one of them came to miss the provider axis."""
    from pathlib import Path

    import metatv.core.repositories.channel_stats as mod

    source = Path(mod.__file__).read_text()
    assert source.count("ChannelDB.special_view ==") == 1, (
        "the special_view filter is written more than once — call "
        "_special_content_query instead")
