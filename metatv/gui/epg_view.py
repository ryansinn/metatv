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

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
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
    QStyledItemDelegate,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.core.channel_name_utils import parse_channel_name
from metatv.core.database import ChannelDB, EpgProgramDB
from metatv.core.repositories.epg import EpgRepository
from metatv.gui.badge_utils import make_audio_chip, make_quality_chip, make_region_chip, make_year_chip
from metatv.gui.content_view import ContentView
from metatv.gui import theme as _theme

_SORT_ROLE     = Qt.ItemDataRole.UserRole + 2  # numeric sort key (seconds)
_PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 3  # 0–100 progress pct for progress bar
_REMAIN_ROLE   = Qt.ItemDataRole.UserRole + 4  # "10m left" tooltip string

# ---------------------------------------------------------------------------
# Events tab constants and pure-function grouping helpers
# ---------------------------------------------------------------------------

# Deliberate heuristic compromise (mirrors content_dedup.py): live-event feeds carry
# no explicit stop time, so "on now" is approximated by a 4-hour look-back window.
# Events that started within the window are grouped as on-now/upcoming; events whose
# start_time is older than the window are filed under "Already passed". This is the
# same trade-off called out in CLAUDE.md's Content Dedup section — a known heuristic
# that is clearly documented rather than silently wrong.
LIVE_EVENT_WINDOW = timedelta(hours=4)


def _classify_event(dto, now: datetime):
    """Classify one LiveEventDTO for timeline ordering.

    Returns:
        ``"always"`` for sentinel/always-available feeds,
        ``"active"`` for events within LIVE_EVENT_WINDOW (on-now + upcoming),
        ``"passed"`` for events older than LIVE_EVENT_WINDOW.
    """
    from metatv.core.repositories.dtos import LiveEventDTO  # local import, avoid circular

    if dto.always_available or dto.start_time is None:
        return "always"
    if dto.start_time >= now - LIVE_EVENT_WINDOW:
        return "active"
    return "passed"


def group_events_timeline(
    events: list,
    now: datetime,
    network_filter: str = "All",
) -> tuple[list, list, list]:
    """Group LiveEventDTOs into (on_now_upcoming, always_available, passed).

    Pure function — no Qt, no DB, no side-effects.  Tested directly in
    ``tests/test_epg_events_tab.py``.

    Args:
        events:  List of ``LiveEventDTO`` instances.
        now:     Reference time (UTC-naive datetime from ``now_utc()``).
        network_filter: ``"All"`` to include every event, or a network name to
            narrow results.

    Returns:
        Three lists: (on-now/upcoming sorted asc, always-available, passed sorted
        most-recent-first).
    """
    filtered = events if network_filter == "All" else [
        e for e in events if e.network == network_filter
    ]
    active, always, passed = [], [], []
    for dto in filtered:
        kind = _classify_event(dto, now)
        if kind == "active":
            active.append(dto)
        elif kind == "always":
            always.append(dto)
        else:
            passed.append(dto)
    # Sort active ascending by start_time (soonest first — "on now" then "upcoming")
    active.sort(key=lambda e: e.start_time or datetime.min)
    # Sort passed most-recent-first
    passed.sort(key=lambda e: e.start_time or datetime.min, reverse=True)
    return active, always, passed


def group_events_by_network(
    events: list,
    now: datetime,
    network_filter: str = "All",
) -> dict[str, tuple[list, list, list]]:
    """Group LiveEventDTOs by network, each group ordered active→always→passed.

    Pure function — no Qt, no DB, no side-effects.

    Args:
        events:  List of ``LiveEventDTO`` instances.
        now:     Reference time (UTC-naive datetime from ``now_utc()``).
        network_filter: ``"All"`` or a specific network name.

    Returns:
        Ordered dict mapping network name → (active, always, passed) tuples,
        sorted by network name.
    """
    filtered = events if network_filter == "All" else [
        e for e in events if e.network == network_filter
    ]
    networks: dict[str, list] = {}
    for dto in filtered:
        key = dto.network or "(Unknown)"
        networks.setdefault(key, []).append(dto)

    result = {}
    for net in sorted(networks.keys()):
        net_events = networks[net]
        a, al, p = [], [], []
        for dto in net_events:
            kind = _classify_event(dto, now)
            if kind == "active":
                a.append(dto)
            elif kind == "always":
                al.append(dto)
            else:
                p.append(dto)
        a.sort(key=lambda e: e.start_time or datetime.min)
        p.sort(key=lambda e: e.start_time or datetime.min, reverse=True)
        result[net] = (a, al, p)
    return result


