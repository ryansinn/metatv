"""WatchAlertsSection and its _AlertRow helper widget."""

import html

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QAbstractScrollArea, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from loguru import logger

from metatv.core.epg_utils import now_utc as _now_utc, is_local_today as _is_local_today, to_local as _to_local
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import series_alert_identity as _series_identity
from metatv.gui import theme as _theme
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.alerts_rows import (
    _AlertRow,
    _name_with_dim_suffix_html,
    _VodAlertRow,
)
from metatv.gui.sidebar.base import CollapsibleSection, _fmt_channel_name

# Item-data roles for the Movies & Series list (_vod_list).  UserRole stays the
# rule_created id for keyword-rule rows (existing click/menu code reads it); the
# extra roles tag the item kind and, for series rows, the series channel id.
_ROLE_KIND = Qt.ItemDataRole.UserRole + 5        # "rule" | "keyword_divider" | "series_divider" | "series"
_ROLE_SERIES_ID = Qt.ItemDataRole.UserRole + 6   # series_channel_id (series rows)

# Row budget (px) for _apply_expansion()'s "expand every group only if the fully
# expanded list still fits a compact height" decision.  It is NOT a widget maximum:
# the three sub-lists share the section's height via equal layout stretch (see
# create_content), so the EPG tree is bounded by its stretch share of the splitter
# pane, not by a hard cap.  A hard cap was deliberately dropped — capping the tree to
# its content left the section's surplus space pooling as a blank gap at the bottom.
_ALERTS_TREE_AUTOEXPAND_BUDGET = 320


def _alerts_title_html(title: str, count: int) -> str:
    """Rich-text for the Alerts header: a recolorable status dot + title + count.

    A single state-driven label replaces the old dual-glyph (siren title + green
    badge).  The dot is a plain glyph that honours CSS ``color`` so its colour is
    the state cue (paired with the count text, so it is colourblind-safe):

        - Quiet (count == 0): gray dot, default-text title, no suffix.
        - Active (count > 0): green dot, green title, " (N)" suffix.

    Args:
        title: The section title (always "Watch Alerts").
        count: Number of unviewed watch-for matches across all rules.

    Returns:
        An HTML string for :meth:`QLabel.setText` (rich-text format).
    """
    if count > 0:
        dot_color = _theme.COLOR_OK
        title_color = _theme.COLOR_OK
        suffix = f" ({count})"
    else:
        dot_color = _theme.COLOR_MUTED
        title_color = _theme.COLOR_TEXT
        suffix = ""
    return (
        f'<span style="color:{dot_color}">{_icons.status_dot_icon}</span> '
        f'<b><span style="color:{title_color}">{title}{suffix}</span></b>'
    )


def _vod_count_label(unviewed: int, count: int) -> str:
    """Right-aligned count text for a watch-for rule row.

    The green tint on the count (and the header dot) already conveys "new", so the
    word is dropped from the text:

        - unviewed > 0:             "{unviewed} of {count}"  (e.g. "5 of 20")
        - unviewed == 0, count > 0: "· {count}"
        - count == 0:               ""

    Args:
        unviewed: Unviewed match count for this rule.
        count: Total match count for this rule.

    Returns:
        The count label text (possibly empty).
    """
    if unviewed > 0:
        return f"{unviewed} of {count}"
    if count > 0:
        return f"· {count}"
    return ""


