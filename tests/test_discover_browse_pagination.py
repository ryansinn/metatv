"""Behavioral tests for _BrowseView lazy-pagination additions (recipe Show all).

The additions are ADDITIVE — Discover still calls only ``load()`` and never
connects ``loadMoreRequested``, so its behaviour is unchanged.  These tests
exercise the new main-thread machinery the recipe "Show all" page drives:

  - ``append(cards)`` grows both the grid pending-card list and the list widget
    WITHOUT clearing the existing cards.
  - ``loadMoreRequested`` fires near-bottom only when ``set_has_more(True)``,
    and is debounced (one emit per near-bottom, not per scroll tick).
  - A fresh ``load()`` resets the pagination state (has_more / pending).
"""

from __future__ import annotations

import pytest

from metatv.core.discovery_engine import ContentCard


# ---------------------------------------------------------------------------
# Headless Qt + minimal stubs (mirrors tests/test_recipe_view.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


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


def _make_image_cache():
    from PyQt6.QtCore import QObject, pyqtSignal

    class _FakeImageCacheQ(QObject):
        image_loaded = pyqtSignal(str, object)
        image_failed = pyqtSignal(str, str)

        def get_image_async(self, url):
            pass

    return _FakeImageCacheQ()


def _make_browse(qapp):
    from metatv.gui.discover_browse import _BrowseView
    return _BrowseView(_make_image_cache(), _FakeConfig())


