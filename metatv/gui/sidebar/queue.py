"""WatchQueueSection — user's ordered watch queue."""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSizePolicy, QListWidget, QListWidgetItem,
    QGraphicsOpacityEffect, QLineEdit,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.chip_row import (
    CHIP_LANG, CHIP_QUALITY, CHIP_YEAR, build_chip_row, episode_code,
    media_icon_role, quality_word, sidebar_meta_line,
)
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection, style_group_heading

_ROLE_AVAILABLE   = Qt.ItemDataRole.UserRole + 1
_ROLE_SEARCH_TITLE = Qt.ItemDataRole.UserRole + 2
# Every row (plain queue entry OR Alerts Matched) carries the SAME harmonized
# UserRole payload shape: a dict keyed by "grain" —
#   "channel"        -> {"grain": "channel", "channel_id": ...}
#   "episode"        -> {"grain": "episode", "episode_id": ..., "channel_id": ...}
#   "matched_channel" -> {"grain": "matched_channel", "channel_id": ...}
#   "matched_series"  -> {"grain": "matched_series", "channel_id": ...}
# Every reader (double-click, selection, context menu) branches on
# payload["grain"] — one shape, all readers (Wave 3 click-semantics
# harmonization; previously matched rows carried a bare id + a separate
# _ROLE_ROW_KIND role, a known trap flagged in review).

_UNAVAILABLE_TOOLTIP = "Source unavailable — double-click to find this on another source."


class _FilterGroup:
    """One rendered header plus its rows, so the filter can hide/count them.

    Holds the row's searchable text next to the item rather than stashing it in
    an item role: the filter then needs nothing from Qt but ``setHidden``, which
    keeps this testable against the shared skeleton section in conftest.
    """

    __slots__ = ("header", "bare_label", "show_count", "rows")

    def __init__(self, header, bare_label: str, show_count: bool):
        self.header = header
        self.bare_label = bare_label      # "Never Watched"
        self.show_count = show_count      # does the unfiltered header carry (N)?
        self.rows: list[tuple[object, str]] = []   # (item, lowercased haystack)

    def unfiltered_text(self) -> str:
        """Header text with no filter applied.

        Derived from the CURRENT row count rather than frozen at render time, so
        an in-place removal leaves the header honest without a full repopulate.
        """
        if not self.show_count:
            return self.bare_label
        return f"{self.bare_label} ({len(self.rows)})"


def _haystack(*parts: str | None) -> str:
    """Lowercased text a row is matched against, from explicitly-passed fields.

    Callers pass both names for a queue entry because they can differ:
    ``search_title`` is the ingestion-cleaned ``detected_title`` while
    ``channel_name`` is what the provider called it when queued, and the user
    may remember either. The year goes in so "1999" finds what you queued from
    that year.
    """
    return " ".join(p for p in parts if p).lower()


