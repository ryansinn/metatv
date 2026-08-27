"""Behavioral tests for the RecipeView masonry redesign layout + entry paths.

Covers the layout the redesign locked in (porting the HTML mockup):

  (a) Two sub-tabs (Recipe | Saved) over a tab stack; the Recipe tab is a
      builder (masonry grid + one-line recipe bar + Matching Content shelf) over
      the "Show all" browse takeover — and the old two-column splitters are gone.
  (b) A preset-tag entry (``seed_facet`` — the details-pane tag right-click seam)
      lands on the *content-first* browse page, and the "Build recipe" affordance
      returns to the builder.
  (c) A nav-chip entry (``on_activate`` with no preset tag) lands on the builder.
  (d) Switching to the Saved tab renders the saved-recipes panel.

The DB worker half is stubbed by a fake ``_run_query`` seam; what matters here is
the layout wiring + the stack page a given entry path lands on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QScrollArea, QStackedWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ── Fakes ──────────────────────────────────────────────────────────────────

class _FakeSeam:
    """Records _run_query calls; supports synchronous delivery in tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None) -> None:
        if token_ref is not None:
            token_ref[0] += 1
        self.calls.append({"on_result": on_result, "token_ref": token_ref, "on_error": on_error})

    def deliver_to(self, on_result: Callable, data: Any) -> None:
        for entry in reversed(self.calls):
            if entry["on_result"] == on_result:
                entry["on_result"](data)
                return
        raise AssertionError(f"No _run_query for {on_result!r}")


@dataclass
class _FakeCard:
    channel_id: str
    title: str
    media_type: str = "movie"
    thumbnail_url: str | None = None
    rating: float | None = None
    year: int | None = None
    genre: str | None = None
    is_favorite: bool = False
    in_queue: bool = False
    already_watched: bool = False
    is_liked: bool = False
    detected_prefix: str | None = None
    progress_fraction: float = 0.0
    variant_count: int = 1


class _FakeConfig:
    """Duck-typed config with the presentation fields the cards/browse read."""

    discover_zoom = 1.0
    global_filter_paused = True   # → empty exclusion sets (no Config plumbing needed)
    saved_recipes: list = []
    movie_icon = "🎬"
    series_icon = "📺"
    rating_star_icon = "★"
    like_icon = "👍"
    favorite_icon = "❤"
    queue_icon = "▶"
    watched_icon = "✓"
    list_view_icon = "☰"
    grid_view_icon = "▦"

    def save(self) -> None:
        pass


class _FakeImageCache(QObject):
    image_loaded = pyqtSignal(str, object)
    image_failed = pyqtSignal(str, str)

    def get_image_async(self, url):  # noqa: D401 - stub
        pass


def _make_view(qapp, config=None):
    from metatv.gui.recipe_view import RecipeView

    seam = _FakeSeam()
    view = RecipeView(
        db=object(),
        config=config if config is not None else _FakeConfig(),
        run_query_fn=seam._run_query,
        image_cache=_FakeImageCache(),
        parent=None,
    )
    return view, seam


# ── (a) Tabbed masonry structure; no legacy splitters ───────────────────────

def test_tabbed_layout_structure(qapp):
    """The view is a Recipe|Saved tab bar over a tab stack; the Recipe tab holds
    the builder (masonry grid + one-line recipe bar + Matching shelf) over the
    "Show all" browse takeover."""
    from metatv.gui.recipe_bar_widgets import _MatchingShelf, _RecipeBar, _RecipeTabBar
    from metatv.gui.recipe_saved_widgets import _SavedRecipesPanel
    from metatv.gui.recipe_widgets import _ClusterGrid

    view, _seam = _make_view(qapp)

    # Two-tab bar over a two-page tab stack.
    assert isinstance(view._tab_bar, _RecipeTabBar)
    assert isinstance(view._tab_stack, QStackedWidget)
    assert view._tab_stack.count() == 2

    # Recipe tab (index 0) holds an inner builder/browse stack.
    assert isinstance(view._stack, QStackedWidget)
    assert view._stack.count() == 2

    # Builder widgets are present and correctly typed.
    assert isinstance(view._cluster_grid, _ClusterGrid)
    assert isinstance(view._recipe_bar, _RecipeBar)
    assert isinstance(view._matching, _MatchingShelf)
    assert isinstance(view._saved_panel, _SavedRecipesPanel)

    # The drill/search cloud lives inside the center stack's cloud page.
    assert view._top_stack.count() == 2
    cloud_page = view._top_stack.widget(1)
    assert isinstance(cloud_page, QScrollArea) and cloud_page.widget() is view._cloud


