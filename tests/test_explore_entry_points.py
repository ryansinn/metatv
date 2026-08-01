"""Behavioral tests for the Explore entry points (id 196).

"Explore →" is now on FOUR sidebar sections (History, Favorites, Watch Queue,
Recommended), all opening the SAME cascading-columns component seeded from that
section's contents.  These tests execute the changed paths and assert the outcomes
that would break:

1. **Seed loaders** (real ``Database`` on a tmp_path file, not ``:memory:``):
   ``load_favorite_ids`` / ``load_queue_ids`` / ``load_recommended_ids`` return the
   ids each rail shows, in that rail's order — and honour the right scoping
   (Favorites/Queue are RECORD views, so an inactive-source entry survives;
   Recommended is forward-looking, so hidden providers are gated out).
2. **Hydration** — ``load_engaged_seed_rows`` returns ordered ``TrailRowDTO``s with
   the engaged extras; a dead id is dropped rather than faked.
3. **One component, four sources** — ``ExploreView`` opens with the right seed,
   header title + icon, and empty/error copy per entry point.
4. **Host wiring** — ``switch_to_explore_view`` activates the right view and sets its
   ``view_mode``/stats label; ``_hide_all_content_views`` deactivates it; the
   splitter clobber guard covers EVERY Explore mode; the deep-link seam resolves all
   four keys.
5. **Sidebar affordance** — the four sections grow the shared "Explore →" link (with
   a tooltip) and emit ``exploreClicked``; other sections do not.
6. **What's New 196** present with non-empty ``test_steps``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _fake_config():
    """Minimal config the seed loaders + trail-map version scoring read."""
    return SimpleNamespace(
        preferred_version_prefixes=[],
        preferred_version_provider_ids=[],
        preferred_version_quality=None,
        filter_adult_mode="all",
        global_filter_paused=False,
        global_filter_excluded_categories=[],
        global_filter_include_uncategorized=True,
        muted_attributes=None,
        rec_dedupe_overrides=[],
    )


class _FakeImageCache:
    """Stand-in ImageCache: exposes the image_loaded signal + no-op fetch."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class _IC(QObject):
            image_loaded = pyqtSignal(str, object)

            def get_image_sync(self, url):
                return None

            def get_image_async(self, url, provider_urls=None):
                return None

        self._ic = _IC()

    def __getattr__(self, name):
        return getattr(self._ic, name)


class _FakeMetadataManager:
    async def get_metadata(self, channel_id, force_refresh=False):
        return None


def _engaged_seed_db(path: Path):
    """Favorites + queue seed across an ACTIVE and an INACTIVE provider.

    Favorites (rail order = played desc, then never-played by name):
        f_recent (played today) · f_old (played 2d ago, INACTIVE source) ·
        f_alpha · f_zulu (never played)
    Queue (position order): q1 · q2 (INACTIVE source) · q_dead (orphan row, no channel)
    """
    from metatv.core.database import ChannelDB, ProviderDB, WatchQueueDB

    db = _make_db(path)
    now = datetime.now()
    with db.session_scope() as session:
        session.add(ProviderDB(id="pa", name="Alpha", type="xtream", url="http://e",
                               username="u", password="p", is_active=True,
                               account_exp_date=now + timedelta(days=30)))
        session.add(ProviderDB(id="pz", name="Zeta", type="xtream", url="http://z",
                               username="u", password="p", is_active=False))
        session.flush()

        def _ch(cid, name, **kw):
            kw.setdefault("provider_id", "pa")
            session.add(ChannelDB(id=cid, source_id=str(uuid.uuid4()), name=name,
                                  media_type="movie", **kw))

        _ch("f_recent", "Recent Favorite", is_favorite=True, last_played=now,
            play_count=4)
        _ch("f_old", "Old Favorite", provider_id="pz", is_favorite=True,
            last_played=now - timedelta(days=2), play_count=1)
        _ch("f_alpha", "Alpha Favorite", is_favorite=True)
        _ch("f_zulu", "Zulu Favorite", is_favorite=True)
        # Favorited but hidden from the corpus — get_favorites filters is_hidden.
        _ch("f_hidden", "Hidden Favorite", is_favorite=True, is_hidden=True)
        # Not a favorite at all.
        _ch("plain", "Just A Movie")
        # Queue members.
        _ch("q1", "Queued One", last_played=now - timedelta(days=1), play_count=2)
        _ch("q2", "Queued Two", provider_id="pz")
        session.flush()

        session.add(WatchQueueDB(channel_id="q1", channel_name="Queued One",
                                 media_type="movie", position=0))
        session.add(WatchQueueDB(channel_id="q2", channel_name="Queued Two",
                                 media_type="movie", position=1))
        # Orphan: queued, but the channel row is gone (source refresh changed the id).
        session.add(WatchQueueDB(channel_id="q_dead", channel_name="Gone Movie",
                                 media_type="movie", position=2))
        session.flush()
    return db


