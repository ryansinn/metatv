"""The Movies and Series groups: keyword rules and monitored series.

Keyword rules ("tell me when anything matching *Dune* arrives") and monitored
series ("tell me about new episodes") are two groups with one list widget and
one refresh, so they travel together. Split from :mod:`alerts` for the reason
given in :mod:`alerts_epg`.
"""

from __future__ import annotations


from PyQt6.QtWidgets import QListWidgetItem, QMenu
from PyQt6.QtCore import Qt, QSize, QTimer
from loguru import logger
from metatv.gui import icons as _icons
from metatv.gui import series_alert_identity as _series_identity
from metatv.gui.sidebar.alerts_rows import _VodAlertRow
from metatv.gui.sidebar.base import GroupHeading
from metatv.gui.sidebar.alerts_common import (
    _ROLE_KIND,
    _ROLE_SERIES_ID,
    _vod_count_label,
)


class MoviesSeriesMixin:
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

    def _show_idle_only_notice(self, watching: int) -> None:
        """One muted line for "you have alerts, none of them is firing".

        The alternative — an empty section — is indistinguishable from a broken
        one, which is the lesson EPG learned in #480.
        """
        from metatv.gui import icons as _icons

        item = QListWidgetItem(
            f"  {_icons.info_icon}  Nothing new from {watching} "
            f"alert{'s' if watching != 1 else ''}"
        )
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(_ROLE_KIND, "heading")
        item.setToolTip(
            f"You are watching for {watching} thing"
            f"{'s' if watching != 1 else ''}; none has anything new.\n"
            "Settings \u2192 Watch Alerts, or Manage Watch Alerts, can show "
            "them all."
        )
        self._vod_list.addItem(item)
        self._update_vod_toggle_label(0)
        self._vod_list.show()
        # Through the existing chokepoint, not a bare set_empty: it reads the
        # list's real contents (this notice counts) AND carries the guard for a
        # __new__'d test double, where set_empty raises RuntimeError.
        self._recompute_empty()

    def _hidden_note(self) -> str:
        """" · N not showing", when idle entries are being filtered out.

        A group heading reading "SERIES 2" with seven monitored series behind it
        is honest about what it lists and silent about what it does not. The
        count stays what is SHOWN — that is what a heading counts — and the
        difference goes in the tooltip, where it can say what to do about it.
        """
        hidden = self.__dict__.get("_idle_hidden", 0)
        if not hidden:
            return ""
        return (
            f"\n\n{hidden} with nothing new "
            f"{'is' if hidden == 1 else 'are'} not shown — turn on "
            '"Show alerts with nothing new" in Settings \u2192 Watch Alerts '
            "or in Manage Watch Alerts."
        )

    def _add_group_heading(self, text: str, count: int | None = None, *,
                           news: int = 0, on_click=None, tooltip: str = "") -> None:
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
            text, count, interactive=on_click is not None,
            tooltip=tooltip + self._hidden_note(), news=news,
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

        # Counted from the FULL sets above, then filtered for display. The
        # section is a noticeboard: by default it lists what has ARRIVED, not
        # the standing watchlist — that is Manage Watch Alerts' job, and for
        # EPG keywords the EPG view's Watch tab. The badge and the "N watching"
        # line still know about everything.
        _unviewed_for = getattr(
            self.config, "get_vod_rule_unviewed_count", lambda _c: 0
        )

        def _rule_is_firing(rule: dict) -> bool:
            """Whether this keyword rule has anything unseen, AVAILABLE-only.

            Same resolution order the rows use below: the re-validated count
            when a DB is wired, the raw config count otherwise. Reading it any
            other way would let a rule matched only on a disabled source count
            as firing here while its row said zero.
            """
            created = rule.get("created")
            if avail is not None:
                return avail.per_rule_unviewed.get(created, 0) > 0
            return _unviewed_for(created) > 0

        watching_total = len(rules) + len(series)
        if not getattr(self.config, "alerts_show_idle_items", False):
            rules = [r for r in rules if _rule_is_firing(r)]
            series = [e for e in series if e["unseen"] > 0]
        self._idle_hidden = watching_total - (len(rules) + len(series))

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
            if self._idle_hidden:
                # Alerts ARE configured; none of them is firing. Hiding the
                # group here would repeat exactly the bug #480 fixed for EPG:
                # a working feature rendering as an absent one.
                self._show_idle_only_notice(watching_total)
            else:
                self._vod_list.hide()
                self._recompute_empty()
            return

        # ── "Watching for" group heading ───────────────────────────────────
        # Only shown when BOTH groups are present — with a single group the
        # sub-section toggle already names it, so a heading would be redundant.
        # It is a collapse toggle like every other group heading; it used to be
        # NoItemFlags and inert while looking identical to the Series one.
        if rules and series:
            # The pill only when the group is CLOSED: expanded, each firing
            # row already carries its own green marker, and a pill on the
            # heading would say the same thing twice.
            self._add_group_heading(
                "Movies", len(rules),
                news=self._firing_count if self._keyword_collapsed else 0,
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

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, created)
            item.setData(_ROLE_KIND, "rule")
            count_tip = f"{count} match{'es' if count != 1 else ''} found" if count else "No matches yet"
            new_tip = f"\n{unviewed} new (unviewed)" if unviewed > 0 else ""
            item.setToolTip(
                f"Watching for: {text}\nType: {match_type}\n{count_tip}{new_tip}"
            )
            self._vod_list.addItem(item)
            row = _VodAlertRow(text, count_text, is_new=unviewed > 0)
            item.setSizeHint(row.sizeHint())
            self._vod_list.setItemWidget(item, row)

        # ── "Series" group heading + monitored-series rows ────────────────
        # The divider appears only when there ARE monitored series; it is a
        # collapse toggle (default expanded) so a heavy monitorer can tuck the
        # idle list away.
        if series:
            self._add_group_heading(
                "Series", len(series),
                news=self._series_new_count if self._series_collapsed else 0,
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
                        title, count_text,
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
            # No title rewrite: the title is the constant "Watch Alerts" now,
            # and the count reaches the header through the status pill below.
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

    def _build_series_context_menu(self, cid: str) -> QMenu:
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
