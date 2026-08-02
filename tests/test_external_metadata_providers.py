"""Behavioral tests for wave4/external-metadata-providers.

Covers TMDbProvider (metatv/metadata_providers/tmdb.py), OMDbProvider
(metatv/metadata_providers/omdb.py), and the config wiring in
MetadataProviderRegistry (metatv/core/metadata_manager.py):

1. is_enabled() gating (empty key vs a set key), for both providers.
2. search() + get_details() parse a realistic TMDb JSON fixture into the
   correct MetadataResult fields (via the title-search fallback path).
3. A channel WITH ChannelDB.detected_tmdb_id skips search entirely and hits
   the id-based detail endpoint directly (never overwrites the field).
4. test_connection() maps HTTP 401 -> a clear "Invalid API key" failure for
   both providers.
5. OMDb's in-band ``{"Response": "False", "Error": "..."}`` (HTTP 200) is
   treated as failure by both get_details() and test_connection() — never
   only a status-code check.
6. Registry config gates: metadata_enabled=False consults nobody;
   metadata_enabled_providers excludes an unlisted provider;
   metadata_provider_priority reorders ahead of each provider's own
   get_priority().
7. No DB session is held open across a network await in either provider's
   get_details() (structural regression guard, mirrors
   test_metadata_manager_session_hygiene.py's _SessionCounter pattern).

No API key is available in this environment — every aiohttp call is mocked;
an autouse fixture also blocks any real socket connection so a mocking gap
fails loudly instead of silently reaching out to the network.
"""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Network lockdown — belt-and-suspenders on top of per-test aiohttp mocking.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch):
    """Fail loudly if any test in this file would open a real socket.

    Every test below mocks ``aiohttp.ClientSession`` directly, so this should
    never trip — it exists so a mocking gap is a hard failure, not a silent
    real HTTP request to TMDb/OMDb (no API key is available in this
    environment; a real call would also just fail).
    """
    def _blocked(*args, **kwargs):
        raise RuntimeError("Real network access attempted in a metadata-provider test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# ---------------------------------------------------------------------------
# aiohttp mocking helpers (pattern from tests/test_provider_probe.py)
# ---------------------------------------------------------------------------

def _make_resp(status: int, json_data: dict | None = None) -> MagicMock:
    """Build a mock aiohttp response as an async context-manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data if json_data is not None else {})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(*responses: MagicMock, probe_fn=None) -> MagicMock:
    """Build a mock aiohttp.ClientSession whose .get() yields *responses* in
    order, one per call — handles multi-request flows (search -> details).

    Args:
        responses: One mock response (see _make_resp) per expected .get() call.
        probe_fn: When given, a zero-arg callable invoked at each ``.get()``
            call site and its return value recorded onto the returned
            session's ``.probed`` list — used by the session-hygiene tests to
            snapshot "how many DB sessions are open right now" at the exact
            moment the network phase begins.
    """
    resp_iter = iter(responses)
    calls: list[tuple] = []
    probed: list = []

    def _get(*args, **kwargs):
        calls.append(args)
        if probe_fn is not None:
            probed.append(probe_fn())
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=next(resp_iter))
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    session = MagicMock()
    session.get = MagicMock(side_effect=_get)
    session.get_calls = calls
    session.probed = probed
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database (CLAUDE.md testing rule: real DB, not :memory:)."""
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'ext_metadata.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(
    session,
    channel_id: str,
    *,
    name: str = "Some Movie",
    media_type: str = "movie",
    detected_title: str | None = None,
    detected_year: str | None = None,
    detected_tmdb_id: str | None = None,
    metadata_id: str | None = None,
) -> None:
    from metatv.core.database import ChannelDB
    session.add(ChannelDB(
        id=channel_id,
        source_id=f"src-{channel_id}",
        provider_id="p1",
        name=name,
        media_type=media_type,
        detected_title=detected_title,
        detected_year=detected_year,
        detected_tmdb_id=detected_tmdb_id,
        metadata_id=metadata_id,
    ))


# ---------------------------------------------------------------------------
# Realistic fixtures
# ---------------------------------------------------------------------------

_TMDB_SEARCH_RESULT = {
    "results": [
        {
            "id": 603,
            "title": "The Matrix",
            "release_date": "1999-03-30",
            "poster_path": "/search_poster.jpg",
            "overview": "A search-result overview.",
        }
    ]
}

