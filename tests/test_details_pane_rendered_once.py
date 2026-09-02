"""One click must render the details pane once, not twice.

From the owner's own log, a single click on a channel:

    07:43:44.368  update_details_pane_for_channel … metadata=False
    07:43:44.385  === fetch_metadata() thread started
    07:43:44.464  update_details_pane_for_channel …          <- again
    07:43:44.537  === fetch_metadata() thread started         <- again

Two renders, two ``get_playable_dto`` reads and two metadata threads for one
channel, on every selection. Two handlers answer one click: ``currentChanged``
renders the pane, and the clicked handler renders it again.

**The clicked handler cannot simply defer to the other one.** Clicking a row
that is ALREADY current emits no ``currentChanged`` at all, and that is the case
it was added for — with a single search result the list auto-selects it, so
*"I can't single click Ghostbusters in the search results to get it to populate
the details panel"* (owner, 2026-09-01, and ``test_click_and_resume_ux`` pins
it). Gating on the channel id cannot separate the two, because by the time
``clicked`` arrives the id says "this row" either way. Nor can gating on what
the pane shows: that would break clicking a row again to refresh a stale pane,
which is the escape hatch the same report relied on.

The one fact that separates them is whether THIS press moved the current row,
and it is knowable only inside ``mousePressEvent`` — before ``super()`` moves
it, and long before ``clicked`` is emitted from the release.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt, QStringListModel
from PyQt6.QtGui import QMouseEvent

from metatv.gui.channel_list_view import ChannelListView
from metatv.gui.main_window_channels import _ChannelListMixin


CHANNEL = "prov_123"


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _Index:
    """The minimum of a QModelIndex this handler touches."""

    def __init__(self, channel_id):
        self._id = channel_id

    def data(self, role):
        return self._id if role == Qt.ItemDataRole.UserRole else None


def _host(moved: bool | None):
    """*moved*: what the view reports, or None for "there is no view yet"."""
    host = SimpleNamespace(
        show_channel_details_by_id=MagicMock(),
        _last_shown_channel_id=None,
    )
    if moved is not None:
        host.channels_list = SimpleNamespace(press_moved_current=lambda: moved)
    return host


# ── the click handler ────────────────────────────────────────────────────────

def test_a_click_that_moved_the_selection_does_not_render_again():
    """The bug: currentChanged rendered it microseconds earlier."""
    host = _host(moved=True)
    _ChannelListMixin._show_details_for_clicked_row(host, _Index(CHANNEL))
    host.show_channel_details_by_id.assert_not_called()


def test_a_click_on_the_already_current_row_still_renders():
    """The Ghostbusters case, and the reason this handler exists at all: one
    search result, auto-selected, so no currentChanged ever fires."""
    host = _host(moved=False)
    _ChannelListMixin._show_details_for_clicked_row(host, _Index(CHANNEL))
    host.show_channel_details_by_id.assert_called_once_with(CHANNEL)
    assert host._last_shown_channel_id == CHANNEL


def test_clicking_the_same_row_again_still_refreshes_it():
    """The escape hatch from the same report — a pane showing Play instead of
    Resume is recovered by clicking the row again. Gating on what the pane
    SHOWS would have removed this."""
    host = _host(moved=False)
    for _ in range(3):
        _ChannelListMixin._show_details_for_clicked_row(host, _Index(CHANNEL))
    assert host.show_channel_details_by_id.call_count == 3


def test_it_renders_when_there_is_no_view_yet():
    """Construction order, and the bare hosts other test files build."""
    host = _host(moved=None)
    _ChannelListMixin._show_details_for_clicked_row(host, _Index(CHANNEL))
    host.show_channel_details_by_id.assert_called_once_with(CHANNEL)


def test_a_non_channel_row_is_ignored():
    """Section headings and person sub-headings carry no channel id."""
    host = _host(moved=False)
    _ChannelListMixin._show_details_for_clicked_row(host, _Index(None))
    host.show_channel_details_by_id.assert_not_called()


def test_a_failing_render_is_logged_not_raised():
    host = _host(moved=False)
    host.show_channel_details_by_id.side_effect = RuntimeError("boom")
    _ChannelListMixin._show_details_for_clicked_row(host, _Index(CHANNEL))


# ── the view's half: the fact must be captured BEFORE super() moves current ──

def _press(view, row):
    rect = view.visualRect(view.model().index(row, 0))
    pos = QPointF(rect.center())
    view.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, view.mapToGlobal(pos),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))


@pytest.fixture()
def view(qapp):
    v = ChannelListView()
    v.setModel(QStringListModel(["row 0", "row 1", "row 2"]))
    v.resize(300, 200)
    return v


def test_no_press_yet_reports_false(view):
    assert view.press_moved_current() is False


def test_a_press_on_a_different_row_reports_moved(view):
    view.setCurrentIndex(view.model().index(0, 0))
    _press(view, 2)
    assert view.press_moved_current() is True
    assert view.currentIndex().row() == 2, "precondition: the press moved it"


def test_a_press_on_the_current_row_reports_not_moved(view):
    """The whole point — and it only works because the flag is computed before
    ``super().mousePressEvent`` sets the current index."""
    view.setCurrentIndex(view.model().index(1, 0))
    _press(view, 1)
    assert view.press_moved_current() is False


def test_the_flag_updates_on_every_press(view):
    view.setCurrentIndex(view.model().index(0, 0))
    _press(view, 1)
    assert view.press_moved_current() is True
    _press(view, 1)
    assert view.press_moved_current() is False, (
        "a second press on the now-current row must report not-moved, or "
        "clicking a row twice stops refreshing it")


# ── what must NOT be gated ───────────────────────────────────────────────────

def test_the_chokepoint_itself_is_not_gated():
    """``_refresh_details_after_playback_stopped`` re-shows the SAME channel on
    purpose, so a part-watched title offers Resume the moment the player
    closes. A guard inside the chokepoint would swallow that silently — the
    #311 shape, where the pane's buttons froze."""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "metatv" / "gui" / "main_window_metadata.py").read_text()
    body = src[src.index("def show_channel_details_by_id"):]
    body = body[:body.index("\n    def ", 1)]
    assert "press_moved_current" not in body