def _recommended_seed_db(path: Path):
    """Taste weights (one liked title) + two unrated candidates, one on a dead source."""
    from metatv.core.database import (
        ChannelDB, MetadataDB, ProviderDB, UserRatingDB,
    )

    db = _make_db(path)
    now = datetime.now()
    genres = ["Sci-Fi", "Adventure"]
    cast = [{"name": "Ada Vex"}, {"name": "Bo Quill"}]
    with db.session_scope() as session:
        session.add(ProviderDB(id="pa", name="Alpha", type="xtream", url="http://e",
                               username="u", password="p", is_active=True,
                               account_exp_date=now + timedelta(days=30)))
        session.add(ProviderDB(id="pz", name="Zeta", type="xtream", url="http://z",
                               username="u", password="p", is_active=False))
        session.flush()

        def _meta(mid, title):
            session.add(MetadataDB(id=mid, title=title, genres=genres, cast=cast,
                                   director="Cy Rune", plot="A crew sails the void.",
                                   year=2020))

        def _ch(cid, name, mid, provider_id="pa"):
            session.add(ChannelDB(id=cid, source_id=str(uuid.uuid4()),
                                  provider_id=provider_id, name=name,
                                  media_type="movie", metadata_id=mid,
                                  detected_title=name))

        _meta("m_liked", "Void Sailors")
        _meta("m_good", "Void Sailors II")
        _meta("m_dead", "Void Sailors III")
        session.flush()
        _ch("liked", "Void Sailors", "m_liked")
        _ch("good", "Void Sailors II", "m_good")
        _ch("dead", "Void Sailors III", "m_dead", provider_id="pz")
        session.flush()
        session.add(UserRatingDB(channel_id="liked", rating=1))
        session.flush()
    return db


# ---------------------------------------------------------------------------
# 1. Seed loaders (real DB)
# ---------------------------------------------------------------------------

class TestFavoritesSeed:
    def test_ids_follow_the_rail_order_and_are_not_provider_gated(self, tmp_path):
        from metatv.gui.trail_map_data import load_favorite_ids

        db = _engaged_seed_db(tmp_path / "fav.db")
        with db.session_scope(commit=False) as session:
            ids = load_favorite_ids(session)
        assert ids == ["f_recent", "f_old", "f_alpha", "f_zulu"], (
            "Continue Watching (last_played desc) then Never Watched (by name) — the "
            "same order the Favorites rail renders"
        )
        assert "f_old" in ids, "record view — a favorite on an inactive source stays"
        assert "f_hidden" not in ids, "hidden channels are not favorites the user sees"
        assert "plain" not in ids, "non-favorites are never seeded"
        db.close()

    def test_limit_bounds_the_seed(self, tmp_path):
        from metatv.gui.trail_map_data import load_favorite_ids

        db = _engaged_seed_db(tmp_path / "fav_limit.db")
        with db.session_scope(commit=False) as session:
            ids = load_favorite_ids(session, limit=2)
        assert ids == ["f_recent", "f_old"], "limit trims the tail, keeps rail order"
        db.close()


