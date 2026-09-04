"""Behavioral tests for Phase 2 (reshaped) — lazy provider-native TMDb enrichment.

Covers the full changed path with all provider HTTP mocked (never a real provider)
and a file-backed (tmp_path) SQLite DB per CLAUDE.md — real Database/Config, mock
ONLY the network.  The six reshape parts:

1. Title-sibling propagation (free): an idless row adopts a confident same-title
   sibling's id (+content_key, marker 'propagated'); a year-mismatch remake does
   not; no sibling → unchanged.
2. COALESCE-preserve on refresh: an enriched id survives a refresh that ships no
   raw tmdb; the narrowed reset clears only still-idless markers; ingestion marks
   an id-bearing new row 'list'.
3. Lazy enqueue: candidates filtered off-thread; a hit writes id+content_key+marker
   'fetched'; an empty response marks 'none'; a fetched row is never re-fetched;
   series uses get_series_info.
4. Source-attributed coalesced notification via a main-thread signal (the worker
   never touches NotificationManager); the host slot shows→updates→dismisses.
5. missing_tmdb_by_source lists only idless rows; opening the view enqueues them.
6. The enrichment funnel buckets by provenance; residual = idless AND 'none'.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache
from metatv.core.tmdb_enrichment_manager import (
    _EMPTY_BACKOFF_S,
    _EMPTY_STREAK_LIMIT,
    _EMPTY_STREAK_MIN_ROWS,
    TmdbEnrichmentManager,
    _extract_tmdb_id,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables + lightweight migrations applied."""
    _clear_tag_cache()
    d = Database(f"sqlite:///{tmp_path / 'tmdb_enrich.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture()
def config_obj(tmp_path):
    """Isolated Config (throttle zeroed so the async pass runs instantly)."""
    from metatv.core.config import Config

    c = Config(config_dir=tmp_path / "config")
    c.tmdb_enrichment_throttle_ms = 0
    return c


@pytest.fixture(scope="module")
def qapp():
    """A QApplication so QObject-based managers can be constructed."""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _provider(session, pid: str = "p1", *, is_active: bool = True) -> str:
    session.add(
        ProviderDB(
            id=pid,
            name=f"Provider {pid}",
            type="xtream",
            url="http://example.com",
            username="u",
            password="p",
            is_active=is_active,
        )
    )
    session.flush()
    return pid


def _channel(
    session,
    provider_id: str = "p1",
    *,
    source_id: str | None = None,
    name: str = "Test",
    media_type: str = "movie",
    detected_title: str | None = None,
    detected_year: str | None = None,
    detected_tmdb_id: str | None = None,
    content_key: str | None = None,
    tmdb_enrich_state: str | None = None,
    is_hidden: bool = False,
) -> str:
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=source_id or str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            media_type=media_type,
            detected_title=detected_title,
            detected_year=detected_year,
            detected_tmdb_id=detected_tmdb_id,
            content_key=content_key,
            tmdb_enrich_state=tmdb_enrich_state,
            is_hidden=is_hidden,
        )
    )
    session.flush()
    return cid


def _make_fake_api(*, vod: dict | None = None, series: dict | None = None, calls: list):
    """Drop-in ``XtreamAPI`` replacement returning canned detail data (by source_id).

    A value of the string ``"ERROR"`` raises to simulate a failure.  Every call is
    appended to *calls* as ``("vod"|"series", source_id)``.
    """
    vod = vod or {}
    series = series or {}

    class _FakeAPI:
        def __init__(self, base_url, username, password):
            self.base_url = base_url

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_vod_info(self, vod_id):
            calls.append(("vod", vod_id))
            v = vod.get(vod_id)
            if v == "ERROR":
                raise RuntimeError("simulated network error")
            return v

        async def get_series_info(self, series_id):
            calls.append(("series", series_id))
            v = series.get(series_id)
            if v == "ERROR":
                raise RuntimeError("simulated network error")
            return v

    return _FakeAPI


