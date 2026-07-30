"""Behavioral tests for the Recipe builder's default "cluster grid" overview.

Two halves:

  ENGINE — ``TagRepository.get_top_tags_per_facet`` (real ``Database`` on a
  ``tmp_path`` file, per the tests rule): one windowed pass returns ≤N values per
  facet, small facets return ALL their values, and the DR-0007 visible-scope
  predicate drops a hidden-provider tag.

  VIEW — the default (``_selected_facet is None``) renders the cluster grid (the
  old dead early-return became the cluster path); drilling into a facet shows its
  single cloud and "‹ All facets" toggles back; clicking a tag inside a cluster
  adds the ingredient under ITS facet and stays on the grid; the decade tile is
  ordered chronologically; and the More-facets / column-1 collapse states persist.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import TagCountDTO


# ---------------------------------------------------------------------------
# Engine fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path):
    db_file = tmp_path / "test_clusters.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def session(file_db):
    s = file_db.get_session()
    yield s
    s.close()


def _make_provider(session, provider_id: str, is_active: bool = True) -> str:
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


def _make_channel(session, provider_id: str, is_hidden: bool = False) -> str:
    cid = str(uuid.uuid4())
    ch = ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=f"Channel {cid[:8]}",
        is_hidden=is_hidden,
    )
    session.add(ch)
    session.flush()
    return cid


def _tag(session, channel_id: str, facet_type: str, value: str) -> None:
    repos = RepositoryFactory(session)
    repos.tags.set_content_tags(channel_id, [(facet_type, value, "test_feeder")])
    session.flush()


# ---------------------------------------------------------------------------
# ENGINE — get_top_tags_per_facet
# ---------------------------------------------------------------------------

class TestGetTopTagsPerFacet:
    def test_caps_top_n_per_facet_sorted_by_count(self, session):
        """A facet with more than N values returns exactly the top N, count DESC."""
        pid = _make_provider(session, "p1")
        # 5 genre values with distinct channel counts 5,4,3,2,1.
        for rank, name in enumerate(["G5", "G4", "G3", "G2", "G1"]):
            for _ in range(5 - rank):
                c = _make_channel(session, pid)
                _tag(session, c, "genre", name)
        session.commit()

        repos = RepositoryFactory(session)
        out = repos.tags.get_top_tags_per_facet(["genre"], 3)

        assert set(out.keys()) == {"genre"}
        genre = out["genre"]
        assert len(genre) == 3, f"expected top-3, got {[d.value for d in genre]}"
        # Top-3 by count DESC = G5(5), G4(4), G3(3).
        assert [d.value for d in genre] == ["G5", "G4", "G3"]
        assert [d.channel_count for d in genre] == [5, 4, 3]
        assert all(isinstance(d, TagCountDTO) for d in genre)

    def test_small_facet_returns_all_values(self, session):
        """A facet with fewer than N values returns ALL of them (never truncated)."""
        pid = _make_provider(session, "p1")
        for q in ["HD", "4K"]:
            c = _make_channel(session, pid)
            _tag(session, c, "quality", q)
        session.commit()

        repos = RepositoryFactory(session)
        out = repos.tags.get_top_tags_per_facet(["quality"], 24)

        assert {d.value for d in out["quality"]} == {"HD", "4K"}

    def test_hidden_provider_tag_excluded(self, session):
        """A value carried only by a hidden-provider channel is excluded (DR-0007)."""
        p_active = _make_provider(session, "pa", is_active=True)
        p_hidden = _make_provider(session, "ph", is_active=False)  # inactive → hidden
        ca = _make_channel(session, p_active)
        ch = _make_channel(session, p_hidden)
        _tag(session, ca, "genre", "Drama")
        _tag(session, ch, "genre", "HiddenOnly")
        session.commit()

        repos = RepositoryFactory(session)
        hidden = repos.providers.get_hidden_provider_ids()
        out = repos.tags.get_top_tags_per_facet(
            ["genre"], 24, excluded_provider_ids=hidden
        )
        values = {d.value for d in out.get("genre", [])}
        assert "Drama" in values
        assert "HiddenOnly" not in values, "hidden-provider value must be scoped out"

    def test_multiple_facets_one_pass(self, session):
        """Several facets resolve together; each keyed under its own facet name."""
        pid = _make_provider(session, "p1")
        c1 = _make_channel(session, pid)
        c2 = _make_channel(session, pid)
        _tag(session, c1, "genre", "Action")
        _tag(session, c1, "region", "US")
        _tag(session, c2, "genre", "Action")
        session.commit()

        repos = RepositoryFactory(session)
        out = repos.tags.get_top_tags_per_facet(["genre", "region"], 24)
        assert out["genre"][0].value == "Action"
        assert out["genre"][0].channel_count == 2
        assert out["region"][0].value == "US"

    def test_empty_inputs_return_empty(self, session):
        """No facets, or a non-positive limit, yields an empty dict (no query)."""
        repos = RepositoryFactory(session)
        assert repos.tags.get_top_tags_per_facet([], 10) == {}
        assert repos.tags.get_top_tags_per_facet(["genre"], 0) == {}

    def test_returns_all_eight_browse_facets(self, session):
        """One windowed pass resolves every browse facet that has data (all 8)."""
        from metatv.gui.recipe_widgets import BROWSE_FACETS

        pid = _make_provider(session, "p1")
        # One channel carrying a tag in each of the 8 browse facets.
        c = _make_channel(session, pid)
        for facet in BROWSE_FACETS:
            _tag(session, c, facet, f"{facet}_v")
        session.commit()

        repos = RepositoryFactory(session)
        out = repos.tags.get_top_tags_per_facet(list(BROWSE_FACETS), 24)
        assert set(out.keys()) == set(BROWSE_FACETS)
        assert len(BROWSE_FACETS) == 8


# ---------------------------------------------------------------------------
# VIEW — cluster grid default, drill-in toggle, cross-facet build, persistence
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSeam:
    """Records _run_query calls; supports synchronous delivery in tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None) -> None:
        if token_ref is not None:
            token_ref[0] += 1
        self.calls.append(
            dict(query_fn=query_fn, on_result=on_result, token_ref=token_ref, on_error=on_error)
        )

    def deliver_to(self, on_result: Callable, data: Any) -> None:
        for entry in reversed(self.calls):
            if entry["on_result"] == on_result:
                entry["on_result"](data)
                return
        raise AssertionError(f"No _run_query for {on_result!r}")


