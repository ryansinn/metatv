"""Regression test for P0-4: views with on_activate must have symmetric on_deactivate.

Verifies:
- discover_view and preferences_view have on_deactivate() methods
- _hide_all_content_views() calls on_deactivate() on the departing discover/preferences view
"""


from tests.conftest import wire_header_search_sync
from unittest.mock import MagicMock, patch
from tests.conftest import wire_nav_host


def _build_mock_window():
    from metatv.gui import main_window as mw_module

    with patch.object(mw_module.MainWindow, "__init__", lambda self: None):
        win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    # Not QMainWindow.__init__ — running Qt's constructor on this half-built
    # object aborts the interpreter. The failure was a READ of an attribute
    # nobody set: on a __new__'d QObject that raises RuntimeError rather than
    # AttributeError, which is why it read as "super-class __init__ was never
    # called" and not as a missing attribute. Setting it is the whole fix.
    wire_nav_host(win)

    # Widgets that _hide_all_content_views hides
    win.channels_list          = MagicMock()
    win.series_tree            = MagicMock()
    win.epg_view               = MagicMock()
    win.preferences_view       = MagicMock()
    win.discover_view          = MagicMock()
    win.provider_editor        = MagicMock()
    win.search_controls        = MagicMock()
    wire_header_search_sync(win)
    win._hidden_banner         = MagicMock()
    win.back_button            = MagicMock()
    win.breadcrumb_label       = MagicMock()
    win._hidden_mode           = False

    # Stubs for optional hasattr checks
    win.filter_panel           = MagicMock()
    win._tab_all_btn           = MagicMock()
    win._tab_hidden_btn        = MagicMock()

    return win


# ---------------------------------------------------------------------------
# Structural: on_deactivate must exist on all four views
# ---------------------------------------------------------------------------

def test_discover_view_has_on_deactivate():
    from metatv.gui.discover_view import DiscoverView
    assert hasattr(DiscoverView, "on_deactivate"), (
        "DiscoverView.on_deactivate() is missing — lifecycle asymmetry (P0-4)"
    )


def test_preferences_view_has_on_deactivate():
    from metatv.gui.preferences_view import PreferencesView
    assert hasattr(PreferencesView, "on_deactivate"), (
        "PreferencesView.on_deactivate() is missing — lifecycle asymmetry (P0-4)"
    )


# ---------------------------------------------------------------------------
# Host wiring: _hide_all_content_views must call on_deactivate on departing views
# ---------------------------------------------------------------------------

def test_hide_calls_discover_on_deactivate_when_visible():
    """discover_view.on_deactivate() must be called if discover_view was visible."""
    win = _build_mock_window()
    win.discover_view.isVisible.return_value = True
    win.epg_view.isVisible.return_value = False
    win.preferences_view.isVisible.return_value = False

    win._hide_all_content_views()

    win.discover_view.on_deactivate.assert_called_once()


def test_hide_calls_preferences_on_deactivate_when_visible():
    """preferences_view.on_deactivate() must be called if preferences_view was visible."""
    win = _build_mock_window()
    win.discover_view.isVisible.return_value = False
    win.epg_view.isVisible.return_value = False
    win.preferences_view.isVisible.return_value = True

    win._hide_all_content_views()

    win.preferences_view.on_deactivate.assert_called_once()


def test_hide_skips_on_deactivate_when_not_visible():
    """on_deactivate must NOT be called if the view was already hidden."""
    win = _build_mock_window()
    win.discover_view.isVisible.return_value = False
    win.epg_view.isVisible.return_value = False
    win.preferences_view.isVisible.return_value = False

    win._hide_all_content_views()

    win.discover_view.on_deactivate.assert_not_called()
    win.preferences_view.on_deactivate.assert_not_called()
