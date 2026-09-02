"""The Watch Alerts section: its shell, and the four groups it hosts.

The section itself is the frame — header, content layout, empty state, row
budget. Each GROUP it shows lives in its own module and is mixed in here:

* :mod:`alerts_epg` — programmes matching your EPG watchlist patterns
* :mod:`alerts_vod` — keyword rules (Movies) and monitored series (Series)
* :mod:`alerts_monitor` — streams being retried after a failure

Split along the groups the design already names, rather than by line count: one
file carrying all four had run to ~1800 lines against a 1000-line standard, and
a reader landing in the middle of it had nothing telling them which group they
were in. The mixins hold no state of their own — they reach the widgets
``create_content`` builds through ``self``.
"""

from __future__ import annotations


from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSizePolicy, QAbstractScrollArea, QListWidget, QTreeWidget

from PyQt6.QtCore import Qt, QSize, pyqtSignal

from metatv.gui import cursor_affordance
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import (
    CollapsibleSection, GroupHeading, make_seamless,
)
from metatv.gui.sidebar.alerts_epg import EpgGroupMixin
from metatv.gui.sidebar.alerts_monitor import StreamMonitoringMixin
from metatv.gui.sidebar.alerts_vod import MoviesSeriesMixin
# Re-exported: this module is the section's public name, and callers (and a
# fair number of tests) import these from here. Keeping the names available
# means the split is invisible from outside.
from metatv.gui.sidebar.alerts_common import (  # noqa: F401
    _ALERTS_TREE_AUTOEXPAND_BUDGET,
    _CHILD_INDENT,
    _ROLE_KIND,
    _ROLE_SERIES_ID,
    _ROW_FALLBACK_H,
    _Airing,
    _quality,
    _started_at,
    _vod_count_label,
    _when,
)

