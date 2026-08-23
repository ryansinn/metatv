"""Metadata provider management and coordination"""
import asyncio
from typing import Any, Optional, Dict, List, Tuple
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
    """Registry for metadata provider plugins.

    Config-aware (wave4/external-metadata-providers): when constructed with a
    ``config`` (the app ``Config``, or any object exposing the same
    ``metadata_*`` attributes), :meth:`get_enabled` additionally honors three
    previously-dead settings — this is their single enforcement chokepoint,
    so no other call site needs to re-check them:

    - ``metadata_enabled`` — master switch; ``False`` means "consult nobody".
    - ``metadata_enabled_providers`` — allow-list by ``name``; when non-empty,
      only listed providers are consulted (each still also gated by its own
      ``is_enabled()``, e.g. an empty API key).
    - ``metadata_provider_priority`` — an explicit ``name`` order that wins
      over :meth:`MetadataProviderPlugin.get_priority`; a provider absent from
      the list keeps its own priority and sorts after every listed provider.

    ``config=None`` (the default) preserves the original behavior exactly —
    every provider is priority-ordered by its own ``get_priority()`` and
    gated only by its own ``is_enabled()``.
    """

    def __init__(self, config: Any = None):
        self.providers: Dict[str, MetadataProviderPlugin] = {}
        self.priority_order: List[str] = []
        self.config = config

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
        self._update_priority_order()  # config's priority list can change between calls
        return [self.providers[name] for name in self.priority_order
                if name in self.providers]

    def get_enabled(self) -> List[MetadataProviderPlugin]:
        """Get enabled providers in priority order.

        Applies the config gates documented on the class, then each
        provider's own :meth:`MetadataProviderPlugin.is_enabled` (e.g. an
        empty API key) — a provider must pass both to be consulted.
        """
        if self.config is not None and not getattr(self.config, "metadata_enabled", True):
            logger.debug("metadata_enabled=False — no metadata provider will be consulted")
            return []

        allowed: Optional[set] = None
        if self.config is not None:
            raw = getattr(self.config, "metadata_enabled_providers", None)
            if raw:
                allowed = set(raw)

        return [
            p for p in self.get_all()
            if (allowed is None or p.name in allowed) and p.is_enabled()
        ]

    def _effective_priority(self, name: str, provider: MetadataProviderPlugin) -> tuple[int, int]:
        """Sort key: config's explicit order first, provider's own priority as tiebreak.

        A provider named in ``config.metadata_provider_priority`` sorts by its
        (0-based) position in that list, ahead of every unlisted provider;
        unlisted providers keep relative order via their own ``get_priority()``.
        """
        priority_list: List[str] = []
        if self.config is not None:
            priority_list = list(getattr(self.config, "metadata_provider_priority", None) or [])
        if name in priority_list:
            return (priority_list.index(name), provider.get_priority())
        return (len(priority_list), provider.get_priority())

    def _update_priority_order(self):
        """Sort providers by config priority override, then own priority (lower = higher)."""
        items = list(self.providers.items())
        items.sort(key=lambda x: self._effective_priority(x[0], x[1]))
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

        Session hygiene: the DB is touched in two short, separate scopes — a
        read (channel identity + cache check) BEFORE any network call, and a
        write (persist the merged result) only AFTER every provider network
        call has returned. No session is held open while awaiting
        ``provider.get_details()`` — those calls are unbounded network I/O and
        holding a session (with `database.py`'s single-writer SQLite) across
        them starved concurrent bulk writers (a Migration Center pass) of the
        write lock long enough to exceed the 30s busy_timeout (owner log
        2026-08-01). See docs/CRITICAL_RULES.md#database-sessions.

        Args:
            channel_id: Channel ID to fetch metadata for
            force_refresh: If True, bypass cache and fetch fresh data

        Returns:
            MetadataResult with merged data from all providers, or None
        """
        logger.debug(f"=== get_metadata called for channel_id={channel_id}, force_refresh={force_refresh}")
        try:
            lookup = self._load_channel_for_metadata(channel_id, force_refresh)
        except Exception as e:
            logger.error(f"Error reading channel for metadata fetch {channel_id}: {e}", exc_info=True)
            return None
        if lookup is None:
            return None
        cached_result, stale_result, ch_name, ch_media_type = lookup
        if cached_result is not None:
            logger.debug(f"Using cached metadata for {ch_name}")
            return cached_result

        # ── Network phase: NO DB session open for the duration of this loop ──
        result = MetadataResult()
        providers_tried = []

        logger.debug(f"Trying {len(self.registry.get_enabled())} enabled providers for {ch_name}")

        for provider in self.registry.get_enabled():
            # Skip if not supported for this media type
            if ch_media_type not in provider.supported_media_types:
                logger.debug(f"Skipping {provider.name}: doesn't support {ch_media_type}")
                continue

            # Rate limit check
            if not await self._check_rate_limit(provider.name):
                logger.debug(f"Rate limit reached for {provider.name}, skipping")
                continue

            try:
                logger.debug(f"Fetching metadata from {provider.name} for {ch_name}")

                # Fetch from provider (network I/O — deliberately no session open here)
                partial = await provider.get_details(
                    channel_id,
                    media_type=ch_media_type
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
        if not (result.title or result.plot or result.poster_url):
            # The refetch came back empty. That is a statement about the
            # PROVIDERS, not about the title — so if we already had something
            # stored, keep showing it rather than reporting the title has no
            # metadata. Returning None here is what left a details pane blank
            # beside a results row that was still rendering the poster.
            if stale_result is not None:
                logger.debug(f"Refetch returned nothing for {ch_name} — keeping stored metadata")
                return stale_result
            logger.debug(f"No metadata found for {ch_name}")
            return None

        try:
            stored = self._persist_metadata_cache(
                channel_id, result, providers_tried, ch_name
            )
        except Exception as e:
            logger.error(f"Error saving metadata for {channel_id}: {e}", exc_info=True)
            return result
        # Return what is NOW STORED, not the raw provider merge: the write
        # deliberately keeps fields the refetch did not supply (see
        # ``_fill_if_present``), so the stored row is the complete picture and
        # the raw result is only the part that came back this time. Returning
        # the latter would show a details pane less than the database holds.
        return stored if stored is not None else result

    def _load_channel_for_metadata(
        self, channel_id: str, force_refresh: bool
    ) -> Optional[Tuple[Optional[MetadataResult], Optional[MetadataResult], str, str]]:
        """Read-only lookup: channel name/media_type + cached metadata, own short scope.

        Runs in its own ``session_scope(commit=False)`` that closes before
        this method returns — the caller (``get_metadata``) performs any
        network fetch strictly AFTER this session is gone, never inside it.

        Args:
            channel_id: Channel ID to look up.
            force_refresh: If True, skip the cache check (still reads identity).

        Returns:
            ``None`` when the channel doesn't exist. Otherwise
            ``(fresh_or_None, stale_or_None, channel_name, media_type)``.

            A non-None FIRST element means the cache was fresh and the caller
            should return it directly without any network fetch. A non-None
            SECOND element means there is stored metadata that has aged past
            its TTL: the caller refetches, but keeps this to fall back on and
            to fill whatever the refetch fails to return. Losing that was the
            bug — a stale row was simply discarded, so a refetch that returned
            less than we already knew showed the user nothing.
        """
        with self.db.session_scope(commit=False) as session:
            logger.debug(f"Querying for channel {channel_id}...")
            channel = session.query(ChannelDB).filter_by(id=channel_id).first()

            if not channel:
                logger.warning(f"Channel not found: {channel_id}")
                return None

            logger.debug(f"Found channel: {channel.name}")
            ch_name = channel.name
            ch_media_type = channel.media_type

            cached_result = None
            stale_result = None
            if channel.metadata_id:
                cached = self._get_cached_metadata(session, channel.metadata_id)
                if cached:
                    stored = self._metadata_db_to_result(cached)
                    if force_refresh or self._is_stale(cached):
                        stale_result = stored
                    else:
                        cached_result = stored

            return (cached_result, stale_result, ch_name, ch_media_type)

    def _persist_metadata_cache(
        self, channel_id: str, result: MetadataResult,
        providers_tried: List[str], ch_name: str,
    ) -> Optional[MetadataResult]:
        """Write phase: open a fresh session only AFTER all network I/O is done.

        Re-queries the channel in this new session (the one from
        ``_load_channel_for_metadata`` is long closed) — a channel deleted
        between the read and this write is logged and skipped rather than
        raising.

        Args:
            channel_id: Channel ID to persist metadata for.
            result: The merged provider result to cache.
            providers_tried: Provider names that contributed data (for logging).
            ch_name: Channel display name (for logging only).

        Returns:
            The row as it stands AFTER the write, mapped to a ``MetadataResult``
            inside the session (ORM objects must not outlive it — CLAUDE.md),
            or ``None`` if the channel vanished. The caller returns this rather
            than its own ``result`` because the write preserves fields the
            refetch did not supply.
        """
        with self.db.session_scope() as session:
            channel = session.query(ChannelDB).filter_by(id=channel_id).first()
            if not channel:
                logger.warning(
                    f"Channel disappeared before metadata cache write: {channel_id}"
                )
                return None
            self._save_metadata_cache(session, channel, result)
            stored_row = self._get_cached_metadata(session, channel.metadata_id)
            stored = self._metadata_db_to_result(stored_row) if stored_row else None
        logger.info(f"Cached metadata for {ch_name} from: {', '.join(providers_tried)}")
        return stored
    
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
    
    @staticmethod
    def _derive_year(year: int | None, release_date: str | None) -> int | None:
        """Return year, falling back to the first 4 chars of release_date if year is absent.

        Called at ingestion (before writing to DB) and at read time (for rows cached before
        the ingestion fix landed). After this runs, callers read .year directly — no runtime
        derivation anywhere else.
        """
        if year:
            return year
        if release_date:
            try:
                return int(release_date[:4])
            except (ValueError, IndexError):
                pass
        return None

    def _metadata_db_to_result(self, metadata: MetadataDB) -> MetadataResult:
        """Convert MetadataDB to MetadataResult"""
        return MetadataResult(
            title=metadata.title,
            year=self._derive_year(metadata.year, metadata.release_date),
            plot=metadata.plot,
            tagline=metadata.tagline,

            poster_url=metadata.poster_url,
            backdrop_url=metadata.backdrop_url,

            cast=metadata.cast or [],
            crew=metadata.crew or [],
            director=metadata.director,

            genres=metadata.genres or [],
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
    
    @staticmethod
    def _fill_if_present(metadata: MetadataDB, field: str, value) -> None:
        """Write *value* onto *metadata.field* only when it carries information.

        "Carries information" means not ``None`` and not an empty
        string/list — an empty list from a provider that returned no cast is
        the same statement as "I don't know", and it must not overwrite a cast
        we already have. ``0`` and ``False`` are kept: a rating of 0 or a
        runtime of 0 is a real answer, so the test is explicitly against
        ``None``/empty-container rather than plain falsiness.
        """
        if value is None:
            return
        if isinstance(value, (str, list, tuple, dict)) and len(value) == 0:
            return
        setattr(metadata, field, value)

    def _save_metadata_cache(self, session, channel: ChannelDB, result: MetadataResult):
        """Save metadata result to cache"""
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
            
            # Update fields — FILLING IN, never blanking out.
            #
            # Every assignment here used to be unconditional, which turned a
            # thin refetch into DATA LOSS. The path: a cached row ages past its
            # TTL (30 days, 90 for old content), so the next time its details
            # pane opens, ``get_metadata`` skips the cache and re-runs the
            # provider chain. If that chain now returns less than it did the
            # first time — a provider disabled, an API key removed, a title the
            # provider no longer matches, a rate limit — the result still has
            # *something* (a title is enough to pass the save gate), and every
            # field it lacks was written back as ``None`` OVER a perfectly good
            # stored value. The user watched a poster that was visible in the
            # results row report "No poster available" in the details pane
            # (owner report, 2026-08-23), and the row would have followed on the
            # next reload.
            #
            # A refetch that learns less than we already knew is not new
            # information, so it does not get to erase old information. Fresh
            # values always win; absent ones leave what is there alone. A
            # deliberate wipe belongs in an explicit "clear metadata" action,
            # not as a silent side effect of opening a details pane.
            _keep = self._fill_if_present

            _keep(metadata, "title", result.title)
            _keep(metadata, "year", self._derive_year(result.year, result.release_date))
            _keep(metadata, "plot", result.plot)
            _keep(metadata, "tagline", result.tagline)

            _keep(metadata, "poster_url", result.poster_url)
            _keep(metadata, "backdrop_url", result.backdrop_url)

            _keep(metadata, "cast", result.cast)
            _keep(metadata, "crew", result.crew)
            _keep(metadata, "genres", result.genres)

            _keep(metadata, "director", result.director)
            _keep(metadata, "content_rating", result.content_rating)

            _keep(metadata, "rating", result.rating)
            _keep(metadata, "rating_count", result.rating_count)

            _keep(metadata, "runtime", result.runtime)
            _keep(metadata, "release_date", result.release_date)

            _keep(metadata, "trailer_url", result.trailer_url)
            _keep(metadata, "imdb_id", result.imdb_id)
            _keep(metadata, "tmdb_id", result.tmdb_id)

            # Provenance and freshness are always overwritten: they describe THIS
            # fetch, not the content. Stamping fetched_at is what stops the row
            # from being re-fetched on every single selection once it goes stale.
            metadata.source = result.provider_name
            metadata.fetched_at = datetime.now()
            
            logger.debug(f"Committing metadata for {channel.name}")
            session.commit()
            logger.debug(f"Successfully saved metadata for {channel.name}")
            
        except Exception as e:
            logger.error(f"Failed to save metadata cache for {channel.name}: {type(e).__name__}: {e}", exc_info=True)
            session.rollback()
            raise  # Re-raise to see the full error in the outer handler