class _ProgressBarDelegate(QStyledItemDelegate):
    """Paints a compact horizontal progress bar in the Remaining column."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        from PyQt6.QtGui import QColor
        pct = index.data(_PROGRESS_ROLE)
        if pct is None:
            super().paint(painter, option, index)
            return
        painter.save()
        r = option.rect.adjusted(4, 6, -4, -6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(55, 55, 55))
        painter.drawRoundedRect(r, 2, 2)
        fill_w = max(4, int(r.width() * pct / 100))
        # hue: 55 (yellow) at start → 30 (orange) near end
        hue = int(55 - (pct / 100) * 25)
        painter.setBrush(QColor.fromHsv(hue, 200, 210, 200))
        from PyQt6.QtCore import QRect
        fill_r = QRect(r.x(), r.y(), fill_w, r.height())
        painter.drawRoundedRect(fill_r, 2, 2)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        from PyQt6.QtCore import QSize
        return QSize(64, super().sizeHint(option, index).height())


class _EpgTreeItem(QTreeWidgetItem):
    """QTreeWidgetItem that sorts any column with a _SORT_ROLE numeric value."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a = self.data(col, _SORT_ROLE)
        b = other.data(col, _SORT_ROLE)
        if a is not None and b is not None:
            return float(a) < float(b)
        # Category column: empty strings sort after non-empty in both directions
        if col == 0:
            a_text = self.text(0)
            b_text = other.text(0)
            if bool(a_text) != bool(b_text):
                return bool(a_text) > bool(b_text)  # non-empty < empty → non-empty first
        return super().__lt__(other)


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


def _progress_bar(start: datetime, stop: datetime, width: int = 20) -> str:
    """ASCII progress bar showing how far through the programme we are."""
    total = max(1, (stop - start).total_seconds())
    elapsed = max(0, (_now_utc() - start).total_seconds())
    ratio = min(1.0, elapsed / total)
    filled = int(ratio * width)
    return "█" * filled + "░" * (width - filled)