_TMDB_MOVIE_DETAIL = {
    "id": 603,
    "title": "The Matrix",
    "overview": "A computer hacker learns the truth about his reality.",
    "tagline": "Welcome to the Real World.",
    "release_date": "1999-03-30",
    "poster_path": "/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg",
    "backdrop_path": "/fNG7i7RqMErkcqhohV2a6cV1Ehy.jpg",
    "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}],
    "runtime": 136,
    "vote_average": 8.2,
    "vote_count": 24000,
    "imdb_id": "tt0133093",
    "credits": {
        "cast": [
            {"name": "Keanu Reeves", "character": "Neo", "profile_path": "/keanu.jpg"},
            {"name": "Laurence Fishburne", "character": "Morpheus", "profile_path": None},
        ],
        "crew": [
            {"name": "Lana Wachowski", "job": "Director", "department": "Directing"},
            {"name": "Lilly Wachowski", "job": "Director", "department": "Directing"},
        ],
    },
}

_OMDB_MOVIE_DETAIL = {
    "Title": "The Matrix",
    "Year": "1999",
    "Rated": "R",
    "Released": "31 Mar 1999",
    "Runtime": "136 min",
    "Genre": "Action, Sci-Fi",
    "Director": "Lana Wachowski, Lilly Wachowski",
    "Actors": "Keanu Reeves, Laurence Fishburne, Carrie-Anne Moss",
    "Plot": "A computer hacker learns the truth about his reality.",
    "Poster": "https://example.com/matrix.jpg",
    "imdbRating": "8.7",
    "imdbVotes": "1,900,000",
    "imdbID": "tt0133093",
    "Ratings": [
        {"Source": "Internet Movie Database", "Value": "8.7/10"},
        {"Source": "Rotten Tomatoes", "Value": "83%"},
        {"Source": "Metacritic", "Value": "73/100"},
    ],
    "Response": "True",
}

_OMDB_NOT_FOUND = {"Response": "False", "Error": "Movie not found!"}


# ---------------------------------------------------------------------------
# is_enabled() gating
# ---------------------------------------------------------------------------

def test_tmdb_disabled_with_empty_key():
    from metatv.metadata_providers.tmdb import TMDbProvider
    provider = TMDbProvider(SimpleNamespace(metadata_tmdb_api_key=""))
    assert provider.is_enabled() is False
    assert provider.requires_api_key() is True


def test_tmdb_enabled_with_key():
    from metatv.metadata_providers.tmdb import TMDbProvider
    provider = TMDbProvider(SimpleNamespace(metadata_tmdb_api_key="abc123"))
    assert provider.is_enabled() is True


def test_omdb_disabled_with_empty_key():
    from metatv.metadata_providers.omdb import OMDbProvider
    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="   "))
    assert provider.is_enabled() is False
    assert provider.requires_api_key() is True


def test_omdb_enabled_with_key():
    from metatv.metadata_providers.omdb import OMDbProvider
    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="xyz789"))
    assert provider.is_enabled() is True


def test_tmdb_priority_and_rate_limit():
    from metatv.metadata_providers.tmdb import TMDbProvider
    provider = TMDbProvider(SimpleNamespace(metadata_tmdb_api_key="k"))
    assert provider.get_priority() == 20
    assert provider.get_rate_limit() == (40, 1)


def test_omdb_priority():
    from metatv.metadata_providers.omdb import OMDbProvider
    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="k"))
    assert provider.get_priority() == 30


# ---------------------------------------------------------------------------
# TMDb: search() + get_details() fixture mapping (title-search fallback path)
# ---------------------------------------------------------------------------

def test_tmdb_search_parses_results():
    from metatv.metadata_providers.tmdb import TMDbProvider
    provider = TMDbProvider(SimpleNamespace(
        metadata_tmdb_api_key="k", metadata_tmdb_language="en-US",
        metadata_tmdb_include_adult=False,
    ))
    session = _make_session(_make_resp(200, _TMDB_SEARCH_RESULT))
    with patch("aiohttp.ClientSession", return_value=session):
        results = asyncio_run(provider.search("The Matrix", 1999, "movie"))

    assert len(results) == 1
    assert results[0]["id"] == 603
    assert results[0]["title"] == "The Matrix"
    assert results[0]["year"] == 1999
    assert results[0]["poster_url"] == "https://image.tmdb.org/t/p/w500/search_poster.jpg"


