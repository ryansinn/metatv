"""A failure toast's action buttons must be readable (owner report 2026-08-31).

A stream-failure notification offers one action per alternative source. The
owner's had seven — "Try Any", "Try AR", "Try ES", "Try LA", two rate actions
and "Copy Error" — laid out in a QHBoxLayout, which divides the toast's fixed
width between them. Each button was crushed below its own text and the label
was CUT, not elided: "r Any", "Try AF", "ate _", "py Er". Unreadable, and no
way to tell which button did what.
"""

import tempfile

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
