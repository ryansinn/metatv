"""_RecipeClusterMixin — the Recipe view's default per-facet "cluster grid".

Extracted from ``recipe_view.py`` (to keep that file under the 1000-line limit)
following the same convention as ``recipe_browse_mixin.py`` / the EPG view's
``epg_*_mixin.py``.  These methods form one cohesive concern: the default facet
overview (a mini weighted tag-cloud per facet, loaded in ONE windowed engine
pass), the center-pane mode switch between that overview and the drilled-in /
search cloud, and the two persisted collapse states (the "More facets" section
and the Tonight's-Recipe column).

The mixin is stateless — it only ever touches ``self`` attributes owned by
:class:`~metatv.gui.recipe_view.RecipeView` (``_cluster_grid``, ``_cluster_data``,
``_top_stack``, ``_back_to_clusters_btn``, ``_stage_hdr``, the ``_col1_*``
collapse widgets, the recipe state, the ``_run_query`` seam + ``_cluster_token``,
and ``_config``), so it is mixed into ``RecipeView`` and never instantiated on
its own.
"""

from __future__ import annotations

from loguru import logger

from metatv.gui.recipe_widgets import (
    _ALL_CLUSTER_FACETS,
    _CLUSTER_LIMIT_PER_FACET,
    _facet_display,
)


class _RecipeClusterMixin:
    """Recipe default cluster-grid overview + center-mode switch (see module docstring)."""

    # ── Data loading ──────────────────────────────────────────────────────

    def _load_clusters(self) -> None:
        """Load the default cluster-grid overview: top-N tags for every facet.

        The single engine chokepoint (``get_top_tags_per_facet``) resolves all
        cluster facets in one windowed pass, scoped exactly like the single-facet
        cloud (DR-0007: ``get_hidden_provider_ids()`` + the user's Global
        Exclusions), off the ``_run_query`` seam.
        """
        excl_prefixes, excl_categories, excl_content_types = self._global_exclusion_sets()
        facets = list(_ALL_CLUSTER_FACETS)
        limit = _CLUSTER_LIMIT_PER_FACET
        self._run_query(
            lambda repos: repos.tags.get_top_tags_per_facet(
                facets,
                limit,
                excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
            ),
            self._on_clusters_loaded,
            token_ref=self._cluster_token,
            on_error=self._on_clusters_error,
        )

    def _on_clusters_loaded(self, data: dict) -> None:
        """Main-thread slot: cache the per-facet top tags and (re)render the grid."""
        if not self._active:
            return
        self._cluster_data = data or {}
        # Only repaint the overview if it's the active center view; a drill-in /
        # search that raced ahead keeps its cloud.
        if self._selected_facet is None and not self._search_query:
            self._render_clusters()

    def _on_clusters_error(self, exc: Exception) -> None:
        logger.error("RecipeView: cluster load failed: {}", exc)
        # Visible failure surface (never a silent empty overview).
        self._cluster_grid.set_clusters({}, {}, {})
        if self._selected_facet is None and not self._search_query:
            self._stage_hdr.setText("Couldn't load facets")

    def _render_clusters(self) -> None:
        """Render the cluster grid from cached data + current recipe marks."""
        self._cluster_grid.set_clusters(
            self._cluster_data, self._recipe_includes, self._recipe_excludes
        )
        self._show_clusters()

    # ── Center-view mode switching (cluster overview ↔ single cloud) ───────

    def _show_clusters(self) -> None:
        """Switch the center pane to the cluster-grid overview (page 0)."""
        self._top_stack.setCurrentIndex(0)
        self._back_to_clusters_btn.setVisible(False)

    def _show_cloud(self) -> None:
        """Switch the center pane to the single-facet / search cloud (page 1)."""
        self._top_stack.setCurrentIndex(1)
        # The back link is the "click the facet again to deselect" affordance —
        # shown whenever a facet is drilled in or a search cloud is up.
        self._back_to_clusters_btn.setVisible(
            self._selected_facet is not None or bool(self._search_query)
        )

    def _enter_facet_mode(self, facet_type: str) -> None:
        """Set the breadcrumb + show the single-facet cloud pane for *facet_type*."""
        self._selected_facet = facet_type
        self._stage_hdr.setText(_facet_display(facet_type))
        self._show_cloud()

    def _on_back_to_clusters(self) -> None:
        """"‹ All facets" — deselect the drilled-in facet / search, back to the grid.

        Decision 4: clicking a cluster's facet drills into its full cloud; this is
        the inverse — it clears the selection and returns to the overview.  The
        recipe ingredients are untouched (they persist across the toggle).
        """
        self._selected_facet = None
        if self._search_query:
            self._search_query = ""
            self._search_results = []
            self._search_box.clear()
        self._stage_hdr.setText("Browse by facet")
        self._render_clusters()

    def _on_cluster_tag_clicked(self, facet_type: str, value: str) -> None:
        """A tag inside a cluster tile → add the ingredient, STAY in the overview.

        Cross-facet build without leaving the grid: reuses the shared
        :meth:`_cycle_tag` include/exclude cycle, then re-renders the cluster grid
        so the clicked tag immediately shows its new mark.
        """
        self._cycle_tag(facet_type, value)
        self._render_clusters()
