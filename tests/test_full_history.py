"""Behavioral tests for the Full Watch-History view (id 178).

Executes the changed paths and asserts the outcomes that would break:

1. **History data layer** (real ``Database`` on a tmp_path file, not ``:memory:``):
   ``load_history_ids`` / ``load_history_seed_rows`` return recently-watched rows in
   ``last_played`` order with ``watch_count`` / ``last_watched`` / watch-state
   populated, and — as a RECORD view — are NOT provider-gated (a row on an inactive
   provider still appears; a never-played row does not).
2. **View lifecycle** — ``ExploreView.on_activate`` (history source) seeds the embedded
   trail-map from history; ``on_deactivate`` releases it; empty history shows a status.
3. **Drill** — expanding a history stop fetches its similars through the SAME
   provider-scoped ``load_similar_rows`` chokepoint (inactive-provider neighbour gated
   out even though it is a valid *history* row).
4. **Nav wiring** — ``switch_to_full_history_view`` activates + is registered in
   ``_hide_all_content_views``; the ``navigate_to`` seam knows ``view:history``.
5. **What's New 178** present with non-empty ``test_steps``.
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
    return SimpleNamespace(
        preferred_version_prefixes=[],
        preferred_version_provider_ids=[],
        preferred_version_quality=None,
        filter_adult_mode="all",
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


def _history_seed_db(path: Path):
    """History-flavoured seed: four *played* titles (one on an INACTIVE provider) +
    one never-played title.  Mirrors the trail-map similarity seed so the real
    ``load_similar_rows`` still returns s1/s2 for the origin.

    last_played order (desc): o, s1, s2, sx.  n1 (never played) is excluded.
    """
    from metatv.core.database import ChannelDB, MetadataDB, ProviderDB

    db = _make_db(path)
    now = datetime.now()
    with db.session_scope() as session:
        session.add(ProviderDB(id="pa", name="Alpha", type="xtream", url="http://e",
                               username="u", password="p", is_active=True,
                               account_exp_date=now + timedelta(days=30)))
        session.add(ProviderDB(id="pz", name="Zeta", type="xtream", url="http://z",
                               username="u", password="p", is_active=False))
        session.flush()
        session.add(MetadataDB(id="m-o", title="The Sea Beast", year=2022,
                               rating=7.0, poster_url="http://p/o.jpg"))
        session.flush()
        o = ChannelDB(id="o", source_id=str(uuid.uuid4()), provider_id="pa",
                      name="The Sea Beast", media_type="movie",
                      content_key="tmdb:1|movie", detected_region="EN",
                      last_played=now, play_count=3)
        o.metadata_id = "m-o"
        session.add(o)
        session.add(ChannelDB(id="s1", source_id=str(uuid.uuid4()), provider_id="pa",
                              name="The Sea Wolf Beast", media_type="movie",
                              content_key="tmdb:2|movie", is_favorite=True,
                              watch_progress=90, last_played=now - timedelta(days=1),
                              play_count=1))
        session.add(ChannelDB(id="s2", source_id=str(uuid.uuid4()), provider_id="pa",
                              name="Deep Beast Sea", media_type="movie",
                              content_key="tmdb:3|movie", watch_completed=True,
                              watch_percent=100, last_played=now - timedelta(days=2),
                              play_count=2))
        # Played, but on an INACTIVE provider — a valid HISTORY row (record view, not
        # gated), yet must be gated OUT of the forward-looking similars drill.
        session.add(ChannelDB(id="sx", source_id=str(uuid.uuid4()), provider_id="pz",
                              name="Beast Below the Sea", media_type="movie",
                              content_key="tmdb:4|movie",
                              last_played=now - timedelta(days=3), play_count=1))
        # Never played → never in history.
        session.add(ChannelDB(id="n1", source_id=str(uuid.uuid4()), provider_id="pa",
                              name="Never Watched", media_type="movie",
                              content_key="tmdb:9|movie"))
        session.flush()
    return db


# ---------------------------------------------------------------------------
# 1. History data layer (real DB)
# ---------------------------------------------------------------------------

class TestHistoryDataLayer:
    def test_history_ids_ordered_and_ungated(self, tmp_path):
        from metatv.gui.trail_map_data import load_history_ids

        db = _history_seed_db(tmp_path / "ids.db")
        with db.session_scope(commit=False) as session:
            ids = load_history_ids(session)
        assert ids == ["o", "s1", "s2", "sx"], "last_played desc; never-played dropped"
        assert "sx" in ids, "record view — inactive-provider history still appears"
        assert "n1" not in ids, "a never-played channel is not history"
        db.close()

    def test_history_seed_rows_populate_extras_and_watch_state(self, tmp_path):
        from metatv.gui.trail_map_data import load_history_seed_rows

        db = _history_seed_db(tmp_path / "rows.db")
        with db.session_scope(commit=False) as session:
            rows = load_history_seed_rows(session)         # ids=None → self-seeds
        assert [r.id for r in rows] == ["o", "s1", "s2", "sx"], "order preserved"
        by_id = {r.id: r for r in rows}
        # watch_count = play_count; last_watched is a friendly non-empty string.
        assert by_id["o"].watch_count == 3
        assert by_id["s2"].watch_count == 2
        assert all(by_id[i].last_watched for i in ("o", "s1", "s2", "sx"))
        # Watch state carried so badges + Play/Resume label work: s1 partial, s2 done.
        assert by_id["s1"].watch_progress == 90 and by_id["s1"].watch_completed is False
        assert by_id["s2"].watch_completed is True
        # NOT provider-gated: the inactive-provider row is present in the seed.
        assert "sx" in by_id
        db.close()

    def test_seed_rows_hydrate_given_ids_in_order(self, tmp_path):
        from metatv.gui.trail_map_data import load_history_seed_rows

        db = _history_seed_db(tmp_path / "given.db")
        with db.session_scope(commit=False) as session:
            rows = load_history_seed_rows(session, ["s2", "o"])   # explicit order
        assert [r.id for r in rows] == ["s2", "o"], "given ids hydrated in that order"
        assert rows[1].watch_count == 3, "extras populated on the given-ids path too"
        db.close()

    def test_fmt_last_watched_buckets(self):
        from metatv.gui.trail_map_data import _fmt_last_watched

        now = datetime.now()
        assert _fmt_last_watched(now) == "just now"
        assert _fmt_last_watched(now - timedelta(days=1)) == "yesterday"
        assert _fmt_last_watched(now - timedelta(days=3)) == "3d ago"
        assert _fmt_last_watched(None) is None


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


def _make_full_history_view(db, qapp):
    from metatv.core.repositories import RepositoryFactory
    from metatv.gui.explore_view import EXPLORE_SOURCES, ExploreView

    def _inline_run_query(query_fn, on_result, *, token_ref=None, on_error=None):
        """Mirror MainWindow._run_query inline (bump token, run query_fn(repos))."""
        if token_ref is not None:
            token_ref[0] += 1
        try:
            with db.session_scope(commit=False) as session:
                data = query_fn(RepositoryFactory(session))
        except Exception as exc:  # pragma: no cover - defensive
            if on_error:
                on_error(exc)
            return
        on_result(data)

    view = ExploreView(
        None, _fake_config(), _FakeImageCache(), db, _FakeMetadataManager(),
        _inline_run_query, source=EXPLORE_SOURCES["history"],
    )
    # Swap the inner trail-map's real pool for an inline one so open()/expand run sync.
    view.trail_map._executor.shutdown(wait=False)
    view.trail_map._executor = _SyncExecutor()
    view.resize(1200, 800)
    view.show()
    qapp.processEvents()
    _LIVE.append(view)
    return view


# ---------------------------------------------------------------------------
# 2. View lifecycle
# ---------------------------------------------------------------------------

class TestFullHistoryView:
    def test_activate_seeds_history_into_the_trail_map(self, tmp_path, qapp):
        db = _history_seed_db(tmp_path / "view.db")
        view = _make_full_history_view(db, qapp)
        view.on_activate()                    # inline: ids → open() → seed rows
        assert [r.id for r in view.trail_map._seed_rows] == ["o", "s1", "s2", "sx"]
        assert view.trail_map.isVisible(), "the trail-map is shown when history exists"
        assert view._status.isHidden(), "the status line is hidden once seeded"
        # Header relabelled for history mode (not 'Explore').
        assert "Watch History" in view.trail_map._header_title.text()
        # A history extra made it all the way onto the cached DTO.
        assert view.trail_map._row_cache["o"].watch_count == 3
        db.close()

    def test_empty_history_shows_status_not_trail_map(self, tmp_path, qapp):
        db = _make_db(tmp_path / "empty.db")   # no channels at all
        view = _make_full_history_view(db, qapp)
        view.on_activate()
        assert view.trail_map.isHidden(), "no history → the trail-map stays hidden"
        assert view._status.isVisible()
        assert "No watch history" in view._status.text()
        db.close()

    def test_deactivate_releases_and_drops_late_result(self, tmp_path, qapp):
        db = _history_seed_db(tmp_path / "deact.db")
        view = _make_full_history_view(db, qapp)
        view.on_activate()
        assert view.trail_map.isVisible()
        token_before = view._token[0]
        view.on_deactivate()
        assert view.trail_map.isHidden(), "on_deactivate hides the trail-map"
        assert view._token[0] > token_before, "token bumped so a late result is dropped"
        db.close()


# ---------------------------------------------------------------------------
# 3. Drill uses the shared, provider-scoped similars loader
# ---------------------------------------------------------------------------

class TestHistoryDrill:
    def test_expanding_a_history_stop_drills_scoped_similars(self, tmp_path, qapp):
        from metatv.gui.trail_map_data import load_similar_rows

        db = _history_seed_db(tmp_path / "drill.db")
        view = _make_full_history_view(db, qapp)
        # The embedded view uses the SHARED, provider-scoped similars chokepoint.
        assert view.trail_map._similars_loader is load_similar_rows
        view.on_activate()
        view.trail_map._select_seed_row("o")     # expand the origin (fetch runs inline)
        drilled = {r.id for r in view.trail_map._similars_cache["o"]}
        assert {"s1", "s2"} <= drilled, "genuine similars appear in the drill column"
        assert "sx" not in drilled, "inactive-provider neighbour gated from similars"
        assert view.trail_map._cols_layout.count() - 1 == 2, "trail + one drill column"
        db.close()


# ---------------------------------------------------------------------------
# 4. Nav wiring — switch + _hide_all_content_views registration + deep-link seam
# ---------------------------------------------------------------------------

def _nav_host(key: str = "history"):
    """A bare ``_NavMixin`` with just the attributes the two nav methods touch.

    ``host.explore_view`` is the mocked Explore view for *key*; the host's lazy
    construction seam (``_ensure_explore_view``) hands it back.
    """
    from metatv.gui.explore_view import EXPLORE_SOURCES
    from metatv.gui.main_window_nav import _NavMixin

    host = _NavMixin()
    # _hide_all_content_views() resets the channel-render banners, which
    # live outside every view; this skeleton host is not a full MainWindow
    # so it needs that method wired in (shared factory — see conftest).
    from tests.conftest import wire_hide_channel_banners
    wire_hide_channel_banners(host)
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
    def test_hide_all_deactivates_and_hides_full_history(self):
        host = _nav_host()
        host.explore_view.isVisible.return_value = True
        host._hide_all_content_views()
        host.explore_view.on_deactivate.assert_called_once()
        host.explore_view.setVisible.assert_called_with(False)

    def test_switch_activates_history_view(self):
        host = _nav_host()
        host.explore_view.isVisible.return_value = False
        host.switch_to_full_history_view()
        assert host.view_mode == "history"
        # _hide_all first (setVisible False), then this view is shown (last call True).
        host.explore_view.setVisible.assert_called_with(True)
        host.explore_view.on_activate.assert_called_once()
        host.stats_label.setText.assert_called_with("Watch History")

    def test_navigate_to_seam_knows_history(self):
        from metatv.gui.main_window_nav import _NAV_VIEW_TARGETS
        assert _NAV_VIEW_TARGETS["history"] == ("switch_to_full_history_view", None)


# ---------------------------------------------------------------------------
# 4b. History full-width — activating collapses the flanks, leaving restores them
# ---------------------------------------------------------------------------

def _real_splitter(qapp, sizes=(300, 500, 200), min_widths=(0, 0, 0)):
    """A REAL CollapsibleSplitter holding 3 real widgets, sized + shown."""
    from PyQt6.QtWidgets import QWidget
    from metatv.gui.collapsible_splitter import CollapsibleSplitter

    splitter = CollapsibleSplitter()
    for mw in min_widths:
        w = QWidget()
        if mw:
            w.setMinimumWidth(mw)
        splitter.addWidget(w)
    # Mirror the real main_splitter's stretch: only the middle (content) panel
    # stretches, so expand_panel restores the flanks to their exact widths.
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    splitter.setStretchFactor(2, 0)
    splitter.resize(1000, 400)
    splitter.setSizes(list(sizes))
    splitter.show()
    qapp.processEvents()
    return splitter


class TestHistoryFullWidth:
    def test_switch_collapses_flanks_and_leaving_restores(self, qapp):
        """Entering history collapses sidebar(0)+details(2) to 0; leaving restores them."""
        host = _nav_host()
        host.explore_view.isVisible.return_value = False
        # Real sidebar has a 200px minimum — prove the collapse still reaches 0.
        splitter = _real_splitter(qapp, min_widths=(200, 400, 0))
        host.main_splitter = splitter

        before = splitter.sizes()
        assert before[0] > 0 and before[2] > 0, "both flanks start open"

        host.switch_to_full_history_view()
        qapp.processEvents()
        collapsed = splitter.sizes()
        assert collapsed[0] == 0 and collapsed[2] == 0, \
            "history activation collapses both flanking panels to zero"

        # Simulate leaving history (switch to any other view runs _hide_all_content_views).
        host.explore_view.isVisible.return_value = True
        host._hide_all_content_views()
        qapp.processEvents()
        restored = splitter.sizes()
        assert restored[0] > 0 and restored[2] > 0, "leaving history reopens both flanks"
        assert restored[0] == before[0] and restored[2] == before[2], \
            "flanks restore to their exact pre-collapse widths"

        splitter.hide()
        splitter.deleteLater()

    def test_leaving_history_does_not_reopen_a_flank_the_user_had_shut(self, qapp):
        """Only panels WE auto-collapsed are restored — a pre-collapsed details pane
        (the common ``details_pane_visible=False`` default) stays shut on the way out."""
        host = _nav_host()
        host.explore_view.isVisible.return_value = False
        splitter = _real_splitter(qapp, min_widths=(200, 400, 0))
        splitter.collapse_panel(2)          # user already had the details pane shut
        qapp.processEvents()
        assert splitter.is_panel_collapsed(2)
        host.main_splitter = splitter

        host.switch_to_full_history_view()
        qapp.processEvents()
        assert splitter.sizes()[0] == 0, "sidebar still auto-collapses"

        host.explore_view.isVisible.return_value = True
        host._hide_all_content_views()
        qapp.processEvents()
        assert splitter.sizes()[0] > 0, "sidebar (which we collapsed) is restored"
        assert splitter.is_panel_collapsed(2), \
            "details pane the user had shut is NOT popped open on the way out"

        splitter.hide()
        splitter.deleteLater()

    def test_switch_without_main_splitter_does_not_raise(self):
        """The nav host in TestNavWiring has no main_splitter — the guard must hold."""
        host = _nav_host()          # no main_splitter attribute set
        host.explore_view.isVisible.return_value = False
        host.switch_to_full_history_view()          # must not AttributeError
        host.explore_view.isVisible.return_value = True
        host._hide_all_content_views()              # nor here


# ---------------------------------------------------------------------------
# 4c. Splitter handle — discoverable grip affordance + collapse round-trip
# ---------------------------------------------------------------------------

class TestCollapsibleSplitterHandle:
    def test_handle_is_discoverable_and_round_trips(self, qapp):
        splitter = _real_splitter(qapp, sizes=(300, 400, 200))
        handle = splitter.handle(1)
        assert handle is not None

        # (i) opted into the pointing-hand affordance via cursor_affordance.
        assert handle.property("clickable") is True
        # (ii) advertises the gesture with a non-empty tooltip.
        assert handle.toolTip(), "handle carries a collapse/expand tooltip"
        # (iii) has real thickness so the grip is visible (was near-zero before).
        assert handle.sizeHint().width() > 0
        assert splitter.handleWidth() >= handle.GRIP_THICKNESS

        # (iv) collapse → expand round-trips the panel's pre-collapse size.
        before = splitter.sizes()[2]
        assert before > 0
        splitter.collapse_panel(2)
        qapp.processEvents()
        assert splitter.sizes()[2] == 0
        splitter.expand_panel(2)
        qapp.processEvents()
        assert splitter.sizes()[2] == before, "expand restores the exact pre-collapse size"

        splitter.hide()
        splitter.deleteLater()

    def test_collapse_reaches_zero_despite_min_width(self, qapp):
        """A min-width panel must still collapse fully to 0 (the sidebar case)."""
        splitter = _real_splitter(qapp, min_widths=(200, 400, 0))
        splitter.collapse_panel(0)
        qapp.processEvents()
        assert splitter.sizes()[0] == 0, \
            "collapse lifts childrenCollapsible so a 200px-min panel reaches 0"
        assert splitter.childrenCollapsible() is False, \
            "drag-collapse protection restored after the programmatic collapse"
        splitter.hide()
        splitter.deleteLater()


# ---------------------------------------------------------------------------
# 4d. Clobber guard — no layout save while history has the flanks collapsed to 0
# ---------------------------------------------------------------------------

class TestLayoutSaveClobberGuard:
    def test_save_splitter_sizes_skipped_while_history_active(self):
        from metatv.gui.main_window import MainWindow

        cfg = SimpleNamespace(
            sidebar_width=340, details_pane_width=400, details_pane_visible=True,
            save=MagicMock(),
        )
        host = SimpleNamespace(
            view_mode="history", config=cfg,
            main_splitter=SimpleNamespace(sizes=lambda: [0, 1200, 0]),
        )
        MainWindow.save_splitter_sizes(host)
        assert cfg.sidebar_width == 340, "history guard must not clobber sidebar_width"
        assert cfg.details_pane_width == 400, "history guard must not clobber details width"
        assert cfg.details_pane_visible is True, "history guard must not flip visibility off"
        cfg.save.assert_not_called()

    def test_save_splitter_sizes_writes_when_not_in_history(self):
        from metatv.gui.main_window import MainWindow

        cfg = SimpleNamespace(
            sidebar_width=0, details_pane_width=0, details_pane_visible=False,
            save=MagicMock(),
        )
        host = SimpleNamespace(
            view_mode="list", config=cfg,
            main_splitter=SimpleNamespace(sizes=lambda: [340, 1200, 400]),
        )
        MainWindow.save_splitter_sizes(host)      # _persist defaults True
        assert cfg.sidebar_width == 340 and cfg.details_pane_width == 400, \
            "outside history the real widths are persisted as before"
        assert cfg.details_pane_visible is True
        cfg.save.assert_called_once()


# ---------------------------------------------------------------------------
# 5. What's New entry 178
# ---------------------------------------------------------------------------

def test_whats_new_entry_178_present_with_test_steps():
    from metatv.whats_new import WHATS_NEW
    entry = next((e for e in WHATS_NEW if e.id == 178), None)
    assert entry is not None, "What's New entry id=178 must be registered"
    assert entry.version == "0.14.1"
    assert entry.date == "2026-07-31"
    assert entry.items, "entry must have items"
    assert entry.test_steps, "entry must carry a non-empty test_steps tuple"


def test_whats_new_entry_185_present_with_test_steps():
    from metatv.whats_new import WHATS_NEW
    entry = next((e for e in WHATS_NEW if e.id == 185), None)
    assert entry is not None, "What's New entry id=185 must be registered"
    assert entry.items, "entry must have items"
    assert entry.test_steps, "entry must carry a non-empty test_steps tuple"
