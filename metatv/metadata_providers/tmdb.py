"""TMDb metadata provider — themoviedb.org.

Fetches poster/plot/cast/genre/rating data from The Movie Database's public
REST API via aiohttp.  Standard-priority external source (behind the free,
already-cached ``ProviderMetadataProvider``): see :meth:`TMDbProvider.get_priority`.

Session hygiene: :meth:`TMDbProvider.get_details` reads the channel's
``detected_tmdb_id`` / ``detected_title`` / ``detected_year`` in ONE short,
synchronous ``session_scope(commit=False)`` block that returns BEFORE any
``await`` runs — the network calls below it (``search()`` / the id-based
detail fetch) never see an open DB session. See
docs/CRITICAL_RULES.md#database-sessions and the split documented at
``metatv/core/metadata_manager.py:139-151``.
"""
from __future__ import annotations

from typing import Any, Optional

import aiohttp
from loguru import logger

from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult

_BASE_URL = "https://api.themoviedb.org/3"
_IMAGE_BASE = "https://image.tmdb.org/t/p"
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# TMDb path segment for each of our media_type strings ("series" -> TMDb "tv").
_TMDB_MEDIA_TYPE: dict[str, str] = {"movie": "movie", "series": "tv"}

# Errors that mean "the network/response was unusable" — collapsed to a clean
# None/[] result rather than propagating (MetadataManager already wraps each
# provider call in its own try/except, but every method here is defensive on
# its own so a bad response never surfaces a raw stack trace).
_NETWORK_ERRORS = (aiohttp.ClientError, TimeoutError, ValueError)