def test_no_legacy_splitters(qapp):
    """The old two-column splitters are gone (masonry replaces them)."""
    view, _seam = _make_view(qapp)
    assert not hasattr(view, "_main_splitter")
    assert not hasattr(view, "_col1_splitter")
    assert not hasattr(view, "_content_splitter")


def test_masonry_shows_all_browse_facets_no_format(qapp):
    """The masonry grid renders a tile per browse facet, and never 'format'."""
    from metatv.core.repositories.dtos import TagCountDTO

    view, seam = _make_view(qapp)
    view._active = True
    view.on_activate()
    seam.deliver_to(view._on_clusters_loaded, {
        "genre": [TagCountDTO("Drama", 100)],
        "region": [TagCountDTO("ES", 80)],
        "language": [TagCountDTO("English", 90)],
        "decade": [TagCountDTO("1990s", 40)],
        "collection": [TagCountDTO("Marvel", 12)],
        "quality": [TagCountDTO("HD", 70)],
        "platform": [TagCountDTO("Netflix", 30)],
        "subtitle": [TagCountDTO("ENG-SUB", 15)],
        "format": [TagCountDTO("Dub", 9)],   # even if delivered, format is not a tile
    })
    facets = {t.facet_type() for t in view._cluster_grid.tiles()}
    assert "format" not in facets, "Format must be excluded from the browse grid"
    assert {"genre", "region", "language", "decade",
            "collection", "quality", "platform", "subtitle"} <= facets


# ── (b) Content-first tag entry + affordance ────────────────────────────────

def test_seed_facet_lands_content_first(qapp):
    """seed_facet (the details-pane tag seam) lands on the browse page, applies
    the tag as the recipe ingredient, and fills the browse grid from the teaser."""
    view, seam = _make_view(qapp)
    view._active = True
    view.on_activate()  # nav lands on the builder first…

    view.seed_facet("genre", "Drama")

    # Content-first: on the browse page (stack index 1), NOT the builder.
    assert view._stack.currentIndex() == 1
    assert view._stack.currentWidget() is view._browse
    # The clicked tag is applied as the single recipe ingredient.
    assert view.recipe_includes == {"genre": {"Drama"}}

    # When the async results land, the browse grid is seeded with the matches.
    seam.deliver_to(view._on_results_loaded,
                    ([_FakeCard("c1", "A"), _FakeCard("c2", "B")], 2))
    assert [c.channel_id for c in view._browse._all_cards] == ["c1", "c2"]


def test_content_first_affordance_returns_to_builder(qapp):
    """The browse page carries a 'Build recipe' affordance that returns to the
    builder (stack page 0) with the seeded ingredient intact."""
    view, _seam = _make_view(qapp)
    view._active = True
    view.seed_facet("genre", "Drama")
    assert view._stack.currentIndex() == 1

    assert "Build recipe" in view._browse._back_btn.text()
    view._browse.backRequested.emit()
    assert view._stack.currentIndex() == 0
    assert view.recipe_includes == {"genre": {"Drama"}}


# ── (c) Nav-chip entry lands on the builder ─────────────────────────────────

def test_nav_chip_entry_lands_on_builder(qapp):
    """Opening via the Recipe nav chip (on_activate, no preset tag) lands on the
    Recipe tab's builder (stack page 0), not the content-first browse page."""
    view, _seam = _make_view(qapp)
    view._active = True
    view._stack.setCurrentIndex(1)          # simulate a prior browse state
    view._tab_bar.set_index(1)
    view._show_tab(1)   # …and a prior Saved tab

    view.on_activate()

    assert view._tab_stack.currentIndex() == 0, "Nav-chip entry lands on the Recipe tab"
    assert view._stack.currentIndex() == 0, "…and on the builder, not the browse page"


# ── (d) Saved-tab switch renders the saved panel ────────────────────────────

def test_saved_tab_switch_renders_panel(qapp):
    """Clicking the Saved tab switches the tab stack and renders the saved cards."""
    config = _FakeConfig()
    config.saved_recipes = [
        {"name": "R1", "includes": {"genre": ["Drama"]}, "excludes": {}},
    ]
    view, _seam = _make_view(qapp, config=config)
    view._active = True

    # Emit the tab-change signal (what clicking the Saved pill does).
    view._tab_bar.tab_changed.emit(1)

    assert view._tab_stack.currentIndex() == 1
    assert len(view._saved_panel.cards()) == 1
