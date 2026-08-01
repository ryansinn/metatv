"""FavoritesSection sidebar widget."""

from PyQt6.QtWidgets import (
    QLabel, QPushButton, QSizePolicy, QListWidget, QListWidgetItem,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QFont

from metatv.core.repositories import RepositoryFactory
from metatv.gui import theme as _theme
from metatv.gui.chip_row import build_chip_row
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection

_ROLE_AVAILABLE    = Qt.ItemDataRole.UserRole + 1
_ROLE_SEARCH_TITLE = Qt.ItemDataRole.UserRole + 2
_ROLE_GRAIN        = Qt.ItemDataRole.UserRole + 3   # "channel" | "episode" (Wave 2 Slice 2B)

_UNAVAILABLE_TOOLTIP = "Source unavailable — double-click to find this on another source."


class FavoritesSection(BackgroundRefreshMixin, CollapsibleSection):
    """Favorites section"""

    EXPLORE_KEY = "favorites"

    favoriteClicked         = pyqtSignal(str)   # channel_id (double-click, available only)
    episodeFavoriteClicked  = pyqtSignal(str)   # episode_id (double-click on a favorited episode)
    itemSelected            = pyqtSignal(str)   # channel_id (single-click)
    channelMiddleClicked    = pyqtSignal(str)   # channel_id — configured middle-click play
    searchRequested         = pyqtSignal(str)   # search_title — double-click on unavailable
    clearUnavailableClicked = pyqtSignal()      # request clear-unavailable
    _data_ready             = pyqtSignal(object)  # (list[FavoriteDTO], list[EpisodeFavoriteDTO]) | None

    def __init__(self, config, db, parent=None):
        self.db = db
        self._has_unavailable = False
        super().__init__("Favorites", config.favorite_icon, config, parent)
        self._init_background_refresh()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "favorites"

    def create_header(self):
        """Header with an "Explore →" link that opens the Favorites trail-map."""
        header = self._build_clickable_header()
        hl = header.layout()
        self.title_label = QLabel(
            f'<span style="color:{_theme.COLOR_GOLD}">{self.icon}</span> <b>{self.title}</b>'
        )
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        hl.addWidget(self.title_label)
        hl.addStretch()
        self._add_explore_link(hl)
        self.main_layout.addWidget(header)

    def create_content(self):
        self.favorites_list = QListWidget()
        # Chip rows fit the sidebar width and elide — never scroll sideways (which
        # would push the right-aligned year/language chips off behind the scrollbar).
        self.favorites_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_list.itemDoubleClicked.connect(self.on_favorite_clicked)
        self.favorites_list.currentItemChanged.connect(self.on_favorite_selected)
        # Middle-click plays the user-configured action (same seam as the channel
        # list) via the shared QListWidget helper — no per-section handler copy.
        from metatv.gui.list_middle_click import install_list_middle_click
        self._list_mc = install_list_middle_click(self.favorites_list)
        self._list_mc.middleClicked.connect(self.channelMiddleClicked)
        _theme.apply_list_selection(self.favorites_list)
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
            channel_dtos = repos.channels.get_favorites_dto(
                adult_mode=adult_mode,
                hidden_provider_ids=hidden,
            )
            episode_dtos = repos.episodes.get_favorites_dto(hidden_provider_ids=hidden)
            return channel_dtos, episode_dtos

    def _populate_rows(self, data) -> None:
        """Main-thread slot: populate favorites_list from (channel, episode) DTOs."""
        dtos, episode_dtos = data
        # "Clear Unavailable" only sweeps channel-grain favorites today (see
        # main_window_favorites._clear_unavailable_favorites) — episode favorites
        # are still shown dimmed with a recovery tooltip, just not counted here so
        # the bulk action's confirmation count matches what it actually removes.
        self._has_unavailable = any(not d.available for d in dtos) if dtos else False
        self.set_empty(len(dtos) == 0 and len(episode_dtos) == 0)
        if not dtos and not episode_dtos:
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
        if episode_dtos:
            self._add_header("Favorited Episodes")
            for dto in episode_dtos:
                self._add_episode_item(dto)

    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self.favorites_list.addItem(item)

    def _add_item(self, dto) -> None:
        """Add a single favorite as the shared chip row, dimming unavailable ones."""
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, dto.id)
        item.setData(_ROLE_AVAILABLE, dto.available)
        item.setData(_ROLE_SEARCH_TITLE, dto.search_title)
        row = build_chip_row(
            media_icon=self._media_icon(dto.media_type),
            title=dto.search_title or dto.name,
            year=dto.detected_year,
            quality=dto.detected_quality,
            prefix=dto.detected_prefix,
        )
        if not dto.available:
            # A custom item widget ignores the item's foreground role, so dim the whole
            # row via a translucency effect (opacity, not a colour literal) and keep the
            # recovery tooltip on the item (mouse-transparent row → item shows it).
            effect = QGraphicsOpacityEffect(row)
            effect.setOpacity(0.45)
            row.setGraphicsEffect(effect)
            item.setToolTip(_UNAVAILABLE_TOOLTIP)
        # Width 0 → the item spans the viewport (no sideways scroll); the row's own
        # height governs the row height.
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self.favorites_list.addItem(item)
        self.favorites_list.setItemWidget(item, row)

    def _add_episode_item(self, dto) -> None:
        """Add a single favorited EPISODE as the shared chip row (Wave 2 Slice 2B).

        Rendered ``Series — S##E## Title``, tagged _ROLE_GRAIN="episode" so
        on_favorite_clicked routes the double-click through episodeFavoriteClicked
        (episode_id) instead of favoriteClicked (channel_id).
        """
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, dto.id)
        item.setData(_ROLE_GRAIN, "episode")
        item.setData(_ROLE_AVAILABLE, dto.available)
        code = (
            f"S{dto.season_num:02d}E{dto.episode_num:02d}"
            if dto.season_num and dto.episode_num
            else f"E{dto.episode_num}" if dto.episode_num else ""
        )
        title = f"{dto.series_name} — {code}" if code else dto.series_name
        if dto.title:
            title += f" {dto.title}"
        row = build_chip_row(media_icon=self.config.series_icon, title=title)
        if not dto.available:
            effect = QGraphicsOpacityEffect(row)
            effect.setOpacity(0.45)
            row.setGraphicsEffect(effect)
            item.setToolTip(_UNAVAILABLE_TOOLTIP)
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self.favorites_list.addItem(item)
        self.favorites_list.setItemWidget(item, row)

    def has_unavailable(self) -> bool:
        """True when at least one CHANNEL-grain favorite in the current list is unavailable."""
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
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if not item_id:
            return
        available = item.data(_ROLE_AVAILABLE)
        if available is False:
            search_title = item.data(_ROLE_SEARCH_TITLE) or ""
            self.searchRequested.emit(search_title)
        elif item.data(_ROLE_GRAIN) == "episode":
            self.episodeFavoriteClicked.emit(item_id)
        else:
            self.favoriteClicked.emit(item_id)

    def on_favorite_selected(self, current, previous):
        if not current:
            return
        if current.data(_ROLE_GRAIN) == "episode":
            # Episode-favorite rows don't drive the details pane yet (Slice 2B
            # scope is play-on-double-click); single-click is a no-op for them.
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)
