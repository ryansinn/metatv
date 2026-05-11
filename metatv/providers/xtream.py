"""Xtream API client implementation"""

import asyncio
from typing import List, Dict, Optional, Any, Tuple
from urllib.parse import urljoin
import aiohttp
from loguru import logger

from metatv.core.models import Channel, Provider, MediaType, StreamQuality, ProviderURL
from metatv.core.connection_tracker import ConnectionTracker
from metatv.providers.base import ProviderPlugin


class XtreamAPI:
    """Xtream Codes API client"""
    
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
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
        """Test connection and authentication
        
        Args:
            provider_url: Optional ProviderURL to track statistics
        
        Returns:
            (success, error_message)
        """
        from time import time
        start_time = time()
        
        try:
            url = self._build_url("get_live_categories")
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response_time_ms = int((time() - start_time) * 1000)
                
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, list):
                        if provider_url:
                            await ConnectionTracker.record_success(provider_url, response_time_ms)
                        return True, None
                    else:
                        error_msg = "Invalid response format"
                        if provider_url:
                            await ConnectionTracker.record_failure(provider_url, error_msg)
                        return False, error_msg
                else:
                    error_msg = f"HTTP {response.status}"
                    if provider_url:
                        await ConnectionTracker.record_failure(provider_url, error_msg)
                    return False, error_msg
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
                    return await response.json()
        except Exception as e:
            logger.error(f"Failed to get server info: {e}")
        return None
    
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
        """Generic category fetcher"""
        try:
            url = self._build_url(action)
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) else []
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
        """Generic stream fetcher"""
        try:
            params = {}
            if category_id:
                params['category_id'] = category_id
            
            url = self._build_url(action, **params)
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"Failed to get streams ({action}): {e}")
        return []
    
    def convert_to_channel(self, raw_data: Dict[str, Any], provider_id: str, media_type: str) -> Channel:
        """Convert Xtream API data to Channel model"""
        
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
        
        return Channel(
            id=f"{provider_id}_{stream_id}",
            source_id=str(stream_id),
            provider_id=provider_id,
            name=name,
            stream_url=stream_url,
            category=raw_data.get('category_name', ''),
            category_id=str(raw_data.get('category_id', '')),
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
        """Fetch all channels from Xtream provider"""
        async with XtreamAPI(provider.url, provider.username, provider.password) as api:
            channels = []
            
            # Fetch live streams
            if progress_callback:
                progress_callback(10, 100, "Fetching live channels...")
            live_streams = await api.get_live_streams()
            for stream in live_streams:
                channel = api.convert_to_channel(stream, provider.id, MediaType.LIVE)
                channels.append(channel)
            
            # Fetch VOD
            if progress_callback:
                progress_callback(40, 100, "Fetching VOD content...")
            vod_streams = await api.get_vod_streams()
            for stream in vod_streams:
                channel = api.convert_to_channel(stream, provider.id, MediaType.MOVIE)
                channels.append(channel)
            
            # Fetch series
            if progress_callback:
                progress_callback(70, 100, "Fetching series...")
            series_list = await api.get_series()
            for series in series_list:
                channel = api.convert_to_channel(series, provider.id, MediaType.SERIES)
                channels.append(channel)
            
            if progress_callback:
                progress_callback(100, 100, f"Loaded {len(channels)} channels")
            
            return channels
    
    async def get_categories(self, provider: Provider) -> List[Dict[str, Any]]:
        """Get all categories from Xtream provider"""
        async with XtreamAPI(provider.url, provider.username, provider.password) as api:
            categories = []
            categories.extend(await api.get_live_categories())
            categories.extend(await api.get_vod_categories())
            categories.extend(await api.get_series_categories())
            return categories
    
    async def fetch_series_info(self, provider: Provider, series_id: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed series information including seasons and episodes"""
        async with XtreamAPI(provider.url, provider.username, provider.password) as api:
            return await api.get_series_info(series_id)
    
    async def get_server_info(self, provider: Provider) -> Optional[Dict[str, Any]]:
        """Get Xtream server information"""
        async with XtreamAPI(provider.url, provider.username, provider.password) as api:
            return await api.get_server_info()