class WatchQueueSection(BackgroundRefreshMixin, CollapsibleSection):
    """Sidebar section showing the user's ordered watch queue."""

    MIN_ROWS: int = 5

    # Uses the base ``create_header``, which grows the shared "Explore →" link.
    EXPLORE_KEY = "queue"

    itemDoubleClicked             = pyqtSignal(str)        # channel_id (channel-grain entries)
    episodeActivated              = pyqtSignal(str)        # episode_id — double-click on an episode-grain entry
    itemSelected                  = pyqtSignal(str)        # channel_id
    channelMiddleClicked          = pyqtSignal(str)        # channel_id — configured middle-click play
    channelContextMenuRequested   = pyqtSignal(str, int, int)  # channel_id, gx, gy
    clearQueueClicked             = pyqtSignal()           # demoted to the ⋯ overflow menu
    clearWatchedClicked           = pyqtSignal()
    clearUnavailableClicked       = pyqtSignal()           # request clear-unavailable
    newMatchesClicked             = pyqtSignal()           # open the new matched content
    searchRequested                = pyqtSignal(str)        # search_title for recovery
    # Alerts Matched (topmost group) — click routing separate from itemSelected
    # so a click both opens details AND acks the match (channel rows), or just
    # navigates (series rows — no unseen-count clearing here, out of scope).
    alertsMatchedClicked           = pyqtSignal(str)        # channel_id
    alertsMatchedSeriesClicked     = pyqtSignal(str)        # series_channel_id
    # Matched-series row "Mark seen" context-menu action — clears unseen_new
    # without navigating (the double-click drill-in and this action are the
    # only two ways to acknowledge a matched-series row; opening the menu
    # itself must never mark-viewed as a side effect).
    alertsMatchedSeriesMarkSeenRequested = pyqtSignal(str)  # series_channel_id
    _data_ready                   = pyqtSignal(object)     # list[QueueEntry] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        self._has_unavailable = False
        super().__init__("Watch Queue", config.queue_icon, config, parent)
        self._init_background_refresh()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "queue"

    def _add_header_actions(self, header_layout) -> None:
        """Add the 🔍 toggle that reveals the find-in-queue box.

        The box is not permanently on screen: it would cost a row of the
        sidebar's scarcest resource in every session, including the many that
        never filter anything. A checkable header button — same size and slot as
        Recommended's refresh button — makes it available without charging rent
        for it.
        """
        self._filter_btn = QPushButton(_icons.search_icon)
        self._filter_btn.setCheckable(True)
        self._filter_btn.setFixedSize(22, 20)  # structural — matches the refresh btn
        self._filter_btn.setToolTip("Find in queue")
        self._filter_btn.clicked.connect(self._toggle_filter_box)
        header_layout.addWidget(self._filter_btn)

    def create_content(self):
        # Pinned GREEN "new matches from your alerts" line — a single clickable row
        # at the very top of the queue.  Hidden until there are unviewed matches;
        # clicking opens the matched content (where it is flagged 🚨/green).
        self._new_matches_btn = QPushButton()
        _theme.style(self._new_matches_btn, "QUEUE_NEW_MATCHES_LINE")
        self._new_matches_btn.clicked.connect(self.newMatchesClicked.emit)
        self._new_matches_btn.hide()
        self.content_layout.addWidget(self._new_matches_btn)

        # Find-in-queue box. Measured on the owner's install: 612 entries, 597 of
        # them never watched, and NOTHING older than three months — so this is not
        # a stale tail an ageing rule could trim (a 3-month cutoff would archive
        # zero rows; a 1-month cutoff would archive 436 of 612). It is a queue
        # filled faster than it is drained, where every entry was added
        # deliberately. Hiding 71% of it to make it navigable would be censorial;
        # letting the user find one title in it is not.
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Find in queue…")
        self._filter.setToolTip("Show only queued titles matching this text")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._on_filter_changed)
        # Escape puts the sidebar back the way it was — the same one action as
        # clicking the header button off, so it also clears (never leaves an
        # invisible filter behind).
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self._filter)
        escape.setContext(Qt.ShortcutContext.WidgetShortcut)
        escape.activated.connect(self._hide_filter_box)
        self.content_layout.addWidget(self._filter)
        self._set_filter_visible(bool(self.config.queue_filter_visible), save=False)

        self._list = QListWidget()
        # Chip rows fit the sidebar width and elide — never scroll sideways (which
        # would push the right-aligned year/language chips off behind the scrollbar).
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        # Middle-click plays the user-configured action (same seam as the channel
        # list) via the shared QListWidget helper — no per-section handler copy.
        from metatv.gui.list_middle_click import install_list_middle_click
        self._list_mc = install_list_middle_click(self._list)
        self._list_mc.middleClicked.connect(self.channelMiddleClicked)
        _theme.apply_list_selection(self._list)
        self.content_layout.addWidget(self._list)

        # Both bulk actions live in the ⋯ overflow. "Clear Watched" used to be a
        # full-width button, which cost ~29px — more than a compact row — in
        # every session, whether or not there was anything to clear.
        self.content_layout.addLayout(self.build_overflow_row([
            (f"{self.config.watched_icon} Clear Watched",
             "Remove finished items — partially watched titles stay",
             self.clearWatchedClicked.emit),
            (f"{self.config.delete_icon} Clear All",
             "Remove everything from the queue",
             self.clearQueueClicked.emit),
        ]))

        # Filter bookkeeping — rebuilt by every _populate_rows.
        self._groups: list[_FilterGroup] = []
        self._no_match_item = None

        self.set_empty(True)

    def budgeted_list(self):
        """The rows this section fits to its height (see
        ``CollapsibleSection.apply_row_budget``)."""
        return self.__dict__.get("_list")

    def item_count(self) -> int | None:
        """Rows currently rendered — inventory, shown only when :meth:`news` is
        quiet.

        Read off the list itself rather than tracked separately, so the header
        cannot claim a number the rows disagree with. The ``+N more`` tail is
        excluded: it is chrome, not content.
        """
        from PyQt6.QtCore import Qt

        from metatv.gui.sidebar.base import _MORE_ROLE, _MORE_ROW

        lst = self.__dict__.get("_list")
        if lst is None:
            return None
        return sum(
            1 for i in range(lst.count())
            if lst.item(i).data(_MORE_ROLE) != _MORE_ROW
        )

    def news(self) -> str:
        """Unviewed watch-for matches — the "a new season dropped" signal."""
        count = self.__dict__.get("_new_match_count", 0)
        return f"{count} new" if count else ""

    def update_new_match_count(self, count: int) -> None:
        """Show/hide the pinned green new-matches banner.

        The bulk "Clear Alerts" action now lives in the Alerts header, so this
        only drives the pinned banner (unchanged behavior).

        Args:
            count: Number of unviewed watch-for matches across all rules.
        """
        # Kept for news() regardless of whether the banner widget exists, so a
        # collapsed section still reports what changed.
        self._new_match_count = count
        self.refresh_header_status()
        try:
            line = self._new_matches_btn
        except (AttributeError, RuntimeError):
            return  # content not built (e.g. __new__ test stub) — nothing to update
        if line is None:
            return
        if count > 0:
            line.setText(
                f"{_icons.watchlist_on_icon} {count} new match"
                f"{'es' if count != 1 else ''} from your alerts  "
                f"{_icons.see_all_arrow_icon}"
            )
            line.setToolTip("Open the new matched content from your watch-for alerts")
            line.show()
        else:
            line.hide()

    # --- BackgroundRefreshMixin hooks ---
    def _refresh_list(self) -> QListWidget:
        return self._list

    def _load_error_message(self) -> str:
        return "Couldn't load watch queue"

    def _load_rows(self):
        from metatv.core.vod_alert_availability import (
            compute_alert_availability, get_unviewed_matched_entries,
        )
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            hidden = set(repos.providers.get_hidden_provider_ids())
            entries = repos.queue.get_all(hidden_provider_ids=hidden)
            # Re-validate the pinned banner's count against live source state (same
            # session): matches on disabled/expired sources must not count here either.
            avail = None
            try:
                avail = compute_alert_availability(self.config, repos)
                self._available_unviewed = avail.unviewed_total
            except Exception:  # noqa: BLE001
                self._available_unviewed = None  # fall back to raw config count
            # Alerts Matched (topmost group) — carried as side-channel instance
            # attributes (same pattern as ``_available_unviewed`` above) rather than
            # widening this method's return value, so every existing caller that
            # feeds a plain ``entries`` list straight into ``_populate_rows`` keeps
            # working unchanged.  ``avail`` is reused (no second bounded query).
            try:
                self._alerts_matched = get_unviewed_matched_entries(
                    self.config, repos, avail
                )
            except Exception:  # noqa: BLE001
                logger.exception("WatchQueueSection: alerts-matched load failed")
                self._alerts_matched = []
            try:
                self._alerts_matched_series = [
                    s for s in self.config.get_monitored_series()
                    if (s.get("unseen_new") or 0) > 0
                ]
            except Exception:  # noqa: BLE001
                self._alerts_matched_series = []
            return entries

    def _populate_rows(self, entries) -> None:
        """Main-thread slot: populate the queue list from QueueEntry plain dataclasses."""
        # The pinned new-matches line is independent of queue contents (it reflects
        # config watch-for matches), so refresh it before the empty-list early-out.
        # Uses the AVAILABLE unviewed count (re-validated in _load_rows), not the raw
        # config total.  Guarded so partially-built __new__ test stubs don't trip.
        try:
            count = getattr(self, "_available_unviewed", None)
            if count is None:
                count = self.config.get_unviewed_vod_match_count()
            self.update_new_match_count(count)
        except (AttributeError, RuntimeError):
            pass
        self._has_unavailable = any(not e.available for e in entries) if entries else False
        # The list was cleared before this call, so every recorded item is gone.
        self._groups = []
        self._no_match_item = None

        # Alerts Matched (topmost group) — set by _load_rows (worker thread) as a
        # side-channel attribute; a direct/legacy caller of _populate_rows that never
        # ran _load_rows simply sees no matched rows.  Read the instance dict
        # directly (not getattr-with-default): on a __new__'d QObject test stub
        # whose C++ super-init never ran, getattr() raises RuntimeError instead of
        # returning the default (see the identical workaround in
        # WatchAlertsSection._compute_alert_availability).
        matched = self.__dict__.get("_alerts_matched") or []
        series_new = self.__dict__.get("_alerts_matched_series") or []
        has_content = bool(entries) or bool(matched) or bool(series_new)
        self.set_empty(not has_content)

        self._add_alerts_matched_section(matched, series_new)

        if not entries:
            if not matched and not series_new:
                item = QListWidgetItem("Queue is empty — right-click any channel to add")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(item)
            return

        # Entries whose source is gone are grouped at the BOTTOM rather than
        # interleaved. They are dimmed either way, but scattered through the
        # list they read as breakage in the queue itself — the owner deleted a
        # source, met 37 unplayable months-old entries mixed into everything
        # else, and reasonably concluded the queue had invented them.
        available = [e for e in entries if e.available]
        unavailable = [e for e in entries if not e.available]

        continue_watching = sorted(
            [e for e in available if e.last_played],
            key=lambda e: e.last_played,
            reverse=True,
        )
        # Newest first, matching Continue Watching above. Queue `position` is
        # append-only, so rendering in that order pinned the oldest additions to
        # the top forever and buried anything queued today ~600 rows down — the
        # queue showed the user exactly the items they no longer remembered.
        never_watched = sorted(
            [e for e in available if not e.last_played],
            key=lambda e: (e.added_at is not None, e.added_at),
            reverse=True,
        )

        if continue_watching:
            self._add_group("Continue Watching", False, continue_watching)

        if never_watched:
            self._add_group("Never Watched", True, never_watched)

        if unavailable:
            # Count in the header because the queue never showed its size
            # anywhere — 611 entries had accumulated with no indication.
            self._add_group("Unavailable", True, unavailable)

        # Re-apply whatever the user is filtering by: a refresh is usually the
        # side effect of acting on ONE row, and silently dropping the filter
        # would dump all 600 entries back on them mid-triage.
        self._apply_filter(self._filter.text())

    # --- Grouping + find-in-queue ---------------------------------------------

    def _add_group(self, bare_label: str, show_count: bool, entries: list) -> None:
        """Render one header + its rows, recording both for the filter."""
        header_text = f"{bare_label} ({len(entries)})" if show_count else bare_label
        group = _FilterGroup(self._add_header(header_text), bare_label, show_count)
        for e in entries:
            group.rows.append((
                self._add_entry_item(e),
                _haystack(
                    e.search_title, e.channel_name, e.episode_title, e.detected_year
                ),
            ))
        self._groups.append(group)

    def _on_filter_changed(self, text: str) -> None:
        self._apply_filter(text)

    def _toggle_filter_box(self) -> None:
        """Header 🔍 clicked — reveal or put away the find-in-queue box."""
        self._set_filter_visible(not self._filter.isVisible())

    def _hide_filter_box(self) -> None:
        """Escape in the box — same action as toggling the button off."""
        self._set_filter_visible(False)

    def _set_filter_visible(self, visible: bool, *, save: bool = True) -> None:
        """Show/hide the box, and CLEAR it on the way out.

        Clearing when hiding is the whole safety of this control: a filter left
        applied behind a hidden box means the queue shows 12 of 612 rows with
        nothing on screen to say why, which reads as the queue having lost
        things — the exact misreading #289 was fixed to stop. Hidden box, whole
        queue. Always.
        """
        if not visible:
            self._filter.clear()          # → _apply_filter("") restores every row
        self._filter.setVisible(visible)
        self._filter_btn.setChecked(visible)
        self._filter_btn.setToolTip("Hide the queue filter" if visible else "Find in queue")
        if visible:
            self._filter.setFocus(Qt.FocusReason.ShortcutFocusReason)
        if save:
            self.config.queue_filter_visible = visible
            try:
                self.config.save()
            except Exception as exc:  # noqa: BLE001 — never break the toggle on a save fault
                logger.warning(f"Could not save queue filter visibility: {exc}")

    def _apply_filter(self, text: str) -> None:
        """Hide non-matching rows; retitle each header with what it is showing.

        Hides rather than re-renders: a keystroke that rebuilt 600 chip-row
        widgets would stutter, and hiding keeps every row's widget, tooltip and
        selection intact so clearing the box is instant.

        Headers become "Never Watched (12 of 597)" while filtering and revert to
        their exact unfiltered text when the box is cleared — a header still
        claiming 597 above 12 visible rows is a lie about what is on screen.
        """
        needle = (text or "").strip().lower()
        visible = 0
        for group in self._groups:
            shown = 0
            for item, haystack in group.rows:
                match = not needle or needle in haystack
                item.setHidden(not match)
                shown += int(match)
            visible += shown
            if needle:
                group.header.setHidden(shown == 0)
                group.header.setText(f"{group.bare_label} ({shown} of {len(group.rows)})")
            else:
                group.header.setHidden(False)
                group.header.setText(group.unfiltered_text())
        self._update_no_match_row(needle, visible)

    # --- In-place removal (InPlaceRowMixin) -----------------------------------

    def _row_matches(self, item, key) -> bool:
        """Match a queue row by the id of its OWN grain.

        Channel-grain and episode-grain rows are independent entries (queuing
        episodes never makes the series root read as queued), so unqueuing a
        series must not take its queued episodes with it — and vice versa.
        Alerts-Matched rows are config-derived, never queue rows, so they never
        match.
        """
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return False
        grain = payload.get("grain")
        if grain == "episode":
            return payload.get("episode_id") == key
        if grain == "channel":
            return payload.get("channel_id") == key
        return False

    def _after_rows_removed(self, list_widget) -> None:
        """Keep the groups, headers and counts honest after a row is taken out."""
        # ``row()`` returns -1 for an item no longer in the list — Qt's own
        # membership test, and the only one available here: QListWidgetItem is
        # unhashable under PyQt6, so a set of live items is not an option.
        for group in list(self._groups):
            group.rows = [
                (item, hay) for item, hay in group.rows if list_widget.row(item) >= 0
            ]
            if group.rows:
                group.header.setText(group.unfiltered_text())
                continue
            # Group emptied — its header would otherwise stand over nothing.
            index = list_widget.row(group.header)
            if index >= 0:
                list_widget.takeItem(index)
            self._groups.remove(group)
        self._has_unavailable = any(g.bare_label == "Unavailable" for g in self._groups)
        if not self._groups:
            self.set_empty(True)
        # A filter may be active: re-apply so the "(N of M)" totals and the
        # no-match row reflect the row that just left.
        self._apply_filter(self._filter.text())

    def _update_no_match_row(self, needle: str, visible: int) -> None:
        """Say so when a filter matches nothing — an all-hidden list reads as broken."""
        if needle and visible == 0:
            text = f"No queued titles match “{needle}”"
            if self._no_match_item is None:
                item = QListWidgetItem(text)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(item)
                self._no_match_item = item
            else:
                self._no_match_item.setText(text)
                self._no_match_item.setHidden(False)
        elif self._no_match_item is not None:
            self._no_match_item.setHidden(True)

    def _add_entry_item(self, e) -> QListWidgetItem:
        """Add a single queue entry as the shared chip row, dimming unavailable ones.

        UserRole carries a dict tagging the entry's grain (Wave 2 Slice 2B) so
        every reader (double-click, selection, context menu) can branch without a
        second lookup: channel-grain -> {"grain": "channel", "channel_id": ...};
        episode-grain -> {"grain": "episode", "episode_id": ..., "channel_id": ...}
        (channel_id there is still the PARENT SERIES, for the context-menu seam).
        """
        item = QListWidgetItem()
        if e.is_episode:
            item.setData(Qt.ItemDataRole.UserRole, {
                "grain": "episode",
                "episode_id": e.episode_id,
                "channel_id": e.channel_id,
            })
            code = (
                f"S{e.season_num:02d}E{e.episode_num:02d}" if e.season_num and e.episode_num
                else f"E{e.episode_num}" if e.episode_num else ""
            )
            title = f"{e.channel_name} — {code}" if code else e.channel_name
            if e.episode_title:
                title += f" {e.episode_title}"
        else:
            item.setData(Qt.ItemDataRole.UserRole, {
                "grain": "channel",
                "channel_id": e.channel_id,
            })
            title = e.search_title or e.channel_name
        item.setData(_ROLE_AVAILABLE, e.available)
        item.setData(_ROLE_SEARCH_TITLE, e.search_title)
        # An episode-grain entry leads with its episode code — that is what
        # distinguishes it from its siblings; a channel-grain entry falls back
        # to the year. The media TYPE is the icon, never a word.
        marker = episode_code(e.season_num, e.episode_num) or e.detected_year
        quality = quality_word(e.detected_quality)
        row = build_chip_row(
            title=title,
            icon_role=media_icon_role(e.media_type),
            chips=(
                (CHIP_QUALITY, quality),
                (CHIP_YEAR, marker),
                (CHIP_LANG, e.detected_prefix),
            ),
            meta=sidebar_meta_line(marker, e.detected_prefix, quality),
            density=self._row_density(),
        )
        if not e.available:
            # A custom item widget ignores the item's foreground role, so dim the whole
            # row via a translucency effect (opacity, not a colour literal) and keep the
            # recovery tooltip on the item (mouse-transparent row → item shows it).
            effect = QGraphicsOpacityEffect(row)
            effect.setOpacity(0.45)
            row.setGraphicsEffect(effect)
            item.setToolTip(_UNAVAILABLE_TOOLTIP)
        elif e.media_type == "series" and not e.is_episode:
            # Series channel-grain row: double-click drills into the season/
            # episode tree, not a direct play. Episode-grain rows are excluded —
            # they always describe a series' PARENT but double-click there plays
            # the specific queued episode.
            item.setToolTip("Double-click to browse the series")
        else:
            item.setToolTip("Double-click to play")
        # Width 0 → the item spans the viewport (no sideways scroll); the row's own
        # height governs the row height.
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        return item

    # --- Alerts Matched (topmost group) ---------------------------------------
    # A third, TOPMOST group ahead of "Continue Watching"/"Never Watched": one row
    # per unviewed watch-for keyword match, plus one row per monitored series with
    # unseen_new > 0.  Purely derived from config state (alerted_ids/viewed_ids,
    # monitored_series) — no new table, so it persists across restarts for free.

    def _add_alerts_matched_section(self, matched, series_new) -> None:
        """Render the Alerts Matched header + rows (no-op when both are empty)."""
        if not matched and not series_new:
            return
        # No emoji: the render's group headings are text. The glyph was baked
        # into the label STRING, so styling the heading uppercased it and the
        # emoji rode along untouched.
        label = "Alerts Matched"
        group = _FilterGroup(self._add_header(label), label, False)
        for m in matched:
            group.rows.append((
                self._add_matched_channel_item(m), _haystack(m.title, m.detected_year)
            ))
        for s in series_new:
            group.rows.append((
                self._add_matched_series_item(s),
                _haystack(s.get("display_title"), s.get("title")),
            ))
        self._groups.append(group)

    def _add_matched_channel_item(self, m) -> QListWidgetItem:
        """One unviewed keyword-match row — a chip row with the green NEW pill."""
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, {
            "grain": "matched_channel",
            "channel_id": m.channel_id,
        })
        quality = quality_word(m.detected_quality)
        row = build_chip_row(
            title=m.title,
            icon_role=media_icon_role(m.media_type),
            chips=(
                (CHIP_QUALITY, quality),
                (CHIP_YEAR, m.detected_year),
                (CHIP_LANG, m.detected_prefix),
            ),
            meta=sidebar_meta_line(m.detected_year, m.detected_prefix, quality),
            density=self._row_density(),
            new_badge=True,
        )
        hint = (
            "double-click to browse the series" if m.media_type == "series"
            else "double-click to play"
        )
        if m.rule_texts:
            quoted = ", ".join(f"'{t}'" for t in m.rule_texts)
            item.setToolTip(f"Matched your alert: {quoted} — {hint}")
        else:
            item.setToolTip(f"Matched your watch-for alert — {hint}")
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        return item

    def _add_matched_series_item(self, entry: dict) -> QListWidgetItem:
        """One monitored-series-with-new-episodes row.

        Built by the SHARED row builder, like every other row in this section.
        It used to be a ``_VodAlertRow`` — a second widget for the same visual
        row, carrying an emoji type icon and an emoji "NEW" badge — so it sat
        out every change made to the real rows around it and ended up the only
        row in the sidebar still wearing the old look.
        """
        cid = entry.get("series_channel_id", "")
        title = entry.get("display_title") or entry.get("title") or "Unknown series"
        unseen = entry.get("unseen_new") or 0
        ep_word = "ep" if unseen == 1 else "eps"

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, {
            "grain": "matched_series",
            "channel_id": cid,
        })
        item.setToolTip(
            f"{title}: +{unseen} new {ep_word} — double-click to browse the series"
        )
        row = build_chip_row(
            title=title,
            icon_role=media_icon_role("series"),
            news_text=f"+{unseen} {ep_word}",
            new_badge=True,
            density=self._row_density(),
        )
        item.setSizeHint(row.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        return item

    def _route_matched_click(self, item: QListWidgetItem) -> bool:
        """Route a SINGLE click on an Alerts Matched row; True if handled.

        Channel rows both open details AND ack the match (every rule that alerted
        it) — the host connects ``alertsMatchedClicked`` to both.  Series rows only
        show details — no unseen-count clearing on single click; that happens on
        the double-click drill-in (opening the season/episode tree IS the ack) or
        the explicit "Mark seen" context-menu action.
        """
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return False
        grain = payload.get("grain")
        if grain == "matched_channel":
            cid = payload.get("channel_id")
            if cid:
                self.alertsMatchedClicked.emit(cid)
            return True
        if grain == "matched_series":
            cid = payload.get("channel_id")
            if cid:
                self.alertsMatchedSeriesClicked.emit(cid)
            return True
        return False

    def has_unavailable(self) -> bool:
        """True when at least one entry in the current list is unavailable."""
        return self._has_unavailable

    def _add_header(self, text: str, count: int | None = None) -> QListWidgetItem:
        """A sub-group heading inside a section — "ALERTS MATCHED · 3".

        Small-caps and muted rather than bold body text, per the V3 render: a
        group heading is a divider, and rendering it at the same weight as the
        titles beneath it made it compete with the content it was separating.
        The count rides on the heading because a group's size is context for
        the rows under it, not news about them.
        """
        label = f"{text}  ·  {count}" if count else text
        item = QListWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        style_group_heading(item)
        self._list.addItem(item)
        return item

    def _on_double_click(self, item: QListWidgetItem) -> None:
        """Route a DOUBLE click. Series (layered) items navigate; leaf items play.

        - matched_channel: ack the match (same as single-click) THEN navigate/play
          through the same chokepoint a plain queue row double-click already uses
          (``itemDoubleClicked`` → host's ``play_queue_item_id``, which resolves
          the channel's media_type and drills into a series or plays a movie/live
          leaf) — never a parallel play/drill path.
        - matched_series: navigate only. Drilling in IS the "seen" ack (the host's
          ``on_series_loaded`` clears ``unseen_new`` on a successful open), so no
          separate mark-viewed emission is needed here.
        - episode / channel (plain queue rows): unchanged — episodes play
          directly; channel rows already resolve series-vs-leaf the same way via
          ``itemDoubleClicked``.
        """
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return
        grain = payload.get("grain")

        if grain == "matched_channel":
            cid = payload.get("channel_id")
            if cid:
                self.alertsMatchedClicked.emit(cid)
                self.itemDoubleClicked.emit(cid)
            return

        if grain == "matched_series":
            cid = payload.get("channel_id")
            if cid:
                self.itemDoubleClicked.emit(cid)
            return

        available = item.data(_ROLE_AVAILABLE)
        if available is False:
            search_title = item.data(_ROLE_SEARCH_TITLE) or ""
            self.searchRequested.emit(search_title)
            return
        if grain == "episode":
            self.episodeActivated.emit(payload["episode_id"])
        else:
            self.itemDoubleClicked.emit(payload["channel_id"])

    def _on_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if not current:
            return
        if self._route_matched_click(current):
            return
        payload = current.data(Qt.ItemDataRole.UserRole)
        channel_id = payload.get("channel_id") if payload else None
        if channel_id:
            # Episode-grain rows still resolve to the SERIES channel_id here —
            # showing the series' own details pane is the closest available
            # surface; a dedicated episode-detail seam from the queue is
            # deferred (Slice 2B scope: play/favorite/queue the episode, not
            # single-click detail routing).
            self.itemSelected.emit(channel_id)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        gp = self._list.viewport().mapToGlobal(pos)

        if item:
            payload = item.data(Qt.ItemDataRole.UserRole)
            grain = payload.get("grain") if isinstance(payload, dict) else None

            if grain == "matched_series":
                # Monitored-series entries are config-only aggregates, not a
                # ChannelDB row the channel_menu.py registry models (play/
                # favorite/queue/etc.) — hand-rolled, mirroring the identical
                # Open-series/Mark-seen pattern the Watch Alerts sidebar section
                # already uses for its own monitored-series rows
                # (sidebar/alerts.py _show_series_context_menu).
                cid = payload.get("channel_id")
                if cid:
                    self._build_matched_series_menu(cid).exec(gp)
                return

            channel_id = payload.get("channel_id") if payload else None
            if channel_id:
                # Emit signal so main_window builds the per-item context menu,
                # which will also append "Clear Unavailable" (see main_window_favorites.py).
                # Episode-grain rows target the PARENT SERIES' channel menu here —
                # channel_menu.py's registry is ChannelDB-only today (episode
                # favorite/queue actions live in the series-tree's own menu instead).
                # matched_channel rows reuse this exact same "queue" surface —
                # previously these rows had NO context menu at all.
                self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())
                return

        # Right-click on empty space or a header — still offer Clear Unavailable.
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        from PyQt6.QtCore import QPoint
        menu = QMenu(self)
        clear_act = QAction("Clear Unavailable", self)
        clear_act.setEnabled(self._has_unavailable)
        if not self._has_unavailable:
            clear_act.setToolTip("No unavailable content")
        clear_act.triggered.connect(self.clearUnavailableClicked.emit)
        menu.addAction(clear_act)
        menu.exec(QPoint(gp.x(), gp.y()))

    def _build_matched_series_menu(self, cid: str) -> "QMenu":
        """Build (does not exec) the Alerts-Matched series row's right-click menu.

        "Open series" reuses the exact same navigate chokepoint as double-click
        (``itemDoubleClicked`` — drilling in is itself the "seen" ack). "Mark
        seen" is the only way to explicitly clear ``unseen_new`` without
        navigating. Building the menu never mutates anything — only a
        triggered action does, so opening the menu is never a mark-viewed
        side effect.
        """
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self._list)
        open_action = menu.addAction(f"{_icons.series_icon}  Open series")
        open_action.setToolTip("Browse this series' seasons and episodes")
        open_action.triggered.connect(
            lambda _=False, c=cid: self.itemDoubleClicked.emit(c)
        )
        seen_action = menu.addAction(f"{_icons.watched_icon}  Mark seen")
        seen_action.setToolTip("Clear the new-episode count for this series")
        seen_action.triggered.connect(
            lambda _=False, c=cid: self.alertsMatchedSeriesMarkSeenRequested.emit(c)
        )
        return menu
