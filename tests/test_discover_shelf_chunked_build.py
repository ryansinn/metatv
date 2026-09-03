"""Behavioral tests for chunked Discover shelf card construction (PERF-17).

``_Shelf._build_ui`` built EVERY card widget synchronously (``DiscoverCard.__init__``
in a straight loop) the instant a shelf's data arrived — the owner sampled this as
multi-second main-thread stalls (3,092 / 3,488 / 6,016ms, 2026-09-03). #712 shipped
``build_chunked``/``ChunkHandle`` (``metatv/gui/chunked_construction.py``) for exactly
this — first batch synchronous, the rest scheduled on ``QTimer.singleShot(0, ...)``
ticks — and named Discover as a planned second adopter. This file proves the
shelf-level wiring: batching, teardown-mid-build, and ``DiscoverView.on_deactivate``
cancelling every live shelf's in-flight build.

Reuses the waiting/cancellation patterns from ``tests/test_chunked_construction.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _cards(n: int) -> list:
    from metatv.core.discovery_engine import ContentCard
    return [
        ContentCard(channel_id=f"ch-{i}", title=f"Title {i}", media_type="movie",
                    thumbnail_url=None, rating=None, year=None, genre=None)
        for i in range(n)
    ]


def _image_cache() -> MagicMock:
    ic = MagicMock()
    ic.get_image_async = MagicMock()
    return ic


# ---------------------------------------------------------------------------
# 1. First batch synchronous, rest after event processing, order preserved
# ---------------------------------------------------------------------------

def test_first_batch_builds_synchronously_rest_after_processing(qapp, qtbot, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.discover_shelf import _CARD_BATCH_SIZE, _Shelf

    cfg = Config(config_dir=tmp_path)
    cards = _cards(40)
    shelf = _Shelf("Drama", "genre:drama", cards, _image_cache(), cfg)
    try:
        assert len(shelf._cards_widgets) == _CARD_BATCH_SIZE, (
            "only the first batch should exist synchronously right after construction"
        )
        assert not shelf._build_handle.done

        qtbot.waitUntil(lambda: shelf._build_handle.done, timeout=2000)

        assert len(shelf._cards_widgets) == 40, "every card must be built once idle"
        built_ids = [w._card.channel_id for w in shelf._cards_widgets]
        assert built_ids == [c.channel_id for c in cards], "build order must match input order"
    finally:
        shelf.deleteLater()


def test_small_card_count_builds_entirely_synchronously(qapp, tmp_path):
    """Fewer cards than one batch — the common case — builds in one shot,
    same as before chunking existed."""
    from metatv.core.config import Config
    from metatv.gui.discover_shelf import _Shelf

    cfg = Config(config_dir=tmp_path)
    cards = _cards(3)
    shelf = _Shelf("Drama", "genre:drama", cards, _image_cache(), cfg)
    try:
        assert len(shelf._cards_widgets) == 3
        assert shelf._build_handle.done
    finally:
        shelf.deleteLater()


# ---------------------------------------------------------------------------
# 2. Teardown mid-build — the real DiscoverView hide path, not a direct call
# ---------------------------------------------------------------------------

def _make_view(tmp_path):
    from metatv.core.config import Config
    from metatv.gui.discover_view import DiscoverView

    cfg = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                 cache_dir=tmp_path / "cache")
    view = DiscoverView(MagicMock(), cfg, MagicMock())
    return view, cfg


def test_hide_requested_mid_build_stops_further_batches_no_error(qapp, qtbot, tmp_path):
    """DiscoverView._on_hide_requested is a real shelf teardown/close path
    (cancel_pending_build() then deleteLater()). Hiding a shelf while its
    chunked build is still in flight (after only the first batch) must never
    build another card and must not raise, even once the widget is destroyed
    mid-build — the liveness guard inside build_chunked."""
    from metatv.gui.discover_view import _ZONE_EXPANDED
    from metatv.gui.discover_shelf import _CARD_BATCH_SIZE, _Shelf

    view, cfg = _make_view(tmp_path)
    shelf = _Shelf("Drama", "genre:drama", _cards(40), _image_cache(), cfg)
    view._shelf_widgets["genre:drama"] = shelf
    view._shelf_zones["genre:drama"] = _ZONE_EXPANDED
    view._expanded_layout.addWidget(shelf)

    assert len(shelf._cards_widgets) == _CARD_BATCH_SIZE, "precondition: build is mid-flight"

    view._on_hide_requested("genre:drama")  # cancels + deleteLater()s the shelf
    qapp.processEvents()  # let the deferred deletion run
    qtbot.wait(200)  # give any (wrongly) still-scheduled batch a chance to fire

    assert len(shelf._cards_widgets) == _CARD_BATCH_SIZE, (
        "hiding mid-build must stop every later batch — no more cards after teardown"
    )


# ---------------------------------------------------------------------------
# 3. on_deactivate cancels every live shelf's in-flight build
# ---------------------------------------------------------------------------

def test_on_deactivate_cancels_every_live_shelf_handle(qapp, tmp_path):
    from metatv.gui.discover_view import _ZONE_EXPANDED, _ZONE_PINNED
    from metatv.gui.discover_shelf import _Shelf

    view, cfg = _make_view(tmp_path)
    shelf_a = _Shelf("Drama", "genre:drama", _cards(40), _image_cache(), cfg)
    shelf_b = _Shelf("Comedy", "genre:comedy", _cards(40), _image_cache(), cfg)
    view._shelf_widgets["genre:drama"] = shelf_a
    view._shelf_widgets["genre:comedy"] = shelf_b
    view._shelf_zones["genre:drama"] = _ZONE_EXPANDED
    view._shelf_zones["genre:comedy"] = _ZONE_PINNED

    assert not shelf_a._build_handle.done
    assert not shelf_b._build_handle.done

    view.on_deactivate()

    assert shelf_a._build_handle._cancelled, "on_deactivate must cancel shelf A's build"
    assert shelf_b._build_handle._cancelled, "on_deactivate must cancel shelf B's build"

    built_a, built_b = len(shelf_a._cards_widgets), len(shelf_b._cards_widgets)
    # Drain anything (wrongly) still queued — cancelled handles must not add
    # further cards no matter how many more event-loop turns run.
    for _ in range(10):
        qapp.processEvents()

    assert len(shelf_a._cards_widgets) == built_a, "cancelled build A must not grow further"
    assert len(shelf_b._cards_widgets) == built_b, "cancelled build B must not grow further"

    shelf_a.deleteLater()
    shelf_b.deleteLater()
