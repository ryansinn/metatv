"""Recommendations obey every exclusion axis, not four of them.

``VisibilityScope`` is the single definition of "which channels are visible",
and the rule about it holds: an axis is added to the SCOPE so every surface
gets it at once, never to one caller. What did not hold is that
``score_candidates`` then filled only PART of that scope — provider ids,
prefixes, uncategorized and keywords — and left the rest at their permissive
defaults. That is the same bug wearing the chokepoint's clothes.

The worst of the four was adult. ``build_adult_filter`` was never called on the
Recommended path at all, so ``adult_mode`` reached the query as ``"all"`` and
the filter that governs the channel list, Discover and the tag counts did not
govern Recommendations.

Each test here asserts the pair — present WITHOUT the axis, absent WITH it —
because "not in the results" is also what a candidate that never qualified
looks like, and that proves nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from metatv.core.database import (
    ChannelDB, ContentTagDB, Database, MetadataDB, TagDB, UserRatingDB,
)
from metatv.core.preference_engine import compute_weights, score_candidates


@pytest.fixture
def file_db(tmp_path: Path):
    """File-backed, not ``:memory:`` — pooled connections must share tables."""
    db = Database(f"sqlite:///{tmp_path / 'rec_excl.db'}")
    db.create_tables()
    yield db
    db.close()


def _seed(session, **channel_kwargs) -> str:
    """A liked Drama title plus one unwatched Drama candidate; return its id.

    The like is what produces taste weights — without it ``compute_weights``
    is empty and ``score_candidates`` returns nothing, so every assertion
    below would pass for the wrong reason.
    """
    meta = MetadataDB(id=str(uuid.uuid4()), title="Great Drama", genres=["Drama"])
    session.add(meta)
    session.flush()

    liked = ChannelDB(
        id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id="p1",
        name="EN - Great Drama (2019)", media_type="movie",
        metadata_id=meta.id, last_played=datetime(2024, 1, 1),
    )
    session.add(liked)
    session.flush()
    session.add(UserRatingDB(channel_id=liked.id, rating=1))

    candidate_id = str(uuid.uuid4())
    session.add(ChannelDB(
        id=candidate_id, source_id=str(uuid.uuid4()), provider_id="p1",
        name="EN - Another Drama Film", detected_title="Another Drama Film",
        media_type="movie", metadata_id=meta.id, detected_prefix="EN",
        **channel_kwargs,
    ))
    return candidate_id


def _ids(session, **kwargs) -> set[str]:
    weights = compute_weights(session)
    assert not weights.is_empty(), "sanity: the liked title produced taste weights"
    return {sc.channel_id for sc in score_candidates(session, weights, limit=30, **kwargs)}


def test_adult_mode_reaches_recommendations(file_db):
    """The leak that mattered: adult content in the rail with the filter on."""
    with file_db.session_scope() as session:
        adult_id = _seed(session, is_adult=True)

    with file_db.session_scope(commit=False) as session:
        permissive = _ids(session, adult_mode="all")
        hidden = _ids(session, adult_mode="hide")

    assert adult_id in permissive, "sanity: the candidate qualifies without the axis"
    assert adult_id not in hidden, (
        "an adult title reached Recommendations with the adult filter on"
    )


def test_a_force_adult_source_is_hidden_too(file_db):
    """A provider whose whole catalogue is adult — the axis's second half."""
    with file_db.session_scope() as session:
        candidate_id = _seed(session)

    with file_db.session_scope(commit=False) as session:
        permissive = _ids(session, adult_mode="hide")
        forced = _ids(session, adult_mode="hide", force_adult_provider_ids=["p1"])

    assert candidate_id in permissive, "sanity: not adult on its own"
    assert candidate_id not in forced, (
        "a title from a force-adult source reached Recommendations"
    )


def test_content_type_exclusions_reach_recommendations(file_db):
    """The AI-provenance layer, which Discover applies and this did not.

    A content_type is a TAG, not a column — the axis is a correlated NOT EXISTS
    over ``content_tags JOIN tags`` — so the fixture has to tag the row rather
    than set a field on it.
    """
    with file_db.session_scope() as session:
        ai_id = _seed(session)
        tag = TagDB(type="content_type", value="ai")
        session.add(tag)
        session.flush()
        session.add(ContentTagDB(channel_id=ai_id, tag_id=tag.id,
                                 source="generated"))

    with file_db.session_scope(commit=False) as session:
        without = _ids(session)
        with_axis = _ids(session, excluded_content_types=["ai"])

    assert ai_id in without, "sanity: present without the axis"
    assert ai_id not in with_axis, "AI content reached Recommendations"


def test_category_exclusions_reach_recommendations(file_db):
    with file_db.session_scope() as session:
        candidate_id = _seed(session, user_category="Sports")

    with file_db.session_scope(commit=False) as session:
        without = _ids(session)
        with_axis = _ids(session, excluded_categories={"Sports"})

    assert candidate_id in without, "sanity: present without the axis"
    assert candidate_id not in with_axis, "an excluded category reached Recommendations"


def test_the_defaults_change_nothing_for_existing_callers(file_db):
    """Every new parameter is permissive by default.

    Three production call sites and seven test files call this function; a new
    axis that filtered by default would silently empty their results.
    """
    with file_db.session_scope() as session:
        candidate_id = _seed(session)

    with file_db.session_scope(commit=False) as session:
        assert candidate_id in _ids(session)


def test_the_sidebar_resolves_every_axis_it_passes():
    """The engine can only apply what the caller resolves.

    The Recommended section resolved ONE of the four — and this is the half a
    query-level test cannot see, because the engine looks correct while the
    caller hands it nothing.
    """
    import inspect

    from metatv.gui.sidebar import recommended

    source = inspect.getsource(recommended)
    for name in ("build_adult_filter", "excluded_tag_content_types",
                 "get_excluded_prefixes"):
        assert name in source, (
            f"the Recommended section never calls {name}, so that axis reaches "
            "the engine unset however complete the engine is"
        )
    for kwarg in ("adult_mode=", "force_adult_provider_ids=",
                  "excluded_content_types="):
        assert kwarg in source, f"{kwarg} is resolved but never passed"
