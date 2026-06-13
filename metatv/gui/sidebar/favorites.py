"""FavoritesSection sidebar widget."""

from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.gui import theme as _theme
from metatv.gui.sidebar.base import CollapsibleSection, _fmt_channel_name


class FavoritesSection(CollapsibleSection):
    """Favorites section"""

    favoriteClicked = pyqtSignal(str)   # channel_id (double-click)
    itemSelected    = pyqtSignal(str)   # channel_id (single-click)
    _data_ready     = pyqtSignal(object)  # list[FavoriteDTO] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        self._executor = ThreadPoolExecutor(max_workers=1)
        super().__init__("Favorites", config.favorite_icon, config, parent)
        self._data_ready.connect(self._on_data_ready)
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
        self.favorites_list = QListWidget()
        self.favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_list.itemDoubleClicked.connect(self.on_favorite_clicked)
        self.favorites_list.currentItemChanged.connect(self.on_favorite_selected)
        self.content_layout.addWidget(self.favorites_list)

    def refresh(self):
        """Kick off an off-thread favorites load; clears the list immediately."""
        self.favorites_list.clear()
        self._executor.submit(self._bg_refresh)

    def _bg_refresh(self) -> None:
        from metatv.core.repositories.dtos import FavoriteDTO
        try:
            adult_mode = getattr(self.config, "filter_adult_mode", "all")
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                dtos = repos.channels.get_favorites_dto(adult_mode=adult_mode)
        except Exception:
            logger.exception("FavoritesSection bg refresh error")
            self._data_ready.emit(None)
            return
        self._data_ready.emit(dtos)

    def _on_data_ready(self, dtos) -> None:
        """Main-thread slot: populate favorites_list from DTOs."""
        self.favorites_list.clear()
        if dtos is None:
            return

        self.set_empty(len(dtos) == 0)
        if not dtos:
            item = QListWidgetItem("No favorites yet")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.favorites_list.addItem(item)
            item = QListWidgetItem("Right-click any channel to add to favorites")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.favorites_list.addItem(item)
            return

        continue_watching = sorted(
            [d for d in dtos if d.last_played], key=lambda d: d.last_played, reverse=True
        )
        never_watched = sorted(
            [d for d in dtos if not d.last_played], key=lambda d: d.name
        )

        if continue_watching:
            self._add_header("Continue Watching")
            for dto in continue_watching:
                self._add_item(dto)
        if never_watched:
            self._add_header("Never Watched")
            for dto in never_watched:
                self._add_item(dto)

    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self.favorites_list.addItem(item)

    def _add_item(self, dto) -> None:
        item = QListWidgetItem(
            f"{self._media_icon(dto.media_type)} {_fmt_channel_name(dto.name)}"
        )
        item.setData(Qt.ItemDataRole.UserRole, dto.id)
        self.favorites_list.addItem(item)

    def _media_icon(self, media_type) -> str:
        from metatv.core.models import MediaType
        if media_type == MediaType.LIVE:
            return self.config.live_icon
        if media_type == MediaType.MOVIE:
            return self.config.movie_icon
        if media_type == MediaType.SERIES:
            return self.config.series_icon
        return self.config.unknown_icon

    # kept for backwards compat (context menu code accesses this list directly)
    def get_media_icon(self, media_type):
        return self._media_icon(media_type)

    def on_favorite_clicked(self, item):
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.favoriteClicked.emit(channel_id)

    def on_favorite_selected(self, current, previous):
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)