def test_tmdb_get_details_via_search_fallback_parses_fixture(db):
    """No detected_tmdb_id -> search() runs, then the top result's id is fetched."""
    from metatv.metadata_providers.tmdb import TMDbProvider

    with db.session_scope() as session:
        _make_channel(session, "c1", detected_title="The Matrix", detected_year="1999")

    provider = TMDbProvider(
        SimpleNamespace(metadata_tmdb_api_key="k", metadata_tmdb_language="en-US",
                         metadata_tmdb_include_adult=False),
        database=db,
    )
    session = _make_session(
        _make_resp(200, _TMDB_SEARCH_RESULT),
        _make_resp(200, _TMDB_MOVIE_DETAIL),
    )
    with patch("aiohttp.ClientSession", return_value=session):
        result = asyncio_run(provider.get_details("c1", media_type="movie"))

    assert session.get.call_count == 2
    assert "/search/movie" in session.get_calls[0][0]
    assert "/movie/603" in session.get_calls[1][0]

    assert result is not None
    assert result.title == "The Matrix"
    assert result.year == 1999
    assert result.plot == "A computer hacker learns the truth about his reality."
    assert result.tagline == "Welcome to the Real World."
    assert result.poster_url == "https://image.tmdb.org/t/p/w500/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg"
    assert result.backdrop_url == "https://image.tmdb.org/t/p/w1280/fNG7i7RqMErkcqhohV2a6cV1Ehy.jpg"
    assert result.genres == ["Action", "Science Fiction"]
    assert result.runtime == 136
    assert result.release_date == "1999-03-30"
    assert result.rating == 8.2
    assert result.rating_count == 24000
    assert result.ratings == {"tmdb": 8.2}
    assert result.imdb_id == "tt0133093"
    assert result.tmdb_id == "603"
    assert result.director == "Lana Wachowski"
    assert {"name": "Keanu Reeves", "character": "Neo",
            "photo_url": "https://image.tmdb.org/t/p/w185/keanu.jpg"} in result.cast
    assert result.provider_name == "tmdb"
    assert 0.0 < result.confidence <= 1.0


def test_tmdb_get_details_with_stored_id_skips_search(db):
    """A channel with detected_tmdb_id set never calls the search endpoint."""
    from metatv.metadata_providers.tmdb import TMDbProvider

    with db.session_scope() as session:
        _make_channel(session, "c2", detected_tmdb_id="603", detected_title="ignored title")

    provider = TMDbProvider(
        SimpleNamespace(metadata_tmdb_api_key="k", metadata_tmdb_language="en-US",
                         metadata_tmdb_include_adult=False),
        database=db,
    )
    session = _make_session(_make_resp(200, _TMDB_MOVIE_DETAIL))
    with patch("aiohttp.ClientSession", return_value=session):
        result = asyncio_run(provider.get_details("c2", media_type="movie"))

    # Exactly one HTTP call — the id-based detail fetch — never /search/.
    assert session.get.call_count == 1
    assert "/movie/603" in session.get_calls[0][0]
    assert "/search/" not in session.get_calls[0][0]
    assert result is not None
    assert result.title == "The Matrix"

    # detected_tmdb_id on the row itself must be untouched — this provider only
    # reads it, the content-identity pipeline owns writing it.
    with db.session_scope(commit=False) as session:
        from metatv.core.database import ChannelDB
        ch = session.query(ChannelDB).filter_by(id="c2").first()
        assert ch.detected_tmdb_id == "603"


# ---------------------------------------------------------------------------
# TMDb: test_connection()
# ---------------------------------------------------------------------------

def test_tmdb_test_connection_success():
    from metatv.metadata_providers.tmdb import TMDbProvider
    provider = TMDbProvider(SimpleNamespace(metadata_tmdb_api_key="k"))
    session = _make_session(_make_resp(200, {"images": {}}))
    with patch("aiohttp.ClientSession", return_value=session):
        ok, message = asyncio_run(provider.test_connection())
    assert ok is True
    assert message is None


