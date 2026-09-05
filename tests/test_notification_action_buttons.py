"""A failure toast's action buttons must be readable (owner report 2026-08-31).

A stream-failure notification offers one action per alternative source. The
owner's had seven — "Try Any", "Try AR", "Try ES", "Try LA", two rate actions
and "Copy Error" — laid out in a QHBoxLayout, which divides the toast's fixed
width between them. Each button was crushed below its own text and the label
was CUT, not elided: "r Any", "Try AF", "ate _", "py Er". Unreadable, and no
way to tell which button did what.
"""

import tempfile
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QPushButton

from metatv.core.config import Config
from metatv.core.notifications import Notification, NotificationType
from metatv.gui.notification_widget import NotificationCard

_LABELS = ("Try Any", "Try AR", "Try ES", "Try LA",
           "Rate this copy", "Rate source", "Copy Error")


@pytest.fixture
def card(qapp):
    note = Notification(
        id="n1", title="Stream Unavailable",
        message="Ghostbusters Frozen Empire\nHTTP 500",
        type=NotificationType.ERROR,
        actions=[(label, lambda: None) for label in _LABELS],
    )
    c = NotificationCard(note, Config(config_dir=tempfile.mkdtemp()))
    c.resize(420, c.sizeHint().height())
    c.show()
    qapp.processEvents()
    return c


def _action_buttons(card):
    return [b for b in card.findChildren(QPushButton)
            if b.text() and b.text() != "×"]


def test_every_action_button_is_wide_enough_for_its_label(card):
    """The defect itself, asserted on painted width rather than on the layout class.

    A test that the layout is a FlowLayout would pass for a flow layout that
    still squeezed its children; this compares each button's actual width to
    what its text needs.
    """
    clipped = [(b.text(), b.width(), b.sizeHint().width())
               for b in _action_buttons(card)
               if b.width() < b.sizeHint().width()]
    assert not clipped, (
        f"{len(clipped)} action button(s) narrower than their own label: "
        f"{clipped}")


def test_the_actions_wrap_rather_than_shrink(card):
    """Seven buttons in a 420px toast cannot fit on one row at full width.

    So the honest outcome is more than one row. If they ever all fit on one,
    the toast got much wider or the actions got fewer — either is fine, but
    the assertion above is the one that must never fail.
    """
    buttons = _action_buttons(card)
    assert len(buttons) == len(_LABELS), "not every action was rendered"
    total = sum(b.sizeHint().width() for b in buttons)
    if total > card.width():
        assert len({b.y() for b in buttons}) > 1, (
            "the actions need more width than the toast has and did not wrap — "
            "which means they were crushed instead")


def test_the_labels_survive_intact(card):
    """'py Er' is what the user saw. The text must be the text."""
    assert [b.text() for b in _action_buttons(card)] == list(_LABELS)


# ---------------------------------------------------------------------------
# REC-2 (Catch, Keep, Record Feature 3): the persistent recording notice
# reuses this SAME chokepoint — a rendered check that its message and BOTH
# actions actually show, and that "Watch" (keep_open) does not close the card
# a "Stop" click does.
# ---------------------------------------------------------------------------

def test_the_persistent_recording_card_renders_its_message_and_both_actions(qapp):
    note = Notification(
        id="n1", title="⏺ RECORDING The Match",
        message="1:12:04 / ~2:03 · 8.4 GB used, 120.0 GB free · ends 21:15 "
                "(+15 min post-roll) · playback on Shark is unavailable "
                "until it finishes",
        type=NotificationType.WARNING,
        dismissible=False,
        actions=[("Watch", lambda: None, True), ("Stop", lambda: None)],
    )
    card = NotificationCard(note, Config(config_dir=tempfile.mkdtemp()))
    card.show()
    qapp.processEvents()

    assert "1:12:04" in card.message_label.text()
    assert "8.4 GB used" in card.message_label.text()
    assert [b.text() for b in _action_buttons(card)] == ["Watch", "Stop"]
    # dismissible=False → no × close button, but the actions still render —
    # the ONLY way to end a persistent card is Stop (or the recording itself
    # finishing), never an accidental close.
    assert not any(b.text() == "×" for b in card.findChildren(QPushButton))


def test_keep_open_action_survives_its_own_click_the_default_does_not(qapp):
    """The generic action-button mechanism's opt-in third element (REC-2):
    "Watch" (keep_open=True) must not dismiss the card; "Stop" (the plain
    2-tuple every pre-existing caller uses) still does, unchanged."""
    calls = []
    note = Notification(
        id="n1", title="Recording", message="", type=NotificationType.WARNING,
        dismissible=False,
        actions=[("Watch", lambda: calls.append("watch"), True),
                 ("Stop", lambda: calls.append("stop"))],
    )
    card = NotificationCard(note, Config(config_dir=tempfile.mkdtemp()))
    card.dismiss = MagicMock()
    card.show()
    qapp.processEvents()

    watch_btn, stop_btn = _action_buttons(card)
    watch_btn.click()
    assert calls == ["watch"]
    card.dismiss.assert_not_called()

    stop_btn.click()
    assert calls == ["watch", "stop"]
    card.dismiss.assert_called_once()
