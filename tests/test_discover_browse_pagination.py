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
