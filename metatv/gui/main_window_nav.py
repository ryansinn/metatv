"""Nav/view-switching mixin — chip toggling, view activation, filter controls.

Extracted from MainWindow; mixed in via:
    class MainWindow(_NavMixin, ..., QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

from loguru import logger

from metatv.core.repositories import RepositoryFactory

# ── QA deep-link target registry (single source of truth) ────────────────────
# ``navigate_to("view:<name>")`` maps a view name → (switch-method, chip attr).
# The chip attr is the ToggleChip to light up; ``None`` means the default list
# view (``switch_to_list_view`` manages its own chips).  Views/chips that are
# lazily created are guarded at call time, so an absent recipe build no-ops.
_NAV_VIEW_TARGETS: dict[str, tuple[str, str | None]] = {
    "browse": ("switch_to_list_view", None),
    "list": ("switch_to_list_view", None),
    "discover": ("switch_to_discover_view", "discover_chip"),
    "recipe": ("switch_to_recipe_view", "recipe_chip"),
    "epg": ("switch_to_epg_view", "epg_chip"),
    "preferences": ("switch_to_preferences_view", "prefs_chip"),
    "history": ("switch_to_full_history_view", None),
}


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
        # Deactivate the Missing TMDb diagnostic view if it exists and is visible
        if "missing_tmdb_view" in self.__dict__:
            if self.missing_tmdb_view.isVisible():
                self.missing_tmdb_view.on_deactivate()
        # Deactivate the Reconnect Engaged Content view if it exists and is visible
        if "reconnect_engaged_view" in self.__dict__:
            if self.reconnect_engaged_view.isVisible():
                self.reconnect_engaged_view.on_deactivate()
        # Deactivate the background metadata enrichment progress view if it
        # exists and is visible (the queue itself keeps running regardless).
        if "metadata_enrichment_view" in self.__dict__:
            if self.metadata_enrichment_view.isVisible():
                self.metadata_enrichment_view.on_deactivate()
        # Deactivate the Sources manager view if it exists and is visible (Wave 6 —
        # Sources moved out of the sidebar stack into the status strip + this view).
        if "sources_manager_view" in self.__dict__:
            if self.sources_manager_view.isVisible():
                self.sources_manager_view.on_deactivate()
        # Deactivate whichever Explore view (History / Favorites / Queue /
        # Recommended) is currently visible.  They are built lazily, so the dict may
        # be absent (early call) or empty.
        if "explore_views" in self.__dict__:
            for view in self.explore_views.values():
                if not view.isVisible():
                    continue
                view.on_deactivate()
                # Symmetric restore: re-expand exactly the flanking panels the
                # Explore activation auto-collapsed (see switch_to_explore_view), so
                # the sidebar + details pane return to their prior widths.
                splitter = getattr(self, "main_splitter", None)
                if splitter is not None:
                    for i in getattr(self, "_explore_restored_panels", (0, 2)):
                        splitter.expand_panel(i)
                    self._explore_restored_panels = []
        # EPG stats-line controls (source status + Refresh) belong to the EPG view
        # only — hide them whenever we blank the content area (guarded: the stats
        # line is built after this mixin's earliest possible call).
        if "epg_status_label" in self.__dict__:
            self.epg_status_label.setVisible(False)
            self.epg_refresh_btn.setVisible(False)
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
        if "missing_tmdb_view" in self.__dict__:
            self.missing_tmdb_view.setVisible(False)
        if "reconnect_engaged_view" in self.__dict__:
            self.reconnect_engaged_view.setVisible(False)
        if "metadata_enrichment_view" in self.__dict__:
            self.metadata_enrichment_view.setVisible(False)
        if "sources_manager_view" in self.__dict__:
            self.sources_manager_view.setVisible(False)
        if "explore_views" in self.__dict__:
            for view in self.explore_views.values():
                view.setVisible(False)
        self.search_controls.setVisible(False)
        self._hidden_banner.setVisible(False)
        # The channel-render banners live in _list_layout, not in any view, so
        # blanking the views never touched them: switching from the channel list
        # to e.g. Sources left "33 hidden by Global Exclusions" stranded above
        # the Sources header, reporting a CHANNEL count over an unrelated view.
        # _hide_channel_banners() is the single reset point for that group, so
        # call it here rather than re-listing the widgets (#266).
        self._hide_channel_banners()
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
        """Switch content area to series tree view.

        Records the originating view so that the Back button can return to it
        (e.g. Recipe → series drill → Back → Recipe, not channel list).
        """
        # Capture origin BEFORE hiding, so isVisible() still reflects the truth.
        if "recipe_view" in self.__dict__ and self.recipe_view.isVisible():
            self._series_return_view = "recipe"
        elif "discover_view" in self.__dict__ and self.discover_view.isVisible():
            self._series_return_view = "discover"
        else:
            self._series_return_view = "list"

        # Deactivate+hide every content overlay (recipe, discover, epg, preferences).
        # This is the fix for the stacking bug: without it the recipe_view overlay
        # remained visible when the series tree was shown on top of it.
        self._hide_all_content_views()

        self.view_mode = "series"
        # _hide_all_content_views() hides both channels_list and series_tree; re-show
        # only what series view needs.
        self.series_tree.setVisible(True)
        self.back_button.setVisible(True)
        self.breadcrumb_label.setText(f"{self.series_icon} {self.current_series.name}")
        self.search_input.setEnabled(False)
        self.search_input.setPlaceholderText("Search not available in series view")
        self.populate_series_tree()
        self.status_bar.showMessage(f"Viewing series: {self.current_series.name}")

    def switch_to_list_view(self):
        """Switch content area back to channel list view."""
        # The user picked a content view themselves, so the first-run
        # hand-off must not fire later and yank them somewhere else.
        # Note this is absent from switch_to_sources_manager on purpose:
        # adding the first source REQUIRES going there, and clearing the
        # flag on that trip would defeat the hand-off every time.
        self.__dict__.pop("_first_source_pending", None)
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
        # The user picked a content view themselves, so the first-run
        # hand-off must not fire later and yank them somewhere else.
        # Note this is absent from switch_to_sources_manager on purpose:
        # adding the first source REQUIRES going there, and clearing the
        # flag on that trip would defeat the hand-off every time.
        self.__dict__.pop("_first_source_pending", None)
        self.view_mode = "epg"
        self._hide_all_content_views()
        self.epg_view.setVisible(True)
        # Source status + Refresh ride on the stats line, only while EPG is active.
        # on_activate → _update_status_label emits epg_status_changed, which fills
        # epg_status_label (below).
        if "epg_status_label" in self.__dict__:
            self.epg_status_label.setVisible(True)
            self.epg_refresh_btn.setVisible(True)
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

    def _on_epg_status_changed(self, text: str, tooltip: str) -> None:
        """Main-thread slot: mirror the EPG view's source-freshness status onto the
        stats line (``epg_status_label``), right-aligned beside the programme count.

        The EPG view owns the status *text* (computed in ``_update_status_label``);
        it only lives on the stats line because that reads as one status strip with
        the "###,### EPG programmes" count.
        """
        if "epg_status_label" not in self.__dict__:
            return
        self.epg_status_label.setText(text)
        self.epg_status_label.setToolTip(tooltip)

    def switch_to_preferences_view(self) -> None:
        """Switch content area to the Taste / Preferences dashboard."""
        # The user picked a content view themselves, so the first-run
        # hand-off must not fire later and yank them somewhere else.
        # Note this is absent from switch_to_sources_manager on purpose:
        # adding the first source REQUIRES going there, and clearing the
        # flag on that trip would defeat the hand-off every time.
        self.__dict__.pop("_first_source_pending", None)
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
        # The user picked a content view themselves, so the first-run
        # hand-off must not fire later and yank them somewhere else.
        # Note this is absent from switch_to_sources_manager on purpose:
        # adding the first source REQUIRES going there, and clearing the
        # flag on that trip would defeat the hand-off every time.
        self.__dict__.pop("_first_source_pending", None)
        self.view_mode = "recipe"
        self._hide_all_content_views()
        self.recipe_view.setVisible(True)
        self.stats_label.setText("Recipe Builder")
        self.recipe_view.on_activate()

    def switch_to_sources_manager(self) -> None:
        """Switch content area to the Sources manager view.

        Opened from the sidebar status strip (Wave 6) — the one place to
        browse/edit/refresh/analyze/toggle/EPG-refresh a source now that
        Sources no longer lives in the sidebar section stack.
        """
        self.view_mode = "sources_manager"
        self._hide_all_content_views()
        self._deactivate_view_chips()  # management view — no chip of its own
        self.sources_manager_view.setVisible(True)
        self.stats_label.setText("Sources")
        self.sources_manager_view.on_activate()

    def switch_to_explore_view(self, key: str) -> None:
        """Switch content area to the Explore view for *key* (embedded trail-map).

        The ONE switch path behind all four "Explore →" sidebar links (and the
        ``navigate_to("view:<key>")`` deep-link seam): History, Favorites, Watch
        Queue and Recommended differ only by their ``ExploreSource``.  None of them
        has a nav chip, so every view chip is cleared and none is lit.

        Args:
            key: An ``EXPLORE_SOURCES`` key (history | favorites | queue |
                recommended).
        """
        view = self._ensure_explore_view(key)
        self.view_mode = view.source.view_mode
        self._hide_all_content_views()
        self._deactivate_view_chips()  # record/engaged view — no chip of its own
        view.setVisible(True)
        self.stats_label.setText(view.source.title)
        view.on_activate()
        # The embedded trail-map is boxed by the sidebar + details pane, so give it
        # the full window: auto-collapse both flanking panels (reusing the splitter's
        # own remember-and-restore collapse_panel, never snapshotting sizes here).  We
        # record ONLY the panels we actually collapse so the symmetric restore in
        # _hide_all_content_views doesn't pop open a details pane the user had shut.
        splitter = getattr(self, "main_splitter", None)
        if splitter is not None:
            self._explore_restored_panels = [
                i for i in (0, 2) if not splitter.is_panel_collapsed(i)
            ]
            for i in self._explore_restored_panels:
                splitter.collapse_panel(i)

    def switch_to_full_history_view(self) -> None:
        """Open the Watch-History Explore view — the named entry point kept for the
        ``view:history`` deep link and the sidebar History section."""
        self.switch_to_explore_view("history")

    def navigate_back(self):
        """Navigate back from series view to the originating view.

        If the drill came from the Recipe or Discover view, return there;
        otherwise fall back to the standard channel list.
        """
        origin = getattr(self, "_series_return_view", "list")
        self._series_return_view = "list"  # reset so stale state never leaks
        if origin == "recipe" and "recipe_view" in self.__dict__:
            self.switch_to_recipe_view()
        elif origin == "discover" and "discover_view" in self.__dict__:
            self.switch_to_discover_view()
        else:
            self.switch_to_list_view()

    # ── QA deep-link navigation seam ─────────────────────────────────────────

    def navigate_to(self, target: str) -> bool:
        """Jump the app to a QA deep-link *target* — the single nav chokepoint.

        Called by the dev QA checklist's "Go ▸" buttons.  Targets are
        ``"<kind>:<arg>"`` strings:

        - ``"view:<name>"``    — browse | list | discover | recipe | epg |
          preferences (see ``_NAV_VIEW_TARGETS``).
        - ``"settings:<tab>"`` — open the Settings dialog, optionally on a tab
          whose label contains ``<tab>`` (case-insensitive).
        - ``"sample:<kind>"``  — find a representative channel (vod | live |
          partial | series) and open Browse + its details.

        Args:
            target: The ``"<kind>:<arg>"`` deep-link string.

        Returns:
            True when navigation was dispatched; False for a malformed/unknown
            target (logged, no-op).  ``sample:`` returns True once the async
            lookup is dispatched — a no-match is handled in the result slot.
        """
        if not target or ":" not in target:
            logger.warning("navigate_to: ignoring malformed target '{}'", target)
            return False
        kind, _, arg = target.partition(":")
        kind = kind.strip().lower()
        arg = arg.strip()
        if kind == "view":
            return self._navigate_to_view(arg)
        if kind == "settings":
            self.open_settings(tab=arg or None)
            return True
        if kind == "sample":
            return self._navigate_to_sample(arg)
        logger.warning("navigate_to: unknown target kind '{}'", kind)
        return False

    def _navigate_to_view(self, name: str) -> bool:
        """Switch to the view named by a ``view:<name>`` deep-link.

        Lights up the view's nav chip (when it has one) and deactivates the
        others, then calls the registered ``switch_to_*`` method.  No-ops
        gracefully when the view/chip isn't built in this session.
        """
        from metatv.gui.explore_view import EXPLORE_SOURCES

        name = name.lower()
        mapping = _NAV_VIEW_TARGETS.get(name)
        if mapping is None:
            # Every Explore entry point is deep-linkable by its source key
            # (favorites | queue | recommended; "history" is in the table above).
            if name in EXPLORE_SOURCES:
                self.switch_to_explore_view(name)
                return True
            logger.warning("navigate_to: unknown view '{}'", name)
            return False
        method_name, chip_attr = mapping
        switch = getattr(self, method_name, None)
        if switch is None:
            logger.warning("navigate_to: nav method {} missing", method_name)
            return False
        if chip_attr is not None:
            chip = getattr(self, chip_attr, None)
            if chip is None:
                logger.warning("navigate_to: chip {} unavailable", chip_attr)
                return False
            chip.blockSignals(True)
            chip.set_enabled(True)
            chip.blockSignals(False)
            self._deactivate_view_chips(chip)
        switch()
        return True

    def _navigate_to_sample(self, kind: str) -> bool:
        """Resolve a representative ``sample:<kind>`` channel and open it.

        The channel lookup runs through the async seam (channels is a large
        table); the result slot lands on Browse and opens the channel's details.
        """
        self._run_query(
            lambda repos: repos.channels.get_sample_channel_id(kind),
            self._on_sample_channel_resolved,
        )
        return True

    def _on_sample_channel_resolved(self, channel_id: str | None) -> None:
        """Main-thread slot: open the resolved sample channel in Browse + details."""
        if not channel_id:
            logger.info("navigate_to: no matching channel for sample deep-link")
            return
        self.switch_to_list_view()
        self.show_channel_details_by_id(channel_id)

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

    def on_sources_manager_toggle(self) -> None:
        """Sources status strip click — toggle the Sources manager open/closed.

        The strip is a plain clickable widget, not a checkable chip (Sources
        manager has no chip of its own — see switch_to_sources_manager), so
        this compares ``view_mode`` directly instead of a chip's checked state.
        Closing goes to switch_to_list_view() — the same fixed "close" target
        every other toggle-to-close view uses (on_discover_view_toggle et al.);
        it runs _hide_all_content_views(), which calls the Sources manager's
        on_deactivate() before hiding it.
        """
        if self.view_mode == "sources_manager":
            self.switch_to_list_view()
        else:
            self.switch_to_sources_manager()

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
            or bool(getattr(self.config, "global_filter_excluded_tag_content_types", []))
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
        if "recipe_view" in self.__dict__:
            self.recipe_view.reload()
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
            if "recipe_view" in self.__dict__:
                self.recipe_view.reload()
            self._refresh_recommended_section()

    def _open_categories_dialog(self) -> None:
        from metatv.gui.categories_dialog import CategoriesDialog
        dlg = CategoriesDialog(self.db, self.config, self)
        dlg.exec()
        self.load_channels()

    # ── Context filters (genre / person / tag click in details pane) ─────────

    def _reset_context_filters(self) -> None:
        """Null every details-pane context filter state var (mutual exclusion).

        Context filters are mutually exclusive — at most one chip active at a
        time.  Each handler calls this before setting its own var, and
        ``_clear_context_filter`` calls it on dismiss.  One chokepoint so a new
        filter type can never silently coexist with a stale one.
        """
        self._details_genre_filter = None
        self._details_person_filter = None
        self._details_tag_filter = None
        self._details_category_filter = None
        self._details_id_filter = None

    def _on_genre_filter_requested(self, genre: str) -> None:
        """Strict SQL genre filter from details-pane chip click."""
        self._reset_context_filters()
        self._details_genre_filter = genre
        self._context_filter_label.setText(f"Genre: {genre}")
        self._context_filter_chip.show()
        self._save_search_state()
        self.switch_to_list_view()
        self.load_channels()

    def _on_person_filter_requested(self, name: str) -> None:
        """Strict SQL cast/crew filter from details-pane chip click."""
        self._reset_context_filters()
        self._details_person_filter = name
        self._context_filter_label.setText(f"Cast/Crew: {name}")
        self._context_filter_chip.show()
        self._save_search_state()
        self.switch_to_list_view()
        self.load_channels()

    def _on_tag_filter_requested(self, facet_type: str, value: str) -> None:
        """Left-click a tag chip → strict context filter for that exact facet.

        COLLECTION is special: it resolves to the curated provider category the
        current channel belongs to (``ChannelDB.category``), NOT a re-derived
        query on the lossy 'collection' residual — so the user sees the actual
        human-curated set.  Every other facet filters on the exact (type, value)
        tag (no hierarchy rollup, v1).
        """
        self._reset_context_filters()
        if facet_type == "collection":
            category = self._resolve_current_channel_category()
            if not category:
                # No curated category to resolve to — leave the list unchanged.
                return
            self._details_category_filter = category
            self._context_filter_label.setText(f"Collection: {category}")
        else:
            self._details_tag_filter = (facet_type, value)
            label = facet_type.replace("_", " ").title()
            self._context_filter_label.setText(f"{label}: {value}")
        self._context_filter_chip.show()
        self._save_search_state()
        self.switch_to_list_view()
        self.load_channels()

    def _on_row_chip_clicked(self, facet: str, value: str) -> None:
        """A chip in a channel-list row was clicked → strict context filter.

        Routes into the SAME handlers a details-pane metadata click uses rather
        than opening a third filtering path (docs/CONTEXT_FILTER_CHIPS.md, and
        CLAUDE.md's single-chokepoint rule): genre has its own dedicated strict
        filter, and the remaining facets are exactly the tag-facet vocabulary
        ``tag_decomposer`` emits, so they go through the tag handler unchanged.

        The delegate only attaches a facet to chips that can actually filter —
        the year and ``×N`` variant chips carry a tooltip but no facet — so an
        unknown facet here means the two have drifted, and it is logged rather
        than silently ignored.

        Args:
            facet: Tag facet type, e.g. ``"quality"``/``"region"``/``"language"``.
            value: The chip's stored value (a code, not its display label).
        """
        from metatv.core.channel_name_utils import tag_value_for

        if not facet or not value:
            return

        if facet == "genre":
            self._on_genre_filter_requested(value)
            return

        if facet == "collection":
            # NOT via _on_tag_filter_requested: its collection branch resolves
            # the CURRENTLY SELECTED channel's category and ignores the value
            # passed in. That is right for a details-pane click (the pane always
            # describes the selected row) but wrong here — a chip click
            # deliberately does not change the selection, so it would filter by
            # whatever happened to be selected before. Set the category filter
            # from the CHIP's own value instead.
            self._reset_context_filters()
            self._details_category_filter = value
            self._context_filter_label.setText(f"Collection: {value}")
            self._context_filter_chip.show()
            self._save_search_state()
            self.switch_to_list_view()
            self.load_channels()
            return

        if facet in ("quality", "region", "language", "audio"):
            # The chip DISPLAYS a code/token; the tag table stores a resolved
            # name or group ("EN" → "English", "4K" → "4K / UHD"). Filtering on
            # the displayed string matched nothing and emptied the list.
            tag_value = tag_value_for(facet, value)
            if not tag_value:
                logger.warning(
                    f"row chip {facet}={value!r} has no tag-table equivalent — "
                    f"not filtering (an empty list would look like a broken filter)"
                )
                return
            self._on_tag_filter_requested(facet, tag_value)
            return

        logger.warning(
            f"row chip emitted an unroutable facet {facet!r} — the delegate's "
            f"facet vocabulary has drifted from tag_decomposer's"
        )

    def _on_tag_discover_requested(self, facet_type: str, value: str) -> None:
        """Right-click a tag chip → open the Recipe view seeded with this one tag.

        Reuses the existing recipe/discover-shelf engine (the tag-facet → poster
        shelf path) rather than hand-rolling a parallel discover surface: the
        Recipe view's "Now Plating" grid IS the one-ingredient-recipe shelf.
        """
        # Activate the Recipe view the same way clicking the Recipe nav chip does.
        if "recipe_chip" in self.__dict__:
            self.recipe_chip.blockSignals(True)
            self.recipe_chip.set_enabled(True)
            self.recipe_chip.blockSignals(False)
            self._deactivate_view_chips(self.recipe_chip)
        self.switch_to_recipe_view()
        self.recipe_view.seed_facet(facet_type, value)

    def _resolve_current_channel_category(self) -> str | None:
        """Return the curated ``category`` of the channel shown in the details pane.

        Single-row PK lookup (the details-pane DTO does not carry category).  Used
        to resolve a COLLECTION chip click to the human-curated provider grouping.
        """
        from metatv.core.database import ChannelDB

        ch = getattr(self.details_pane, "current_channel", None)
        cid = getattr(ch, "id", None)
        if not cid:
            return None
        with self.db.session_scope() as session:
            row = (
                session.query(ChannelDB.category)
                .filter(ChannelDB.id == cid)
                .first()
            )
        return row[0] if row and row[0] else None

    def _clear_context_filter(self) -> None:
        """Dismiss the details-pane context filter and restore normal results."""
        self._reset_context_filters()
        self._context_filter_chip.hide()
        self._save_search_state()
        self.load_channels()

