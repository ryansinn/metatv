"""Channel-list load, filter pipeline, and context-menu glue mixin for :class:`MainWindow`.

This module holds :class:`_ChannelListMixin` — the channel-list loading, filter
pipeline, and unified context-menu infrastructure methods extracted verbatim from
``main_window.py`` as part of the B10 decomposition.  It covers:

* Filter panel toggle (``toggle_filters``)
* Search debounce handler (``_on_search_text_changed``)
* Non-blocking channel load + async query worker (``load_channels``, ``_query_channels``)
* Load-error and load-result handlers (``_on_channels_load_error``, ``_on_channels_loaded``)
* Channel-list render pass (``filter_channels``)
* Media-type helpers and category picker (``get_enabled_media_types``, ``_open_category_picker``)
* Tier-1 bypass ("show filtered results") and filter-change handler
  (``_show_filtered_results``, ``on_filter_changed``)
* Filter-statistics background load (``initialize_filter_stats``, ``_on_filter_stats_loaded``)
* Unified context-menu seam: ``_show_channel_menu``, ``_bg_fetch_ctx_data``,
  ``_on_ctx_data_ready``, ``_build_handlers``, ``_show_context_menu_for``

The methods rely on attributes and sibling methods defined on ``MainWindow``
(e.g. ``self.db``, ``self.executor``, ``self._run_query``, ``self.config``,
``self.player_manager``); they resolve via ``self``/MRO at runtime, so the
split is behaviour-preserving.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.gui import theme as _theme


class _ChannelListMixin:
    """Channel-list load, filter pipeline, and context-menu glue methods mixed into :class:`MainWindow`."""

    def toggle_filters(self):
        """Toggle filter panel visibility via inner splitter collapse."""
        if not hasattr(self, '_inner_splitter'):
            return
        sizes = self._inner_splitter.sizes()
        if sizes[0] > 0:
            self._inner_splitter.setSizes([0, sum(sizes)])
            self.config.filter_section_visible = False
        else:
            w = getattr(self.config, 'filter_panel_width', 220)
            self._inner_splitter.setSizes([w, max(200, sum(sizes) - w)])
            self.config.filter_section_visible = True
        self.config.save()

    def _on_search_text_changed(self, text: str) -> None:
        """Handle search input changes — debounce to avoid per-keystroke DB queries."""
        if getattr(self, "_suppress_search_handler", False):
            return  # programmatic restore — caller issues the load; skip debounce/save
        self._bypass_tier1_filters = False  # new search term — cancel any bypass
        self._save_search_state()
        self._search_debounce.start()  # restart the 200ms timer on each keystroke

    def _set_search_text_silently(self, text: str) -> None:
        """Set the search box text without retriggering the load — keeping the clear ×.

        ``blockSignals(True)`` would suppress the QLineEdit clear button (its
        visibility is driven by ``textChanged``), so on startup-with-restored-text
        the × never appeared until the user edited the box.  Guard the handler
        instead of blocking the signal, so the button stays in sync.
        """
        self._suppress_search_handler = True
        try:
            self.search_input.setText(text)
        finally:
            self._suppress_search_handler = False

    # ── Search state persistence ────────────────────────────────────────────

    def _save_search_state(self) -> None:
        """Persist the current search/filter state to config (no-op if remember_search is off)."""
        if not getattr(self.config, 'remember_search', True):
            return
        query = self.search_input.text() if hasattr(self, 'search_input') else ""
        state = {
            "query": query,
            "provider_id": getattr(self, 'selected_provider_id', None),
            "hidden_mode": bool(getattr(self, '_hidden_mode', False)),
            "genre_filter": getattr(self, '_details_genre_filter', None),
            "person_filter": getattr(self, '_details_person_filter', None),
        }
        self.config.last_search_state = state
        self.config.save()

    def restore_search_state(self) -> bool:
        """Restore a previously saved search state and trigger a channel load.

        Returns True if a non-trivial state was restored (caller can skip their own
        ``load_channels()`` call since this method issues one).  Returns False if the
        feature is disabled or nothing was saved — the caller must call ``load_channels()``
        themselves.

        Must be called on the main thread after the UI is fully set up.
        """
        if not getattr(self.config, 'remember_search', True):
            return False
        state = getattr(self.config, 'last_search_state', {})
        if not state:
            return False

        query = state.get("query", "")
        provider_id = state.get("provider_id")
        hidden_mode = bool(state.get("hidden_mode", False))
        genre_filter = state.get("genre_filter")
        person_filter = state.get("person_filter")

        any_non_trivial = query or provider_id or hidden_mode or genre_filter or person_filter
        if not any_non_trivial:
            return False  # saved state is the empty default — nothing to restore

        logger.info(
            "Restoring search state: query={!r} provider={} hidden={} genre={} person={}",
            query, provider_id, hidden_mode, genre_filter, person_filter,
        )

        # Restore context chips (genre / person)
        if genre_filter:
            self._details_genre_filter = genre_filter
            self._details_person_filter = None
            if hasattr(self, '_context_filter_label'):
                self._context_filter_label.setText(f"Genre: {genre_filter}")
            if hasattr(self, '_context_filter_chip'):
                self._context_filter_chip.show()
        elif person_filter:
            self._details_person_filter = person_filter
            self._details_genre_filter = None
            if hasattr(self, '_context_filter_label'):
                self._context_filter_label.setText(f"Cast/Crew: {person_filter}")
            if hasattr(self, '_context_filter_chip'):
                self._context_filter_chip.show()

        # Restore hidden/all toggle — update UI buttons without retriggering load
        if hidden_mode:
            self._hidden_mode = True
            if hasattr(self, '_tab_all_btn'):
                self._tab_all_btn.blockSignals(True)
                self._tab_hidden_btn.blockSignals(True)
                self._tab_all_btn.setChecked(False)
                self._tab_hidden_btn.setChecked(True)
                self._tab_all_btn.blockSignals(False)
                self._tab_hidden_btn.blockSignals(False)
            if hasattr(self, '_hidden_banner'):
                self._hidden_banner.setVisible(True)

        # Restore source filter — update sidebar selection without triggering load
        if provider_id:
            self.selected_provider_id = provider_id
            src = self.sidebar_sections.get("sources") if hasattr(self, 'sidebar_sections') else None
            if src is not None and hasattr(src, 'select_provider'):
                src.select_provider(provider_id)

        # Restore query text without retriggering the debounce (load is issued below).
        if hasattr(self, 'search_input') and query:
            self._set_search_text_silently(query)

        # Re-run the async channel load with restored state
        self.load_channels(provider_id)
        return True

    def load_channels(self, provider_id=None):
        """Load channels from database into the list (non-blocking)."""
        from metatv.core.filter_utils import get_active_content_type_filter

        # Stop any pending debounce timer so we don't queue a second load
        self._search_debounce.stop()

        # Show loading state immediately so the user knows something is happening.
        # Reset the model (clears the list) and show a banner; the result/error
        # slots clear the banner before rendering their own state.
        self.all_channels = []
        self.channel_model.set_channels(
            [],
            provider_icon_map={},
            show_provider_icon=False,
            has_more=False,
            query_params={},
        )
        from metatv.gui import icons as _icons
        self._show_channel_banner(f"{_icons.loading_icon} Loading channels…")
        self.stats_label.setText("Loading channels…")
        self.status_bar.showMessage("Loading channels…")

        # --- All UI-state reads must happen here on the main thread ---
        filter_state = self.current_filter_state or (
            self.filter_panel.get_filter_state()
            if hasattr(self, 'filter_panel')
            else {}
        )

        # Tag-model (Slice B): tag_includes from get_filter_state() replaces the old
        # prefix-list resolution.  The legacy '_language_prefixes' etc. fields are
        # kept in the state dict as None so the params block below still compiles;
        # they are not passed to get_all() when tag_includes is present.
        tag_includes = filter_state.get('tag_includes')  # dict[str, set[str]] | None
        language_prefixes: list = []
        region_prefixes:   list = []
        platform_prefixes: list = []
        quality_prefixes:  list = []

        # Resolve provider filter on main thread (tiny queries)
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            active_providers = repos.providers.get_all(active_only=True)
            all_providers   = repos.providers.get_all()
        finally:
            session.close()

        active_provider_ids = [p.id for p in active_providers]
        inactive_provider_ids = [p.id for p in all_providers if p.id not in active_provider_ids]
        force_adult_ids     = [p.id for p in all_providers if getattr(p, 'force_adult', False)]
        excluded_ids        = set(filter_state.get('excluded_provider_ids', []))

        if provider_id:
            target_provider_id = provider_id
        else:
            visible_ids = [pid for pid in active_provider_ids if pid not in excluded_ids]
            if len(visible_ids) == len(active_provider_ids) and len(visible_ids) == 1:
                target_provider_id = visible_ids[0]
            elif len(visible_ids) < len(active_provider_ids):
                target_provider_id = visible_ids if visible_ids else None
            else:
                target_provider_id = None

        # Build provider icon map (used later for display)
        show_provider_icon = (target_provider_id is None)
        provider_icon_map: dict = {}
        if show_provider_icon:
            for p in all_providers:
                provider_icon_map[p.id] = (getattr(p, "icon", "") or self.config.provider_icon)

        from metatv.core.filter_utils import get_excluded_prefixes, get_active_category_filter
        _filter_paused = self.config.global_filter_paused
        if _filter_paused:
            _global_excluded_prefixes: set = set()
        else:
            _cat_excluded, _ = get_active_category_filter(self.config)
            _global_excluded_prefixes = set(_cat_excluded or []) | get_excluded_prefixes(self.config)
        _search_text = (self.search_input.text().strip()
                        if hasattr(self, 'search_input') else "")
        # _bypass_tier1_filters: set when user clicks "Show filtered results" in the
        # zero-results state. Allows them to see what's hidden without changing settings.
        _bypassing = self._bypass_tier1_filters
        _genre_filters = filter_state.get('_genre_filters')
        params = dict(
            provider_id=target_provider_id,
            media_types=filter_state.get('media_types', ['live', 'movie', 'series']),
            # Legacy prefix lists — now always empty (tag_includes is the active path).
            # Kept in params so _query_channels_page (pagination) still has these keys.
            language_prefixes=None,
            region_prefixes=None,
            quality_prefixes=None,
            platform_prefixes=None,
            genre_filters=None if _bypassing else _genre_filters,
            invert_prefix_filters=False,
            include_untagged=filter_state.get('include_untagged', True),
            include_untagged_quality=filter_state.get('include_untagged_quality', True),
            adult_mode=filter_state.get('adult_mode', 'hide'),
            force_adult_ids=force_adult_ids,
            # Tag facet filter — the active filter path (Slice B).
            # None when bypassing or no facet is constrained.
            tag_includes=None if _bypassing else tag_includes,
            # Global filter — bypassed when paused so the user can see everything
            source_categories=None if _filter_paused else get_active_content_type_filter(self.config),
            excluded_prefixes=_global_excluded_prefixes,
            excluded_user_categories=set() if _filter_paused else set(self.config.global_filter_excluded_user_categories),
            search_query=_search_text or None,
            strict_genre_filter=self._details_genre_filter,
            person_filter=self._details_person_filter,
            page_size=self._search_page_size,
            show_provider_icon=show_provider_icon,
            provider_icon_map=provider_icon_map,
            given_provider_id=provider_id,
            hidden_only=self._hidden_mode,
            bypassing_tier1=_bypassing,
            # Watched filter — OFF by default; when ON excludes watch_completed channels
            hide_watched=filter_state.get('hide_watched', False),
        )

        # Run the heavy query off the UI thread via the async seam; stale results
        # are dropped by the seam's token_ref. _on_channels_loaded receives the
        # (dtos, params) tuple the query_fn returns and renders on the main thread.
        self._run_query(
            lambda repos: self._query_channels(repos, params),
            self._on_channels_loaded,
            token_ref=self._load_channels_token,
            on_error=self._on_channels_load_error,
        )

    @staticmethod
    def _query_channels(repos, params: dict) -> tuple[list, dict]:
        """Worker (off-thread): run the heavy DB query and return (dtos, params).

        Receives the seam's RepositoryFactory; reads only. Maps the surviving
        ChannelDB rows to ChannelListDTOs so no ORM object crosses the boundary.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories.dtos import ChannelListDTO

        force_adult_ids = params['force_adult_ids']
        hidden_only = params.get('hidden_only', False)
        _page_size = params.get('page_size', 5_000)
        # Canonical provider scoping: hide inactive + expired sources (see
        # ProviderRepository.get_hidden_provider_ids — single source of truth).
        providers_to_exclude = repos.providers.get_hidden_provider_ids()
        if hidden_only:
            channels = repos.channels.get_hidden_channels(
                excluded_user_categories=params.get('excluded_user_categories'),
                search_query=params.get('search_query'),
                provider_id=params['provider_id'],
                excluded_provider_ids=providers_to_exclude or None,
            )
        else:
            channels = repos.channels.get_all(
                provider_id=params['provider_id'],
                media_types=params['media_types'],
                language_prefixes=params.get('language_prefixes'),
                region_prefixes=params.get('region_prefixes'),
                quality_prefixes=params.get('quality_prefixes'),
                platform_prefixes=params.get('platform_prefixes'),
                genre_filters=params.get('genre_filters'),
                invert_prefix_filters=params['invert_prefix_filters'],
                include_untagged=params['include_untagged'],
                include_untagged_quality=params.get('include_untagged_quality', True),
                adult_mode=params['adult_mode'],
                force_adult_provider_ids=force_adult_ids or None,
                source_categories=params['source_categories'],
                include_uncategorized_content_types=True,
                hidden_only=False,
                include_hidden=False,
                search_query=params.get('search_query'),
                strict_genre_filter=params.get('strict_genre_filter'),
                person_filter=params.get('person_filter'),
                excluded_provider_ids=providers_to_exclude or None,
                tag_includes=params.get('tag_includes'),
                exclude_watched=params.get('hide_watched', False),
                limit=_page_size,
            )
        # Raw count of SQL rows fetched BEFORE the Python-side exclusion filtering
        # below. Paging (has_more + the next OFFSET) must be based on this, not on
        # the surviving count — otherwise an active exclusion makes page 1 look
        # short (has_more=False → list dead-ends early) and would overlap rows.
        params['raw_fetched'] = len(channels)
        total = repos.channels.count(provider_id=params['provider_id'])
        has_adult = bool(force_adult_ids) or repos.session.query(ChannelDB).filter(
            ChannelDB.is_adult == True
        ).limit(1).count() > 0
        if not hidden_only:
            excluded_prefixes = params.get('excluded_prefixes', set())
            if excluded_prefixes:
                channels = [
                    c for c in channels
                    if c.detected_prefix not in excluded_prefixes
                    and c.detected_region not in excluded_prefixes
                ]
            excluded_user_cats = params.get('excluded_user_categories', set())
            if excluded_user_cats:
                channels = [
                    c for c in channels
                    if c.user_category not in excluded_user_cats
                ]

        # When zero results + Tier 1 filters active, count what exists without
        # those filters so we can tell the user "X results are filtered out".
        filtered_out_count = 0
        # tag_includes is the active filter path (Slice B); legacy prefix lists are now always None.
        tier1_active = bool(params.get('tag_includes'))
        if not hidden_only and len(channels) == 0 and tier1_active:
            unfiltered = repos.channels.get_all(
                provider_id=params['provider_id'],
                media_types=params.get('media_types'),
                adult_mode=params.get('adult_mode', 'all'),
                force_adult_provider_ids=force_adult_ids or None,
                source_categories=params.get('source_categories'),
                search_query=params.get('search_query'),
                limit=_page_size,
            )
            # Apply global exclusions to the unfiltered set too
            if excluded_prefixes:
                unfiltered = [
                    c for c in unfiltered
                    if c.detected_prefix not in excluded_prefixes
                    and c.detected_region not in excluded_prefixes
                ]
            filtered_out_count = len(unfiltered)

        # When "Hide watched" is ON, count how many results are hidden because they're
        # watched — used to show "N watched hidden" in the stats label.
        watched_hidden_count = 0
        if not hidden_only and params.get('hide_watched', False):
            watched_hidden_count = repos.channels.count_watched_matching(
                provider_id=params['provider_id'],
                media_types=params.get('media_types'),
                excluded_provider_ids=providers_to_exclude or None,
                search_query=params.get('search_query'),
                adult_mode=params.get('adult_mode', 'all'),
                force_adult_provider_ids=force_adult_ids or None,
                tag_includes=params.get('tag_includes'),
            )

        # get_all() now returns results sorted and limited — no extra sort needed
        params['total_channels']    = total
        params['has_adult']         = has_adult
        params['filtered_out_count'] = filtered_out_count
        params['watched_hidden_count'] = watched_hidden_count
        # Batch-fetch all user ratings in one query (avoids N+1) then map surviving
        # ORM rows → DTOs so no ChannelDB crosses the boundary.
        ratings_map = repos.ratings.get_all_map()
        dtos = [ChannelListDTO.from_orm(c, user_rating=ratings_map.get(c.id, 0)) for c in channels]
        return dtos, params

    def _on_channels_load_error(self, exc: Exception) -> None:
        """Main thread: clear the loading state when the channel query fails."""
        logger.error(f"Channel query failed: {exc}")
        self._clear_provider_busy()
        # Clear the loading banner so the spinner doesn't hang.
        self._hide_channel_banners()
        self.stats_label.setText("Couldn't load channels")
        self.status_bar.showMessage("Couldn't load channels")

    def _on_channels_loaded(self, result) -> None:
        """Main thread: populate the virtualized channel model from query results.

        ``result`` is the ``(dtos, params)`` tuple returned by ``_query_channels``.
        Stale results are already dropped by the seam's ``token_ref``.
        """
        channels, params = result

        # A current channel load finished — the visible result of a provider toggle's
        # canonical refresh. Clear any provider busy/spinner state now.
        self._clear_provider_busy()
        self._hide_channel_banners()

        total_channels    = params.get('total_channels', 0)
        show_provider_icon = params.get('show_provider_icon', False)
        provider_icon_map  = params.get('provider_icon_map', {})
        given_provider_id  = params.get('given_provider_id')

        logger.info(f"=== Loading {len(channels):,} channels (filtered from {total_channels:,} total) ===")

        if not channels:
            logger.warning("No channels match current filters!")
            if params.get('hidden_only'):
                self.status_bar.showMessage("No hidden channels found")
                self.stats_label.setText("No hidden channels")
            else:
                filtered_out = params.get('filtered_out_count', 0)
                if filtered_out > 0:
                    # Results exist but are hidden by Tier 1 filters — show the
                    # actionable button in the banner area.
                    self._show_channel_filter_button(filtered_out)
                    self.status_bar.showMessage(
                        f"No results — {filtered_out:,} match{'es' if filtered_out == 1 else ''} hidden by current filters"
                    )
                    self.stats_label.setText(f"0 shown · {filtered_out:,} filtered")
                else:
                    self.status_bar.showMessage("No channels match — try a different search or check filter settings")
                    self.stats_label.setText(f"Showing 0 of {total_channels:,}")
            return

        # Track bypass state so filter_channels() can show the banner
        self._currently_bypassing = params.get('bypassing_tier1', False)

        # Build legacy all_channels cache (still used by toggle_favorite / the
        # favorites cache update in _apply_favorite_toggle path).
        self.all_channels = []
        for channel in channels:
            media_icon = self.get_media_type_icon(channel.media_type)
            fav_icon   = self.favorite_icon if channel.is_favorite else self.unfavorite_icon
            src_badge  = ""
            if show_provider_icon and channel.provider_id in provider_icon_map:
                src_badge = provider_icon_map[channel.provider_id] + " "
            prefix_str   = f"[{channel.detected_prefix}] " if channel.detected_prefix else ""
            lang_str     = f"[{channel.detected_region}] " if channel.detected_region else ""
            prefix_group = prefix_str + lang_str
            dot_sep      = "· " if prefix_group.strip() else ""
            quality_str  = f" · {channel.detected_quality}" if channel.detected_quality else ""
            year_str     = f" · {channel.detected_year}" if channel.detected_year else ""
            bare         = channel.detected_title or channel.name
            display_text = f"{src_badge}{media_icon}{fav_icon} {prefix_group}{dot_sep}{bare}{quality_str}{year_str}"
            if channel.category:
                display_text += f" [{channel.category}]"
            self.all_channels.append((display_text, channel))

        shown = len(channels)
        # Paging is keyed off the RAW SQL rows fetched (before Python exclusions),
        # not the surviving `shown` — otherwise an active exclusion shortens page 1
        # and wrongly reports exhaustion. hidden_only loads everything in one shot
        # (no offset/limit), so it never pages.
        raw_fetched = params.get('raw_fetched', shown)
        page_size = params.get('page_size', self._search_page_size)
        has_more = (not params.get('hidden_only')) and (raw_fetched >= page_size)

        # Populate the virtualized model — this replaces the old addItem loop.
        # Pass through display helpers so the model can compose identical text.
        self.channel_model.set_channels(
            channels,
            provider_icon_map=provider_icon_map,
            show_provider_icon=show_provider_icon,
            has_more=has_more,
            next_offset=raw_fetched,
            query_params=params,
            favorite_icon=self.favorite_icon,
            unfavorite_icon=self.unfavorite_icon,
            get_media_type_icon=self.get_media_type_icon,
            partial_threshold_pct=int(
                getattr(self.config, "watch_partial_threshold", 0.10) * 100
            ),
        )

        # Stash the stats context so _refresh_channel_stats_label() can recompute
        # the "Showing N of M" label live as fetchMore() streams in more pages.
        self._stats_total_channels = total_channels
        self._stats_hidden_only = bool(params.get('hidden_only'))
        # tag_includes is the active filter indicator (Slice B).
        self._stats_panel_filtering = bool(params.get('tag_includes'))
        # Watched-filter context: count hidden because watched (0 when filter is OFF).
        self._stats_watched_hidden = int(params.get('watched_hidden_count', 0))
        self._stats_hide_watched   = bool(params.get('hide_watched', False))
        self._refresh_channel_stats_label()

        if params.get('hidden_only'):
            self.status_bar.showMessage(f"{shown:,} hidden channel{'s' if shown != 1 else ''} — right-click to unhide")
        elif given_provider_id:
            self.status_bar.showMessage(f"{shown:,} channels from selected provider")
        else:
            self.status_bar.showMessage(f"{shown:,} channels from active providers")

        self.filter_channels()

    def _refresh_channel_stats_label(self) -> None:
        """Set the stats label from the current loaded row count.

        Called on the initial load and again after every fetchMore() page so the
        "Showing N of M" count grows as the user scrolls (N = rows loaded so far;
        M = the provider's total). Reads the context stashed by the last load.
        """
        if not hasattr(self, 'channel_model'):
            return
        shown = self.channel_model.rowCount()
        total = getattr(self, '_stats_total_channels', shown)
        if getattr(self, '_stats_hidden_only', False):
            self.stats_label.setText(f"{shown:,} hidden channel{'s' if shown != 1 else ''}")
        elif getattr(self, '_stats_panel_filtering', False):
            excluded = max(0, total - shown)
            watched_hidden = getattr(self, '_stats_watched_hidden', 0)
            if getattr(self, '_stats_hide_watched', False) and watched_hidden > 0:
                self.stats_label.setText(
                    f"Showing {shown:,} of {total:,} · {excluded:,} filtered out"
                    f" · {watched_hidden:,} watched hidden"
                )
            else:
                self.stats_label.setText(
                    f"Showing {shown:,} of {total:,} · {excluded:,} filtered out"
                )
        elif getattr(self, '_stats_hide_watched', False):
            watched_hidden = getattr(self, '_stats_watched_hidden', 0)
            if watched_hidden > 0:
                self.stats_label.setText(
                    f"Showing {shown:,} of {total:,} channels · {watched_hidden:,} watched hidden"
                )
            else:
                self.stats_label.setText(f"Showing {shown:,} of {total:,} channels")
        else:
            self.stats_label.setText(f"Showing {shown:,} of {total:,} channels")

    def filter_channels(self, _unused: str = "") -> None:
        """Update banner/status state after a channel load completes.

        With the virtualized model, SQL-side filtering is the only filter and
        the model itself renders visible rows.  This method now manages only the
        bypass banner (shown above the list when Tier 1 filters are suspended)
        and the status bar message.  The _unused parameter is kept for callers
        that still pass a text argument (e.g., search-input signal connections).
        """
        from metatv.gui import icons as _icons

        if self._currently_bypassing:
            self._show_channel_banner(
                f"{_icons.watch_alerts_icon}  Showing results from filtered categories — "
                "filters suspended. Change search or filters to restore."
            )
        else:
            self._hide_channel_banners()

        total = self.channel_model.rowCount()
        logger.debug(f"filter_channels: model has {total} rows")
        if total == 0:
            self.status_bar.showMessage("No channels match — try a different search or filter")
        else:
            self.status_bar.showMessage(f"{total:,} channels loaded")

    # ---- Banner helpers (main thread only) ------------------------------------

    def _show_channel_banner(self, text: str) -> None:
        """Show the info banner strip above the channel list."""
        if not hasattr(self, '_channel_banner'):
            return
        self._channel_banner.setText(text)
        self._channel_banner.setVisible(True)
        if hasattr(self, '_channel_filter_btn'):
            self._channel_filter_btn.setVisible(False)

    def _show_channel_filter_button(self, filtered_out: int) -> None:
        """Show the actionable 'N filtered — click to show' button in the banner area."""
        if not hasattr(self, '_channel_filter_btn'):
            return
        label = (
            f"{filtered_out:,} result{'s' if filtered_out != 1 else ''} filtered  —  click to show"
        )
        self._channel_filter_btn.setText(label)
        self._channel_filter_btn.setVisible(True)
        if hasattr(self, '_channel_banner'):
            self._channel_banner.setVisible(False)

    def _hide_channel_banners(self) -> None:
        """Hide both the info banner and the filter button."""
        if hasattr(self, '_channel_banner'):
            self._channel_banner.setVisible(False)
        if hasattr(self, '_channel_filter_btn'):
            self._channel_filter_btn.setVisible(False)

    def get_enabled_media_types(self) -> list:
        """Get list of enabled media types from the filter panel."""
        if hasattr(self, 'filter_panel'):
            return self.filter_panel.get_filter_state().get(
                'media_types', ['live', 'movie', 'series'])
        return ['live', 'movie', 'series']

    def _open_category_picker(self, channel_ids: list[str]) -> None:
        """Open the CategoryPickerDialog and assign the selected category to channel_ids."""
        from metatv.gui.category_picker_dialog import CategoryPickerDialog
        dlg = CategoryPickerDialog(self.db, self.config, len(channel_ids), self)
        if dlg.exec() != CategoryPickerDialog.DialogCode.Accepted:
            return

        category = dlg.selected_category()
        mood     = dlg.selected_mood()
        exclude  = dlg.add_to_exclusions()

        if not category:
            return

        # Global Exclusions — update config on main thread before submitting the worker
        # so the signal-triggered reload sees the updated exclusion set.
        if exclude and category not in self.config.global_filter_excluded_user_categories:
            self.config.global_filter_excluded_user_categories.append(category)
            self.config.save()
            self._update_filter_btn_state()

        # Assign in background — emit signal after commit so reload is guaranteed post-write
        def _do_assign():
            session = self.db.get_session()
            try:
                repos = RepositoryFactory(session)
                updated = repos.channels.assign_user_category(channel_ids, category, mood)
                logger.info(
                    f"Assigned {updated} channels to category {category!r} mood={mood!r}"
                )  # noqa
            finally:
                session.close()
            self._category_assigned.emit()

        self.executor.submit(_do_assign)

        # Notify the user
        n = len(channel_ids)
        excl_note = " (added to Global Exclusions)" if exclude else ""
        self.status_bar.showMessage(
            f"{n:,} channel{'s' if n != 1 else ''} → \"{category}\"{excl_note}"
        )

        if hasattr(self, "discover_view"):
            QTimer.singleShot(500, self.discover_view.reload)

    def _show_filtered_results(self) -> None:
        """Temporarily bypass Tier 1 filters to show what's being hidden.

        Called when the user clicks the "N results filtered" button in the zero-results
        state. Filters are not changed — next search or filter change restores normal view.
        """
        self._bypass_tier1_filters = True
        self.load_channels()

    def on_filter_changed(self):
        """Handle filter changes from FilterBar or media chips"""
        logger.info("Filter changed, reloading channels...")
        self._bypass_tier1_filters = False  # user changed filters — cancel any bypass
        self.current_filter_state = (
            self.filter_panel.get_filter_state()
            if hasattr(self, 'filter_panel')
            else {}
        )
        # Chip state drives provider filtering; sidebar selection is set separately
        # via on_provider_selected_new which calls load_channels(provider_id) directly.
        # Reset the cursor so a subsequent source click toggles on rather than off.
        self.selected_provider_id = None
        self.load_channels(None)

    def initialize_filter_stats(self) -> None:
        """Kick off a background load of tag-facet statistics for the filter bar.

        Runs ``TagRepository.get_facet_value_counts`` off the UI thread via
        ``_run_query``; ``_on_filter_stats_loaded`` applies the result on the
        main thread once it arrives.

        The query is a single GROUP BY over content_tags JOIN tags JOIN channels,
        scoped to visible channels on active sources — memory-safe over 1M+ rows.
        """
        self._run_query(
            lambda repos: repos.tags.get_facet_value_counts(
                excluded_provider_ids=list(repos.providers.get_hidden_provider_ids()),
            ),
            self._on_filter_stats_loaded,
            token_ref=self._filter_stats_token,
            on_error=lambda e: logger.error(f"Failed to load filter stats: {e}"),
        )

    def _on_filter_stats_loaded(self, tag_counts: dict) -> None:
        """Main-thread handler: apply tag-facet counts to the filter panel."""
        # Legacy prefix field — now always empty since we use the tag model.
        self._filter_unmapped_prefixes = []
        if hasattr(self, 'filter_panel'):
            self.filter_panel.update_data(tag_counts)
        total = sum(sum(v.values()) for v in tag_counts.values())
        logger.info(f"Initialized filter stats (tag model): {total:,} total tag-value occurrences")

    # ---- Unified context menu infrastructure ----------------------------------

    def _show_channel_menu(
        self,
        channel_ids: list[str],
        surface: str,
        gx: int,
        gy: int,
        entry_id: str = "",
    ) -> None:
        """Gather DB context off-thread, then build and exec the menu on the main thread.

        This is the single entry point for all channel context menus in the
        MainWindow family.  Multi-select passes all ids; single-select passes
        a one-element list.  The DB worker builds a ``ChannelMenuContext``
        with DB-derived fields and emits ``_ctx_data_ready``; the main-thread
        handler finishes with config-derived fields and calls ``build_channel_menu``.
        """
        self.executor.submit(
            self._bg_fetch_ctx_data,
            channel_ids, surface, gx, gy, entry_id,
        )

    def _bg_fetch_ctx_data(
        self,
        channel_ids: list[str],
        surface: str,
        gx: int,
        gy: int,
        entry_id: str,
    ) -> None:
        """Worker: gather DB fields for context menu (runs off-thread)."""
        from metatv.gui.channel_menu import ChannelMenuContext

        if len(channel_ids) == 1:
            cid = channel_ids[0]
            with self.db.session_scope(commit=False) as session:
                repos = RepositoryFactory(session)
                channel = repos.channels.get_by_id(cid) if cid else None
                if channel is None and surface != "retry":
                    return
                if channel is not None:
                    ctx = ChannelMenuContext(
                        channel_ids=channel_ids,
                        surface=surface,
                        media_type=channel.media_type or "",
                        is_favorite=bool(channel.is_favorite),
                        in_queue=repos.queue.is_queued(cid),
                        rating=repos.ratings.get(cid) or 0,
                        is_hidden=bool(channel.is_hidden),
                        is_vod_watched=bool(
                            getattr(channel, "watch_completed", False)
                        ),
                        channel_name=channel.name or "",
                        user_category=channel.user_category,
                        entry_id=entry_id,
                        channel_found=True,
                        watch_progress=int(
                            getattr(channel, "watch_progress", 0) or 0
                        ),
                        watch_completed=bool(
                            getattr(channel, "watch_completed", False)
                        ),
                    )
                else:
                    # retry surface with no matching channel row
                    ctx = ChannelMenuContext(
                        channel_ids=channel_ids,
                        surface=surface,
                        entry_id=entry_id,
                        channel_found=False,
                    )
        else:
            # Multi-select — query watch state so the bulk-toggle label is accurate.
            # is_vod_watched=True only when every selected channel is watch_completed.
            from metatv.core.database import ChannelDB as _ChannelDB
            with self.db.session_scope(commit=False) as session:
                watched_count = (
                    session.query(_ChannelDB)
                    .filter(
                        _ChannelDB.id.in_(channel_ids),
                        _ChannelDB.watch_completed == True,  # noqa: E712
                    )
                    .count()
                )
            all_watched = len(channel_ids) > 0 and watched_count == len(channel_ids)
            ctx = ChannelMenuContext(
                channel_ids=channel_ids,
                surface=surface,
                entry_id=entry_id,
                is_vod_watched=all_watched,
            )

        self._ctx_data_ready.emit(ctx, gx, gy)

    def _on_ctx_data_ready(self, ctx, gx: int, gy: int) -> None:
        """Main-thread handler: finish context, build menu, exec it."""
        from PyQt6.QtCore import QPoint
        from metatv.gui.channel_menu import build_channel_menu

        # Finish with main-thread-only fields
        cid = ctx.channel_id
        if cid:
            ctx.is_watched = cid in self.config.epg_watchlist_channels
            _is_mon = getattr(self.config, "is_series_monitored", None)
            ctx.is_series_monitored = bool(_is_mon(cid)) if callable(_is_mon) else False
        ctx.playback_resume_mode = getattr(self.config, "playback_resume_mode", "resume")

        surface = ctx.surface
        if surface == "favorites":
            fav_section = (
                self.sidebar_sections.get("favorites")
                if hasattr(self, "sidebar_sections") else None
            )
            ctx.has_unavailable = fav_section.has_unavailable() if fav_section else False
        elif surface == "queue":
            queue_section = (
                self.sidebar_sections.get("queue")
                if hasattr(self, "sidebar_sections") else None
            )
            ctx.has_unavailable = queue_section.has_unavailable() if queue_section else False

        handlers = self._build_handlers(ctx)
        menu = build_channel_menu(ctx, handlers, parent=self)
        menu.exec(QPoint(gx, gy))

    def _build_handlers(self, ctx) -> dict:
        """Build the handler dict for the given surface and context."""
        surface = ctx.surface
        cid = ctx.channel_id
        ids = ctx.channel_ids

        # Resolve the play handler by surface
        if surface == "history":
            play_fn = lambda: self.play_from_history_id(cid)
        elif surface == "favorites":
            play_fn = lambda: self.play_favorite_id(cid)
        elif surface == "queue":
            play_fn = lambda: self.play_queue_item_id(cid)
        else:
            play_fn = lambda: self.play_channel_by_id(cid)

        # Hide handler varies by surface
        if surface == "history":
            hide_fn = lambda: self._hide_channel_from_history(cid)
        elif surface == "alerts":
            hide_fn = lambda: self._hide_channel_from_alerts(cid)
        else:
            # channel, queue, recommended
            hide_fn = lambda: self._hide_channel_from_recommendations(cid)

        # Clear-unavailable handler varies by surface
        fav_section = (
            self.sidebar_sections.get("favorites")
            if hasattr(self, "sidebar_sections") else None
        )
        queue_section = (
            self.sidebar_sections.get("queue")
            if hasattr(self, "sidebar_sections") else None
        )

        handlers: dict = {
            "play": play_fn,
            "play_new_window": lambda: self.play_channel_new_window_by_id(cid),
            "play_open_ended_buffer": lambda: self.play_channel_open_ended_buffer_by_id(cid),
            "play_from_beginning": lambda: self.play_channel_from_beginning_by_id(cid),
            "resume_from": lambda: self.play_channel_resume_by_id(cid),
            "favorite": lambda: self._toggle_favorite_by_id(
                cid, not ctx.is_favorite
            ),
            "queue": (
                (lambda: self._remove_from_queue(cid))
                if ctx.in_queue
                else (lambda: self._add_to_queue(cid))
            ),
            "like": lambda: self._toggle_rating(cid, 1),
            "dislike": lambda: self._toggle_rating(cid, -1),
            "watch": (
                (lambda: self._unwatch_channel_from_list(cid))
                if ctx.is_watched
                else (lambda: self._watch_channel_from_list(cid))
            ),
            "monitor_series": (
                (lambda: self._unmonitor_series(cid))
                if ctx.is_series_monitored
                else (lambda: self._monitor_series(cid))
            ),
            "mark_watched": (
                (lambda: self._mark_channel_unwatched(cid))
                if ctx.is_vod_watched
                else (lambda: self._mark_channel_watched(cid))
            ),
            "track": lambda: self._prompt_track_from_list(ctx.channel_name),
            "unhide": lambda: self._unhide_channel(cid),
            "hide": hide_fn,
            "remove_history": lambda: self.remove_from_history(cid),
            "not_interested": lambda: self._not_interested(cid),
            "category": lambda: self._open_category_picker([cid]),
            "remove_retry": lambda: self.stream_retry_manager.remove(ctx.entry_id),
            "clear_retry": self.stream_retry_manager.clear_all,
            # Multi-select quick-picks
            "quickpick_trash": lambda: self._quick_assign_category(
                ids, "Trash", "dislike", True
            ),
            "quickpick_watch_later": lambda: self._quick_assign_category(
                ids, "Watch Later", None, False
            ),
            "quickpick_explore": lambda: self._quick_assign_category(
                ids, "Explore", "curious", False
            ),
            "bulk_category": lambda: self._open_category_picker(ids),
            # Multi-select Play All — look up playable DTOs off-thread, then delegate
            "play_all": lambda: self._trigger_play_all_channels(ids),
            # Multi-select bulk actions
            "bulk_mark_watched": lambda: self._bulk_mark_watched(ids),
            "bulk_favorite": lambda: self._bulk_add_to_favorites(ids),
            "bulk_queue": lambda: self._bulk_add_to_queue(ids),
            "bulk_hide": lambda: self._bulk_hide_channels(ids),
        }

        if fav_section is not None:
            handlers["clear_unavailable"] = fav_section.clearUnavailableClicked.emit
        elif queue_section is not None:
            handlers["clear_unavailable"] = queue_section.clearUnavailableClicked.emit

        # For queue surface, override clear_unavailable to queue section's signal
        if surface == "queue" and queue_section is not None:
            handlers["clear_unavailable"] = queue_section.clearUnavailableClicked.emit
        elif surface == "favorites" and fav_section is not None:
            handlers["clear_unavailable"] = fav_section.clearUnavailableClicked.emit

        return handlers

    # ---- Context menu entry points (thin wrappers) ---------------------------

    def _show_context_menu_for(self, channel_id: str, gx: int, gy: int,
                               surface: str) -> None:
        """Legacy single-channel entry point — delegates to _show_channel_menu."""
        self._show_channel_menu([channel_id], surface, gx, gy)

    # ---- QListView / ChannelListModel adapters --------------------------------

    def _on_channel_double_clicked(self, index) -> None:
        """Handle double-click on a QListView item (replaces itemDoubleClicked).

        Derives the channel_id from the model index and delegates to
        ``play_channel_by_id`` (which already handles series drill-in).  The
        old ``play_channel(item)`` takes a ``QListWidgetItem``; since we now
        use a ``QListView`` we extract the id here and call the by-id path.
        """
        from PyQt6.QtCore import Qt
        channel_id = index.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        self.play_channel_by_id(channel_id)

    def _on_channel_middle_clicked(self, index) -> None:
        """Middle-click plays the user-configured action for the clicked row.

        The action is chosen in Settings → Interaction and persisted to
        ``config.middle_click_action``; this looks the key up in the shared
        ``MIDDLE_CLICK_ACTIONS`` registry and dispatches to the mapped per-play
        path (e.g. resume from saved position, or play with endless buffer) —
        no parallel play path, no hardcoded behaviour.
        """
        from PyQt6.QtCore import Qt
        from metatv.gui.middle_click_actions import (
            DEFAULT_MIDDLE_CLICK_ACTION,
            middle_click_action,
        )
        channel_id = index.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        key = getattr(self.config, "middle_click_action", DEFAULT_MIDDLE_CLICK_ACTION)
        play_fn = getattr(self, middle_click_action(key).method, None)
        if callable(play_fn):
            play_fn(channel_id)

    def _on_channel_page_requested(self, query_params: dict, offset: int, page_size: int) -> None:
        """Handle a ``page_requested`` signal from ChannelListModel (main thread).

        Captures the model's current generation so the arriving page can be
        compared and dropped if a newer set_channels() was called in the
        meantime.  The actual DB read runs off-thread via ``_run_query``; the
        result is delivered to ``_on_channel_page_loaded`` on the main thread.
        """
        generation = self.channel_model.generation
        self._run_query(
            lambda repos: self._query_channels_page(repos, query_params, offset, page_size),
            lambda result: self._on_channel_page_loaded(result, generation),
            # No token_ref: we want ALL page results (older pages are guarded by
            # the generation int, not by a supersede token).
        )

    @staticmethod
    def _query_channels_page(repos, query_params: dict, offset: int, page_size: int):
        """Worker (off-thread): fetch one incremental page, return (dtos, has_more).

        Mirrors ``_query_channels`` but is simpler — no count / adult / filtered-out
        logic needed for subsequent pages (that info was already shown for page 1).
        """
        from metatv.core.repositories.dtos import ChannelListDTO

        hidden_only = query_params.get('hidden_only', False)
        force_adult_ids = query_params.get('force_adult_ids', [])
        providers_to_exclude = repos.providers.get_hidden_provider_ids()

        if hidden_only:
            # get_hidden_channels does not support offset/limit — use get_all
            # with hidden_only=True which routes through the same SQL filter.
            rows = repos.channels.get_all(
                provider_id=query_params.get('provider_id'),
                hidden_only=True,
                include_hidden=True,
                search_query=query_params.get('search_query'),
                excluded_provider_ids=providers_to_exclude or None,
                adult_mode='all',
                limit=page_size,
                offset=offset,
            )
        else:
            rows = repos.channels.get_all(
                provider_id=query_params.get('provider_id'),
                media_types=query_params.get('media_types'),
                language_prefixes=query_params.get('language_prefixes'),
                region_prefixes=query_params.get('region_prefixes'),
                quality_prefixes=query_params.get('quality_prefixes'),
                platform_prefixes=query_params.get('platform_prefixes'),
                genre_filters=query_params.get('genre_filters'),
                invert_prefix_filters=query_params.get('invert_prefix_filters', False),
                include_untagged=query_params.get('include_untagged', True),
                include_untagged_quality=query_params.get('include_untagged_quality', True),
                adult_mode=query_params.get('adult_mode', 'hide'),
                force_adult_provider_ids=force_adult_ids or None,
                source_categories=query_params.get('source_categories'),
                include_uncategorized_content_types=True,
                hidden_only=False,
                include_hidden=False,
                search_query=query_params.get('search_query'),
                strict_genre_filter=query_params.get('strict_genre_filter'),
                person_filter=query_params.get('person_filter'),
                excluded_provider_ids=providers_to_exclude or None,
                tag_includes=query_params.get('tag_includes'),
                limit=page_size,
                offset=offset,
            )
        # Raw SQL count BEFORE Python-side exclusion. has_more and the next OFFSET
        # advance by this — never by the surviving count — so exclusions can't
        # stall paging or cause the next page to overlap already-shown rows.
        raw_count = len(rows)
        has_more = raw_count >= page_size

        # Apply global exclusions (same as _query_channels)
        excluded_prefixes = query_params.get('excluded_prefixes', set())
        excluded_user_cats = query_params.get('excluded_user_categories', set())
        if excluded_prefixes:
            rows = [
                c for c in rows
                if c.detected_prefix not in excluded_prefixes
                and c.detected_region not in excluded_prefixes
            ]
        if excluded_user_cats and not hidden_only:
            rows = [c for c in rows if c.user_category not in excluded_user_cats]

        ratings_map = repos.ratings.get_all_map()
        dtos = [ChannelListDTO.from_orm(c, user_rating=ratings_map.get(c.id, 0)) for c in rows]
        return dtos, has_more, raw_count

    def _on_channel_page_loaded(self, result, generation: int) -> None:
        """Main-thread: deliver a fetched page to the model.

        ``result`` is the ``(dtos, has_more)`` tuple from ``_query_channels_page``.
        The ``generation`` is compared inside ``channel_model.append_page`` and
        dropped if it no longer matches the current model generation.
        """
        if result is None:
            # Error already logged by _run_query; clear the fetching flag so a
            # later scroll can retry.
            self.channel_model.mark_fetch_failed()
            return
        dtos, has_more, raw_count = result
        self.channel_model.append_page(
            dtos, has_more=has_more, raw_count=raw_count, generation=generation
        )
        # Reflect the grown loaded count in the "Showing N of M" label.
        self._refresh_channel_stats_label()

    # ---- Multi-select Play All -----------------------------------------------

    def _trigger_play_all_channels(self, channel_ids: list[str]) -> None:
        """Kick off a Play-All for the selected channel IDs.

        Looks up each channel's playable DTO off the main thread (same pattern as
        ``play_channel_by_id`` but batched), converts non-series channels to
        :class:`_PlayAllItem` values in selection order, and delegates to
        :meth:`_play_all_items`.  Series channels are skipped with a log warning —
        they have no single stream URL and are not playable via Play All.

        Args:
            channel_ids: Ordered list of channel IDs as they appear in the
                multi-select (selection order = play order).
        """
        from metatv.gui.main_window_series import _PlayAllItem

        def _bg_fetch(repos) -> list:
            """Off-thread: look up playable DTOs for channel_ids in selection order."""
            from metatv.core.models import MediaType
            items: list[_PlayAllItem] = []
            for cid in channel_ids:
                dto = repos.channels.get_playable_dto(cid)
                if dto is None:
                    logger.warning(f"Play All: channel {cid!r} not found, skipping")
                    continue
                if dto.media_type == MediaType.SERIES:
                    logger.info(
                        f"Play All: skipping series channel {dto.name!r} "
                        f"(series have no direct stream URL)"
                    )
                    continue
                if not dto.stream_url:
                    logger.warning(f"Play All: {dto.name!r} has no stream URL, skipping")
                    continue
                items.append(_PlayAllItem(
                    stream_url=dto.stream_url,
                    title=dto.name,
                    content_id=dto.id,
                    provider_id=dto.provider_id,
                    media_type=dto.media_type or "live",
                ))
            return items

        def _on_items_ready(items: list) -> None:
            if not items:
                self.status_bar.showMessage("No playable streams in selection")
                return
            self._play_all_items(items)

        self._run_query(
            _bg_fetch,
            _on_items_ready,
            on_error=lambda e: logger.error(f"Play All channel lookup failed: {e}"),
        )