def _drain(mgr, qapp, timeout: float = 6.0) -> None:
    """Drive an ``enqueue``-triggered drain to completion (process queued signals)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        qapp.processEvents()
        with mgr._lock:
            idle = not mgr._busy and not mgr._queue
        if idle:
            break
        time.sleep(0.01)
    # Let any final queued signals (collapses / progress clear) deliver.
    for _ in range(5):
        qapp.processEvents()
        time.sleep(0.01)


# ---------------------------------------------------------------------------
# 0. _extract_tmdb_id — response parsing (unchanged)
# ---------------------------------------------------------------------------


class TestExtractTmdbId:
    def test_pulls_nested_tmdb_id(self):
        assert _extract_tmdb_id({"info": {"tmdb_id": "1181863"}}) == "1181863"

    def test_accepts_legacy_tmdb_key(self):
        assert _extract_tmdb_id({"info": {"tmdb": "603"}}) == "603"

    @pytest.mark.parametrize("resp", [
        None, {}, {"info": {}}, {"info": {"tmdb_id": "0"}},
        {"info": {"tmdb_id": ""}}, {"info": "notadict"}, [1, 2, 3],
    ])
    def test_rejects_missing_or_sentinel(self, resp):
        assert _extract_tmdb_id(resp) is None


# ---------------------------------------------------------------------------
# 1. Title-sibling propagation (free, no network)
# ---------------------------------------------------------------------------


def test_propagation_adopts_confident_sibling(db):
    with db.session_scope() as session:
        _provider(session)
        _channel(session, media_type="movie", detected_title="The Matrix",
                 detected_year="1999", detected_tmdb_id="603")
        idless = _channel(session, media_type="movie", detected_title="the  matrix",
                          detected_year="1999")

    with db.session_scope() as session:
        adopted = RepositoryFactory(session).channels.propagate_tmdb_from_title_siblings()
    assert adopted == 1

    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.detected_tmdb_id, ChannelDB.content_key, ChannelDB.tmdb_enrich_state
        ).filter_by(id=idless).one()
    assert row.detected_tmdb_id == "603"
    assert row.content_key == "tmdb:603|movie"          # content_key_for chokepoint
    assert row.tmdb_enrich_state == "propagated"


def test_propagation_year_mismatch_remake_not_adopted(db):
    with db.session_scope() as session:
        _provider(session)
        _channel(session, media_type="movie", detected_title="Dune",
                 detected_year="2021", detected_tmdb_id="438631")
        old = _channel(session, media_type="movie", detected_title="Dune",
                       detected_year="1984")  # remake, >1yr apart → skip

    with db.session_scope() as session:
        adopted = RepositoryFactory(session).channels.propagate_tmdb_from_title_siblings()
    assert adopted == 0

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=old).scalar() is None
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=old).scalar() is None


def test_propagation_no_sibling_unchanged(db):
    with db.session_scope() as session:
        _provider(session)
        lone = _channel(session, media_type="movie", detected_title="Unique Film",
                        detected_year="2010")

    with db.session_scope() as session:
        adopted = RepositoryFactory(session).channels.propagate_tmdb_from_title_siblings()
    assert adopted == 0
    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=lone).scalar() is None


def test_propagation_ambiguous_remake_split_skipped(db):
    """Two distinct year-compatible sibling ids for the same title → don't guess."""
    with db.session_scope() as session:
        _provider(session)
        # An idless row with no year, and two id-bearing siblings with different ids.
        _channel(session, media_type="movie", detected_title="Clash",
                 detected_year="2010", detected_tmdb_id="111")
        _channel(session, media_type="movie", detected_title="Clash",
                 detected_year="2010", detected_tmdb_id="222")
        idless = _channel(session, media_type="movie", detected_title="Clash")  # no year

    with db.session_scope() as session:
        adopted = RepositoryFactory(session).channels.propagate_tmdb_from_title_siblings()
    assert adopted == 0
    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=idless).scalar() is None


# ---------------------------------------------------------------------------
# 2. COALESCE-preserve on refresh + narrowed reset + 'list' at ingestion
# ---------------------------------------------------------------------------


def test_refresh_preserves_enriched_id_via_coalesce(db):
    from metatv.core.provider_loader import ProviderLoadThread

    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        _provider(session)
        session.add(ChannelDB(
            id=cid, source_id="s1", provider_id="p1", name="Movie", media_type="movie",
            detected_tmdb_id="999", content_key="tmdb:999|movie",
            tmdb_enrich_state="fetched", raw_data={},
        ))

    # A refresh whose list row ships NO tmdb id (incoming detected_tmdb_id is None).
    batch = [{
        "id": cid, "source_id": "s1", "provider_id": "p1", "name": "Movie",
        "stream_url": None, "category": None, "category_id": None, "logo_url": None,
        "media_type": "movie", "quality": "unknown", "is_adult": False, "raw_data": {},
        "detected_tmdb_id": None, "tmdb_enrich_state": None, "source_num": None,
        "source_category": None, "source_quality_flags": None,
    }]
    with db.session_scope() as session:
        ProviderLoadThread._flush_batch(session, batch)

    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.detected_tmdb_id, ChannelDB.tmdb_enrich_state
        ).filter_by(id=cid).one()
    assert row.detected_tmdb_id == "999", "enriched id must survive a refresh with no raw id"
    assert row.tmdb_enrich_state == "fetched", "resolved marker must not be clobbered"


def test_ingestion_marks_list_when_id_present(db):
    from metatv.core.provider_loader import ProviderLoadThread

    with_id = str(uuid.uuid4())
    without_id = str(uuid.uuid4())
    with db.session_scope() as session:
        _provider(session)

    def _row(cid, tmdb):
        return {
            "id": cid, "source_id": cid, "provider_id": "p1", "name": "M",
            "stream_url": None, "category": None, "category_id": None, "logo_url": None,
            "media_type": "movie", "quality": "unknown", "is_adult": False, "raw_data": {},
            "detected_tmdb_id": tmdb,
            "tmdb_enrich_state": "list" if tmdb else None,
            "source_num": None, "source_category": None, "source_quality_flags": None,
        }

    with db.session_scope() as session:
        ProviderLoadThread._flush_batch(session, [_row(with_id, "500"), _row(without_id, None)])

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=with_id).scalar() == "list"
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=without_id).scalar() is None


def test_reset_only_clears_still_idless_rows(db):
    with db.session_scope() as session:
        _provider(session, "p1")
        a = _channel(session, "p1", tmdb_enrich_state="none")                       # idless
        b = _channel(session, "p1", tmdb_enrich_state="fetched", detected_tmdb_id="5")  # has id
        c = _channel(session, "p1", tmdb_enrich_state="list", detected_tmdb_id="7")     # has id

    with db.session_scope() as session:
        cleared = RepositoryFactory(session).channels.reset_tmdb_enrich_state("p1")
    assert cleared == 1  # only the idless 'none' row

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=a).scalar() is None
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=b).scalar() == "fetched"
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=c).scalar() == "list"


# ---------------------------------------------------------------------------
# 3. Repository: candidate filtering + apply enrichment ('fetched' marker)
# ---------------------------------------------------------------------------