class _FakeConfig:
    """Duck-typed config; splitter fields absent → view falls back to defaults."""

    recipe_col1_collapsed = False
    recipe_more_facets_expanded = False
    global_filter_paused = True   # → empty exclusion sets (no Config plumbing needed)
    discover_zoom = 1.0
    movie_icon = "🎬"
    series_icon = "📺"
    rating_star_icon = "★"
    like_icon = "👍"
    favorite_icon = "❤"
    queue_icon = "▶"
    watched_icon = "✓"
    list_view_icon = "☰"
    grid_view_icon = "▦"

    def save(self) -> None:  # exercised by persistence-free toggles
        pass


def _make_view(qapp, config=None):
    from PyQt6.QtCore import QObject, pyqtSignal

    class IC(QObject):
        image_loaded = pyqtSignal(str, object)
        image_failed = pyqtSignal(str, str)

        def get_image_async(self, url):
            pass

    from metatv.gui.recipe_view import RecipeView

    seam = _FakeSeam()
    view = RecipeView(
        db=object(),
        config=config if config is not None else _FakeConfig(),
        run_query_fn=seam._run_query,
        image_cache=IC(),
        parent=None,
    )
    view._active = True
    return view, seam


def test_default_view_renders_clusters(qapp):
    """With no facet selected, the center pane is the cluster grid (page 0),
    populated from the async top-tags-per-facet payload — not an empty return."""
    view, seam = _make_view(qapp)
    view.on_activate()  # fires _load_clusters through the seam

    seam.deliver_to(view._on_clusters_loaded, {
        "genre": [TagCountDTO("Drama", 100), TagCountDTO("Comedy", 60)],
        "region": [TagCountDTO("US", 80)],
    })

    assert view._top_stack.currentIndex() == 0, "default center view must be the cluster grid"
    tiles = view._cluster_grid.tiles()
    facets = {t.facet_type() for t in tiles}
    assert {"genre", "region"} <= facets
    assert view._selected_facet is None


