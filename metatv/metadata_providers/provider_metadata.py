"""Provider metadata plugin - extracts from raw_data field"""
from typing import Optional, Dict, List, Any
import re

from loguru import logger

from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult


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

                result = MetadataResult(
                    title=info.get('name') or channel.name,
                    plot=info.get('plot') or info.get('description'),
                    tagline=info.get('tagline'),

                    # Images (use logo_url/stream_icon as poster fallback)
                    poster_url=info.get('cover') or info.get('movie_image') or channel.logo_url,
                    backdrop_url=self._get_first_or_none(info.get('backdrop_path', [])),
                    logo_url=channel.logo_url,

                    # People
                    director=info.get('director'),
                    cast=self._parse_cast_string(info.get('cast', '')),

                    # Classification
                    genres=self._parse_genres(info.get('genre', '')),
                    content_rating=info.get('rating') if isinstance(info.get('rating'), str) else None,

                    # Ratings
                    rating=self._parse_rating(info.get('rating')),

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

                logger.debug(f"Extracted metadata: title={result.title}, plot_len={len(result.plot) if result.plot else 0}, poster={bool(result.poster_url)}, cast={len(result.cast) if result.cast else 0}")
                return result

        except Exception as e:
            logger.warning(f"Failed to extract provider metadata for {channel_id}: {e}", exc_info=True)
            return None
    
    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Always available (database)"""
        return (True, None)
    
    def _parse_cast_string(self, cast_str: str) -> List[Dict[str, Any]]:
        """Parse comma-separated cast string into structured list
        
        Args:
            cast_str: "Actor1, Actor2, Actor3" format
        
        Returns:
            List of dicts with 'name' key
        """
        if not cast_str:
            return []
        
        # Split by comma and clean
        names = [name.strip() for name in cast_str.split(',') if name.strip()]
        
        # Return as list of dicts for consistency with TMDb format
        return [{"name": name, "character": None, "photo_url": None} for name in names]
    
    def _parse_genres(self, genre_str: str) -> List[str]:
        if not genre_str:
            return []
        # Some providers use " / " (Xtream/TREX style), others use "," — handle both.
        # Do NOT split on "&" since "Action & Adventure" is a single genre.
        return [g.strip() for g in re.split(r'\s*/\s*|,\s*', genre_str) if g.strip()]
    
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
