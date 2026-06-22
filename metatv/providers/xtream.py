"""Xtream API client implementation"""

import asyncio
from typing import List, Dict, Optional, Any, Tuple
from urllib.parse import urljoin
import aiohttp
from loguru import logger

from metatv.core.models import Channel, Provider, MediaType, StreamQuality, ProviderURL
from metatv.core.connection_tracker import ConnectionTracker
from metatv.providers.base import ProviderPlugin


# Headers that pass Cloudflare's bot-detection (HTTP 520 / 403 without these).
# Single source of truth lives in metatv.core.http_headers; re-exported here
# under the legacy name so existing importers keep working unchanged.
from metatv.core.http_headers import STREAM_HTTP_HEADERS as _DEFAULT_HEADERS

# Timeout for bulk catalog reads (get_*_streams / get_*_categories).
#
# These responses can be tens of megabytes and a slow-but-healthy server may take
# minutes to stream one (observed: an 18 MB live list at ~227 KB/s = 81 s). A `total`
# deadline punishes that — it conflates "the server is dead" with "the server is slow
# but still sending" and silently drops the whole catalog, leaving the provider with 0
# channels. We use `sock_read` instead: it fires only when *no bytes arrive* for the
# window, so a steady trickle never trips it while a genuinely stalled connection still
# does. Deliberately NO `total` — large catalogs on slow servers legitimately run long.
_CONTENT_READ_TIMEOUT = aiohttp.ClientTimeout(sock_connect=15, sock_read=60)


