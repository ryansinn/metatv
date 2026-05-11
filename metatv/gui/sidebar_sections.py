"""Modular collapsible sidebar sections"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame, QSizePolicy, QTreeWidget,
    QTreeWidgetItem, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont
from loguru import logger

from metatv.core.repositories import RepositoryFactory


class ProviderItemWidget(QWidget):
    """Custom widget for provider items with refresh button"""
    
    refreshClicked = pyqtSignal(str)  # provider_id
    
    def __init__(self, provider_id, provider_name, is_active=True, parent=None):
        super().__init__(parent)
        self.provider_id = provider_id
        
        # Set opaque background to prevent tree item text from showing through
        self.setAutoFillBackground(True)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        
        # Status indicator
        status = "●" if is_active else "○"
        status_label = QLabel(status)
        status_label.setFixedWidth(12)
        layout.addWidget(status_label, 0)
        
        # Provider name with elided text
        text_label = QLabel(provider_name)
        text_label.setWordWrap(False)
        # Enable eliding to truncate long names with ...
        from PyQt6.QtCore import Qt
        text_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(text_label, 1)  # Stretch factor 1
        
        # Refresh button
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(24, 20)
        refresh_btn.setToolTip("Refresh channels from provider")
        refresh_btn.clicked.connect(lambda: self.refreshClicked.emit(self.provider_id))
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(68, 136, 255, 0.2);
                border: 1px solid #4488ff;
                border-radius: 3px;
                font-size: 10px;
                color: #4488ff;
            }
            QPushButton:hover {
                background-color: rgba(68, 136, 255, 0.4);
            }
            QPushButton:pressed {
                background-color: rgba(68, 136, 255, 0.6);
            }
        """)
        layout.addWidget(refresh_btn)
        
        self.setLayout(layout)


