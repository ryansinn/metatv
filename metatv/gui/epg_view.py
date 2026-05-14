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
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.core.database import ChannelDB, EpgProgramDB, ProviderDB
from metatv.core.repositories.epg import EpgRepository
from metatv.gui.content_view import ContentView

_SORT_ROLE = Qt.ItemDataRole.UserRole + 2  # stores epoch float for time-column sorting


class _EpgTreeItem(QTreeWidgetItem):
    """QTreeWidgetItem that sorts the Time column (col 0) by epoch timestamp."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col == 0:
            a = self.data(0, _SORT_ROLE) or 0.0
            b = other.data(0, _SORT_ROLE) or 0.0
            return a < b
        return super().__lt__(other)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_time(dt: datetime) -> str:
    """Convert UTC-naive EPG datetime to local time for display."""
    local = dt.replace(tzinfo=timezone.utc).astimezone()
    return local.strftime("%-I:%M %p").lstrip("0") or "12:00 AM"


def _minutes_away(dt: datetime) -> int:
    return max(0, int((dt - _now_utc()).total_seconds() / 60))


def _duration_str(start: datetime, stop: datetime) -> str:
    secs = max(0, int((stop - start).total_seconds()))
    mins = secs // 60
    if mins >= 60:
        return f"{mins // 60}h {mins % 60}m"
    return f"{mins}m"


def _remaining_str(stop: datetime) -> str:
    mins = max(0, int((stop - _now_utc()).total_seconds() / 60))
    if mins == 0:
        return "ending"
    if mins >= 60:
        return f"{mins // 60}h {mins % 60}m left"
    return f"{mins}m left"


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

    # Internal thread-safe signals
    _data_loaded = pyqtSignal(object)  # payload dict keyed by tab

    def __init__(self, config, db, epg_manager, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        self.db = db
        self.epg_manager = epg_manager
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="EpgView")
        self._provider_ids: list[str] = []
        self._channel_name_map: dict[str, str] = {}  # channel_db_id → name

        # Cached data for tabs
        self._on_now_programs: list[EpgProgramDB] = []
        self._browse_programs:  list[EpgProgramDB] = []
        self._watchlist_data:   dict[str, list[EpgProgramDB]] = {}
        self._live_data:        dict[str, list[EpgProgramDB]] = {}
        self._recommendations:  list[tuple[str, str, int]] = []

        self._setup_ui()
        self._data_loaded.connect(self._on_data_loaded)

        # Refresh On Now cards every 60 seconds while visible
        self._live_refresh_timer = QTimer(self)
        self._live_refresh_timer.setInterval(60_000)
        self._live_refresh_timer.timeout.connect(self._reload_on_now)

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
        self.tab_bar.addTab("📋 Watchlist")
        self.tab_bar.addTab("📺 On Now")
        self.tab_bar.addTab("📅 Browse")
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        header_layout.addWidget(self.tab_bar)
        header_layout.addStretch()

        # Search (only for Browse)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search programmes…")
        self.search_input.setFixedWidth(200)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setVisible(False)
        header_layout.addWidget(self.search_input)

        # Region filter
        header_layout.addWidget(QLabel("Region:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("All")
        self.lang_combo.setFixedWidth(72)
        self.lang_combo.setToolTip("Filter by channel region (country code suffix in EPG IDs)")
        self.lang_combo.currentIndexChanged.connect(self._on_lang_filter_changed)
        header_layout.addWidget(self.lang_combo)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        header_layout.addWidget(self.status_label)

        # Refresh button
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setToolTip("Refresh EPG data")
        self.refresh_btn.setFixedWidth(30)
        self.refresh_btn.clicked.connect(self._on_force_refresh)
        header_layout.addWidget(self.refresh_btn)

        root.addWidget(header_widget)

        # Thin separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #333;")
        root.addWidget(sep)

        # ── Stacked content area ────────────────────────────────────────
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self._build_watchlist_tab()
        self._build_on_now_tab()
        self._build_browse_tab()

    # ── Tab 0: Watchlist ───────────────────────────────────────────────

    def _build_watchlist_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # "MY WATCHLIST" header
        wl_header = QHBoxLayout()
        wl_title = QLabel("MY WATCHLIST")
        wl_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #aaa; letter-spacing: 1px;")
        wl_header.addWidget(wl_title)
        wl_header.addStretch()
        layout.addLayout(wl_header)

        # Always-visible add-keyword row
        hint = QLabel("Track a show or keyword — type it and press Enter to add it to your watchlist:")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)

        add_row = QHBoxLayout()
        self.add_pattern_input = QLineEdit()
        self.add_pattern_input.setPlaceholderText("e.g.  NHL  ·  Jeopardy  ·  MasterChef Canada")
        self.add_pattern_input.returnPressed.connect(self._on_add_pattern)
        add_row.addWidget(self.add_pattern_input, 1)
        self.add_btn = QPushButton("Track")
        self.add_btn.setFixedWidth(60)
        self.add_btn.clicked.connect(self._on_add_pattern)
        add_row.addWidget(self.add_btn)
        layout.addLayout(add_row)

        # Watchlist items (scrollable)
        self.watchlist_scroll = QScrollArea()
        self.watchlist_scroll.setWidgetResizable(True)
        self.watchlist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.watchlist_content = QWidget()
        self.watchlist_layout = QVBoxLayout(self.watchlist_content)
        self.watchlist_layout.setSpacing(4)
        self.watchlist_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.watchlist_scroll.setWidget(self.watchlist_content)
        layout.addWidget(self.watchlist_scroll, 3)

        # Empty state label
        self.wl_empty_label = QLabel("No watchlist items yet.\nAdd a show or keyword above to get started.")
        self.wl_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wl_empty_label.setStyleSheet("color: #666; font-size: 13px; padding: 20px;")

        # Separator before recommendations
        rec_sep = QFrame()
        rec_sep.setFrameShape(QFrame.Shape.HLine)
        rec_sep.setStyleSheet("border: none; border-top: 1px solid #333; margin-top: 8px;")
        layout.addWidget(rec_sep)

        # Recommendations
        rec_header = QHBoxLayout()
        rec_title = QLabel("RECOMMENDED FOR YOU")
        rec_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #aaa; letter-spacing: 1px;")
        rec_header.addWidget(rec_title)
        rec_header.addStretch()
        self.manage_dismissed_btn = QPushButton("manage dismissed")
        self.manage_dismissed_btn.setStyleSheet("color: #888; font-size: 11px; border: none; background: transparent;")
        self.manage_dismissed_btn.clicked.connect(self._manage_dismissed)
        rec_header.addWidget(self.manage_dismissed_btn)
        layout.addLayout(rec_header)

        self.rec_scroll = QScrollArea()
        self.rec_scroll.setWidgetResizable(True)
        self.rec_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rec_scroll.setMaximumHeight(200)
        self.rec_content = QWidget()
        self.rec_layout = QVBoxLayout(self.rec_content)
        self.rec_layout.setSpacing(4)
        self.rec_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rec_scroll.setWidget(self.rec_content)
        layout.addWidget(self.rec_scroll, 1)

        self.rec_empty_label = QLabel("Add watchlist items to get recommendations.")
        self.rec_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rec_empty_label.setStyleSheet("color: #555; font-size: 12px; padding: 10px;")

        self.stack.addWidget(page)

    # ── Tab 1: On Now ──────────────────────────────────────────────────

    def _build_on_now_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Filter row
        filter_row = QHBoxLayout()
        self.filler_check_btn = QPushButton("Hide Filler ✓")
        self.filler_check_btn.setCheckable(True)
        self.filler_check_btn.setChecked(True)
        self.filler_check_btn.setFixedWidth(100)
        self.filler_check_btn.clicked.connect(self._reload_on_now)
        filter_row.addWidget(QLabel("Airing right now — double-click to play:"))
        filter_row.addStretch()
        filter_row.addWidget(self.filler_check_btn)
        layout.addLayout(filter_row)

        # Programme tree: Channel | Show | Progress | Remaining
        self.on_now_list = QTreeWidget()
        self.on_now_list.setAlternatingRowColors(True)
        self.on_now_list.setRootIsDecorated(False)
        self.on_now_list.setUniformRowHeights(True)
        self.on_now_list.setSortingEnabled(True)
        self.on_now_list.setColumnCount(4)
        self.on_now_list.setHeaderLabels(["Channel", "Show", "Progress", "Remaining"])
        hdr = self.on_now_list.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.on_now_list.setColumnWidth(2, 140)
        self.on_now_list.itemDoubleClicked.connect(self._on_now_double_click)
        self.on_now_list.currentItemChanged.connect(self._on_now_selection_changed)
        layout.addWidget(self.on_now_list)

        self.on_now_stats = QLabel("")
        self.on_now_stats.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.on_now_stats)

        self.stack.addWidget(page)

    # ── Tab 2: Browse ──────────────────────────────────────────────────

    def _build_browse_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

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
        layout.addWidget(self.browse_list)

        self.browse_stats = QLabel("")
        self.browse_stats.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.browse_stats)

        self.stack.addWidget(page)

    # ------------------------------------------------------------------
    # ContentView interface
    # ------------------------------------------------------------------

    def get_view_name(self) -> str:
        return "EPG"

    def get_selected_channel(self) -> Optional[ChannelDB]:
        return None  # EPG doesn't track a single selected channel

    def on_activate(self) -> None:
        """Called when the EPG chip is clicked and view becomes visible."""
        self._load_provider_ids()
        self._update_status_label()

        # Default to Browse when watchlist is empty so the user sees content
        if not self.config.epg_watchlist_patterns and self.tab_bar.currentIndex() == 0:
            self.tab_bar.blockSignals(True)
            self.tab_bar.setCurrentIndex(2)
            self.tab_bar.blockSignals(False)
            self.stack.setCurrentIndex(2)

        self._reload_all()
        self.epg_manager.refresh_all_if_needed()
        self._live_refresh_timer.start()

    def on_deactivate(self) -> None:
        self._live_refresh_timer.stop()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_provider_ids(self) -> None:
        session = self.db.get_session()
        try:
            providers = session.query(ProviderDB).filter_by(is_active=True).all()
            self._provider_ids = [
                p.id for p in providers
                if getattr(p, "epg_url", "")
            ]
            self._populate_lang_filter(session)
        finally:
            session.close()

    def _populate_lang_filter(self, session) -> None:
        """Fill region dropdown from 2-letter country-code suffixes in EPG IDs.

        Samples up to 10k distinct channel IDs, counts suffix frequency,
        and shows the top 10 codes — keeps the dropdown short and relevant.
        """
        from collections import Counter
        from metatv.core.database import EpgProgramDB as EPG
        rows = (
            session.query(EPG.channel_epg_id)
            .filter(EPG.provider_id.in_(self._provider_ids))
            .distinct()
            .limit(10_000)
            .all()
        )
        counts: Counter = Counter()
        for (epg_id,) in rows:
            # Strict 2-letter suffix only — avoids .hdtv, .vod, etc.
            m = re.search(r"\.([a-z]{2})$", (epg_id or "").lower())
            if m:
                counts[m.group(1).upper()] += 1

        self.lang_combo.blockSignals(True)
        current = self.lang_combo.currentText()
        self.lang_combo.clear()
        self.lang_combo.addItem("All")
        for code, _ in counts.most_common(10):
            self.lang_combo.addItem(code)
        idx = self.lang_combo.findText(current)
        self.lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.lang_combo.blockSignals(False)

    def _reload_all(self) -> None:
        tab = self.tab_bar.currentIndex()
        if tab == 0:
            self._reload_watchlist()
        elif tab == 1:
            self._reload_on_now()
        elif tab == 2:
            self._reload_browse()

    def _reload_watchlist(self) -> None:
        patterns = self.config.epg_watchlist_patterns
        provider_ids = self._filtered_provider_ids()
        lang = self._current_lang_code()
        self._executor.submit(self._fetch_watchlist, patterns, provider_ids, lang)

    def _reload_on_now(self) -> None:
        provider_ids = self._filtered_provider_ids()
        hide_filler = self.filler_check_btn.isChecked()
        lang = self._current_lang_code()
        self._executor.submit(self._fetch_on_now, provider_ids, hide_filler, lang)

    def _reload_browse(self) -> None:
        provider_ids = self._filtered_provider_ids()
        target_date = self.date_combo.currentData()
        time_slot = self.time_combo.currentData()
        search = self.search_input.text().strip()
        hide_filler = self.hide_filler_btn.isChecked()
        lang = self._current_lang_code()
        self._executor.submit(
            self._fetch_browse, provider_ids, target_date, time_slot, search, hide_filler, lang
        )

    def _filtered_provider_ids(self) -> list[str]:
        return self._provider_ids

    def _current_lang_code(self) -> str:
        """Return selected 2-letter region code (lowercase), or '' for All."""
        text = self.lang_combo.currentText()
        return "" if text == "All" else text.lower()

    # ── Background workers ─────────────────────────────────────────────

    def _fetch_watchlist(self, patterns: list[str], provider_ids: list[str], lang_code: str = "") -> None:
        session = self.db.get_session()
        try:
            repo = EpgRepository(session)
            watchlist_data = repo.get_upcoming_for_watchlist(patterns, hours_ahead=48,
                                                              provider_ids=provider_ids,
                                                              lang_code=lang_code)
            live_data = repo.get_live_for_watchlist(patterns, provider_ids=provider_ids,
                                                     lang_code=lang_code)

            # Build dismissed set (expired entries are filtered out)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            dismissed = {
                cid for cid, ts_str in self.config.epg_dismissed_channels.items()
                if _parse_iso(ts_str) > now
            }

            recs = repo.get_recommendations(
                patterns=patterns,
                dismissed_ids=dismissed,
                provider_ids=provider_ids,
                limit=8,
            )

            # Build channel name map
            name_map = self._build_name_map(session, watchlist_data, live_data)
            self._channel_name_map.update(name_map)

            self._data_loaded.emit({
                "tab": "watchlist",
                "watchlist_data": watchlist_data,
                "live_data": live_data,
                "recommendations": recs,
                "dismissed": dismissed,
            })
        except Exception as e:
            logger.error(f"EpgView watchlist fetch error: {e}")
        finally:
            session.close()

    def _fetch_on_now(self, provider_ids: list[str], hide_filler: bool, lang_code: str = "") -> None:
        if not provider_ids:
            logger.warning("EpgView on-now: no EPG provider IDs — is EPG loaded?")
            self._data_loaded.emit({"tab": "on_now", "programs": []})
            return
        session = self.db.get_session()
        try:
            repo = EpgRepository(session)
            filler = self.config.epg_filler_patterns if hide_filler else []
            dismissed = self._dismissed_ids()
            programs = repo.get_current_programs(
                provider_ids=provider_ids,
                hide_filler=hide_filler,
                filler_patterns=filler,
                dismissed_channel_ids=dismissed,
                lang_code=lang_code,
            )
            logger.debug(f"EpgView on-now: {len(programs)} programmes from providers {provider_ids}")
            # Build name map
            name_map: dict[str, str] = {}
            for p in programs:
                if p.channel_db_id and p.channel_db_id not in name_map:
                    ch = session.query(ChannelDB).filter_by(id=p.channel_db_id).first()
                    if ch:
                        name_map[p.channel_db_id] = ch.name
            self._channel_name_map.update(name_map)

            self._data_loaded.emit({"tab": "on_now", "programs": programs})
        except Exception as e:
            logger.error(f"EpgView on-now fetch error: {e}")
            self._data_loaded.emit({"tab": "on_now", "programs": []})
        finally:
            session.close()

    def _fetch_browse(self, provider_ids: list[str], target_date: date,
                      time_slot: str, search: str, hide_filler: bool, lang_code: str = "") -> None:
        session = self.db.get_session()
        try:
            repo = EpgRepository(session)
            filler = self.config.epg_filler_patterns if hide_filler else []

            if search:
                programs = repo.search_programs(search, provider_ids, hours_ahead=168,
                                                lang_code=lang_code)
            else:
                programs = repo.get_schedule(
                    target_date=target_date,
                    provider_ids=provider_ids,
                    hide_filler=hide_filler,
                    filler_patterns=filler,
                    time_slot=time_slot,
                    lang_code=lang_code,
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
            )
        elif tab == "on_now":
            self._render_on_now(payload["programs"])
        elif tab == "browse":
            self._render_browse(payload["programs"])

    # ── Watchlist render ───────────────────────────────────────────────

    def _render_watchlist(self, watchlist_data: dict, live_data: dict,
                          recommendations: list, dismissed: set) -> None:
        # Clear existing watchlist widgets (never delete the sentinel labels)
        while self.watchlist_layout.count():
            child = self.watchlist_layout.takeAt(0)
            w = child.widget()
            if w and w is not self.wl_empty_label:
                w.deleteLater()

        patterns = self.config.epg_watchlist_patterns

        if not patterns:
            self.watchlist_layout.addWidget(self.wl_empty_label)
        else:
            for pattern in patterns:
                live_progs = live_data.get(pattern, [])
                upcoming   = watchlist_data.get(pattern, [])
                self.watchlist_layout.addWidget(
                    self._make_watchlist_item(pattern, live_progs, upcoming[:3])
                )

        # Recommendations
        while self.rec_layout.count():
            child = self.rec_layout.takeAt(0)
            w = child.widget()
            if w and w is not self.rec_empty_label:
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
        w = QWidget()
        w.setStyleSheet("QWidget { background: rgba(255,255,255,0.03); border-radius: 6px; }")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        # Header row
        header = QHBoxLayout()
        is_live_now = bool(live)
        icon = "🔴" if is_live_now else "⏰"
        title_lbl = QLabel(f"{icon}  {pattern}")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(title_lbl)
        header.addStretch()

        if is_live_now:
            prog = live[0]
            ch_name = self._channel_name_map.get(prog.channel_db_id or "", prog.channel_epg_id)
            play_btn = QPushButton("▶ Play")
            play_btn.setFixedWidth(70)
            play_btn.setStyleSheet("background: #2a6; color: white; border-radius: 3px; padding: 2px 6px;")
            play_btn.clicked.connect(lambda _=False, cid=prog.channel_db_id: self._play_channel(cid))
            live_lbl = QLabel(f"ON NOW → {ch_name}")
            live_lbl.setStyleSheet("color: #4a4; font-size: 12px;")
            header.addWidget(live_lbl)
            header.addWidget(play_btn)

        remove_btn = QPushButton("×")
        remove_btn.setFixedWidth(24)
        remove_btn.setToolTip(f"Remove '{pattern}' from watchlist")
        remove_btn.setStyleSheet("color: #666; border: none; background: transparent; font-size: 14px;")
        remove_btn.clicked.connect(lambda _=False, p=pattern: self._remove_pattern(p))
        header.addWidget(remove_btn)
        layout.addLayout(header)

        # Upcoming airings (up to 3)
        shown = live[:1] + upcoming  # live entry first if present
        for prog in shown[:3]:
            ch_name = self._channel_name_map.get(prog.channel_db_id or "", prog.channel_epg_id)
            now = _now_utc()
            if prog.start_time <= now:
                time_str = f"{_remaining_str(prog.stop_time)}"
                prefix = "  ▶ "
            else:
                mins = _minutes_away(prog.start_time)
                if mins < 120:
                    time_str = f"in {mins} min"
                elif prog.start_time.date() == date.today():
                    time_str = f"Today {_format_time(prog.start_time)}"
                else:
                    time_str = f"{prog.start_time.strftime('%a')} {_format_time(prog.start_time)}"
                prefix = "  "

            row_lbl = QLabel(f"{prefix}{time_str}  ·  {ch_name}")
            row_lbl.setStyleSheet("color: #999; font-size: 11px; padding-left: 16px;")
            layout.addWidget(row_lbl)

        return w

    def _make_recommendation_item(self, channel_db_id: str, channel_name: str, count: int) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        name_lbl = QLabel(f"{channel_name}")
        name_lbl.setStyleSheet("font-size: 12px;")
        count_lbl = QLabel(f"{count} matches")
        count_lbl.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(name_lbl)
        layout.addWidget(count_lbl)
        layout.addStretch()

        watch_btn = QPushButton("+ Watch")
        watch_btn.setFixedWidth(70)
        watch_btn.setStyleSheet("color: #4af; border: 1px solid #4af; border-radius: 3px; padding: 1px 4px; font-size: 11px;")
        watch_btn.setToolTip(f"Add '{channel_name}' to watchlist")
        watch_btn.clicked.connect(lambda _=False, n=channel_name: self._add_pattern(n))
        layout.addWidget(watch_btn)

        skip_btn = QPushButton("× skip")
        skip_btn.setFixedWidth(55)
        skip_btn.setStyleSheet("color: #666; border: none; background: transparent; font-size: 11px;")
        skip_btn.setToolTip("Dismiss this recommendation for 7 days")
        skip_btn.clicked.connect(lambda _=False, cid=channel_db_id: self._dismiss_channel(cid))
        layout.addWidget(skip_btn)

        return w

    # ── On Now render ──────────────────────────────────────────────────

    def _render_on_now(self, programs: list[EpgProgramDB]) -> None:
        self.on_now_list.setSortingEnabled(False)
        self.on_now_list.clear()
        patterns = [p.lower() for p in self.config.epg_watchlist_patterns]

        for prog in programs:
            ch_name = self._channel_name_map.get(prog.channel_db_id or "", prog.channel_epg_id)
            progress = _progress_bar(prog.start_time, prog.stop_time, 16)
            remaining = _remaining_str(prog.stop_time)
            title = prog.title
            if prog.is_live:
                title += " ᴸᶦᵛᵉ"
            if prog.is_new:
                title += " ᴺᵉʷ"

            item = _EpgTreeItem([ch_name, title, progress, remaining])
            item.setData(0, Qt.ItemDataRole.UserRole, prog.channel_db_id)
            item.setData(0, _SORT_ROLE, prog.start_time.timestamp())

            if any(pat in prog.title.lower() for pat in patterns):
                for col in range(4):
                    item.setForeground(col, QColor("#4af"))
                font = item.font(1)
                font.setBold(True)
                item.setFont(1, font)

            self.on_now_list.addTopLevelItem(item)

        self.on_now_list.setSortingEnabled(True)
        count = len(programs)
        self.on_now_stats.setText(f"{count:,} channels on now")
        self.status_message.emit(f"EPG: {count:,} on now")

    # ── Browse render ──────────────────────────────────────────────────

    def _render_browse(self, programs: list[EpgProgramDB]) -> None:
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
        self.search_input.setVisible(index == 2)
        self._reload_all()

    def _on_search_changed(self, _: str) -> None:
        self._reload_browse()

    def _on_lang_filter_changed(self, _: int) -> None:
        self._reload_all()

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

    def _on_add_pattern(self) -> None:
        pattern = self.add_pattern_input.text().strip()
        if pattern and pattern not in self.config.epg_watchlist_patterns:
            self.config.epg_watchlist_patterns.append(pattern)
            self.config.save()
        self.add_pattern_input.clear()
        self._reload_watchlist()

    def _add_pattern(self, pattern: str) -> None:
        if pattern and pattern not in self.config.epg_watchlist_patterns:
            self.config.epg_watchlist_patterns.append(pattern)
            self.config.save()
            self._reload_watchlist()

    def _remove_pattern(self, pattern: str) -> None:
        if pattern in self.config.epg_watchlist_patterns:
            self.config.epg_watchlist_patterns.remove(pattern)
            self.config.save()
            self._reload_watchlist()

    def _dismiss_channel(self, channel_db_id: str) -> None:
        dismiss_until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        self.config.epg_dismissed_channels[channel_db_id] = dismiss_until
        self.config.save()
        self._reload_watchlist()

    def _dismissed_ids(self) -> set[str]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
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

        now = datetime.now(timezone.utc).replace(tzinfo=None)
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
