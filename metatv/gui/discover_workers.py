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

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.core.discovery_engine import ContentCard

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
        get_by_decade, get_by_actor, get_by_user_category,
    )

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
    return []


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
        from metatv.core.filter_utils import get_active_category_filter, get_excluded_prefixes, excluded_tag_content_types
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            ss = build_status_sets(session)
            cat_excluded, include_uncategorized = get_active_category_filter(self._config)
            per_prefix = get_excluded_prefixes(self._config)
            all_excl = list(set(cat_excluded or []) | per_prefix)
            fk = dict(excluded_prefixes=all_excl or None,
                      include_uncategorized=include_uncategorized,
                      # Content-provenance layer (paused-aware): hide AI content everywhere.
                      excluded_content_types=excluded_tag_content_types(self._config) or None)
            sk = dict(fav_ids=ss.fav_ids, queue_ids=ss.queue_ids,
                      watched_ids=ss.watched_ids, liked_ids=ss.liked_ids,
                      progress_map=ss.progress_map)
            adult_mode, force_adult_ids = build_adult_filter(session, self._config)
            af = dict(adult_mode=adult_mode, force_adult_provider_ids=force_adult_ids or None)
            # Canonical provider scoping: hide inactive + expired sources.
            _excl_ids = RepositoryFactory(session).providers.get_hidden_provider_ids()
            ek = dict(excluded_provider_ids=_excl_ids or None)

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

    Emits ``ready(shelf_key, cards)`` on success (or with an empty list on
    error).  The view connects to this and calls ``_Shelf.set_cards()``.
    """

    ready = pyqtSignal(str, list)  # (shelf_key, cards)

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
        from metatv.core.filter_utils import get_active_category_filter, get_excluded_prefixes, excluded_tag_content_types
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            ss = build_status_sets(session)
            cat_excluded, include_uncategorized = get_active_category_filter(self._config)
            per_prefix = get_excluded_prefixes(self._config)
            all_excl = list(set(cat_excluded or []) | per_prefix)
            fk = dict(excluded_prefixes=all_excl or None,
                      include_uncategorized=include_uncategorized,
                      # Content-provenance layer (paused-aware): hide AI content everywhere.
                      excluded_content_types=excluded_tag_content_types(self._config) or None)
            sk = dict(fav_ids=ss.fav_ids, queue_ids=ss.queue_ids,
                      watched_ids=ss.watched_ids, liked_ids=ss.liked_ids,
                      progress_map=ss.progress_map)
            adult_mode, force_adult_ids = build_adult_filter(session, self._config)
            af = dict(adult_mode=adult_mode, force_adult_provider_ids=force_adult_ids or None)
            _excl_ids = RepositoryFactory(session).providers.get_hidden_provider_ids()
            ek = dict(excluded_provider_ids=_excl_ids or None)

            cards = fetch_cards_for_key(
                session, self._config, self._shelf_key, self._limit,
                sk=sk, fk=fk, af=af, ek=ek,
            )
        except Exception:
            logger.exception("ShelfCardsWorker error for %s", self._shelf_key)
            cards = []
        finally:
            session.close()
        if not self._cancelled:
            self.ready.emit(self._shelf_key, cards)


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
            get_all_user_categories,
            _rank_genres_by_preference, build_status_sets, build_adult_filter,
        )
        from metatv.core.filter_utils import get_active_category_filter, get_excluded_prefixes, excluded_tag_content_types
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            ss = build_status_sets(session)
            sk = dict(fav_ids=ss.fav_ids, queue_ids=ss.queue_ids,
                      watched_ids=ss.watched_ids, liked_ids=ss.liked_ids,
                      progress_map=ss.progress_map)

            cat_excluded, include_uncategorized = get_active_category_filter(self._config)
            per_prefix = get_excluded_prefixes(self._config)
            all_excl = list(set(cat_excluded or []) | per_prefix)
            fk = dict(excluded_prefixes=all_excl or None,
                      include_uncategorized=include_uncategorized,
                      # Content-provenance layer (paused-aware): hide AI content everywhere.
                      excluded_content_types=excluded_tag_content_types(self._config) or None)

            adult_mode, force_adult_ids = build_adult_filter(session, self._config)
            af = dict(adult_mode=adult_mode, force_adult_provider_ids=force_adult_ids or None)
            # Canonical provider scoping: hide inactive + expired sources.
            _excl_ids = RepositoryFactory(session).providers.get_hidden_provider_ids()
            ek = dict(excluded_provider_ids=_excl_ids or None)

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

            # ── Fixed shelves ─────────────────────────────────────────────────
            for key, title in (
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
                from metatv.core.preference_engine import compute_weights
                weights = compute_weights(session)
            except Exception:
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

        except Exception:
            logger.exception("DiscoverView loader error")
        finally:
            session.close()
            # In finally so a cancel-triggered early return still fires it —
            # the thread's started→run slot returns, letting QThread.quit() take
            # effect (the finished→quit connection) so on_deactivate's wait()
            # succeeds instead of timing out on a still-running thread.
            self.finished.emit()
