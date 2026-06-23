"""Regression test for P0-3 / B3-1: closeEvent must call shutdown on all thread-owning
managers. Managers are now registered via _cleanables (B3-1 cleanup registry) rather
than individual hasattr checks.
"""

from unittest.mock import MagicMock, patch
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
    win.player_manager       = MagicMock()
    win.stream_retry_manager = MagicMock()
    win.db                   = MagicMock()
    win.epg_manager          = MagicMock()
    win.image_cache          = MagicMock()
    win.executor             = MagicMock()
    win.config               = MagicMock()

    # B3-1: populate the cleanup registry (mirrors registration order in __init__ / setup_ui)
    win._cleanables = [
        ("player_manager",       win.player_manager.cleanup),
        ("image_cache",          win.image_cache.shutdown),
        ("stream_retry_manager", win.stream_retry_manager.stop),
        ("executor",             lambda: win.executor.shutdown(wait=False)),
        ("epg_manager",          win.epg_manager.shutdown),
    ]

    # Content views whose background work closeEvent stops on exit (F3-1).
    # Default to not-visible so on_deactivate is not invoked unless a test opts in.
    for _name in ("discover_view", "preferences_view", "epg_view", "recipe_view"):
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


def test_cleanable_registry_calls_registered_fn():
    """B3-1: any callable registered via _cleanables must be invoked in closeEvent."""
    win = _build_mock_window()
    sentinel = MagicMock()
    win._cleanables.append(("test_sentinel", sentinel))
    win.closeEvent(_make_close_event())
    sentinel.assert_called_once()


def test_cleanable_registry_exception_does_not_abort_close():
    """B3-1: a failing cleanable must not prevent the rest from running or the window closing."""
    win = _build_mock_window()
    boom = MagicMock(side_effect=RuntimeError("boom"))
    after = MagicMock()
    win._cleanables.append(("boom", boom))
    win._cleanables.append(("after", after))
    ev = _make_close_event()
    win.closeEvent(ev)
    after.assert_called_once()
    ev.accept.assert_called_once()
