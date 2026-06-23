"""Behavioral tests for the Recipe builder data layer (task #56, slice 1).

Tests the two new TagRepository methods:
- get_facet_summary()   → list[FacetSummaryDTO]
- get_tag_counts_for_facet() → list[TagCountDTO]

Coverage:
- get_facet_summary returns distinct-value counts, not channel counts.
- Hidden-provider channels are EXCLUDED from both methods.
- get_facet_summary uses canonical facet order (genre before language before …).
- get_tag_counts_for_facet sorts by channel_count DESC.
- get_tag_counts_for_facet ``limit`` parameter caps results.
- Both methods return frozen DTOs (no ORM objects cross the boundary).
- Zero-count entries are omitted from both results.
- Facet types outside the canonical order appear appended (alphabetically).
"""

from __future__ import annotations

import uuid
from typing import List

import pytest

from metatv.core.database import ChannelDB, ContentTagDB, Database, ProviderDB, TagDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import FacetSummaryDTO, TagCountDTO
from metatv.core.repositories.tag import _clear_tag_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created."""
    db_file = tmp_path / "test_recipe.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def session(file_db):
    """Fresh session per test; caller manages commit explicitly."""
    s = file_db.get_session()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(session, provider_id: str, is_active: bool = True) -> str:
    """Insert a minimal ProviderDB row and return its id."""
    p = ProviderDB(
        id=provider_id,
        name=f"Provider {provider_id}",
        type="xtream",
        url="http://example.com",
        username="u",
        password="p",
        is_active=is_active,
    )
    session.add(p)
    session.flush()
    return p.id


def _make_channel(
    session,
    provider_id: str,
    is_hidden: bool = False,
    name: str | None = None,
) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    cid = str(uuid.uuid4())
    ch = ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name or f"Channel {cid[:8]}",
        is_hidden=is_hidden,
    )
    session.add(ch)
    session.flush()
    return cid


def _tag_channel(session, channel_id: str, facet_type: str, value: str) -> None:
    """Tag a channel with (facet_type, value) via TagRepository.set_content_tags."""
    repos = RepositoryFactory(session)
    repos.tags.set_content_tags(
        channel_id,
        [(facet_type, value, "test_feeder")],
    )
    session.flush()


# ---------------------------------------------------------------------------
# get_facet_summary — basic correctness
# ---------------------------------------------------------------------------

class TestGetFacetSummary:
    def test_single_facet_distinct_count(self, session):
        """With 3 channels tagged with 2 distinct genre values, summary shows genre → 2."""
        pid = _make_provider(session, "p1")
        c1 = _make_channel(session, pid)
        c2 = _make_channel(session, pid)
        c3 = _make_channel(session, pid)
        _tag_channel(session, c1, "genre", "Drama")
        _tag_channel(session, c2, "genre", "Drama")   # same value → still 1 distinct
        _tag_channel(session, c3, "genre", "Action")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_facet_summary()
        by_type = {dto.facet_type: dto.distinct_values for dto in results}

        assert by_type["genre"] == 2

    def test_counts_distinct_values_not_channels(self, session):
        """distinct_values counts tag VALUES, not channels."""
        pid = _make_provider(session, "p1")
        for _ in range(10):
            cid = _make_channel(session, pid)
            _tag_channel(session, cid, "language", "English")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_facet_summary()
        by_type = {dto.facet_type: dto.distinct_values for dto in results}

        # 10 channels all with the same value → 1 distinct value
        assert by_type["language"] == 1

    def test_multiple_facet_types_all_returned(self, session):
        """Multiple facet types are all present in the summary."""
        pid = _make_provider(session, "p1")
        cid = _make_channel(session, pid)
        _tag_channel(session, cid, "genre", "Comedy")
        _tag_channel(session, cid, "language", "French")
        _tag_channel(session, cid, "region", "FR")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_facet_summary()
        types_returned = {dto.facet_type for dto in results}

        assert "genre" in types_returned
        assert "language" in types_returned
        assert "region" in types_returned

    def test_empty_db_returns_empty_list(self, session):
        """With no channels or tags, get_facet_summary returns an empty list."""
        repos = RepositoryFactory(session)
        assert repos.tags.get_facet_summary() == []

    def test_returns_frozen_dtos_not_orm(self, session):
        """Results are frozen FacetSummaryDTO instances, not ORM objects."""
        pid = _make_provider(session, "p1")
        cid = _make_channel(session, pid)
        _tag_channel(session, cid, "genre", "Drama")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_facet_summary()

        assert all(isinstance(dto, FacetSummaryDTO) for dto in results)
        # Frozen dataclasses should reject attribute mutation
        for dto in results:
            with pytest.raises((AttributeError, TypeError)):
                dto.distinct_values = 999  # type: ignore[misc]

    def test_canonical_facet_order_genre_before_language(self, session):
        """genre appears before language in the canonical sort order."""
        pid = _make_provider(session, "p1")
        cid = _make_channel(session, pid)
        _tag_channel(session, cid, "language", "English")
        _tag_channel(session, cid, "genre", "Action")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_facet_summary()
        types_in_order = [dto.facet_type for dto in results]

        assert types_in_order.index("genre") < types_in_order.index("language")

    def test_unseen_facet_type_appended_after_canonical(self, session):
        """A tag namespace not in _FACET_ORDER is appended after all canonical types."""
        pid = _make_provider(session, "p1")
        cid = _make_channel(session, pid)
        _tag_channel(session, cid, "genre", "Action")
        _tag_channel(session, cid, "zz_custom_namespace", "SomeValue")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_facet_summary()
        types_in_order = [dto.facet_type for dto in results]

        # "zz_custom_namespace" is not in _FACET_ORDER → must appear after "genre"
        assert "zz_custom_namespace" in types_in_order
        assert types_in_order.index("genre") < types_in_order.index("zz_custom_namespace")


# ---------------------------------------------------------------------------
# get_facet_summary — active-source scoping (the critical exclusion test)
# ---------------------------------------------------------------------------

class TestGetFacetSummaryActiveSourceScoping:
    def test_hidden_provider_channels_excluded(self, session):
        """Channels from hidden providers are NOT counted in get_facet_summary.

        Setup: active provider p1 has 2 genre values (Drama, Comedy).
               hidden provider p2 has 1 extra genre value (SciFi).
        Expected: genre distinct_values == 2 (SciFi excluded because p2 is hidden).
        """
        p1 = _make_provider(session, "p1", is_active=True)
        p2 = _make_provider(session, "p2", is_active=False)  # inactive → hidden

        c1 = _make_channel(session, p1)
        c2 = _make_channel(session, p1)
        c3 = _make_channel(session, p2)   # hidden provider
        _tag_channel(session, c1, "genre", "Drama")
        _tag_channel(session, c2, "genre", "Comedy")
        _tag_channel(session, c3, "genre", "SciFi")   # should NOT be counted
        session.commit()

        repos = RepositoryFactory(session)
        hidden_ids = repos.providers.get_hidden_provider_ids()
        results = repos.tags.get_facet_summary(excluded_provider_ids=hidden_ids)
        by_type = {dto.facet_type: dto.distinct_values for dto in results}

        assert by_type.get("genre") == 2, (
            f"Expected 2 distinct genre values from active provider only; got {by_type}"
        )

    def test_hidden_provider_facet_type_disappears_when_only_source(self, session):
        """If the only channel carrying a facet belongs to a hidden provider, that facet
        is omitted entirely from get_facet_summary."""
        p_active = _make_provider(session, "pactive", is_active=True)
        p_hidden = _make_provider(session, "phidden", is_active=False)

        c_active = _make_channel(session, p_active)
        c_hidden = _make_channel(session, p_hidden)
        _tag_channel(session, c_active, "genre", "Action")
        _tag_channel(session, c_hidden, "collection", "Hidden Collection")
        session.commit()

        repos = RepositoryFactory(session)
        hidden_ids = repos.providers.get_hidden_provider_ids()
        results = repos.tags.get_facet_summary(excluded_provider_ids=hidden_ids)
        types_returned = {dto.facet_type for dto in results}

        assert "collection" not in types_returned, (
            "collection facet should be absent — its only channel is on a hidden provider"
        )
        assert "genre" in types_returned

    def test_no_excluded_ids_includes_all(self, session):
        """Passing excluded_provider_ids=None (or []) includes channels from all providers."""
        p_inactive = _make_provider(session, "pinactive", is_active=False)
        cid = _make_channel(session, p_inactive)
        _tag_channel(session, cid, "genre", "Thriller")
        session.commit()

        repos = RepositoryFactory(session)
        # No exclusions — inactive provider's content should appear
        results = repos.tags.get_facet_summary(excluded_provider_ids=None)
        by_type = {dto.facet_type: dto.distinct_values for dto in results}

        assert by_type.get("genre", 0) >= 1, (
            "With no exclusions, inactive provider channels should be included"
        )


# ---------------------------------------------------------------------------
# get_tag_counts_for_facet — basic correctness
# ---------------------------------------------------------------------------

class TestGetTagCountsForFacet:
    def test_returns_values_with_correct_channel_counts(self, session):
        """get_tag_counts_for_facet returns each value with its channel count."""
        pid = _make_provider(session, "p1")
        for _ in range(5):
            _tag_channel(session, _make_channel(session, pid), "genre", "Drama")
        for _ in range(3):
            _tag_channel(session, _make_channel(session, pid), "genre", "Comedy")
        _tag_channel(session, _make_channel(session, pid), "genre", "Action")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_tag_counts_for_facet("genre")
        by_value = {dto.value: dto.channel_count for dto in results}

        assert by_value["Drama"] == 5
        assert by_value["Comedy"] == 3
        assert by_value["Action"] == 1

    def test_sorted_by_channel_count_desc(self, session):
        """Results are ordered by channel_count descending (most common first)."""
        pid = _make_provider(session, "p1")
        for _ in range(10):
            _tag_channel(session, _make_channel(session, pid), "genre", "Action")
        for _ in range(2):
            _tag_channel(session, _make_channel(session, pid), "genre", "Comedy")
        for _ in range(7):
            _tag_channel(session, _make_channel(session, pid), "genre", "Drama")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_tag_counts_for_facet("genre")
        counts = [dto.channel_count for dto in results]

        # Must be non-increasing
        assert counts == sorted(counts, reverse=True), (
            f"Expected descending order, got: {counts}"
        )
        # First result should be Action (10 channels)
        assert results[0].value == "Action"

    def test_limit_caps_results(self, session):
        """When limit is specified, at most limit rows are returned."""
        pid = _make_provider(session, "p1")
        for i in range(20):
            _tag_channel(session, _make_channel(session, pid), "genre", f"Genre{i:02d}")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_tag_counts_for_facet("genre", limit=5)

        assert len(results) <= 5

    def test_limit_none_returns_all(self, session):
        """When limit is None, all values are returned."""
        pid = _make_provider(session, "p1")
        for i in range(15):
            _tag_channel(session, _make_channel(session, pid), "genre", f"Genre{i:02d}")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_tag_counts_for_facet("genre", limit=None)

        assert len(results) == 15

    def test_unknown_facet_type_returns_empty(self, session):
        """Querying a facet type with no tags returns an empty list."""
        pid = _make_provider(session, "p1")
        _tag_channel(session, _make_channel(session, pid), "genre", "Drama")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_tag_counts_for_facet("nonexistent_facet")

        assert results == []

    def test_only_queries_requested_facet_type(self, session):
        """get_tag_counts_for_facet only returns values for the requested type."""
        pid = _make_provider(session, "p1")
        cid = _make_channel(session, pid)
        _tag_channel(session, cid, "genre", "Drama")
        _tag_channel(session, cid, "language", "English")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_tag_counts_for_facet("genre")
        values = [dto.value for dto in results]

        assert "Drama" in values
        assert "English" not in values

    def test_returns_frozen_dtos_not_orm(self, session):
        """Results are frozen TagCountDTO instances, not ORM objects."""
        pid = _make_provider(session, "p1")
        _tag_channel(session, _make_channel(session, pid), "genre", "Action")
        session.commit()

        repos = RepositoryFactory(session)
        results = repos.tags.get_tag_counts_for_facet("genre")

        assert all(isinstance(dto, TagCountDTO) for dto in results)
        for dto in results:
            with pytest.raises((AttributeError, TypeError)):
                dto.channel_count = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_tag_counts_for_facet — active-source scoping
# ---------------------------------------------------------------------------

class TestGetTagCountsForFacetActiveSourceScoping:
    def test_hidden_provider_channels_excluded_from_counts(self, session):
        """Channels from hidden providers are NOT counted in channel_count.

        Setup: active provider has 3 Drama channels.
               hidden provider has 5 Drama channels.
        Expected: Drama channel_count == 3.
        """
        p_active = _make_provider(session, "pact", is_active=True)
        p_hidden = _make_provider(session, "phid", is_active=False)

        for _ in range(3):
            _tag_channel(session, _make_channel(session, p_active), "genre", "Drama")
        for _ in range(5):
            _tag_channel(session, _make_channel(session, p_hidden), "genre", "Drama")
        session.commit()

        repos = RepositoryFactory(session)
        hidden_ids = repos.providers.get_hidden_provider_ids()
        results = repos.tags.get_tag_counts_for_facet("genre", excluded_provider_ids=hidden_ids)
        by_value = {dto.value: dto.channel_count for dto in results}

        assert by_value.get("Drama") == 3, (
            f"Expected Drama count=3 from active provider only; got {by_value}"
        )

    def test_hidden_provider_only_value_excluded_entirely(self, session):
        """A tag value only present on hidden-provider channels is omitted from results."""
        p_active = _make_provider(session, "pact", is_active=True)
        p_hidden = _make_provider(session, "phid", is_active=False)

        _tag_channel(session, _make_channel(session, p_active), "genre", "Action")
        _tag_channel(session, _make_channel(session, p_hidden), "genre", "ExclusiveToHidden")
        session.commit()

        repos = RepositoryFactory(session)
        hidden_ids = repos.providers.get_hidden_provider_ids()
        results = repos.tags.get_tag_counts_for_facet("genre", excluded_provider_ids=hidden_ids)
        values = [dto.value for dto in results]

        assert "ExclusiveToHidden" not in values, (
            "Value only on hidden provider must not appear in results"
        )
        assert "Action" in values

    def test_limit_applied_after_scoping(self, session):
        """limit is applied after active-source scoping, not before."""
        p_active = _make_provider(session, "pact", is_active=True)
        p_hidden = _make_provider(session, "phid", is_active=False)

        # Active: 10 distinct genres with 1 channel each
        for i in range(10):
            _tag_channel(session, _make_channel(session, p_active), "genre", f"AGenre{i}")
        # Hidden: 5 more genres — must NOT appear even if limit would include them
        for i in range(5):
            _tag_channel(session, _make_channel(session, p_hidden), "genre", f"ZHidden{i}")
        session.commit()

        repos = RepositoryFactory(session)
        hidden_ids = repos.providers.get_hidden_provider_ids()
        results = repos.tags.get_tag_counts_for_facet(
            "genre", excluded_provider_ids=hidden_ids, limit=5
        )
        values = [dto.value for dto in results]

        assert len(values) <= 5
        for v in values:
            assert not v.startswith("ZHidden"), (
                f"Hidden provider value '{v}' leaked into scoped+limited results"
            )