class HistoryItemWidget(QWidget):
    """Custom widget for history list items with play next button"""
    
    playNextClicked = pyqtSignal(str)  # channel_id
    
    def __init__(self, channel_id, text, has_next_episode=False, parent=None):
        super().__init__(parent)
        self.channel_id = channel_id
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        
        # Text label (series name + episode info)
        text_label = QLabel(text)
        text_label.setWordWrap(False)
        layout.addWidget(text_label, 1)  # Stretch factor 1
        
        # Play next button (only show if there's a next episode)
        if has_next_episode:
            next_btn = QPushButton(">>")
            next_btn.setFixedSize(30, 20)
            next_btn.setToolTip("Play next episode")
            next_btn.clicked.connect(lambda: self.playNextClicked.emit(self.channel_id))
            next_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(68, 136, 255, 0.2);
                    border: 1px solid #4488ff;
                    border-radius: 3px;
                    font-size: 11px;
                    font-weight: bold;
                    color: #4488ff;
                }
                QPushButton:hover {
                    background-color: rgba(68, 136, 255, 0.4);
                }
                QPushButton:pressed {
                    background-color: rgba(68, 136, 255, 0.6);
                }
            """)
            layout.addWidget(next_btn)
        
        self.setLayout(layout)


class CollapsibleSection(QFrame):
    """Base class for collapsible sidebar sections with resize support"""
    
    # Signal when section wants to update its size
    sizeChanged = pyqtSignal()
    
    def __init__(self, title: str, icon: str, config, parent=None):
        super().__init__(parent)
        self.title = title
        self.icon = icon
        self.config = config
        self.is_collapsed = False
        self.is_empty = True
        
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        
        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Header
        self.create_header()
        
        # Content container
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.addWidget(self.content_widget)
        
        # Create section-specific content
        self.create_content()
    
    def create_header(self):
        """Create collapsible header with title and toggle button"""
        header = QWidget()
        header.setStyleSheet("background-color: rgba(255, 255, 255, 0.05);")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)
        
        # Collapse/expand button
        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_btn)
        
        # Title with icon
        self.title_label = QLabel(f"{self.icon} <b>{self.title}</b>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        
        self.main_layout.addWidget(header)
    
    def create_content(self):
        """Override in subclasses to add section-specific content"""
        pass
    
    def toggle_collapse(self):
        """Toggle collapsed/expanded state"""
        self.set_collapsed(not self.is_collapsed)
    
    def set_collapsed(self, collapsed: bool, save: bool = True):
        """Set collapsed state
        
        Args:
            collapsed: Whether to collapse the section
            save: Whether to save state to config (default: True)
        """
        self.is_collapsed = collapsed
        self.content_widget.setVisible(not collapsed)
        
        # Update button icon
        if collapsed:
            self.toggle_btn.setText(self.config.expand_icon)
        else:
            self.toggle_btn.setText(self.config.collapse_icon)
        
        # Force size update
        if collapsed:
            self.setMaximumHeight(self.minimumSizeHint().height())
        else:
            self.setMaximumHeight(16777215)  # Qt's QWIDGETSIZE_MAX
        
        # Notify parent to adjust layout
        self.updateGeometry()
        self.sizeChanged.emit()
        
        # Save state (unless explicitly disabled, e.g. during restore)
        if save:
            self.save_state()
    
    def set_empty(self, empty: bool):
        """Set empty state and auto-collapse if empty"""
        was_empty = self.is_empty
        self.is_empty = empty
        
        # Auto-collapse when becoming empty
        if empty and not was_empty:
            self.set_collapsed(True)
        # Auto-expand when getting content (if not manually collapsed)
        elif not empty and was_empty and self.is_collapsed:
            # Only auto-expand if this is the first content
            self.set_collapsed(False)
    
    def get_section_id(self):
        """Get unique ID for this section (for saving state)"""
        # Override in subclasses or use title as default
        return self.title.lower().replace(" ", "_")
    
    def save_state(self):
        """Save section state to config"""
        section_id = self.get_section_id()
        
        # Get or create section states dict in config
        if not hasattr(self.config, 'sidebar_section_states'):
            self.config.sidebar_section_states = {}
        
        self.config.sidebar_section_states[section_id] = {
            'collapsed': self.is_collapsed,
            'height': self.height()
        }
        
        # Save config to disk
        try:
            self.config.save()
        except Exception as e:
            logger.warning(f"Could not save section state: {e}")
    
    def restore_state(self):
        """Restore section state from config"""
        section_id = self.get_section_id()
        
        if not hasattr(self.config, 'sidebar_section_states'):
            return
        
        state = self.config.sidebar_section_states.get(section_id)
        if state:
            # Restore collapsed state (don't save during restore)
            collapsed = state.get('collapsed', False)
            self.set_collapsed(collapsed, save=False)
            
            # Restore height (if not collapsed)
            if not collapsed:
                height = state.get('height')
                if height:
                    self.setMinimumHeight(height)
    
    def refresh(self):
        """Refresh section content - override in subclasses"""
        pass


class SourcesSection(CollapsibleSection):
    """Sources provider list section"""
    
    # Signals
    providerSelected = pyqtSignal(str)  # provider_id
    providerRefreshClicked = pyqtSignal(str)  # provider_id
    addProviderClicked = pyqtSignal()
    settingsClicked = pyqtSignal()
    
    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Sources", "📡", config, parent)
    
    def get_section_id(self):
        return "sources"
    
    def create_content(self):
        """Create sources tree and buttons"""
        from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
        
        # Sources tree
        self.sources_tree = QTreeWidget()
        self.sources_tree.setHeaderHidden(True)
        self.sources_tree.setMaximumHeight(200)
        self.sources_tree.itemClicked.connect(self.on_provider_clicked)
        self.content_layout.addWidget(self.sources_tree)
        
        # Buttons
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        self.add_btn = QPushButton("Add Provider")
        self.add_btn.clicked.connect(self.addProviderClicked.emit)
        button_layout.addWidget(self.add_btn)
        
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.settingsClicked.emit)
        button_layout.addWidget(self.settings_btn)
        
        self.content_layout.addWidget(button_widget)
    
    def refresh(self):
        """Load providers from database"""
        self.sources_tree.clear()
        
        with self.db.get_session() as session:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            
            self.set_empty(len(providers) == 0)
            
            for provider in providers:
                item = QTreeWidgetItem(self.sources_tree)
                # Clear any default text display
                item.setText(0, "")
                item.setData(0, Qt.ItemDataRole.UserRole, provider.id)
                # Disable item interaction flags that might interfere
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                
                # Create custom widget with refresh button
                widget = ProviderItemWidget(
                    provider.id,
                    provider.name,
                    provider.is_active
                )
                # Use lambda with default argument to avoid closure issues
                widget.refreshClicked.connect(
                    lambda pid=provider.id: self.providerRefreshClicked.emit(pid)
                )
                
                self.sources_tree.setItemWidget(item, 0, widget)
    
    def on_provider_clicked(self, item, column):
        """Handle provider selection"""
        provider_id = item.data(0, Qt.ItemDataRole.UserRole)
        if provider_id:
            self.providerSelected.emit(provider_id)
    
    def update_provider_status(self, provider_id: str, status: str):
        """Update visual status indicator for a provider
        
        Args:
            provider_id: Provider ID
            status: 'disabled', 'testing', 'online', 'offline'
        """
        for i in range(self.sources_tree.topLevelItemCount()):
            item = self.sources_tree.topLevelItem(i)
            pid = item.data(0, Qt.ItemDataRole.UserRole)
            if pid == provider_id:
                # Update item text with status indicator
                with self.db.get_session() as session:
                    repos = RepositoryFactory(session)
                    provider = repos.providers.get_by_id(provider_id)
                    if provider:
                        if status == 'disabled':
                            status_icon = "○"
                        elif status == 'testing':
                            status_icon = "⟳"
                        elif status == 'online':
                            status_icon = "●✓"
                        elif status == 'offline':
                            status_icon = "⚠"
                        else:
                            status_icon = "●"
                        
                        item.setText(0, f"{status_icon} {provider.name}")
                break


class WatchAlertsSection(CollapsibleSection):
    """Watch alerts section"""
    
    alertClicked = pyqtSignal(str)  # alert_id
    
    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Watch Alerts", "⚠", config, parent)
    
    def get_section_id(self):
        return "alerts"
    
    def create_content(self):
        """Create alerts list"""
        from PyQt6.QtWidgets import QListWidget
        
        self.alerts_list = QListWidget()
        self.alerts_list.setMaximumHeight(120)
        self.content_layout.addWidget(self.alerts_list)
        
        # Placeholder for now
        self.set_empty(True)
    
    def refresh(self):
        """Load alerts from database"""
        # TODO: Implement when alert system is integrated
        self.set_empty(True)


class HistorySection(CollapsibleSection):
    """Playback history section"""
    
    historyItemClicked = pyqtSignal(str)  # channel_id
    clearHistoryClicked = pyqtSignal()
    
    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("History", config.history_icon, config, parent)
    
    def get_section_id(self):
        return "history"
    
    def create_content(self):
        """Create history list and clear button"""
        from PyQt6.QtWidgets import QListWidget
        
        # History list
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(150)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.itemDoubleClicked.connect(self.on_history_item_clicked)
        self.content_layout.addWidget(self.history_list)
        
        # Clear button
        self.clear_btn = QPushButton(f"{self.config.delete_icon} Clear History")
        self.clear_btn.clicked.connect(self.clearHistoryClicked.emit)
        self.content_layout.addWidget(self.clear_btn)
    
    def refresh(self):
        """Load history from database"""
        from metatv.core.models import MediaType
        
        self.history_list.clear()
        
        with self.db.get_session() as session:
            repos = RepositoryFactory(session)
            recent = repos.channels.get_recent_history(limit=30)
            
            self.set_empty(len(recent) == 0)
            
            if len(recent) == 0:
                return
            
            for channel in recent:
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(self.history_list)
                
                # Get media type icon
                media_icon = self.get_media_icon(channel.media_type)
                
                # For series, show last watched episode as subtitle
                if channel.media_type == MediaType.SERIES:
                    # Find most recent episode played for this series
                    last_episode = repos.episodes.get_last_played(
                        series_id=channel.source_id,
                        provider_id=channel.provider_id
                    )
                    
                    if last_episode:
                        # Format: S03E01 or just episode title
                        episode_code = f"S{last_episode.season_num:02d}E{last_episode.episode_num:02d}"
                        item.setText(f"{media_icon} {channel.name}\n   → {episode_code}")
                    else:
                        item.setText(f"{media_icon} {channel.name}")
                else:
                    item.setText(f"{media_icon} {channel.name}")
                
                item.setData(Qt.ItemDataRole.UserRole, channel.id)
    
    def get_media_icon(self, media_type):
        """Get icon for media type"""
        from metatv.core.models import MediaType
        if media_type == MediaType.LIVE:
            return self.config.live_icon
        elif media_type == MediaType.MOVIE:
            return self.config.movie_icon
        elif media_type == MediaType.SERIES:
            return self.config.series_icon
        return self.config.unknown_icon
    
    def on_history_item_clicked(self, item):
        """Handle history item double-click"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.historyItemClicked.emit(channel_id)


