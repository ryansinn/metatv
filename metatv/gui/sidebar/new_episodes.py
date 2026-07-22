"""NewEpisodesSection — sidebar section showing series with new unseen episodes."""

from PyQt6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.sidebar.base import CollapsibleSection

_ROLE_CHANNEL_ID = Qt.ItemDataRole.UserRole


class NewEpisodesSection(CollapsibleSection):
    """Sidebar section showing series being monitored that have unseen new episodes.

    This section reads directly from ``config.get_monitored_series()`` (an
    in-memory list), so no background thread is needed — ``refresh()`` is
    synchronous.
    """

    # Emitted when the user single-clicks a series row (channel_id)
    seriesClicked = pyqtSignal(str)
    # Emitted when the user clicks "Mark seen" for a series (channel_id)
    markSeenClicked = pyqtSignal(str)
    # Emitted when the user clicks "Manage alerts…" — host opens the dialog
    manageRequested = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__("New Episodes", _icons.new_episodes_icon, config, parent)
        self.set_empty(True)

    def get_section_id(self) -> str:
        return "new_episodes"

    def create_content(self) -> None:
        """Create the list widget + a persistent 'Manage alerts…' affordance."""
        self._list = QListWidget()
        self._list.setToolTip("Series with new episodes since your last visit")
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.content_layout.addWidget(self._list)

        # Always-visible entry to the see-all / stop-alerts dialog.
        self._manage_btn = QPushButton(f"{_icons.manage_icon} Manage alerts…")
        self._manage_btn.setFlat(True)
        self._manage_btn.setToolTip("See every series you're alerting on and stop any of them")
        self._manage_btn.setStyleSheet(
            f"QPushButton {{ font-size: {_theme.FONT_SM}; color: {_theme.COLOR_ACCENT_BLUE};"
            f" border: none; padding: 2px; text-align: left; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_BLUE_2}; }}"
        )
        self._manage_btn.clicked.connect(lambda: self.manageRequested.emit())
        self.content_layout.addWidget(self._manage_btn)

    # ------------------------------------------------------------------
    # Refresh (synchronous — reads in-memory config)
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read config and repopulate the list."""
        self._list.clear()

        entries = self.config.get_monitored_series()
        with_new = [e for e in entries if e.get("unseen_new", 0) > 0]

        if not with_new:
            item = QListWidgetItem("No new episodes")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor(_theme.COLOR_MUTED))
            self._list.addItem(item)
            self.set_empty(True)
            return

        self.set_empty(False)

        for entry in with_new:
            cid = entry.get("series_channel_id", "")
            title = entry.get("title", "Unknown series")
            unseen = entry.get("unseen_new", 0)
            ep_word = "ep" if unseen == 1 else "eps"

            # Main row: icon + title + count
            row_widget_item = QListWidgetItem(
                f"{_icons.new_episodes_icon} {title}   +{unseen} {ep_word}"
            )
            row_widget_item.setData(_ROLE_CHANNEL_ID, cid)
            row_widget_item.setToolTip(
                f"{title}\n{unseen} new {ep_word} — click to open, "
                "right-click or use 'Mark seen' to clear"
            )
            self._list.addItem(row_widget_item)

            # "Mark seen" sub-row (non-selectable, small button via item text)
            seen_item = QListWidgetItem(f"   {_icons.watched_icon} Mark seen")
            seen_item.setData(_ROLE_CHANNEL_ID, f"__mark_seen__{cid}")
            seen_item.setForeground(QColor(_theme.COLOR_MUTED))
            seen_item.setToolTip(f"Mark all new episodes of {title} as seen")
            self._list.addItem(seen_item)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_selection_changed(
        self, current: QListWidgetItem, _previous: QListWidgetItem
    ) -> None:
        if current is None:
            return
        raw = current.data(_ROLE_CHANNEL_ID)
        if raw and isinstance(raw, str):
            if raw.startswith("__mark_seen__"):
                cid = raw[len("__mark_seen__"):]
                if cid:
                    self.markSeenClicked.emit(cid)
                    # Deselect so the user can click it again after more episodes arrive
                    self._list.clearSelection()
            elif raw:
                self.seriesClicked.emit(raw)
