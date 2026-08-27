"""Behavioral tests for recipe-view polish (fixes #99 and #100).

#99 — Now-Plating / Show-All context menu
  - Right-clicking a card in the Now-Plating strip emits cardContextMenu on the strip
  - _NowPlatingStrip.cardContextMenu is forwarded to RecipeView.channelContextMenuRequested
  - _BrowseView.cardContextMenu is also forwarded to RecipeView.channelContextMenuRequested

#100 — cross-facet tag search box (relocated above the cluster grid)
  - _TagSearchBar exposes a _box QLineEdit with a clear button
  - RecipeView.clear_recipe() also clears the cross-facet search box
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Module-level qapp fixture (headless Qt)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Minimal stubs (shared with the existing test_recipe_view.py helpers)
# ---------------------------------------------------------------------------

class _FakeSeam:
    def __init__(self):
        self.calls: list[dict] = []

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
        if token_ref is not None:
            token_ref[0] += 1
        self.calls.append(dict(query_fn=query_fn, on_result=on_result,
                                token_ref=token_ref, on_error=on_error))

    def deliver_last(self, data):
        entry = self.calls[-1]
        entry["on_result"](data)


@dataclass(frozen=True)
class _FacetSummaryDTO:
    facet_type: str
    distinct_values: int


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


def _make_view(qapp):
    from metatv.gui.recipe_view import RecipeView
    from PyQt6.QtCore import QObject, pyqtSignal

    seam = _FakeSeam()

    class _FakeDB:
        pass

    class _FakeConfig:
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

    class _FakeImageCacheQ(QObject):
        image_loaded = pyqtSignal(str, object)
        image_failed = pyqtSignal(str, str)

        def get_image_async(self, url):
            pass

    view = RecipeView(
        db=_FakeDB(),
        config=_FakeConfig(),
        run_query_fn=seam._run_query,
        image_cache=_FakeImageCacheQ(),
        parent=None,
    )
    return view, seam


# ---------------------------------------------------------------------------
# #99 — Now-Plating card context menu
# ---------------------------------------------------------------------------

def test_matching_shelf_has_card_context_menu_signal(qapp):
    """_MatchingShelf exposes a cardContextMenu(str, int, int) signal."""
    from metatv.gui.recipe_bar_widgets import _MatchingShelf
    from PyQt6.QtCore import QObject, pyqtSignal

    class _FakeCache(QObject):
        image_loaded = pyqtSignal(str, object)
        image_failed = pyqtSignal(str, str)
        def get_image_async(self, url): pass

    class _FakeCfg:
        discover_zoom = 1.0
        movie_icon = "🎬"
        series_icon = "📺"
        rating_star_icon = "★"
        like_icon = "👍"
        favorite_icon = "❤"
        queue_icon = "▶"
        watched_icon = "✓"

    shelf = _MatchingShelf(_FakeCache(), _FakeCfg())
    # Signal must exist with 3 args (channel_id, gx, gy).
    captured: list[tuple] = []
    shelf.cardContextMenu.connect(lambda cid, gx, gy: captured.append((cid, gx, gy)))
    shelf.cardContextMenu.emit("chan_1", 100, 200)
    assert captured == [("chan_1", 100, 200)]


def test_matching_card_context_menu_wired_on_load_results(qapp):
    """After load_results, right-clicking a card emits RecipeView.channelContextMenuRequested."""
    view, seam = _make_view(qapp)
    view._active = True

    captured: list[tuple] = []
    view.channelContextMenuRequested.connect(
        lambda cid, gx, gy: captured.append((cid, gx, gy))
    )

    cards = [_FakeCard("chan_42", "Test Channel")]
    view._on_results_loaded((cards, 1))

    # Simulate a right-click context-menu event on the card widget.
    card_widget = view._matching._card_widgets[0]
    card_widget.contextMenuRequested.emit("chan_42", 55, 77)

    assert captured == [("chan_42", 55, 77)], (
        "Right-clicking a Matching Content card must emit channelContextMenuRequested"
    )


def test_browse_card_context_menu_forwarded_to_recipe_view(qapp):
    """_browse.cardContextMenu is forwarded to RecipeView.channelContextMenuRequested."""
    view, seam = _make_view(qapp)

    captured: list[tuple] = []
    view.channelContextMenuRequested.connect(
        lambda cid, gx, gy: captured.append((cid, gx, gy))
    )

    # Emit from the browse sub-view's cardContextMenu signal directly.
    view._browse.cardContextMenu.emit("browse_chan", 10, 20)

    assert captured == [("browse_chan", 10, 20)], (
        "_browse.cardContextMenu must be wired to channelContextMenuRequested"
    )


def test_recipe_view_has_channel_context_menu_required_signal(qapp):
    """RecipeView exposes channelContextMenuRequested(str, int, int)."""
    view, seam = _make_view(qapp)
    captured: list = []
    view.channelContextMenuRequested.connect(lambda *a: captured.append(a))
    view.channelContextMenuRequested.emit("c1", 1, 2)
    assert captured == [("c1", 1, 2)]


# ---------------------------------------------------------------------------
# Cross-facet tag search box (relocated above the cluster grid)
# ---------------------------------------------------------------------------

def test_search_bar_has_box(qapp):
    """_TagSearchBar exposes a QLineEdit search box with a clear button."""
    from metatv.gui.recipe_widgets import _TagSearchBar
    from PyQt6.QtWidgets import QLineEdit
    bar = _TagSearchBar()
    assert isinstance(bar._box, QLineEdit)
    assert bar._box.isClearButtonEnabled()


def test_clear_recipe_also_clears_search_box(qapp):
    """RecipeView.clear_recipe() also clears the cross-facet search box."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"

    # Set search text and recipe ingredients.
    view._search_box._box.setText("lan")
    view._search_query = "lan"
    view._recipe_includes = {"genre": {"Drama"}}

    # clear_recipe must reset both the recipe AND the search box.
    view.clear_recipe()

    assert view._search_box.text() == "", (
        "clear_recipe() must clear the cross-facet search box"
    )
    assert view._search_query == ""
    assert not view.recipe_includes, "Recipe includes must be empty after clear_recipe()"
