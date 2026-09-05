"""Core data models"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List
from enum import Enum

from metatv.core.url_policy import UrlRankingPolicy, get_url_ranking_policy


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

    # Canonical TMDb id extracted from raw_data at ingestion (validated via
    # content_identity.valid_tmdb_id). Persisted to ChannelDB.detected_tmdb_id
    # by the catalog upsert; drives the tmdb-first content_key. None when the
    # provider ships no id (or a sentinel).
    detected_tmdb_id: Optional[str] = None

    # Provider rating/added-date extracted from raw_data at ingestion (DB-4;
    # content_identity.rating_from_raw/added_from_raw). Persisted to
    # ChannelDB.detected_rating/detected_added by the catalog upsert so the
    # Discover shelf queries can sort/filter on an indexed column instead of
    # json_extract()'ing raw_data per row.
    detected_rating: Optional[float] = None
    detected_added: Optional[int] = None

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
    #: False when the failure says nothing about THIS host.
    #:
    #: A 403/405/401/429 is a statement about the caller — a blocked VPN exit
    #: IP, an expired subscription — and every host on the account returns it
    #: identically. Counting it against a host demotes a perfectly good address
    #: for something it did not do, and when all hosts are refused it demotes
    #: all of them equally while also putting every one into cooldown, so the
    #: next genuine attempt is delayed across the board.
    #:
    #: The attempt is still RECORDED, because the history is true and the
    #: diagnosis reads it. It just does not count toward health or cooldown.
    host_at_fault: bool = True


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

    # One-shot: try this URL first on the next connection attempt; cleared as
    # soon as the next attempt on it is recorded, so evidence resumes control.
    try_first: bool = False

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

    def health_score(self, decay: float) -> float:
        """Recency-weighted (EWMA) success ratio over ``recent_attempts``.

        ``recent_attempts`` is stored oldest-first (``add_attempt`` appends);
        this walks it newest-first and weights attempt ``i`` (0 = newest) by
        ``decay ** i``, so a recent run of failures drags the score down fast
        while an old failure fades out — unlike ``reliability_score``, a
        lifetime ratio that a single stale outage can never meaningfully move.

        Falls back to the legacy lifetime ratio (``reliability_score``, as a
        0-1 fraction) when ``recent_attempts`` is empty — every existing
        user's pre-upgrade data — so upgrading does not reset a host with a
        long track record back to "untested". With no data at all, returns
        ``1.0`` (untested = optimistic), matching today's behaviour.
        """
        if self.recent_attempts:
            weighted_success = 0.0
            weight_total = 0.0
            weight = 1.0
            for attempt in reversed(self.recent_attempts):
                # A refusal aimed at the account, not this host, is skipped
                # entirely rather than counted as a failure — including its
                # weight, so it does not even push older evidence down the
                # decay curve.
                if not attempt.success and not attempt.host_at_fault:
                    continue
                weighted_success += weight * (1.0 if attempt.success else 0.0)
                weight_total += weight
                weight *= decay
            return weighted_success / weight_total if weight_total else 1.0

        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total

    def median_latency_ms(self) -> int:
        """Median ``response_time_ms`` over the successful ``recent_attempts``.

        Returns ``0`` when no successful attempt recorded a latency, so an
        untested/unmeasured URL stays cheap to try rather than being sorted
        behind every measured host.
        """
        latencies = [
            a.response_time_ms
            for a in self.recent_attempts
            if a.success and a.response_time_ms is not None
        ]
        if not latencies:
            return 0
        return int(statistics.median(latencies))
    
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

    def ordered_urls(self, policy: Optional[UrlRankingPolicy] = None) -> List[str]:
        """Return base URLs ranked by what's happening NOW, not a lifetime average.

        Sort key: ``(0 if try_first else 1, cooldown_tier, -health, median_latency_ms, priority)``.

        - ``try_first``: a one-shot user override ("I know something the stats
          don't") that outranks even ``cooldown_tier`` — the user is asking to
          try this address DESPITE a recent failure, not merely ahead of an
          untested one. Cleared by :class:`~metatv.core.url_cycle.UrlCycler`
          as soon as the next attempt on it is recorded.
        - ``cooldown_tier``: ``1`` if the URL's most recent attempt failed
          within the last ``config.url_cooldown_minutes``, else ``0``. This
          only DEMOTES — it never removes a URL from the list, so a total
          outage across every host still returns all of them (there must
          always be something left to try).
        - ``health``: recency-weighted (EWMA) success ratio via
          :meth:`ProviderURL.health_score` — falls back to the lifetime ratio
          for pre-upgrade data with no ``recent_attempts``, and to ``1.0``
          (optimistic) for a never-tried URL.
        - ``median_latency_ms``: via :meth:`ProviderURL.median_latency_ms` —
          ``0`` (cheapest) when unmeasured, so untested URLs still get a
          chance rather than being buried behind measured-but-slow ones.
        - ``priority``: the existing manual field, final tiebreak.

        A chronically slow-but-successful host (e.g. one that answers in
        10-12s every time) no longer sits at the top forever just because it
        never technically fails — the fast, healthy host now sorts first.

        The legacy ``self.url`` is always the final fallback if not already
        present. ``policy`` defaults to the process-wide
        :func:`~metatv.core.url_policy.get_url_ranking_policy` — resolved once
        from ``Config`` at startup, so editing the config actually changes the
        ranking.  Tests pass one explicitly rather than touching the global.
        """
        if policy is None:
            policy = get_url_ranking_policy()

        decay = policy.health_decay
        cooldown = timedelta(minutes=policy.cooldown_minutes)
        now = datetime.now()

        def _key(pu: ProviderURL):
            cooldown_tier = 0
            if pu.recent_attempts:
                newest = pu.recent_attempts[-1]
                if not newest.success and (now - newest.timestamp) <= cooldown:
                    cooldown_tier = 1
            health = pu.health_score(decay)
            latency = pu.median_latency_ms()
            return (0 if pu.try_first else 1, cooldown_tier, -health, latency, pu.priority)

        seen: set = set()
        ordered: List[str] = []
        for pu in sorted((u for u in self.urls if u.is_active), key=_key):
            base = pu.url.rstrip('/')
            if base not in seen:
                seen.add(base)
                ordered.append(base)

        primary = (self.url or '').rstrip('/')
        if primary and primary not in seen:
            ordered.append(primary)

        return ordered or [self.url]


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
