"""Nav/view-switching mixin — chip toggling, view activation, filter controls.

Extracted from MainWindow; mixed in via:
    class MainWindow(_NavMixin, ..., QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

from loguru import logger

from metatv.core.repositories import RepositoryFactory


class _NavMixin:
    """Mixin: view switching, chip activation, filter controls."""

    # ── Content-area blanking ───────────────────────────────────────────────

    def _hide_all_content_views(self) -> None:
        """Blank-slate all views. Call before activating any single view."""
        if self.epg_view.isVisible():
            self.epg_view.on_deactivate()
        if self.discover_view.isVisible():
            self.discover_view.on_deactivate()
        if self.preferences_view.isVisible():
            self.preferences_view.on_deactivate()
        # Deactivate source analytics view if it exists and is visible
        if "source_analytics" in self.__dict__:
            if self.source_analytics.isVisible():
                self.source_analytics.on_deactivate()
        # Deactivate recipe view if it exists and is visible
        if "recipe_view" in self.__dict__:
            if self.recipe_view.isVisible():
                self.recipe_view.on_deactivate()
        self.channels_list.setVisible(False)
        self.series_tree.setVisible(False)
        self.epg_view.setVisible(False)
        self.preferences_view.setVisible(False)
        self.discover_view.setVisible(False)
        self.provider_editor.setVisible(False)
        if "source_analytics" in self.__dict__:
            self.source_analytics.setVisible(False)
        if "recipe_view" in self.__dict__:
            self.recipe_view.setVisible(False)
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

        if hasattr(self, 'channel_model') and self.channel_model.rowCount() > 0:
            # Banners are now in the banner strip, not in the model, so rowCount()
            # equals the number of real channel rows. It reflects what's loaded so
            # far (paging loads more on scroll), so report the loaded count plainly
            # — the legacy `all_channels` cache only holds page 1 and would make
            # "of Y / filtered out" go negative once more pages stream in.
            shown = self.channel_model.rowCount()
            self.stats_label.setText(f"Showing {shown:,} channels")

        self.current_series = None
        self.series_data = None
        self.status_bar.showMessage("Returned to channel list")

    def switch_to_epg_view(self):
        """Switch content area to EPG view."""
        self.view_mode = "epg"
        self._hide_all_content_views()
        self.epg_view.setVisible(True)
        self.epg_view.on_activate()
        self.stats_label.setText("EPG — counting…")
        provider_ids = list(self.epg_view._provider_ids)
        self._run_query(
            lambda repos: repos.epg.count_by_providers(provider_ids),
            self._on_epg_count_loaded,
            token_ref=self._epg_count_token,
            on_error=self._on_epg_count_failed,
        )

    def _on_epg_count_loaded(self, total: int) -> None:
        """Main-thread slot: update stats_label with the EPG programme count."""
        if self.view_mode != "epg":
            return
        self.stats_label.setText(f"{total:,} EPG programmes" if total else "EPG — fetching…")

    def _on_epg_count_failed(self, exc: Exception) -> None:
        """Main-thread slot: clear the "counting…" placeholder if the count query fails."""
        if self.view_mode != "epg":
            return
        self.stats_label.setText("EPG — count unavailable")

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

    def switch_to_recipe_view(self) -> None:
        """Switch content area to the Recipe builder view."""
        self.view_mode = "recipe"
        self._hide_all_content_views()
        self.recipe_view.setVisible(True)
        self.stats_label.setText("Recipe Builder")
        self.recipe_view.on_activate()

    def navigate_back(self):
        """Navigate back from series view to channel list."""
        self.switch_to_list_view()

    # ── View/chip wiring ────────────────────────────────────────────────────

    def _on_view_channel_selected(self, channel):
        """Handle channel selected from a content view."""
        if channel:
            self.details_pane.show_channel(channel)

    def _deactivate_view_chips(self, *keep) -> None:
        """Deactivate all view chips except those in keep."""
        chips = [self.search_chip, self.epg_chip, self.prefs_chip, self.discover_chip]
        if "recipe_chip" in self.__dict__:
            chips.append(self.recipe_chip)
        for chip in chips:
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

    def on_recipe_view_toggle(self) -> None:
        if self.recipe_chip.is_enabled():
            self._deactivate_view_chips(self.recipe_chip)
            self.switch_to_recipe_view()
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
        self._save_search_state()
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
        self._save_search_state()
        self.switch_to_list_view()
        self.load_channels()

    def _on_person_filter_requested(self, name: str) -> None:
        """Strict SQL cast/crew filter from details-pane chip click."""
        self._details_genre_filter = None
        self._details_person_filter = name
        self._context_filter_label.setText(f"Cast/Crew: {name}")
        self._context_filter_chip.show()
        self._save_search_state()
        self.switch_to_list_view()
        self.load_channels()

    def _clear_context_filter(self) -> None:
        """Dismiss the details-pane context filter and restore normal results."""
        self._details_genre_filter = None
        self._details_person_filter = None
        self._context_filter_chip.hide()
        self._save_search_state()
        self.load_channels()

