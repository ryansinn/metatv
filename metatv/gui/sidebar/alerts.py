"""WatchAlertsSection and its _AlertRow helper widget."""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QAbstractScrollArea, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from loguru import logger

from metatv.core.epg_utils import now_utc as _now_utc, is_local_today as _is_local_today, to_local as _to_local
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection, _fmt_channel_name


class _AlertRow(QWidget):
    """Channel row widget for Watch Alerts: name + right-aligned time + hover play button."""

    play_clicked = pyqtSignal()
    row_clicked  = pyqtSignal()  # single click anywhere except the play button

    def __init__(self, ch_name: str, time_str: str, config, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)

        name_lbl = QLabel(ch_name)
        layout.addWidget(name_lbl, 1)

        self.time_lbl = QLabel(time_str)
        self.time_lbl.setStyleSheet(_theme.CHANNEL_NAME_DIM)
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.time_lbl)

        self.play_btn = QPushButton(config.play_icon)
        self.play_btn.setFixedSize(20, 18)
        self.play_btn.setFlat(True)
        self.play_btn.setToolTip("Play")
        self.play_btn.setStyleSheet(_theme.PLAY_BTN_SMALL)
        self.play_btn.clicked.connect(self.play_clicked)
        self.play_btn.hide()
        layout.addWidget(self.play_btn)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        # row_clicked fires only when clicking outside the play button area
        self.row_clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.play_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.play_btn.hide()
        super().leaveEvent(event)