class EpgView(ContentView):
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
        sep.setStyleSheet("border: none; border-top: 1px solid #333;")
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
        ci_note.setStyleSheet("color: #555; font-size: 10px;")
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
            "color: #888; font-size: 11px; border: none; background: transparent;"
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
        self.on_now_list.setColumnWidth(1, 130)
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
        # Restore persisted sort; save whenever user clicks a header
        _col = self.config.epg_filter_state.get("on_now_sort_col", 0)
        _ord = Qt.SortOrder(self.config.epg_filter_state.get("on_now_sort_order", 0))
        self.on_now_list.sortByColumn(_col, _ord)
        self.on_now_list.header().sortIndicatorChanged.connect(
            lambda col, order: self._save_epg_sort("on_now", col, order)
        )
        layout.addWidget(self.on_now_list)

        self.on_now_stats = QLabel("")
        self.on_now_stats.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(self.on_now_stats)

        self.stack.addWidget(page)

    # ── Tab 2: Browse ──────────────────────────────────────────────────

    def _build_browse_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Search row with clear button
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search programmes…")
        self.search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_input, 1)
        browse_clear = QPushButton(self.config.close_icon)
        browse_clear.setFixedWidth(24)
        browse_clear.setToolTip("Clear")
        browse_clear.setStyleSheet(_theme.CLEAR_BTN)
        browse_clear.clicked.connect(self.search_input.clear)
        search_row.addWidget(browse_clear)
        layout.addLayout(search_row)

        # Filter row
        filter_row = QHBoxLayout()

        self.date_combo = QComboBox()
        self.date_combo.setFixedWidth(110)
        today = date.today()
        for i in range(6):
            d = today + timedelta(days=i)
            label = "Today" if i == 0 else ("Tomorrow" if i == 1 else d.strftime("%a %b %d"))
            self.date_combo.addItem(label, d)
        self.date_combo.currentIndexChanged.connect(self._reload_browse)

        self.time_combo = QComboBox()
        self.time_combo.setFixedWidth(120)
        for label, val in [
            ("All Day", "all"),
            ("Morning 6–12", "morning"),
            ("Afternoon 12–6", "afternoon"),
            ("Prime Time 6–11", "primetime"),
            ("Late Night 11–3", "latenight"),
        ]:
            self.time_combo.addItem(label, val)
        self.time_combo.currentIndexChanged.connect(self._reload_browse)

        self.hide_filler_btn = QPushButton("Hide Filler ✓")
        self.hide_filler_btn.setCheckable(True)
        self.hide_filler_btn.setChecked(self.config.epg_hide_filler)
        self.hide_filler_btn.setFixedWidth(100)
        self.hide_filler_btn.clicked.connect(self._reload_browse)

        filter_row.addWidget(self.date_combo)
        filter_row.addWidget(self.time_combo)
        filter_row.addStretch()
        filter_row.addWidget(self.hide_filler_btn)
        layout.addLayout(filter_row)

        # Programme tree: Time | Channel | Show | Duration
        self.browse_list = QTreeWidget()
        self.browse_list.setAlternatingRowColors(True)
        self.browse_list.setRootIsDecorated(False)
        self.browse_list.setUniformRowHeights(True)
        self.browse_list.setSortingEnabled(True)
        self.browse_list.setColumnCount(4)
        self.browse_list.setHeaderLabels(["Time", "Channel", "Show", "Duration"])
        hdr = self.browse_list.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.browse_list.itemDoubleClicked.connect(self._browse_double_click)
        self.browse_list.currentItemChanged.connect(self._browse_selection_changed)
        self.browse_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.browse_list.customContextMenuRequested.connect(self._on_browse_context_menu)
        # Restore persisted sort
        _bcol = self.config.epg_filter_state.get("browse_sort_col", 0)
        _bord = Qt.SortOrder(self.config.epg_filter_state.get("browse_sort_order", 0))
        self.browse_list.sortByColumn(_bcol, _bord)
        self.browse_list.header().sortIndicatorChanged.connect(
            lambda col, order: self._save_epg_sort("browse", col, order)
        )
        self.browse_list.setVisible(False)
        layout.addWidget(self.browse_list)

        self.browse_placeholder = QLabel("Search for a programme, sport, or show above")
        self.browse_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browse_placeholder.setStyleSheet("color: #555; font-size: 13px; padding: 40px;")
        layout.addWidget(self.browse_placeholder)

        self.browse_stats = QLabel("")
        self.browse_stats.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(self.browse_stats)

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

    # ── Tab 6: Events ──────────────────────────────────────────────────

    def _build_events_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # ── Control row: Timeline/Network toggle + network filter combo ──
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)

        self._events_timeline_btn = QPushButton("Timeline")
        self._events_timeline_btn.setCheckable(True)
        self._events_timeline_btn.setToolTip("Show events grouped by time (on now → upcoming → always → passed)")
        ctrl_row.addWidget(self._events_timeline_btn)

        self._events_network_btn = QPushButton("By Network")
        self._events_network_btn.setCheckable(True)
        self._events_network_btn.setToolTip("Show events grouped by broadcaster / network")
        ctrl_row.addWidget(self._events_network_btn)

        ctrl_row.addSpacing(12)

        self._events_network_combo = QComboBox()
        self._events_network_combo.setFixedWidth(160)
        self._events_network_combo.setToolTip("Filter by network — narrows both Timeline and By Network views")
        self._events_network_combo.addItem("All")
        ctrl_row.addWidget(self._events_network_combo)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # ── Event list ─────────────────────────────────────────────────
        self._events_list = QListWidget()
        self._events_list.setAlternatingRowColors(False)
        self._events_list.setSpacing(1)
        self._events_list.setUniformItemSizes(False)
        self._events_list.itemClicked.connect(self._on_events_item_clicked)
        self._events_list.itemDoubleClicked.connect(self._on_events_item_double_clicked)
        layout.addWidget(self._events_list)

        self._events_stats = QLabel("")
        self._events_stats.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(self._events_stats)

        self.stack.addWidget(page)

        # ── Wire toggle buttons ────────────────────────────────────────
        # Restore from config
        mode = self.config.epg_events_view_mode
        self._events_timeline_btn.setChecked(mode == "timeline")
        self._events_network_btn.setChecked(mode == "network")
        self._apply_events_toggle_styles()

        self._events_timeline_btn.clicked.connect(self._on_events_mode_timeline)
        self._events_network_btn.clicked.connect(self._on_events_mode_network)
        self._events_network_combo.currentTextChanged.connect(self._on_events_network_changed)

    # ------------------------------------------------------------------
    # Events tab — interaction handlers
    # ------------------------------------------------------------------

    def _apply_events_toggle_styles(self) -> None:
        """Apply active/inactive styles to the Timeline / By Network buttons."""
        if self._events_timeline_btn.isChecked():
            self._events_timeline_btn.setStyleSheet(_theme.EVENTS_SEG_ACTIVE)
            self._events_network_btn.setStyleSheet(_theme.EVENTS_SEG_INACTIVE)
        else:
            self._events_timeline_btn.setStyleSheet(_theme.EVENTS_SEG_INACTIVE)
            self._events_network_btn.setStyleSheet(_theme.EVENTS_SEG_ACTIVE)

    def _on_events_mode_timeline(self) -> None:
        self._events_timeline_btn.setChecked(True)
        self._events_network_btn.setChecked(False)
        self._apply_events_toggle_styles()
        self.config.epg_events_view_mode = "timeline"
        self.config.save()
        self._render_events(self._events_dto_cache)

    def _on_events_mode_network(self) -> None:
        self._events_timeline_btn.setChecked(False)
        self._events_network_btn.setChecked(True)
        self._apply_events_toggle_styles()
        self.config.epg_events_view_mode = "network"
        self.config.save()
        self._render_events(self._events_dto_cache)

    def _on_events_network_changed(self, network: str) -> None:
        self.config.epg_events_network_filter = network
        self.config.save()
        self._render_events(self._events_dto_cache)

    def _on_events_item_clicked(self, item: "QListWidgetItem") -> None:
        """Single-click → emit channel_selected (details pane)."""
        ch_id = item.data(Qt.ItemDataRole.UserRole)
        if ch_id:
            self._emit_channel_selected(ch_id)

    def _on_events_item_double_clicked(self, item: "QListWidgetItem") -> None:
        """Double-click → play the channel."""
        ch_id = item.data(Qt.ItemDataRole.UserRole)
        if ch_id:
            self._play_channel(ch_id)

    # ------------------------------------------------------------------
    # Events tab — data loading
    # ------------------------------------------------------------------

    def _reload_events(self) -> None:
        """Fetch live events off-thread; re-fetch from DB on activate."""
        self._executor.submit(self._fetch_events)

    def _fetch_events(self) -> None:
        """Worker — runs off-thread.  Returns LiveEventDTOs via _data_loaded signal."""
        from metatv.core.repositories import RepositoryFactory
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            excluded = set(repos.providers.get_hidden_provider_ids())
            dtos = repos.channels.get_live_events_dto(excluded_provider_ids=excluded)
            self._data_loaded.emit({"tab": "events", "dtos": dtos})
        except Exception as e:
            logger.error(f"EpgView events fetch error: {e}")
            self._data_loaded.emit({"tab": "events", "dtos": []})
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Events tab — render (main thread)
    # ------------------------------------------------------------------

    def _render_events(self, dtos: list) -> None:
        """Render (or re-group) the events list from cached DTOs on the main thread.

        Called both after a fresh DB fetch (dtos are new) and by the 60-second timer
        (dtos are the cached list — re-group against the fresh ``now_utc()``).
        """
        self._events_list.clear()
        if not dtos:
            item = QListWidgetItem("No platform-event channels found.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(QColor(_theme.COLOR_FAINT))
            self._events_list.addItem(item)
            self._events_stats.setText("")
            return

        now = _now_utc()
        network_filter = self.config.epg_events_network_filter
        mode = self.config.epg_events_view_mode

        def _add_header(text: str) -> None:
            header = QListWidgetItem(text)
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
            font = QFont()
            font.setBold(True)
            header.setFont(font)
            header.setForeground(QColor(_theme.COLOR_MUTED_2))
            self._events_list.addItem(header)

        def _event_time_str(dto) -> str:
            """Format start_time or availability as a human-readable hint."""
            if dto.always_available:
                return "Always on"
            st = dto.start_time
            if st is None:
                return "Always on"
            if st < now - LIVE_EVENT_WINDOW:
                return "ended"
            local_dt = _to_local(st)
            if _is_local_today(st):
                return f"Today {local_dt.strftime('%-I:%M%p').lower().rstrip('m') + 'm'}"
            return f"{_local_weekday(st)} {local_dt.strftime('%-I:%M%p').lower().rstrip('m') + 'm'}"

        def _time_style(dto) -> str:
            """Return a theme style string for the time hint based on event state."""
            if dto.always_available or dto.start_time is None:
                return _theme.EVENTS_TIME_HINT
            if dto.start_time < now - LIVE_EVENT_WINDOW:
                return _theme.EVENTS_TIME_HINT_PASSED
            # Check if within window (on-now)
            if dto.start_time <= now:
                return _theme.EVENTS_TIME_ON_NOW
            return _theme.EVENTS_TIME_HINT

        def _add_event_row(dto) -> None:
            label = dto.detected_title or dto.name
            time_hint = _event_time_str(dto)
            net_str = f"[{dto.network}]  " if dto.network else ""
            region_str = f"  {dto.region}" if dto.region else ""
            display = f"{net_str}{label}{region_str}  ·  {time_hint}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, dto.channel_id)
            item.setToolTip(
                f"Network: {dto.network or '—'}  |  Region: {dto.region or '—'}"
                f"  |  Ch: {dto.channel_num or '—'}"
                f"\nDouble-click to play · Single-click for details"
            )
            # Dim passed events
            if not dto.always_available and dto.start_time and dto.start_time < now - LIVE_EVENT_WINDOW:
                item.setForeground(QColor(_theme.COLOR_FAINT))
            elif not dto.always_available and dto.start_time and dto.start_time <= now:
                item.setForeground(QColor(_theme.COLOR_OK))
            self._events_list.addItem(item)

        total = 0
        if mode == "timeline":
            active, always, passed = group_events_timeline(dtos, now, network_filter)
            if active:
                _add_header(f"ON NOW + UPCOMING  ·  {len(active)}")
                for dto in active:
                    _add_event_row(dto)
                    total += 1
            if always:
                _add_header(f"ALWAYS AVAILABLE  ·  {len(always)}")
                for dto in always:
                    _add_event_row(dto)
                    total += 1
            if passed:
                _add_header(f"ALREADY PASSED  ·  {len(passed)}")
                for dto in passed:
                    _add_event_row(dto)
                    total += 1
            if not (active or always or passed):
                item = QListWidgetItem("No events match the current filter.")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(QColor(_theme.COLOR_FAINT))
                self._events_list.addItem(item)
        else:
            # By Network
            net_groups = group_events_by_network(dtos, now, network_filter)
            for net_name, (active, always, passed) in net_groups.items():
                n = len(active) + len(always) + len(passed)
                if n == 0:
                    continue
                _add_header(f"{net_name}  ·  {n}")
                for dto in active:
                    _add_event_row(dto)
                    total += 1
                for dto in always:
                    _add_event_row(dto)
                    total += 1
                for dto in passed:
                    _add_event_row(dto)
                    total += 1
            if not net_groups:
                item = QListWidgetItem("No events match the current filter.")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(QColor(_theme.COLOR_FAINT))
                self._events_list.addItem(item)

        self._events_stats.setText(f"{total:,} event{'s' if total != 1 else ''}")

        # Rebuild the network filter combo to reflect current event data
        # (block signals to avoid recursive render)
        all_networks = sorted({d.network for d in dtos if d.network})
        saved = self.config.epg_events_network_filter
        self._events_network_combo.blockSignals(True)
        self._events_network_combo.clear()
        self._events_network_combo.addItem("All")
        for net in all_networks:
            self._events_network_combo.addItem(net)
        # Restore saved selection if still present
        idx = self._events_network_combo.findText(saved)
        self._events_network_combo.setCurrentIndex(max(0, idx))
        self._events_network_combo.blockSignals(False)

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
                full = self._CATEGORY_FULL_NAMES.get(prefix, "")
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
                full = self._CATEGORY_FULL_NAMES.get(cat_code, "")
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
        lbl.setStyleSheet("font-size: 12px; color: #ddd;")
        h.addWidget(lbl, 1)
        det = QLabel(detail)
        det.setStyleSheet("font-size: 11px; color: #555;")
        h.addWidget(det)
        rm_btn = QPushButton(self.config.close_icon)
        rm_btn.setFixedWidth(24)
        rm_btn.setStyleSheet("border: none; color: #888; font-size: 14px; font-weight: bold;")
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

    def _reload_browse(self) -> None:
        search = self.search_input.text().strip()
        if not search:
            self._data_loaded.emit({"tab": "browse", "programs": [], "placeholder": True})
            return
        provider_ids = self._filtered_provider_ids()
        target_date = self.date_combo.currentData()
        time_slot = self.time_combo.currentData()
        hide_filler = self.hide_filler_btn.isChecked()
        self._executor.submit(
            self._fetch_browse, provider_ids, target_date, time_slot, search, hide_filler
        )

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
            # Build name + quality maps
            name_map: dict[str, str] = {}
            quality_map: dict[str, str] = {}
            for p in programs:
                if p.channel_db_id and p.channel_db_id not in name_map:
                    ch = session.query(ChannelDB).filter_by(id=p.channel_db_id).first()
                    if ch:
                        name_map[p.channel_db_id] = ch.name
                        if ch.detected_quality:
                            quality_map[p.channel_db_id] = ch.detected_quality.upper()
            self._channel_name_map.update(name_map)
            self._channel_quality_map.update(quality_map)

            self._data_loaded.emit({"tab": "on_now", "programs": programs})
        except Exception as e:
            logger.error(f"EpgView on-now fetch error: {e}")
            self._data_loaded.emit({"tab": "on_now", "programs": []})
        finally:
            session.close()

    def _fetch_browse(self, provider_ids: list[str], target_date: date,
                      time_slot: str, search: str, hide_filler: bool) -> None:
        session = self.db.get_session()
        try:
            repo = EpgRepository(session)
            filler = self.config.epg_filler_patterns if hide_filler else []

            if search:
                programs = repo.search_programs(search, provider_ids, hours_ahead=168)
            else:
                programs = repo.get_schedule(
                    target_date=target_date,
                    provider_ids=provider_ids,
                    hide_filler=hide_filler,
                    filler_patterns=filler,
                    time_slot=time_slot,
                )

            # Build channel name map
            name_map: dict[str, str] = {}
            for p in programs:
                if p.channel_db_id and p.channel_db_id not in name_map:
                    ch = session.query(ChannelDB).filter_by(id=p.channel_db_id).first()
                    if ch:
                        name_map[p.channel_db_id] = ch.name
            self._channel_name_map.update(name_map)

            self._data_loaded.emit({"tab": "browse", "programs": programs})
        except Exception as e:
            logger.error(f"EpgView browse fetch error: {e}")
        finally:
            session.close()

    def _build_name_map(self, session, watchlist_data, live_data) -> dict[str, str]:
        name_map: dict[str, str] = {}
        quality_map: dict[str, str] = {}
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
        self._channel_quality_map.update(quality_map)
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
            empty.setStyleSheet("color: #666; font-size: 13px; padding: 20px;")
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
            live_lbl.setStyleSheet("color: #4a4; font-size: 12px;")
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
            """Build one channel row: Xm left [REGION] [LANG?] bare_name [QUALITY?] year? [▶]"""
            raw_name = self._channel_name_map.get(prog.channel_db_id or "", prog.channel_epg_id)
            p = parse_channel_name(raw_name)

            db_quality = self._channel_quality_map.get(prog.channel_db_id or "")
            display_quality = db_quality or (p.quality[0] if p.quality else "")

            row_w = QWidget()
            cid = prog.channel_db_id
            row_w.setCursor(Qt.CursorShape.PointingHandCursor)
            row_w.mousePressEvent = lambda e, c=cid: self._emit_channel_selected(c)
            row = QHBoxLayout(row_w)
            row.setContentsMargins(16, 0, 4, 0)
            row.setSpacing(4)

            time_lbl = QLabel(f"{_remaining_str(prog.stop_time)}  ·")
            time_lbl.setFixedWidth(90)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            time_lbl.setStyleSheet(_theme.TIME_LABEL)
            row.addWidget(time_lbl)

            if p.region:
                row.addWidget(make_region_chip(p.region, row_w))
            if p.audio:
                row.addWidget(make_audio_chip(p.audio, row_w))
            if p.lang:
                row.addWidget(make_region_chip(p.lang, row_w))

            name_lbl = QLabel(p.bare_name or raw_name)
            name_lbl.setStyleSheet(_theme.CHANNEL_NAME_LIVE)
            row.addWidget(name_lbl, 1)

            if display_quality:
                row.addWidget(make_quality_chip(display_quality, row_w))
            if p.year:
                row.addWidget(make_year_chip(p.year, row_w))

            pb = QPushButton(self.config.play_icon)
            pb.setFixedSize(22, 20)
            pb.setFlat(True)
            pb.setToolTip(f"Play: {p.bare_name or raw_name}")
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
                    "font-size: 11px; color: #ddd; font-weight: bold;"
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
                    "QPushButton { color: #666; font-size: 10px; border: none;"
                    " text-align: left; padding-left: 16px; }"
                    "QPushButton:hover { color: #999; }"
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
                "QPushButton { color: #555; font-size: 10px; border: none;"
                " text-align: left; padding: 2px 8px; }"
                "QPushButton:hover { color: #888; }"
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
            raw_name = self._channel_name_map.get(prog.channel_db_id or "", prog.channel_epg_id)
            p = parse_channel_name(raw_name)
            db_quality = self._channel_quality_map.get(prog.channel_db_id or "")
            display_quality = db_quality or (p.quality[0] if p.quality else "")

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
            cid = prog.channel_db_id
            row_w.setCursor(Qt.CursorShape.PointingHandCursor)
            row_w.mousePressEvent = lambda e, c=cid: self._emit_channel_selected(c)
            row = QHBoxLayout(row_w)
            row.setContentsMargins(16, 0, 4, 0)
            row.setSpacing(4)
            time_lbl = QLabel(f"{time_str}  ·")
            time_lbl.setFixedWidth(90)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            time_lbl.setStyleSheet(_theme.TIME_LABEL_UPCOMING)
            row.addWidget(time_lbl)
            if p.region:
                row.addWidget(make_region_chip(p.region, row_w))
            if p.audio:
                row.addWidget(make_audio_chip(p.audio, row_w))
            if p.lang:
                row.addWidget(make_region_chip(p.lang, row_w))
            name_lbl = QLabel(p.bare_name or raw_name)
            name_lbl.setStyleSheet(_theme.CHANNEL_NAME_UPCOMING)
            row.addWidget(name_lbl, 1)
            if display_quality:
                row.addWidget(make_quality_chip(display_quality, row_w))
            if p.year:
                row.addWidget(make_year_chip(p.year, row_w))
            return row_w

        for title, progs in list(up_title_groups.items())[:3]:
            if title.casefold() != pattern.casefold():
                title_lbl = QLabel(title)
                title_lbl.setWordWrap(True)
                title_lbl.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
                title_lbl.setStyleSheet(
                    "font-size: 11px; color: #bbb; font-style: italic; padding-left: 8px;"
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
            "QPushButton { color: #555; font-size: 11px; border: none;"
            " text-align: left; padding: 2px 4px; }"
            "QPushButton:hover { color: #888; }"
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
        icon_lbl.setStyleSheet("font-size: 13px;")
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
                "background: #2a6; color: white; border-radius: 3px; padding: 2px 6px;"
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
            prog_lbl.setStyleSheet("color: #999; font-size: 11px; padding-left: 16px;")
            layout.addWidget(prog_lbl)
        else:
            no_epg = QLabel("  No EPG data")
            no_epg.setStyleSheet("color: #555; font-size: 11px; padding-left: 16px;")
            layout.addWidget(no_epg)

        return w

    def _make_recommendation_item(self, channel_db_id: str, channel_name: str, count: int) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        p = parse_channel_name(channel_name)
        db_quality = self._channel_quality_map.get(channel_db_id, "")
        display_quality = db_quality or (p.quality[0] if p.quality else "")

        if p.region:
            layout.addWidget(make_region_chip(p.region, w))
        if p.audio:
            layout.addWidget(make_audio_chip(p.audio, w))
        if p.lang:
            layout.addWidget(make_region_chip(p.lang, w))
        name_lbl = QLabel(p.bare_name or channel_name)
        name_lbl.setStyleSheet("font-size: 12px;")
        layout.addWidget(name_lbl)
        if display_quality:
            layout.addWidget(make_quality_chip(display_quality, w))
        if p.year:
            layout.addWidget(make_year_chip(p.year, w))
        count_lbl = QLabel(f"{count} matches")
        count_lbl.setStyleSheet(_theme.LABEL_MUTED)
        layout.addWidget(count_lbl)
        layout.addStretch()

        watch_btn = QPushButton("+ Watch")
        watch_btn.setFixedWidth(70)
        watch_btn.setStyleSheet("color: #4af; border: 1px solid #4af; border-radius: 3px; padding: 1px 4px; font-size: 11px;")
        watch_btn.setToolTip(f"Add '{channel_name}' to watchlist")
        watch_btn.clicked.connect(lambda _=False, n=channel_name: self._add_pattern(n))
        layout.addWidget(watch_btn)

        skip_btn = QPushButton(f"{self.config.close_icon} skip")
        skip_btn.setFixedWidth(55)
        skip_btn.setStyleSheet("color: #666; border: none; background: transparent; font-size: 11px;")
        skip_btn.setToolTip("Dismiss this recommendation for 7 days")
        skip_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._dismiss_channel(cid))
        layout.addWidget(skip_btn)

        return w

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

    # Maps category/prefix codes → human-readable name for tooltips.
    # Covers common 2-letter ISO codes, 3-letter sport codes from _COUNTRY_ABBREV,
    # and known competition codes. Best-effort — unknown codes show the raw code.
    _CATEGORY_FULL_NAMES: dict[str, str] = {
        # 2-letter ISO
        "US": "United States", "UK": "United Kingdom", "GB": "United Kingdom",
        "BE": "Belgium", "FR": "France", "DE": "Germany", "ES": "Spain",
        "IT": "Italy", "PT": "Portugal", "NL": "Netherlands", "SE": "Sweden",
        "NO": "Norway", "DK": "Denmark", "FI": "Finland", "PL": "Poland",
        "RO": "Romania", "HU": "Hungary", "CZ": "Czech Republic", "GR": "Greece",
        "TR": "Turkey", "RU": "Russia", "UA": "Ukraine", "BR": "Brazil",
        "MX": "Mexico", "CA": "Canada", "AU": "Australia", "NZ": "New Zealand",
        "JP": "Japan", "KR": "South Korea", "CN": "China", "IN": "India",
        "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PE": "Peru",
        "VE": "Venezuela", "IR": "Iran", "SA": "Saudi Arabia", "AE": "UAE",
        "EG": "Egypt", "MA": "Morocco", "IL": "Israel", "ZA": "South Africa",
        "NG": "Nigeria", "PK": "Pakistan", "BD": "Bangladesh", "TH": "Thailand",
        "VN": "Vietnam", "ID": "Indonesia", "PH": "Philippines", "AT": "Austria",
        "CH": "Switzerland", "IE": "Ireland", "HR": "Croatia", "SK": "Slovakia",
        "SI": "Slovenia", "BG": "Bulgaria", "RS": "Serbia", "BA": "Bosnia",
        "AL": "Albania", "MK": "North Macedonia", "LU": "Luxembourg",
        # 3-letter from _COUNTRY_ABBREV
        "ARG": "Argentina", "AUS": "Australia", "AUT": "Austria", "BEL": "Belgium",
        "BOL": "Bolivia", "BRA": "Brazil", "CAN": "Canada", "CHL": "Chile",
        "COL": "Colombia", "HRV": "Croatia", "DEN": "Denmark", "ECU": "Ecuador",
        "FIN": "Finland", "FRA": "France", "GER": "Germany", "GRE": "Greece",
        "HUN": "Hungary", "IRL": "Ireland", "ITA": "Italy", "MEX": "Mexico",
        "NED": "Netherlands", "NOR": "Norway", "PAR": "Paraguay", "PER": "Peru",
        "POL": "Poland", "POR": "Portugal", "ROU": "Romania", "RUS": "Russia",
        "ESP": "Spain", "SWE": "Sweden", "SUI": "Switzerland", "TUR": "Turkey",
        "UKR": "Ukraine", "URY": "Uruguay", "VEN": "Venezuela",
        # Common sports/competition leagues — displayed as-is in tooltip
        "EPL": "English Premier League", "EFL": "English Football League",
        "NBA": "NBA Basketball", "NFL": "NFL Football", "MLB": "MLB Baseball",
        "NHL": "NHL Hockey", "UFC": "UFC / MMA", "WWE": "WWE Wrestling",
        # Well-known brands — used for tooltip display when user manually assigns
        "BEIN": "beIN Sports", "MBC": "MBC", "SKY": "Sky",
        "ESPN": "ESPN", "FOX": "Fox", "CNN": "CNN",
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
                _p = parse_channel_name(ch_name)
                category, bare_name = _p.region, _p.bare_name

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
                full_name = self._CATEGORY_FULL_NAMES.get(category, "")
                item.setToolTip(0, full_name if full_name else category)

            if any(pat in prog.title.lower() for pat in patterns):
                for col in range(5):
                    item.setForeground(col, QColor("#4af"))
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

    # ── Browse render ──────────────────────────────────────────────────

    def _render_browse(self, programs: list[EpgProgramDB], placeholder: bool = False) -> None:
        if placeholder:
            self.browse_list.setVisible(False)
            self.browse_placeholder.setVisible(True)
            self.browse_stats.clear()
            return
        self.browse_placeholder.setVisible(False)
        self.browse_list.setVisible(True)
        self.browse_list.setSortingEnabled(False)
        self.browse_list.clear()
        patterns = [p.lower() for p in self.config.epg_watchlist_patterns]

        for prog in programs:
            ch_name = self._channel_name_map.get(prog.channel_db_id or "", prog.channel_epg_id)
            time_str = _format_time(prog.start_time)
            dur = _duration_str(prog.start_time, prog.stop_time)
            title = prog.title
            if prog.is_live:
                title += " ᴸᶦᵛᵉ"
            if prog.is_new:
                title += " ᴺᵉʷ"

            item = _EpgTreeItem([time_str, ch_name, title, dur])
            item.setData(0, Qt.ItemDataRole.UserRole, prog.channel_db_id)
            item.setData(0, _SORT_ROLE, prog.start_time.timestamp())

            if any(pat in prog.title.lower() for pat in patterns):
                for col in range(4):
                    item.setForeground(col, QColor("#4af"))
                font = item.font(2)
                font.setBold(True)
                item.setFont(2, font)

            self.browse_list.addTopLevelItem(item)

        self.browse_list.setSortingEnabled(True)
        count = len(programs)
        self.browse_stats.setText(f"{count:,} programmes")
        self.status_message.emit(f"EPG: {count:,} programmes")

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

    def _on_now_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu
        items = self.on_now_list.selectedItems()
        if not items:
            return
        n = len(items)
        menu = QMenu(self)

        assign_act = menu.addAction(f"Assign category… ({n} channel{'s' if n > 1 else ''})")
        assign_act.triggered.connect(lambda: self._bulk_assign_category(items[:]))

        ch_ids = [i.data(0, Qt.ItemDataRole.UserRole) for i in items]
        has_override = any(
            cid in self.config.epg_category_overrides for cid in ch_ids if cid
        )
        if has_override:
            rm_act = menu.addAction("Remove category override")
            rm_act.triggered.connect(lambda: self._remove_category_overrides(ch_ids[:]))

        watched = [cid for cid in ch_ids if cid and cid in self.config.epg_watchlist_channels]
        unwatched = [cid for cid in ch_ids if cid and cid not in self.config.epg_watchlist_channels]
        if unwatched:
            watch_act = menu.addAction(f"Watch channel{'s' if len(unwatched) > 1 else ''}…")
            watch_act.triggered.connect(lambda: [self._watch_channel(cid) for cid in unwatched])
        if watched:
            unwatch_act = menu.addAction(f"Unwatch channel{'s' if len(watched) > 1 else ''}…")
            unwatch_act.triggered.connect(lambda: [self._unwatch_channel(cid) for cid in watched])

        # Track show title as watchlist pattern
        show_titles = list({
            i.text(3).split(" ᴸᶦᵛᵉ")[0].split(" ᴺᵉʷ")[0].strip() for i in items
        })
        if show_titles:
            preview = show_titles[0] if len(show_titles) == 1 else f"{len(show_titles)} shows"
            track_act = menu.addAction(f"Track show: '{preview}'…")
            track_act.triggered.connect(lambda: self._track_shows_from_items(items[:]))

        menu.addSeparator()
        hide_ch = menu.addAction(f"Hide channel{'s' if n > 1 else ''}…")
        hide_ch.triggered.connect(lambda: self._bulk_hide_channels(ch_ids[:]))
        hide_show = menu.addAction(f"Hide show{'s' if n > 1 else ''}…")
        hide_show.triggered.connect(lambda: self._bulk_hide_titles(items[:]))

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
        return sorted(existing | visible | set(self._CATEGORY_FULL_NAMES.keys()))

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
            full = self._CATEGORY_FULL_NAMES.get(category, "")
            cat_label = f'Hide category: "{category}"' + (f" — {full}" if full else "")
            btn_cat = QPushButton(cat_label)
            btn_cat.clicked.connect(lambda: (self._hide_category(category), dlg.accept()))
            lay.addWidget(btn_cat)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet("color: #888;")
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

    def _browse_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        self._play_channel(item.data(0, Qt.ItemDataRole.UserRole))

    def _on_browse_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu
        item = self.browse_list.itemAt(pos)
        if not item:
            return
        title = item.text(2).split(" ᴸᶦᵛᵉ")[0].split(" ᴺᵉʷ")[0].strip()
        channel_db_id = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        track_act = menu.addAction(f"Track: '{title}'…")
        track_act.triggered.connect(lambda: self._prompt_track(title))
        if channel_db_id and channel_db_id not in self.config.epg_watchlist_channels:
            watch_act = menu.addAction("Watch this channel")
            watch_act.triggered.connect(lambda: self._watch_channel(channel_db_id))
        play_act = menu.addAction(f"{self.config.play_icon} Play")
        play_act.triggered.connect(lambda: self._play_channel(channel_db_id))
        menu.exec(self.browse_list.viewport().mapToGlobal(pos))

    def _on_now_selection_changed(self, current, _) -> None:
        if not current:
            return
        self._emit_channel_selected(current.data(0, Qt.ItemDataRole.UserRole))

    def _browse_selection_changed(self, current, _) -> None:
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


# ------------------------------------------------------------------
# Manage Dismissed dialog
# ------------------------------------------------------------------

class _DismissedDialog(QDialog):
    """Lists dismissed channels and allows un-dismissing them."""

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Manage Dismissed Channels")
        self.resize(400, 300)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dismissed recommendations (click to un-dismiss):"))

        self.list = QListWidget()
        layout.addWidget(self.list)

        now = _now_utc()
        for cid, ts_str in list(self.config.epg_dismissed_channels.items()):
            until = _parse_iso(ts_str)
            if until > now:
                days = max(0, (until - now).days)
                item = QListWidgetItem(f"{cid} — {days}d remaining")
                item.setData(Qt.ItemDataRole.UserRole, cid)
                self.list.addItem(item)

        if self.list.count() == 0:
            self.list.addItem("No dismissed channels.")

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        undismiss_btn = QPushButton("Un-dismiss selected")
        undismiss_btn.clicked.connect(self._undismiss)
        btn_box.addButton(undismiss_btn, QDialogButtonBox.ButtonRole.ActionRole)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _undismiss(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid and cid in self.config.epg_dismissed_channels:
            del self.config.epg_dismissed_channels[cid]
            self.config.save()
            row = self.list.row(item)
            self.list.takeItem(row)


# ------------------------------------------------------------------
# Assign Category dialog
# ------------------------------------------------------------------

class _AssignCategoryDialog(QDialog):
    """Lets the user pick or type a category code to assign to selected channels."""

    def __init__(self, known: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Category")
        self.setModal(True)
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(12, 12, 12, 12)

        lay.addWidget(QLabel("Category code (e.g. BEIN, US, UK, NHL):"))

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Type a code or pick from list below…")
        lay.addWidget(self._edit)

        from PyQt6.QtWidgets import QComboBox
        combo = QComboBox()
        combo.addItem("— pick existing —")
        combo.addItems(known)
        combo.currentIndexChanged.connect(
            lambda i: self._edit.setText(combo.currentText()) if i > 0 else None
        )
        lay.addWidget(combo)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def category_code(self) -> str:
        return self._edit.text().strip().upper()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_iso(ts_str: str) -> datetime:
    """Parse ISO timestamp string to naive datetime (UTC)."""
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return datetime.min
