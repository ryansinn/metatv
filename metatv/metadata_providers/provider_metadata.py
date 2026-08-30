"""Provider metadata plugin - extracts from raw_data field"""
from typing import Optional, Dict, List, Any
import json
import re

from loguru import logger

from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult
from metatv.metadata_providers.raw_parse import (
    extract_artwork,
    extract_trailer,
    parse_cast_string,
    parse_genres,
)


def _parse_rating(rating_value) -> Optional[float]:
    """Parse rating value from various formats

    Args:
        rating_value: Could be string, float, or int

    Returns:
        Float rating on 0-10 scale, or None
    """
    if rating_value is None:
        return None

    try:
        # Convert to float
        rating = float(rating_value)

        # Clamp to 0-10 range
        return max(0.0, min(10.0, rating))

    except (ValueError, TypeError):
        return None

def _parse_runtime(duration_value) -> Optional[int]:
    """Parse a runtime in minutes from whatever shape the provider used.

    Args:
        duration_value: ``"120 min"``, ``"45"``, ``120`` — or junk.

    Returns:
        Runtime in minutes, or ``None``.

    Notes:
        ``"0"`` yields ``None``, not ``0``. Providers use zero as "unknown", and
        the string is truthy so the guard below cannot catch it — a stored 0
        would render as a real "0 min" runtime, which is worse than showing
        nothing.
    """
    if not duration_value:
        return None

    try:
        # If already an int, return it
        if isinstance(duration_value, int):
            return duration_value or None

        # Try to extract number from string
        duration_str = str(duration_value)
        match = re.search(r'(\d+)', duration_str)
        if match:
            return int(match.group(1)) or None

    except (ValueError, TypeError):
        pass

    return None


def _info_of(raw_data) -> "dict | None":
    """Resolve a stored blob to the info dict ``metadata_from_raw`` would use.

    The flat ``raw_data`` is the base and a nested ``raw_data['info']`` is
    layered on top, so a TOP-level key (``episode_run_time``, ``trailer``)
    stays reachable even when the provider also sends an info dict. Both fields
    were missed for the same reason, so the resolution lives in one place
    rather than being re-derived per field.

    Only for the technical fields that read it — ``duration``,
    ``episode_run_time``, ``trailer``, ``youtube_trailer``. Do NOT reuse this
    for ``rating``: ``metadata_from_raw`` deliberately drops the top-level
    ``rating``/``rating_5based``, which are Xtream stream-API placeholders
    (always "10"/"5"), and a merged view would put them back.

    Args:
        raw_data: A stored provider blob — dict, JSON string, or None.

    Returns:
        The info dict, or None when there is nothing to read.
    """
    if not raw_data:
        return None
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw_data, dict):
        return None
    info = raw_data.get('info')
    if not isinstance(info, dict) or not info:
        return raw_data
    # MERGED, not "nested wins outright". A payload can carry a non-empty info
    # dict AND a top-level episode_run_time, and returning info alone made the
    # top-level key unreachable — a regression the existing runtime tests
    # caught. Nested values win where both spell the same key.
    merged = dict(raw_data)
    merged.update(info)
    return merged


def trailer_from_raw(raw_data) -> Optional[str]:
    """Return the trailer URL a provider payload implies, or None.

    Sibling of :func:`runtime_from_raw`, for the same reason: ingestion and the
    one-time backfill must agree on where a field lives, so they call the same
    function. The shapes themselves live in ``raw_parse.extract_trailer``.

    Args:
        raw_data: A stored provider blob — dict, JSON string, or None.

    Returns:
        A playable URL, or None.
    """
    info = _info_of(raw_data)
    return extract_trailer(info) if info is not None else None


