"""Base class for content views"""
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import pyqtSignal
from typing import Optional


class ContentView(QWidget):
    """Base class for swappable content views
    
    Different views can be shown in the main content area:
    - BrowseView: Channel list with search and filters
    - FavoritesView: Grid/bookshelf view of favorites
    - SettingsView: Application settings
    - etc.
    """
    
    # Signal when a channel is selected (for details pane)
    channel_selected = pyqtSignal(object)  # channel object
    
    # Signal when view needs status bar update
    status_message = pyqtSignal(str)
    
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
    
    def get_selected_channel(self) -> Optional[object]:
        """Get currently selected channel
        
        Override in subclasses to return the selected channel object.
        Returns None if no channel is selected.
        """
        return None
    
    def on_activate(self):
        """Called when this view becomes active
        
        Override in subclasses to perform any necessary setup
        when the view is shown.
        """
        pass
    
    def on_deactivate(self):
        """Called when this view is hidden
        
        Override in subclasses to perform any necessary cleanup
        when the view is hidden.
        """
        pass
    
    def get_view_name(self) -> str:
        """Get display name for this view
        
        Override in subclasses.
        """
        return "View"
