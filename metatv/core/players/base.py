"""Base player plugin interface"""

from abc import ABC, abstractmethod
from typing import Optional
from enum import Enum


class QueueMode(Enum):
    """Queue mode for adding items to playlist"""
    REPLACE = "replace"  # Replace current playlist
    APPEND = "append"  # Add to end of playlist
    APPEND_PLAY = "append-play"  # Add to end and play if nothing playing
    INSERT_NEXT = "insert-next"  # Insert after current item


class PlayerPlugin(ABC):
    """Abstract base class for media player plugins"""
    
    @abstractmethod
    def __init__(self, config):
        """Initialize player with configuration"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Player name"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if player is available on system"""
        pass
    
    @abstractmethod
    def play(self, url: str, title: str) -> bool:
        """Play a URL
        
        Args:
            url: Stream URL to play
            title: Title to display
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def queue(self, url: str, title: str, mode: QueueMode = QueueMode.APPEND_PLAY) -> bool:
        """Add URL to playlist queue
        
        Args:
            url: Stream URL to queue
            title: Title to display
            mode: How to add to queue
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def stop(self) -> bool:
        """Stop playback
        
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def is_running(self) -> bool:
        """Check if player is currently running
        
        Returns:
            True if player process is running
        """
        pass
    
    @abstractmethod
    def cleanup(self):
        """Cleanup resources (sockets, processes, etc.)"""
        pass
