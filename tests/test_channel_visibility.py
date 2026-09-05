"""Proves ``metatv.core.channel_visibility`` is a faithful extraction.

This is a PURE REFACTOR slice (see PR description): ``channel_visibility.py``
is the new single definition of "which channels are visible", and
``ChannelRepository._apply_channel_filters`` is migrated onto it. No
call-site behavior may change.

Two kinds of proof:

(a) **Migrated axes** (``excluded_provider_ids`` / ``include_hidden`` /
    ``excluded_keywords`` / ``adult_mode`` + ``force_adult_provider_ids``) —
    ``_reference_pre_refactor_filters`` below is a literal transcription of
    the predicate blocks that used to live inline in
    ``ChannelRepository._apply_channel_filters`` *before* this slice moved
    them into ``channel_visibility.apply()`` (see git history / the PR diff
    for the pre-refactor source). For a matrix of scopes (each axis alone,
    combined, and the empty scope) the reference oracle and
    ``channel_visibility.apply()`` must return the identical channel-id set
    against the same seeded database. ``ChannelRepository.get_all()``
    (the actual migrated call site) is additionally exercised end-to-end for
    a representative subset to prove the full integration, not just the
    extracted function in isolation.

(b) **Provisioned axes** (``excluded_prefixes`` / ``excluded_categories`` /
    ``excluded_content_types`` / ``include_uncategorized``) — not used by
    ``_apply_channel_filters`` pre- or post-refactor (that method has no
    equivalent predicate to move), but required by the module's
    ``VisibilityScope`` schema for the follow-up migration slice
    (discovery_engine.py / preference_engine.py / tag.py). These are proven
    against the already-canonical ``filter_utils`` builders
    (``channel_exclusion_criterion`` / ``tag_content_type_exclusion_criterion``)
    that ``channel_visibility.apply()`` reuses, plus concrete seeded-row
    behavior (including the "language wins over region" edge case).

Real ``Database`` on a ``tmp_path`` file (never ``:memory:`` — project rule
for DB-session work).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import or_

from metatv.core.channel_visibility import VisibilityScope, apply as apply_visibility
from metatv.core.database import ChannelDB, Database
from metatv.core.filter_utils import keyword_exclusion_criterion
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.channel import ChannelRepository


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def file_db(tmp_path: Path):
    db = Database(f"sqlite:///{tmp_path / 'channel_visibility.db'}")
    db.create_tables()
    yield db
    db.close()


def _add_channel(
    session,
    name: str,
    *,
    provider_id: str = "p1",
    is_hidden: bool = False,
    is_adult: bool = False,
    detected_restricted: bool = False,
    detected_prefix: str | None = None,
    detected_region: str | None = None,
    user_category: str | None = None,
    detected_title: str | None = None,
    media_type: str = "movie",
) -> str:
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            media_type=media_type,
            is_hidden=is_hidden,
            is_adult=is_adult,
            detected_restricted=detected_restricted,
            detected_prefix=detected_prefix,
            detected_region=detected_region,
            user_category=user_category,
            detected_title=detected_title,
        )
    )
    session.flush()
    return cid


@pytest.fixture
def seeded(file_db):
    """A representative channel set covering every migrated + provisioned axis.

    Returns a dict of channel_id keyed by short name, plus the ``Database``.
    """
    ids: dict[str, str] = {}
    with file_db.session_scope() as session:
        ids["visible"] = _add_channel(session, "EN - Plain Movie")
        ids["hidden"] = _add_channel(session, "EN - Hidden Movie", is_hidden=True)
        ids["other_provider"] = _add_channel(session, "EN - Other Provider", provider_id="p2")
        ids["is_adult_flag"] = _add_channel(session, "EN - Adult Flagged", is_adult=True)
        ids["detected_restricted"] = _add_channel(
            session, "XXX - Restricted Name", detected_restricted=True
        )
        ids["force_adult_provider"] = _add_channel(
            session, "EN - Force Adult Provider", provider_id="p3"
        )
        ids["wrestling_kw"] = _add_channel(
            session, "EN - WWE Wrestling Special", detected_title="WWE Wrestling Special"
        )
        ids["has_prefix_en"] = _add_channel(session, "EN - Has Prefix", detected_prefix="EN")
        ids["has_prefix_fr_region_de"] = _add_channel(
            session, "FR movie tagged DE region",
            detected_prefix="FR", detected_region="DE",
        )
        ids["no_prefix_region_de"] = _add_channel(
            session, "No-prefix movie tagged DE region",
            detected_prefix=None, detected_region="DE",
        )
        ids["no_prefix_no_region"] = _add_channel(session, "Fully untagged movie")
        ids["category_sports"] = _add_channel(
            session, "EN - Sports Category", user_category="Sports"
        )
        ids["category_none"] = _add_channel(session, "EN - No Category")
    return ids, file_db


def _ids(rows) -> set[str]:
    return {r.id for r in rows}


# ---------------------------------------------------------------------------
# (a) Migrated axes — reference oracle == channel_visibility.apply()
# ---------------------------------------------------------------------------


def _reference_pre_refactor_filters(
    query,
    *,
    excluded_provider_ids=None,
    include_hidden: bool = False,
    excluded_keywords=None,
    adult_mode: str = "all",
    force_adult_provider_ids=None,
):
    """Literal transcription of the pre-refactor inline predicate blocks that
    used to live in ``ChannelRepository._apply_channel_filters`` (before this
    slice moved them into ``channel_visibility.apply()``). Deliberately NOT
    implemented by calling ``channel_visibility`` — an independent oracle so a
    regression introduced while moving the code would actually be caught.
    """
    if excluded_provider_ids:
        query = query.filter(~ChannelDB.provider_id.in_(excluded_provider_ids))

    if not include_hidden:
        query = query.filter_by(is_hidden=False)

    if excluded_keywords:
        query = query.filter(keyword_exclusion_criterion(excluded_keywords, ChannelDB))

    if adult_mode != "all":
        force_ids = force_adult_provider_ids or []
        restricted_expr = or_(
            ChannelDB.is_adult == True,  # noqa: E712
            ChannelDB.detected_restricted == True,  # noqa: E712
        )
        if force_ids:
            restricted_expr = or_(restricted_expr, ChannelDB.provider_id.in_(force_ids))
        if adult_mode == "hide":
            query = query.filter(~restricted_expr)
        elif adult_mode == "only":
            query = query.filter(restricted_expr)

    return query


# Matrix: (kwargs to build BOTH the oracle call and the VisibilityScope)
MIGRATED_AXES_MATRIX = [
    {},  # empty scope
    {"excluded_provider_ids": ["p2"]},
    {"include_hidden": True},
    {"excluded_keywords": {"wrestling"}},
    {"adult_mode": "hide"},
    {"adult_mode": "only"},
    {"adult_mode": "hide", "force_adult_provider_ids": ["p3"]},
    {"adult_mode": "only", "force_adult_provider_ids": ["p3"]},
    # combined
    {
        "excluded_provider_ids": ["p2"],
        "excluded_keywords": {"wrestling"},
        "adult_mode": "hide",
        "force_adult_provider_ids": ["p3"],
    },
    {
        "include_hidden": True,
        "excluded_provider_ids": ["p2"],
        "adult_mode": "only",
        "force_adult_provider_ids": ["p3"],
    },
]


@pytest.mark.parametrize("kwargs", MIGRATED_AXES_MATRIX)
def test_migrated_axes_match_pre_refactor_oracle(seeded, kwargs):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        oracle_rows = _reference_pre_refactor_filters(
            session.query(ChannelDB), **kwargs
        ).all()
        scope = VisibilityScope(
            excluded_provider_ids=list(kwargs.get("excluded_provider_ids") or []),
            include_hidden=bool(kwargs.get("include_hidden", False)),
            excluded_keywords=set(kwargs.get("excluded_keywords") or []),
            adult_mode=kwargs.get("adult_mode", "all"),
            force_adult_provider_ids=list(kwargs.get("force_adult_provider_ids") or []),
        )
        refactored_rows = apply_visibility(session.query(ChannelDB), scope).all()

        assert _ids(oracle_rows) == _ids(refactored_rows), (
            f"channel_visibility.apply() diverged from the pre-refactor oracle "
            f"for kwargs={kwargs}"
        )


def test_migrated_axes_actually_discriminate(seeded):
    """Sanity guard: the matrix must contain scopes that produce DIFFERENT
    result sets, or the equality assertions in
    ``test_migrated_axes_match_pre_refactor_oracle`` would trivially pass even
    for a broken extraction (e.g. an ``apply()`` that always returns
    everything, or always returns nothing).
    """
    ids, db = seeded
    result_sets = []
    with db.session_scope(commit=False) as session:
        for kwargs in MIGRATED_AXES_MATRIX:
            scope = VisibilityScope(
                excluded_provider_ids=list(kwargs.get("excluded_provider_ids") or []),
                include_hidden=bool(kwargs.get("include_hidden", False)),
                excluded_keywords=set(kwargs.get("excluded_keywords") or []),
                adult_mode=kwargs.get("adult_mode", "all"),
                force_adult_provider_ids=list(kwargs.get("force_adult_provider_ids") or []),
            )
            rows = apply_visibility(session.query(ChannelDB), scope).all()
            result_sets.append(frozenset(_ids(rows)))
    distinct = set(result_sets)
    assert len(distinct) > 1, "matrix scopes must produce more than one distinct result set"


# ---------------------------------------------------------------------------
# (a-cont'd) End-to-end through the actual migrated call site: get_all()
# ---------------------------------------------------------------------------


def test_get_all_excludes_hidden_by_default(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repo = ChannelRepository(session)
        result_ids = {c.id for c in repo.get_all()}
    assert ids["hidden"] not in result_ids
    assert ids["visible"] in result_ids


def test_get_all_include_hidden_reveals_hidden_channel(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repo = ChannelRepository(session)
        result_ids = {c.id for c in repo.get_all(include_hidden=True)}
    assert ids["hidden"] in result_ids


def test_get_all_excluded_provider_ids_drops_that_providers_channels(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repo = ChannelRepository(session)
        result_ids = {c.id for c in repo.get_all(excluded_provider_ids=["p2"])}
    assert ids["other_provider"] not in result_ids
    assert ids["visible"] in result_ids


def test_get_all_excluded_keywords_drops_matching_title(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repo = ChannelRepository(session)
        result_ids = {c.id for c in repo.get_all(excluded_keywords=["wrestling"])}
    assert ids["wrestling_kw"] not in result_ids
    assert ids["visible"] in result_ids


def test_get_all_adult_mode_hide_drops_restricted_channels(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repo = ChannelRepository(session)
        result_ids = {c.id for c in repo.get_all(adult_mode="hide")}
    assert ids["is_adult_flag"] not in result_ids
    assert ids["detected_restricted"] not in result_ids
    assert ids["visible"] in result_ids


def test_get_all_adult_mode_hide_with_force_provider_drops_that_providers_channels(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repo = ChannelRepository(session)
        result_ids = {
            c.id for c in repo.get_all(
                adult_mode="hide", force_adult_provider_ids=["p3"],
            )
        }
    assert ids["force_adult_provider"] not in result_ids
    assert ids["visible"] in result_ids


def test_get_all_adult_mode_only_shows_only_restricted_channels(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repo = ChannelRepository(session)
        result_ids = {c.id for c in repo.get_all(adult_mode="only")}
    assert ids["is_adult_flag"] in result_ids
    assert ids["detected_restricted"] in result_ids
    assert ids["visible"] not in result_ids


def test_get_all_combined_visibility_axes(seeded):
    """All four migrated axes together, through the real ChannelRepository.get_all()."""
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repo = ChannelRepository(session)
        result_ids = {
            c.id for c in repo.get_all(
                excluded_provider_ids=["p2"],
                excluded_keywords=["wrestling"],
                adult_mode="hide",
                force_adult_provider_ids=["p3"],
            )
        }
    assert ids["visible"] in result_ids
    assert ids["other_provider"] not in result_ids
    assert ids["wrestling_kw"] not in result_ids
    assert ids["is_adult_flag"] not in result_ids
    assert ids["detected_restricted"] not in result_ids
    assert ids["force_adult_provider"] not in result_ids
    assert ids["hidden"] not in result_ids  # default gate still applies


# ---------------------------------------------------------------------------
# (b) Provisioned axes — not migrated (no _apply_channel_filters predicate to
# move), proven against the already-canonical filter_utils builders that
# channel_visibility.apply() reuses.
# ---------------------------------------------------------------------------


def test_excluded_prefixes_language_wins_over_region(seeded):
    """A channel WITH a prefix is judged on the prefix alone — an excluded
    region tag never hides it if its own prefix isn't excluded. A channel
    with NO prefix falls back to its region. Mirrors
    filter_utils.channel_exclusion_criterion's documented contract.
    """
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        scope = VisibilityScope(excluded_prefixes={"DE"})
        result_ids = _ids(apply_visibility(session.query(ChannelDB), scope).all())

    # FR-prefixed channel tagged region=DE: prefix (FR, not excluded) wins — kept.
    assert ids["has_prefix_fr_region_de"] in result_ids
    # No-prefix channel tagged region=DE: region fallback applies — excluded.
    assert ids["no_prefix_region_de"] not in result_ids
    # Fully untagged channel: no prefix, no region — always kept (nothing to match).
    assert ids["no_prefix_no_region"] in result_ids


def test_excluded_prefixes_empty_is_noop(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        scope = VisibilityScope()  # excluded_prefixes empty by default
        # NOTE: include_hidden also defaults False (its own, non-empty-set gate),
        # so the "no other axis filters anything" baseline is visible-only, not
        # every row in the table.
        visible_ids = _ids(
            session.query(ChannelDB).filter(ChannelDB.is_hidden == False).all()  # noqa: E712
        )
        result_ids = _ids(apply_visibility(session.query(ChannelDB), scope).all())
    assert result_ids == visible_ids


def test_include_uncategorized_false_drops_untagged_channels(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        scope = VisibilityScope(include_uncategorized=False)
        result_ids = _ids(apply_visibility(session.query(ChannelDB), scope).all())
    assert ids["no_prefix_no_region"] not in result_ids
    assert ids["no_prefix_region_de"] not in result_ids
    assert ids["has_prefix_en"] in result_ids


def test_excluded_categories_drops_matching_user_category(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        scope = VisibilityScope(excluded_categories={"Sports"})
        result_ids = _ids(apply_visibility(session.query(ChannelDB), scope).all())
    assert ids["category_sports"] not in result_ids
    assert ids["category_none"] in result_ids  # NULL category never dropped


def test_excluded_content_types_drops_tagged_channel(file_db):
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)
        ai_id = _add_channel(session, "AI Generated Movie")
        plain_id = _add_channel(session, "Ordinary Movie")
        repos.tags.set_content_tags(ai_id, [("content_type", "ai_generated", "test")])

    with file_db.session_scope(commit=False) as session:
        scope = VisibilityScope(excluded_content_types={"ai_generated"})
        result_ids = _ids(apply_visibility(session.query(ChannelDB), scope).all())
    assert ai_id not in result_ids
    assert plain_id in result_ids


def test_provisioned_axes_default_to_noop(seeded):
    """Every provisioned-but-unmigrated field defaults to a no-op — a caller
    that only sets the migrated fields sees the full unfiltered-by-those-axes
    result (proves 'safe empty default' from the module docstring)."""
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        all_visible_ids = _ids(
            session.query(ChannelDB).filter(ChannelDB.is_hidden == False).all()  # noqa: E712
        )
        scope = VisibilityScope()
        result_ids = _ids(apply_visibility(session.query(ChannelDB), scope).all())
    assert result_ids == all_visible_ids


# ---------------------------------------------------------------------------
# channel_cls override — the module must not hardcode ChannelDB internally
# ---------------------------------------------------------------------------


def test_apply_accepts_channel_cls_override(seeded):
    """apply() must work through an aliased ChannelDB, not just the bare class
    (a requirement for future callers that alias ChannelDB in a join)."""
    from sqlalchemy.orm import aliased

    ids, db = seeded
    with db.session_scope(commit=False) as session:
        aliased_ch = aliased(ChannelDB, flat=True)
        query = session.query(aliased_ch)
        scope = VisibilityScope(excluded_provider_ids=["p2"])
        result_ids = _ids(apply_visibility(query, scope, channel_cls=aliased_ch).all())
    assert ids["other_provider"] not in result_ids
    assert ids["visible"] in result_ids


# ---------------------------------------------------------------------------
# VE-1 — the dead-signal-streak axis (the "hide dead events" setting)
# ---------------------------------------------------------------------------

def _add_streak_channels(session) -> dict[str, str]:
    """Three live channels: streak 0, 2 and 5 (the column is NOT NULL, default 0)."""
    ids = {}
    for key, streak in (("s0", 0), ("s2", 2), ("s5", 5)):
        cid = _add_channel(session, f"EN - Event {key}", media_type="live")
        ch = session.get(ChannelDB, cid)
        ch.signal_dead_streak = streak
        ids[key] = cid
    session.flush()
    return ids


def test_dead_signal_axis_excludes_only_rows_at_or_past_the_floor(file_db):
    """VE-1: floor 3 hides the streak-5 channel and nothing else; floor None
    = the axis is off."""
    with file_db.session_scope() as session:
        ids = _add_streak_channels(session)
        base = session.query(ChannelDB)

        on = apply_visibility(base, VisibilityScope(dead_signal_streak_floor=3),
                              channel_cls=ChannelDB)
        visible = {r.id for r in on.all()}
        assert ids["s5"] not in visible, "streak 5 must be hidden at floor 3"
        assert {ids["s0"], ids["s2"]} <= visible

        off = apply_visibility(base, VisibilityScope(dead_signal_streak_floor=None),
                               channel_cls=ChannelDB)
        assert set(ids.values()) <= {r.id for r in off.all()}


def test_get_all_threads_the_dead_signal_floor(file_db):
    """The channel-list path (``get_all``) carries the axis end to end."""
    with file_db.session_scope() as session:
        ids = _add_streak_channels(session)
        repo = ChannelRepository(session)
        names_hidden = {c.id for c in repo.get_all(dead_signal_streak_floor=3)}
        names_all = {c.id for c in repo.get_all()}
        assert ids["s5"] not in names_hidden
        assert ids["s5"] in names_all
        assert names_all - names_hidden == {ids["s5"]}


def test_dead_signal_floor_resolves_from_the_two_settings():
    """``hide_dead_events`` is the switch; ``signal_dead_streak_to_hide`` the N."""
    from types import SimpleNamespace

    from metatv.core.visibility_resolver import dead_signal_streak_floor

    assert dead_signal_streak_floor(
        SimpleNamespace(hide_dead_events=False, signal_dead_streak_to_hide=3)) is None
    assert dead_signal_streak_floor(
        SimpleNamespace(hide_dead_events=True, signal_dead_streak_to_hide=3)) == 3
