"""Connection tracking for provider URLs"""

import asyncio
from datetime import datetime
from typing import Optional
from loguru import logger
import aiohttp

from metatv.core.models import ProviderURL, ConnectionAttempt


class ConnectionTracker:
    """Track connection success/failure for provider URLs"""
    
    @staticmethod
    async def get_client_ip() -> Optional[str]:
        """Get client's public IP address"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.ipify.org?format=text', timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        return await response.text()
        except Exception as e:
            logger.debug(f"Could not fetch client IP: {e}")
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
        
        logger.info(f"Connection success: {provider_url.url} from IP {client_ip} (score: {provider_url.reliability_score:.1f}%)")
    
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
        
        # Check if this IP appears blocked
        if client_ip and provider_url.is_ip_blocked(client_ip):
            logger.warning(
                f"Connection failure: {provider_url.url} from IP {client_ip} - "
                f"POSSIBLY BLOCKED ({provider_url.get_ip_failure_count(client_ip)} failures) - {error_message}"
            )
        else:
            logger.warning(
                f"Connection failure: {provider_url.url} from IP {client_ip} - {error_message} "
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