def test_candidates_by_ids_only_idless_unattempted_visible_vod(db):
    with db.session_scope() as session:
        _provider(session, "p1", is_active=True)
        _provider(session, "p2", is_active=False)  # hidden (inactive)
        want = _channel(session, "p1", media_type="movie")
        want2 = _channel(session, "p1", media_type="series")
        has_id = _channel(session, "p1", media_type="movie", detected_tmdb_id="99")
        attempted = _channel(session, "p1", media_type="movie", tmdb_enrich_state="none")
        live = _channel(session, "p1", media_type="live")
        hidden_row = _channel(session, "p1", media_type="movie", is_hidden=True)
        p2row = _channel(session, "p2", media_type="movie")

    all_ids = [want, want2, has_id, attempted, live, hidden_row, p2row]
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        excluded = set(repos.providers.get_hidden_provider_ids())
        rows = repos.channels.select_tmdb_candidates_by_ids(all_ids, excluded)

    ids = {r["id"] for r in rows}
    assert ids == {want, want2}
    assert all(set(r) == {"id", "provider_id", "source_id", "media_type"} for r in rows)


def test_apply_enrichment_writes_fetched_marker_and_counts_collapse(db):
    with db.session_scope() as session:
        _provider(session)
        _channel(session, media_type="movie", detected_title="EN Movie",
                 detected_tmdb_id="999", content_key="tmdb:999|movie")
        idless = _channel(session, media_type="movie", detected_title="ES Pelicula")
        lonely = _channel(session, media_type="movie", detected_title="Unique")

    with db.session_scope() as session:
        collapses = RepositoryFactory(session).channels.apply_tmdb_enrichment(
            hits={idless: "999", lonely: "12345"}, misses=[]
        )
    assert collapses == 1  # only idless shares its key with another row

    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.detected_tmdb_id, ChannelDB.content_key, ChannelDB.tmdb_enrich_state
        ).filter_by(id=idless).one()
    assert row.detected_tmdb_id == "999"
    assert row.content_key == "tmdb:999|movie"
    assert row.tmdb_enrich_state == "fetched"


def test_apply_enrichment_marks_misses_none(db):
    with db.session_scope() as session:
        _provider(session)
        a = _channel(session, media_type="movie")
        b = _channel(session, media_type="movie")
    with db.session_scope() as session:
        got = RepositoryFactory(session).channels.apply_tmdb_enrichment(hits={}, misses=[a, b])
    assert got == 0
    with db.session_scope(commit=False) as session:
        for cid in (a, b):
            row = session.query(ChannelDB).filter_by(id=cid).one()
            assert row.tmdb_enrich_state == "none"
            assert row.detected_tmdb_id is None


# ---------------------------------------------------------------------------
# 3b. Manager: lazy enqueue → fetch → mark (via _process_batch, deterministic)
# ---------------------------------------------------------------------------


def test_process_batch_movie_hit_collapses(db, config_obj, monkeypatch, qapp):
    with db.session_scope() as session:
        _provider(session)
        _channel(session, media_type="movie", detected_title="EN Movie",
                 detected_tmdb_id="999", content_key="tmdb:999|movie", source_id="100")
        idless = _channel(session, media_type="movie", detected_title="ES Peli", source_id="200")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"200": {"info": {"tmdb_id": "999"}}}, calls=calls))

    collapses: list = []
    mgr = TmdbEnrichmentManager(db, config_obj)
    mgr.collapses_found.connect(collapses.append)
    try:
        mgr._process_batch([idless])
    finally:
        mgr.shutdown()

    assert ("vod", "200") in calls
    assert collapses == [1]
    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.detected_tmdb_id, ChannelDB.content_key, ChannelDB.tmdb_enrich_state
        ).filter_by(id=idless).one()
    assert row.detected_tmdb_id == "999"
    assert row.content_key == "tmdb:999|movie"
    assert row.tmdb_enrich_state == "fetched"


def test_process_batch_series_uses_series_endpoint(db, config_obj, monkeypatch, qapp):
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, media_type="series", detected_title="Serie", source_id="300")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(series={"300": {"info": {"tmdb_id": "42"}}}, calls=calls))

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr._process_batch([cid])
    finally:
        mgr.shutdown()

    assert ("series", "300") in calls
    assert not any(kind == "vod" for kind, _ in calls)
    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.content_key).filter_by(id=cid).scalar() == "tmdb:42|series"


def test_process_batch_empty_marks_none_and_not_reattempted(db, config_obj, monkeypatch, qapp):
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, media_type="movie", detected_title="No Id", source_id="400")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"400": {"info": {"tmdb_id": "0"}}}, calls=calls))

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr._process_batch([cid])
        with db.session_scope(commit=False) as session:
            row = session.query(
                ChannelDB.tmdb_enrich_state, ChannelDB.detected_tmdb_id
            ).filter_by(id=cid).one()
        assert row.tmdb_enrich_state == "none"
        assert row.detected_tmdb_id is None

        # Re-processing the same (now-marked) id makes NO further call (fetch-once).
        calls.clear()
        mgr._process_batch([cid])
        assert calls == []
    finally:
        mgr.shutdown()


def test_process_batch_http_error_defers_gracefully(db, config_obj, monkeypatch, qapp):
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, media_type="movie", detected_title="Boom", source_id="500")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"500": "ERROR"}, calls=calls))

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr._process_batch([cid])  # must not raise
    finally:
        mgr.shutdown()

    assert ("vod", "500") in calls
    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.tmdb_enrich_state, ChannelDB.detected_tmdb_id
        ).filter_by(id=cid).one()
    assert row.tmdb_enrich_state is None  # deferred, not marked
    assert row.detected_tmdb_id is None


