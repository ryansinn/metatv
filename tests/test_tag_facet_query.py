"""Behavioral tests for TagRepository.get_channel_ids_by_tag_facets (Tags Slice T3).

The method implements standard faceted search over content_tags:
  - Within a facet: OR (any matching value satisfies the facet)
  - Across facets: AND (every constrained facet must be satisfied)
  - Excludes: NOT (any channel carrying an excluded tag is dropped)
  - All filtering is done in SQL (EXISTS subqueries) — no Python-side
    materialisation, safe over 1M+ rows.

Coverage:
  - Headline case: platform:Disney+ with language unconstrained → only
    Disney+ channels, regardless of language (the whole point).
  - Cross-facet AND/intersection: language:English AND platform:Disney+ →
    only the English Disney+ channel.
  - OR within a single facet: language:{English, Spanish} → all three.
  - Excludes drop matching channels without touching the rest.
  - Empty includes + excludes → all channels.
  - base_channel_ids pre-filter scopes the result.
  - Non-existent tag value → empty set (not a crash).
  - Exclude of a non-existent tag is a no-op (not a crash).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_db(tmp_path: Path):
    """File-backed SQLite Database (required — :memory: gives each connection
    a separate empty DB, which breaks session_scope)."""
    db_file = tmp_path / "test_facets.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def three_channels(file_db):
    """Seed three canonical channels and return their ids.

    c1 — Disney+ English US movie (platform:Disney+, language:English, region:US)
    c2 — English non-Disney movie  (language:English)
    c3 — Spanish Disney movie       (platform:Disney+, language:Spanish)

    Returns:
        (c1_id, c2_id, c3_id, db)
    """
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)

        c1 = _add_channel(session, "Disney+ English US Movie")
        repos.tags.set_content_tags(
            c1,
            [
                ("platform", "Disney+", "test_feeder"),
                ("language", "English", "test_feeder"),
                ("region", "US", "test_feeder"),
            ],
        )

        c2 = _add_channel(session, "English Non-Disney Movie")
        repos.tags.set_content_tags(
            c2,
            [("language", "English", "test_feeder")],
        )

        c3 = _add_channel(session, "Spanish Disney Movie")
        repos.tags.set_content_tags(
            c3,
            [
                ("platform", "Disney+", "test_feeder"),
                ("language", "Spanish", "test_feeder"),
            ],
        )

    return c1, c2, c3, file_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_channel(session, name: str) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id="test_provider",
            name=name,
        )
    )
    session.flush()
    return cid


def _query(db, includes, excludes=None, base_channel_ids=None) -> set[str]:
    """Run get_channel_ids_by_tag_facets inside a read-only session_scope."""
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        return repos.tags.get_channel_ids_by_tag_facets(
            includes,
            excludes,
            base_channel_ids=base_channel_ids,
        )


# ---------------------------------------------------------------------------
# Platform-only (headline case)
# ---------------------------------------------------------------------------


class TestPlatformFacetNoLanguageConstraint:
    """The headline Disney+ case: platform constrained, language unconstrained.

    A plain prefix-union model cannot express this (it returns the union of all
    Disney+ prefixes AND all English-language prefixes, which is too broad).
    The faceted engine returns exactly the Disney+ channels regardless of
    language.
    """

    def test_disney_plus_returns_both_disney_channels_not_plain_english(
        self, three_channels
    ):
        c1, c2, c3, db = three_channels

        result = _query(db, {"platform": {"Disney+"}})

        assert c1 in result, "Disney+ English US channel must be included"
        assert c3 in result, "Disney+ Spanish channel must be included"
        assert c2 not in result, "Plain-English (non-Disney+) channel must be excluded"
        assert len(result) == 2

    def test_unknown_platform_returns_empty_set(self, three_channels):
        """A platform value not present in the DB → empty (not a crash)."""
        _c1, _c2, _c3, db = three_channels

        result = _query(db, {"platform": {"Netflix"}})

        assert result == set()


# ---------------------------------------------------------------------------
# Cross-facet AND (intersection)
# ---------------------------------------------------------------------------


class TestCrossFacetAnd:
    def test_english_and_disney_plus_returns_only_c1(self, three_channels):
        """language:English AND platform:Disney+ → only the English Disney+ channel."""
        c1, c2, c3, db = three_channels

        result = _query(db, {"language": {"English"}, "platform": {"Disney+"}})

        assert result == {c1}

    def test_three_facets_returns_only_exact_match(self, three_channels):
        """platform:Disney+ AND language:English AND region:US → only c1."""
        c1, c2, c3, db = three_channels

        result = _query(
            db,
            {"platform": {"Disney+"}, "language": {"English"}, "region": {"US"}},
        )

        assert result == {c1}

    def test_region_us_no_spanish_disney_because_no_us_tag(self, three_channels):
        """c3 has no region:US tag, so platform:Disney+ AND region:US excludes it."""
        c1, c2, c3, db = three_channels

        result = _query(db, {"platform": {"Disney+"}, "region": {"US"}})

        assert c1 in result
        assert c3 not in result
        assert c2 not in result


# ---------------------------------------------------------------------------
# OR within a single facet
# ---------------------------------------------------------------------------


class TestOrWithinFacet:
    def test_english_or_spanish_returns_all_three(self, three_channels):
        """language:{English, Spanish} matches every channel that has either."""
        c1, c2, c3, db = three_channels

        result = _query(db, {"language": {"English", "Spanish"}})

        assert result == {c1, c2, c3}

    def test_english_only_returns_c1_and_c2(self, three_channels):
        """language:{English} → the two English channels only."""
        c1, c2, c3, db = three_channels

        result = _query(db, {"language": {"English"}})

        assert result == {c1, c2}
        assert c3 not in result


# ---------------------------------------------------------------------------
# Excludes
# ---------------------------------------------------------------------------


class TestExcludes:
    def test_exclude_spanish_drops_c3(self, three_channels):
        """Excluding language:Spanish removes c3 from an otherwise unrestricted set."""
        c1, c2, c3, db = three_channels

        result = _query(db, {}, {"language": {"Spanish"}})

        assert c1 in result
        assert c2 in result
        assert c3 not in result

    def test_exclude_disney_plus_drops_c1_and_c3(self, three_channels):
        """Excluding platform:Disney+ leaves only c2."""
        c1, c2, c3, db = three_channels

        result = _query(db, {}, {"platform": {"Disney+"}})

        assert result == {c2}

    def test_include_english_exclude_disney_returns_c2_only(self, three_channels):
        """language:English included AND platform:Disney+ excluded → c2 only.

        c1 is English but also Disney+ → excluded.
        c2 is English and not Disney+ → included.
        c3 is not English → not in the include set.
        """
        c1, c2, c3, db = three_channels

        result = _query(db, {"language": {"English"}}, {"platform": {"Disney+"}})

        assert result == {c2}

    def test_exclude_nonexistent_tag_is_noop(self, three_channels):
        """Excluding a tag value that no channel carries does not drop any channels."""
        c1, c2, c3, db = three_channels

        result = _query(db, {}, {"platform": {"Hulu"}})

        assert result == {c1, c2, c3}


# ---------------------------------------------------------------------------
# Empty inputs
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    def test_empty_includes_and_excludes_returns_all_channels(self, three_channels):
        """No constraints → all seeded channels."""
        c1, c2, c3, db = three_channels

        result = _query(db, {}, {})

        assert result == {c1, c2, c3}

    def test_none_excludes_is_same_as_empty(self, three_channels):
        """Passing excludes=None is equivalent to excludes={}."""
        c1, c2, c3, db = three_channels

        result = _query(db, {}, None)

        assert result == {c1, c2, c3}

    def test_empty_value_set_in_includes_is_ignored(self, three_channels):
        """An include entry with an empty value set imposes no constraint."""
        c1, c2, c3, db = three_channels

        # language:{} should be ignored, so this is equivalent to empty includes.
        result = _query(db, {"language": set()}, {})

        assert result == {c1, c2, c3}


# ---------------------------------------------------------------------------
# base_channel_ids pre-filter
# ---------------------------------------------------------------------------


class TestBaseChannelIds:
    def test_base_channel_ids_scopes_result(self, three_channels):
        """base_channel_ids restricts the search space before facet filtering."""
        c1, c2, c3, db = three_channels

        # Only consider c1 and c2; platform:Disney+ applied on top → only c1.
        result = _query(
            db,
            {"platform": {"Disney+"}},
            base_channel_ids={c1, c2},
        )

        assert result == {c1}

    def test_empty_base_channel_ids_returns_empty(self, three_channels):
        """An empty base_channel_ids pre-filter yields an empty result."""
        _c1, _c2, _c3, db = three_channels

        result = _query(db, {}, base_channel_ids=set())

        assert result == set()


# ---------------------------------------------------------------------------
# excluded_provider_ids — visible-channel scoping (recipe YIELDS path)
# ---------------------------------------------------------------------------


def _add_scoped_channel(session, name, provider_id, is_hidden=False) -> str:
    """Insert a ChannelDB row with an explicit provider + hidden state."""
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            is_hidden=is_hidden,
        )
    )
    session.flush()
    return cid


def _scoped_query(db, includes, excludes=None, excluded_provider_ids=None) -> set[str]:
    """Run get_channel_ids_by_tag_facets with provider/visibility scoping."""
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        return repos.tags.get_channel_ids_by_tag_facets(
            includes,
            excludes,
            excluded_provider_ids=excluded_provider_ids,
        )


@pytest.fixture
def drama_across_sources(file_db):
    """Seed Drama channels spanning an active provider, a hidden provider,
    an individually-hidden channel, and a ## category header.

    Returns (active_id, other_provider_id, hidden_chan_id, header_id, db).
    """
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)

        active = _add_scoped_channel(session, "Active Drama", "prov_active")
        repos.tags.set_content_tags(active, [("genre", "Drama", "f")])

        other = _add_scoped_channel(session, "Other Drama", "prov_other")
        repos.tags.set_content_tags(other, [("genre", "Drama", "f")])

        hidden_chan = _add_scoped_channel(
            session, "Hidden Drama", "prov_active", is_hidden=True
        )
        repos.tags.set_content_tags(hidden_chan, [("genre", "Drama", "f")])

        header = _add_scoped_channel(session, "## DRAMA HEADER", "prov_active")
        repos.tags.set_content_tags(header, [("genre", "Drama", "f")])

    return active, other, hidden_chan, header, file_db


class TestExcludedProviderScoping:
    def test_excluded_provider_dropped_from_result(self, drama_across_sources):
        """A channel on an excluded provider is not counted in the result."""
        active, other, _hidden, _hdr, db = drama_across_sources

        result = _scoped_query(
            db, {"genre": {"Drama"}}, excluded_provider_ids=["prov_other"]
        )

        assert other not in result
        assert active in result

    def test_scope_drops_individually_hidden_channel(self, drama_across_sources):
        """is_hidden channels are excluded once scoping is requested — even with
        an empty exclusion list (recipe always passes a list)."""
        active, _other, hidden_chan, _hdr, db = drama_across_sources

        result = _scoped_query(db, {"genre": {"Drama"}}, excluded_provider_ids=[])

        assert hidden_chan not in result
        assert active in result

    def test_scope_drops_category_header(self, drama_across_sources):
        """## provider category headers are excluded once scoping is requested."""
        active, _other, _hidden, header, db = drama_across_sources

        result = _scoped_query(db, {"genre": {"Drama"}}, excluded_provider_ids=[])

        assert header not in result
        assert active in result

    def test_none_excluded_is_unscoped_backward_compat(self, drama_across_sources):
        """The default (excluded_provider_ids=None) stays scope-agnostic — hidden
        and header channels are still returned (existing callers unaffected)."""
        active, other, hidden_chan, header, db = drama_across_sources

        result = _scoped_query(db, {"genre": {"Drama"}}, excluded_provider_ids=None)

        assert result == {active, other, hidden_chan, header}

    def test_excludes_apply_alongside_scoping(self, file_db):
        """tag excludes still drop matching channels when provider-scoped."""
        with file_db.session_scope() as session:
            repos = RepositoryFactory(session)
            keep = _add_scoped_channel(session, "Keep", "prov_active")
            repos.tags.set_content_tags(keep, [("genre", "Drama", "f")])
            drop = _add_scoped_channel(session, "Drop", "prov_active")
            repos.tags.set_content_tags(
                drop, [("genre", "Drama", "f"), ("language", "Spanish", "f")]
            )

        result = _scoped_query(
            file_db,
            {"genre": {"Drama"}},
            excludes={"language": {"Spanish"}},
            excluded_provider_ids=[],
        )

        assert result == {keep}


