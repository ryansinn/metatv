"""Nav/view-switching mixin — chip toggling, view activation, filter controls.

Extracted from MainWindow; mixed in via:


class MainWindow(_NavMixin, ..., QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

from loguru import logger

from metatv.gui import deferred_config_save as _cfgsave


#: Every host-owned widget that occupies the content area, in no particular
#: order. ``_hide_all_content_views`` iterates it to deactivate and hide them —
#: one list, so a view added to the deactivation half and forgotten in the
#: hiding half cannot happen again (it happened).
#:
#: Lazily-built views are simply absent from the host until first use, so the
#: loop reads ``self.__dict__`` — see the note at the loop for why that is not
#: interchangeable with ``getattr``.
CONTENT_VIEW_ATTRS: tuple[str, ...] = (
    "channels_list",
    "series_tree",
    "epg_view",
    "preferences_view",
    "discover_view",
    "provider_editor",
    "source_analytics_view",
    "recipe_view",
    "missing_tmdb_view",
    "reconnect_engaged_view",
    "metadata_enrichment_view",
    "sources_manager_view",
)



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

#: Retired ``view:<name>`` targets — nav surfaces that used to exist and are
#: gone, but old What's New ``test_steps`` are an append-only, never-edited
#: historical record (CLAUDE.md) that still names them. Each maps the retired
#: name to the CURRENT ``_NAV_VIEW_TARGETS`` key it should resolve to, so a
#: legacy deep link lands on something coherent instead of silently no-oping.
#:
#: "sports"/"events" -> "list": the Sports and Events views were retired
#: (owner: "it's better the channels are just in search results flagged as
#: live") — live sports channels are found in the list/search view now, so
#: that is where their old deep links land.
_RETIRED_NAV_VIEW_TARGETS: dict[str, str] = {
    "sports": "list",
    "events": "list",
}


class _NavMixin:
    """Mixin: view switching, chip activation, filter controls."""

    # ── Content-area blanking ───────────────────────────────────────────────

    def _hide_all_content_views(self) -> None:
        """Blank-slate all views. Call before activating any single view.

        That includes the status line. Sixty of the sixty-five
        ``status_bar.showMessage`` calls pass no timeout, so a message stands
        until something else overwrites it — and a view that has nothing to say
        never does. Leaving EPG for Discover left "EPG: 2,109 on now" sitting
        under a page it had nothing to do with. Owner: "it doesn't seem to do
        anything on Recommended or Discover and keeps the previous status so
        EPG -> Discover still shows EPG: 2,109 on now."

        Cleared HERE, at the one seam every view switch already passes through,
        rather than by giving each view an "and clear the status bar" line —
        which is the enumeration that leaves the next view out.
        """
        self.status_bar.clearMessage()
        # ONE list, both operations. This method used to carry two: a
        # hand-written sequence of ``if visible: view.on_deactivate()`` and a
        # separate hand-written sequence of ``view.setVisible(False)``. Adding
        # the Sports view to the first and not the second left it VISIBLE
        # behind the next view — nothing raised, and the only symptom was two
        # views drawn at once.
        #
        # ``getattr(view, "on_deactivate", None)`` is polymorphism, not a
        # defensive hasattr: the list genuinely mixes ContentViews with a
        # QTreeView and a QListView, and only the former have a lifecycle.
        #
        # The ``isVisible()`` gate is deliberate and tested
        # (test_hide_skips_on_deactivate_when_not_visible). It looks like an
        # asymmetry — activation is unconditional — and it was checked against
        # a SHOWN window before being left alone: the timer starts on activate
        # and stops on switch-away exactly as it should. ``isVisible()`` is
        # False only for a widget whose ancestor chain is hidden, which in a
        # running app means "this view is not the one on screen". A test
        # fixture that never calls ``show()`` sees it as False for everything,
        # and that is the fixture's limit, not a bug to code around.
        for attr in CONTENT_VIEW_ATTRS:
            # ``self.__dict__.get``, NOT ``getattr(self, attr, None)``. On a
            # skeleton host (``MainWindow.__new__``, which several lifecycle
            # tests use) attribute access goes through Qt and raises
            # RuntimeError — which a None default does not absorb, because it
            # is not AttributeError. The line each lazy view used to carry,
            # ``if "recipe_view" in self.__dict__``, was dodging exactly this.
            view = self.__dict__.get(attr)
            if view is None:
                continue
            deactivate = getattr(view, "on_deactivate", None)
            if deactivate is not None and view.isVisible():
                deactivate()
            view.setVisible(False)

        # Explore views (History / Favorites / Queue / Recommended) are built
        # lazily into a DICT rather than as attributes, so they are their own
        # loop — and their deactivation restores the flanking panels the
        # activation auto-collapsed, which nothing else in the list needs.
        if "explore_views" in self.__dict__:
            for view in self.explore_views.values():
                if view.isVisible():
                    view.on_deactivate()
                    splitter = getattr(self, "main_splitter", None)
                    if splitter is not None:
                        for i in getattr(self, "_explore_restored_panels", (0, 2)):
                            splitter.expand_panel(i)
                        self._explore_restored_panels = []
                view.setVisible(False)

        # EPG stats-line controls (source status + Refresh) belong to the EPG
        # view only — hide them whenever we blank the content area (guarded:
        # the stats line is built after this mixin's earliest possible call).
        if "epg_status_label" in self.__dict__:
            self.epg_status_label.setVisible(False)
            self.epg_refresh_btn.setVisible(False)
        self.search_controls.setVisible(False)
        self._sync_header_search_visibility(False)
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
        if "filter_chip_bar" in self.__dict__:
            self.filter_chip_bar.setVisible(False)
        self._hidden_mode = False
        if hasattr(self, "_tab_all_btn"):
            self._tab_all_btn.setChecked(True)
            self._tab_hidden_btn.setChecked(False)
        self.show_series_nav(None)

    def show_series_nav(self, series_name: "str | None") -> None:
        """Show or hide the series navigation bar, contents and all.

        One method rather than three call sites each setting the button, the
        label and now the bar: the bar was added and every existing site
        toggled only what was INSIDE it, which is precisely how it stayed
        visible-but-empty everywhere for as long as it did.

        Args:
            series_name: The series to name in the breadcrumb, or ``None`` to
                leave series view — which hides the whole bar, so no other view
                pays a row for it.
        """
        showing = series_name is not None
        self._series_nav_bar.setVisible(showing)
        self.back_button.setVisible(showing)
        self.breadcrumb_label.setText(
            f"{self.series_icon} {series_name}" if showing else ""
        )

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
        self.show_series_nav(self.current_series.name)
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
        self._sync_header_search_visibility(True)
        if hasattr(self, "filter_panel"):
            # Not setVisible(True): in chip mode the column is meant to be shut,
            # and forcing it here would re-open it on every return to the list.
            # _apply_filter_ui_mode is the only thing that decides.
            self._apply_filter_ui_mode()
        self.search_input.setEnabled(True)
        self.search_input.setPlaceholderText("Filter channels by name, category...")

        if hasattr(self, 'channel_model') and self.channel_model.loaded_count() > 0:
            # loaded_count(), NOT rowCount(): the latter is the DISPLAY count and
            # includes section headers, which every search now creates. It reflects
            # what's loaded so far (paging loads more on scroll), so report it
            # plainly — the legacy `all_channels` cache only holds page 1 and would
            # make "of Y / filtered out" go negative once more pages stream in.
            shown = self.channel_model.loaded_count()
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

        A RETIRED name (``_RETIRED_NAV_VIEW_TARGETS`` — a view that used to
        exist and is gone) resolves to whatever current target replaces it,
        rather than no-oping: an old What's New entry's ``test_steps`` is an
        append-only historical record and still says ``view:sports``, and a
        "Go ▸" button that silently does nothing reads as a bug, not history.
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
            retired_target = _RETIRED_NAV_VIEW_TARGETS.get(name)
            if retired_target is not None:
                logger.info(
                    "navigate_to: 'view:{}' was retired — landing on 'view:{}' instead",
                    name, retired_target,
                )
                return self._navigate_to_view(retired_target)
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

    # ── Sidebar section header menu ─────────────────────────────────────────

    def _wire_sidebar_section_menu(self, section, section_id: str) -> None:
        """Connect one section's header-menu signals (called from the sidebar
        build loop in ``create_sidebar``, the same site that wires
        ``exploreClicked`` — one place, not a per-section enumeration)."""
        section.hideRequested.connect(lambda sid=section_id: self._hide_sidebar_section(sid))
        section.sidebarSettingsRequested.connect(lambda: self.navigate_to("settings:Sidebar"))

    def _hide_sidebar_section(self, section_id: str) -> None:
        """Hide a section via the config chokepoint, with an Undo toast.

        A right-click shortcut over what Settings -> Sidebar's checkboxes
        already write; reapplied via the one chokepoint
        (``_apply_sidebar_visibility``), never a direct ``setVisible``.
        """
        section = self.sidebar_sections.get(section_id)
        order = list(self.config.sidebar_sections or self.sidebar_sections.keys())
        visible = list(self.config.sidebar_visible_sections or order)
        if section_id not in visible:
            return
        visible.remove(section_id)
        self.config.sidebar_visible_sections = visible
        _cfgsave.save_soon(self)
        self._apply_sidebar_visibility()
        title = section.title if section is not None else section_id

        def _undo() -> None:
            # Position by canonical order, not a blind append: [a,b,c] minus
            # b, undone, must come back as [a,b,c] not [a,c,b].
            current = list(self.config.sidebar_visible_sections or [])
            if section_id in current:
                return
            target = order.index(section_id) if section_id in order else len(order)
            insert_at = next(
                (i for i, sid in enumerate(current)
                 if sid in order and order.index(sid) > target),
                len(current),
            )
            current.insert(insert_at, section_id)
            self.config.sidebar_visible_sections = current
            _cfgsave.save_soon(self)
            self._apply_sidebar_visibility()

        self.notification_manager.show(
            title="Section hidden",
            message=f"{title} is hidden — restore it any time in Settings → Sidebar.",
            type="info",
            auto_dismiss_ms=8000,
            actions=[("Undo", _undo)],
        )

    # ── View/chip wiring ────────────────────────────────────────────────────

    def _on_view_channel_selected(self, channel):
        """Handle channel selected from a content view."""
        if channel:
            self.details_pane.show_channel(channel)

    def _deactivate_view_chips(self, *keep) -> None:
        """Deactivate all view chips except those in keep.

        Derived from ``app_header.NAV_CHIP_SPECS`` — the same tuple that BUILDS
        the switcher — rather than a second hand-written list. A chip missing
        from a hand-written copy stays lit while another view is showing, and
        nothing fails; the sixth chip is what made that worth fixing rather than
        extending.

        ``getattr`` with a default because the chips are created together but
        this can be reached before ``_create_nav_group`` on an early path.
        """
        from metatv.gui.app_header import NAV_CHIP_SPECS

        chips = [
            chip for attr, *_ in NAV_CHIP_SPECS
            if (chip := getattr(self, attr, None)) is not None
        ]
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
            if self._returning_list_is_stale():
                self.load_channels()
        else:
            self.search_chip.blockSignals(True)
            self.search_chip.set_enabled(True)
            self.search_chip.blockSignals(False)

    def _returning_list_is_stale(self) -> bool:
        """Whether coming back to the list needs a fresh query.

        It used to always. Returning from Discover re-ran the whole
        785,551-row filter for a search the user had not touched — owner,
        2026-09-02: "search is reloading the search results every time the
        search view regains focus even on the same search".

        Nothing that invalidates the rows can happen unnoticed, which is what
        makes skipping safe rather than optimistic:

        * every corpus mutation goes through
          ``_refresh_provider_dependent_views``, which reloads the list itself
          — whether or not the list is the visible view;
        * every path that changes the search state (the debounce, the context
          filter chips, the hidden tab, a provider selection) already calls
          ``load_channels`` at the time it changes it;
        * per-channel state (favourite, rating, hidden) is pushed into the rows
          in place by ``channel_state_bus``, never by a requery.

        So the two things left to check are the two this cannot know from those
        chokepoints: that there are rows at all, and that they answer the query
        currently in the box.
        """
        model = self.__dict__.get("channel_model")
        if model is None or model.loaded_count() <= 0:
            return True
        box = self.__dict__.get("search_input")
        current = box.text().strip() if box is not None else ""
        return current != model.loaded_search_query()

    def on_hidden_view_toggle(self) -> None:
        self._set_list_scope("hidden")

    def _set_list_scope(self, scope: str) -> None:
        """Switch between All/Downloaded/Hidden (DL-5). Downloaded is a
        record/engaged view (DR-0007): titles with >=1 completed download
        regardless of source state or Global Exclusions (not Recordings)."""
        self._tab_all_btn.setChecked(scope == "all")
        self._tab_hidden_btn.setChecked(scope == "hidden")
        if "_tab_downloaded_btn" in self.__dict__:  # hasattr raises on a bare __new__'d host
            self._tab_downloaded_btn.setChecked(scope == "downloaded")
        self._list_scope = scope
        hidden = scope == "hidden"
        self._hidden_mode = hidden  # kept in sync — many existing readers use it
        self._save_search_state()
        if hidden:
            self.view_mode = "hidden"
            self._hidden_banner.setVisible(True)
            self.stats_label.setText("Hidden channels")
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
        _cfgsave.save_soon(self)
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
            self.load_channels(keep_rows=True)
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

    def _activate_context_filter(self, label: str, **state) -> None:
        """THE way a context filter is applied. Every entry point routes here.

        Each caller used to repeat the same seven-line ritual — reset, set its
        own state var, set the label, show the chip, save search state, switch
        to the list, reload — which is how the row-chip work ended up adding an
        eighth hand-rolled copy that set the right variable from the wrong
        field. One chokepoint, per CLAUDE.md's single-source-of-truth rule; a
        new filter type sets its var here and inherits the rest.

        Args:
            label: Chip text, e.g. ``"Genre: Drama"``.
            **state: Exactly one ``_details_*_filter`` attribute to set.
                Mutual exclusion is enforced by the reset below, so passing more
                than one is a caller bug rather than a supported combination.
        """
        self._reset_context_filters()
        for name, value in state.items():
            setattr(self, name, value)
        self._context_filter_label.setText(label)
        self._context_filter_chip.show()
        self._save_search_state()
        self.switch_to_list_view()
        self.load_channels()

    def _on_genre_filter_requested(self, genre: str) -> None:
        """Strict SQL genre filter from a genre chip (details pane or row)."""
        self._activate_context_filter(f"Genre: {genre}", _details_genre_filter=genre)

    def _on_person_filter_requested(self, name: str) -> None:
        """Strict SQL cast/crew filter from details-pane chip click."""
        self._activate_context_filter(f"Cast/Crew: {name}", _details_person_filter=name)

    def _on_lightbox_lens_search(self, lens: str, value: str) -> None:
        """The lightbox lens strip's "See all in Search" — commit to the list.

        A cast/genre click INSIDE the lightbox re-seeds the overlay rather than
        filtering the list behind it; this is the explicit opt-in to the list,
        and it routes into the same strict handlers a details-pane click uses so
        the user lands on the set the lens was paging — not a second answer.
        """
        if lens == "person":
            self._on_person_filter_requested(value)
        elif lens == "genre":
            self._on_genre_filter_requested(value)

    def _on_category_filter_requested(self, category: str) -> None:
        """Strict SQL filter on the curated provider ``ChannelDB.category``.

        The one collection/category entry point, shared by the details-pane tag
        chip and the row chip. Collection is special among facets: it filters on
        the human-curated ``category`` column, NOT a re-derived query on the
        lossy ``detected_collection`` residual, so the user sees the actual
        curated set. The two callers differ only in where they GET the category
        — the details pane looks it up for the channel it is showing, the row
        chip reads it off the clicked row — never in how they apply it.
        """
        if not category:
            # Nothing curated to filter on — leave the list untouched rather
            # than applying a filter that matches nothing.
            return
        self._activate_context_filter(
            f"Collection: {category}", _details_category_filter=category
        )

    def _on_tag_filter_requested(self, facet_type: str, value: str) -> None:
        """Left-click a tag chip → strict context filter for that exact facet.

        Collection defers to :meth:`_on_category_filter_requested` (it filters a
        different column); every other facet filters on the exact (type, value)
        tag, no hierarchy rollup.
        """
        if facet_type == "collection":
            self._on_category_filter_requested(self._resolve_current_channel_category())
            return
        label = facet_type.replace("_", " ").title()
        self._activate_context_filter(
            f"{label}: {value}", _details_tag_filter=(facet_type, value)
        )

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
            # The chip DISPLAYS detected_collection but must FILTER on the
            # curated ChannelDB.category — different columns. The delegate
            # carries the raw category as the chip's value for exactly this
            # reason; routing through the shared entry point keeps this
            # identical to a details-pane collection click.
            self._on_category_filter_requested(value)
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
        """Right-click a tag chip → the Recipe view seeded with this one tag.
        Reuses the recipe/discover-shelf engine rather than a parallel discover
        surface: the "Now Plating" grid IS the one-ingredient-recipe shelf."""
        self._activate_recipe_view()
        self.recipe_view.seed_facet(facet_type, value)

    def _activate_recipe_view(self) -> None:
        """Open the Recipe view the way its nav chip does (chip lit with signals
        blocked, siblings dimmed, switch) — the one programmatic entry point."""
        if "recipe_chip" in self.__dict__:
            self.recipe_chip.blockSignals(True)
            self.recipe_chip.set_enabled(True)
            self.recipe_chip.blockSignals(False)
            self._deactivate_view_chips(self.recipe_chip)
        self.switch_to_recipe_view()

    def _on_discover_recipe_edit_requested(self, name: str) -> None:
        """A Discover recipe shelf's ✎ click (#587) — the builder, loaded."""
        self._activate_recipe_view()
        self.recipe_view.load_saved_recipe_by_name(name)

    def _on_trail_recipe_requested(self, channel_id: str) -> None:
        """"Make recipe" from the trail-map — open the Recipe builder, SEEDED.

        It used to switch to Recipe and discard the ``channel_id``, so this
        landed you in an empty builder — which reads as a dead button (owner
        report, 2026-08-27).

        Seeds the GENRE only: seeding every facet a title has narrows the
        recipe until it returns just that title. Routed through
        ``_on_tag_discover_requested``, the same seam the details-pane tag
        right-click uses. Rationale and cases: tests/test_trail_map_make_recipe.py.
        """
        # ``__dict__.get``, never ``hasattr``: PyQt raises RuntimeError — not
        # AttributeError — for attribute access on a ``__new__``'d QObject, and
        # hasattr does not absorb it, so the guard itself explodes on exactly
        # the skeleton hosts the tests drive (CLAUDE.md).
        for name in ("_lightbox", "_trail_map"):
            overlay = self.__dict__.get(name)
            if overlay is not None and overlay.isVisible():
                overlay.hide()

        from metatv.core.repositories import RepositoryFactory   # local, as elsewhere here

        with self.db.session_scope(commit=False) as session:
            genre = RepositoryFactory(session).channels.get_detected_genre(channel_id)
        if genre:
            self._on_tag_discover_requested("genre", genre)
            return
        # No stored genre: still open the builder rather than swallowing the
        # click, but empty — there is nothing honest to seed it with.
        self.switch_to_recipe_view()

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

