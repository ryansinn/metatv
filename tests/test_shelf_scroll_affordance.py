"""A Discover shelf shows a visible way to reach the rest of the row.

macOS draws scrollbars as OVERLAYS — they appear while scrolling and fade out —
so ``ScrollBarAsNeeded`` leaves a shelf with no affordance at rest and a
scrollable row reads as the whole content. Owner report: "the scroll bar on
shelves doesn't appear on MacOS."

The fix is a real control rather than a forced-visible scrollbar, so it behaves
identically on every platform instead of depending on a per-OS scrollbar style.

These assert RENDERED GEOMETRY, not just that widgets exist: a button that is
constructed but sits at (0,0) under the first card, or one that never hides at
the end of the row, passes any existence check while looking wrong.
"""

from __future__ import annotations


import pytest

from metatv.core.config import Config
from metatv.core.discovery_engine import ContentCard
from metatv.gui.discover_shelf import _Shelf

BTN_MARGIN = 2


def _cards(n: int) -> list[ContentCard]:
    return [
        ContentCard(channel_id=f"c{i}", title=f"Title {i}", media_type="movie",
                    thumbnail_url=None, rating=None, year=None, genre=None)
        for i in range(n)
    ]


@pytest.fixture()
def shelf(qapp, tmp_path):
    """A shelf wide enough to overflow, actually shown so geometry is real."""
    cfg = Config(config_dir=tmp_path)
    sh = _Shelf("Drama", "genre:drama", _cards(40), None, cfg)
    sh.resize(800, 300)
    sh.show()
    qapp.processEvents()
    sh._sync_page_buttons()
    qapp.processEvents()
    yield sh
    sh.deleteLater()


def test_the_row_actually_overflows(shelf):
    """Precondition — without this the rest of the file proves nothing."""
    bar = shelf._scroll_area.horizontalScrollBar()
    assert bar.maximum() > bar.minimum(), "the row fits; there is nothing to page"


def test_the_right_chevron_is_pinned_to_the_right_edge(shelf, qapp):
    """Position, not existence: a button at x=0 would sit under the first card."""
    vw = shelf._scroll_area.viewport().width()
    btn = shelf._page_right
    assert btn.isVisible(), "no way to reach the rest of the row"
    expected = vw - btn.width() - BTN_MARGIN
    assert btn.x() == expected, f"right chevron at x={btn.x()}, expected {expected}"
    assert btn.x() + btn.width() <= vw, "the chevron is off the edge of the row"


def test_the_chevron_is_vertically_centred_in_the_row(shelf):
    vp_h = shelf._scroll_area.viewport().height()
    btn = shelf._page_right
    centre_offset = btn.y() + btn.height() // 2
    assert abs(centre_offset - vp_h // 2) <= 2, (
        f"chevron centred at {centre_offset}, row centre is {vp_h // 2}"
    )
    assert btn.height() >= 24, "too small to hit comfortably"


def test_no_left_chevron_at_the_start_of_the_row(shelf):
    """Hidden rather than disabled — a dead control over artwork reads as a card."""
    assert not shelf._page_left.isVisible()


def test_paging_moves_about_one_screenful_and_reveals_the_left_chevron(shelf, qapp):
    bar = shelf._scroll_area.horizontalScrollBar()
    vw = shelf._scroll_area.viewport().width()
    shelf._page(1)
    qapp.processEvents()
    shelf._sync_page_buttons()

    assert bar.value() > 0, "paging right did not move the row"
    assert abs(bar.value() - (vw - 40)) <= 1, (
        f"moved {bar.value()}px; a page is the viewport width less an overlap"
    )
    assert shelf._page_left.isVisible(), "there is room to go back but no way to"


def test_the_right_chevron_disappears_at_the_end(shelf, qapp):
    bar = shelf._scroll_area.horizontalScrollBar()
    bar.setValue(bar.maximum())
    qapp.processEvents()
    shelf._sync_page_buttons()

    assert not shelf._page_right.isVisible(), "offers to scroll past the last card"
    assert shelf._page_left.isVisible()


def test_a_short_row_shows_no_chevrons_at_all(qapp, tmp_path):
    """Two cards fit; the shelf must not sprout controls it does not need."""
    sh = _Shelf("Drama", "genre:drama", _cards(2), None, Config(config_dir=tmp_path))
    sh.resize(1200, 300)
    sh.show()
    qapp.processEvents()
    sh._sync_page_buttons()
    try:
        assert not sh._page_left.isVisible()
        assert not sh._page_right.isVisible()
    finally:
        sh.deleteLater()


def test_the_chevrons_use_the_shared_icon_and_theme_role(shelf):
    """Not a literal glyph and not a raw stylesheet (CLAUDE.md)."""
    from metatv.gui import icons as _icons

    assert shelf._page_left.text() == _icons.nav_prev_icon
    assert shelf._page_right.text() == _icons.nav_next_icon
    assert shelf._page_right.toolTip(), "an icon-only control needs a tooltip"
