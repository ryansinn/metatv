"""DEBT-1b — the watch-alert family, moved verbatim.

``_AlertsMixin`` is mixed into :class:`~metatv.gui.main_window.MainWindow`
(main_window.py's class bases), same shape as every other ``main_window_*.py``
mixin: its methods read/write ``self.*`` attributes MainWindow's
``__init__``/``setup_ui`` already establish (``self.config``, ``self.db``,
``self.epg_manager``, ``self.sidebar_sections``, ``self.status_bar``,
``self.vod_watch_alert_manager``, ``self.channel_model``, ``self.details_pane``).

``main_window.py`` is PINNED by the code-health ratchet and is the one file
that grows at every measurement — this is a pure extraction, not a rewrite.
Every method here is the SAME body, docstring and rationale comment it had in
``main_window.py``; nothing was reworded, reordered within a function, or
changed in behaviour.

The series-monitor leftovers (``_monitor_series``, ``_on_details_monitor_toggled``,
``_on_mark_series_seen``, ``_backfill_series_display_titles``) were NOT moved
here — DEBT-1b left them on ``MainWindow`` (cohesion over arithmetic; moving
them into either mixin then would have scattered one small cohesive group
rather than shrink one). DEBT-1c later folded them into ``_SeriesMixin``
(``main_window_series.py``) once that file had room, after its playback
family moved out to ``main_window_series_playback.py``. Several call sites in
this file reach back into ``MainWindow`` for methods that stayed behind
(``self._refresh_queue_section``,
``self._relink_epg_channel``, ``self._on_vod_rule_show_matches``,
``self._set_search_text_silently``, ``self._save_search_state``,
``self.switch_to_list_view``, ``self.load_channels``,
``self.show_channel_details_by_id``) — the same cross-mixin pattern
``main_window_overlays.py``'s ``_OverlaysMixin`` and
``main_window_menu_actions.py``'s ``_MenuActionsMixin`` already use.
``self.*`` attribute lookup does not care which class in the MRO defines
the name.
"""

from __future__ import annotations