def _cards(prefix: str, n: int) -> list[ContentCard]:
    return [
        ContentCard(
            channel_id=f"{prefix}{i}",
            title=f"{prefix} title {i}",
            media_type="movie",
            thumbnail_url=None,   # None → no async poster load attempted
            rating=None,
            year=None,
            genre=None,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# append() grows both surfaces without clearing
# ---------------------------------------------------------------------------

def test_append_grows_grid_and_list_without_clearing(qapp):
    view = _make_browse(qapp)
    view.load("Title", _cards("a", 5))

    assert len(view._all_pending_cards) == 5
    assert view._list_widget.count() == 5

    view.append(_cards("b", 7))

    # Grid pending list extended (not replaced).
    assert len(view._all_pending_cards) == 12
    pending_ids = [c.channel_id for c in view._all_pending_cards]
    assert pending_ids[:5] == [f"a{i}" for i in range(5)]
    assert pending_ids[5:] == [f"b{i}" for i in range(7)]
    # List widget grown to match.
    assert view._list_widget.count() == 12
    # _all_cards (the filter source) also grew.
    assert len(view._all_cards) == 12


def test_append_empty_is_a_noop(qapp):
    view = _make_browse(qapp)
    view.load("Title", _cards("a", 3))
    view.append([])
    assert len(view._all_pending_cards) == 3
    assert view._list_widget.count() == 3


# ---------------------------------------------------------------------------
# loadMoreRequested: gated on set_has_more, debounced
# ---------------------------------------------------------------------------

def test_load_more_not_emitted_without_has_more(qapp):
    view = _make_browse(qapp)
    view.load("Title", _cards("a", 3))
    fired: list[int] = []
    view.loadMoreRequested.connect(lambda: fired.append(1))

    # has_more defaults False → near-bottom must NOT emit.
    sb = view._grid_scroll.verticalScrollBar()
    sb.setRange(0, 1000)
    sb.setValue(1000)            # at the very bottom
    view._maybe_request_more(sb)
    assert fired == []


def test_load_more_emitted_near_bottom_when_has_more(qapp):
    view = _make_browse(qapp)
    view.load("Title", _cards("a", 3))
    fired: list[int] = []
    view.loadMoreRequested.connect(lambda: fired.append(1))

    view.set_has_more(True)
    sb = view._grid_scroll.verticalScrollBar()
    sb.setRange(0, 1000)
    sb.setPageStep(100)
    sb.setValue(1000)            # near/at the bottom
    view._maybe_request_more(sb)
    assert fired == [1]


def test_load_more_debounced_until_set_has_more_rearms(qapp):
    view = _make_browse(qapp)
    view.load("Title", _cards("a", 3))
    fired: list[int] = []
    view.loadMoreRequested.connect(lambda: fired.append(1))

    view.set_has_more(True)
    sb = view._grid_scroll.verticalScrollBar()
    sb.setRange(0, 1000)
    sb.setPageStep(100)
    sb.setValue(1000)

    view._maybe_request_more(sb)   # fires once
    view._maybe_request_more(sb)   # debounced — _load_more_pending is True
    assert fired == [1]

    # Caller appended the page and re-armed: another near-bottom may fire again.
    view.set_has_more(True)
    view._maybe_request_more(sb)
    assert fired == [1, 1]


def test_load_more_not_emitted_far_from_bottom(qapp):
    view = _make_browse(qapp)
    view.load("Title", _cards("a", 3))
    fired: list[int] = []
    view.loadMoreRequested.connect(lambda: fired.append(1))

    view.set_has_more(True)
    sb = view._grid_scroll.verticalScrollBar()
    sb.setRange(0, 1000)
    sb.setPageStep(100)
    sb.setValue(0)               # top of the scroll → not near bottom
    view._maybe_request_more(sb)
    assert fired == []


def test_list_scroll_also_triggers_load_more(qapp):
    view = _make_browse(qapp)
    view.load("Title", _cards("a", 3))
    fired: list[int] = []
    view.loadMoreRequested.connect(lambda: fired.append(1))

    view.set_has_more(True)
    lsb = view._list_widget.verticalScrollBar()
    lsb.setRange(0, 1000)
    lsb.setPageStep(100)
    lsb.setValue(1000)
    view._maybe_request_more_list()
    assert fired == [1]


# ---------------------------------------------------------------------------
# A fresh load() resets pagination state
# ---------------------------------------------------------------------------

def test_fresh_load_resets_has_more_and_pending(qapp):
    view = _make_browse(qapp)
    view.load("Title", _cards("a", 3))
    view.set_has_more(True)
    view._load_more_pending = True

    # A fresh load (e.g. a new recipe page-1 seed) starts clean.
    view.load("Title 2", _cards("z", 4))
    assert view._has_more is False
    assert view._load_more_pending is False
    assert [c.channel_id for c in view._all_cards] == [f"z{i}" for i in range(4)]


# ---------------------------------------------------------------------------
# Fix B: preserve_filter keeps search-box text across a filter-triggered reseed
# (QA regression 10bc0a7)
# ---------------------------------------------------------------------------

def test_load_clears_filter_by_default(qapp):
    """Default load() (fresh recipe entry / recipe change) clears the search box."""
    view = _make_browse(qapp)
    view._search_box.setText("drama")
    assert view.current_filter() == "drama"

    view.load("Title", _cards("a", 5))
    assert view.current_filter() == "", (
        "Default load() must clear the search box so a fresh recipe page starts unfiltered"
    )


def test_load_preserve_filter_keeps_search_box_text(qapp):
    """load(preserve_filter=True) keeps the search-box text across a filter reseed.

    This is Fix B for QA bug 10bc0a7: when the user types a filter and the DB
    reseed calls load(..., preserve_filter=True), current_filter() must still
    return the typed text so that subsequent lazy pages (_load_more_see_all)
    thread the filter into their query and don't load unfiltered content.
    """
    view = _make_browse(qapp)
    view._search_box.setText("drama")

    view.load("Filtered Results", _cards("a", 5), preserve_filter=True)

    assert view.current_filter() == "drama", (
        "preserve_filter=True must keep the search-box text so lazy pages "
        "can read current_filter() and stay filtered"
    )


def test_filter_reseed_preserves_text_so_lazy_page_stays_filtered(qapp):
    """Simulate the full Fix B scenario: filter → reseed → lazy page all reads same filter.

    Sequence:
      1. User opens Show All (no filter yet).
      2. User types "drama" → _apply_filter fires → filterChanged emitted.
      3. Caller fetches filtered page-1 and calls load(..., preserve_filter=True).
      4. User scrolls → _load_more_see_all reads current_filter() → must be "drama".
    """
    view = _make_browse(qapp)
    view.load("Show All", _cards("a", 5))   # initial, no filter

    # User types filter — simulates the filterChanged signal being processed
    view._search_box.setText("drama")

    # Caller delivers filtered page-1 with preserve_filter=True.
    view.load("Filtered Results", _cards("b", 5), preserve_filter=True)

    # After the filtered reseed, current_filter() must still return "drama"
    # so _load_more_see_all threads it into the next page query.
    assert view.current_filter() == "drama", (
        "current_filter() must return the typed filter after a preserve_filter reseed; "
        "without this, _load_more_see_all would load unfiltered content on the next scroll"
    )


# ---------------------------------------------------------------------------
# Clear button wires correctly
# ---------------------------------------------------------------------------

def test_clear_button_clears_search_box_and_filter(qapp):
    """Clicking the clear button empties _search_box and resets current_filter."""
    view = _make_browse(qapp)
    view.load("Title", _cards("dark", 5))

    view._search_box.setText("dark")
    assert view._search_box.text() == "dark"

    # Simulate a click: call the connected slot directly (no event loop needed).
    view._clear_btn.clicked.emit()

    assert view._search_box.text() == ""
    assert view.current_filter() == ""