def test_tmdb_test_connection_401_is_invalid_key():
    from metatv.metadata_providers.tmdb import TMDbProvider
    provider = TMDbProvider(SimpleNamespace(metadata_tmdb_api_key="bad-key"))
    session = _make_session(_make_resp(401, {"status_message": "Invalid API key"}))
    with patch("aiohttp.ClientSession", return_value=session):
        ok, message = asyncio_run(provider.test_connection())
    assert ok is False
    assert message == "Invalid API key"


def test_tmdb_test_connection_network_failure_distinct_message():
    from metatv.metadata_providers.tmdb import TMDbProvider
    provider = TMDbProvider(SimpleNamespace(metadata_tmdb_api_key="k"))
    import aiohttp as aiohttp_mod
    with patch("aiohttp.ClientSession", side_effect=aiohttp_mod.ClientConnectionError("boom")):
        ok, message = asyncio_run(provider.test_connection())
    assert ok is False
    assert message != "Invalid API key"
    assert "TMDb" in message


def test_tmdb_test_connection_no_key():
    from metatv.metadata_providers.tmdb import TMDbProvider
    provider = TMDbProvider(SimpleNamespace(metadata_tmdb_api_key=""))
    ok, message = asyncio_run(provider.test_connection())
    assert ok is False
    assert message


# ---------------------------------------------------------------------------
# OMDb: get_details() fixture mapping + in-band failure handling
# ---------------------------------------------------------------------------

def test_omdb_get_details_parses_fixture(db):
    from metatv.metadata_providers.omdb import OMDbProvider

    with db.session_scope() as session:
        _make_channel(session, "c3", detected_title="The Matrix", detected_year="1999")

    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="k"), database=db)
    session = _make_session(_make_resp(200, _OMDB_MOVIE_DETAIL))
    with patch("aiohttp.ClientSession", return_value=session):
        result = asyncio_run(provider.get_details("c3", media_type="movie"))

    assert result is not None
    assert result.title == "The Matrix"
    assert result.year == 1999
    assert result.plot == "A computer hacker learns the truth about his reality."
    assert result.content_rating == "R"
    assert result.genres == ["Action", "Sci-Fi"]
    assert result.director == "Lana Wachowski, Lilly Wachowski"
    assert {"name": "Keanu Reeves", "character": None, "photo_url": None} in result.cast
    assert result.runtime == 136
    assert result.release_date == "1999-03-31"
    assert result.rating == 8.7
    assert result.rating_count == 1900000
    assert result.ratings["rt"] == 83.0
    assert result.ratings["metacritic"] == 73.0
    assert result.imdb_id == "tt0133093"
    assert result.provider_name == "omdb"

    # t=/y= (title search) params, since no imdb id was cached on this channel.
    _, kwargs = session.get.call_args
    assert kwargs["params"].get("t") == "The Matrix"
    assert kwargs["params"].get("y") == "1999"
    assert "i" not in kwargs["params"]


def test_omdb_in_band_response_false_treated_as_failure(db):
    """OMDb signals failure at HTTP 200 via Response:'False' — must not be
    mistaken for success just because the status code is 200."""
    from metatv.metadata_providers.omdb import OMDbProvider

    with db.session_scope() as session:
        _make_channel(session, "c4", detected_title="Nonexistent Movie 12345")

    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="k"), database=db)
    session = _make_session(_make_resp(200, _OMDB_NOT_FOUND))
    with patch("aiohttp.ClientSession", return_value=session):
        result = asyncio_run(provider.get_details("c4", media_type="movie"))

    assert result is None


def test_omdb_test_connection_in_band_false_treated_as_failure():
    from metatv.metadata_providers.omdb import OMDbProvider
    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="k"))
    session = _make_session(_make_resp(200, _OMDB_NOT_FOUND))
    with patch("aiohttp.ClientSession", return_value=session):
        ok, message = asyncio_run(provider.test_connection())
    assert ok is False
    assert message == "Movie not found!"


def test_omdb_test_connection_401_is_invalid_key():
    from metatv.metadata_providers.omdb import OMDbProvider
    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="bad-key"))
    session = _make_session(_make_resp(401, {}))
    with patch("aiohttp.ClientSession", return_value=session):
        ok, message = asyncio_run(provider.test_connection())
    assert ok is False
    assert message == "Invalid API key"


