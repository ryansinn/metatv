"""Behavioral tests for the Discover genre-shelf perf fix (#genre-perf).

Owner report: expanding/pinning a Discover genre shelf took 15-20s because
``get_by_genre`` ran a ~200-condition ``json_extract(raw_data, '$.genre')
LIKE …`` OR-chain against the full ``raw_data`` blob for every movie/series
row (240k+). The fix stores canonical genre(s) once at ingestion
(``ChannelDB.detected_genre``/``detected_genres``, computed by
``update_detected_prefixes()``) and reads them at query time instead.

Coverage:
1. Ingestion (``update_detected_prefixes``) writes ``detected_genre`` /
   ``detected_genres`` correctly — single genre, HTML-escaped alias, and a
   multi-segment compound raw string.
2. ``DetectedGenreBackfillTask`` populates pre-existing rows and is
   idempotent/version-gated.
3. Crash-retry: a task whose ``run()`` raises must not bump the version
   (modeled on ``test_migration_center.py::test_crashed_task_does_not_bump_version``).
4. ``get_by_genre`` preserves the EXACT old shelf-membership semantics for a
   seeded multi-genre fixture (segment-boundary-anchored matching, compound
   vs. pure-component separation) — now reading the stored field.
5. The old ``raw_data`` genre ``json_extract`` expression is gone from the
   engine's emitted SQL (static + dynamic proof).
6. EXPLAIN QUERY PLAN proves the genre lookup never falls back to an
   unindexed full scan of ``channels``.

GENRE-1 (owner-diagnosed, 2026-09-08): the Xtream VOD/movie payload's
``raw_data`` carries no ``genre`` key at all (only the series payload does),
so ``genres_from_raw()`` returned ``[]`` for every one of 529,280 real movies
and a genre chip found 15 Horror / 6 Thriller titles out of 785,925 channels.
The fix is a write-time fallback to ``filter_utils.genres_from_category()``
on the provider ``category`` string (e.g. ``"|EN| HORROR/THRILLER"``) when
the raw genre is empty:

7. Ingestion falls back to the category cross-walk for a genre-less movie,
   never overrides a raw-derived list, a non-genre category (e.g.
   "NETFLIX MOVIES") still yields ``None`` rather than an empty-list
   stand-in, and — CI regression, PR #813 — a LIVE channel's category
   (its bouquet) never becomes a genre guess, gated by the pre-existing
   ``channel_lens.GENRE_MEDIA_TYPES`` (movie/series only), the same line
   ``tag_decomposer`` already draws via its own ``target_facet`` check.
8. ``DetectedGenreBackfillTask`` (version 2) backfills a pre-existing movie
   row whose ``detected_genres`` is NULL and whose category names a genre.
9. The untouched, pre-existing ``genre_predicate('Horror')`` (the SAME
   predicate the details-pane genre chip uses) now finds a category-derived
   movie — proof the fix is a stored-field write, not a new read path.
"""

from __future__ import annotations

import re
import uuid

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def file_db(tmp_path):
    """File-backed SQLite Database (not :memory: — see CLAUDE.md tests rule)."""
    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path / 'genre_backfill.db'}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def cfg(tmp_path):
    """Isolated Config instance — never touches the real ~/.config/metatv."""
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


def _add_provider(db) -> None:
    from metatv.core.database import ProviderDB

    session = db.get_session()
    try:
        session.add(ProviderDB(
            id="p1", name="P", type="xtream", url="http://x.example.com", is_active=True,
        ))
        session.commit()
    finally:
        session.close()


