"""Player manager facade for simple player operations"""

from typing import Optional, List
from loguru import logger
import subprocess

from metatv.core.config import Config
from metatv.core.players.base import PlayerPlugin, QueueMode
from metatv.core.players.mpv import MPVPlayer


class PlayerManager:
    """Facade for managing media player operations with instance limit enforcement"""
    
    def __init__(self, config: Config):
        """Initialize player manager
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.player: Optional[PlayerPlugin] = None
        self.running_instances: List[subprocess.Popen] = []  # Track all player processes
        self._initialize_player()
    
    def _initialize_player(self):
        """Initialize the appropriate player based on configuration"""
        # For now, only MPV is supported
        # Future: Add VLC, ffplay, etc.
        
        mpv = MPVPlayer(self.config)
        if mpv.is_available():
            self.player = mpv
            logger.info(f"Initialized player: {self.player.name}")
        else:
            logger.error("No media player available! Please install mpv.")
            self.player = None
    
    def is_available(self) -> bool:
        """Check if a player is available
        
        Returns:
            True if player is available, False otherwise
        """
        return self.player is not None and self.player.is_available()
    
    def get_player_name(self) -> Optional[str]:
        """Get name of current player
        
        Returns:
            Player name or None if no player available
        """
        return self.player.name if self.player else None
    
    def play(self, url: str, title: str, provider_max_connections: int = 1) -> bool:
        """Play a URL with instance limit enforcement
        
        Args:
            url: Stream URL to play
            title: Title to display
            provider_max_connections: Max connections allowed by provider
            
        Returns:
            True if successful, False otherwise
        """
        if not self.player:
            logger.error("No player available")
            return False
        
        # Clean up dead processes
        self._cleanup_dead_instances()
        
        # Determine effective max instances
        max_instances = self._get_effective_max_instances(provider_max_connections)
        
        # Check if we've hit the limit
        if max_instances > 0 and len(self.running_instances) >= max_instances:
            logger.warning(
                f"Max player instances reached ({len(self.running_instances)}/{max_instances}). "
                f"Close existing players or increase max_player_instances in config."
            )
            return False
        
        # Play the stream
        result = self.player.play(url, title)
        
        # Track the instance if it's a new process
        if result and self.config.player_mode == "multiple-instances":
            # For multiple instances, we'd need to track each process
            # This is a simplified version - full implementation would require
            # returning the process from player.play() and tracking it here
            pass
        
        return result
    
    def queue(self, url: str, title: str, mode: QueueMode = QueueMode.APPEND_PLAY) -> bool:
        """Add URL to playlist queue
        
        Args:
            url: Stream URL to queue
            title: Title to display
            mode: How to add to queue
            
        Returns:
            True if successful, False otherwise
        """
        if not self.player:
            logger.error("No player available")
            return False
        
        return self.player.queue(url, title, mode)
    
    def stop(self) -> bool:
        """Stop playback
        
        Returns:
            True if successful, False otherwise
        """
        if not self.player:
            return False
        
        return self.player.stop()
    
    def is_running(self) -> bool:
        """Check if player is currently running
        
        Returns:
            True if player process is running
        """
        if not self.player:
            return False
        
        return self.player.is_running()
    
    def _get_effective_max_instances(self, provider_max_connections: int) -> int:
        """Calculate effective max instances based on config
        
        Args:
            provider_max_connections: Max connections from provider
            
        Returns:
            Effective max instances (0 = unlimited)
        """
        config_max = self.config.max_player_instances
        
        if config_max == -1:
            # Unlimited
            return 0
        elif config_max == 0:
            # Use provider's limit
            return provider_max_connections
        else:
            # Use config value
            return config_max
    
    def _cleanup_dead_instances(self):
        """Remove dead processes from tracking list"""
        self.running_instances = [p for p in self.running_instances if p.poll() is None]
    
    def get_active_instance_count(self) -> int:
        """Get number of currently running player instances
        
        Returns:
            Number of active player processes
        """
        self._cleanup_dead_instances()
        return len(self.running_instances)
    
    def cleanup(self):
        """Cleanup player resources"""
        if self.player:
            self.player.cleanup()
        
        # Cleanup tracked instances
        self._cleanup_dead_instances()
        logger.info("Player manager cleanup complete")