def test_omdb_test_connection_success():
    from metatv.metadata_providers.omdb import OMDbProvider
    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="k"))
    session = _make_session(_make_resp(200, _OMDB_MOVIE_DETAIL))
    with patch("aiohttp.ClientSession", return_value=session):
        ok, message = asyncio_run(provider.test_connection())
    assert ok is True
    assert message is None


def test_omdb_reuses_cached_imdb_id_instead_of_title_search(db):
    """A channel whose linked MetadataDB row already carries an imdb_id (from a
    prior fetch cycle, e.g. TMDb) is looked up by &i= instead of &t=/&y=."""
    from metatv.core.database import MetadataDB
    from metatv.metadata_providers.omdb import OMDbProvider

    with db.session_scope() as session:
        session.add(MetadataDB(id="meta1", title="The Matrix", imdb_id="tt0133093"))
        _make_channel(session, "c5", detected_title="The Matrix", metadata_id="meta1")

    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="k"), database=db)
    session = _make_session(_make_resp(200, _OMDB_MOVIE_DETAIL))
    with patch("aiohttp.ClientSession", return_value=session):
        result = asyncio_run(provider.get_details("c5", media_type="movie"))

    assert result is not None
    _, kwargs = session.get.call_args
    assert kwargs["params"].get("i") == "tt0133093"
    assert "t" not in kwargs["params"]


# ---------------------------------------------------------------------------
# Registry config gates (metadata_enabled / metadata_enabled_providers /
# metadata_provider_priority) — metatv/core/metadata_manager.py
# ---------------------------------------------------------------------------

def _dummy_provider(name: str, *, priority: int = 50, enabled: bool = True):
    from metatv.metadata_providers.base import MetadataProviderPlugin

    class _P(MetadataProviderPlugin):
        @property
        def name(self) -> str:
            return name

        @property
        def display_name(self) -> str:
            return name

        @property
        def supported_media_types(self):
            return ["movie", "series"]

        @property
        def supported_fields(self):
            return []

        async def search(self, title, year=None, media_type="movie"):
            return []

        async def get_details(self, external_id, media_type="movie"):
            return None

        async def test_connection(self):
            return (True, None)

        def get_priority(self) -> int:
            return priority

        def is_enabled(self) -> bool:
            return enabled

    return _P()


def test_registry_config_none_preserves_original_behavior():
    """Backward compatibility: MetadataProviderRegistry() with no config still
    orders purely by get_priority() and gates only on is_enabled()."""
    from metatv.core.metadata_manager import MetadataProviderRegistry

    registry = MetadataProviderRegistry()
    registry.register(_dummy_provider("b", priority=2))
    registry.register(_dummy_provider("a", priority=1))
    assert [p.name for p in registry.get_all()] == ["a", "b"]
    assert [p.name for p in registry.get_enabled()] == ["a", "b"]


def test_registry_metadata_enabled_false_consults_nobody():
    from metatv.core.metadata_manager import MetadataProviderRegistry

    cfg = SimpleNamespace(metadata_enabled=False, metadata_enabled_providers=[],
                           metadata_provider_priority=[])
    registry = MetadataProviderRegistry(cfg)
    registry.register(_dummy_provider("provider"))
    registry.register(_dummy_provider("tmdb"))
    assert registry.get_enabled() == []


def test_registry_enabled_providers_excludes_unlisted():
    from metatv.core.metadata_manager import MetadataProviderRegistry

    cfg = SimpleNamespace(metadata_enabled=True, metadata_enabled_providers=["tmdb"],
                           metadata_provider_priority=[])
    registry = MetadataProviderRegistry(cfg)
    registry.register(_dummy_provider("provider"))  # is_enabled()=True but NOT allow-listed
    registry.register(_dummy_provider("tmdb"))
    names = [p.name for p in registry.get_enabled()]
    assert names == ["tmdb"]


def test_registry_enabled_providers_still_checks_own_is_enabled():
    """The allow-list is necessary but not sufficient — a listed provider that
    reports its own is_enabled()=False (e.g. empty API key) still doesn't run."""
    from metatv.core.metadata_manager import MetadataProviderRegistry

    cfg = SimpleNamespace(metadata_enabled=True, metadata_enabled_providers=["tmdb"],
                           metadata_provider_priority=[])
    registry = MetadataProviderRegistry(cfg)
    registry.register(_dummy_provider("tmdb", enabled=False))
    assert registry.get_enabled() == []


