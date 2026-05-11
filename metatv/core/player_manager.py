"""Player manager facade for simple player operations"""

from typing import Optional
from loguru import logger

from metatv.core.config import Config
from metatv.core.players.base import PlayerPlugin, QueueMode
from metatv.core.players.mpv import MPVPlayer


class PlayerManager:
    """Facade for managing media player operations"""
    
    def __init__(self, config: Config):
        """Initialize player manager
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.player: Optional[PlayerPlugin] = None
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
    
    def play(self, url: str, title: str) -> bool:
        """Play a URL
        
        Args:
            url: Stream URL to play
            title: Title to display
            
        Returns:
            True if successful, False otherwise
        """
        if not self.player:
            logger.error("No player available")
            return False
        
        return self.player.play(url, title)
    
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
    
    def cleanup(self):
        """Cleanup player resources"""
        if self.player:
            self.player.cleanup()
            logger.info("Player manager cleanup complete")
