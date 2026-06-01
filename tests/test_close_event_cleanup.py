"""Regression test for P0-3: closeEvent must call shutdown on all thread-owning managers.

Asserts that epg_manager.shutdown(), image_cache.shutdown(), and executor.shutdown()
are each invoked when the window closes.
"""

from unittest.mock import MagicMock, patch, call
import pytest


def _make_close_event():
    event = MagicMock()
    event.accept = MagicMock()
    return event


def _build_mock_window():
    """Build a minimal fake MainWindow with MagicMock attributes for the managers."""
    # Avoid importing MainWindow (requires QApplication + full config/db setup).
    # Instead patch __init__ and instantiate a thin shell.
    from metatv.gui import main_window as mw_module

    with patch.object(mw_module.MainWindow, "__init__", lambda self: None):
        win = mw_module.MainWindow.__new__(mw_module.MainWindow)

    # Managers that closeEvent must shut down
    win.player_manager    = MagicMock()
    win.stream_retry_manager = MagicMock()
    win.db                = MagicMock()
    win.epg_manager       = MagicMock()
    win.image_cache       = MagicMock()
    win.executor          = MagicMock()
    win.config            = MagicMock()

    # Content views whose background work closeEvent stops on exit (F3-1).
    # Default to not-visible so on_deactivate is not invoked unless a test opts in.
    for _name in ("discover_view", "preferences_view", "epg_view"):
        view = MagicMock()
        view.isVisible.return_value = False
        setattr(win, _name, view)

    # Stub out helper methods called inside closeEvent
    win.save_splitter_sizes = MagicMock()
    win.saveGeometry        = MagicMock(return_value=b"geometry")

    return win


def test_epg_manager_shutdown_called_on_close():
    """epg_manager.shutdown() must be called in closeEvent."""
    win = _build_mock_window()
    win.closeEvent(_make_close_event())
    win.epg_manager.shutdown.assert_called_once()


def test_image_cache_shutdown_called_on_close():
    """image_cache.shutdown() must be called in closeEvent."""
    win = _build_mock_window()
    win.closeEvent(_make_close_event())
    win.image_cache.shutdown.assert_called_once()


def test_executor_shutdown_called_on_close():
    """self.executor.shutdown() must be called in closeEvent."""
    win = _build_mock_window()
    win.closeEvent(_make_close_event())
    win.executor.shutdown.assert_called_once()


def test_preferences_executor_shutdown_called_on_close():
    """preferences_view._executor.shutdown() must be called in closeEvent (F3-1)."""
    win = _build_mock_window()
    win.closeEvent(_make_close_event())
    win.preferences_view._executor.shutdown.assert_called_once()


def test_visible_view_on_deactivate_called_on_close():
    """The active content view's on_deactivate() must be called on close (F3-1)."""
    win = _build_mock_window()
    win.discover_view.isVisible.return_value = True
    win.closeEvent(_make_close_event())
    win.discover_view.on_deactivate.assert_called_once()
    # A hidden view must not be deactivated.
    win.epg_view.on_deactivate.assert_not_called()


def test_existing_cleanup_still_runs():
    """player_manager.cleanup() and db.close() must still be called."""
    win = _build_mock_window()
    win.closeEvent(_make_close_event())
    win.player_manager.cleanup.assert_called_once()
    win.db.close.assert_called_once()


def test_event_accepted():
    """event.accept() must always be called (window must close)."""
    win = _build_mock_window()
    ev = _make_close_event()
    win.closeEvent(ev)
    ev.accept.assert_called_once()
