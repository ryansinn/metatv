"""Behavioral tests for Phase 2 — provider-native TMDb enrichment of idless VOD.

Covers the full changed path with all provider HTTP mocked (never a real
provider) and a file-backed (tmp_path) SQLite DB per CLAUDE.md:

1. ``select_tmdb_enrichment_candidates`` picks only idless, unattempted, visible,
   active-provider VOD rows.
2. ``apply_tmdb_enrichment`` stores the id, recomputes ``content_key`` through the
   ``content_key_for`` chokepoint (tmdb-first), marks the attempt, and reports the
   number of rows that landed in a shared collapse group.
3. ``reset_tmdb_enrich_state`` clears the marker on content refresh.
4. The manager end-to-end: a movie hit collapses onto an existing same-id row; a
   series row uses ``get_series_info`` (not ``get_vod_info``); an empty response
   marks the row attempted-but-empty and is NOT re-attempted next pass
   (resumability); an HTTP error defers the row gracefully with no crash.
5. The provider request carries the app User-Agent.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache
from metatv.core.tmdb_enrichment_manager import TmdbEnrichmentManager, _extract_tmdb_id


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
            detected_tmdb_id=detected_tmdb_id,
            content_key=content_key,
            tmdb_enrich_state=tmdb_enrich_state,
            is_hidden=is_hidden,
        )
    )
    session.flush()
    return cid


def _make_fake_api(*, vod: dict | None = None, series: dict | None = None, calls: list):
    """Build a drop-in replacement for ``XtreamAPI`` that returns canned detail data.

    Values are keyed by source_id.  A value of the string ``"ERROR"`` raises to
    simulate an HTTP/connection failure.  Every call is appended to *calls* as
    ``("vod"|"series", source_id)`` so a test can assert which endpoint was used.
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


# ---------------------------------------------------------------------------
# 1. _extract_tmdb_id — response parsing
# ---------------------------------------------------------------------------


class TestExtractTmdbId:
    def test_pulls_nested_tmdb_id(self):
        assert _extract_tmdb_id({"info": {"tmdb_id": "1181863"}}) == "1181863"

    def test_accepts_legacy_tmdb_key(self):
        assert _extract_tmdb_id({"info": {"tmdb": "603"}}) == "603"

    @pytest.mark.parametrize("resp", [
        None,
        {},
        {"info": {}},
        {"info": {"tmdb_id": "0"}},      # sentinel
        {"info": {"tmdb_id": ""}},       # sentinel
        {"info": "notadict"},
        [1, 2, 3],
    ])
    def test_rejects_missing_or_sentinel(self, resp):
        assert _extract_tmdb_id(resp) is None


# ---------------------------------------------------------------------------
# 2. Repository: candidate selection
# ---------------------------------------------------------------------------


def test_candidates_only_idless_unattempted_visible_vod(db):
    with db.session_scope() as session:
        _provider(session, "p1", is_active=True)
        _provider(session, "p2", is_active=False)  # hidden (inactive)

        want = _channel(session, "p1", media_type="movie")                 # ✓
        want2 = _channel(session, "p1", media_type="series")               # ✓
        _channel(session, "p1", media_type="movie", detected_tmdb_id="99")  # has id → ✗
        _channel(session, "p1", media_type="movie", tmdb_enrich_state="none")  # attempted → ✗
        _channel(session, "p1", media_type="live")                          # live → ✗
        _channel(session, "p1", media_type="movie", is_hidden=True)         # hidden row → ✗
        _channel(session, "p2", media_type="movie")                        # hidden provider → ✗

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        excluded = set(repos.providers.get_hidden_provider_ids())
        rows = repos.channels.select_tmdb_enrichment_candidates(
            limit=100, excluded_provider_ids=excluded
        )

    ids = {r["id"] for r in rows}
    assert ids == {want, want2}
    # Shape check — plain dicts crossing the worker boundary, no ORM objects.
    assert all(set(r) == {"id", "provider_id", "source_id", "media_type"} for r in rows)


def test_provider_ids_with_candidates(db):
    with db.session_scope() as session:
        _provider(session, "p1")
        _provider(session, "p2")
        _provider(session, "p3", is_active=False)
        _channel(session, "p1", media_type="movie")
        _channel(session, "p2", media_type="series")
        _channel(session, "p2", media_type="movie", detected_tmdb_id="7")  # has id → not a candidate
        _channel(session, "p3", media_type="movie")                        # hidden provider

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        excluded = set(repos.providers.get_hidden_provider_ids())
        pids = set(repos.channels.provider_ids_with_tmdb_candidates(excluded))
    assert pids == {"p1", "p2"}


def test_candidates_respect_limit(db):
    with db.session_scope() as session:
        _provider(session)
        for _ in range(5):
            _channel(session, media_type="movie")

    with db.session_scope(commit=False) as session:
        rows = RepositoryFactory(session).channels.select_tmdb_enrichment_candidates(
            limit=3, excluded_provider_ids=set()
        )
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# 3. Repository: apply enrichment (content_key chokepoint + collapse count)
# ---------------------------------------------------------------------------