class WatchAlertsSection(
    EpgGroupMixin,
    MoviesSeriesMixin,
    StreamMonitoringMixin,
    BackgroundRefreshMixin,
    CollapsibleSection,
):
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
        self._start_clock()

    def get_section_id(self):
        return "alerts"

    def create_header(self):
        header = self._build_clickable_header()
        hl = header.layout()
        # The SHARED title label, like every other section. Watch Alerts used
        # to prepend a recolorable status dot here — grey quiet, green when
        # something was new — which was the right idea before the header grew
        # the filled "+N" pill that says the same thing louder and with a
        # number in it. Two indicators for one fact is what the V3 pass keeps
        # removing. Owner: "watch alerts icon could probably go as well, since
        # we have the +1 or whatever filled chip in the header to note what is
        # going on."
        self.title_label = self.make_title_label()
        hl.addWidget(self.title_label)
        hl.addStretch(1)
        # The SAME status widget every other section header uses. Watch Alerts
        # was the one that hand-rolled its count into the title instead.
        hl.addWidget(self.make_status_label())

        hl.addStretch()

        # "Clear all" — acknowledge every new match; shown only when N > 0.
        self._clear_all_btn = QPushButton("Clear all")
        self._clear_all_btn.setFlat(True)
        self._clear_all_btn.setToolTip("Acknowledge all new matches")
        _theme.style(self._clear_all_btn, "LINK_BTN_SM")
        self._clear_all_btn.clicked.connect(self.clearAllAlertsClicked.emit)
        self._clear_all_btn.hide()
        hl.addWidget(self._clear_all_btn)

        # The base class's hooks, which this override had been skipping — which
        # is how Manage / + ended up looking for somewhere else to live.
        self._add_header_actions(hl)
        self._add_explore_link(hl)

        self.main_layout.addWidget(header)

    def _add_header_actions(self, header_layout: "QHBoxLayout") -> None:
        """Manage / + in the SECTION header, left of the Explore → link.

        They govern the whole section — keyword rules and monitored series
        across EPG, Movies & Series and Stream Monitoring alike — so parking
        them on a sub-group's heading said they belonged to that group.
        Owner: "they apply to everything, not just EPG."

        This is the base class's own hook for exactly this, which also retires
        the strip-in-the-body and the re-parenting that kept it on whichever
        sub-header happened to be visible.

        Icon-only, both of them: the header is 300px wide and already carries a
        title, a count and an arrow.

        """

        # Icon-only, like the +. As a text button it did not fit beside the
        # group heading it now shares a line with — "Movies & Series (6) · 2
        # new" truncated to "· 2 ne". The tooltip carries the words.
        # The busy indicator sits with the section's own controls, not on a
        # sub-group heading. It reports on a check that belongs to the whole
        # section, and its old home — the "Movies & Series" header — is being
        # dissolved. Here it also stops being re-parented every refresh.
        self._series_spinner = _icon_utils.busy_spinner(
            None, color=_theme.COLOR_TEXT
        )
        if self._series_spinner is not None:
            self._series_spinner.setToolTip(
                "Checking monitored series for new episodes…"
            )
            # hide() AFTER addWidget: adding a widget to a layout re-parents it,
            # and a re-parented widget takes its new parent's visibility — so
            # hiding first left the indicator showing with nothing running.
            # Added BEFORE the status pill (create_header adds actions, then
            # the pill, then the arrow), so a check starting or finishing never
            # moves the count. Owner: "it disappears so it fucks with the
            # position and order."
            header_layout.addWidget(self._series_spinner)
            self._series_spinner.hide()

        self._manage_btn = QPushButton()
        self._manage_btn.setFixedSize(24, 20)
        self._manage_btn.setToolTip(
            "Manage watch alerts — keyword rules and monitored series"
        )
        _theme.style(self._manage_btn, "PANEL_BTN")
        cursor_affordance.set_clickable(self._manage_btn)

        def _paint_manage() -> str:
            self._manage_btn.setIcon(_icon_utils.resolve_icon(
                _icons.vector_key("manage"), _theme.COLOR_TEXT
            ))
            self._manage_btn.setIconSize(QSize(13, 13))
            return _theme.PANEL_BTN

        _theme.style_fn(self._manage_btn, _paint_manage)
        self._manage_btn.clicked.connect(self.manageWatchForClicked.emit)
        header_layout.addWidget(self._manage_btn)

        self._add_btn = QPushButton()
        self._add_btn.setFixedSize(24, 20)
        self._add_btn.setToolTip("Watch for new content…")
        _theme.style(self._add_btn, "PANEL_BTN")
        cursor_affordance.set_clickable(self._add_btn)

        def _paint_add() -> str:
            self._add_btn.setIcon(_icon_utils.resolve_icon(
                _icons.vector_key("add"), _theme.COLOR_TEXT
            ))
            self._add_btn.setIconSize(QSize(13, 13))
            return _theme.PANEL_BTN

        _theme.style_fn(self._add_btn, _paint_add)
        self._add_btn.clicked.connect(self.addWatchForClicked.emit)
        header_layout.addWidget(self._add_btn)

    def extra_budgeted_lists(self):
        """Movies & Series and Stream Monitoring, fitted from the shared seam.

        Declared here rather than sized at populate time so they are re-fitted
        on every resize like every other list in the rail. Sizing them once,
        when they were repopulated, measured a viewport that had not been laid
        out yet — which is how Movies & Series ended up drawn in a box with
        room for five rows.
        """
        return (
            self.__dict__.get("_vod_list"),
            self.__dict__.get("_retry_list"),
        )

    def reapply_row_budget(self) -> None:
        """Fit as the base class does, then catch the views it skipped.

        The fit has to happen after layout rather than at populate time. This
        hook is called from a zero-timer after a resize, so the views have
        actually been laid out — measuring at populate time reads a viewport
        that does not exist yet and locks in a wrong fixed height, which is how
        rows ended up drawn over each other.

        **Mostly redundant since 2026-09-02, deliberately kept for one case.**
        Removing the "Show N more" mode folded the fit INTO
        ``apply_row_budget`` and ``apply_tree_row_budget``, so the base class
        now sizes all three of these views itself and this loop re-sizes them a
        second time. ``fit_to_rows`` is a pure measure-and-set, so the repeat
        costs one layout pass and changes nothing.

        What it still covers: ``reapply_row_budget`` skips an extra list that
        is not ``isVisible()``, and this does not. A collapsed sub-group's list
        would otherwise keep whatever height it had when it was hidden. Worth
        one honest sentence rather than a silent duplicate — ledger D22.
        """
        super().reapply_row_budget()
        for view in (self.__dict__.get("alerts_tree"),
                     self.__dict__.get("_vod_list"),
                     self.__dict__.get("_retry_list")):
            if view is not None:
                self.fit_to_rows(view)

    def create_content(self):
        from PyQt6.QtWidgets import QHeaderView


        # ── EPG sub-section ────────────────────────────────────────────────
        # Live/upcoming programmes from the EPG watchlist.  Given its own labelled +
        # collapsible sub-header so it sits parallel with the other sub-sections
        # (it previously floated label-less at the top — the inconsistency the
        # consolidation fixes).  Hidden entirely when nothing is airing now/soon.
        self._epg_collapsed = False
        #: EPG group title -> the expand/collapse the USER chose for it.
        #: Only ever written by a click. _apply_expansion's automatic budget
        #: decision may not overrule an entry here — same rule as the sidebar's
        #: _auto_folded: auto may only undo what auto did.
        self._user_expansion: dict[str, bool] = {}
        self._epg_has_rows = False

        epg_hdr_row = QHBoxLayout()
        epg_hdr_row.setContentsMargins(0, 2, 0, 1)
        epg_hdr_row.setSpacing(4)

        # The SAME heading widget the groups inside this section use. It was a
        # QPushButton drawing "{caret} EPG ({count})" — a third way of writing a
        # heading in a section that already had two, and a caret beside a
        # clickable title is a second affordance for one action.
        self._epg_toggle = GroupHeading(
            "EPG", interactive=True,
            tooltip=("Live TV programs and events from your watchlist, airing "
                     "now or soon — click to collapse or expand"),
        )
        self._epg_toggle.clicked.connect(self._toggle_epg)
        epg_hdr_row.addWidget(self._epg_toggle)
        epg_hdr_row.addStretch()

        self._epg_hdr_container = QWidget()
        self._epg_hdr_container.setLayout(epg_hdr_row)
        self._epg_hdr_container.hide()
        self.content_layout.addWidget(self._epg_hdr_container)

        self.alerts_tree = QTreeWidget()
        # R13 mechanism 1, same as the two sub-lists below: the EPG group is
        # budgeted (apply_tree_row_budget) and must never scroll inside the
        # sidebar's own scroll area.
        self.alerts_tree.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.alerts_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.alerts_tree.setHeaderHidden(True)
        self.alerts_tree.setColumnCount(1)
        # No tree indentation and no native indicator: both put EPG rows in a
        # different left column from the Movies/Series rows below, so the
        # section had two left edges. A child row insets ITSELF (see
        # _AlertRow(indent=)) and the disclosure caret lives in the row's own
        # left slot, beside play and new, which is where the design puts it.
        self.alerts_tree.setIndentation(0)
        self.alerts_tree.setRootIsDecorated(False)
        self.alerts_tree.header().setStretchLastSection(True)
        self.alerts_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.alerts_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.alerts_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.alerts_tree.customContextMenuRequested.connect(self._on_context_menu)
        make_seamless(self.alerts_tree)
        # Expanding + equal stretch (shared by all three sub-lists) so the section's
        # surplus vertical space is DISTRIBUTED among them rather than pooling in one
        # ballooning list or a dead gap.  No maximumHeight: the stretch share bounds
        # the tree within the splitter pane, and a long watchlist scrolls internally.
        # Sized to CONTENT, not given an equal expanding share. Three widgets
        # each claiming a third of the panel left ~150px of dead space between
        # EPG and Movies whenever one was short — they read as ONE list, so
        # each takes the height its rows need and the column packs upward.
        self.alerts_tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.alerts_tree.hide()
        self.content_layout.addWidget(self.alerts_tree)

        self._update_epg_toggle_label(0)
        # ── end EPG sub-section ────────────────────────────────────────────

        # ── Movies & Series ───────────────────────────────────────────────
        # No wrapper heading. It used to carry one ("Movies & Series (13)"),
        # which read as a PEER of the "Watching for" and "Series" headings it
        # actually CONTAINS — same weight, nested meaning. Dissolving it leaves
        # four groups at one level, which is the approved design: EPG, Watching
        # for, Series, Stream Monitoring.
        #
        # Nothing was lost with it. Its collapse state is now the two inner
        # headings' own (below); its spinner moved to the section header, which
        # is what the check actually belongs to; and its "N new" label
        # duplicated the count the section header badge already shows.
        self._series_collapsed = False   # the "Series" group heading toggle
        self._keyword_collapsed = False  # the "Watching for" group heading toggle
        self._vod_list = QListWidget()
        # R13 mechanism 1 — no nested scrollbars. This sub-list still had one:
        # a scroll area inside the sidebar's own, in a band ~35px tall, which is
        # a window too small to read through. It now shows what fits and ends
        # with "+N more", like every other list in the rail.
        self._vod_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._vod_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._vod_list.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        # Equal stretch with the EPG tree so Movies & Series always gets its fair share
        # of the section's height (never starved to a sliver) and grows to help fill the
        # pane instead of leaving a gap.  A long list scrolls within its share.
        self._vod_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        _theme.style_fn(self._vod_list, lambda: f"QListWidget {{ font-size: {_theme.FONT_MD}; }}")
        make_seamless(self._vod_list)
        cursor_affordance.set_clickable(self._vod_list)
        self._vod_list.itemClicked.connect(self._on_vod_item_clicked)
        self._vod_list.itemDoubleClicked.connect(self._on_vod_item_double_clicked)
        self._vod_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._vod_list.customContextMenuRequested.connect(self._on_vod_context_menu)
        self._vod_list.hide()
        self.content_layout.addWidget(self._vod_list)

        self._update_vod_toggle_label(0)
        # ── end Movies & Series sub-section ────────────────────────────────

        # Stream Monitoring collapsible sub-section
        self._retry_collapsed = False

        retry_hdr_row = QHBoxLayout()
        retry_hdr_row.setContentsMargins(0, 2, 0, 1)
        retry_hdr_row.setSpacing(4)

        # The standalone "i" glyph is gone: it was a control that did nothing
        # but hold a tooltip, sitting beside a heading that already has one.
        # Its text lives here now, so nothing is lost and there is one fewer
        # thing on the row to wonder about.
        self._retry_toggle = GroupHeading(
            "Stream Monitoring", interactive=True,
            tooltip=(
                "Streams that previously failed to play, re-checked "
                "periodically.\nYou get a notification when one becomes "
                "available again.\nDouble-click an entry to retry it now.\n"
                "Click this heading to collapse or expand."
            ),
        )
        self._retry_toggle.clicked.connect(self._toggle_stream_monitoring)
        retry_hdr_row.addWidget(self._retry_toggle)

        retry_hdr_row.addStretch()

        self._retry_hdr_container = QWidget()
        self._retry_hdr_container.setLayout(retry_hdr_row)
        self._retry_hdr_container.hide()
        self.content_layout.addWidget(self._retry_hdr_container)

        self._retry_list = QListWidget()
        # R13 mechanism 1 — no nested scrollbars. This sub-list still had one:
        # a scroll area inside the sidebar's own, in a band ~35px tall, which is
        # a window too small to read through. It now shows what fits and ends
        # with "+N more", like every other list in the rail.
        self._retry_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._retry_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._retry_list.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        # Matching Expanding + equal stretch so Stream Monitoring shares the pane on the
        # same footing as the other two sub-lists.
        self._retry_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        _theme.style_fn(self._retry_list, lambda: f"QListWidget {{ font-size: {_theme.FONT_MD}; }}")
        make_seamless(self._retry_list)
        self._retry_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._retry_list.customContextMenuRequested.connect(self._on_retry_context_menu)
        self._retry_list.itemDoubleClicked.connect(self._on_retry_double_clicked)
        self._retry_list.hide()

        self.content_layout.addWidget(self._retry_list)

        self._update_retry_toggle_label(0)

        # ONE trailing stretch, and the views carry none. They used to share the
        # surplus equally with an Expanding policy, which was right while they
        # were three visibly separate boxes — as one flat list it left ~150px of
        # dead space between EPG and Movies whenever a view was short. Each view
        # sizes to its rows (_fit_to_rows) and the slack collects here.
        self.content_layout.addStretch(1)
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






    # ------------------------------------------------------------------
    # Movies & Series helpers
    # ------------------------------------------------------------------



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
        # "+2", not "2 new" — the design's header pill. The word is redundant
        # inside a green pill that only ever appears when something is new, and
        # it made the pill wide enough to crowd the buttons beside it.
        return f"+{total}" if total else ""















    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------





    # ------------------------------------------------------------------
    # BackgroundRefreshMixin hooks
    # ------------------------------------------------------------------





















