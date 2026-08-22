"""EPG View — watchlist-first electronic programme guide.

Three tabs:
  Watchlist  — Your tracked shows + recommendations
  On Now     — What's airing right now across all matched channels
  Browse     — Time-sorted schedule with date/time/search filtering
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from metatv.core.channel_name_utils import parse_channel_name
from metatv.core.database import ChannelDB, EpgProgramDB, ProviderDB
from metatv.core.repositories.dtos import LiveEventDTO
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
    epg_is_stale as _epg_is_stale,
    fmt_duration as _duration_str,
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
from metatv.gui.epg_on_now_mixin import _EpgOnNowMixin
from metatv.gui.epg_watchlist_mixin import _EpgWatchlistMixin


def epg_empty_state(readiness: dict, programme_count: int) -> tuple[str, str]:
    """Explain WHY the guide is empty, and what to do about it.

    ``get_epg_active_provider_ids()`` returning nothing collapsed four very
    different situations into one flat "No EPG sources" (task #17): a user with
    no sources at all, one whose sources carry no guide URL, one who switched
    EPG off, and one who is fully configured but hasn't fetched yet. Only the
    last is a "press Refresh" situation; the others need different actions, and
    two of them aren't problems at all.

    Pure so the wording is testable without a database or a Qt view.

    Args:
        readiness: ``ProviderRepository.get_epg_readiness()`` output.
        programme_count: Rows currently stored in the EPG table.

    Returns:
        ``(headline, hint)``. Both are ``""`` when the guide has data and there
        is nothing to explain. The EPG chip stays enabled in every case (owner
        call) — this is an explanation, never a reason to disable navigation.
    """
    total = readiness.get("total", 0)
    with_url = readiness.get("with_url", 0)
    enabled = readiness.get("enabled", 0)
    eligible = readiness.get("eligible", 0)

    if programme_count > 0:
        return "", ""
    if total == 0:
        return (
            "No sources yet",
            "Add a source and the guide will fill in from it.",
        )
    if eligible == 0 and enabled == 0:
        return (
            "TV guide is turned off",
            "Turn it on per source in Sources → pick a source → EPG.",
        )
    if eligible == 0 and with_url == 0:
        return (
            "No guide available from your sources",
            "None of your sources published a guide URL. You can supply your "
            "own XMLTV URL in Sources → pick a source → EPG.",
        )
    if eligible == 0:
        return (
            "TV guide is not set up",
            "Check Sources → pick a source → EPG — it needs both a guide URL "
            "and the EPG switch turned on.",
        )
    return (
        "Guide not downloaded yet",
        "Your sources are ready — use Refresh Guide to fetch the listings.",
    )


class EpgView(_EpgWatchlistMixin, _EpgOnNowMixin, _EpgBrowseMixin, _EpgEventsMixin, ContentView):
    """Watchlist-first EPG view with On Now and Browse tabs."""

    play_channel_requested = pyqtSignal(object)  # ChannelDB
    watchlist_changed = pyqtSignal()             # patterns or channels modified
    # Source-freshness status (text, tooltip). The status text does NOT live in
    # the EPG view — the host mirrors it onto the "###,### EPG programmes" stats
    # line (right-aligned) so status + count read as one strip. Emitted whenever
    # _update_status_label recomputes (on_activate, _on_epg_refreshed).
    epg_status_changed = pyqtSignal(str, str)    # (status text, tooltip)
    # "Show all in Search" clicked on a watchlist card — MainWindow connects this
    # to the existing search_for_title(title) seam (main_window_favorites.py),
    # which switches to the channel list, enables the Search chip, and pre-fills
    # the query with the watchlist pattern.
    search_requested = pyqtSignal(str)           # pattern

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
        self._channel_audio_map: dict[str, str] = {}    # channel_db_id → audio form (from detected_audio)
        # channel_db_id → (play_count, last_played). Populated alongside the other
        # _channel_*_map dicts by _build_name_map (same already-fetched ChannelDB
        # row — no extra query) so the watchlist can rank "previously watched"
        # channels first within a quality tier.
        self._channel_watch_map: dict[str, tuple[int, datetime | None]] = {}
        # channel_db_id → provider_id — Browse's source-glyph prefix (Q4, wave3/browse-makeover).
        self._channel_provider_map: dict[str, str] = {}
        # channel_db_ids carrying a globally-excluded content_type tag (AI Generated,
        # AI Voiceover). Resolved off-thread in _fetch_on_now; dropped in _render_on_now.
        self._on_now_excluded_ct_ids: set[str] = set()

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
        # A single row: the tab bar owns the full header width so every tab fits
        # without a ‹ › overflow-scroll state.  The source-freshness status text +
        # Refresh button do NOT live here — the host renders them right-aligned on
        # the "###,### EPG programmes" stats line (status via the epg_status_changed
        # signal; Refresh wired to _on_force_refresh).
        header_widget = QWidget()
        header_widget.setObjectName("epgHeader")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(8)

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

        root.addWidget(header_widget)

        # Thin separator
        self._header_sep = QFrame()
        self._header_sep.setFrameShape(QFrame.Shape.HLine)
        _theme.style_fn(self._header_sep, lambda: f"border: none; border-top: 1px solid {_theme.COLOR_LINE};")
        root.addWidget(self._header_sep)

        # ── Stale-EPG notice ────────────────────────────────────────────
        # Surfaces sources whose provider feed serves out-of-date guide data, so an
        # empty On Now reads as "provider's guide is stale" rather than "EPG is broken".
        self._stale_epg_notice = QLabel("")
        self._stale_epg_notice.setWordWrap(True)
        _theme.style(self._stale_epg_notice, "EPG_STALE_NOTICE")
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
        _theme.style(sec1_lbl, "SECTION_HDR_LG")
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
            _theme.style(lbl, "SECTION_ITEM")
            lbl.setWordWrap(True)
            self._hidden_layout.addWidget(lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        _theme.style(sep, "SEPARATOR_H")
        self._hidden_layout.addWidget(sep)

        # ── Section 2: Filler patterns ──────────────────────────────────
        sec2_lbl = QLabel("FILLER PATTERNS")
        _theme.style(sec2_lbl, "SECTION_HDR_LG")
        self._hidden_layout.addWidget(sec2_lbl)

        hint = QLabel("Substring match — hides any show whose title contains these words.")
        _theme.style(hint, "SECTION_HINT")
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
        add_input.setClearButtonEnabled(True)
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
        _theme.style(sep2, "SEPARATOR_H")
        self._hidden_layout.addWidget(sep2)

        # ── Section 3: Hidden channels ──────────────────────────────────
        sec3_lbl = QLabel("HIDDEN CHANNELS")
        _theme.style(sec3_lbl, "SECTION_HDR_LG")
        self._hidden_layout.addWidget(sec3_lbl)

        hidden_channels = list(self.config.epg_hidden_channels or [])
        if hidden_channels:
            hint3 = QLabel("Entire channel hidden from On Now.")
            _theme.style(hint3, "SECTION_HINT")
            self._hidden_layout.addWidget(hint3)
            for ch_id in hidden_channels:
                ch_name = self._get_channel_name_from_db(ch_id)
                self._hidden_layout.addWidget(self._make_hidden_row(
                    ch_name, "channel",
                    lambda _, cid=ch_id: self._remove_hidden_channel(cid),
                ))
        else:
            lbl3 = QLabel("No channels hidden yet — use the 🚫 button on any On Now row.")
            _theme.style(lbl3, "SECTION_ITEM")
            lbl3.setWordWrap(True)
            self._hidden_layout.addWidget(lbl3)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        _theme.style(sep3, "SEPARATOR_H")
        self._hidden_layout.addWidget(sep3)

        # ── Section 4: Hidden categories ────────────────────────────────
        sec4_lbl = QLabel("HIDDEN CATEGORIES")
        _theme.style(sec4_lbl, "SECTION_HDR_LG")
        self._hidden_layout.addWidget(sec4_lbl)

        hidden_prefixes = list(self.config.epg_hidden_prefixes or [])
        if hidden_prefixes:
            hint4 = QLabel("All channels with this prefix are hidden from On Now.")
            _theme.style(hint4, "SECTION_HINT")
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
            _theme.style(lbl4, "SECTION_ITEM")
            lbl4.setWordWrap(True)
            self._hidden_layout.addWidget(lbl4)

        sep5 = QFrame()
        sep5.setFrameShape(QFrame.Shape.HLine)
        _theme.style(sep5, "SEPARATOR_H")
        self._hidden_layout.addWidget(sep5)

        # ── Section 5: Category overrides ──────────────────────────────
        sec5_lbl = QLabel("CATEGORY OVERRIDES")
        _theme.style(sec5_lbl, "SECTION_HDR_LG")
        self._hidden_layout.addWidget(sec5_lbl)

        overrides = dict(self.config.epg_category_overrides or {})
        if overrides:
            hint5 = QLabel("Manually assigned categories — applied before auto-detection.")
            _theme.style(hint5, "SECTION_HINT")
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
            _theme.style(lbl5, "SECTION_ITEM")
            lbl5.setWordWrap(True)
            self._hidden_layout.addWidget(lbl5)

    def _make_hidden_row(self, label: str, detail: str, on_remove) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(8)
        lbl = QLabel(label)
        _theme.style_fn(lbl, lambda: f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_TEXT_2};")
        h.addWidget(lbl, 1)
        det = QLabel(detail)
        _theme.style_fn(det, lambda: f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_FAINT};")
        h.addWidget(det)
        rm_btn = QPushButton(self.config.close_icon)
        rm_btn.setFixedWidth(24)
        _theme.style_fn(rm_btn, lambda: f"border: none; color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_2XL}; font-weight: bold;")
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
        # Re-resolve the Browse start anchors ("Now"/"Tonight"/…) against the current
        # clock so their labels and floored datetimes stay fresh across the session.
        self._refresh_browse_anchors()
        # The Phase-2 timeline scrubber handle snaps back to NOW each time Browse is
        # (re)opened; the next Browse configure consumes this flag.
        self._scrubber_reset_to_now = True

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

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this view's own persistent chrome —
        every label/notice/stats-footer styled once at construction across the
        header + all six tabs (Watchlist/My Channels/Discover/On Now/Browse/
        Events), spread across ``epg_view.py`` and its four mixin files
        (``epg_watchlist_mixin.py``/``epg_on_now_mixin.py``/
        ``epg_browse_mixin.py``/``epg_events_mixin.py`` — split out only to
        stay under the project's 1000-line file limit; every ``self.*`` here
        is this SAME ``EpgView`` instance). Called from
        ``MainWindow.refresh_theme()``.

        Per-row/per-card content (On Now/Browse tree rows, watchlist/channel/
        recommendation cards, event rows, the Manage tab's hidden-items list)
        is torn down and rebuilt from current tokens on every reload, so it's
        already live — same rationale as the channel-list row delegate.
        """
        _theme.style_fn(self._header_sep, lambda: f"border: none; border-top: 1px solid {_theme.COLOR_LINE};")
        _theme.style(self._stale_epg_notice, "EPG_STALE_NOTICE")

        # Watchlist / My Channels / Discover tabs (epg_watchlist_mixin.py)
        _theme.style(self._watchlist_hint_lbl, "LABEL_MUTED")
        _theme.style_fn(self._watchlist_ci_note_lbl, lambda: f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_SM};")
        _theme.style(self.ch_empty_label, "EMPTY_LABEL")
        _theme.style(self._rec_title_lbl, "CHANNEL_NAME_DIM")
        _theme.style_fn(self.manage_dismissed_btn, lambda: f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD}; border: none; background: transparent;")
        _theme.style(self.rec_empty_label, "EMPTY_LABEL")

        # On Now tab (epg_on_now_mixin.py)
        _theme.style(self.on_now_stats, "LABEL_MUTED")

        # Browse tab (epg_browse_mixin.py)
        _theme.style(self._anchor_label, "LABEL_MUTED")
        _theme.style(self._scrubber_left_label, "LABEL_MUTED")
        _theme.style(self._scrubber_right_label, "LABEL_MUTED")
        _theme.style(self._scrubber_pos_label, "EPG_SCRUBBER_POS")
        _theme.style_fn(self.browse_placeholder, lambda: f"color: {_theme.COLOR_FAINT}; font-size: {_theme.FONT_XL}; padding: 40px;")
        _theme.style(self.browse_stats, "LABEL_MUTED")

        # Events tab (epg_events_mixin.py) — reuse the existing active/inactive
        # toggle-style method rather than duplicating its branching here.
        _theme.style(self._events_stats, "LABEL_MUTED")
        self._apply_events_toggle_styles()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_provider_ids(self) -> None:
        from metatv.core.repositories import RepositoryFactory
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            self._provider_ids = repos.providers.get_epg_active_provider_ids()
            # Kept alongside the ids so the empty state can explain WHY it is
            # empty rather than only that it is (#17).
            self._epg_readiness = repos.providers.get_epg_readiness()
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

    def _filtered_provider_ids(self) -> list[str]:
        return self._provider_ids

    # ── Background workers ─────────────────────────────────────────────

    def _build_name_map(self, session, watchlist_data, live_data) -> dict[str, str]:
        """Build channel display maps from stored detected_* fields.

        Populates _channel_quality_map, _channel_prefix_map, _channel_title_map,
        _channel_region_map, _channel_year_map, _channel_audio_map, and
        _channel_watch_map as a side-effect.  Returns the raw name map for
        backwards compatibility.

        Reads stored detected_* fields written at ingestion time — no parse_channel_name
        call here (ingestion-only rule, CLAUDE.md). _channel_watch_map reuses this
        SAME per-channel ``ch`` row already fetched for the other maps — no extra
        query — so ``_render_watchlist``'s ranking pass (quality tier + previously
        watched) has the data it needs without a per-row lookup.
        """
        name_map: dict[str, str] = {}
        quality_map: dict[str, str] = {}
        prefix_map: dict[str, str] = {}
        title_map: dict[str, str] = {}
        region_map: dict[str, str] = {}
        year_map: dict[str, str] = {}
        audio_map: dict[str, str] = {}
        watch_map: dict[str, tuple[int, datetime | None]] = {}
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
                    if ch.detected_audio:
                        audio_map[p.channel_db_id] = ch.detected_audio.get("form", "") or ""
                    watch_map[p.channel_db_id] = (ch.play_count or 0, ch.last_played)
        self._channel_quality_map.update(quality_map)
        self._channel_prefix_map.update(prefix_map)
        self._channel_title_map.update(title_map)
        self._channel_region_map.update(region_map)
        self._channel_year_map.update(year_map)
        self._channel_audio_map.update(audio_map)
        self._channel_watch_map.update(watch_map)
        return name_map

    # ------------------------------------------------------------------
    # Interaction handlers
    # ------------------------------------------------------------------

    def _on_tab_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self._reload_all()

    def _host(self):
        """Return the MainWindow host (Qt top-level parent) for delegating core actions."""
        return self.window()

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
        _theme.style_fn(cancel, lambda: f"color: {_theme.COLOR_MUTED};")
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

    def _epg_source_info(self) -> dict[str, tuple[str, object]]:
        """Return ``{provider_id: (name, epg_data_end)}`` for the active EPG sources.

        One query — feeds the header label/tooltip detail without a session per
        provider. ``epg_data_end`` is UTC-naive; staleness is decided by the
        canonical :func:`epg_utils.epg_is_stale`, never an inline comparison.
        """
        if not self._provider_ids:
            return {}
        session = self.db.get_session()
        try:
            rows = (
                session.query(ProviderDB.id, ProviderDB.name, ProviderDB.epg_data_end)
                .filter(ProviderDB.id.in_(self._provider_ids))
                .all()
            )
            return {r.id: (r.name, r.epg_data_end) for r in rows}
        finally:
            session.close()

    def _update_status_label(self) -> None:
        """EPG source status: source names + freshness/staleness (flagged c3e1aaf3).

        Compact label (single source → its freshness; multiple → "N sources" plus a
        stale count when any guide is stale) with a per-source tooltip naming each
        source and its freshness via the ``EpgManager.get_status_text`` chokepoint.
        The text does not live in the view — it is emitted via ``epg_status_changed``
        so the host renders it on the "###,### EPG programmes" stats line.
        """
        if not self._provider_ids:
            # Say WHICH of the several "no EPG" situations this is, and what to
            # do — "No EPG sources" was accurate and useless (#17).
            headline, hint = epg_empty_state(
                getattr(self, "_epg_readiness", {}) or {}, 0
            )
            self.epg_status_changed.emit(headline or "No EPG sources", hint)
            return

        info = self._epg_source_info()
        lines: list[str] = []
        stale_count = 0
        for pid in self._provider_ids:
            name, end = info.get(pid, (pid, None))
            status = self.epg_manager.get_status_text(pid)
            if _epg_is_stale(end):
                stale_count += 1
                lines.append(f"{name}: {status}  (stale)")
            else:
                lines.append(f"{name}: {status}")
        tooltip = "\n".join(lines)

        if len(self._provider_ids) == 1:
            pid = self._provider_ids[0]
            name, _end = info.get(pid, (pid, None))
            text = f"{name} · {self.epg_manager.get_status_text(pid)}"
        else:
            suffix = f" · {stale_count} stale" if stale_count else ""
            text = f"{len(self._provider_ids)} sources{suffix}"
        self.epg_status_changed.emit(text, tooltip)

    # ── Watchlist management ───────────────────────────────────────────

    def _prompt_track(self, default_text: str) -> None:
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Track show",
            "Add watchlist pattern — edit to a keyword for broader matching:",
            text=default_text,
        )
        if ok and text.strip():
            self._add_pattern(text.strip())

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

