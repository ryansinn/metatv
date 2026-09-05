"""PERF-16 — the Similar-titles lightbox and the Explore trail map, built LAZILY.

``_OverlaysMixin`` is mixed into :class:`~metatv.gui.main_window.MainWindow`
(main_window.py's class bases), same shape as every other ``main_window_*.py``
mixin: its methods read/write ``self.*`` attributes MainWindow's
``__init__``/``setup_ui`` already establish (``self.config``, ``self.db``,
``self.image_cache``, ``self.metadata_manager``, ``self._poster_lightbox``,
``self._register_cleanable``).

Both overlays used to be built eagerly inside ``setup_ui`` — a hidden QWidget
overlay paid for at every launch whether or not the user ever opens Similar
Titles or Explore (``similar_lightbox_card._build_header`` alone sampled at
819 ms). ``_ensure_similar_lightbox``/``_ensure_trail_map`` are the single
construction seam each overlay now goes through: first call builds it (same
constructor args, same signal connects, same ``_register_cleanable`` call the
eager version made at construction time — the cleanup registry is a plain
list appended to, so registering after ``setup_ui`` has already run is no
different from registering during it), stores it on ``self``, and returns it;
every later call — including the first — returns that same instance.

``_show_similar_lightbox``/``_show_trail_map``/``_connect_trail_map_signals``
moved here alongside their builders (verbatim, except the first two now call
the ensure-builder before touching the widget) since they are the overlays'
other callers-in. Every OTHER reader of ``self._lightbox``/``self._trail_map``
that can run before either is ever opened (the resize handler, the trail-map
"open details"/"make recipe" handlers) reads via ``self.__dict__.get(...)``
and no-ops when absent — never ``hasattr``, which on a ``__new__``'d skeleton
host raises ``RuntimeError`` (not ``AttributeError``) that a bool test cannot
absorb (CLAUDE.md).
"""

from __future__ import annotations


class _OverlaysMixin:
    """Mixin: lazy construction of the Similar-titles lightbox and trail map."""

    def _ensure_similar_lightbox(self):
        """Return the Similar-titles lightbox, building + wiring it on first use.

        Returns:
            The cached-or-new ``SimilarTitleLightbox``.
        """
        lightbox = self.__dict__.get("_lightbox")
        if lightbox is not None:
            return lightbox

        # Similar titles lightbox — overlay child widget, hidden by default
        from metatv.gui.similar_lightbox import SimilarTitleLightbox
        self._lightbox = SimilarTitleLightbox(
            self, self.config, self.image_cache, self.db, self.metadata_manager
        )
        self._lightbox.play_requested.connect(self.play_channel_by_id)
        self._lightbox.queue_toggled.connect(self._on_details_queue_toggle)
        self._lightbox.favorite_toggled.connect(self.toggle_favorite_by_id)
        self._lightbox.hide_requested.connect(self._on_hide_from_details_pane)
        self._lightbox.rating_requested.connect(self._toggle_rating)
        self._lightbox.suppression_requested.connect(self._on_suppression_requested)
        self._lightbox.explore_requested.connect(self._show_trail_map)
        # Registered here, beside construction, exactly as the trail map below
        # is. It owns a ThreadPoolExecutor and was the one widget that owned a
        # pool with nothing stopping it.
        self._register_cleanable("lightbox", self._lightbox.shutdown)
        # The lens strip's "See all in Search" — the only way a metadata click
        # inside the overlay reaches the channel list, and it goes through the
        # same strict context-filter chokepoint a details-pane click uses.
        self._lightbox.lens_search_requested.connect(self._on_lightbox_lens_search)
        # A click on the Similar-Titles lightbox poster enlarges it via the SAME
        # overlay the details pane (poster_enlarged) and trail-map feed.
        self._lightbox.poster_expand_requested.connect(self._poster_lightbox.show_pixmap)
        return self._lightbox

    def _ensure_trail_map(self):
        """Return the Explore trail-map, building + wiring it on first use.

        Returns:
            The cached-or-new ``TrailMapView``.
        """
        trail_map = self.__dict__.get("_trail_map")
        if trail_map is not None:
            return trail_map

        # Explore trail-map — cascading-columns adjacency browser (opened from the
        # lightbox's Explore button; seeded with the walked nav trail).  Relays the
        # same per-title intents to the existing host handlers the lightbox/details
        # pane use (single chokepoint per action).
        from metatv.gui.trail_map_view import TrailMapView
        self._trail_map = TrailMapView(
            self, self.config, self.image_cache, self.db, self.metadata_manager
        )
        self._connect_trail_map_signals(self._trail_map)
        self._register_cleanable("trail_map", self._trail_map.shutdown)
        return self._trail_map

    def _show_similar_lightbox(
        self,
        channel_ids: list,
        index: int,
        origin_title: str,
    ) -> None:
        lightbox = self._ensure_similar_lightbox()
        lightbox.resize(self.size())
        lightbox.show_preview(channel_ids, index, origin_title)

    def _connect_trail_map_signals(self, tm) -> None:
        """Wire a TrailMapView's per-title intents to the shared host handlers.

        One seam for BOTH trail-map instances (the lightbox Explore overlay and the
        embedded Full Watch-History view) so every action routes through the same
        canonical play/queue/favorite/rating handlers (single chokepoint).
        """
        tm.play_requested.connect(self.play_channel_by_id)
        tm.resume_requested.connect(self.play_channel_resume_by_id)
        tm.queue_toggled.connect(self._on_details_queue_toggle)
        tm.favorite_toggled.connect(self.toggle_favorite_by_id)
        tm.rating_requested.connect(self._toggle_rating)
        tm.suppression_requested.connect(self._on_suppression_requested)
        tm.watched_toggled.connect(self._on_details_watched_toggled)
        tm.open_details_requested.connect(self._on_trail_open_details)
        tm.recipe_requested.connect(self._on_trail_recipe_requested)
        tm.poster_expand_requested.connect(self._poster_lightbox.show_pixmap)

    def _show_trail_map(self, seed_ids: list) -> None:
        """Open the Explore trail-map seeded with the lightbox's walked trail.

        The lightbox is dismissed so the trail-map is the single active surface;
        both are overlays over the same window.
        """
        lightbox = self.__dict__.get("_lightbox")
        if lightbox is not None and lightbox.isVisible():
            lightbox.hide()
        trail_map = self._ensure_trail_map()
        trail_map.resize(self.size())
        trail_map.open(list(seed_ids))
