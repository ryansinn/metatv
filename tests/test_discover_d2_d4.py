"""Behavioral tests for Discover-view improvements D2 and D4.

D4 — Re-collapsed shelves jump to the top of the collapsed zone.
D2 — Collapsed strips are buffered during streaming load; batch-built afterwards
     to eliminate the "counting up" stutter.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_card(i: int):
    from metatv.core.discovery_engine import ContentCard
    return ContentCard(
        channel_id=f"ch-{i}",
        title=f"Movie {i}",
        media_type="movie",
        thumbnail_url=None,
        rating=7.5,
        year=2020,
        genre="Test",
    )


def _make_image_cache():
    ic = MagicMock()
    ic.get_image_async = MagicMock()
    return ic


def _make_shelf_data(key: str, title: str, *, header_only: bool = False):
    """Return a minimal _ShelfData for testing."""
    from metatv.gui.discover_workers import _ShelfData
    return _ShelfData(
        title=title,
        shelf_key=key,
        cards=[],
        header_only=header_only,
    )


def _make_discover_view(qapp, *, collapse_to_top: bool = True):
    """Construct a DiscoverView without a real DB / loader thread."""
    from metatv.core.config import Config
    from metatv.gui.discover_view import DiscoverView

    cfg = Config()
    cfg.discover_collapse_to_top = collapse_to_top

    ic = _make_image_cache()

    db = MagicMock()

    view = DiscoverView.__new__(DiscoverView)
    # Manually initialise everything __init__ normally does.
    from PyQt6.QtWidgets import QWidget
    QWidget.__init__(view)
    view._db = db
    view._config = cfg
    view._image_cache = ic
    view._thread = None
    view._see_all_thread = None
    view._see_all_worker = None
    view._expand_thread = None
    view._expand_worker = None
    view._inflight_expand = None
    view._loaded = False
    from metatv.core.discovery_engine import ContentCard
    view._shelf_data_cache = {}
    view._loaded_shelf_keys = set()
    view._shelf_widgets = {}
    view._shelf_zones = {}
    view._pending_collapsed = []
    view._batch_timer = None
    view._setup_ui()
    return view, cfg


# ---------------------------------------------------------------------------
# D4 — at_top placement
# ---------------------------------------------------------------------------

class TestCollapseToTop:
    """D4: re-collapsed shelves land at the top of the collapsed zone."""

    def _build_collapsed_shelf(self, view, key: str, title: str):
        """Place a real _Shelf widget into the collapsed zone via _on_shelf_ready
        (using a non-header_only shelf so it builds immediately), then move it
        to the collapsed zone to simulate an initial collapsed shelf."""
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui import theme as _theme
        from metatv.gui.discover_view import _ZONE_COLLAPSED
        shelf = _Shelf(title, key, [], view._image_cache, view._config, collapsed=True)
        view._shelf_widgets[key] = shelf
        view._shelf_zones[key] = _ZONE_COLLAPSED
        view._collapsed_layout.addWidget(shelf)
        view._update_more_btn()
        return shelf

    def test_user_collapse_inserts_at_top_when_flag_is_true(self, qapp):
        """With collapse_to_top=True, re-collapsing a shelf puts it at index 0."""
        from metatv.gui.discover_view import _ZONE_EXPANDED, _ZONE_COLLAPSED

        view, cfg = _make_discover_view(qapp, collapse_to_top=True)
        assert cfg.discover_collapse_to_top is True

        # Seed two already-collapsed shelves (bottom of list) so we can verify
        # the re-collapsed shelf lands at top (index 0), not at end.
        self._build_collapsed_shelf(view, "genre:Drama", "Drama")
        self._build_collapsed_shelf(view, "genre:Horror", "Horror")

        # Now place a shelf in the *expanded* zone (simulates a shelf the user
        # had expanded earlier), then re-collapse it via _move_shelf.
        from metatv.gui.discover_shelf import _Shelf
        target = _Shelf("Action", "genre:Action", [], view._image_cache, view._config,
                        collapsed=False)
        view._shelf_widgets["genre:Action"] = target
        view._shelf_zones["genre:Action"] = _ZONE_EXPANDED
        view._expanded_layout.addWidget(target)

        view._move_shelf("genre:Action", _ZONE_COLLAPSED)

        # The re-collapsed shelf must be at index 0 of the collapsed layout.
        item = view._collapsed_layout.itemAt(0)
        assert item is not None, "collapsed layout must not be empty"
        assert item.widget() is target, (
            "re-collapsed shelf must be at index 0 of the collapsed layout "
            f"when discover_collapse_to_top=True; got {item.widget()!r}"
        )

    def test_user_collapse_appends_when_flag_is_false(self, qapp):
        """With collapse_to_top=False, re-collapsing a shelf appends to the end."""
        from metatv.gui.discover_view import _ZONE_EXPANDED, _ZONE_COLLAPSED

        view, cfg = _make_discover_view(qapp, collapse_to_top=False)
        assert cfg.discover_collapse_to_top is False

        # Seed two already-collapsed shelves.
        self._build_collapsed_shelf(view, "genre:Drama", "Drama")
        self._build_collapsed_shelf(view, "genre:Horror", "Horror")

        from metatv.gui.discover_shelf import _Shelf
        target = _Shelf("Action", "genre:Action", [], view._image_cache, view._config,
                        collapsed=False)
        view._shelf_widgets["genre:Action"] = target
        view._shelf_zones["genre:Action"] = _ZONE_EXPANDED
        view._expanded_layout.addWidget(target)

        view._move_shelf("genre:Action", _ZONE_COLLAPSED)

        count = view._collapsed_layout.count()
        last_item = view._collapsed_layout.itemAt(count - 1)
        assert last_item is not None
        assert last_item.widget() is target, (
            "re-collapsed shelf must append to the end of the collapsed layout "
            f"when discover_collapse_to_top=False; got {last_item.widget()!r} at last pos"
        )

    def test_initial_load_placement_always_appends_in_order(self, qapp):
        """Batch-built initial-load shelves append in natural order (at_top=False)."""
        from metatv.gui.discover_view import _ZONE_COLLAPSED

        view, cfg = _make_discover_view(qapp, collapse_to_top=True)

        # Buffer three collapsed strips in order.
        keys = ["genre:Drama", "genre:Horror", "genre:Action"]
        for key in keys:
            data = _make_shelf_data(key, key.split(":")[1], header_only=True)
            view._pending_collapsed.append(data)

        # Flush the batch (same as the timer firing).
        view._flush_pending_collapsed()

        count = view._collapsed_layout.count()
        assert count == len(keys), f"expected {len(keys)} collapsed strips, got {count}"

        for i, key in enumerate(keys):
            item = view._collapsed_layout.itemAt(i)
            assert item is not None
            shelf = item.widget()
            assert shelf is not None
            assert shelf._shelf_key == key, (
                f"initial-load shelf at index {i} should have key {key!r}, "
                f"got {shelf._key!r} — order must be preserved, not reversed"
            )

    def test_add_to_zone_at_top_inserts_at_index_zero(self, qapp):
        """_add_to_zone with at_top=True inserts at position 0."""
        from metatv.gui.discover_view import _ZONE_COLLAPSED
        from metatv.gui.discover_shelf import _Shelf

        view, cfg = _make_discover_view(qapp)

        shelf_a = _Shelf("A", "genre:A", [], view._image_cache, view._config, collapsed=True)
        shelf_b = _Shelf("B", "genre:B", [], view._image_cache, view._config, collapsed=True)

        # Add A first (at_top=False = normal append).
        view._collapsed_layout.addWidget(shelf_a)
        # Now add B at_top=True → must be at index 0, before A.
        view._add_to_zone(shelf_b, _ZONE_COLLAPSED, at_top=True)

        assert view._collapsed_layout.itemAt(0).widget() is shelf_b, (
            "shelf added with at_top=True must be at index 0"
        )
        assert view._collapsed_layout.itemAt(1).widget() is shelf_a, (
            "previously appended shelf must shift to index 1"
        )

    def test_add_to_zone_at_top_false_appends(self, qapp):
        """_add_to_zone with at_top=False (default) appends."""
        from metatv.gui.discover_view import _ZONE_COLLAPSED
        from metatv.gui.discover_shelf import _Shelf

        view, cfg = _make_discover_view(qapp)

        shelf_a = _Shelf("A", "genre:A", [], view._image_cache, view._config, collapsed=True)
        shelf_b = _Shelf("B", "genre:B", [], view._image_cache, view._config, collapsed=True)

        view._collapsed_layout.addWidget(shelf_a)
        view._add_to_zone(shelf_b, _ZONE_COLLAPSED, at_top=False)

        assert view._collapsed_layout.itemAt(0).widget() is shelf_a
        assert view._collapsed_layout.itemAt(1).widget() is shelf_b, (
            "shelf added with at_top=False must append to the end"
        )


# ---------------------------------------------------------------------------
# D2 — collapsed-strip buffering
# ---------------------------------------------------------------------------

class TestCollapsedStripBuffering:
    """D2: header_only shelves are buffered; batch-built in one pass."""

    def test_header_only_shelves_buffered_not_built_immediately(self, qapp):
        """header_only _ShelfData must land in _pending_collapsed, not _collapsed_layout."""
        view, cfg = _make_discover_view(qapp)

        # Feed several collapsed strips.
        keys = ["genre:Drama", "genre:Horror", "genre:Action"]
        for key in keys:
            data = _make_shelf_data(key, key.split(":")[1], header_only=True)
            view._on_shelf_ready(data)

        assert view._collapsed_layout.count() == 0, (
            "_collapsed_layout must be empty while strips are still buffered — "
            f"got {view._collapsed_layout.count()} widgets"
        )
        assert len(view._pending_collapsed) == len(keys), (
            f"all {len(keys)} header_only shelves must be in _pending_collapsed, "
            f"got {len(view._pending_collapsed)}"
        )
        # No widgets built yet.
        for key in keys:
            assert key not in view._shelf_widgets, (
                f"shelf widget for {key!r} must not exist before batch flush"
            )

    def test_more_btn_count_reflects_pending_total(self, qapp):
        """More Categories count includes both built and pending collapsed strips."""
        from metatv.gui.discover_view import _ZONE_COLLAPSED
        from metatv.gui.discover_shelf import _Shelf

        view, cfg = _make_discover_view(qapp)

        # Add one already-built collapsed strip.
        shelf_a = _Shelf("A", "genre:A", [], view._image_cache, view._config, collapsed=True)
        view._collapsed_layout.addWidget(shelf_a)

        # Buffer two pending strips.
        for key in ["genre:Drama", "genre:Horror"]:
            view._pending_collapsed.append(
                _make_shelf_data(key, key.split(":")[1], header_only=True)
            )
        view._update_more_btn()

        btn_text = view._more_btn.text()
        assert "3" in btn_text, (
            f"More Categories button must show total count (built + pending = 3), "
            f"got: {btn_text!r}"
        )

    def test_flush_builds_all_pending_strips(self, qapp):
        """After _flush_pending_collapsed, all strips exist and pending is empty."""
        view, cfg = _make_discover_view(qapp)

        keys = ["genre:Drama", "genre:Horror", "genre:Action", "decade:1990"]
        for key in keys:
            data = _make_shelf_data(key, key.split(":")[-1], header_only=True)
            view._pending_collapsed.append(data)

        # Directly invoke the batch builder (replaces "timer fires").
        view._flush_pending_collapsed()

        assert view._pending_collapsed == [], (
            "_pending_collapsed must be empty after flush"
        )
        assert view._collapsed_layout.count() == len(keys), (
            f"all {len(keys)} strips must be in _collapsed_layout after flush, "
            f"got {view._collapsed_layout.count()}"
        )
        for key in keys:
            assert key in view._shelf_widgets, (
                f"shelf widget for {key!r} must exist in _shelf_widgets after flush"
            )
            assert key in view._shelf_zones, (
                f"shelf zone for {key!r} must be recorded in _shelf_zones after flush"
            )

    def test_non_header_only_shelf_builds_immediately(self, qapp):
        """A non-collapsed shelf (with cards) still builds immediately — not buffered."""
        from metatv.gui.discover_workers import _ShelfData

        view, cfg = _make_discover_view(qapp)

        data = _ShelfData(
            title="Recently Added",
            shelf_key="recently_added",
            cards=[_make_card(0), _make_card(1)],
            header_only=False,
        )
        view._on_shelf_ready(data)

        assert "recently_added" in view._shelf_widgets, (
            "non-header_only shelf must be built immediately (not buffered)"
        )
        assert view._pending_collapsed == [], (
            "non-header_only shelf must not enter the pending buffer"
        )

    def test_flush_is_idempotent_when_called_twice(self, qapp):
        """Calling _flush_pending_collapsed twice does not duplicate widgets."""
        view, cfg = _make_discover_view(qapp)

        for key in ["genre:Drama", "genre:Horror"]:
            view._pending_collapsed.append(
                _make_shelf_data(key, key.split(":")[1], header_only=True)
            )

        view._flush_pending_collapsed()
        count_after_first = view._collapsed_layout.count()

        # Second flush — pending is already empty, should be a no-op.
        view._flush_pending_collapsed()
        count_after_second = view._collapsed_layout.count()

        assert count_after_first == count_after_second == 2, (
            "second flush must not add duplicate widgets; "
            f"got {count_after_first} after first flush, {count_after_second} after second"
        )

    def test_pending_hide_removes_from_buffer_without_flush(self, qapp):
        """Hiding a pending shelf removes it from the buffer, not via full flush."""
        view, cfg = _make_discover_view(qapp)

        keys = ["genre:Drama", "genre:Horror", "genre:Action"]
        for key in keys:
            view._pending_collapsed.append(
                _make_shelf_data(key, key.split(":")[1], header_only=True)
            )

        # Hide the middle one while still pending.
        view._on_hide_requested("genre:Horror")

        remaining_keys = [d.shelf_key for d in view._pending_collapsed]
        assert "genre:Horror" not in remaining_keys, (
            "hidden shelf must be removed from pending buffer"
        )
        assert len(remaining_keys) == 2, (
            f"two shelves must remain in buffer; got {remaining_keys}"
        )
        # Widget must not have been built for the hidden shelf.
        assert "genre:Horror" not in view._shelf_widgets

    def test_expand_pending_shelf_flushes_batch(self, qapp):
        """Expanding a shelf that's still pending flushes the batch first."""
        view, cfg = _make_discover_view(qapp)

        keys = ["genre:Drama", "genre:Horror", "genre:Action"]
        for key in keys:
            view._pending_collapsed.append(
                _make_shelf_data(key, key.split(":")[1], header_only=True)
            )

        # Patch _start_expand_fetch so we don't need a real DB.
        view._start_expand_fetch = MagicMock()

        # Expand "genre:Horror" while it's still pending.
        view._on_expand_requested("genre:Horror")

        # All shelves must now be built (flush triggered).
        assert view._pending_collapsed == [], "pending buffer must be empty after expand"
        for key in keys:
            assert key in view._shelf_widgets, (
                f"all shelves must be built after expand-triggered flush; missing {key!r}"
            )

        # The expanded shelf must be in the expanded zone.
        from metatv.gui.discover_view import _ZONE_EXPANDED
        assert view._shelf_zones.get("genre:Horror") == _ZONE_EXPANDED, (
            "expanded shelf must be in the expanded zone"
        )
