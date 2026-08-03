"""Proves the three remaining visibility engines were migrated onto the single
``metatv.core.channel_visibility`` chokepoint (the follow-up half of the
refactor started by ``channel_visibility.py`` / ``tests/test_channel_visibility.py``).

Covers:

1. ``discovery_engine.get_recently_added`` (exercises the migrated
   ``_apply_prefix_filter`` / ``_apply_content_type_exclusion`` /
   ``_apply_keyword_exclusion`` / ``_apply_adult_filter`` /
   ``_apply_provider_exclusion`` helpers in one query).
2. ``preference_engine.score_candidates`` (Recommendations) — the structural
   cause of the reported "Recommendations ignores global exclusions" bug: it
   used to call ``discovery_engine._apply_prefix_filter`` directly, so it
   inherited that helper's flat, non-canonical prefix check.
3. ``TagRepository.get_facet_value_counts`` / ``_scope_to_visible_channels``
   (the filter panel's facet counts) — closes the self-documented 3-axis gap
   (prefix / user-category / content-type) where the panel's counts used to
   disagree with what the corresponding filtered list actually returns.

Also pins the divergence-reconciliation decision made in this slice: the
canonical, region-aware ``filter_utils.channel_exclusion_criterion``
("language wins over region") now governs ALL THREE paths, replacing
``discovery_engine``'s old flat ``detected_prefix NOT IN (...)`` check that
never consulted ``detected_region`` for prefix-less channels. A channel with
NO ``detected_prefix`` but an excluded ``detected_region`` is now hidden on
all three surfaces; a channel WITH an un-excluded prefix stays visible even
when its (irrelevant) region tag is excluded.

Real ``Database`` on a ``tmp_path`` file (never ``:memory:`` — project rule
for DB-session work).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, MetadataDB, ProviderDB, UserRatingDB
from metatv.core.discovery_engine import get_recently_added
from metatv.core.preference_engine import compute_weights, score_candidates
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def file_db(tmp_path: Path):
    db = Database(f"sqlite:///{tmp_path / 'filter_paths_unified.db'}")
    db.create_tables()
    yield db
    db.close()


def _add_channel(
    session,
    name: str,
    *,
    provider_id: str = "prov_active",
    is_hidden: bool = False,
    is_adult: bool = False,
    detected_prefix: str | None = None,
    detected_region: str | None = None,
    user_category: str | None = None,
    detected_title: str | None = None,
    media_type: str = "movie",
    added: str = "1",
) -> str:
    """Create a ChannelDB row + a matching MetadataDB row (genre=Action) so
    every seeded channel is a valid preference-engine candidate."""
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    session.add(MetadataDB(id=mid, title=name, genres=["Action"], media_type=media_type))
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            media_type=media_type,
            is_hidden=is_hidden,
            is_adult=is_adult,
            detected_prefix=detected_prefix,
            detected_region=detected_region,
            user_category=user_category,
            detected_title=detected_title,
            metadata_id=mid,
            raw_data={"added": added, "rating": "7.0", "genre": "Action"},
        )
    )
    session.flush()
    return cid


@pytest.fixture
def seeded(file_db):
    """A representative channel set spanning every Global-Exclusion axis.

    Returns ``(ids, db)`` where ``ids`` maps short names to channel ids.
    """
    ids: dict[str, str] = {}
    with file_db.session_scope() as session:
        session.add(ProviderDB(id="prov_active", name="Active", type="xtream", url="http://x", is_active=True))
        session.add(ProviderDB(id="prov_hidden", name="Hidden", type="xtream", url="http://x", is_active=False))
        session.flush()

        ids["visible"] = _add_channel(session, "Visible Movie", added="1")
        ids["hidden_provider"] = _add_channel(
            session, "Hidden Provider Movie",
            provider_id="prov_hidden", added="2",
        )
        ids["excl_prefix"] = _add_channel(
            session, "Excluded Prefix Movie",
            detected_prefix="XX", added="3",
        )
        # No prefix, region-only tag matching the SAME excluded code as
        # excl_prefix — the "language wins over region" fallback case.
        ids["region_fallback"] = _add_channel(
            session, "Region Fallback Movie",
            detected_prefix=None, detected_region="XX", added="4",
        )
        # HAS an un-excluded prefix but its region tag IS excluded — must stay
        # visible (prefix wins over region).
        ids["prefix_wins"] = _add_channel(
            session, "Prefix Wins Movie",
            detected_prefix="EN", detected_region="XX", added="5",
        )
        ids["excl_category"] = _add_channel(
            session, "Excluded Category Movie",
            user_category="Sports", added="6",
        )
        ids["excl_content_type"] = _add_channel(
            session, "Excluded Content Type Movie", added="7",
        )
        ids["excl_keyword"] = _add_channel(
            session, "WWE Wrestling Special",
            detected_title="WWE Wrestling Special", added="8",
        )
        ids["restricted_adult"] = _add_channel(
            session, "Restricted Adult Movie",
            is_adult=True, added="9",
        )
        ids["liked_seed"] = _add_channel(
            session, "Liked Seed Movie", added="10",
        )

        repos = RepositoryFactory(session)
        repos.tags.set_content_tags(
            ids["excl_content_type"], [("content_type", "ai_generated", "test")]
        )
        # Genre tag on a subset — used by the tag.py facet-count tests.
        for key in ("visible", "excl_prefix", "excl_category", "excl_content_type", "hidden_provider"):
            repos.tags.set_content_tags(ids[key], [("genre", "Action", "test")])

        session.add(UserRatingDB(channel_id=ids["liked_seed"], rating=1))

    return ids, file_db


# ---------------------------------------------------------------------------
# 1) discovery_engine — get_recently_added exercises all migrated helpers
# ---------------------------------------------------------------------------


def test_discovery_engine_hidden_provider_never_shown(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        cards = get_recently_added(session, limit=50, excluded_provider_ids=["prov_hidden"])
    card_ids = {c.channel_id for c in cards}
    assert ids["hidden_provider"] not in card_ids
    assert ids["visible"] in card_ids


def test_discovery_engine_excludes_prefix_content_type_keyword_adult(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        cards = get_recently_added(
            session, limit=50,
            excluded_prefixes=["XX"], include_uncategorized=True,
            excluded_content_types={"ai_generated"},
            excluded_keywords=["wrestling"],
            adult_mode="hide",
            excluded_provider_ids=["prov_hidden"],
        )
    card_ids = {c.channel_id for c in cards}

    assert ids["visible"] in card_ids
    assert ids["hidden_provider"] not in card_ids  # absolute gate
    assert ids["excl_prefix"] not in card_ids
    assert ids["excl_content_type"] not in card_ids
    assert ids["excl_keyword"] not in card_ids
    assert ids["restricted_adult"] not in card_ids
    # user_category exclusion is NOT wired into any discovery_engine shelf
    # query (pre-existing, unchanged by this migration) — stays visible.
    assert ids["excl_category"] in card_ids


def test_discovery_engine_reconciles_prefix_region_divergence(seeded):
    """Pins the divergence-reconciliation decision (see module docstring):
    discovery_engine now uses the canonical, region-aware predicate instead
    of its old flat ``detected_prefix NOT IN (...)`` check. This assertion
    would FAIL against the pre-migration ``_apply_prefix_filter`` (which
    always showed prefix-less channels regardless of their region tag)."""
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        cards = get_recently_added(session, limit=50, excluded_prefixes=["XX"])
    card_ids = {c.channel_id for c in cards}

    # No prefix, region="XX" (excluded) → region fallback applies → hidden.
    assert ids["region_fallback"] not in card_ids
    # Prefix="EN" (not excluded), region="XX" (excluded) → prefix wins → shown.
    assert ids["prefix_wins"] in card_ids


# ---------------------------------------------------------------------------
# 2) preference_engine.score_candidates — Recommendations
# ---------------------------------------------------------------------------


def test_score_candidates_hidden_provider_never_shown(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        weights = compute_weights(session)
        recs = score_candidates(
            session, weights, limit=50, excluded_provider_ids=["prov_hidden"],
        )
    rec_ids = {r.channel_id for r in recs}
    assert ids["hidden_provider"] not in rec_ids
    assert ids["visible"] in rec_ids


def test_score_candidates_excludes_prefix_and_keyword(seeded):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        weights = compute_weights(session)
        recs = score_candidates(
            session, weights, limit=50,
            excluded_prefixes=["XX"], include_uncategorized=True,
            excluded_keywords=["wrestling"],
            excluded_provider_ids=["prov_hidden"],
        )
    rec_ids = {r.channel_id for r in recs}

    assert ids["visible"] in rec_ids
    assert ids["hidden_provider"] not in rec_ids  # absolute gate
    assert ids["excl_prefix"] not in rec_ids
    assert ids["excl_keyword"] not in rec_ids
    # content_type / user_category axes have no parameter on score_candidates
    # today (a separate, un-briefed gap — not addressed by this migration);
    # documented here so a future slice has a concrete regression baseline.
    assert ids["excl_content_type"] in rec_ids
    assert ids["excl_category"] in rec_ids


def test_score_candidates_reconciles_prefix_region_divergence(seeded):
    """Pins the SAME reconciliation for Recommendations: score_candidates used
    to call discovery_engine._apply_prefix_filter directly, inheriting its
    flat prefix-only check — this is the structural fix for the reported
    'Recommendations ignores global exclusions' bug. Would FAIL if
    score_candidates reverted to the old flat check (or to calling
    discovery_engine._apply_prefix_filter instead of channel_visibility.apply
    directly)."""
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        weights = compute_weights(session)
        recs = score_candidates(session, weights, limit=50, excluded_prefixes=["XX"])
    rec_ids = {r.channel_id for r in recs}

    assert ids["region_fallback"] not in rec_ids
    assert ids["prefix_wins"] in rec_ids


# ---------------------------------------------------------------------------
# 3) TagRepository — filter-panel facet counts vs. the actual filtered list
# ---------------------------------------------------------------------------


def test_facet_value_counts_gap_closed_matches_list(seeded):
    """The self-documented 3-axis gap (prefix / user-category / content-type)
    on ``get_facet_value_counts`` is closed: its counts now agree with
    ``get_channel_ids_by_tag_facets`` (the actual list) for the SAME scope.

    On the pre-fix tree ``get_facet_value_counts`` does not accept
    ``excluded_prefixes`` / ``excluded_categories`` / ``excluded_tag_content_types``
    at all, so this call raises ``TypeError`` there — the sharpest possible
    'fails on the pre-fix tree' signal.
    """
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        hidden_provider_ids = repos.providers.get_hidden_provider_ids()
        assert hidden_provider_ids == ["prov_hidden"]

        # Baseline: only the absolute hidden-provider gate applied. Five
        # channels carry the "genre":"Action" tag; one (hidden_provider) is
        # gated by the absolute provider rule, leaving four.
        baseline = repos.tags.get_facet_value_counts(excluded_provider_ids=hidden_provider_ids)
        assert baseline["genre"]["Action"] == 4

        scoped_counts = repos.tags.get_facet_value_counts(
            excluded_provider_ids=hidden_provider_ids,
            excluded_prefixes={"XX"},
            excluded_categories={"Sports"},
            excluded_tag_content_types={"ai_generated"},
        )
        scoped_list = repos.tags.get_channel_ids_by_tag_facets(
            includes={"genre": {"Action"}},
            excluded_provider_ids=hidden_provider_ids,
            excluded_prefixes={"XX"},
            excluded_categories={"Sports"},
            excluded_tag_content_types={"ai_generated"},
        )

    action_count = scoped_counts.get("genre", {}).get("Action", 0)
    assert action_count == 1
    assert action_count == len(scoped_list)
    assert scoped_list == {ids["visible"]}


@pytest.mark.parametrize(
    "axis_kwargs, dropped_key",
    [
        ({"excluded_prefixes": {"XX"}}, "excl_prefix"),
        ({"excluded_categories": {"Sports"}}, "excl_category"),
        ({"excluded_tag_content_types": {"ai_generated"}}, "excl_content_type"),
    ],
)
def test_facet_value_counts_each_axis_drops_only_its_own_channel(seeded, axis_kwargs, dropped_key):
    ids, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        hidden_provider_ids = repos.providers.get_hidden_provider_ids()

        counts = repos.tags.get_facet_value_counts(
            excluded_provider_ids=hidden_provider_ids, **axis_kwargs
        )
        list_ids = repos.tags.get_channel_ids_by_tag_facets(
            includes={"genre": {"Action"}},
            excluded_provider_ids=hidden_provider_ids,
            **axis_kwargs,
        )

    assert counts["genre"]["Action"] == 3
    assert counts["genre"]["Action"] == len(list_ids)
    assert ids[dropped_key] not in list_ids
    assert ids["visible"] in list_ids