# ---------------------------------------------------------------------------
# 3c. Per-provider empty-batch backoff (ENRICH-1)
# ---------------------------------------------------------------------------
#
# Owner log 2026-09-03 04:37-04:38: one provider answered two consecutive
# drain batches ALL EMPTY (0/18, then 0/27) at latency=11161ms while another
# provider on the same drain landed 39-40 hits per batch. _process_batch had
# no memory between batches, so the silent provider kept eating its share of
# every drain. These tests drive _process_batch directly (same pattern as 3b
# above) with a monkeypatched _fetch_provider, reusing the `_provider`/
# `_channel` seeders shared with every other test in this file — no second
# seeder.


def _scripted_fetch_provider(monkeypatch, responses):
    """Monkeypatch stand-in for ``TmdbEnrichmentManager._fetch_provider``.

    ``responses`` maps provider_id -> a list of "recipes" consumed one per
    call to that provider (the last entry repeats once the list is down to
    one). A recipe is the string ``"empty"`` (every row of that call is a
    miss), ``"hit"`` (every row is a hit with a canned tmdb id), or a
    callable ``recipe(rows) -> (hits, misses, meta, errors)`` for a test that
    needs to control specific rows (ids aren't known until the DB assigns
    them). ``deferred`` is always False — these are real, completed batches.

    Returns the list of provider ids ``_fetch_provider`` was actually called
    for, in call order — the thing every test below asserts against.
    """
    calls: list[str] = []
    queues = {pid: list(seq) for pid, seq in responses.items()}

    async def fake(self, provider, rows, concurrency, throttle):
        calls.append(provider.id)
        queue = queues[provider.id]
        recipe = queue.pop(0) if len(queue) > 1 else queue[0]
        if recipe == "empty":
            return ({}, [r["id"] for r in rows], {}, 0, False)
        if recipe == "hit":
            hits = {r["id"]: str(900000 + i) for i, r in enumerate(rows)}
            return (hits, [], {}, 0, False)
        hits, misses, meta, errors = recipe(rows)
        return (dict(hits), list(misses), dict(meta), errors, False)

    monkeypatch.setattr(TmdbEnrichmentManager, "_fetch_provider", fake)
    return calls


def _idless_movies(session, provider_id: str, n: int) -> list[str]:
    """Seed *n* fresh idless/unattempted movie candidates for *provider_id*."""
    return [
        _channel(session, provider_id=provider_id, media_type="movie",
                 detected_title=f"{provider_id}-{i}", source_id=f"{provider_id}-{i}")
        for i in range(n)
    ]


def test_three_consecutive_empty_batches_backs_off_provider(db, config_obj, monkeypatch, qapp):
    """3 straight all-empty (>= _EMPTY_STREAK_MIN_ROWS-row) batches for A ->
    the 4th drain does NOT call _fetch_provider for A, while B (which hits
    every batch) keeps being fetched. The "skipped — backing off" line is
    logged exactly once — at the moment the backoff is set, not per skip.

    Pre-fix (no streak/backoff at all) this fails: A would be fetched a 4th
    time and no "backing off" line would ever be logged.
    """
    from loguru import logger as _loguru_logger

    with db.session_scope() as session:
        _provider(session, "pA")
        _provider(session, "pB")

    calls = _scripted_fetch_provider(monkeypatch, {"pA": ["empty"], "pB": ["hit"]})

    messages: list[str] = []
    sink_id = _loguru_logger.add(
        lambda msg: messages.append(msg.record["message"]), level="INFO")

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        for _ in range(_EMPTY_STREAK_LIMIT):
            with db.session_scope() as session:
                a_ids = _idless_movies(session, "pA", _EMPTY_STREAK_MIN_ROWS)
                b_ids = _idless_movies(session, "pB", 2)
            mgr._process_batch(a_ids + b_ids)

        assert calls.count("pA") == _EMPTY_STREAK_LIMIT
        assert calls.count("pB") == _EMPTY_STREAK_LIMIT

        with db.session_scope() as session:
            a_ids_4 = _idless_movies(session, "pA", _EMPTY_STREAK_MIN_ROWS)
            b_ids_4 = _idless_movies(session, "pB", 2)
        mgr._process_batch(a_ids_4 + b_ids_4)
    finally:
        mgr.shutdown()
        _loguru_logger.remove(sink_id)

    # 4th drain: A is skipped entirely, B is still fetched.
    assert calls.count("pA") == _EMPTY_STREAK_LIMIT, \
        "A must NOT be fetched on the backed-off drain"
    assert calls.count("pB") == _EMPTY_STREAK_LIMIT + 1

    with db.session_scope(commit=False) as session:
        untouched = session.query(ChannelDB.tmdb_enrich_state).filter(
            ChannelDB.id.in_(a_ids_4)).all()
    assert all(r.tmdb_enrich_state is None for r in untouched), \
        "A's rows on the skipped drain must stay pending, not marked"

    backoff_lines = [m for m in messages if "backing off" in m]
    assert len(backoff_lines) == 1
    assert "Provider pA" in backoff_lines[0]


