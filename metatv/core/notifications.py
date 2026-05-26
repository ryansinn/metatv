"""Notification system for background operations"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable
from uuid import uuid4

try:
    from PyQt6.QtCore import QTimer
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


class NotificationType(Enum):
    """Type of notification"""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    PROGRESS = "progress"


class NotificationPriority(Enum):
    """Notification priority"""
    LOW = 1
    NORMAL = 2
    HIGH = 3


@dataclass
class Notification:
    """Notification data"""
    
    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    message: str = ""
    type: NotificationType = NotificationType.INFO
    priority: NotificationPriority = NotificationPriority.NORMAL
    
    # Progress-specific
    progress: Optional[float] = None  # 0.0 to 1.0
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    estimated_time_remaining: Optional[int] = None  # seconds
    
    # Actions
    actions: list = field(default_factory=list)  # List of (label, callback)
    dismissible: bool = True
    auto_dismiss_seconds: Optional[int] = None
    
    # Grouping
    group_id: Optional[str] = None  # For grouping related notifications
    
    # State
    created_at: datetime = field(default_factory=datetime.now)
    is_collapsed: bool = False
    is_dismissed: bool = False


class NotificationManager:
    """Manages application notifications"""
    
    def __init__(self, max_visible: int = 3):
        self.notifications: list[Notification] = []
        self.max_visible = max_visible
        self.listeners: list[Callable] = []
        self.auto_dismiss_timers: dict = {}  # notification_id -> QTimer
    
    def add_listener(self, callback: Callable):
        """Add notification change listener"""
        self.listeners.append(callback)
    
    def remove_listener(self, callback: Callable):
        """Remove notification change listener"""
        if callback in self.listeners:
            self.listeners.remove(callback)
    
    def _notify_listeners(self):
        """Notify all listeners of changes"""
        for callback in self.listeners:
            callback(self.get_visible_notifications())
    
    def _setup_auto_dismiss(self, notification_id: str, seconds: int):
        """Set up auto-dismiss timer for a notification"""
        if not QT_AVAILABLE:
            return
        
        from loguru import logger
        
        # Cancel existing timer if any
        if notification_id in self.auto_dismiss_timers:
            self.auto_dismiss_timers[notification_id].stop()
            del self.auto_dismiss_timers[notification_id]
        
        # Create new timer
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._auto_dismiss_callback(notification_id))
        timer.start(int(seconds * 1000))
        self.auto_dismiss_timers[notification_id] = timer
        
        logger.debug(f"Auto-dismiss timer created for {notification_id}: {seconds}s")
    
    def _auto_dismiss_callback(self, notification_id: str):
        """Callback when auto-dismiss timer fires"""
        from loguru import logger
        logger.debug(f"Auto-dismiss timer fired for {notification_id}")
        self.dismiss(notification_id)
    
    def show(self, notification: Notification = None, **kwargs) -> str:
        """Show a notification
        
        Args:
            notification: Notification object OR
            **kwargs: title, message, type, auto_dismiss_ms, etc.
        
        Returns:
            notification_id
        """
        if notification is None:
            # Create notification from kwargs
            notif_type = kwargs.get('type', 'info')
            if isinstance(notif_type, str):
                notif_type = NotificationType(notif_type)
            
            auto_dismiss_ms = kwargs.get('auto_dismiss_ms')
            if 'auto_dismiss_seconds' in kwargs:
                auto_dismiss_seconds = kwargs['auto_dismiss_seconds']
            else:
                auto_dismiss_seconds = auto_dismiss_ms / 1000 if auto_dismiss_ms else None
            
            notification = Notification(
                title=kwargs.get('title', ''),
                message=kwargs.get('message', ''),
                type=notif_type,
                dismissible=kwargs.get('dismissible', True),
                auto_dismiss_seconds=auto_dismiss_seconds,
                actions=kwargs.get('actions', []),
            )
        
        self.notifications.append(notification)
        
        # Set up auto-dismiss timer if specified
        if notification.auto_dismiss_seconds and notification.auto_dismiss_seconds > 0:
            self._setup_auto_dismiss(notification.id, notification.auto_dismiss_seconds)
        
        self._notify_listeners()
        return notification.id
    
    def update(self, notification_id: str, **kwargs):
        """Update an existing notification"""
        for notif in self.notifications:
            if notif.id == notification_id:
                auto_dismiss_changed = 'auto_dismiss_seconds' in kwargs

                # Convert string type to enum before setting attributes
                if 'type' in kwargs and isinstance(kwargs['type'], str):
                    kwargs['type'] = NotificationType(kwargs['type'])

                for key, value in kwargs.items():
                    if hasattr(notif, key):
                        setattr(notif, key, value)

                if auto_dismiss_changed:
                    if notif.auto_dismiss_seconds and notif.auto_dismiss_seconds > 0:
                        self._setup_auto_dismiss(notif.id, notif.auto_dismiss_seconds)
                    elif notification_id in self.auto_dismiss_timers:
                        # Switching to persistent — cancel the existing timer
                        self.auto_dismiss_timers[notification_id].stop()
                        del self.auto_dismiss_timers[notification_id]

                self._notify_listeners()
                break
    
    def dismiss(self, notification_id: str):
        """Dismiss a notification"""
        from loguru import logger
        logger.debug(f"Dismissing notification {notification_id}")
        
        # Cancel auto-dismiss timer if exists
        if notification_id in self.auto_dismiss_timers:
            self.auto_dismiss_timers[notification_id].stop()
            del self.auto_dismiss_timers[notification_id]
            logger.debug(f"Cleaned up timer for {notification_id}")
        
        self.update(notification_id, is_dismissed=True)
        # Remove from list
        self.notifications = [n for n in self.notifications if n.id != notification_id]
        self._notify_listeners()
    
    def get_visible_notifications(self) -> list[Notification]:
        """Get currently visible notifications"""
        active = [n for n in self.notifications if not n.is_dismissed]
        
        # Sort by priority and time
        active.sort(key=lambda n: (n.priority.value, n.created_at), reverse=True)
        
        return active[:self.max_visible]
    
    def get_all_notifications(self) -> list[Notification]:
        """Get all notifications including dismissed"""
        return self.notifications.copy()
    
    def clear_all(self):
        """Clear all notifications"""
        # Stop all auto-dismiss timers
        for timer in self.auto_dismiss_timers.values():
            timer.stop()
        self.auto_dismiss_timers.clear()
        
        self.notifications.clear()
        self._notify_listeners()
    
    def show_progress(self, title: str, total: Optional[int] = None, 
                     group_id: Optional[str] = None) -> str:
        """Show a progress notification
        
        Returns:
            notification_id for updating progress
        """
        notif = Notification(
            title=title,
            type=NotificationType.PROGRESS,
            progress=0.0,
            progress_current=0,
            progress_total=total,
            dismissible=False,
            group_id=group_id
        )
        return self.show(notif)
    
    def update_progress(self, notification_id: str, current: int, 
                       total: Optional[int] = None, message: Optional[str] = None):
        """Update progress notification"""
        updates = {
            'progress_current': current,
        }
        
        if total is not None:
            updates['progress_total'] = total
            updates['progress'] = current / total if total > 0 else 0.0
        
        if message:
            updates['message'] = message
        
        self.update(notification_id, **updates)
    
    def complete_progress(self, notification_id: str, message: str = "Complete"):
        """Mark progress as complete"""
        self.update(
            notification_id,
            type=NotificationType.SUCCESS,
            progress=1.0,
            message=message,
            dismissible=True,
            auto_dismiss_seconds=5
        )
