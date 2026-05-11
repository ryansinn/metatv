"""Provider factory and registry"""

from typing import Dict, Type, Optional
from loguru import logger

from metatv.providers.base import ProviderPlugin
from metatv.providers.xtream import XtreamProvider


class ProviderRegistry:
    """Registry of available provider plugins"""
    
    _providers: Dict[str, Type[ProviderPlugin]] = {}
    
    @classmethod
    def register(cls, provider_type: str, provider_class: Type[ProviderPlugin]):
        """Register a provider plugin
        
        Args:
            provider_type: Type identifier (e.g., 'xtream', 'm3u')
            provider_class: Provider class implementing ProviderPlugin
        """
        cls._providers[provider_type] = provider_class
        logger.debug(f"Registered provider: {provider_type} -> {provider_class.__name__}")
    
    @classmethod
    def get_provider(cls, provider_type: str) -> Optional[ProviderPlugin]:
        """Get a provider instance by type
        
        Args:
            provider_type: Type identifier
        
        Returns:
            Provider plugin instance, or None if not found
        """
        provider_class = cls._providers.get(provider_type)
        if provider_class:
            return provider_class()
        else:
            logger.warning(f"Unknown provider type: {provider_type}")
            return None
    
    @classmethod
    def list_providers(cls) -> Dict[str, str]:
        """List all registered providers
        
        Returns:
            Dictionary mapping provider_type to provider name
        """
        return {
            ptype: pcls().name 
            for ptype, pcls in cls._providers.items()
        }
    
    @classmethod
    def is_registered(cls, provider_type: str) -> bool:
        """Check if a provider type is registered"""
        return provider_type in cls._providers


# Register built-in providers
ProviderRegistry.register('xtream', XtreamProvider)


def get_provider(provider_type: str) -> Optional[ProviderPlugin]:
    """Convenience function to get a provider instance
    
    Args:
        provider_type: Type identifier (e.g., 'xtream')
    
    Returns:
        Provider plugin instance, or None if not found
    """
    return ProviderRegistry.get_provider(provider_type)
