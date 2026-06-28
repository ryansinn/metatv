"""Regression tests for the anchored-facet query rewrite (perf/recipe-faceted-query-anchor).

The _faceted_channel_id_query() method was rewritten to anchor its driving
scan on the FIRST constrained include facet's tag membership rather than
enumerating the entire content_tags table.  The result set must be IDENTICAL
to the prior implementation — only the access path changed.

These tests execute the changed code path (real Database on tmp_path, not
:memory:) and assert the OUTCOME that would break if the anchor rewrite were
wrong.  Coverage:

  - Single include facet: returns exactly the channels carrying that tag.
  - Two include facets AND: only channels with BOTH (anchor + remaining EXISTS);
    a channel with only the anchor facet is EXCLUDED.
  - Include + exclude combination: the NOT EXISTS path drops the excluded channel
    while keeping the rest.
  - count_channels_by_tag_facets and sample_channels_by_tag_facets(limit=…)
    agree with get_channel_ids_by_tag_facets (same identities), including with
    collapse_variants=True.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    """Wipe the process-level tag-id cache between tests."""
    _clear_tag_cache()
    yield
    _clear_tag_cache()


@pytest.fixture
def file_db(tmp_path: Path):
    """File-backed SQLite Database (required — :memory: is connection-scoped)."""
    db_file = tmp_path / "test_anchor.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_channel(session, name: str, **kwargs) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id="prov_test",
            name=name,
            **kwargs,
        )
    )
    session.flush()
    return cid


def _ids(db, includes, excludes=None) -> set[str]:
    """Run get_channel_ids_by_tag_facets in a read-only scope."""
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        return repos.tags.get_channel_ids_by_tag_facets(includes, excludes)


def _count(db, includes, excludes=None, collapse_variants=False) -> int:
    """Run count_channels_by_tag_facets."""
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        return repos.tags.count_channels_by_tag_facets(
            includes, excludes, collapse_variants=collapse_variants
        )


def _sample_ids(db, includes, excludes=None, limit=100, collapse_variants=False) -> set[str]:
    """Run sample_channels_by_tag_facets and return the set of channel ids."""
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        cards = repos.tags.sample_channels_by_tag_facets(
            includes, excludes, limit=limit, collapse_variants=collapse_variants
        )
        return {c.channel_id for c in cards}


# ---------------------------------------------------------------------------
# Fixture: three channels with two facets to exercise anchor + remaining EXISTS
#
#   drama_action    — genre:Drama  AND  collection:Action  (has BOTH)
#   drama_only      — genre:Drama  (anchor facet only — must be EXCLUDED by AND)
#   action_only     — collection:Action (second facet only — not in anchor → excluded by anchor)
# ---------------------------------------------------------------------------


@pytest.fixture
def anchor_test_channels(file_db):
    """Seed three channels covering single-facet and two-facet AND cases."""
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)

        drama_action = _add_channel(session, "Drama Action Channel")
        repos.tags.set_content_tags(
            drama_action,
            [
                ("genre", "Drama", "feeder"),
                ("collection", "Action", "feeder"),
            ],
        )

        drama_only = _add_channel(session, "Drama Only Channel")
        repos.tags.set_content_tags(drama_only, [("genre", "Drama", "feeder")])

        action_only = _add_channel(session, "Action Only Channel")
        repos.tags.set_content_tags(action_only, [("collection", "Action", "feeder")])

    return drama_action, drama_only, action_only, file_db


# ---------------------------------------------------------------------------
# Single include facet — anchor path
# ---------------------------------------------------------------------------


class TestSingleFacetAnchor:
    """When there is exactly one constrained include facet the anchor IS that
    facet — the driving scan is bounded to its tag membership directly."""

    def test_single_facet_returns_only_matching_channels(self, anchor_test_channels):
        """genre:Drama → drama_action + drama_only; action_only is EXCLUDED."""
        da, do, ao, db = anchor_test_channels

        result = _ids(db, {"genre": {"Drama"}})

        assert da in result, "drama_action must be included (has genre:Drama)"
        assert do in result, "drama_only must be included (has genre:Drama)"
        assert ao not in result, "action_only must be EXCLUDED (no genre:Drama tag)"

    def test_single_facet_count_agrees_with_id_set(self, anchor_test_channels):
        """count_* and get_*_ids agree on the single-facet anchor path."""
        _da, _do, _ao, db = anchor_test_channels

        ids = _ids(db, {"genre": {"Drama"}})
        count = _count(db, {"genre": {"Drama"}})

        assert count == len(ids) == 2

    def test_single_facet_sample_ids_agree_with_id_set(self, anchor_test_channels):
        """sample_channels_by_tag_facets returns the same channels as get_*_ids."""
        da, do, ao, db = anchor_test_channels

        ids = _ids(db, {"genre": {"Drama"}})
        sample = _sample_ids(db, {"genre": {"Drama"}})

        assert sample == ids
        assert ao not in sample


# ---------------------------------------------------------------------------
# Two include facets AND — anchor + remaining correlated EXISTS
# ---------------------------------------------------------------------------


class TestTwoFacetAnd:
    """With two constrained facets, the anchor is the first; the second rides
    as a correlated EXISTS.  Only channels with BOTH tags pass.  A channel
    that has only the anchor facet must be EXCLUDED by the remaining EXISTS."""

    def test_two_facets_and_returns_only_both(self, anchor_test_channels):
        """genre:Drama AND collection:Action → only drama_action.

        drama_only has only the anchor facet (genre:Drama) but NOT
        collection:Action — the remaining EXISTS must EXCLUDE it.
        """
        da, do, ao, db = anchor_test_channels

        result = _ids(db, {"genre": {"Drama"}, "collection": {"Action"}})

        assert result == {da}, (
            "Only the channel with BOTH facets must be returned. "
            f"drama_only={do!r} should be EXCLUDED (anchor-only channel passes "
            "the anchor scan but must be dropped by the remaining EXISTS)."
        )

    def test_anchor_only_channel_is_excluded_by_remaining_exists(self, anchor_test_channels):
        """The key correctness assertion: drama_only carries the anchor tag
        (genre:Drama) but not the second tag (collection:Action), so it must
        not appear in the result of the two-facet AND query."""
        _da, do, _ao, db = anchor_test_channels

        result = _ids(db, {"genre": {"Drama"}, "collection": {"Action"}})

        assert do not in result, (
            f"drama_only ({do!r}) has only the anchor facet; "
            "the remaining EXISTS should have excluded it."
        )

    def test_two_facets_count_agrees_with_id_set(self, anchor_test_channels):
        """count_* and get_*_ids agree on the two-facet AND path."""
        _da, _do, _ao, db = anchor_test_channels

        ids = _ids(db, {"genre": {"Drama"}, "collection": {"Action"}})
        count = _count(db, {"genre": {"Drama"}, "collection": {"Action"}})

        assert count == len(ids) == 1

    def test_two_facets_sample_ids_agree(self, anchor_test_channels):
        """sample_channels_by_tag_facets returns the same result as get_*_ids."""
        da, _do, _ao, db = anchor_test_channels

        sample = _sample_ids(db, {"genre": {"Drama"}, "collection": {"Action"}})

        assert sample == {da}


# ---------------------------------------------------------------------------
# Include + exclude combination — NOT EXISTS path
# ---------------------------------------------------------------------------


class TestIncludeExcludeCombination:
    """Exclude facets use the NOT EXISTS block (unchanged by the rewrite).
    Verify the combined path still produces correct results."""

    def test_include_genre_exclude_collection_drops_drama_action(
        self, anchor_test_channels
    ):
        """genre:Drama included, collection:Action excluded.

        drama_action has BOTH → dropped by NOT EXISTS.
        drama_only has genre:Drama and NO collection:Action → kept.
        action_only has no genre:Drama → excluded by anchor.
        """
        da, do, ao, db = anchor_test_channels

        result = _ids(db, {"genre": {"Drama"}}, {"collection": {"Action"}})

        assert do in result, "drama_only must be kept (has Drama, no Action)"
        assert da not in result, "drama_action must be dropped (has Action tag → NOT EXISTS)"
        assert ao not in result, "action_only must be excluded (no Drama anchor)"

    def test_exclude_drops_channel_not_in_include_mismatch(self, anchor_test_channels):
        """Combining anchored include with exclude leaves exactly the right channel."""
        da, do, ao, db = anchor_test_channels

        result = _ids(db, {"genre": {"Drama"}}, excludes={"collection": {"Action"}})

        assert result == {do}

    def test_count_and_sample_agree_with_include_exclude(self, anchor_test_channels):
        """count_* and sample_* agree with get_*_ids on the combined path."""
        _da, do, _ao, db = anchor_test_channels

        ids = _ids(db, {"genre": {"Drama"}}, {"collection": {"Action"}})
        count = _count(db, {"genre": {"Drama"}}, {"collection": {"Action"}})
        sample = _sample_ids(db, {"genre": {"Drama"}}, {"collection": {"Action"}})

        assert count == len(ids) == 1
        assert sample == ids == {do}


# ---------------------------------------------------------------------------
# collapse_variants=True — count_* and sample_* agree with get_*_ids
# ---------------------------------------------------------------------------


class TestCollapseVariants:
    """collapse_variants groups same-content_key channels; the anchor rewrite
    must not break the collapsed count/sample path."""

    @pytest.fixture
    def collapse_channels(self, file_db):
        """Seed two genre:Drama channels sharing a content_key (they collapse
        into one group) and one with a distinct key (remains separate)."""
        shared_key = "shared-drama|movie|2022"
        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)

            # Two variants sharing a content_key
            v1 = _add_channel(session, "Drama HD", content_key=shared_key)
            repos.tags.set_content_tags(v1, [("genre", "Drama", "f")])

            v2 = _add_channel(session, "Drama 4K", content_key=shared_key)
            repos.tags.set_content_tags(v2, [("genre", "Drama", "f")])

            # One standalone
            solo = _add_channel(session, "Drama Solo", content_key="solo|movie|2023")
            repos.tags.set_content_tags(solo, [("genre", "Drama", "f")])

        return v1, v2, solo, file_db

    def test_collapse_count_is_group_count_not_row_count(self, collapse_channels):
        """collapse_variants=True counts distinct content_key groups, not raw rows."""
        v1, v2, solo, db = collapse_channels

        raw_count = _count(db, {"genre": {"Drama"}}, collapse_variants=False)
        collapsed_count = _count(db, {"genre": {"Drama"}}, collapse_variants=True)

        assert raw_count == 3, "Three raw channels seeded"
        assert collapsed_count == 2, (
            "Two distinct content_key groups (the shared pair collapses to one)"
        )

    def test_collapse_sample_returns_one_representative_per_group(
        self, collapse_channels
    ):
        """sample_channels_by_tag_facets(collapse_variants=True) yields one card
        per content_key group — not one per raw channel."""
        v1, v2, solo, db = collapse_channels

        collapsed_cards = _sample_ids(db, {"genre": {"Drama"}}, collapse_variants=True)
        raw_cards = _sample_ids(db, {"genre": {"Drama"}}, collapse_variants=False)

        assert len(raw_cards) == 3
        assert len(collapsed_cards) == 2

        # The representative for the shared pair is one of v1 or v2.
        assert solo in collapsed_cards, "Solo channel must have a card"
        shared_rep = collapsed_cards - {solo}
        assert len(shared_rep) == 1
        assert shared_rep.issubset({v1, v2}), "The shared-pair representative must be v1 or v2"

    def test_collapse_count_and_sample_agree(self, collapse_channels):
        """Collapsed count == len(collapsed sample) (they use the same logic)."""
        _v1, _v2, _solo, db = collapse_channels

        count = _count(db, {"genre": {"Drama"}}, collapse_variants=True)
        sample = _sample_ids(db, {"genre": {"Drama"}}, collapse_variants=True, limit=50)

        assert count == len(sample) == 2


# ---------------------------------------------------------------------------
# No-facet baseline — empty includes → all channels returned
# ---------------------------------------------------------------------------


class TestEmptyIncludesBaseline:
    """When no include facets are constrained the anchor branch takes the
    else-path (query = session.query(outer.channel_id).distinct()), which is
    the same as the original full-table scan.  Correctness must be preserved."""

    def test_empty_includes_returns_all_tagged_channels(self, anchor_test_channels):
        """No include constraints → all three seeded channels."""
        da, do, ao, db = anchor_test_channels

        result = _ids(db, {})

        assert result == {da, do, ao}

    def test_empty_includes_excludes_still_work(self, anchor_test_channels):
        """Excludes still drop channels when there are no include constraints."""
        da, do, ao, db = anchor_test_channels

        # Exclude collection:Action → drops drama_action and action_only
        result = _ids(db, {}, {"collection": {"Action"}})

        assert result == {do}
