"""The EPG group: what your watchlist patterns match in the guide.

Everything from the off-thread query to the clock that keeps the rendered rows
honest. Split from :mod:`alerts` because the section carries four independent
groups and one file carrying all four ran past 1800 lines — well over the
1000-line standard — with no seam telling a reader which half they were in.

Mixed into ``WatchAlertsSection``; it reaches the section's widgets
(``alerts_tree``, ``_epg_toggle``, ``_epg_hdr_container``) through ``self``,
which ``create_content`` builds.
"""

from __future__ import annotations


from PyQt6.QtWidgets import QListWidgetItem, QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt, QSize, QTimer
from metatv.core.epg_utils import now_utc as _now_utc, is_local_today as _is_local_today, to_local as _to_local
from metatv.gui import icons as _icons
from metatv.gui.relative_time import humanize_remaining, humanize_until
from metatv.gui.sidebar.alerts_rows import _AlertRow
from metatv.gui.sidebar.base import (
    CollapsibleSection, GroupHeading, _fmt_channel_name,
)
from metatv.gui.sidebar.alerts_common import (
    _CHILD_INDENT,
    _Airing,
    _quality,
    _region,
    _started_at,
    _when,
    _ALERTS_TREE_AUTOEXPAND_BUDGET,
)


class EpgGroupMixin:
    #: Why the EPG group has nothing to list. The distinction earns its keep on
    #: the first two: an unconfigured watchlist should show nothing, but a
    #: CONFIGURED one with nothing airing must still hold its place — rendering
    #: those two states identically is what made a working feature look broken.
    EPG_EMPTY_NO_PATTERNS = "no_patterns"

    EPG_EMPTY_NO_SOURCE   = "no_source"

    EPG_EMPTY_NO_MATCHES  = "no_matches"

    EPG_EMPTY_GUIDE_ENDED = "guide_ended"

    #: Reasons the group hides rather than explains itself. Both mean the user
    #: has not set this up — there is no promise outstanding, so a line saying
    #: nothing is airing would be noise about a feature they never asked for.
    EPG_EMPTY_SILENT = frozenset({EPG_EMPTY_NO_PATTERNS, EPG_EMPTY_NO_SOURCE})

    #: How often the visible rows recompute their own time text. Cheap by
    #: construction: no query, no network, just arithmetic against timestamps
    #: the rows already hold.
    TICK_MS = 30_000

    def _epg_empty_notice(self, reason: str) -> tuple[str, str, str]:
        """Icon, sentence and tooltip for an EPG group with nothing to list.

        Monochrome glyphs on both: a colour emoji beside the muted row text
        reads as an error state rather than a note.

        The guide-ended case takes the warning glyph because it is actionable —
        the alerts are fine and a guide refresh is what fixes it — while a
        merely-quiet watchlist takes its own icon and states the count, so the
        user can see their rules are still loaded.
        """
        if reason == self.EPG_EMPTY_GUIDE_ENDED:
            return (
                _icons.notification_warning_icon,
                "Guide data has run out",
                "This source's guide has no programmes left to start, so no "
                "alert can match until it is refreshed. It refreshes on its "
                "own schedule; Settings → EPG can force it sooner.",
            )
        count = len(self.config.epg_watchlist_patterns or ())
        return (
            _icons.info_icon,
            f"Nothing airing from {count} alerts",
            f"Your {count} watch alerts are loaded — none of them is on now or "
            f"coming up in the next 24 hours.",
        )

    def _update_epg_toggle_label(self, count: int) -> None:
        """Refresh the EPG heading's count, and remember it.

        Remembering matters because a notice render draws one row that is not a
        programme: re-deriving the count from ``topLevelItemCount()`` on the
        next collapse would put a "1" chip next to the words "Nothing airing".
        """
        self._epg_count = count
        self._epg_toggle.set_count(count or None)

    def _toggle_epg(self) -> None:
        self._epg_collapsed = not self._epg_collapsed
        self.alerts_tree.setVisible(not self._epg_collapsed and self._epg_has_rows)
        self._update_epg_toggle_label(self.__dict__.get("_epg_count", 0))

    def budgeted_tree(self):
        """Watch Alerts fits its top-level groups, not a flat list.

        This is the section R13 names directly — 173px subdivided four ways,
        each sub-group scrolling in about 35px.
        """
        return self.__dict__.get("alerts_tree")

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

    def _refresh_list(self) -> QTreeWidget:
        return self.alerts_tree

    def _load_error_message(self) -> str:
        return "Couldn't load watch alerts"

    def _loading_message(self) -> str:
        return "Loading alerts…"

    def _show_tree_notice(self, tree, icon: str, message: str,
                          tooltip: str = "") -> None:
        """Render ONE non-selectable row in place of the EPG programme rows.

        The loading, error and nothing-airing states are the same widget problem
        — the base CollapsibleSection builds them from QListWidgetItem +
        addItem, which QTreeWidget does not have — so they share one body
        rather than three that drift. The count is forced to 0: a notice is not
        a programme, and letting topLevelItemCount() speak would put a "1" chip
        on the heading beside the words "Nothing airing".
        """
        tree.clear()
        item = QTreeWidgetItem([f"{icon} {message}"])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        if tooltip:
            item.setToolTip(0, tooltip)
        tree.addTopLevelItem(item)
        self._reveal_epg_subsection(count=0)
        self.set_empty(False)

    def show_load_error(self, tree, message: str) -> None:
        """Override for QTreeWidget: render a non-selectable error row."""
        self._show_tree_notice(tree, _icons.notification_warning_icon, message)

    def show_loading(self, tree, message: str = "Loading…") -> None:
        """Override for QTreeWidget: render a transient, non-selectable loading row."""
        self._show_tree_notice(tree, _icons.loading_icon, message)

    def _reveal_epg_subsection(self, count: int | None = None) -> None:
        """Show the EPG sub-header + tree (loading / error / notice / populated).

        Args:
            count: Programmes to put on the heading chip. ``None`` counts the
                tree's own top-level rows, which is right for a populated
                render; a notice render passes 0, because the one row it drew
                is a sentence, not a programme.
        """
        # Guarded for __new__ test stubs (no full constructor → no EPG widgets),
        # matching this file's other stub-tolerant helpers.
        if "_epg_hdr_container" not in self.__dict__:
            return
        self._epg_has_rows = True
        self._epg_hdr_container.show()
        self.alerts_tree.setVisible(not self._epg_collapsed)
        if count is None:
            count = self.alerts_tree.topLevelItemCount()
        self._update_epg_toggle_label(count)

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

        Returns a plain dict with keys 'live_groups', 'upcoming_only' and
        'empty_reason' (never None for valid-empty; None is reserved for real
        exceptions and emitted only by the mixin's try/except wrapper).

        ``empty_reason`` is what lets the main thread tell "you have not set
        any alerts up" apart from "your alerts are fine, the guide ran out" —
        two states that used to render identically, as nothing at all.
        """
        from metatv.core.repositories.epg import EpgRepository
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.database import ChannelDB

        def _empty(reason: str) -> dict:
            return {"live_groups": {}, "upcoming_only": {}, "empty_reason": reason}

        patterns = self.config.epg_watchlist_patterns
        if not patterns:
            return _empty(self.EPG_EMPTY_NO_PATTERNS)

        with self.db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            provider_ids = repos.providers.get_epg_active_provider_ids()
            if not provider_ids:
                return _empty(self.EPG_EMPTY_NO_SOURCE)

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

            def _channel_display(prog) -> tuple[str, str, str]:
                """The row's channel text, its quality and its region, apart.

                Both tokens are pulled OUT of the formatted name so the row can
                chip them beside the title — each is a claim about THIS copy,
                not part of what the channel is called. Region left inside the
                string as "[DE]" is why the programme row could not say what
                language its play button was about to start.
                """
                rec = channel_names.get(prog.channel_db_id)
                if rec is None:
                    return _fmt_channel_name(prog.channel_epg_id or "Unknown"), "", ""
                return _fmt_channel_name(
                    rec["name"],
                    detected_title=rec["detected_title"],
                    detected_year=rec["detected_year"],
                    detected_region=None,        # drawn as a chip instead
                    detected_quality=None,       # drawn as a chip instead
                ), (rec["detected_quality"] or ""), (rec["detected_region"] or "")

            # Unified per-title groups — upcoming for a live title folds under WATCH NOW,
            # preventing the same show from appearing in both sections simultaneously.
            # live_groups: key -> {'live': [...], 'upcoming': [...], 'title': str}
            # upcoming_only: key -> {'airings': [...], 'title': str}
            live_groups: dict[str, dict] = {}
            upcoming_only: dict[str, dict] = {}

            for _pattern, progs in live_data.items():
                for prog in progs:
                    ch_display, ch_quality, ch_region = _channel_display(prog)
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
                                prog.start_time, ch_quality, ch_region)
                    )

            for _pattern, progs in upcoming_data.items():
                for prog in progs:
                    ch_display, ch_quality, ch_region = _channel_display(prog)
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
                                    None, ch_quality, ch_region)
                        )
                    else:
                        if key not in upcoming_only:
                            upcoming_only[key] = {'airings': [], 'title': prog.title}
                        upcoming_only[key]['airings'].append(
                            _Airing(ts, time_str, ch_display,
                                    prog.channel_db_id, prog.start_time,
                                    None, ch_quality, ch_region)
                        )

            # Only asked when there is nothing to show, and only to explain the
            # nothing: a matched watchlist never pays for this query.
            reason = ""
            if not live_groups and not upcoming_only:
                reason = (
                    self.EPG_EMPTY_NO_MATCHES
                    if repo.has_future_programmes(
                        provider_ids,
                        excluded_channel_provider_ids=excluded_ch_provider_ids,
                    )
                    else self.EPG_EMPTY_GUIDE_ENDED
                )

        return {
            "live_groups": live_groups,
            "upcoming_only": upcoming_only,
            "empty_reason": reason,
        }

    def _populate_rows(self, data: dict) -> None:
        """Main thread: rebuild the alerts_tree from pre-computed plain data.

        'data' is the dict returned by _load_rows (never None here — None is
        handled by the mixin which calls show_load_error instead).
        """
        live_groups   = data["live_groups"]
        upcoming_only = data["upcoming_only"]

        # Dropped FIRST, before any early return. The caller has already
        # cleared the tree, so every item still in this list is a deleted C++
        # object and touching one raises RuntimeError — which is what would
        # happen on the next toggle if an empty refresh took a return below
        # without passing through the rebuild that repopulates it.
        self._upcoming_items: list[QTreeWidgetItem] = []
        #: The heading's own item, dropped here for the SAME reason as the list
        #: above and not merely alongside it: it is a tree item too, the clear
        #: deletes it too, and reading it back after an empty refresh raises
        #: the same RuntimeError. Adding a second tracked item without
        #: extending this reset is exactly how the first one got missed.
        self._upcoming_heading_item = None
        #: When the SOONEST upcoming programme starts, for the collapsed
        #: heading's chip. Kept as the timestamp, not the rendered string, for
        #: the reason the rows keep theirs: the text goes stale on the clock
        #: tick and the instant does not.
        self._upcoming_next_when = None

        if not live_groups and not upcoming_only:
            # Nothing to list. The group VANISHING here is what made a working
            # watchlist read as a broken feature: seven alerts configured, and
            # the EPG heading simply gone — flashing into view for the loading
            # row and back out a moment later. It disappears only when there is
            # genuinely nothing to keep a place for; otherwise it holds its
            # space and says which nothing this is.
            reason = data.get("empty_reason", "")
            # A payload with no stated reason (a direct/legacy caller) falls
            # through to the notice — but never one that reads "Nothing airing
            # from 0 alerts", so an unconfigured watchlist stays silent whatever
            # the payload says.
            if not self.config.epg_watchlist_patterns:
                reason = self.EPG_EMPTY_NO_PATTERNS
            if reason in self.EPG_EMPTY_SILENT:
                self._hide_epg_subsection()
            else:
                icon, text, tip = self._epg_empty_notice(reason)
                self._show_tree_notice(self.alerts_tree, icon, text, tip)
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
                        started_at=None, first_source=None,
                        first_source_name="", region="") -> "QTreeWidgetItem":
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
            # Built from the SAME airing its play button starts, so its
            # progress bar is that source's progress rather than a claim about
            # the programme in the abstract — owner: "the bundled results ...
            # should use progress bars corresponding to the source attached to
            # the play button."
            row = _AlertRow(title, time_str, self.config, when=when, live=live,
                            started_at=started_at, bar_source=first_source_name,
                            region=region,
                            expandable=True, expanded=hdr.isExpanded())

            def _toggle(_=False, i=hdr, r=row):
                i.setExpanded(not i.isExpanded())
                r.set_expanded(i.isExpanded())
                self.fit_to_rows(self.alerts_tree)

            # The ROW opens the row — the title, the time, the marker, the empty
            # space. This used to hang off play_clicked, so only the 18px slot
            # responded and the row had to count as playable to open at all.
            row.expand_clicked.connect(_toggle)

            # ...and the play button plays, without making anyone open the row
            # first. Owner: "user doesn't typically care about row". Which
            # source it picks is the first LIVE airing as the group is ordered;
            # a real preference is roadmapped.
            if first_source:
                row.play_clicked.connect(
                    lambda _=False, cid=first_source: self.alertClicked.emit(cid)
                )
            else:
                row.play_clicked.connect(_toggle)
            hdr.setSizeHint(0, QSize(0, row.sizeHint().height()))
            self.alerts_tree.setItemWidget(hdr, 0, row)
            return hdr

        def _add_child(parent_item, ch_name, time_str, channel_db_id, title,
                       when=None, live=False, started_at=None,
                       quality="", region="") -> None:
            child = QTreeWidgetItem()
            child.setData(0, Qt.ItemDataRole.UserRole, channel_db_id)
            child.setToolTip(0, f"{title}\n{ch_name}")
            parent_item.addChild(child)
            row = _AlertRow(ch_name, time_str, self.config, when=when, live=live,
                            started_at=started_at, quality=quality,
                            region=region, indent=_CHILD_INDENT)
            _wire_row(row, channel_db_id)
            self.alerts_tree.setItemWidget(child, 0, row)

        def _add_direct(ch_name, time_str, channel_db_id, title,
                        when=None, live=False, started_at=None,
                        quality="", region="") -> "QTreeWidgetItem":
            """Single-channel item: header IS the row — no expand arrow.
            Shows the show title; channel name is the tooltip.

            Returns the item so the caller can put it under a sub-group — an
            upcoming programme is hidden and shown as a block.
            """
            item = QTreeWidgetItem()
            item.setData(0, Qt.ItemDataRole.UserRole, channel_db_id)
            item.setToolTip(0, ch_name)
            self.alerts_tree.addTopLevelItem(item)
            # marker_column: a single-source programme has nothing to disclose,
            # but it is still a TOP-LEVEL row — it reserves the column so its
            # title starts where a bundled programme's does.
            row = _AlertRow(title, time_str, self.config, when=when, live=live,
                            started_at=started_at, quality=quality, region=region,
                            bar_source=ch_name, marker_column=True)
            _wire_row(row, channel_db_id)
            self.alerts_tree.setItemWidget(item, 0, row)
            return item

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
                                live=a in live_items, started_at=_started_at(a),
                                quality=_quality(a), region=_region(a))
                else:
                    lead = live_items[0]
                    hdr = _add_parent(
                        title, lead[1], len(all_items) - 1,
                        when=_when(lead), live=True, started_at=_started_at(lead),
                        first_source=lead[3], first_source_name=lead[2],
                        region=_region(lead),
                    )
                    for a in live_items[:10]:
                        _add_child(hdr, a[2], a[1], a[3], title, _when(a), live=True,
                                   started_at=_started_at(a),
                                   quality=_quality(a), region=_region(a))
                    for a in up_items[:5]:
                        _add_child(hdr, a[2], a[1], a[3], title, _when(a), live=False,
                                   quality=_quality(a), region=_region(a))

        if upcoming_only:
            self._add_upcoming_heading(len(upcoming_only))
            # Soonest first, which is the order the block is built in — so the
            # chip names the same airing as the first row under the heading.
            self._upcoming_next_when = min(
                (_when(a) for grp in upcoming_only.values()
                 for a in grp["airings"] if _when(a) is not None),
                default=None,
            )
            for key, grp in sorted(upcoming_only.items(),
                                   key=lambda kv: min(a[0] for a in kv[1]['airings'])):
                title = grp['title']
                airings = sorted(grp['airings'], key=lambda a: a[0])
                if len(airings) == 1:
                    a = airings[0]
                    self._upcoming_items.append(_add_direct(
                        a[2], a[1], a[3], title, _when(a), live=False,
                        quality=_quality(a), region=_region(a)))
                else:
                    lead = airings[0]
                    # No first_source: every airing here is in the FUTURE, so
                    # the row is not live and never offers a play button.
                    hdr = _add_parent(
                        title, lead[1], len(airings) - 1, when=_when(lead),
                    )
                    self._upcoming_items.append(hdr)
                    for a in airings[:10]:
                        _add_child(hdr, a[2], a[1], a[3], title, _when(a), live=False,
                                   quality=_quality(a), region=_region(a))

        self._apply_upcoming_collapse()
        self._reveal_epg_subsection()
        self.set_empty(False)
        QTimer.singleShot(0, self._apply_expansion)
        QTimer.singleShot(0, self.reapply_row_budget)
        self._schedule_boundary(live_groups, upcoming_only)

    #: Text of the sub-group that holds programmes which have not started.
    #:
    #: The word is the one the full EPG watchlist view already uses for the
    #: same split ("ON NOW · n" / "UPCOMING · n", epg_watchlist_mixin.py), so
    #: the sidebar and the view name the same thing the same way. Owner: "or
    #: whatever title we used before, it was good".
    UPCOMING_HEADING = "Upcoming"

    def _add_upcoming_heading(self, count: int) -> None:
        """Put a foldable "UPCOMING n" heading above the not-yet-airing block.

        A ``GroupHeading``, not a rule or a divider row, because that widget is
        already the section's one sub-group heading — it exists precisely
        because this section had grown THREE ways of drawing the same thing
        (real headings, em-dash divider rows, a separate collapsible
        sub-section), two of which looked identical and only one of which was
        clickable. A ``──── UPCOMING ────`` bar would be a fourth.

        No caret, for the same reason the section headers have not had one
        since #329: the heading itself is the control, and a caret beside a
        clickable title is a second affordance for one action. What says it is
        interactive is the pointing-hand cursor and the tooltip; what says
        there is something inside while it is closed is the count, which
        ``GroupHeading`` keeps visible when collapsed for exactly that reason.

        There is deliberately no matching "On now" heading. What is on now sits
        at the top where it always did, and a heading over it would spend a row
        to label the thing you are already looking at. Owner: "We don't have to
        have a header for what's on now."

        Args:
            count: How many upcoming programmes the group holds.
        """
        item = QTreeWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)      # a label, not a target
        self.alerts_tree.addTopLevelItem(item)
        heading = GroupHeading(
            self.UPCOMING_HEADING, count, interactive=True,
            # One nesting step in, the same step the child airings take, so it
            # heads the rows below it instead of lining up with EPG above.
            indent=_CHILD_INDENT,
            tooltip="Programmes that have not started yet — "
                    "click to collapse or expand",
        )
        heading.clicked.connect(self._toggle_epg_upcoming)
        self.alerts_tree.setItemWidget(item, 0, heading)
        self._upcoming_heading_item = item

    def _toggle_epg_upcoming(self) -> None:
        """Fold or unfold the Upcoming block, and remember the choice."""
        self.config.alerts_epg_upcoming_collapsed = (
            not self.config.alerts_epg_upcoming_collapsed
        )
        self.config.save()
        self._apply_upcoming_collapse()
        self.reapply_row_budget()

    def _apply_upcoming_collapse(self) -> None:
        """Show or hide the upcoming rows to match the stored choice.

        Hidden rather than removed: ``fit_to_rows`` sizes the tree from Qt's own
        ``viewportSizeHint``, which already excludes hidden items, so the
        section shrinks to what is left without anything here doing arithmetic.
        """
        collapsed = bool(self.config.alerts_epg_upcoming_collapsed)
        for item in self.__dict__.get("_upcoming_items", ()):
            item.setHidden(collapsed)
        self._refresh_upcoming_tail()

    def _upcoming_heading(self) -> "GroupHeading | None":
        """The Upcoming heading widget, or None when the block is not built."""
        item = self.__dict__.get("_upcoming_heading_item")
        if item is None or "alerts_tree" not in self.__dict__:
            return None
        widget = self.alerts_tree.itemWidget(item, 0)
        return widget if isinstance(widget, GroupHeading) else None

    def _refresh_upcoming_tail(self, now=None) -> None:
        """Put the next start time on the heading, but only while it is closed.

        Through ``humanize_until`` with the same arguments the rows pass, so
        the chip and the first row under it cannot render the same instant two
        different ways.

        Args:
            now: The instant to render against; defaults to the current one.
                Passed in from the clock tick so every row and this chip share
                one reading of the time.
        """
        heading = self._upcoming_heading()
        if heading is None:
            return
        when = self.__dict__.get("_upcoming_next_when")
        show = bool(self.config.alerts_epg_upcoming_collapsed) and when is not None
        heading.set_tail(
            humanize_until(when, now or _now_utc(),
                           to_local=_to_local, is_local_today=_is_local_today)
            if show else ""
        )

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
        # The collapsed heading's chip is a rendered time like any other and
        # goes stale on the same schedule. Same ``now``, so it cannot drift
        # from the rows by a tick.
        self._refresh_upcoming_tail(now)

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

    def _sync_carets(self) -> None:
        """Point every parent row's caret at its item's real expanded state.

        Rows are built before expansion is decided (``_apply_expansion`` runs on
        a zero-timer), so a caret drawn at construction is a guess. This makes it
        report rather than predict — and it is called again after every
        expansion change for the same reason.
        """
        tree = self.__dict__.get("alerts_tree")
        if tree is None:
            return
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            row = tree.itemWidget(item, 0)
            if isinstance(row, _AlertRow) and item.childCount():
                row.set_expanded(item.isExpanded())

    def _apply_expansion(self) -> None:
        """Expand every group if the fully-expanded list stays compact; else expand none.

        The budget is the fixed ``_ALERTS_TREE_AUTOEXPAND_BUDGET`` (in rows via the same
        ``sizeHintForRow(0)``/fallback-22 primitive), NOT the live ``viewport().height()``
        — the tree's height now flexes with its stretch share of the pane, so reading the
        viewport here would make the decision jitter with the pane size.  A fixed budget
        keeps the "auto-expand only a short watchlist; leave a long one collapsed so it
        scrolls compactly" behaviour stable regardless of how tall the section is dragged.
        """
        self._sync_carets()
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
