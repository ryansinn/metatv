"""Provider metadata plugin - extracts from raw_data field"""
from typing import Optional, Dict, List, Any
import re

from loguru import logger

from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult
from metatv.metadata_providers.raw_parse import (
    extract_artwork,
    parse_cast_string,
    parse_genres,
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

                # Xtream API stores metadata in 'info' dict
                info = channel.raw_data.get('info', {})

                # Preserve raw_data rating as fallback before potentially filtering
                raw_rating = channel.raw_data.get('rating') if channel.raw_data else None

                if not info:
                    # Maybe raw_data IS the info (flat structure)
                    info = dict(channel.raw_data)   # shallow copy — don't mutate stored raw_data
                    logger.debug(f"Using flat raw_data structure for {channel.name}")
                    # Xtream top-level 'rating'/'rating_5based' are stream-API placeholders
                    # (always '10'/'5') — not real content ratings from TMDb/IMDb.
                    info.pop('rating', None)
                    info.pop('rating_5based', None)
                else:
                    logger.debug(f"Using nested 'info' structure for {channel.name}")

                logger.debug(f"Available fields in raw_data: {list(info.keys())}")

                # Title — prefer a real provider-supplied name, but when the
                # provider only echoes the raw channel name back (the common
                # Xtream case, or no name at all), fall back to the clean
                # detected_title computed at ingestion (single source of truth).
                # Storing the raw name here re-introduced the language prefix +
                # (YYYY) that detected_title already stripped, which the details
                # pane then rendered — duplicating the chips shown beside it.
                info_name = info.get('name')
                clean_title = channel.detected_title or channel.name
                if info_name and info_name.strip().casefold() != channel.name.strip().casefold():
                    resolved_title = info_name
                else:
                    resolved_title = clean_title

                _poster, _backdrop = extract_artwork(info)
                result = MetadataResult(
                    title=resolved_title,
                    plot=info.get('plot') or info.get('description'),
                    tagline=info.get('tagline'),

                    # Images. The keys and their precedence live in
                    # raw_parse.extract_artwork — the same helper the enrichment
                    # sweep's harvest uses, so the two can't disagree about where
                    # a poster is. The logo_url fallback stays HERE because it is
                    # a fact about this channel, not about the blob.
                    poster_url=_poster or channel.logo_url,
                    backdrop_url=_backdrop,
                    logo_url=channel.logo_url,

                    # People
                    director=info.get('director'),
                    cast=self._parse_cast_string(info.get('cast', '')),

                    # Classification
                    genres=self._parse_genres(info.get('genre', '')),
                    content_rating=info.get('rating') if isinstance(info.get('rating'), str) else None,

                    # Ratings — use info rating if available, fall back to raw_data rating
                    rating=self._parse_rating(info.get('rating')) or self._parse_rating(raw_rating),

                    # Technical
                    runtime=self._parse_runtime(info.get('duration')),
                    release_date=info.get('releaseDate') or info.get('release_date'),

                    # Links
                    trailer_url=info.get('youtube_trailer'),
                    tmdb_id=str(info.get('tmdb_id', '')) if info.get('tmdb_id') else None,

                    # Metadata
                    provider_name="provider",
                    confidence=0.8  # Good quality but not verified against external source
                )

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
    
    def _parse_rating(self, rating_value) -> Optional[float]:
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
    
    def _parse_runtime(self, duration_value) -> Optional[int]:
        """Parse runtime from various formats
        
        Args:
            duration_value: Could be string like "120 min" or int
        
        Returns:
            Runtime in minutes as int, or None
        """
        if not duration_value:
            return None
        
        try:
            # If already an int, return it
            if isinstance(duration_value, int):
                return duration_value
            
            # Try to extract number from string
            duration_str = str(duration_value)
            match = re.search(r'(\d+)', duration_str)
            if match:
                return int(match.group(1))
        
        except (ValueError, TypeError):
            pass
        
        return None
    
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
