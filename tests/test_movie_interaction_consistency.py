"""Behavioural tests for consistent movie interaction across every surface.

Covers the two gaps this change closes:

1. Middle-click routes through ONE seam (``_dispatch_middle_click``) that maps
   ``config.middle_click_action`` → the mapped play method and calls it with the
   channel id — and every movie surface reaches that seam:
     * a Discover ``_ContentCard`` emits ``middleClicked(channel_id)`` on a
       MiddleButton press, and
     * the reusable ``QListWidget`` helper emits ``middleClicked(channel_id)``
       for the item under the cursor (sidebar Recommended / Queue / Favorites).
2. The Discover-family + record ``SURFACE_LAYOUTS`` carry the full standard
   movie block (``mark_watched`` / ``category`` / ``play_open_ended_buffer``).
"""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _press_event(button):
    """Build a MouseButtonPress QMouseEvent for *button* at a fixed position."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5.0, 5.0),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def _dispatch_host(action_key: str):
    """A minimal ``_ChannelListMixin`` host with config + play methods stubbed."""
    from metatv.gui.main_window_channels import _ChannelListMixin
    host = _ChannelListMixin.__new__(_ChannelListMixin)
    host.config = MagicMock()
    host.config.middle_click_action = action_key
    host.play_channel_resume_by_id = MagicMock()
    host.play_channel_open_ended_buffer_by_id = MagicMock()
    return host


# ---------------------------------------------------------------------------
# 1. _dispatch_middle_click seam — the single chokepoint
# ---------------------------------------------------------------------------

def test_dispatch_seam_resume_action_calls_resume_method(qapp):
    """config.middle_click_action='playback_position' → play_channel_resume_by_id(cid)."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    host = _dispatch_host("playback_position")
    _ChannelListMixin._dispatch_middle_click(host, "movie-1")

    host.play_channel_resume_by_id.assert_called_once_with("movie-1")
    host.play_channel_open_ended_buffer_by_id.assert_not_called()


def test_dispatch_seam_endless_buffer_action_calls_buffer_method(qapp):
    """config.middle_click_action='endless_buffer' → play_channel_open_ended_buffer_by_id(cid)."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    host = _dispatch_host("endless_buffer")
    _ChannelListMixin._dispatch_middle_click(host, "movie-2")

    host.play_channel_open_ended_buffer_by_id.assert_called_once_with("movie-2")
    host.play_channel_resume_by_id.assert_not_called()


def test_dispatch_seam_ignores_falsy_channel_id(qapp):
    """A click that resolves no channel id (empty space) must be a no-op."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    host = _dispatch_host("playback_position")
    _ChannelListMixin._dispatch_middle_click(host, "")

    host.play_channel_resume_by_id.assert_not_called()
    host.play_channel_open_ended_buffer_by_id.assert_not_called()