class _AlertsMixin:
    """Mixin: EPG-link and VOD watch-alert handlers for the sidebar/details pane."""

    def _refresh_watch_alerts(self, *_) -> None:
        """Refresh the sidebar Watch Alerts section after any EPG data update."""
        section = self.sidebar_sections.get("alerts")
        if section:
            section.refresh()

    def _clear_epg_link(self, channel_id: str) -> None:
        """Unlink this channel's EPG guide data and block it from re-matching.

        Handler for the channel-menu "Clear EPG link" action and the details-pane
        rail's 🧹 button. Delegates to ``EpgManager.clear_channel_epg_link`` — the
        single chokepoint that persists the block (``config.epg_link_blocklist``)
        and nulls the DB link on its single-worker executor.
        """
        self.epg_manager.clear_channel_epg_link(channel_id)

    def _on_details_clear_epg_link(self, channel_id: str) -> None:
        """Details-pane rail 🧹 click — toggles clear/re-link by current blocked state.

        The single rail button mirrors the channel-menu action's toggle: check
        ``config.epg_link_blocklist`` (the same source of truth the pane's own
        ``ChannelActionState.epg_link_blocked`` was populated from) to decide
        which half of the pair applies.
        """
        if channel_id in (self.config.epg_link_blocklist or []):
            self._relink_epg_channel(channel_id)
        else:
            self._clear_epg_link(channel_id)

    def _refresh_vod_alerts_section(self) -> None:
        """Refresh the VOD watch-for sub-list in the Alerts sidebar section."""
        section = self.sidebar_sections.get("alerts")
        if section and hasattr(section, "refresh_vod_rules"):
            section.refresh_vod_rules()

    def _refresh_alert_visibility(self) -> None:
        """Single chokepoint: refresh every alert-visibility surface from config.

        Called after a new match is found and after any clear (per-item or bulk) so
        the green + 🚨 cue stays consistent everywhere: the Alerts sidebar badge +
        rule rows, the Watch Queue pinned line, the channel-list rows, and the
        details Alert button for the currently-shown title.
        """
        self._refresh_vod_alerts_section()
        self._refresh_queue_section()
        # Channel-list rows — repaint with the fresh unviewed set (no full reload).
        model = getattr(self, "channel_model", None)
        if model is not None and hasattr(model, "update_new_match_ids"):
            model.update_new_match_ids(self.config.get_unviewed_vod_match_ids())
        # Details pane — re-evaluate the Alert button for the shown title.
        pane = getattr(self, "details_pane", None)
        current = getattr(pane, "current_channel", None) if pane is not None else None
        if current is not None and getattr(current, "id", None):
            ab = getattr(pane, "_action_bar", None)
            if ab is not None and hasattr(ab, "set_new_match"):
                ab.set_new_match(self.config.is_vod_match_unviewed(current.id))

    def _on_alerts_matched_clicked(self, channel_id: str) -> None:
        """Watch Queue 'Alerts Matched' row click: open details AND ack the match.

        Reuses the existing per-match "viewed" chokepoint
        (``Config.mark_vod_alert_match_viewed`` — marks the channel viewed across
        every rule that alerted it) rather than adding a parallel method, then
        re-runs the single alert-visibility refresh so the Alerts Matched rows,
        the pinned banner count, and every other alert-visibility surface can't
        disagree.
        """
        self.show_channel_details_by_id(channel_id)
        if self.config.mark_vod_alert_match_viewed(channel_id):
            self._refresh_alert_visibility()

    def _clear_vod_alert(self, channel_id: str) -> None:
        """Acknowledge a single matched channel (per-item 'Clear alert')."""
        if not channel_id:
            return
        if self.config.mark_vod_alert_match_viewed(channel_id):
            self._refresh_alert_visibility()

    def _clear_all_alerts(self) -> None:
        """Bulk-acknowledge every new match (Alerts header 'Clear all')."""
        cleared = self.config.mark_all_vod_alerts_viewed()
        if cleared:
            self._refresh_alert_visibility()
            self.status(
                f"Cleared {cleared} new-match alert{'s' if cleared != 1 else ''}",
                ms=0,
            )

    def _clear_vod_rule_alert(self, rule_created: str) -> None:
        """Acknowledge just one rule's matches (Alerts row 'Clear this alert')."""
        cleared = self.config.mark_vod_rule_viewed(rule_created)
        if cleared:
            self._refresh_alert_visibility()
            self.status(
                f"Cleared {cleared} new-match alert{'s' if cleared != 1 else ''}",
                ms=0,
            )

    def _on_queue_new_matches_clicked(self) -> None:
        """Open the new matched content from the Watch Queue's pinned green line.

        Shows the STORED matched ids (via ``_on_vod_rule_show_matches``) for the rule
        with the most unviewed matches, so the results list opens with the new items
        flagged 🚨/green.  No-op if nothing is unviewed.
        """
        best_rule = None
        best_count = 0
        for rule in self.config.get_vod_watch_alerts():
            n = self.config.get_vod_rule_unviewed_count(rule.get("created", ""))
            if n > best_count:
                best_count = n
                best_rule = rule
        if best_rule is not None:
            self._on_vod_rule_show_matches(best_rule.get("created", ""))

    def _on_add_watch_for(self) -> None:
        """Open the 'Watch for…' dialog; add rule to config + run a check on confirm."""
        from metatv.gui.vod_watch_alert_dialog import WatchForDialog
        dlg = WatchForDialog(self)

        def _on_rule_added(rule: dict) -> None:
            self.config.add_vod_watch_alert(rule)
            # Seed the rule with what already matches, recorded as ALREADY SEEN
            # (see VodWatchAlertManager.baseline_rule): this dialog is headed
            # "Watch for new content" and promises an alert when matching
            # content "appears on any of your sources", so the catalogue as it
            # stands right now is the rule's starting point, not 102 pieces of
            # news. The backlog stays one click away via the rule's own "View
            # matches". baseline_rule emits new_matches_found when it lands,
            # which runs the composite refresh.
            self.vod_watch_alert_manager.baseline_rule(rule)
            self._refresh_alert_visibility()

        dlg.rule_added.connect(_on_rule_added)
        dlg.exec()

    def _open_vod_alerts_dialog(self) -> None:
        """Open the manage-rules dialog (see-all + remove)."""
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog
        dlg = ManageVodAlertsDialog(self.config, self)
        # ``changed`` fires from _finalize_pending_removals — i.e. rules and
        # monitored series were DELETED, taking their matches with them, so
        # every alert-visibility surface has to re-read (not just this section).
        dlg.changed.connect(self._refresh_alert_visibility)
        dlg.view_matches_requested.connect(self._on_vod_rule_view_matches)
        dlg.exec()

    def _on_vod_rule_view_matches(self, text: str, match_type: str) -> None:
        """Populate the main channel list with content matching a VOD watch-for rule.

        Sets the search box to the rule's keyword, switches to the list view, and
        triggers a channel load.  The existing media-type filter remains unchanged so
        the user is not surprised by their panel state changing; the keyword alone
        surfaces the relevant content.
        """
        # Set the search text without retriggering the debounce (load is issued below).
        if hasattr(self, "search_input"):
            self._set_search_text_silently(text)

        self._save_search_state()
        self.switch_to_list_view()
        self.load_channels()