class WatchAlertsSection(BackgroundRefreshMixin, CollapsibleSection):
    """Alerts section — EPG watch alerts + VOD watch-for rules + stream retry monitoring."""

    alertClicked    = pyqtSignal(str)        # channel_db_id — play (double-click or play button)
    channel_selected = pyqtSignal(str)      # channel_db_id — single click → load details pane
    channelContextMenuRequested = pyqtSignal(str, int, int) # channel_db_id, global_x, global_y
    retryRemoveRequested = pyqtSignal(str)                  # entry_id
    retryClearAllRequested = pyqtSignal()
    retryPlayRequested = pyqtSignal(str, str, str)            # channel_id, stream_url, channel_name
    retryContextMenuRequested = pyqtSignal(str, str, int, int)  # entry_id, channel_id, x, y
    # VOD watch-for signals
    addWatchForClicked = pyqtSignal()        # "+" button → open "Watch for…" dialog
    manageWatchForClicked = pyqtSignal()     # "Manage…" link → open manage dialog
    vodAlertClicked = pyqtSignal(str)        # channel_db_id — play matched content
    _data_ready = pyqtSignal(object)         # dict | None (None = load failure)

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Alerts", _icons.alert_icon, config, parent)
        self._init_background_refresh()

    def get_section_id(self):
        return "alerts"

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
            f'<span style="color:{_theme.COLOR_WARN}">{self.icon}</span> <b>{self.title}</b>'
        )
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        hl.addWidget(self.title_label)
        hl.addStretch()

        _btn_style = (
            "QPushButton {{ font-size: {fs}; border: 1px solid {c};"
            " border-radius: 3px; color: {c}; background: {bg}; }}"
            "QPushButton:hover {{ background: {hbg}; }}"
        )
        add_btn = QPushButton("+")
        add_btn.setFixedSize(22, 20)
        add_btn.setToolTip("Watch for new content…")
        add_btn.setStyleSheet(_btn_style.format(
            fs=_theme.FONT_LG,
            c=_theme.COLOR_DIM,
            bg=_theme.OVERLAY_05,
            hbg=_theme.OVERLAY_15,
        ))
        add_btn.clicked.connect(self.addWatchForClicked.emit)
        hl.addWidget(add_btn)

        self.main_layout.addWidget(header)

    def create_content(self):
        from PyQt6.QtWidgets import QHeaderView
        self.alerts_tree = QTreeWidget()
        self.alerts_tree.setHeaderHidden(True)
        self.alerts_tree.setColumnCount(1)
        self.alerts_tree.setIndentation(12)
        self.alerts_tree.header().setStretchLastSection(True)
        self.alerts_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.alerts_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.alerts_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.alerts_tree.customContextMenuRequested.connect(self._on_context_menu)
        self.content_layout.addWidget(self.alerts_tree)

        # ── VOD Watch-For sub-section ──────────────────────────────────────
        self._vod_collapsed = False

        vod_hdr_row = QHBoxLayout()
        vod_hdr_row.setContentsMargins(0, 4, 0, 2)
        vod_hdr_row.setSpacing(4)

        self._vod_toggle = QPushButton()
        self._vod_toggle.setFlat(True)
        self._vod_toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._vod_toggle.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD}; font-weight: bold;"
            " border: none; text-align: left; padding: 0 2px; }"
            f"QPushButton:hover {{ color: {_theme.COLOR_DIM}; }}"
        )
        self._vod_toggle.clicked.connect(self._toggle_vod_watching)
        vod_hdr_row.addWidget(self._vod_toggle)
        vod_hdr_row.addStretch()

        self._vod_manage_btn = QPushButton("Manage…")
        self._vod_manage_btn.setFlat(True)
        self._vod_manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._vod_manage_btn.setToolTip("View and remove watch-for rules")
        self._vod_manage_btn.setStyleSheet(
            f"QPushButton {{ font-size: {_theme.FONT_SM}; color: {_theme.COLOR_ACCENT_BLUE};"
            f" border: none; padding: 0 2px; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_BLUE_2}; }}"
        )
        self._vod_manage_btn.clicked.connect(self.manageWatchForClicked.emit)
        vod_hdr_row.addWidget(self._vod_manage_btn)

        self._vod_hdr_container = QWidget()
        self._vod_hdr_container.setLayout(vod_hdr_row)
        self._vod_hdr_container.hide()
        self.content_layout.addWidget(self._vod_hdr_container)

        self._vod_list = QListWidget()
        self._vod_list.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self._vod_list.setMaximumHeight(150)
        self._vod_list.setStyleSheet(f"QListWidget {{ font-size: {_theme.FONT_MD}; }}")
        self._vod_list.itemDoubleClicked.connect(self._on_vod_item_double_clicked)
        self._vod_list.hide()
        self.content_layout.addWidget(self._vod_list)

        self._update_vod_toggle_label(0)
        # ── end VOD Watch-For sub-section ─────────────────────────────────

        # Stream Monitoring collapsible sub-section
        self._retry_collapsed = False

        retry_hdr_row = QHBoxLayout()
        retry_hdr_row.setContentsMargins(0, 4, 0, 2)
        retry_hdr_row.setSpacing(4)

        self._retry_toggle = QPushButton()
        self._retry_toggle.setFlat(True)
        self._retry_toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._retry_toggle.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD}; font-weight: bold;"
            " border: none; text-align: left; padding: 0 2px; }"
            f"QPushButton:hover {{ color: {_theme.COLOR_DIM}; }}"
        )
        self._retry_toggle.clicked.connect(self._toggle_stream_monitoring)
        retry_hdr_row.addWidget(self._retry_toggle)

        _info_lbl = QLabel(self.config.info_icon)
        _info_lbl.setStyleSheet(f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_MD};")
        _info_lbl.setToolTip(
            "Stream Monitoring periodically re-checks streams that previously\n"
            "failed to play. When a stream becomes available again you'll\n"
            "receive a notification. Double-click an entry to retry immediately."
        )
        retry_hdr_row.addWidget(_info_lbl)
        retry_hdr_row.addStretch()

        self._retry_hdr_container = QWidget()
        self._retry_hdr_container.setLayout(retry_hdr_row)
        self._retry_hdr_container.hide()
        self.content_layout.addWidget(self._retry_hdr_container)

        self._retry_list = QListWidget()
        self._retry_list.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self._retry_list.setMaximumHeight(120)
        self._retry_list.setStyleSheet(f"QListWidget {{ font-size: {_theme.FONT_MD}; }}")
        self._retry_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._retry_list.customContextMenuRequested.connect(self._on_retry_context_menu)
        self._retry_list.itemDoubleClicked.connect(self._on_retry_double_clicked)
        self._retry_list.hide()
        self.content_layout.addWidget(self._retry_list)

        self._update_retry_toggle_label(0)
        self.set_empty(True)

    # ------------------------------------------------------------------
    # VOD Watch-For helpers
    # ------------------------------------------------------------------

    def _update_vod_toggle_label(self, count: int) -> None:
        arrow = self.config.expand_icon if self._vod_collapsed else self.config.collapse_icon
        label = f"Watching for  ({count})" if count else "Watching for"
        self._vod_toggle.setText(f"{arrow}  {label}")

    def _toggle_vod_watching(self) -> None:
        self._vod_collapsed = not self._vod_collapsed
        if self._vod_collapsed:
            self._vod_list.hide()
        else:
            self._vod_list.show()
        self._update_vod_toggle_label(self._vod_list.count())

    def refresh_vod_rules(self) -> None:
        """Repopulate the VOD watch-for sub-list from config rules.

        Reads ``config.get_vod_watch_alerts()`` synchronously (config is
        in-memory), then for each rule fetches matching channel names from the
        DB to show a per-rule match count.  Called on startup, after a rule is
        added/removed, and after ``VodWatchAlertManager.new_matches_found``.
        """
        rules = getattr(self.config, "get_vod_watch_alerts", lambda: [])()
        self._vod_list.clear()

        if not rules:
            self._vod_hdr_container.hide()
            self._vod_list.hide()
            return

        # Build a channel-id → rule mapping for match count display.
        # We query alerted_ids from config (already stored) — no DB needed here.
        from metatv.gui import icons as _icons  # local import avoids circular at top

        type_icons = {"movie": _icons.movie_icon, "series": _icons.series_icon}

        for rule in rules:
            text = rule.get("text") or "?"
            match_type = rule.get("match_type", "any")
            alerted_ids = rule.get("alerted_ids") or []
            count = len(alerted_ids)

            type_icon = type_icons.get(match_type, "")
            type_suffix = f"  ({match_type})" if match_type != "any" else ""
            count_badge = f"  · {count}" if count > 0 else ""
            label = f"{type_icon}{_icons.alert_icon} {text}{type_suffix}{count_badge}"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, rule.get("created", ""))
            count_tip = f"{count} match{'es' if count != 1 else ''} found" if count else "No matches yet"
            item.setToolTip(
                f"Watching for: {text}\nType: {match_type}\n{count_tip}"
            )
            if count == 0:
                from PyQt6.QtGui import QColor
                item.setForeground(QColor(_theme.COLOR_MUTED))
            self._vod_list.addItem(item)

        count = self._vod_list.count()
        self._update_vod_toggle_label(count)
        self._vod_hdr_container.show()
        if not self._vod_collapsed:
            self._vod_list.show()

    def _on_vod_item_double_clicked(self, item: "QListWidgetItem") -> None:
        """Double-clicking a rule row opens the manage dialog."""
        self.manageWatchForClicked.emit()

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    def _update_retry_toggle_label(self, count: int) -> None:
        arrow = self.config.expand_icon if self._retry_collapsed else self.config.collapse_icon
        label = f"Stream Monitoring  ({count})" if count else "Stream Monitoring"
        self._retry_toggle.setText(f"{arrow}  {label}")

    def _toggle_stream_monitoring(self) -> None:
        self._retry_collapsed = not self._retry_collapsed
        if self._retry_collapsed:
            self._retry_list.hide()
        else:
            self._retry_list.show()
        self._update_retry_toggle_label(self._retry_list.count())

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        # child (airing) rows under a group header, or direct single-channel items
        if item.parent() or item.childCount() == 0:
            channel_db_id = item.data(0, Qt.ItemDataRole.UserRole)
            if channel_db_id:
                self.alertClicked.emit(channel_db_id)

    def _on_context_menu(self, pos) -> None:
        item = self.alerts_tree.itemAt(pos)
        if not item or not item.parent():  # skip headers
            return
        channel_db_id = item.data(0, Qt.ItemDataRole.UserRole)
        if channel_db_id:
            gp = self.alerts_tree.viewport().mapToGlobal(pos)
            self.channelContextMenuRequested.emit(channel_db_id, gp.x(), gp.y())

    # ------------------------------------------------------------------
    # BackgroundRefreshMixin hooks
    # ------------------------------------------------------------------

    def _refresh_list(self) -> QTreeWidget:
        return self.alerts_tree

    def _load_error_message(self) -> str:
        return "Couldn't load watch alerts"

    def _loading_message(self) -> str:
        return "Loading alerts…"

    def show_load_error(self, tree, message: str) -> None:
        """Override for QTreeWidget: render a non-selectable error row.

        The base CollapsibleSection.show_load_error uses QListWidgetItem + addItem,
        which does not exist on QTreeWidget and would crash. This override adds a
        top-level QTreeWidgetItem instead.
        """
        tree.clear()
        item = QTreeWidgetItem([f"{_icons.notification_warning_icon} {message}"])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        tree.addTopLevelItem(item)
        self.set_empty(False)

    def show_loading(self, tree, message: str = "Loading…") -> None:
        """Override for QTreeWidget: render a transient, non-selectable loading row.

        The base CollapsibleSection.show_loading uses QListWidgetItem + addItem,
        which does not exist on QTreeWidget. Mirrors the QTreeWidget show_load_error
        override but uses icons.loading_icon.
        """
        tree.clear()
        item = QTreeWidgetItem([f"{_icons.loading_icon} {message}"])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        tree.addTopLevelItem(item)
        self.set_empty(False)

    def _load_rows(self) -> dict:
        """Worker thread — NO widget access.

        Returns a plain dict with keys 'live_groups' and 'upcoming_only'
        (never None for valid-empty; None is reserved for real exceptions
        and emitted only by the mixin's try/except wrapper).
        """
        from metatv.core.repositories.epg import EpgRepository
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.database import ChannelDB

        _empty: dict = {"live_groups": {}, "upcoming_only": {}}

        patterns = self.config.epg_watchlist_patterns
        if not patterns:
            return _empty

        with self.db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            provider_ids = repos.providers.get_epg_active_provider_ids()
            if not provider_ids:
                return _empty

            excluded_ch_provider_ids = set(repos.providers.get_hidden_provider_ids())

            repo = EpgRepository(session)
            live_data     = repo.get_live_for_watchlist(
                patterns, provider_ids=provider_ids,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )
            upcoming_data = repo.get_upcoming_for_watchlist(
                patterns, hours_ahead=24, provider_ids=provider_ids,
                excluded_channel_provider_ids=excluded_ch_provider_ids,
            )

            # Batch channel-name lookup — one IN query instead of N per-programme queries.
            all_channel_ids: set[str] = set()
            for progs in live_data.values():
                for prog in progs:
                    if prog.channel_db_id:
                        all_channel_ids.add(prog.channel_db_id)
            for progs in upcoming_data.values():
                for prog in progs:
                    if prog.channel_db_id:
                        all_channel_ids.add(prog.channel_db_id)

            channel_names: dict[str, str] = {}
            if all_channel_ids:
                rows = (
                    session.query(ChannelDB.id, ChannelDB.name)
                    .filter(ChannelDB.id.in_(all_channel_ids))
                    .all()
                )
                channel_names = {cid: name for cid, name in rows}

            now = _now_utc()

            def _title_key(title: str) -> str:
                return " ".join(title.casefold().replace("&", "and").split())

            def _channel_display(prog) -> str:
                raw_name = channel_names.get(prog.channel_db_id) or (prog.channel_epg_id or "Unknown")
                return _fmt_channel_name(raw_name)

            # Unified per-title groups — upcoming for a live title folds under WATCH NOW,
            # preventing the same show from appearing in both sections simultaneously.
            # live_groups: key -> {'live': [...], 'upcoming': [...], 'title': str}
            # upcoming_only: key -> {'airings': [...], 'title': str}
            live_groups: dict[str, dict] = {}
            upcoming_only: dict[str, dict] = {}

            for _pattern, progs in live_data.items():
                for prog in progs:
                    ch_display = _channel_display(prog)
                    mins_left = max(0, int((prog.stop_time - now).total_seconds() / 60))
                    time_str = f"{mins_left}m left" if mins_left >= 1 else "ending"
                    key = _title_key(prog.title)
                    if key not in live_groups:
                        live_groups[key] = {'live': [], 'upcoming': [], 'title': prog.title}
                    live_groups[key]['live'].append(
                        (mins_left, time_str, ch_display, prog.channel_db_id)
                    )

            for _pattern, progs in upcoming_data.items():
                for prog in progs:
                    ch_display = _channel_display(prog)
                    mins = int((prog.start_time - now).total_seconds() / 60)
                    if mins < 60:
                        time_str = f"in {mins}m"
                    elif _is_local_today(prog.start_time):
                        time_str = _to_local(prog.start_time).strftime("%-I:%M %p")
                    else:
                        time_str = _to_local(prog.start_time).strftime("%a %-I:%M %p")
                    key = _title_key(prog.title)
                    ts = prog.start_time.timestamp()
                    if key in live_groups:
                        live_groups[key]['upcoming'].append(
                            (ts, time_str, ch_display, prog.channel_db_id)
                        )
                    else:
                        if key not in upcoming_only:
                            upcoming_only[key] = {'airings': [], 'title': prog.title}
                        upcoming_only[key]['airings'].append(
                            (ts, time_str, ch_display, prog.channel_db_id)
                        )

        return {"live_groups": live_groups, "upcoming_only": upcoming_only}

    def _populate_rows(self, data: dict) -> None:
        """Main thread: rebuild the alerts_tree from pre-computed plain data.

        'data' is the dict returned by _load_rows (never None here — None is
        handled by the mixin which calls show_load_error instead).
        """
        live_groups   = data["live_groups"]
        upcoming_only = data["upcoming_only"]

        if not live_groups and not upcoming_only:
            self.set_empty(True)
            return

        def _section_hdr(text: str) -> None:
            item = QTreeWidgetItem([text])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(0, QColor(_theme.COLOR_FAINT))
            f = item.font(0)
            f.setPointSize(9)
            f.setBold(True)
            item.setFont(0, f)
            self.alerts_tree.addTopLevelItem(item)

        def _wire_row(row: _AlertRow, channel_db_id: str) -> None:
            """Connect an _AlertRow's signals to the section's public signals."""
            row.play_clicked.connect(
                lambda _=False, cid=channel_db_id: self.alertClicked.emit(cid)
            )
            row.row_clicked.connect(
                lambda cid=channel_db_id: self.channel_selected.emit(cid)
            )

        def _add_child(parent_item, ch_name, time_str, channel_db_id, title) -> None:
            child = QTreeWidgetItem()
            child.setData(0, Qt.ItemDataRole.UserRole, channel_db_id)
            child.setToolTip(0, f"{title}\n{ch_name}")
            parent_item.addChild(child)
            row = _AlertRow(ch_name, time_str, self.config)
            _wire_row(row, channel_db_id)
            self.alerts_tree.setItemWidget(child, 0, row)

        def _add_direct(ch_name, time_str, channel_db_id, title) -> None:
            """Single-channel item: header IS the row — no expand arrow.
            Shows the show title; channel name is the tooltip."""
            item = QTreeWidgetItem()
            item.setData(0, Qt.ItemDataRole.UserRole, channel_db_id)
            item.setToolTip(0, ch_name)
            self.alerts_tree.addTopLevelItem(item)
            row = _AlertRow(title, time_str, self.config)
            _wire_row(row, channel_db_id)
            self.alerts_tree.setItemWidget(item, 0, row)

        if live_groups:
            _section_hdr("WATCH NOW")
            for key, grp in sorted(live_groups.items(),
                                   key=lambda kv: min(a[0] for a in kv[1]['live'])):
                title = grp['title']
                live_items = sorted(grp['live'], key=lambda a: a[0])
                up_items   = sorted(grp['upcoming'], key=lambda a: a[0])
                all_items  = live_items + up_items
                if len(all_items) == 1:
                    a = all_items[0]
                    _add_direct(a[2], a[1], a[3], title)
                else:
                    rep_time = live_items[0][1]
                    count_badge = f"  +{len(all_items) - 1}"
                    hdr = QTreeWidgetItem([f"{title}  ·  {rep_time}{count_badge}"])
                    hdr.setFlags(hdr.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    self.alerts_tree.addTopLevelItem(hdr)
                    for a in live_items[:10]:
                        _add_child(hdr, a[2], a[1], a[3], title)
                    for a in up_items[:5]:
                        _add_child(hdr, a[2], a[1], a[3], title)

        if upcoming_only:
            _section_hdr("UPCOMING")
            for key, grp in sorted(upcoming_only.items(),
                                   key=lambda kv: min(a[0] for a in kv[1]['airings'])):
                title = grp['title']
                airings = sorted(grp['airings'], key=lambda a: a[0])
                if len(airings) == 1:
                    a = airings[0]
                    _add_direct(a[2], a[1], a[3], title)
                else:
                    rep_time = airings[0][1]
                    count_badge = f"  +{len(airings) - 1}"
                    hdr = QTreeWidgetItem([f"{title}  ·  {rep_time}{count_badge}"])
                    hdr.setFlags(hdr.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    self.alerts_tree.addTopLevelItem(hdr)
                    for a in airings[:10]:
                        _add_child(hdr, a[2], a[1], a[3], title)

        self.set_empty(False)
        QTimer.singleShot(0, self._apply_expansion)

    def refresh_retry(self, entries: list) -> None:
        """Populate the stream retry sub-list from StreamRetryDB entries."""
        self._retry_list.clear()
        if not entries:
            self._retry_hdr_container.hide()
            self._retry_list.hide()
            return

        from datetime import datetime, timezone
        now = datetime.utcnow()

        for entry in entries:
            icon = _icons.stream_retry_online_icon if entry.status == "online" \
                else _icons.stream_retry_pending_icon
            item = QListWidgetItem(f"{icon}  {entry.channel_name}")
            item.setData(Qt.ItemDataRole.UserRole,     entry.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, entry.channel_id)
            item.setData(Qt.ItemDataRole.UserRole + 2, entry.stream_url)
            item.setData(Qt.ItemDataRole.UserRole + 3, entry.channel_name)

            # Tooltip
            attempts = entry.attempt_count or 0
            error_line = f"Error: {entry.last_error}" if entry.last_error else "No error detail"
            if entry.next_check_at and entry.status == "pending":
                delta = entry.next_check_at - now
                secs = max(0, int(delta.total_seconds()))
                if secs < 3600:
                    next_check = f"{secs // 60}m"
                else:
                    next_check = f"{secs // 3600}h {(secs % 3600) // 60}m"
                timing = f"Next check in {next_check}"
            else:
                timing = "Back online!" if entry.status == "online" else ""

            item.setToolTip(
                f"{entry.channel_name}\n{error_line}\nAttempts: {attempts}\n{timing}"
            )
            self._retry_list.addItem(item)

        count = self._retry_list.count()
        self._update_retry_toggle_label(count)
        self._retry_hdr_container.show()
        if not self._retry_collapsed:
            self._retry_list.show()

    def _on_retry_double_clicked(self, item: "QListWidgetItem") -> None:
        channel_id   = item.data(Qt.ItemDataRole.UserRole + 1)
        stream_url   = item.data(Qt.ItemDataRole.UserRole + 2)
        channel_name = item.data(Qt.ItemDataRole.UserRole + 3) or ""
        if channel_id and stream_url:
            self.retryPlayRequested.emit(channel_id, stream_url, channel_name)

    def _on_retry_context_menu(self, pos) -> None:
        item = self._retry_list.itemAt(pos)
        if not item:
            return
        entry_id   = item.data(Qt.ItemDataRole.UserRole)
        channel_id = item.data(Qt.ItemDataRole.UserRole + 1)
        gp = self._retry_list.viewport().mapToGlobal(pos)
        self.retryContextMenuRequested.emit(entry_id, channel_id or "", gp.x(), gp.y())

    def _apply_expansion(self) -> None:
        """Expand all items if they all fit in the visible tree height; otherwise expand none."""
        tree = self.alerts_tree
        n = tree.topLevelItemCount()
        if n == 0:
            return
        row_h = tree.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 22
        visible_h = tree.viewport().height()
        if visible_h <= 0:
            visible_h = tree.height()
        if visible_h <= 0:
            return
        max_rows = visible_h // row_h
        total_if_expanded = sum(
            1 + tree.topLevelItem(i).childCount()
            for i in range(n)
        )
        expand_all = total_if_expanded <= max_rows
        for i in range(n):
            item = tree.topLevelItem(i)
            if item.childCount() == 0:
                continue  # section header — not expandable
            item.setExpanded(expand_all)