def runtime_from_raw(raw_data) -> Optional[int]:
    """Return the runtime in minutes a provider payload implies, or None.

    The single definition of *where the runtime lives*. Ingestion
    (``metadata_from_raw``) and the one-time backfill
    (``core.migrations.raw_field_backfill``) both call this, so a new provider
    shape is taught here once rather than drifting between the two.

    Three keys, in precedence order:

    * ``info.duration`` — the movie shape (``"120 min"`` / ``120``).
    * ``info.episode_run_time`` — a nested series shape.
    * ``raw_data.episode_run_time`` — the series shape the owner's three
      providers actually send: a bare minutes string at the TOP level, with no
      ``info`` sub-dict at all.

    The third key is why this is not simply ``info.get('duration')``. Nothing
    read it, so ``MetadataDB.runtime`` was populated on **0 of 652,216 rows** —
    the one surface that renders a runtime never had one to show. Of the
    owner's 127,552 series, 48,322 resolve a real value here; the remaining
    79,230 send ``"0"``, which ``_parse_runtime`` deliberately maps to None.

    Args:
        raw_data: A stored provider blob — dict, JSON string, or None.

    Returns:
        Runtime in minutes, or None when the payload implies none.
    """
    info = _info_of(raw_data)
    if info is None:
        return None
    return _parse_runtime(info.get('duration') or info.get('episode_run_time'))


def metadata_from_raw(raw_data, *, name: str, detected_title: str | None = None,
                      logo_url: str | None = None) -> "Optional[MetadataResult]":
    """Parse a provider's stored ``raw_data`` into metadata. No session, no network.

    Lifted out of :meth:`ProviderMetadataProvider.get_details` so the offline
    backfill can use the SAME parse. That method is async and opens a session
    per channel, which is fine for one details pane and unusable for the
    400,000 rows the backfill walks — but a second parser would be two answers
    to "what does this blob mean", and the genre/cast splitting already lives in
    one place (raw_parse.py) precisely to avoid that.

    Args:
        raw_data: The provider's stored record (dict), or None.
        name: The channel's raw name, used as the title fallback.
        detected_title: The ingestion-cleaned title; preferred over *name*.
        logo_url: The channel's stored poster, used when the blob has none.

    Returns:
        A ``MetadataResult``, or None when there is nothing to parse.
    """
    if not raw_data:
        return None
    # Xtream API stores metadata in 'info' dict
    info = raw_data.get('info', {})

    # Preserve raw_data rating as fallback before potentially filtering
    raw_rating = raw_data.get('rating') if raw_data else None

    # NO per-row logging in here. This function runs once per catalogue row: on
    # the owner's library the three DEBUG lines that used to sit in this block
    # fired 650,101 times each and produced 1.30M of 1.44M total log lines —
    # 330 MB, which under a seven-day retention left 8 days of history where
    # there would otherwise be 76. Whether a blob was flat or nested is not
    # worth one line per title; the shape is visible in the row itself.
    if not info:
        # Maybe raw_data IS the info (flat structure)
        info = dict(raw_data)   # shallow copy — don't mutate stored raw_data
        # Xtream top-level 'rating'/'rating_5based' are stream-API placeholders
        # (always '10'/'5') — not real content ratings from TMDb/IMDb.
        info.pop('rating', None)
        info.pop('rating_5based', None)

    # Title — prefer a real provider-supplied name, but when the
    # provider only echoes the raw channel name back (the common
    # Xtream case, or no name at all), fall back to the clean
    # detected_title computed at ingestion (single source of truth).
    # Storing the raw name here re-introduced the language prefix +
    # (YYYY) that detected_title already stripped, which the details
    # pane then rendered — duplicating the chips shown beside it.
    info_name = info.get('name')
    clean_title = detected_title or name
    if info_name and info_name.strip().casefold() != name.strip().casefold():
        resolved_title = info_name
    else:
        resolved_title = clean_title

    _poster, _backdrop = extract_artwork(info)
    return MetadataResult(
        title=resolved_title,
        plot=info.get('plot') or info.get('description'),
        tagline=info.get('tagline'),

        # Images. The keys and their precedence live in
        # raw_parse.extract_artwork — the same helper the enrichment
        # sweep's harvest uses, so the two can't disagree about where
        # a poster is. The logo_url fallback stays HERE because it is
        # a fact about this channel, not about the blob.
        poster_url=_poster or logo_url,
        backdrop_url=_backdrop,
        logo_url=logo_url,

        # People
        director=info.get('director'),
        cast=parse_cast_string(info.get('cast', '')),

        # Classification
        genres=parse_genres(info.get('genre', '')),
        content_rating=info.get('rating') if isinstance(info.get('rating'), str) else None,

        # Ratings — use info rating if available, fall back to raw_data rating
        rating=_parse_rating(info.get('rating')) or _parse_rating(raw_rating),

        # Technical
        runtime=runtime_from_raw(raw_data),
        release_date=info.get('releaseDate') or info.get('release_date'),

        # Links
        trailer_url=extract_trailer(info),
        tmdb_id=str(info.get('tmdb_id', '')) if info.get('tmdb_id') else None,

        # Metadata
        provider_name="provider",
        confidence=0.8  # Good quality but not verified against external source
    )