def test_a_hit_after_two_empties_resets_the_streak(db, config_obj, monkeypatch, qapp):
    """A hit resets the streak — 2 empties + 1 hit + 2 more empties never backs off.

    Without the reset, the two pre-hit empties would still count: the two
    empties after the hit would carry the streak from 2 straight to the
    _EMPTY_STREAK_LIMIT and back A off before the 5th call — proving this
    needs the reset, not just the plain empty-batch counter.
    """
    def _one_hit(rows):
        ids = [r["id"] for r in rows]
        return {ids[0]: "12345"}, ids[1:], {}, 0

    with db.session_scope() as session:
        _provider(session, "pA")

    calls = _scripted_fetch_provider(
        monkeypatch, {"pA": ["empty", "empty", _one_hit, "empty", "empty"]})

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        for _ in range(5):
            with db.session_scope() as session:
                ids = _idless_movies(session, "pA", _EMPTY_STREAK_MIN_ROWS)
            mgr._process_batch(ids)
    finally:
        mgr.shutdown()

    # All 5 batches were actually fetched — the hit on batch 3 cleared the
    # streak the first two empties had built, so the two empties after it
    # (2 total, short of the 3-limit) never triggered a backoff.
    assert calls.count("pA") == 5
    with mgr._lock:
        assert mgr._empty_streak.get("pA", 0) == 2
        assert "pA" not in mgr._provider_backoff_until


def test_small_empty_batch_does_not_count_toward_streak(db, config_obj, monkeypatch, qapp):
    """A batch under _EMPTY_STREAK_MIN_ROWS that misses says nothing — no streak."""
    assert _EMPTY_STREAK_MIN_ROWS > 3, "test assumes 3 rows is below the floor"

    with db.session_scope() as session:
        _provider(session, "pA")

    calls = _scripted_fetch_provider(monkeypatch, {"pA": ["empty"]})

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        for _ in range(_EMPTY_STREAK_LIMIT + 2):
            with db.session_scope() as session:
                ids = _idless_movies(session, "pA", 3)
            mgr._process_batch(ids)
    finally:
        mgr.shutdown()

    # Every batch was fetched — a 3-row miss never advances the streak, so
    # the provider was never backed off no matter how many ran.
    assert calls.count("pA") == _EMPTY_STREAK_LIMIT + 2
    with mgr._lock:
        assert mgr._empty_streak.get("pA", 0) == 0
        assert "pA" not in mgr._provider_backoff_until


def test_provider_is_fetched_again_after_backoff_expires(db, config_obj, monkeypatch, qapp):
    """Past the _EMPTY_BACKOFF_S deadline, a rested provider is tried again."""
    with db.session_scope() as session:
        _provider(session, "pA")

    calls = _scripted_fetch_provider(monkeypatch, {"pA": ["empty"]})

    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        for _ in range(_EMPTY_STREAK_LIMIT):
            with db.session_scope() as session:
                ids = _idless_movies(session, "pA", _EMPTY_STREAK_MIN_ROWS)
            mgr._process_batch(ids)
        assert calls.count("pA") == _EMPTY_STREAK_LIMIT

        # Still well inside the backoff window: not fetched.
        clock["t"] += 60.0
        with db.session_scope() as session:
            ids = _idless_movies(session, "pA", _EMPTY_STREAK_MIN_ROWS)
        mgr._process_batch(ids)
        assert calls.count("pA") == _EMPTY_STREAK_LIMIT

        # Past the deadline: fetched again.
        clock["t"] += _EMPTY_BACKOFF_S + 1.0
        with db.session_scope() as session:
            ids = _idless_movies(session, "pA", _EMPTY_STREAK_MIN_ROWS)
        mgr._process_batch(ids)
        assert calls.count("pA") == _EMPTY_STREAK_LIMIT + 1
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 3b. Migration-resilience wave 2 — defer bulk writes while a migration runs
# ---------------------------------------------------------------------------
#
# Owner log 2026-08-01: a details-pane browse enqueued a drain batch whose
# write raced a running Migration Center pass ("database is locked" 90s after
# an earlier migration crash). TmdbEnrichmentManager now polls an injected
# MigrationManager's `.is_running` before each bulk-write batch method and
# yields its single-worker turn instead — see _defer_for_migration.

class _FakeMigrationManager:
    """Reports `.is_running` True for a fixed number of polls, then False."""

    def __init__(self, running_for_n_checks: int) -> None:
        self._remaining = running_for_n_checks
        self.checks = 0

    @property
    def is_running(self) -> bool:
        self.checks += 1
        if self._remaining > 0:
            self._remaining -= 1
            return True
        return False


def test_defer_for_migration_polls_until_not_running(db, config_obj, monkeypatch, qapp):
    from metatv.core import tmdb_enrichment_manager as tem_mod

    sleeps: list[float] = []
    monkeypatch.setattr(tem_mod.time, "sleep", lambda s: sleeps.append(s))

    fake_mm = _FakeMigrationManager(running_for_n_checks=3)
    mgr = TmdbEnrichmentManager(db, config_obj, migration_manager=fake_mm)
    try:
        mgr._defer_for_migration()
    finally:
        mgr.shutdown()

    assert len(sleeps) == 3, f"expected 3 poll sleeps while migration ran, got {sleeps}"
    assert all(s == tem_mod._MIGRATION_DEFER_POLL_S for s in sleeps)
    assert fake_mm.checks == 4, "expected one extra check that finally saw not-running"


def test_defer_for_migration_no_wait_when_not_running(db, config_obj, monkeypatch, qapp):
    from metatv.core import tmdb_enrichment_manager as tem_mod

    sleeps: list[float] = []
    monkeypatch.setattr(tem_mod.time, "sleep", lambda s: sleeps.append(s))

    fake_mm = _FakeMigrationManager(running_for_n_checks=0)
    mgr = TmdbEnrichmentManager(db, config_obj, migration_manager=fake_mm)
    try:
        mgr._defer_for_migration()
    finally:
        mgr.shutdown()

    assert sleeps == [], "must not sleep when the migration is already finished"


