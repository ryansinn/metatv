"""Behavior tests for the provider-toggle busy affordance.

Toggling a source active/inactive triggers a multi-second canonical refresh
(recommendations recompute over the whole library). The row's buttons must disable
with a spinner so the user sees progress and can't stack repeat clicks. These execute
the real widget/guard logic, not source-string checks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.gui import icons as _icons


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_set_busy_disables_buttons_and_shows_spinner(qapp):
    from metatv.gui.sidebar.sources import ProviderItemWidget
    w = ProviderItemWidget("p1", "Prov", is_active=True)

    assert all(b.isEnabled() for b in w._action_btns)

    w.set_busy(True)
    assert all(not b.isEnabled() for b in w._action_btns)
    assert w._toggle_btn.text() == _icons.loading_icon

    w.set_busy(False)
    assert all(b.isEnabled() for b in w._action_btns)
    assert w._toggle_btn.text() == "●"   # active glyph restored


def test_busy_constructor_param_renders_busy(qapp):
    from metatv.gui.sidebar.sources import ProviderItemWidget
    w = ProviderItemWidget("p1", "Prov", is_active=False, busy=True)
    assert all(not b.isEnabled() for b in w._action_btns)
    assert w._toggle_btn.text() == _icons.loading_icon


def test_toggle_reentrancy_guard_blocks_while_busy():
    """A second toggle while one is in flight must no-op — no DB work, no re-mark."""
    from metatv.gui.main_window import MainWindow

    sources = MagicMock()
    sources.is_provider_busy.return_value = True
    me = SimpleNamespace(
        sidebar_sections={"sources": sources},
        status_bar=MagicMock(),
        db=MagicMock(),
    )

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
        sidebar_sections={"sources": sources},
        status_bar=MagicMock(),
        db=db,
        _refresh_provider_dependent_views=MagicMock(),
        _clear_provider_busy=MagicMock(),
    )

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
