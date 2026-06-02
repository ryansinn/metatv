"""HistorySection and HistoryItemWidget."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

from metatv.core.repositories import RepositoryFactory
from metatv.gui.sidebar.base import CollapsibleSection


class HistoryItemWidget(QWidget):
    """Custom widget for history list items with play next button"""

    playNextClicked = pyqtSignal(str)  # channel_id

    def __init__(self, channel_id, text, has_next_episode=False, parent=None):
        super().__init__(parent)
        self.channel_id = channel_id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        # Text label (series name + episode info)
        text_label = QLabel(text)
        text_label.setWordWrap(False)
        layout.addWidget(text_label, 1)  # Stretch factor 1

        # Play next button (only show if there's a next episode)
        if has_next_episode:
            next_btn = QPushButton(">>")
            next_btn.setFixedSize(30, 20)
            next_btn.setToolTip("Play next episode")
            next_btn.clicked.connect(lambda: self.playNextClicked.emit(self.channel_id))
            next_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(68, 136, 255, 0.2);
                    border: 1px solid #4488ff;
                    border-radius: 3px;
                    font-size: 11px;
                    font-weight: bold;
                    color: #4488ff;
                }
                QPushButton:hover {
                    background-color: rgba(68, 136, 255, 0.4);
                }
                QPushButton:pressed {
                    background-color: rgba(68, 136, 255, 0.6);
                }
            """)
            layout.addWidget(next_btn)

        self.setLayout(layout)


class HistorySection(CollapsibleSection):
    """Playback history section"""

    historyItemClicked = pyqtSignal(str)  # channel_id (double-click)
    itemSelected = pyqtSignal(str)  # channel_id (single-click)
    clearHistoryClicked = pyqtSignal()

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("History", config.history_icon, config, parent)

    def get_section_id(self):
        return "history"

    def create_content(self):
        """Create history list and clear button"""
        from PyQt6.QtWidgets import QListWidget

        # History list
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(150)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.itemDoubleClicked.connect(self.on_history_item_clicked)
        self.history_list.currentItemChanged.connect(self.on_history_item_selected)
        self.content_layout.addWidget(self.history_list)

        # Clear button
        self.clear_btn = QPushButton(f"{self.config.delete_icon} Clear History")
        self.clear_btn.clicked.connect(self.clearHistoryClicked.emit)
        self.content_layout.addWidget(self.clear_btn)

    def refresh(self):
        """Load history from database — shows all providers, no filtering"""
        from metatv.core.models import MediaType

        self.history_list.clear()

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            adult_mode = getattr(self.config, "filter_adult_mode", "all")
            recent = repos.channels.get_recent_history(limit=30, adult_mode=adult_mode)

            self.set_empty(len(recent) == 0)

            if len(recent) == 0:
                return

            for channel in recent:
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(self.history_list)

                media_icon = self.get_media_icon(channel.media_type)

                if channel.media_type == MediaType.SERIES:
                    last_episode = repos.episodes.get_last_played(
                        series_id=channel.source_id,
                        provider_id=channel.provider_id
                    )
                    if last_episode:
                        episode_code = f"S{last_episode.season_num:02d}E{last_episode.episode_num:02d}"
                        item.setText(f"{media_icon} {channel.name}\n   → {episode_code}")
                    else:
                        item.setText(f"{media_icon} {channel.name}")
                else:
                    item.setText(f"{media_icon} {channel.name}")

                item.setData(Qt.ItemDataRole.UserRole, channel.id)
        finally:
            session.close()

    def get_media_icon(self, media_type):
        """Get icon for media type"""
        from metatv.core.models import MediaType
        if media_type == MediaType.LIVE:
            return self.config.live_icon
        elif media_type == MediaType.MOVIE:
            return self.config.movie_icon
        elif media_type == MediaType.SERIES:
            return self.config.series_icon
        return self.config.unknown_icon

    def on_history_item_clicked(self, item):
        """Handle history item double-click"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.historyItemClicked.emit(channel_id)

    def on_history_item_selected(self, current, previous):
        """Handle history item single-click selection"""
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)
