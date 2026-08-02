"""HistorySection."""

from PyQt6.QtWidgets import QLabel, QPushButton, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from metatv.core.repositories import RepositoryFactory
from metatv.gui.chip_row import build_chip_row
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection
from metatv.gui import theme as _theme


class HistorySection(BackgroundRefreshMixin, CollapsibleSection):
    """Playback history section"""

    EXPLORE_KEY = "history"

    historyItemClicked = pyqtSignal(str)   # channel_id (double-click)
    itemSelected       = pyqtSignal(str)   # channel_id (single-click)
    clearHistoryClicked = pyqtSignal()
    playNextClicked     = pyqtSignal(str)  # episode_id — the row's ">>" "Play Next Episode" button
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
            trailing_button = self._build_play_next_button(dto) if dto.has_next else None
            row = build_chip_row(
                media_icon=self._media_icon(dto.media_type),
                title=title,
                year=dto.detected_year,
                quality=dto.detected_quality,
                prefix=dto.detected_prefix,
                trailing_button=trailing_button,
            )
            # Width 0 → the item spans the viewport (no sideways scroll); the row's own
            # height governs the row height.
            item.setSizeHint(QSize(0, row.sizeHint().height()))
            self.history_list.setItemWidget(item, row)

    def _build_play_next_button(self, dto) -> QPushButton:
        """Build the row's ">>" "Play Next Episode" button (Wave 5).

        Only called for rows where ``dto.has_next`` is True (a series with a
        resolved smart-ladder resume target — see
        ``EpisodeRepository.get_resume_dto``). Emits :attr:`playNextClicked` with
        the resume target's episode id; MainWindow wires that straight into the
        existing :meth:`~metatv.gui.main_window_series.play_episode_by_id`
        chokepoint, so this row never grows its own play path.
        """
        next_btn = QPushButton(">>")
        next_btn.setFixedSize(30, 20)
        next_btn.setToolTip(f"Play next episode: {dto.next_episode_code}")
        next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        next_btn.setStyleSheet(_theme.HISTORY_PLAY_NEXT_BUTTON)
        episode_id = dto.next_episode_id
        next_btn.clicked.connect(lambda: self.playNextClicked.emit(episode_id))
        return next_btn

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