class FavoritesSection(CollapsibleSection):
    """Favorites section"""
    
    favoriteClicked = pyqtSignal(str)  # channel_id
    
    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Favorites", "★", config, parent)
        
        # Favorites should expand to fill remaining space
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    
    def get_section_id(self):
        return "favorites"
    
    def create_content(self):
        """Create favorites list"""
        from PyQt6.QtWidgets import QListWidget
        
        self.favorites_list = QListWidget()
        self.favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites_list.itemDoubleClicked.connect(self.on_favorite_clicked)
        self.content_layout.addWidget(self.favorites_list)
    
    def refresh(self):
        """Load favorites from database"""
        self.favorites_list.clear()
        
        with self.db.get_session() as session:
            repos = RepositoryFactory(session)
            all_favorites = repos.channels.get_favorites()
            
            self.set_empty(len(all_favorites) == 0)
            
            if len(all_favorites) == 0:
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem("No favorites yet")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.favorites_list.addItem(item)
                item = QListWidgetItem("Right-click any channel to add to favorites")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.favorites_list.addItem(item)
                return
            
            # Separate into continue watching and never watched
            continue_watching = [c for c in all_favorites if c.last_played]
            never_watched = [c for c in all_favorites if not c.last_played]
            
            # Sort
            continue_watching.sort(key=lambda c: c.last_played, reverse=True)
            never_watched.sort(key=lambda c: c.name)
            
            # Add headers and items
            if continue_watching:
                self.add_header("Continue Watching")
                for channel in continue_watching:
                    self.add_favorite_item(channel)
            
            if never_watched:
                self.add_header("Never Watched")
                for channel in never_watched:
                    self.add_favorite_item(channel)
    
    def add_header(self, text):
        """Add a section header"""
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtGui import QFont
        
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self.favorites_list.addItem(item)
    
    def add_favorite_item(self, channel):
        """Add a favorite channel item"""
        from PyQt6.QtWidgets import QListWidgetItem
        
        item = QListWidgetItem(self.favorites_list)
        
        # Get media type icon
        media_icon = self.get_media_icon(channel.media_type)
        
        item.setText(f"{media_icon} {channel.name}")
        item.setData(Qt.ItemDataRole.UserRole, channel.id)
    
    def get_media_icon(self, media_type):
        """Get icon for media type"""
        from metatv.core.models import MediaType
        if media_type == MediaType.LIVE:
            return self.config.live_icon
        elif media_type == MediaType.MOVIE:
            return self.config.movie_icon
        elif media_type == MediaType.SERIES:
            return self.config.series_icon
        return self.config.unknown_icon
    
    def on_favorite_clicked(self, item):
        """Handle favorite item double-click"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.favoriteClicked.emit(channel_id)

