"""FavoritesSection sidebar widget."""

from PyQt6.QtWidgets import QLabel, QPushButton, QSizePolicy, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from metatv.core.repositories import RepositoryFactory
from metatv.gui import theme as _theme
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection, _fmt_channel_name

_ROLE_AVAILABLE    = Qt.ItemDataRole.UserRole + 1
_ROLE_SEARCH_TITLE = Qt.ItemDataRole.UserRole + 2

_UNAVAILABLE_TOOLTIP = "Source unavailable — double-click to find this on another source."


class FavoritesSection(BackgroundRefreshMixin, CollapsibleSection):
    """Favorites section"""

    favoriteClicked         = pyqtSignal(str)   # channel_id (double-click, available only)
    itemSelected            = pyqtSignal(str)   # channel_id (single-click)
    channelMiddleClicked    = pyqtSignal(str)   # channel_id — configured middle-click play
    searchRequested         = pyqtSignal(str)   # search_title — double-click on unavailable
    clearUnavailableClicked = pyqtSignal()      # request clear-unavailable
    _data_ready             = pyqtSignal(object)  # list[FavoriteDTO] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        self._has_unavailable = False
        super().__init__("Favorites", config.favorite_icon, config, parent)
        self._init_background_refresh()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "favorites"

    def create_header(self):
        header = self._build_clickable_header()
        hl = header.layout()
        self.title_label = QLabel(
            f'<span style="color:{_theme.COLOR_GOLD}">{self.icon}</span> <b>{self.title}</b>'
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
        # Middle-click plays the user-configured action (same seam as the channel
        # list) via the shared QListWidget helper — no per-section handler copy.
        from metatv.gui.list_middle_click import install_list_middle_click
        self._list_mc = install_list_middle_click(self.favorites_list)
        self._list_mc.middleClicked.connect(self.channelMiddleClicked)
        self.content_layout.addWidget(self.favorites_list)

    # --- BackgroundRefreshMixin hooks ---
    def _refresh_list(self) -> QListWidget:
        return self.favorites_list

    def _load_error_message(self) -> str:
        return "Couldn't load favorites"

    def _load_rows(self):
        adult_mode = getattr(self.config, "filter_adult_mode", "all")
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            hidden = set(repos.providers.get_hidden_provider_ids())
            return repos.channels.get_favorites_dto(
                adult_mode=adult_mode,
                hidden_provider_ids=hidden,
            )

    def _populate_rows(self, dtos) -> None:
        """Main-thread slot: populate favorites_list from DTOs."""
        self._has_unavailable = any(not d.available for d in dtos) if dtos else False
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
            f"{self._media_icon(dto.media_type)} "
            f"{_fmt_channel_name(dto.name, detected_title=dto.search_title, detected_region=dto.detected_region, detected_quality=dto.detected_quality, detected_year=dto.detected_year)}"
        )
        item.setData(Qt.ItemDataRole.UserRole, dto.id)
        item.setData(_ROLE_AVAILABLE, dto.available)
        item.setData(_ROLE_SEARCH_TITLE, dto.search_title)
        if not dto.available:
            item.setForeground(QColor(_theme.COLOR_MUTED))
            item.setToolTip(_UNAVAILABLE_TOOLTIP)
        self.favorites_list.addItem(item)

    def has_unavailable(self) -> bool:
        """True when at least one favorite in the current list is unavailable."""
        return self._has_unavailable

    def _media_icon(self, media_type) -> str:
        from metatv.core.models import MediaType
        if media_type == MediaType.LIVE:
            return self.config.live_icon
        if media_type == MediaType.MOVIE:
            return self.config.movie_icon
        if media_type == MediaType.SERIES:
            return self.config.series_icon
        return self.config.unknown_icon

    def on_favorite_clicked(self, item):
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        available = item.data(_ROLE_AVAILABLE)
        if available is False:
            search_title = item.data(_ROLE_SEARCH_TITLE) or ""
            self.searchRequested.emit(search_title)
        else:
            self.favoriteClicked.emit(channel_id)

    def on_favorite_selected(self, current, previous):
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)
