"""Sports channel browser with cascading Sport → League filters."""

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal
from loguru import logger

from metatv.core.database import ChannelDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui.content_view import ContentView
from metatv.gui.sports_filter_bar import SportsFilterBar


class SportsView(ContentView):
    """Sports channel browser with cascading sport/league/team filters.

    Loading flow:
        1. ``on_activate()`` → background: fetch taxonomy
        2. ``_taxonomy_loaded`` signal → main thread: populate filter dropdowns
        3. ``_load_channels()`` → background: fetch filtered channels
        4. ``_channels_loaded`` signal → main thread: apply in-memory team filter
           → populate list
    """

    play_channel_requested = pyqtSignal(object)  # ChannelDB

    # Thread-safe signals (private — internal implementation detail)
    _taxonomy_loaded = pyqtSignal(object, object)  # (taxonomy Dict, counts Dict)
    _channels_loaded = pyqtSignal(list)            # List[ChannelDB]

    def __init__(self, config, db, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        self.db = db
        self.executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="SportsView"
        )
        self._channels: List[ChannelDB] = []
        self._taxonomy_initialized = False  # True after first successful taxonomy load

        self._setup_ui()

        self._taxonomy_loaded.connect(self._on_taxonomy_loaded)
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
        title = QLabel("⚽ Sports")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.on_activate)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        # Cascade filter bar
        self.filter_bar = SportsFilterBar()
        self.filter_bar.filter_changed.connect(self._on_filter_changed)
        layout.addWidget(self.filter_bar)

        # Inline text search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search sports channels…")
        self.search_input.textChanged.connect(self._apply_search)
        self.search_input.textChanged.connect(self._save_filter_state)
        layout.addWidget(self.search_input)

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
        self.stats_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.stats_label)

    # ------------------------------------------------------------------
    # ContentView interface
    # ------------------------------------------------------------------

    def on_activate(self) -> None:
        """Load taxonomy and channels when the view becomes active."""
        self.channel_list.clear()
        self.stats_label.setText("Loading…")
        self.refresh_btn.setEnabled(False)
        self.executor.submit(self._fetch_taxonomy)

    def get_view_name(self) -> str:
        return "Sports"

    def get_selected_channel(self) -> Optional[ChannelDB]:
        item = self.channel_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole + 1)
        return None

    def get_sports_channel_count(self) -> int:
        """Return total number of sports channels (for badge in chip)."""
        session = self.db.get_session()
        try:
            return session.query(ChannelDB).filter(
                ChannelDB.special_view == 'sports'
            ).count()
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Background workers
    # ------------------------------------------------------------------

    def _fetch_taxonomy(self) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            taxonomy = repos.channels.get_sports_taxonomy()
            counts = repos.channels.get_sports_counts()
            self._taxonomy_loaded.emit(taxonomy, counts)
        except Exception as e:
            logger.error(f"SportsView: failed to load taxonomy: {e}")
            self._taxonomy_loaded.emit({}, {})
        finally:
            session.close()

    def _fetch_channels(self, sport_types: List[str], league_names: List[str]) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channels = repos.channels.get_sports_channels(
                sport_types=sport_types or None,
                league_names=league_names or None,
            )
            self._channels_loaded.emit(channels)
        except Exception as e:
            logger.error(f"SportsView: failed to load channels: {e}")
            self._channels_loaded.emit([])
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Main-thread slots
    # ------------------------------------------------------------------

    def _on_taxonomy_loaded(self, taxonomy: Dict, counts: Dict) -> None:
        self.filter_bar.load_taxonomy(taxonomy, sport_counts=counts)

        if not self._taxonomy_initialized:
            # First load: restore last session's filter state from config
            saved = self.config.sports_filter_state
            if saved:
                self.filter_bar.restore_filter_state(saved)
                search_text = saved.get('search_text', '')
                if search_text:
                    self.search_input.blockSignals(True)
                    self.search_input.setText(search_text)
                    self.search_input.blockSignals(False)
            self._taxonomy_initialized = True

        self._load_channels()

    def _on_channels_loaded(self, channels: List[ChannelDB]) -> None:
        self._channels = channels
        self.refresh_btn.setEnabled(True)
        self._apply_search(self.search_input.text())

    def _apply_search(self, text: str) -> None:
        """Filter the current channel list in memory by search text."""
        query = text.lower().strip()
        visible = [
            ch for ch in self._channels
            if not query or query in ch.name.lower()
        ]
        self._populate_list(visible)

    def _on_filter_changed(self) -> None:
        self._save_filter_state()
        self._load_channels()

    def _save_filter_state(self) -> None:
        """Persist current filter selections (including search text) to config."""
        state = self.filter_bar.get_filter_state()
        state['search_text'] = self.search_input.text()
        self.config.sports_filter_state = state
        self.config.save()

    def _load_channels(self) -> None:
        state = self.filter_bar.get_filter_state()
        self.executor.submit(
            self._fetch_channels,
            state['sport_types'],
            state['league_names'],
        )

    def _populate_list(self, channels: List[ChannelDB]) -> None:
        self.channel_list.setUpdatesEnabled(False)
        self.channel_list.clear()

        for ch in channels:
            parts = []
            if ch.sport_type and ch.sport_type != 'unknown':
                parts.append(f"[{ch.sport_type.replace('_', ' ').upper()}]")
            if ch.league_name:
                parts.append(f"[{ch.league_name}]")
            prefix = ' '.join(parts)
            display = f"{prefix}  {ch.name}" if prefix else ch.name

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, ch.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, ch)  # store object for selection
            self.channel_list.addItem(item)

        self.channel_list.setUpdatesEnabled(True)

        count = len(channels)
        total = len(self._channels)
        if count < total:
            self.stats_label.setText(f"{count:,} of {total:,} sports channels")
        else:
            self.stats_label.setText(f"{count:,} sports channels")
        self.status_message.emit(f"{count:,} sports channels")

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
