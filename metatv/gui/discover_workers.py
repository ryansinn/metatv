"""Discover view — background loader workers (_ShelfData, _LoaderWorker, _SeeAllWorker)."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.core.discovery_engine import ContentCard

_SEE_ALL_LIMIT = 500  # max cards fetched for the "See All" browse grid


class _ShelfData:
    __slots__ = ("title", "shelf_key", "cards", "is_featured_actor", "is_user_category")

    def __init__(self, title: str, shelf_key: str, cards: list[ContentCard],
                 is_featured_actor: bool = False,
                 is_user_category: bool = False) -> None:
        self.title = title
        self.shelf_key = shelf_key
        self.cards = cards
        self.is_featured_actor = is_featured_actor
        self.is_user_category = is_user_category


class _SeeAllWorker(QObject):
    """Fetch the full item set for a shelf — runs in a background thread."""

    ready = pyqtSignal(str, list)  # (shelf_key, cards)

    def __init__(self, db: Database, config: Config, shelf_key: str) -> None:
        super().__init__()
        self._db = db
        self._config = config
        self._shelf_key = shelf_key

    def run(self) -> None:
        from metatv.core.discovery_engine import (
            get_recently_added, get_top_rated, get_by_genre,
            get_by_decade, get_by_actor, build_status_sets, build_adult_filter,
        )
        from metatv.core.filter_utils import get_active_category_filter, get_excluded_prefixes
        session = self._db.get_session()
        try:
            ss = build_status_sets(session)
            cat_excluded, include_uncategorized = get_active_category_filter(self._config)
            per_prefix = get_excluded_prefixes(self._config)
            all_excl = list(set(cat_excluded or []) | per_prefix)
            fk = dict(excluded_prefixes=all_excl or None,
                      include_uncategorized=include_uncategorized)
            sk = dict(fav_ids=ss.fav_ids, queue_ids=ss.queue_ids,
                      watched_ids=ss.watched_ids, liked_ids=ss.liked_ids)
            adult_mode, force_adult_ids = build_adult_filter(session, self._config)
            af = dict(adult_mode=adult_mode, force_adult_provider_ids=force_adult_ids or None)

            key = self._shelf_key
            limit = _SEE_ALL_LIMIT
            if key == "recently_added":
                cards = get_recently_added(session, limit=limit, **sk, **fk, **af)
            elif key == "top_movies":
                cards = get_top_rated(session, "movie", limit=limit, **sk, **fk, **af)
            elif key == "top_series":
                cards = get_top_rated(session, "series", limit=limit, **sk, **fk, **af)
            elif key.startswith("genre:"):
                cards = get_by_genre(session, key[6:], limit=limit, **sk, **fk, **af)
            elif key.startswith("decade:"):
                cards = get_by_decade(session, int(key[7:]), limit=limit, **sk, **fk, **af)
            elif key.startswith("actor:"):
                cards = get_by_actor(session, key[6:], limit=limit, **sk, **fk, **af)
            else:
                cards = []
        except Exception:
            logger.exception("SeeAllWorker error for %s", self._shelf_key)
            cards = []
        finally:
            session.close()
        self.ready.emit(self._shelf_key, cards)


class _LoaderWorker(QObject):
    shelfReady = pyqtSignal(object)   # _ShelfData
    finished   = pyqtSignal()

    def __init__(self, db: Database, config: Config) -> None:
        super().__init__()
        self._db = db
        self._config = config

    def run(self) -> None:
        from metatv.core.discovery_engine import (
            get_recently_added, get_top_rated, get_by_genre,
            get_by_decade, get_featured_actor, get_all_genres, get_all_decades,
            get_all_user_categories, get_by_user_category,
            _rank_genres_by_preference, build_status_sets, build_adult_filter,
        )
        from metatv.core.filter_utils import get_active_category_filter, get_excluded_prefixes
        session = self._db.get_session()
        try:
            ss = build_status_sets(session)
            sk = dict(fav_ids=ss.fav_ids, queue_ids=ss.queue_ids,
                      watched_ids=ss.watched_ids, liked_ids=ss.liked_ids)

            cat_excluded, include_uncategorized = get_active_category_filter(self._config)
            per_prefix = get_excluded_prefixes(self._config)
            all_excl = list(set(cat_excluded or []) | per_prefix)
            fk = dict(excluded_prefixes=all_excl or None,
                      include_uncategorized=include_uncategorized)

            adult_mode, force_adult_ids = build_adult_filter(session, self._config)
            af = dict(adult_mode=adult_mode, force_adult_provider_ids=force_adult_ids or None)

            excluded_user_cats = list(getattr(
                self._config, "global_filter_excluded_user_categories", []
            ))
            hidden = set(self._config.discover_hidden_shelves)

            def emit(data: _ShelfData) -> None:
                if data.shelf_key in hidden:
                    return
                if not data.cards:
                    return
                self.shelfReady.emit(_ShelfData(data.title, data.shelf_key, data.cards))

            # ── User-defined category shelves — shown FIRST (user curated) ──────
            user_cats = get_all_user_categories(
                session, excluded_user_categories=excluded_user_cats
            )
            for cat in user_cats:
                key = f"user_cat:{cat['name']}"
                if key not in hidden:
                    cards = get_by_user_category(
                        session, cat["name"], limit=30, **sk, **fk, **af
                    )
                    emit(_ShelfData(cat["name"], key, cards, is_user_category=True))

            # Fixed shelves
            emit(_ShelfData(
                "Recently Added", "recently_added",
                get_recently_added(session, limit=30, **sk, **fk, **af),
            ))
            emit(_ShelfData(
                "Top Rated Movies", "top_movies",
                get_top_rated(session, "movie", limit=30, **sk, **fk, **af),
            ))
            emit(_ShelfData(
                "Top Rated Series", "top_series",
                get_top_rated(session, "series", limit=30, **sk, **fk, **af),
            ))

            # Featured Actor
            try:
                from metatv.core.preference_engine import compute_weights
                weights = compute_weights(session)
            except Exception:
                weights = None
            actor, cards = get_featured_actor(session, weights, **sk, **fk, **af)
            if actor:
                emit(_ShelfData(f"Featured: {actor}", f"actor:{actor}", cards,
                                is_featured_actor=True))

            # Genre shelves — preference-ranked, no hard cap
            genres = get_all_genres(session, min_count=10, **fk, **af)
            genres = _rank_genres_by_preference(genres, ss.liked_ids, session, **fk)
            for genre in genres:
                key = f"genre:{genre}"
                if key not in hidden:
                    cards = get_by_genre(session, genre, limit=30, **sk, **fk, **af)
                    emit(_ShelfData(genre, key, cards))

            # Decade shelves — no hard cap
            for decade in get_all_decades(session, **fk, **af):
                key = f"decade:{decade}"
                if key not in hidden:
                    cards = get_by_decade(session, decade, limit=30, **sk, **fk, **af)
                    emit(_ShelfData(f"{decade}s", key, cards))

        except Exception:
            logger.exception("DiscoverView loader error")
        finally:
            session.close()
        self.finished.emit()
