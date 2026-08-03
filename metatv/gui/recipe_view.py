"""RecipeView — tag-cloud "Recipe" builder (task #56; masonry redesign).

Reached via the ✦ Recipe nav chip.  Two sub-tabs — **Recipe** (builder) and
**Saved** — sit above a stack:

    RECIPE TAB (builder)
        ┌ Browse by facet ─────────────── [Search tags across all facets…] ┐
        │  a MASONRY-packed grid of per-facet mini tag-clouds (all browse    │
        │  facets at once — genre/region/language/decade/collection/quality/ │
        │  platform/subtitle; Format hidden).  Clicking a facet heading      │
        │  drills into its full cloud; clicking a tag adds an ingredient and │
        │  stays on the grid.  The decade tile is a chronological chip strip.│
        ├───────────────────────────────────────────────────────────────────┤
        │ RECIPE  <ingredient pills>            → N titles  [✦ Save] [Clear] │  ← one-line bar
        ├───────────────────────────────────────────────────────────────────┤
        │ MATCHING CONTENT   preview · N total                  [Show all →] │
        │ ▸ a Discover-style horizontal shelf of result cards                │
        └───────────────────────────────────────────────────────────────────┘

    SAVED TAB — a responsive grid of saved-recipe cards (name · match count ·
    ingredient tags).  Clicking a card reloads it into the builder; the trash
    button deletes it.  Persisted to the ``saved_recipes`` Config field.

"Show all →" hands off to the SAME Discover-like full-takeover browse view the
old design used (``_BrowseView`` reused via ``_RecipeBrowseMixin``), with lazy DB
pagination — never a parallel grid.

Helper widgets live in ``recipe_widgets.py`` (facet meta + masonry grid),
``recipe_bar_widgets.py`` (tab bar + one-line recipe bar + Matching shelf), and
``recipe_saved_widgets.py`` (Saved cards); host logic is split across
``recipe_cluster_mixin.py`` (grid loads), ``recipe_browse_mixin.py`` (Show-all),
and ``recipe_saved_mixin.py`` (Saved round-trip).

Data wiring (all DB reads off the main thread via the owner's _run_query seam):
  - Clusters ← TagRepository.get_top_tags_per_facet(facets, N, ...)  (one windowed
                pass — top-N tags for every browse facet, EXCLUDING format)
  - Cloud    ← TagRepository.get_tag_counts_for_facet(facet, ...)    (drill-in)
  - YIELDS   ← TagRepository.count_channels_by_tag_facets(...)       (SQL COUNT)
  - Results  ← TagRepository.sample_channels_by_tag_facets(...)      (bounded LIMIT)

Scoping follows DR-0007: the engine is agnostic; the view (control layer) passes
ProviderRepository.get_hidden_provider_ids() AND the user's Global Exclusions
(_global_exclusion_sets(), resolved from Config) into every faceted read.

Selection/playback are host-delegated like DiscoverView: result cards emit
channelSelected / playRequested (channel_id), wired by MainWindow to
show_channel_details_by_id / play_channel_by_id (provider_id threading reused).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.recipe_browse_mixin import _RecipeBrowseMixin
from metatv.gui.recipe_cluster_mixin import _RecipeClusterMixin
from metatv.gui.recipe_saved_mixin import _RecipeSavedMixin
from metatv.gui.weighted_tag_cloud import WeightedTagCloud

# Re-exported for backward compatibility — tests and callers import these helper
# widgets / functions from ``recipe_view`` (their original home before the split).
from metatv.gui.recipe_widgets import (  # noqa: F401
    _ALL_CLUSTER_FACETS,
    _CLUSTER_LIMIT_PER_FACET,
    _facet_meta,
    _ROLE_ORDER,
    BROWSE_FACETS,
    _ClusterGrid,
    _ClusterTile,
    _TagSearchBar,
    _clear_layout,
    _decade_sort_key,
    _facet_color,
    _facet_display,
    _facet_role,
    _generate_recipe_name,
)
from metatv.gui.recipe_bar_widgets import (  # noqa: F401
    _MatchingShelf,
    _RecipeBar,
    _RecipeTabBar,
)
from metatv.gui.recipe_saved_widgets import (  # noqa: F401
    _SavedRecipeCard,
    _SavedRecipesPanel,
)

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.repositories.dtos import TagCountDTO


# ---------------------------------------------------------------------------
# Main RecipeView
# ---------------------------------------------------------------------------

class RecipeView(_RecipeClusterMixin, _RecipeBrowseMixin, _RecipeSavedMixin, QWidget):
    """Two-tab (Recipe | Saved) masonry Recipe builder view.

    Registered as a chip-nav destination by MainWindow.  Follows the same
    on_activate / on_deactivate lifecycle as DiscoverView and EpgView.

    All DB reads go through the owner's ``_run_query`` seam (passed as
    ``run_query_fn``) which runs them off the main thread and delivers results via
    signal on the main thread.

    Selection/playback are host-delegated like DiscoverView/EpgView: the Matching
    Content cards emit ``channelSelected`` / ``playRequested`` (channel_id), which
    MainWindow connects to ``show_channel_details_by_id`` / ``play_channel_by_id``.

    Attributes:
        _recipe_includes: Current include recipe state (``facet_type → set[value]``).
        _recipe_excludes: Current exclude recipe state (``facet_type → set[value]``).
        _selected_facet: The drilled-in facet, or None for the cluster overview.
        _tag_counts:     Most recently loaded TagCountDTOs for the current facet.
        _active:         True while the view is visible (between on_activate /
            on_deactivate).
    """

    channelSelected              = pyqtSignal(str)        # channel_id — select → details pane
    playRequested                = pyqtSignal(str)        # channel_id — play (host-delegated)
    channelMiddleClicked         = pyqtSignal(str)        # channel_id — configured middle-click play
    channelContextMenuRequested  = pyqtSignal(str, int, int)  # channel_id, gx, gy
    tmdbEnrichRequested          = pyqtSignal(list)       # channel_ids just rendered → lazy TMDb enrichment

    def __init__(
        self,
        db: Database,
        config: Config,
        run_query_fn,
        image_cache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._run_query = run_query_fn
        self._image_cache = image_cache

        # Recipe state
        self._recipe_includes: dict[str, set[str]] = {}
        self._recipe_excludes: dict[str, set[str]] = {}
        self._selected_facet: str | None = None
        self._tag_counts: list[TagCountDTO] = []
        self._active: bool = False

        # Default "cluster grid" overview state: the last-loaded top-N-per-facet
        # payload (``{facet: [TagCountDTO, …]}``).  When ``_selected_facet is None``
        # and no search is active the center shows the masonry cluster grid.
        self._cluster_data: dict[str, list] = {}

        # Cross-facet tag search state.  When _search_query is non-empty the center
        # cloud shows matches across ALL facets (color-coded) instead of the
        # selected facet's tags; _search_results caches the last result set.
        self._search_query: str = ""
        self._search_results: list = []

        # Saved-recipes render generation (drops stale per-card count results).
        self._saved_gen: int = 0

        # Tokens for stale-drop on rapid switches
        self._cluster_token: list[int] = [0]
        self._cloud_token: list[int] = [0]
        self._results_token: list[int] = [0]
        self._see_all_token: list[int] = [0]
        self._search_token: list[int] = [0]

        # "Show all" lazy-pagination state.
        self._see_all_offset: int = 0
        self._see_all_total: int = 0
        self._see_all_loading: bool = False

        # Debounce timer — coalesces rapid tag clicks into a single DB query.
        self._results_debounce = QTimer(self)
        self._results_debounce.setSingleShot(True)
        self._results_debounce.setInterval(self._DEBOUNCE_MS)
        self._results_debounce.timeout.connect(self._load_results)

        self._build_ui()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        """Called by MainWindow when this view becomes visible."""
        self._active = True
        # Re-entering via the Recipe chip is the user's 1-click "back to building"
        # path — always land on the Recipe tab's builder, never a stale page.
        self._tab_bar.set_index(0)
        self._show_tab(0)
        self._stack.setCurrentIndex(0)
        logger.debug("RecipeView: activated")
        self._load_clusters()

    def on_deactivate(self) -> None:
        """Called by MainWindow when another view is selected."""
        self._active = False
        self._results_debounce.stop()
        # Cancel any in-flight see-all load so a late result can't repopulate the
        # browse grid after we've navigated away.
        self._see_all_token[0] += 1
        logger.debug("RecipeView: deactivated")

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this view's own persistent chrome
        (the "All facets" back button + "Browse by facet" stage header, both
        styled once at construction) and forward to every child widget that
        has its own ``refresh_theme()`` — same recursion pattern as
        ``MainWindow.refresh_theme()`` forwarding to ``details_pane``/
        ``filter_panel``. Called from ``MainWindow.refresh_theme()``.
        """
        self._back_to_clusters_btn.setStyleSheet(_theme.RECIPE_BACK_TO_GRID_BTN)
        self._stage_hdr.setStyleSheet(_theme.RECIPE_BROWSE_HDR)
        for child in (
            self._tab_bar, self._cluster_grid, self._cloud,
            self._recipe_bar, self._matching, self._browse, self._saved_panel,
        ):
            if hasattr(child, "refresh_theme"):
                child.refresh_theme()

    def reload(self) -> None:
        """Re-issue all data loads against the *current* config.

        Called by the host after the user changes Global Exclusions, so the
        cluster grid / cloud / results re-resolve :meth:`_global_exclusion_sets`
        and drop now-excluded values.  Safe whether visible or not; a no-op before
        first activation.
        """
        if not self._active:
            return
        logger.debug("RecipeView: reload (config changed)")
        self._load_clusters()
        if self._selected_facet is not None:
            self._load_cloud(self._selected_facet)
        if self._recipe_includes or self._recipe_excludes or self._stack.currentIndex() == 1:
            self._load_results()
        # Refresh the Saved tab counts too if it is the active tab.
        if self._tab_stack.currentIndex() == 1:
            self._load_saved_recipes()

    # ── Public helpers ────────────────────────────────────────────────────

    def seed_facet(self, facet_type: str, value: str) -> None:
        """Seed the recipe with one ingredient and land on the content-first view.

        Public entry point for the details-pane tag right-click → Recipe path.
        Replaces the current recipe with exactly one ingredient, selects that
        facet, and loads the matching content through the same recipe→shelf
        chokepoint a hand-built one-ingredient recipe uses.

        Content-first: lands on the full-results browse page (stack page 1) showing
        what matches the tag; the builder is one click away via the browse page's
        "Build recipe" affordance.

        Must be called after the view is activated so the async slots render.
        """
        self._recipe_includes = {facet_type: {value}}
        self._recipe_excludes = {}
        self._selected_facet = facet_type
        self._search_query = ""
        self._search_results = []
        self._search_box.clear()
        # Ensure we're on the Recipe tab (seed is a builder entry).
        self._tab_bar.set_index(0)
        self._show_tab(0)
        self._enter_facet_mode(facet_type)
        self._recipe_bar.update_recipe(self._recipe_includes, self._recipe_excludes, None)
        self._matching.load_results([], 0)
        self._stack.setCurrentIndex(1)
        self._browse.load(self._browse_title(), [])
        self._browse.set_has_more(False)
        self._load_cloud(facet_type)
        self._load_results()

    def clear_recipe(self) -> None:
        """Remove all ingredients and refresh the view.

        Also clears the cross-facet search box so the cluster overview is restored.
        """
        self._recipe_includes.clear()
        self._recipe_excludes.clear()
        self._recipe_bar.update_recipe(self._recipe_includes, self._recipe_excludes, 0)
        self._matching.load_results([], 0)
        self._search_box.clear()
        self._search_query = ""
        self._search_results = []
        self._cloud.clear_filter()
        self._rebuild_cloud()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Sub-tab bar: Recipe | Saved.
        self._tab_bar = _RecipeTabBar()
        self._tab_bar.tab_changed.connect(self._on_tab_changed)
        outer.addWidget(self._tab_bar)

        # Tab stack: page 0 = Recipe tab, page 1 = Saved tab.
        self._tab_stack = QStackedWidget()
        outer.addWidget(self._tab_stack, stretch=1)

        self._tab_stack.addWidget(self._build_recipe_tab())   # index 0
        self._tab_stack.addWidget(self._build_saved_tab())     # index 1

    def _build_recipe_tab(self) -> QWidget:
        """Build the Recipe tab: builder (masonry + bar + shelf) over the Show-all
        browse takeover, in an inner QStackedWidget (``self._stack``)."""
        recipe_tab = QWidget()
        rvl = QVBoxLayout(recipe_tab)
        rvl.setContentsMargins(0, 0, 0, 0)
        rvl.setSpacing(0)

        # Inner stack — page 0 = builder, page 1 = full-results browse.
        self._stack = QStackedWidget()
        rvl.addWidget(self._stack)

        # --- Page 0: the builder ---
        builder = QWidget()
        bvl = QVBoxLayout(builder)
        bvl.setContentsMargins(0, 0, 0, 0)
        bvl.setSpacing(0)

        # Browse area (dominant): header + masonry grid / drill cloud stack.
        browse = QWidget()
        browse_l = QVBoxLayout(browse)
        browse_l.setContentsMargins(16, 12, 16, 8)
        browse_l.setSpacing(8)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(8)
        self._back_to_clusters_btn = QPushButton(f"{_icons.nav_prev_icon} All facets")
        self._back_to_clusters_btn.setFlat(True)
        self._back_to_clusters_btn.setStyleSheet(_theme.RECIPE_BACK_TO_GRID_BTN)
        self._back_to_clusters_btn.setToolTip("Back to the facet overview")
        self._back_to_clusters_btn.clicked.connect(self._on_back_to_clusters)
        self._back_to_clusters_btn.setVisible(False)
        hdr_row.addWidget(self._back_to_clusters_btn)

        self._stage_hdr = QLabel("Browse by facet")
        self._stage_hdr.setStyleSheet(_theme.RECIPE_BROWSE_HDR)
        hdr_row.addWidget(self._stage_hdr)
        hdr_row.addStretch()

        self._search_box = _TagSearchBar()
        self._search_box.search_changed.connect(self._on_search_changed)
        hdr_row.addWidget(self._search_box)
        browse_l.addLayout(hdr_row)

        # Center stack — page 0 = masonry cluster grid, page 1 = drill/search cloud.
        self._top_stack = QStackedWidget()

        cluster_scroll = QScrollArea()
        cluster_scroll.setWidgetResizable(True)
        cluster_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cluster_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._cluster_grid = _ClusterGrid()
        self._cluster_grid.facet_selected.connect(self._on_facet_selected)
        self._cluster_grid.tag_clicked.connect(self._on_cluster_tag_clicked)
        cluster_scroll.setWidget(self._cluster_grid)
        self._top_stack.addWidget(cluster_scroll)   # index 0 — masonry overview

        cloud_scroll = QScrollArea()
        cloud_scroll.setWidgetResizable(True)
        cloud_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cloud_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._cloud = WeightedTagCloud()
        self._cloud.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._cloud.tag_clicked.connect(self._on_tag_clicked)
        self._cloud.tag_clicked_facet.connect(self._on_search_tag_clicked)
        cloud_scroll.setWidget(self._cloud)
        self._top_stack.addWidget(cloud_scroll)     # index 1 — single/search cloud

        browse_l.addWidget(self._top_stack, stretch=1)
        bvl.addWidget(browse, stretch=1)

        # The slim one-line recipe "sentence" bar.
        self._recipe_bar = _RecipeBar()
        self._recipe_bar.ingredient_remove_requested.connect(self._on_ingredient_remove)
        self._recipe_bar.save_requested.connect(self._on_save_recipe)
        self._recipe_bar.clear_requested.connect(self.clear_recipe)
        bvl.addWidget(self._recipe_bar)

        # Matching Content — Discover-style horizontal shelf.
        self._matching = _MatchingShelf(self._image_cache, self._config)
        self._matching.cardClicked.connect(self.channelSelected)
        self._matching.cardDoubleClicked.connect(self.playRequested)
        self._matching.cardMiddleClicked.connect(self.channelMiddleClicked)
        self._matching.cardContextMenu.connect(self.channelContextMenuRequested)
        self._matching.showAllRequested.connect(self._on_show_all)
        bvl.addWidget(self._matching)

        self._stack.addWidget(builder)   # page 0

        # --- Page 1: the full-results browse grid (reuses Discover _BrowseView) ---
        from metatv.gui.discover_browse import _BrowseView

        self._browse = _BrowseView(self._image_cache, self._config)
        self._browse.set_back_label(
            f"{_icons.recipe_icon} Build recipe",
            "Return to the recipe builder to refine ingredients",
        )
        self._browse.backRequested.connect(self._on_browse_back)
        self._browse.cardClicked.connect(self.channelSelected)
        self._browse.cardDoubleClicked.connect(self.playRequested)
        self._browse.cardMiddleClicked.connect(self.channelMiddleClicked)
        self._browse.cardContextMenu.connect(self.channelContextMenuRequested)
        self._browse.loadMoreRequested.connect(self._load_more_see_all)
        self._browse.filterChanged.connect(self._on_see_all_filter_changed)
        self._stack.addWidget(self._browse)

        return recipe_tab

    def _build_saved_tab(self) -> QWidget:
        """Build the Saved tab: a scrollable responsive grid of saved-recipe cards."""
        saved_scroll = QScrollArea()
        saved_scroll.setWidgetResizable(True)
        saved_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        saved_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._saved_panel = _SavedRecipesPanel()
        self._saved_panel.loadRequested.connect(self._on_saved_load)
        self._saved_panel.deleteRequested.connect(self._on_saved_delete)
        self._saved_panel.renameRequested.connect(self._on_saved_rename)
        saved_scroll.setWidget(self._saved_panel)
        return saved_scroll

    # ── Tab switching ─────────────────────────────────────────────────────

    def _show_tab(self, index: int) -> None:
        """Switch the top-level tab stack (0 = Recipe, 1 = Saved)."""
        self._tab_stack.setCurrentIndex(1 if index else 0)

    def _on_tab_changed(self, index: int) -> None:
        """User clicked a sub-tab — switch panels; render Saved lazily on entry."""
        self._show_tab(index)
        if index == 1:
            self._load_saved_recipes()

    # ── Data loading ──────────────────────────────────────────────────────

    def _global_exclusion_sets(self) -> tuple[set[str], set[str], set[str], set[str]]:
        """Resolve the user's Global Exclusions for the faceted queries.

        The control layer (DR-0007): we read ``Config`` here on the main thread
        and hand plain sets to the engine, which never touches Config itself.
        Delegates to the SAME ``filter_utils`` resolvers the main channel list uses
        (one chokepoint), and is paused-aware (all sets empty when paused).

        Returns:
            ``(excluded_prefixes, excluded_categories, excluded_content_types,
            excluded_keywords)``.
        """
        from metatv.core.filter_utils import (
            get_active_category_filter,
            get_excluded_prefixes,
            excluded_tag_content_types,
            keyword_exclusion_list,
        )

        cfg = self._config
        if getattr(cfg, "global_filter_paused", False):
            return set(), set(), set(), set()
        _cat_excluded, _ = get_active_category_filter(cfg)
        excluded_prefixes: set[str] = set(_cat_excluded or []) | get_excluded_prefixes(cfg)
        excluded_categories: set[str] = set(
            getattr(cfg, "global_filter_excluded_user_categories", []) or []
        )
        excluded_content_types: set[str] = excluded_tag_content_types(cfg)
        excluded_keywords: set[str] = set(keyword_exclusion_list(cfg))
        return excluded_prefixes, excluded_categories, excluded_content_types, excluded_keywords

    # The masonry cluster-grid overview + center-mode switch live in
    # _RecipeClusterMixin; the Saved round-trip lives in _RecipeSavedMixin.

    def _load_cloud(self, facet_type: str) -> None:
        """Load tag counts for the selected facet (off-thread)."""
        excl_prefixes, excl_categories, excl_content_types, excl_keywords = self._global_exclusion_sets()
        self._run_query(
            lambda repos: repos.tags.get_tag_counts_for_facet(
                facet_type,
                excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
                excluded_keywords=excl_keywords,
            ),
            self._on_cloud_loaded,
            token_ref=self._cloud_token,
            on_error=self._on_cloud_error,
        )

    def _on_cloud_loaded(self, counts: list) -> None:
        """Main-thread slot: repopulate the WeightedTagCloud."""
        if not self._active:
            return
        self._tag_counts = counts
        self._rebuild_cloud()

    def _on_cloud_error(self, exc: Exception) -> None:
        logger.error("RecipeView: cloud load failed: {}", exc)
        self._stage_hdr.setText("Couldn't load tags")

    def _rebuild_cloud(self) -> None:
        """Re-render the center view with current tag counts + recipe state.

        The default (``_selected_facet is None`` and no active search) renders the
        masonry cluster grid; a selected facet renders that facet's single cloud.
        """
        facet = self._selected_facet
        if facet is None:
            self._render_clusters()
            return

        meta = _facet_meta().get(facet)
        color = meta[1] if meta else _theme.COLOR_TEXT
        display = meta[0] if meta else facet.title()

        includes = self._recipe_includes.get(facet, set())
        excludes = self._recipe_excludes.get(facet, set())

        items: list[tuple[str, int, str]] = []
        for dto in self._tag_counts:
            if dto.value in includes:
                state = "include"
            elif dto.value in excludes:
                state = "exclude"
            else:
                state = "none"
            items.append((dto.value, dto.channel_count, state))

        display_map: dict[str, str] | None = None
        if facet == "content_type":
            from metatv.core.channel_name_utils import content_type_display
            display_map = {v: content_type_display(v) for v, _c, _s in items}

        self._cloud.set_tags(items, facet_color=color, facet_name=display,
                             display_map=display_map)
        self._show_cloud()

    # Result-shelf card cap — the bounded preview never materialises the full set.
    _RESULTS_CARD_CAP: int = 60

    # Debounce window for _load_results (ms).
    _DEBOUNCE_MS: int = 300

    # "Show all →" lazy-pagination page size.
    _SEE_ALL_PAGE: int = 60

    def _load_results(self) -> None:
        """Load the YIELDS count + a bounded set of result cards (off-thread)."""
        includes = {k: set(v) for k, v in self._recipe_includes.items() if v}
        excludes = {k: set(v) for k, v in self._recipe_excludes.items() if v}
        excl_prefixes, excl_categories, excl_content_types, excl_keywords = self._global_exclusion_sets()
        cap = self._RESULTS_CARD_CAP

        def _query(repos):
            hidden = repos.providers.get_hidden_provider_ids()
            total = repos.tags.count_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
                excluded_keywords=excl_keywords,
                collapse_variants=True,
            )
            if total == 0:
                return ([], 0)
            cards = repos.tags.sample_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
                excluded_keywords=excl_keywords,
                limit=cap,
                collapse_variants=True,
            )
            return (cards, total)

        self._run_query(
            _query,
            self._on_results_loaded,
            token_ref=self._results_token,
            on_error=self._on_results_error,
        )

    def _on_results_loaded(self, payload: tuple) -> None:
        """Main-thread slot: update the Matching shelf and recipe-bar YIELDS."""
        if not self._active:
            return
        cards, total = payload
        # Feed the just-rendered matching cards to lazy TMDb enrichment (host chokepoint).
        if cards:
            self.tmdbEnrichRequested.emit([c.channel_id for c in cards])
        self._matching.load_results(cards, total)
        self._recipe_bar.update_recipe(self._recipe_includes, self._recipe_excludes, total)
        if self._stack.currentIndex() == 1:
            self._reseed_see_all()

    def _on_results_error(self, exc: Exception) -> None:
        logger.error("RecipeView: results load failed: {}", exc)

    # "Show all →" full-results browse drill-down + lazy DB pagination live
    # in _RecipeBrowseMixin (recipe_browse_mixin.py), mixed into this class.

    # ── Event handlers ────────────────────────────────────────────────────

    def _on_facet_selected(self, facet_type: str) -> None:
        """User clicked a cluster's facet header → drill into its full cloud."""
        self._enter_facet_mode(facet_type)
        self._tag_counts = []
        self._load_cloud(facet_type)

    def _cycle_tag(self, facet: str | None, value: str) -> None:
        """Cycle ``(facet, value)`` through none → include → exclude → none.

        The single ingredient-mutation chokepoint shared by the single-facet cloud,
        the cross-facet search cloud, and the masonry tiles.  Mutates recipe state,
        renders the recipe bar instantly, and fires the debounced results load — but
        leaves the *cloud* re-render to the caller.
        """
        if facet is None:
            return

        inc = self._recipe_includes.setdefault(facet, set())
        exc = self._recipe_excludes.setdefault(facet, set())

        if value in inc:
            inc.discard(value)
            exc.add(value)
            logger.debug("RecipeView: {} {} → exclude", facet, value)
        elif value in exc:
            exc.discard(value)
            logger.debug("RecipeView: {} {} → none", facet, value)
        else:
            inc.add(value)
            logger.debug("RecipeView: {} {} → include", facet, value)

        if not inc:
            self._recipe_includes.pop(facet, None)
        if not exc:
            self._recipe_excludes.pop(facet, None)

        self._recipe_bar.update_recipe(self._recipe_includes, self._recipe_excludes, None)
        self._results_debounce.start()

    def _on_tag_clicked(self, value: str) -> None:
        """Single-facet cloud click → cycle the value under the selected facet."""
        facet = self._selected_facet
        if facet is None:
            return
        self._cycle_tag(facet, value)
        self._rebuild_cloud()

    def _on_search_tag_clicked(self, facet_type: str, value: str) -> None:
        """Cross-facet search cloud click → cycle the value under ITS own facet."""
        self._cycle_tag(facet_type, value)
        if self._search_query:
            self._render_search_cloud(self._search_results)
        else:
            self._rebuild_cloud()

    # ── Cross-facet tag search ────────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        """Search box settled — search across facets, or restore the prior view."""
        self._search_query = text.strip()
        if not self._search_query:
            self._search_results = []
            facet = self._selected_facet
            if facet is not None:
                self._stage_hdr.setText(_facet_display(facet))
            else:
                self._stage_hdr.setText("Browse by facet")
            self._rebuild_cloud()
            return
        self._load_search(self._search_query)

    def _load_search(self, query: str) -> None:
        """Run the cross-facet tag search off-thread via the async seam."""
        excl_prefixes, excl_categories, excl_content_types, excl_keywords = self._global_exclusion_sets()
        self._run_query(
            lambda repos: repos.tags.search_tag_values_across_facets(
                query,
                excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
                excluded_keywords=excl_keywords,
            ),
            self._on_search_loaded,
            token_ref=self._search_token,
            on_error=self._on_search_error,
        )

    def _on_search_loaded(self, results: list) -> None:
        """Main-thread slot: fill the cloud with cross-facet matches."""
        if not self._active:
            return
        if not self._search_query:
            return
        self._search_results = results
        self._render_search_cloud(results)
        self._stage_hdr.setText(f'Matches for "{self._search_query}"')
        self._show_cloud()

    def _render_search_cloud(self, results: list) -> None:
        """Render *results* (cross-facet matches) into the cloud, colored by facet."""
        from metatv.core.channel_name_utils import content_type_display
        items: list[tuple[str, int, str, str, str]] = []
        display_map: dict[str, str] = {}
        for dto in results:
            ftype = dto.facet_type
            if dto.value in self._recipe_includes.get(ftype, set()):
                state = "include"
            elif dto.value in self._recipe_excludes.get(ftype, set()):
                state = "exclude"
            else:
                state = "none"
            items.append(
                (dto.value, dto.channel_count, state, _facet_color(ftype), ftype)
            )
            if ftype == "content_type":
                display_map[dto.value] = content_type_display(dto.value)
        self._cloud.set_multi_facet_tags(
            items, facet_name=f'"{self._search_query}"',
            display_map=display_map or None,
        )

    def _on_search_error(self, exc: Exception) -> None:
        logger.error("RecipeView: tag search failed: {}", exc)

    def _on_ingredient_remove(self, facet_type: str, value: str) -> None:
        """Remove an ingredient pill from the recipe bar (cycles state → none)."""
        self._recipe_includes.get(facet_type, set()).discard(value)
        self._recipe_excludes.get(facet_type, set()).discard(value)

        if not self._recipe_includes.get(facet_type):
            self._recipe_includes.pop(facet_type, None)
        if not self._recipe_excludes.get(facet_type):
            self._recipe_excludes.pop(facet_type, None)

        self._recipe_bar.update_recipe(self._recipe_includes, self._recipe_excludes, None)
        if self._search_query:
            self._render_search_cloud(self._search_results)
        else:
            self._rebuild_cloud()
        self._results_debounce.start()

    # ── Accessors (for tests) ─────────────────────────────────────────────

    @property
    def recipe_includes(self) -> dict[str, set[str]]:
        """Current include recipe state (read-only view for tests)."""
        return self._recipe_includes

    @property
    def recipe_excludes(self) -> dict[str, set[str]]:
        """Current exclude recipe state (read-only view for tests)."""
        return self._recipe_excludes

    @property
    def selected_facet(self) -> str | None:
        """Currently selected facet type (read-only for tests)."""
        return self._selected_facet
