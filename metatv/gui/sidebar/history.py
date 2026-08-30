"""HistorySection."""

from PyQt6.QtWidgets import QPushButton, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from metatv.core.repositories import RepositoryFactory
from metatv.core.history_buckets import BUCKETS, bucket_for
from metatv.gui.chip_row import (
    CHIP_LANG, CHIP_QUALITY, CHIP_YEAR, build_chip_row, media_icon_role,
    sidebar_meta_line,
)
from metatv.gui.relative_time import humanize_ago
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import (
    GroupHeading, SectionAction, CollapsibleSection, make_seamless,
)
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


#: How many history entries to load. A bound on MEMORY, not a product decision
#: about how much history is worth keeping: 30 was arbitrary from when a section
#: could only ever show a handful of rows, and once scrolling could reveal more
#: it became the ceiling a viewer hits rather than a height anyone chose.
HISTORY_ROW_LIMIT = 300


#: The episode this row names, kept off ``UserRole`` — that holds the channel
#: id and a dozen handlers read it back.
_ROLE_EPISODE_ID = Qt.ItemDataRole.UserRole + 7

#: Marks a list item as a time-group heading rather than a channel row. Read by
#: click handling and by in-place removal, both of which must skip headings —
#: ``UserRole`` alone is not enough, because ``itemAt()`` still returns a
#: heading under the cursor and it would fall through to the row branch with a
#: null channel id.
_ROLE_BUCKET = Qt.ItemDataRole.UserRole + 8


