"""Main application window"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QSplitter,
    QTreeWidget, QListWidget, QMenuBar, QMenu,
    QCheckBox, QTreeWidgetItem, QLineEdit, QListWidgetItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from loguru import logger
import subprocess
import shutil
import requests
from urllib.parse import urlparse, urlunparse
from datetime import datetime

from metatv.core.config import Config
from metatv.core.database import Database, SeasonDB, EpisodeDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.notifications import NotificationManager
from metatv.core.player_manager import PlayerManager
from metatv.core.provider_loader import SeriesLoadThread
from metatv.gui.dialogs import AddProviderDialog
from metatv.gui.notification_widget import NotificationWidget
from metatv.gui.provider_editor import ProviderEditorView
from metatv.gui.sidebar_sections import (
    SourcesSection, WatchAlertsSection,
    HistorySection, FavoritesSection
)
from metatv.gui.filter_bar import FilterBar, ToggleChip
from metatv.gui.collapsible_splitter import CollapsibleSplitter
from metatv.gui.details_pane import DetailsPaneWidget
from metatv.gui.ppv_view import PPVView
from metatv.gui.sports_view import SportsView
from metatv.gui.events_view import EventsView
from metatv.gui.epg_view import EpgView
from metatv.core.epg_manager import EpgManager
from metatv.core.image_cache import ImageCache
from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
from metatv.metadata_providers.provider_metadata import ProviderMetadataProvider


class MainWindow(QMainWindow):
    """Main application window"""
    
    # Signal for thread-safe metadata updates (channel_id, metadata)
    metadata_loaded = pyqtSignal(object, object)
    
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.notification_manager = NotificationManager(
            max_visible=config.max_stacked_notifications
        )
        
        # UI Icons from config - Media Types
        self.favorite_icon = config.favorite_icon
        self.unfavorite_icon = config.unfavorite_icon
        self.live_icon = config.live_icon
        self.movie_icon = config.movie_icon
        self.series_icon = config.series_icon
        self.season_icon = config.season_icon
        self.episode_icon = config.episode_icon
        self.unknown_icon = config.unknown_icon
        
        # UI Control Icons
        self.expand_icon = config.expand_icon
        self.collapse_icon = config.collapse_icon
        self.play_icon = config.play_icon
        self.loading_icon = config.loading_icon
        self.close_icon = config.close_icon
        self.delete_icon = config.delete_icon
        self.refresh_icon = config.refresh_icon
        self.settings_icon = config.settings_icon
        self.search_icon = config.search_icon
        self.filter_icon = config.filter_icon
        self.history_icon = config.history_icon
        
        # Store active threads to prevent garbage collection
        self.active_threads = []
        
        # Track selected provider for filtering
        self.selected_provider_id = None
        self._in_provider_edit_mode = False
        
        # Store channel data for filtering
        self.all_channels = []  # List of (display_text, channel_db_obj)
        self.max_display_limit = 10000  # Max channels to display without search
        
        # Filter state
        self.current_filter_state = None
        
        # Player management
        self.player_manager = PlayerManager(config)
        self.loading_channels = set()  # Track channels being loaded
        self.refreshing_providers = set()  # Track providers being refreshed
        
        # Navigation state for series browsing
        self.view_mode = "list"  # "list" or "series"
        self.current_series = None  # Current series being viewed (channel object)
        self.series_data = None  # Loaded series data (seasons/episodes)
        
        # Initialize database
        self.db = Database(config.database_url)
        self.db.create_tables()
        
        # Initialize metadata system
        self.image_cache = ImageCache(
            cache_dir=config.image_cache_dir,
            max_size_mb=config.image_cache_max_size_mb
        )
        
        # Initialize metadata provider registry
        self.metadata_registry = MetadataProviderRegistry()
        
        # Register provider metadata plugin (extracts from raw_data)
        provider_metadata = ProviderMetadataProvider(self.db)
        self.metadata_registry.register(provider_metadata)
        
        # Initialize metadata manager
        self.metadata_manager = MetadataManager(self.metadata_registry, self.db)
        
        self.setup_ui()
        self.setup_notifications()
        self.load_providers()
        self.load_favorites()
        self.load_history()
        
        # Auto-load channels from all active providers on startup
        self.load_channels()
        
        # Initialize filter statistics
        self.initialize_filter_stats()
        
        # Test provider connections in background
        self.test_all_providers()
        
        # Connect metadata loaded signal for thread-safe UI updates
        self.metadata_loaded.connect(self._update_details_with_metadata)
        
        logger.info("Main window initialized")
    
    def setup_ui(self):
        """Set up the user interface"""
        self.setWindowTitle("MetaTV - IPTV Stream Organizer")

        # Restore saved geometry, or fall back to a sensible default
        restored = False
        saved_geom = getattr(self.config, 'window_geometry', '')
        if saved_geom:
            try:
                import base64
                from PyQt6.QtCore import QByteArray
                geom_bytes = QByteArray(base64.b64decode(saved_geom))
                restored = self.restoreGeometry(geom_bytes)
            except Exception as e:
                logger.warning(f"Could not restore window geometry: {e}")
        if not restored:
            self.setGeometry(100, 100, 1400, 900)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        
        # Create collapsible splitter for sidebar, content, and details pane
        self.main_splitter = CollapsibleSplitter(Qt.Orientation.Horizontal)
        
        # Left sidebar
        sidebar = self.create_sidebar()
        sidebar.setMinimumWidth(200)
        self.main_splitter.addWidget(sidebar)

        # Main content area
        content = self.create_content_area()
        content.setMinimumWidth(400)
        self.main_splitter.addWidget(content)

        # Right details pane
        self.details_pane = DetailsPaneWidget(self.config, self.image_cache)
        self.details_pane.play_requested.connect(self.play_channel_by_id)
        self.details_pane.favorite_toggled.connect(self.toggle_favorite_by_id)
        self.main_splitter.addWidget(self.details_pane)

        # Center panel gets all extra space when window is resized
        self.main_splitter.setStretchFactor(0, 0)  # sidebar: fixed
        self.main_splitter.setStretchFactor(1, 1)  # center: stretches
        self.main_splitter.setStretchFactor(2, 0)  # details: fixed

        # Set initial sizes: sidebar | content | details
        sidebar_width = getattr(self.config, 'sidebar_width', 340)
        details_width = getattr(self.config, 'details_pane_width', 400)
        total_width = self.width()
        content_width = max(400, total_width - sidebar_width - details_width)

        self.main_splitter.setSizes([sidebar_width, content_width, details_width])
        
        # Initially collapse details pane if not visible in config
        if not getattr(self.config, 'details_pane_visible', False):
            self.main_splitter.collapse_panel(2)  # Collapse right panel
        
        # Connect splitter moved signal to save widths
        self.main_splitter.splitterMoved.connect(self.save_splitter_sizes)
        
        main_layout.addWidget(self.main_splitter)
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def create_menu_bar(self):
        """Create application menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction("&Add Provider...", self.add_provider)
        file_menu.addSeparator()
        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction("&Refresh", self.refresh_channels)
        view_menu.addAction("&Operations", self.show_operations)
        
        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction("&Diagnostics", self.show_diagnostics)
        tools_menu.addAction("&Filters", self.manage_filters)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("&About", self.show_about)
    
    def create_sidebar(self) -> QWidget:
        """Create modular sidebar with resizable sections"""
        # Use QSplitter for resizable sections
        self.sidebar_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Track section widgets
        self.sidebar_sections = {}
        
        # Create sections based on config order
        for section_id in self.config.sidebar_sections:
            # Skip if not visible
            if section_id not in self.config.sidebar_visible_sections:
                continue
            
            section = self.create_section(section_id)
            if section:
                self.sidebar_sections[section_id] = section
                self.sidebar_splitter.addWidget(section)
                
                # Restore state
                section.restore_state()
        
        # Restore section sizes from config
        if self.config.sidebar_section_sizes:
            self.sidebar_splitter.setSizes(self.config.sidebar_section_sizes)
        
        # Connect splitter moved signal to save sizes
        self.sidebar_splitter.splitterMoved.connect(self.save_sidebar_section_sizes)
        
        return self.sidebar_splitter
    
    def create_section(self, section_id: str):
        """Create a sidebar section by ID"""
        if section_id == "sources":
            section = SourcesSection(self.config, self.db, self)
            section.providerSelected.connect(self.on_provider_selected_new)
            section.providerRefreshClicked.connect(self.refresh_provider)
            section.providerEditClicked.connect(self.enter_provider_edit_mode)
            section.providerToggleClicked.connect(self.toggle_provider_active)
            section.addProviderClicked.connect(self.add_provider)
            return section
        
        elif section_id == "alerts":
            section = WatchAlertsSection(self.config, self.db, self)
            # TODO: Connect alert signals when implemented
            return section
        
        elif section_id == "history":
            section = HistorySection(self.config, self.db, self)
            section.historyItemClicked.connect(self.play_from_history_id)
            section.itemSelected.connect(self.show_channel_details_by_id)
            section.clearHistoryClicked.connect(self.clear_history)
            # Connect context menu handler
            section.history_list.customContextMenuRequested.connect(
                lambda pos: self.show_history_context_menu(pos, section.history_list)
            )
            return section
        
        elif section_id == "favorites":
            section = FavoritesSection(self.config, self.db, self)
            section.favoriteClicked.connect(self.play_favorite_id)
            section.itemSelected.connect(self.show_channel_details_by_id)
            # Connect context menu handler
            section.favorites_list.customContextMenuRequested.connect(
                lambda pos: self.show_favorites_context_menu(pos, section.favorites_list)
            )
            return section
        
        return None
    
    def refresh_sidebar(self):
        """Refresh all sidebar sections"""
        for section in self.sidebar_sections.values():
            section.refresh()

    
    def create_content_area(self) -> QWidget:
        """Create main content area"""
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        
        # Navigation bar (hidden by default, shown in series view)
        nav_bar = QWidget()
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        
        self.back_button = QPushButton(f"← Back")
        self.back_button.clicked.connect(self.navigate_back)
        self.back_button.setVisible(False)
        nav_layout.addWidget(self.back_button)
        
        self.breadcrumb_label = QLabel("")
        nav_layout.addWidget(self.breadcrumb_label)
        nav_layout.addStretch()
        
        self.content_layout.addWidget(nav_bar)
        
        # Media type chips (above search)
        media_widget = QWidget()
        media_layout = QHBoxLayout(media_widget)
        media_layout.setContentsMargins(0, 5, 0, 5)
        media_layout.addWidget(QLabel("Media:"))
        
        self.live_chip = ToggleChip("Live", enabled=True)
        media_layout.addWidget(self.live_chip)
        
        self.movies_chip = ToggleChip("Movies", enabled=True)
        media_layout.addWidget(self.movies_chip)
        
        self.series_chip = ToggleChip("Series", enabled=True)
        media_layout.addWidget(self.series_chip)
        
        # Restore media chip state from config (before connecting signals)
        enabled_types = getattr(self.config, 'filter_enabled_media_types', ['live', 'movie', 'series'])
        # If empty list, use default
        if not enabled_types:
            enabled_types = ['live', 'movie', 'series']
        logger.debug(f"Restoring media chip state from config: {enabled_types}")
        self.live_chip.set_enabled('live' in enabled_types)
        self.movies_chip.set_enabled('movie' in enabled_types)
        self.series_chip.set_enabled('series' in enabled_types)
        logger.debug(f"After restore - Live: {self.live_chip.is_enabled()}, Movies: {self.movies_chip.is_enabled()}, Series: {self.series_chip.is_enabled()}")
        
        # NOW connect signals after state is restored
        self.live_chip.clicked.connect(self.on_filter_changed)
        self.movies_chip.clicked.connect(self.on_filter_changed)
        self.series_chip.clicked.connect(self.on_filter_changed)
        
        media_layout.addStretch()
        
        # Special content view chips (PPV, Events, Sports)
        media_layout.addWidget(QLabel(" | "))
        media_layout.addWidget(QLabel("Special:"))
        
        self.ppv_chip = ToggleChip("💰 PPV", enabled=False)
        self.ppv_chip.clicked.connect(self.on_special_view_toggle)
        media_layout.addWidget(self.ppv_chip)
        
        self.events_chip = ToggleChip("🎪 Events", enabled=False)
        self.events_chip.clicked.connect(self.on_special_view_toggle)
        media_layout.addWidget(self.events_chip)
        
        self.sports_chip = ToggleChip("⚽ Sports", enabled=False)
        self.sports_chip.clicked.connect(self.on_special_view_toggle)
        media_layout.addWidget(self.sports_chip)

        self.epg_chip = ToggleChip("📅 EPG", enabled=False)
        self.epg_chip.clicked.connect(self.on_special_view_toggle)
        media_layout.addWidget(self.epg_chip)
        
        self.content_layout.addWidget(media_widget)
        
        # Search and filter controls
        self.search_controls = QWidget()
        controls_layout = QHBoxLayout(self.search_controls)
        controls_layout.addWidget(QLabel("Search:"))
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter channels by name, category...")
        self.search_input.textChanged.connect(self.filter_channels)
        controls_layout.addWidget(self.search_input)
        
        # Clear search button
        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(30)
        clear_btn.setToolTip("Clear search")
        clear_btn.clicked.connect(lambda: self.search_input.clear())
        controls_layout.addWidget(clear_btn)
        
        # Toggle filters button
        self.toggle_filters_btn = QPushButton("⚙ Filters ▼")
        self.toggle_filters_btn.setFixedWidth(100)
        self.toggle_filters_btn.setToolTip("Show/hide filters")
        self.toggle_filters_btn.clicked.connect(self.toggle_filters)
        controls_layout.addWidget(self.toggle_filters_btn)

        # Settings button
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setToolTip("Open settings (Ctrl+,)")
        settings_btn.clicked.connect(self.open_settings)
        controls_layout.addWidget(settings_btn)

        self.content_layout.addWidget(self.search_controls)

        # Collapsible filter bar
        self.filter_bar = FilterBar(self.config)
        self.filter_bar.filter_changed.connect(self.on_filter_changed)
        
        # Restore filter section visibility from config
        self.filters_visible = getattr(self.config, 'filter_section_visible', True)
        self.filter_bar.setVisible(self.filters_visible)
        self.toggle_filters_btn.setText("⚙ Filters ▼" if self.filters_visible else "⚙ Filters ▶")
        
        self.content_layout.addWidget(self.filter_bar)
        
        # Channels list (default view)
        self.channels_list = QListWidget()
        self.channels_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channels_list.customContextMenuRequested.connect(self.show_channel_context_menu)
        self.channels_list.itemDoubleClicked.connect(self.play_channel)
        self.channels_list.currentItemChanged.connect(self.on_channel_selection_changed)
        self.content_layout.addWidget(self.channels_list)
        
        # Series tree view (hidden by default)
        self.series_tree = QTreeWidget()
        self.series_tree.setHeaderLabels(["Title", "Episode", "Runtime", "Rating"])
        self.series_tree.setColumnWidth(0, 400)
        self.series_tree.setColumnWidth(1, 80)
        self.series_tree.setColumnWidth(2, 80)
        self.series_tree.setColumnWidth(3, 80)
        # Disable Qt's default double-click expansion behavior (it defaults to True in Qt6)
        # We handle expansion manually in play_series_item() to differentiate seasons vs episodes
        self.series_tree.setExpandsOnDoubleClick(False)
        self.series_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.series_tree.customContextMenuRequested.connect(self.show_series_context_menu)
        self.series_tree.itemDoubleClicked.connect(self.play_series_item)
        self.series_tree.setVisible(False)
        self.content_layout.addWidget(self.series_tree)
        
        # PPV view (hidden by default)
        self.ppv_view = PPVView(self.config, self.db, self)
        self.ppv_view.play_channel_requested.connect(self.play_ppv_event)
        self.ppv_view.status_message.connect(lambda msg: self.status_bar.showMessage(msg))
        self.ppv_view.setVisible(False)
        self.content_layout.addWidget(self.ppv_view)

        # Events view (hidden by default)
        self.events_view = EventsView(self.config, self.db, self)
        self.events_view.play_channel_requested.connect(self.play_special_event)
        self.events_view.status_message.connect(lambda msg: self.status_bar.showMessage(msg))
        self.events_view.channel_selected.connect(self._on_view_channel_selected)
        self.events_view.setVisible(False)
        self.content_layout.addWidget(self.events_view)

        # Sports view (hidden by default)
        self.sports_view = SportsView(self.config, self.db, self)
        self.sports_view.play_channel_requested.connect(self.play_special_event)
        self.sports_view.status_message.connect(lambda msg: self.status_bar.showMessage(msg))
        self.sports_view.channel_selected.connect(self._on_view_channel_selected)
        self.sports_view.setVisible(False)
        self.content_layout.addWidget(self.sports_view)

        # EPG manager + view (hidden by default)
        self.epg_manager = EpgManager(self.db, self.config, self.notification_manager, parent=self)
        self.epg_view = EpgView(self.config, self.db, self.epg_manager, self)
        self.epg_view.play_channel_requested.connect(self.play_special_event)
        self.epg_view.status_message.connect(lambda msg: self.status_bar.showMessage(msg))
        self.epg_view.channel_selected.connect(self._on_view_channel_selected)
        self.epg_view.setVisible(False)
        self.content_layout.addWidget(self.epg_view)
        self.epg_manager.start_notification_timer()

        # Provider editor (hidden by default; replaces center panel in edit mode)
        self.provider_editor = ProviderEditorView(self.db, self)
        self.provider_editor.done.connect(self.exit_provider_edit_mode)
        self.provider_editor.provider_saved.connect(self._on_provider_saved)
        self.provider_editor.provider_deleted.connect(self._on_provider_deleted)
        self.provider_editor.refresh_requested.connect(self.refresh_provider)
        self.provider_editor.setVisible(False)
        self.content_layout.addWidget(self.provider_editor)

        # Stats label below all views
        stats_container = QWidget()
        stats_layout = QHBoxLayout(stats_container)
        stats_layout.setContentsMargins(10, 5, 10, 5)
        
        self.stats_label = QLabel("Showing 0 of 0 channels")
        self.stats_label.setStyleSheet("color: #666666; font-size: 12px;")
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        
        self.content_layout.addWidget(stats_container)
        
        return content
    
    def get_media_type_icon(self, media_type: str) -> str:
        """Get icon for media type"""
        from metatv.core.models import MediaType
        
        if media_type == MediaType.LIVE:
            return self.live_icon
        elif media_type == MediaType.MOVIE:
            return self.movie_icon
        elif media_type == MediaType.SERIES:
            return self.series_icon
        else:
            return self.unknown_icon
    
    def setup_notifications(self):
        """Set up notification system"""
        # Create notification widget (as child of central widget)
        self.notification_widget = NotificationWidget(
            self.notification_manager, self.config, self.centralWidget()
        )
        
        # Listen for notification changes
        self.notification_manager.add_listener(self.update_notifications)
        
        # Test notification (remove later)
        # self.show_test_notification()
    
    def update_notifications(self, notifications):
        """Update notification widget"""
        self.notification_widget.update_notifications(notifications)
        # Force repaint to ensure text renders properly
        self.notification_widget.update()
        self.notification_widget.repaint()
    
    def resizeEvent(self, event):
        """Handle window resize to reposition notifications"""
        super().resizeEvent(event)
        if hasattr(self, 'notification_widget'):
            self.notification_widget.reposition()
    
    def show_test_notification(self):
        """Show a test notification (for development)"""
        notif_id = self.notification_manager.show_progress(
            title="Loading Example TV",
            total=150000
        )
        
        # Simulate progress
        progress = 0
        def update_progress():
            nonlocal progress
            progress += 5000
            self.notification_manager.update_progress(notif_id, progress, 150000)
            if progress >= 150000:
                self.notification_manager.complete_progress(
                    notif_id, 
                    "150,000 channels loaded"
                )
        
        timer = QTimer(self)
        timer.timeout.connect(update_progress)
        timer.start(500)
    
    # Action handlers
    def add_provider(self):
        """Show add provider dialog"""
        dialog = AddProviderDialog(self, self.config, self.db, self.notification_manager)
        if dialog.exec():
            self.load_providers()
    
    def _hide_all_content_views(self):
        """Hide every content widget so one can be shown exclusively."""
        self.channels_list.setVisible(False)
        self.series_tree.setVisible(False)
        self.ppv_view.setVisible(False)
        self.events_view.setVisible(False)
        self.sports_view.setVisible(False)
        self.provider_editor.setVisible(False)
        self.filter_bar.setVisible(False)

    def enter_provider_edit_mode(self, provider_id: str):
        """Switch center panel to provider editor for the given provider."""
        self._hide_all_content_views()
        self.search_controls.setVisible(False)
        self.provider_editor.setVisible(True)
        self.provider_editor.load_provider(provider_id)
        self.stats_label.setText("Editing provider — click a source to switch")
        self._in_provider_edit_mode = True

    def exit_provider_edit_mode(self):
        """Return to the normal channel list view."""
        self._in_provider_edit_mode = False
        self.switch_to_list_view()
        self.load_providers()

    def toggle_provider_active(self, provider_id: str):
        """Flip the is_active flag for a provider and refresh the sidebar."""
        session = self.db.get_session()
        try:
            from metatv.core.database import ProviderDB as _PDB
            db_prov = session.query(_PDB).filter_by(id=provider_id).first()
            if db_prov:
                db_prov.is_active = not db_prov.is_active
                session.commit()
                logger.info(f"Provider '{db_prov.name}' is_active → {db_prov.is_active}")
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to toggle provider: {e}")
        finally:
            session.close()
        self.load_providers()

    def _on_provider_saved(self, provider_id: str):
        """Reload sidebar after a provider is saved in the editor."""
        self.load_providers()
        self.status_bar.showMessage("Provider saved.", 3000)

    def _on_provider_deleted(self, provider_id: str):
        """Clean up after a provider is deleted from the editor."""
        self.load_providers()
        self.exit_provider_edit_mode()
        self.status_bar.showMessage("Provider deleted.", 3000)

    def edit_provider(self):
        """Legacy hook — no longer used (edit triggers from sidebar widget)."""
        pass
    
    def refresh_channels(self):
        """Refresh channel list"""
        self.status_bar.showMessage("Refreshing channels...")
        logger.info("Refreshing channels")
        self.load_providers()
    
    def load_providers(self):
        """Load providers from database into sidebar"""
        if "sources" in self.sidebar_sections:
            self.sidebar_sections["sources"].refresh()
        self._refresh_details_provider_map()

    def _refresh_details_provider_map(self):
        """Push current provider icon/name map to the details pane."""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            provider_map = {
                p.id: {"icon": getattr(p, "icon", "") or "", "name": p.name}
                for p in providers
            }
            self.details_pane.set_provider_map(provider_map)
        except Exception as e:
            logger.warning(f"Could not refresh provider map: {e}")
        finally:
            session.close()
    
    def load_history(self):
        """Load playback history into sidebar"""
        if "history" in self.sidebar_sections:
            self.sidebar_sections["history"].refresh()
    
    def load_favorites(self):
        """Load favorites into sidebar"""
        if "favorites" in self.sidebar_sections:
            self.sidebar_sections["favorites"].refresh()
    
    def refresh_provider(self, provider_id: str):
        """Refresh channels from a specific provider"""
        # Prevent duplicate refresh calls
        if provider_id in self.refreshing_providers:
            logger.warning(f"Provider {provider_id} is already being refreshed, ignoring duplicate call")
            return
        
        self.refreshing_providers.add(provider_id)
        logger.info(f"Refreshing provider: {provider_id}")
        
        session = self.db.get_session()
        try:
            from metatv.core.models import Provider
            from metatv.core.provider_loader import ProviderLoadThread
            
            repos = RepositoryFactory(session)
            db_provider = repos.providers.get_by_id(provider_id)
            if not db_provider:
                logger.error(f"Provider not found: {provider_id}")
                return
            
            # Convert to model
            provider = repos.providers.to_model(db_provider)
            
            # Show progress notification
            notif_id = self.notification_manager.show_progress(
                title=f"Refreshing {provider.name}",
                total=100
            )
            
            # Start loading in background thread
            load_thread = ProviderLoadThread(provider, self.db)
            load_thread.provider_id = provider.id  # Store for cleanup
            load_thread.progress.connect(
                lambda cur, tot, msg: self.notification_manager.update_progress(notif_id, cur, tot, msg)
            )
            load_thread.finished.connect(
                lambda success, msg: self.on_provider_refresh_finished(notif_id, success, msg, load_thread)
            )
            
            # Keep thread alive
            self.active_threads.append(load_thread)
            load_thread.start()
            
        finally:
            session.close()
    
    def on_provider_refresh_finished(self, notif_id: str, success: bool, message: str, thread):
        """Handle provider refresh completion"""
        # Remove thread from active list
        if thread in self.active_threads:
            self.active_threads.remove(thread)
        
        # Remove provider from refreshing set
        provider_id = getattr(thread, 'provider_id', None)
        if provider_id:
            if provider_id in self.refreshing_providers:
                self.refreshing_providers.discard(provider_id)
                logger.info(f"Provider {provider_id} refresh completed")
            else:
                logger.warning(f"Provider {provider_id} was not in refreshing set")
        else:
            logger.warning("Provider refresh finished but no provider_id found on thread")
        
        if success:
            self.notification_manager.complete_progress(notif_id, message)
            
            # Update detected prefixes for all channels
            session = self.db.get_session()
            try:
                repos = RepositoryFactory(session)
                logger.info("Updating detected prefixes after provider refresh...")
                updated = repos.channels.update_detected_prefixes(provider_id=None)
                logger.info(f"Updated {updated} channel prefixes")
                
                # Get prefix statistics
                stats = repos.channels.get_prefix_stats(
                    provider_id=None,
                    language_groups=self.config.filter_language_groups,
                    quality_groups=self.config.filter_quality_groups,
                )

                # Update filter bar with current counts
                self.filter_bar.update_filter_groups(
                    language_groups=stats['language_groups'],
                    quality_groups=stats['quality_groups'],
                )
                logger.info(f"Filter stats: {stats['channels_with_prefix']} channels have prefixes")
                
            except Exception as e:
                logger.error(f"Failed to update prefix stats: {e}")
            finally:
                session.close()
            
            # Reload sidebar and channels
            self.load_providers()
            self.load_channels()
        else:
            from metatv.core.notifications import NotificationType
            self.notification_manager.update(
                notif_id,
                type=NotificationType.ERROR,
                title="Refresh Failed",
                message=message,
                dismissible=True,
                auto_dismiss_seconds=5
            )
    
    def on_provider_selected(self, item, column):
        """Handle provider selection in tree"""
        provider_id = item.data(0, Qt.ItemDataRole.UserRole)
        if provider_id:
            self.selected_provider_id = provider_id
            logger.info(f"Selected provider: {provider_id}")
            self.load_channels(provider_id)
    
    def on_provider_selected_new(self, provider_id: str):
        """Handle provider selection from modular sidebar.

        In provider edit mode, clicking a source switches the editor instead of
        filtering the channel list.
        """
        if self._in_provider_edit_mode:
            self.provider_editor.load_provider(provider_id)
            return
        self.selected_provider_id = provider_id
        logger.info(f"Selected provider: {provider_id}")
        self.load_channels(provider_id)
    
    def toggle_filters(self):
        """Toggle filter bar visibility"""
        self.filters_visible = not self.filters_visible
        self.filter_bar.setVisible(self.filters_visible)
        
        if self.filters_visible:
            self.toggle_filters_btn.setText("⚙ Filters ▼")
        else:
            self.toggle_filters_btn.setText("⚙ Filters ▶")
        
        # Save state to config
        self.config.filter_section_visible = self.filters_visible
        self.config.save()
        
        logger.debug(f"Filters visibility: {self.filters_visible}")
    
    def toggle_provider_visibility(self, provider_id: str):
        """Toggle provider visibility (active/disabled)"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider = repos.providers.get_by_id(provider_id)
            if provider:
                # Toggle active state
                provider.is_active = not provider.is_active
                session.commit()
                
                logger.info(f"Provider {provider.name} is now {'active' if provider.is_active else 'disabled'}")
                
                # Update status button
                self.update_provider_status(provider_id, "testing" if provider.is_active else "disabled")
                
                # Reload channels
                self.load_channels()
                
                # Test connection if enabled
                if provider.is_active:
                    self.test_provider_connection(provider_id)
        finally:
            session.close()
    
    def load_channels(self, provider_id=None):
        """Load channels from database into the list"""
        self.channels_list.clear()
        self.all_channels = []
        
        session = self.db.get_session()
        try:
            from metatv.core.database import ChannelDB
            
            repos = RepositoryFactory(session)
            
            # Get filter state from FilterBar
            filter_state = self.current_filter_state or self.filter_bar.get_filter_state()
            
            # Convert language/quality groups to prefix lists
            language_prefixes = []
            for group_name in filter_state.get('language_groups', []):
                prefixes = self.config.filter_language_groups.get(group_name, [])
                language_prefixes.extend(prefixes)

            quality_prefixes = []
            for group_name in filter_state.get('quality_groups', []):
                prefixes = self.config.filter_quality_groups.get(group_name, [])
                quality_prefixes.extend(prefixes)

            # If no specific groups selected, pass None (show all)
            language_prefixes = language_prefixes if language_prefixes else None
            quality_prefixes = quality_prefixes if quality_prefixes else None

            # Get enabled media types
            media_types = filter_state.get('media_types', ['live', 'movie', 'series'])
            show_excluded = filter_state.get('show_excluded', False)
            include_untagged = filter_state.get('include_untagged', True)
            adult_mode = filter_state.get('adult_mode', 'hide')

            # Determine provider filter
            # Start from all active providers, then subtract source-chip exclusions
            active_providers = repos.providers.get_all(active_only=True)
            active_provider_ids = [p.id for p in active_providers]

            # Update source chips in filter bar
            self.filter_bar.update_source_chips(active_providers)

            excluded_ids = set(filter_state.get('excluded_provider_ids', []))

            if provider_id:
                # Sidebar selected a specific provider
                target_provider_id = provider_id
            else:
                visible_ids = [pid for pid in active_provider_ids if pid not in excluded_ids]
                if len(visible_ids) == len(active_provider_ids) and len(visible_ids) == 1:
                    target_provider_id = visible_ids[0]
                elif len(visible_ids) < len(active_provider_ids):
                    # Source chips excluded some — pass the list
                    target_provider_id = visible_ids if visible_ids else None
                else:
                    target_provider_id = None  # show all active

            # Get filtered channels from repository
            # Collect provider IDs that are force_adult so the query can match them
            all_providers = repos.providers.get_all()
            force_adult_ids = [p.id for p in all_providers if getattr(p, 'force_adult', False)]

            channels = repos.channels.get_all(
                provider_id=target_provider_id,
                media_types=media_types,
                language_prefixes=language_prefixes,
                quality_prefixes=quality_prefixes,
                invert_prefix_filters=show_excluded,
                include_untagged=include_untagged,
                adult_mode=adult_mode,
                force_adult_provider_ids=force_adult_ids or None,
            )

            # Show the adult filter only when there are actually adult channels or
            # at least one provider is marked force_adult
            has_adult = bool(force_adult_ids) or session.query(ChannelDB).filter(
                ChannelDB.is_adult == True
            ).limit(1).count() > 0
            self.filter_bar.set_adult_filter_visible(has_adult)
            
            # Sort by name
            channels = sorted(channels, key=lambda c: c.name)
            
            # Get total count for stats
            total_channels = repos.channels.count(provider_id=target_provider_id)
            
            logger.info(f"=== Loading {len(channels)} channels (filtered from {total_channels} total) ===")
            
            if len(channels) == 0:
                logger.warning("No channels match current filters!")
                self.status_bar.showMessage("No channels match filters - try adjusting filter settings")
                # Update filter stats
                self.stats_label.setText(f"Showing 0 of {total_channels:,} · {total_channels:,} filtered out")
                return
            
            # Build provider icon map for multi-provider display
            show_provider_icon = target_provider_id is None
            provider_icon_map: dict = {}
            if show_provider_icon:
                all_provs = repos.providers.get_all()
                for p in all_provs:
                    provider_icon_map[p.id] = (getattr(p, "icon", "") or "📡")

            # Store channels for text filtering
            for channel in channels:
                # Get media type icon
                media_icon = self.get_media_type_icon(channel.media_type)

                # Show favorite status with star icon
                fav_icon = self.favorite_icon if channel.is_favorite else self.unfavorite_icon

                # Provider badge when multiple sources active
                src_badge = ""
                if show_provider_icon and channel.provider_id in provider_icon_map:
                    src_badge = provider_icon_map[channel.provider_id] + " "

                # Format: "[src icon] 📺★ Channel Name [Category] (Quality)"
                display_text = f"{src_badge}{media_icon}{fav_icon} {channel.name}"
                if channel.category:
                    display_text += f" [{channel.category}]"
                if channel.quality and channel.quality != "unknown":
                    display_text += f" ({channel.quality})"

                self.all_channels.append((display_text, channel))
            
            # Update filter stats
            shown = len(channels)
            filtered = total_channels - shown
            self.stats_label.setText(f"Showing {shown:,} of {total_channels:,} · {filtered:,} filtered out")
            
            # Apply current search text filter
            self.filter_channels(self.search_input.text() if hasattr(self, 'search_input') else "")
            
            # Update special content view badges
            if hasattr(self, 'ppv_chip'):
                ppv_count = session.query(ChannelDB).filter(ChannelDB.special_view == 'ppv').count()
                self.ppv_chip.set_count(ppv_count)
            if hasattr(self, 'events_chip'):
                events_count = session.query(ChannelDB).filter(
                    ChannelDB.special_view == 'live_event',
                    ChannelDB.stream_url.isnot(None),
                    ~ChannelDB.name.like('#%'),
                ).count()
                self.events_chip.set_count(events_count)
            if hasattr(self, 'sports_chip'):
                sports_count = session.query(ChannelDB).filter(
                    ChannelDB.special_view == 'sports',
                    ChannelDB.stream_url.isnot(None),
                    ~ChannelDB.name.like('#%'),
                ).count()
                self.sports_chip.set_count(sports_count)
            
            # Update status bar
            if provider_id:
                self.status_bar.showMessage(f"{len(channels):,} channels from selected provider")
            else:
                self.status_bar.showMessage(f"{len(channels):,} channels from active providers")
                
        except Exception as e:
            logger.error(f"Failed to load channels: {e}")
            import traceback
            traceback.print_exc()
        finally:
            session.close()
    
    def filter_channels(self, search_text: str):
        """Filter channels based on search text"""
        # Disable updates while populating for better performance
        self.channels_list.setUpdatesEnabled(False)
        self.channels_list.clear()
        
        search_text = search_text.lower().strip()
        total = len(self.all_channels)
        
        logger.info(f"Filtering {total} channels with search: '{search_text}'")
        
        if not search_text:
            # Show all channels (with limit)
            if total > self.max_display_limit:
                # Too many channels - show message
                item = QListWidgetItem(f"⚠️  Too many channels ({total:,}) to display")
                item.setFlags(Qt.ItemFlag.NoItemFlags)  # Make it non-selectable
                self.channels_list.addItem(item)
                
                item = QListWidgetItem(f"Use the search box above to filter channels")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.channels_list.addItem(item)
                
                item = QListWidgetItem(f"")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.channels_list.addItem(item)
                
                item = QListWidgetItem(f"Try searching for: channel name, category, quality (hd, 4k), etc.")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.channels_list.addItem(item)
                
                self.status_bar.showMessage(f"{total:,} channels - use search to filter")
            else:
                # Show all channels
                for display_text, channel in self.all_channels:
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.ItemDataRole.UserRole, channel.id)
                    self.channels_list.addItem(item)
                
                logger.info(f"Created {total} channel items (showing all)")
                self.status_bar.showMessage(f"{total:,} channels loaded")
        else:
            # Filter channels
            filtered = []
            for display_text, channel in self.all_channels:
                # Search in display text (includes name, category, quality)
                if search_text in display_text.lower():
                    filtered.append((display_text, channel))
                    # Limit filtered results too
                    if len(filtered) >= self.max_display_limit:
                        break
            
            for display_text, channel in filtered:
                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, channel.id)
                self.channels_list.addItem(item)
            
            logger.info(f"Created {len(filtered)} channel items with IDs")
            
            # Update status with filter results
            shown = len(filtered)
            if shown >= self.max_display_limit:
                self.status_bar.showMessage(f"Showing first {shown:,} of {total:,} channels (refine search for more)")
            elif shown > 0:
                self.status_bar.showMessage(f"Showing {shown:,} of {total:,} channels")
            else:
                self.status_bar.showMessage(f"No channels match '{search_text}'")
        
        # Re-enable updates
        self.channels_list.setUpdatesEnabled(True)
    
    def get_enabled_media_types(self) -> list:
        """Get list of enabled media types from chips"""
        types = []
        if self.live_chip.is_enabled():
            types.append("live")
        if self.movies_chip.is_enabled():
            types.append("movie")
        if self.series_chip.is_enabled():
            types.append("series")
        return types
    
    def on_filter_changed(self):
        """Handle filter changes from FilterBar or media chips"""
        logger.info("Filter changed, reloading channels...")
        # Get filter state from FilterBar and add media types from chips
        self.current_filter_state = self.filter_bar.get_filter_state()
        self.current_filter_state['media_types'] = self.get_enabled_media_types()
        self.load_channels(self.selected_provider_id)
    
    def initialize_filter_stats(self):
        """Initialize filter bar with current prefix statistics"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            
            # Get prefix statistics
            stats = repos.channels.get_prefix_stats(
                provider_id=None,
                language_groups=self.config.filter_language_groups,
                quality_groups=self.config.filter_quality_groups,
            )

            # Update filter bar with current counts
            self.filter_bar.update_filter_groups(
                language_groups=stats['language_groups'],
                quality_groups=stats['quality_groups'],
            )

            logger.info(f"Initialized filter stats: {stats['channels_with_prefix']} channels with prefixes")
            
        except Exception as e:
            logger.error(f"Failed to initialize filter stats: {e}")
        finally:
            session.close()
    
    def show_history_context_menu(self, position, list_widget=None):
        """Show context menu for history list"""
        # Use provided list widget or try to get from modular section
        if list_widget is None:
            if "history" in self.sidebar_sections:
                list_widget = self.sidebar_sections["history"].history_list
            else:
                return
        
        item = list_widget.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        
        session = self.db.get_session()
        try:
            from PyQt6.QtWidgets import QMenu
            from PyQt6.QtGui import QAction
            
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                return
            
            menu = QMenu()
            
            # Add/Remove favorite
            if channel.is_favorite:
                fav_action = QAction(f"Remove from Favorites ({self.unfavorite_icon})", self)
            else:
                fav_action = QAction(f"Add to Favorites ({self.favorite_icon})", self)
            fav_action.triggered.connect(lambda: self.toggle_favorite(item))
            menu.addAction(fav_action)
            
            menu.addSeparator()
            
            # Remove from history
            remove_action = QAction(f"Remove from History ({self.delete_icon})", self)
            remove_action.triggered.connect(lambda: self.remove_from_history(channel_id))
            menu.addAction(remove_action)
            
            menu.addSeparator()
            
            play_action = QAction("Play", self)
            play_action.triggered.connect(lambda: self.play_from_history(item))
            menu.addAction(play_action)
            
            menu.exec(list_widget.mapToGlobal(position))
        finally:
            session.close()
    
    def play_from_history(self, item):
        """Play a channel from history"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        
        # Reuse existing play_channel logic
        self.play_channel(item)
    
    def play_from_history_id(self, channel_id: str):
        """Play a channel from history by ID"""
        with self.db.get_session() as session:
            from metatv.core.models import MediaType
            
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                # Check if series
                if channel.media_type == MediaType.SERIES:
                    # Find last played episode and play it
                    last_episode = repos.episodes.get_last_played(
                        series_id=channel.source_id,
                        provider_id=channel.provider_id
                    )
                    
                    if last_episode:
                        logger.info(f"Playing last watched episode from history: {last_episode.title}")
                        self.play_episode(last_episode)
                    else:
                        # No episode history, open series view
                        logger.info("No episode history found, opening series view")
                        self.drill_into_series(channel)
                else:
                    self.play_media(channel)
    
    def remove_from_history(self, channel_id: str):
        """Remove a single channel from history"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                channel_name = channel.name
                repos.channels.remove_from_history(channel_id)
                
                self.status_bar.showMessage(f"Removed {channel_name} from history")
                logger.info(f"Removed {channel_name} from history")
                
                # Reload history
                self.load_history()
        finally:
            session.close()
    
    def clear_history(self):
        """Clear all history"""
        from PyQt6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to clear all playback history?\n\nThis will not remove favorites.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            session = self.db.get_session()
            try:
                repos = RepositoryFactory(session)
                count = repos.channels.clear_history()
                
                self.status_bar.showMessage("History cleared")
                logger.info("Cleared all playback history")
                
                # Reload history and favorites (favorites may need updating to show unwatched)
                self.load_history()
                self.load_favorites()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to clear history: {e}")
                self.status_bar.showMessage(f"Error clearing history: {e}")
            finally:
                session.close()
    
    def show_favorites_context_menu(self, position, list_widget=None):
        """Show context menu for favorites list"""
        # Use provided list widget or fallback to legacy self.favorites_list
        if list_widget is None:
            if hasattr(self, 'favorites_list'):
                list_widget = self.favorites_list
            else:
                return
        
        item = list_widget.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        menu = QMenu()
        
        remove_action = QAction(f"Remove from Favorites ({self.unfavorite_icon})", self)
        remove_action.triggered.connect(lambda: self.toggle_favorite(item))
        menu.addAction(remove_action)
        
        play_action = QAction("Play", self)
        play_action.triggered.connect(lambda: self.play_favorite(item))
        menu.addAction(play_action)
        
        menu.exec(list_widget.mapToGlobal(position))
    
    def show_channel_context_menu(self, position):
        """Show context menu for channel list"""
        item = self.channels_list.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        
        session = self.db.get_session()
        try:
            from PyQt6.QtWidgets import QMenu
            from PyQt6.QtGui import QAction
            
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                return
            
            menu = QMenu()
            
            # Add/Remove favorite
            if channel.is_favorite:
                fav_action = QAction(f"Remove from Favorites ({self.unfavorite_icon})", self)
            else:
                fav_action = QAction(f"Add to Favorites ({self.favorite_icon})", self)
            fav_action.triggered.connect(lambda: self.toggle_favorite(item))
            menu.addAction(fav_action)
            
            menu.addSeparator()
            
            play_action = QAction("Play", self)
            play_action.triggered.connect(lambda: self.play_channel(item))
            menu.addAction(play_action)
            
            menu.exec(self.channels_list.mapToGlobal(position))
        finally:
            session.close()
    
    def play_favorite(self, item):
        """Play a favorite channel"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        
        # Reuse existing play_channel logic
        self.play_channel(item)
    
    def play_favorite_id(self, channel_id: str):
        """Play a favorite channel by ID"""
        with self.db.get_session() as session:
            from metatv.core.models import MediaType
            
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                # Check if series
                if channel.media_type == MediaType.SERIES:
                    self.drill_into_series(channel)
                else:
                    self.play_media(channel)
    
    def toggle_favorite(self, item):
        """Toggle favorite status of a channel"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                # Toggle favorite status
                new_status = repos.channels.toggle_favorite(channel_id)
                channel.is_favorite = new_status
                
                status = "added to" if channel.is_favorite else "removed from"
                self.status_bar.showMessage(f"{channel.name} {status} favorites")
                logger.info(f"Toggled favorite for {channel.name}: {channel.is_favorite}")
                
                # Update the icon on the current item only (fast, no database query)
                current_text = item.text()
                if channel.is_favorite:
                    # Replace unfavorite icon with favorite icon
                    updated_text = current_text.replace(self.unfavorite_icon, self.favorite_icon)
                else:
                    # Replace favorite icon with unfavorite icon
                    updated_text = current_text.replace(self.favorite_icon, self.unfavorite_icon)
                item.setText(updated_text)
                
                # Also update in all_channels cache for filtering
                for i, (text, ch) in enumerate(self.all_channels):
                    if ch.id == channel_id:
                        ch.is_favorite = channel.is_favorite
                        # Update cached display text
                        media_icon = self.get_media_type_icon(ch.media_type)
                        fav_icon = self.favorite_icon if ch.is_favorite else self.unfavorite_icon
                        display_text = f"{media_icon}{fav_icon} {ch.name}"
                        if ch.category:
                            display_text += f" [{ch.category}]"
                        if ch.quality and ch.quality != "unknown":
                            display_text += f" ({ch.quality})"
                        self.all_channels[i] = (display_text, ch)
                        break
                
                # Only refresh favorites sidebar (fast, no full reload)
                self.load_favorites()
        finally:
            session.close()
    
    def show_channel_details_by_id(self, channel_id: str):
        """Show channel details in details pane (for sidebar selections)"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                self.update_details_pane_for_channel(channel)
        finally:
            session.close()
    
    def on_channel_selection_changed(self, current, previous):
        """Handle channel selection change - update details pane"""
        if not current:
            return
        
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                self.update_details_pane_for_channel(channel)
        finally:
            session.close()
    
    def update_details_pane_for_channel(self, channel):
        """Update details pane with channel metadata (async)"""
        from concurrent.futures import ThreadPoolExecutor
        import asyncio
        
        # Get provider URLs for image failover
        provider_urls = []
        try:
            session = self.db.get_session()
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(channel.provider_id)
            if provider_db and provider_db.urls:
                import json
                urls_data = json.loads(provider_db.urls) if isinstance(provider_db.urls, str) else provider_db.urls
                provider_urls = [u.get('url') for u in urls_data if u.get('is_active', True) and u.get('url')]
            session.close()
            logger.debug(f"Provider URLs for failover: {provider_urls}")
        except Exception as e:
            logger.warning(f"Could not fetch provider URLs: {e}")
        
        # Set provider URLs in details pane
        self.details_pane.set_provider_urls(provider_urls)
        
        # Show basic channel info immediately (Tier 1 - instant)
        self.details_pane.show_channel(channel, metadata=None)
        logger.debug(f"Showing basic info for: {channel.name}")
        
        # Fetch metadata in background thread
        def fetch_metadata():
            logger.debug(f"=== fetch_metadata() thread started for {channel.name}")
            try:
                # Create a new event loop for this thread
                logger.debug("Creating event loop...")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                logger.debug(f"Fetching metadata for: {channel.name} (id={channel.id})")
                logger.debug(f"Calling metadata_manager.get_metadata({channel.id})...")
                
                metadata = loop.run_until_complete(
                    self.metadata_manager.get_metadata(channel.id)
                )
                
                logger.debug(f"get_metadata returned: {metadata}")
                loop.close()
                
                if metadata:
                    logger.info(f"Metadata fetched for {channel.name}: plot={bool(metadata.plot)}, cast={len(metadata.cast)}, poster={bool(metadata.poster_url)}")
                else:
                    logger.warning(f"No metadata returned for {channel.name}")
                
                return metadata
            except Exception as e:
                logger.error(f"Failed to load metadata for {channel.name}: {e}", exc_info=True)
                return None
        
        def on_metadata_loaded(future):
            try:
                metadata = future.result()
                logger.debug(f"on_metadata_loaded called, metadata={metadata is not None}")
                if metadata:
                    logger.debug(f"Emitting metadata_loaded signal for {channel.name}")
                    # Emit signal for thread-safe UI update on main thread
                    self.metadata_loaded.emit(channel, metadata)
                else:
                    logger.warning(f"on_metadata_loaded: No metadata returned for {channel.name}")
            except Exception as e:
                logger.error(f"Error in on_metadata_loaded: {e}", exc_info=True)
        
        # Submit to thread pool
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fetch_metadata)
        future.add_done_callback(on_metadata_loaded)
    
    def _update_details_with_metadata(self, channel, metadata):
        """Update details pane with metadata (called on main thread)"""
        try:
            logger.debug(f"_update_details_with_metadata called for {channel.name}")
            logger.debug(f"Metadata has plot: {bool(metadata.plot)}, cast: {len(metadata.cast) if metadata.cast else 0}")
            self.details_pane.show_channel(channel, metadata=metadata)
            logger.debug(f"Details pane updated with metadata for {channel.name}")
        except Exception as e:
            logger.error(f"Error updating details pane: {e}", exc_info=True)
    
    def play_channel_by_id(self, channel_id: str):
        """Play channel by ID (for details pane Play button)"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                from metatv.core.models import MediaType
                if channel.media_type == MediaType.SERIES:
                    self.drill_into_series(channel)
                else:
                    self.play_media(channel)
        finally:
            session.close()
    
    def toggle_favorite_by_id(self, channel_id: str):
        """Toggle favorite by ID (for details pane Favorite button)"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                new_status = repos.channels.toggle_favorite(channel_id)
                channel.is_favorite = new_status
                
                status = "added to" if channel.is_favorite else "removed from"
                self.status_bar.showMessage(f"{channel.name} {status} favorites")
                
                # Update details pane to reflect new favorite status
                self.update_details_pane_for_channel(channel)
                
                # Refresh favorites sidebar
                self.load_favorites()
                
                # Update channel list display if visible
                for i in range(self.channels_list.count()):
                    item = self.channels_list.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == channel_id:
                        current_text = item.text()
                        if channel.is_favorite:
                            updated_text = current_text.replace(self.unfavorite_icon, self.favorite_icon)
                        else:
                            updated_text = current_text.replace(self.favorite_icon, self.unfavorite_icon)
                        item.setText(updated_text)
                        break
        finally:
            session.close()
    
    def play_channel(self, item):
        """Play selected channel in external player or drill down into series"""
        logger.info(f"=== play_channel called ===")
        logger.info(f"Item type: {type(item)}")
        logger.info(f"Item text: {item.text() if hasattr(item, 'text') else 'N/A'}")
        
        try:
            channel_id = item.data(Qt.ItemDataRole.UserRole)
            logger.info(f"Channel ID from item data: {channel_id}")
        except Exception as e:
            logger.error(f"Error getting channel ID: {e}")
            self.status_bar.showMessage(f"Error: Cannot get channel ID - {e}")
            return
        
        if not channel_id:
            logger.warning("No channel ID found for selected item")
            self.status_bar.showMessage("Cannot play this item - no channel ID")
            return
        
        # Get channel from database to check media type
        session = self.db.get_session()
        try:
            from metatv.core.models import MediaType
            
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            
            if not channel:
                logger.error(f"Channel not found: {channel_id}")
                self.status_bar.showMessage("Error: Channel not found")
                return
            
            # Check if this is a series - if so, drill down instead of playing
            if channel.media_type == MediaType.SERIES:
                logger.info(f"Series detected: {channel.name}, drilling down...")
                self.drill_into_series(channel)
                return
            
            # For live and movies, proceed with playback
            self.play_media(channel)
            
        except Exception as e:
            logger.error(f"Error in play_channel: {e}")
            self.status_bar.showMessage(f"Error: {e}")
        finally:
            session.close()
    
    def drill_into_series(self, channel):
        """Drill down into series to show seasons/episodes"""
        logger.info(f"Drilling into series: {channel.name}")
        self.current_series = channel
        
        # Get provider info
        from metatv.core.models import Provider
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(channel.provider_id)

            if not provider_db:
                self.status_bar.showMessage("Error: Provider not found")
                return

            provider = repos.providers.to_model(provider_db)
        finally:
            session.close()
        
        # Start loading series in background
        load_thread = SeriesLoadThread(
            provider=provider,
            series_id=channel.source_id,
            series_name=channel.name,
            db=self.db
        )
        load_thread.finished.connect(self.on_series_loaded)
        load_thread.progress.connect(lambda msg: self.status_bar.showMessage(msg))
        
        # Store thread to prevent garbage collection
        self.active_threads.append(load_thread)
        load_thread.start()
        
        # Show loading notification
        notification_id = self.notification_manager.show_progress(
            title=f"Loading {channel.name}"
        )
        load_thread.notification_id = notification_id
    
    def on_series_loaded(self, success, message, series_data):
        """Handle series data loaded"""
        thread = self.sender()
        
        # Dismiss notification
        if hasattr(thread, 'notification_id'):
            if success:
                self.notification_manager.complete_progress(
                    thread.notification_id,
                    f"Loaded {message}"
                )
            else:
                from metatv.core.notifications import NotificationType
                self.notification_manager.update(
                    thread.notification_id,
                    type=NotificationType.ERROR,
                    title="Series Load Failed",
                    message=message,
                    dismissible=True,
                    auto_dismiss_seconds=5
                )
        
        # Remove thread
        if thread in self.active_threads:
            self.active_threads.remove(thread)
        
        if not success:
            logger.error(f"Failed to load series: {message}")
            self.status_bar.showMessage(f"Error: {message}")
            return
        
        # Store series data and switch to series view
        self.series_data = series_data
        self.switch_to_series_view()
    
    def switch_to_series_view(self):
        """Switch content area to series tree view"""
        self.view_mode = "series"
        
        # Hide list and special views, show tree
        self.channels_list.setVisible(False)
        self.series_tree.setVisible(True)
        self.ppv_view.setVisible(False)
        
        # Show back button and breadcrumb
        self.back_button.setVisible(True)
        self.breadcrumb_label.setText(f"{self.series_icon} {self.current_series.name}")
        
        # Disable search for now (could add series-specific search later)
        self.search_input.setEnabled(False)
        self.search_input.setPlaceholderText("Search not available in series view")
        
        # Populate series tree
        self.populate_series_tree()
        
        self.status_bar.showMessage(f"Viewing series: {self.current_series.name}")
    
    def switch_to_list_view(self):
        """Switch content area back to channel list view"""
        self.view_mode = "list"
        
        # Show list, hide tree and special views
        self._in_provider_edit_mode = False
        self.channels_list.setVisible(True)
        self.series_tree.setVisible(False)
        self.ppv_view.setVisible(False)
        self.events_view.setVisible(False)
        self.sports_view.setVisible(False)
        self.provider_editor.setVisible(False)
        
        # Hide back button
        self.back_button.setVisible(False)
        self.breadcrumb_label.setText("")
        
        # Restore search bar and filter bar
        self.search_controls.setVisible(True)
        self.filter_bar.setVisible(self.filters_visible)
        self.search_input.setEnabled(True)
        self.search_input.setPlaceholderText("Filter channels by name, category...")
        
        # Restore channel stats (based on all_channels list)
        if hasattr(self, 'all_channels') and self.all_channels:
            total_channels = len(self.all_channels)
            # Count what's actually in the list view currently
            shown = self.channels_list.count()
            # Subtract non-channel items (warnings, messages, etc.)
            for i in range(self.channels_list.count()):
                item = self.channels_list.item(i)
                if not item.data(Qt.ItemDataRole.UserRole):  # No channel data = message item
                    shown -= 1
            
            filtered = total_channels - shown
            if filtered > 0:
                self.stats_label.setText(f"Showing {shown:,} of {total_channels:,} · {filtered:,} filtered out")
            else:
                self.stats_label.setText(f"Showing {shown:,} of {total_channels:,} channels")
        
        # Clear series data
        self.current_series = None
        self.series_data = None
        
        self.status_bar.showMessage("Returned to channel list")
    
    def switch_to_ppv_view(self):
        """Switch content area to PPV view"""
        self.view_mode = "ppv"

        self.channels_list.setVisible(False)
        self.series_tree.setVisible(False)
        self.events_view.setVisible(False)
        self.sports_view.setVisible(False)
        self.epg_view.setVisible(False)
        self.ppv_view.setVisible(True)
        
        # Hide back button
        self.back_button.setVisible(False)
        self.breadcrumb_label.setText("")
        
        self.search_controls.setVisible(False)
        
        # Activate PPV view (loads events)
        self.ppv_view.on_activate()
        
        # Update stats
        ppv_count = self.ppv_view.get_ppv_event_count()
        self.stats_label.setText(f"{ppv_count} PPV events")
    
    def switch_to_events_view(self):
        """Switch content area to Events view."""
        self.view_mode = "events"

        self.channels_list.setVisible(False)
        self.series_tree.setVisible(False)
        self.ppv_view.setVisible(False)
        self.sports_view.setVisible(False)
        self.epg_view.setVisible(False)
        self.events_view.setVisible(True)

        self.back_button.setVisible(False)
        self.breadcrumb_label.setText("")

        self.search_controls.setVisible(False)

        self.events_view.on_activate()

        count = self.events_view.get_events_channel_count()
        self.stats_label.setText(f"{count:,} live events")

    def switch_to_sports_view(self):
        """Switch content area to Sports view."""
        self.view_mode = "sports"

        self.channels_list.setVisible(False)
        self.series_tree.setVisible(False)
        self.ppv_view.setVisible(False)
        self.events_view.setVisible(False)
        self.epg_view.setVisible(False)
        self.sports_view.setVisible(True)

        self.back_button.setVisible(False)
        self.breadcrumb_label.setText("")

        self.search_controls.setVisible(False)

        self.sports_view.on_activate()

        count = self.sports_view.get_sports_channel_count()
        self.stats_label.setText(f"{count:,} sports channels")

    def switch_to_epg_view(self):
        """Switch content area to EPG view."""
        self.view_mode = "epg"

        self.channels_list.setVisible(False)
        self.series_tree.setVisible(False)
        self.ppv_view.setVisible(False)
        self.events_view.setVisible(False)
        self.sports_view.setVisible(False)
        self.epg_view.setVisible(True)

        self.back_button.setVisible(False)
        self.breadcrumb_label.setText("")
        self.search_controls.setVisible(False)

        self.epg_view.on_activate()

        total = self.epg_manager.get_total_programmes(self.epg_view._provider_ids)
        if total:
            self.stats_label.setText(f"{total:,} EPG programmes")
        else:
            self.stats_label.setText("EPG — fetching…")

    def play_special_event(self, channel):
        """Play a channel from EventsView or SportsView."""
        logger.info(f"Playing special event: {channel.name}")

        if not channel.stream_url:
            self.status_bar.showMessage(f"No stream URL available for {channel.name}")
            return

        self.player_manager.play(channel.stream_url, channel.name)

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.mark_played(channel.id)
        finally:
            session.close()

        self.status_bar.showMessage(f"Playing: {channel.name}")

    def _on_view_channel_selected(self, channel):
        """Handle channel selected from SportsView or EventsView."""
        if channel:
            self.details_pane.show_channel(channel)

    def on_special_view_toggle(self):
        """Handle special content view chip toggles"""
        sender = self.sender()
        
        # Determine which chip was clicked
        if sender == self.ppv_chip:
            if self.ppv_chip.is_enabled():
                self.events_chip.set_enabled(False)
                self.sports_chip.set_enabled(False)
                self.epg_chip.set_enabled(False)
                self.switch_to_ppv_view()
            else:
                self.switch_to_list_view()

        elif sender == self.events_chip:
            if self.events_chip.is_enabled():
                self.ppv_chip.set_enabled(False)
                self.sports_chip.set_enabled(False)
                self.epg_chip.set_enabled(False)
                self.switch_to_events_view()
            else:
                self.switch_to_list_view()

        elif sender == self.sports_chip:
            if self.sports_chip.is_enabled():
                self.ppv_chip.set_enabled(False)
                self.events_chip.set_enabled(False)
                self.epg_chip.set_enabled(False)
                self.switch_to_sports_view()
            else:
                self.switch_to_list_view()

        elif sender == self.epg_chip:
            if self.epg_chip.is_enabled():
                self.ppv_chip.set_enabled(False)
                self.events_chip.set_enabled(False)
                self.sports_chip.set_enabled(False)
                self.switch_to_epg_view()
            else:
                self.switch_to_list_view()
    
    def play_ppv_event(self, channel):
        """Play PPV event from PPV view"""
        logger.info(f"Playing PPV event: {channel.name}")
        
        # Validate stream URL
        if not channel.stream_url:
            self.status_bar.showMessage(f"No stream URL available for {channel.name}")
            return
        
        # Play through player manager
        self.player_manager.play(channel.stream_url, channel.name)
        
        # Update play count and last_played
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.mark_played(channel.id)
        finally:
            session.close()

        self.status_bar.showMessage(f"Playing: {channel.name}")
    
    def navigate_back(self):
        """Navigate back from series view to channel list"""
        self.switch_to_list_view()
    
    def populate_series_tree(self):
        """Populate the series tree widget with seasons and episodes"""
        self.series_tree.clear()
        
        if not self.series_data:
            logger.warning("No series data available for tree population")
            return
        
        # Get seasons and episodes from database
        # Note: series_id in SeasonDB is the provider's source_id, not the database UUID
        with self.db.get_session() as session:
            repos = RepositoryFactory(session)
            seasons = repos.seasons.get_by_series(
                series_id=self.current_series.source_id,
                provider_id=self.current_series.provider_id
            )
            
            logger.info(f"Found {len(seasons)} seasons in database for series {self.current_series.source_id}")
            
            total_episodes = 0
            
            for season in seasons:
                # Create season item
                season_item = QTreeWidgetItem(self.series_tree)
                season_item.setText(0, f"{self.season_icon} {season.name}")
                season_item.setText(1, f"{season.episode_count} episodes")
                
                # Extract rating from season raw_data if available
                if season.raw_data and isinstance(season.raw_data, dict):
                    rating = season.raw_data.get("rating", "")
                    if rating:
                        season_item.setText(3, f"★ {rating}")
                
                season_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "season", "data": season})
                
                logger.debug(f"Added season: {season.name} ({season.episode_count} episodes)")
                
                # Get episodes for this season
                repos = RepositoryFactory(session)
                episodes = repos.episodes.get_by_season(season_id=season.id)
                total_episodes += len(episodes)
                
                logger.debug(f"Found {len(episodes)} episodes for {season.name}")
                
                for episode in episodes:
                    # Create episode item
                    episode_item = QTreeWidgetItem(season_item)
                    watched_indicator = "✓ " if episode.is_watched else ""
                    episode_item.setText(0, f"  {self.episode_icon} {watched_indicator}{episode.title}")
                    
                    # Episode number
                    episode_item.setText(1, f"E{episode.episode_num}")
                    
                    # Duration
                    if episode.duration:
                        episode_item.setText(2, episode.duration)
                    
                    # Rating from episode raw_data
                    if episode.raw_data and isinstance(episode.raw_data, dict):
                        info = episode.raw_data.get("info", {})
                        if isinstance(info, dict):
                            rating = info.get("rating", "")
                            if rating:
                                episode_item.setText(3, f"★ {rating}")
                    
                    episode_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": episode})
                
                # Initially collapse seasons
                season_item.setExpanded(False)
            
            # Update stats label with season/episode counts
            if len(seasons) == 0:
                self.stats_label.setText("No items to display")
            else:
                # Use generic "items" term since it could be Seasons, Specials, etc.
                season_word = "item" if len(seasons) == 1 else "items"
                episode_word = "episode" if total_episodes == 1 else "episodes"
                self.stats_label.setText(f"Showing {len(seasons)} {season_word} · {total_episodes} {episode_word}")
    
    def on_tree_item_expanded(self, item):
        """Handle tree item expanded (no-op, using native arrows)"""
        pass
    
    def on_tree_item_collapsed(self, item):
        """Handle tree item collapsed (no-op, using native arrows)"""
        pass
    
    def play_series_item(self, item, column):
        """Handle double-click on series tree item"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        
        if not data:
            logger.warning("Double-click on tree item with no UserRole data")
            return
        
        item_type = data.get("type")
        logger.info(f"Double-clicked tree item: type={item_type}, expanded={item.isExpanded()}")
        
        if item_type == "season":
            # Toggle expand/collapse on double-click
            new_state = not item.isExpanded()
            item.setExpanded(new_state)
            logger.info(f"Toggled season expansion: {new_state}")
        elif item_type == "episode":
            # Play episode
            episode = data["data"]
            self.play_episode(episode)
    
    def play_episode(self, episode):
        """Play an episode and optionally queue subsequent episodes"""
        logger.info(f"Playing episode: {episode.title}")
        
        if not episode.stream_url:
            self.status_bar.showMessage("Error: No stream URL for episode")
            return
        
        self.status_bar.showMessage(f"Playing: {episode.title}")
        
        # Record playback
        from datetime import datetime
        with self.db.get_session() as session:
            repos = RepositoryFactory(session)
            
            # Update episode playback
            repos.episodes.mark_played(episode.id)
            
            logger.info(f"Episode playback recorded: {episode.title}")
            logger.info(f"  Episode series_id: {episode.series_id}")
            logger.info(f"  Episode provider_id: {episode.provider_id}")
            
            # Also update the parent series channel for history tracking
            parent_channel = repos.channels.get_by_source_id(
                provider_id=episode.provider_id,
                source_id=episode.series_id
            )
            
            if parent_channel:
                repos.channels.mark_played(parent_channel.id)
                logger.info(f"Updated parent series playback: {parent_channel.name} (play count: {parent_channel.play_count})")
            else:
                logger.warning(f"Could not find parent channel for episode. series_id={episode.series_id}, provider_id={episode.provider_id}")
            
            # Get subsequent episodes to queue if auto-queue is enabled
            episodes_to_queue = []
            if self.config.autoplay_season_episodes and episode.season_id:
                # Get all episodes in this season
                all_episodes = repos.episodes.get_by_season(season_id=episode.season_id)
                
                # Filter for episodes that come after the current one
                episodes_to_queue = [
                    ep for ep in all_episodes 
                    if ep.episode_num > episode.episode_num
                ]
                
                # Sort by episode number
                episodes_to_queue.sort(key=lambda ep: ep.episode_num)
                
                if episodes_to_queue:
                    episode_range = f"E{episodes_to_queue[0].episode_num}-E{episodes_to_queue[-1].episode_num}"
                    logger.info(f"Will queue {len(episodes_to_queue)} subsequent episodes: {episode_range}")
                    logger.debug(f"Queue list: {[f'E{ep.episode_num}: {ep.title}' for ep in episodes_to_queue]}")
        
        # Update UI lists in real-time
        self.load_history()
        self.load_favorites()
        
        # Launch player with first episode
        self.launch_player_for_episode(episode.stream_url, episode.title, episodes_to_queue)
    
    def launch_player_for_episode(self, stream_url, title, queue_episodes=None):
        """Launch media player for an episode and queue subsequent episodes
        
        Args:
            stream_url: URL of the episode to play
            title: Title of the episode
            queue_episodes: Optional list of EpisodeDB objects to queue after current episode
        """
        if not self.player_manager.is_available():
            logger.error("No media player available")
            self.status_bar.showMessage("Error: No media player found. Please install mpv.")
            return
        
        # Play first episode using player manager
        logger.info(f"Playing first episode: {title}")
        if self.player_manager.play(stream_url, title):
            
            # Queue subsequent episodes if provided
            if queue_episodes:
                from metatv.core.players.base import QueueMode
                queued_count = 0
                
                logger.info(f"Queueing {len(queue_episodes)} subsequent episodes...")
                for ep in queue_episodes:
                    if ep.stream_url:
                        if self.player_manager.queue(ep.stream_url, ep.title, QueueMode.APPEND):
                            queued_count += 1
                            logger.debug(f"Queued E{ep.episode_num}: {ep.title}")
                        else:
                            logger.warning(f"Failed to queue E{ep.episode_num}: {ep.title}")
                
                if queued_count > 0:
                    status_msg = f"Playing: {title} (+{queued_count} queued)"
                    logger.info(f"Successfully queued {queued_count}/{len(queue_episodes)} episodes")
                    logger.warning(f"Note: mpv limitation - queued episodes will show current title until they start playing")
                else:
                    status_msg = f"Playing: {title}"
            else:
                status_msg = f"Playing: {title}"
            
            QTimer.singleShot(2000, lambda: self.status_bar.showMessage(status_msg))
        else:
            logger.error(f"Failed to play episode: {title}")
            self.status_bar.showMessage(f"Error playing: {title}")
    
    
    def show_series_context_menu(self, position):
        """Show context menu for series tree items"""
        item = self.series_tree.itemAt(position)
        if not item:
            return
        
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        menu = QMenu(self)
        
        if data["type"] == "episode":
            episode = data["data"]
            
            play_action = QAction(f"{self.play_icon} Play Episode", self)
            play_action.triggered.connect(lambda: self.play_episode(episode))
            menu.addAction(play_action)
            
            if episode.is_watched:
                mark_unwatched_action = QAction("Mark as Unwatched", self)
                mark_unwatched_action.triggered.connect(lambda: self.toggle_episode_watched(episode))
                menu.addAction(mark_unwatched_action)
            else:
                mark_watched_action = QAction("Mark as Watched", self)
                mark_watched_action.triggered.connect(lambda: self.toggle_episode_watched(episode))
                menu.addAction(mark_watched_action)
        
        elif data["type"] == "season":
            season = data["data"]
            
            expand_action = QAction("Expand All Episodes", self)
            expand_action.triggered.connect(lambda: item.setExpanded(True))
            menu.addAction(expand_action)
            
            collapse_action = QAction("Collapse", self)
            collapse_action.triggered.connect(lambda: item.setExpanded(False))
            menu.addAction(collapse_action)
        
        menu.exec(self.series_tree.viewport().mapToGlobal(position))
    
    def toggle_episode_watched(self, episode):
        """Toggle episode watched status"""
        with self.db.get_session() as session:
            repos = RepositoryFactory(session)
            repos.episodes.mark_watched(episode.id, not episode.is_watched)
            logger.info(f"Toggled watched status for episode: {episode.title}")
        
        # Refresh the tree to update display
        self.populate_series_tree()
    
    def validate_stream_url(self, url: str, timeout: int = 5) -> bool:
        """Validate a stream URL by reading its first bytes.

        Sends a streaming GET request and confirms that the server delivers
        data — the same thing mpv would do.  HEAD requests are unreliable for
        IPTV (servers often return 5xx on HEAD while serving fine on GET).
        """
        try:
            from metatv.providers.xtream import _DEFAULT_HEADERS
            logger.debug(f"Validating stream URL: {url}")
            with requests.get(
                url,
                stream=True,
                timeout=(timeout, timeout),
                allow_redirects=True,
                headers=_DEFAULT_HEADERS,
            ) as response:
                if response.status_code >= 400:
                    logger.warning(f"Stream URL returned HTTP {response.status_code}")
                    return False
                # Read a small chunk — confirms the server is actually streaming
                chunk = next(response.iter_content(chunk_size=64), None)
                if chunk is None:
                    logger.warning(f"Stream URL returned no data")
                    return False
                logger.debug(f"Stream URL validated: HTTP {response.status_code}, got {len(chunk)} bytes")
                return True
        except requests.exceptions.Timeout:
            logger.warning(f"Stream URL validation timeout: {url}")
            return False
        except requests.exceptions.ConnectionError:
            logger.warning(f"Stream URL connection failed: {url}")
            return False
        except Exception as e:
            logger.warning(f"Stream URL validation error: {e}")
            return False
    
    def validate_and_failover_stream_url(self, stream_url: str, provider_id: str, 
                                          source_id: str, media_type: str) -> str:
        """Validate stream URL and try alternate provider URLs if needed
        
        Args:
            stream_url: Original stream URL
            provider_id: Provider ID for looking up alternates
            source_id: Channel's source ID (stream ID from provider)
            media_type: Type of media (live/movie/series)
            
        Returns:
            Working URL or empty string if all failed
        """
        # First try the original URL
        if self.validate_stream_url(stream_url):
            return stream_url
        
        logger.warning(f"Primary URL failed validation: {stream_url}")
        
        # Extract base URL from stream URL
        parsed = urlparse(stream_url)
        original_base = f"{parsed.scheme}://{parsed.netloc}"
        
        # Try to reconstruct URL with alternate provider domains
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(provider_id)
            
            if not provider_db:
                logger.error(f"Provider not found: {provider_id}")
                return ""
            
            provider_model = repos.providers.to_model(provider_db)
            candidate_bases = [u for u in provider_model.ordered_urls() if u.rstrip('/') != original_base]

            if not candidate_bases:
                logger.warning(f"Provider {provider_db.name} has no alternate URLs configured")
                logger.error("No working alternate URLs found")
                return ""

            logger.info(f"Trying {len(candidate_bases)} alternate URL(s) for {provider_db.name} (reliability order)")

            raw_urls = provider_db.urls or []
            if isinstance(raw_urls, str):
                import json as _json
                raw_urls = _json.loads(raw_urls)

            for alt_base in candidate_bases:
                new_stream_url = self.reconstruct_stream_url(stream_url, original_base, alt_base)
                logger.info(f"Trying: {new_stream_url}")

                url_entry = next((u for u in raw_urls if u.get('url', '').rstrip('/') == alt_base), None)
                if self.validate_stream_url(new_stream_url):
                    logger.info("Alternate URL validated successfully")
                    if url_entry:
                        url_entry['success_count'] = url_entry.get('success_count', 0) + 1
                        url_entry['last_success'] = datetime.now().isoformat()
                        provider_db.urls = raw_urls
                        repos.providers.update(provider_db)
                        session.commit()
                    return new_stream_url
                else:
                    if url_entry:
                        url_entry['failure_count'] = url_entry.get('failure_count', 0) + 1
                        url_entry['last_failure'] = datetime.now().isoformat()
                        provider_db.urls = raw_urls
                        repos.providers.update(provider_db)
                        session.commit()

            logger.error("No working alternate URLs found")
            return ""
            
        finally:
            session.close()
    
    def reconstruct_stream_url(self, original_url: str, old_base: str, new_base: str) -> str:
        """Reconstruct stream URL with new base domain
        
        Args:
            original_url: Original full stream URL
            old_base: Old base URL to replace
            new_base: New base URL
            
        Returns:
            Reconstructed URL
        """
        # Simple string replacement
        if original_url.startswith(old_base):
            return original_url.replace(old_base, new_base, 1)
        return original_url
    
    def play_media(self, channel):
        """Play a media item (live stream or movie) in external player"""
        channel_id = channel.id
        
        # Prevent double-clicks while loading
        if channel_id in self.loading_channels:
            logger.info(f"Channel {channel_id} is already loading, ignoring double-click")
            self.status_bar.showMessage("Already loading this channel...")
            return
        
        self.loading_channels.add(channel_id)
        
        # Get a fresh session for playback recording
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            # Refresh channel object in this session
            channel = repos.channels.get_by_id(channel_id)
            
            if not channel:
                logger.error(f"Channel not found: {channel_id}")
                self.status_bar.showMessage("Error: Channel not found")
                self.loading_channels.discard(channel_id)
                return
            
            # Validate stream URL
            if not channel.stream_url:
                logger.error(f"Channel {channel.name} has no stream URL")
                self.status_bar.showMessage(f"Error: No stream URL for {channel.name}")
                return
            
            # Check if player is available
            if not self.player_manager.is_available():
                logger.error("No media player available")
                self.status_bar.showMessage("Error: No media player found. Please install mpv.")
                return
            
            # Show loading notification
            notif_id = self.notification_manager.show(
                title="Loading Stream",
                message=f"Buffering {channel.name}...",
                type="info",
                auto_dismiss_ms=5000
            )
            
            # Launch player
            logger.info(f"=== Playing Channel ===")
            logger.info(f"Name: {channel.name}")
            logger.info(f"Media Type: {channel.media_type}")
            logger.info(f"Stream URL: {channel.stream_url}")
            logger.info(f"Player: {self.player_manager.get_player_name()}")
            
            # Validate and failover if needed
            final_url = self.validate_and_failover_stream_url(
                channel.stream_url,
                channel.provider_id,
                channel.source_id,
                channel.media_type
            )
            
            if not final_url:
                logger.error(f"All stream URLs failed validation for {channel.name}")
                self.status_bar.showMessage(f"Error: Stream unavailable for {channel.name}")
                self.notification_manager.update(
                    notif_id,
                    title="Stream Unavailable",
                    message=f"{channel.name} - All URLs failed (possibly geo-blocked)",
                    type="error",
                    dismissible=True,
                    auto_dismiss_seconds=10
                )
                self.loading_channels.discard(channel_id)
                return
            
            if final_url != channel.stream_url:
                logger.info(f"Using failover URL: {final_url}")
            
            self.status_bar.showMessage(f"Loading: {channel.name}...")
            
            # Play using player manager
            if self.player_manager.play(final_url, channel.name):
                # Record playback in database
                repos.channels.mark_played(channel.id)
                logger.info(f"Recorded playback: {channel.name} (play count: {channel.play_count + 1})")
                
                # Update UI lists in real-time
                self.load_history()
                self.load_favorites()
                
                # Update status after brief delay
                QTimer.singleShot(2000, lambda: self.status_bar.showMessage(f"Playing: {channel.name}"))
            else:
                logger.error(f"Failed to play: {channel.name}")
                self.status_bar.showMessage(f"Error playing: {channel.name}")
            
            # Remove from loading set after delay
            QTimer.singleShot(3000, lambda: self.loading_channels.discard(channel_id))
            
        except Exception as e:
            logger.error(f"Error playing channel: {e}")
            self.status_bar.showMessage(f"Error playing channel: {e}")
            self.loading_channels.discard(channel_id)
        finally:
            session.close()
    
    def launch_new_mpv(self, url: str):
        """Launch a new mpv instance"""
        cmd = ["mpv"] + self.config.mpv_extra_args + [url]
        logger.info(f"Launching new mpv: {' '.join(cmd)}")
        # Use DEVNULL to prevent pipe buffer from filling and blocking
        process = subprocess.Popen(cmd, 
                       stdout=subprocess.DEVNULL, 
                       stderr=subprocess.DEVNULL)
        logger.info(f"mpv process started with PID: {process.pid}")
    
    def ensure_single_mpv_running(self):
        """Ensure single mpv instance is running with IPC"""
        import os
        
        # Check if mpv is already running
        if self.mpv_process and self.mpv_process.poll() is None:
            logger.info("Single mpv instance already running")
            return True
        
        # Clean up old socket
        if os.path.exists(self.mpv_socket):
            try:
                os.remove(self.mpv_socket)
            except Exception as e:
                logger.warning(f"Could not remove old socket: {e}")
        
        # Start mpv with IPC and idle mode
        cmd = [
            "mpv",
            "--idle",
            "--force-window",
            f"--input-ipc-server={self.mpv_socket}",
            "--title=MetaTV Player"
        ] + self.config.mpv_extra_args
        
        try:
            self.mpv_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"Started single mpv instance with PID {self.mpv_process.pid}")
            
            # Wait a moment for socket to be created
            import time
            for i in range(10):
                if os.path.exists(self.mpv_socket):
                    logger.info(f"mpv IPC socket ready: {self.mpv_socket}")
                    return True
                time.sleep(0.1)
            
            logger.warning("mpv socket not created in time")
            return False
        except Exception as e:
            logger.error(f"Failed to start single mpv instance: {e}")
            return False
    
    def play_in_single_mpv(self, url: str, title: str) -> bool:
        """Send URL to single mpv instance via IPC"""
        import socket
        import json
        import os
        
        # Ensure mpv is running
        if not self.ensure_single_mpv_running():
            return False
        
        # Check socket exists
        if not os.path.exists(self.mpv_socket):
            logger.warning(f"mpv socket not found: {self.mpv_socket}")
            return False
        
        try:
            # Connect to mpv IPC socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.mpv_socket)
            
            # Send loadfile command
            command = {
                "command": ["loadfile", url, "replace"]
            }
            sock.send((json.dumps(command) + "\n").encode('utf-8'))
            
            # Optional: Set media title
            title_command = {
                "command": ["set_property", "media-title", title]
            }
            sock.send((json.dumps(title_command) + "\n").encode('utf-8'))
            
            sock.close()
            logger.info(f"Sent URL to single mpv instance: {url}")
            return True
        except Exception as e:
            logger.error(f"Failed to communicate with mpv: {e}")
            return False
    
    def update_provider_status(self, provider_id: str, status: str):
        """Update provider status indicator in sidebar
        
        Args:
            provider_id: Provider ID
            status: 'disabled', 'testing', 'online', 'offline'
        """
        if "sources" in self.sidebar_sections:
            self.sidebar_sections["sources"].update_provider_status(provider_id, status)
    
    def test_all_providers(self):
        """Test connection for all active providers on startup"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all(active_only=True)
            
            for provider in providers:
                self.update_provider_status(provider.id, "testing")
                self.test_provider_connection(provider.id)
        finally:
            session.close()
    
    def test_provider_connection(self, provider_id: str):
        """Test connection to a specific provider"""
        session = self.db.get_session()
        try:
            from metatv.core.provider_loader import ProviderTestThread
            
            repos = RepositoryFactory(session)
            db_provider = repos.providers.get_by_id(provider_id)
            if not db_provider:
                return
            
            # Start test in background
            test_thread = ProviderTestThread(
                db_provider.type,
                db_provider.url,
                db_provider.username,
                db_provider.password
            )
            test_thread.result.connect(
                lambda success, msg, pid=provider_id: self.on_connection_test_result(pid, success, msg)
            )
            
            # Keep thread alive
            self.active_threads.append(test_thread)
            test_thread.finished.connect(
                lambda: self.active_threads.remove(test_thread) if test_thread in self.active_threads else None
            )
            
            test_thread.start()
        finally:
            session.close()
    
    def on_connection_test_result(self, provider_id: str, success: bool, message: str):
        """Handle connection test result"""
        logger.info(f"Provider {provider_id} test result: {'online' if success else 'offline'} - {message}")
        self.update_provider_status(provider_id, "online" if success else "offline")
    
    def show_operations(self):
        """Show operations panel"""
        logger.info("Show operations panel")
    
    def show_diagnostics(self):
        """Show diagnostics window"""
        logger.info("Show diagnostics")
    
    def manage_filters(self):
        """Show filter management"""
        logger.info("Manage filters")
    
    def open_settings(self):
        """Open settings dialog"""
        from metatv.gui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.config, self)
        dialog.exec()
    
    def show_about(self):
        """Show about dialog"""
        logger.info("Show about")
    
    def save_splitter_sizes(self):
        """Save all splitter panel sizes to config"""
        try:
            sizes = self.main_splitter.sizes()
            if sizes and len(sizes) >= 3:
                sidebar_width = sizes[0]
                details_width = sizes[2]
                
                self.config.sidebar_width = sidebar_width
                self.config.details_pane_width = details_width
                
                # Track if details pane is visible
                self.config.details_pane_visible = (details_width > 0)
                
                self.config.save()
                logger.debug(f"Saved splitter sizes: sidebar={sidebar_width}px, details={details_width}px")
        except Exception as e:
            logger.warning(f"Could not save splitter sizes: {e}")
    
    def save_sidebar_section_sizes(self):
        """Save sidebar section sizes to config"""
        try:
            sizes = self.sidebar_splitter.sizes()
            if sizes:
                self.config.sidebar_section_sizes = sizes
                self.config.save()
                logger.debug(f"Saved sidebar section sizes: {sizes}")
        except Exception as e:
            logger.warning(f"Could not save sidebar section sizes: {e}")
    
    def closeEvent(self, event):
        """Handle window close"""
        # Save window geometry so it restores on next launch
        try:
            import base64
            self.config.window_geometry = base64.b64encode(
                bytes(self.saveGeometry())
            ).decode("ascii")
        except Exception as e:
            logger.warning(f"Could not save window geometry: {e}")

        # Save splitter sizes one final time
        self.save_splitter_sizes()

        # Cleanup player resources
        self.player_manager.cleanup()

        # Close database
        self.db.close()
        event.accept()
