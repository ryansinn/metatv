"""Reusable middle-click support for plain ``QListWidget`` movie surfaces.

The channel list (a ``QListView``) has its own ``ChannelListView.middle_clicked``
signal.  The sidebar sections (Recommended / Queue / Favorites) and the Discover
"See all" list view instead use plain ``QListWidget``s, so this installs the same
middle-click-to-play gesture on any of them without copy-pasting the handler:

    self._mc = install_list_middle_click(self._list)
    self._mc.middleClicked.connect(self._dispatch_middle_click)

On a middle-button press over an item, ``middleClicked`` fires with the item's
``Qt.ItemDataRole.UserRole`` value (the channel id) — matching the channel
list's contract — so the host can route it through the one middle-click seam
(``MainWindow._dispatch_middle_click``).  Presses on empty space or on items
with no id (section headers / placeholders) are ignored.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QListWidget


class ListMiddleClickFilter(QObject):
    """Event filter that emits ``middleClicked(channel_id)`` for a ``QListWidget``.

    Installed on the list's viewport.  Reads the channel id from the item under
    the cursor (``Qt.ItemDataRole.UserRole``) and ignores presses on empty space
    or on items with no id (headers / placeholders).
    """

    middleClicked = pyqtSignal(str)  # channel_id under the middle-click

    def __init__(self, list_widget: QListWidget) -> None:
        super().__init__(list_widget)
        self._list = list_widget
        list_widget.viewport().installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.MiddleButton
        ):
            item = self._list.itemAt(event.position().toPoint())
            if item is not None:
                channel_id = item.data(Qt.ItemDataRole.UserRole)
                if channel_id:
                    self.middleClicked.emit(channel_id)
                    return True
        return super().eventFilter(obj, event)


def install_list_middle_click(list_widget: QListWidget) -> ListMiddleClickFilter:
    """Install middle-click-to-play on *list_widget* and return the filter.

    The returned :class:`ListMiddleClickFilter` owns a ``middleClicked(str)``
    signal; the caller keeps a reference (it is parented to *list_widget* so it
    lives as long as the list) and connects the signal to the middle-click seam.

    Args:
        list_widget: A ``QListWidget`` whose items carry a channel id in
            ``Qt.ItemDataRole.UserRole``.

    Returns:
        The installed :class:`ListMiddleClickFilter`.
    """
    return ListMiddleClickFilter(list_widget)
