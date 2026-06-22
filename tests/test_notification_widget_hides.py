"""Exclusions-chip dead-zone fix — the notification overlay must hide when empty.

The bottom-right notification overlay is `raise_()`d above the bottom nav bar. If
it stays visible while empty, it sits over the Exclusions chip (far-right of the
bar) and swallows its clicks — the long-standing "chip dead until a notification
appears/dismisses" bug. The overlay must be hidden whenever there's nothing to
show, so it never intercepts clicks meant for the chip beneath it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_widget(qapp):
    from PyQt6.QtWidgets import QWidget
    from metatv.core.config import Config
    from metatv.gui.notification_widget import NotificationWidget

    parent = QWidget()
    parent.resize(1200, 800)
    w = NotificationWidget(MagicMock(), Config(), parent)
    w._parent_keepalive = parent  # keep the parent referenced for the test's lifetime
    return w


def test_starts_hidden(qapp):
    """A freshly built (empty) overlay must be hidden — it would cover the chip."""
    w = _make_widget(qapp)
    assert w.isHidden(), "NotificationWidget must start hidden when there's nothing to show"


def test_hidden_when_updated_with_no_notifications(qapp):
    """update_notifications([]) hides the overlay (frees the chip beneath it)."""
    w = _make_widget(qapp)
    w.update_notifications([])
    assert w.isHidden()


def test_visible_with_notification_then_hidden_when_drained(qapp):
    """Shown while a notification exists; hidden again once it drains."""
    from metatv.core.notifications import Notification, NotificationType

    w = _make_widget(qapp)
    n = Notification(title="Hi", message="there", type=NotificationType.INFO)

    w.update_notifications([n])
    assert not w.isHidden(), "overlay must be visible while a notification is present"

    w.update_notifications([])
    assert w.isHidden(), "overlay must hide again once notifications drain (frees the chip)"
