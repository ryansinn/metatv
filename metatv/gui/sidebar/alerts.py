"""WatchAlertsSection and its _AlertRow helper widget."""

import html

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QAbstractScrollArea, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem,
)
from datetime import datetime
from typing import NamedTuple

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from loguru import logger

from metatv.core.epg_utils import now_utc as _now_utc, is_local_today as _is_local_today, to_local as _to_local
from metatv.gui import cursor_affordance
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import series_alert_identity as _series_identity
from metatv.gui import theme as _theme
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.relative_time import humanize_remaining, humanize_until
from metatv.gui.sidebar.alerts_rows import (
    news_chip_sheet,
    _AlertRow,
    _name_with_dim_suffix_html,
    _VodAlertRow,
)
from metatv.gui.sidebar.base import (
    CollapsibleSection, GroupHeading, _fmt_channel_name,
)

# Item-data roles for the Movies & Series list (_vod_list).  UserRole stays the
# rule_created id for keyword-rule rows (existing click/menu code reads it); the
# extra roles tag the item kind and, for series rows, the series channel id.
_ROLE_KIND = Qt.ItemDataRole.UserRole + 5        # "rule" | "heading" | "series"
#: Height assumed for a row that never had an explicit size hint set —
#: a plain text item rather than one carrying a widget.
_ROW_FALLBACK_H = 22

_ROLE_SERIES_ID = Qt.ItemDataRole.UserRole + 6   # series_channel_id (series rows)


def _quality(airing) -> str:
    """The airing's quality token, or "" — sibling of :func:`_when`."""
    return airing[6] if len(airing) > 6 else ""


def _started_at(airing) -> "datetime | None":
    """The airing's start, or ``None`` — sibling of :func:`_when`.

    Same tolerance for a hand-built short tuple from a test seam.
    """
    return airing[5] if len(airing) > 5 else None


def _when(airing) -> "datetime | None":
    """The airing's timestamp, or ``None`` for a record that predates the field.

    Not defensive programming for its own sake: ``_load_rows`` always produces
    an :class:`_Airing`, but this dict is a documented seam that tests build by
    hand, and a four-element tuple from one of those should render a row that
    simply does not self-refresh rather than raise.
    """
    return airing[4] if len(airing) > 4 else None


class _Airing(NamedTuple):
    """One airing of one programme on one channel, as ``_load_rows`` hands it on.

    A NamedTuple rather than a bare tuple because this grew a fifth field and
    the plain-tuple version broke five tests that unpacked it — positional
    tuples do not survive gaining a member. Index access still works, so the
    existing ``a[1]`` / ``a[2]`` call sites are untouched, and ``when``
    defaults so a four-field construction stays legal.

    Attributes:
        sort_key: Minutes-left for a live airing, epoch seconds for an upcoming
            one — whichever orders that list.
        time_text: The rendered time as of load. Correct only for that instant;
            the row recomputes it on the tick (see ``_AlertRow.refresh_time``).
        channel: Display name of the channel.
        channel_db_id: The channel's DB id, for play/select.
        when: ``stop_time`` for a live airing, ``start_time`` for an upcoming
            one, UTC-naive. This is what makes the row refreshable and what
            ``_schedule_boundary`` aims its timer at.
        started_at: ``start_time`` for a LIVE airing, so the row can show how
            far through the programme is. ``when`` alone gives the end but not
            the duration, and 30 minutes left means something different on a
            half-hour show than on a three-hour one. ``None`` on upcoming rows,
            which have not started.
    """

    sort_key: float
    time_text: str
    channel: str
    channel_db_id: str
    when: "datetime | None" = None
    started_at: "datetime | None" = None
    quality: str = ""

# Row budget (px) for _apply_expansion()'s "expand every group only if the fully
# expanded list still fits a compact height" decision.  It is NOT a widget maximum:
# the three sub-lists share the section's height via equal layout stretch (see
# create_content), so the EPG tree is bounded by its stretch share of the splitter
# pane, not by a hard cap.  A hard cap was deliberately dropped — capping the tree to
# its content left the section's surplus space pooling as a blank gap at the bottom.
_ALERTS_TREE_AUTOEXPAND_BUDGET = 320


