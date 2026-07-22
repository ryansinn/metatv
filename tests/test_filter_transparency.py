"""Behavioral tests for the per-layer filter-transparency feature (B2).

A search (the alert live-search OR a normal search) that hides results now reports,
per filter layer, exactly how many results it dropped and lets the user reveal each
layer for THIS view only — never mutating the stored settings:

  * 🔒 Global Exclusions  → ``hidden_by_exclusions`` / ``_show_exclusion_hidden``
  * 🔎 search / Tier-1     → ``hidden_by_search``     / ``_show_filtered_results``

These tests drive the real query path (``_ChannelListMixin._query_channels`` against a
file-backed DB, per CLAUDE.md) to assert both counts, and the reveal handlers to assert
the view-scoped bypass flags. They also cover the gold-bar breakdown renderer.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui.main_window_channels import _ChannelListMixin


# ---------------------------------------------------------------------------
# Fixtures — file-backed DB (CLAUDE.md: never :memory:)
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def file_db(tmp_path: Path):
    db_file = tmp_path / "filter_transparency.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def session(file_db):
    s = file_db.get_session()
    # Seed an ACTIVE, non-expired provider so p1 channels aren't scoped out as
    # orphaned/inactive by get_hidden_provider_ids (the canonical provider gate that
    # _query_channels applies before the transparency layers being tested here).
    s.add(ProviderDB(
        id="p1", name="Test Source", type="xtream", url="http://example",
        is_active=True, account_status="Active",
    ))
    s.commit()
    yield s
    s.close()


def _ch(
    session,
    name: str,
    *,
    provider_id: str = "p1",
    media_type: str = "movie",
    detected_region: str | None = None,
    detected_prefix: str | None = None,
    detected_title: str | None = None,
    user_category: str | None = None,
) -> str:
    """Insert a minimal visible ChannelDB and return its id."""
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=False,
        detected_region=detected_region,
        detected_prefix=detected_prefix,
        detected_title=detected_title or name,
        user_category=user_category,
    )
    session.add(ch)
    session.flush()
    return ch.id


def _tag(repos, channel_id: str, *pairs: tuple[str, str]) -> None:
    repos.tags.set_content_tags(
        channel_id, [(t, v, "test_feeder") for t, v in pairs]
    )


def _params(**overrides) -> dict:
    """A full params dict shaped like ``load_channels`` builds for a normal search."""
    base = dict(
        provider_id=None,
        media_types=["live", "movie", "series"],
        language_prefixes=None,
        region_prefixes=None,
        quality_prefixes=None,
        platform_prefixes=None,
        genre_filters=None,
        invert_prefix_filters=False,
        include_untagged=True,
        include_untagged_quality=True,
        adult_mode="all",
        force_adult_ids=[],
        tag_includes=None,
        source_categories=None,
        excluded_prefixes=set(),
        excluded_user_categories=set(),
        bypass_global_exclusions=False,
        search_query=None,
        strict_genre_filter=None,
        person_filter=None,
        context_tag_filter=None,
        context_category_filter=None,
        context_id_filter=None,
        id_filter_show_all=False,
        page_size=1000,
        show_provider_icon=False,
        provider_icon_map={},
        given_provider_id=None,
        hidden_only=False,
        bypassing_tier1=False,
        hide_watched=False,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Layer 1 — Global Exclusions: hidden_by_exclusions
# ---------------------------------------------------------------------------

class TestHiddenByExclusions:
    def test_counts_results_dropped_by_region_exclusion(self, session):
        """3 EN + 2 AR matches, region AR excluded → 3 visible, hidden_by_exclusions == 2."""
        repos = RepositoryFactory(session)
        for i in range(3):
            _ch(session, f"Odyssey EN {i}", detected_region="EN")
        for i in range(2):
            _ch(session, f"Odyssey AR {i}", detected_region="AR")
        session.commit()

        params = _params(search_query="Odyssey", excluded_prefixes={"AR"})
        dtos, out = _ChannelListMixin._query_channels(repos, params)

        assert len(dtos) == 3, "only the 3 non-excluded (EN) matches are visible"
        assert out["hidden_by_exclusions"] == 2, "the 2 AR matches are counted as exclusion-hidden"
        assert out["hidden_by_search"] == 0, "no Tier-1 filter active"

    def test_counts_results_dropped_by_user_category_exclusion(self, session):
        """User-category exclusion is counted in the same layer."""
        repos = RepositoryFactory(session)
        for i in range(2):
            _ch(session, f"Widget Keep {i}", user_category="Keep")
        for i in range(4):
            _ch(session, f"Widget Trash {i}", user_category="Trash")
        session.commit()

        params = _params(search_query="Widget", excluded_user_categories={"Trash"})
        dtos, out = _ChannelListMixin._query_channels(repos, params)

        assert len(dtos) == 2
        assert out["hidden_by_exclusions"] == 4

    def test_bypass_reveals_excluded_and_zeroes_count(self, session):
        """bypass_global_exclusions=True → all matches visible, hidden_by_exclusions == 0."""
        repos = RepositoryFactory(session)
        for i in range(3):
            _ch(session, f"Odyssey EN {i}", detected_region="EN")
        for i in range(2):
            _ch(session, f"Odyssey AR {i}", detected_region="AR")
        session.commit()

        params = _params(
            search_query="Odyssey",
            excluded_prefixes={"AR"},
            bypass_global_exclusions=True,
        )
        dtos, out = _ChannelListMixin._query_channels(repos, params)

        assert len(dtos) == 5, "bypass reveals the AR matches for this view"
        assert out["hidden_by_exclusions"] == 0, "nothing is hidden once the layer is bypassed"


# ---------------------------------------------------------------------------
# Layer 2 — search / Tier-1 tag filters: hidden_by_search
# ---------------------------------------------------------------------------

class TestHiddenBySearch:
    def test_counts_results_dropped_by_tag_filter(self, session):
        """2 Disney+ + 3 plain matches, tag_includes=Disney+ → 2 visible, hidden_by_search == 3."""
        repos = RepositoryFactory(session)
        disney = [_ch(session, f"Widget Disney {i}") for i in range(2)]
        plain = [_ch(session, f"Widget Plain {i}") for i in range(3)]
        for cid in disney:
            _tag(repos, cid, ("platform", "Disney+"))
        for cid in plain:
            _tag(repos, cid, ("language", "English"))
        session.commit()

        params = _params(
            search_query="Widget",
            tag_includes={"platform": {"Disney+"}},
        )
        dtos, out = _ChannelListMixin._query_channels(repos, params)

        assert len(dtos) == 2, "only the Disney+ matches survive the Tier-1 filter"
        assert out["hidden_by_search"] == 3, "the 3 plain matches are counted as search-filtered"
        assert out["hidden_by_exclusions"] == 0

    def test_bypass_tier1_shows_all_and_zeroes_count(self, session):
        """The Tier-1 reveal sets tag_includes=None (bypassing) → all matches, hidden_by_search == 0."""
        repos = RepositoryFactory(session)
        disney = [_ch(session, f"Widget Disney {i}") for i in range(2)]
        plain = [_ch(session, f"Widget Plain {i}") for i in range(3)]
        for cid in disney:
            _tag(repos, cid, ("platform", "Disney+"))
        session.commit()

        # _show_filtered_results sets _bypass_tier1_filters → load_channels passes
        # tag_includes=None, so the search-filter layer imposes nothing.
        params = _params(search_query="Widget", tag_includes=None, bypassing_tier1=True)
        dtos, out = _ChannelListMixin._query_channels(repos, params)

        assert len(dtos) == 5, "all matches visible when the Tier-1 filter is bypassed"
        assert out["hidden_by_search"] == 0

    def test_both_layers_counted_independently(self, session):
        """A search hit by BOTH layers reports each layer's own count.

        Widget matches: 2 Disney+/EN (visible), 3 Disney+/AR (region-excluded),
        4 plain/EN (Tier-1-filtered).  hidden_by_exclusions counts the 3 AR;
        hidden_by_search counts only what the tag filter removes on top of the
        exclusion layer (the 4 plain/EN), never double-counting the AR rows.
        """
        repos = RepositoryFactory(session)
        vis = [_ch(session, f"Widget Vis {i}", detected_region="EN") for i in range(2)]
        excl = [_ch(session, f"Widget Excl {i}", detected_region="AR") for i in range(3)]
        plain = [_ch(session, f"Widget Plain {i}", detected_region="EN") for i in range(4)]
        for cid in vis + excl:
            _tag(repos, cid, ("platform", "Disney+"))
        for cid in plain:
            _tag(repos, cid, ("language", "English"))
        session.commit()

        params = _params(
            search_query="Widget",
            tag_includes={"platform": {"Disney+"}},
            excluded_prefixes={"AR"},
        )
        dtos, out = _ChannelListMixin._query_channels(repos, params)

        assert len(dtos) == 2, "only Disney+ AND non-excluded matches are visible"
        assert out["hidden_by_exclusions"] == 3, "the 3 AR Disney+ matches"
        assert out["hidden_by_search"] == 4, "the 4 plain/EN matches removed by the tag filter"


# ---------------------------------------------------------------------------
# Reveal handlers — set the view-scoped bypass flags, never the stored settings
# ---------------------------------------------------------------------------

class TestRevealHandlers:
    def _host(self):
        host = _ChannelListMixin()
        host._bypass_tier1_filters = False
        host._bypass_global_exclusions = False
        host._details_id_filter = None
        host.load_channels = MagicMock()
        return host

    def test_show_exclusion_hidden_sets_flag_and_reloads(self):
        host = self._host()
        host._show_exclusion_hidden()
        assert host._bypass_global_exclusions is True
        assert host._bypass_tier1_filters is False, "exclusion reveal must not touch the Tier-1 bypass"
        host.load_channels.assert_called_once()

    def test_show_filtered_results_sets_tier1_flag_and_reloads(self):
        host = self._host()
        host._show_filtered_results()
        assert host._bypass_tier1_filters is True
        assert host._bypass_global_exclusions is False, "Tier-1 reveal must not touch the exclusion bypass"
        host.load_channels.assert_called_once()


# ---------------------------------------------------------------------------
# Gold-bar breakdown renderer — up to two segments, each shown only when > 0
# ---------------------------------------------------------------------------

class TestBreakdownRenderer:
    def _host(self, qapp):
        from PyQt6.QtWidgets import QWidget, QPushButton
        host = _ChannelListMixin()
        host._channel_filter_bar = QWidget()
        host._channel_exclusion_btn = QPushButton()
        host._channel_filter_btn = QPushButton()
        return host

    def test_only_exclusion_segment_when_only_exclusions_hidden(self, qapp):
        host = self._host(qapp)
        host._show_channel_filter_breakdown(hidden_by_exclusions=4, hidden_by_search=0)
        assert host._channel_exclusion_btn.isVisible()
        assert not host._channel_filter_btn.isVisible()
        assert host._channel_filter_bar.isVisible()
        assert "4" in host._channel_exclusion_btn.text()
        assert "Global Exclusions" in host._channel_exclusion_btn.text()

    def test_only_search_segment_when_only_search_hidden(self, qapp):
        host = self._host(qapp)
        host._show_channel_filter_breakdown(hidden_by_exclusions=0, hidden_by_search=7)
        assert not host._channel_exclusion_btn.isVisible()
        assert host._channel_filter_btn.isVisible()
        assert "7" in host._channel_filter_btn.text()
        assert "search filters" in host._channel_filter_btn.text().lower()

    def test_both_segments_when_both_hidden(self, qapp):
        host = self._host(qapp)
        host._show_channel_filter_breakdown(hidden_by_exclusions=2, hidden_by_search=5)
        assert host._channel_exclusion_btn.isVisible()
        assert host._channel_filter_btn.isVisible()
        assert host._channel_filter_bar.isVisible()

    def test_bar_hidden_when_nothing_hidden(self, qapp):
        host = self._host(qapp)
        host._channel_filter_bar.setVisible(True)
        host._show_channel_filter_breakdown(hidden_by_exclusions=0, hidden_by_search=0)
        assert not host._channel_exclusion_btn.isVisible()
        assert not host._channel_filter_btn.isVisible()
        assert not host._channel_filter_bar.isVisible()
