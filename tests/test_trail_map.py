"""Behavioral tests for the Explore trail-map (id 176).

Executes the changed paths and asserts the outcomes that would break:

1. **Data layer** (real ``Database`` on a tmp_path file, not ``:memory:``):
   ``load_seed_rows`` hydrates + orders the seed; ``load_similar_rows`` returns the
   scoped neighbours and honours the ``excluded_provider_ids`` gate.
2. **Columns render from a seed**, and **expanding a stop** fetches its similars and
   renders a new column; **de-dup** keeps a path title from reappearing.
3. **Detail strip** reflects the selected item + the 3 Play states; **favourite** and
   **watched** toggles emit the right intent; sentiment actions are mutually exclusive.
4. **Data-source-agnostic API** — injectable seed/similars loaders (the Watch-History
   reuse seam).
5. **Entry point** — the lightbox's Explore button seeds the nav trail.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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
    )


class _FakeImageCache:
    """Stand-in ImageCache: exposes the image_loaded signal + no-op fetch."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class _IC(QObject):
            image_loaded = pyqtSignal(str, object)
            def get_image_sync(self, url):  # noqa: D401
                return None
            def get_image_async(self, url, provider_urls=None):
                return None
        self._ic = _IC()

    def __getattr__(self, name):
        return getattr(self._ic, name)