class TMDbProvider(MetadataProviderPlugin):
    """The Movie Database (themoviedb.org) metadata plugin.

    Args:
        config: App ``Config`` (or any object exposing ``metadata_tmdb_api_key``,
            ``metadata_tmdb_language``, ``metadata_tmdb_include_adult`` — a bare
            ``SimpleNamespace`` works too, e.g. for a throwaway "test this key"
            instance built from an unsaved Settings-dialog field).
        database: ``Database`` instance used only for the short
            ``detected_tmdb_id`` lookup in :meth:`get_details`. May be ``None``
            for an instance that only ever calls :meth:`test_connection`.
    """

    def __init__(self, config: Any, database: Any = None) -> None:
        self.config = config
        self.db = database

    @property
    def name(self) -> str:
        return "tmdb"

    @property
    def display_name(self) -> str:
        return "TMDb"

    @property
    def supported_media_types(self) -> list[str]:
        return ["movie", "series"]

    @property
    def supported_fields(self) -> list[str]:
        return [
            "title", "year", "plot", "tagline", "poster", "backdrop",
            "cast", "crew", "director", "genres", "rating", "rating_count",
            "runtime", "release_date", "imdb_id", "tmdb_id",
        ]

    def get_priority(self) -> int:
        return 20

    def requires_api_key(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return bool(self._api_key())

    def get_rate_limit(self) -> tuple[int, int]:
        # TMDb documents ~50 req/s; stay comfortably under it.
        return (40, 1)

    def _api_key(self) -> str:
        return (getattr(self.config, "metadata_tmdb_api_key", "") or "").strip()

    def _language(self) -> str:
        return getattr(self.config, "metadata_tmdb_language", "en-US") or "en-US"

    def _include_adult(self) -> bool:
        return bool(getattr(self.config, "metadata_tmdb_include_adult", False))

    async def search(self, title: str, year: Optional[int] = None,
                      media_type: str = "movie") -> list[dict[str, Any]]:
        """Search TMDb by title (+ optional year). Pure network call — no DB access.

        Args:
            title: Content title to search for.
            year: Optional year to narrow results.
            media_type: ``"movie"`` or ``"series"`` (mapped to TMDb's ``movie``/``tv``).

        Returns:
            List of ``{"id", "title", "year", "poster_url", "overview"}`` dicts,
            best match first (TMDb's own relevance ordering). Empty on any
            failure — never raises.
        """
        tmdb_type = _TMDB_MEDIA_TYPE.get(media_type, "movie")
        params: dict[str, str] = {
            "api_key": self._api_key(),
            "query": title,
            "language": self._language(),
            "include_adult": str(self._include_adult()).lower(),
        }
        if year:
            year_param = "year" if tmdb_type == "movie" else "first_air_date_year"
            params[year_param] = str(year)

        data = await self._get_json(f"{_BASE_URL}/search/{tmdb_type}", params)
        if data is None:
            return []

        results: list[dict[str, Any]] = []
        for r in data.get("results", []) or []:
            results.append({
                "id": r.get("id"),
                "title": r.get("title") or r.get("name"),
                "year": _year_from_date(r.get("release_date") or r.get("first_air_date")),
                "poster_url": _image_url(r.get("poster_path"), "w500"),
                "overview": r.get("overview"),
            })
        return results

    async def get_details(self, external_id: str,
                           media_type: str = "movie") -> Optional[MetadataResult]:
        """Fetch full metadata for a channel.

        ``external_id`` here is the local channel id — ``MetadataManager`` calls
        every registered provider uniformly with the channel id (see
        ``ProviderMetadataProvider.get_details`` for the same convention), so
        this provider does its own short DB read to resolve the channel's
        already-known ``detected_tmdb_id`` (preferred, skips search entirely)
        or its ``detected_title``/``detected_year`` (search fallback).

        Args:
            external_id: Local channel id.
            media_type: ``"movie"`` or ``"series"``.

        Returns:
            A populated ``MetadataResult``, or ``None`` when the channel is
            unknown, has nothing to look up, or TMDb has no match.
        """
        lookup = self._load_channel_lookup(external_id)
        if lookup is None:
            return None
        tmdb_id, title, year, resolved_media_type = lookup

        # ── Network phase below: the DB session opened in _load_channel_lookup
        # is already closed — nothing here holds one open across an await. ──
        if tmdb_id:
            return await self._get_details_by_id(tmdb_id, resolved_media_type)

        if not title:
            return None

        results = await self.search(title, year, resolved_media_type)
        if not results or not results[0].get("id"):
            return None
        return await self._get_details_by_id(str(results[0]["id"]), resolved_media_type)

    def _load_channel_lookup(
        self, channel_id: str
    ) -> Optional[tuple[Optional[str], Optional[str], Optional[int], str]]:
        """Short, synchronous DB read — closes before any network call.

        Args:
            channel_id: Local channel id.

        Returns:
            ``(detected_tmdb_id, title, year, media_type)``, or ``None`` if the
            channel doesn't exist. Only ever READS ``detected_tmdb_id`` — never
            writes/corrects it, that field belongs to the content-identity
            pipeline (CLAUDE.md).
        """
        if self.db is None:
            logger.debug("TMDbProvider.get_details called with no database configured")
            return None
        from metatv.core.database import ChannelDB
        with self.db.session_scope(commit=False) as session:
            channel = session.query(ChannelDB).filter_by(id=channel_id).first()
            if not channel:
                return None
            title = channel.detected_title or channel.name
            year = _parse_stored_year(channel.detected_year)
            return (channel.detected_tmdb_id, title, year, channel.media_type or "movie")

    async def _get_details_by_id(self, tmdb_id: str,
                                  media_type: str = "movie") -> Optional[MetadataResult]:
        """Fetch ``/movie|tv/{id}?append_to_response=credits`` and map it.

        Args:
            tmdb_id: TMDb numeric id (as a string).
            media_type: ``"movie"`` or ``"series"``.

        Returns:
            A populated ``MetadataResult``, or ``None`` on any failure.
        """
        tmdb_type = _TMDB_MEDIA_TYPE.get(media_type, "movie")
        params = {
            "api_key": self._api_key(),
            "language": self._language(),
            "append_to_response": "credits",
        }
        data = await self._get_json(f"{_BASE_URL}/{tmdb_type}/{tmdb_id}", params)
        if data is None:
            return None
        return self._map_details(data)

    def _map_details(self, data: dict[str, Any]) -> MetadataResult:
        """Map a TMDb ``/movie|tv/{id}`` detail response to ``MetadataResult``.

        Exhaustive over every ``MetadataResult`` field this endpoint (with
        ``append_to_response=credits``) can supply. Deliberately left unset
        (not requested by this ``append_to_response``, so never guessed):
        ``content_rating`` (needs ``release_dates``/``content_ratings``),
        ``trailer_url`` (needs ``videos``), ``imdb_id`` for series (TMDb only
        returns it natively for movies — series needs ``external_ids``).

        Args:
            data: Parsed JSON body of the detail response.

        Returns:
            A populated ``MetadataResult``.
        """
        credits_ = data.get("credits") or {}
        cast_list = [
            {
                "name": c.get("name"),
                "character": c.get("character"),
                "photo_url": _image_url(c.get("profile_path"), "w185"),
            }
            for c in (credits_.get("cast") or [])[:20]
        ]
        crew_list = [
            {"name": c.get("name"), "job": c.get("job"), "department": c.get("department")}
            for c in (credits_.get("crew") or [])[:20]
        ]
        director = next(
            (c.get("name") for c in (credits_.get("crew") or []) if c.get("job") == "Director"),
            None,
        )

        runtime = data.get("runtime")
        if runtime is None:
            episode_runtimes = data.get("episode_run_time") or []
            runtime = episode_runtimes[0] if episode_runtimes else None

        release_date = data.get("release_date") or data.get("first_air_date") or None
        vote_average = data.get("vote_average")
        rating = float(vote_average) if vote_average is not None else None

        return MetadataResult(
            title=data.get("title") or data.get("name"),
            year=_year_from_date(release_date),
            plot=data.get("overview") or None,
            tagline=data.get("tagline") or None,

            poster_url=_image_url(data.get("poster_path"), "w500"),
            backdrop_url=_image_url(data.get("backdrop_path"), "w1280"),

            cast=cast_list,
            crew=crew_list,
            director=director,

            genres=[g.get("name") for g in (data.get("genres") or []) if g.get("name")],

            rating=rating,
            rating_count=data.get("vote_count"),
            ratings={"tmdb": rating} if rating is not None else {},

            runtime=runtime,
            release_date=release_date,

            imdb_id=data.get("imdb_id") or None,
            tmdb_id=str(data.get("id")) if data.get("id") is not None else None,

            provider_name="tmdb",
            confidence=0.75,
        )

    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Probe ``/3/configuration`` — cheapest authenticated TMDb endpoint.

        Returns:
            ``(True, None)`` on success; ``(False, "Invalid API key")`` on a 401;
            ``(False, <message>)`` for any other HTTP or network failure.
        """
        if not self._api_key():
            return (False, "No API key configured")
        try:
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.get(
                    f"{_BASE_URL}/configuration", params={"api_key": self._api_key()}
                ) as resp:
                    if resp.status == 401:
                        return (False, "Invalid API key")
                    if resp.status != 200:
                        return (False, f"TMDb returned HTTP {resp.status}")
                    return (True, None)
        except _NETWORK_ERRORS as e:
            return (False, f"Could not reach TMDb: {e}")

    async def _get_json(self, url: str, params: dict[str, str]) -> Optional[dict[str, Any]]:
        """Shared GET + JSON decode. Network/decode errors collapse to ``None``.

        Args:
            url: Full request URL.
            params: Query parameters.

        Returns:
            Parsed JSON body, or ``None`` on any HTTP-status or network failure.
        """
        try:
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.debug(f"TMDb request to {url} returned HTTP {resp.status}")
                        return None
                    return await resp.json()
        except _NETWORK_ERRORS as e:
            logger.warning(f"TMDb request to {url} failed: {e}")
            return None


def _image_url(path: Optional[str], size: str) -> Optional[str]:
    """Build a full TMDb image URL from a ``poster_path``/``backdrop_path`` fragment."""
    if not path:
        return None
    return f"{_IMAGE_BASE}/{size}{path}"


def _year_from_date(date_str: Optional[str]) -> Optional[int]:
    """Extract the year from a TMDb ISO date string (``'2025-08-01'`` -> ``2025``)."""
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None


def _parse_stored_year(detected_year: Optional[str]) -> Optional[int]:
    """Parse the first year out of ``ChannelDB.detected_year`` (e.g. ``'1993-2002'``)."""
    if not detected_year:
        return None
    try:
        return int(str(detected_year)[:4])
    except (ValueError, TypeError):
        return None
