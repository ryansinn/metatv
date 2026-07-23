"""_RecipeBrowseMixin — the Recipe view's "Show all" full-results browse page.

Extracted from ``recipe_view.py`` (to keep that file under the 1000-line limit)
following the EPG view's mixin convention (``epg_*_mixin.py``).  These methods
form one cohesive concern: swapping the builder for the full-results browse grid
(reusing Discover's ``_BrowseView``), lazy DB pagination as the user scrolls, and
keeping the browse page in sync when the recipe / Global Exclusions change.

The mixin is stateless — it only ever touches ``self`` attributes owned by
:class:`~metatv.gui.recipe_view.RecipeView` (``_browse``, ``_now_plating``,
``_stack``, the recipe state, the ``_see_all_*`` pagination cursors, and the
``_run_query`` seam), so it is mixed into ``RecipeView`` and never instantiated
on its own.
"""

from __future__ import annotations

from loguru import logger

from metatv.gui.recipe_widgets import _generate_recipe_name


class _RecipeBrowseMixin:
    """Recipe "Show all" browse drill-down + lazy pagination (see module docstring)."""

    def _browse_title(self) -> str:
        """Build the browse-page title from the recipe name + match count.

        Uses the rail's editorial recipe name when the recipe has ingredients
        (else a neutral "Tonight's Recipe"), suffixed with the live match count
        — e.g. "Late-Night Drama Selection · 366,085 matches".
        """
        total = self._now_plating._total_count
        if self._recipe_includes or self._recipe_excludes:
            name = _generate_recipe_name(self._recipe_includes, self._recipe_excludes)
        else:
            name = "Tonight's Recipe"
        suffix = f"  ·  {total:,} match{'es' if total != 1 else ''}"
        return f"{name}{suffix}"

    def _on_show_all(self) -> None:
        """Swap the bounded teaser for the full-results browse grid.

        Page 1 does ZERO new DB/image work: it seeds the browse grid with the
        cards the teaser already fetched+rendered (≤ :data:`_RESULTS_CARD_CAP`),
        sets the pagination offset to that seed count and the known total to the
        teaser's match total, and flags ``set_has_more`` so the next near-bottom
        scroll pages from the DB via :meth:`_load_more_see_all`.  No big up-front
        fetch.  The shared deterministic ordering of
        ``sample_channels_by_tag_facets`` makes the seeded teaser cards align
        with the DB pages that follow.
        """
        self._stack.setCurrentIndex(1)
        self._reseed_see_all()

    def _reseed_see_all(self) -> None:
        """Reset the browse page to a fresh page-1 seed from the current teaser.

        Loads the browse grid with the cards the teaser already fetched+rendered
        (≤ :data:`_RESULTS_CARD_CAP`) — ZERO new DB/image work — then resets the
        pagination offset to that seed count, the total to the teaser's match
        count, and arms ``set_has_more`` if any matches remain.  Bumps the
        ``_see_all_token`` so any in-flight page from a prior recipe is dropped.
        Shared by :meth:`_on_show_all` (first open) and :meth:`_on_results_loaded`
        (recipe / exclusions changed while browsing).
        """
        # Drop any page request still in flight against the previous recipe.
        self._see_all_token[0] += 1
        # Page 1 = the cards the strip already rendered (zero-latency feedback).
        cached_cards = [w._card for w in self._now_plating._card_widgets]
        self._browse.load(self._browse_title(), cached_cards)
        self._see_all_offset = len(cached_cards)
        self._see_all_total = self._now_plating._total_count
        self._see_all_loading = False
        self._browse.set_has_more(self._see_all_offset < self._see_all_total)

    def _on_browse_back(self) -> None:
        """Browse 'Back' → return to the constructor (page 0)."""
        self._stack.setCurrentIndex(0)

    def _on_see_all_filter_changed(self, text: str) -> None:
        """Filter text changed in the browse view — trigger a SQL-filtered fresh fetch.

        Bug D fix: the previous ``_apply_filter`` in ``_BrowseView`` only
        filtered already-loaded cards.  Lazy-loaded subsequent pages ignored the
        filter and appended everything, making results below the visible viewport
        appear unfiltered.  By re-seeding the browse pagination here — bumping
        the token, resetting offset to 0, and loading the first filtered page
        from the DB — every page (including all subsequent lazy loads) passes
        ``name_filter`` to ``sample_channels_by_tag_facets`` at the SQL level.

        The ``_BrowseView._apply_filter`` still rebuilds the in-memory subset
        immediately (fast feedback while the DB fetch is in flight), but that
        subset is limited to already-loaded cards.  The DB fetch replaces the
        view with the correct full-corpus filtered result once it arrives.

        Clearing the filter (``text == ""``) behaves the same way: a fresh
        unfiltered fetch re-seeds from offset=0.
        """
        # Bump token so any in-flight un-filtered page is dropped.
        self._see_all_token[0] += 1
        self._see_all_loading = False
        self._see_all_offset = 0
        # Total is unknown until the new filtered fetch arrives; assume non-zero
        # so _load_more_see_all can fire.  It will be capped correctly once the
        # first filtered page lands (offset advances; set_has_more compares to total).
        # If the filter yields fewer than one page the offset will meet total and stop.
        # We keep the existing total as an upper bound — it will only over-arm the
        # guard, which is safe (next scroll fires a query that returns 0 cards and
        # stops).
        name_filter = text.strip() or None

        includes = {k: set(v) for k, v in self._recipe_includes.items() if v}
        excludes = {k: set(v) for k, v in self._recipe_excludes.items() if v}
        excl_prefixes, excl_categories, excl_content_types = self._global_exclusion_sets()
        limit = self._SEE_ALL_PAGE

        def _query(repos):
            hidden = repos.providers.get_hidden_provider_ids()
            return repos.tags.sample_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
                limit=limit,
                offset=0,
                name_filter=name_filter,
                collapse_variants=True,
            )

        self._run_query(
            _query,
            self._on_see_all_filter_loaded,
            token_ref=self._see_all_token,
            on_error=self._on_see_all_error,
        )

    def _on_see_all_filter_loaded(self, cards: list) -> None:
        """Main-thread slot: replace the browse grid with the first filtered page.

        Called when the DB-side filtered fetch started by
        :meth:`_on_see_all_filter_changed` delivers its first page.  Replaces
        (not appends) the browse view so the user sees only results matching the
        filter string.  Arms ``set_has_more`` so further scrolling lazy-loads
        additional filtered pages.

        ``preserve_filter=True`` is critical here: without it ``load()`` would
        clear the search box, making ``current_filter()`` return ``""`` so the
        next lazy page (``_load_more_see_all``) would fetch unfiltered results
        and append them below the filtered ones (QA bug 10bc0a7 Fix B).
        """
        if not self._active:
            return
        # Replace (not append): load() resets has_more + pending so the
        # pagination state starts clean for the filtered set.
        # preserve_filter=True keeps the search-box text so subsequent lazy
        # pages (via _load_more_see_all → current_filter()) stay filtered.
        self._browse.load(self._browse_title(), cards, preserve_filter=True)
        self._see_all_offset = len(cards)
        self._see_all_loading = False
        self._browse.set_has_more(self._see_all_offset < self._see_all_total)

    def _load_more_see_all(self) -> None:
        """Fetch+append the next browse page from the DB (off-thread).

        Fired by ``_browse.loadMoreRequested`` on a near-bottom scroll.  Pages
        ``_SEE_ALL_PAGE`` cards at a time from ``_see_all_offset``, reusing the
        EXACT scoping as :meth:`_load_results` (Global Exclusions +
        ``get_hidden_provider_ids()``) and the SAME deterministic ordering so the
        page is disjoint from what's already shown.  Guarded by
        ``_see_all_loading`` (no overlapping loads) and ``_see_all_token`` (drop a
        stale page after a recipe change / deactivate).  When a filter is active
        (``_browse.current_filter()`` is non-empty), it is threaded into the
        query so every page respects it at the SQL level.
        """
        if self._see_all_loading or self._see_all_offset >= self._see_all_total:
            return
        self._see_all_loading = True

        includes = {k: set(v) for k, v in self._recipe_includes.items() if v}
        excludes = {k: set(v) for k, v in self._recipe_excludes.items() if v}
        excl_prefixes, excl_categories, excl_content_types = self._global_exclusion_sets()
        limit = self._SEE_ALL_PAGE
        offset = self._see_all_offset
        # Thread the current filter text (if any) into the DB query so lazy pages
        # also respect it (Bug D fix — previously new pages ignored the filter).
        name_filter = self._browse.current_filter().strip() or None

        def _query(repos):
            hidden = repos.providers.get_hidden_provider_ids()
            return repos.tags.sample_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
                limit=limit,
                offset=offset,
                name_filter=name_filter,
                collapse_variants=True,
            )

        self._run_query(
            _query,
            self._on_see_all_loaded,
            token_ref=self._see_all_token,
            on_error=self._on_see_all_error,
        )

    def _on_see_all_loaded(self, cards: list) -> None:
        """Main-thread slot: append the fetched page to the browse grid."""
        if not self._active:
            return
        self._browse.append(cards)
        self._see_all_offset += len(cards)
        self._see_all_loading = False
        # Re-arm "has more" (also re-arms the browse debounce) only while pages
        # remain — once offset >= total, no further query can fire.
        self._browse.set_has_more(self._see_all_offset < self._see_all_total)

    def _on_see_all_error(self, exc: Exception) -> None:
        logger.error("RecipeView: see-all load failed: {}", exc)
        self._see_all_loading = False
