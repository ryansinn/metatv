"""RecipeView — tag-cloud "Recipe" builder (task #56; two-column redesign).

Two-column view reached via the ✦ Recipe nav chip:

    COLUMN 1  — "THE PANTRY" facet sidebar + "SAVED RECIPES", stacked over the
                "TONIGHT'S RECIPE" ingredient rail (a vertical QSplitter).
    COLUMN 2  — the WeightedTagCloud stacked over the "Now Plating" results
                grid (a vertical QSplitter, cloud on top, results getting the
                bottom half — a real, browsable results area, not a thin strip).

All three splitters (Column 1 vs 2, pantry vs rail, cloud vs Now Plating) persist
their sizes to Config and restore on construction, per DESIGN.md (save on change,
restore in __init__ with signals blocked, connect handlers after).

Entry behaviour is content-first: :meth:`seed_facet` (the details-pane tag
right-click seam) lands on the full-results browse page showing what matches the
tag, with a "Build recipe" affordance back to the builder.  Opening via the nav
chip (no preset tag) lands on the builder as before.

Helper widgets (Pantry / rail / Now Plating grid) live in ``recipe_widgets.py``
and are re-exported here for backward compatibility.

Data wiring (all DB reads off the main thread via the owner's _run_query seam):
  - Pantry  ← TagRepository.get_facet_summary(...)
  - Cloud   ← TagRepository.get_tag_counts_for_facet(facet, ...)
  - YIELDS  ← TagRepository.count_channels_by_tag_facets(...)        (SQL COUNT)
  - Results ← TagRepository.sample_channels_by_tag_facets(...)       (bounded
                LIMIT → session-free ContentCards; never materialises the set).

Scoping follows DR-0007: the engine is agnostic; the view (control layer) passes
ProviderRepository.get_hidden_provider_ids() AND the user's Global Exclusions
(_global_exclusion_sets(), resolved from Config) into every faceted read, so the
pantry, cloud, YIELDS, and results all agree.

Selection/playback are host-delegated like DiscoverView: result cards emit
channelSelected / playRequested (channel_id), wired by MainWindow to
show_channel_details_by_id / play_channel_by_id (provider_id threading reused).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from metatv.core.recipe_state import (
    DEFAULT_RATING_RANGE as _DEFAULT_RATING_RANGE,
    deserialize_recipe as _deserialize_recipe,
    rating_range_is_full as _rating_range_is_full,
    serialize_recipe as _serialize_recipe,
)
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.rating_range_slider import format_rating_range as _format_rating_range
from metatv.gui.recipe_browse_mixin import _RecipeBrowseMixin
from metatv.gui.weighted_tag_cloud import WeightedTagCloud

# Re-exported for backward compatibility — tests and callers import these helper
# widgets / functions from ``recipe_view`` (their original home before the split).
from metatv.gui.recipe_widgets import (  # noqa: F401
    _FACET_META,
    _ROLE_ORDER,
    _ChipRow,
    _FacetRowButton,
    _GridContainer,
    _NowPlatingStrip,
    _PantrySidebar,
    _RecipeRail,
    _clear_layout,
    _facet_color,
    _facet_display,
    _facet_role,
    _generate_recipe_name,
)

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.repositories.dtos import TagCountDTO


# ---------------------------------------------------------------------------
# Main RecipeView
# ---------------------------------------------------------------------------

class RecipeView(_RecipeBrowseMixin, QWidget):
    """Three-column Recipe builder view.

    Registered as a chip-nav destination by MainWindow.  Follows the same
    on_activate / on_deactivate lifecycle as DiscoverView and EpgView.

    The view is stateless about DB reads: all reads go through the owner's
    ``_run_query`` seam (passed as ``run_query_fn`` in the constructor) which
    runs them off the main thread and delivers results via signal on the main
    thread.

    Selection/playback are host-delegated like DiscoverView/EpgView: the
    "Now Plating" result cards emit ``channelSelected`` / ``playRequested``
    (channel_id), which MainWindow connects to ``show_channel_details_by_id`` /
    ``play_channel_by_id`` — so provider_id threading and the canonical play
    path are reused, never hand-rolled here.

    Attributes:
        _recipe_includes: Current include recipe state.  Maps
            ``facet_type → set[value]``.
        _recipe_excludes: Current exclude recipe state.  Maps
            ``facet_type → set[value]``.
        _selected_facet: The currently selected facet in the Pantry.
        _tag_counts:     Most recently loaded TagCountDTOs for the current facet.
        _active:         True while the view is visible (between on_activate /
            on_deactivate).
    """

    channelSelected              = pyqtSignal(str)        # channel_id — select → details pane
    playRequested                = pyqtSignal(str)        # channel_id — play (host-delegated)
    channelMiddleClicked         = pyqtSignal(str)        # channel_id — configured middle-click play
    channelContextMenuRequested  = pyqtSignal(str, int, int)  # channel_id, gx, gy

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
        # Rating-range ingredient — the first non-tag criterion.  Full 0–10 span
        # = no filter (see core.recipe_state).  Threaded into every faceted read.
        self._rating_range: tuple[float, float] = tuple(_DEFAULT_RATING_RANGE)
        self._selected_facet: str | None = None
        self._tag_counts: list[TagCountDTO] = []
        self._active: bool = False

        # Cross-facet Pantry search state.  When _search_query is non-empty the
        # center cloud shows matches across ALL facets (color-coded) instead of
        # the selected facet's tags; _search_results caches the last result set so
        # a tag click can re-render the search cloud with updated include marks.
        self._search_query: str = ""
        self._search_results: list = []

        # Tokens for stale-drop on rapid switches
        self._pantry_token: list[int] = [0]
        self._cloud_token: list[int] = [0]
        self._results_token: list[int] = [0]
        self._see_all_token: list[int] = [0]
        self._search_token: list[int] = [0]

        # "Show all" lazy-pagination state: how many cards we've already shown
        # (the page-1 seed reuses the teaser's cards), the known full match
        # total, and a guard so we never fire overlapping page loads.
        self._see_all_offset: int = 0
        self._see_all_total: int = 0
        self._see_all_loading: bool = False

        # Debounce timer — coalesces rapid tag clicks into a single DB query.
        # Each mutation renders the rail/cloud instantly and restarts this timer;
        # the timer fires _load_results() once after the idle window expires.
        self._results_debounce = QTimer(self)
        self._results_debounce.setSingleShot(True)
        self._results_debounce.setInterval(self._DEBOUNCE_MS)
        self._results_debounce.timeout.connect(self._load_results)

        # Debounce splitter-drag persistence — ``splitterMoved`` fires per drag
        # pixel; coalesce the whole burst into ONE config write ~500 ms after the
        # drag settles (mirrors MainWindow._layout_save_debounce), so a resize
        # doesn't rewrite + back up config.yaml dozens of times per second.
        self._layout_save_debounce = QTimer(self)
        self._layout_save_debounce.setSingleShot(True)
        self._layout_save_debounce.setInterval(500)
        self._layout_save_debounce.timeout.connect(self._persist_splitter_sizes)

        self._build_ui()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        """Called by MainWindow when this view becomes visible."""
        self._active = True
        # Re-entering via the Recipe chip is the user's 1-click "back to
        # building" path — always land on the constructor, never a stale browse
        # page from a previous visit.
        self._stack.setCurrentIndex(0)
        logger.debug("RecipeView: activated")
        # Restore the rating slider to the current recipe state, and refresh the
        # Saved Recipes list (config may have changed while we were away).
        self._pantry.set_rating_range(*self._rating_range)
        self._load_saved_recipes()
        self._load_pantry()

    def on_deactivate(self) -> None:
        """Called by MainWindow when another view is selected."""
        self._active = False
        self._results_debounce.stop()
        # Cancel any in-flight see-all load so a late result can't repopulate the
        # browse grid after we've navigated away (matches the _results_token bump).
        self._see_all_token[0] += 1
        logger.debug("RecipeView: deactivated")

    def reload(self) -> None:
        """Re-issue all data loads against the *current* config.

        Called by the host (MainWindow) after the user changes Global
        Exclusions, so the pantry / cloud / results re-resolve
        :meth:`_global_exclusion_sets` and drop now-excluded values.  Mirrors
        the loads ``on_activate`` triggers:

        - re-load the pantry (which cascades to the cloud via the currently
          selected facet in ``_on_pantry_loaded``), and
        - re-load the results shelf + YIELDS when a recipe is in progress, so
          the count and cards reflect the new exclusions immediately.

        Safe to call whether the view is visible or not, and a no-op before the
        view has ever been activated (nothing has been loaded yet, so there is
        no stale state to refresh).  The ``_run_query`` token guards drop any
        in-flight result superseded by this reload.
        """
        if not self._active:
            return
        logger.debug("RecipeView: reload (config changed)")
        self._load_pantry()
        # Re-run the teaser results when a recipe is in progress OR the browse
        # drill-down is showing (it may have no ingredients yet still needs to
        # re-resolve the new exclusions).  _on_results_loaded re-seeds the browse
        # page from the fresh teaser once the new total + cards land, so the full
        # grid honors the new exclusions — not just the teaser.
        if self._recipe_includes or self._recipe_excludes or self._stack.currentIndex() == 1:
            self._load_results()

    # ── Public helpers ────────────────────────────────────────────────────

    def seed_facet(self, facet_type: str, value: str) -> None:
        """Seed the recipe with one ingredient and land on the content-first view.

        Public entry point for the details-pane tag right-click → Recipe path.
        Replaces the current recipe with exactly one ingredient (``facet_type``
        = ``value``), selects that facet, and loads the matching content through
        the same recipe→shelf chokepoint a hand-built one-ingredient recipe uses
        (``count_channels_by_tag_facets`` / ``sample_channels_by_tag_facets``) —
        no parallel discover path.

        **Content-first (owner direction):** a preset-tag entry lands on the
        full-results browse page (stack page 1) showing *what matches the tag*,
        not the builder — "most users will want to just see whatever content
        matches the filter, not immediately go to build a filter."  The builder
        is one click away via the browse page's "Build recipe" affordance (the
        relabelled Back link → :meth:`_on_browse_back`), which returns to the
        constructor with this seeded ingredient already in the rail + cloud.

        The browse grid is empty until the async results land: once the teaser
        count + cards arrive, :meth:`_on_results_loaded` re-seeds the browse page
        (it already does so whenever page 1 is showing) — no parallel wiring.

        Must be called after the view is activated (``on_activate`` /
        ``switch_to_recipe_view``) so the async result slots render.

        Args:
            facet_type: The facet namespace (e.g. ``"genre"``, ``"collection"``).
            value: The single tag value to seed as an include ingredient.
        """
        # Replace any in-progress recipe with just this one ingredient.
        self._recipe_includes = {facet_type: {value}}
        self._recipe_excludes = {}
        # A seeded entry replaces the whole recipe → reset the rating band too.
        self._rating_range = tuple(_DEFAULT_RATING_RANGE)
        self._pantry.set_rating_range(*self._rating_range)
        self._selected_facet = facet_type
        # Drop any cross-facet pantry search so the seeded facet's cloud shows.
        self._search_query = ""
        self._search_results = []
        self._pantry.clear_filter()
        self._pantry.clear_match_counts()
        # Keep the selection through the async pantry load (preselect → no override).
        self._pantry.preselect_facet(facet_type)
        self._stage_hdr.setText(_facet_display(facet_type))
        # Render the rail instantly (so the builder is ready behind the browse page).
        self._render_rail(None)
        # Reset the teaser so the initial browse title shows a clean "0 matches"
        # instead of a stale count from a previous recipe.
        self._now_plating.load_results([], 0)
        # Content-first: land on the browse page and seed it with a title + empty
        # grid; _on_results_loaded fills it in once the count + cards arrive.
        self._stack.setCurrentIndex(1)
        self._browse.load(self._browse_title(), [])
        self._browse.set_has_more(False)
        self._load_cloud(facet_type)
        self._load_results()

    def clear_recipe(self) -> None:
        """Remove all ingredients and refresh the view.

        Resets the rating band to the full span (no filter) and clears the Pantry
        filter text box so the full facet list is restored.
        """
        self._recipe_includes.clear()
        self._recipe_excludes.clear()
        # Reset the rating ingredient too (silent slider restore — no re-query).
        self._rating_range = tuple(_DEFAULT_RATING_RANGE)
        self._pantry.set_rating_range(*self._rating_range)
        self._render_rail(0)
        self._now_plating.load_results([], 0)
        # Clear pantry filter so the full facet list is visible after a recipe reset.
        self._pantry.clear_filter()
        # Clear the center facet-value filter so all tag chips reappear.
        self._cloud.clear_filter()
        # Rebuild cloud with no states
        self._rebuild_cloud()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # The view's outer layout holds only a QStackedWidget:
        #   page 0 — the 2-column constructor (see below)
        #   page 1 — the full-results browse grid (reuses Discover's _BrowseView)
        # "Show all →" swaps to page 1; a preset-tag entry (seed_facet) also lands
        # on page 1 (content-first); the Recipe chip / browse Back returns to 0.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # --- Page 0: the 2-column constructor ---
        #   COLUMN 1 (col1 splitter, vertical): Pantry over the Tonight's-Recipe rail
        #   COLUMN 2 (col2): stage header over a vertical splitter of cloud / results
        # The two columns sit either side of the horizontal _main_splitter, so the
        # user can widen the pantry column or give the cloud/results more room; all
        # three splitters persist their sizes (see _init_splitter_sizes).
        constructor = QWidget()
        root = QVBoxLayout(constructor)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setChildrenCollapsible(False)

        # ── COLUMN 1 — Pantry (top) over Tonight's Recipe rail (bottom) ──
        self._col1_splitter = QSplitter(Qt.Orientation.Vertical)
        self._col1_splitter.setChildrenCollapsible(False)

        self._pantry = _PantrySidebar()
        self._pantry.facet_selected.connect(self._on_facet_selected)
        self._pantry.search_changed.connect(self._on_search_changed)
        self._pantry.rating_range_changed.connect(self._on_rating_range_changed)
        self._pantry.saved_recipe_selected.connect(self._on_saved_recipe_selected)
        self._pantry.saved_recipe_deleted.connect(self._on_saved_recipe_deleted)
        self._col1_splitter.addWidget(self._pantry)

        self._rail = _RecipeRail()
        self._rail.clear_btn.clicked.connect(self.clear_recipe)
        self._rail.save_btn.clicked.connect(self._on_save_recipe)
        self._rail.ingredient_remove_requested.connect(self._on_ingredient_remove)
        self._col1_splitter.addWidget(self._rail)

        self._main_splitter.addWidget(self._col1_splitter)

        # ── COLUMN 2 — stage header over a cloud / Now-Plating vertical splitter ──
        col2 = QWidget()
        col2_layout = QVBoxLayout(col2)
        col2_layout.setContentsMargins(16, 12, 16, 8)
        col2_layout.setSpacing(6)

        # Stage header (facet name label)
        self._stage_hdr = QLabel("Select a facet from The Pantry")
        self._stage_hdr.setStyleSheet(_theme.RECIPE_STAGE_HDR)
        col2_layout.addWidget(self._stage_hdr)

        self._content_splitter = QSplitter(Qt.Orientation.Vertical)
        self._content_splitter.setChildrenCollapsible(False)

        # Tag cloud (top) — wrapped in a scroll area so a facet with many values
        # scrolls within its splitter pane instead of squeezing the results grid.
        cloud_scroll = QScrollArea()
        cloud_scroll.setWidgetResizable(True)
        cloud_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cloud_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._cloud = WeightedTagCloud()
        self._cloud.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._cloud.tag_clicked.connect(self._on_tag_clicked)
        # Cross-facet search tags carry their own facet → add under that facet.
        self._cloud.tag_clicked_facet.connect(self._on_search_tag_clicked)
        cloud_scroll.setWidget(self._cloud)
        self._content_splitter.addWidget(cloud_scroll)

        # Now Plating grid (bottom) — real result cards (reuses Discover card
        # surface + flow layout).  Now a real half-height results area, not a strip.
        self._now_plating = _NowPlatingStrip(self._image_cache, self._config)
        self._now_plating.cardClicked.connect(self.channelSelected)
        self._now_plating.cardDoubleClicked.connect(self.playRequested)
        self._now_plating.cardMiddleClicked.connect(self.channelMiddleClicked)
        self._now_plating.cardContextMenu.connect(self.channelContextMenuRequested)
        self._now_plating.showAllRequested.connect(self._on_show_all)
        self._content_splitter.addWidget(self._now_plating)

        col2_layout.addWidget(self._content_splitter, stretch=1)
        self._main_splitter.addWidget(col2)

        # Column 2 grows first when the window widens (the pantry column stays lean).
        self._main_splitter.setStretchFactor(0, 0)
        self._main_splitter.setStretchFactor(1, 1)

        root.addWidget(self._main_splitter)

        # Constructor is page 0.
        self._stack.addWidget(constructor)

        # --- Page 1: the full-results browse grid (reuses Discover _BrowseView) ---
        from metatv.gui.discover_browse import _BrowseView

        self._browse = _BrowseView(self._image_cache, self._config)
        # The browse "back" link is the return-to-builder affordance here (unlike
        # Discover, where it returns to the shelf list): relabel it "Build recipe"
        # so a content-first entry (or a "Show all" drill-down) reads clearly as a
        # way into the recipe builder.  Discover keeps the default "← Back".
        self._browse.set_back_label(
            f"{_icons.recipe_icon} Build recipe",
            "Return to the recipe builder to refine ingredients",
        )
        self._browse.backRequested.connect(self._on_browse_back)
        self._browse.cardClicked.connect(self.channelSelected)
        self._browse.cardDoubleClicked.connect(self.playRequested)
        self._browse.cardMiddleClicked.connect(self.channelMiddleClicked)
        self._browse.cardContextMenu.connect(self.channelContextMenuRequested)
        # Lazy DB pagination: each near-bottom scroll asks for the next page.
        self._browse.loadMoreRequested.connect(self._load_more_see_all)
        # Filter-change: wire into the DB-level filter so every lazy page also
        # respects the filter (Bug D — previously only already-loaded cards were
        # filtered, and new pages appended unfiltered content below them).
        self._browse.filterChanged.connect(self._on_see_all_filter_changed)
        self._stack.addWidget(self._browse)

        # Restore persisted splitter sizes (with signals blocked), THEN connect the
        # save handlers — DESIGN.md: restore in __init__, connect handlers after.
        self._init_splitter_sizes()

    # ── Splitter geometry persistence ─────────────────────────────────────

    # Fallback splitter sizes (px) when Config has none yet — landscape-friendly
    # (wide content column, cloud getting a bit more than half of column 2).
    _DEFAULT_MAIN_SIZES: tuple[int, int] = (320, 940)          # [col1, col2]
    _DEFAULT_COL1_SIZES: tuple[int, int] = (440, 320)          # [pantry, rail]
    _DEFAULT_CONTENT_SIZES: tuple[int, int] = (360, 440)       # [cloud, now-plating]

    def _init_splitter_sizes(self) -> None:
        """Restore persisted splitter sizes, then connect the save handlers.

        Follows the DESIGN.md persistence pattern: the sizes are applied with the
        splitters' signals blocked (so restoring never fires a save), and only
        afterwards is each ``splitterMoved`` connected to the debounced save.
        Empty/absent config falls back to the landscape-friendly defaults above.
        """
        cfg = self._config
        specs = (
            (self._main_splitter, "recipe_main_splitter_sizes", self._DEFAULT_MAIN_SIZES),
            (self._col1_splitter, "recipe_col1_splitter_sizes", self._DEFAULT_COL1_SIZES),
            (self._content_splitter, "recipe_content_splitter_sizes", self._DEFAULT_CONTENT_SIZES),
        )
        for splitter, field, default in specs:
            saved = getattr(cfg, field, None)
            sizes = [int(x) for x in saved] if saved else list(default)
            splitter.blockSignals(True)
            splitter.setSizes(sizes)
            splitter.blockSignals(False)
        # Connect save handlers only after the restore pass.
        for splitter, _field, _default in specs:
            splitter.splitterMoved.connect(self._on_splitter_moved)

    def _on_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        """A splitter was dragged — (re)start the debounced config write."""
        self._layout_save_debounce.start()

    def _persist_splitter_sizes(self) -> None:
        """Write all three recipe splitter geometries to Config in one save."""
        cfg = self._config
        cfg.recipe_main_splitter_sizes = self._main_splitter.sizes()
        cfg.recipe_col1_splitter_sizes = self._col1_splitter.sizes()
        cfg.recipe_content_splitter_sizes = self._content_splitter.sizes()
        try:
            cfg.save()
        except Exception as e:  # never let a config write crash the UI
            logger.warning("RecipeView: could not persist splitter sizes: {}", e)

    # ── Data loading ──────────────────────────────────────────────────────

    def _global_exclusion_sets(self) -> tuple[set[str], set[str], set[str]]:
        """Resolve the user's Global Exclusions for the faceted queries.

        The control layer (DR-0007): we read ``Config`` here on the main thread
        and hand plain sets to the engine, which never touches Config itself.

        This delegates to the **same** ``filter_utils`` resolvers the main
        channel list uses (``main_window_channels.py`` ``_query_channels_page``)
        — a single chokepoint, so the recipe view never re-derives the union
        from raw config lists:

        - **excluded_prefixes** = ``get_active_category_filter(config)`` (the
          category blacklist, resolved to leaf prefix codes) ∪
          ``get_excluded_prefixes(config)`` (the explicit "Block [PREFIX]" set).
          ``get_active_category_filter`` is the one place the category-group
          selection is expanded into the leaf codes that match ``detected_prefix``
          / ``detected_region``; hand-rolling ``set(config.…_excluded_categories)``
          here bypassed that expansion, so checked groups never excluded anything.
        - **excluded_categories** = ``global_filter_excluded_user_categories``,
          matched against ``user_category``.

        Both ``filter_utils`` helpers are paused-aware: when
        ``global_filter_paused`` is True they yield no exclusions, so BOTH sets
        come back empty (everything reappears) — same as the main list.

        Returns:
            ``(excluded_prefixes, excluded_categories, excluded_content_types)`` —
            three ``set[str]``, all empty when global filtering is paused.  The
            third is the content-provenance layer (``content_type`` tag values,
            e.g. ``ai_generated``) resolved by
            :func:`~metatv.core.filter_utils.excluded_tag_content_types`, so the
            recipe pantry/cloud/YIELDS drop globally-excluded AI content too.
        """
        from metatv.core.filter_utils import (
            get_active_category_filter,
            get_excluded_prefixes,
            excluded_tag_content_types,
        )

        cfg = self._config
        if getattr(cfg, "global_filter_paused", False):
            return set(), set(), set()
        _cat_excluded, _ = get_active_category_filter(cfg)
        excluded_prefixes: set[str] = set(_cat_excluded or []) | get_excluded_prefixes(cfg)
        excluded_categories: set[str] = set(
            getattr(cfg, "global_filter_excluded_user_categories", []) or []
        )
        excluded_content_types: set[str] = excluded_tag_content_types(cfg)
        return excluded_prefixes, excluded_categories, excluded_content_types

    def _load_pantry(self) -> None:
        """Load facet summaries from the DB (off-thread)."""
        excl_prefixes, excl_categories, excl_content_types = self._global_exclusion_sets()
        self._run_query(
            lambda repos: repos.tags.get_facet_summary(
                excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
            ),
            self._on_pantry_loaded,
            token_ref=self._pantry_token,
            on_error=self._on_pantry_error,
        )

    def _on_pantry_loaded(self, summaries: list) -> None:
        """Main-thread slot: populate the pantry sidebar."""
        if not self._active:
            return
        self._pantry.load_facets(summaries)
        # If a facet was already selected before reload, keep it
        if self._pantry.selected_facet():
            self._on_facet_selected(self._pantry.selected_facet())

    def _on_pantry_error(self, exc: Exception) -> None:
        logger.error("RecipeView: pantry load failed: {}", exc)
        self._stage_hdr.setText("Couldn't load facets")

    def _load_cloud(self, facet_type: str) -> None:
        """Load tag counts for the selected facet (off-thread)."""
        excl_prefixes, excl_categories, excl_content_types = self._global_exclusion_sets()
        self._run_query(
            lambda repos: repos.tags.get_tag_counts_for_facet(
                facet_type,
                excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
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
        """Re-render the WeightedTagCloud with current tag counts + recipe state."""
        facet = self._selected_facet
        if facet is None:
            return

        meta = _FACET_META.get(facet)
        color = meta[1] if meta else _theme.COLOR_TEXT
        display = meta[0] if meta else facet.title()

        includes = self._recipe_includes.get(facet, set())
        excludes = self._recipe_excludes.get(facet, set())

        # Build items: (value, count, state) — state is "include", "exclude", or "none"
        items: list[tuple[str, int, str]] = []
        for dto in self._tag_counts:
            if dto.value in includes:
                state = "include"
            elif dto.value in excludes:
                state = "exclude"
            else:
                state = "none"
            items.append((dto.value, dto.channel_count, state))

        # content_type values are stored slugs — show friendly labels (identity
        # stays the slug for click/recipe state) via the single display chokepoint.
        display_map: dict[str, str] | None = None
        if facet == "content_type":
            from metatv.core.channel_name_utils import content_type_display
            display_map = {v: content_type_display(v) for v, _c, _s in items}

        self._cloud.set_tags(items, facet_color=color, facet_name=display,
                             display_map=display_map)

    # Result-grid card cap — a gridful of cards.  The bounded preview never
    # materialises the full set: a broad facet costs one SQL COUNT for YIELDS
    # plus a LIMIT slice of <= this many session-free ContentCards.
    _RESULTS_CARD_CAP: int = 60

    # Debounce window for _load_results: rapid successive tag clicks
    # coalesce into one DB round-trip while the rail/cloud update instantly.
    _DEBOUNCE_MS: int = 300

    # "Show all →" lazy-pagination page size — how many cards each near-bottom
    # scroll fetches+appends from the DB.  There is NO hard cap: paging continues
    # until offset >= total, so the browse grid can reach the full match set.
    _SEE_ALL_PAGE: int = 60

    def _load_results(self) -> None:
        """Load the YIELDS count + a bounded set of result cards (off-thread)."""
        # Snapshot recipe state for the lambda (closed over)
        includes = {k: set(v) for k, v in self._recipe_includes.items() if v}
        excludes = {k: set(v) for k, v in self._recipe_excludes.items() if v}
        excl_prefixes, excl_categories, excl_content_types = self._global_exclusion_sets()
        rating_range = self._rating_range_arg()
        cap = self._RESULTS_CARD_CAP

        def _query(repos):
            # Count stays entirely in SQL — a broad facet (e.g. language:English
            # ≈ 170k channels) costs one COUNT, never a 170k-id Python set.  The
            # card sample is a bounded LIMIT slice mapped to session-free
            # ContentCards.  Both are scoped to visible channels on active
            # sources via excluded_provider_ids AND to the user's Global
            # Exclusions, so the shelf agrees with YIELDS and never leaks
            # disabled-source or globally-banished channels.
            hidden = repos.providers.get_hidden_provider_ids()
            total = repos.tags.count_channels_by_tag_facets(
                includes=includes,
                excludes=excludes,
                excluded_provider_ids=hidden,
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
                rating_range=rating_range,
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
                rating_range=rating_range,
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
        """Main-thread slot: update 'Now Plating' shelf and recipe rail YIELDS."""
        if not self._active:
            return
        cards, total = payload
        self._now_plating.load_results(cards, total)
        # Update rail with current recipe + count
        self._render_rail(total)
        # If the "Show all" browse page is showing, the recipe (or Global
        # Exclusions) just changed underneath it — re-seed it from this fresh
        # teaser so the full-page pagination reflects the new recipe.  Doing this
        # here (rather than in reload()) means the browse re-seeds AFTER the new
        # teaser cards + total have actually landed, never from stale state.
        if self._stack.currentIndex() == 1:
            self._reseed_see_all()

    def _on_results_error(self, exc: Exception) -> None:
        logger.error("RecipeView: results load failed: {}", exc)

    # "Show all →" full-results browse drill-down + lazy DB pagination live
    # in _RecipeBrowseMixin (recipe_browse_mixin.py), mixed into this class.

    # ── Event handlers ────────────────────────────────────────────────────

    def _on_facet_selected(self, facet_type: str) -> None:
        """User clicked a facet row in the Pantry."""
        self._selected_facet = facet_type
        meta = _FACET_META.get(facet_type)
        display = meta[0] if meta else facet_type.title()
        self._stage_hdr.setText(display)
        self._tag_counts = []
        self._load_cloud(facet_type)

    def _cycle_tag(self, facet: str | None, value: str) -> None:
        """Cycle ``(facet, value)`` through none → include → exclude → none.

        The single ingredient-mutation chokepoint shared by the single-facet
        cloud (:meth:`_on_tag_clicked`) and the cross-facet search cloud
        (:meth:`_on_search_tag_clicked`).  Mutates recipe state, renders the rail
        instantly, and fires the debounced results load — but leaves the *cloud*
        re-render to the caller (each mode redraws a different cloud).
        """
        if facet is None:
            return

        inc = self._recipe_includes.setdefault(facet, set())
        exc = self._recipe_excludes.setdefault(facet, set())

        if value in inc:
            # include → exclude
            inc.discard(value)
            exc.add(value)
            logger.debug("RecipeView: {} {} → exclude", facet, value)
        elif value in exc:
            # exclude → none
            exc.discard(value)
            logger.debug("RecipeView: {} {} → none", facet, value)
        else:
            # none → include
            inc.add(value)
            logger.debug("RecipeView: {} {} → include", facet, value)

        # Prune empty sets
        if not inc:
            self._recipe_includes.pop(facet, None)
        if not exc:
            self._recipe_excludes.pop(facet, None)

        # Re-render rail immediately (pure in-memory — no DB wait), then fire the
        # debounced results load so rapid clicks coalesce.
        self._render_rail(None)
        self._results_debounce.start()

    def _on_tag_clicked(self, value: str) -> None:
        """Single-facet cloud click → cycle the value under the selected facet."""
        facet = self._selected_facet
        if facet is None:
            return
        self._cycle_tag(facet, value)
        self._rebuild_cloud()

    def _on_search_tag_clicked(self, facet_type: str, value: str) -> None:
        """Cross-facet search cloud click → cycle the value under ITS own facet.

        Reuses the same :meth:`_cycle_tag` include/exclude path as the single-facet
        cloud (never a parallel add), then re-renders the search cloud so the
        clicked tag immediately shows its new include/exclude mark.
        """
        self._cycle_tag(facet_type, value)
        if self._search_query:
            self._render_search_cloud(self._search_results)
        else:
            self._rebuild_cloud()

    # ── Cross-facet Pantry search ─────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        """Pantry search text settled — search across facets or restore the facet cloud."""
        self._search_query = text.strip()
        if not self._search_query:
            # Empty search → today's behaviour: drop badges, show selected facet.
            self._search_results = []
            self._pantry.clear_match_counts()
            facet = self._selected_facet
            if facet is not None:
                self._stage_hdr.setText(_facet_display(facet))
            self._rebuild_cloud()
            return
        self._load_search(self._search_query)

    def _load_search(self, query: str) -> None:
        """Run the cross-facet tag search off-thread via the async seam."""
        excl_prefixes, excl_categories, excl_content_types = self._global_exclusion_sets()
        self._run_query(
            lambda repos: repos.tags.search_tag_values_across_facets(
                query,
                excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
                excluded_prefixes=excl_prefixes,
                excluded_categories=excl_categories,
                excluded_tag_content_types=excl_content_types,
            ),
            self._on_search_loaded,
            token_ref=self._search_token,
            on_error=self._on_search_error,
        )

    def _on_search_loaded(self, results: list) -> None:
        """Main-thread slot: fill the cloud with cross-facet matches + set badges."""
        if not self._active:
            return
        # A late result from a stale query (now cleared) must not repaint.
        if not self._search_query:
            return
        self._search_results = results
        self._render_search_cloud(results)
        # Per-facet match badge: count distinct matching values per facet.
        counts: dict[str, int] = {}
        for dto in results:
            counts[dto.facet_type] = counts.get(dto.facet_type, 0) + 1
        self._pantry.set_match_counts(counts)
        self._stage_hdr.setText(f'Matches for "{self._search_query}"')

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
            # content_type slugs get a friendly label; identity stays the slug.
            if ftype == "content_type":
                display_map[dto.value] = content_type_display(dto.value)
        self._cloud.set_multi_facet_tags(
            items, facet_name=f'"{self._search_query}"',
            display_map=display_map or None,
        )

    def _on_search_error(self, exc: Exception) -> None:
        logger.error("RecipeView: tag search failed: {}", exc)

    def _on_ingredient_remove(self, facet_type: str, value: str) -> None:
        """Remove an ingredient chip from the recipe rail (cycles state → none)."""
        self._recipe_includes.get(facet_type, set()).discard(value)
        self._recipe_excludes.get(facet_type, set()).discard(value)

        # Prune empty sets
        if not self._recipe_includes.get(facet_type):
            self._recipe_includes.pop(facet_type, None)
        if not self._recipe_excludes.get(facet_type):
            self._recipe_excludes.pop(facet_type, None)

        # Render rail + cloud immediately; debounce the expensive DB count.
        self._render_rail(None)
        # Re-render whichever cloud is showing so the removed tag loses its mark.
        if self._search_query:
            self._render_search_cloud(self._search_results)
        else:
            self._rebuild_cloud()
        self._results_debounce.start()

    # ── Rating ingredient + rail render chokepoint ────────────────────────

    def _rating_range_arg(self) -> tuple[float, float] | None:
        """Return the active rating band, or ``None`` when it imposes no filter.

        The single resolver both the rail menu line and every faceted query use:
        a full 0–10 span becomes ``None`` so no rating EXISTS is added and no
        "RATING" line renders.
        """
        return None if _rating_range_is_full(self._rating_range) else tuple(self._rating_range)

    def _render_rail(self, match_count: int | None) -> None:
        """Re-render the recipe card (rail) with current state + the rating band.

        Single chokepoint for rail updates so the RATING menu line and the
        Save-button enabled state always reflect the live recipe.
        """
        self._rail.update_recipe(
            self._recipe_includes,
            self._recipe_excludes,
            match_count,
            rating_range=self._rating_range_arg(),
        )
        has_recipe = bool(self._recipe_includes or self._recipe_excludes) or (
            self._rating_range_arg() is not None
        )
        self._rail.save_btn.setEnabled(has_recipe)

    def _on_rating_range_changed(self, lo: float, hi: float) -> None:
        """Rating slider moved → update the band, rail, and (debounced) results."""
        self._rating_range = (lo, hi)
        # Instant rail feedback (RATING line + Save enabled); coalesce the count.
        self._render_rail(None)
        self._results_debounce.start()

    # ── Saved recipes ─────────────────────────────────────────────────────

    def _load_saved_recipes(self) -> None:
        """Refresh the pantry's Saved Recipes list from Config."""
        self._pantry.load_saved_recipes(list(getattr(self._config, "recipe_saved", []) or []))

    def _saved_recipe_name(self) -> str:
        """Build a display name for the current recipe (rating-only aware)."""
        if self._recipe_includes or self._recipe_excludes:
            return _generate_recipe_name(self._recipe_includes, self._recipe_excludes)
        # Rating-only recipe → name from the band.
        return f"Rated {_format_rating_range(self._rating_range[0], self._rating_range[1])}"

    def _on_save_recipe(self) -> None:
        """Persist the current recipe (incl. the rating band) to Config."""
        if not (self._recipe_includes or self._recipe_excludes) and self._rating_range_arg() is None:
            return  # nothing to save
        payload = _serialize_recipe(
            self._recipe_includes,
            self._recipe_excludes,
            self._rating_range_arg(),
            name=self._saved_recipe_name(),
        )
        saved = list(getattr(self._config, "recipe_saved", []) or [])
        saved.append(payload)
        self._config.recipe_saved = saved
        try:
            self._config.save()
        except Exception as e:  # never let a config write crash the UI
            logger.warning("RecipeView: could not save recipe: {}", e)
        logger.debug("RecipeView: saved recipe {!r}", payload.get("name"))
        self._load_saved_recipes()

    def _apply_recipe_state(
        self,
        includes: dict[str, set[str]],
        excludes: dict[str, set[str]],
        rating_range: tuple[float, float],
    ) -> None:
        """Load a full recipe state into the builder (used by saved-recipe load).

        Replaces the in-progress recipe, restores the rating slider silently, and
        re-renders the rail + cloud + results through the existing chokepoints.
        """
        self._recipe_includes = {k: set(v) for k, v in includes.items() if v}
        self._recipe_excludes = {k: set(v) for k, v in excludes.items() if v}
        self._rating_range = tuple(rating_range)
        self._pantry.set_rating_range(*self._rating_range)
        # Drop any cross-facet search so the selected-facet cloud shows.
        self._search_query = ""
        self._search_results = []
        self._pantry.clear_filter()
        self._pantry.clear_match_counts()
        self._render_rail(None)
        # Re-mark the currently-showing cloud so loaded ingredients read as active.
        if self._selected_facet is not None:
            self._rebuild_cloud()
        self._load_results()

    def _on_saved_recipe_selected(self, name: str) -> None:
        """A saved-recipe row was clicked → load it into the builder."""
        for rec in (getattr(self._config, "recipe_saved", []) or []):
            if str(rec.get("name")) == name:
                includes, excludes, rating_range = _deserialize_recipe(rec)
                self._apply_recipe_state(includes, excludes, rating_range)
                # Content-first entries may be on the browse page — land on the
                # builder so the freshly-loaded recipe is visible.
                self._stack.setCurrentIndex(0)
                return

    def _on_saved_recipe_deleted(self, name: str) -> None:
        """A saved-recipe row's × was clicked → remove it from Config."""
        saved = list(getattr(self._config, "recipe_saved", []) or [])
        for i, rec in enumerate(saved):
            if str(rec.get("name")) == name:
                del saved[i]
                break
        self._config.recipe_saved = saved
        try:
            self._config.save()
        except Exception as e:  # never let a config write crash the UI
            logger.warning("RecipeView: could not delete saved recipe: {}", e)
        self._load_saved_recipes()

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

    @property
    def rating_range(self) -> tuple[float, float]:
        """Current rating band ``(min, max)`` (read-only for tests)."""
        return self._rating_range