def _alerts_title_html(title: str, count: int) -> str:
    """Rich-text for the Alerts header: a recolorable status dot + title + count.

The DOT carries the state; the title does not. Colouring the whole title
    green and appending " (N)" made the header read as a different section
    when something was new, and the count then had no chip of its own — the
    approved design has a plain white title beside a filled green pill, which
    is what ``make_status_label`` already renders for every other section.

        - Quiet (count == 0): grey dot, plain title.
        - Active (count > 0): green dot, plain title. The count lives in the
          header's status label.

    Args:
        title: The section title (always "Watch Alerts").
        count: Number of unviewed watch-for matches across all rules.

    Returns:
        An HTML string for :meth:`QLabel.setText` (rich-text format).
    """
    dot_color = _theme.COLOR_OK if count > 0 else _theme.COLOR_MUTED
    return (
        f'<span style="color:{dot_color}">{_icons.status_dot_icon}</span> '
        f'<b><span style="color:{_theme.COLOR_TEXT_HI}">{title}</span></b>'
    )


def _vod_count_label(unviewed: int, count: int) -> str:
    """Right-aligned count text for a watch-for rule row.

    The count is a CHIP, so it carries no leading "·". That dot was a separator
    from when the count was loose text sharing a line with the title — inside a
    chip it reads as part of the number.

        - unviewed > 0:             "+{unviewed}"  (a filled news pill)
        - unviewed == 0, count > 0: "{count}"
        - count == 0:               ""

    Args:
        unviewed: Unviewed match count for this rule.
        count: Total match count for this rule.

    Returns:
        The count label text (possibly empty).
    """
    if unviewed > 0:
        # "+5", not "5 of 20": the chip is narrow, and how many are NEW is the
        # fact worth the space. The total is in the row's tooltip.
        return f"+{unviewed}"
    if count > 0:
        return str(count)
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
        self._start_clock()

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
        """Movies & Series and Stream Monitoring, budgeted from the shared seam.

        Declared here rather than budgeted at populate time so they are re-fitted
        on every resize like every other list in the rail. Budgeting them once,
        when they were repopulated, measured a viewport that had not been laid
        out yet — which is how Movies & Series ended up showing a divider and
        "+ 12 more →" in a box with room for five rows.
        """
        return (
            (self.__dict__.get("_vod_list"), self.manageWatchForClicked.emit),
            (self.__dict__.get("_retry_list"), self.manageWatchForClicked.emit),
        )

    def reapply_row_budget(self) -> None:
        """Budget as the base class does, then size each view to its rows.

        The fit has to happen HERE rather than only at populate time. This hook
        is called from a zero-timer after a resize, so the views have actually
        been laid out — measuring at populate time reads a viewport that does
        not exist yet and locks in a wrong fixed height, which is how rows
        ended up drawn over each other.
        """
        super().reapply_row_budget()
        for view in (self.__dict__.get("alerts_tree"),
                     self.__dict__.get("_vod_list"),
                     self.__dict__.get("_retry_list")):
            if view is not None:
                self.fit_to_rows(view)

    @staticmethod
    def _make_seamless(view) -> None:
        """Strip a sub-list's frame and ground so it reads as part of the section.

        The section is built from three widgets — an EPG tree and two lists —
        stacked in one panel. Each drew its own frame and background, so the
        approved single flat surface arrived as THREE BORDERED BOXES with
        headings floating between them. Owner: "that doesn't look like the
        design we planned."

        They are one list to the reader; they are three only to the layout.
        """
        from PyQt6.QtWidgets import QFrame

        view.setFrameShape(QFrame.Shape.NoFrame)
        view.viewport().setAutoFillBackground(False)
        # LIST_SELECTION_QSS is APPENDED, not replaced. style_fn hands Qt one
        # sheet, so returning only the seamless rules wiped the selection rules
        # apply_list_selection had put there — leaving Qt's raw blue highlight
        # with unreadable text on it. Composing both is the whole job here.
        _theme.style_fn(view, lambda: (
            f"QAbstractScrollArea, QListWidget, QTreeWidget {{"
            f" background: transparent; border: none;"
            f" font-size: {_theme.FONT_MD}; color: {_theme.COLOR_TEXT_HI}; }}"
            + _theme.LIST_SELECTION_QSS
        ))

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
        self.alerts_tree.setIndentation(12)
        self.alerts_tree.header().setStretchLastSection(True)
        self.alerts_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.alerts_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.alerts_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.alerts_tree.customContextMenuRequested.connect(self._on_context_menu)
        _theme.apply_list_selection(self.alerts_tree)
        self._make_seamless(self.alerts_tree)
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
        _theme.apply_list_selection(self._vod_list)
        self._make_seamless(self._vod_list)
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
        retry_hdr_row.setContentsMargins(0, 4, 0, 2)
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
        _theme.apply_list_selection(self._retry_list)
        self._make_seamless(self._retry_list)
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

    def _update_epg_toggle_label(self, count: int) -> None:
        """Refresh the EPG heading's count."""
        self._epg_toggle.set_count(count or None)

    def _toggle_epg(self) -> None:
        self._epg_collapsed = not self._epg_collapsed
        self.alerts_tree.setVisible(not self._epg_collapsed and self._epg_has_rows)
        self._update_epg_toggle_label(self.alerts_tree.topLevelItemCount())

    # ------------------------------------------------------------------
    # Movies & Series helpers
    # ------------------------------------------------------------------

    def _update_vod_toggle_label(self, count: int) -> None:
        """Recompute the section-level "new" totals after a VOD refresh.

        Named for a toggle that no longer exists — kept as the one place that
        recomputes ``_firing_count`` + ``_series_new_count`` for the section
        header's badge, which every caller already routes through.
        """
        firing = self.__dict__.get("_firing_count")
        if firing is None:
            firing = getattr(
                self.config, "get_rules_with_new_matches_count", lambda: 0
            )()
        self._new_total = firing + self.__dict__.get("_series_new_count", 0)

    def budgeted_tree(self):
        """Watch Alerts fits its top-level groups, not a flat list.

        This is the section R13 names directly — 173px subdivided four ways,
        each sub-group scrolling in about 35px.
        """
        return self.__dict__.get("alerts_tree")

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
        visible instead of silently changing state underfoot.

        A real spinning widget (``icon_utils.busy_spinner``) rather than the
        static ``⟳`` plus the word "checking…" this used to append to the
        label. ``sidebar/sources.py``'s ``set_busy``/``set_epg_refreshing``
        still use the static idiom and should move to the same helper.
        """
        self._series_checking = busy
        spinner = self.__dict__.get("_series_spinner")
        if spinner is not None:
            spinner.setVisible(busy)
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

    def _toggle_series_group(self) -> None:
        """Collapse/expand the monitored-series group."""
        self._series_collapsed = not self._series_collapsed
        self.refresh_vod_rules()

    def _toggle_keyword_group(self) -> None:
        """Collapse/expand the keyword watch-for group.

        New: this heading used to be ``NoItemFlags`` and inert while the Series
        heading beside it — visually identical — collapsed on click. One
        grammar means both behave the same way.
        """
        self._keyword_collapsed = not self._keyword_collapsed
        self.refresh_vod_rules()

    def _add_group_heading(self, text: str, count: int | None = None, *,
                           on_click=None, tooltip: str = "") -> None:
        """Add one sub-group heading to the VOD list.

        The item is always ``NoItemFlags`` — a heading is chrome, so the row
        budget skips it and it can never be selected — and any click comes from
        the WIDGET's signal rather than from item flags. That split is what
        removes the old inconsistency: the two em-dash dividers looked
        identical, but one was clickable because it had flags and the other was
        not because it did not.
        """
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        # Tagged so the context-menu handler can recognise a heading. NoItemFlags
        # alone is not enough: itemAt() still returns it under the cursor, and
        # without a kind it would fall through to the keyword-rule branch with a
        # null rule id.
        item.setData(_ROLE_KIND, "heading")
        self._vod_list.addItem(item)
        heading = GroupHeading(
            text, count, interactive=on_click is not None, tooltip=tooltip
        )
        if on_click is not None:
            heading.clicked.connect(on_click)
        item.setSizeHint(QSize(0, heading.sizeHint().height()))
        self._vod_list.setItemWidget(item, heading)

    def _toggle_series_group(self) -> None:
        """Collapse/expand the monitored-series group."""
        self._series_collapsed = not self._series_collapsed
        self.refresh_vod_rules()

    def _toggle_keyword_group(self) -> None:
        """Collapse/expand the keyword watch-for group.

        New: this heading used to be ``NoItemFlags`` and inert while the Series
        heading beside it — visually identical — collapsed on click. One
        grammar means both behave the same way.
        """
        self._keyword_collapsed = not self._keyword_collapsed
        self.refresh_vod_rules()

    def _add_group_heading(self, text: str, count: int | None = None, *,
                           on_click=None, tooltip: str = "") -> None:
        """Add one sub-group heading to the VOD list.

        The item is always ``NoItemFlags`` — a heading is chrome, so the row
        budget skips it and it can never be selected — and any click comes from
        the WIDGET's signal rather than from item flags. That split is what
        removes the old inconsistency: the two em-dash dividers looked
        identical, but one was clickable because it had flags and the other was
        not because it did not.
        """
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        # Tagged so the context-menu handler can recognise a heading. NoItemFlags
        # alone is not enough: itemAt() still returns it under the cursor, and
        # without a kind it would fall through to the keyword-rule branch with a
        # null rule id.
        item.setData(_ROLE_KIND, "heading")
        self._vod_list.addItem(item)
        heading = GroupHeading(
            text, count, interactive=on_click is not None, tooltip=tooltip
        )
        if on_click is not None:
            heading.clicked.connect(on_click)
        item.setSizeHint(QSize(0, heading.sizeHint().height()))
        self._vod_list.setItemWidget(item, heading)

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
            self._vod_list.hide()
            self._recompute_empty()
            return

        type_icons = {"movie": _icons.movie_icon, "series": _icons.series_icon}
        _unviewed_for = getattr(
            self.config, "get_vod_rule_unviewed_count", lambda _c: 0
        )

        # ── "Watching for" group heading ───────────────────────────────────
        # Only shown when BOTH groups are present — with a single group the
        # sub-section toggle already names it, so a heading would be redundant.
        # It is a collapse toggle like every other group heading; it used to be
        # NoItemFlags and inert while looking identical to the Series one.
        if rules and series:
            self._add_group_heading(
                "Movies", len(rules),
                on_click=self._toggle_keyword_group,
                tooltip="Titles you are watching for — click to collapse or expand",
            )

        # ── Keyword rules ─────────────────────────────────────────────────
        # Skipped wholesale when the group is collapsed — but only when its
        # heading is actually drawn (headings appear only with BOTH groups
        # present), or a collapsed flag would hide rows with no way back.
        for rule in ([] if (self._keyword_collapsed and rules and series) else rules):
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
            # No leading emoji: the GROUP heading above already says what these
            # are, and a glyph repeated on every row is the redundancy the type
            # icons were supposed to remove, not add.
            count_text = _vod_count_label(unviewed, count)
            count_style = (
                news_chip_sheet() if unviewed > 0 else _theme.SIDEBAR_CHIP_YEAR
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
            row = _VodAlertRow("", text, count_text, count_style,
                               is_new=unviewed > 0)
            item.setSizeHint(row.sizeHint())
            self._vod_list.setItemWidget(item, row)

        # ── "Series" group heading + monitored-series rows ────────────────
        # The divider appears only when there ARE monitored series; it is a
        # collapse toggle (default expanded) so a heavy monitorer can tuck the
        # idle list away.
        if series:
            self._add_group_heading(
                "Series", len(series),
                on_click=self._toggle_series_group,
                tooltip=("Series you're monitoring for new episodes — "
                         "click to collapse or expand"),
            )

            if not self._series_collapsed:
                for s in series:
                    cid, title, unseen = s["cid"], s["title"], s["unseen"]
                    has_new = unseen > 0
                    # New-episode series get 🆕 + a green "+N eps" count (colour PLUS
                    # the icon/count, never colour alone); idle ones show 📺, no count.
                    ep_word = "ep" if unseen == 1 else "eps"
                    # "+3", not "+3 eps": the chip is narrow and the group it
                    # sits under is called Series, so the unit is already said.
                    # The tooltip still spells it out.
                    count_text = f"+{unseen}" if has_new else ""
                    count_style = (
                        news_chip_sheet() if has_new else _theme.SIDEBAR_CHIP_YEAR
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
                        "", title, count_text, count_style,
                        suffix=s.get("suffix", ""), is_new=has_new,
                        marker=s.get("episode_code", ""),
                    )
                    item.setSizeHint(row.sizeHint())
                    self._vod_list.setItemWidget(item, row)

        self._update_vod_toggle_label(len(rules) + len(series))
        self._vod_list.show()
        QTimer.singleShot(0, self.reapply_row_budget)
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
        # Group headings no longer arrive here: they are NoItemFlags items whose
        # GroupHeading widget emits its own clicked signal (see
        # _add_group_heading), so an unselectable item cannot reach this handler.
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
        if kind == "heading":
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
        """Refresh the Stream Monitoring heading's count."""
        self._retry_toggle.set_count(count or None)

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
                    session.query(
                        ChannelDB.id,
                        ChannelDB.name,
                        ChannelDB.detected_title,
                        ChannelDB.detected_year,
                        ChannelDB.detected_region,
                        ChannelDB.detected_quality,
                    )
                    .filter(ChannelDB.id.in_(all_channel_ids))
                    .all()
                )
                # The ingestion-computed fields, not just the raw name. Watch
                # Alerts was the one sidebar surface still rendering the
                # provider's string verbatim, which is why a channel showed as
                # "KANAL 4 [DNK] [HEVC]" — brackets and all — where every other
                # list renders the bare title with the tags as tags.
                channel_names = {
                    r[0]: {
                        "name": r[1], "detected_title": r[2],
                        "detected_year": r[3], "detected_region": r[4],
                        "detected_quality": r[5],
                    }
                    for r in rows
                }

            now = _now_utc()

            def _title_key(title: str) -> str:
                return " ".join(title.casefold().replace("&", "and").split())

            def _channel_display(prog) -> tuple[str, str]:
                """The row's channel text, and its quality token separately.

                The quality is pulled OUT of the formatted name so the row can
                draw it as a chip beside the title — a claim about this copy —
                rather than leaving "[RAW]" inside the string.
                """
                rec = channel_names.get(prog.channel_db_id)
                if rec is None:
                    return _fmt_channel_name(prog.channel_epg_id or "Unknown"), ""
                quality = rec["detected_quality"] or ""
                return _fmt_channel_name(
                    rec["name"],
                    detected_title=rec["detected_title"],
                    detected_year=rec["detected_year"],
                    detected_region=rec["detected_region"],
                    detected_quality=None,       # drawn as a chip instead
                ), quality

            # Unified per-title groups — upcoming for a live title folds under WATCH NOW,
            # preventing the same show from appearing in both sections simultaneously.
            # live_groups: key -> {'live': [...], 'upcoming': [...], 'title': str}
            # upcoming_only: key -> {'airings': [...], 'title': str}
            live_groups: dict[str, dict] = {}
            upcoming_only: dict[str, dict] = {}

            for _pattern, progs in live_data.items():
                for prog in progs:
                    ch_display, ch_quality = _channel_display(prog)
                    mins_left = max(0, int((prog.stop_time - now).total_seconds() / 60))
                    time_str = humanize_remaining(prog.stop_time, now)
                    key = _title_key(prog.title)
                    if key not in live_groups:
                        live_groups[key] = {'live': [], 'upcoming': [], 'title': prog.title}
                    # stop_time rides along so the 30s repaint tick can recompute
                    # this row's text without a re-query — the string above is
                    # only ever correct for the instant it was built.
                    live_groups[key]['live'].append(
                        _Airing(mins_left, time_str, ch_display,
                                prog.channel_db_id, prog.stop_time,
                                prog.start_time, ch_quality)
                    )

            for _pattern, progs in upcoming_data.items():
                for prog in progs:
                    ch_display, ch_quality = _channel_display(prog)
                    time_str = humanize_until(
                        prog.start_time, now,
                        to_local=_to_local, is_local_today=_is_local_today,
                    )
                    key = _title_key(prog.title)
                    ts = prog.start_time.timestamp()
                    if key in live_groups:
                        live_groups[key]['upcoming'].append(
                            _Airing(ts, time_str, ch_display,
                                    prog.channel_db_id, prog.start_time,
                                    None, ch_quality)
                        )
                    else:
                        if key not in upcoming_only:
                            upcoming_only[key] = {'airings': [], 'title': prog.title}
                        upcoming_only[key]['airings'].append(
                            _Airing(ts, time_str, ch_display,
                                    prog.channel_db_id, prog.start_time,
                                    None, ch_quality)
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

        def _wire_row(row: _AlertRow, channel_db_id: str) -> None:
            """Connect an _AlertRow's signals to the section's public signals."""
            row.play_clicked.connect(
                lambda _=False, cid=channel_db_id: self.alertClicked.emit(cid)
            )
            row.row_clicked.connect(
                lambda cid=channel_db_id: self.channel_selected.emit(cid)
            )

        def _add_parent(title, time_str, _extra=0, when=None, live=False,
                        started_at=None) -> "QTreeWidgetItem":
            """The programme row that expands to its airings.

            A real row widget, not a text item reading
            "Title  ·  3m left  +2". The dot was a separator asked to do a
            layout's job, and a text item cannot carry a chip, a progress bar
            or the left slot every other row in this section has.
            """
            hdr = QTreeWidgetItem()
            hdr.setFlags(hdr.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.alerts_tree.addTopLevelItem(hdr)
            # No "+N" chip. The caret already says the row expands, and the
            # count of what is behind it is the one fact you get for free by
            # opening it — the approved render carries only the time.
            row = _AlertRow(title, time_str, self.config, when=when, live=live,
                            started_at=started_at, chip_time=True)
            hdr.setSizeHint(0, QSize(0, row.sizeHint().height()))
            self.alerts_tree.setItemWidget(hdr, 0, row)
            return hdr

        def _add_child(parent_item, ch_name, time_str, channel_db_id, title,
                       when=None, live=False, started_at=None,
                       quality="") -> None:
            child = QTreeWidgetItem()
            child.setData(0, Qt.ItemDataRole.UserRole, channel_db_id)
            child.setToolTip(0, f"{title}\n{ch_name}")
            parent_item.addChild(child)
            row = _AlertRow(ch_name, time_str, self.config, when=when, live=live,
                            started_at=started_at, quality=quality)
            _wire_row(row, channel_db_id)
            self.alerts_tree.setItemWidget(child, 0, row)

        def _add_direct(ch_name, time_str, channel_db_id, title,
                        when=None, live=False, started_at=None,
                       quality="") -> None:
            """Single-channel item: header IS the row — no expand arrow.
            Shows the show title; channel name is the tooltip."""
            item = QTreeWidgetItem()
            item.setData(0, Qt.ItemDataRole.UserRole, channel_db_id)
            item.setToolTip(0, ch_name)
            self.alerts_tree.addTopLevelItem(item)
            row = _AlertRow(title, time_str, self.config, when=when, live=live,
                            started_at=started_at, quality=quality)
            _wire_row(row, channel_db_id)
            self.alerts_tree.setItemWidget(item, 0, row)

        if live_groups:
            for key, grp in sorted(live_groups.items(),
                                   key=lambda kv: min(a[0] for a in kv[1]['live'])):
                title = grp['title']
                live_items = sorted(grp['live'], key=lambda a: a[0])
                up_items   = sorted(grp['upcoming'], key=lambda a: a[0])
                all_items  = live_items + up_items
                if len(all_items) == 1:
                    a = all_items[0]
                    _add_direct(a[2], a[1], a[3], title, _when(a),
                                live=a in live_items, started_at=_started_at(a))
                else:
                    lead = live_items[0]
                    hdr = _add_parent(
                        title, lead[1], len(all_items) - 1,
                        when=_when(lead), live=True, started_at=_started_at(lead),
                    )
                    for a in live_items[:10]:
                        _add_child(hdr, a[2], a[1], a[3], title, _when(a), live=True,
                                   started_at=_started_at(a),
                                   quality=_quality(a))
                    for a in up_items[:5]:
                        _add_child(hdr, a[2], a[1], a[3], title, _when(a), live=False,
                                   quality=_quality(a))

        if upcoming_only:
            for key, grp in sorted(upcoming_only.items(),
                                   key=lambda kv: min(a[0] for a in kv[1]['airings'])):
                title = grp['title']
                airings = sorted(grp['airings'], key=lambda a: a[0])
                if len(airings) == 1:
                    a = airings[0]
                    _add_direct(a[2], a[1], a[3], title, _when(a), live=False)
                else:
                    lead = airings[0]
                    hdr = _add_parent(
                        title, lead[1], len(airings) - 1, when=_when(lead),
                    )
                    for a in airings[:10]:
                        _add_child(hdr, a[2], a[1], a[3], title, _when(a), live=False,
                                   quality=_quality(a))

        self._reveal_epg_subsection()
        self.set_empty(False)
        QTimer.singleShot(0, self._apply_expansion)
        QTimer.singleShot(0, self.reapply_row_budget)
        self._schedule_boundary(live_groups, upcoming_only)

    #: How often the visible rows recompute their own time text. Cheap by
    #: construction: no query, no network, just arithmetic against timestamps
    #: the rows already hold.
    TICK_MS = 30_000

    def _start_clock(self) -> None:
        """Begin the 30-second repaint tick, once.

        Parented to ``self`` so Qt destroys it with the section — a timer is not
        a background pool and does not want a cleanup-registry entry, but it
        must not outlive the widget it repaints.
        """
        if "_clock" in self.__dict__:
            return
        self._clock = QTimer(self)
        self._clock.setInterval(self.TICK_MS)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    def set_playing(self, channel_id: str | None) -> None:
        """Light the play marker on whichever row is the thing now playing.

        Fed by the same playback-health poll that drives
        ``details_pane.set_playing`` (main_window_streaming._notify_details_playing),
        so the sidebar and the details pane can never disagree about what is on —
        one source, two readers, rather than a second thing that also tries to
        track playback.

        Args:
            channel_id: The channel now playing, or ``None`` to clear.
        """
        if "alerts_tree" not in self.__dict__:
            return
        for item, row in self._iter_rows():
            row.set_playing(
                channel_id is not None
                and item.data(0, Qt.ItemDataRole.UserRole) == channel_id
            )

    def _iter_rows(self):
        """Every (item, _AlertRow) pair in the EPG tree, parents and children."""
        tree = self.alerts_tree
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            widget = tree.itemWidget(top, 0)
            if isinstance(widget, _AlertRow):
                yield top, widget
            for j in range(top.childCount()):
                child = top.child(j)
                w = tree.itemWidget(child, 0)
                if isinstance(w, _AlertRow):
                    yield child, w

    def _tick(self) -> None:
        """Refresh every visible row's time text against the current instant.

        This is the half of "staying current" that needs no data: a programme's
        remaining time and a countdown to one starting are pure functions of
        ``now`` and a timestamp already in memory. Membership — which rows
        belong at all — is the other half, and it is handled by
        :meth:`_schedule_boundary` instead of by polling here.

        Skipped entirely while collapsed: repainting rows nobody can see is
        the one cost this design cannot justify.
        """
        # ``is_collapsed`` is an ATTRIBUTE, and read via __dict__ rather than
        # hasattr: on a test double built with __new__ a missing Qt attribute
        # raises RuntimeError, which hasattr does not absorb.
        if self.__dict__.get("is_collapsed") or "alerts_tree" not in self.__dict__:
            return
        now = _now_utc()
        for _item, row in self._iter_rows():
            row.refresh_time(now)

    def _schedule_boundary(self, live_groups: dict, upcoming_only: dict) -> None:
        """Reload once, at the next instant the LIST ITSELF changes.

        A row leaves WATCH NOW when its ``stop_time`` passes and enters when its
        ``start_time`` arrives. Both instants are already known from the rows
        just loaded, so the correct thing is a single-shot timer aimed at the
        earliest of them — not a poll, which either wastes queries or leaves a
        finished programme on screen for up to a full interval. This is the bug
        the owner reported: a row reading "in 13m" that was already playing.

        Rescheduled on every populate, so the timer always points at the next
        boundary rather than a stale one.
        """
        now = _now_utc()
        boundaries = [
            _when(a)
            for grp in live_groups.values()
            for a in (*grp["live"], *grp["upcoming"])
            if _when(a) is not None
        ] + [
            _when(a)
            for grp in upcoming_only.values()
            for a in grp["airings"]
            if _when(a) is not None
        ]
        future = [b for b in boundaries if b > now]
        if "_boundary" in self.__dict__:
            self._boundary.stop()
        if not future:
            return
        secs = max(1.0, (min(future) - now).total_seconds())
        # Qt's int millisecond ceiling is ~24.8 days; a boundary further out
        # than that would overflow to a negative interval and fire immediately.
        secs = min(secs, 6 * 60 * 60)
        self._boundary = QTimer(self)
        self._boundary.setSingleShot(True)
        self._boundary.timeout.connect(self.refresh)
        self._boundary.start(int(secs * 1000) + 1000)

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
