"""Regression tests for the series-drill stacking bug.

When double-clicking a series result card from the Recipe view (or Discover),
``switch_to_series_view`` used to leave the overlay visible, stacking the
series tree on top of it.  These tests pin the corrected behaviour:

1. ``switch_to_series_view`` calls ``_hide_all_content_views`` first, which
   deactivates and hides the recipe_view (or any other content overlay).
2. After the call, ``series_tree`` is visible and ``recipe_view`` is hidden.
3. ``recipe_view.on_deactivate()`` was called exactly once.
4. ``navigate_back`` (the Back button handler) returns to the originating
   view: recipe→recipe, discover→discover, list→list.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

from metatv.gui.main_window_nav import _NavMixin


# ---------------------------------------------------------------------------
# Minimal collaborator stubs
# ---------------------------------------------------------------------------

class _FakeWidget:
    """Tiny widget stub: tracks setVisible calls and holds an isVisible state."""

    def __init__(self, visible: bool = False):
        self._visible = visible
        self.on_deactivate = MagicMock()
        self.on_activate = MagicMock()

    def isVisible(self) -> bool:
        return self._visible

    def setVisible(self, v: bool) -> None:
        self._visible = v


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, t: str) -> None:
        self.text = t

    def setEnabled(self, _v: bool) -> None:
        pass

    def setPlaceholderText(self, _t: str) -> None:
        pass


class _FakeSearchInput:
    def setEnabled(self, _v: bool) -> None:
        pass

    def setPlaceholderText(self, _t: str) -> None:
        pass


class _FakeSeries:
    name = "Test Series"


def _make_host() -> _NavMixin:
    """Real _NavMixin bound to fake widget collaborators.

    ``_hide_all_content_views`` is the REAL method (we want to exercise it);
    only the side-effecting helpers it calls are stubbed where needed.
    ``populate_series_tree`` and ``status_bar.showMessage`` are no-ops.
    """
    host = _NavMixin.__new__(_NavMixin)

    # Required base widgets
    host.channels_list    = _FakeWidget(visible=False)
    host.series_tree      = _FakeWidget(visible=False)
    host.epg_view         = _FakeWidget(visible=False)
    host.preferences_view = _FakeWidget(visible=False)
    host.discover_view    = _FakeWidget(visible=False)
    host.provider_editor  = _FakeWidget(visible=False)
    host.search_controls  = _FakeWidget(visible=False)
    host._hidden_banner   = _FakeWidget(visible=False)
    host.back_button      = _FakeWidget(visible=False)
    host.breadcrumb_label = _FakeLabel()
    host._hidden_mode     = False

    # Optional widgets that _hide_all_content_views checks via hasattr
    host.filter_panel  = _FakeWidget(visible=False)
    host._tab_all_btn  = MagicMock()
    host._tab_hidden_btn = MagicMock()

    # Series-view helpers
    host.series_icon        = "🎬"
    host.current_series     = _FakeSeries()
    host.search_input       = _FakeSearchInput()
    host.populate_series_tree = MagicMock()
    host.status_bar         = MagicMock()
    host.view_mode          = "list"

    # switch_to_recipe_view / switch_to_discover_view / switch_to_list_view
    # are the REAL methods — they call _hide_all_content_views internally.
    # Stub just the helpers those methods call that we don't need to exercise.
    host.stats_label        = _FakeLabel()
    host._run_query         = MagicMock()
    host._in_provider_edit_mode = False
    host.channel_model      = MagicMock()
    host.channel_model.rowCount.return_value = 0
    host.search_chip        = MagicMock()
    host.search_chip.is_enabled.return_value = False
    host.epg_chip           = MagicMock()
    host.prefs_chip         = MagicMock()
    host.discover_chip      = MagicMock()
    host._epg_count_token   = [0]

    return host


# ---------------------------------------------------------------------------
# Primary fix: recipe_view is hidden + deactivated when drilling into series
# ---------------------------------------------------------------------------

def test_switch_to_series_hides_recipe_view():
    """recipe_view must be hidden after switch_to_series_view."""
    host = _make_host()
    recipe_view = _FakeWidget(visible=True)   # recipe is the active overlay
    host.recipe_view = recipe_view

    host.switch_to_series_view()

    assert not recipe_view.isVisible(), (
        "recipe_view must be hidden after switch_to_series_view (stacking bug)"
    )


def test_switch_to_series_calls_recipe_on_deactivate():
    """recipe_view.on_deactivate() must be called once (lifecycle rule)."""
    host = _make_host()
    recipe_view = _FakeWidget(visible=True)
    host.recipe_view = recipe_view

    host.switch_to_series_view()

    recipe_view.on_deactivate.assert_called_once()


def test_switch_to_series_shows_series_tree():
    """series_tree must be visible after switch_to_series_view."""
    host = _make_host()
    host.recipe_view = _FakeWidget(visible=True)

    host.switch_to_series_view()

    assert host.series_tree.isVisible()


def test_switch_to_series_shows_back_button():
    """back_button must be visible after switch_to_series_view."""
    host = _make_host()
    host.recipe_view = _FakeWidget(visible=True)

    host.switch_to_series_view()

    assert host.back_button.isVisible()


def test_switch_to_series_does_not_deactivate_hidden_recipe():
    """on_deactivate must NOT be called when recipe_view was already hidden."""
    host = _make_host()
    recipe_view = _FakeWidget(visible=False)   # not the active view
    host.recipe_view = recipe_view

    host.switch_to_series_view()

    recipe_view.on_deactivate.assert_not_called()


# ---------------------------------------------------------------------------
# Secondary fix: navigate_back restores the originating view
# ---------------------------------------------------------------------------

def test_navigate_back_from_recipe_returns_to_recipe():
    """Back from a recipe-origin drill must call switch_to_recipe_view."""
    host = _make_host()
    recipe_view = _FakeWidget(visible=True)
    host.recipe_view = recipe_view

    host.switch_to_series_view()  # captures origin = "recipe"

    # now recipe_view is hidden; Back should re-show it
    host.navigate_back()

    assert recipe_view.isVisible(), (
        "navigate_back must restore recipe_view when the drill originated there"
    )


def test_navigate_back_from_discover_returns_to_discover():
    """Back from a discover-origin drill must call switch_to_discover_view."""
    host = _make_host()
    host.discover_view = _FakeWidget(visible=True)

    host.switch_to_series_view()  # captures origin = "discover"
    host.navigate_back()

    assert host.discover_view.isVisible()


def test_navigate_back_from_list_returns_to_list():
    """Back from a channel-list origin drill must restore channels_list."""
    host = _make_host()
    # No recipe/discover visible → origin = "list"
    host.switch_to_series_view()
    host.navigate_back()

    assert host.channels_list.isVisible(), (
        "navigate_back from list origin must restore channels_list"
    )


def test_navigate_back_origin_resets_after_use():
    """_series_return_view must be reset to 'list' after navigate_back fires."""
    host = _make_host()
    host.recipe_view = _FakeWidget(visible=True)
    host.switch_to_series_view()
    host.navigate_back()

    assert getattr(host, "_series_return_view", "list") == "list", (
        "_series_return_view must reset to 'list' after navigate_back to avoid stale state"
    )
