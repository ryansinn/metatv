"""Behavioral tests for the Discover pin-implies-expand zone state machine.

Guards the three core invariants:

1. ``pin ⟹ (pinned zone, expanded, cards loaded)``
   Pinning a collapsed (header-only) shelf puts it in the pinned zone AND
   triggers a card fetch; the shelf is never left in the collapsed state.

2. ``pinned ∧ collapsed`` is impossible
   After ``_move_shelf(key, _ZONE_PINNED)``, the shelf widget's ``_collapsed``
   flag must be False.

3. ``_sanitize_zone_config`` enforces mutual exclusion
   A key that appears in both ``pinned`` and ``collapsed`` config lists is
   removed from the lower-priority list (collapsed), so the view and config
   agree after sanitisation.

4. Default expansion includes ``recently_added``, ``top_movies``, ``top_series``
   on first launch.

5. Manage-dialog ``_transfer`` to pinned removes the key from expanded/collapsed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config(tmp_path):
    """Isolated config that writes to tmp_path, not ~/.config/metatv."""
    from metatv.core.config import Config
    return Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                  cache_dir=tmp_path / "cache")


# ---------------------------------------------------------------------------
# Helper — a minimal DiscoverView with no DB / image-cache wiring
# ---------------------------------------------------------------------------

def _build_view(qapp, config):
    """Build a DiscoverView using __new__ to skip real DB / thread start."""
    from metatv.gui.discover_view import DiscoverView
    view = DiscoverView.__new__(DiscoverView)
    view._config = config
    view._shelf_widgets = {}
    view._shelf_zones   = {}
    view._loaded_shelf_keys = set()
    view._inflight_expand   = None
    view._pending_collapsed = []
    view._batch_timer       = None
    view._more_expanded     = False  # needed by _update_more_btn
    return view


# ---------------------------------------------------------------------------
# 1. pin ⟹ expand: card fetch is triggered when pinning a header-only shelf
# ---------------------------------------------------------------------------

class TestPinTriggersCardFetch:

    def test_pin_collapsed_shelf_starts_card_fetch(self, qapp, config):
        """_on_pin_requested must start _start_expand_fetch for an unloaded shelf."""
        from metatv.gui.discover_view import DiscoverView, _ZONE_COLLAPSED, _ZONE_PINNED
        from metatv.gui.discover_shelf import _Shelf

        view = _build_view(qapp, config)

        # Build a header-only shelf in the collapsed zone.
        image_cache = MagicMock()
        shelf = _Shelf("Recently Added", "recently_added", [],
                       image_cache, config, collapsed=True)
        view._shelf_widgets["recently_added"] = shelf
        view._shelf_zones["recently_added"]   = _ZONE_COLLAPSED

        # Wire minimal zone containers so _move_shelf can call _add/_remove.
        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        for attr in ("_pinned_zone", "_expanded_zone", "_collapsed_zone"):
            w = QWidget()
            setattr(view, attr, w)
        for attr in ("_pinned_layout", "_expanded_layout", "_collapsed_layout"):
            setattr(view, attr, QVBoxLayout())
        view._more_btn = MagicMock()
        view._config.discover_collapse_to_top = True

        fetched: list[str] = []

        def _fake_fetch(shelf_key):
            fetched.append(shelf_key)

        view._start_expand_fetch = _fake_fetch

        view._on_pin_requested("recently_added")

        # The shelf must now be in the pinned zone.
        assert view._shelf_zones.get("recently_added") == _ZONE_PINNED, (
            f"shelf must be in pinned zone, got {view._shelf_zones.get('recently_added')!r}"
        )
        # A card fetch must have been started.
        assert "recently_added" in fetched, (
            "_start_expand_fetch must be called when pinning an unloaded shelf"
        )

    def test_pin_loaded_shelf_no_double_fetch(self, qapp, config):
        """Pinning an already-loaded shelf must NOT start a redundant card fetch."""
        from metatv.gui.discover_view import _ZONE_EXPANDED, _ZONE_PINNED
        from metatv.gui.discover_shelf import _Shelf

        view = _build_view(qapp, config)
        image_cache = MagicMock()
        shelf = _Shelf("Top Movies", "top_movies", [],
                       image_cache, config, collapsed=False)
        view._shelf_widgets["top_movies"] = shelf
        view._shelf_zones["top_movies"]   = _ZONE_EXPANDED
        # Mark as already loaded.
        view._loaded_shelf_keys.add("top_movies")

        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        for attr in ("_pinned_zone", "_expanded_zone", "_collapsed_zone"):
            setattr(view, attr, QWidget())
        for attr in ("_pinned_layout", "_expanded_layout", "_collapsed_layout"):
            setattr(view, attr, QVBoxLayout())
        view._more_btn = MagicMock()

        fetched: list[str] = []
        view._start_expand_fetch = lambda k: fetched.append(k)

        view._on_pin_requested("top_movies")

        assert fetched == [], (
            "_start_expand_fetch must NOT be called when the shelf is already loaded"
        )


# ---------------------------------------------------------------------------
# 2. pinned ∧ collapsed is impossible after _move_shelf
# ---------------------------------------------------------------------------

class TestMoveShelfPinImpliesExpanded:

    def test_move_to_pinned_uncollapses_shelf(self, qapp, config):
        """_move_shelf(key, PINNED) must set set_collapsed(False) on the widget."""
        from metatv.gui.discover_view import _ZONE_COLLAPSED, _ZONE_PINNED
        from metatv.gui.discover_shelf import _Shelf

        view = _build_view(qapp, config)
        image_cache = MagicMock()
        shelf = _Shelf("Genre", "genre:Action", [],
                       image_cache, config, collapsed=True)
        view._shelf_widgets["genre:Action"] = shelf
        view._shelf_zones["genre:Action"]   = _ZONE_COLLAPSED

        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        for attr in ("_pinned_zone", "_expanded_zone", "_collapsed_zone"):
            w = QWidget()
            setattr(view, attr, w)
        for attr in ("_pinned_layout", "_expanded_layout", "_collapsed_layout"):
            setattr(view, attr, QVBoxLayout())
        view._more_btn = MagicMock()

        # Before: collapsed.
        assert shelf._collapsed is True

        view._move_shelf("genre:Action", _ZONE_PINNED)

        # After: not collapsed (pin ⟹ expand).
        assert shelf._collapsed is False, (
            "A shelf moved to the pinned zone must not be collapsed"
        )
        assert shelf._pinned is True, (
            "A shelf moved to the pinned zone must have _pinned=True"
        )

    def test_move_to_collapsed_sets_collapsed_true(self, qapp, config):
        """_move_shelf(key, COLLAPSED) sets collapsed=True on the widget."""
        from metatv.gui.discover_view import _ZONE_EXPANDED, _ZONE_COLLAPSED
        from metatv.gui.discover_shelf import _Shelf

        view = _build_view(qapp, config)
        image_cache = MagicMock()
        shelf = _Shelf("Genre", "genre:Drama", [],
                       image_cache, config, collapsed=False)
        view._shelf_widgets["genre:Drama"] = shelf
        view._shelf_zones["genre:Drama"]   = _ZONE_EXPANDED

        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        for attr in ("_pinned_zone", "_expanded_zone", "_collapsed_zone"):
            setattr(view, attr, QWidget())
        for attr in ("_pinned_layout", "_expanded_layout", "_collapsed_layout"):
            setattr(view, attr, QVBoxLayout())
        view._more_btn = MagicMock()

        assert shelf._collapsed is False
        view._move_shelf("genre:Drama", _ZONE_COLLAPSED)
        assert shelf._collapsed is True


# ---------------------------------------------------------------------------
# 3. _sanitize_zone_config enforces mutual exclusion
# ---------------------------------------------------------------------------

class TestSanitizeZoneConfig:

    def test_key_in_pinned_and_collapsed_removed_from_collapsed(self, config):
        """A key that is in both pinned and collapsed is removed from collapsed."""
        from metatv.gui.discover_view import DiscoverView

        config.discover_pinned_shelves    = ["recently_added", "top_movies"]
        config.discover_expanded_shelves  = []
        config.discover_collapsed_shelves = ["recently_added", "genre:Action"]
        config.discover_hidden_shelves    = []

        view = DiscoverView.__new__(DiscoverView)
        view._config = config
        view._sanitize_zone_config()

        # recently_added was in both pinned and collapsed; must be removed from collapsed.
        assert "recently_added" not in config.discover_collapsed_shelves, (
            "A key in pinned must be removed from collapsed after sanitisation"
        )
        # genre:Action was only in collapsed — must stay.
        assert "genre:Action" in config.discover_collapsed_shelves
        # top_movies was only in pinned — must stay.
        assert "top_movies" in config.discover_pinned_shelves
        # recently_added must remain in pinned.
        assert "recently_added" in config.discover_pinned_shelves

    def test_key_in_pinned_and_expanded_removed_from_expanded(self, config):
        """A key in both pinned and expanded is removed from expanded."""
        from metatv.gui.discover_view import DiscoverView

        config.discover_pinned_shelves    = ["top_movies"]
        config.discover_expanded_shelves  = ["top_movies", "recently_added"]
        config.discover_collapsed_shelves = []
        config.discover_hidden_shelves    = []

        view = DiscoverView.__new__(DiscoverView)
        view._config = config
        view._sanitize_zone_config()

        assert "top_movies" not in config.discover_expanded_shelves, (
            "A key in pinned must be removed from expanded after sanitisation"
        )
        assert "recently_added" in config.discover_expanded_shelves

    def test_expanded_key_removed_from_collapsed(self, config):
        """A key in both expanded and collapsed is removed from collapsed."""
        from metatv.gui.discover_view import DiscoverView

        config.discover_pinned_shelves    = []
        config.discover_expanded_shelves  = ["genre:Action"]
        config.discover_collapsed_shelves = ["genre:Action", "genre:Drama"]
        config.discover_hidden_shelves    = []

        view = DiscoverView.__new__(DiscoverView)
        view._config = config
        view._sanitize_zone_config()

        assert "genre:Action" not in config.discover_collapsed_shelves
        assert "genre:Drama" in config.discover_collapsed_shelves

    def test_duplicate_entries_deduped(self, config):
        """Duplicate keys within a single list are removed."""
        from metatv.gui.discover_view import DiscoverView

        config.discover_pinned_shelves    = ["top_movies", "top_movies", "recently_added"]
        config.discover_expanded_shelves  = []
        config.discover_collapsed_shelves = []
        config.discover_hidden_shelves    = []

        view = DiscoverView.__new__(DiscoverView)
        view._config = config
        view._sanitize_zone_config()

        assert config.discover_pinned_shelves.count("top_movies") == 1, (
            "Duplicate entries must be deduplicated within the pinned list"
        )


# ---------------------------------------------------------------------------
# 4. Default expanded set includes recently_added, top_movies, top_series
# ---------------------------------------------------------------------------

class TestDefaultExpandedSet:

    def test_default_expanded_includes_key_shelves(self):
        """_DEFAULT_EXPANDED must include recently_added, top_movies, top_series."""
        from metatv.gui.discover_view import _DEFAULT_EXPANDED

        for key in ("recently_added", "top_movies", "top_series"):
            assert key in _DEFAULT_EXPANDED, (
                f"'{key}' must be in _DEFAULT_EXPANDED for sensible first-run defaults"
            )

    def test_first_launch_defaults_top_series_expanded(self):
        """On first launch, top_series maps to the expanded zone."""
        from metatv.gui.discover_workers import determine_zone, _ZONE_EXPANDED
        from metatv.gui.discover_view import _DEFAULT_EXPANDED

        zone = determine_zone(
            "top_series",
            pinned=frozenset(),
            expanded=frozenset(),
            collapsed=frozenset(),
            hidden=frozenset(),
            default_expanded=_DEFAULT_EXPANDED,
            first_launch=True,
        )
        assert zone == _ZONE_EXPANDED, (
            f"top_series must map to expanded on first launch, got {zone!r}"
        )

    def test_first_launch_genre_still_collapsed(self):
        """On first launch, genre shelves default to the collapsed zone."""
        from metatv.gui.discover_workers import determine_zone, _ZONE_COLLAPSED
        from metatv.gui.discover_view import _DEFAULT_EXPANDED

        zone = determine_zone(
            "genre:Action",
            pinned=frozenset(),
            expanded=frozenset(),
            collapsed=frozenset(),
            hidden=frozenset(),
            default_expanded=_DEFAULT_EXPANDED,
            first_launch=True,
        )
        assert zone == _ZONE_COLLAPSED, (
            f"genre:Action must map to collapsed on first launch, got {zone!r}"
        )


# ---------------------------------------------------------------------------
# 5. Manage-dialog _transfer to pinned cleans other lists
# ---------------------------------------------------------------------------

class TestManageDialogTransferToPinned:

    def _build_dialog(self, config):
        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        from metatv.gui.discover_filter_dialog import DiscoverManageDialog
        dlg = DiscoverManageDialog.__new__(DiscoverManageDialog)
        dlg._config   = config
        dlg._pinned   = config.discover_pinned_shelves
        dlg._expanded = config.discover_expanded_shelves
        dlg._collapsed = config.discover_collapsed_shelves
        dlg._hidden   = config.discover_hidden_shelves
        dlg._titles   = {}
        dlg._row_widgets = {}
        dlg._changed  = False
        # The _transfer mutual-exclusion guard reads these containers to clean
        # up stale row widgets when a key appears in multiple zones.
        for attr in ("_pinned_list", "_expanded_list", "_collapsed_list", "_hidden_list"):
            w = QWidget()
            w.setLayout(QVBoxLayout())
            setattr(dlg, attr, w)
        return dlg

    def test_transfer_collapsed_to_pinned_removes_from_collapsed(self, qapp, config):
        """Transferring a shelf from collapsed to pinned removes it from collapsed."""
        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        from metatv.gui.discover_filter_dialog import _ShelfRow

        config.discover_pinned_shelves    = []
        config.discover_expanded_shelves  = []
        config.discover_collapsed_shelves = ["genre:Action"]
        config.discover_hidden_shelves    = []

        dlg = self._build_dialog(config)

        # Build minimal src/dst container widgets.
        src_container = QWidget()
        src_container.setLayout(QVBoxLayout())
        dst_container = QWidget()
        dst_container.setLayout(QVBoxLayout())

        # Put a stale row into the collapsed container.
        stale_row = _ShelfRow("genre:Action", "genre:Action")
        src_container.layout().addWidget(stale_row)
        dlg._row_widgets["genre:Action"] = stale_row

        # Patch _commit so it doesn't touch the real filesystem.
        dlg._commit = MagicMock()
        dlg._build_pinned_row = lambda k: _ShelfRow(k, k)
        dlg._sync_empty_label = MagicMock()
        dlg._add_empty_label  = MagicMock()

        # Transfer from collapsed to pinned.
        dlg._transfer(
            "genre:Action",
            dlg._collapsed, src_container,
            dlg._pinned,    dst_container,
            dlg._build_pinned_row,
        )

        assert "genre:Action" in dlg._pinned, "key must be in pinned after transfer"
        assert "genre:Action" not in dlg._collapsed, (
            "key must be removed from collapsed after transfer to pinned"
        )

    def test_transfer_pinned_deduped_from_expanded(self, qapp, config):
        """If a key is in both expanded and collapsed (inconsistent config), pinning
        it removes it from both other lists via the mutual-exclusion guard."""
        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        from metatv.gui.discover_filter_dialog import _ShelfRow

        # Simulate an inconsistent state: key in expanded AND collapsed.
        config.discover_pinned_shelves    = []
        config.discover_expanded_shelves  = ["recently_added"]
        config.discover_collapsed_shelves = ["recently_added", "genre:Drama"]
        config.discover_hidden_shelves    = []

        dlg = self._build_dialog(config)

        src_container = QWidget()
        src_container.setLayout(QVBoxLayout())
        dst_container = QWidget()
        dst_container.setLayout(QVBoxLayout())

        stale_row = _ShelfRow("recently_added", "recently_added")
        src_container.layout().addWidget(stale_row)
        dlg._row_widgets["recently_added"] = stale_row

        dlg._commit = MagicMock()
        dlg._build_pinned_row = lambda k: _ShelfRow(k, k)
        dlg._sync_empty_label = MagicMock()
        dlg._add_empty_label  = MagicMock()

        # Transfer from expanded to pinned.
        dlg._transfer(
            "recently_added",
            dlg._expanded, src_container,
            dlg._pinned,   dst_container,
            dlg._build_pinned_row,
        )

        assert "recently_added" in dlg._pinned
        assert "recently_added" not in dlg._expanded
        assert "recently_added" not in dlg._collapsed, (
            "pin transfer must also remove key from collapsed (mutual-exclusion guard)"
        )
        # genre:Drama must be untouched.
        assert "genre:Drama" in dlg._collapsed


# ---------------------------------------------------------------------------
# 6. un-pinning returns to EXPANDED, not COLLAPSED
# ---------------------------------------------------------------------------

class TestUnpinReturnsToExpanded:

    def test_unpin_moves_to_expanded_zone(self, qapp, config):
        """_on_unpin_requested must move the shelf to _ZONE_EXPANDED, not COLLAPSED."""
        from metatv.gui.discover_view import _ZONE_PINNED, _ZONE_EXPANDED
        from metatv.gui.discover_shelf import _Shelf

        view = _build_view(qapp, config)
        image_cache = MagicMock()
        shelf = _Shelf("Recently Added", "recently_added", [],
                       image_cache, config, pinned=True, collapsed=False)
        view._shelf_widgets["recently_added"] = shelf
        view._shelf_zones["recently_added"]   = _ZONE_PINNED

        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        for attr in ("_pinned_zone", "_expanded_zone", "_collapsed_zone"):
            setattr(view, attr, QWidget())
        for attr in ("_pinned_layout", "_expanded_layout", "_collapsed_layout"):
            setattr(view, attr, QVBoxLayout())
        view._more_btn = MagicMock()

        view._on_unpin_requested("recently_added")

        assert view._shelf_zones.get("recently_added") == _ZONE_EXPANDED, (
            "Un-pinning must move the shelf to the expanded zone"
        )
        assert shelf._pinned is False
        assert shelf._collapsed is False, "Un-pinned shelf must not be collapsed"
