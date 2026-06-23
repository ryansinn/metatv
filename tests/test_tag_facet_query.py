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
