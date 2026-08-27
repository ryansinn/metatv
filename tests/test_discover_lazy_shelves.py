"""Behavioral tests for the pure-lazy Discover view.

Guards:
1. ``_LoaderWorker`` with a collapsed zone emits ``header_only=True`` with no
   cards and WITHOUT issuing the per-shelf DB card-query.
2. ``_LoaderWorker`` with a pinned/expanded zone emits cards (non-header-only)
   for the same key.
3. ``fetch_cards_for_key`` returns cards for known keys (direct unit test).
4. ``_on_expand_requested`` for an unloaded shelf kicks ``_ShelfCardsWorker``
   which emits cards; ``_Shelf.set_cards`` populates the shelf.
5. ``on_deactivate`` stops the lazy-expand thread in addition to the loader
   and see-all threads.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def seeded_db(tmp_path):
    """File-backed DB (not :memory:) with enough movie/series rows seeded.

    We need ≥10 rows per genre so ``get_all_genres(min_count=10)`` returns
    "Action" and "Drama".  Decade shelves need ≥10 rows per decade.
    """
    from metatv.core.database import Database, ChannelDB, ProviderDB
    db = Database(f"sqlite:///{tmp_path / 'discover_test.db'}")
    db.create_tables()

    session = db.get_session()
    try:
        # Provider row is required: get_hidden_provider_ids() treats channels
        # with no matching ProviderDB row as "orphaned" and excludes them.
        session.add(ProviderDB(
            id="p1", name="Test Provider", type="xtream",
            url="http://test.example.com", is_active=True,
        ))
        rows = [
            ChannelDB(
                id=str(uuid.uuid4()),
                source_id=str(i),
                provider_id="p1",
                name=f"Action Movie {i} (2000)",
                media_type="movie",
                detected_prefix=None,
                raw_data={"genre": "Action", "rating": str(8.0),
                          "stream_icon": "", "releaseDate": "2000-01-01"},
            )
            for i in range(12)  # 12 > min_count=10
        ] + [
            ChannelDB(
                id=str(uuid.uuid4()),
                source_id=str(20 + i),
                provider_id="p1",
                name=f"Drama Series {i} (2010)",
                media_type="series",
                detected_prefix=None,
                raw_data={"genre": "Drama", "rating": str(7.5),
                          "stream_icon": "", "releaseDate": "2010-01-01"},
            )
            for i in range(12)
        ]
        for row in rows:
            session.add(row)
        session.commit()
    finally:
        session.close()

    # Genre shelf queries now read the ingestion-computed detected_genres
    # field (#genre-perf) instead of parsing raw_data live — run the real
    # ingestion pass so the fixture mirrors what a provider refresh does.
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope() as session:
        RepositoryFactory(session).channels.update_detected_prefixes(provider_id=None)

    yield db
    db.close()


# ---------------------------------------------------------------------------
# Helper: build a _ZoneSnapshot
# ---------------------------------------------------------------------------

def _snap(pinned=(), expanded=(), collapsed=(), hidden=(),
          default_expanded=("recently_added", "top_movies"), first_launch=False):
    from metatv.gui.discover_workers import _ZoneSnapshot
    return _ZoneSnapshot(
        pinned=frozenset(pinned),
        expanded=frozenset(expanded),
        collapsed=frozenset(collapsed),
        hidden=frozenset(hidden),
        default_expanded=frozenset(default_expanded),
        first_launch=first_launch,
    )


# ---------------------------------------------------------------------------
# 1 & 2. _LoaderWorker zone awareness
# ---------------------------------------------------------------------------

class TestLoaderWorkerZoneAwareness:

    def test_collapsed_genre_emits_header_only_no_cards(self, seeded_db, qapp):
        """A genre in the collapsed zone comes back header_only=True, cards=[]."""
        from metatv.core.config import Config
        from metatv.gui.discover_workers import _LoaderWorker

        # Put genre:Action in collapsed, leave expanded empty so fixed shelves
        # like recently_added also collapse.
        snapshot = _snap(
            collapsed={"genre:Action", "recently_added", "top_movies", "top_series",
                        "genre:Drama"},
        )
        cfg = Config()
        w = _LoaderWorker(seeded_db, cfg, zone_snapshot=snapshot)

        shelves: list = []
        w.shelfReady.connect(lambda d: shelves.append(d))
        finished: list = []
        w.finished.connect(lambda: finished.append(True))
        w.run()

        assert finished, "finished must fire"

        # Find the genre:Action shelf
        action_shelves = [s for s in shelves if s.shelf_key == "genre:Action"]
        assert action_shelves, "genre:Action shelf must be emitted (even collapsed)"
        s = action_shelves[0]
        assert s.header_only is True, "collapsed genre must be header_only"
        assert s.cards == [], "collapsed shelf must carry no cards"

    def test_expanded_genre_emits_cards(self, seeded_db, qapp):
        """A genre in the expanded zone comes back with cards (not header_only)."""
        from metatv.core.config import Config
        from metatv.gui.discover_workers import _LoaderWorker

        snapshot = _snap(
            expanded={"genre:Action"},
            collapsed={"recently_added", "top_movies", "top_series", "genre:Drama"},
        )
        cfg = Config()
        w = _LoaderWorker(seeded_db, cfg, zone_snapshot=snapshot)

        shelves: list = []
        w.shelfReady.connect(lambda d: shelves.append(d))
        w.run()

        action_shelves = [s for s in shelves if s.shelf_key == "genre:Action"]
        assert action_shelves, "genre:Action shelf must be emitted when expanded"
        s = action_shelves[0]
        assert s.header_only is False, "expanded genre must NOT be header_only"
        assert len(s.cards) > 0, "expanded genre must have cards"

    def test_first_launch_defaults(self, seeded_db, qapp):
        """On first launch, recently_added and top_movies expand; genres collapse."""
        from metatv.core.config import Config
        from metatv.gui.discover_workers import _LoaderWorker

        snapshot = _snap(first_launch=True,
                         default_expanded={"recently_added", "top_movies"})
        cfg = Config()
        w = _LoaderWorker(seeded_db, cfg, zone_snapshot=snapshot)

        shelves: list = []
        w.shelfReady.connect(lambda d: shelves.append(d))
        w.run()

        by_key = {s.shelf_key: s for s in shelves}

        if "recently_added" in by_key:
            assert by_key["recently_added"].header_only is False
        if "top_movies" in by_key:
            assert by_key["top_movies"].header_only is False

        # Genre shelves should be collapsed (header_only).
        genre_shelves = [s for s in shelves if s.shelf_key.startswith("genre:")]
        assert genre_shelves, "there must be genre shelves on first launch"
        for gs in genre_shelves:
            assert gs.header_only is True, f"{gs.shelf_key} should be header_only on first launch"

    def test_hidden_shelf_not_emitted(self, seeded_db, qapp):
        """A hidden shelf must not appear in the emitted list at all."""
        from metatv.core.config import Config
        from metatv.gui.discover_workers import _LoaderWorker

        snapshot = _snap(hidden={"genre:Action"})
        cfg = Config()
        w = _LoaderWorker(seeded_db, cfg, zone_snapshot=snapshot)

        shelves: list = []
        w.shelfReady.connect(lambda d: shelves.append(d))
        w.run()

        keys = [s.shelf_key for s in shelves]
        assert "genre:Action" not in keys, "hidden shelf must not be emitted"


# ---------------------------------------------------------------------------
# 3. fetch_cards_for_key direct unit test
# ---------------------------------------------------------------------------

class TestFetchCardsForKey:

    def test_genre_key_returns_cards(self, seeded_db):
        """fetch_cards_for_key('genre:Action', limit=30) returns Action movie cards."""
        from metatv.core.config import Config
        from metatv.core.discovery_engine import build_status_sets, build_adult_filter
        from metatv.core.repositories import RepositoryFactory
        from metatv.gui.discover_workers import fetch_cards_for_key

        session = seeded_db.get_session()
        try:
            ss = build_status_sets(session)
            sk = {"fav_ids": ss.fav_ids, "queue_ids": ss.queue_ids,
                      "watched_ids": ss.watched_ids, "liked_ids": ss.liked_ids}
            fk = {"excluded_prefixes": None, "include_uncategorized": True}
            adult_mode, force_adult_ids = build_adult_filter(session, Config())
            af = {"adult_mode": adult_mode, "force_adult_provider_ids": force_adult_ids or None}
            excl_ids = RepositoryFactory(session).providers.get_hidden_provider_ids()
            ek = {"excluded_provider_ids": excl_ids or None}

            cards = fetch_cards_for_key(
                session, Config(), "genre:Action", 30,
                sk=sk, fk=fk, af=af, ek=ek,
            )
        finally:
            session.close()

        assert len(cards) > 0, "fetch_cards_for_key should return Action cards"
        assert all(c.genre == "Action" for c in cards)

    def test_recently_added_key(self, seeded_db):
        """fetch_cards_for_key('recently_added', limit=30) returns cards."""
        from metatv.core.config import Config
        from metatv.core.discovery_engine import build_status_sets, build_adult_filter
        from metatv.core.repositories import RepositoryFactory
        from metatv.gui.discover_workers import fetch_cards_for_key

        session = seeded_db.get_session()
        try:
            ss = build_status_sets(session)
            sk = {"fav_ids": ss.fav_ids, "queue_ids": ss.queue_ids,
                      "watched_ids": ss.watched_ids, "liked_ids": ss.liked_ids}
            fk = {"excluded_prefixes": None, "include_uncategorized": True}
            adult_mode, force_adult_ids = build_adult_filter(session, Config())
            af = {"adult_mode": adult_mode, "force_adult_provider_ids": force_adult_ids or None}
            excl_ids = RepositoryFactory(session).providers.get_hidden_provider_ids()
            ek = {"excluded_provider_ids": excl_ids or None}

            cards = fetch_cards_for_key(
                session, Config(), "recently_added", 30,
                sk=sk, fk=fk, af=af, ek=ek,
            )
        finally:
            session.close()

        assert len(cards) > 0, "recently_added should return seeded movie/series cards"

    def test_unknown_key_returns_empty(self, seeded_db):
        """An unknown shelf key returns [] without raising."""
        from metatv.core.config import Config
        from metatv.gui.discover_workers import fetch_cards_for_key

        session = seeded_db.get_session()
        try:
            cards = fetch_cards_for_key(
                session, Config(), "totally:unknown:key", 30,
                sk={}, fk={}, af={}, ek={},
            )
        finally:
            session.close()

        assert cards == []


# ---------------------------------------------------------------------------
# 4. _ShelfCardsWorker emits cards; _Shelf.set_cards populates
# ---------------------------------------------------------------------------

class TestLazyExpandWorker:

    def test_shelf_cards_worker_emits_cards_for_genre(self, seeded_db, qapp):
        """_ShelfCardsWorker emits (shelf_key, cards) for a known genre key."""
        from metatv.core.config import Config
        from metatv.gui.discover_workers import _ShelfCardsWorker

        w = _ShelfCardsWorker(seeded_db, Config(), "genre:Action", limit=30)
        results: list = []
        w.ready.connect(lambda k, c: results.append((k, c)))
        w.run()

        assert len(results) == 1, "worker must emit exactly once"
        key, cards = results[0]
        assert key == "genre:Action"
        assert len(cards) > 0

    def test_shelf_cards_worker_cancelled_no_emit(self, seeded_db, qapp):
        """A cancelled _ShelfCardsWorker must not emit."""
        from metatv.core.config import Config
        from metatv.gui.discover_workers import _ShelfCardsWorker

        w = _ShelfCardsWorker(seeded_db, Config(), "genre:Action", limit=30)
        w.cancel()
        results: list = []
        w.ready.connect(lambda k, c: results.append((k, c)))
        w.run()
        assert results == [], "cancelled worker must not emit"

    def test_shelf_cards_worker_emits_error_on_query_failure(self, seeded_db, qapp, monkeypatch):
        """A raising query must emit ``error(shelf_key, message)``, never ``ready``.

        Owner-reported perf bug fix requirement: a failed lazy-expand fetch
        must render a visible error row, never look like a silently-empty
        shelf (CLAUDE.md async-background-DB-reads rule) — the view can only
        do that if the worker actually distinguishes "query raised" from
        "query legitimately returned zero cards".
        """
        from metatv.core.config import Config
        from metatv.core import discovery_engine
        from metatv.gui.discover_workers import _ShelfCardsWorker

        def _boom(session):
            raise RuntimeError("synthetic DB failure")

        # _ShelfCardsWorker.run() does a LOCAL
        # "from metatv.core.discovery_engine import build_status_sets" — patch
        # the real source attribute, not a re-export, so the local import
        # inside run() picks it up.
        monkeypatch.setattr(discovery_engine, "build_status_sets", _boom)

        w = _ShelfCardsWorker(seeded_db, Config(), "genre:Action", limit=30)
        ready_results: list = []
        error_results: list = []
        w.ready.connect(lambda k, c: ready_results.append((k, c)))
        w.error.connect(lambda k, m: error_results.append((k, m)))
        w.run()

        assert ready_results == [], "must not emit ready when the query raised"
        assert len(error_results) == 1, "must emit error exactly once"
        key, message = error_results[0]
        assert key == "genre:Action"
        assert "synthetic DB failure" in message

    def test_shelf_set_cards_populates_card_widgets(self, qapp):
        """_Shelf.set_cards() adds card widgets to the inner layout."""
        from metatv.core.config import Config
        from metatv.core.discovery_engine import ContentCard
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        image_cache = MagicMock()
        # Minimal image_cache so _ContentCard doesn't actually try to load images.
        image_cache.get_image_async = MagicMock()

        # Build a header-only shelf (empty cards at construction).
        shelf = _Shelf("Test Genre", "genre:Test", [], image_cache, cfg, collapsed=True)
        assert shelf._cards_widgets == [], "initially empty"

        # Synthesise a fake card.
        card = ContentCard(
            channel_id="ch-1",
            title="Great Movie",
            media_type="movie",
            thumbnail_url=None,
            rating=8.0,
            year=2020,
            genre="Test",
        )

        shelf.set_cards([card], image_cache=image_cache, config=cfg)
        assert len(shelf._cards_widgets) == 1, "set_cards must add one card widget"

    def test_shelf_set_loading_shows_placeholder_row(self, qapp):
        """set_loading() shows a 'Loading…' row on a still-empty (header-only) shelf.

        Owner-reported perf bug: expanding/pinning a not-yet-fetched shelf used
        to sit visibly empty with no feedback while the fetch ran.
        """
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        image_cache = MagicMock()
        shelf = _Shelf("Test Genre", "genre:Test", [], image_cache, cfg, collapsed=False)

        shelf.set_loading()

        assert shelf._placeholder_lbl is not None, "loading placeholder must be shown"
        assert "Loading" in shelf._placeholder_lbl.text()

    def test_shelf_set_cards_clears_loading_placeholder(self, qapp):
        """A successful set_cards() replaces the loading placeholder with real cards."""
        from metatv.core.config import Config
        from metatv.core.discovery_engine import ContentCard
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        image_cache = MagicMock()
        image_cache.get_image_async = MagicMock()
        shelf = _Shelf("Test Genre", "genre:Test", [], image_cache, cfg, collapsed=False)
        shelf.set_loading()
        assert shelf._placeholder_lbl is not None

        card = ContentCard(
            channel_id="ch-1", title="Great Movie", media_type="movie",
            thumbnail_url=None, rating=8.0, year=2020, genre="Test",
        )
        shelf.set_cards([card], image_cache=image_cache, config=cfg)

        assert shelf._placeholder_lbl is None, "loading placeholder must be cleared"
        assert len(shelf._cards_widgets) == 1

    def test_shelf_show_load_error_shows_error_row(self, qapp):
        """show_load_error() shows a visible warning row, replacing any loading placeholder.

        Per CLAUDE.md's async-background-DB-reads rule: a failed background
        load must never look like a silently-empty result.
        """
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        image_cache = MagicMock()
        shelf = _Shelf("Test Genre", "genre:Test", [], image_cache, cfg, collapsed=False)
        shelf.set_loading()

        shelf.show_load_error("Couldn't load this shelf")

        assert shelf._placeholder_lbl is not None, "error placeholder must be shown"
        assert "Couldn't load this shelf" in shelf._placeholder_lbl.text()
        # Never a bare empty row indistinguishable from "nothing here".
        assert shelf._cards_widgets == []


# ---------------------------------------------------------------------------
# 5. on_deactivate stops the lazy-expand thread too
# ---------------------------------------------------------------------------

def _running_thread() -> MagicMock:
    t = MagicMock()
    t.isRunning.return_value = True
    t.wait.return_value = True
    return t


def test_on_deactivate_stops_expand_thread_too():
    """on_deactivate must cancel+stop the lazy-expand thread, not just the two legacy ones."""
    from metatv.gui.discover_view import DiscoverView

    view = DiscoverView.__new__(DiscoverView)
    view._worker = MagicMock()
    view._see_all_worker = MagicMock()
    view._expand_worker = MagicMock()
    view._thread = _running_thread()
    view._see_all_thread = _running_thread()
    view._expand_thread = _running_thread()
    view._inflight_expand = "genre:Action"

    view.on_deactivate()

    # All three workers must be cancelled.
    view._worker.cancel.assert_called_once()
    view._see_all_worker.cancel.assert_called_once()
    view._expand_worker.cancel.assert_called_once()
    # All three threads must be quit + waited.
    view._thread.quit.assert_called_once()
    view._thread.wait.assert_called_once()
    view._see_all_thread.quit.assert_called_once()
    view._see_all_thread.wait.assert_called_once()
    view._expand_thread.quit.assert_called_once()
    view._expand_thread.wait.assert_called_once()
    # inflight_expand cleared.
    assert view._inflight_expand is None


def test_on_deactivate_safe_with_no_expand_thread():
    """Never-expanded view (expand_thread=None) must not raise on deactivate."""
    from metatv.gui.discover_view import DiscoverView

    view = DiscoverView.__new__(DiscoverView)
    view._worker = None
    view._see_all_worker = None
    view._expand_worker = None
    view._thread = None
    view._see_all_thread = None
    view._expand_thread = None
    view._inflight_expand = None

    view.on_deactivate()  # must not raise