class WatchAlertsSection(BackgroundRefreshMixin, CollapsibleSection):
    """Alerts section — EPG watch alerts + VOD watch-for rules + stream retry monitoring."""

    MIN_ROWS: int = 7   # three nested sub-groups need room to be legible

    alertClicked    = pyqtSignal(str)        # channel_db_id — play (double-click or play button)
    channel_selected = pyqtSignal(str)      # channel_db_id — single click → load details pane
    channelContextMenuRequested = pyqtSignal(str, int, int) # channel_db_id, global_x, global_y
    retryRemoveRequested = pyqtSignal(str)                  # entry_id
    retryClearAllRequested = pyqtSignal()
    retryPlayRequested = pyqtSignal(str, str, str)            # channel_id, stream_url, channel_name
    retryContextMenuRequested = pyqtSignal(str, str, int, int)  # entry_id, channel_id, x, y
    # VOD watch-for signals
    addWatchForClicked = pyqtSignal()        # "+" button → open "Watch for…" dialog
    manageWatchForClicked = pyqtSignal()     # header "Manage" → open shared manage dialog
    vodAlertClicked = pyqtSignal(str)        # channel_db_id — play matched content
    vodRuleViewMatchesRequested = pyqtSignal(str, str)  # text, match_type → keyword search (dialog fallback)
    vodRuleShowMatchesRequested = pyqtSignal(str)  # rule_created → show the rule's STORED matched ids
    vodRuleRemoveRequested = pyqtSignal(str)  # rule_created → remove rule + refresh
    vodRuleClearAlertRequested = pyqtSignal(str)  # rule_created → ack just this rule's matches
    clearAllAlertsClicked = pyqtSignal()     # header "Clear all" → ack every new match
    # Monitored-series signals (folded in from the retired New Episodes section)
    # seriesClicked: SINGLE click only — DETAILS ONLY (loads the series into the
    # details pane, no navigation). seriesActivated is the separate DRILL-IN
    # signal (double-click / "Open series" menu action) — the two must never be
    # merged, mirroring the queue.py Alerts Matched precedent (#365) where a
    # matched_series row's single click and double-click/menu-open are likewise
    # distinct chokepoints.
    seriesClicked = pyqtSignal(str)          # series_channel_id → open series details
    seriesActivated = pyqtSignal(str)        # series_channel_id → drill into series (browse)
    seriesMarkSeenRequested = pyqtSignal(str)  # series_channel_id → clear unseen count
    seriesStopRequested = pyqtSignal(str)    # series_channel_id → stop monitoring
    _data_ready = pyqtSignal(object)         # dict | None (None = load failure)

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Watch Alerts", _icons.alert_icon, config, parent)
        self._init_background_refresh()

    def get_section_id(self):
        return "alerts"

    def create_header(self):
        header = self._build_clickable_header()
        hl = header.layout()
        # A single state-driven label: a recolorable status dot + "Watch Alerts" + an
        # optional " (N)" count.  Replaces the old warn-siren title + separate
        # green badge — the dot's colour IS the glance (gray = quiet, green = new),
        # visible even when the section is collapsed.  Updated by update_new_match_badge.
        self.title_label = QLabel(_alerts_title_html(self.title, 0))
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        hl.addWidget(self.title_label)

        hl.addStretch()

        # "Clear all" — acknowledge every new match; shown only when N > 0.
        self._clear_all_btn = QPushButton("Clear all")
        self._clear_all_btn.setFlat(True)
        self._clear_all_btn.setToolTip("Acknowledge all new matches")
        _theme.style(self._clear_all_btn, "LINK_BTN_SM")
        self._clear_all_btn.clicked.connect(self.clearAllAlertsClicked.emit)
        self._clear_all_btn.hide()
        hl.addWidget(self._clear_all_btn)

        # "Manage" — always reachable, even when every sub-section below is empty.
        # Opens the shared manage dialog (keyword rules + monitored series).  This
        # is the whole point of the consolidation: management can no longer hide
        # inside a collapsible/hideable body.
        self._manage_btn = QPushButton("Manage")
        self._manage_btn.setFlat(True)
        self._manage_btn.setToolTip(
            "Manage watch alerts — keyword rules and monitored series"
        )
        _theme.style(self._manage_btn, "LINK_BTN_SM")
        self._manage_btn.clicked.connect(self.manageWatchForClicked.emit)
        hl.addWidget(self._manage_btn)

        _btn_style = (
            "QPushButton {{ font-size: {fs}; border: 1px solid {c};"
            " border-radius: 3px; color: {c}; background: {bg}; }}"
            "QPushButton:hover {{ background: {hbg}; }}"
        )
        add_btn = QPushButton(_icons.add_icon)
        add_btn.setFixedSize(22, 20)
        add_btn.setToolTip("Watch for new content…")
        _theme.style_fn(add_btn, lambda: _btn_style.format(
            fs=_theme.FONT_LG,
            c=_theme.COLOR_TEXT, bc=_theme.COLOR_BORDER,
            bg=_theme.OVERLAY_05,
            hbg=_theme.OVERLAY_15,
        ))
        add_btn.clicked.connect(self.addWatchForClicked.emit)
        hl.addWidget(add_btn)

        self.main_layout.addWidget(header)

    def create_content(self):
        from PyQt6.QtWidgets import QHeaderView

        # ── EPG sub-section ────────────────────────────────────────────────
        # Live/upcoming programmes from the EPG watchlist.  Given its own labelled +
        # collapsible sub-header so it sits parallel with the other sub-sections
        # (it previously floated label-less at the top — the inconsistency the
        # consolidation fixes).  Hidden entirely when nothing is airing now/soon.
        self._epg_collapsed = False
        self._epg_has_rows = False

        epg_hdr_row = QHBoxLayout()
        epg_hdr_row.setContentsMargins(0, 4, 0, 2)
        epg_hdr_row.setSpacing(4)

        self._epg_toggle = QPushButton()
        self._epg_toggle.setFlat(True)
        self._epg_toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        _theme.style(self._epg_toggle, "SIDEBAR_SUBSECTION_TOGGLE")
        self._epg_toggle.setToolTip(
            "Live TV programs and events from your watchlist, airing now or soon."
        )
        self._epg_toggle.clicked.connect(self._toggle_epg)
        epg_hdr_row.addWidget(self._epg_toggle)
        epg_hdr_row.addStretch()

        self._epg_hdr_container = QWidget()
        self._epg_hdr_container.setLayout(epg_hdr_row)
        self._epg_hdr_container.hide()
        self.content_layout.addWidget(self._epg_hdr_container)

        self.alerts_tree = QTreeWidget()
        self.alerts_tree.setHeaderHidden(True)
        self.alerts_tree.setColumnCount(1)
        self.alerts_tree.setIndentation(12)
        self.alerts_tree.header().setStretchLastSection(True)
        self.alerts_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.alerts_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.alerts_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.alerts_tree.customContextMenuRequested.connect(self._on_context_menu)
        _theme.apply_list_selection(self.alerts_tree)
        # Expanding + equal stretch (shared by all three sub-lists) so the section's
        # surplus vertical space is DISTRIBUTED among them rather than pooling in one
        # ballooning list or a dead gap.  No maximumHeight: the stretch share bounds
        # the tree within the splitter pane, and a long watchlist scrolls internally.
        self.alerts_tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.alerts_tree.hide()
        self.content_layout.addWidget(self.alerts_tree, 1)

        self._update_epg_toggle_label(0)
        # ── end EPG sub-section ────────────────────────────────────────────

        # ── Movies & Series sub-section ────────────────────────────────────
        # Keyword watch-for rules PLUS monitored series (folded in from the retired
        # New Episodes section).  Management is the header "Manage" button now.
        self._vod_collapsed = False
        self._series_collapsed = False  # the "──── Series ────" divider toggle

        vod_hdr_row = QHBoxLayout()
        vod_hdr_row.setContentsMargins(0, 4, 0, 2)
        vod_hdr_row.setSpacing(4)

        self._vod_toggle = QPushButton()
        self._vod_toggle.setFlat(True)
        self._vod_toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        _theme.style(self._vod_toggle, "SIDEBAR_SUBSECTION_TOGGLE")
        self._vod_toggle.clicked.connect(self._toggle_vod_watching)
        vod_hdr_row.addWidget(self._vod_toggle)
        vod_hdr_row.addStretch()

        self._vod_hdr_container = QWidget()
        self._vod_hdr_container.setLayout(vod_hdr_row)
        self._vod_hdr_container.hide()
        self.content_layout.addWidget(self._vod_hdr_container)

        self._vod_list = QListWidget()
        self._vod_list.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        # Equal stretch with the EPG tree so Movies & Series always gets its fair share
        # of the section's height (never starved to a sliver) and grows to help fill the
        # pane instead of leaving a gap.  A long list scrolls within its share.
        self._vod_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        _theme.style_fn(self._vod_list, lambda: f"QListWidget {{ font-size: {_theme.FONT_MD}; }}")
        _theme.apply_list_selection(self._vod_list)
        cursor_affordance.set_clickable(self._vod_list)
        self._vod_list.itemClicked.connect(self._on_vod_item_clicked)
        self._vod_list.itemDoubleClicked.connect(self._on_vod_item_double_clicked)
        self._vod_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._vod_list.customContextMenuRequested.connect(self._on_vod_context_menu)
        self._vod_list.hide()
        self.content_layout.addWidget(self._vod_list, 1)

        self._update_vod_toggle_label(0)
        # ── end Movies & Series sub-section ────────────────────────────────

        # Stream Monitoring collapsible sub-section
        self._retry_collapsed = False

        retry_hdr_row = QHBoxLayout()
        retry_hdr_row.setContentsMargins(0, 4, 0, 2)
        retry_hdr_row.setSpacing(4)

        self._retry_toggle = QPushButton()
        self._retry_toggle.setFlat(True)
        self._retry_toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        _theme.style(self._retry_toggle, "SIDEBAR_SUBSECTION_TOGGLE")
        self._retry_toggle.clicked.connect(self._toggle_stream_monitoring)
        retry_hdr_row.addWidget(self._retry_toggle)

        _info_lbl = QLabel(self.config.info_icon)
        _theme.style_fn(_info_lbl, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD};")
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
        # Matching Expanding + equal stretch so Stream Monitoring shares the pane on the
        # same footing as the other two sub-lists.
        self._retry_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        _theme.style_fn(self._retry_list, lambda: f"QListWidget {{ font-size: {_theme.FONT_MD}; }}")
        _theme.apply_list_selection(self._retry_list)
        self._retry_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._retry_list.customContextMenuRequested.connect(self._on_retry_context_menu)
        self._retry_list.itemDoubleClicked.connect(self._on_retry_double_clicked)
        self._retry_list.hide()
        self.content_layout.addWidget(self._retry_list, 1)

        self._update_retry_toggle_label(0)

        # NO trailing stretch: the three sub-lists carry equal layout stretch and an
        # Expanding vertical policy, so the section's surplus height is shared among the
        # visible lists (each grows to help fill the pane) instead of pooling as a blank
        # gap at the bottom.  When a list is hidden its stretch drops out and the
        # remaining visible list(s) take the space.
        self.set_empty(True)

    # ------------------------------------------------------------------
    # Overall empty-state
    # ------------------------------------------------------------------

    def _recompute_empty(self) -> None:
        """Set the section's empty state from ALL sub-sections' current contents.

        The section shows a tidy header-only line when every sub-section is empty;
        it auto-expands when any of EPG / Movies & Series / Stream Monitoring gains
        rows.  Guarded so ``__new__`` test stubs (no full constructor) skip it.
        """
        if "_retry_list" not in self.__dict__:
            return
        epg = self.__dict__.get("_epg_has_rows", False)
        has_rows = epg or self._vod_list.count() > 0 or self._retry_list.count() > 0
        self.set_empty(not has_rows)

    # ------------------------------------------------------------------
    # EPG sub-section helpers
    # ------------------------------------------------------------------

    def _update_epg_toggle_label(self, count: int) -> None:
        arrow = self.config.expand_icon if self._epg_collapsed else self.config.collapse_icon
        label = f"EPG  ({count})" if count else "EPG"
        self._epg_toggle.setText(f"{arrow}  {label}")

    def _toggle_epg(self) -> None:
        self._epg_collapsed = not self._epg_collapsed
        self.alerts_tree.setVisible(not self._epg_collapsed and self._epg_has_rows)
        self._update_epg_toggle_label(self.alerts_tree.topLevelItemCount())

    # ------------------------------------------------------------------
    # Movies & Series helpers
    # ------------------------------------------------------------------

    def _update_vod_toggle_label(self, count: int) -> None:
        arrow = self.config.expand_icon if self._vod_collapsed else self.config.collapse_icon
        # ``_vod_toggle`` is a QPushButton, which treats a lone "&" as a keyboard
        # mnemonic (rendering "Movies _Series").  Escape it as "&&" so the label
        # shows a literal ampersand.  (The manage-dialog QLabel sub-header does not
        # process mnemonics, so it stays a single "&".)
        label = "Movies && Series"
        if count:
            label += f"  ({count})"
        # Surface firing alerts on the toggle itself (plain text — the header dot
        # carries the colour): "Movies & Series (5)  ·  3 new".  Combines firing
        # keyword rules (AVAILABLE-only, stashed by the last refresh) with the
        # number of monitored series that have unseen new episodes.  Read via
        # __dict__ (not getattr) so a __new__'d test stub — whose Qt C++ side was
        # never initialised — does not raise instead of returning the default.
        firing = self.__dict__.get("_firing_count")
        if firing is None:
            firing = getattr(self.config, "get_rules_with_new_matches_count", lambda: 0)()
        new_total = firing + self.__dict__.get("_series_new_count", 0)
        if new_total > 0:
            label += f"  ·  {new_total} new"
        if self.__dict__.get("_series_checking"):
            label += f"  {_icons.loading_icon} checking…"
        self._vod_toggle.setText(f"{arrow}  {label}")

    def news(self) -> str:
        """Firing rules plus series with unseen episodes.

        Reads the same two counters the VOD toggle line already keeps, so the
        header and that line can never disagree about whether anything is new.
        """
        firing = self.__dict__.get("_firing_count")
        if firing is None:
            firing = getattr(self.config, "get_rules_with_new_matches_count",
                             lambda: 0)()
        total = firing + self.__dict__.get("_series_new_count", 0)
        return f"{total} new" if total else ""

    def set_series_checking(self, busy: bool) -> None:
        """Show/clear a subtle busy hint on the Movies & Series header.

        Wired to ``SeriesMonitorManager.checking_started``/``checking_finished``
        so a startup, recurring-timer, or post-provider-refresh recheck pass is
        visible instead of silently changing state underfoot. Same
        ``icons.loading_icon`` idiom as the per-row spinners in
        ``sidebar/sources.py`` (``set_busy``/``set_epg_refreshing``), applied to
        this section's sub-header instead of a per-row button.
        """
        self._series_checking = busy
        self._update_vod_toggle_label(self._vod_list.count())

    def _series_display_entries(self) -> list[dict]:
        """Monitored-series rows for render: cleaned title + unseen count, sorted.

        New-episode series (``unseen_new > 0``) are pinned to the top, then idle
        ones — each group sorted A–Z by the CLEANED display title.  The cleaned
        title is read from the stored ``display_title`` (persisted at monitor-add
        time / backfilled from the channel's ingestion-computed ``detected_title``);
        render never re-parses the raw name.  Falls back to the raw ``title`` only
        for a not-yet-backfilled entry whose source channel is gone.

        Each row also carries the persisted identity fields (``language``,
        ``region``, ``source``, raw ``title``) and a ``suffix`` — a dim inline
        disambiguator, non-empty ONLY when two entries share a cleaned title (the
        "two Fallout" case).  All identity data is read from stored fields; nothing
        re-parses the raw name at render.
        """
        entries = getattr(self.config, "get_monitored_series", lambda: [])()
        # Pair each display dict with its raw config entry so the shared
        # disambiguation helper (which reads the raw stored fields) can run on the
        # SORTED order and align 1:1 back onto the rows.
        pairs: list[tuple[dict, dict]] = []
        for e in entries:
            pairs.append((
                {
                    "cid": e.get("series_channel_id", ""),
                    "title": e.get("display_title") or e.get("title") or "Unknown series",
                    "unseen": e.get("unseen_new") or 0,
                    "language": (e.get("language") or "").strip(),
                    "region": (e.get("region") or "").strip(),
                    "source": (e.get("source") or "").strip(),
                    "raw_title": e.get("title") or "",
                    # Provider(s) credited for the current unseen count (toast +
                    # row-tooltip attribution) — persisted on the config entry,
                    # cleared alongside unseen_new.  Never re-derived at render.
                    "growth_providers": list(e.get("growth_providers") or []),
                },
                e,
            ))
        # (unseen <= 0) sorts new-first (False < True); then A–Z within each group.
        pairs.sort(key=lambda p: (p[0]["unseen"] <= 0, p[0]["title"].casefold()))

        suffixes = _series_identity.disambiguation_suffixes([e for _, e in pairs])
        out: list[dict] = []
        for (row, _raw), suffix in zip(pairs, suffixes):
            row["suffix"] = suffix
            out.append(row)
        return out

    def _compute_alert_availability(self):
        """Re-validate stored matches against live source state (one bounded query).

        Returns an :class:`AlertAvailability`, or ``None`` when no DB is wired (test
        stubs / early init) so callers fall back to the raw config counts.
        """
        # Read the instance dict directly: getattr() on a __new__'d QObject stub
        # (tests) whose C++ super-init never ran raises RuntimeError instead of
        # returning the default, so a plain getattr(self, "db", None) would crash.
        db = self.__dict__.get("db")
        if db is None:
            return None
        try:
            from metatv.core.repositories import RepositoryFactory
            from metatv.core.vod_alert_availability import compute_alert_availability
            with db.session_scope(commit=False) as session:
                return compute_alert_availability(self.config, RepositoryFactory(session))
        except Exception:  # noqa: BLE001
            logger.exception("Alert availability re-validation failed; using raw counts")
            return None

    def _toggle_vod_watching(self) -> None:
        self._vod_collapsed = not self._vod_collapsed
        if self._vod_collapsed:
            self._vod_list.hide()
        else:
            self._vod_list.show()
        self._update_vod_toggle_label(self._vod_list.count())

    def refresh_vod_rules(self) -> None:
        """Repopulate the Movies & Series sub-list: keyword rules + monitored series.

        Reads ``config.get_vod_watch_alerts()`` and ``config.get_monitored_series()``
        synchronously (config is in-memory); a single bounded query re-validates the
        keyword-rule match counts against live source state.  Series rows read the
        stored cleaned ``display_title`` — no name re-parsing at render.  Called on
        startup, after a rule/series is added/removed, after a mark-seen, and after
        ``VodWatchAlertManager.new_matches_found`` / ``new_episodes_found``.
        """
        from metatv.gui import icons as _icons  # local import avoids circular at top

        rules = getattr(self.config, "get_vod_watch_alerts", lambda: [])()
        series = self._series_display_entries()
        self._vod_list.clear()

        # Re-validate every count against LIVE source state (once, one bounded query):
        # matches on disabled/expired sources never count or show — anywhere.  When no
        # DB is wired (test stubs) avail is None → fall back to the raw config counts.
        avail = self._compute_alert_availability()

        # Header glance = number of ALERTS (rules) currently firing (AVAILABLE-only),
        # NOT the total matched-item count.  The item count feeds only the tooltip.
        if avail is not None:
            _rules_firing = avail.firing_rules
            _new_items = avail.unviewed_total
        else:
            _rules_firing = getattr(self.config, "get_rules_with_new_matches_count", lambda: 0)()
            _new_items = getattr(self.config, "get_unviewed_vod_match_count", lambda: 0)()
        self._firing_count = _rules_firing  # read by _update_vod_toggle_label
        self._series_new_count = sum(1 for s in series if s["unseen"] > 0)
        # Header dot/(N) reflect TOTAL firing = keyword rules + series with new
        # episodes (so a collapsed section glows even when only a series is new).
        # "Clear all" stays tied to keyword rules ONLY (series are cleared via each
        # row's "Mark seen"), so it gets the separate clearable_count.
        self.update_new_match_badge(
            _rules_firing + self._series_new_count,
            _new_items,
            clearable_count=_rules_firing,
        )

        if not rules and not series:
            self._vod_hdr_container.hide()
            self._vod_list.hide()
            self._recompute_empty()
            return

        type_icons = {"movie": _icons.movie_icon, "series": _icons.series_icon}
        _unviewed_for = getattr(
            self.config, "get_vod_rule_unviewed_count", lambda _c: 0
        )

        # ── "Watching for" divider (keyword group label) ──────────────────
        # Only shown when BOTH groups are present — with a single group the
        # sub-section toggle already names it, so a label would be redundant.  A
        # plain, non-interactive muted row mirroring the Series divider's look
        # (that one is a collapse toggle; this one is just a label).
        if rules and series:
            kw_divider = QListWidgetItem("──── Watching for ────")
            kw_divider.setData(_ROLE_KIND, "keyword_divider")
            kw_divider.setForeground(QColor(_theme.COLOR_MUTED))
            kw_divider.setFlags(Qt.ItemFlag.NoItemFlags)  # label only — not clickable
            kw_divider.setToolTip("Keyword watch-for rules")
            self._vod_list.addItem(kw_divider)

        # ── Keyword rules ─────────────────────────────────────────────────
        for rule in rules:
            text = rule.get("text") or "?"
            match_type = rule.get("match_type", "any")
            created = rule.get("created", "")
            # Counts reflect AVAILABLE matches only (raw config counts as fallback).
            if avail is not None:
                count = avail.per_rule_total.get(created, 0)
                unviewed = avail.per_rule_unviewed.get(created, 0)
            else:
                count = len(rule.get("alerted_ids") or [])
                unviewed = _unviewed_for(created)

            # The far-left type icon already conveys the type, so the leading
            # second 🚨 and the "  (type)" suffix are dropped.  Only the count is
            # tinted green (unviewed) — the name stays fully legible.
            type_icon = type_icons.get(match_type, "")
            count_text = _vod_count_label(unviewed, count)
            count_style = (
                _theme.VOD_ALERT_COUNT_NEW if unviewed > 0
                else _theme.VOD_ALERT_COUNT_IDLE
            )

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, created)
            item.setData(_ROLE_KIND, "rule")
            count_tip = f"{count} match{'es' if count != 1 else ''} found" if count else "No matches yet"
            new_tip = f"\n{unviewed} new (unviewed)" if unviewed > 0 else ""
            item.setToolTip(
                f"Watching for: {text}\nType: {match_type}\n{count_tip}{new_tip}"
            )
            self._vod_list.addItem(item)
            row = _VodAlertRow(type_icon, text, count_text, count_style)
            item.setSizeHint(row.sizeHint())
            self._vod_list.setItemWidget(item, row)

        # ── Series divider + monitored-series rows ────────────────────────
        # The divider appears only when there ARE monitored series; it is a
        # collapse toggle (default expanded) so a heavy monitorer can tuck the
        # idle list away.
        if series:
            arrow = self.config.expand_icon if self._series_collapsed else self.config.collapse_icon
            divider = QListWidgetItem(f"{arrow}  ──── Series ({len(series)}) ────")
            divider.setData(_ROLE_KIND, "series_divider")
            divider.setForeground(QColor(_theme.COLOR_MUTED))
            divider.setToolTip("Series you're monitoring for new episodes — click to collapse/expand")
            self._vod_list.addItem(divider)

            if not self._series_collapsed:
                for s in series:
                    cid, title, unseen = s["cid"], s["title"], s["unseen"]
                    has_new = unseen > 0
                    # New-episode series get 🆕 + a green "+N eps" count (colour PLUS
                    # the icon/count, never colour alone); idle ones show 📺, no count.
                    type_icon = _icons.new_episodes_icon if has_new else _icons.series_icon
                    ep_word = "ep" if unseen == 1 else "eps"
                    count_text = f"+{unseen} {ep_word}" if has_new else ""
                    count_style = (
                        _theme.VOD_ALERT_COUNT_NEW if has_new
                        else _theme.VOD_ALERT_COUNT_IDLE
                    )
                    item = QListWidgetItem()
                    item.setData(_ROLE_KIND, "series")
                    item.setData(_ROLE_SERIES_ID, cid)
                    # Always-on identity tooltip (Language/Region/Source) so any
                    # series is fully identifiable on hover, even when two share a
                    # cleaned title.
                    tip = f"{title}"
                    if has_new:
                        # Name the provider(s) that gained episodes (e.g. "2 new
                        # eps on ProSat") — a monitored series is often mirrored
                        # across sources, and growth can land on any of them.
                        growers = s.get("growth_providers") or []
                        provider_note = f" on {', '.join(growers)}" if growers else ""
                        tip += (
                            f"\n{unseen} new {ep_word}{provider_note} — double-click "
                            "to browse the series, right-click to mark seen / stop"
                        )
                    else:
                        tip += (
                            "\nMonitoring for new episodes — double-click to browse "
                            "the series, right-click to stop"
                        )
                    tip += "\n\n" + _series_identity.identity_lines(
                        language=s["language"], region=s["region"], source=s["source"]
                    )
                    item.setToolTip(tip)
                    self._vod_list.addItem(item)
                    # A dim inline suffix only when this cleaned title collides.
                    row = _VodAlertRow(
                        type_icon, title, count_text, count_style,
                        suffix=s.get("suffix", ""),
                    )
                    item.setSizeHint(row.sizeHint())
                    self._vod_list.setItemWidget(item, row)

        # Toggle count = keyword rules + monitored series (the divider row is chrome).
        self._update_vod_toggle_label(len(rules) + len(series))
        self._vod_hdr_container.show()
        if not self._vod_collapsed:
            self._vod_list.show()
        self._recompute_empty()

    def update_new_match_badge(
        self, count: int, item_count: int | None = None, *,
        clearable_count: int | None = None,
    ) -> None:
        """Recompute the Alerts header dot/title/count + Clear-all visibility.

        The header is one state-driven label: gray dot + plain title when quiet,
        green dot + green "Alerts (N)" when alerts are firing.  The dot/title/"(N)"
        reflect the TOTAL firing count (keyword rules + series with new episodes),
        so a collapsed section still glows when only a series is new.

        "Clear all" acknowledges keyword matches only, so its visibility is driven
        by a SEPARATE ``clearable_count`` — a series-only new-episode state must not
        surface it (series are cleared per-row via "Mark seen").

        Args:
            count: TOTAL firing count for the header glance (rules + series).
            item_count: Total unviewed matched items (keyword) — shown in the
                tooltip.  Defaults to ``count`` when omitted.
            clearable_count: Firing KEYWORD rules only — drives "Clear all".
                Defaults to ``count`` for back-compat (keyword-only callers).
        """
        clearable = count if clearable_count is None else clearable_count
        try:
            self.title_label.setText(_alerts_title_html(self.title, count))
            if count > 0:
                items = count if item_count is None else item_count
                series_new = max(0, count - clearable)
                if series_new > 0:
                    # Mixed / series-included — spell out both numbers.
                    parts = []
                    if clearable > 0:
                        parts.append(
                            f"{clearable} keyword match{'es' if clearable != 1 else ''}"
                        )
                    parts.append(
                        f"{series_new} series with new episode"
                        f"{'s' if series_new != 1 else ''}"
                    )
                    self.title_label.setToolTip(
                        f"{count} alert{'s' if count != 1 else ''} — "
                        + ", ".join(parts)
                    )
                else:
                    # Keyword-only — unchanged wording incl. the matched-item total.
                    verb = "have" if count != 1 else "has"
                    self.title_label.setToolTip(
                        f"{count} alert{'s' if count != 1 else ''} {verb} new matches "
                        f"({items} new item{'s' if items != 1 else ''})"
                    )
            else:
                self.title_label.setToolTip("")
            self._clear_all_btn.setVisible(clearable > 0)
        except (AttributeError, RuntimeError):
            return  # header not built (e.g. __new__ test stub) — nothing to update

    def _on_vod_item_clicked(self, item: "QListWidgetItem") -> None:
        """Single-click routing by item kind.

        - keyword rule → show that rule's STORED matched channels (carries the rule
          id, not a keyword — a fresh keyword search would be lossy).
        - series → open the series details pane.
        - series divider → toggle the series block collapse.
        """
        kind = item.data(_ROLE_KIND)
        if kind == "series_divider":
            self._series_collapsed = not self._series_collapsed
            self.refresh_vod_rules()
            return
        if kind == "series":
            cid = item.data(_ROLE_SERIES_ID)
            if cid:
                self.seriesClicked.emit(cid)
            return
        rule_created = item.data(Qt.ItemDataRole.UserRole)
        if rule_created:
            self.vodRuleShowMatchesRequested.emit(rule_created)

    def _on_vod_item_double_clicked(self, item: "QListWidgetItem") -> None:
        """Double-click: series DRILLS IN (season/episode tree); a rule opens the manage dialog.

        Owner-reported bug: double-click on a monitored-series row used to emit
        the same details-only ``seriesClicked`` as a single click, so it never
        actually browsed the series. Drilling in is itself the "seen" ack
        (mirrors the matched_series row in Watch Queue / Alerts Matched, #365) —
        no separate mark-viewed emission needed here.
        """
        kind = item.data(_ROLE_KIND)
        if kind == "series":
            cid = item.data(_ROLE_SERIES_ID)
            if cid:
                self.seriesActivated.emit(cid)
            return
        if kind == "series_divider":
            return  # single-click already toggles it
        self.manageWatchForClicked.emit()

    def _on_vod_context_menu(self, pos) -> None:
        """Right-click menu — differs by item kind (keyword rule vs monitored series)."""
        from PyQt6.QtWidgets import QMenu
        item = self._vod_list.itemAt(pos)
        if not item:
            return

        kind = item.data(_ROLE_KIND)
        if kind == "series":
            self._show_series_context_menu(item, pos)
            return
        if kind in ("series_divider", "keyword_divider"):
            return

        rule_created = item.data(Qt.ItemDataRole.UserRole)
        unviewed = getattr(
            self.config, "get_vod_rule_unviewed_count", lambda _c: 0
        )(rule_created)

        menu = QMenu(self._vod_list)
        # When this rule has new (unviewed) matches, offer a per-rule acknowledge
        # near the top — clears just this alert's green, not every rule's.
        if unviewed > 0:
            clear_action = menu.addAction(f"{_icons.new_match_icon}  Clear this alert")
            clear_action.setToolTip("Acknowledge just this alert's new matches")
            clear_action.triggered.connect(
                lambda _=False, rc=rule_created: self.vodRuleClearAlertRequested.emit(rc)
            )
            menu.addSeparator()
        if rule_created:
            view_action = menu.addAction(f"{_icons.search_icon}  View matches")
            view_action.setToolTip("Show this alert's matched content in the main list")
            view_action.triggered.connect(
                lambda _=False, rc=rule_created: self.vodRuleShowMatchesRequested.emit(rc)
            )
            menu.addSeparator()

        remove_action = menu.addAction(f"{_icons.close_icon}  Remove rule")
        remove_action.setToolTip("Delete this watch-for rule")
        remove_action.triggered.connect(
            lambda _=False, rc=rule_created: self.vodRuleRemoveRequested.emit(rc)
        )

        menu.addSeparator()
        manage_action = menu.addAction(f"{_icons.manage_icon}  Manage rules…")
        manage_action.setToolTip("View and manage all watch-for rules")
        manage_action.triggered.connect(self.manageWatchForClicked.emit)

        menu.exec(self._vod_list.viewport().mapToGlobal(pos))

    def _show_series_context_menu(self, item: "QListWidgetItem", pos) -> None:
        """Right-click on a monitored-series row → Open / Mark seen / Stop / Manage."""
        cid = item.data(_ROLE_SERIES_ID)
        if not cid:
            return
        menu = self._build_series_context_menu(cid)
        menu.exec(self._vod_list.viewport().mapToGlobal(pos))

    def _build_series_context_menu(self, cid: str) -> "QMenu":
        """Build (does not exec) a monitored-series row's right-click menu.

        Hand-rolled (not the channel_menu.py registry): a monitored-series entry
        is a config-only aggregate, not a ChannelDB row the registry models
        (play/favorite/queue/etc.) — the identical rationale queue.py's
        ``_build_matched_series_menu`` documents for the sibling Alerts Matched
        series row (#365). "Open series" reuses the SAME drill chokepoint as
        double-click (``seriesActivated``) — never the details-only
        ``seriesClicked`` (that was the owner-reported bug: right-click "Open
        series" only loaded the details pane instead of browsing in). Building
        the menu never mutates/navigates anything — only a triggered action does
        (mirrors queue.py's ``_build_matched_series_menu`` — opening the menu is
        never itself a mark-viewed/navigate side effect), and splitting build
        from exec lets tests trigger an action without a blocking ``exec()``.
        """
        from PyQt6.QtWidgets import QMenu
        unseen = 0
        for e in getattr(self.config, "get_monitored_series", lambda: [])():
            if e.get("series_channel_id") == cid:
                unseen = e.get("unseen_new") or 0
                break

        menu = QMenu(self._vod_list)
        open_action = menu.addAction(f"{_icons.series_icon}  Open series")
        open_action.setToolTip("Browse this series' seasons and episodes")
        open_action.triggered.connect(lambda _=False, c=cid: self.seriesActivated.emit(c))

        if unseen > 0:
            seen_action = menu.addAction(f"{_icons.watched_icon}  Mark seen")
            seen_action.setToolTip("Clear the new-episode count for this series")
            seen_action.triggered.connect(
                lambda _=False, c=cid: self.seriesMarkSeenRequested.emit(c)
            )

        menu.addSeparator()
        stop_action = menu.addAction(f"{_icons.close_icon}  Stop alerts")
        stop_action.setToolTip("Stop monitoring this series for new episodes")
        stop_action.triggered.connect(
            lambda _=False, c=cid: self.seriesStopRequested.emit(c)
        )

        menu.addSeparator()
        manage_action = menu.addAction(f"{_icons.manage_icon}  Manage…")
        manage_action.setToolTip("Manage watch alerts — keyword rules and monitored series")
        manage_action.triggered.connect(self.manageWatchForClicked.emit)

        return menu

    def _rule_info_for_created(self, rule_created: str) -> tuple[str, str]:
        """Return (text, match_type) for the rule identified by rule_created, or ('', 'any')."""
        rules = getattr(self.config, "get_vod_watch_alerts", lambda: [])()
        for rule in rules:
            if rule.get("created") == rule_created:
                return rule.get("text", ""), rule.get("match_type", "any")
        return "", "any"

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
        self._reveal_epg_subsection()
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
        self._reveal_epg_subsection()
        self.set_empty(False)

    def _reveal_epg_subsection(self) -> None:
        """Show the EPG sub-header + tree (for loading / error / populated states)."""
        # Guarded for __new__ test stubs (no full constructor → no EPG widgets),
        # matching this file's other stub-tolerant helpers.
        if "_epg_hdr_container" not in self.__dict__:
            return
        self._epg_has_rows = True
        self._epg_hdr_container.show()
        self.alerts_tree.setVisible(not self._epg_collapsed)
        self._update_epg_toggle_label(self.alerts_tree.topLevelItemCount())

    def _hide_epg_subsection(self) -> None:
        """Hide the EPG sub-header + tree, then recompute the section's empty state."""
        self._epg_has_rows = False
        if "_epg_hdr_container" in self.__dict__:
            self._epg_hdr_container.hide()
            self.alerts_tree.hide()
            self._update_epg_toggle_label(0)
        self._recompute_empty()

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
            # No live/upcoming matches — hide the EPG sub-section entirely, then let
            # the other sub-sections decide the section's overall empty state.
            self._hide_epg_subsection()
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

        self._reveal_epg_subsection()
        self.set_empty(False)
        QTimer.singleShot(0, self._apply_expansion)

    def refresh_retry(self, entries: list) -> None:
        """Populate the stream retry sub-list from StreamRetryDB entries."""
        self._retry_list.clear()
        if not entries:
            self._retry_hdr_container.hide()
            self._retry_list.hide()
            self._recompute_empty()
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
        self._recompute_empty()

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
        """Expand every group if the fully-expanded list stays compact; else expand none.

        The budget is the fixed ``_ALERTS_TREE_AUTOEXPAND_BUDGET`` (in rows via the same
        ``sizeHintForRow(0)``/fallback-22 primitive), NOT the live ``viewport().height()``
        — the tree's height now flexes with its stretch share of the pane, so reading the
        viewport here would make the decision jitter with the pane size.  A fixed budget
        keeps the "auto-expand only a short watchlist; leave a long one collapsed so it
        scrolls compactly" behaviour stable regardless of how tall the section is dragged.
        """
        tree = self.alerts_tree
        n = tree.topLevelItemCount()
        if n == 0:
            return
        row_h = tree.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 22
        max_rows = max(1, _ALERTS_TREE_AUTOEXPAND_BUDGET // row_h)
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
