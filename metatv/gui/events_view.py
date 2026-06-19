"""Live Events channel browser — simple searchable list of [EVENT] channels."""

from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal
from loguru import logger

from metatv.core.database import ChannelDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui.content_view import ContentView
from metatv.gui import theme as _theme


class EventsView(ContentView):
    """Live events channel list.

    Shows channels with ``special_view == 'live_event'`` in a searchable
    QListWidget. No countdown timers or card layout — just a fast, filterable
    list consistent with the rest of the channel browser.
    """

    play_channel_requested = pyqtSignal(object)  # ChannelDB

    _channels_loaded = pyqtSignal(list)  # List[ChannelDB]

    def __init__(self, config, db, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        self.db = db
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="EventsView"
        )
        self._all_channels: List[ChannelDB] = []
        self._search_initialized = False

        self._setup_ui()
        self._channels_loaded.connect(self._on_channels_loaded)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header row
        header = QHBoxLayout()
        title = QLabel("🎪 Live Events")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        self.refresh_btn = QPushButton("⟳ Refresh")
        self.refresh_btn.setToolTip("Reload event channels")
        self.refresh_btn.clicked.connect(self.on_activate)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        # Inline search with clear button
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search events…")
        self.search_input.textChanged.connect(self._apply_search)
        self.search_input.textChanged.connect(self._save_filter_state)
        search_row.addWidget(self.search_input, 1)
        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(24)
        clear_btn.setToolTip("Clear")
        clear_btn.setStyleSheet(f"border: none; color: {_theme.COLOR_DISABLED}; font-size: 10px;")
        clear_btn.clicked.connect(self.search_input.clear)
        search_row.addWidget(clear_btn)
        layout.addLayout(search_row)

        # Channel list
        self.channel_list = QListWidget()
        self.channel_list.itemDoubleClicked.connect(self._on_double_click)
        self.channel_list.currentItemChanged.connect(self._on_selection_changed)
        self.channel_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        layout.addWidget(self.channel_list)

        # Stats label
        self.stats_label = QLabel("Loading…")
        self.stats_label.setStyleSheet(f"color: {_theme.COLOR_MUTED_2}; font-size: 12px;")
        layout.addWidget(self.stats_label)

    # ------------------------------------------------------------------
    # ContentView interface
    # ------------------------------------------------------------------

    def on_activate(self) -> None:
        """Load events channels when the view becomes active."""
        self._all_channels = []
        self.channel_list.clear()
        self.stats_label.setText("Loading…")
        self.refresh_btn.setEnabled(False)
        self.executor.submit(self._fetch_channels)

    def get_view_name(self) -> str:
        return "Live Events"

    def get_selected_channel(self) -> Optional[ChannelDB]:
        item = self.channel_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole + 1)
        return None

    def get_events_channel_count(self) -> int:
        """Return total number of event channels (for chip badge)."""
        session = self.db.get_session()
        try:
            return session.query(ChannelDB).filter(
                ChannelDB.special_view == 'live_event'
            ).count()
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _fetch_channels(self) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channels = repos.channels.get_events_channels()
            self._channels_loaded.emit(channels)
        except Exception as e:
            logger.error(f"EventsView: failed to load events: {e}")
            self._channels_loaded.emit([])
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Main-thread slots
    # ------------------------------------------------------------------

    def _on_channels_loaded(self, channels: List[ChannelDB]) -> None:
        self._all_channels = channels
        self.refresh_btn.setEnabled(True)

        # First load: restore saved search text from config
        if not self._search_initialized:
            saved = self.config.events_filter_state
            if saved.get('search_text'):
                self.search_input.blockSignals(True)
                self.search_input.setText(saved['search_text'])
                self.search_input.blockSignals(False)
            self._search_initialized = True

        self._apply_search(self.search_input.text())

    def _save_filter_state(self, _text: str = '') -> None:
        """Persist current search text to config for cross-session restore."""
        self.config.events_filter_state = {'search_text': self.search_input.text()}
        self.config.save()

    def _apply_search(self, text: str) -> None:
        """Filter the list in memory based on search text."""
        query = text.lower().strip()
        visible = [
            ch for ch in self._all_channels
            if not query or query in ch.name.lower()
        ]
        self._populate_list(visible)

    def _populate_list(self, channels: List[ChannelDB]) -> None:
        self.channel_list.setUpdatesEnabled(False)
        self.channel_list.clear()

        for ch in channels:
            item = QListWidgetItem(ch.name)
            item.setData(Qt.ItemDataRole.UserRole, ch.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, ch)
            self.channel_list.addItem(item)

        self.channel_list.setUpdatesEnabled(True)

        count = len(channels)
        total = len(self._all_channels)
        if count < total:
            self.stats_label.setText(f"{count:,} of {total:,} events")
        else:
            self.stats_label.setText(f"{count:,} live events")
        self.status_message.emit(f"{count:,} live events")

    # ------------------------------------------------------------------
    # Interaction handlers
    # ------------------------------------------------------------------

    def _on_double_click(self, item: QListWidgetItem) -> None:
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            ch = repos.channels.get_by_id(channel_id)
            if ch:
                self.play_channel_requested.emit(ch)
        finally:
            session.close()

    def _on_selection_changed(
        self, current: QListWidgetItem, _previous: QListWidgetItem
    ) -> None:
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            ch = repos.channels.get_by_id(channel_id)
            if ch:
                self.channel_selected.emit(ch)
        finally:
            session.close()

    def closeEvent(self, event) -> None:
        self.executor.shutdown(wait=False)
        super().closeEvent(event)