# ---------------------------------------------------------------------------
# count_* / sample_* — SQL count + bounded preview (no full materialisation)
# ---------------------------------------------------------------------------


class TestCountAndSample:
    def test_count_matches_id_set_length(self, three_channels):
        """count_channels_by_tag_facets equals len(get_channel_ids_by_tag_facets)."""
        _c1, _c2, _c3, db = three_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            ids = repos.tags.get_channel_ids_by_tag_facets({"platform": {"Disney+"}})
            count = repos.tags.count_channels_by_tag_facets({"platform": {"Disney+"}})
        assert count == len(ids) == 2

    def test_count_respects_provider_scope(self, drama_across_sources):
        """The SQL count excludes hidden-provider / hidden / header channels."""
        active, _other, _hidden, _hdr, db = drama_across_sources
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            count = repos.tags.count_channels_by_tag_facets(
                {"genre": {"Drama"}}, excluded_provider_ids=["prov_other"]
            )
        assert count == 1  # only the active-provider, visible, non-header channel

    def test_count_respects_excludes(self, three_channels):
        """Excludes drop matching channels from the count."""
        _c1, _c2, _c3, db = three_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            count = repos.tags.count_channels_by_tag_facets(
                {"platform": {"Disney+"}}, excludes={"language": {"Spanish"}}
            )
        assert count == 1  # Disney+ minus the Spanish one

    def test_sample_returns_bounded_names(self, three_channels):
        """sample_channel_names_by_tag_facets returns <=limit names from the set."""
        c1, _c2, c3, db = three_channels  # c1, c3 are Disney+
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            names = repos.tags.sample_channel_names_by_tag_facets(
                {"platform": {"Disney+"}}, limit=1
            )
        assert len(names) == 1
        assert names[0] in {"Disney+ English US Movie", "Spanish Disney Movie"}

    def test_sample_respects_provider_scope(self, drama_across_sources):
        """The preview sample never includes hidden-source/header channels."""
        _active, _other, _hidden, _hdr, db = drama_across_sources
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            names = repos.tags.sample_channel_names_by_tag_facets(
                {"genre": {"Drama"}}, excluded_provider_ids=["prov_other"], limit=20
            )
        assert names == ["Active Drama"]

    def test_sample_empty_when_no_match(self, three_channels):
        """A non-existent value yields an empty preview, not a crash."""
        _c1, _c2, _c3, db = three_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            names = repos.tags.sample_channel_names_by_tag_facets(
                {"platform": {"Nope+"}}
            )
        assert names == []