class TestQueueSeed:
    def test_ids_follow_queue_position_and_keep_inactive_sources(self, tmp_path):
        from metatv.gui.trail_map_data import load_queue_ids

        db = _engaged_seed_db(tmp_path / "queue.db")
        with db.session_scope(commit=False) as session:
            ids = load_queue_ids(session)
        assert ids == ["q1", "q2", "q_dead"], "the user's own queue order (position)"
        assert "q2" in ids, "record view — a queued title on an inactive source stays"
        db.close()

    def test_orphaned_entry_is_dropped_at_hydration(self, tmp_path):
        """The queue keeps orphans visible; the trail-map can only walk real rows."""
        from metatv.gui.trail_map_data import load_engaged_seed_rows, load_queue_ids

        db = _engaged_seed_db(tmp_path / "queue_orphan.db")
        with db.session_scope(commit=False) as session:
            rows = load_engaged_seed_rows(session, load_queue_ids(session))
        assert [r.id for r in rows] == ["q1", "q2"], "orphan dropped, order preserved"
        db.close()


class TestRecommendedSeed:
    def test_no_taste_yet_returns_empty(self, tmp_path):
        from metatv.gui.trail_map_data import load_recommended_ids

        db = _engaged_seed_db(tmp_path / "rec_empty.db")  # ratings-free corpus
        with db.session_scope(commit=False) as session:
            ids = load_recommended_ids(session, _fake_config())
        assert ids == [], "no weights → no recommendations to explore"
        db.close()

    def test_scored_ids_returned_and_hidden_providers_gated(self, tmp_path):
        from metatv.gui.trail_map_data import load_recommended_ids

        db = _recommended_seed_db(tmp_path / "rec.db")
        with db.session_scope(commit=False) as session:
            ids = load_recommended_ids(session, _fake_config())
        assert "good" in ids, "an unrated title matching the user's taste is recommended"
        assert "dead" not in ids, (
            "forward-looking view — a candidate on an inactive source is gated out"
        )
        assert "liked" not in ids, "an already-rated title is not re-recommended"
        db.close()

    def test_does_not_record_impressions(self, tmp_path):
        """Opening Explore must not double-count what the rail already showed."""
        from metatv.core.database import ChannelDB
        from metatv.gui.trail_map_data import load_recommended_ids

        db = _recommended_seed_db(tmp_path / "rec_impr.db")
        with db.session_scope(commit=False) as session:
            load_recommended_ids(session, _fake_config())
        with db.session_scope(commit=False) as session:
            shown = session.get(ChannelDB, "good").rec_shown_count
        assert not shown, "Explore reads the engine; only the rail records impressions"
        db.close()


class TestEngagedHydration:
    def test_rows_carry_watch_extras_in_the_given_order(self, tmp_path):
        from metatv.gui.trail_map_data import load_engaged_seed_rows

        db = _engaged_seed_db(tmp_path / "hydrate.db")
        with db.session_scope(commit=False) as session:
            rows = load_engaged_seed_rows(session, ["f_alpha", "f_recent"])
        assert [r.id for r in rows] == ["f_alpha", "f_recent"], "given order preserved"
        by_id = {r.id: r for r in rows}
        assert by_id["f_recent"].watch_count == 4
        assert by_id["f_recent"].last_watched, "friendly 'when' string populated"
        assert by_id["f_recent"].is_favorite is True
        assert by_id["f_alpha"].watch_count == 0, "never played → zero, not None"
        db.close()

    def test_empty_ids_is_a_no_op(self, tmp_path):
        from metatv.gui.trail_map_data import load_engaged_seed_rows

        db = _engaged_seed_db(tmp_path / "hydrate_empty.db")
        with db.session_scope(commit=False) as session:
            assert load_engaged_seed_rows(session, []) == []
            assert load_engaged_seed_rows(session) == []
        db.close()


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------

