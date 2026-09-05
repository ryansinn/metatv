"""Discover view — background loader workers (_ShelfData, _LoaderWorker, _SeeAllWorker).

Module-level shared helpers
----------------------------
``determine_zone(shelf_key, *, pinned, expanded, collapsed, hidden,
                 default_expanded, first_launch) -> str``
    Single source of truth for zone assignment.  Imported by both
    ``_LoaderWorker`` (to decide whether to fetch cards) and
    ``DiscoverView._determine_zone`` (to route incoming shelf data).

``fetch_cards_for_key(session, config, shelf_key, limit) -> list[ContentCard]``
    Single dispatcher for "get the cards for a shelf key".  Called by
    ``_LoaderWorker`` (pinned/expanded shelves), ``_SeeAllWorker``, and
    ``_ShelfCardsWorker`` (lazy-expand fetch).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

from metatv.core.visibility_resolver import (
    dead_signal_streak_floor as _dead_signal_streak_floor,
)
from metatv.core.config import Config
from metatv.core.database import Database
from metatv.core.discovery_engine import ContentCard
from metatv.gui import icons as _icons

if TYPE_CHECKING:
    pass

_SEE_ALL_LIMIT = 500  # max cards fetched for the "See All" browse grid

# Zone constants (mirrored in discover_view to avoid circular import)
_ZONE_PINNED    = "pinned"
_ZONE_EXPANDED  = "expanded"
_ZONE_COLLAPSED = "collapsed"


# ---------------------------------------------------------------------------
# Shared zone-decision helper  (#2 chokepoint)
# ---------------------------------------------------------------------------

def determine_zone(
    shelf_key: str,
    *,
    pinned: set[str],
    expanded: set[str],
    collapsed: set[str],
    hidden: set[str],
    default_expanded: set[str],
    first_launch: bool,
) -> str:
    """Return the zone string for *shelf_key* given the current config state.

    This is the *single* source of truth used by both the loader worker (to
    decide whether to query cards) and DiscoverView (to route shelf widgets).

    Args:
        shelf_key:        The canonical key (e.g. ``"genre:Action"``).
        pinned:           Keys currently in the pinned zone.
        expanded:         Keys currently in the expanded zone.
        collapsed:        Keys currently in the collapsed zone.
        hidden:           Keys currently hidden (not shown at all).
        default_expanded: Keys that are expanded on first launch.
        first_launch:     True when no zone config exists yet.

    Returns:
        One of ``"pinned"``, ``"expanded"``, or ``"collapsed"``.
        (Hidden keys are filtered out before calling this; the loader skips
        them entirely.)
    """
    if shelf_key in pinned:
        return _ZONE_PINNED
    if shelf_key in expanded:
        return _ZONE_EXPANDED
    if shelf_key in collapsed:
        return _ZONE_COLLAPSED
    # No explicit config → fall back to first-launch defaults.
    if first_launch:
        return _ZONE_EXPANDED if shelf_key in default_expanded else _ZONE_COLLAPSED
    return _ZONE_COLLAPSED


# ---------------------------------------------------------------------------
# Shared card-fetch dispatcher  (#3 chokepoint)
# ---------------------------------------------------------------------------

def fetch_cards_for_key(
    session,
    config: Config,
    shelf_key: str,
    limit: int,
    *,
    sk: dict,
    fk: dict,
    af: dict,
    ek: dict,
) -> list[ContentCard]:
    """Fetch and return the card list for *shelf_key* at the given *limit*.

    This is the *single* dispatcher used by ``_LoaderWorker`` (eager shelves),
    ``_SeeAllWorker`` (browse drill-down), and ``_ShelfCardsWorker``
    (lazy-expand on-demand fetch).

    All four kwargs dicts (``sk``, ``fk``, ``af``, ``ek``) mirror the
    pattern already used throughout the workers — status, filter, adult, and
    provider-exclusion kwargs respectively.  Pass the pre-built dicts from
    the calling worker.

    Returns an empty list for unknown keys.
    """
    from metatv.core.discovery_engine import (
        get_recently_added, get_top_rated, get_by_genre,
        get_by_decade, get_by_actor, get_by_user_category, get_by_collection,
        get_recommended,
    )

    if shelf_key == "recommended":
        # Takes no sk/fk/af/ek: every exclusion axis comes from
        # preference_engine.recommendation_scope, which is the one place that
        # knows what a recommendation may contain. Passing the shelf kwargs too
        # would be a second, competing answer to the same question.
        return get_recommended(session, config, limit=limit)

    if shelf_key == "recently_added":
        return get_recently_added(session, limit=limit, **sk, **fk, **af, **ek)
    if shelf_key == "top_movies":
        return get_top_rated(session, "movie", limit=limit, **sk, **fk, **af, **ek)
    if shelf_key == "top_series":
        return get_top_rated(session, "series", limit=limit, **sk, **fk, **af, **ek)
    if shelf_key.startswith("genre:"):
        return get_by_genre(session, shelf_key[6:], limit=limit, **sk, **fk, **af, **ek)
    if shelf_key.startswith("decade:"):
        return get_by_decade(session, int(shelf_key[7:]), limit=limit, **sk, **fk, **af, **ek)
    if shelf_key.startswith("actor:"):
        return get_by_actor(session, shelf_key[6:], limit=limit, **sk, **fk, **af, **ek)
    if shelf_key.startswith("user_cat:"):
        cat_name = shelf_key[9:]
        return get_by_user_category(session, cat_name, limit=limit, **sk, **fk, **af, **ek)
    if shelf_key.startswith("collection:"):
        return get_by_collection(session, shelf_key[11:], limit=limit, **sk, **fk, **af, **ek)
    if shelf_key.startswith(_RECIPE_PREFIX):
        return _cards_for_saved_recipe(
            session, config, shelf_key[len(_RECIPE_PREFIX):], limit,
        )
    return []


#: Shelf-key namespace for a saved recipe, mirroring ``user_cat:``.
_RECIPE_PREFIX = "recipe:"


def _cards_for_saved_recipe(session, config: Config, name: str,
                            limit: int) -> list[ContentCard]:
    """Cards matching the saved recipe called *name*.

    Deliberately NOT routed through the ``sk``/``fk``/``af``/``ek`` kwargs the
    other shelves use. A recipe is a facet query, and the one that already
    answers it is ``TagRepository.sample_channels_by_tag_facets`` — the same
    call the Recipe view's own results shelf makes. Reusing it is what
    guarantees a recipe shows the SAME titles on both screens; a second query
    assembled from the shelf kwargs would drift the first time either changed.

    The exclusion sets come from ``filter_utils.global_exclusion_sets``, which
    is also what the Recipe view resolves — including the excluded-user-category
    axis the shelf kwargs fold into ``excluded_prefixes`` and cannot express
    separately.

    Args:
        session: Open DB session.
        config: The application Config (holds ``saved_recipes``).
        name: The recipe's name, from the shelf key.
        limit: Card cap.

    Returns:
        Matching cards, or an empty list when the recipe no longer exists.
    """
    from metatv.core.filter_utils import global_exclusion_sets
    from metatv.core.repositories import RepositoryFactory

    recipe = next(
        (r for r in (getattr(config, "saved_recipes", None) or [])
         if isinstance(r, dict) and r.get("name") == name),
        None,
    )
    if recipe is None:
        return []

    includes = {k: set(v) for k, v in (recipe.get("includes") or {}).items() if v}
    excludes = {k: set(v) for k, v in (recipe.get("excludes") or {}).items() if v}
    if not includes and not excludes:
        return []

    prefixes, categories, content_types, keywords = global_exclusion_sets(config)
    repos = RepositoryFactory(session)
    return repos.tags.sample_channels_by_tag_facets(
        includes=includes,
        excludes=excludes,
        # NOT ``or None``. The sampler applies EVERY global-exclusion axis
        # inside a block gated on ``excluded_provider_ids is not None``, so
        # passing None when no source happens to be hidden silently disables
        # the prefix, category, content-type and keyword exclusions too. An
        # empty list is the correct "nothing hidden" value, and is what the
        # Recipe view passes.
        excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
        excluded_prefixes=prefixes or None,
        excluded_categories=categories or None,
        excluded_tag_content_types=content_types or None,
        excluded_keywords=keywords or None,
        limit=limit,
        collapse_variants=True,
    )


# ---------------------------------------------------------------------------
# Shelf-config canonicalization  (#4 chokepoint — moved out of DiscoverView
# so its own file, pinned at its code_health_baseline ceiling, had room for
# the PERF-17 chunked-build lifecycle wiring instead)
# ---------------------------------------------------------------------------

def normalize_shelf_config(config: Config) -> None:
    """Canonicalize HTML-entity-encoded genre shelf keys in the persisted config.

    Before bug A was fixed, provider genre strings like "Action &amp; Adventure"
    were stored as-is, creating shelf keys like "genre:Action &amp; Adventure".
    After the fix, get_all_genres() returns canonical "Action & Adventure" which
    produces "genre:Action & Adventure" — a different key.  The two variants
    would both appear in the zone lists, causing the same shelf to show twice.

    Called once by ``DiscoverView.on_activate()`` before the first load, and
    sanitizes all four discover_*_shelves lists by:
      1. Unescaping HTML entities in any "genre:*" key.
      2. De-duplicating while preserving original order (first occurrence wins
         so the user's pinned/expanded/collapsed/order state is kept).

    The config is saved only if any list changed.

    Args:
        config: The application Config to normalize in place.
    """
    import html as _html

    def _clean(key: str) -> str:
        if key.startswith("genre:"):
            return "genre:" + _html.unescape(key[6:])
        return key

    def _dedup_ordered(lst: list) -> list:
        seen: set = set()
        out: list = []
        for item in lst:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    changed = False
    for attr in ("discover_pinned_shelves", "discover_expanded_shelves",
                 "discover_collapsed_shelves", "discover_hidden_shelves",
                 "discover_shelf_order"):
        raw: list = list(getattr(config, attr, []))
        normalized = _dedup_ordered([_clean(k) for k in raw])
        if normalized != raw:
            setattr(config, attr, normalized)
            changed = True
    if changed:
        logger.debug("DiscoverView: migrated HTML-entity genre keys in shelf config")
        config.save()


# ---------------------------------------------------------------------------
# Data transfer object
# ---------------------------------------------------------------------------

class _ShelfData:
    __slots__ = ("title", "shelf_key", "cards", "is_featured_actor",
                 "is_user_category", "header_only")

    def __init__(self, title: str, shelf_key: str, cards: list[ContentCard],
                 is_featured_actor: bool = False,
                 is_user_category: bool = False,
                 header_only: bool = False) -> None:
        self.title = title
        self.shelf_key = shelf_key
        self.cards = cards
        self.is_featured_actor = is_featured_actor
        self.is_user_category = is_user_category
        self.header_only = header_only


# ---------------------------------------------------------------------------
# Zone snapshot  (plain data; thread-safe to pass from main → worker)
# ---------------------------------------------------------------------------

@dataclass
class _ZoneSnapshot:
    """Immutable snapshot of the zone config passed from DiscoverView to workers."""
    pinned: frozenset[str] = field(default_factory=frozenset)
    expanded: frozenset[str] = field(default_factory=frozenset)
    collapsed: frozenset[str] = field(default_factory=frozenset)
    hidden: frozenset[str] = field(default_factory=frozenset)
    default_expanded: frozenset[str] = field(default_factory=frozenset)
    first_launch: bool = False


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class _SeeAllWorker(QObject):
    """Fetch the full item set for a shelf — runs in a background thread."""

    ready = pyqtSignal(str, list)  # (shelf_key, cards)

    def __init__(self, db: Database, config: Config, shelf_key: str) -> None:
        super().__init__()
        self._db = db
        self._config = config
        self._shelf_key = shelf_key
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation — suppresses the ``ready`` emit into a torn-down view."""
        self._cancelled = True

    def run(self) -> None:
        from metatv.core.discovery_engine import build_status_sets, build_adult_filter
        from metatv.core.filter_utils import (
            get_active_category_filter, get_excluded_prefixes, excluded_tag_content_types,
            keyword_exclusion_list,
        )
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            ss = build_status_sets(session)
            cat_excluded, include_uncategorized = get_active_category_filter(self._config)
            per_prefix = get_excluded_prefixes(self._config)
            all_excl = list(set(cat_excluded or []) | per_prefix)
            fk = {"excluded_prefixes": all_excl or None,
                      "include_uncategorized": include_uncategorized,
                      # Content-provenance layer (paused-aware): hide AI content everywhere.
                      "excluded_content_types": excluded_tag_content_types(self._config) or None,
                      "excluded_keywords": keyword_exclusion_list(self._config) or None}
            sk = {"fav_ids": ss.fav_ids, "queue_ids": ss.queue_ids,
                      "watched_ids": ss.watched_ids, "liked_ids": ss.liked_ids,
                      "progress_map": ss.progress_map}
            adult_mode, force_adult_ids = build_adult_filter(session, self._config)
            af = {"adult_mode": adult_mode, "force_adult_provider_ids": force_adult_ids or None}
            # Canonical provider scoping: hide inactive + expired sources.
            _excl_ids = RepositoryFactory(session).providers.get_hidden_provider_ids()
            ek = {"excluded_provider_ids": _excl_ids or None,
                  "dead_signal_streak_floor": _dead_signal_streak_floor(self._config)}

            cards = fetch_cards_for_key(
                session, self._config, self._shelf_key, _SEE_ALL_LIMIT,
                sk=sk, fk=fk, af=af, ek=ek,
            )
        except Exception:
            logger.exception("SeeAllWorker error for %s", self._shelf_key)
            cards = []
        finally:
            session.close()
        if not self._cancelled:
            self.ready.emit(self._shelf_key, cards)


class _ShelfCardsWorker(QObject):
    """Fetch cards for a single collapsed shelf on lazy-expand.

    Emits ``ready(shelf_key, cards)`` on success — *cards* may legitimately be
    an empty list (a shelf with nothing matching after filters).  Emits
    ``error(shelf_key, message)`` when the query itself raised, so the view can
    render a distinct error row instead of a silently-empty shelf (never
    conflate "genuinely empty" with "the fetch failed" — CLAUDE.md's
    async-background-DB-reads rule).
    """

    ready = pyqtSignal(str, list)  # (shelf_key, cards)
    error = pyqtSignal(str, str)   # (shelf_key, message)

    def __init__(self, db: Database, config: Config, shelf_key: str,
                 limit: int = 30) -> None:
        super().__init__()
        self._db = db
        self._config = config
        self._shelf_key = shelf_key
        self._limit = limit
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from metatv.core.discovery_engine import build_status_sets, build_adult_filter
        from metatv.core.filter_utils import (
            get_active_category_filter, get_excluded_prefixes, excluded_tag_content_types,
            keyword_exclusion_list,
        )
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        cards: list | None = None
        error_message: str | None = None
        try:
            ss = build_status_sets(session)
            cat_excluded, include_uncategorized = get_active_category_filter(self._config)
            per_prefix = get_excluded_prefixes(self._config)
            all_excl = list(set(cat_excluded or []) | per_prefix)
            fk = {"excluded_prefixes": all_excl or None,
                      "include_uncategorized": include_uncategorized,
                      # Content-provenance layer (paused-aware): hide AI content everywhere.
                      "excluded_content_types": excluded_tag_content_types(self._config) or None,
                      "excluded_keywords": keyword_exclusion_list(self._config) or None}
            sk = {"fav_ids": ss.fav_ids, "queue_ids": ss.queue_ids,
                      "watched_ids": ss.watched_ids, "liked_ids": ss.liked_ids,
                      "progress_map": ss.progress_map}
            adult_mode, force_adult_ids = build_adult_filter(session, self._config)
            af = {"adult_mode": adult_mode, "force_adult_provider_ids": force_adult_ids or None}
            _excl_ids = RepositoryFactory(session).providers.get_hidden_provider_ids()
            ek = {"excluded_provider_ids": _excl_ids or None,
                  "dead_signal_streak_floor": _dead_signal_streak_floor(self._config)}

            cards = fetch_cards_for_key(
                session, self._config, self._shelf_key, self._limit,
                sk=sk, fk=fk, af=af, ek=ek,
            )
        except Exception as exc:
            logger.exception("ShelfCardsWorker error for %s", self._shelf_key)
            error_message = str(exc) or exc.__class__.__name__
        finally:
            session.close()
        if self._cancelled:
            return
        if cards is not None:
            self.ready.emit(self._shelf_key, cards)
        else:
            self.error.emit(self._shelf_key, error_message or "Unknown error")


class _LoaderWorker(QObject):
    shelfReady = pyqtSignal(object)   # _ShelfData
    finished   = pyqtSignal()

    def __init__(self, db: Database, config: Config,
                 zone_snapshot: _ZoneSnapshot | None = None) -> None:
        super().__init__()
        self._db = db
        self._config = config
        self._zone_snapshot = zone_snapshot
        self._cancelled = False

    def cancel(self) -> None:
        """Request cooperative cancellation.

        ``run()`` is a long loop over every genre/decade and monopolizes the
        thread's event loop, so ``QThread.quit()`` cannot interrupt it. Setting
        this flag lets ``run()`` bail out between shelf queries so the thread
        actually stops (and isn't destroyed mid-run on close — which aborts).
        """
        self._cancelled = True

    def run(self) -> None:
        from metatv.core.discovery_engine import (
            get_featured_actor, get_all_genres, get_all_decades,
            get_all_user_categories, get_all_collections,
            MIN_COLLECTION_SHELF_MEMBERS,
            _rank_genres_by_preference, build_status_sets, build_adult_filter,
        )
        from metatv.core.filter_utils import (
            get_active_category_filter, get_excluded_prefixes, excluded_tag_content_types,
            keyword_exclusion_list,
        )
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            ss = build_status_sets(session)
            sk = {"fav_ids": ss.fav_ids, "queue_ids": ss.queue_ids,
                      "watched_ids": ss.watched_ids, "liked_ids": ss.liked_ids,
                      "progress_map": ss.progress_map}

            cat_excluded, include_uncategorized = get_active_category_filter(self._config)
            per_prefix = get_excluded_prefixes(self._config)
            all_excl = list(set(cat_excluded or []) | per_prefix)
            fk = {"excluded_prefixes": all_excl or None,
                      "include_uncategorized": include_uncategorized,
                      # Content-provenance layer (paused-aware): hide AI content everywhere.
                      "excluded_content_types": excluded_tag_content_types(self._config) or None,
                      "excluded_keywords": keyword_exclusion_list(self._config) or None}

            adult_mode, force_adult_ids = build_adult_filter(session, self._config)
            af = {"adult_mode": adult_mode, "force_adult_provider_ids": force_adult_ids or None}
            # Canonical provider scoping: hide inactive + expired sources.
            _excl_ids = RepositoryFactory(session).providers.get_hidden_provider_ids()
            ek = {"excluded_provider_ids": _excl_ids or None,
                  "dead_signal_streak_floor": _dead_signal_streak_floor(self._config)}

            excluded_user_cats = list(getattr(
                self._config, "global_filter_excluded_user_categories", []
            ))

            # Build the zone snapshot — use the one passed in or fall back to
            # a fresh read of the config (the pre-lazy legacy path, kept for
            # compat with callers that don't pass a snapshot yet).
            zs = self._zone_snapshot
            if zs is None:
                zs = _ZoneSnapshot(
                    pinned=frozenset(self._config.discover_pinned_shelves),
                    expanded=frozenset(self._config.discover_expanded_shelves),
                    collapsed=frozenset(self._config.discover_collapsed_shelves),
                    hidden=frozenset(self._config.discover_hidden_shelves),
                    default_expanded=frozenset(),
                    first_launch=(
                        not self._config.discover_pinned_shelves
                        and not self._config.discover_expanded_shelves
                        and not self._config.discover_collapsed_shelves
                        and not self._config.discover_hidden_shelves
                    ),
                )

            hidden = zs.hidden

            def _zone(key: str) -> str:
                return determine_zone(
                    key,
                    pinned=zs.pinned,
                    expanded=zs.expanded,
                    collapsed=zs.collapsed,
                    hidden=zs.hidden,
                    default_expanded=zs.default_expanded,
                    first_launch=zs.first_launch,
                )

            def emit(data: _ShelfData) -> None:
                if data.shelf_key in hidden:
                    return
                # header_only shelves always emit (they carry no cards — that's the point).
                # Card-bearing shelves skip if empty.
                if not data.header_only and not data.cards:
                    return
                self.shelfReady.emit(
                    _ShelfData(
                        data.title, data.shelf_key, data.cards,
                        is_featured_actor=data.is_featured_actor,
                        is_user_category=data.is_user_category,
                        header_only=data.header_only,
                    )
                )

            # ── User-defined category shelves — shown FIRST (user curated) ──────
            user_cats = get_all_user_categories(
                session, excluded_user_categories=excluded_user_cats
            )
            for cat in user_cats:
                if self._cancelled:
                    return
                key = f"user_cat:{cat['name']}"
                if key in hidden:
                    continue
                zone = _zone(key)
                if zone in (_ZONE_PINNED, _ZONE_EXPANDED):
                    cards = fetch_cards_for_key(
                        session, self._config, key, 30,
                        sk=sk, fk=fk, af=af, ek=ek,
                    )
                    emit(_ShelfData(cat["name"], key, cards, is_user_category=True))
                else:
                    emit(_ShelfData(cat["name"], key, [], is_user_category=True,
                                    header_only=True))

            # ── Saved-recipe shelves — the user's own facet queries ────────────
            #
            # Owner: "saved recipes should be available as Discover Shelves".
            # A recipe already IS a shelf in everything but where it appears —
            # a named facet query the user built and kept. Placed beside the
            # user-category shelves because they are the same kind of thing:
            # curated by the user, so they come before the catalogue's own.
            #
            # ``show_in_discover`` (default True — absent on pre-#587 saves)
            # is the per-recipe master switch: OFF skips the shelf entirely,
            # never even as a header-only strip. The title carries the ✦
            # marker (icons.recipe_icon) as a non-color cue, which is also
            # what keeps a recipe and a same-named user category
            # distinguishable in the shelf manager, where both appear as
            # reorderable rows.
            for recipe in (getattr(self._config, "saved_recipes", None) or []):
                if self._cancelled:
                    return
                if not isinstance(recipe, dict):
                    continue
                if not recipe.get("show_in_discover", True):
                    continue
                recipe_name = (recipe.get("name") or "").strip()
                if not recipe_name:
                    continue
                key = f"{_RECIPE_PREFIX}{recipe_name}"
                if key in hidden:
                    continue
                title = f"{_icons.recipe_icon} {recipe_name}"
                if _zone(key) in (_ZONE_PINNED, _ZONE_EXPANDED):
                    emit(_ShelfData(title, key, fetch_cards_for_key(
                        session, self._config, key, 30,
                        sk=sk, fk=fk, af=af, ek=ek,
                    )))
                else:
                    emit(_ShelfData(title, key, [], header_only=True))

            # ── Fixed shelves ─────────────────────────────────────────────────
            for key, title in (
                # First: it is the one shelf built from YOUR taste rather than
                # from the catalogue, so it is what the grocery's butcher puts
                # at the front. Falls back to nothing (header_only) until there
                # is enough signal, exactly like the sidebar section.
                ("recommended",    "Recommended for You"),
                ("recently_added", "Recently Added"),
                ("top_movies",     "Top Rated Movies"),
                ("top_series",     "Top Rated Series"),
            ):
                if self._cancelled:
                    return
                if key in hidden:
                    continue
                zone = _zone(key)
                if zone in (_ZONE_PINNED, _ZONE_EXPANDED):
                    cards = fetch_cards_for_key(
                        session, self._config, key, 30,
                        sk=sk, fk=fk, af=af, ek=ek,
                    )
                    emit(_ShelfData(title, key, cards))
                else:
                    emit(_ShelfData(title, key, [], header_only=True))

            # ── Featured Actor ────────────────────────────────────────────────
            # The title IS the actor name, which requires fetching to discover;
            # so we always fetch eagerly for this shelf (it starts in
            # _DEFAULT_EXPANDED and has a unique key per actor).
            if self._cancelled:
                return
            try:
                from metatv.core.preference_engine import RecScoringSettings, compute_weights
                weights = compute_weights(
                    session, settings=RecScoringSettings.from_config(self._config)
                )
            except Exception:
                logger.warning("Featured-actor shelf falling back to unweighted", exc_info=True)
                weights = None
            actor, cards = get_featured_actor(session, weights, **sk, **fk, **af, **ek)
            if actor:
                key = f"actor:{actor}"
                if key not in hidden:
                    emit(_ShelfData(f"Featured: {actor}", key, cards,
                                    is_featured_actor=True))

            # ── Genre shelves — preference-ranked, no hard cap ────────────────
            genres = get_all_genres(session, min_count=10, **fk, **af, **ek)
            genres = _rank_genres_by_preference(genres, ss.liked_ids, session, **fk)
            for genre in genres:
                if self._cancelled:
                    return
                key = f"genre:{genre}"
                if key in hidden:
                    continue
                zone = _zone(key)
                if zone in (_ZONE_PINNED, _ZONE_EXPANDED):
                    cards = fetch_cards_for_key(
                        session, self._config, key, 30,
                        sk=sk, fk=fk, af=af, ek=ek,
                    )
                    emit(_ShelfData(genre, key, cards))
                else:
                    emit(_ShelfData(genre, key, [], header_only=True))

            # ── Decade shelves — no hard cap ──────────────────────────────────
            for decade in get_all_decades(session, **fk, **af, **ek):
                if self._cancelled:
                    return
                key = f"decade:{decade}"
                if key in hidden:
                    continue
                zone = _zone(key)
                if zone in (_ZONE_PINNED, _ZONE_EXPANDED):
                    cards = fetch_cards_for_key(
                        session, self._config, key, 30,
                        sk=sk, fk=fk, af=af, ek=ek,
                    )
                    emit(_ShelfData(f"{decade}s", key, cards))
                else:
                    emit(_ShelfData(f"{decade}s", key, [], header_only=True))

            # ── Collection shelves — provider-category "Collections" (#256),
            # e.g. "Apple+ Kids", "Hindu Subs" — no hard cap beyond the
            # min-member floor applied inside get_all_collections().
            collections = get_all_collections(
                session, min_count=MIN_COLLECTION_SHELF_MEMBERS, **fk, **af, **ek
            )
            for collection in collections:
                if self._cancelled:
                    return
                key = f"collection:{collection}"
                if key in hidden:
                    continue
                zone = _zone(key)
                if zone in (_ZONE_PINNED, _ZONE_EXPANDED):
                    cards = fetch_cards_for_key(
                        session, self._config, key, 30,
                        sk=sk, fk=fk, af=af, ek=ek,
                    )
                    emit(_ShelfData(collection, key, cards))
                else:
                    emit(_ShelfData(collection, key, [], header_only=True))

        except Exception:
            logger.exception("DiscoverView loader error")
        finally:
            session.close()
            # In finally so a cancel-triggered early return still fires it —
            # the thread's started→run slot returns, letting QThread.quit() take
            # effect (the finished→quit connection) so on_deactivate's wait()
            # succeeds instead of timing out on a still-running thread.
            self.finished.emit()
