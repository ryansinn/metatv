"""HistorySection and HistoryItemWidget."""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from metatv.core.repositories import RepositoryFactory
from metatv.gui.chip_row import build_chip_row
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection
from metatv.gui import theme as _theme


class HistoryItemWidget(QWidget):
    """Custom widget for history list items with play next button"""

    playNextClicked = pyqtSignal(str)  # channel_id

    def __init__(self, channel_id, text, has_next_episode=False, parent=None):
        super().__init__(parent)
        self.channel_id = channel_id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        text_label = QLabel(text)
        text_label.setWordWrap(False)
        layout.addWidget(text_label, 1)

        if has_next_episode:
            next_btn = QPushButton(">>")
            next_btn.setFixedSize(30, 20)
            next_btn.setToolTip("Play next episode")
            next_btn.clicked.connect(lambda: self.playNextClicked.emit(self.channel_id))
            next_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {_theme.OVERLAY_BLUE_20};
                    border: 1px solid {_theme.COLOR_ACCENT_BLUE};
                    border-radius: 3px;
                    font-size: {_theme.FONT_MD};
                    font-weight: bold;
                    color: {_theme.COLOR_ACCENT_BLUE};
                }}
                QPushButton:hover {{
                    background-color: {_theme.OVERLAY_BLUE_40};
                }}
                QPushButton:pressed {{
                    background-color: {_theme.OVERLAY_BLUE_60};
                }}
            """)
            layout.addWidget(next_btn)

        self.setLayout(layout)


class HistorySection(BackgroundRefreshMixin, CollapsibleSection):
    """Playback history section"""

    EXPLORE_KEY = "history"

    historyItemClicked = pyqtSignal(str)   # channel_id (double-click)
    itemSelected       = pyqtSignal(str)   # channel_id (single-click)
    clearHistoryClicked = pyqtSignal()
    # "Explore →" (open the Watch-History trail-map) is the shared base-class
    # ``exploreClicked`` signal — see CollapsibleSection._add_explore_link.
    _data_ready        = pyqtSignal(object)  # list[HistoryDTO] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("History", config.history_icon, config, parent)
        self._init_background_refresh()

    def get_section_id(self):
        return "history"

    def create_header(self):
        """Header with an "Explore →" link that opens the Watch-History trail-map."""
        header = self._build_clickable_header()
        hl = header.layout()
        self.title_label = QLabel(f"{self.icon} <b>{self.title}</b>")
        hl.addWidget(self.title_label)
        hl.addStretch()
        self._add_explore_link(hl)
        self.main_layout.addWidget(header)

    def create_content(self):
        self.history_list = QListWidget()
        # Chip rows fit the sidebar width and elide — never scroll sideways (which
        # would push the right-aligned year/language chips off behind the scrollbar).
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.itemDoubleClicked.connect(self.on_history_item_clicked)
        self.history_list.currentItemChanged.connect(self.on_history_item_selected)
        _theme.apply_list_selection(self.history_list)
        self.content_layout.addWidget(self.history_list)

        self.clear_btn = QPushButton(f"{self.config.delete_icon} Clear History")
        self.clear_btn.clicked.connect(self.clearHistoryClicked.emit)
        self.content_layout.addWidget(self.clear_btn)

    # --- BackgroundRefreshMixin hooks ---
    def _refresh_list(self) -> QListWidget:
        return self.history_list

    def _load_error_message(self) -> str:
        return "Couldn't load history"

    def _load_rows(self):
        from metatv.core.repositories.dtos import build_history_dtos
        adult_mode = getattr(self.config, "filter_adult_mode", "all")
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            return build_history_dtos(repos, limit=30, adult_mode=adult_mode)

    def _populate_rows(self, dtos) -> None:
        """Main-thread slot: populate history_list from DTOs."""
        self.set_empty(len(dtos) == 0)
        if not dtos:
            return

        for dto in dtos:
            item = QListWidgetItem(self.history_list)
            item.setData(Qt.ItemDataRole.UserRole, dto.id)
            # Episode code kept visible as a suffix on the title. Middle-elision
            # preserves the END of the title, so the "→ S01E02" tail survives even
            # when the series name is truncated.
            title = dto.detected_title or dto.name
            if dto.episode_code:
                title = f"{title} → {dto.episode_code}"
            row = build_chip_row(
                media_icon=self._media_icon(dto.media_type),
                title=title,
                year=dto.detected_year,
                quality=dto.detected_quality,
                prefix=dto.detected_prefix,
            )
            # Width 0 → the item spans the viewport (no sideways scroll); the row's own
            # height governs the row height.
            item.setSizeHint(QSize(0, row.sizeHint().height()))
            self.history_list.setItemWidget(item, row)

    def _media_icon(self, media_type) -> str:
        from metatv.core.models import MediaType
        if media_type == MediaType.LIVE:
            return self.config.live_icon
        if media_type == MediaType.MOVIE:
            return self.config.movie_icon
        if media_type == MediaType.SERIES:
            return self.config.series_icon
        return self.config.unknown_icon

    def on_history_item_clicked(self, item):
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.historyItemClicked.emit(channel_id)

    def on_history_item_selected(self, current, previous):
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)
