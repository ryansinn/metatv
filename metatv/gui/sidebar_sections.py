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
    """Custom widget for provider items with refresh, edit, and toggle buttons."""

    refreshClicked = pyqtSignal(str)   # provider_id
    editClicked = pyqtSignal(str)      # provider_id
    toggleClicked = pyqtSignal(str)    # provider_id

    def __init__(self, provider_id: str, provider_name: str, is_active: bool = True,
                 icon: str = "", sub_color: str = "", parent=None):
        super().__init__(parent)
        self.provider_id = provider_id
        self._is_active = is_active

        self.setAutoFillBackground(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        # Provider icon / emoji (optional)
        if icon:
            icon_lbl = QLabel(icon)
            icon_lbl.setFixedWidth(18)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_lbl)

        # Active/inactive dot
        self._status_lbl = QLabel("●" if is_active else "○")
        self._status_lbl.setFixedWidth(12)
        self._status_lbl.setStyleSheet(f"color: {'#4CAF50' if is_active else '#555'};")
        layout.addWidget(self._status_lbl)

        # Provider name — colored by subscription time if available
        self._name_lbl = QLabel(provider_name)
        self._name_lbl.setWordWrap(False)
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        if sub_color:
            self._name_lbl.setStyleSheet(f"color: {sub_color};")
        layout.addWidget(self._name_lbl, 1)

        _btn_style = """
            QPushButton {{
                background: rgba({r},{g},{b},0.15);
                border: 1px solid rgba({r},{g},{b},0.5);
                border-radius: 3px;
                font-size: 10px;
                color: rgb({r},{g},{b});
            }}
            QPushButton:hover {{ background: rgba({r},{g},{b},0.35); }}
        """

        # Toggle (enable/disable)
        self._toggle_btn = QPushButton("●" if is_active else "○")
        self._toggle_btn.setFixedSize(22, 20)
        self._toggle_btn.setToolTip("Enable / Disable this provider")
        self._toggle_btn.setStyleSheet(_btn_style.format(r=180, g=180, b=180))
        self._toggle_btn.clicked.connect(lambda: self.toggleClicked.emit(self.provider_id))
        layout.addWidget(self._toggle_btn)

        # Edit pencil
        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(22, 20)
        edit_btn.setToolTip("Edit provider settings")
        edit_btn.setStyleSheet(_btn_style.format(r=100, g=160, b=255))
        edit_btn.clicked.connect(lambda: self.editClicked.emit(self.provider_id))
        layout.addWidget(edit_btn)

        # Refresh
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(22, 20)
        refresh_btn.setToolTip("Refresh channels from provider")
        refresh_btn.setStyleSheet(_btn_style.format(r=68, g=136, b=255))
        refresh_btn.clicked.connect(lambda: self.refreshClicked.emit(self.provider_id))
        layout.addWidget(refresh_btn)

    def update_active(self, is_active: bool):
        self._is_active = is_active
        self._status_lbl.setText("●" if is_active else "○")
        self._status_lbl.setStyleSheet(f"color: {'#4CAF50' if is_active else '#555'};")
        self._toggle_btn.setText("●" if is_active else "○")


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

    providerSelected = pyqtSignal(str)         # provider_id
    providerRefreshClicked = pyqtSignal(str)   # provider_id
    providerEditClicked = pyqtSignal(str)      # provider_id
    providerToggleClicked = pyqtSignal(str)    # provider_id
    addProviderClicked = pyqtSignal()

    def __init__(self, config, db, parent=None):
        self.db = db
        super().__init__("Sources", "📡", config, parent)

    def get_section_id(self):
        return "sources"

    def create_header(self):
        """Override to add '+' button in the header instead of bottom buttons."""
        header = QWidget()
        header.setStyleSheet("background-color: rgba(255, 255, 255, 0.05);")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 3, 5, 3)

        self.toggle_btn = QPushButton(self.config.collapse_icon)
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        header_layout.addWidget(self.toggle_btn)

        self.title_label = QLabel(f"📡 <b>Sources</b>")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        add_btn = QPushButton("+")
        add_btn.setFixedSize(22, 20)
        add_btn.setToolTip("Add Source…")
        add_btn.setStyleSheet("""
            QPushButton { font-size: 14px; font-weight: bold; border: 1px solid #4488ff;
                          border-radius: 3px; color: #4488ff; background: rgba(68,136,255,0.1); }
            QPushButton:hover { background: rgba(68,136,255,0.3); }
        """)
        add_btn.clicked.connect(self.addProviderClicked.emit)
        header_layout.addWidget(add_btn)

        self.main_layout.addWidget(header)

    def create_content(self):
        """Create sources tree (no bottom buttons — they moved to the header)."""
        from PyQt6.QtWidgets import QTreeWidget
        self.sources_tree = QTreeWidget()
        self.sources_tree.setHeaderHidden(True)
        self.sources_tree.setMaximumHeight(250)
        self.sources_tree.itemClicked.connect(self.on_provider_clicked)
        self.content_layout.addWidget(self.sources_tree)

    def refresh(self):
        """Load providers from database."""
        self.sources_tree.clear()

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            self.set_empty(len(providers) == 0)

            for provider in providers:
                from PyQt6.QtWidgets import QTreeWidgetItem
                item = QTreeWidgetItem(self.sources_tree)
                item.setText(0, "")
                item.setData(0, Qt.ItemDataRole.UserRole, provider.id)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                # Subscription color from cached account info
                sub_color = ""
                if provider.account_exp_date:
                    from metatv.gui.provider_editor import subscription_color
                    sub_color = subscription_color(provider.account_exp_date, provider.account_created_at)

                icon = getattr(provider, "icon", "") or ""

                widget = ProviderItemWidget(
                    provider.id, provider.name,
                    is_active=provider.is_active,
                    icon=icon,
                    sub_color=sub_color,
                )
                widget.refreshClicked.connect(
                    lambda pid=provider.id: self.providerRefreshClicked.emit(pid)
                )
                widget.editClicked.connect(
                    lambda pid=provider.id: self.providerEditClicked.emit(pid)
                )
                widget.toggleClicked.connect(
                    lambda pid=provider.id: self.providerToggleClicked.emit(pid)
                )
                self.sources_tree.setItemWidget(item, 0, widget)
        finally:
            session.close()

    def on_provider_clicked(self, item, column):
        provider_id = item.data(0, Qt.ItemDataRole.UserRole)
        if provider_id:
            self.providerSelected.emit(provider_id)

    def update_provider_status(self, provider_id: str, status: str):
        """Legacy method — no-op; widgets now update via refresh()."""
        pass


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
    
    historyItemClicked = pyqtSignal(str)  # channel_id (double-click)
    itemSelected = pyqtSignal(str)  # channel_id (single-click)
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
        self.history_list.currentItemChanged.connect(self.on_history_item_selected)
        self.content_layout.addWidget(self.history_list)
        
        # Clear button
        self.clear_btn = QPushButton(f"{self.config.delete_icon} Clear History")
        self.clear_btn.clicked.connect(self.clearHistoryClicked.emit)
        self.content_layout.addWidget(self.clear_btn)
    
    def refresh(self):
        """Load history from database — shows all providers, no filtering"""
        from metatv.core.models import MediaType

        self.history_list.clear()

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            recent = repos.channels.get_recent_history(limit=30)

            self.set_empty(len(recent) == 0)

            if len(recent) == 0:
                return

            for channel in recent:
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(self.history_list)

                media_icon = self.get_media_icon(channel.media_type)

                if channel.media_type == MediaType.SERIES:
                    last_episode = repos.episodes.get_last_played(
                        series_id=channel.source_id,
                        provider_id=channel.provider_id
                    )
                    if last_episode:
                        episode_code = f"S{last_episode.season_num:02d}E{last_episode.episode_num:02d}"
                        item.setText(f"{media_icon} {channel.name}\n   → {episode_code}")
                    else:
                        item.setText(f"{media_icon} {channel.name}")
                else:
                    item.setText(f"{media_icon} {channel.name}")

                item.setData(Qt.ItemDataRole.UserRole, channel.id)
        finally:
            session.close()
    
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
    
    def on_history_item_selected(self, current, previous):
        """Handle history item single-click selection"""
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)


class FavoritesSection(CollapsibleSection):
    """Favorites section"""
    
    favoriteClicked = pyqtSignal(str)  # channel_id (double-click)
    itemSelected = pyqtSignal(str)  # channel_id (single-click)
    
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
        self.favorites_list.currentItemChanged.connect(self.on_favorite_selected)
        self.content_layout.addWidget(self.favorites_list)
    
    def refresh(self):
        """Load favorites from database — shows all providers, no filtering"""
        self.favorites_list.clear()

        session = self.db.get_session()
        try:
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
        finally:
            session.close()

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
    
    def on_favorite_selected(self, current, previous):
        """Handle favorite item single-click selection"""
        if not current:
            return
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemSelected.emit(channel_id)