def test_registry_priority_override_reorders():
    from metatv.core.metadata_manager import MetadataProviderRegistry

    cfg = SimpleNamespace(metadata_enabled=True, metadata_enabled_providers=[],
                           metadata_provider_priority=["omdb", "provider", "tmdb"])
    registry = MetadataProviderRegistry(cfg)
    # Registered in an order that would sort differently by get_priority() alone.
    registry.register(_dummy_provider("provider", priority=1))
    registry.register(_dummy_provider("tmdb", priority=20))
    registry.register(_dummy_provider("omdb", priority=30))
    assert [p.name for p in registry.get_all()] == ["omdb", "provider", "tmdb"]


def test_registry_priority_override_unlisted_provider_sorts_after_listed():
    from metatv.core.metadata_manager import MetadataProviderRegistry

    cfg = SimpleNamespace(metadata_enabled=True, metadata_enabled_providers=[],
                           metadata_provider_priority=["tmdb"])
    registry = MetadataProviderRegistry(cfg)
    registry.register(_dummy_provider("provider", priority=1))  # unlisted — own priority=1
    registry.register(_dummy_provider("tmdb", priority=20))     # listed — wins regardless
    assert [p.name for p in registry.get_all()] == ["tmdb", "provider"]


# ---------------------------------------------------------------------------
# Config migration: metadata_enabled_providers allow-list merge
# (coordinator follow-up — an owner-reported real config.yaml persisted from
# before TMDb/OMDb existed had metadata_enabled_providers: [provider], so
# widening the Field default_factory alone did nothing: pydantic loads the
# persisted value verbatim, silently excluding tmdb/omdb from
# MetadataProviderRegistry.get_enabled() forever — pasting a TMDb API key
# into Settings was a silent no-op. metatv/core/config.py's
# _migrate_metadata_enabled_providers() (model_post_init, version-gated by
# metadata_enabled_providers_version) closes that gap for existing installs.
# ---------------------------------------------------------------------------

def test_migration_merges_missing_providers_and_new_provider_is_consulted(tmp_path):
    """The exact owner-reported scenario: a persisted config whose
    metadata_enabled_providers is exactly ["provider"] (predates TMDb/OMDb) must,
    once loaded, actually consult TMDb given a key — not merely end up with an
    updated list that nothing reads."""
    from metatv.core.config import Config
    from metatv.core.metadata_manager import MetadataProviderRegistry
    from metatv.metadata_providers.tmdb import TMDbProvider

    cfg = Config(
        config_dir=tmp_path,
        metadata_enabled_providers=["provider"],
        metadata_enabled_providers_version=0,
        metadata_tmdb_api_key="a-real-key",
    )
    assert "tmdb" in cfg.metadata_enabled_providers
    assert cfg.metadata_enabled_providers_version == 1

    registry = MetadataProviderRegistry(cfg)
    registry.register(_dummy_provider("provider"))
    registry.register(TMDbProvider(cfg))
    consulted = [p.name for p in registry.get_enabled()]
    assert "tmdb" in consulted, f"TMDb must actually be consulted once merged+keyed, got {consulted}"


def test_migration_idempotent_across_two_runs(tmp_path):
    """A second invocation (simulating a second app launch re-reading the
    already-migrated state) must not duplicate entries or change anything."""
    from metatv.core.config import Config

    cfg = Config(config_dir=tmp_path, metadata_enabled_providers=["provider"],
                 metadata_enabled_providers_version=0)
    first_run_list = list(cfg.metadata_enabled_providers)
    assert cfg.metadata_enabled_providers_version == 1

    cfg._migrate_metadata_enabled_providers()  # second run
    assert cfg.metadata_enabled_providers == first_run_list
    assert cfg.metadata_enabled_providers_version == 1


def test_migration_leaves_fully_populated_list_untouched(tmp_path):
    """A list that already contains every shipped name is left byte-for-byte as
    is (no duplicate append, no reordering) — the version still advances."""
    from metatv.core.config import Config

    cfg = Config(config_dir=tmp_path, metadata_enabled_providers=["provider", "tmdb", "omdb"],
                 metadata_enabled_providers_version=0)
    assert cfg.metadata_enabled_providers == ["provider", "tmdb", "omdb"]
    assert cfg.metadata_enabled_providers_version == 1