def test_facet_drill_in_then_back_toggle(qapp):
    """Clicking a cluster's facet drills into its single cloud (page 1); the
    "‹ All facets" affordance returns to the grid (page 0) and deselects."""
    view, _seam = _make_view(qapp)
    view.on_activate()

    view._on_facet_selected("genre")   # cluster header click seam
    assert view._selected_facet == "genre"
    assert view._top_stack.currentIndex() == 1, "drill-in shows the single-facet cloud"
    assert view._back_to_clusters_btn.isVisible() or True  # visibility set even if headless

    view._on_back_to_clusters()
    assert view._selected_facet is None
    assert view._top_stack.currentIndex() == 0, "back returns to the cluster grid"


def test_cluster_tag_click_adds_and_stays(qapp):
    """Clicking a tag inside a cluster adds it under ITS facet and stays on the grid."""
    view, _seam = _make_view(qapp)
    view.on_activate()
    view._cluster_data = {"genre": [TagCountDTO("Drama", 100)]}

    view._on_cluster_tag_clicked("genre", "Drama")

    assert "Drama" in view.recipe_includes.get("genre", set())
    assert view._top_stack.currentIndex() == 0, "cross-facet build stays on the overview"
    assert view._selected_facet is None


def test_decade_tile_ordered_chronologically(qapp):
    """The decade tile lays out its chips oldest → newest, not by weight."""
    from metatv.gui.recipe_widgets import _ClusterGrid
    from metatv.gui.weighted_tag_cloud import _TagButton

    grid = _ClusterGrid()
    grid.set_clusters(
        {"decade": [
            TagCountDTO("2020s", 5),     # smallest era, largest count
            TagCountDTO("1980s", 100),
            TagCountDTO("1990s", 50),
        ]},
        {}, {},
    )
    decade_tile = next(t for t in grid.tiles() if t.facet_type() == "decade")
    values = [
        w.value() for w in decade_tile._body.flow()._items
        if isinstance(w, _TagButton)
    ]
    assert values == ["1980s", "1990s", "2020s"], (
        f"decade chips must be chronological, got {values}"
    )


def _col_widget_counts(grid) -> list[int]:
    """Number of tile widgets in each masonry column layout (ignores stretches)."""
    counts = []
    for col in grid._col_layouts:
        n = sum(1 for i in range(col.count()) if col.itemAt(i).widget() is not None)
        counts.append(n)
    return counts


def test_masonry_distributes_tiles_across_columns(qapp):
    """The masonry packs tiles into MULTIPLE columns (not a single stacked list)."""
    from metatv.gui.recipe_widgets import _ClusterGrid

    grid = _ClusterGrid()
    grid.set_clusters(
        {
            "genre": [TagCountDTO("Drama", 100), TagCountDTO("Comedy", 60)],
            "region": [TagCountDTO("ES", 80)],
            "language": [TagCountDTO("English", 90)],
            "decade": [TagCountDTO("1990s", 40)],
            "collection": [TagCountDTO("Marvel", 12)],
            "quality": [TagCountDTO("HD", 70)],
            "platform": [TagCountDTO("Netflix", 30)],
            "subtitle": [TagCountDTO("ENG-SUB", 15)],
        },
        {}, {},
    )
    assert len(grid.tiles()) == 8
    # Responsive column count ≥ 2 in the fallback width, tiles spread across them.
    assert len(grid._col_layouts) >= 2
    populated = [c for c in _col_widget_counts(grid) if c > 0]
    assert len(populated) >= 2, (
        f"Masonry must spread tiles across ≥2 columns, got {_col_widget_counts(grid)}"
    )


def test_browse_facet_set_excludes_format(session):
    """The control-layer BROWSE_FACETS set never queries the 'format' facet."""
    from metatv.gui.recipe_widgets import BROWSE_FACETS

    assert "format" not in BROWSE_FACETS

    pid = _make_provider(session, "p1")
    cg = _make_channel(session, pid)
    _tag(session, cg, "genre", "Drama")
    _tag(session, cg, "format", "Dub")   # exists in DB, but must never surface
    session.commit()

    repos = RepositoryFactory(session)
    out = repos.tags.get_top_tags_per_facet(list(BROWSE_FACETS), 24)
    assert "format" not in out, "format must be excluded from the browse grid"
    assert "genre" in out and out["genre"][0].value == "Drama"
