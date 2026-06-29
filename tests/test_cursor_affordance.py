"""Behavioral tests for the app-wide pointing-hand cursor affordance.

The affordance is a single application-level event filter
(:mod:`metatv.gui.cursor_affordance`) that, on a widget's ``Enter`` event, gives
clickable controls ``Qt.CursorShape.PointingHandCursor``. These tests construct
the filter and synthesize ``Enter`` events on sample widgets, then assert the
resulting ``widget.cursor().shape()`` — exercising the real decision path rather
than its shape.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QPushButton,
    QRadioButton,
)

from metatv.gui.cursor_affordance import (
    CLICKABLE_PROPERTY,
    PointingHandFilter,
)


@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


def _send_enter(filt: PointingHandFilter, widget) -> bool:
    """Run *widget* through the filter's Enter handling; return its result."""
    event = QEvent(QEvent.Type.Enter)
    return filt.eventFilter(widget, event)


def test_enter_sets_hand_on_enabled_button(qapp):
    """An enabled push-button (chips/rail buttons are QPushButtons) gets the hand."""
    filt = PointingHandFilter()
    btn = QPushButton("Play")
    assert btn.cursor().shape() != Qt.CursorShape.PointingHandCursor

    consumed = _send_enter(filt, btn)

    assert btn.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert consumed is False, "filter must never swallow the Enter event"


def test_enter_does_not_set_hand_on_checkbox(qapp):
    """A QCheckBox keeps the normal cursor — its box is the affordance."""
    filt = PointingHandFilter()
    box = QCheckBox("Enabled")

    _send_enter(filt, box)

    assert box.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_enter_does_not_set_hand_on_radio(qapp):
    """A QRadioButton keeps the normal cursor — its circle is the affordance."""
    filt = PointingHandFilter()
    radio = QRadioButton("Option")

    _send_enter(filt, radio)

    assert radio.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_enter_does_not_set_hand_on_disabled_button(qapp):
    """A disabled button offers nothing to click — no hand."""
    filt = PointingHandFilter()
    btn = QPushButton("Unavailable")
    btn.setEnabled(False)

    _send_enter(filt, btn)

    assert btn.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_disabling_after_hover_clears_the_hand(qapp):
    """A button hovered while enabled, then disabled, drops the hand on re-hover."""
    filt = PointingHandFilter()
    btn = QPushButton("Toggle")

    _send_enter(filt, btn)
    assert btn.cursor().shape() == Qt.CursorShape.PointingHandCursor

    btn.setEnabled(False)
    _send_enter(filt, btn)
    assert btn.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_custom_label_opts_in_via_property(qapp):
    """A non-button widget opts in with the ``clickable=True`` dynamic property."""
    filt = PointingHandFilter()
    label = QLabel("Genre: Drama")
    label.setProperty(CLICKABLE_PROPERTY, True)

    _send_enter(filt, label)

    assert label.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_plain_label_without_property_gets_nothing(qapp):
    """A plain (non-opted-in) label is not treated as clickable."""
    filt = PointingHandFilter()
    label = QLabel("Just text")

    _send_enter(filt, label)

    assert label.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_non_enter_event_is_ignored(qapp):
    """Events other than Enter never touch the cursor."""
    filt = PointingHandFilter()
    btn = QPushButton("Play")

    consumed = filt.eventFilter(btn, QEvent(QEvent.Type.Leave))

    assert btn.cursor().shape() != Qt.CursorShape.PointingHandCursor
    assert consumed is False