class XtreamAPI:
    """Xtream Codes API client"""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=_DEFAULT_HEADERS)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _build_url(self, action: str, **params) -> str:
        """Build API URL with authentication"""
        base_params = {
            'username': self.username,
            'password': self.password,
        }
        base_params.update(params)
        
        # Build query string
        query_parts = [f"{k}={v}" for k, v in base_params.items() if v is not None]
        query_string = "&".join(query_parts)
        
        return f"{self.base_url}/player_api.php?action={action}&{query_string}"
    
    async def test_connection(self, provider_url: Optional[ProviderURL] = None) -> tuple[bool, Optional[str]]:
        """Test connection and authentication.

        Checks the auth endpoint first to surface account-level errors (expired,
        banned, etc.) before hitting a content endpoint.

        Args:
            provider_url: Optional ProviderURL to track statistics

        Returns:
            (success, error_message)
        """
        from time import time
        from datetime import datetime
        start_time = time()

        try:
            # Step 1: hit the auth endpoint — gives us account status + server info
            auth_url = f"{self.base_url}/player_api.php?username={self.username}&password={self.password}"
            async with self.session.get(auth_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response_time_ms = int((time() - start_time) * 1000)

                if response.status != 200:
                    error_msg = f"HTTP {response.status}"
                    if provider_url:
                        await ConnectionTracker.record_failure(provider_url, error_msg)
                    return False, error_msg

                data = await response.json(content_type=None)
                if not isinstance(data, dict):
                    error_msg = "Unexpected auth response format"
                    if provider_url:
                        await ConnectionTracker.record_failure(provider_url, error_msg)
                    return False, error_msg

                user_info = data.get("user_info", {})
                status = user_info.get("status", "")
                auth = user_info.get("auth", 0)

                if not auth:
                    error_msg = "Authentication failed — check username and password"
                    if provider_url:
                        await ConnectionTracker.record_failure(provider_url, error_msg)
                    return False, error_msg

                if status and status.lower() not in ("active", ""):
                    # Expired / Banned / Disabled — give a human-readable message
                    exp_ts = user_info.get("exp_date")
                    exp_str = ""
                    if exp_ts:
                        try:
                            exp_str = f" (expired {datetime.fromtimestamp(int(exp_ts)).strftime('%Y-%m-%d')})"
                        except Exception:
                            pass
                    error_msg = f"Account {status}{exp_str}"
                    if provider_url:
                        await ConnectionTracker.record_failure(provider_url, error_msg)
                    return False, error_msg

            if provider_url:
                await ConnectionTracker.record_success(provider_url, response_time_ms)
            return True, None

        except asyncio.TimeoutError:
            error_msg = "Connection timeout"
            if provider_url:
                await ConnectionTracker.record_failure(provider_url, error_msg)
            return False, error_msg
        except aiohttp.ClientError as e:
            error_msg = f"Connection error: {str(e)}"
            if provider_url:
                await ConnectionTracker.record_failure(provider_url, error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            if provider_url:
                await ConnectionTracker.record_failure(provider_url, error_msg)
            return False, error_msg
    
    async def get_server_info(self) -> Optional[Dict[str, Any]]:
        """Get server information"""
        try:
            url = f"{self.base_url}/player_api.php?username={self.username}&password={self.password}"
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    return await response.json(content_type=None)
        except Exception as e:
            logger.error(f"Failed to get server info: {e}")
        return None

    async def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Fetch and parse account/subscription info from the auth endpoint.

        Returns a dict with keys: status, exp_date, created_at, active_cons,
        max_connections, auth — or None on failure.
        """
        data = await self.get_server_info()
        if not data or not isinstance(data, dict):
            return None
        user_info = data.get("user_info", {})
        if not user_info:
            return None
        return {
            "status": user_info.get("status", "Unknown"),
            "auth": user_info.get("auth", 0),
            "exp_date": user_info.get("exp_date"),       # Unix timestamp string
            "created_at": user_info.get("created_at"),   # Unix timestamp string
            "active_cons": int(user_info.get("active_cons", 0) or 0),
            "max_connections": int(user_info.get("max_connections", 1) or 1),
            "is_trial": user_info.get("is_trial", "0") == "1",
            "server_info": data.get("server_info", {}),
        }
    
    async def get_live_categories(self) -> List[Dict[str, Any]]:
        """Get live TV categories"""
        return await self._get_categories("get_live_categories")
    
    async def get_vod_categories(self) -> List[Dict[str, Any]]:
        """Get VOD categories"""
        return await self._get_categories("get_vod_categories")
    
    async def get_series_categories(self) -> List[Dict[str, Any]]:
        """Get series categories"""
        return await self._get_categories("get_series_categories")
    
    async def _get_categories(self, action: str) -> List[Dict[str, Any]]:
        """Generic category fetcher. Raises aiohttp.ClientError on connection failure."""
        url = self._build_url(action)
        try:
            async with self.session.get(url, timeout=_CONTENT_READ_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) else []
                logger.error(f"Failed to get categories ({action}): HTTP {response.status}")
                return []
        except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.error(f"Failed to get categories ({action}): {e}")
            return []
    
    async def get_live_streams(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get live TV streams"""
        return await self._get_streams("get_live_streams", category_id)
    
    async def get_vod_streams(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get VOD streams"""
        return await self._get_streams("get_vod_streams", category_id)
    
    async def get_series(self, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get series"""
        return await self._get_streams("get_series", category_id)
    
    async def get_series_info(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed series information including seasons and episodes
        
        Args:
            series_id: The series ID
            
        Returns:
            Dictionary with 'info', 'seasons', and 'episodes' keys
        """
        try:
            url = self._build_url("get_series_info", series_id=series_id)
            logger.debug(f"Fetching series info from: {url}")
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"Series info response type: {type(data)}")
                    if isinstance(data, dict):
                        logger.debug(f"Series info keys: {data.keys()}")
                    else:
                        logger.warning(f"Expected dict, got {type(data)}: {data[:2] if isinstance(data, list) else data}")
                    return data
        except Exception as e:
            logger.error(f"Failed to get series info for {series_id}: {e}")
        return None
    
    async def _get_streams(self, action: str, category_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generic stream fetcher. Raises aiohttp.ClientError on connection failure."""
        params = {}
        if category_id:
            params['category_id'] = category_id

        url = self._build_url(action, **params)
        try:
            async with self.session.get(url, timeout=_CONTENT_READ_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) else []
                logger.error(f"Failed to get streams ({action}): HTTP {response.status}")
                return []
        except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError):
            raise  # Let caller handle connection failures for URL cycling
        except Exception as e:
            logger.error(f"Failed to get streams ({action}): {e}")
            return []
    
    def convert_to_channel(self, raw_data: Dict[str, Any], provider_id: str, media_type: str,
                           category_map: Optional[Dict[str, str]] = None) -> Channel:
        """Convert Xtream API data to Channel model.

        ``category_map`` resolves the provider's numeric ``category_id`` to its
        human category *name* (built per provider + media type at fetch time —
        the streams endpoints carry only the id; the names live in
        ``get_*_categories``). When omitted, falls back to any inline name.
        """
        
        # Generate stream URL
        stream_id = raw_data.get('stream_id') or raw_data.get('series_id')
        extension = raw_data.get('container_extension', 'ts')
        
        if media_type == MediaType.LIVE:
            stream_url = f"{self.base_url}/live/{self.username}/{self.password}/{stream_id}.{extension}"
        elif media_type == MediaType.MOVIE:
            stream_url = f"{self.base_url}/movie/{self.username}/{self.password}/{stream_id}.{extension}"
        else:
            stream_url = f"{self.base_url}/series/{self.username}/{self.password}/{stream_id}.{extension}"
        
        # Determine quality
        name = raw_data.get('name', '')
        quality = StreamQuality.UNKNOWN
        if 'UHD' in name or '4K' in name:
            quality = StreamQuality.UHD
        elif 'FHD' in name or '1080' in name:
            quality = StreamQuality.FHD
        elif 'HD' in name or '720' in name:
            quality = StreamQuality.HD
        elif 'SD' in name:
            quality = StreamQuality.SD
        
        # Resolve the provider's category NAME from its id via category_map (the
        # join the streams endpoint can't do — it carries only the id). Fall back
        # to any inline name, then empty (no regression if the categories call
        # failed). The id is provider-/type-local, never a global key.
        category_id = str(raw_data.get('category_id', ''))
        category_name = (category_map or {}).get(category_id) or raw_data.get('category_name', '') or ''

        return Channel(
            id=f"{provider_id}_{stream_id}",
            source_id=str(stream_id),
            provider_id=provider_id,
            name=name,
            stream_url=stream_url,
            category=category_name,
            category_id=category_id,
            logo_url=raw_data.get('stream_icon'),
            epg_channel_id=raw_data.get('epg_channel_id'),
            media_type=media_type,
            quality=quality,
            raw_data=raw_data
        )


class XtreamProvider(ProviderPlugin):
    """Xtream Codes provider plugin implementation"""
    
    @property
    def name(self) -> str:
        return "Xtream Codes"
    
    @property
    def provider_type(self) -> str:
        return "xtream"
    
    async def test_connection(self, url: str, username: Optional[str] = None, 
                            password: Optional[str] = None, **kwargs) -> Tuple[bool, Optional[str]]:
        """Test connection to Xtream provider"""
        async with XtreamAPI(url, username, password) as api:
            return await api.test_connection()
    
    async def fetch_channels(self, provider: Provider,
                           progress_callback: Optional[callable] = None) -> List[Channel]:
        """Fetch all channels, cycling through alternate URLs on connection failure."""
        urls_to_try = provider.ordered_urls()
        last_error: Optional[str] = None

        for idx, base_url in enumerate(urls_to_try):
            label = f"URL {idx + 1}/{len(urls_to_try)}: {base_url}"
            if progress_callback:
                progress_callback(5, 100, f"Connecting ({label})…")
            logger.info(f"Refresh attempt {label}")

            try:
                channels = await self._fetch_from_base(
                    base_url, provider, progress_callback
                )
                # Record success on the matching ProviderURL object
                for pu in provider.urls:
                    if pu.url.rstrip('/') == base_url.rstrip('/'):
                        pu.success_count += 1
                        break
                return channels

            except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = str(e)
                logger.warning(f"Connection failed for {base_url}: {e}")
                # Record failure on the matching ProviderURL object
                for pu in provider.urls:
                    if pu.url.rstrip('/') == base_url.rstrip('/'):
                        pu.failure_count += 1
                        break
                if idx < len(urls_to_try) - 1:
                    logger.info("Trying next URL…")
                continue

        logger.error(f"All {len(urls_to_try)} URL(s) failed for provider '{provider.name}'. Last error: {last_error}")
        return []


    async def _fetch_from_base(self, base_url: str, provider: Provider,
                               progress_callback: Optional[callable]) -> List[Channel]:
        """Fetch all channel types from a single base URL. Raises on connection error."""
        async with XtreamAPI(base_url, provider.username, provider.password) as api:
            channels: List[Channel] = []

            # Resolve category id→name up front: the streams endpoints carry only
            # category_id; the human names live in get_*_categories. Maps are per
            # media type (live/vod/series ids are separate namespaces) and per
            # provider (ids are provider-local). A failed call → empty map → the
            # category stays blank, exactly as before (no regression).
            def _cat_map(cats: List[Dict[str, Any]]) -> Dict[str, str]:
                return {
                    str(c.get('category_id', '')): c.get('category_name', '')
                    for c in cats if c.get('category_id') is not None
                }

            if progress_callback:
                progress_callback(8, 100, "Fetching categories…")
            live_cats = _cat_map(await api.get_live_categories())
            vod_cats = _cat_map(await api.get_vod_categories())
            series_cats = _cat_map(await api.get_series_categories())

            if progress_callback:
                progress_callback(10, 100, "Fetching live channels…")
            for stream in await api.get_live_streams():
                channels.append(api.convert_to_channel(stream, provider.id, MediaType.LIVE, live_cats))

            if progress_callback:
                progress_callback(40, 100, "Fetching VOD content…")
            for stream in await api.get_vod_streams():
                channels.append(api.convert_to_channel(stream, provider.id, MediaType.MOVIE, vod_cats))

            if progress_callback:
                progress_callback(70, 100, "Fetching series…")
            for series in await api.get_series():
                channels.append(api.convert_to_channel(series, provider.id, MediaType.SERIES, series_cats))

            if progress_callback:
                progress_callback(100, 100, f"Loaded {len(channels):,} channels")

            return channels
    
    async def get_categories(self, provider: Provider) -> List[Dict[str, Any]]:
        """Get all categories, cycling through URLs on connection failure."""
        for base_url in provider.ordered_urls():
            try:
                async with XtreamAPI(base_url, provider.username, provider.password) as api:
                    categories: List[Dict[str, Any]] = []
                    categories.extend(await api.get_live_categories())
                    categories.extend(await api.get_vod_categories())
                    categories.extend(await api.get_series_categories())
                    return categories
            except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"get_categories: {base_url} failed: {e}, trying next…")
        logger.error(f"get_categories: all URLs failed for provider '{provider.name}'")
        return []

    async def fetch_series_info(self, provider: Provider, series_id: str) -> Optional[Dict[str, Any]]:
        """Fetch series info, cycling through URLs on connection failure."""
        for base_url in provider.ordered_urls():
            try:
                async with XtreamAPI(base_url, provider.username, provider.password) as api:
                    result = await api.get_series_info(series_id)
                    if result is not None:
                        return result
            except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"fetch_series_info: {base_url} failed: {e}, trying next…")
        logger.error(f"fetch_series_info: all URLs failed for provider '{provider.name}'")
        return None

    async def get_server_info(self, provider: Provider) -> Optional[Dict[str, Any]]:
        """Get server info, cycling through URLs on connection failure."""
        for base_url in provider.ordered_urls():
            try:
                async with XtreamAPI(base_url, provider.username, provider.password) as api:
                    result = await api.get_server_info()
                    if result is not None:
                        return result
            except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"get_server_info: {base_url} failed: {e}, trying next…")
        logger.error(f"get_server_info: all URLs failed for provider '{provider.name}'")
        return None

    async def fetch_account_info(self, provider: Provider) -> Optional[Dict[str, Any]]:
        """Fetch parsed account/subscription info, cycling through URLs on failure."""
        for base_url in provider.ordered_urls():
            try:
                async with XtreamAPI(base_url, provider.username, provider.password) as api:
                    result = await api.get_account_info()
                    if result is not None:
                        return result
            except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"fetch_account_info: {base_url} failed: {e}, trying next…")
        logger.error(f"fetch_account_info: all URLs failed for provider '{provider.name}'")
        return None