def test_apply_enrichment_writes_tmdb_key_and_counts_collapse(db):
    with db.session_scope() as session:
        _provider(session)
        existing = _channel(session, media_type="movie", detected_title="EN Movie",
                            detected_tmdb_id="999", content_key="tmdb:999|movie")
        idless = _channel(session, media_type="movie", detected_title="ES Pelicula")
        lonely = _channel(session, media_type="movie", detected_title="Unique")

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        # idless collapses onto `existing` (same tmdb); lonely gets a unique id.
        collapses = repos.channels.apply_tmdb_enrichment(
            hits={idless: "999", lonely: "12345"}, misses=[]
        )

    # Only `idless` shares its key with another row → exactly one new collapse.
    assert collapses == 1

    with db.session_scope(commit=False) as session:
        r_idless = session.query(
            ChannelDB.detected_tmdb_id, ChannelDB.content_key, ChannelDB.tmdb_enrich_state
        ).filter_by(id=idless).one()
        lonely_key = session.query(ChannelDB.content_key).filter_by(id=lonely).scalar()

    assert r_idless.detected_tmdb_id == "999"
    assert r_idless.content_key == "tmdb:999|movie"   # content_key_for chokepoint, tmdb-first
    assert r_idless.tmdb_enrich_state == "done"
    assert lonely_key == "tmdb:12345|movie"


def test_apply_enrichment_marks_misses(db):
    with db.session_scope() as session:
        _provider(session)
        a = _channel(session, media_type="movie")
        b = _channel(session, media_type="movie")

    with db.session_scope() as session:
        got = RepositoryFactory(session).channels.apply_tmdb_enrichment(
            hits={}, misses=[a, b]
        )
    assert got == 0

    with db.session_scope(commit=False) as session:
        for cid in (a, b):
            row = session.query(ChannelDB).filter_by(id=cid).one()
            assert row.tmdb_enrich_state == "none"
            assert row.detected_tmdb_id is None


def test_series_tmdb_key_namespaced_by_media_type(db):
    with db.session_scope() as session:
        _provider(session)
        s = _channel(session, media_type="series", detected_title="Serie")

    with db.session_scope() as session:
        RepositoryFactory(session).channels.apply_tmdb_enrichment(hits={s: "603"}, misses=[])

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.content_key).filter_by(id=s).scalar() == "tmdb:603|series"


# ---------------------------------------------------------------------------
# 4. Repository: content-refresh marker reset
# ---------------------------------------------------------------------------


def test_reset_clears_marker_for_provider_only(db):
    with db.session_scope() as session:
        _provider(session, "p1")
        _provider(session, "p2")
        a = _channel(session, "p1", tmdb_enrich_state="none")
        b = _channel(session, "p1", tmdb_enrich_state="done", detected_tmdb_id="5")
        other = _channel(session, "p2", tmdb_enrich_state="none")

    with db.session_scope() as session:
        cleared = RepositoryFactory(session).channels.reset_tmdb_enrich_state("p1")

    assert cleared == 2  # both p1 rows, not the p2 row

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=a).scalar() is None
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=b).scalar() is None
        assert session.query(ChannelDB.tmdb_enrich_state).filter_by(id=other).scalar() == "none"


# ---------------------------------------------------------------------------
# 5. Manager end-to-end (provider HTTP mocked)
# ---------------------------------------------------------------------------


def test_manager_movie_hit_collapses(db, config_obj, monkeypatch, qapp):
    with db.session_scope() as session:
        _provider(session)
        _channel(session, media_type="movie", detected_title="EN Movie",
                 detected_tmdb_id="999", content_key="tmdb:999|movie", source_id="100")
        idless = _channel(session, media_type="movie", detected_title="ES Pelicula",
                          source_id="200")

    calls: list = []
    fake = _make_fake_api(vod={"200": {"info": {"tmdb_id": "999"}}}, calls=calls)
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI", fake)

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        collapses = mgr._run_pass()
    finally:
        mgr.shutdown()

    assert ("vod", "200") in calls
    assert collapses == 1

    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.detected_tmdb_id, ChannelDB.content_key, ChannelDB.tmdb_enrich_state
        ).filter_by(id=idless).one()
    assert row.detected_tmdb_id == "999"
    assert row.content_key == "tmdb:999|movie"
    assert row.tmdb_enrich_state == "done"