def test_migration_never_reapplies_once_versioned_even_if_list_shrinks(tmp_path):
    """Once metadata_enabled_providers_version is already 1 (migration already ran),
    a list missing tmdb/omdb is NOT re-merged — proves the version-gate (not a plain
    membership check) protects a future deliberate removal, if this list ever grows
    an editing UI, from being silently undone on a later launch."""
    from metatv.core.config import Config

    cfg = Config(config_dir=tmp_path, metadata_enabled_providers=["tmdb"],
                 metadata_enabled_providers_version=1)
    assert cfg.metadata_enabled_providers == ["tmdb"], "already-migrated config must not be touched again"


def test_migration_does_not_touch_unrelated_config_keys(tmp_path):
    """The migration only ever touches metadata_enabled_providers/_version — every
    other field passed through construction is unaffected."""
    from metatv.core.config import Config

    cfg = Config(
        config_dir=tmp_path,
        metadata_enabled_providers=["provider"],
        metadata_enabled_providers_version=0,
        metadata_cache_ttl_days=45,
        metadata_tmdb_language="fr-FR",
    )
    assert cfg.metadata_cache_ttl_days == 45
    assert cfg.metadata_tmdb_language == "fr-FR"


# ---------------------------------------------------------------------------
# Session hygiene — no DB session open across a network await
# (mirrors tests/test_metadata_manager_session_hygiene.py's _SessionCounter)
# ---------------------------------------------------------------------------

class _SessionCounter:
    """Wraps Database.SessionLocal to count currently-open sessions."""

    def __init__(self, db):
        self._real_factory = db.SessionLocal
        self.open_count = 0

    def __call__(self, *args, **kwargs):
        session = self._real_factory(*args, **kwargs)
        self.open_count += 1
        real_close = session.close

        def _tracked_close():
            self.open_count -= 1
            real_close()

        session.close = _tracked_close
        return session


def test_tmdb_get_details_holds_no_session_during_network_call(db):
    """Guards TMDbProvider._load_channel_lookup()'s short-session contract:
    both the search() call and the id-based details call must see 0 open
    sessions — the DB read closes before either network await runs."""
    from metatv.metadata_providers.tmdb import TMDbProvider

    with db.session_scope() as session:
        _make_channel(session, "c6", detected_title="The Matrix", detected_year="1999")

    counter = _SessionCounter(db)
    db.SessionLocal = counter

    mock_session = _make_session(
        _make_resp(200, _TMDB_SEARCH_RESULT),
        _make_resp(200, _TMDB_MOVIE_DETAIL),
        probe_fn=lambda: counter.open_count,
    )

    provider = TMDbProvider(
        SimpleNamespace(metadata_tmdb_api_key="k", metadata_tmdb_language="en-US",
                         metadata_tmdb_include_adult=False),
        database=db,
    )
    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = asyncio_run(provider.get_details("c6", media_type="movie"))

    assert mock_session.probed == [0, 0], (
        f"expected 0 open sessions during both network calls, saw {mock_session.probed}"
    )
    assert result is not None
    assert result.title == "The Matrix"


def test_omdb_get_details_holds_no_session_during_network_call(db):
    """Guards OMDbProvider._load_channel_lookup()'s short-session contract —
    the DB read (title/year/cached-imdb_id) closes before the network await."""
    from metatv.metadata_providers.omdb import OMDbProvider

    with db.session_scope() as session:
        _make_channel(session, "c7", detected_title="The Matrix", detected_year="1999")

    counter = _SessionCounter(db)
    db.SessionLocal = counter

    mock_session = _make_session(
        _make_resp(200, _OMDB_MOVIE_DETAIL),
        probe_fn=lambda: counter.open_count,
    )

    provider = OMDbProvider(SimpleNamespace(metadata_omdb_api_key="k"), database=db)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = asyncio_run(provider.get_details("c7", media_type="movie"))

    assert mock_session.probed == [0], (
        f"expected 0 open sessions during the network call, saw {mock_session.probed}"
    )
    assert result is not None
    assert result.title == "The Matrix"


# ---------------------------------------------------------------------------
# asyncio.run shim (kept local/obvious — no new dependency, matches every
# other async test in this codebase, e.g. test_metadata_manager_session_hygiene.py)
# ---------------------------------------------------------------------------

def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