# ---------------------------------------------------------------------------
# Global Exclusions — excluded_prefixes / excluded_categories (Task A)
# ---------------------------------------------------------------------------
#
# The recipe must honour the user's Global Exclusions (the same set the main
# channel list applies): a channel whose detected_prefix OR detected_region is
# in excluded_prefixes, or whose user_category is in excluded_categories, must
# disappear from the cloud counts, YIELDS, and the preview.  Untagged (NULL)
# channels must NOT be dropped — the `col NOT IN (...)` NULL trap.


def _add_excl_channel(session, name, provider_id="prov_active", *,
                      detected_prefix=None, detected_region=None,
                      user_category=None) -> str:
    """Insert a ChannelDB row carrying the Global-Exclusion-relevant columns."""
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            detected_prefix=detected_prefix,
            detected_region=detected_region,
            user_category=user_category,
        )
    )
    session.flush()
    return cid


@pytest.fixture
def global_exclusion_channels(file_db):
    """Seed four Drama channels exercising every Global-Exclusion axis.

    - keep_null  — no prefix/region/category at all (the NULL-trap canary).
    - excl_prefix — detected_prefix='AR' (excluded via excluded_prefixes).
    - excl_region — detected_region='AR' (excluded via excluded_prefixes too —
                    prefixes match BOTH detected_prefix and detected_region).
    - excl_cat    — user_category='Kids' (excluded via excluded_categories).

    Returns (keep_null, excl_prefix, excl_region, excl_cat, db).
    """
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)

        keep_null = _add_excl_channel(session, "Drama Null")
        repos.tags.set_content_tags(keep_null, [("genre", "Drama", "f")])

        excl_prefix = _add_excl_channel(session, "Drama AR Prefix", detected_prefix="AR")
        repos.tags.set_content_tags(excl_prefix, [("genre", "Drama", "f")])

        excl_region = _add_excl_channel(session, "Drama AR Region", detected_region="AR")
        repos.tags.set_content_tags(excl_region, [("genre", "Drama", "f")])

        excl_cat = _add_excl_channel(session, "Drama Kids Cat", user_category="Kids")
        repos.tags.set_content_tags(excl_cat, [("genre", "Drama", "f")])

    return keep_null, excl_prefix, excl_region, excl_cat, file_db


