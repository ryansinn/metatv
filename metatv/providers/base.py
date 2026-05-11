"""Provider plugin base class"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from metatv.core.models import Channel, Provider


class ProviderPlugin(ABC):
    """Base class for provider plugins"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name"""
        pass
    
    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider type identifier (e.g., 'xtream', 'm3u', 'plex')"""
        pass
    
    @abstractmethod
    async def test_connection(self, url: str, username: Optional[str] = None, 
                            password: Optional[str] = None, **kwargs) -> Tuple[bool, Optional[str]]:
        """Test connection to provider
        
        Returns:
            (success, error_message)
        """
        pass
    
    @abstractmethod
    async def fetch_channels(self, provider: Provider, 
                           progress_callback: Optional[callable] = None) -> List[Channel]:
        """Fetch all channels from provider
        
        Args:
            provider: Provider instance
            progress_callback: Optional callback(current, total, message)
        
        Returns:
            List of Channel objects
        """
        pass
    
    @abstractmethod
    async def get_categories(self, provider: Provider) -> List[Dict[str, Any]]:
        """Get available categories from provider
        
        Returns:
            List of category dictionaries
        """
        pass
    
    @abstractmethod
    async def fetch_series_info(self, provider: Provider, series_id: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed series information including seasons and episodes
        
        Args:
            provider: Provider instance
            series_id: Provider-specific series identifier
        
        Returns:
            Dictionary containing series info with seasons and episodes, or None if not found
            Expected structure:
            {
                'info': {...},  # Series metadata
                'seasons': [...],  # List of season dicts
                'episodes': [...]  # List of episode dicts or nested lists
            }
        """
        pass
    
    async def search_content(self, provider: Provider, query: str) -> List[Channel]:
        """Search for content (optional, default: not supported)
        
        Args:
            provider: Provider instance
            query: Search query string
        
        Returns:
            List of matching Channel objects
        """
        # Default implementation: not supported
        return []
    
    async def get_server_info(self, provider: Provider) -> Optional[Dict[str, Any]]:
        """Get server/provider information (optional)
        
        Returns:
            Dictionary with server info, or None if not supported
        """
        # Default implementation: not supported
        return None