def test_manager_splits_cap_fairly_across_providers(db, config_obj, monkeypatch, qapp):
    """Both providers get attempted in one pass — the big one can't starve the small one."""
    config_obj.tmdb_enrichment_session_cap = 4
    with db.session_scope() as session:
        _provider(session, "big")
        _provider(session, "small")
        # 'big' has many idless rows; 'small' has one. Ordered by provider_id, a
        # single LIMIT would take only 'big' rows — fair splitting must still reach 'small'.
        for i in range(10):
            _channel(session, "big", media_type="movie", source_id=f"b{i}")
        _channel(session, "small", media_type="movie", source_id="s0")

    calls: list = []
    vod = {f"b{i}": {"info": {"tmdb_id": "1"}} for i in range(10)}
    vod["s0"] = {"info": {"tmdb_id": "2"}}
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI",
                        _make_fake_api(vod=vod, calls=calls))

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr._run_pass()
    finally:
        mgr.shutdown()

    attempted = {sid for _kind, sid in calls}
    assert "s0" in attempted, "the small provider must be attempted despite the cap"
    assert len(attempted) <= 4, "the session cap must be respected"


def test_manager_series_uses_series_endpoint(db, config_obj, monkeypatch, qapp):
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, media_type="series", detected_title="Serie", source_id="300")

    calls: list = []
    fake = _make_fake_api(series={"300": {"info": {"tmdb_id": "42"}}}, calls=calls)
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI", fake)

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr._run_pass()
    finally:
        mgr.shutdown()

    assert ("series", "300") in calls
    assert not any(kind == "vod" for kind, _ in calls), "series must not hit the vod endpoint"

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=cid).scalar() == "42"
        assert session.query(ChannelDB.content_key).filter_by(id=cid).scalar() == "tmdb:42|series"


def test_manager_empty_response_not_reattempted(db, config_obj, monkeypatch, qapp):
    """A row the detail endpoint has no id for is marked 'none' and never re-fetched."""
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, media_type="movie", detected_title="No Id", source_id="400")

    calls: list = []
    fake = _make_fake_api(vod={"400": {"info": {"tmdb_id": "0"}}}, calls=calls)
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI", fake)

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr._run_pass()  # first pass — attempted, empty
        with db.session_scope(commit=False) as session:
            row = session.query(
                ChannelDB.tmdb_enrich_state, ChannelDB.detected_tmdb_id
            ).filter_by(id=cid).one()
        assert row.tmdb_enrich_state == "none"
        assert row.detected_tmdb_id is None

        # Second pass — the 'none' marker excludes it, so NO further call is made.
        calls.clear()
        mgr._run_pass()
        assert calls == [], "an attempted-empty row must not be re-fetched (resumability)"
    finally:
        mgr.shutdown()


def test_manager_http_error_defers_gracefully(db, config_obj, monkeypatch, qapp):
    """A transient error leaves the row unattempted (NULL marker) with no crash."""
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, media_type="movie", detected_title="Boom", source_id="500")

    calls: list = []
    fake = _make_fake_api(vod={"500": "ERROR"}, calls=calls)
    monkeypatch.setattr("metatv.providers.xtream.XtreamAPI", fake)

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        collapses = mgr._run_pass()  # must not raise
    finally:
        mgr.shutdown()

    assert collapses == 0
    assert ("vod", "500") in calls  # it WAS attempted
    with db.session_scope(commit=False) as session:
        row = session.query(
            ChannelDB.tmdb_enrich_state, ChannelDB.detected_tmdb_id
        ).filter_by(id=cid).one()
    # Left unattempted → deferred to a future launch (no retry storm within a pass).
    assert row.tmdb_enrich_state is None
    assert row.detected_tmdb_id is None


def test_manager_disabled_by_config_makes_no_calls(db, config_obj, monkeypatch, qapp):
    config_obj.tmdb_enrichment_enabled = False
    with db.session_scope() as session:
        _provider(session)
        _channel(session, media_type="movie", source_id="600")

    calls: list = []
    monkeypatch.setattr(
        "metatv.providers.xtream.XtreamAPI",
        _make_fake_api(vod={"600": {"info": {"tmdb_id": "1"}}}, calls=calls),
    )

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        mgr.start()          # gated off — submits nothing
        mgr._executor.shutdown(wait=True)
    finally:
        pass
    assert calls == []


# ---------------------------------------------------------------------------
# 6. The provider request carries the app User-Agent
# ---------------------------------------------------------------------------


def test_request_sends_app_user_agent(monkeypatch):
    """XtreamAPI opens its session with the canonical stream User-Agent header."""
    import aiohttp

    from metatv.core.http_headers import stream_user_agent
    from metatv.providers.xtream import XtreamAPI

    captured: dict = {}

    class _FakeSession:
        def __init__(self, *args, headers=None, **kwargs):
            captured["headers"] = headers or {}

        async def close(self):
            return None

    monkeypatch.setattr(aiohttp, "ClientSession", _FakeSession)

    async def _open():
        async with XtreamAPI("http://host:8080", "u", "p"):
            pass

    asyncio.run(_open())

    assert captured["headers"].get("User-Agent") == stream_user_agent()


def test_get_vod_info_hits_vod_endpoint(monkeypatch):
    """get_vod_info builds the get_vod_info action URL and returns the parsed body."""
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
