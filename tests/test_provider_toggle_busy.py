"""Behavior tests for the provider-toggle busy affordance.

Toggling a source active/inactive triggers a multi-second canonical refresh
(recommendations recompute over the whole library). The re-entrancy guard and
the busy-then-refresh sequence live in ``MainWindow.toggle_provider_active``;
these execute it. (The sidebar row widget they once also covered,
``ProviderItemWidget``, was removed with the Sources manager's move to chips.)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.conftest import wire_status_method


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _icon_bytes(btn) -> bytes:
    """Raw pixel bytes of *btn*'s current icon, for "did it actually repaint"."""
    image = btn.icon().pixmap(btn.iconSize()).toImage()
    return image.bits().asstring(image.sizeInBytes())


def test_toggle_reentrancy_guard_blocks_while_busy():
    """A second toggle while one is in flight must no-op — no DB work, no re-mark."""
    from metatv.gui.main_window import MainWindow

    sources = MagicMock()
    sources.is_provider_busy.return_value = True
    me = SimpleNamespace(
        # Wave 6: Sources left the sidebar stack — bare hosts must expose the
        # resolver the provider mixin now calls.
        _sources_status_target=lambda: sources,
        sidebar_sections={"sources": sources},
        status_bar=MagicMock(),
        db=MagicMock(),
    )
    wire_status_method(me)

    MainWindow.toggle_provider_active(me, "p1")

    sources.set_provider_busy.assert_not_called()
    me.db.get_session.assert_not_called()


def test_toggle_marks_busy_then_refreshes_when_idle():
    """First toggle (not busy) marks the row busy and runs the canonical refresh."""
    from metatv.gui.main_window import MainWindow

    sources = MagicMock()
    sources.is_provider_busy.return_value = False
    db = MagicMock()
    prov = MagicMock(is_active=True, name="Prov")
    db.get_session.return_value.query.return_value.filter_by.return_value.first.return_value = prov
    me = SimpleNamespace(
        _sources_status_target=lambda: sources,
        sidebar_sections={"sources": sources},
        status_bar=MagicMock(),
        db=db,
        _refresh_provider_dependent_views=MagicMock(),
        _clear_provider_busy=MagicMock(),
    )
    wire_status_method(me)

    # Patch the module QTimer so the safety-net singleShot is a no-op.
    import metatv.gui.main_window as mw
    orig = mw.QTimer
    mw.QTimer = MagicMock()
    try:
        MainWindow.toggle_provider_active(me, "p1")
    finally:
        mw.QTimer = orig

    sources.set_provider_busy.assert_called_once_with("p1", True)
    me._refresh_provider_dependent_views.assert_called_once()
