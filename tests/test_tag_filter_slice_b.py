"""End-to-end behavioral tests for tag-filter Slice B.

Slice B wires the faceted tag model into the channel-list query path:
  - FilterPanel.update_data() now receives {facet_type: {value: count}} from
    TagRepository.get_facet_value_counts() instead of the old prefix-stats dict.
  - FilterPanel.get_filter_state() builds tag_includes: {facet_type: set(values)}
    (cross-axis expansion is deleted — intersection is the correct model).
  - ChannelRepository.get_all(tag_includes=…) ANDs per-facet correlated EXISTS
    subqueries into the SQL query (no id-set materialisation; pagination safe).

Headline invariant tested here:
    Seed Disney+ English movies, plain-English movies, Spanish Disney+ movies.
    Filter: Language = all-selected (unconstrained) + Platform = {Disney+}.
    Result: only Disney+ channels (English + Spanish), NOT plain-English movies.
    i.e. Platform-only restriction is a strict intersection, not a union.

Additional coverage:
  - get_facet_value_counts: populated facets; active-source scoping.
  - Single-facet subset (Language={English}) intersects with Platform={Disney+}.
  - Active-source scoping: excluded provider channels never appear.
  - Pagination: offset/limit returns a bounded page with correct has_more logic.
  - Tag_includes=None means no facet filter (all channels pass).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures — file-backed DB (CLAUDE.md: never :memory:)
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path: Path):
    """File-backed SQLite DB with all tables created."""
    db_file = tmp_path / "slice_b.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def session(file_db):
    s = file_db.get_session()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _ch(
    session,
    name: str,
    *,
    provider_id: str = "p1",
    media_type: str = "movie",
) -> str:
    """Insert a minimal visible ChannelDB and return its id."""
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=False,
    )
    session.add(ch)
    session.flush()
    return ch.id


def _tag(repos, channel_id: str, *pairs: tuple[str, str]) -> None:
    """Tag channel_id with (type, value) pairs via set_content_tags."""
    repos.tags.set_content_tags(
        channel_id,
        [(t, v, "test_feeder") for t, v in pairs],
    )


# ---------------------------------------------------------------------------
# Headline test
# ---------------------------------------------------------------------------

class TestHeadlineIntersection:
    """Platform=Disney+ filter with all-languages returns only Disney+ channels."""

    def test_platform_only_filter_returns_only_disney(self, session):
        """Headline end-to-end: Language unconstrained + Platform={Disney+} → Disney+ only.

        Seeds:
          A — Disney+ English movie  (language=English, platform=Disney+)
          B — plain English movie    (language=English, no platform tag)
          C — Spanish Disney+ movie  (language=Spanish, platform=Disney+)

        Filter: tag_includes = {"platform": {"Disney+"}}  (language unconstrained)
        Expected: {A, C}  (both carry platform=Disney+; B has no platform tag)
        """
        repos = RepositoryFactory(session)

        id_a = _ch(session, "EN Disney+ Movie A")
        id_b = _ch(session, "EN Plain Movie B")
        id_c = _ch(session, "ES Disney+ Movie C")

        _tag(repos, id_a, ("language", "English"), ("platform", "Disney+"))
        _tag(repos, id_b, ("language", "English"))
        _tag(repos, id_c, ("language", "Spanish"), ("platform", "Disney+"))
        session.commit()

        rows = repos.channels.get_all(
            tag_includes={"platform": {"Disney+"}},
        )
        result_ids = {r.id for r in rows}

        assert id_a in result_ids, "Disney+ English movie must be in result"
        assert id_c in result_ids, "Disney+ Spanish movie must be in result"
        assert id_b not in result_ids, "Plain English movie (no platform tag) must be excluded"

    def test_language_and_platform_intersection(self, session):
        """Language=English AND Platform=Disney+ → only the English Disney+ channel.

        Intersection (not union): selecting both Language=English and Platform=Disney+
        must return only channels that carry BOTH tags.
        """
        repos = RepositoryFactory(session)

        id_a = _ch(session, "EN Disney+ Movie A")   # English + Disney+
        id_b = _ch(session, "EN Plain Movie B")      # English only
        id_c = _ch(session, "ES Disney+ Movie C")    # Disney+ only (Spanish)

        _tag(repos, id_a, ("language", "English"), ("platform", "Disney+"))
        _tag(repos, id_b, ("language", "English"))
        _tag(repos, id_c, ("language", "Spanish"), ("platform", "Disney+"))
        session.commit()

        rows = repos.channels.get_all(
            tag_includes={"language": {"English"}, "platform": {"Disney+"}},
        )
        result_ids = {r.id for r in rows}

        assert result_ids == {id_a}, (
            "Language=English AND Platform=Disney+ must return only the English Disney+ channel"
        )

    def test_no_tag_includes_returns_all(self, session):
        """tag_includes=None means no facet filter — all visible channels pass."""
        repos = RepositoryFactory(session)

        id_a = _ch(session, "Movie A")
        id_b = _ch(session, "Movie B")
        _tag(repos, id_a, ("platform", "Disney+"))
        session.commit()

        rows = repos.channels.get_all(tag_includes=None)
        result_ids = {r.id for r in rows}

        assert {id_a, id_b} <= result_ids, "No tag filter: all channels must pass"

    def test_empty_tag_includes_returns_all(self, session):
        """tag_includes={} (empty dict) imposes no constraint — all visible channels pass."""
        repos = RepositoryFactory(session)

        id_a = _ch(session, "Movie A")
        id_b = _ch(session, "Movie B")
        session.commit()

        rows = repos.channels.get_all(tag_includes={})
        result_ids = {r.id for r in rows}
        assert {id_a, id_b} <= result_ids


# ---------------------------------------------------------------------------
# get_facet_value_counts
# ---------------------------------------------------------------------------

class TestGetFacetValueCounts:
    """TagRepository.get_facet_value_counts returns per-facet counts from the DB."""

    def test_populated_facets_appear_in_counts(self, session):
        """After tagging channels, get_facet_value_counts returns their counts."""
        repos = RepositoryFactory(session)

        id_a = _ch(session, "EN Disney+ Movie", provider_id="p1")
        id_b = _ch(session, "EN Movie",        provider_id="p1")
        id_c = _ch(session, "ES Disney+ Movie", provider_id="p1")

        _tag(repos, id_a, ("language", "English"), ("platform", "Disney+"))
        _tag(repos, id_b, ("language", "English"))
        _tag(repos, id_c, ("language", "Spanish"), ("platform", "Disney+"))
        session.commit()

        counts = repos.tags.get_facet_value_counts()

        assert counts.get("language", {}).get("English", 0) == 2, (
            "English language tag should count 2 channels"
        )
        assert counts.get("language", {}).get("Spanish", 0) == 1
        assert counts.get("platform", {}).get("Disney+", 0) == 2, (
            "Disney+ platform tag should count 2 channels"
        )

    def test_active_source_scoping(self, session):
        """Channels from excluded providers are not counted."""
        repos = RepositoryFactory(session)

        id_active   = _ch(session, "Active Provider Movie", provider_id="active")
        id_inactive = _ch(session, "Inactive Provider Movie", provider_id="inactive")

        _tag(repos, id_active,   ("platform", "Netflix"))
        _tag(repos, id_inactive, ("platform", "Netflix"))
        session.commit()

        counts = repos.tags.get_facet_value_counts(
            excluded_provider_ids=["inactive"],
        )

        netflix_count = counts.get("platform", {}).get("Netflix", 0)
        assert netflix_count == 1, (
            "Excluded provider's channels must not appear in facet counts"
        )

    def test_empty_result_for_no_tags(self, session):
        """When no content_tags rows exist, result is an empty dict."""
        repos = RepositoryFactory(session)
        _ch(session, "Untagged Channel")
        session.commit()

        counts = repos.tags.get_facet_value_counts()
        assert counts == {}, "No tags → empty dict"

    def test_hidden_channels_excluded(self, session):
        """Hidden channels (is_hidden=True) must not be counted."""
        repos = RepositoryFactory(session)

        id_vis = _ch(session, "Visible Movie")
        ch_hid = ChannelDB(
            id=str(uuid.uuid4()),
            source_id=str(uuid.uuid4()),
            provider_id="p1",
            name="Hidden Movie",
            media_type="movie",
            is_hidden=True,  # hidden
        )
        session.add(ch_hid)
        session.flush()

        _tag(repos, id_vis,    ("platform", "Hulu"))
        _tag(repos, ch_hid.id, ("platform", "Hulu"))
        session.commit()

        counts = repos.tags.get_facet_value_counts()
        hulu_count = counts.get("platform", {}).get("Hulu", 0)
        assert hulu_count == 1, "Hidden channel's tags must not be counted"


# ---------------------------------------------------------------------------
# Pagination with tag_includes
# ---------------------------------------------------------------------------

class TestPaginationWithTagIncludes:
    """tag_includes is ANDed into the paginated get_all query (no id-set materialisation)."""

    def test_pagination_returns_bounded_page(self, session):
        """With tag_includes + limit, only the requested page size is returned."""
        repos = RepositoryFactory(session)

        # Seed 5 Disney+ channels + 3 plain channels
        disney_ids = set()
        for i in range(5):
            cid = _ch(session, f"Disney+ Movie {i:02d}")
            _tag(repos, cid, ("platform", "Disney+"))
            disney_ids.add(cid)
        for i in range(3):
            cid = _ch(session, f"Plain Movie {i:02d}")
            _tag(repos, cid, ("language", "English"))
        session.commit()

        # Page 1 — limit=3 of Disney+ channels
        page1 = repos.channels.get_all(
            tag_includes={"platform": {"Disney+"}},
            limit=3,
        )
        assert len(page1) == 3, "Page 1 must return exactly 3 rows (limit=3)"
        assert all(r.id in disney_ids for r in page1), (
            "All returned channels must carry the Disney+ platform tag"
        )

    def test_pagination_offset_advances_correctly(self, session):
        """Offset + limit on a tag-filtered query pages without overlap or gap."""
        repos = RepositoryFactory(session)

        disney_ids = set()
        for i in range(4):
            cid = _ch(session, f"Disney+ Movie {i:02d}")
            _tag(repos, cid, ("platform", "Disney+"))
            disney_ids.add(cid)
        session.commit()

        page1 = repos.channels.get_all(
            tag_includes={"platform": {"Disney+"}},
            limit=2, offset=0,
        )
        page2 = repos.channels.get_all(
            tag_includes={"platform": {"Disney+"}},
            limit=2, offset=2,
        )
        page1_ids = {r.id for r in page1}
        page2_ids = {r.id for r in page2}

        assert len(page1_ids) == 2
        assert len(page2_ids) == 2
        assert page1_ids.isdisjoint(page2_ids), "Pages must not overlap"
        assert page1_ids | page2_ids == disney_ids, "Two pages cover all Disney+ channels"

    def test_has_more_logic(self, session):
        """When more rows exist than page_size, the raw_count drives has_more correctly."""
        repos = RepositoryFactory(session)

        for i in range(6):
            cid = _ch(session, f"Disney+ Movie {i:02d}")
            _tag(repos, cid, ("platform", "Disney+"))
        session.commit()

        # Fetch page_size=4 rows from 6 Disney+ channels
        rows = repos.channels.get_all(
            tag_includes={"platform": {"Disney+"}},
            limit=4,
        )
        # raw_count == len(rows) == 4 from SQL; >= page_size → has_more=True
        raw_count = len(rows)
        page_size = 4
        has_more = raw_count >= page_size
        assert has_more, (
            "raw_count=4 >= page_size=4 → has_more must be True (more rows exist)"
        )

        # Fetch page_size=10 rows — all 6 fit → has_more=False
        rows_all = repos.channels.get_all(
            tag_includes={"platform": {"Disney+"}},
            limit=10,
        )
        raw_count_all = len(rows_all)
        has_more_all = raw_count_all >= 10
        assert not has_more_all, (
            "raw_count=6 < page_size=10 → has_more must be False"
        )


# ---------------------------------------------------------------------------
# Active-source scoping in channel query
# ---------------------------------------------------------------------------

class TestActiveSourceScoping:
    """get_all(excluded_provider_ids=…) + tag_includes respects active-source scoping."""

    def test_excluded_provider_channels_hidden_from_results(self, session):
        """Channels on excluded providers do not appear even if they carry the right tag."""
        repos = RepositoryFactory(session)

        id_active   = _ch(session, "Active Disney+ Movie",   provider_id="active")
        id_inactive = _ch(session, "Inactive Disney+ Movie", provider_id="inactive")

        _tag(repos, id_active,   ("platform", "Disney+"))
        _tag(repos, id_inactive, ("platform", "Disney+"))
        session.commit()

        rows = repos.channels.get_all(
            tag_includes={"platform": {"Disney+"}},
            excluded_provider_ids=["inactive"],
        )
        result_ids = {r.id for r in rows}

        assert id_active in result_ids, "Active provider's Disney+ channel must appear"
        assert id_inactive not in result_ids, (
            "Inactive provider's channel must be excluded even with matching tag"
        )
