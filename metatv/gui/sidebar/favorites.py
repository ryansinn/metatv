"""FavoritesSection sidebar widget."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from metatv.core.repositories import RepositoryFactory
from metatv.gui import theme as _theme
from metatv.gui.sidebar.base import CollapsibleSection, _fmt_channel_name


class FavoritesSection(CollapsibleSection):
    """Favorites section"""

    favoriteClicked = pyqtSignal(str)  # channel_id (double-click)
    itemSelected = pyqtSignal(str)  # channel_id (single-click)

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Favorites", config.favorite_icon, config, parent)

        # Favorites should expand to fill remaining space
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "favorites"

    def create_header(self):
        header = QWidget()
        header.setStyleSheet(_theme.HEADER_TINT)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(5, 3, 5, 3)
        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        hl.addWidget(self.toggle_btn)
        self.title_label = QLabel(
            f'<span style="color:#FFD700">{self.icon}</span> <b>{self.title}</b>'
        )
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        hl.addWidget(self.title_label)
        hl.addStretch()
        self.main_layout.addWidget(header)

    def create_content(self):
        """Create favorites list"""
        from PyQt6.QtWidgets import QListWidget

        self.favorites_list = QListWidget()
        self.favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_list.itemDoubleClicked.connect(self.on_favorite_clicked)
        self.favorites_list.currentItemChanged.connect(self.on_favorite_selected)
        self.content_layout.addWidget(self.favorites_list)

    def refresh(self):
        """Load favorites from database — shows all providers, no filtering"""
        self.favorites_list.clear()

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            adult_mode = getattr(self.config, "filter_adult_mode", "all")
            all_favorites = repos.channels.get_favorites(adult_mode=adult_mode)

            self.set_empty(len(all_favorites) == 0)

            if len(all_favorites) == 0:
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem("No favorites yet")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.favorites_list.addItem(item)
                item = QListWidgetItem("Right-click any channel to add to favorites")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.favorites_list.addItem(item)
                return

            # Separate into continue watching and never watched
            continue_watching = [c for c in all_favorites if c.last_played]
            never_watched = [c for c in all_favorites if not c.last_played]

            # Sort
            continue_watching.sort(key=lambda c: c.last_played, reverse=True)
            never_watched.sort(key=lambda c: c.name)

            # Add headers and items
            if continue_watching:
                self.add_header("Continue Watching")
                for channel in continue_watching:
                    self.add_favorite_item(channel)

            if never_watched:
                self.add_header("Never Watched")
                for channel in never_watched:
                    self.add_favorite_item(channel)
        finally:
            session.close()

    def add_header(self, text):
        """Add a section header"""
        from PyQt6.QtWidgets import QListWidgetItem

        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self.favorites_list.addItem(item)

    def add_favorite_item(self, channel):
        """Add a favorite channel item"""
        from PyQt6.QtWidgets import QListWidgetItem

        item = QListWidgetItem(self.favorites_list)

        # Get media type icon
        media_icon = self.get_media_icon(channel.media_type)

        item.setText(f"{media_icon} {_fmt_channel_name(channel.name)}")
        item.setData(Qt.ItemDataRole.UserRole, channel.id)

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

    def on_favorite_clicked(self, item):
        """Handle favorite item double-click"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.favoriteClicked.emit(channel_id)

    def on_favorite_selected(self, current, previous):
        """Handle favorite item single-click selection"""
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)
