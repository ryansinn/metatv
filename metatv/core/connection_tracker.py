"""Connection tracking for provider URLs"""

from datetime import datetime
from typing import Optional
from loguru import logger

from metatv.core.models import ProviderURL, ConnectionAttempt


class ConnectionTracker:
    """Track connection success/failure for provider URLs"""
    
    @staticmethod
    async def get_client_ip() -> Optional[str]:
        """Always None. The public-IP lookup this used to do is gone.

        It fetched ``https://api.ipify.org`` — an HTTPS round-trip to a third
        party, on the failure path, telling that third party the user's address
        every time a provider URL misbehaved. It shipped in the initial commit
        and was never revisited.

        It is removed rather than fixed because the feature it fed never
        worked. ``ProviderURL.failed_client_ips`` counts failures per IP and
        ``is_ip_blocked`` reads that count — but of **280 recorded attempts in
        the owner's library, 280 have ``client_ip: null``**, so the dict is
        always empty and the check always False. Meanwhile ``url_cycle.py``,
        the actual chokepoint for URL cycling, documents that it deliberately
        does NOT route through this class precisely because of the ipify
        round-trip.

        So the app paid a privacy cost for a signal nothing ever read.

        The method is KEPT, returning None, so the two call sites and the
        stored JSON shape stay valid. If per-network failure detection is
        wanted later, store a salted hash of the address rather than the
        address: it answers "these failures are all on the network you are on
        now" without keeping anything identifying, which matters in a codebase
        that has already leaked credentials into shareable log files once.
        """
        return None
    
    @staticmethod
    async def record_success(provider_url: ProviderURL, response_time_ms: Optional[int] = None):
        """Record successful connection"""
        client_ip = await ConnectionTracker.get_client_ip()
        
        attempt = ConnectionAttempt(
            success=True,
            client_ip=client_ip,
            response_time_ms=response_time_ms
        )
        provider_url.add_attempt(attempt)
        
        provider_url.success_count += 1
        provider_url.last_success = datetime.now()
        provider_url.last_error = None
        
        logger.info(
            f"Connection success: {provider_url.url} "
            f"(score: {provider_url.reliability_score:.1f}%)"
        )
    
    @staticmethod
    async def record_failure(provider_url: ProviderURL, error_message: str):
        """Record failed connection"""
        client_ip = await ConnectionTracker.get_client_ip()
        
        attempt = ConnectionAttempt(
            success=False,
            client_ip=client_ip,
            error_message=error_message
        )
        provider_url.add_attempt(attempt)
        
        provider_url.failure_count += 1
        provider_url.last_failure = datetime.now()
        provider_url.last_error = error_message
        
        # The "is this IP blocked" branch is gone with the lookup that fed it:
        # client_ip is always None now, so it could never be taken. The
        # per-network signal it wanted is worth having — see get_client_ip's
        # note on hashing — but it needs building, not a dead branch pretending
        # to provide it.
        logger.warning(
            f"Connection failure: {provider_url.url} - {error_message} "
            f"(score: {provider_url.reliability_score:.1f}%)"
        )
    
    @staticmethod
    def reset_stats(provider_url: ProviderURL):
        """Reset connection statistics"""
        provider_url.success_count = 0
        provider_url.failure_count = 0
        provider_url.last_success = None
        provider_url.last_failure = None
        provider_url.last_error = None
        logger.info(f"Reset connection stats: {provider_url.url}")
    
    @staticmethod
    def get_best_url(urls: list[ProviderURL]) -> Optional[ProviderURL]:
        """Get the most reliable active URL
        
        Sorting priority:
        1. Active URLs only
        2. URLs with successful connections
        3. Highest reliability score
        4. Lowest priority number (manual priority)
        5. Most recent success
        """
        active_urls = [url for url in urls if url.is_active]
        
        if not active_urls:
            return None
        
        # Sort by reliability and priority
        sorted_urls = sorted(
            active_urls,
            key=lambda u: (
                -u.success_count if u.success_count > 0 else 0,  # Prefer tested URLs
                -u.reliability_score,  # Higher reliability
                u.priority,  # Lower priority number
                -(u.last_success.timestamp() if u.last_success else 0)  # More recent
            )
        )
        
        return sorted_urls[0] if sorted_urls else None
    
    @staticmethod
    def should_retry_failed_url(provider_url: ProviderURL, retry_after_minutes: int = 30) -> bool:
        """Determine if a failed URL should be retried
        
        Args:
            provider_url: The URL to check
            retry_after_minutes: Minutes to wait before retrying
        
        Returns:
            True if enough time has passed since last failure
        """
        if not provider_url.last_failure:
            return True
        
        minutes_since_failure = (datetime.now() - provider_url.last_failure).total_seconds() / 60
        return minutes_since_failure >= retry_after_minutes
