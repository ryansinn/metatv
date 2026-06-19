"""Mixin for the EPG View's Events tab (Band 10 B10-4 file split).

``_EpgEventsMixin`` is a plain Python mixin — it does NOT inherit from QWidget.
It is mixed into ``EpgView`` via multiple inheritance and accesses all shared
instance state through ``self`` at runtime (MRO resolution).

Also exports the three module-level pure-function helpers that the Events tab
owns:

    * ``_classify_event``
    * ``group_events_timeline``
    * ``group_events_by_network``
    * ``LIVE_EVENT_WINDOW``

These are imported back into ``metatv.gui.epg_view`` for backwards compatibility
(tests import them from the original module).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from loguru import logger

from metatv.core.epg_utils import (
    now_utc as _now_utc,
    is_local_today as _is_local_today,
    local_weekday as _local_weekday,
    to_local as _to_local,
)
from metatv.gui import theme as _theme

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


# ---------------------------------------------------------------------------
# Mixin class
# ---------------------------------------------------------------------------

class _EpgEventsMixin:
    """Mixin providing the Events tab for ``EpgView``.

    All methods access shared ``EpgView`` state through ``self`` — no
    parameters are rewired.  Do not inherit from QWidget here.
    """

    # ------------------------------------------------------------------
    # Events tab — build
    # ------------------------------------------------------------------

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
