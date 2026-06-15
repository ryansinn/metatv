"""Regression tests: provider mutations refresh ALL dependent views (normalized).

The recurring bug these guard: a provider mutation hand-picked a subset of views
to refresh, leaving others stale — e.g. editing a source's icon refreshed the
sidebar but not the main list's ``provider_icon_map``, so a new source showed its
content with no icon. The fix funnels every provider mutation through the single
canonical ``_refresh_provider_dependent_views``.

These execute the real methods (via ``__new__`` + stubs), not source-string shape
checks: they assert the canonical refresh touches the full view set, and that the
handlers delegate to it rather than re-implementing a partial refresh.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from metatv.gui.main_window import MainWindow


_DEPENDENT_REFRESHERS = [
    "load_providers",
    "load_favorites",
    "load_history",
    "_refresh_queue_section",
    "_refresh_recommended_section",
    "load_channels",
]

# The canonical method is a plain orchestration method; drive its unbound function
# with a SimpleNamespace as `self` so `hasattr` behaves normally (a bare
# QMainWindow.__new__ instance raises RuntimeError on attribute lookup via sip).
_CANONICAL = MainWindow._refresh_provider_dependent_views


def _bare_window() -> MainWindow:
    return MainWindow.__new__(MainWindow)


def test_canonical_refresh_touches_every_dependent_view():
    """_refresh_provider_dependent_views must refresh the full corpus-derived set:
    all sidebar sections + the main list + the lazy overlay views."""
    me = SimpleNamespace(**{name: MagicMock() for name in _DEPENDENT_REFRESHERS})
    me.discover_view = MagicMock()
    me.preferences_view = MagicMock()

    _CANONICAL(me)

    for name in _DEPENDENT_REFRESHERS:
        getattr(me, name).assert_called_once()
    # Main list refresh is what rebuilds provider_icon_map — the icon-bug guard.
    me.load_channels.assert_called_once()
    me.discover_view.reload.assert_called_once()
    me.preferences_view.refresh.assert_called_once()


def test_canonical_refresh_skips_absent_overlay_views():
    """The overlay views are lazily constructed; refresh must not blow up when
    they don't exist yet (hasattr guard)."""
    me = SimpleNamespace(**{name: MagicMock() for name in _DEPENDENT_REFRESHERS})
    # No discover_view / preferences_view attributes set.

    _CANONICAL(me)  # must not raise

    for name in _DEPENDENT_REFRESHERS:
        getattr(me, name).assert_called_once()


def test_provider_saved_funnels_through_canonical():
    """Editing a source (the icon-change path) must go through the canonical
    refresh, not just reload the sidebar."""
    w = _bare_window()
    w._refresh_provider_dependent_views = MagicMock()
    w.status_bar = MagicMock()

    w._on_provider_saved("prov-1")

    w._refresh_provider_dependent_views.assert_called_once()


def test_provider_deleted_funnels_through_canonical():
    w = _bare_window()
    w._refresh_provider_dependent_views = MagicMock()
    w.exit_provider_edit_mode = MagicMock()
    w.status_bar = MagicMock()

    w._on_provider_deleted("prov-1")

    w._refresh_provider_dependent_views.assert_called_once()
    w.exit_provider_edit_mode.assert_called_once()