class TestGlobalExclusionScoping:
    """excluded_prefixes / excluded_categories drop globally-banished channels."""

    def test_count_drops_excluded_prefix_and_region(self, global_exclusion_channels):
        """A prefix code in excluded_prefixes drops channels matching it on EITHER
        detected_prefix or detected_region; the NULL channel survives."""
        _keep, _ep, _er, _ec, db = global_exclusion_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            count = repos.tags.count_channels_by_tag_facets(
                {"genre": {"Drama"}},
                excluded_provider_ids=[],
                excluded_prefixes={"AR"},
            )
        # keep_null + excl_cat survive; the two AR channels are dropped.
        assert count == 2

    def test_count_drops_excluded_category(self, global_exclusion_channels):
        """A user_category in excluded_categories drops that channel only."""
        _keep, _ep, _er, _ec, db = global_exclusion_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            count = repos.tags.count_channels_by_tag_facets(
                {"genre": {"Drama"}},
                excluded_provider_ids=[],
                excluded_categories={"Kids"},
            )
        # keep_null + the two AR channels survive; only excl_cat is dropped.
        assert count == 3

    def test_null_columns_never_dropped(self, global_exclusion_channels):
        """The fully-NULL channel survives every exclusion set (NULL trap)."""
        keep_null, _ep, _er, _ec, db = global_exclusion_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            ids = repos.tags.get_channel_ids_by_tag_facets(
                {"genre": {"Drama"}},
                excluded_provider_ids=[],
                excluded_prefixes={"AR", "KU"},
                excluded_categories={"Kids", "Adult"},
            )
        assert keep_null in ids

    def test_empty_sets_keep_everything(self, global_exclusion_channels):
        """Empty exclusion sets (paused global filter) drop nothing."""
        keep_null, ep, er, ec, db = global_exclusion_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            count = repos.tags.count_channels_by_tag_facets(
                {"genre": {"Drama"}},
                excluded_provider_ids=[],
                excluded_prefixes=set(),
                excluded_categories=set(),
            )
            ids = repos.tags.get_channel_ids_by_tag_facets(
                {"genre": {"Drama"}}, excluded_provider_ids=[]
            )
        assert count == 4
        assert {keep_null, ep, er, ec} <= ids

    def test_cloud_counts_drop_excluded_prefix(self, global_exclusion_channels):
        """get_tag_counts_for_facet (the cloud) honours excluded_prefixes."""
        _keep, _ep, _er, _ec, db = global_exclusion_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            counts = repos.tags.get_tag_counts_for_facet(
                "genre",
                excluded_provider_ids=[],
                excluded_prefixes={"AR"},
            )
        # The cloud's Drama tile must drop the two AR channels.
        drama = next(c for c in counts if c.value == "Drama")
        assert drama.channel_count == 2

    def test_facet_summary_drops_excluded(self, global_exclusion_channels):
        """get_facet_summary (the pantry) runs with exclusion sets without error
        and still reports the genre facet (the surviving channels carry it)."""
        _keep, _ep, _er, _ec, db = global_exclusion_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            summary = repos.tags.get_facet_summary(
                excluded_provider_ids=[],
                excluded_prefixes={"AR"},
                excluded_categories={"Kids"},
            )
        # genre still present (keep_null carries it); distinct value count is 1.
        genre = next(s for s in summary if s.facet_type == "genre")
        assert genre.distinct_values == 1

    def test_sample_preview_drops_excluded(self, global_exclusion_channels):
        """The preview sample never includes globally-excluded channels."""
        _keep, _ep, _er, _ec, db = global_exclusion_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            names = repos.tags.sample_channel_names_by_tag_facets(
                {"genre": {"Drama"}},
                excluded_provider_ids=[],
                excluded_prefixes={"AR"},
                excluded_categories={"Kids"},
                limit=20,
            )
        assert names == ["Drama Null"]


