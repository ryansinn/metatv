"""WatchQueueSection — user's ordered watch queue."""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSizePolicy, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from metatv.core.repositories import RepositoryFactory
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection, _fmt_channel_name


class WatchQueueSection(BackgroundRefreshMixin, CollapsibleSection):
    """Sidebar section showing the user's ordered watch queue."""

    itemDoubleClicked             = pyqtSignal(str)        # channel_id
    itemSelected                  = pyqtSignal(str)        # channel_id
    channelContextMenuRequested   = pyqtSignal(str, int, int)  # channel_id, gx, gy
    clearQueueClicked             = pyqtSignal()
    clearWatchedClicked           = pyqtSignal()
    _data_ready                   = pyqtSignal(object)     # list[QueueEntry] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Watch Queue", config.queue_icon, config, parent)
        self._init_background_refresh()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "queue"

    def create_content(self):
        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self.content_layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._clear_watched_btn = QPushButton(f"{self.config.watched_icon} Clear Watched")
        self._clear_watched_btn.clicked.connect(self.clearWatchedClicked.emit)
        btn_row.addWidget(self._clear_watched_btn)

        self._clear_all_btn = QPushButton(f"{self.config.delete_icon} Clear All")
        self._clear_all_btn.clicked.connect(self.clearQueueClicked.emit)
        btn_row.addWidget(self._clear_all_btn)
        self.content_layout.addLayout(btn_row)

        self.set_empty(True)

    # --- BackgroundRefreshMixin hooks ---
    def _refresh_list(self) -> QListWidget:
        return self._list

    def _load_error_message(self) -> str:
        return "Couldn't load watch queue"

    def _load_rows(self):
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            return repos.queue.get_all()

    def _populate_rows(self, entries) -> None:
        """Main-thread slot: populate the queue list from QueueEntry plain dataclasses."""
        self.set_empty(len(entries) == 0)
        if not entries:
            item = QListWidgetItem("Queue is empty — right-click any channel to add")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            return

        continue_watching = sorted(
            [e for e in entries if e.last_played],
            key=lambda e: e.last_played,
            reverse=True,
        )
        never_watched = [e for e in entries if not e.last_played]

        if continue_watching:
            self._add_header("Continue Watching")
            for e in continue_watching:
                item = QListWidgetItem(
                    f"{self._media_icon(e.media_type)} {_fmt_channel_name(e.channel_name)}"
                )
                item.setData(Qt.ItemDataRole.UserRole, e.channel_id)
                self._list.addItem(item)

        if never_watched:
            self._add_header("Never Watched")
            for e in never_watched:
                item = QListWidgetItem(
                    f"{self._media_icon(e.media_type)} {_fmt_channel_name(e.channel_name)}"
                )
                item.setData(Qt.ItemDataRole.UserRole, e.channel_id)
                self._list.addItem(item)

    def _media_icon(self, media_type: str) -> str:
        if media_type == "movie":
            return self.config.movie_icon
        if media_type == "series":
            return self.config.series_icon
        if media_type == "live":
            return self.config.live_icon
        return self.config.unknown_icon

    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self._list.addItem(item)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemDoubleClicked.emit(channel_id)

    def _on_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if current:
            channel_id = current.data(Qt.ItemDataRole.UserRole)
            if channel_id:
                self.itemSelected.emit(channel_id)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            gp = self._list.viewport().mapToGlobal(pos)
            self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())