class ProviderMetadataProvider(MetadataProviderPlugin):
    """Extract metadata from provider's raw_data field (Xtream API)
    
    This provider has the highest priority (1) because it's free, instant,
    and the data is already cached in the database from the provider.
    """
    
    def __init__(self, database):
        """Initialize with database access
        
        Args:
            database: Database instance for accessing ChannelDB
        """
        self.db = database
    
    @property
    def name(self) -> str:
        return "provider"
    
    @property
    def display_name(self) -> str:
        return "Provider Metadata"
    
    @property
    def supported_media_types(self) -> List[str]:
        return ["movie", "series", "live"]
    
    @property
    def supported_fields(self) -> List[str]:
        return [
            "poster", "backdrop", "plot", "cast", "director", "genres",
            "rating", "release_date", "runtime", "trailer", "tmdb_id"
        ]
    
    def get_priority(self) -> int:
        return 1  # Highest priority (already cached, no API call)
    
    async def search(self, title: str, year: Optional[int] = None,
                    media_type: str = "movie") -> List[Dict[str, Any]]:
        """Search not implemented - this provider only serves cached data"""
        return []
    
    async def get_details(self, channel_id: str,
                         media_type: str = "movie") -> Optional[MetadataResult]:
        """Extract metadata from channel's raw_data field
        
        Args:
            channel_id: Channel ID in database
            media_type: Type of content
        
        Returns:
            MetadataResult with fields from raw_data, or None if not available
        """
        try:
            with self.db.session_scope() as session:
                from metatv.core.database import ChannelDB
                channel = session.query(ChannelDB).filter_by(id=channel_id).first()

                if not channel:
                    logger.debug(f"Channel not found: {channel_id}")
                    return None

                if not channel.raw_data:
                    logger.debug(f"No raw_data for channel: {channel.name}")
                    return None

                result = metadata_from_raw(
                    channel.raw_data,
                    name=channel.name,
                    detected_title=channel.detected_title,
                    logo_url=channel.logo_url,
                )
                if result is None:
                    return None

                logger.debug(f"Extracted metadata: title={result.title}, plot_len={len(result.plot) if result.plot else 0}, poster={bool(result.poster_url)}, cast={len(result.cast) if result.cast else 0}, rating={result.rating}")
                return result

        except Exception as e:
            logger.warning(f"Failed to extract provider metadata for {channel_id}: {e}", exc_info=True)
            return None
    
    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Always available (database)"""
        return (True, None)
    
    def _parse_cast_string(self, cast_str: str) -> List[Dict[str, Any]]:
        """Parse comma-separated cast string into structured list.

        Thin wrapper over the shared parser so there is one cast parser in the
        codebase (also used by the enrichment sweep — see raw_parse.py).
        """
        return parse_cast_string(cast_str)

    def _parse_genres(self, genre_str: str) -> List[str]:
        """Parse a provider genre string into a list.

        Thin wrapper over the shared parser so there is one genre parser in the
        codebase (also used by the enrichment sweep — see raw_parse.py).
        """
        return parse_genres(genre_str)
    
    _parse_rating = staticmethod(_parse_rating)


    _parse_runtime = staticmethod(_parse_runtime)


    def _get_first_or_none(self, value) -> Optional[str]:
        """Get first element of list or return None
        
        Args:
            value: Could be list, string, or None
        
        Returns:
            First element if list, value if string, None otherwise
        """
        if isinstance(value, list) and value:
            return value[0]
        elif isinstance(value, str):
            return value
        return None
