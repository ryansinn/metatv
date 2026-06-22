"""Behavior tests for the per-source channel-list filter toggle.

Clicking the active source a second time deselects it (toggle OFF); clicking a
different source switches the filter without a clear; edit-mode routes to the
editor instead of touching the filter.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(selected_provider_id=None, in_edit_mode=False):
    """Return a SimpleNamespace that quacks like the relevant slice of MainWindow."""
    load_channels = MagicMock()
    sources = SimpleNamespace(clear_selection=MagicMock())
    provider_editor = MagicMock()
    me = SimpleNamespace(
        selected_provider_id=selected_provider_id,
        _in_provider_edit_mode=in_edit_mode,
        load_channels=load_channels,
        sidebar_sections={"sources": sources},
        provider_editor=provider_editor,
        _save_search_state=MagicMock(),  # added by _ChannelListMixin
    )
    return me, load_channels, sources, provider_editor


# ---------------------------------------------------------------------------
# on_provider_selected_new — toggle behaviour
# ---------------------------------------------------------------------------

def test_first_click_sets_filter():
    """First click on a source activates the per-source filter (toggle ON)."""
    from metatv.gui.main_window import MainWindow

    me, load_channels, sources, _ = _make_window(selected_provider_id=None)
    MainWindow.on_provider_selected_new(me, "p1")

    assert me.selected_provider_id == "p1"
    load_channels.assert_called_once_with("p1")
    sources.clear_selection.assert_not_called()


def test_second_click_on_active_source_clears_filter():
    """Clicking the already-active source toggles the filter OFF."""
    from metatv.gui.main_window import MainWindow

    me, load_channels, sources, _ = _make_window(selected_provider_id="p1")
    MainWindow.on_provider_selected_new(me, "p1")

    assert me.selected_provider_id is None
    load_channels.assert_called_once_with(None)
    sources.clear_selection.assert_called_once()


def test_click_different_source_switches_filter():
    """Clicking a source different from the active one switches (not toggles)."""
    from metatv.gui.main_window import MainWindow

    me, load_channels, sources, _ = _make_window(selected_provider_id="p1")
    MainWindow.on_provider_selected_new(me, "p2")

    assert me.selected_provider_id == "p2"
    load_channels.assert_called_once_with("p2")
    sources.clear_selection.assert_not_called()


def test_falsy_provider_id_does_not_toggle_off():
    """An empty/falsy provider_id should not be treated as a toggle-off."""
    from metatv.gui.main_window import MainWindow

    me, load_channels, sources, _ = _make_window(selected_provider_id="p1")
    # Empty string → falls into the else branch (not the toggle guard), switches to "".
    MainWindow.on_provider_selected_new(me, "")

    # selected_provider_id becomes "" (the new value), not None
    assert me.selected_provider_id == ""
    load_channels.assert_called_once_with("")
    sources.clear_selection.assert_not_called()


def test_edit_mode_routes_to_editor_not_filter():
    """In provider-edit mode, clicking a source loads the editor, not the filter."""
    from metatv.gui.main_window import MainWindow

    me, load_channels, sources, provider_editor = _make_window(
        selected_provider_id=None, in_edit_mode=True
    )
    MainWindow.on_provider_selected_new(me, "p1")

    provider_editor.load_provider.assert_called_once_with("p1")
    # No filter state change
    assert me.selected_provider_id is None
    load_channels.assert_not_called()
    sources.clear_selection.assert_not_called()


def test_edit_mode_does_not_change_existing_filter():
    """Edit-mode click must not disturb an already-active filter."""
    from metatv.gui.main_window import MainWindow

    me, load_channels, _, provider_editor = _make_window(
        selected_provider_id="p1", in_edit_mode=True
    )
    MainWindow.on_provider_selected_new(me, "p2")

    # Filter cursor unchanged
    assert me.selected_provider_id == "p1"
    load_channels.assert_not_called()


def test_no_sources_section_does_not_crash_on_toggle_off():
    """If the sources section is absent from sidebar_sections, toggle-off is still safe."""
    from metatv.gui.main_window import MainWindow

    load_channels = MagicMock()
    me = SimpleNamespace(
        selected_provider_id="p1",
        _in_provider_edit_mode=False,
        load_channels=load_channels,
        sidebar_sections={},          # no "sources" key
        provider_editor=MagicMock(),
        _save_search_state=MagicMock(),
    )
    MainWindow.on_provider_selected_new(me, "p1")

    assert me.selected_provider_id is None
    load_channels.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# SourcesSection.clear_selection — widget behaviour (needs headless Qt)
# ---------------------------------------------------------------------------

def test_clear_selection_leaves_no_current_item(qapp):
    """clear_selection() removes the row selection from the QTreeWidget."""
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
    from PyQt6.QtCore import Qt

    # Build a minimal tree with one item selected.
    tree = QTreeWidget()
    item = QTreeWidgetItem(tree)
    item.setText(0, "Provider A")
    item.setData(0, Qt.ItemDataRole.UserRole, "pa")
    tree.setCurrentItem(item)

    assert tree.currentItem() is item   # sanity: item is selected

    # Now wire it to a minimal SourcesSection stub and call clear_selection.
    from metatv.gui.sidebar.sources import SourcesSection
    sec = SourcesSection.__new__(SourcesSection)
    sec.sources_tree = tree

    sec.clear_selection()

    assert tree.currentItem() is None
    assert len(tree.selectedItems()) == 0
