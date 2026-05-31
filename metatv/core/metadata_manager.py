"""Metadata provider management and coordination"""
import asyncio
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from collections import deque

from loguru import logger

from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult
from metatv.core.database import MetadataDB, ChannelDB


class RateLimiter:
    """Simple rate limiter for API calls"""
    
    def __init__(self, max_requests: int, time_window: int):
        """Initialize rate limiter
        
        Args:
            max_requests: Maximum number of requests allowed
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()  # Timestamps of recent requests
    
    def can_request(self) -> bool:
        """Check if a request can be made now"""
        if self.max_requests == 0:  # No limit
            return True
        
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.time_window)
        
        # Remove old requests outside time window
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()
        
        return len(self.requests) < self.max_requests
    
    def record_request(self):
        """Record that a request was made"""
        if self.max_requests == 0:  # No limit
            return
        
        self.requests.append(datetime.now())
    
    async def wait_if_needed(self):
        """Wait until a request can be made"""
        while not self.can_request():
            await asyncio.sleep(0.1)  # Wait 100ms and check again
        
        self.record_request()


class MetadataProviderRegistry:
    """Registry for metadata provider plugins"""
    
    def __init__(self):
        self.providers: Dict[str, MetadataProviderPlugin] = {}
        self.priority_order: List[str] = []
    
    def register(self, provider: MetadataProviderPlugin):
        """Register a metadata provider
        
        Args:
            provider: MetadataProviderPlugin instance
        """
        self.providers[provider.name] = provider
        self._update_priority_order()
        logger.info(f"Registered metadata provider: {provider.display_name} "
                   f"(priority={provider.get_priority()})")
    
    def unregister(self, name: str):
        """Unregister a provider by name"""
        if name in self.providers:
            del self.providers[name]
            self._update_priority_order()
            logger.info(f"Unregistered metadata provider: {name}")
    
    def get(self, name: str) -> Optional[MetadataProviderPlugin]:
        """Get provider by name"""
        return self.providers.get(name)
    
    def get_all(self) -> List[MetadataProviderPlugin]:
        """Get all registered providers in priority order"""
        return [self.providers[name] for name in self.priority_order 
                if name in self.providers]
    
    def get_enabled(self) -> List[MetadataProviderPlugin]:
        """Get enabled providers in priority order"""
        return [p for p in self.get_all() if p.is_enabled()]
    
    def _update_priority_order(self):
        """Sort providers by priority (lower = higher priority)"""
        items = list(self.providers.items())
        items.sort(key=lambda x: x[1].get_priority())
        self.priority_order = [name for name, _ in items]
        logger.debug(f"Provider priority order: {self.priority_order}")


class MetadataManager:
    """Manages metadata fetching with plugin fallback chain
    
    Features:
    - Three-tier loading: Database cache → Provider data → External APIs
    - Rate limiting per provider
    - Intelligent merging of partial results
    - Cache staleness detection
    """
    
    # Default cache TTL
    DEFAULT_CACHE_TTL_DAYS = 30  # Fresh content
    OLD_CONTENT_CACHE_TTL_DAYS = 90  # Content older than 2 years
    
    def __init__(self, registry: MetadataProviderRegistry, database):
        """Initialize metadata manager
        
        Args:
            registry: MetadataProviderRegistry with registered providers
            database: Database instance
        """
        self.registry = registry
        self.db = database
        self.rate_limiters: Dict[str, RateLimiter] = {}
        
        # Create rate limiters for each provider
        self._init_rate_limiters()
    
    def _init_rate_limiters(self):
        """Initialize rate limiters for all providers"""
        for provider in self.registry.get_all():
            max_requests, time_window = provider.get_rate_limit()
            if max_requests > 0:
                self.rate_limiters[provider.name] = RateLimiter(max_requests, time_window)
                logger.debug(f"Rate limiter for {provider.name}: "
                           f"{max_requests} requests per {time_window}s")
    
    async def get_metadata(self, channel_id: str,
                          force_refresh: bool = False) -> Optional[MetadataResult]:
        """Get metadata using plugin fallback chain
        
        Args:
            channel_id: Channel ID to fetch metadata for
            force_refresh: If True, bypass cache and fetch fresh data
        
        Returns:
            MetadataResult with merged data from all providers, or None
        """
        logger.debug(f"=== get_metadata called for channel_id={channel_id}, force_refresh={force_refresh}")
        try:
            logger.debug(f"Getting database session...")
            session = self.db.get_session()
            try:
                logger.debug(f"Querying for channel {channel_id}...")
                channel = session.query(ChannelDB).filter_by(id=channel_id).first()
                
                if not channel:
                    logger.warning(f"Channel not found: {channel_id}")
                    return None
                
                logger.debug(f"Found channel: {channel.name}")
                
                # Check cache first (unless force refresh)
                if not force_refresh and channel.metadata_id:
                    cached = self._get_cached_metadata(session, channel.metadata_id)
                    if cached and not self._is_stale(cached):
                        logger.debug(f"Using cached metadata for {channel.name}")
                        return self._metadata_db_to_result(cached)
                
                # Try providers in priority order
                result = MetadataResult()
                providers_tried = []
                
                logger.debug(f"Trying {len(self.registry.get_enabled())} enabled providers for {channel.name}")
                
                for provider in self.registry.get_enabled():
                    # Skip if not supported for this media type
                    if channel.media_type not in provider.supported_media_types:
                        logger.debug(f"Skipping {provider.name}: doesn't support {channel.media_type}")
                        continue
                    
                    # Rate limit check
                    if not await self._check_rate_limit(provider.name):
                        logger.debug(f"Rate limit reached for {provider.name}, skipping")
                        continue
                    
                    try:
                        logger.debug(f"Fetching metadata from {provider.name} for {channel.name}")
                        
                        # Fetch from provider
                        partial = await provider.get_details(
                            channel.id,
                            media_type=channel.media_type
                        )
                        
                        if partial:
                            logger.debug(f"{provider.name} returned: title={partial.title}, plot={'Yes' if partial.plot else 'No'}, poster={'Yes' if partial.poster_url else 'No'}")
                            providers_tried.append(provider.name)
                            
                            # Merge partial result (fill in missing fields only)
                            result.merge(partial)
                            
                            # If all important fields populated, stop early
                            if result.is_complete():
                                logger.debug(f"Metadata complete after {provider.name}")
                                break
                        else:
                            logger.debug(f"{provider.name} returned None")
                    
                    except Exception as e:
                        logger.warning(f"Metadata fetch failed from {provider.name}: {e}", exc_info=True)
                        continue
                
                logger.debug(f"Merged result: title={result.title}, plot={'Yes' if result.plot else 'No'}, poster={'Yes' if result.poster_url else 'No'}")
                
                # Save to cache if we got any data
                if result.title or result.plot or result.poster_url:
                    self._save_metadata_cache(session, channel, result)
                    logger.info(f"Cached metadata for {channel.name} from: {', '.join(providers_tried)}")
                    return result
                
                logger.debug(f"No metadata found for {channel.name}")
                return None
            finally:
                session.close()
        
        except Exception as e:
            logger.error(f"Error fetching metadata for {channel_id}: {e}", exc_info=True)
            return None
    
    async def _check_rate_limit(self, provider_name: str) -> bool:
        """Check and wait for rate limit if needed
        
        Args:
            provider_name: Name of provider to check
        
        Returns:
            True if request can proceed
        """
        if provider_name in self.rate_limiters:
            limiter = self.rate_limiters[provider_name]
            if not limiter.can_request():
                await limiter.wait_if_needed()
            else:
                limiter.record_request()
        
        return True
    
    def _get_cached_metadata(self, session, metadata_id: str) -> Optional[MetadataDB]:
        """Get cached metadata from database"""
        return session.query(MetadataDB).filter_by(id=metadata_id).first()
    
    def _is_stale(self, metadata: MetadataDB) -> bool:
        """Check if cached metadata is stale
        
        Args:
            metadata: MetadataDB instance
        
        Returns:
            True if metadata should be refreshed
        """
        if not metadata.fetched_at:
            return True
        
        # Use different TTL for old vs new content
        now = datetime.now()
        age_days = (now - metadata.fetched_at).days
        
        # Check if content is old (released > 2 years ago)
        is_old_content = False
        if metadata.year:
            current_year = now.year
            is_old_content = (current_year - metadata.year) > 2
        
        ttl_days = self.OLD_CONTENT_CACHE_TTL_DAYS if is_old_content else self.DEFAULT_CACHE_TTL_DAYS
        
        return age_days > ttl_days
    
    def _metadata_db_to_result(self, metadata: MetadataDB) -> MetadataResult:
        """Convert MetadataDB to MetadataResult"""
        import json
        
        # Deserialize JSON fields (they're stored as strings in SQLite)
        cast = metadata.cast
        if isinstance(cast, str):
            cast = json.loads(cast) if cast else []
        elif cast is None:
            cast = []
            
        crew = metadata.crew
        if isinstance(crew, str):
            crew = json.loads(crew) if crew else []
        elif crew is None:
            crew = []
            
        genres = metadata.genres
        if isinstance(genres, str):
            genres = json.loads(genres) if genres else []
        elif genres is None:
            genres = []
        
        return MetadataResult(
            title=metadata.title,
            year=metadata.year,
            plot=metadata.plot,
            tagline=metadata.tagline,
            
            poster_url=metadata.poster_url,
            backdrop_url=metadata.backdrop_url,
            
            cast=cast,
            crew=crew,
            director=metadata.director,
            
            genres=genres,
            content_rating=metadata.content_rating,
            
            rating=metadata.rating,
            rating_count=metadata.rating_count,
            
            runtime=metadata.runtime,
            release_date=metadata.release_date,
            
            trailer_url=metadata.trailer_url,
            imdb_id=metadata.imdb_id,
            tmdb_id=metadata.tmdb_id,
            
            provider_name=metadata.source,
            confidence=1.0
        )
    
    def _save_metadata_cache(self, session, channel: ChannelDB, result: MetadataResult):
        """Save metadata result to cache"""
        import json
        
        try:
            logger.debug(f"Saving metadata cache for {channel.name}")
            
            # Create or update MetadataDB entry
            if channel.metadata_id:
                metadata = session.query(MetadataDB).filter_by(id=channel.metadata_id).first()
            else:
                metadata = None
            
            if not metadata:
                # Generate new ID
                metadata_id = f"meta_{channel.id}"
                metadata = MetadataDB(id=metadata_id)
                session.add(metadata)
                channel.metadata_id = metadata_id
            
            # Update fields
            metadata.title = result.title
            metadata.year = result.year
            metadata.plot = result.plot
            metadata.tagline = result.tagline
            
            metadata.poster_url = result.poster_url
            metadata.backdrop_url = result.backdrop_url
            
            # Convert cast/crew to JSON strings for SQLite compatibility
            logger.debug(f"Cast data type: {type(result.cast)}, value: {result.cast[:2] if result.cast else None}")
            logger.debug(f"Crew data type: {type(result.crew)}, value: {result.crew[:2] if result.crew else None}")
            
            # Manually serialize to JSON strings to avoid SQLAlchemy JSON issues
            metadata.cast = json.dumps(result.cast) if result.cast else json.dumps([])
            metadata.crew = json.dumps(result.crew) if result.crew else json.dumps([])
            metadata.genres = json.dumps(result.genres) if result.genres else json.dumps([])

            metadata.director = result.director
            metadata.content_rating = result.content_rating
            
            metadata.rating = result.rating
            metadata.rating_count = result.rating_count
            
            metadata.runtime = result.runtime
            metadata.release_date = result.release_date
            
            metadata.trailer_url = result.trailer_url
            metadata.imdb_id = result.imdb_id
            metadata.tmdb_id = result.tmdb_id
            
            metadata.source = result.provider_name
            metadata.fetched_at = datetime.now()
            
            logger.debug(f"Committing metadata for {channel.name}")
            session.commit()
            logger.debug(f"Successfully saved metadata for {channel.name}")
            
        except Exception as e:
            logger.error(f"Failed to save metadata cache for {channel.name}: {type(e).__name__}: {e}", exc_info=True)
            session.rollback()
            raise  # Re-raise to see the full error in the outer handler