class _PixImageCache:
    """ImageCache stand-in whose ``get_image_sync`` returns a real (non-null) pixmap.

    Lets the Part-C column-poster-peek path resolve synchronously so the enlarge
    emit is deterministic (no background image load to race)."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal
        from PyQt6.QtGui import QPixmap

        pix = QPixmap(10, 15)  # sized → not null

        class _IC(QObject):
            image_loaded = pyqtSignal(str, object)
            def get_image_sync(self, url):  # noqa: D401
                return pix
            def get_image_async(self, url, provider_urls=None):
                return None
        self._ic = _IC()

    def __getattr__(self, name):
        return getattr(self._ic, name)


class _FakeMetadataManager:
    async def get_metadata(self, channel_id, force_refresh=False):
        return None


def _seed_db(path: Path):
    """Origin 'o' + two genuine similars ('s1' partial, 's2' completed) + a similar on
    an INACTIVE provider ('sx') that the scoping gate must exclude."""
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
                      content_key="tmdb:1|movie", detected_region="EN")
        o.metadata_id = "m-o"
        session.add(o)
        session.add(ChannelDB(id="s1", source_id=str(uuid.uuid4()), provider_id="pa",
                              name="The Sea Wolf Beast", media_type="movie",
                              content_key="tmdb:2|movie", is_favorite=True,
                              watch_progress=90))
        session.add(ChannelDB(id="s2", source_id=str(uuid.uuid4()), provider_id="pa",
                              name="Deep Beast Sea", media_type="movie",
                              content_key="tmdb:3|movie", watch_completed=True))
        session.add(ChannelDB(id="sx", source_id=str(uuid.uuid4()), provider_id="pz",
                              name="Beast Below the Sea", media_type="movie",
                              content_key="tmdb:4|movie"))
        session.flush()
    return db


# ---------------------------------------------------------------------------
# 1. Data layer (real DB)
# ---------------------------------------------------------------------------

class TestDataLayer:
    def test_seed_rows_hydrate_and_preserve_order(self, tmp_path):
        from metatv.gui.trail_map_data import load_seed_rows

        db = _seed_db(tmp_path / "seed.db")
        with db.session_scope(commit=False) as session:
            rows = load_seed_rows(session, ["s1", "o"])
        assert [r.id for r in rows] == ["s1", "o"], "order must match the id list"
        origin = next(r for r in rows if r.id == "o")
        assert origin.title == "The Sea Beast"
        assert origin.year == 2022
        assert origin.rating == 7.0
        assert origin.poster_url == "http://p/o.jpg"
        assert origin.lang == "EN"
        assert origin.dedup_key == "tmdb:1|movie"
        s1 = next(r for r in rows if r.id == "s1")
        assert s1.is_favorite is True and s1.watch_progress == 90
        db.close()

    def test_similar_rows_scoped_and_gated(self, tmp_path):
        from metatv.gui.trail_map_data import load_similar_rows

        db = _seed_db(tmp_path / "sim.db")
        with db.session_scope(commit=False) as session:
            # No gate → the inactive-provider neighbour CAN appear.
            open_ids = {r.id for r in load_similar_rows(session, "o", config=None)}
            # Gate the inactive provider → its neighbour must be excluded.
            gated_ids = {r.id for r in load_similar_rows(
                session, "o", excluded_provider_ids={"pz"}, config=None)}
        assert "o" not in open_ids, "origin never appears among its own similars"
        assert {"s1", "s2"} <= open_ids
        assert "sx" in open_ids, "un-gated, the pz neighbour is a candidate"
        assert "sx" not in gated_ids, "the excluded-provider neighbour must be gated out"
        db.close()


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------

class _SyncExecutor:
    """Runs submitted work inline so the worker→slot path is exercised deterministically
    (no background thread — the real thread pool's timing would race the assertions)."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, wait=False):
        pass


_LIVE_VIEWS: list = []


@pytest.fixture(autouse=True)
def _cleanup_views(qapp):
    """Tear down any TrailMapView + host built during a test (no stray widgets/threads)."""
    yield
    while _LIVE_VIEWS:
        tm, host = _LIVE_VIEWS.pop()
        try:
            tm.shutdown()
            tm.hide()
            tm.deleteLater()
            host.hide()
            host.deleteLater()
        except Exception:
            pass
    qapp.processEvents()


def _make_view(db, qapp, image_cache=None, **kw):
    from PyQt6.QtWidgets import QWidget
    from metatv.gui.trail_map_view import TrailMapView

    host = QWidget()
    host.resize(1400, 900)
    host.show()
    tm = TrailMapView(host, _fake_config(), image_cache or _FakeImageCache(), db,
                      _FakeMetadataManager(), **kw)
    # Swap the real thread pool for an inline one so open()/expand run synchronously.
    tm._executor.shutdown(wait=False)
    tm._executor = _SyncExecutor()
    tm._host_ref = host  # keep host alive
    _LIVE_VIEWS.append((tm, host))
    return tm


def _rows_in_columns(tm):
    from metatv.gui.trail_map_view import _TrailRow
    return tm.findChildren(_TrailRow)


# ---------------------------------------------------------------------------
# 2. Columns render + expand + de-dup
# ---------------------------------------------------------------------------

class TestColumnsAndExpand:
    def test_seed_renders_trail_column(self, tmp_path, qapp):
        # A MULTI-item trail renders a single trail column and does NOT auto-drill
        # (single-item auto-drill is covered in TestSingleItemAutoDrill).
        db = _seed_db(tmp_path / "cols.db")
        tm = _make_view(db, qapp)
        tm.open(["o", "s1"])              # inline executor loads the seed synchronously
        assert [r.title for r in tm._seed_rows] == ["The Sea Beast", "The Sea Wolf Beast"]
        assert tm._selected_id == "s1", "the last (current) stop is auto-selected"
        assert tm._drill == [], "a multi-item trail is not auto-drilled"
        # One column (the trail) with two rows.
        assert tm._cols_layout.count() - 1 == 1
        rows = _rows_in_columns(tm)
        assert len(rows) == 2
        db.close()

    def test_expanding_a_stop_fetches_and_renders_a_new_column(self, tmp_path, qapp):
        db = _seed_db(tmp_path / "expand.db")
        tm = _make_view(db, qapp)
        tm.open(["o"])
        tm._select_seed_row("o")          # user expands the seed stop (fetch runs inline)
        assert tm._drill == ["o"]
        assert {r.id for r in tm._similars_cache["o"]} >= {"s1", "s2"}
        assert "sx" not in {r.id for r in tm._similars_cache["o"]}, "gate applied"
        assert tm._cols_layout.count() - 1 == 2, "trail + one drilled column"
        db.close()

    def test_dedup_keeps_a_path_title_out_of_the_next_column(self, tmp_path, qapp):
        db = _seed_db(tmp_path / "dedup.db")
        tm = _make_view(db, qapp)
        tm.open(["o"])
        tm._select_seed_row("o")
        raw = tm._similars_cache["o"]
        shown = tm._filter_path(raw, upto_index=0)
        assert all(r.id != "o" for r in shown), "the origin (on the path) is filtered"
        # A candidate sharing the origin's dedup_key would also be filtered.
        from metatv.gui.trail_map_data import TrailRowDTO
        dupe = TrailRowDTO(
            id="dupe", title="Alt", year=None, poster_url=None, media_type="movie",
            provider_id="pa", lang="", rating=None, user_rating=0, in_queue=False,
            is_favorite=False, is_suppressed=False, watch_progress=0,
            watch_completed=False, watch_percent=0, dedup_key="tmdb:1|movie",
        )
        assert not tm._filter_path([dupe], upto_index=0), "same content_key as origin → dropped"
        db.close()


# ---------------------------------------------------------------------------
# 2b. Single-item trail auto-expands on open (Part A)
# ---------------------------------------------------------------------------

class TestSingleItemAutoDrill:
    def test_single_seed_auto_drills(self, tmp_path, qapp):
        """A 1-id seed has one possible next action, so it drills on open: its
        similars are fetched, the drilled column renders and its detail populates."""
        db = _seed_db(tmp_path / "auto1.db")
        tm = _make_view(db, qapp)
        tm.open(["o"])                     # single-item trail → auto-drill (inline)
        assert tm._drill == ["o"], "a 1-item trail auto-drills its only stop"
        assert "o" in tm._similars_cache, "similars fetched for the auto-drilled stop"
        assert {r.id for r in tm._similars_cache["o"]} >= {"s1", "s2"}
        assert tm._cols_layout.count() - 1 == 2, "trail + the auto-drilled column"
        assert tm._selected_id == "o", "the auto-drilled stop is selected"
        assert "o" in tm._detail_cache, "the selected stop's detail was fetched/populated"
        assert tm._detail._title_lbl.text() == "The Sea Beast"
        db.close()

    def test_multi_seed_does_not_auto_drill(self, tmp_path, qapp):
        """A 2+-id seed (e.g. the Full-History trail) must NOT auto-fetch every
        stop's similars — it waits for the user to pick a stop to expand."""
        db = _seed_db(tmp_path / "auto2.db")
        tm = _make_view(db, qapp)
        tm.open(["o", "s1"])               # multi-item trail → NO auto-drill
        assert tm._drill == [], "a multi-item trail does not auto-drill"
        assert tm._similars_cache == {}, "no premature similars fetch for a multi-item trail"
        assert tm._cols_layout.count() - 1 == 1, "only the trail column"
        assert tm._selected_id == "s1", "the current (last) stop is selected"
        db.close()


# ---------------------------------------------------------------------------
# 2c. Column-row poster click enlarges (peek), never drills (Part C)
# ---------------------------------------------------------------------------

def _press_event():
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(2, 2), QPointF(2, 2),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


class TestColumnPosterEnlarge:
    def test_thumb_press_is_consumed_and_emits_clicked(self, qapp):
        """The poster thumbnail emits ``clicked`` and CONSUMES the press (accepts
        it) so it never propagates to the row's select/drill handler."""
        from metatv.gui.trail_map_view import _ClickableThumb
        thumb = _ClickableThumb("A")
        fired = []
        thumb.clicked.connect(lambda: fired.append(1))
        ev = _press_event()
        thumb.mousePressEvent(ev)
        assert fired == [1], "thumb press emits clicked"
        assert ev.isAccepted(), "thumb press is consumed (won't select/drill the row)"

    def test_row_relays_thumb_click_as_poster_clicked(self, qapp):
        """The row relays its thumb's click as ``poster_clicked(id)`` (distinct from
        the whole-row ``clicked``)."""
        from metatv.gui.trail_map_view import _TrailRow
        row = _TrailRow(_dto(id="r1", title="Row One"))
        peeks, selects = [], []
        row.poster_clicked.connect(lambda cid: peeks.append(cid))
        row.clicked.connect(lambda cid: selects.append(cid))
        row.thumb.clicked.emit()
        assert peeks == ["r1"], "thumb click relays as poster_clicked with the row id"
        assert selects == [], "a poster click does NOT fire the row select"

    def test_column_poster_click_enlarges_not_drills(self, tmp_path, qapp):
        """Clicking a rendered column row's poster emits the trail-map's
        ``poster_expand_requested`` (with the loaded pixmap) and leaves the drill /
        selection untouched."""
        db = _seed_db(tmp_path / "peek.db")
        tm = _make_view(db, qapp, image_cache=_PixImageCache())
        tm.open(["o", "s1"])               # 2-item → no auto-drill; trail has 2 rows
        drill_before = list(tm._drill)
        selected_before = tm._selected_id
        got = []
        tm.poster_expand_requested.connect(lambda pix: got.append(pix))
        # Find the rendered "o" row (it has a metadata poster_url) and click its thumb.
        o_row = next(r for r in _rows_in_columns(tm) if r._id == "o")
        o_row.thumb.clicked.emit()
        assert len(got) == 1 and not got[0].isNull(), "poster peek emitted a pixmap"
        assert tm._drill == drill_before, "poster peek must not change the drill"
        assert tm._selected_id == selected_before, "poster peek must not change selection"
        db.close()


# ---------------------------------------------------------------------------
# 2d. Path-aware column highlighting (breadcrumb, not leaf-id match) — Part E
# ---------------------------------------------------------------------------

def _columns_in_order(tm):
    from metatv.gui.trail_map_view import _TrailColumn
    out = []
    for i in range(tm._cols_layout.count()):
        w = tm._cols_layout.itemAt(i).widget()
        if isinstance(w, _TrailColumn):
            out.append(w)
    return out


def _selected_ids(col):
    from metatv.gui.trail_map_view import _TrailRow
    return [r._id for r in col.findChildren(_TrailRow) if r._selected]


def _row_ids(col):
    from metatv.gui.trail_map_view import _TrailRow
    return [r._id for r in col.findChildren(_TrailRow)]


class TestPathAwareHighlight:
    def test_breadcrumb_highlight_one_per_column_leaf_once(self, tmp_path, qapp):
        """A 3-deep drill lights the DRILLED chain one-per-column; the leaf, which
        also appears as a similar in an earlier column, is highlighted exactly once
        (in its own column) and NOT in the earlier column."""
        db = _seed_db(tmp_path / "hl.db")

        # Deterministic adjacency via injected loaders (independent of the heuristic).
        # Note: the leaf "C" is a similar of BOTH the root R and of A.
        adj = {
            "R": [_dto(id="A", title="A", dedup_key="A"),
                  _dto(id="C", title="C", dedup_key="C")],
            "A": [_dto(id="C", title="C", dedup_key="C"),
                  _dto(id="X", title="X", dedup_key="X")],
            "C": [_dto(id="D", title="D", dedup_key="D")],
        }

        def fake_seed(session, ids):
            return [_dto(id="R", title="Root", dedup_key="R")]

        def fake_sim(session, parent_id, *, excluded_provider_ids=None, config=None, limit=20):
            return list(adj.get(parent_id, []))

        tm = _make_view(db, qapp, seed_loader=fake_seed, similars_loader=fake_sim)
        tm.open(["R"])                       # single seed → auto-drill R (Part A)
        tm._select_drill_row(0, "A")         # drill A
        tm._select_drill_row(1, "C")         # drill C (the leaf)
        assert tm._drill == ["R", "A", "C"]

        cols = _columns_in_order(tm)
        assert len(cols) == 4, "trail + 3 drilled columns"
        # Each column highlights exactly its breadcrumb item (the _drill chain).
        assert _selected_ids(cols[0]) == ["R"], "trail highlights the explored root"
        assert _selected_ids(cols[1]) == ["A"], "SIMILAR TO R highlights the drilled child A"
        assert _selected_ids(cols[2]) == ["C"], "SIMILAR TO A highlights the drilled child C"
        assert _selected_ids(cols[3]) == [], "the frontier column has no selected child"
        # The leaf C is a similar of R too — present in col 1 but NOT highlighted there.
        assert "C" in _row_ids(cols[1]), "the leaf also appears earlier as a similar"
        assert "C" not in _selected_ids(cols[1]), "leaf must NOT light up in the earlier column"
        # …and it is highlighted exactly ONCE across all columns.
        from metatv.gui.trail_map_view import _TrailRow
        leaf_hits = sum(
            1 for col in cols for r in col.findChildren(_TrailRow)
            if r._id == "C" and r._selected
        )
        assert leaf_hits == 1, "the leaf is highlighted exactly once"
        db.close()


# ---------------------------------------------------------------------------
# 2e. Row title/year layout (Part F) + shared lang chip (Part G)
# ---------------------------------------------------------------------------

class TestRowTitleYearLayout:
    def test_year_shown_once(self, qapp):
        """A trail row shows the year on its title line only — NOT also on the
        shared badge line (which would render it twice)."""
        from PyQt6.QtWidgets import QLabel
        from metatv.gui.trail_map_view import _TrailRow
        row = _TrailRow(_dto(id="r", title="Some Title", year=2022, lang="EN"))
        year_labels = [l for l in row.findChildren(QLabel) if l.text() == "2022"]
        assert len(year_labels) == 1, "the year must appear exactly once (title line only)"

    def test_title_and_year_share_baseline(self, qapp):
        from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
        from metatv.gui.trail_map_view import _TrailRow
        host = QWidget()
        host.resize(420, 120)
        row = _TrailRow(_dto(id="r", title="Aligned Title", year=2019))
        QVBoxLayout(host).addWidget(row)
        host.show()
        qapp.processEvents()
        title_lbl = next(l for l in row.findChildren(QLabel) if l.text() == "Aligned Title")
        year_lbl = next(l for l in row.findChildren(QLabel) if l.text() == "2019")
        # Both AlignBottom in the same row → their bottom edges line up (one line).
        assert abs(title_lbl.geometry().bottom() - year_lbl.geometry().bottom()) <= 3
        host.hide()

    def test_long_title_wraps_two_lines_and_elides_inside_column(self, qapp):
        """A long title wraps to at most 2 lines, ellipsizes the overflow, and every
        line stays within the (fixed) column width (Part H). Flows to Full-History."""
        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        from metatv.gui.trail_map_view import _TrailRow, _ElidedTitleLabel, _DRILL_COL_W
        long = ("Eternal Sunshine Of The Spotless Mind Special Extended "
                "4K Remastered Collectors Edition")
        host = QWidget()
        host.setFixedWidth(_DRILL_COL_W)
        host.resize(_DRILL_COL_W, 140)
        row = _TrailRow(_dto(id="r", title=long))
        QVBoxLayout(host).addWidget(row)
        host.show()
        qapp.processEvents()
        lbl = row.findChild(_ElidedTitleLabel)
        assert lbl is not None
        shown = lbl.text()
        assert shown.count("\n") <= 1, f"title must be ≤ 2 lines; got {shown!r}"
        assert "…" in shown, "a very long title must be ellipsized"
        fm = lbl.fontMetrics()
        for line in shown.split("\n"):
            assert fm.horizontalAdvance(line) <= lbl.width() + 2, (
                f"line {line!r} overflows the column width {lbl.width()}"
            )
        assert lbl.toolTip() == long, "the full title is preserved as the tooltip"
        host.hide()


class TestSharedLangChip:
    def test_sim_badges_lang_uses_shared_bordered_chip(self, qapp):
        from PyQt6.QtWidgets import QLabel
        from metatv.gui import theme as _theme
        from metatv.gui.sim_badges import make_sim_badges
        w = make_sim_badges({"lang": "LAT", "rating": 8.0, "year": 2020})
        lang_lbl = next(l for l in w.findChildren(QLabel) if l.text() == "LAT")
        assert lang_lbl.styleSheet() == _theme.LANG_CHIP, (
            "the sim-badges lang label must use the shared canonical LANG_CHIP token"
        )
        # The canonical chip is the BORDERED style (background + radius), not the old
        # borderless muted text.
        assert "background" in _theme.LANG_CHIP and "border-radius" in _theme.LANG_CHIP

    def test_detail_strip_and_sim_badges_share_the_token(self, qapp):
        """One source of truth: the trail-map detail strip renders the lang chip with
        the SAME token the shared sim-badges renderer uses.

        Matches the ROLE NAME rather than a specific call form. Styling now goes
        through ``theme.style(widget, "ROLE")`` (#277) instead of
        ``setStyleSheet(_theme.ROLE)``, and pinning the old spelling made a
        mechanical migration look like a broken invariant.
        """
        import inspect
        from metatv.gui import trail_map_detail, sim_badges
        for module in (trail_map_detail, sim_badges):
            src = inspect.getsource(module)
            assert "LANG_CHIP" in src, (
                f"{module.__name__} no longer references the shared LANG_CHIP role"
            )


# ---------------------------------------------------------------------------
# 3. Detail strip — 3 Play states + toggles
# ---------------------------------------------------------------------------

def _dto(**kw):
    from metatv.gui.trail_map_data import TrailRowDTO
    base = dict(
        id="x", title="X", year=2000, poster_url=None, media_type="movie",
        provider_id="pa", lang="EN", rating=None, user_rating=0, in_queue=False,
        is_favorite=False, is_suppressed=False, watch_progress=0,
        watch_completed=False, watch_percent=0, dedup_key="k",
    )
    base.update(kw)
    return TrailRowDTO(**base)


class TestDetailStrip:
    def test_three_play_states(self, qapp):
        from metatv.gui.trail_map_detail import TrailDetailStrip
        d = TrailDetailStrip()
        d.populate(_dto(watch_progress=0, watch_completed=False))
        assert d._play_btn.text().endswith("Play")
        d.populate(_dto(watch_progress=754, watch_completed=False))
        assert "Resume 12:34" in d._play_btn.text()
        d.populate(_dto(watch_completed=True))
        assert "Play again" in d._play_btn.text()

    def test_play_vs_resume_signal(self, qapp):
        from metatv.gui.trail_map_detail import TrailDetailStrip
        d = TrailDetailStrip()
        played, resumed = [], []
        d.play_requested.connect(lambda: played.append(1))
        d.resume_requested.connect(lambda: resumed.append(1))
        d.populate(_dto(watch_progress=0))          # none → Play
        d._play_btn.click()
        d.populate(_dto(watch_progress=120))        # partial → Resume
        d._play_btn.click()
        assert played == [1] and resumed == [1]

    def test_watched_badge_toggles_bool(self, qapp):
        from metatv.gui.trail_map_detail import TrailDetailStrip
        d = TrailDetailStrip()
        got = []
        d.watched_toggled.connect(lambda on: got.append(on))
        d.populate(_dto(watch_completed=False))     # not watched → click marks (True)
        d._on_watched_badge()
        d.populate(_dto(watch_completed=True))      # watched → click unmarks (False)
        d._on_watched_badge()
        assert got == [True, False]

    def test_favorite_star_state_and_signal(self, qapp):
        from metatv.gui.trail_map_detail import TrailDetailStrip
        from metatv.gui import icons as _icons
        d = TrailDetailStrip()
        fired = []
        d.favorite_clicked.connect(lambda: fired.append(1))
        d.populate(_dto(is_favorite=True))
        assert d._fav_star.isChecked() is True
        assert d._fav_star.text() == _icons.favorite_icon
        d._fav_star.click()
        assert fired == [1]

    def test_overview_only_when_available(self, qapp):
        from metatv.gui.trail_map_detail import TrailDetailStrip
        d = TrailDetailStrip()
        d.populate(_dto(id="a"))
        d.set_metadata("a", {})                      # no plot
        # (isHidden reflects the explicit hide/show flag regardless of an unshown parent)
        assert d._overview_lbl.isHidden()
        d.set_metadata("a", {"plot": "A relentless hunt.", "cast": "Zoe S.",
                             "director": "Chris W."})
        assert not d._overview_lbl.isHidden()
        assert "relentless" in d._overview_lbl.text()
        assert not d._crew_lbl.isHidden()
        assert "dir. Chris W." in d._crew_lbl.text()

    def test_stale_metadata_dropped(self, qapp):
        from metatv.gui.trail_map_detail import TrailDetailStrip
        d = TrailDetailStrip()
        d.populate(_dto(id="current"))
        d.set_metadata("stale", {"plot": "should be ignored"})
        assert d._overview_lbl.isHidden()


# ---------------------------------------------------------------------------
# 4. SentimentBar — mutual exclusion + independent queue
# ---------------------------------------------------------------------------

class TestSentimentBar:
    def test_mutual_exclusion(self, qapp):
        from metatv.gui.sentiment_bar import SentimentBar
        sb = SentimentBar()
        rates, supp = [], []
        sb.rating_clicked.connect(lambda r: rates.append(r))
        sb.suppression_toggled.connect(lambda o: supp.append(o))
        sb._like_btn.click()
        assert sb._like_btn.isChecked() and not sb._dislike_btn.isChecked()
        sb._dislike_btn.click()
        assert sb._dislike_btn.isChecked() and not sb._like_btn.isChecked()
        sb._not_interested_btn.click()
        assert sb._not_interested_btn.isChecked() and not sb._dislike_btn.isChecked()
        assert rates == [1, -1] and supp == [True]

    def test_queue_independent(self, qapp):
        from metatv.gui.sentiment_bar import SentimentBar
        sb = SentimentBar()
        fired = []
        sb.queue_clicked.connect(lambda: fired.append(1))
        sb._like_btn.click()
        sb._queue_btn.click()
        assert sb._like_btn.isChecked(), "a queue toggle must not clear sentiment"
        assert fired == [1]

    def test_set_state_no_emit(self, qapp):
        from metatv.gui.sentiment_bar import SentimentBar
        sb = SentimentBar()
        fired = []
        sb.rating_clicked.connect(lambda r: fired.append(r))
        sb.set_state(user_rating=-1, is_suppressed=False, in_queue=True)
        assert sb._dislike_btn.isChecked() and sb._queue_btn.isChecked()
        assert fired == [], "set_state must not fire signals"


# ---------------------------------------------------------------------------
# 5. View relays + optimistic cache
# ---------------------------------------------------------------------------

class TestViewRelays:
    def test_favorite_relay_and_optimistic(self, tmp_path, qapp):
        db = _seed_db(tmp_path / "relay.db")
        tm = _make_view(db, qapp)
        tm.open(["o"])
        got = []
        tm.favorite_toggled.connect(lambda cid: got.append(cid))
        assert tm._row_cache["o"].is_favorite is False
        tm._detail._fav_star.click()               # star click → view relays + optimistic
        assert got == ["o"]
        assert tm._row_cache["o"].is_favorite is True, "cache flips optimistically"
        db.close()

    def test_watched_relay_sets_completed_and_clears_resume(self, tmp_path, qapp):
        db = _seed_db(tmp_path / "watch.db")
        tm = _make_view(db, qapp)
        tm.open(["o", "s1"])                       # s1 is partial (progress 90)
        got = []
        tm.watched_toggled.connect(lambda cid, on: got.append((cid, on)))
        tm._select_seed_row("s1")
        tm._detail._on_watched_badge()             # partial → mark done
        assert got == [("s1", True)]
        assert tm._row_cache["s1"].watch_completed is True
        assert tm._row_cache["s1"].watch_progress == 0
        db.close()


# ---------------------------------------------------------------------------
# 6. Data-source-agnostic API (the Watch-History reuse seam)
# ---------------------------------------------------------------------------

class TestInjectableLoaders:
    def test_custom_loaders_drive_the_columns(self, tmp_path, qapp):
        db = _seed_db(tmp_path / "inject.db")
        calls = {"seed": 0, "sim": []}

        def fake_seed(session, ids):
            calls["seed"] += 1
            return [_dto(id="h1", title="Watched One"), _dto(id="h2", title="Watched Two")]

        def fake_sim(session, parent_id, *, excluded_provider_ids=None, config=None, limit=20):
            calls["sim"].append(parent_id)
            return [_dto(id=f"{parent_id}-a", title="Neighbour A", dedup_key="na")]

        tm = _make_view(db, qapp, seed_loader=fake_seed, similars_loader=fake_sim)
        tm.open(["h1", "h2"])                       # seed loader invoked once (inline)
        assert calls["seed"] == 1
        assert [r.title for r in tm._seed_rows] == ["Watched One", "Watched Two"]
        tm._select_seed_row("h1")                   # similars loader invoked once
        assert calls["sim"] == ["h1"]
        assert tm._cols_layout.count() - 1 == 2
        db.close()


# ---------------------------------------------------------------------------
# 7. Shared badge renderer + lightbox entry point
# ---------------------------------------------------------------------------

class TestSharedBadgeRenderer:
    def test_make_sim_badges_renders_active_state_glyphs(self, qapp):
        from PyQt6.QtWidgets import QLabel
        from metatv.gui import icons as _icons
        from metatv.gui.sim_badges import make_sim_badges

        w = make_sim_badges({
            "lang": "LAT", "rating": 8.3, "year": 2021,
            "user_rating": 1, "in_queue": True, "is_favorite": True, "watched": True,
        })
        tips = [lbl.toolTip() for lbl in w.findChildren(QLabel)]
        texts = [lbl.text() for lbl in w.findChildren(QLabel)]
        assert {"You liked this", "In Watch Later", "In Favorites", "Watched"} <= set(tips)
        assert _icons.like_icon in texts and _icons.watched_icon in texts
        assert "LAT" in texts and f"{_icons.rating_star_icon}8.3" in texts

    def test_lightbox_card_delegates_to_shared_renderer(self, qapp):
        # The lightbox strip card still renders badges (via the shared renderer).
        from metatv.gui.similar_lightbox_card import _LightboxCard
        from PyQt6.QtWidgets import QLabel
        card = _LightboxCard()
        card._populate_similar([{
            "id": "c1", "name": "M", "year": 2021, "poster_url": None,
            "watched": True, "user_rating": 1,
        }])
        strip_card = card._strip_layout.itemAt(0).widget()
        tips = {lbl.toolTip() for lbl in strip_card.findChildren(QLabel)}
        assert {"Watched", "You liked this"} <= tips


class TestLightboxEntryPoint:
    def test_explore_seeds_the_walked_trail(self):
        from metatv.gui.similar_lightbox import SimilarTitleLightbox

        captured = []

        class _FakeSig:
            def emit(self, seed):
                captured.append(seed)

        lb = SimilarTitleLightbox.__new__(SimilarTitleLightbox)
        lb._nav_stack = ["a", "b"]
        lb._current_id = "c"
        lb.explore_requested = _FakeSig()
        lb._on_explore()
        assert captured == [["a", "b", "c"]], "seed = the walked trail (nav-stack + current)"


# ---------------------------------------------------------------------------
# 8. What's New entry 176
# ---------------------------------------------------------------------------

def test_whats_new_entry_176_present_with_test_steps():
    from metatv.whats_new import WHATS_NEW
    entry = next((e for e in WHATS_NEW if e.id == 176), None)
    assert entry is not None, "What's New entry id=176 must be registered"
    assert entry.version == "0.14.1"
    assert entry.date == "2026-07-31"
    assert entry.items, "entry must have items"
    assert entry.test_steps, "entry must carry a non-empty test_steps tuple"


def test_whats_new_entry_179_present_with_test_steps():
    """Explore + lightbox poster-interaction polish (Parts A+B+C)."""
    from metatv.whats_new import WHATS_NEW
    entry = next((e for e in WHATS_NEW if e.id == 179), None)
    assert entry is not None, "What's New entry id=179 must be registered"
    assert entry.version == "0.15.0"
    assert entry.date == "2026-07-31"
    assert entry.items, "entry must have items"
    assert entry.test_steps, "entry must carry a non-empty test_steps tuple"
