"""Behavioral tests for recipe-view polish (fixes #99 and #100).

#99 — Now-Plating / Show-All context menu
  - Right-clicking a card in the Now-Plating strip emits cardContextMenu on the strip
  - _NowPlatingStrip.cardContextMenu is forwarded to RecipeView.channelContextMenuRequested
  - _BrowseView.cardContextMenu is also forwarded to RecipeView.channelContextMenuRequested

#100 — Pantry filter text box
  - Pantry has a _filter_box QLineEdit attribute
  - Typing in the filter box hides non-matching facet buttons
  - Clearing the filter box restores all facet buttons
  - _PantrySidebar.clear_filter() empties the filter and shows all facets
  - RecipeView.clear_recipe() also clears the Pantry filter
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

def test_now_plating_strip_has_card_context_menu_signal(qapp):
    """_NowPlatingStrip exposes a cardContextMenu(str, int, int) signal."""
    from metatv.gui.recipe_view import _NowPlatingStrip
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

    strip = _NowPlatingStrip(_FakeCache(), _FakeCfg())
    # Signal must exist with 3 args (channel_id, gx, gy).
    captured: list[tuple] = []
    strip.cardContextMenu.connect(lambda cid, gx, gy: captured.append((cid, gx, gy)))
    strip.cardContextMenu.emit("chan_1", 100, 200)
    assert captured == [("chan_1", 100, 200)]


def test_now_plating_card_context_menu_wired_on_load_results(qapp):
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
    card_widget = view._now_plating._card_widgets[0]
    card_widget.contextMenuRequested.emit("chan_42", 55, 77)

    assert captured == [("chan_42", 55, 77)], (
        "Right-clicking a Now-Plating card must emit channelContextMenuRequested"
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
# #100 — Pantry filter text box
# ---------------------------------------------------------------------------

def test_pantry_has_filter_box(qapp):
    """_PantrySidebar has a _filter_box QLineEdit attribute."""
    from metatv.gui.recipe_view import _PantrySidebar
    from PyQt6.QtWidgets import QLineEdit
    pantry = _PantrySidebar()
    assert hasattr(pantry, "_filter_box"), "_PantrySidebar must have _filter_box"
    assert isinstance(pantry._filter_box, QLineEdit)


def test_pantry_filter_hides_non_matching_facets(qapp):
    """Typing in the filter box hides facet buttons whose name doesn't match."""
    view, seam = _make_view(qapp)
    view._active = True

    summaries = [
        _FacetSummaryDTO("genre", 100),
        _FacetSummaryDTO("language", 50),
        _FacetSummaryDTO("region", 75),
    ]
    view._on_pantry_loaded(summaries)
    buttons = view._pantry._facet_buttons
    assert len(buttons) == 3

    # Type "lang" — only the "Language" button should remain visible.
    # Use isHidden() (explicit hide state) instead of isVisible() which requires a
    # shown window hierarchy — in headless tests, all widgets report isVisible()=False.
    view._pantry._filter_box.setText("lang")
    not_hidden = [b for b in buttons if not b.isHidden()]
    explicitly_hidden = [b for b in buttons if b.isHidden()]

    assert len(not_hidden) == 1, (
        f"Expected 1 visible facet, got {[b.facet_type for b in not_hidden]}"
    )
    assert not_hidden[0].facet_type == "language"
    assert len(explicitly_hidden) == 2


def test_pantry_filter_restore_on_clear(qapp):
    """Clearing the filter box restores visibility of all facet buttons."""
    view, seam = _make_view(qapp)
    view._active = True

    summaries = [
        _FacetSummaryDTO("genre", 100),
        _FacetSummaryDTO("language", 50),
    ]
    view._on_pantry_loaded(summaries)
    buttons = view._pantry._facet_buttons

    # Filter to narrow list, then clear.
    # Use isHidden() for headless compatibility (isVisible() needs a shown window).
    view._pantry._filter_box.setText("genre")
    assert sum(1 for b in buttons if not b.isHidden()) == 1

    view._pantry._filter_box.clear()
    assert all(not b.isHidden() for b in buttons), (
        "All facet buttons must be un-hidden after clearing the filter"
    )


def test_pantry_clear_filter_method(qapp):
    """_PantrySidebar.clear_filter() empties the filter box and shows all facets."""
    view, seam = _make_view(qapp)
    view._active = True

    summaries = [
        _FacetSummaryDTO("genre", 120),
        _FacetSummaryDTO("platform", 30),
    ]
    view._on_pantry_loaded(summaries)
    view._pantry._filter_box.setText("genre")

    # At least one button hidden by the filter (use isHidden() for headless compat).
    assert any(b.isHidden() for b in view._pantry._facet_buttons)

    view._pantry.clear_filter()

    assert view._pantry._filter_box.text() == "", "clear_filter must empty the text box"
    assert all(not b.isHidden() for b in view._pantry._facet_buttons), (
        "All facet buttons must be un-hidden after clear_filter()"
    )


def test_clear_recipe_also_clears_pantry_filter(qapp):
    """RecipeView.clear_recipe() also clears the Pantry filter text box."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"

    summaries = [
        _FacetSummaryDTO("genre", 100),
        _FacetSummaryDTO("language", 50),
        _FacetSummaryDTO("region", 75),
    ]
    view._on_pantry_loaded(summaries)

    # Set filter text and recipe ingredients.
    view._pantry._filter_box.setText("lan")
    view._recipe_includes = {"genre": {"Drama"}}

    # clear_recipe must reset both the recipe AND the pantry filter.
    view.clear_recipe()

    assert view._pantry._filter_box.text() == "", (
        "clear_recipe() must clear the Pantry filter text box"
    )
    assert all(not b.isHidden() for b in view._pantry._facet_buttons), (
        "All Pantry facets must be un-hidden after clear_recipe()"
    )
    assert not view.recipe_includes, "Recipe includes must be empty after clear_recipe()"