def _add_channel(db, *, raw_genre: str | None, name: str = "Movie",
                  media_type: str = "movie", category: str = "") -> str:
    """Insert a bare (pre-ingestion) ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    channel_id = str(uuid.uuid4())
    session = db.get_session()
    try:
        raw_data = {"rating": "7.0"}
        if raw_genre is not None:
            raw_data["genre"] = raw_genre
        session.add(ChannelDB(
            id=channel_id, source_id=channel_id, provider_id="p1",
            name=name, media_type=media_type, raw_data=raw_data,
            category=category,
        ))
        session.commit()
    finally:
        session.close()
    return channel_id


def _run_ingestion(db) -> None:
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        RepositoryFactory(session).channels.update_detected_prefixes(provider_id=None)


# ---------------------------------------------------------------------------
# 1. Ingestion writes detected_genre / detected_genres
# ---------------------------------------------------------------------------

class TestIngestionWritesGenre:

    def test_single_genre_stored_canonical(self, file_db):
        """A plain single-segment genre is stored on both fields as-is."""
        _add_provider(file_db)
        cid = _add_channel(file_db, raw_genre="Drama")
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genre == "Drama"
            assert ch.detected_genres == ["Drama"]
        finally:
            session.close()

    def test_html_escaped_alias_canonicalized(self, file_db):
        """'Action &amp; Adventure' collapses to canonical 'Action & Adventure'
        (bug A) and a foreign-language alias ('Drame') collapses to 'Drama'."""
        _add_provider(file_db)
        cid_amp = _add_channel(file_db, raw_genre="Action &amp; Adventure", name="M1")
        cid_fr = _add_channel(file_db, raw_genre="Drame", name="M2")
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch_amp = session.query(ChannelDB).get(cid_amp)
            ch_fr = session.query(ChannelDB).get(cid_fr)
            assert ch_amp.detected_genre == "Action & Adventure"
            assert ch_amp.detected_genres == ["Action & Adventure"]
            assert ch_fr.detected_genre == "Drama"
            assert ch_fr.detected_genres == ["Drama"]
        finally:
            session.close()

    def test_multi_segment_genre_stores_every_canonical_segment(self, file_db):
        """'Action &amp; Adventure / Sci-Fi' stores BOTH canonical segments —
        detected_genre is the first (display), detected_genres has both
        (shelf membership)."""
        _add_provider(file_db)
        cid = _add_channel(file_db, raw_genre="Action &amp; Adventure / Sci-Fi")
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genre == "Action & Adventure"
            assert ch.detected_genres == ["Action & Adventure", "Science Fiction"]
        finally:
            session.close()

    def test_no_genre_leaves_fields_null(self, file_db):
        """A channel with no raw_data genre gets NULL on both fields."""
        _add_provider(file_db)
        cid = _add_channel(file_db, raw_genre=None)
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genre is None
            assert ch.detected_genres is None
        finally:
            session.close()

    def test_bogus_sentinel_genre_dropped(self, file_db):
        """A literal 'null'/'undefined' provider genre never enters detected_genres."""
        _add_provider(file_db)
        cid = _add_channel(file_db, raw_genre="null")
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genre is None
            assert ch.detected_genres is None
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 2. DetectedGenreBackfillTask
# ---------------------------------------------------------------------------

class TestDetectedGenreBackfillTask:

    def test_needs_run_true_when_version_behind(self, file_db, cfg):
        from metatv.core.migrations.detected_genre_backfill import (
            CURRENT_VERSION, DetectedGenreBackfillTask,
        )

        task = DetectedGenreBackfillTask(file_db)
        assert cfg.genre_backfill_version == 0
        assert task.needs_run(cfg) is True
        cfg.genre_backfill_version = CURRENT_VERSION
        assert task.needs_run(cfg) is False

    def test_run_populates_pre_existing_rows(self, file_db, cfg):
        """Rows inserted BEFORE the fix (no detected_genre(s)) get backfilled."""
        from metatv.core.database import ChannelDB
        from metatv.core.migrations.detected_genre_backfill import DetectedGenreBackfillTask

        _add_provider(file_db)
        cid = _add_channel(file_db, raw_genre="Comedy")

        session = file_db.get_session()
        try:
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genre is None, "pre-condition: not yet backfilled"
        finally:
            session.close()

        task = DetectedGenreBackfillTask(file_db)
        progress: list[tuple[int, int]] = []
        task.run(lambda d, t: progress.append((d, t)), lambda: False)

        session = file_db.get_session()
        try:
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genre == "Comedy"
            assert ch.detected_genres == ["Comedy"]
        finally:
            session.close()

    def test_on_completed_bumps_version(self, file_db, cfg):
        from metatv.core.migrations.detected_genre_backfill import (
            CURRENT_VERSION, DetectedGenreBackfillTask,
        )

        task = DetectedGenreBackfillTask(file_db)
        task.on_completed(cfg)
        assert cfg.genre_backfill_version == CURRENT_VERSION


# ---------------------------------------------------------------------------
# 3. Crash-retry — modeled on
#    test_migration_center.py::test_crashed_task_does_not_bump_version
# ---------------------------------------------------------------------------

class TestDetectedGenreBackfillCrashRetry:

    def test_crashed_run_does_not_bump_version(self, file_db, cfg, monkeypatch):
        """A run() that raises must leave genre_backfill_version unbumped so
        the task retries on the next launch — the real MigrationManager wiring
        is what guarantees this (#364): it skips on_completed for any task
        whose run() raised. Uses the REAL task + REAL MigrationManager, not
        a generic mock, to prove THIS task integrates with that mechanism.
        """
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.detected_genre_backfill import (
            DetectedGenreBackfillTask,
        )

        task = DetectedGenreBackfillTask(file_db)

        def _boom(progress_cb, is_cancelled, config=None):
            raise RuntimeError("database is locked")

        monkeypatch.setattr(task, "run", _boom)

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        import threading
        mgr._cancel_event = threading.Event()
        finished: list[str] = []
        from unittest.mock import MagicMock
        mgr._task_finished = MagicMock(emit=lambda tid: finished.append(tid))
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.genre_backfill_version == 0, (
            "a crashed run() must NOT bump the version — it must retry next launch"
        )
        assert finished == ["detected_genre_backfill"], "widget must still get the finish signal"

    def test_successful_run_bumps_version_after_crash_retry(self, file_db, cfg):
        """After a (simulated) prior crash, a real successful run completes
        normally and bumps the version — proving the task isn't permanently
        broken by the crash path."""
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.migrations.detected_genre_backfill import (
            CURRENT_VERSION, DetectedGenreBackfillTask,
        )

        _add_provider(file_db)
        _add_channel(file_db, raw_genre="Horror")

        task = DetectedGenreBackfillTask(file_db)
        assert cfg.genre_backfill_version == 0

        mgr = MigrationManager.__new__(MigrationManager)
        mgr.config = cfg
        import threading
        mgr._cancel_event = threading.Event()
        from unittest.mock import MagicMock
        mgr._task_finished = MagicMock(emit=lambda tid: None)
        mgr._task_started = MagicMock(emit=lambda *a: None)
        mgr._task_progress = MagicMock(emit=lambda *a: None)
        mgr._all_finished = MagicMock(emit=lambda *a: None)

        mgr._run_all([task])

        assert cfg.genre_backfill_version == CURRENT_VERSION


# ---------------------------------------------------------------------------
# 4. get_by_genre — exact old-semantics preservation for a multi-genre fixture
# ---------------------------------------------------------------------------

class TestGetByGenreSemanticsPreserved:
    """Seeded per the PR brief: raw genres "Drame", "Action &amp; Adventure /
    Sci-Fi", "Sci-Fi & Fantasy". Derived OLD (pre-fix) shelf membership, by
    replaying the old alias/segment-boundary matching by hand:

      - "Drame" (single segment)                       → Drama shelf only.
      - "Action &amp; Adventure / Sci-Fi" (two segments)
          segment 1 "Action &amp; Adventure" matches the "Action & Adventure"
          shelf (canonical + escaped-alias match).
          segment 2 "Sci-Fi" is a bare pure-component segment — it matches the
          "Science Fiction" shelf (alias "sci-fi" → "Science Fiction"), NOT
          "Sci-Fi & Fantasy" (segment-boundary matching means "Sci-Fi" alone
          never satisfies a "Sci-Fi & Fantasy" alias, which requires the full
          compound string as a whole segment) — this is precisely bug B's
          compound/component separation the old code already enforced.
      - "Sci-Fi & Fantasy" (single segment, the compound itself)
          → Sci-Fi & Fantasy shelf only.

    So the multi-genre row appears on TWO shelves (Action & Adventure,
    Science Fiction) — not three, and NOT on Sci-Fi & Fantasy.
    """

    @pytest.fixture()
    def seeded(self, file_db):
        _add_provider(file_db)
        _add_channel(file_db, raw_genre="Drame", name="Drame Movie")
        _add_channel(file_db, raw_genre="Action &amp; Adventure / Sci-Fi",
                     name="Multi Genre Movie")
        _add_channel(file_db, raw_genre="Sci-Fi & Fantasy", name="Compound Movie")
        _run_ingestion(file_db)
        return file_db

    def _titles(self, db, genre: str) -> set[str]:
        from metatv.core.discovery_engine import get_by_genre

        session = db.get_session()
        try:
            cards = get_by_genre(session, genre, limit=50)
        finally:
            session.close()
        return {c.title for c in cards}

    def test_drama_shelf_has_only_drame_row(self, seeded):
        assert self._titles(seeded, "Drama") == {"Drame Movie"}

    def test_action_adventure_shelf_has_only_multi_genre_row(self, seeded):
        assert self._titles(seeded, "Action & Adventure") == {"Multi Genre Movie"}

    def test_science_fiction_shelf_has_only_multi_genre_row(self, seeded):
        """The bare 'Sci-Fi' segment lands on Science Fiction, not the compound."""
        assert self._titles(seeded, "Science Fiction") == {"Multi Genre Movie"}

    def test_sci_fi_fantasy_shelf_has_only_the_compound_row(self, seeded):
        """The multi-genre row's bare 'Sci-Fi' segment must NOT bleed into the
        'Sci-Fi & Fantasy' shelf (compound/component separation, bug B)."""
        assert self._titles(seeded, "Sci-Fi & Fantasy") == {"Compound Movie"}


# ---------------------------------------------------------------------------
# 5. The old raw_data genre json_extract expression is gone
# ---------------------------------------------------------------------------

class TestRawDataGenreExpressionRemoved:

    def test_source_has_no_raw_data_genre_json_extract(self):
        """Static proof: the alias-matching json_extract(raw_data,'$.genre')
        expression no longer appears anywhere in discovery_engine.py."""
        import metatv.core.discovery_engine as mod

        src = open(mod.__file__, encoding="utf-8").read()
        assert "json_extract(channels.raw_data, '$.genre')" not in src
        assert "_genre_segment_conditions" not in src

    def test_get_by_genre_emits_no_raw_data_genre_expression(self, file_db):
        """Dynamic proof: capture the actual SQL get_by_genre sends to SQLite
        and assert the genre-matching predicate never touches raw_data."""
        from sqlalchemy import event
        from metatv.core.discovery_engine import get_by_genre

        _add_provider(file_db)
        _add_channel(file_db, raw_genre="Drama")
        _run_ingestion(file_db)

        captured: list[tuple[str, object]] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            captured.append((statement, parameters))

        event.listen(file_db.engine, "before_cursor_execute", _capture)
        session = file_db.get_session()
        try:
            get_by_genre(session, "Drama", limit=50)
        finally:
            session.close()
            event.remove(file_db.engine, "before_cursor_execute", _capture)

        selects = [s for s, _ in captured if s.strip().upper().startswith("SELECT")]
        assert len(selects) == 1, f"expected exactly one SELECT, got {len(selects)}"
        sql = selects[0]
        assert "json_extract(channels.raw_data, '$.genre')" not in sql
        assert "json_each(channels.detected_genres)" in sql


# ---------------------------------------------------------------------------
# 6. EXPLAIN QUERY PLAN — no unindexed full scan of channels
# ---------------------------------------------------------------------------

class TestGetByGenreQueryPlan:

    def _capture_and_plan(self, db, genre: str):
        """Capture get_by_genre's real compiled SQL, then run
        EXPLAIN QUERY PLAN on that exact statement + params."""
        from sqlalchemy import event
        from metatv.core.discovery_engine import get_by_genre

        captured: list[tuple[str, object]] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            captured.append((statement, parameters))

        event.listen(db.engine, "before_cursor_execute", _capture)
        session = db.get_session()
        try:
            get_by_genre(session, genre, limit=50)
        finally:
            session.close()
            event.remove(db.engine, "before_cursor_execute", _capture)

        sql, params = next(
            (s, p) for s, p in captured if s.strip().upper().startswith("SELECT")
        )
        raw_conn = db.engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            plan = cur.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
        finally:
            raw_conn.close()
        return plan

    def test_no_unindexed_scan_of_channels(self, file_db):
        """The genre lookup must never fall back to a bare 'SCAN … channels'
        with no index — every plan step touching the channels table must be
        either a SEARCH (indexed row access) or a SCAN that itself names an
        index (e.g. a covering index). This is what actually changed: the
        OLD query's ~200-condition json_extract(raw_data,'$.genre') LIKE
        OR-chain was residual-filter work on every scanned row regardless of
        which index selected those rows; the NEW query replaces that residual
        cost with a cheap json_each() over a tiny pre-extracted column — but
        row *selection* was already index-driven via media_type/is_hidden in
        both versions, so the meaningful, testable delta is: no bare
        unindexed scan is introduced, and (see test 5 above) raw_data is
        never touched for genre matching any more.
        """
        _add_provider(file_db)
        # A few hundred rows across several genres so SQLite's cost-based
        # planner reliably prefers an index over a raw scan (matches its
        # real choice on a 240k-row production library).
        genres = ["Drama", "Comedy", "Action & Adventure", "Horror"]
        for i in range(300):
            _add_channel(
                file_db, raw_genre=genres[i % len(genres)], name=f"Movie {i}",
                media_type="movie" if i % 2 == 0 else "series",
            )
        _run_ingestion(file_db)

        plan = self._capture_and_plan(file_db, "Drama")
        assert plan, "EXPLAIN QUERY PLAN returned nothing"

        for row in plan:
            detail = row[-1]
            if re.search(r"\bSCAN\b", detail, re.I) and re.search(r"\bchannels\b", detail, re.I):
                assert re.search(r"\bINDEX\b", detail, re.I), (
                    f"unindexed SCAN of channels in genre-lookup plan: {detail!r}\n"
                    f"full plan: {plan}"
                )


# ---------------------------------------------------------------------------
# 7. GENRE-1 — ingestion falls back to genres_from_category() for a
#    genre-less movie (the actual owner-diagnosed bug)
# ---------------------------------------------------------------------------

class TestIngestionCategoryGenreFallback:

    def test_movie_with_no_raw_genre_falls_back_to_category(self, file_db):
        """A movie whose raw_data carries no 'genre' key (the real Xtream VOD
        shape) but whose category names one gets detected_genre(s) from the
        category cross-walk."""
        _add_provider(file_db)
        cid = _add_channel(
            file_db, raw_genre=None, category="|EN| HORROR/THRILLER",
        )
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genres == ["Horror", "Thriller"]
            assert ch.detected_genre == "Horror"
        finally:
            session.close()

    def test_raw_genre_always_wins_over_category(self, file_db):
        """A row with BOTH a raw_data genre and a genre-bearing category keeps
        the raw-derived list unchanged — the category fallback never
        overrides a source-denoted raw genre."""
        _add_provider(file_db)
        cid = _add_channel(
            file_db, raw_genre="Comedy", category="|EN| HORROR/THRILLER",
        )
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genre == "Comedy"
            assert ch.detected_genres == ["Comedy"]
        finally:
            session.close()

    def test_category_with_no_recognisable_genre_stays_null(self, file_db):
        """Real owner categories that denote no genre ('NETFLIX MOVIES',
        '4K MOVIES') must leave detected_genre(s) NULL, not an empty list
        masquerading as data."""
        _add_provider(file_db)
        cid_netflix = _add_channel(
            file_db, raw_genre=None, category="NETFLIX MOVIES", name="M1",
        )
        cid_4k = _add_channel(
            file_db, raw_genre=None, category="4K MOVIES", name="M2",
        )
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch_netflix = session.query(ChannelDB).get(cid_netflix)
            ch_4k = session.query(ChannelDB).get(cid_4k)
            assert ch_netflix.detected_genre is None
            assert ch_netflix.detected_genres is None
            assert ch_4k.detected_genre is None
            assert ch_4k.detected_genres is None
        finally:
            session.close()

    def test_live_channel_category_never_becomes_a_genre(self, file_db):
        """CI regression (PR #813): a LIVE channel's category is its bouquet
        ("News", "|EN| HORROR/THRILLER" as a channel grouping), never a genre
        guess — GENRE_MEDIA_TYPES (channel_lens.py) gates the category
        fallback to movie/series only, the same line tag_decomposer already
        draws via its own ``target_facet`` check. The identical category on a
        MOVIE row (below) DOES yield genres — proves the gate is on
        media_type, not on the category string."""
        _add_provider(file_db)
        cid_live = _add_channel(
            file_db, raw_genre=None, category="|EN| HORROR/THRILLER",
            media_type="live", name="AR| CNN ENGLISH",
        )
        cid_movie = _add_channel(
            file_db, raw_genre=None, category="|EN| HORROR/THRILLER",
            media_type="movie", name="Some Horror Movie",
        )
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            from metatv.core.database import ChannelDB
            ch_live = session.query(ChannelDB).get(cid_live)
            ch_movie = session.query(ChannelDB).get(cid_movie)
            assert ch_live.detected_genre is None
            assert ch_live.detected_genres is None
            assert ch_movie.detected_genres == ["Horror", "Thriller"]
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 8. GENRE-1 — DetectedGenreBackfillTask (version 2) backfills pre-existing
#    movie rows via the category fallback
# ---------------------------------------------------------------------------

class TestDetectedGenreBackfillTaskCategoryFallback:

    def test_run_populates_preexisting_category_only_movie_row(self, file_db, cfg):
        """A movie row that predates GENRE-1 — detected_genres NULL, a
        genre-bearing category, no raw genre — gets backfilled by the SAME
        DetectedGenreBackfillTask (now version 2), via the identical
        update_detected_prefixes() pass version 1 always used, not a second
        targeted query."""
        from metatv.core.database import ChannelDB
        from metatv.core.migrations.detected_genre_backfill import DetectedGenreBackfillTask

        _add_provider(file_db)
        cid = _add_channel(
            file_db, raw_genre=None, category="|EN| HORROR/THRILLER",
        )

        session = file_db.get_session()
        try:
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genres is None, "pre-condition: not yet backfilled"
        finally:
            session.close()

        task = DetectedGenreBackfillTask(file_db)
        progress: list[tuple[int, int]] = []
        task.run(lambda d, t: progress.append((d, t)), lambda: False)

        session = file_db.get_session()
        try:
            ch = session.query(ChannelDB).get(cid)
            assert ch.detected_genres == ["Horror", "Thriller"]
            assert ch.detected_genre == "Horror"
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 9. GENRE-1 — the untouched genre_predicate('Horror') (the SAME strict
#    predicate the details-pane genre chip uses, channel_lens.py) finds a
#    category-derived movie once the field is populated at ingestion.
#
#    This is the proof the fix is a write-time (ingestion) change and not a
#    read-time one: genre_predicate() itself is not modified by GENRE-1.
# ---------------------------------------------------------------------------

class TestGenrePredicateFindsCategoryDerivedMovie:

    def test_genre_predicate_selects_category_derived_movie(self, file_db):
        """Regression proof for the owner's bug report: a movie whose ONLY
        genre signal is its provider category ('|EN| HORROR/THRILLER', no
        raw_data genre) must be selected by channel_lens.genre_predicate('Horror')
        once ingestion has run.

        Confirmed FAILING against pre-GENRE-1 main (channel.detected_genres
        stayed NULL for every movie since genres_from_raw() always returned
        [] for the Xtream VOD shape, so this query returned zero rows) —
        see the GENRE-1 PR description.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories.channel_lens import genre_predicate

        _add_provider(file_db)
        cid = _add_channel(
            file_db, raw_genre=None, category="|EN| HORROR/THRILLER",
            name="Category-Only Horror Movie",
        )
        _run_ingestion(file_db)

        session = file_db.get_session()
        try:
            rows = (
                session.query(ChannelDB)
                .filter(
                    ChannelDB.media_type.in_(["movie", "series"]),
                    genre_predicate("Horror"),
                )
                .all()
            )
            assert cid in {r.id for r in rows}, (
                "genre_predicate('Horror') must select the category-derived movie"
            )
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 10. W-1 — version 3 re-runs the SAME full pass and now also fixes
#     detected_added (series "added"->"last_modified"), detected_year (a
#     metadata-only series) and the genre case-sensitivity bug, all through
#     the identical update_detected_prefixes() codepath GENRE-1 already used.
# ---------------------------------------------------------------------------

class TestDetectedGenreBackfillTaskVersion3:

    def test_version_bumped_to_3(self):
        from metatv.core.migrations.detected_genre_backfill import CURRENT_VERSION
        assert CURRENT_VERSION == 3, (
            f"Expected version 3 (W-1), got {CURRENT_VERSION}"
        )

    def test_run_backfills_a_seeded_row_for_each_of_added_year_and_genre(self, file_db, cfg):
        """A real Database on a tmp_path FILE (never :memory:), one
        pre-existing (pre-migration) row per bug, all fixed by the SAME
        DetectedGenreBackfillTask.run() call at version 3."""
        from metatv.core.database import ChannelDB, MetadataDB
        from metatv.core.migrations.detected_genre_backfill import DetectedGenreBackfillTask

        _add_provider(file_db)

        # (1) detected_added: a series row shaped exactly like the real
        # provider payload -- "last_modified", no "added" key at all.
        series_added_id = str(uuid.uuid4())
        # (2) detected_year: a series whose NAME carries no year, but whose
        # linked MetadataDB row does.
        series_year_id = str(uuid.uuid4())
        # (3) detected_genre: a movie whose only genre signal is an
        # uppercase category leaf the case-sensitivity bug used to drop.
        genre_movie_id = str(uuid.uuid4())

        session = file_db.get_session()
        try:
            session.add(MetadataDB(id="meta1", title="Some Series", year=2019, media_type="series"))
            session.flush()
            session.add(ChannelDB(
                id=series_added_id, source_id=series_added_id, provider_id="p1",
                name="EN - Frauds (2025)", media_type="series",
                raw_data={"last_modified": "1759675302"},
            ))
            session.add(ChannelDB(
                id=series_year_id, source_id=series_year_id, provider_id="p1",
                name="EN - Some Series", media_type="series",
                raw_data={}, metadata_id="meta1",
            ))
            session.add(ChannelDB(
                id=genre_movie_id, source_id=genre_movie_id, provider_id="p1",
                name="EN - Some Anime Movie", media_type="movie",
                raw_data={"rating": "7.0"}, category="|EN| ANIME",
            ))
            session.commit()
        finally:
            session.close()

        task = DetectedGenreBackfillTask(file_db)
        progress: list[tuple[int, int]] = []
        task.run(lambda d, t: progress.append((d, t)), lambda: False)

        session = file_db.get_session()
        try:
            added_row = session.query(ChannelDB).get(series_added_id)
            assert added_row.detected_added == 1759675302, (
                f"Expected detected_added from last_modified, got {added_row.detected_added!r}"
            )

            year_row = session.query(ChannelDB).get(series_year_id)
            assert year_row.detected_year == "2019", (
                f"Expected detected_year from metadata, got {year_row.detected_year!r}"
            )

            genre_row = session.query(ChannelDB).get(genre_movie_id)
            assert genre_row.detected_genre == "Anime", (
                f"Expected detected_genre 'Anime', got {genre_row.detected_genre!r}"
            )
        finally:
            session.close()

        assert progress, "progress_cb must be called at least once"