class _SyncExecutor:
    """Runs submitted work inline so the worker→slot path is deterministic."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, wait=False):
        pass


_LIVE: list = []


@pytest.fixture(autouse=True)
def _cleanup(qapp):
    yield
    while _LIVE:
        view = _LIVE.pop()
        try:
            view.shutdown()
            view.hide()
            view.deleteLater()
        except Exception:
            pass
    qapp.processEvents()


def _make_explore_view(db, qapp, key, *, fail=False):
    from metatv.core.repositories import RepositoryFactory
    from metatv.gui.explore_view import EXPLORE_SOURCES, ExploreView

    def _inline_run_query(query_fn, on_result, *, token_ref=None, on_error=None):
        """Mirror MainWindow._run_query inline (bump token, run query_fn(repos))."""
        if token_ref is not None:
            token_ref[0] += 1
        try:
            if fail:
                raise RuntimeError("boom")
            with db.session_scope(commit=False) as session:
                data = query_fn(RepositoryFactory(session))
        except Exception as exc:
            if on_error:
                on_error(exc)
            return
        on_result(data)

    view = ExploreView(
        None, _fake_config(), _FakeImageCache(), db, _FakeMetadataManager(),
        _inline_run_query, source=EXPLORE_SOURCES[key],
    )
    # Swap the inner trail-map's real pool for an inline one so open() runs sync.
    view.trail_map._executor.shutdown(wait=False)
    view.trail_map._executor = _SyncExecutor()
    view.resize(1200, 800)
    view.show()
    qapp.processEvents()
    _LIVE.append(view)
    return view


# ---------------------------------------------------------------------------
# 2. One component, four sources
# ---------------------------------------------------------------------------

class TestExploreViewPerSource:
    def test_favorites_seeds_favorites_and_labels_the_header(self, tmp_path, qapp):
        db = _engaged_seed_db(tmp_path / "v_fav.db")
        view = _make_explore_view(db, qapp, "favorites")
        view.on_activate()
        assert [r.id for r in view.trail_map._seed_rows] == [
            "f_recent", "f_old", "f_alpha", "f_zulu",
        ], "column 0 is the Favorites rail, in rail order"
        assert view.trail_map.isVisible()
        header = view.trail_map._header_title.text()
        assert "Favorites" in header
        assert view.source.icon in header, "header carries this entry point's icon"
        assert view.trail_map._row_cache["f_recent"].watch_count == 4
        db.close()

    def test_queue_seeds_queue_in_position_order(self, tmp_path, qapp):
        db = _engaged_seed_db(tmp_path / "v_queue.db")
        view = _make_explore_view(db, qapp, "queue")
        view.on_activate()
        assert [r.id for r in view.trail_map._seed_rows] == ["q1", "q2"]
        assert "Watch Queue" in view.trail_map._header_title.text()
        db.close()

    def test_recommended_seeds_the_engine_result(self, tmp_path, qapp):
        db = _recommended_seed_db(tmp_path / "v_rec.db")
        view = _make_explore_view(db, qapp, "recommended")
        view.on_activate()
        seeded = [r.id for r in view.trail_map._seed_rows]
        assert "good" in seeded and "dead" not in seeded
        assert "Recommended" in view.trail_map._header_title.text()
        db.close()

    def test_every_source_shares_one_view_class_and_the_scoped_drill(self, tmp_path, qapp):
        from metatv.gui.explore_view import EXPLORE_SOURCES, ExploreView
        from metatv.gui.trail_map_data import load_similar_rows

        db = _engaged_seed_db(tmp_path / "v_shared.db")
        views = [
            _make_explore_view(db, qapp, k) for k in EXPLORE_SOURCES
        ]
        assert all(type(v) is ExploreView for v in views), "one component, no forks"
        assert {v.source.key for v in views} == set(EXPLORE_SOURCES)
        # Whichever entry point opened it, drilling is the SAME provider-scoped
        # similars chokepoint (forward-looking discovery keeps its gate).
        assert all(v.trail_map._similars_loader is load_similar_rows for v in views)
        db.close()

    @pytest.mark.parametrize(
        "key,needle",
        [("favorites", "No favorites"), ("queue", "watch queue is empty"),
         ("recommended", "No recommendations")],
    )
    def test_empty_source_shows_its_own_status_not_the_trail_map(
        self, tmp_path, qapp, key, needle
    ):
        db = _make_db(tmp_path / f"empty_{key}.db")     # nothing at all
        view = _make_explore_view(db, qapp, key)
        view.on_activate()
        assert view.trail_map.isHidden(), "nothing to seed → trail-map stays hidden"
        assert view._status.isVisible()
        assert needle in view._status.text()
        db.close()

    def test_load_failure_renders_this_source_error_copy(self, tmp_path, qapp):
        db = _engaged_seed_db(tmp_path / "v_err.db")
        view = _make_explore_view(db, qapp, "queue", fail=True)
        view.on_activate()
        assert view.trail_map.isHidden()
        assert "Couldn't load your watch queue" in view._status.text(), (
            "a failed seed read is surfaced, never a silent empty state"
        )
        db.close()

    def test_deactivate_releases_and_drops_a_late_result(self, tmp_path, qapp):
        db = _engaged_seed_db(tmp_path / "v_deact.db")
        view = _make_explore_view(db, qapp, "favorites")
        view.on_activate()
        assert view.trail_map.isVisible()
        token_before = view._token[0]
        view.on_deactivate()
        assert view.trail_map.isHidden(), "on_deactivate hides the trail-map"
        assert view._token[0] > token_before, "token bumped → a late result is dropped"
        db.close()


# ---------------------------------------------------------------------------
# 3. Host wiring — switch / hide-all / clobber guard / deep links
# ---------------------------------------------------------------------------

def _nav_host(key: str):
    """A bare ``_NavMixin`` with just the attributes the nav methods touch."""
    from metatv.gui.explore_view import EXPLORE_SOURCES
    from metatv.gui.main_window_nav import _NavMixin

    host = _NavMixin()
    for name in (
        "epg_view", "discover_view", "preferences_view", "channels_list",
        "series_tree", "provider_editor", "search_controls", "_hidden_banner",
        "back_button", "breadcrumb_label", "stats_label",
        "search_chip", "epg_chip", "prefs_chip", "discover_chip",
    ):
        setattr(host, name, MagicMock())
    view = MagicMock()
    view.source = EXPLORE_SOURCES[key]
    host.explore_view = view
    host.explore_views = {key: view}
    host._ensure_explore_view = lambda k: host.explore_views[k]
    return host


class TestNavWiring:
    @pytest.mark.parametrize(
        "key,view_mode,title",
        [("favorites", "explore_favorites", "Favorites"),
         ("queue", "explore_queue", "Watch Queue"),
         ("recommended", "explore_recommended", "Recommended")],
    )
    def test_switch_activates_the_right_explore_view(self, key, view_mode, title):
        host = _nav_host(key)
        host.explore_view.isVisible.return_value = False
        host.switch_to_explore_view(key)
        assert host.view_mode == view_mode
        host.explore_view.setVisible.assert_called_with(True)
        host.explore_view.on_activate.assert_called_once()
        host.stats_label.setText.assert_called_with(title)

    @pytest.mark.parametrize("key", ["favorites", "queue", "recommended"])
    def test_hide_all_deactivates_and_hides_the_explore_view(self, key):
        host = _nav_host(key)
        host.explore_view.isVisible.return_value = True
        host._hide_all_content_views()
        host.explore_view.on_deactivate.assert_called_once()
        host.explore_view.setVisible.assert_called_with(False)

    def test_hide_all_leaves_an_invisible_explore_view_alone(self):
        host = _nav_host("queue")
        host.explore_view.isVisible.return_value = False
        host._hide_all_content_views()
        host.explore_view.on_deactivate.assert_not_called()

    def test_hide_all_survives_before_the_registry_exists(self):
        """_hide_all_content_views runs during setup_ui, before explore_views is set."""
        host = _nav_host("queue")
        del host.explore_views
        host._hide_all_content_views()   # must not raise

    @pytest.mark.parametrize("key", ["favorites", "queue", "recommended"])
    def test_deep_link_seam_resolves_every_explore_key(self, key):
        host = _nav_host(key)
        host.explore_view.isVisible.return_value = False
        assert host.navigate_to(f"view:{key}") is True
        host.explore_view.on_activate.assert_called_once()

    def test_deep_link_still_rejects_an_unknown_view(self):
        host = _nav_host("queue")
        assert host.navigate_to("view:nope") is False


class TestFullWidthAndClobberGuard:
    def test_switch_collapses_flanks_and_leaving_restores(self, qapp):
        """Every Explore view gets the full window, not just Watch History."""
        from PyQt6.QtWidgets import QWidget
        from metatv.gui.collapsible_splitter import CollapsibleSplitter

        host = _nav_host("recommended")
        host.explore_view.isVisible.return_value = False
        splitter = CollapsibleSplitter()
        for mw in (200, 400, 0):
            w = QWidget()
            if mw:
                w.setMinimumWidth(mw)
            splitter.addWidget(w)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.resize(1000, 400)
        splitter.setSizes([300, 500, 200])
        splitter.show()
        qapp.processEvents()
        host.main_splitter = splitter

        before = splitter.sizes()
        host.switch_to_explore_view("recommended")
        qapp.processEvents()
        assert splitter.sizes()[0] == 0 and splitter.sizes()[2] == 0, \
            "Explore activation collapses both flanking panels to zero"

        host.explore_view.isVisible.return_value = True
        host._hide_all_content_views()
        qapp.processEvents()
        assert splitter.sizes()[0] == before[0] and splitter.sizes()[2] == before[2], \
            "leaving Explore restores the flanks to their exact widths"

        splitter.hide()
        splitter.deleteLater()

    @pytest.mark.parametrize(
        "view_mode",
        ["history", "explore_favorites", "explore_queue", "explore_recommended"],
    )
    def test_layout_save_is_skipped_in_every_explore_mode(self, view_mode):
        """The flanks are collapsed to 0 in ALL four — none may clobber the config."""
        from metatv.gui.main_window import MainWindow

        cfg = SimpleNamespace(
            sidebar_width=340, details_pane_width=400, details_pane_visible=True,
            save=MagicMock(),
        )
        host = SimpleNamespace(
            view_mode=view_mode, config=cfg,
            main_splitter=SimpleNamespace(sizes=lambda: [0, 1200, 0]),
        )
        MainWindow.save_splitter_sizes(host)
        assert cfg.sidebar_width == 340 and cfg.details_pane_width == 400
        assert cfg.details_pane_visible is True
        cfg.save.assert_not_called()

    def test_explore_view_modes_covers_every_source(self):
        from metatv.gui.explore_view import EXPLORE_SOURCES, EXPLORE_VIEW_MODES
        assert EXPLORE_VIEW_MODES == {s.view_mode for s in EXPLORE_SOURCES.values()}
        assert "history" in EXPLORE_VIEW_MODES, "the original mode name is preserved"


# ---------------------------------------------------------------------------
# 4. Sidebar affordance — the shared "Explore →" link
# ---------------------------------------------------------------------------

def _section(cls, tmp_path, name):
    from metatv.core.config import Config
    config = Config(config_dir=tmp_path / name)
    db = _make_db(tmp_path / f"{name}.db")
    section = cls(config, db, None)
    return section, db


class TestSidebarExploreLinks:
    @pytest.mark.parametrize(
        "module,cls_name,key",
        [("history", "HistorySection", "history"),
         ("favorites", "FavoritesSection", "favorites"),
         ("queue", "WatchQueueSection", "queue"),
         ("recommended", "RecommendedSection", "recommended")],
    )
    def test_section_grows_the_link_and_emits_on_click(
        self, qapp, tmp_path, module, cls_name, key
    ):
        import importlib
        from metatv.gui.explore_view import EXPLORE_SOURCES

        cls = getattr(importlib.import_module(f"metatv.gui.sidebar.{module}"), cls_name)
        section, db = _section(cls, tmp_path, f"{key}_link")
        assert section.EXPLORE_KEY == key
        btn = section.explore_btn
        assert "Explore" in btn.text(), "one shared label across every entry point"
        assert btn.toolTip() == EXPLORE_SOURCES[key].link_tooltip, \
            "the rail and the view it opens describe themselves identically"

        seen: list = []
        section.exploreClicked.connect(lambda: seen.append(key))
        btn.click()
        qapp.processEvents()
        assert seen == [key], "clicking the link asks the host to open this Explore view"
        section.deleteLater()
        db.close()

    def test_a_section_without_an_explore_key_grows_no_link(self, qapp, tmp_path):
        from metatv.core.config import Config
        from metatv.gui.sidebar.base import CollapsibleSection

        section = CollapsibleSection(
            "Plain", "*", Config(config_dir=tmp_path / "plain")
        )
        assert section.EXPLORE_KEY is None
        assert not hasattr(section, "explore_btn"), "opt-in only"
        section.deleteLater()


# ---------------------------------------------------------------------------
# 5. What's New entry 196
# ---------------------------------------------------------------------------

def test_whats_new_entry_196_present_with_test_steps():
    from metatv.whats_new import WHATS_NEW
    entry = next((e for e in WHATS_NEW if e.id == 196), None)
    assert entry is not None, "What's New entry id=196 must be registered"
    assert entry.items, "entry must have items"
    assert entry.test_steps, "entry must carry a non-empty test_steps tuple"
