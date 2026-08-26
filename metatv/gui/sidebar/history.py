"""HistorySection."""

from PyQt6.QtWidgets import QPushButton, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from metatv.core.repositories import RepositoryFactory
from metatv.gui.chip_row import (
    CHIP_YEAR, build_chip_row, media_icon_role, sidebar_meta_line,
)
from metatv.gui.relative_time import humanize_ago, humanize_ago_terse
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import SectionAction, CollapsibleSection, make_seamless
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


#: How many history entries to load. A bound on MEMORY, not a product decision
#: about how much history is worth keeping: 30 was arbitrary from when a section
#: could only ever show a handful of rows, and once scrolling could reveal more
#: it became the ceiling a viewer hits rather than a height anyone chose.
HISTORY_ROW_LIMIT = 300


class HistorySection(BackgroundRefreshMixin, CollapsibleSection):
    """Playback history section"""
    def budgeted_list(self):
        """The rows this section fits to its height (see
        ``CollapsibleSection.apply_row_budget``)."""
        return self.__dict__.get("history_list")

    def item_count(self) -> int | None:
        """Rows currently rendered — inventory, shown only when
        :meth:`news` is quiet.

        Read off the list itself rather than tracked separately, so the
        header cannot claim a number the rows disagree with. The
        ``+N more`` tail is excluded: it is chrome, not content.
        """
        lst = self.__dict__.get("history_list")
        if lst is None:
            return None
        from metatv.gui.sidebar.base import _MORE_ROLE, _MORE_ROW
        from PyQt6.QtCore import Qt

        return sum(
            1 for i in range(lst.count())
            if lst.item(i).data(_MORE_ROLE) != _MORE_ROW
        )


    MIN_ROWS: int = 4

    EXPLORE_KEY = "history"

    historyItemClicked = pyqtSignal(str)   # channel_id (double-click)
    itemSelected       = pyqtSignal(str)   # channel_id (single-click)
    clearHistoryClicked = pyqtSignal()
    #: Age-scoped clear; carries the day threshold.
    clearOldHistoryClicked = pyqtSignal(int)
    playNextClicked     = pyqtSignal(str)  # episode_id — the row's ">>" "Play Next Episode" button
    # "Explore →" (open the Watch-History trail-map) is the shared base-class
    # ``exploreClicked`` signal — see CollapsibleSection._add_explore_link.
    _data_ready        = pyqtSignal(object)  # list[HistoryDTO] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("History", config.history_icon, config, parent,
                         vector_role="history")
        self._init_background_refresh()

    def get_section_id(self):
        return "history"

    def overflow_actions(self):
        return [
            # Both destructive, so both stay behind the ⋯ however few there
            # are. The older-than option exists because all-or-nothing made
            # tidying up an all-or-nothing decision — owner: "people aren't
            # wiping history daily ... add a second wipe history option that
            # wipes history older than a month".
            SectionAction(
                f"{self.config.delete_icon} Clear history older than 30 days",
                "Forget what you played more than a month ago, keeping "
                "everything since",
                lambda: self.clearOldHistoryClicked.emit(30),
                destructive=True,
            ),
            SectionAction(
                f"{self.config.delete_icon} Clear all history",
                "Remove every entry from your history",
                self.clearHistoryClicked.emit,
                destructive=True,
            ),
        ]

    def create_content(self):
        self.history_list = QListWidget()
        # Chip rows fit the sidebar width and elide — never scroll sideways (which
        # would push the right-aligned year/language chips off behind the scrollbar).
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.itemDoubleClicked.connect(self.on_history_item_clicked)
        self.history_list.currentItemChanged.connect(self.on_history_item_selected)
        make_seamless(self.history_list)
        self.content_layout.addWidget(self.history_list)

        # The destructive bulk action lives in the ⋯ overflow, like Watch
        # Queue's — a full-width button charged ~29px a session for something
        # you use once in a while.

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
            return build_history_dtos(
                repos, limit=HISTORY_ROW_LIMIT, adult_mode=adult_mode
            )

    def _populate_rows(self, dtos) -> None:
        """Main-thread slot: populate history_list from DTOs."""
        self.set_empty(len(dtos) == 0)
        if not dtos:
            return

        for dto in dtos:
            item = QListWidgetItem(self.history_list)
            item.setData(Qt.ItemDataRole.UserRole, dto.id)
            title = dto.detected_title or dto.name
            trailing_button = self._build_play_next_button(dto) if dto.has_next else None
            # The episode code moves OFF the title and onto the meta line, where
            # the V3 render puts it. It used to be appended as "→ S01E02" so
            # middle-elision would preserve it, which worked but spent title
            # width on it; on its own line it is always fully visible and the
            # title gets the whole row. The identifying fact leads (the episode
            # you were on, or the year that tells two same-named films apart)
            # and the time closes the line, which is how the render reads:
            # "S18E01 · 2 hours ago", "1984 · yesterday", "3 days ago".
            # History spends its ONE chip on what tells its rows apart — the
            # episode you were on, or the year that separates two same-named
            # films — and its tail on WHEN, because this is a list ordered by
            # exactly that. The language chip other sections show would say the
            # same thing on every row of a personal history.
            marker = dto.episode_code or dto.detected_year
            row = build_chip_row(
                title=title,
                icon_role=media_icon_role(dto.media_type),
                chips=((CHIP_YEAR, marker),),
                tail=humanize_ago_terse(dto.last_played),
                meta=sidebar_meta_line(marker, humanize_ago(dto.last_played)),
                density=self._row_density(),
                trailing_button=trailing_button,
            )
            # Width 0 → the item spans the viewport (no sideways scroll); the row's own
            # height governs the row height.
            item.setSizeHint(QSize(0, row.sizeHint().height()))
            self.history_list.setItemWidget(item, row)

    def _after_rows_removed(self, list_widget) -> None:
        """In-place removal upkeep. History renders no group headers, so this is
        only the section's own empty state (rows key on a plain UserRole id)."""
        if list_widget.count() == 0:
            self.set_empty(True)

    def _build_play_next_button(self, dto) -> QPushButton:
        """Build the row's "Play Next Episode" button (Wave 5).

        Only called for rows where ``dto.has_next`` is True (a series with a
        resolved smart-ladder resume target — see
        ``EpisodeRepository.get_resume_dto``). Emits :attr:`playNextClicked` with
        the resume target's episode id; MainWindow wires that straight into the
        existing :meth:`~metatv.gui.main_window_series.play_episode_by_id`
        chokepoint, so this row never grows its own play path.
        """
        next_btn = QPushButton()
        next_btn.setFixedSize(26, 18)
        next_btn.setToolTip(f"Play next episode: {dto.next_episode_code}")
        next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _theme.style(next_btn, "HISTORY_PLAY_NEXT_BUTTON")

        # The skip-next transport glyph, not ">>": that is fast-forward, and it
        # means "speed up" rather than "skip ahead". Re-rendered on every palette
        # switch — an already-rasterised pixmap cannot recolour itself.
        def _paint_glyph() -> str:
            next_btn.setIcon(
                _icon_utils.resolve_icon(
                    _icons.vector_key("next_episode"), _theme.COLOR_TEXT
                )
            )
            next_btn.setIconSize(QSize(14, 14))
            return _theme.HISTORY_PLAY_NEXT_BUTTON

        _theme.style_fn(next_btn, _paint_glyph)
        episode_id = dto.next_episode_id
        next_btn.clicked.connect(lambda: self.playNextClicked.emit(episode_id))
        return next_btn

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
