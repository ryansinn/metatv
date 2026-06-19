"""EPG View — watchlist-first electronic programme guide.

Three tabs:
  Watchlist  — Your tracked shows + recommendations
  On Now     — What's airing right now across all matched channels
  Browse     — Time-sorted schedule with date/time/search filtering
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from PyQt6.QtCore import Qt, QByteArray, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.core.channel_name_utils import parse_channel_name, REGION_FULL_NAMES
from metatv.core.database import ChannelDB, EpgProgramDB
from metatv.core.repositories.dtos import LiveEventDTO
from metatv.gui.badge_utils import make_audio_chip, make_quality_chip, make_region_chip, make_year_chip
from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu
from metatv.gui.content_view import ContentView
from metatv.gui.details_versions import resolve_category_name
from metatv.gui import theme as _theme
from metatv.gui.epg_events_mixin import (
    _EpgEventsMixin,
    LIVE_EVENT_WINDOW,
    _classify_event,
    group_events_timeline,
    group_events_by_network,
)

from metatv.core.epg_utils import (
    now_utc as _now_utc,
    fmt_time as _format_time,
    fmt_duration as _duration_str,
    minutes_away as _minutes_away,
    remaining_str as _remaining_str,
    is_local_today as _is_local_today,
    local_weekday as _local_weekday,
    to_local as _to_local,
)
from metatv.gui import icons as _icons

# Re-export shared EPG widget primitives (moved to epg_widgets.py).
# Kept here for backwards compatibility — existing code and tests that
# import these names from metatv.gui.epg_view continue to resolve fine.
from metatv.gui.epg_widgets import (
    _SORT_ROLE,
    _PROGRESS_ROLE,
    _REMAIN_ROLE,
    _ProgressBarDelegate,
    _EpgTreeItem,
    _progress_bar,
    _DismissedDialog,
    _AssignCategoryDialog,
    _parse_iso,
)
from metatv.gui.epg_browse_mixin import _EpgBrowseMixin


class EpgView(_EpgBrowseMixin, _EpgEventsMixin, ContentView):
    """Watchlist-first EPG view with On Now and Browse tabs."""

    play_channel_requested = pyqtSignal(object)  # ChannelDB
    watchlist_changed = pyqtSignal()             # patterns or channels modified

    # Internal thread-safe signals
    _data_loaded = pyqtSignal(object)  # payload dict keyed by tab

    def __init__(self, config, db, epg_manager, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        self.db = db
        self.epg_manager = epg_manager
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="EpgView")
        self._provider_ids: list[str] = []
        self._channel_name_map: dict[str, str] = {}    # channel_db_id → name
        self._channel_quality_map: dict[str, str] = {}  # channel_db_id → quality (e.g. "hd")
        self._channel_prefix_map: dict[str, str] = {}   # channel_db_id → detected_prefix
        self._channel_title_map: dict[str, str] = {}    # channel_db_id → detected_title
        self._channel_region_map: dict[str, str] = {}   # channel_db_id → detected_region
        self._channel_year_map: dict[str, str] = {}     # channel_db_id → detected_year

        # Cached data for tabs
        self._on_now_programs: list[EpgProgramDB] = []
        self._browse_programs:  list[EpgProgramDB] = []
        self._watchlist_data:   dict[str, list[EpgProgramDB]] = {}
        self._live_data:        dict[str, list[EpgProgramDB]] = {}
        self._recommendations:  list[tuple[str, str, int]] = []
        self._events_dto_cache: list = []   # list[LiveEventDTO] — cached for timer re-group

        self._setup_ui()
        self._data_loaded.connect(self._on_data_loaded)

        # Refresh On Now cards every 60 seconds while visible; also re-groups Events.
        self._live_refresh_timer = QTimer(self)
        self._live_refresh_timer.setInterval(60_000)
        self._live_refresh_timer.timeout.connect(self._on_live_timer_tick)

        # Connect EPG manager signals
        self.epg_manager.refresh_finished.connect(self._on_epg_refreshed)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ─────────────────────────────────────────────────────
        header_widget = QWidget()
        header_widget.setObjectName("epgHeader")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(8)

        # Tab bar
        self.tab_bar = QTabBar()
        self.tab_bar.addTab(f"{self.config.watchlist_icon} Watchlist")      # 0
        self.tab_bar.addTab(f"{self.config.series_icon} My Channels")      # 1
        self.tab_bar.addTab(f"{self.config.discover_icon} Discover")       # 2
        self.tab_bar.addTab(f"{self.config.live_indicator_icon} On Now")   # 3
        self.tab_bar.addTab(f"{self.config.calendar_icon} Browse")         # 4
        self.tab_bar.addTab(f"{self.config.hide_icon} Manage")             # 5
        self.tab_bar.addTab(f"{_icons.events_icon} Events")                # 6
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        header_layout.addWidget(self.tab_bar)
        header_layout.addStretch()

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(_theme.CHANNEL_NAME_DIM)
        header_layout.addWidget(self.status_label)

        # Refresh button
        self.refresh_btn = QPushButton(f"{self.config.refresh_icon} Refresh")
        self.refresh_btn.setToolTip("Refresh EPG data from all providers")
        self.refresh_btn.clicked.connect(self._on_force_refresh)
        header_layout.addWidget(self.refresh_btn)

        root.addWidget(header_widget)

        # Thin separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"border: none; border-top: 1px solid {_theme.COLOR_LINE};")
        root.addWidget(sep)

        # ── Stale-EPG notice ────────────────────────────────────────────
        # Surfaces sources whose provider feed serves out-of-date guide data, so an
        # empty On Now reads as "provider's guide is stale" rather than "EPG is broken".
        self._stale_epg_notice = QLabel("")
        self._stale_epg_notice.setWordWrap(True)
        self._stale_epg_notice.setStyleSheet(_theme.EPG_STALE_NOTICE)
        self._stale_epg_notice.setContentsMargins(12, 6, 12, 6)
        self._stale_epg_notice.hide()
        root.addWidget(self._stale_epg_notice)

        # ── Stacked content area ────────────────────────────────────────
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self._build_watchlist_tab()    # stack 0
        self._build_channels_tab()    # stack 1
        self._build_discover_tab()    # stack 2
        self._build_on_now_tab()      # stack 3
        self._build_browse_tab()      # stack 4
        self._build_hidden_tab()      # stack 5
        self._build_events_tab()      # stack 6

    # ── Tab 0: Watchlist ───────────────────────────────────────────────

    def _build_watchlist_tab(self) -> None:
        from metatv.gui.flow_layout import FlowLayout
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Add-keyword row
        hint = QLabel("Track a show or keyword — press Enter or click Track to add:")
        hint.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(hint)

        add_row = QHBoxLayout()
        self.add_pattern_input = QLineEdit()
        self.add_pattern_input.setPlaceholderText("e.g.  NHL  ·  Jeopardy  ·  MasterChef Canada")
        self.add_pattern_input.setToolTip("Pattern matching is not case-sensitive")
        self.add_pattern_input.returnPressed.connect(self._on_add_pattern)
        add_row.addWidget(self.add_pattern_input, 1)
        self.add_btn = QPushButton("Track")
        self.add_btn.setFixedWidth(60)
        self.add_btn.clicked.connect(self._on_add_pattern)
        add_row.addWidget(self.add_btn)
        layout.addLayout(add_row)

        ci_note = QLabel("Patterns are not case-sensitive")
        ci_note.setStyleSheet(f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_SM};")
        layout.addWidget(ci_note)

        # Pattern cards — responsive FlowLayout
        self.watchlist_scroll = QScrollArea()
        self.watchlist_scroll.setWidgetResizable(True)
        self.watchlist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.watchlist_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.watchlist_scroll.setWidget(QWidget())  # placeholder; fully rebuilt each render
        layout.addWidget(self.watchlist_scroll, 1)

        self.stack.addWidget(page)

    def _build_channels_tab(self) -> None:
        from metatv.gui.flow_layout import FlowLayout
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Pinned channels — right-click any channel in On Now to add one."))
        hdr.addStretch()
        layout.addLayout(hdr)

        self.channels_scroll = QScrollArea()
        self.channels_scroll.setWidgetResizable(True)
        self.channels_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.channels_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.channels_content = QWidget()
        self.channels_layout = FlowLayout(self.channels_content, spacing=8)
        self.channels_scroll.setWidget(self.channels_content)
        layout.addWidget(self.channels_scroll, 1)

        self.ch_empty_label = QLabel(
            "No channels pinned yet.\nRight-click any channel in On Now → Watch this channel."
        )
        self.ch_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ch_empty_label.setStyleSheet(_theme.EMPTY_LABEL)

        self.stack.addWidget(page)

    def _build_discover_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        rec_header = QHBoxLayout()
        rec_title = QLabel("Channels with content matching your watchlist patterns:")
        rec_title.setStyleSheet(_theme.CHANNEL_NAME_DIM)
        rec_header.addWidget(rec_title)
        rec_header.addStretch()
        self.manage_dismissed_btn = QPushButton("Manage dismissed")
        self.manage_dismissed_btn.setStyleSheet(
            f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD}; border: none; background: transparent;"
        )
        self.manage_dismissed_btn.clicked.connect(self._manage_dismissed)
        rec_header.addWidget(self.manage_dismissed_btn)
        layout.addLayout(rec_header)

        self.rec_scroll = QScrollArea()
        self.rec_scroll.setWidgetResizable(True)
        self.rec_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rec_content = QWidget()
        self.rec_layout = QVBoxLayout(self.rec_content)
        self.rec_layout.setSpacing(4)
        self.rec_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rec_scroll.setWidget(self.rec_content)
        layout.addWidget(self.rec_scroll, 1)

        self.rec_empty_label = QLabel(
            "Add watchlist patterns to get channel recommendations."
        )
        self.rec_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rec_empty_label.setStyleSheet(_theme.EMPTY_LABEL)

        self.stack.addWidget(page)

    # ── Tab 1: On Now ──────────────────────────────────────────────────

    def _build_on_now_tab(self) -> None:
        from metatv.gui.filter_bar import FilterDropdown

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Filter row: search | region dropdown | → | Hide Hidden
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        self.on_now_search = QLineEdit()
        self.on_now_search.setPlaceholderText("Search On Now…")
        self.on_now_search.setFixedWidth(180)
        self.on_now_search.textChanged.connect(self._apply_on_now_filters)
        filter_row.addWidget(self.on_now_search)

        on_now_clear = QPushButton(self.config.close_icon)
        on_now_clear.setFixedWidth(24)
        on_now_clear.setToolTip("Clear search")
        on_now_clear.setStyleSheet(_theme.CLEAR_BTN)
        on_now_clear.clicked.connect(self.on_now_search.clear)
        filter_row.addWidget(on_now_clear)

        self.on_now_prefix_dropdown = FilterDropdown("Category", {}, all_selected=True)
        self.on_now_prefix_dropdown.filter_changed.connect(self._apply_on_now_filters)
        filter_row.addWidget(self.on_now_prefix_dropdown)

        filter_row.addStretch()

        self.filler_check_btn = QPushButton("Show All")
        self.filler_check_btn.setCheckable(True)
        self.filler_check_btn.setChecked(True)
        self.filler_check_btn.setFixedWidth(110)
        self.filler_check_btn.clicked.connect(self._on_filler_toggled)
        filter_row.addWidget(self.filler_check_btn)

        layout.addLayout(filter_row)

        # Programme tree: Category | Channel | Quality | Show | Progress | [hide]
        # Logical columns: 0=Category(""), 1=Channel, 2=Quality, 3=Show, 4=Progress, 5=Hide
        self.on_now_list = QTreeWidget()
        self.on_now_list.setAlternatingRowColors(True)
        self.on_now_list.setRootIsDecorated(False)
        self.on_now_list.setUniformRowHeights(True)
        self.on_now_list.setSortingEnabled(True)
        self.on_now_list.setColumnCount(6)
        self.on_now_list.setHeaderLabels(["", "Channel", "Quality", "Show", "Progress", "Hide"])
        hdr = self.on_now_list.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        hdr.setStretchLastSection(False)
        hdr.setSectionsMovable(True)
        hdr.resizeSection(1, 220)
        self.on_now_list.setColumnWidth(2, 44)
        self.on_now_list.setColumnWidth(4, 64)
        self.on_now_list.setColumnWidth(5, 22)
        self.on_now_list.headerItem().setToolTip(0, "Category / prefix extracted from channel name")
        self.on_now_list.headerItem().setToolTip(2, "Stream quality (4K / FHD / HD / etc.)")
        self.on_now_list.headerItem().setToolTip(4, "Progress through current show (hover for time remaining)")
        self._progress_delegate = _ProgressBarDelegate(self.on_now_list)
        self.on_now_list.setItemDelegateForColumn(4, self._progress_delegate)
        from PyQt6.QtWidgets import QAbstractItemView
        self.on_now_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.on_now_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.on_now_list.customContextMenuRequested.connect(self._on_now_context_menu)
        self.on_now_list.itemDoubleClicked.connect(self._on_now_double_click)
        self.on_now_list.itemClicked.connect(self._on_now_item_clicked)
        self.on_now_list.currentItemChanged.connect(self._on_now_selection_changed)
        # Restore persisted header state (column order + widths) or apply default visual order.
        # Default visual order: [Category(0), Progress(4), Show(3), Channel(1), Hide(5), Quality(2)]
        _saved_header = self.config.epg_filter_state.get("on_now_header_state")
        if _saved_header:
            try:
                hdr.restoreState(QByteArray.fromBase64(_saved_header.encode("ascii")))
                hdr.setStretchLastSection(False)  # re-assert after restoreState
            except Exception:
                _saved_header = None  # fall through to default order
        if not _saved_header:
            # Apply default visual order: logical indices [0, 4, 3, 1, 5, 2]
            # moveSection(from_visual, to_visual) — apply in order to avoid conflicts
            hdr.moveSection(hdr.visualIndex(4), 1)  # Progress → visual 1
            hdr.moveSection(hdr.visualIndex(3), 2)  # Show    → visual 2
            hdr.moveSection(hdr.visualIndex(1), 3)  # Channel → visual 3
            hdr.moveSection(hdr.visualIndex(5), 4)  # Hide    → visual 4
            # Quality ends up at visual 5 (last) naturally
        # Restore persisted sort; save whenever user clicks a header
        _col = self.config.epg_filter_state.get("on_now_sort_col", 0)
        _ord = Qt.SortOrder(self.config.epg_filter_state.get("on_now_sort_order", 0))
        self.on_now_list.sortByColumn(_col, _ord)
        hdr.sortIndicatorChanged.connect(
            lambda col, order: self._save_epg_sort("on_now", col, order)
        )
        hdr.sectionMoved.connect(self._save_on_now_header_state)
        layout.addWidget(self.on_now_list)

        self.on_now_stats = QLabel("")
        self.on_now_stats.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(self.on_now_stats)

        self.stack.addWidget(page)

    # ── Tab 3: Hidden ──────────────────────────────────────────────────

    def _build_hidden_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._hidden_content = QWidget()
        self._hidden_layout = QVBoxLayout(self._hidden_content)
        self._hidden_layout.setSpacing(4)
        self._hidden_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._hidden_content)
        layout.addWidget(scroll)

        self.stack.addWidget(page)

    def _render_hidden(self) -> None:
        while self._hidden_layout.count():
            item = self._hidden_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── Section 1: User-hidden show titles ──────────────────────────
        sec1_lbl = QLabel("HIDDEN SHOWS")
        sec1_lbl.setStyleSheet(_theme.SECTION_HDR_LG)
        self._hidden_layout.addWidget(sec1_lbl)

        hidden_titles = list(self.config.epg_hidden_titles or [])
        if hidden_titles:
            for title in hidden_titles:
                self._hidden_layout.addWidget(self._make_hidden_row(
                    title, "exact match · global",
                    lambda _, t=title: self._remove_hidden_title(t),
                ))
        else:
            lbl = QLabel("No shows hidden yet — click 🚫 on any On Now row to hide a show.")
            lbl.setStyleSheet(_theme.SECTION_ITEM)
            lbl.setWordWrap(True)
            self._hidden_layout.addWidget(lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(_theme.SEPARATOR_H)
        self._hidden_layout.addWidget(sep)

        # ── Section 2: Filler patterns ──────────────────────────────────
        sec2_lbl = QLabel("FILLER PATTERNS")
        sec2_lbl.setStyleSheet(_theme.SECTION_HDR_LG)
        self._hidden_layout.addWidget(sec2_lbl)

        hint = QLabel("Substring match — hides any show whose title contains these words.")
        hint.setStyleSheet(_theme.SECTION_HINT)
        hint.setWordWrap(True)
        self._hidden_layout.addWidget(hint)

        filler_patterns = list(self.config.epg_filler_patterns or [])
        for pattern in filler_patterns:
            self._hidden_layout.addWidget(self._make_hidden_row(
                pattern, "substring match",
                lambda _, p=pattern: self._remove_filler_pattern(p),
            ))

        # Add-pattern row
        add_row = QHBoxLayout()
        add_input = QLineEdit()
        add_input.setPlaceholderText("Add filler pattern…")
        add_btn = QPushButton("Add")
        add_btn.setFixedWidth(50)
        add_btn.clicked.connect(lambda: self._add_filler_pattern(add_input.text().strip()))
        add_input.returnPressed.connect(lambda: self._add_filler_pattern(add_input.text().strip()))
        add_row.addWidget(add_input, 1)
        add_row.addWidget(add_btn)
        self._hidden_layout.addLayout(add_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(_theme.SEPARATOR_H)
        self._hidden_layout.addWidget(sep2)

        # ── Section 3: Hidden channels ──────────────────────────────────
        sec3_lbl = QLabel("HIDDEN CHANNELS")
        sec3_lbl.setStyleSheet(_theme.SECTION_HDR_LG)
        self._hidden_layout.addWidget(sec3_lbl)

        hidden_channels = list(self.config.epg_hidden_channels or [])
        if hidden_channels:
            hint3 = QLabel("Entire channel hidden from On Now.")
            hint3.setStyleSheet(_theme.SECTION_HINT)
            self._hidden_layout.addWidget(hint3)
            for ch_id in hidden_channels:
                ch_name = self._get_channel_name_from_db(ch_id)
                self._hidden_layout.addWidget(self._make_hidden_row(
                    ch_name, "channel",
                    lambda _, cid=ch_id: self._remove_hidden_channel(cid),
                ))
        else:
            lbl3 = QLabel("No channels hidden yet — use the 🚫 button on any On Now row.")
            lbl3.setStyleSheet(_theme.SECTION_ITEM)
            lbl3.setWordWrap(True)
            self._hidden_layout.addWidget(lbl3)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(_theme.SEPARATOR_H)
        self._hidden_layout.addWidget(sep3)

        # ── Section 4: Hidden categories ────────────────────────────────
        sec4_lbl = QLabel("HIDDEN CATEGORIES")
        sec4_lbl.setStyleSheet(_theme.SECTION_HDR_LG)
        self._hidden_layout.addWidget(sec4_lbl)

        hidden_prefixes = list(self.config.epg_hidden_prefixes or [])
        if hidden_prefixes:
            hint4 = QLabel("All channels with this prefix are hidden from On Now.")
            hint4.setStyleSheet(_theme.SECTION_HINT)
            self._hidden_layout.addWidget(hint4)
            for prefix in hidden_prefixes:
                full = resolve_category_name(prefix, self.config)
                label = f"{prefix}  —  {full}" if full else prefix
                self._hidden_layout.addWidget(self._make_hidden_row(
                    label, "category",
                    lambda _, p=prefix: self._remove_hidden_category(p),
                ))
        else:
            lbl4 = QLabel("No categories hidden yet — use the ⊘ button on any On Now row.")
            lbl4.setStyleSheet(_theme.SECTION_ITEM)
            lbl4.setWordWrap(True)
            self._hidden_layout.addWidget(lbl4)

        sep5 = QFrame()
        sep5.setFrameShape(QFrame.Shape.HLine)
        sep5.setStyleSheet(_theme.SEPARATOR_H)
        self._hidden_layout.addWidget(sep5)

        # ── Section 5: Category overrides ──────────────────────────────
        sec5_lbl = QLabel("CATEGORY OVERRIDES")
        sec5_lbl.setStyleSheet(_theme.SECTION_HDR_LG)
        self._hidden_layout.addWidget(sec5_lbl)

        overrides = dict(self.config.epg_category_overrides or {})
        if overrides:
            hint5 = QLabel("Manually assigned categories — applied before auto-detection.")
            hint5.setStyleSheet(_theme.SECTION_HINT)
            self._hidden_layout.addWidget(hint5)
            for ch_id, cat_code in overrides.items():
                ch_name = self._get_channel_name_from_db(ch_id)
                full = resolve_category_name(cat_code, self.config)
                cat_label = f"{cat_code}  —  {full}" if full else cat_code
                self._hidden_layout.addWidget(self._make_hidden_row(
                    ch_name, cat_label,
                    lambda _, cid=ch_id: self._remove_category_overrides([cid]),
                ))
        else:
            lbl5 = QLabel(
                "No overrides yet — right-click On Now rows to assign a category."
            )
            lbl5.setStyleSheet(_theme.SECTION_ITEM)
            lbl5.setWordWrap(True)
            self._hidden_layout.addWidget(lbl5)

    def _make_hidden_row(self, label: str, detail: str, on_remove) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(8)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_TEXT_2};")
        h.addWidget(lbl, 1)
        det = QLabel(detail)
        det.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_FAINT};")
        h.addWidget(det)
        rm_btn = QPushButton(self.config.close_icon)
        rm_btn.setFixedWidth(24)
        rm_btn.setStyleSheet(f"border: none; color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_2XL}; font-weight: bold;")
        rm_btn.setToolTip("Remove")
        rm_btn.clicked.connect(on_remove)
        h.addWidget(rm_btn)
        return row

    def _remove_hidden_title(self, title: str) -> None:
        hidden = list(self.config.epg_hidden_titles or [])
        if title in hidden:
            hidden.remove(title)
            self.config.epg_hidden_titles = hidden
            self.config.save()
        self._render_hidden()
        self._update_filler_btn_label()

    def _remove_filler_pattern(self, pattern: str) -> None:
        patterns = list(self.config.epg_filler_patterns or [])
        if pattern in patterns:
            patterns.remove(pattern)
            self.config.epg_filler_patterns = patterns
            self.config.save()
        self._render_hidden()
        self._update_filler_btn_label()

    def _add_filler_pattern(self, pattern: str) -> None:
        if not pattern:
            return
        patterns = list(self.config.epg_filler_patterns or [])
        if pattern not in patterns:
            patterns.append(pattern)
            self.config.epg_filler_patterns = patterns
            self.config.save()
        self._render_hidden()
        self._update_filler_btn_label()

    # ------------------------------------------------------------------
    # ContentView interface
    # ------------------------------------------------------------------

    def get_view_name(self) -> str:
        return "EPG"

    def get_selected_channel(self) -> Optional[ChannelDB]:
        return None  # EPG doesn't track a single selected channel

    def _refresh_stale_epg_notice(self) -> None:
        """Show/hide the banner listing active sources whose EPG guide data is stale."""
        from metatv.core.repositories import RepositoryFactory
        session = self.db.get_session()
        try:
            stale = RepositoryFactory(session).providers.get_stale_epg_providers()
        finally:
            session.close()
        if not stale:
            self._stale_epg_notice.hide()
            return
        parts = []
        for _id, name, data_end in stale:
            try:
                day = _to_local(data_end).strftime("%d %b %Y").lstrip("0")
            except Exception:
                day = str(data_end)
            parts.append(f"{name} (guide ends {day})")
        self._stale_epg_notice.setText(
            f"{_icons.notification_warning_icon}  Stale guide data — these sources' "
            f"providers aren't supplying current EPG, so they won't show in On Now: "
            + "; ".join(parts)
        )
        self._stale_epg_notice.show()

    def on_activate(self) -> None:
        """Called when the EPG chip is clicked and view becomes visible."""
        self._load_provider_ids()
        self._refresh_stale_epg_notice()
        self._update_status_label()

        # Default to On Now (tab 3); stay on a watchlist tab only if patterns already exist
        if self.tab_bar.currentIndex() in (0, 1, 2) and not self.config.epg_watchlist_patterns:
            self.tab_bar.blockSignals(True)
            self.tab_bar.setCurrentIndex(3)
            self.tab_bar.blockSignals(False)
            self.stack.setCurrentIndex(3)

        self._reload_all()
        self.epg_manager.refresh_all_if_needed()
        # Relink is cheap (DB-only) and fixes partial-match gaps without a network
        # fetch — run it every activation so newly-loaded channels are linked before
        # the user sees On Now / Watchlist.  refresh_finished is emitted per changed
        # provider so _on_epg_refreshed calls _reload_all() automatically.
        self.epg_manager.relink_all()
        self._live_refresh_timer.start()

    def on_deactivate(self) -> None:
        self._live_refresh_timer.stop()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_provider_ids(self) -> None:
        from metatv.core.repositories import RepositoryFactory
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            self._provider_ids = repos.providers.get_epg_active_provider_ids()
        finally:
            session.close()

    def _reload_all(self) -> None:
        tab = self.tab_bar.currentIndex()
        if tab in (0, 1, 2):
            self._reload_watchlist()   # Watchlist / My Channels / Discover share one fetch
        elif tab == 3:
            self._reload_on_now()
        elif tab == 4:
            self._reload_browse()
        elif tab == 5:
            self._render_hidden()
        elif tab == 6:
            self._reload_events()

    def _on_live_timer_tick(self) -> None:
        """60-second timer: reload On Now data, and re-group Events from cache."""
        tab = self.tab_bar.currentIndex()
        if tab == 3:
            self._reload_on_now()
        elif tab == 6:
            # Re-group from cached DTOs — no DB round-trip needed; just recompute
            # "on now" boundary against the fresh now_utc().
            self._render_events(self._events_dto_cache)
        else:
            # If the user is on another tab, still refresh On Now in the background
            # so the data is ready when they switch back.
            self._reload_on_now()

    def _reload_watchlist(self) -> None:
        patterns = self.config.epg_watchlist_patterns
        provider_ids = self._filtered_provider_ids()
        self._executor.submit(self._fetch_watchlist, patterns, provider_ids)

    def _reload_on_now(self) -> None:
        provider_ids = self._filtered_provider_ids()
        hide_filler = self.filler_check_btn.isChecked()
        # Show loading state immediately so the list isn't blank during the 10–15 s query.
        if self.on_now_list.topLevelItemCount() == 0:
            from PyQt6.QtWidgets import QTreeWidgetItem
            placeholder = QTreeWidgetItem(["", "Loading channels on now…", "", "", "", ""])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            placeholder.setForeground(1, QColor(_theme.COLOR_MUTED))
            self.on_now_list.addTopLevelItem(placeholder)
        self.on_now_stats.setText("Loading…")
        self._executor.submit(self._fetch_on_now, provider_ids, hide_filler)

    def _filtered_provider_ids(self) -> list[str]:
        return self._provider_ids

    # ── Background workers ─────────────────────────────────────────────

    def _fetch_watchlist(self, patterns: list[str], provider_ids: list[str]) -> None:
        session = self.db.get_session()
        try:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            excluded_ch_provider_ids = set(repos.providers.get_hidden_provider_ids())
            repo = repos.epg
            watchlist_data = repo.get_upcoming_for_watchlist(
                patterns, hours_ahead=48,
                provider_ids=provider_ids,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )
            live_data = repo.get_live_for_watchlist(
                patterns,
                provider_ids=provider_ids,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )

            # Build dismissed set (expired entries are filtered out)
            now = _now_utc()
            dismissed = {
                cid for cid, ts_str in self.config.epg_dismissed_channels.items()
                if _parse_iso(ts_str) > now
            }

            recs = repo.get_recommendations(
                patterns=patterns,
                dismissed_ids=dismissed,
                provider_ids=provider_ids,
                limit=8,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )

            # Build channel name map
            name_map = self._build_name_map(session, watchlist_data, live_data)
            self._channel_name_map.update(name_map)

            # MY CHANNELS — current program for each pinned channel
            channel_ids = self.config.epg_watchlist_channels
            channel_now: dict[str, EpgProgramDB | None] = {}
            channel_names: dict[str, str] = {}
            for cid in channel_ids:
                channel_now[cid] = repo.get_now_for_channel(cid)
                ch = session.query(ChannelDB).filter_by(id=cid).first()
                channel_names[cid] = ch.name if ch else cid

            self._data_loaded.emit({
                "tab": "watchlist",
                "watchlist_data": watchlist_data,
                "live_data": live_data,
                "recommendations": recs,
                "dismissed": dismissed,
                "channel_now": channel_now,
                "channel_names": channel_names,
            })
        except Exception as e:
            logger.error(f"EpgView watchlist fetch error: {e}")
        finally:
            session.close()

    def _fetch_on_now(self, provider_ids: list[str], hide_filler: bool) -> None:
        if not provider_ids:
            logger.warning("EpgView on-now: no EPG provider IDs — is EPG loaded?")
            self._data_loaded.emit({"tab": "on_now", "programs": []})
            return
        session = self.db.get_session()
        try:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            excluded_ch_provider_ids = set(repos.providers.get_hidden_provider_ids())
            repo = repos.epg
            filler = self.config.epg_filler_patterns if hide_filler else []
            dismissed = self._dismissed_ids()
            programs = repo.get_current_programs(
                provider_ids=provider_ids,
                hide_filler=hide_filler,
                filler_patterns=filler,
                dismissed_channel_ids=dismissed,
                hidden_titles=list(self.config.epg_hidden_titles or []),
                hidden_channel_ids=list(self.config.epg_hidden_channels or []),
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )
            logger.debug(f"EpgView on-now: {len(programs)} programmes from providers {provider_ids}")
            # Build name + quality + prefix + title + region + year maps from stored DB fields
            name_map: dict[str, str] = {}
            quality_map: dict[str, str] = {}
            prefix_map: dict[str, str] = {}
            title_map: dict[str, str] = {}
            region_map: dict[str, str] = {}
            year_map: dict[str, str] = {}
            for p in programs:
                if p.channel_db_id and p.channel_db_id not in name_map:
                    ch = session.query(ChannelDB).filter_by(id=p.channel_db_id).first()
                    if ch:
                        name_map[p.channel_db_id] = ch.name
                        if ch.detected_quality:
                            quality_map[p.channel_db_id] = ch.detected_quality.upper()
                        prefix_map[p.channel_db_id] = ch.detected_prefix or ""
                        title_map[p.channel_db_id] = ch.detected_title or ch.name
                        region_map[p.channel_db_id] = ch.detected_region or ""
                        year_map[p.channel_db_id] = ch.detected_year or ""
            self._channel_name_map.update(name_map)
            self._channel_quality_map.update(quality_map)
            self._channel_prefix_map.update(prefix_map)
            self._channel_title_map.update(title_map)
            self._channel_region_map.update(region_map)
            self._channel_year_map.update(year_map)

            self._data_loaded.emit({"tab": "on_now", "programs": programs})
        except Exception as e:
            logger.error(f"EpgView on-now fetch error: {e}")
            self._data_loaded.emit({"tab": "on_now", "programs": []})
        finally:
            session.close()

    def _build_name_map(self, session, watchlist_data, live_data) -> dict[str, str]:
        """Build channel display maps from stored detected_* fields.

        Populates _channel_quality_map, _channel_prefix_map, _channel_title_map,
        _channel_region_map, and _channel_year_map as a side-effect.  Returns the
        raw name map for backwards compatibility with the caller.

        Reads stored detected_* fields written at ingestion time — no parse_channel_name
        call here (ingestion-only rule, CLAUDE.md).
        """
        name_map: dict[str, str] = {}
        quality_map: dict[str, str] = {}
        prefix_map: dict[str, str] = {}
        title_map: dict[str, str] = {}
        region_map: dict[str, str] = {}
        year_map: dict[str, str] = {}
        all_progs: list[EpgProgramDB] = []
        for progs in watchlist_data.values():
            all_progs.extend(progs)
        for progs in live_data.values():
            all_progs.extend(progs)
        for p in all_progs:
            if p.channel_db_id and p.channel_db_id not in name_map:
                ch = session.query(ChannelDB).filter_by(id=p.channel_db_id).first()
                if ch:
                    name_map[p.channel_db_id] = ch.name
                    if ch.detected_quality:
                        quality_map[p.channel_db_id] = ch.detected_quality.upper()
                    prefix_map[p.channel_db_id] = ch.detected_prefix or ""
                    title_map[p.channel_db_id] = ch.detected_title or ch.name
                    region_map[p.channel_db_id] = ch.detected_region or ""
                    year_map[p.channel_db_id] = ch.detected_year or ""
        self._channel_quality_map.update(quality_map)
        self._channel_prefix_map.update(prefix_map)
        self._channel_title_map.update(title_map)
        self._channel_region_map.update(region_map)
        self._channel_year_map.update(year_map)
        return name_map

    # ------------------------------------------------------------------
    # Main-thread render slots
    # ------------------------------------------------------------------

    def _on_data_loaded(self, payload: dict) -> None:
        tab = payload["tab"]
        if tab == "watchlist":
            self._render_watchlist(
                payload["watchlist_data"],
                payload["live_data"],
                payload["recommendations"],
                payload["dismissed"],
                payload.get("channel_now", {}),
                payload.get("channel_names", {}),
            )
        elif tab == "on_now":
            self._render_on_now(payload["programs"])
        elif tab == "browse":
            self._render_browse(payload["programs"], payload.get("placeholder", False))
        elif tab == "events":
            self._events_dto_cache = payload["dtos"]
            self._render_events(self._events_dto_cache)

    # ── Watchlist render ───────────────────────────────────────────────

    def _render_watchlist(self, watchlist_data: dict, live_data: dict,
                          recommendations: list, dismissed: set,
                          channel_now: dict | None = None,
                          channel_names: dict | None = None) -> None:
        from metatv.gui.flow_layout import FlowLayout

        old_wl = self.watchlist_scroll.takeWidget()
        if old_wl:
            old_wl.deleteLater()

        wl_content = QWidget()
        wl_outer = QVBoxLayout(wl_content)
        wl_outer.setContentsMargins(0, 4, 0, 8)
        wl_outer.setSpacing(0)

        patterns = self.config.epg_watchlist_patterns

        if not patterns:
            empty = QLabel("No watchlist items yet.\nAdd a show or keyword above to get started.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_XL}; padding: 20px;")
            wl_outer.addWidget(empty)
            wl_outer.addStretch()
        else:
            on_now: list[tuple] = []
            upcoming_only: list[tuple] = []
            off_air: list[str] = []

            for pattern in patterns:
                live_progs = live_data.get(pattern, [])
                upc = watchlist_data.get(pattern, [])
                if live_progs:
                    on_now.append((pattern, live_progs, upc))
                elif upc:
                    upcoming_only.append((pattern, upc))
                else:
                    off_air.append(pattern)

            def _section_hdr(text: str) -> QLabel:
                lbl = QLabel(text)
                lbl.setStyleSheet(_theme.SECTION_HDR)
                return lbl

            def _two_col_row(cards: list, h_estimates: list[int]) -> QWidget:
                """Greedy 2-column layout: always add each card to the shorter column.
                Preserves original order within each column."""
                col0_h, col0_cards = 0, []
                col1_h, col1_cards = 0, []
                for card, h in zip(cards, h_estimates):
                    if col0_h <= col1_h:
                        col0_cards.append(card)
                        col0_h += h
                    else:
                        col1_cards.append(card)
                        col1_h += h

                container = QWidget()
                h_layout = QHBoxLayout(container)
                h_layout.setContentsMargins(0, 0, 0, 0)
                h_layout.setSpacing(8)
                for col_cards in (col0_cards, col1_cards):
                    col_w = QWidget()
                    col_v = QVBoxLayout(col_w)
                    col_v.setContentsMargins(0, 0, 0, 0)
                    col_v.setSpacing(8)
                    for card in col_cards:
                        col_v.addWidget(card)
                    col_v.addStretch()
                    h_layout.addWidget(col_w, 1)
                return container

            if on_now:
                wl_outer.addWidget(_section_hdr(f"ON NOW  ·  {len(on_now)}"))
                cards = [self._make_watchlist_item(p, l, u[:3]) for p, l, u in on_now]
                h_ests = [max(len(l), 1) for p, l, u in on_now]
                wl_outer.addWidget(_two_col_row(cards, h_ests))

            if upcoming_only:
                wl_outer.addWidget(_section_hdr(f"UPCOMING  ·  {len(upcoming_only)}"))
                cards = [self._make_watchlist_item(p, [], u[:3]) for p, u in upcoming_only]
                h_ests = [max(len(u), 1) for p, u in upcoming_only]
                wl_outer.addWidget(_two_col_row(cards, h_ests))

            if off_air:
                wl_outer.addWidget(self._make_quiet_section(off_air))

            wl_outer.addStretch()

        self.watchlist_scroll.setWidget(wl_content)

        # MY CHANNELS
        while self.channels_layout.count():
            child = self.channels_layout.takeAt(0)
            w = child.widget()
            if w:
                if w is self.ch_empty_label:
                    w.setParent(None)
                else:
                    w.deleteLater()

        channel_ids = self.config.epg_watchlist_channels
        channel_now = channel_now or {}
        channel_names = channel_names or {}

        if not channel_ids:
            self.channels_layout.addWidget(self.ch_empty_label)
        else:
            for cid in channel_ids:
                prog = channel_now.get(cid)
                name = channel_names.get(cid, cid)
                self.channels_layout.addWidget(self._make_channel_item(cid, name, prog))

        # Recommendations
        while self.rec_layout.count():
            child = self.rec_layout.takeAt(0)
            w = child.widget()
            if w:
                if w is self.rec_empty_label:
                    w.setParent(None)
                else:
                    w.deleteLater()

        if not recommendations:
            self.rec_layout.addWidget(self.rec_empty_label)
        else:
            for channel_db_id, channel_name, count in recommendations:
                self.rec_layout.addWidget(
                    self._make_recommendation_item(channel_db_id, channel_name, count)
                )

    def _make_watchlist_item(self, pattern: str, live: list[EpgProgramDB],
                              upcoming: list[EpgProgramDB]) -> QWidget:
        from collections import defaultdict

        w = QWidget()
        w.setMinimumWidth(320)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.setStyleSheet(_theme.CARD_BG)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        # ── Header ──────────────────────────────────────────────────────── #
        is_live = bool(live)
        icon = self.config.live_indicator_icon if is_live else self.config.watchlist_icon

        # Group live programmes by show title (most channels = most popular first)
        title_groups: dict[str, list] = defaultdict(list)
        for prog in live:
            title_groups[prog.title].append(prog)
        title_groups = dict(sorted(title_groups.items(), key=lambda kv: -len(kv[1])))

        header = QHBoxLayout()
        pattern_lbl = QLabel(f"{icon}  {pattern}")
        pattern_lbl.setStyleSheet(_theme.LIST_TITLE)
        header.addWidget(pattern_lbl)
        header.addStretch()

        if is_live:
            n = len(live)
            live_lbl = QLabel(f"ON NOW ({n})" if n > 1 else "ON NOW")
            live_lbl.setStyleSheet(f"color: {_theme.COLOR_OK}; font-size: {_theme.FONT_LG};")
            header.addWidget(live_lbl)

        remove_btn = QPushButton(self.config.close_icon)
        remove_btn.setFixedWidth(24)
        remove_btn.setToolTip(f"Remove '{pattern}' from watchlist")
        remove_btn.setStyleSheet(_theme.CLOSE_BTN)
        remove_btn.clicked.connect(lambda _=False, p=pattern: self._remove_pattern(p))
        header.addWidget(remove_btn)
        layout.addLayout(header)

        # ── Live title groups ────────────────────────────────────────────── #
        _MAX_VISIBLE = 3  # channels shown per title group before "more" toggle
        _MAX_GROUPS = 4   # title groups shown per card before "more programs" toggle

        def _ch_row(prog):
            """Build one channel row: Xm left [REGION] [LANG?] bare_name [QUALITY?] year? [▶]

            Reads stored detected_* maps (prefix/title/quality/region/year) — no
            parse_channel_name() call (ingestion-only rule, CLAUDE.md).
            Audio chips omitted: detected_audio has no stored column; dropped here
            (see B10-2 deferred notes — adding detected_audio is a future ingestion task).
            """
            cid = prog.channel_db_id or ""
            raw_name = self._channel_name_map.get(cid, prog.channel_epg_id)
            category = self._channel_prefix_map.get(cid, "")
            bare_name = self._channel_title_map.get(cid, raw_name)
            region = self._channel_region_map.get(cid, "")
            display_quality = self._channel_quality_map.get(cid, "")
            year = self._channel_year_map.get(cid, "")

            row_w = QWidget()
            row_w.setCursor(Qt.CursorShape.PointingHandCursor)
            row_w.mousePressEvent = lambda e, c=prog.channel_db_id: self._emit_channel_selected(c)
            row = QHBoxLayout(row_w)
            row.setContentsMargins(16, 0, 4, 0)
            row.setSpacing(4)

            time_lbl = QLabel(f"{_remaining_str(prog.stop_time)}  ·")
            time_lbl.setFixedWidth(90)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            time_lbl.setStyleSheet(_theme.TIME_LABEL)
            row.addWidget(time_lbl)

            if category:
                row.addWidget(make_region_chip(category, row_w))
            if region:
                row.addWidget(make_region_chip(region, row_w))

            name_lbl = QLabel(bare_name)
            name_lbl.setStyleSheet(_theme.CHANNEL_NAME_LIVE)
            row.addWidget(name_lbl, 1)

            if display_quality:
                row.addWidget(make_quality_chip(display_quality, row_w))
            if year:
                row.addWidget(make_year_chip(year, row_w))

            pb = QPushButton(self.config.play_icon)
            pb.setFixedSize(22, 20)
            pb.setFlat(True)
            pb.setToolTip(f"Play: {bare_name}")
            pb.setStyleSheet(_theme.PLAY_BTN)
            cid = prog.channel_db_id
            pb.clicked.connect(lambda _=False, c=cid: self._play_channel(c))
            row.addWidget(pb)
            return row_w

        def _render_group(title: str, progs: list, target_layout) -> None:
            """Render one title group (label + channel rows + optional expand) into target_layout."""
            if title.casefold() != pattern.casefold():
                title_lbl = QLabel(title)
                title_lbl.setWordWrap(True)
                # Ignored policy: long titles don't inflate the card's minimum/preferred width
                title_lbl.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
                title_lbl.setStyleSheet(
                    f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT_2}; font-weight: bold;"
                    " padding-left: 8px; padding-top: 4px;"
                )
                target_layout.addWidget(title_lbl)

            for prog in progs[:_MAX_VISIBLE]:
                target_layout.addWidget(_ch_row(prog))

            if len(progs) > _MAX_VISIBLE:
                extra = progs[_MAX_VISIBLE:]
                n_more = len(extra)

                extra_container = QWidget()
                extra_inner = QVBoxLayout(extra_container)
                extra_inner.setContentsMargins(0, 0, 0, 0)
                extra_inner.setSpacing(2)
                for ep in extra:
                    extra_inner.addWidget(_ch_row(ep))
                extra_container.hide()

                expand_btn = QPushButton(f"{self.config.move_down_icon}  {n_more} more channels")
                expand_btn.setFlat(True)
                expand_btn.setStyleSheet(
                    f"QPushButton {{ color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_SM}; border: none;"
                    " text-align: left; padding-left: 16px; }"
                    f"QPushButton:hover {{ color: {_theme.COLOR_DIM_2}; }}"
                )

                def _toggle(checked=False, btn=expand_btn, cont=extra_container, n=n_more):
                    if cont.isHidden():
                        cont.show()
                        btn.setText(f"{self.config.move_up_icon}  fewer channels")
                    else:
                        cont.hide()
                        btn.setText(f"{self.config.move_down_icon}  {n} more channels")

                expand_btn.clicked.connect(_toggle)
                target_layout.addWidget(expand_btn)
                target_layout.addWidget(extra_container)

        group_list = list(title_groups.items())
        visible_groups = group_list[:_MAX_GROUPS]
        extra_groups = group_list[_MAX_GROUPS:]

        for title, progs in visible_groups:
            _render_group(title, progs, layout)

        if extra_groups:
            n_extra_grps = len(extra_groups)
            extra_grp_container = QWidget()
            extra_grp_layout = QVBoxLayout(extra_grp_container)
            extra_grp_layout.setContentsMargins(0, 0, 0, 0)
            extra_grp_layout.setSpacing(3)
            for title, progs in extra_groups:
                _render_group(title, progs, extra_grp_layout)
            extra_grp_container.hide()

            more_grps_btn = QPushButton(
                f"{self.config.move_down_icon}  {n_extra_grps} more programs"
            )
            more_grps_btn.setFlat(True)
            more_grps_btn.setStyleSheet(
                f"QPushButton {{ color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_SM}; border: none;"
                " text-align: left; padding: 2px 8px; }"
                f"QPushButton:hover {{ color: {_theme.COLOR_MUTED}; }}"
            )

            def _toggle_groups(_, btn=more_grps_btn, cont=extra_grp_container, n=n_extra_grps):
                if cont.isHidden():
                    cont.show()
                    btn.setText(f"{self.config.move_up_icon}  fewer programs")
                else:
                    cont.hide()
                    btn.setText(f"{self.config.move_down_icon}  {n} more programs")

            more_grps_btn.clicked.connect(_toggle_groups)
            layout.addWidget(more_grps_btn)
            layout.addWidget(extra_grp_container)

        # ── Separator + upcoming ─────────────────────────────────────────── #
        if is_live and upcoming:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(_theme.SEPARATOR_LINE)
            sep.setMaximumHeight(1)
            layout.addWidget(sep)

        # Group upcoming by title (up to 3 title groups, up to 2 channels each)
        up_title_groups: dict[str, list] = defaultdict(list)
        for prog in upcoming:
            up_title_groups[prog.title].append(prog)
        # Sort by earliest start time per group
        up_title_groups = dict(
            sorted(up_title_groups.items(), key=lambda kv: kv[1][0].start_time)
        )

        def _up_row(prog):
            """Build one upcoming-row widget using stored detected_* maps.

            Mirrors _ch_row: reads prefix/title/quality/region/year from pre-fetched
            maps — no parse_channel_name() call (ingestion-only rule, CLAUDE.md).
            Audio chips omitted: detected_audio has no stored column (deferred, B10-2).
            """
            cid = prog.channel_db_id or ""
            raw_name = self._channel_name_map.get(cid, prog.channel_epg_id)
            category = self._channel_prefix_map.get(cid, "")
            bare_name = self._channel_title_map.get(cid, raw_name)
            region = self._channel_region_map.get(cid, "")
            display_quality = self._channel_quality_map.get(cid, "")
            year = self._channel_year_map.get(cid, "")

            now = _now_utc()
            if prog.start_time <= now:
                time_str = _remaining_str(prog.stop_time)
            else:
                mins = _minutes_away(prog.start_time)
                if mins < 120:
                    time_str = f"in {mins} min"
                elif _is_local_today(prog.start_time):
                    time_str = f"Today {_format_time(prog.start_time)}"
                else:
                    time_str = f"{_local_weekday(prog.start_time)} {_format_time(prog.start_time)}"

            row_w = QWidget()
            row_w.setCursor(Qt.CursorShape.PointingHandCursor)
            row_w.mousePressEvent = lambda e, c=prog.channel_db_id: self._emit_channel_selected(c)
            row = QHBoxLayout(row_w)
            row.setContentsMargins(16, 0, 4, 0)
            row.setSpacing(4)
            time_lbl = QLabel(f"{time_str}  ·")
            time_lbl.setFixedWidth(90)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            time_lbl.setStyleSheet(_theme.TIME_LABEL_UPCOMING)
            row.addWidget(time_lbl)
            if category:
                row.addWidget(make_region_chip(category, row_w))
            if region:
                row.addWidget(make_region_chip(region, row_w))
            name_lbl = QLabel(bare_name)
            name_lbl.setStyleSheet(_theme.CHANNEL_NAME_UPCOMING)
            row.addWidget(name_lbl, 1)
            if display_quality:
                row.addWidget(make_quality_chip(display_quality, row_w))
            if year:
                row.addWidget(make_year_chip(year, row_w))
            return row_w

        for title, progs in list(up_title_groups.items())[:3]:
            if title.casefold() != pattern.casefold():
                title_lbl = QLabel(title)
                title_lbl.setWordWrap(True)
                title_lbl.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
                title_lbl.setStyleSheet(
                    f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT_LOW}; font-style: italic; padding-left: 8px;"
                )
                layout.addWidget(title_lbl)
            for prog in progs[:2]:
                layout.addWidget(_up_row(prog))

        return w

    def _make_quiet_section(self, patterns: list[str]) -> QWidget:
        """Collapsible section for watchlist patterns that have no current or upcoming matches."""
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(4)

        collapsed = self.config.epg_watchlist_quiet_collapsed
        n = len(patterns)

        toggle_btn = QPushButton()
        toggle_btn.setFlat(True)
        toggle_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_MD}; border: none;"
            " text-align: left; padding: 2px 4px; }"
            f"QPushButton:hover {{ color: {_theme.COLOR_MUTED}; }}"
        )

        cards_container = QWidget()
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(6)
        for pattern in patterns:
            card = self._make_watchlist_item(pattern, [], [])
            card.setStyleSheet(card.styleSheet() + " opacity: 0.55;")
            cards_layout.addWidget(card)

        def _update_label():
            arrow = self.config.move_down_icon if cards_container.isHidden() else self.config.move_up_icon
            toggle_btn.setText(f"{arrow}  OFF AIR  ·  {n}")

        def _toggle(checked=False):
            if cards_container.isHidden():
                cards_container.show()
                self.config.epg_watchlist_quiet_collapsed = False
            else:
                cards_container.hide()
                self.config.epg_watchlist_quiet_collapsed = True
            self.config.save()
            _update_label()

        toggle_btn.clicked.connect(_toggle)
        outer.addWidget(toggle_btn)
        outer.addWidget(cards_container)

        if collapsed:
            cards_container.hide()
        _update_label()

        return w

    def _make_channel_item(self, channel_db_id: str, channel_name: str,
                           prog: EpgProgramDB | None) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(280)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.setStyleSheet(_theme.CARD_BG)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        p = parse_channel_name(channel_name)
        db_quality = self._channel_quality_map.get(channel_db_id, "")
        display_quality = db_quality or (p.quality[0] if p.quality else "")

        header = QHBoxLayout()
        icon_lbl = QLabel(f"{self.config.series_icon} ")
        icon_lbl.setStyleSheet(f"font-size: {_theme.FONT_XL};")
        header.addWidget(icon_lbl)
        if p.region:
            header.addWidget(make_region_chip(p.region, w))
        if p.audio:
            header.addWidget(make_audio_chip(p.audio, w))
        if p.lang:
            header.addWidget(make_region_chip(p.lang, w))
        ch_lbl = QLabel(p.bare_name or channel_name)
        ch_lbl.setStyleSheet(_theme.LIST_TITLE)
        header.addWidget(ch_lbl)
        if display_quality:
            header.addWidget(make_quality_chip(display_quality, w))
        if p.year:
            header.addWidget(make_year_chip(p.year, w))
        header.addStretch()

        if prog:
            play_btn = QPushButton(f"{self.config.play_icon} Play")
            play_btn.setFixedWidth(70)
            play_btn.setStyleSheet(
                f"background: {_theme.COLOR_ACCENT_GREEN}; color: white; border-radius: 3px; padding: 2px 6px;"
            )
            play_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._play_channel(cid))
            header.addWidget(play_btn)

        remove_btn = QPushButton(self.config.close_icon)
        remove_btn.setFixedWidth(24)
        remove_btn.setToolTip(f"Stop watching '{channel_name}'")
        remove_btn.setStyleSheet(_theme.CLOSE_BTN)
        remove_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._unwatch_channel(cid))
        header.addWidget(remove_btn)
        layout.addLayout(header)

        if prog:
            now = _now_utc()
            remain = _remaining_str(prog.stop_time) if prog.stop_time > now else ""
            suffix = f"  ·  {remain}" if remain else ""
            prog_lbl = QLabel(f"  {prog.title}{suffix}")
            prog_lbl.setStyleSheet(f"color: {_theme.COLOR_DIM_2}; font-size: {_theme.FONT_MD}; padding-left: 16px;")
            layout.addWidget(prog_lbl)
        else:
            no_epg = QLabel("  No EPG data")
            no_epg.setStyleSheet(f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_MD}; padding-left: 16px;")
            layout.addWidget(no_epg)

        return w

    def _make_recommendation_item(self, channel_db_id: str, channel_name: str, count: int) -> QWidget:
        # Outer container holds header row + expandable matches sub-list.
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── Header row (chips, name, count, buttons) ─────────────────────────
        header_w = QWidget()
        layout = QHBoxLayout(header_w)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        # Clicking the header row body → details pane
        # (QPushButtons consume their own clicks, so buttons remain independent.)
        header_w.setCursor(Qt.CursorShape.PointingHandCursor)
        header_w.mousePressEvent = lambda e, cid=channel_db_id: self._emit_channel_selected(cid)

        p = parse_channel_name(channel_name)
        db_quality = self._channel_quality_map.get(channel_db_id, "")
        display_quality = db_quality or (p.quality[0] if p.quality else "")

        if p.region:
            layout.addWidget(make_region_chip(p.region, header_w))
        if p.audio:
            layout.addWidget(make_audio_chip(p.audio, header_w))
        if p.lang:
            layout.addWidget(make_region_chip(p.lang, header_w))
        name_lbl = QLabel(p.bare_name or channel_name)
        name_lbl.setStyleSheet(_theme.DISCOVER_REC_NAME)
        layout.addWidget(name_lbl)
        if display_quality:
            layout.addWidget(make_quality_chip(display_quality, header_w))
        if p.year:
            layout.addWidget(make_year_chip(p.year, header_w))

        # Expandable count toggle label
        _collapsed_state = [True]  # mutable cell to capture toggle state in closures

        count_lbl = QLabel(f"{_icons.expand_icon} {count} matches")
        count_lbl.setStyleSheet(_theme.DISCOVER_REC_COUNT)
        count_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(count_lbl)
        layout.addStretch()

        # + Channel button (pins to My Channels watch list)
        watch_btn = QPushButton("+ Channel")
        watch_btn.setFixedWidth(75)
        watch_btn.setStyleSheet(_theme.DISCOVER_REC_PILL_BTN)
        watch_btn.setToolTip("Add to My Channels")
        watch_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._watch_channel(cid))
        layout.addWidget(watch_btn)

        # Play button
        play_btn = QPushButton(_icons.play_icon)
        play_btn.setFixedWidth(28)
        play_btn.setStyleSheet(_theme.DISCOVER_REC_PILL_BTN)
        play_btn.setToolTip("Play this channel")
        play_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._play_channel(cid))
        layout.addWidget(play_btn)

        # Skip / dismiss button
        skip_btn = QPushButton(f"{_icons.close_icon} skip")
        skip_btn.setFixedWidth(55)
        skip_btn.setStyleSheet(_theme.DISCOVER_REC_SKIP_BTN)
        skip_btn.setToolTip("Dismiss this recommendation for 7 days")
        skip_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._dismiss_channel(cid))
        layout.addWidget(skip_btn)

        outer_layout.addWidget(header_w)

        # ── Expandable matches sub-list (lazy-loaded on first expand) ────────
        sub_list = QWidget()
        sub_list.hide()
        sub_layout = QVBoxLayout(sub_list)
        sub_layout.setContentsMargins(16, 2, 10, 4)
        sub_layout.setSpacing(1)
        outer_layout.addWidget(sub_list)

        _loaded = [False]  # lazy-load flag

        def _toggle_matches(_event=None) -> None:
            if _collapsed_state[0]:
                # Expand
                _collapsed_state[0] = False
                count_lbl.setText(f"{_icons.collapse_icon} {count} matches")
                if not _loaded[0]:
                    _loaded[0] = True
                    self._load_rec_matches(channel_db_id, sub_layout)
                sub_list.show()
            else:
                # Collapse
                _collapsed_state[0] = True
                count_lbl.setText(f"{_icons.expand_icon} {count} matches")
                sub_list.hide()

        count_lbl.mousePressEvent = _toggle_matches

        return outer

    def _load_rec_matches(self, channel_db_id: str, sub_layout: QVBoxLayout) -> None:
        """Fetch and render matching upcoming programmes into the sub-list.

        Runs inline (blocking) — the query is a tiny bounded single-channel
        lookup (limit 10) and is only triggered by an explicit user click.
        """
        from metatv.core.repositories import RepositoryFactory

        patterns = self.config.epg_watchlist_patterns
        provider_ids = self._filtered_provider_ids()

        try:
            with self.db.session_scope(commit=False) as session:
                repos = RepositoryFactory(session)
                rows = repos.epg.get_matching_programs(
                    channel_db_id=channel_db_id,
                    patterns=patterns,
                    provider_ids=provider_ids,
                )
        except Exception as exc:
            logger.warning(f"EpgView: failed to load rec matches for {channel_db_id}: {exc}")
            rows = []

        if not rows:
            lbl = QLabel("No upcoming matches found")
            lbl.setStyleSheet(_theme.LABEL_MUTED)
            sub_layout.addWidget(lbl)
            return

        for title, start_time in rows:
            local_dt = _to_local(start_time)
            time_str = _format_time(local_dt)
            row_lbl = QLabel(f"{time_str}  ·  {title}")
            row_lbl.setStyleSheet(_theme.DISCOVER_REC_MATCH_ROW)
            sub_layout.addWidget(row_lbl)

    # ── On Now render ──────────────────────────────────────────────────

    # Regex extracts the prefix from "BE ★ Channel Name", "US| Channel Name",
    # "ARGENTINA ★ ...", "EPL ★ ...", "EFL-L1 ★ ..." — allows hyphens/digits for
    # competition/league codes. Best-effort; not all prefixes are countries.
    _PREFIX_RE = re.compile(
        r'^([A-Z][A-Z0-9\-]{1,11})\s*(?:[★|]|-\s+)\s*(.+)$',
        re.IGNORECASE,
    )

    # Normalize full country names that appear as prefixes → short codes for display
    _COUNTRY_ABBREV: dict[str, str] = {
        "ARGENTINA": "ARG",
        "AUSTRALIA": "AUS",
        "AUSTRIA": "AUT",
        "BELGIUM": "BEL",
        "BOLIVIA": "BOL",
        "BRAZIL": "BRA",
        "CANADA": "CAN",
        "CHILE": "CHL",
        "COLOMBIA": "COL",
        "CROATIA": "HRV",
        "DENMARK": "DEN",
        "ECUADOR": "ECU",
        "FINLAND": "FIN",
        "FRANCE": "FRA",
        "GERMANY": "GER",
        "GREECE": "GRE",
        "HUNGARY": "HUN",
        "IRELAND": "IRL",
        "ITALY": "ITA",
        "MEXICO": "MEX",
        "NETHERLANDS": "NED",
        "NORWAY": "NOR",
        "PARAGUAY": "PAR",
        "PERU": "PER",
        "POLAND": "POL",
        "PORTUGAL": "POR",
        "ROMANIA": "ROU",
        "RUSSIA": "RUS",
        "SPAIN": "ESP",
        "SWEDEN": "SWE",
        "SWITZERLAND": "SUI",
        "TURKEY": "TUR",
        "UKRAINE": "UKR",
        "URUGUAY": "URY",
        "VENEZUELA": "VEN",
    }

    @staticmethod
    def _on_now_hidden_prefixes(config) -> set[str]:
        """Prefixes/categories hidden from the On Now grid.

        EPG-specific ``epg_hidden_prefixes`` plus the global content exclusions —
        the union of ``global_filter_excluded_categories`` AND
        ``global_filter_excluded_prefixes``, the latter gated by
        ``global_filter_paused``. Mirrors the main channel list's ``_is_filtered``
        (main_window_metadata.py) so On Now and the list agree.
        """
        paused = getattr(config, 'global_filter_paused', False)
        global_excluded = (
            set()
            if paused
            else (
                set(config.global_filter_excluded_categories or [])
                | set(config.global_filter_excluded_prefixes or [])
            )
        )
        return set(config.epg_hidden_prefixes or []) | global_excluded

    def _render_on_now(self, programs: list[EpgProgramDB]) -> None:
        self.on_now_list.setSortingEnabled(False)
        self.on_now_list.clear()
        patterns = [p.lower() for p in self.config.epg_watchlist_patterns]
        hidden_prefixes = self._on_now_hidden_prefixes(self.config)
        now = _now_utc()
        prefix_counts: dict[str, int] = {}

        for prog in programs:
            ch_name = self._channel_name_map.get(prog.channel_db_id or "", prog.channel_epg_id)
            title = prog.title
            if prog.is_live:
                title += " ᴸᶦᵛᵉ"
            if prog.is_new:
                title += " ᴺᵉʷ"

            override_cat = self.config.epg_category_overrides.get(prog.channel_db_id or "")
            if override_cat:
                category = override_cat
                bare_name = ch_name
            else:
                category = self._channel_prefix_map.get(prog.channel_db_id or "", "")
                bare_name = self._channel_title_map.get(prog.channel_db_id or "", ch_name)

            if category in hidden_prefixes:
                continue

            if category:
                prefix_counts[category] = prefix_counts.get(category, 0) + 1

            # Progress bar data
            total_secs = max(1, (prog.stop_time - prog.start_time).total_seconds())
            elapsed_secs = max(0, (now - prog.start_time).total_seconds())
            pct = int(min(100, elapsed_secs / total_secs * 100))
            remaining_text = _remaining_str(prog.stop_time)
            secs_remaining = max(0.0, (prog.stop_time - now).total_seconds())

            quality = self._channel_quality_map.get(prog.channel_db_id or "", "")
            # Columns: Category | Channel | Quality | Show | Progress bar | 🚫
            item = _EpgTreeItem([category, bare_name, quality, title, "", self.config.hide_icon])
            item.setData(0, Qt.ItemDataRole.UserRole, prog.channel_db_id)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, category)  # store category for dialog
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
            item.setData(4, _SORT_ROLE, secs_remaining)
            item.setData(4, _PROGRESS_ROLE, pct)
            item.setData(4, _REMAIN_ROLE, remaining_text)
            item.setToolTip(4, remaining_text)
            item.setData(5, Qt.ItemDataRole.UserRole, prog.title)
            item.setTextAlignment(5, Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(5, "Click to hide…")

            if category:
                item.setToolTip(0, resolve_category_name(category, self.config) or category)

            if any(pat in prog.title.lower() for pat in patterns):
                for col in range(5):
                    item.setForeground(col, QColor(_theme.COLOR_ACCENT_HOVER))
                font = item.font(3)
                font.setBold(True)
                item.setFont(3, font)

            self.on_now_list.addTopLevelItem(item)

        self.on_now_prefix_dropdown.update_groups(prefix_counts)
        self.on_now_list.setSortingEnabled(True)
        self._apply_on_now_filters()
        self._update_filler_btn_label()
        count = self.on_now_list.topLevelItemCount()
        self.on_now_stats.setText(f"{count:,} channels on now")
        self.status_message.emit(f"EPG: {count:,} on now")

    # ------------------------------------------------------------------
    # Interaction handlers
    # ------------------------------------------------------------------

    def _on_tab_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self._reload_all()

    def _apply_on_now_filters(self) -> None:
        """Client-side filter on the On Now tree: search text + region prefix."""
        q = self.on_now_search.text().strip().lower()
        selected = set(self.on_now_prefix_dropdown.get_selected())
        all_prefixes = set(self.on_now_prefix_dropdown.groups.keys())
        filter_prefix = bool(selected) and selected != all_prefixes

        for i in range(self.on_now_list.topLevelItemCount()):
            item = self.on_now_list.topLevelItem(i)
            visible = True

            if q:
                region = item.text(0).lower()
                ch = item.text(1).lower()
                show = item.text(3).lower()
                if q not in region and q not in ch and q not in show:
                    visible = False

            if visible and filter_prefix:
                if item.text(0) not in selected:
                    visible = False

            item.setHidden(not visible)

    def _on_now_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 5 and len(self.on_now_list.selectedItems()) == 1:
            title = item.data(5, Qt.ItemDataRole.UserRole)
            ch_id = item.data(0, Qt.ItemDataRole.UserRole)
            ch_name = item.text(1)
            category = item.data(0, Qt.ItemDataRole.UserRole + 1) or ""
            if title or ch_id:
                self._show_hide_dialog(title, ch_id, ch_name, category)

    def _host(self):
        """Return the MainWindow host (Qt top-level parent) for delegating core actions."""
        return self.window()

    def _on_now_context_menu(self, pos) -> None:
        from metatv.core.repositories import RepositoryFactory

        items = self.on_now_list.selectedItems()
        if not items:
            return

        ch_ids = [i.data(0, Qt.ItemDataRole.UserRole) for i in items]
        valid_ch_ids = [cid for cid in ch_ids if cid]
        is_single = len(items) == 1

        # ── Build context ────────────────────────────────────────────────────
        ctx_kwargs: dict = dict(
            channel_ids=valid_ch_ids or ch_ids,
            surface="epg_on_now",
        )

        if is_single and valid_ch_ids:
            cid = valid_ch_ids[0]
            with self.db.session_scope(commit=False) as session:
                repos = RepositoryFactory(session)
                ch = repos.channels.get_by_id(cid)
                if ch:
                    ctx_kwargs.update(
                        media_type=ch.media_type or "",
                        is_favorite=ch.is_favorite or False,
                        in_queue=repos.queue.is_queued(cid),
                        rating=repos.ratings.get(cid) or 0,
                        is_hidden=ch.is_hidden or False,
                        channel_name=ch.name or "",
                        channel_found=True,
                    )
                else:
                    ctx_kwargs["channel_found"] = False
        else:
            ctx_kwargs["channel_found"] = True

        ctx = ChannelMenuContext(**ctx_kwargs)

        # ── Build handlers ───────────────────────────────────────────────────
        host = self._host()
        handlers: dict = {}

        # Core single-select handlers (only offered for single selection)
        if is_single and valid_ch_ids:
            cid = valid_ch_ids[0]
            is_fav = ctx.is_favorite

            def _play_h(c=cid):
                if hasattr(host, "play_channel_by_id"):
                    host.play_channel_by_id(c)
                else:
                    self._play_channel(c)

            def _play_new_h(c=cid):
                if hasattr(host, "play_channel_new_window_by_id"):
                    host.play_channel_new_window_by_id(c)

            def _fav_h(c=cid, f=is_fav):
                if hasattr(host, "_toggle_favorite_by_id"):
                    host._toggle_favorite_by_id(c, not f)

            def _queue_h(c=cid, iq=ctx.in_queue):
                if hasattr(host, "_add_to_queue") and hasattr(host, "_remove_from_queue"):
                    if iq:
                        host._remove_from_queue(c)
                    else:
                        host._add_to_queue(c)

            handlers["play"] = _play_h
            handlers["play_new_window"] = _play_new_h
            handlers["favorite"] = _fav_h
            handlers["queue"] = _queue_h

            if ctx.media_type in ("movie", "series"):
                def _like_h(c=cid):
                    if hasattr(host, "_toggle_rating"):
                        host._toggle_rating(c, 1)

                def _dislike_h(c=cid):
                    if hasattr(host, "_toggle_rating"):
                        host._toggle_rating(c, -1)

                handlers["like"] = _like_h
                handlers["dislike"] = _dislike_h

        # EPG-extra handlers
        watched = [cid for cid in valid_ch_ids if cid in self.config.epg_watchlist_channels]
        unwatched = [cid for cid in valid_ch_ids if cid not in self.config.epg_watchlist_channels]
        items_snap = items[:]
        valid_ids_snap = valid_ch_ids[:]

        if unwatched:
            _unwatched_snap = unwatched[:]
            handlers["epg_watch"] = lambda ids=_unwatched_snap: [
                self._watch_channel(c) for c in ids
            ]

        if watched:
            _watched_snap = watched[:]
            handlers["epg_unwatch"] = lambda ids=_watched_snap: [
                self._unwatch_channel(c) for c in ids
            ]

        # Track show — only when there are recognizable show titles
        show_titles = list({
            i.text(3).split(" ᴸᶦᵛᵉ")[0].split(" ᴺᵉʷ")[0].strip() for i in items
        })
        if show_titles:
            handlers["epg_track_show"] = lambda its=items_snap: self._track_shows_from_items(its)

        handlers["epg_assign_category"] = lambda its=items_snap: self._bulk_assign_category(its)

        has_override = any(
            cid in self.config.epg_category_overrides for cid in valid_ch_ids
        )
        if has_override:
            handlers["epg_remove_override"] = lambda ids=valid_ids_snap: (
                self._remove_category_overrides(ids)
            )

        handlers["epg_hide_channel"] = lambda ids=valid_ids_snap: self._bulk_hide_channels(ids)
        handlers["epg_hide_show"] = lambda its=items_snap: self._bulk_hide_titles(its)

        menu = build_channel_menu(ctx, handlers, parent=self)
        menu.exec(self.on_now_list.viewport().mapToGlobal(pos))

    def _bulk_assign_category(self, items: list[QTreeWidgetItem]) -> None:
        dlg = _AssignCategoryDialog(self._known_categories(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        code = dlg.category_code()
        if not code:
            return
        overrides = dict(self.config.epg_category_overrides)
        for item in items:
            cid = item.data(0, Qt.ItemDataRole.UserRole)
            if cid:
                overrides[cid] = code
        self.config.epg_category_overrides = overrides
        self.config.save()
        self._reload_on_now()

    def _remove_category_overrides(self, ch_ids: list[str]) -> None:
        overrides = dict(self.config.epg_category_overrides)
        for cid in ch_ids:
            overrides.pop(cid, None)
        self.config.epg_category_overrides = overrides
        self.config.save()
        self._reload_on_now()
        self._render_hidden()

    def _bulk_hide_channels(self, ch_ids: list[str]) -> None:
        hidden = list(self.config.epg_hidden_channels or [])
        for cid in ch_ids:
            if cid and cid not in hidden:
                hidden.append(cid)
        self.config.epg_hidden_channels = hidden
        self.config.save()
        self._reload_on_now()

    def _bulk_hide_titles(self, items: list[QTreeWidgetItem]) -> None:
        hidden = list(self.config.epg_hidden_titles or [])
        for item in items:
            title = item.data(5, Qt.ItemDataRole.UserRole)
            if title and title not in hidden:
                hidden.append(title)
        self.config.epg_hidden_titles = hidden
        self.config.save()
        self._reload_on_now()

    def _known_categories(self) -> list[str]:
        existing = set(self.config.epg_category_overrides.values())
        visible = {
            self.on_now_list.topLevelItem(i).text(0)
            for i in range(self.on_now_list.topLevelItemCount())
            if self.on_now_list.topLevelItem(i).text(0)
        }
        return sorted(existing | visible | set(REGION_FULL_NAMES.keys()))

    def _show_hide_dialog(self, title: str, ch_id: str | None, ch_name: str, category: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Hide from On Now")
        dlg.setModal(True)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(6)
        lay.setContentsMargins(12, 12, 12, 12)
        prompt = QLabel("What would you like to hide?")
        prompt.setStyleSheet("font-weight: bold;")
        lay.addWidget(prompt)
        if title:
            btn_show = QPushButton(f'Hide show: "{title}"')
            btn_show.clicked.connect(lambda: (self._hide_title(title), dlg.accept()))
            lay.addWidget(btn_show)
        if ch_id and ch_name:
            btn_ch = QPushButton(f'Hide channel: "{ch_name}"')
            btn_ch.clicked.connect(lambda: (self._hide_channel(ch_id), dlg.accept()))
            lay.addWidget(btn_ch)
        if category:
            full = resolve_category_name(category, self.config)
            cat_label = f'Hide category: "{category}"' + (f" — {full}" if full else "")
            btn_cat = QPushButton(cat_label)
            btn_cat.clicked.connect(lambda: (self._hide_category(category), dlg.accept()))
            lay.addWidget(btn_cat)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(f"color: {_theme.COLOR_MUTED};")
        cancel.clicked.connect(dlg.reject)
        lay.addWidget(cancel)
        dlg.exec()

    def _hide_title(self, title: str) -> None:
        hidden = list(self.config.epg_hidden_titles or [])
        if title not in hidden:
            hidden.append(title)
            self.config.epg_hidden_titles = hidden
            self.config.save()
        self._reload_on_now()

    def _hide_channel(self, ch_id: str) -> None:
        hidden = list(self.config.epg_hidden_channels or [])
        if ch_id not in hidden:
            hidden.append(ch_id)
            self.config.epg_hidden_channels = hidden
            self.config.save()
        self._reload_on_now()

    def _hide_category(self, prefix: str) -> None:
        hidden = list(self.config.epg_hidden_prefixes or [])
        if prefix not in hidden:
            hidden.append(prefix)
            self.config.epg_hidden_prefixes = hidden
            self.config.save()
        self._reload_on_now()

    def _remove_hidden_channel(self, ch_id: str) -> None:
        hidden = list(self.config.epg_hidden_channels or [])
        if ch_id in hidden:
            hidden.remove(ch_id)
            self.config.epg_hidden_channels = hidden
            self.config.save()
        self._render_hidden()
        self._update_filler_btn_label()

    def _remove_hidden_category(self, prefix: str) -> None:
        hidden = list(self.config.epg_hidden_prefixes or [])
        if prefix in hidden:
            hidden.remove(prefix)
            self.config.epg_hidden_prefixes = hidden
            self.config.save()
        self._render_hidden()
        self._update_filler_btn_label()

    def _get_channel_name_from_db(self, ch_id: str) -> str:
        session = self.db.get_session()
        try:
            ch = session.query(ChannelDB).filter_by(id=ch_id).first()
            return ch.name if ch else ch_id
        finally:
            session.close()

    def _on_filler_toggled(self) -> None:
        self._update_filler_btn_label()
        self._reload_on_now()

    def _update_filler_btn_label(self) -> None:
        n = (len(self.config.epg_hidden_titles or [])
             + len(self.config.epg_filler_patterns or [])
             + len(self.config.epg_hidden_channels or [])
             + len(self.config.epg_hidden_prefixes or []))
        if self.filler_check_btn.isChecked():
            # Hiding is active — clicking will show everything
            self.filler_check_btn.setText("Show All")
        else:
            # Hiding is off — clicking will re-enable hiding
            self.filler_check_btn.setText(f"Hide ({n})")

    def _on_search_changed(self, _: str) -> None:
        self._reload_browse()

    def _save_epg_sort(self, tab: str, col: int, order: Qt.SortOrder) -> None:
        self.config.epg_filter_state[f"{tab}_sort_col"] = col
        self.config.epg_filter_state[f"{tab}_sort_order"] = int(order.value)
        self.config.save()

    def _save_on_now_header_state(self) -> None:
        """Persist On Now column order/widths so they survive restarts."""
        raw = bytes(self.on_now_list.header().saveState().toBase64()).decode("ascii")
        self.config.epg_filter_state["on_now_header_state"] = raw
        self.config.save()

    def _on_force_refresh(self) -> None:
        for pid in self._provider_ids:
            self.epg_manager.force_refresh_provider(pid)

    def _on_epg_refreshed(self, provider_id: str, count: int) -> None:
        if provider_id in self._provider_ids:
            self._update_status_label()
            self._reload_all()

    def _update_status_label(self) -> None:
        if not self._provider_ids:
            self.status_label.setText("No EPG sources")
            return
        texts = [self.epg_manager.get_status_text(pid) for pid in self._provider_ids]
        self.status_label.setText(texts[0] if len(texts) == 1 else f"{len(texts)} sources")

    # ── Watchlist management ───────────────────────────────────────────

    def _track_shows_from_items(self, items: list[QTreeWidgetItem]) -> None:
        from PyQt6.QtWidgets import QInputDialog
        titles = list({
            i.text(3).split(" ᴸᶦᵛᵉ")[0].split(" ᴺᵉʷ")[0].strip() for i in items
        })
        default = titles[0] if len(titles) == 1 else ""
        text, ok = QInputDialog.getText(
            self, "Track show",
            "Add watchlist pattern — edit to a keyword for broader matching:",
            text=default,
        )
        if ok and text.strip():
            self._add_pattern(text.strip())

    def _prompt_track(self, default_text: str) -> None:
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Track show",
            "Add watchlist pattern — edit to a keyword for broader matching:",
            text=default_text,
        )
        if ok and text.strip():
            self._add_pattern(text.strip())

    def _on_add_pattern(self) -> None:
        pattern = self.add_pattern_input.text().strip()
        if pattern and pattern not in self.config.epg_watchlist_patterns:
            self.config.epg_watchlist_patterns.append(pattern)
            self.config.save()
            self.watchlist_changed.emit()
        self.add_pattern_input.clear()
        self._reload_watchlist()

    def _add_pattern(self, pattern: str) -> None:
        if pattern and pattern not in self.config.epg_watchlist_patterns:
            self.config.epg_watchlist_patterns.append(pattern)
            self.config.save()
            self.watchlist_changed.emit()
            self._reload_watchlist()

    def _remove_pattern(self, pattern: str) -> None:
        if pattern in self.config.epg_watchlist_patterns:
            self.config.epg_watchlist_patterns.remove(pattern)
            self.config.save()
            self.watchlist_changed.emit()
            self._reload_watchlist()

    def _watch_channel(self, channel_db_id: str) -> None:
        if channel_db_id not in self.config.epg_watchlist_channels:
            self.config.epg_watchlist_channels.append(channel_db_id)
            self.config.save()
            self.watchlist_changed.emit()
            self._reload_watchlist()

    def _unwatch_channel(self, channel_db_id: str) -> None:
        if channel_db_id in self.config.epg_watchlist_channels:
            self.config.epg_watchlist_channels.remove(channel_db_id)
            self.config.save()
            self.watchlist_changed.emit()
            self._reload_watchlist()

    def _dismiss_channel(self, channel_db_id: str) -> None:
        dismiss_until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        self.config.epg_dismissed_channels[channel_db_id] = dismiss_until
        self.config.save()
        self._reload_watchlist()

    def _dismissed_ids(self) -> set[str]:
        now = _now_utc()
        return {
            cid for cid, ts_str in self.config.epg_dismissed_channels.items()
            if _parse_iso(ts_str) > now
        }

    def _manage_dismissed(self) -> None:
        dlg = _DismissedDialog(self.config, self)
        dlg.exec()
        self._reload_watchlist()

    # ── Playback ───────────────────────────────────────────────────────

    def _play_channel(self, channel_db_id: str | None) -> None:
        if not channel_db_id:
            return
        session = self.db.get_session()
        try:
            ch = session.query(ChannelDB).filter_by(id=channel_db_id).first()
            if ch:
                self.play_channel_requested.emit(ch)
        finally:
            session.close()

    def _on_now_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        self._play_channel(item.data(0, Qt.ItemDataRole.UserRole))

    def _on_now_selection_changed(self, current, _) -> None:
        if not current:
            return
        self._emit_channel_selected(current.data(0, Qt.ItemDataRole.UserRole))

    def _emit_channel_selected(self, channel_db_id: str | None) -> None:
        if not channel_db_id:
            return
        session = self.db.get_session()
        try:
            ch = session.query(ChannelDB).filter_by(id=channel_db_id).first()
            if ch:
                self.channel_selected.emit(ch)
        finally:
            session.close()

    def closeEvent(self, event) -> None:
        self._executor.shutdown(wait=False)
        super().closeEvent(event)

