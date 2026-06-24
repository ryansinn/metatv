"""Behavioral regression: _on_filter_toggle must call recipe_view.reload().

Bug: the exclusions pause/resume toggle handler in main_window_nav.py reloaded
discover_view but NOT recipe_view, so toggling exclusions left the recipe's
pantry, tag cloud, and results showing stale (unfiltered) data.

Fix: added ``if "recipe_view" in self.__dict__: self.recipe_view.reload()``
to ``_on_filter_toggle``, mirroring the existing pattern in
``_open_global_filter_dialog``.

These tests drive the toggle handler directly (no Qt event loop needed)
and assert recipe_view.reload() is called on both pause and resume.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Minimal host stub — enough for _on_filter_toggle to run
# ---------------------------------------------------------------------------

def _make_host(tmp_path: Path, *, has_recipe_view: bool = True):
    """Return an object with just enough state for _on_filter_toggle."""
    from metatv.core.config import Config
    from metatv.gui import main_window_nav  # noqa: F401  (imports the mixin only)

    # Config that writes to tmp_path, not the real home directory.
    config = Config(config_dir=tmp_path)
    config.global_filter_paused = False

    host = SimpleNamespace()
    host.config = config
    host.discover_view = MagicMock()
    host.preferences_view = MagicMock()
    # Simulate MainWindow's _refresh_recommended_section and load_channels
    host.load_channels = MagicMock()
    host._refresh_recommended_section = MagicMock()
    host._update_filter_btn_state = MagicMock()

    if has_recipe_view:
        host.recipe_view = MagicMock()

    # Bind the unbound method from the mixin directly onto our stub.
    import types
    from metatv.gui.main_window_nav import _NavMixin
    host._on_filter_toggle = types.MethodType(_NavMixin._on_filter_toggle, host)

    return host


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_filter_toggle_pause_calls_recipe_view_reload(tmp_path):
    """Pausing exclusions (resume=False) must call recipe_view.reload()."""
    host = _make_host(tmp_path, has_recipe_view=True)
    host._on_filter_toggle(resume=False)
    host.recipe_view.reload.assert_called_once()


def test_filter_toggle_resume_calls_recipe_view_reload(tmp_path):
    """Resuming exclusions (resume=True) must call recipe_view.reload()."""
    host = _make_host(tmp_path, has_recipe_view=True)
    host.config.global_filter_paused = True  # start paused
    host._on_filter_toggle(resume=True)
    host.recipe_view.reload.assert_called_once()


def test_filter_toggle_still_calls_discover_view_reload(tmp_path):
    """discover_view.reload() must still be called (no regression)."""
    host = _make_host(tmp_path, has_recipe_view=True)
    host._on_filter_toggle(resume=False)
    host.discover_view.reload.assert_called_once()


def test_filter_toggle_no_recipe_view_does_not_crash(tmp_path):
    """When recipe_view has not been instantiated yet, the toggle must not crash."""
    host = _make_host(tmp_path, has_recipe_view=False)
    # Must not raise AttributeError
    host._on_filter_toggle(resume=False)
    host.discover_view.reload.assert_called_once()