class HistorySection(BackgroundRefreshMixin, CollapsibleSection):
    """Playback history section"""
    def budgeted_list(self):
        """The rows this section fits to its height (see
        ``CollapsibleSection.apply_row_budget``)."""
        return self.__dict__.get("history_list")

    def item_count(self) -> int | None:
        """Rows currently rendered — inventory, shown only when
        :meth:`news` is quiet.

        Read off the list itself rather than tracked separately, so the header
        cannot claim a number the rows disagree with — counted through the one
        shared ``count_content_rows``, which counts SELECTABLE rows so group
        headings, empty-state placeholders and the ``+N more`` tail are all
        excluded as the chrome they are.
        """
        lst = self.__dict__.get("history_list")
        if lst is None:
            return None
        return self.count_content_rows(lst)


    MIN_ROWS: int = 4

    EXPLORE_KEY = "history"

    # channel_id, episode_id — the episode this row NAMES, "" when it names
    # none. Two arguments rather than a second signal: a double-click is one
    # action with one handler, and splitting it by row kind is how a surface
    # grows a parallel play path.
    historyItemClicked = pyqtSignal(str, str)
    itemSelected       = pyqtSignal(str)   # channel_id (single-click)
    clearHistoryClicked = pyqtSignal()
    #: Age-scoped clear; carries the day threshold.
    clearOldHistoryClicked = pyqtSignal(int)
    #: One time group's clear; carries the bucket key ("yesterday", "older", …).
    #: The per-group counterpart to ``clearHistoryClicked`` — the ⋯ menu keeps
    #: "Clear all history", so a heading only ever forgets its own group.
    clearHistoryGroupClicked = pyqtSignal(str)
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
        """Main-thread slot: populate history_list from DTOs, grouped by when.

        The rows carry no timestamp of their own any more; the GROUP does. This
        is a list ordered by exactly one thing — when you watched something —
        and every row spent a slot repeating the fact the order already told
        you, while two rows for the same film at different qualities looked
        identical because the chip that tells them apart had nowhere to go.
        Owner: *"rather than having the time on the same line as the history
        entries, why not just have subdivisions … does it really matter when
        someone watched something? it's already in chronological order"*, and
        of the duplicate rows: *"you play a 4k and the user chooses a lower
        quality but then when they go back to resume there are just two with
        the same title and no indication of what the difference is."*

        The freed slot goes to quality, beside the title — where V3 settled it
        belongs (ledger F10) — with language after the year in the right rail.
        """
        self.set_empty(len(dtos) == 0)
        if not dtos:
            return

        # One pass, in the order the DTOs already arrive (newest first), so the
        # groups come out newest-first too without a second sort.
        grouped: dict[str, list] = {}
        for dto in dtos:
            grouped.setdefault(bucket_for(dto.last_played), []).append(dto)

        for bucket in BUCKETS:
            rows = grouped.get(bucket.key)
            if not rows:
                continue          # an empty group draws no heading
            self._add_group_heading(bucket, len(rows))
            for dto in rows:
                self._add_history_row(dto)

    def _add_group_heading(self, bucket, count: int) -> None:
        """Insert one time-group heading, with its own "forget these" control."""
        item = QListWidgetItem(self.history_list)
        item.setData(_ROLE_BUCKET, bucket.key)
        # No UserRole: a heading is not a channel, and every click handler reads
        # UserRole back as a channel id.
        item.setFlags(Qt.ItemFlag.NoItemFlags)

        forget = QPushButton()
        forget.setFixedSize(20, 20)
        forget.setToolTip(f"Forget everything under {bucket.label}")
        forget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # A VECTOR glyph, not the delete_icon emoji: an emoji set as a button's
        # TEXT is drawn at the font size and clips inside a 20x20 button (ledger
        # F13). Repainted through style_fn so it recolours on a palette switch —
        # an already-rasterised pixmap cannot.
        def _paint_glyph() -> str:
            forget.setIcon(
                _icon_utils.resolve_icon(
                    _icons.vector_key("delete"), _theme.COLOR_MUTED_2
                )
            )
            forget.setIconSize(QSize(13, 13))
            return _theme.HISTORY_GROUP_FORGET_BUTTON

        _theme.style_fn(forget, _paint_glyph)
        forget.clicked.connect(
            lambda _checked=False, key=bucket.key:
            self.clearHistoryGroupClicked.emit(key)
        )

        heading = GroupHeading(
            bucket.label, count,
            tooltip=f"{count} played — {bucket.label.lower()}",
            trailing_button=forget,
        )
        item.setSizeHint(QSize(0, heading.sizeHint().height()))
        self.history_list.setItemWidget(item, heading)

    def _add_history_row(self, dto) -> None:
        """Insert one channel row."""
        item = QListWidgetItem(self.history_list)
        item.setData(Qt.ItemDataRole.UserRole, dto.id)
        item.setData(_ROLE_EPISODE_ID, dto.episode_id or "")
        title = dto.detected_title or dto.name
        trailing_button = self._build_play_next_button(dto) if dto.has_next else None
        # The episode code or the year still leads the meta line — it is the
        # identifying fact — but the time no longer closes it, because the
        # heading above the row now says when.
        marker = dto.episode_code or dto.detected_year
        row = build_chip_row(
            title=title,
            icon_role=media_icon_role(dto.media_type),
            # Quality travels WITH the title (V3, ledger F10): it is what tells
            # two rows for the same film apart, so it has to sit where the eye
            # compares them rather than in the right rail.
            title_chips=((CHIP_QUALITY, dto.detected_quality),),
            chips=((CHIP_YEAR, marker), (CHIP_LANG, dto.detected_prefix)),
            meta=sidebar_meta_line(marker, humanize_ago(dto.last_played)),
            density=self._row_density(),
            trailing_button=trailing_button,
        )
        # Width 0 → the item spans the viewport (no sideways scroll); the row's own
        # height governs the row height.
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self.history_list.setItemWidget(item, row)

    def _after_rows_removed(self, list_widget) -> None:
        """In-place removal upkeep: drop headings whose group just emptied.

        History DOES render group headings now, so removing the last row under
        one leaves a heading standing over nothing — with a count of N and a
        "forget these" button that would forget an empty set. This walks
        backwards (so indices stay valid as items are taken) and removes any
        heading not followed by at least one row.
        """
        for index in range(list_widget.count() - 1, -1, -1):
            item = list_widget.item(index)
            if item.data(_ROLE_BUCKET) is None:
                continue
            nxt = list_widget.item(index + 1)
            # A heading is orphaned when the next item is another heading, or
            # when it is the last item in the list.
            if nxt is None or nxt.data(_ROLE_BUCKET) is not None:
                list_widget.takeItem(index)

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
        """Double-click: play what this row is ABOUT.

        A series row names one episode — the one you last watched, which is the
        code on its meta line. Sending only the channel id made the host
        re-derive a target from the series, and for a finished episode with
        nothing after it that resolved to no target at all, so a double-click
        opened the series browser instead of playing. Owner: "double clicking a
        watched episode in history doesn't play the episode (it should play on
        double click) it instead opens the browse the series."
        """
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.historyItemClicked.emit(channel_id,
                                         item.data(_ROLE_EPISODE_ID) or "")

    def on_history_item_selected(self, current, previous):
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)
