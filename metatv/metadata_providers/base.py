"""Base classes for metadata provider plugins"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field


@dataclass
class MetadataResult:
    """Standard metadata result structure
    
    All metadata providers return this standardized format.
    Fields are optional - providers populate what they can.
    """
    # Basic info
    title: Optional[str] = None
    year: Optional[int] = None
    plot: Optional[str] = None
    tagline: Optional[str] = None
    
    # Media URLs
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    logo_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    
    # People
    cast: List[Dict[str, Any]] = field(default_factory=list)  # [{name, character, photo_url}]
    crew: List[Dict[str, Any]] = field(default_factory=list)  # [{name, job, department}]
    director: Optional[str] = None
    
    # Classification
    genres: List[str] = field(default_factory=list)
    content_rating: Optional[str] = None  # PG-13, TV-MA, etc.
    
    # Ratings
    rating: Optional[float] = None  # 0-10 scale
    rating_count: Optional[int] = None
    ratings: Dict[str, float] = field(default_factory=dict)  # {"imdb": 8.5, "tmdb": 8.2, "rt": 85}
    
    # Technical
    runtime: Optional[int] = None  # minutes
    release_date: Optional[str] = None  # ISO date
    
    # Links
    trailer_url: Optional[str] = None
    imdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    
    # Provider info
    provider_name: Optional[str] = None  # Which plugin provided this data
    confidence: float = 0.0  # 0-1 confidence score, default to 0 for empty results
    
    def merge(self, other: 'MetadataResult', prefer_higher_confidence: bool = True):
        """Merge another result into this one
        
        Only fills in missing fields. If this result is empty, always accepts data.
        If both have data, uses confidence to decide.
        
        Args:
            other: MetadataResult to merge from
            prefer_higher_confidence: If True, only overwrite if other has higher confidence
        """
        if not other:
            return
        
        # If we're empty (no title), always accept data regardless of confidence
        is_empty = self.title is None and self.plot is None and self.poster_url is None
        
        # Check confidence only if we already have data
        if not is_empty and prefer_higher_confidence and other.confidence < self.confidence:
            return
        
        # Update confidence to the higher value
        if other.confidence > self.confidence:
            self.confidence = other.confidence
            if other.provider_name:
                self.provider_name = other.provider_name
        
        # Merge each field (only if current field is None/empty)
        for field_name in self.__dataclass_fields__:
            if field_name in ('provider_name', 'confidence'):
                continue  # Skip metadata fields
            
            current_value = getattr(self, field_name)
            other_value = getattr(other, field_name)
            
            # Only overwrite if current is None/empty and other has value
            if other_value is not None:
                if isinstance(other_value, (list, dict)):
                    # For lists/dicts, only overwrite if empty
                    if not current_value:
                        setattr(self, field_name, other_value)
                else:
                    # For scalar values, overwrite None
                    if current_value is None:
                        setattr(self, field_name, other_value)
    
    def is_complete(self, required_fields: Optional[List[str]] = None) -> bool:
        """Check if all required fields are populated
        
        Args:
            required_fields: List of field names that must be present.
                           If None, checks common fields.
        """
        if required_fields is None:
            required_fields = ['title', 'plot', 'poster_url']
        
        for field_name in required_fields:
            value = getattr(self, field_name, None)
            if value is None or (isinstance(value, (list, dict, str)) and not value):
                return False
        
        return True


class MetadataProviderPlugin(ABC):
    """Base class for metadata provider plugins
    
    Plugins can fetch metadata from external APIs (TMDb, OMDb, etc.)
    or extract from provider's raw data (Xtream API fields).
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name (e.g., 'tmdb', 'omdb', 'provider')"""
        pass
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for UI (e.g., 'The Movie Database')"""
        pass
    
    @property
    @abstractmethod
    def supported_media_types(self) -> List[str]:
        """Media types this provider supports: ['movie', 'series', 'live']"""
        pass
    
    @property
    @abstractmethod
    def supported_fields(self) -> List[str]:
        """Fields this provider can populate
        
        Examples: ['poster', 'cast', 'plot', 'rating', 'trailer', etc.]
        """
        pass
    
    @abstractmethod
    async def search(self, title: str, year: Optional[int] = None,
                    media_type: str = "movie") -> List[Dict[str, Any]]:
        """Search for content by title and year
        
        Args:
            title: Content title to search for
            year: Optional year to narrow results
            media_type: Type of content ('movie', 'series', 'live')
        
        Returns:
            List of search results with at least 'id' and 'title' keys
        """
        pass
    
    @abstractmethod
    async def get_details(self, external_id: str,
                         media_type: str = "movie") -> Optional[MetadataResult]:
        """Get full metadata for content by external ID
        
        Args:
            external_id: Provider-specific ID (tmdb_id, imdb_id, channel_id, etc.)
            media_type: Type of content ('movie', 'series', 'live')
        
        Returns:
            MetadataResult with populated fields, or None if not found
        """
        pass
    
    @abstractmethod
    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test if provider is accessible and configured correctly
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        pass
    
    def get_rate_limit(self) -> tuple[int, int]:
        """Return (requests, seconds) for rate limiting
        
        Returns:
            Tuple of (max_requests, time_window_seconds).
            (0, 0) means no rate limiting.
        """
        return (0, 0)  # 0 = no limit
    
    def requires_api_key(self) -> bool:
        """Whether this provider needs an API key"""
        return False
    
    def get_priority(self) -> int:
        """Default priority (lower = higher priority)
        
        Can be overridden in config.
        Suggested values:
        - 1-10: Cached/local data sources (provider raw_data)
        - 11-50: Standard metadata APIs (TMDb, OMDb)
        - 51-100: Secondary sources (FanartTV, TVDB)
        """
        return 50  # Medium priority
    
    def is_enabled(self) -> bool:
        """Whether this provider is enabled
        
        Override to check configuration or API key availability.
        """
        return True