# ---------------------------------------------------------------------------
# sample_channels_by_tag_facets — bounded ContentCard result shelf (Task B)
# ---------------------------------------------------------------------------


class TestSampleChannelsAsCards:
    """The card-bearing sibling returns session-free ContentCards, scoped
    identically to the count/name preview."""

    def test_returns_content_cards_with_core_fields(self, three_channels):
        """Each result is a ContentCard carrying channel_id + title."""
        from metatv.core.discovery_engine import ContentCard

        c1, _c2, c3, db = three_channels  # c1, c3 are Disney+
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"platform": {"Disney+"}}, limit=24
            )
        assert all(isinstance(c, ContentCard) for c in cards)
        ids = {c.channel_id for c in cards}
        assert ids == {c1, c3}
        assert all(c.title for c in cards)

    def test_card_sample_respects_limit(self, three_channels):
        """The bounded LIMIT caps the number of cards returned."""
        _c1, _c2, _c3, db = three_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"platform": {"Disney+"}}, limit=1
            )
        assert len(cards) == 1

    def test_card_sample_respects_global_exclusions(self, global_exclusion_channels):
        """Cards are scoped by provider AND Global Exclusions (same as YIELDS)."""
        keep_null, _ep, _er, _ec, db = global_exclusion_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                excluded_provider_ids=[],
                excluded_prefixes={"AR"},
                excluded_categories={"Kids"},
            )
        assert {c.channel_id for c in cards} == {keep_null}

    def test_card_sample_empty_when_no_match(self, three_channels):
        """A non-existent value yields an empty card list, not a crash."""
        _c1, _c2, _c3, db = three_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets({"platform": {"Nope+"}})
        assert cards == []


