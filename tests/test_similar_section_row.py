"""Behavioral tests for the Similar-content row buttons (details_similar._SimilarSection).

Covers two reported bugs in the per-row queue button:
- It crashed: QPushButton.clicked emits clicked(bool), and the bool bound to the
  handler's first param (_btn), so _btn.setText() ran on a bool → AttributeError
  → core dump. The handler must absorb the checked bool.
- Clickable buttons lacked the pointing-hand cursor.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _section(qapp):
    from metatv.core.config import Config
    from metatv.gui.details_similar import _SimilarSection
    return _SimilarSection(Config())


def _version(**kw):
    from metatv.gui.details_versions import ChannelVersion
    base = dict(channel_id="c1", name="Show", in_queue=False)
    base.update(kw)
    return ChannelVersion(**base)


def _find_button(row_w, needle: str):
    from PyQt6.QtWidgets import QPushButton
    for b in row_w.findChildren(QPushButton):
        if needle in b.toolTip():
            return b
    return None


def test_queue_button_click_does_not_crash_and_toggles(qapp):
    """Clicking the queue button must not crash and must optimistically flip state."""
    s = _section(qapp)
    v = _version(in_queue=False)
    s._channel_ids = [v.channel_id]
    row = s._make_row(v)

    btn = _find_button(row, "Queue")
    assert btn is not None, "queue button should exist in the row"

    emitted: list[str] = []
    s.queue_toggled.connect(lambda cid: emitted.append(cid))

    btn.click()  # emits clicked(False) — must not raise

    assert v.in_queue is True, "queue click must optimistically flip in_queue"
    assert emitted == [v.channel_id], "queue_toggled must emit the channel_id"
    # Tooltip flips to the remove affordance.
    assert "Remove" in btn.toolTip()


def test_queue_button_click_toggles_back_off(qapp):
    """A second click flips it back (no crash either direction)."""
    s = _section(qapp)
    v = _version(in_queue=True)
    s._channel_ids = [v.channel_id]
    row = s._make_row(v)
    btn = _find_button(row, "Queue")
    btn.click()
    assert v.in_queue is False


def test_row_buttons_have_pointing_hand_cursor(qapp):
    """Every clickable button in the row shows the pointing-hand cursor."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QPushButton

    s = _section(qapp)
    v = _version(detected_prefix="EN")  # include the prefix chip too
    s._channel_ids = [v.channel_id]
    row = s._make_row(v)

    btns = row.findChildren(QPushButton)
    assert btns, "row should contain buttons"
    for b in btns:
        assert b.cursor().shape() == Qt.CursorShape.PointingHandCursor, (
            f"button {b.text()!r} must show the pointing-hand cursor"
        )
