"""Behavioral tests — inline clear button standardization.

Pins the convention that every filter/search QLineEdit uses
setClearButtonEnabled(True) [isClearButtonEnabled() must return True] (the built-in inline × provided by Qt) and that
the existing clear_filter() public API still works correctly after the removal
of the bespoke external clear buttons.

Boxes covered:
  * _PantrySidebar._filter_box          (recipe_view.py)
  * WeightedTagCloud._filter_edit        (weighted_tag_cloud.py)
  * _BrowseView._search_box             (discover_browse.py)
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Module-level qapp fixture (headless Qt)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

class _FakeConfig:
    """Minimal config stub sufficient for widget construction."""
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


class _FakeImageCache:
    """Stub that accepts image-cache calls without side effects."""

    def get_image_async(self, url: str) -> None:  # noqa: ANN001
        pass


# ---------------------------------------------------------------------------
# _PantrySidebar._filter_box — recipe Pantry facet filter
# ---------------------------------------------------------------------------

def test_pantry_filter_box_has_clear_button(qapp):
    """_PantrySidebar._filter_box must have isClearButtonEnabled() == True."""
    from metatv.gui.recipe_view import _PantrySidebar
    pantry = _PantrySidebar()
    assert pantry._filter_box.isClearButtonEnabled(), (
        "_PantrySidebar._filter_box must call setClearButtonEnabled(True) [isClearButtonEnabled() must return True]"
    )


def test_pantry_clear_filter_still_works(qapp):
    """clear_filter() must empty the text box after the external button was removed."""
    from metatv.gui.recipe_view import _PantrySidebar
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _FacetSummaryDTO:
        facet_type: str
        distinct_values: int

    pantry = _PantrySidebar()
    pantry.load_facets([_FacetSummaryDTO("genre", 100), _FacetSummaryDTO("region", 50)])
    pantry._filter_box.setText("genre")
    assert pantry._filter_box.text() == "genre"
    pantry.clear_filter()
    assert pantry._filter_box.text() == "", (
        "clear_filter() must empty the filter box"
    )
    assert all(not b.isHidden() for b in pantry._facet_buttons), (
        "clear_filter() must make all facet buttons visible"
    )


# ---------------------------------------------------------------------------
# WeightedTagCloud._filter_edit — recipe tag-cloud filter
# ---------------------------------------------------------------------------

def test_tag_cloud_filter_edit_has_clear_button(qapp):
    """WeightedTagCloud._filter_edit must have isClearButtonEnabled() == True."""
    from metatv.gui.weighted_tag_cloud import WeightedTagCloud
    cloud = WeightedTagCloud()
    assert cloud._filter_edit.isClearButtonEnabled(), (
        "WeightedTagCloud._filter_edit must call setClearButtonEnabled(True) [isClearButtonEnabled() must return True]"
    )


def test_tag_cloud_clear_filter_still_works(qapp):
    """WeightedTagCloud.clear_filter() must reset the filter box to empty."""
    from metatv.gui import theme as _theme
    from metatv.gui.weighted_tag_cloud import WeightedTagCloud
    cloud = WeightedTagCloud()
    cloud.set_tags(
        [("Drama", 100, "none"), ("Comedy", 80, "none"), ("Action", 60, "none")],
        facet_color=_theme.COLOR_ACCENT_TEAL,
        facet_name="Genre",
    )
    cloud._filter_edit.setText("drama")
    assert cloud._filter_edit.text() == "drama"
    cloud.clear_filter()
    assert cloud._filter_edit.text() == "", (
        "clear_filter() must empty the filter text"
    )


# ---------------------------------------------------------------------------
# _BrowseView._search_box — Discover Browse drill-down filter
# ---------------------------------------------------------------------------

def test_browse_view_search_box_has_clear_button(qapp):
    """_BrowseView._search_box must have isClearButtonEnabled() == True."""
    from metatv.gui.discover_browse import _BrowseView
    view = _BrowseView(image_cache=_FakeImageCache(), config=_FakeConfig())
    assert view._search_box.isClearButtonEnabled(), (
        "_BrowseView._search_box must call setClearButtonEnabled(True) [isClearButtonEnabled() must return True]"
    )
