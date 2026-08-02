"""OMDb metadata provider — omdbapi.com.

Session hygiene: mirrors ``TMDbProvider`` — :meth:`OMDbProvider.get_details`
reads the channel's title/year (and any already-cached ``MetadataDB.imdb_id``
left over from a prior fetch cycle) in ONE short, synchronous
``session_scope(commit=False)`` block that returns BEFORE any network
``await`` runs. See docs/CRITICAL_RULES.md#database-sessions and the split
documented at ``metatv/core/metadata_manager.py:139-151``.

OMDb signals failure IN-BAND at HTTP 200 (``{"Response": "False", "Error": "..."}``),
never only via status codes — every call here checks ``Response`` before trusting
the payload.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import aiohttp
from loguru import logger

from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult
from metatv.metadata_providers.raw_parse import parse_cast_string, parse_genres

_BASE_URL = "http://www.omdbapi.com/"
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Well-known IMDb id (The Shawshank Redemption) used only to probe key
# validity in test_connection() — never surfaced to the user, just cheap and
# guaranteed to exist.
_PROBE_IMDB_ID = "tt0111161"

_MEDIA_TYPE_PARAM: dict[str, str] = {"movie": "movie", "series": "series"}

_NETWORK_ERRORS = (aiohttp.ClientError, TimeoutError, ValueError)


class OMDbProvider(MetadataProviderPlugin):
    """OMDb (omdbapi.com) metadata plugin — IMDb-sourced ratings/plot/cast.

    Args:
        config: App ``Config`` (or any object exposing ``metadata_omdb_api_key``
            — a bare ``SimpleNamespace`` works too, e.g. for a throwaway "test
            this key" instance built from an unsaved Settings-dialog field).
        database: ``Database`` instance used only for the short title/year/
            cached-imdb_id lookup in :meth:`get_details`. May be ``None`` for
            an instance that only ever calls :meth:`test_connection`.
    """

    def __init__(self, config: Any, database: Any = None) -> None:
        self.config = config
        self.db = database

    @property
    def name(self) -> str:
        return "omdb"

    @property
    def display_name(self) -> str:
        return "OMDb"

    @property
    def supported_media_types(self) -> list[str]:
        return ["movie", "series"]

    @property
    def supported_fields(self) -> list[str]:
        return [
            "title", "year", "plot", "poster", "cast", "director", "genres",
            "content_rating", "rating", "rating_count", "runtime",
            "release_date", "imdb_id",
        ]

    def get_priority(self) -> int:
        return 30

    def requires_api_key(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return bool(self._api_key())

    def _api_key(self) -> str:
        return (getattr(self.config, "metadata_omdb_api_key", "") or "").strip()

    async def search(self, title: str, year: Optional[int] = None,
                      media_type: str = "movie") -> list[dict[str, Any]]:
        """OMDb's ``s=`` (fuzzy multi-result) search. Pure network call — no DB access.

        Args:
            title: Content title to search for.
            year: Optional year to narrow results.
            media_type: ``"movie"`` or ``"series"``.

        Returns:
            List of ``{"id", "title", "year", "poster_url"}`` dicts. Empty on
            any failure or in-band ``Response:"False"`` — never raises.
        """
        params: dict[str, str] = {
            "apikey": self._api_key(),
            "s": title,
            "type": _MEDIA_TYPE_PARAM.get(media_type, "movie"),
        }
        if year:
            params["y"] = str(year)

        data = await self._get(params)
        if data is None or data.get("Response") != "True":
            return []

        results: list[dict[str, Any]] = []
        for r in data.get("Search", []) or []:
            results.append({
                "id": r.get("imdbID"),
                "title": r.get("Title"),
                "year": _parse_omdb_year(r.get("Year")),
                "poster_url": _clean(r.get("Poster")),
            })
        return results

    async def get_details(self, external_id: str,
                           media_type: str = "movie") -> Optional[MetadataResult]:
        """Fetch metadata for a channel.

        ``external_id`` is the local channel id — ``MetadataManager`` calls
        every registered provider uniformly with the channel id (same
        convention as ``ProviderMetadataProvider.get_details``), so this
        provider does its own short DB read to resolve title/year and any
        already-known imdb id.

        Args:
            external_id: Local channel id.
            media_type: ``"movie"`` or ``"series"``.

        Returns:
            A populated ``MetadataResult``, or ``None`` when the channel is
            unknown, has nothing to look up, or OMDb reports no match.
        """
        lookup = self._load_channel_lookup(external_id)
        if lookup is None:
            return None
        title, year, imdb_id = lookup
        if not title and not imdb_id:
            return None

        # ── Network phase below: the DB session opened in _load_channel_lookup
        # is already closed — nothing here holds one open across an await. ──
        params: dict[str, str] = {
            "apikey": self._api_key(),
            "type": _MEDIA_TYPE_PARAM.get(media_type, "movie"),
        }
        if imdb_id:
            params["i"] = imdb_id
        else:
            params["t"] = title
            if year:
                params["y"] = str(year)

        data = await self._get(params)
        if data is None:
            return None
        if data.get("Response") != "True":
            logger.debug(f"OMDb lookup failed for '{title}': {data.get('Error')}")
            return None
        return self._map_details(data)

    def _load_channel_lookup(
        self, channel_id: str
    ) -> Optional[tuple[Optional[str], Optional[int], Optional[str]]]:
        """Short, synchronous DB read — closes before any network call.

        Args:
            channel_id: Local channel id.

        Returns:
            ``(title, year, cached_imdb_id)``, or ``None`` if the channel
            doesn't exist. ``cached_imdb_id`` comes from a PRIOR fetch cycle's
            cached ``MetadataDB.imdb_id`` (e.g. left by TMDb on an earlier
            pass) — reused so OMDb can look up by id (``&i=``) instead of a
            fuzzy title search when already known. Never written back.
        """
        if self.db is None:
            logger.debug("OMDbProvider.get_details called with no database configured")
            return None
        from metatv.core.database import ChannelDB, MetadataDB
        with self.db.session_scope(commit=False) as session:
            channel = session.query(ChannelDB).filter_by(id=channel_id).first()
            if not channel:
                return None
            title = channel.detected_title or channel.name
            year = _parse_stored_year(channel.detected_year)
            imdb_id = None
            if channel.metadata_id:
                meta = session.query(MetadataDB).filter_by(id=channel.metadata_id).first()
                if meta and meta.imdb_id:
                    imdb_id = meta.imdb_id
            return (title, year, imdb_id)

    async def _get(self, params: dict[str, str]) -> Optional[dict[str, Any]]:
        """Shared GET + JSON decode. Network/decode/401 errors collapse to ``None``.

        Args:
            params: Query parameters (``apikey`` already included by the caller).

        Returns:
            Parsed JSON body, or ``None`` on any HTTP-status or network failure.
        """
        try:
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.get(_BASE_URL, params=params) as resp:
                    if resp.status == 401:
                        logger.debug("OMDb returned HTTP 401 (invalid API key)")
                        return None
                    if resp.status != 200:
                        logger.debug(f"OMDb returned HTTP {resp.status}")
                        return None
                    return await resp.json()
        except _NETWORK_ERRORS as e:
            logger.warning(f"OMDb request failed: {e}")
            return None

    def _map_details(self, data: dict[str, Any]) -> MetadataResult:
        """Map an OMDb ``Response:"True"`` payload to ``MetadataResult``.

        Exhaustive over every ``MetadataResult`` field OMDb can supply. OMDb has
        no backdrop/tagline/trailer/structured-crew concept, so those stay unset
        rather than guessed.

        Args:
            data: Parsed JSON body (already confirmed ``Response == "True"``).

        Returns:
            A populated ``MetadataResult``.
        """
        ratings: dict[str, float] = {}
        imdb_rating = _clean(data.get("imdbRating"))
        if imdb_rating:
            try:
                ratings["imdb"] = float(imdb_rating)
            except ValueError:
                pass
        for entry in data.get("Ratings", []) or []:
            source = entry.get("Source")
            value = entry.get("Value") or ""
            if source == "Rotten Tomatoes" and value.endswith("%"):
                try:
                    ratings["rt"] = float(value.rstrip("%"))
                except ValueError:
                    pass
            elif source == "Metacritic" and "/" in value:
                try:
                    ratings["metacritic"] = float(value.split("/")[0])
                except ValueError:
                    pass

        rating_count = None
        votes = _clean(data.get("imdbVotes"))
        if votes:
            try:
                rating_count = int(votes.replace(",", ""))
            except ValueError:
                pass

        runtime = None
        runtime_str = _clean(data.get("Runtime"))
        if runtime_str:
            digits = "".join(ch for ch in runtime_str if ch.isdigit())
            if digits:
                runtime = int(digits)

        return MetadataResult(
            title=_clean(data.get("Title")),
            year=_parse_omdb_year(data.get("Year")),
            plot=_clean(data.get("Plot")),

            poster_url=_clean(data.get("Poster")),

            cast=parse_cast_string(_clean(data.get("Actors")) or ""),
            director=_clean(data.get("Director")),

            genres=parse_genres(_clean(data.get("Genre")) or ""),
            content_rating=_clean(data.get("Rated")),

            rating=ratings.get("imdb"),
            rating_count=rating_count,
            ratings=ratings,

            runtime=runtime,
            release_date=_parse_omdb_release_date(data.get("Released")),

            imdb_id=_clean(data.get("imdbID")),

            provider_name="omdb",
            confidence=0.65,
        )

    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Probe a well-known IMDb id — cheapest deterministic OMDb call.

        Returns:
            ``(True, None)`` on success; ``(False, "Invalid API key")`` on a 401
            OR an in-band ``Response:"False"`` error; ``(False, <message>)`` for
            any other HTTP or network failure.
        """
        if not self._api_key():
            return (False, "No API key configured")
        try:
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.get(
                    _BASE_URL, params={"apikey": self._api_key(), "i": _PROBE_IMDB_ID}
                ) as resp:
                    if resp.status == 401:
                        return (False, "Invalid API key")
                    if resp.status != 200:
                        return (False, f"OMDb returned HTTP {resp.status}")
                    data = await resp.json()
        except _NETWORK_ERRORS as e:
            return (False, f"Could not reach OMDb: {e}")

        if data.get("Response") != "True":
            error = data.get("Error") or "OMDb request failed"
            # OMDb's in-band error for a bad key is textual, not a 401 — normalize
            # it to the same clear message test_connection()'s HTTP-401 branch uses.
            if "api key" in error.lower():
                return (False, "Invalid API key")
            return (False, error)
        return (True, None)


def _clean(value: Optional[str]) -> Optional[str]:
    """OMDb uses the literal string ``"N/A"`` for every absent field — normalize to None."""
    if value is None:
        return None
    value = str(value).strip()
    if not value or value == "N/A":
        return None
    return value


def _parse_omdb_year(year_str: Optional[str]) -> Optional[int]:
    """Extract the first 4-digit year from OMDb's ``Year`` (``'1994'`` or ``'1994–1999'``)."""
    cleaned = _clean(year_str)
    if not cleaned:
        return None
    try:
        return int(cleaned[:4])
    except ValueError:
        return None


def _parse_omdb_release_date(released_str: Optional[str]) -> Optional[str]:
    """Convert OMDb's ``'14 Oct 1994'`` to ISO ``'1994-10-14'`` (None if unparseable/N/A)."""
    cleaned = _clean(released_str)
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def _parse_stored_year(detected_year: Optional[str]) -> Optional[int]:
    """Parse the first year out of ``ChannelDB.detected_year`` (e.g. ``'1993-2002'``)."""
    if not detected_year:
        return None
    try:
        return int(str(detected_year)[:4])
    except (ValueError, TypeError):
        return None