def test_defer_for_migration_noop_without_migration_manager(db, config_obj, monkeypatch, qapp):
    """Default construction (migration_manager=None) — zero behavior change
    for every existing call site that doesn't wire one in."""
    from metatv.core import tmdb_enrichment_manager as tem_mod

    sleeps: list[float] = []
    monkeypatch.setattr(tem_mod.time, "sleep", lambda s: sleeps.append(s))

    mgr = TmdbEnrichmentManager(db, config_obj)  # no migration_manager
    try:
        mgr._defer_for_migration()
    finally:
        mgr.shutdown()

    assert sleeps == []


def test_defer_for_migration_bounded_by_max_wait(db, config_obj, monkeypatch, qapp):
    """A stuck/misreporting MigrationManager can't wedge enrichment forever —
    the courtesy wait is bounded."""
    from metatv.core import tmdb_enrichment_manager as tem_mod

    sleeps: list[float] = []
    monkeypatch.setattr(tem_mod.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(tem_mod, "_MIGRATION_DEFER_MAX_WAIT_S", 3.0)

    class _AlwaysRunning:
        is_running = True

    mgr = TmdbEnrichmentManager(db, config_obj, migration_manager=_AlwaysRunning())
    try:
        mgr._defer_for_migration()
    finally:
        mgr.shutdown()

    # 3.0s ceiling / 1.0s poll interval => bails after 3 sleeps.
    assert len(sleeps) == 3, f"expected the wait to be capped at 3 polls, got {sleeps}"


def test_process_batch_defers_then_completes_once_migration_finishes(
    db, config_obj, monkeypatch, qapp
):
    """End-to-end: a drain batch called while a migration is "running" waits,
    then still completes (enriches the row) once it reports finished — the
    write isn't dropped, just delayed."""
    from metatv.core import tmdb_enrichment_manager as tem_mod

    with db.session_scope() as session:
        _provider(session)
        _channel(session, media_type="movie", detected_title="EN Movie",
                 detected_tmdb_id="999", content_key="tmdb:999|movie", source_id="100")
        idless = _channel(session, media_type="movie", detected_title="ES Peli", source_id="200")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"200": {"info": {"tmdb_id": "999"}}}, calls=calls))

    sleeps: list[float] = []
    monkeypatch.setattr(tem_mod.time, "sleep", lambda s: sleeps.append(s))

    fake_mm = _FakeMigrationManager(running_for_n_checks=2)
    mgr = TmdbEnrichmentManager(db, config_obj, migration_manager=fake_mm)
    try:
        mgr._process_batch([idless])
    finally:
        mgr.shutdown()

    assert len(sleeps) == 2, f"expected the batch to defer twice, got {sleeps}"
    assert ("vod", "200") in calls  # ...but still ran once the migration "finished"
    with db.session_scope(commit=False) as session:
        row = session.query(ChannelDB.detected_tmdb_id).filter_by(id=idless).one()
    assert row.detected_tmdb_id == "999"


def test_enqueue_disabled_by_config_makes_no_calls(db, config_obj, monkeypatch, qapp):
    config_obj.tmdb_enrichment_enabled = False
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, media_type="movie", source_id="600")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"600": {"info": {"tmdb_id": "1"}}}, calls=calls))

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr.enqueue([cid])          # gated off — nothing queued, nothing submitted
        _drain(mgr, qapp, timeout=1.0)
    finally:
        mgr.shutdown()
    assert calls == []


def test_enqueue_end_to_end_and_dedup(db, config_obj, monkeypatch, qapp):
    """The public enqueue path drains, enriches, and drops re-enqueued ids."""
    with db.session_scope() as session:
        _provider(session)
        _channel(session, media_type="movie", detected_title="EN Movie",
                 detected_tmdb_id="999", content_key="tmdb:999|movie", source_id="100")
        idless = _channel(session, media_type="movie", detected_title="ES Peli", source_id="200")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"200": {"info": {"tmdb_id": "999"}}}, calls=calls))

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr.enqueue([idless, "100"])   # '100' already has an id → filtered off-thread
        _drain(mgr, qapp)
        assert ("vod", "200") in calls
        with db.session_scope(commit=False) as session:
            assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=idless).scalar() == "999"

        # Re-enqueue the same ids: _seen drops them, no new work submitted.
        calls.clear()
        mgr.enqueue([idless, "100"])
        _drain(mgr, qapp, timeout=1.0)
        assert calls == []
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 4. Notification — source-attributed, coalesced, via a MAIN-THREAD signal
# ---------------------------------------------------------------------------


def test_progress_signal_is_source_attributed_and_coalesced(db, config_obj, qapp):
    """The worker publishes counts via enrichment_progress, never NotificationManager."""
    with db.session_scope() as session:
        _provider(session, "p1")
        a = _channel(session, "p1", media_type="movie", detected_title="A", source_id="1")
        b = _channel(session, "p1", media_type="movie", detected_title="B", source_id="2")

    mgr = TmdbEnrichmentManager(db, config_obj)
    # The manager must have NO handle to the NotificationManager (signal-only path).
    assert not hasattr(mgr, "notification_manager")

    events: list = []
    mgr.enrichment_progress.connect(lambda pid, name, n: events.append((name, n)))

    # Resolve a batch (emits the start count) then clear (emits 0) — the drain's ends.
    by_provider = {"p1": [{"id": a, "source_id": "1", "media_type": "movie"},
                          {"id": b, "source_id": "2", "media_type": "movie"}]}
    names = {"p1": "Provider p1"}
    mgr._begin_inflight(by_provider, names)
    mgr._clear_all_inflight()
    mgr.shutdown()

    assert events == [("Provider p1", 2), ("Provider p1", 0)]