def test_channel_list_handler_delegates_to_dispatch_seam(qapp):
    """_on_channel_middle_clicked resolves the row id and calls _dispatch_middle_click."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    host = _ChannelListMixin.__new__(_ChannelListMixin)
    host._dispatch_middle_click = MagicMock()
    index = MagicMock()
    index.data.return_value = "row-cid"

    _ChannelListMixin._on_channel_middle_clicked(host, index)

    host._dispatch_middle_click.assert_called_once_with("row-cid")


# ---------------------------------------------------------------------------
# 2. Discover card emits middleClicked on a MiddleButton press
# ---------------------------------------------------------------------------

def _content_card(qapp, channel_id: str):
    from metatv.core.config import Config
    from metatv.core.discovery_engine import ContentCard
    from metatv.gui.discover_card import _ContentCard

    card = ContentCard(
        channel_id=channel_id,
        title="Some Movie (2021)",
        media_type="movie",
        thumbnail_url=None,   # no thumbnail → no ImageCache interaction in __init__
        rating=None,
        year=2021,
        genre=None,
    )
    return _ContentCard(card, MagicMock(), Config())


def test_discover_card_emits_middle_clicked_on_middle_press(qapp):
    from PyQt6.QtCore import Qt

    widget = _content_card(qapp, "card-cid")
    captured: list[str] = []
    widget.middleClicked.connect(captured.append)

    widget.mousePressEvent(_press_event(Qt.MouseButton.MiddleButton))

    assert captured == ["card-cid"], "middle-button press must emit middleClicked(channel_id)"


def test_discover_card_left_press_does_not_emit_middle_clicked(qapp):
    from PyQt6.QtCore import Qt

    widget = _content_card(qapp, "card-cid")
    middle: list[str] = []
    left: list[str] = []
    widget.middleClicked.connect(middle.append)
    widget.clicked.connect(left.append)

    widget.mousePressEvent(_press_event(Qt.MouseButton.LeftButton))

    assert middle == [], "a left-button press must NOT emit middleClicked"
    assert left == ["card-cid"], "a left-button press still emits clicked"


# ---------------------------------------------------------------------------
# 3. Reusable QListWidget middle-click helper
# ---------------------------------------------------------------------------

def test_list_middle_click_helper_emits_channel_id_under_cursor(qapp):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from metatv.gui.list_middle_click import install_list_middle_click

    lst = QListWidget()
    item = QListWidgetItem("A Movie")
    item.setData(Qt.ItemDataRole.UserRole, "list-cid")
    lst.addItem(item)

    flt = install_list_middle_click(lst)
    lst.itemAt = lambda _pos: item   # deterministic hit-test

    captured: list[str] = []
    flt.middleClicked.connect(captured.append)

    handled = flt.eventFilter(lst.viewport(), _press_event(Qt.MouseButton.MiddleButton))

    assert captured == ["list-cid"], "middle press over an item must emit its channel_id"
    assert handled is True, "the helper consumes the middle-click it handled"


def test_list_middle_click_helper_ignores_empty_space(qapp):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.list_middle_click import install_list_middle_click

    lst = QListWidget()
    flt = install_list_middle_click(lst)
    lst.itemAt = lambda _pos: None   # cursor over empty space

    captured: list[str] = []
    flt.middleClicked.connect(captured.append)

    handled = flt.eventFilter(lst.viewport(), _press_event(Qt.MouseButton.MiddleButton))

    assert captured == [], "a middle press over empty space must not emit"
    assert handled is False, "an unhandled press falls through to the base filter"


def test_list_middle_click_helper_ignores_left_button(qapp):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from metatv.gui.list_middle_click import install_list_middle_click

    lst = QListWidget()
    item = QListWidgetItem("A Movie")
    item.setData(Qt.ItemDataRole.UserRole, "list-cid")
    lst.addItem(item)
    flt = install_list_middle_click(lst)
    lst.itemAt = lambda _pos: item

    captured: list[str] = []
    flt.middleClicked.connect(captured.append)

    flt.eventFilter(lst.viewport(), _press_event(Qt.MouseButton.LeftButton))

    assert captured == [], "a left-button press must not emit middleClicked"


# ---------------------------------------------------------------------------
# 4. Full standard menu on the Discover-family + record surfaces
# ---------------------------------------------------------------------------

def test_recommended_layout_has_full_standard_block():
    """The shared Discover-family layout carries the full standard movie block."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS

    layout = SURFACE_LAYOUTS["recommended"]
    for action in ("play_open_ended_buffer", "mark_watched", "category"):
        assert action in layout, f"'recommended' layout must include {action!r}"
    # Kept — auto-hidden by their applies= predicates when N/A.
    assert "not_interested" in layout
    assert "clear_alert" in layout


def test_favorites_layout_gained_mark_watched_and_category():
    from metatv.gui.channel_menu import SURFACE_LAYOUTS

    layout = SURFACE_LAYOUTS["favorites"]
    assert "mark_watched" in layout
    assert "category" in layout
    # Surface-specific extra is preserved.
    assert "clear_unavailable" in layout


def test_queue_layout_gained_buffer_and_category():
    from metatv.gui.channel_menu import SURFACE_LAYOUTS

    layout = SURFACE_LAYOUTS["queue"]
    assert "play_open_ended_buffer" in layout
    assert "category" in layout
    # Already present, must remain.
    assert "mark_watched" in layout
    assert "clear_unavailable" in layout


def test_history_and_epg_layouts_left_unchanged():
    """History / EPG are separate concerns — they must NOT gain the record extras."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS

    assert "category" not in SURFACE_LAYOUTS["history"]
    assert "clear_unavailable" not in SURFACE_LAYOUTS["history"]
    assert "mark_watched" not in SURFACE_LAYOUTS["epg_on_now"]
