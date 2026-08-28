"""The "N hidden because watched" count must obey the axes the list obeyed.

``count_watched_matching`` hand-listed 23 parameters and forwarded 26, and its
caller in ``main_window_channels`` hand-listed 22 more to feed it — three
enumerations of one axis set kept in step by memory.  They had drifted:
``channel_ids``, ``excluded_keywords`` and ``include_dead`` reached ``get_all``
and never reached the count, so a watched row the list had dropped for some
OTHER reason was still reported as "hidden because watched".

The count now forwards by derivation from ``_apply_channel_filters``'s own
signature, so a newly added axis reaches it without anyone remembering.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.channel import (
    _COUNT_WATCHED_IGNORED,
    _COUNT_WATCHED_OMITS,
    _apply_channel_filters_axes,
)
from tests.conftest import make_channel


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database — a real file, never :memory: (CLAUDE.md)."""
    d = Database(f"sqlite:///{tmp_path / 'watched_axes.db'}")
    d.create_tables()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# The drift guard — derived, not hand-listed
# ---------------------------------------------------------------------------


def test_every_sql_axis_is_forwarded_or_explicitly_omitted():
    """A new axis on _apply_channel_filters must reach the count, or say why not.

    This is the guard the three hand-copies never had.  It fails the suite on a
    newly added axis rather than letting the count quietly disagree with the
    list — the enumeration failure CLAUDE.md names.
    """
    axes = _apply_channel_filters_axes()
    unaccounted = axes - _COUNT_WATCHED_OMITS
    # Everything not omitted is forwarded verbatim, so the only thing to assert
    # is that the omit list names real axes and stays small and justified.
    assert _COUNT_WATCHED_OMITS <= axes, (
        f"_COUNT_WATCHED_OMITS names axes _apply_channel_filters does not "
        f"accept: {sorted(_COUNT_WATCHED_OMITS - axes)}"
    )
    assert unaccounted, "sanity: the count must forward something"
    # The three that had gone missing are now in the forwarded set.
    for axis in ("channel_ids", "excluded_keywords", "include_dead"):
        assert axis in unaccounted, f"{axis} is silently dropped again"


def test_ignored_axes_are_disjoint_from_forwarded_ones():
    """A Python-side axis must not also be claimed as SQL-forwarded."""
    assert not (_COUNT_WATCHED_IGNORED & _apply_channel_filters_axes()), (
        "an axis cannot be both forwarded to SQL and knowingly skipped: "
        f"{sorted(_COUNT_WATCHED_IGNORED & _apply_channel_filters_axes())}"
    )


def test_an_unknown_axis_raises_rather_than_being_swallowed(db):
    """**axes must not silently absorb a typo — that is how drift hides."""
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        with pytest.raises(TypeError, match="unexpected axis"):
            repos.channels.count_watched_matching(exclude_wathced=True)


# ---------------------------------------------------------------------------
# The behaviour the drift broke
# ---------------------------------------------------------------------------


def _watched(session, name: str, **kw) -> ChannelDB:
    return make_channel(session, name, media_type="movie", watch_completed=True, **kw)


def test_a_watched_row_excluded_by_keyword_is_not_counted_as_watched_hidden(db):
    """The headline case: the list dropped it for a keyword, not for being watched."""
    with db.session_scope() as session:
        _watched(session, "Keep This Film")
        _watched(session, "Some Trailer Film")   # 'trailer' is the excluded keyword

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        both = repos.channels.count_watched_matching(media_types=["movie"])
        filtered = repos.channels.count_watched_matching(
            media_types=["movie"], excluded_keywords=["trailer"]
        )

    assert both == 2, "precondition: both rows are watched and visible"
    assert filtered == 1, (
        "the keyword-excluded row was counted as 'hidden because watched', but "
        "the list had already dropped it for the keyword"
    )


def test_channel_ids_restriction_reaches_the_count(db):
    """A restricted id-set (alert 'show matches') must narrow the count too."""
    with db.session_scope() as session:
        a = _watched(session, "Alpha").id
        _watched(session, "Beta")

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        assert repos.channels.count_watched_matching(media_types=["movie"]) == 2
        assert repos.channels.count_watched_matching(
            media_types=["movie"], channel_ids={a}
        ) == 1


def test_the_caller_can_splat_its_whole_axis_dict(db):
    """Python-side axes are accepted and skipped, so **_axes works as-is."""
    with db.session_scope() as session:
        _watched(session, "Gamma")

    axes = {
        "media_types": ["movie"],
        "exclude_watched": True,      # omitted: this method narrows TO watched
        "limit": 5000,                # ignored: pagination
        "collapse_variants": True,    # ignored: applied in Python by get_all
        "excluded_prefixes": {"XX"},  # ignored: applied in Python by get_all
    }
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        assert repos.channels.count_watched_matching(**axes) == 1