def test_enrichment_settled_emitted_once_when_the_queue_fully_drains(
    db, config_obj, monkeypatch, qapp
):
    """enrichment_settled fires exactly once after a real enqueue()-driven drain.

    RefreshCoalescer (gui/refresh_coalescer.py) uses this signal as its
    drain-complete flush trigger, so it must fire after the batch write AND
    the end-of-drain sibling-propagation sweep have both run — not mid-drain.
    """
    with db.session_scope() as session:
        _provider(session)
        idless = _channel(session, media_type="movie", detected_title="ES Peli", source_id="200")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"200": {"info": {"tmdb_id": "999"}}}, calls=calls))

    settled: list = []
    mgr = TmdbEnrichmentManager(db, config_obj)
    mgr.enrichment_settled.connect(lambda: settled.append(None))
    try:
        mgr.enqueue([idless])
        _drain(mgr, qapp)
    finally:
        mgr.shutdown()

    assert settled == [None]


def test_host_notification_slot_coalesces_show_update_dismiss():
    """MainWindow._on_tmdb_enrichment_progress: one toast per source, updated then cleared."""
    from metatv.gui.main_window import MainWindow

    class _FakeNM:
        def __init__(self):
            self.calls = []

        def show(self, *, title, message, type, dismissible):
            self.calls.append(("show", message))
            return "notif-1"

        def update(self, notif_id, **kwargs):
            self.calls.append(("update", notif_id, kwargs.get("message")))

        def dismiss(self, notif_id):
            self.calls.append(("dismiss", notif_id))

    class _Host:
        pass

    host = _Host()
    host.notification_manager = _FakeNM()
    host._tmdb_enrich_notifs = {}

    slot = MainWindow._on_tmdb_enrichment_progress
    slot(host, "p1", "Acme", 2)   # create
    slot(host, "p1", "Acme", 5)   # update in place (coalesced)
    slot(host, "p1", "Acme", 0)   # dismiss when drained

    kinds = [c[0] for c in host.notification_manager.calls]
    assert kinds == ["show", "update", "dismiss"]
    assert "2 titles from Acme" in host.notification_manager.calls[0][1]
    assert "5 titles from Acme" in host.notification_manager.calls[1][2]
    assert host._tmdb_enrich_notifs == {}  # cleared after dismiss


# ---------------------------------------------------------------------------
# 5. "Missing TMDb data" view — repo lists idless rows; opening it enqueues
# ---------------------------------------------------------------------------


def test_missing_by_source_lists_only_idless(db):
    with db.session_scope() as session:
        _provider(session, "p1")
        i1 = _channel(session, "p1", media_type="movie", detected_title="Idless One")
        i2 = _channel(session, "p1", media_type="series", detected_title="Idless Two")
        _channel(session, "p1", media_type="movie", detected_tmdb_id="5")   # has id → excluded
        _channel(session, "p1", media_type="live", detected_title="CNN")     # live → excluded
        _channel(session, "p1", media_type="movie", detected_title="Hid", is_hidden=True)

    with db.session_scope(commit=False) as session:
        groups = RepositoryFactory(session).channels.missing_tmdb_by_source(set())

    assert len(groups) == 1
    g = groups[0]
    assert g.provider_id == "p1"
    assert g.missing_count == 2
    sampled = {r.channel_id for r in g.sample}
    assert sampled == {i1, i2}


def test_missing_view_slot_enqueues_loaded_sample():
    from metatv.gui.missing_tmdb_view import MissingTmdbView
    from metatv.core.repositories.dtos import MissingTmdbSourceDTO, MissingTmdbRowDTO

    enqueued: list = []

    class _FakeMW:
        def _enqueue_tmdb_enrichment(self, ids):
            enqueued.extend(ids)

    class _FakeLayout:
        def addWidget(self, *_a, **_k):
            pass

    view = MissingTmdbView.__new__(MissingTmdbView)   # skip QWidget __init__
    view.main_window = _FakeMW()
    view._clear_layout = lambda layout: None
    view._sources_layout = _FakeLayout()
    view._source_block = lambda group: None  # don't build real widgets in this unit test

    groups = [
        MissingTmdbSourceDTO(
            provider_id="p1", provider_name="Acme", missing_count=2, residual_count=0,
            sample=[
                MissingTmdbRowDTO("cid-a", "A", "A", "2020", "movie", True),
                MissingTmdbRowDTO("cid-b", "B", "B", None, "series", True),
            ],
        )
    ]
    # Bypass the real QWidget layout rendering; only the enqueue side-effect matters.
    view._on_sources_loaded(groups)
    assert set(enqueued) == {"cid-a", "cid-b"}


# ---------------------------------------------------------------------------
# 6. Analytics funnel — provenance buckets + residual
# ---------------------------------------------------------------------------


def test_funnel_buckets_by_provenance_and_residual(db):
    with db.session_scope() as session:
        _provider(session, "p1")
        _channel(session, "p1", media_type="movie", detected_tmdb_id="1", tmdb_enrich_state="list")
        _channel(session, "p1", media_type="movie", detected_tmdb_id="2", tmdb_enrich_state="propagated")
        _channel(session, "p1", media_type="series", detected_tmdb_id="3", tmdb_enrich_state="fetched")
        _channel(session, "p1", media_type="movie")                              # unattempted
        _channel(session, "p1", media_type="movie", tmdb_enrich_state="none")    # residual
        _channel(session, "p1", media_type="live")                              # live → excluded
        _channel(session, "p1", media_type="movie", is_hidden=True)             # hidden → excluded

    with db.session_scope(commit=False) as session:
        f = RepositoryFactory(session).channels.tmdb_enrichment_funnel(set())

    assert f.from_list == 1
    assert f.propagated == 1
    assert f.fetched == 1
    assert f.unattempted == 1
    assert f.residual == 1               # idless AND 'none'
    assert f.total_vod == 5
    assert f.resolved == 3
    assert f.idless == 2


