"""Nav/view-switching mixin — chip toggling, view activation, filter controls.

Extracted from MainWindow; mixed in via:
    class MainWindow(_NavMixin, ..., QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

from loguru import logger

from metatv.core.repositories import RepositoryFactory


class _NavMixin:
    """Mixin: view switching, chip activation, filter controls, prefix migration."""

    # ── Content-area blanking ───────────────────────────────────────────────

    def _hide_all_content_views(self) -> None:
        """Blank-slate all views. Call before activating any single view."""
        if self.epg_view.isVisible():
            self.epg_view.on_deactivate()
        if self.discover_view.isVisible():
            self.discover_view.on_deactivate()
        if self.preferences_view.isVisible():
            self.preferences_view.on_deactivate()
        self.channels_list.setVisible(False)
        self.series_tree.setVisible(False)
        self.epg_view.setVisible(False)
        self.preferences_view.setVisible(False)
        self.discover_view.setVisible(False)
        self.provider_editor.setVisible(False)
        self.search_controls.setVisible(False)
        self._hidden_banner.setVisible(False)
        if hasattr(self, "filter_panel"):
            self.filter_panel.setVisible(False)
        self._hidden_mode = False
        if hasattr(self, "_tab_all_btn"):
            self._tab_all_btn.setChecked(True)
            self._tab_hidden_btn.setChecked(False)
        self.back_button.setVisible(False)
        self.breadcrumb_label.setText("")

    # ── Switch-to helpers ───────────────────────────────────────────────────

    def switch_to_series_view(self):
        """Switch content area to series tree view."""
        self.view_mode = "series"
        self.channels_list.setVisible(False)
        self.series_tree.setVisible(True)
        self.back_button.setVisible(True)
        self.breadcrumb_label.setText(f"{self.series_icon} {self.current_series.name}")
        self.search_input.setEnabled(False)
        self.search_input.setPlaceholderText("Search not available in series view")
        self.populate_series_tree()
        self.status_bar.showMessage(f"Viewing series: {self.current_series.name}")

    def switch_to_list_view(self):
        """Switch content area back to channel list view."""
        self.view_mode = "list"
        self._in_provider_edit_mode = False
        self._hide_all_content_views()
        self._deactivate_view_chips(self.search_chip)
        self.search_chip.blockSignals(True)
        self.search_chip.set_enabled(True)
        self.search_chip.blockSignals(False)

        self.channels_list.setVisible(True)
        self.search_controls.setVisible(True)
        if hasattr(self, "filter_panel"):
            self.filter_panel.setVisible(True)
        self.search_input.setEnabled(True)
        self.search_input.setPlaceholderText("Filter channels by name, category...")

        if hasattr(self, 'all_channels') and self.all_channels:
            total_channels = len(self.all_channels)
            shown = self.channels_list.count()
            for i in range(self.channels_list.count()):
                item = self.channels_list.item(i)
                if not item.data(1):  # Qt.ItemDataRole.UserRole == 1
                    shown -= 1
            filtered = total_channels - shown
            if filtered > 0:
                self.stats_label.setText(f"Showing {shown:,} of {total_channels:,} · {filtered:,} filtered out")
            else:
                self.stats_label.setText(f"Showing {shown:,} of {total_channels:,} channels")

        self.current_series = None
        self.series_data = None
        self.status_bar.showMessage("Returned to channel list")

    def switch_to_epg_view(self):
        """Switch content area to EPG view."""
        self.view_mode = "epg"
        self._hide_all_content_views()
        self.epg_view.setVisible(True)
        self.epg_view.on_activate()
        total = self.epg_manager.get_total_programmes(self.epg_view._provider_ids)
        self.stats_label.setText(f"{total:,} EPG programmes" if total else "EPG — fetching…")

    def switch_to_preferences_view(self) -> None:
        """Switch content area to the Taste / Preferences dashboard."""
        self.view_mode = "preferences"
        self._hide_all_content_views()
        self.preferences_view.setVisible(True)
        self.stats_label.setText("Preference dashboard")
        self.preferences_view.on_activate()

    def switch_to_discover_view(self) -> None:
        """Switch content area to the Discovery browse view."""
        self.view_mode = "discover"
        self._hide_all_content_views()
        self.discover_view.setVisible(True)
        self.stats_label.setText("Discover")
        self.discover_view.on_activate()

    def navigate_back(self):
        """Navigate back from series view to channel list."""
        self.switch_to_list_view()

    # ── Special-content playback ────────────────────────────────────────────

    def play_special_event(self, channel):
        """Play a channel from a special content view."""
        logger.info(f"Playing special event: {channel.name}")
        if not channel.stream_url:
            self.status_bar.showMessage(f"No stream URL available for {channel.name}")
            return
        self.player_manager.play(channel.stream_url, channel.name)
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.mark_played(channel.id)
        finally:
            session.close()
        self.status_bar.showMessage(f"Playing: {channel.name}")

    # ── View/chip wiring ────────────────────────────────────────────────────

    def _on_view_channel_selected(self, channel):
        """Handle channel selected from a content view."""
        if channel:
            self.details_pane.show_channel(channel)

    def _deactivate_view_chips(self, *keep) -> None:
        """Deactivate all view chips except those in keep."""
        for chip in (self.search_chip, self.epg_chip, self.prefs_chip,
                     self.discover_chip):
            if chip not in keep:
                chip.blockSignals(True)
                chip.set_enabled(False)
                chip.blockSignals(False)

    def on_special_view_toggle(self) -> None:
        if self.epg_chip.is_enabled():
            self._deactivate_view_chips(self.epg_chip)
            self.switch_to_epg_view()
        else:
            self.switch_to_list_view()

    def on_preferences_view_toggle(self) -> None:
        if self.prefs_chip.is_enabled():
            self._deactivate_view_chips(self.prefs_chip)
            self.switch_to_preferences_view()
        else:
            self.switch_to_list_view()

    def on_discover_view_toggle(self) -> None:
        if self.discover_chip.is_enabled():
            self._deactivate_view_chips(self.discover_chip)
            self.switch_to_discover_view()
        else:
            self.switch_to_list_view()

    def on_search_view_toggle(self) -> None:
        if self.search_chip.is_enabled():
            self.switch_to_list_view()
            self.load_channels()
        else:
            self.search_chip.blockSignals(True)
            self.search_chip.set_enabled(True)
            self.search_chip.blockSignals(False)

    def on_hidden_view_toggle(self) -> None:
        self._set_search_tab(True)

    def _set_search_tab(self, hidden: bool) -> None:
        """Switch the channel list between All and Hidden tabs."""
        self._tab_all_btn.setChecked(not hidden)
        self._tab_hidden_btn.setChecked(hidden)
        self._hidden_mode = hidden
        if hidden:
            self.view_mode = "hidden"
            self._hidden_banner.setVisible(True)
            self.stats_label.setText("Hidden channels")
            if self.view_mode not in ("hidden", "list"):
                self._hide_all_content_views()
                self.channels_list.setVisible(True)
                self.search_controls.setVisible(True)
        else:
            self.view_mode = "list"
            self._hidden_banner.setVisible(False)
        self.load_channels()

    # ── Filter controls ─────────────────────────────────────────────────────

    def _update_filter_btn_state(self) -> None:
        """Sync FilterChip visual state with current filter config."""
        active = (
            bool(self.config.global_filter_excluded_categories)
            or bool(self.config.global_filter_excluded_content_types)
            or bool(self.config.global_filter_excluded_prefixes)
            or bool(getattr(self.config, "global_filter_excluded_user_categories", []))
            or bool(getattr(self.config, "global_filter_excluded_source_categories", []))
            or not getattr(self.config, "global_filter_include_uncategorized", True)
        )
        self._filter_chip.set_filter_state(active, self.config.global_filter_paused)

    def _on_filter_toggle(self, resume: bool) -> None:
        """FilterChip clicked while filters are set: resume=True → unpause, False → pause."""
        self.config.global_filter_paused = not resume
        self.config.save()
        self._update_filter_btn_state()
        self.load_channels()
        if hasattr(self, "discover_view"):
            self.discover_view.reload()
        if hasattr(self, "preferences_view"):
            self.preferences_view.refresh()
        self._refresh_recommended_section()

    def _open_global_filter_dialog(self) -> None:
        from metatv.gui.global_filter_dialog import GlobalFilterDialog
        dlg = GlobalFilterDialog(self.db, self.config, self)
        if dlg.exec() == GlobalFilterDialog.DialogCode.Accepted:
            self.config.global_filter_paused = False
            self.config.save()
            self._update_filter_btn_state()
            self.load_channels()
            if hasattr(self, "discover_view"):
                self.discover_view.reload()
            if hasattr(self, "preferences_view"):
                self.preferences_view.refresh()
            self._refresh_recommended_section()

    def _open_categories_dialog(self) -> None:
        from metatv.gui.categories_dialog import CategoriesDialog
        dlg = CategoriesDialog(self.db, self.config, self)
        dlg.exec()
        self.load_channels()

    # ── Context filters (genre / person click in details pane) ──────────────

    def _on_genre_filter_requested(self, genre: str) -> None:
        """Strict SQL genre filter from details-pane chip click."""
        self._details_person_filter = None
        self._details_genre_filter = genre
        self._context_filter_label.setText(f"Genre: {genre}")
        self._context_filter_chip.show()
        self.switch_to_list_view()
        self.load_channels()

    def _on_person_filter_requested(self, name: str) -> None:
        """Strict SQL cast/crew filter from details-pane chip click."""
        self._details_genre_filter = None
        self._details_person_filter = name
        self._context_filter_label.setText(f"Cast/Crew: {name}")
        self._context_filter_chip.show()
        self.switch_to_list_view()
        self.load_channels()

    def _clear_context_filter(self) -> None:
        """Dismiss the details-pane context filter and restore normal results."""
        self._details_genre_filter = None
        self._details_person_filter = None
        self._context_filter_chip.hide()
        self.load_channels()

    # ── Compound-prefix migration ───────────────────────────────────────────

    _PREFIX_PARSE_VERSION = 6  # bumped: [4K][US] bracket quality parsing, numeric prefix guard, 24/7 title strip, Guard-3 prefix clear, · display format

    def _check_prefix_migration(self) -> None:
        """Run a one-time background rescan if prefix parsing logic has been updated."""
        if getattr(self.config, "prefix_parse_version", 0) < self._PREFIX_PARSE_VERSION:
            self.executor.submit(self._bg_prefix_migration)

    def _bg_prefix_migration(self) -> None:
        """Worker: reparse all channels' detected_prefix/quality for compound prefixes."""
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes()
        self._prefix_migration_done.emit()

    def _on_prefix_migration_done(self) -> None:
        """Called on main thread when the background prefix migration finishes."""
        self.config.prefix_parse_version = self._PREFIX_PARSE_VERSION
        self.config.save()
        self.load_channels()
