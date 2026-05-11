"""Core data models"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum


# Common media type constants (not exhaustive - providers can use any string)
class MediaType:
    """Common media type constants - providers can use any string value"""
    LIVE = "live"
    MOVIE = "movie"
    SERIES = "series"
    UNKNOWN = "unknown"


class StreamQuality(Enum):
    """Stream quality indicator"""
    SD = "sd"
    HD = "hd"
    FHD = "fhd"
    UHD = "uhd"
    UNKNOWN = "unknown"


@dataclass
class Channel:
    """Standardized channel model"""
    
    # Core identifiers
    id: str
    source_id: str  # Original stream ID from provider (e.g., "12345")
    provider_id: str  # Which provider this came from (e.g., "trex-abc123")
    name: str
    stream_url: str  # Cached URL, can be reconstructed dynamically
    
    # Organization
    category: str = ""
    category_id: Optional[str] = None
    
    # Metadata
    language: Optional[str] = None
    logo_url: Optional[str] = None
    epg_channel_id: Optional[str] = None
    
    # Media info
    media_type: str = MediaType.UNKNOWN  # Use MediaType constants or any provider-specific string
    quality: StreamQuality = StreamQuality.UNKNOWN
    
    # Linking
    metadata_id: Optional[str] = None  # Links to Metadata object
    
    # Status
    is_favorite: bool = False
    is_hidden: bool = False
    last_played: Optional[datetime] = None
    play_count: int = 0
    
    # Raw data from provider
    raw_data: dict = field(default_factory=dict)
    
    # Timestamps
    added_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class Metadata:
    """Media metadata from external sources"""
    
    id: str
    title: str
    
    # Basic info
    year: Optional[int] = None
    runtime: Optional[int] = None  # minutes
    
    # Classification
    genres: List[str] = field(default_factory=list)
    media_type: str = MediaType.UNKNOWN  # Use MediaType constants or any provider-specific string
    
    # People
    actors: List[str] = field(default_factory=list)
    director: Optional[str] = None
    
    # Content
    plot: Optional[str] = None
    tagline: Optional[str] = None
    
    # Ratings
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    
    # Images
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    
    # External IDs
    imdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    
    # Source tracking
    source: str = "unknown"  # Which metadata provider
    
    # Timestamps
    fetched_at: datetime = field(default_factory=datetime.now)


@dataclass
class ConnectionAttempt:
    """Record of a connection attempt"""
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = False
    client_ip: Optional[str] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[int] = None


@dataclass
class ProviderURL:
    """Provider URL with priority and connection tracking"""
    url: str
    priority: int = 0  # Lower is higher priority
    is_active: bool = True
    
    # Connection statistics
    success_count: int = 0
    failure_count: int = 0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_error: Optional[str] = None
    
    # Recent connection attempts (last 100)
    recent_attempts: List[ConnectionAttempt] = field(default_factory=list)
    
    # Client IP failure tracking
    failed_client_ips: dict = field(default_factory=dict)  # {ip: failure_count}
    
    def add_attempt(self, attempt: ConnectionAttempt):
        """Add a connection attempt to history"""
        self.recent_attempts.append(attempt)
        # Keep only last 100
        if len(self.recent_attempts) > 100:
            self.recent_attempts = self.recent_attempts[-100:]
        
        # Track client IP failures
        if not attempt.success and attempt.client_ip:
            if attempt.client_ip not in self.failed_client_ips:
                self.failed_client_ips[attempt.client_ip] = 0
            self.failed_client_ips[attempt.client_ip] += 1
    
    def get_ip_failure_count(self, ip: str) -> int:
        """Get failure count for specific IP"""
        return self.failed_client_ips.get(ip, 0)
    
    def is_ip_blocked(self, ip: str, threshold: int = 3) -> bool:
        """Check if IP appears to be blocked"""
        return self.get_ip_failure_count(ip) >= threshold
    
    # Derived reliability score (0-100)
    @property
    def reliability_score(self) -> float:
        """Calculate reliability score based on success/failure ratio"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 100.0  # Untested, assume good
        return (self.success_count / total) * 100
    
    @property
    def status(self) -> str:
        """Get current status description"""
        if not self.is_active:
            return "Disabled"
        if self.success_count == 0 and self.failure_count == 0:
            return "Untested"
        if self.last_failure and self.last_success:
            if self.last_failure > self.last_success:
                return "Failing"
        if self.last_success:
            return "Working"
        return "Unknown"


@dataclass
class Provider:
    """IPTV provider/source"""
    
    id: str
    name: str
    type: str  # "xtream", "m3u", etc.
    
    # Connection details (stored encrypted)
    url: str  # Primary URL (for backward compatibility)
    urls: List[ProviderURL] = field(default_factory=list)  # Multiple URLs with priority
    username: Optional[str] = None
    password: Optional[str] = None
    
    # Refresh schedule
    refresh_schedule: str = "manual"  # manual, launch, daily, weekly, monthly
    last_refresh: Optional[datetime] = None
    
    # Status
    is_active: bool = True
    last_sync: Optional[datetime] = None
    last_error: Optional[str] = None
    
    # Statistics
    total_channels: int = 0
    total_categories: int = 0
    
    # Timestamps
    added_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class Filter:
    """Filter configuration"""
    
    id: str
    name: str
    description: str = ""
    
    # Scope
    is_global: bool = False
    provider_id: Optional[str] = None  # If not global
    
    # Filter rules (as JSON-serializable dict)
    rules: dict = field(default_factory=dict)
    
    # State
    is_enabled: bool = True
    order: int = 0  # Execution order
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