def test_funnel_excludes_hidden_providers(db):
    with db.session_scope() as session:
        _provider(session, "p1", is_active=True)
        _provider(session, "p2", is_active=False)
        _channel(session, "p1", media_type="movie")
        _channel(session, "p2", media_type="movie")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        excluded = set(repos.providers.get_hidden_provider_ids())
        f = repos.channels.tmdb_enrichment_funnel(excluded)
    assert f.total_vod == 1  # only the active provider's row


# ---------------------------------------------------------------------------
# 7. The provider request carries the app User-Agent (unchanged base)
# ---------------------------------------------------------------------------


def test_get_vod_info_hits_vod_endpoint(monkeypatch):
    from metatv.providers.xtream import XtreamAPI

    seen: dict = {}

    class _Resp:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def json(self, content_type=None):
            return {"info": {"tmdb_id": "1181863"}}

    class _FakeSession:
        def __init__(self, *a, headers=None, **k):
            pass

        def get(self, url, timeout=None):
            seen["url"] = url
            return _Resp()

        async def close(self):
            return None

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", _FakeSession)

    async def _run():
        async with XtreamAPI("http://host:8080", "u", "p") as api:
            return await api.get_vod_info("1471095")

    data = asyncio.run(_run())
    assert "action=get_vod_info" in seen["url"]
    assert "vod_id=1471095" in seen["url"]
    assert _extract_tmdb_id(data) == "1181863"


# ---------------------------------------------------------------------------
# 7. Post-drain sibling propagation — an id learned by a FETCH must reach its
#    siblings (#284)
# ---------------------------------------------------------------------------
#
# Propagation ran at ingestion and after a refresh queue drained, but never after
# enrichment.  So an id discovered by browsing identified exactly one row and
# stopped there: the owner's "The Lobster" sat as a 'fetched' tmdb:254320 row
# beside two idless copies of itself, reading as if versions were missing.


def test_drain_that_writes_ids_propagates_them_to_siblings(db, config_obj, monkeypatch, qapp):
    """The reported shape end to end: a fetch identifies one row, siblings follow."""
    with db.session_scope() as session:
        _provider(session)
        target = _channel(session, media_type="movie", detected_title="The Lobster",
                          source_id="10", content_key="the lobster|movie|")
        sib_a = _channel(session, media_type="movie", detected_title="The Lobster",
                         detected_year="2015", source_id="11",
                         content_key="the lobster|movie|2015")
        sib_b = _channel(session, media_type="movie", detected_title="The Lobster",
                         source_id="12", content_key="the lobster|movie|")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"10": {"info": {"tmdb_id": "254320"}}},
                                       calls=calls))

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr.enqueue([target])          # only the browsed row is enqueued
        _drain(mgr, qapp)
    finally:
        mgr.shutdown()

    with db.session_scope(commit=False) as session:
        keys = {
            r.content_key
            for r in session.query(ChannelDB.content_key)
            .filter(ChannelDB.id.in_([target, sib_a, sib_b])).all()
        }
    assert keys == {"tmdb:254320|movie"}, (
        f"the fetched id never reached the siblings — still {sorted(keys)}; "
        f"'Other versions' cannot group them"
    )


def test_a_drain_that_learns_nothing_runs_no_sweep(db, config_obj, monkeypatch, qapp):
    """Browsing that resolves nothing must not pay for a whole-library scan."""
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, media_type="movie", detected_title="Nothing Here",
                       source_id="20")

    calls: list = []
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod={"20": {"info": {}}}, calls=calls))

    swept: list = []
    from metatv.core.repositories.channel import ChannelRepository
    real = ChannelRepository.propagate_tmdb_from_title_siblings
    monkeypatch.setattr(
        ChannelRepository, "propagate_tmdb_from_title_siblings",
        lambda self, *a, **k: (swept.append(1), real(self, *a, **k))[1],
    )

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr.enqueue([cid])
        _drain(mgr, qapp)
    finally:
        mgr.shutdown()

    assert calls, "the fetch never ran — the test would pass vacuously"
    assert swept == [], "swept the whole library after a drain that wrote no ids"


def test_the_sweep_runs_once_per_drain_not_once_per_batch(db, config_obj, monkeypatch, qapp):
    """It is a whole-library scan; per-batch would make browsing quadratic."""
    with db.session_scope() as session:
        _provider(session)
        ids = [
            _channel(session, media_type="movie", detected_title=f"Film {i}",
                     source_id=str(300 + i))
            for i in range(6)                                # 3 batches of 2
        ]

    calls: list = []
    monkeypatch.setattr(
        "metatv.providers.xtream.XtreamAPI",
        _make_fake_api(
            vod={str(300 + i): {"info": {"tmdb_id": str(600 + i)}} for i in range(6)},
            calls=calls,
        ),
    )
    monkeypatch.setattr("metatv.core.tmdb_enrichment_manager._DRAIN_BATCH", 2)

    sweeps: list = []
    from metatv.core.repositories.channel import ChannelRepository
    real = ChannelRepository.propagate_tmdb_from_title_siblings
    monkeypatch.setattr(
        ChannelRepository, "propagate_tmdb_from_title_siblings",
        lambda self, *a, **k: (sweeps.append(1), real(self, *a, **k))[1],
    )

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr.enqueue(ids)
        _drain(mgr, qapp)
    finally:
        mgr.shutdown()

    assert len(calls) == 6, f"expected 6 fetches across 3 batches, got {len(calls)}"
    assert len(sweeps) == 1, f"swept {len(sweeps)}x for one drain of 3 batches"