# ---------------------------------------------------------------------------
# Stable pagination — sample_channels_by_tag_facets(limit, offset)
# ---------------------------------------------------------------------------
#
# The recipe "Show all" browse page pages through the FULL match set via the
# offset parameter.  Pages are ordered by the stored clean title (detected_title,
# case-insensitive, falling back to name) with channel_id as a deterministic
# tiebreaker, so successive (limit, offset) pages are disjoint and together cover
# the whole set with no overlap and no gaps — and the browse reads as ONE true
# A→Z run (no "4K leads" / per-prefix / per-case sub-runs; variants sit adjacent).


@pytest.fixture
def many_drama_channels(file_db):
    """Seed N>2*page channels that all match genre:Drama; return (ids, db)."""
    n = 25
    ids: list[str] = []
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)
        for i in range(n):
            # Names intentionally inverse to channel_id/insertion order so the
            # name-ordered result is provably NOT just id/insertion order.
            cid = _add_channel(session, f"Drama {n - i:03d}")
            repos.tags.set_content_tags(cid, [("genre", "Drama", "test_feeder")])
            ids.append(cid)
    return ids, file_db


class TestStablePagination:
    def test_pages_are_disjoint_and_cover_full_set(self, many_drama_channels):
        """Paging through (limit, offset) yields disjoint pages covering all ids."""
        all_ids, db = many_drama_channels
        page = 10
        seen: list[str] = []
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            offset = 0
            while True:
                cards = repos.tags.sample_channels_by_tag_facets(
                    {"genre": {"Drama"}}, limit=page, offset=offset
                )
                if not cards:
                    break
                seen.extend(c.channel_id for c in cards)
                offset += len(cards)

        # No duplicates across pages, and the union covers the full match set.
        assert len(seen) == len(set(seen)), "Pages overlapped (a duplicate id)"
        assert set(seen) == set(all_ids), "Pages did not cover the full set"

    def test_adjacent_pages_do_not_overlap(self, many_drama_channels):
        """Page (limit=N, offset=0) and (limit=N, offset=N) share no ids."""
        _all_ids, db = many_drama_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            p0 = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}}, limit=8, offset=0
            )
            p1 = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}}, limit=8, offset=8
            )
        s0 = {c.channel_id for c in p0}
        s1 = {c.channel_id for c in p1}
        assert len(s0) == 8 and len(s1) == 8
        assert s0.isdisjoint(s1), "offset=0 and offset=N pages overlapped"

    def test_ordering_is_deterministic_across_calls(self, many_drama_channels):
        """The same (limit, offset) returns the same ids in the same order."""
        _all_ids, db = many_drama_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            a = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}}, limit=7, offset=7
            )
            b = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}}, limit=7, offset=7
            )
        assert [c.channel_id for c in a] == [c.channel_id for c in b]

    def test_card_order_is_alphabetical_by_name(self, many_drama_channels):
        """Cards page through in (name, channel_id) order — alphabetical browse.

        The seeded names are deliberately inverse to channel_id/insertion order,
        so an id-ordered (or insertion-ordered) result would differ from the
        name-sorted order — this asserts the page sequence follows name order.
        """
        from metatv.core.database import ChannelDB

        all_ids, db = many_drama_channels
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            # Canonical expected order: matching channels sorted by (name, id).
            expected = [
                r.id
                for r in session.query(ChannelDB.id)
                .filter(ChannelDB.id.in_(all_ids))
                .order_by(ChannelDB.name, ChannelDB.id)
                .all()
            ]
            # Page through the whole set and collect the actual id sequence.
            seen: list[str] = []
            offset = 0
            while True:
                cards = repos.tags.sample_channels_by_tag_facets(
                    {"genre": {"Drama"}}, limit=6, offset=offset
                )
                if not cards:
                    break
                seen.extend(c.channel_id for c in cards)
                offset += len(cards)
        assert seen == expected, "Show-all pages are not in (name, id) order"

    def test_card_order_uses_clean_title_case_insensitive(self, file_db):
        """Show-all orders by detected_title (clean), case-insensitive — not raw name.

        Regression for the "4K leads the list" + "A→Z then restarts" bug: prefix
        junk ("4K - ", "|EN| ") in the raw name must not drive the sort, and case
        must not split titles into separate runs.
        """
        from metatv.core.database import ChannelDB

        db = file_db
        # (raw_name, detected_title) — clean titles span case + a "4K -" prefix.
        seed = [
            ("4K - Banana (2024)", "Banana"),   # prefix must not sort under "4"
            ("|EN| zebra raw", "Zebra"),
            ("DRAGON RAW", "dragon"),            # uppercase raw, lowercase title
            ("apple raw", "Apple"),
        ]
        ids_by_title: dict[str, str] = {}
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            for raw, clean in seed:
                cid = _add_channel(session, raw)
                session.query(ChannelDB).filter_by(id=cid).update(
                    {"detected_title": clean}
                )
                repos.tags.set_content_tags(cid, [("genre", "Drama", "test")])
                ids_by_title[clean] = cid

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}}, limit=10, offset=0
            )

        got = [c.channel_id for c in cards]
        # Case-insensitive by clean title: Apple, Banana, dragon, Zebra — NOT raw
        # name order (which would sort "4K -" first and split by case).
        expected = [ids_by_title[t] for t in ("Apple", "Banana", "dragon", "Zebra")]
        assert got == expected
