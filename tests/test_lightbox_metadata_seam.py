"""The Similar-Titles lightbox enriches its main card via the canonical
``metadata_manager.get_metadata`` seam (on-demand), not by reading the stored
``MetadataDB`` row.

Root cause these tests lock down: metadata is fetched on demand, so only ~0.2% of
channels have a stored ``MetadataDB`` row. The lightbox used to read ONLY that
stored row (``session.get(MetadataDB, ch.metadata_id)``), leaving the card bare
(no poster/plot/cast/genres/rating) for any title never previously opened in the
details pane. The fix routes the main card through the SAME 3-tier seam the details
pane uses (DB cache → provider raw_data → external API), which also persists on
fetch — so repeat opens are cheap.

Real file-backed SQLite + real ``Config``; the ONLY mocked boundary is the
network/metadata fetch (``get_metadata``), per the tests-prove-behavior rule.
"""

from __future__ import annotations

import uuid

from metatv.metadata_providers.base import MetadataResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _config(tmp_path):
    """A real Config rooted in tmp_path (autouse _isolate_user_config also guards home)."""
    from metatv.core.config import Config
    return Config(config_dir=tmp_path)


def _make_provider(session, pid="p1"):
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=True,
    ))
    session.flush()


def _make_channel(session, *, cid, name, content_key, provider_id="p1",
                  media_type="movie", metadata_id=None, detected_year=None):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        content_key=content_key,
        metadata_id=metadata_id,
        detected_year=detected_year,
    )
    session.add(ch)
    session.flush()
    return ch


class _StubMM:
    """Stand-in MetadataManager: records each call, returns a per-id MetadataResult.

    This is the single mocked boundary — the on-demand network/metadata fetch.
    ``get_metadata`` is a coroutine (matching the real seam), so the lightbox's
    event-loop invocation exercises the real code path.
    """

    def __init__(self, results=None):
        self._results = results or {}
        self.calls: list[str] = []

    async def get_metadata(self, channel_id, force_refresh=False):
        self.calls.append(channel_id)
        return self._results.get(channel_id)


def _lightbox(db, config, mm):
    """A SimilarTitleLightbox with only the attrs ``_bg_load`` touches (no Qt tree)."""
    from metatv.gui.similar_lightbox import SimilarTitleLightbox

    emitted: list[tuple] = []

    class _Sig:
        def emit(self, cid, data):
            emitted.append((cid, data))

    lb = SimilarTitleLightbox.__new__(SimilarTitleLightbox)
    lb._db = db
    lb._config = config
    lb._metadata_manager = mm
    lb._data_ready = _Sig()
    lb._emitted = emitted
    return lb


def _load(db, config, mm, channel_id) -> dict:
    lb = _lightbox(db, config, mm)
    lb._bg_load(channel_id)
    assert lb._emitted, "lightbox emitted no data"
    return lb._emitted[0][1]


_RICH = MetadataResult(
    title="Rich Movie",
    year=2021,
    plot="A gripping tale spanning decades.",
    poster_url="https://image.tmdb.org/t/p/w500/rich.jpg",
    cast=[{"name": "Jane Doe"}, {"name": "John Roe"}],
    genres=["Drama", "Thriller"],
    rating=7.8,
    runtime=118,
    director="Ada Helm",
)


# ---------------------------------------------------------------------------
# 1. Main card fills from the on-demand fetch (the real-bug fix)
# ---------------------------------------------------------------------------

def test_main_card_populated_from_fetched_metadata(tmp_path):
    """A channel with NO stored MetadataDB row still gets a full card from the seam.

    FAILS against the old stored-only read: with metadata_id=None the old
    ``session.get(MetadataDB, ...)`` was None, so poster/plot/rating were None,
    cast="" and genres=[].
    """
    db = _make_db(tmp_path / "seam_main.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_channel(s, cid="main", name="Rich Movie", content_key="k-rich|movie")

    mm = _StubMM({"main": _RICH})
    data = _load(db, _config(tmp_path), mm, "main")

    assert data.get("poster_url") == "https://image.tmdb.org/t/p/w500/rich.jpg"
    assert data.get("plot") == "A gripping tale spanning decades."
    cast = data.get("cast") or ""
    assert "Jane Doe" in cast and "dir. Ada Helm" in cast
    assert data.get("genres") == ["Drama", "Thriller"]
    assert data.get("rating") == 7.8
    assert data.get("runtime") == 118
    assert data.get("year") == 2021
    db.close()


def test_get_metadata_invoked_with_channel_id(tmp_path):
    """The seam is actually used — get_metadata is called with the main channel id."""
    db = _make_db(tmp_path / "seam_called.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_channel(s, cid="main", name="Rich Movie", content_key="k-rich|movie")

    mm = _StubMM({"main": _RICH})
    _load(db, _config(tmp_path), mm, "main")

    assert mm.calls == ["main"], (
        f"the shared metadata seam must be invoked for the main channel; got {mm.calls}"
    )
    db.close()


def test_missing_metadata_degrades_gracefully(tmp_path):
    """No provider data anywhere → get_metadata returns None → card degrades, no crash."""
    db = _make_db(tmp_path / "seam_none.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_channel(s, cid="main", name="Bare Movie",
                      content_key="k-bare|movie", detected_year=1998)

    mm = _StubMM({})  # returns None for every id
    data = _load(db, _config(tmp_path), mm, "main")

    assert data, "even with no metadata the card gets its channel-derived skeleton"
    assert data.get("name") == "Bare Movie"
    assert data.get("plot") is None
    # Falls back to the ingested detected_year (stored as a string on ChannelDB).
    assert str(data.get("year")) == "1998"
    assert mm.calls == ["main"]
    db.close()


# ---------------------------------------------------------------------------
# 2. Perf guard — the strip is NOT fetched on demand per item
# ---------------------------------------------------------------------------

def test_strip_does_not_call_get_metadata_per_item(tmp_path):
    """Only the MAIN card is fetched on demand; the (<=12) strip items stay light.

    12 network fetches on every open would make browsing janky, so the strip reads
    name/year from channel fields and its poster from the STORED MetadataDB row if
    present (else a placeholder).
    """
    from metatv.core.database import MetadataDB

    db = _make_db(tmp_path / "seam_strip.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_channel(s, cid="main", name="Galaxy Warriors Rising",
                      content_key="k-main|movie")
        # Two similar candidates sharing the >=4-length words galaxy/warriors.
        s.add(MetadataDB(id="sm1", title="Galaxy Warriors Reborn", year=2019,
                         poster_url="https://img/reborn.jpg"))
        s.flush()
        c1 = _make_channel(s, cid="sim1", name="Galaxy Warriors Reborn",
                           content_key="k-sim1|movie")
        c1.metadata_id = "sm1"
        _make_channel(s, cid="sim2", name="Galaxy Warriors Legends",
                      content_key="k-sim2|movie")

    mm = _StubMM({"main": _RICH})
    data = _load(db, _config(tmp_path), mm, "main")

    assert len(data.get("similar") or []) >= 2, "expected similar candidates in the strip"
    assert mm.calls == ["main"], (
        f"get_metadata must run ONCE (main only), never per strip item; got {mm.calls}"
    )
    # The strip poster comes from the STORED row (proving no on-demand fetch for it).
    strip = {item["id"]: item for item in data["similar"]}
    assert strip["sim1"]["poster_url"] == "https://img/reborn.jpg"
    assert strip["sim2"]["poster_url"] is None  # no stored row → placeholder path
    db.close()
