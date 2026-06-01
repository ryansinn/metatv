"""Main application window"""

import asyncio
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import time

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QSplitter,
    QTreeWidget, QListWidget, QMenuBar, QMenu,
    QCheckBox, QTreeWidgetItem, QLineEdit, QListWidgetItem
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from metatv.gui.icon_utils import resolve_icon
from loguru import logger
from concurrent.futures import ThreadPoolExecutor
import requests
from urllib.parse import urlparse, urlunparse
from datetime import datetime

from metatv.core.channel_name_utils import parse_channel_name
from metatv.core.config import Config
from metatv.core.database import Database, SeasonDB, EpisodeDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import parse_provider_urls
from metatv.core.notifications import NotificationManager
from metatv.core.player_manager import PlayerManager
from metatv.core.provider_loader import SeriesLoadThread
from metatv.gui.dialogs import AddProviderDialog
from metatv.gui.notification_widget import NotificationWidget
from metatv.gui.provider_editor import ProviderEditorView
from metatv.gui.sidebar_sections import (
    SourcesSection, WatchAlertsSection,
    HistorySection, FavoritesSection,
    RecommendedSection, WatchQueueSection,
)
from metatv.gui.filter_bar import ToggleChip, FilterChip
from metatv.gui.collapsible_splitter import CollapsibleSplitter
from metatv.gui.details_pane import DetailsPaneWidget
from metatv.gui.details_actions import ChannelActionState
from metatv.gui.details_versions import ChannelVersion
from metatv.gui.discover_view import DiscoverView
from metatv.gui.epg_view import EpgView
from metatv.gui.preferences_view import PreferencesView
from metatv.core.epg_manager import EpgManager
from metatv.core.image_cache import ImageCache
from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
from metatv.metadata_providers.provider_metadata import ProviderMetadataProvider

# Increment this when the prefix detection logic changes to trigger a one-time
# background re-scan for all users who have an older detected version stored in config.
CURRENT_DETECTOR_VERSION = 1


def _looks_like_text(chunk: bytes) -> bool:
    """Return True if a stream response chunk looks like text rather than binary video data.

    MPEG-TS sync byte (0x47) as the first byte is a strong binary signal.
    Otherwise we check the printable-ASCII ratio of the first 256 bytes.
    """
    if not chunk:
        return False
    if chunk[0] == 0x47:   # MPEG-TS sync byte — definitely binary
        return False
    printable = sum(1 for b in chunk[:256] if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D))
    return (printable / min(len(chunk), 256)) > 0.85


_SXXEXX = re.compile(r'[-–\s]+S(\d{1,3})E(\d{1,4})[-–\s]*(.*)$', re.IGNORECASE)


def _clean_episode_title(raw: str, season_num: int, ep_num: int, series_name: str | None) -> str:
    """Strip series name and SxxExx prefix from a raw IPTV episode title."""
    m = _SXXEXX.search(raw)
    if m:
        s, e, after = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        if s == season_num and e == ep_num:
            return after if after else f"Episode {ep_num}"
    if series_name and raw.startswith(series_name):
        remainder = raw[len(series_name):].lstrip(" -–").strip()
        if remainder:
            return remainder
    return raw


def _format_episode_duration(raw: str) -> str:
    """Convert 'HH:MM:SS' → '1h 21m' or '53m'."""
    parts = raw.split(":")
    if len(parts) == 3:
        try:
            h, m = int(parts[0]), int(parts[1])
            return f"{h}h {m}m" if h else f"{m}m"
        except ValueError:
            pass
    return raw


from metatv.core.preference_engine import version_score as _version_score


from PyQt6.QtCore import QThread, pyqtSignal as _pyqtSignal

class _PrefixRescanThread(QThread):
    """Background thread that re-runs update_detected_prefixes and emits the count."""
    finished = _pyqtSignal(int)

    def __init__(self, db, separators, parent=None):
        super().__init__(parent)
        self._db = db
        self._separators = separators

    def run(self):
        from metatv.core.repositories import RepositoryFactory
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            updated = repos.channels.update_detected_prefixes(separators=self._separators)
            self.finished.emit(updated)
        except Exception as e:
            logger.error(f"Prefix rescan failed: {e}")
            self.finished.emit(0)
        finally:
            session.close()


class MainWindow(QMainWindow):
    """Main application window"""
    
    # Signal for thread-safe metadata updates (channel_id, metadata)
    metadata_loaded = pyqtSignal(object, object)
    _channels_loaded = pyqtSignal(list, dict)        # (channels, params) — worker → main thread
    _category_assigned = pyqtSignal()               # emitted from worker after category DB write commits
    _versions_loaded = pyqtSignal(str, list)         # (channel_id, list[ChannelVersion]) — versions worker → main thread
    _similar_titles_loaded = pyqtSignal(str, list)   # (channel_id, list[ChannelVersion]) — similar titles worker → main thread
    _action_state_loaded = pyqtSignal(object)        # ChannelActionState — action state worker → main thread
    # Episode preflight results — emitted from done callback, connected to main-thread slots.
    # QTimer.singleShot from a non-main thread is unreliable; signals are always safe.
    _episode_ready  = pyqtSignal(str, str, str, object)  # notif_id, url, title, queue_episodes
    _episode_failed = pyqtSignal(str, str, str, str)     # notif_id, title, detail, stream_url
    # Context menu async fetch: (channel, in_queue, rating, gx, gy, variant)
    _ctx_data_ready = pyqtSignal(object, bool, object, int, int, str)
    
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
        self.hide_icon = config.hide_icon
        self.refresh_icon = config.refresh_icon
        self.settings_icon = config.settings_icon
        self.search_icon = config.search_icon
        self.filter_icon = config.filter_icon
        self.watched_icon = config.watched_icon
        self.rating_star_icon = config.rating_star_icon
        self.history_icon = config.history_icon
        self.queue_icon = config.queue_icon

        # Store active threads to prevent garbage collection
        self.active_threads = []
        
        # Track selected provider for filtering
        self.selected_provider_id = None
        self._in_provider_edit_mode = False
        
        # Store channel data for display
        self.all_channels = []  # List of (display_text, channel_db_obj)
        self.max_display_limit = 10000  # Max QListWidgetItems to render at once
        self._search_page_size = 5_000   # Max rows returned by get_all() per load

        # When True, Tier 1 filters (language/quality/platform) are bypassed for one
        # load — so the user can see what exists in filtered categories without having
        # to open the filter bar and change settings. Cleared on next filter change.
        self._bypass_tier1_filters: bool = False
        self._currently_bypassing: bool = False  # set after load completes, read by filter_channels

        # Debounce timer for search input → avoids a DB query per keystroke
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(200)
        self._search_debounce.timeout.connect(self.load_channels)
        
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

        # Stream retry manager — must exist before setup_ui() which wires sidebar signals
        from metatv.core.stream_retry_manager import StreamRetryManager
        self.stream_retry_manager = StreamRetryManager(self.db, self.validate_stream_url, parent=self)

        self.setup_ui()
        self.setup_notifications()

        # Initialize before load_channels() which uses these
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._load_channels_token: int = 0
        self._hidden_mode: bool = False
        self._last_shown_channel_id: str | None = None
        self.metadata_loaded.connect(self._update_details_with_metadata)
        self._channels_loaded.connect(self._on_channels_loaded)
        self._category_assigned.connect(self.load_channels)
        self._episode_ready.connect(self._do_launch_episode)
        self._episode_failed.connect(self._on_episode_stream_unavailable)
        self._ctx_data_ready.connect(self._on_ctx_data_ready)

        self.stream_retry_manager.stream_online.connect(self._on_stream_back_online)
        self.stream_retry_manager.retry_list_changed.connect(self._refresh_alerts_retry_section)
        self.stream_retry_manager.start()
        self._refresh_alerts_retry_section()  # restore persisted entries on startup

        self.load_providers()
        self.load_favorites()
        self.load_history()
        self._refresh_queue_section()
        self._refresh_recommended_section()

        # Auto-load channels from all active providers on startup
        self.load_channels()

        # Initialize filter statistics
        self.initialize_filter_stats()

        # Test provider connections in background
        self.test_all_providers()

        # One-time auto-rescan if prefix detector version is behind
        QTimer.singleShot(1000, self._maybe_rescan_prefixes)

        logger.info("Main window initialized")
    
    def setup_ui(self):
        """Set up the user interface"""
        self.setWindowTitle("MetaTV - IPTV Stream Organizer")

        # Restore saved geometry, or fall back to a sensible default
        restored = False
        saved_geom = getattr(self.config, 'window_geometry', '')
        if saved_geom:
            try:
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
        self.details_pane = DetailsPaneWidget(self.config, self.image_cache, self.db)
        self.details_pane.play_requested.connect(self.play_channel_by_id)
        self.details_pane.favorite_toggled.connect(self.toggle_favorite_by_id)
        self.details_pane.queue_toggled.connect(self._on_details_queue_toggle)
        self.details_pane.rating_requested.connect(self._toggle_rating)
        self.details_pane.suppression_requested.connect(self._on_suppression_requested)
        self.details_pane.hide_requested.connect(self._on_hide_from_details_pane)
        self.details_pane.unhide_requested.connect(self._unhide_channel)
        self.details_pane.channel_versions_requested.connect(self._fetch_channel_versions)
        self.details_pane.version_selected.connect(self.show_channel_details_by_id)
        self.details_pane.prefix_block_requested.connect(self._on_prefix_block)
        self.details_pane.prefix_unblock_requested.connect(self._on_prefix_unblock)
        self.details_pane.prefix_name_saved.connect(self._on_prefix_name_saved)
        self.details_pane.manage_filters_requested.connect(self.manage_filters)
        self.details_pane.similar_titles_requested.connect(self._fetch_similar_titles)
        self.details_pane.similar_preview_requested.connect(self._show_similar_lightbox)
        self.details_pane.action_state_requested.connect(self._on_action_state_requested)
        self._versions_loaded.connect(self._on_versions_loaded)
        self._similar_titles_loaded.connect(self._on_similar_titles_loaded)
        self._action_state_loaded.connect(self._on_action_state_loaded)
        self.main_splitter.addWidget(self.details_pane)

        # Similar titles lightbox — overlay child widget, hidden by default
        from metatv.gui.similar_lightbox import SimilarTitleLightbox
        self._lightbox = SimilarTitleLightbox(self, self.config, self.image_cache, self.db)
        self._lightbox.play_requested.connect(self.play_channel_by_id)
        self._lightbox.queue_toggled.connect(self._on_details_queue_toggle)
        self._lightbox.favorite_toggled.connect(self.toggle_favorite_by_id)
        self._lightbox.hide_requested.connect(self._on_hide_from_details_pane)
        self._lightbox.rating_requested.connect(self._toggle_rating)
        self._lightbox.suppression_requested.connect(self._on_suppression_requested)

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
        
        main_layout.addWidget(self.main_splitter, 1)
        main_layout.addWidget(self._create_bottom_nav_bar())

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

        # Wrap in outer widget so a Settings button can live at the bottom
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self.sidebar_splitter)

        settings_btn = QPushButton(f"{self.config.settings_icon} Settings")
        settings_btn.setFlat(True)
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip("Open application settings (Ctrl+,)")
        settings_btn.setStyleSheet(
            "QPushButton { font-size: 13px; color: #bbbbbb; padding: 7px 12px;"
            " border-top: 1px solid #333; background: #1e1e1e; }"
            "QPushButton:hover { color: #eeeeee; background: #2a2a2a; }"
        )
        settings_btn.clicked.connect(self.open_settings)
        outer_layout.addWidget(settings_btn)

        return outer
    
    def create_section(self, section_id: str):
        """Create a sidebar section by ID"""
        if section_id == "sources":
            section = SourcesSection(self.config, self.db, self)
            section.providerSelected.connect(self.on_provider_selected_new)
            section.providerRefreshClicked.connect(self.refresh_provider)
            section.providerEditClicked.connect(self.enter_provider_edit_mode)
            section.providerToggleClicked.connect(self.toggle_provider_active)
            section.addProviderClicked.connect(self.add_provider)
            section.refreshAllClicked.connect(self.refresh_all_providers)
            return section

        elif section_id == "alerts":
            section = WatchAlertsSection(self.config, self.db, self)
            section.alertClicked.connect(self._on_alert_clicked)
            section.channel_selected.connect(self._on_alert_channel_details)
            section.channelContextMenuRequested.connect(self._on_alert_channel_context_menu)
            section.retryRemoveRequested.connect(self.stream_retry_manager.remove)
            section.retryClearAllRequested.connect(self.stream_retry_manager.clear_all)
            section.retryPlayRequested.connect(self._on_retry_play_requested)
            section.retryContextMenuRequested.connect(self._on_retry_context_menu_requested)
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

        elif section_id == "recommended":
            section = RecommendedSection(self.config, self.db, self)
            section.itemSelected.connect(self._on_rec_sidebar_selected)
            section.itemDoubleClicked.connect(self.play_channel_by_id)
            section.channelContextMenuRequested.connect(self._on_rec_channel_context_menu)
            return section

        elif section_id == "queue":
            section = WatchQueueSection(self.config, self.db, self)
            section.itemSelected.connect(self.show_channel_details_by_id)
            section.itemDoubleClicked.connect(self.play_queue_item_id)
            section.channelContextMenuRequested.connect(self._on_queue_channel_context_menu)
            section.clearQueueClicked.connect(self._clear_queue)
            section.clearWatchedClicked.connect(self._clear_watched_queue)
            return section

        return None
    
    def refresh_sidebar(self):
        """Refresh all sidebar sections"""
        for section in self.sidebar_sections.values():
            section.refresh()

    def _refresh_watch_alerts(self, *_) -> None:
        """Refresh the sidebar Watch Alerts section after any EPG data update."""
        section = self.sidebar_sections.get("alerts")
        if section:
            section.refresh()

    def _watch_channel_from_list(self, channel_id: str) -> None:
        if channel_id not in self.config.epg_watchlist_channels:
            self.config.epg_watchlist_channels.append(channel_id)
            self.config.save()
            self._refresh_watch_alerts()

    def _unwatch_channel_from_list(self, channel_id: str) -> None:
        if channel_id in self.config.epg_watchlist_channels:
            self.config.epg_watchlist_channels.remove(channel_id)
            self.config.save()
            self._refresh_watch_alerts()

    def _prompt_track_from_list(self, channel_name: str) -> None:
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Track keyword",
            "Add watchlist pattern — edit to a keyword for broader matching:",
            text=channel_name,
        )
        if ok and text.strip():
            patterns = list(self.config.epg_watchlist_patterns)
            if text.strip() not in patterns:
                patterns.append(text.strip())
                self.config.epg_watchlist_patterns = patterns
                self.config.save()
            self._refresh_watch_alerts()

    def _toggle_rating(self, channel_id: str, rating: int) -> None:
        """Toggle a like (+1) or dislike (-1) rating; clicking the active rating clears it."""
        from datetime import datetime
        from metatv.core.database import UserRatingDB
        session = self.db.get_session()
        try:
            current = session.get(UserRatingDB, channel_id)
            if current and current.rating == rating:
                session.delete(current)
            else:
                session.merge(UserRatingDB(channel_id=channel_id, rating=rating,
                                           rated_at=datetime.utcnow()))
            session.commit()
        finally:
            session.close()
        if self.view_mode == "preferences":
            self.preferences_view.refresh()
        self._refresh_recommended_section()

    def _toggle_favorite_by_id(self, channel_id: str, make_favorite: bool) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                channel.is_favorite = make_favorite
                session.commit()
                self.load_favorites()
        finally:
            session.close()

    def _hide_channel_from_alerts(self, channel_id: str) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.set_hidden(channel_id, True)
            self._refresh_watch_alerts()
            self.load_history()
            self.load_channels()
        finally:
            session.close()

    def _not_interested(self, channel_id: str, suppressed: bool = True) -> None:
        """Suppress (or un-suppress) channel from recommendations only."""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.set_rec_suppressed(channel_id, suppressed)
            session.commit()
        finally:
            session.close()
        self.preferences_view.refresh()
        self._refresh_recommended_section()

    def _on_suppression_requested(self, channel_id: str, suppressed: bool) -> None:
        self._not_interested(channel_id, suppressed)

    def _on_hide_from_details_pane(self, channel_id: str) -> None:
        self._hide_channel_from_recommendations(channel_id)

    # --- Action state (async) ---

    def _on_action_state_requested(self, channel_id: str) -> None:
        self.executor.submit(self._bg_fetch_action_state, channel_id)

    def _bg_fetch_action_state(self, channel_id: str) -> None:
        session = self.db.get_session()
        try:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            state = ChannelActionState(
                channel_id=channel_id,
                in_queue=repos.queue.is_queued(channel_id),
                rating=repos.ratings.get(channel_id) or 0,
            )
            ch = repos.channels.get_by_id(channel_id)
            if ch:
                state.is_suppressed = bool(ch.is_rec_suppressed)
                state.is_hidden = bool(ch.is_hidden)
            self._action_state_loaded.emit(state)
        except Exception as e:
            logger.error(f"Failed to fetch action state for {channel_id}: {e}")
        finally:
            session.close()

    def _on_action_state_loaded(self, state) -> None:
        self.details_pane.apply_action_state(state)

    # --- Other Versions / Other Sources ---

    def _fetch_channel_versions(self, channel_id: str) -> None:
        self.executor.submit(self._bg_fetch_versions, channel_id)

    def _bg_fetch_versions(self, channel_id: str) -> None:
        from metatv.core.database import ChannelDB, WatchQueueDB, ProviderDB
        from metatv.core.content_dedup import normalize_title

        session = self.db.get_session()
        try:
            channel = session.get(ChannelDB, channel_id)
            if not channel:
                return

            queue_ids = {r.channel_id for r in session.query(WatchQueueDB).all()}
            provider_names = {p.id: p.name for p in session.query(ProviderDB).all()}
            _filter_paused = self.config.global_filter_paused
            excluded_cats = set() if _filter_paused else set(self.config.global_filter_excluded_categories)
            blocked_prefixes = set() if _filter_paused else set(self.config.global_filter_excluded_prefixes)
            all_excluded = excluded_cats | blocked_prefixes

            def _is_filtered(ch: ChannelDB) -> bool:
                p = ch.detected_prefix
                return bool(p and p in all_excluded)

            def _is_hidden_category(ch: ChannelDB) -> bool:
                return bool(ch.detected_prefix and ch.detected_prefix in blocked_prefixes)

            def _first_significant_word(text: str) -> str:
                """Return first word ≥3 chars, avoiding noise like 'a', 'an', 'the'."""
                for w in text.split():
                    if len(w) >= 3:
                        return w
                return text.split()[0] if text.split() else ""

            is_live = channel.media_type == "live"
            if is_live:
                norm = normalize_title(channel.name, channel.detected_prefix)
                if not norm:
                    self._versions_loaded.emit(channel_id, [])
                    return
                first_word = _first_significant_word(norm)
                candidates = (
                    session.query(ChannelDB)
                    .filter(
                        ChannelDB.media_type == "live",
                        ChannelDB.id != channel_id,
                        ChannelDB.name.ilike(f"%{first_word}%"),
                    )
                    .all()
                )
                versions_raw = [
                    ch for ch in candidates
                    if normalize_title(ch.name, ch.detected_prefix) == norm
                ]
            else:
                # Use normalize_title comparison (same as live branch) — avoids strict year/director
                # matching from build_dedup_key which breaks when providers have inconsistent metadata.
                current_norm = normalize_title(channel.name, channel.detected_prefix)
                if not current_norm:
                    self._versions_loaded.emit(channel_id, [])
                    return
                first_word = _first_significant_word(current_norm)
                if not first_word:
                    self._versions_loaded.emit(channel_id, [])
                    return
                candidates = (
                    session.query(ChannelDB)
                    .filter(
                        ChannelDB.media_type == channel.media_type,
                        ChannelDB.id != channel_id,
                        ChannelDB.name.ilike(f"%{first_word}%"),
                    )
                    .all()
                )
                versions_raw = [
                    ch for ch in candidates
                    if normalize_title(ch.name, ch.detected_prefix) == current_norm
                ]

            current_score = _version_score(channel, self.config)
            best_score = current_score
            best_ch = None
            for ch in versions_raw:
                s = _version_score(ch, self.config)
                if s > best_score:
                    best_score = s
                    best_ch = ch

            versions = [
                ChannelVersion(
                    channel_id=ch.id,
                    name=ch.name,
                    in_queue=ch.id in queue_ids,
                    detected_prefix=ch.detected_prefix,
                    is_preferred=(ch is best_ch),
                    is_filtered=_is_filtered(ch) if not ch.is_hidden else False,
                    is_hidden=bool(ch.is_hidden),
                    is_hidden_category=_is_hidden_category(ch),
                    is_favorite=bool(ch.is_favorite),
                    in_history=bool(ch.play_count),
                    provider_name=provider_names.get(ch.provider_id),
                )
                for ch in versions_raw
            ]
            versions.sort(key=lambda v: (
                v.is_hidden,
                v.is_filtered,
                -_version_score(
                    next(c for c in versions_raw if c.id == v.channel_id), self.config
                ),
                v.name,
            ))
            versions = versions[:20]

        except Exception:
            logger.exception("Error fetching channel versions for %s", channel_id)
            versions = []
        finally:
            session.close()

        self._versions_loaded.emit(channel_id, versions)

    def _on_versions_loaded(self, channel_id: str, versions: list) -> None:
        if (self.details_pane.current_channel
                and self.details_pane.current_channel.id == channel_id):
            self.details_pane.set_versions(versions)

    def _on_prefix_block(self, prefix: str) -> None:
        if prefix and prefix not in self.config.global_filter_excluded_prefixes:
            self.config.global_filter_excluded_prefixes.append(prefix)
            self.config.save()
            self._update_filter_btn_state()
            self.load_channels()
            if self.details_pane.current_channel:
                self._fetch_channel_versions(self.details_pane.current_channel.id)
            self.notification_manager.show(
                title=f"{prefix} channels hidden",
                type="info",
                auto_dismiss_ms=6000,
                actions=[("Undo", lambda p=prefix: self._on_prefix_unblock(p))],
            )

    def _on_prefix_unblock(self, prefix: str) -> None:
        if prefix in self.config.global_filter_excluded_prefixes:
            self.config.global_filter_excluded_prefixes.remove(prefix)
            self.config.save()
            self._update_filter_btn_state()
            self.load_channels()
            if self.details_pane.current_channel:
                self._fetch_channel_versions(self.details_pane.current_channel.id)
            self.notification_manager.show(
                title=f"{prefix} channels visible again",
                type="info",
                auto_dismiss_ms=4000,
            )

    def _on_prefix_name_saved(self, prefix: str, name: str) -> None:
        if name:
            self.config.category_name_overrides[prefix] = name
        else:
            self.config.category_name_overrides.pop(prefix, None)
        self.config.save()
        if self.details_pane.current_channel:
            self._fetch_channel_versions(self.details_pane.current_channel.id)

    def _fetch_similar_titles(self, channel_id: str) -> None:
        self.executor.submit(self._bg_fetch_similar_titles, channel_id)

    def _bg_fetch_similar_titles(self, channel_id: str) -> None:
        from metatv.core.database import ChannelDB, WatchQueueDB
        from metatv.core.content_dedup import normalize_title, build_dedup_key
        _non_ascii = re.compile(r'[^\x00-\x7F]+')

        session = self.db.get_session()
        try:
            channel = session.get(ChannelDB, channel_id)
            if not channel:
                self._similar_titles_loaded.emit(channel_id, [])
                return

            norm = normalize_title(channel.name, channel.detected_prefix)
            words = [w for w in norm.split() if len(w) >= 4]
            if not words:
                self._similar_titles_loaded.emit(channel_id, [])
                return

            # SQL pre-filter: same media_type, first key word in name (no prefix filter —
            # dedup and word-overlap handle language duplicates)
            candidates = (
                session.query(ChannelDB)
                .filter(
                    ChannelDB.media_type == channel.media_type,
                    ChannelDB.id != channel_id,
                    ChannelDB.is_hidden == False,
                    ChannelDB.name.ilike(f"%{words[0]}%"),
                )
                .limit(200)
                .all()
            )

            # Python-level: word overlap ≥ 50% of current title's key words
            threshold = max(1, len(words) // 2)
            seen_norms: set[str] = set()
            # Also exclude channels that are exact dedup matches (those are "Other Versions")
            from metatv.core.database import MetadataDB
            current_meta = session.get(MetadataDB, channel.metadata_id) if channel.metadata_id else None
            current_key = build_dedup_key(channel, current_meta)

            results: list[ChannelDB] = []
            for ch in candidates:
                ch_norm = normalize_title(ch.name, ch.detected_prefix)
                # Use ASCII-only projection for word matching so bilingual titles
                # like "Nobody Wants This هیچکس..." match on their Latin portion.
                ch_norm_ascii = _non_ascii.sub(" ", ch_norm).strip()
                ch_words = {w for w in ch_norm_ascii.split() if len(w) >= 4}
                overlap = sum(1 for w in words if w in ch_words)
                if overlap >= threshold and ch_norm != norm and ch_norm not in seen_norms:
                    # Skip exact dedup matches (other versions of same content)
                    if current_key:
                        ch_meta = session.get(MetadataDB, ch.metadata_id) if ch.metadata_id else None
                        if build_dedup_key(ch, ch_meta) == current_key:
                            continue
                    seen_norms.add(ch_norm)
                    results.append(ch)

            queue_ids = {r.channel_id for r in session.query(WatchQueueDB).all()}
            similar = [
                ChannelVersion(
                    channel_id=ch.id,
                    name=ch.name,
                    in_queue=ch.id in queue_ids,
                    detected_prefix=ch.detected_prefix,
                    is_favorite=bool(ch.is_favorite),
                    in_history=bool(ch.play_count),
                )
                for ch in results[:20]
            ]
        except Exception:
            logger.exception("Error fetching similar titles for %s", channel_id)
            similar = []
        finally:
            session.close()

        self._similar_titles_loaded.emit(channel_id, similar)

    def _on_similar_titles_loaded(self, channel_id: str, titles: list) -> None:
        if (self.details_pane.current_channel
                and self.details_pane.current_channel.id == channel_id):
            self.details_pane.set_similar_titles(titles)

    def _hide_channel_from_recommendations(self, channel_id: str) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.set_hidden(channel_id, True)
            session.commit()
        finally:
            session.close()
        self.preferences_view.refresh()
        self._refresh_recommended_section()
        self.load_channels()

    def _unhide_channel(self, channel_id: str) -> None:
        def _bg() -> None:
            session = self.db.get_session()
            try:
                repos = RepositoryFactory(session)
                repos.channels.set_hidden(channel_id, False)
            finally:
                session.close()
        self.executor.submit(_bg)
        QTimer.singleShot(150, self.load_channels)

    # --- Recommended sidebar helpers ---

    def _on_rec_sidebar_selected(self, channel_id: str, reason: str) -> None:
        self.show_channel_details_by_id(channel_id)
        self.details_pane.set_recommendation_reason(reason)

    def _refresh_recommended_section(self) -> None:
        section = self.sidebar_sections.get("recommended")
        if section:
            section.refresh()

    # --- Watch Queue helpers ---

    def _add_to_queue(self, channel_id: str) -> None:
        from metatv.core.database import ChannelDB
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            ch = session.get(ChannelDB, channel_id)
            repos.queue.add(
                channel_id,
                channel_name=ch.name if ch else "",
                media_type=ch.media_type if ch else "",
                source_id=ch.source_id if ch else "",
            )
            session.commit()
        finally:
            session.close()
        self._refresh_queue_section()
        self._refresh_recommended_section()

    def _remove_from_queue(self, channel_id: str) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.queue.remove(channel_id)
            session.commit()
        finally:
            session.close()
        self._refresh_queue_section()
        self._refresh_recommended_section()

    def _refresh_queue_section(self) -> None:
        section = self.sidebar_sections.get("queue")
        if section:
            section.refresh()

    def _refresh_alerts_retry_section(self) -> None:
        section = self.sidebar_sections.get("alerts")
        if section and hasattr(section, "refresh_retry"):
            entries = self.stream_retry_manager.get_all_pending()
            section.refresh_retry(entries)

    def _on_retry_play_requested(self, channel_id: str, stream_url: str, channel_name: str) -> None:
        """Double-click on a Stream Monitoring item — try launching the stream again."""
        from metatv.core.database import ChannelDB
        session = self.db.get_session()
        try:
            channel = session.query(ChannelDB).filter_by(id=channel_id).first()
        finally:
            session.close()
        if channel:
            self.play_media(channel)
        else:
            # Episode path — no ChannelDB entry; validate and play directly
            self.launch_player_for_episode(stream_url, channel_name or stream_url, [])

    def _on_retry_context_menu_requested(self, entry_id: str, channel_id: str, x: int, y: int) -> None:
        """Build combined channel + Stream Monitoring context menu."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QAction
        from metatv.core.database import UserRatingDB

        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id) if channel_id else None
            if channel:
                rating_row = session.get(UserRatingDB, channel_id)
                current_rating = rating_row.rating if rating_row else 0
            else:
                current_rating = 0
        finally:
            session.close()

        menu = QMenu(self)

        if channel:
            play_act = QAction(f"{self.config.play_icon} Play", self)
            play_act.triggered.connect(lambda: self.play_channel_by_id(channel_id))
            menu.addAction(play_act)

            menu.addSeparator()

            if channel.is_favorite:
                fav_act = QAction(f"Remove from Favorites ({self.unfavorite_icon})", self)
                fav_act.triggered.connect(lambda: self._toggle_favorite_by_id(channel_id, False))
            else:
                fav_act = QAction(f"{self.config.favorite_icon} Add to Favorites", self)
                fav_act.triggered.connect(lambda: self._toggle_favorite_by_id(channel_id, True))
            menu.addAction(fav_act)

            if channel.media_type in ("movie", "series"):
                menu.addSeparator()
                like_act = QAction(f"{self.config.like_icon} Like", self)
                like_act.setCheckable(True)
                like_act.setChecked(current_rating == 1)
                like_act.triggered.connect(lambda: self._toggle_rating(channel_id, 1))
                menu.addAction(like_act)
                dislike_act = QAction(f"{self.config.dislike_icon} Dislike", self)
                dislike_act.setCheckable(True)
                dislike_act.setChecked(current_rating == -1)
                dislike_act.triggered.connect(lambda: self._toggle_rating(channel_id, -1))
                menu.addAction(dislike_act)

            menu.addSeparator()

        remove_act = QAction(f"{self.config.close_icon} Remove from Stream Monitoring", self)
        remove_act.triggered.connect(lambda: self.stream_retry_manager.remove(entry_id))
        menu.addAction(remove_act)
        clear_act = QAction("Clear all from Stream Monitoring", self)
        clear_act.triggered.connect(self.stream_retry_manager.clear_all)
        menu.addAction(clear_act)
        menu.exec(QPoint(x, y))

    def _on_stream_back_online(self, channel_id: str, channel_name: str) -> None:
        from PyQt6.QtWidgets import QApplication
        self.notification_manager.show(
            title="Stream Available",
            message=f"{channel_name} is back online.",
            type="success",
            dismissible=True,
            auto_dismiss_seconds=30,
        )
        self._refresh_alerts_retry_section()

    def _clear_queue(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Clear Queue",
            "Are you sure you want to clear the watch queue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            session = self.db.get_session()
            try:
                repos = RepositoryFactory(session)
                repos.queue.clear()
                session.commit()
            finally:
                session.close()
            self._refresh_queue_section()

    def _clear_watched_queue(self) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            count = repos.queue.clear_watched()
            session.commit()
        finally:
            session.close()
        self._refresh_queue_section()
        if count:
            self.status_bar.showMessage(f"Removed {count} watched item(s) from queue")

    def play_queue_item_id(self, channel_id: str) -> None:
        """Play a queue item — series opens the season view, others play directly."""
        from metatv.core.models import MediaType
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
        finally:
            session.close()
        if not channel:
            return
        if channel.media_type == MediaType.SERIES:
            self.drill_into_series(channel)
        else:
            self.play_media(channel)

    def _on_details_queue_toggle(self, channel_id: str) -> None:
        """Handle queue toggle from the details pane button."""
        from metatv.core.database import ChannelDB
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            if repos.queue.is_queued(channel_id):
                repos.queue.remove(channel_id)
            else:
                ch = session.get(ChannelDB, channel_id)
                repos.queue.add(
                    channel_id,
                    channel_name=ch.name if ch else "",
                    media_type=ch.media_type if ch else "",
                    source_id=ch.source_id if ch else "",
                )
            session.commit()
        finally:
            session.close()
        self._refresh_queue_section()

    def _on_queue_channel_context_menu(self, channel_id: str, gx: int, gy: int) -> None:
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        from metatv.core.database import UserRatingDB
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                return
            rating_row = session.get(UserRatingDB, channel_id)
            current_rating = rating_row.rating if rating_row else 0
        finally:
            session.close()

        menu = QMenu(self)

        play_act = QAction(f"{self.config.play_icon} Play", self)
        play_act.triggered.connect(lambda: self.play_queue_item_id(channel_id))
        menu.addAction(play_act)

        menu.addSeparator()

        remove_act = QAction(f"{self.config.queue_icon} Remove from Queue", self)
        remove_act.triggered.connect(lambda: self._remove_from_queue(channel_id))
        menu.addAction(remove_act)

        menu.addSeparator()

        fav_act = QAction(f"{self.config.favorite_icon} Add to Favorites", self)
        fav_act.triggered.connect(lambda: self._toggle_favorite_by_id(channel_id, True))
        menu.addAction(fav_act)

        if channel.media_type in ("movie", "series"):
            menu.addSeparator()
            like_act = QAction(f"{self.config.like_icon} Like", self)
            like_act.setCheckable(True)
            like_act.setChecked(current_rating == 1)
            like_act.triggered.connect(lambda: self._toggle_rating(channel_id, 1))
            menu.addAction(like_act)

            dislike_act = QAction(f"{self.config.dislike_icon} Dislike", self)
            dislike_act.setCheckable(True)
            dislike_act.setChecked(current_rating == -1)
            dislike_act.triggered.connect(lambda: self._toggle_rating(channel_id, -1))
            menu.addAction(dislike_act)

        menu.exec(QPoint(gx, gy))

    def _on_rec_channel_context_menu(self, channel_id: str, gx: int, gy: int) -> None:
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        from metatv.core.database import UserRatingDB
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                return
            rating_row = session.get(UserRatingDB, channel_id)
            current_rating = rating_row.rating if rating_row else 0
            in_queue = repos.queue.is_queued(channel_id)
        finally:
            session.close()

        menu = QMenu(self)

        play_act = QAction(f"{self.config.play_icon} Play", self)
        play_act.triggered.connect(lambda: self.play_channel_by_id(channel_id))
        menu.addAction(play_act)

        queue_act = QAction(
            f"{self.config.queue_icon} {'Remove from Queue' if in_queue else 'Add to Queue'}", self
        )
        queue_act.triggered.connect(
            lambda: self._remove_from_queue(channel_id) if in_queue else self._add_to_queue(channel_id)
        )
        menu.addAction(queue_act)

        menu.addSeparator()

        like_act = QAction(f"{self.config.like_icon} Like", self)
        like_act.setCheckable(True)
        like_act.setChecked(current_rating == 1)
        like_act.triggered.connect(lambda: self._toggle_rating(channel_id, 1))
        menu.addAction(like_act)

        dislike_act = QAction(f"{self.config.dislike_icon} Dislike", self)
        dislike_act.setCheckable(True)
        dislike_act.setChecked(current_rating == -1)
        dislike_act.triggered.connect(lambda: self._toggle_rating(channel_id, -1))
        menu.addAction(dislike_act)

        menu.addSeparator()

        not_interested_act = QAction(f"{self.config.not_interested_icon} Not Interested", self)
        not_interested_act.triggered.connect(lambda: self._not_interested(channel_id))
        menu.addAction(not_interested_act)

        hide_act = QAction(f"{self.config.hide_icon} Hide", self)
        hide_act.triggered.connect(lambda: self._hide_channel_from_recommendations(channel_id))
        menu.addAction(hide_act)

        menu.exec(QPoint(gx, gy))

    def _on_alert_channel_context_menu(self, channel_id: str, gx: int, gy: int) -> None:
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                return
            menu = QMenu()

            play_act = QAction(f"{self.config.play_icon} Play", self)
            play_act.triggered.connect(lambda: self.play_channel_by_id(channel_id))
            menu.addAction(play_act)

            menu.addSeparator()

            if channel.is_favorite:
                fav_act = QAction(f"Remove from Favorites ({self.unfavorite_icon})", self)
                fav_act.triggered.connect(lambda: self._toggle_favorite_by_id(channel_id, False))
            else:
                fav_act = QAction(f"Add to Favorites ({self.favorite_icon})", self)
                fav_act.triggered.connect(lambda: self._toggle_favorite_by_id(channel_id, True))
            menu.addAction(fav_act)

            if channel_id in self.config.epg_watchlist_channels:
                watch_act = QAction("Stop watching this channel", self)
                watch_act.triggered.connect(lambda: self._unwatch_channel_from_list(channel_id))
            else:
                watch_act = QAction("Watch this channel (EPG alerts)", self)
                watch_act.triggered.connect(lambda: self._watch_channel_from_list(channel_id))
            menu.addAction(watch_act)

            menu.addSeparator()

            hide_act = QAction(f"{self.hide_icon} Hide channel", self)
            hide_act.triggered.connect(lambda: self._hide_channel_from_alerts(channel_id))
            menu.addAction(hide_act)

            menu.exec(QPoint(gx, gy))
        finally:
            session.close()

    def _on_alert_clicked(self, channel_db_id: str) -> None:
        """Play the channel immediately when a sidebar watch alert is double-clicked."""
        if channel_db_id:
            self.play_channel_by_id(channel_db_id)

    def _on_alert_channel_details(self, channel_db_id: str) -> None:
        """Show channel details in the right pane when a watch alert row is single-clicked."""
        if not channel_db_id:
            return
        session = self.db.get_session()
        try:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_db_id)
            if channel:
                self.details_pane.show_channel(channel)
        finally:
            session.close()

    def _create_bottom_nav_bar(self) -> QWidget:
        """Build the full-width bottom tab bar with nav chips and Exclusions control."""
        bar = QWidget()
        bar.setObjectName("bottomNavBar")
        bar.setStyleSheet(
            "#bottomNavBar { background: #1e1e1e; border-top: 1px solid #333; }"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # Nav chip group — centered in the bar with 30px gaps between chips
        nav_group = QWidget()
        nav_layout = QHBoxLayout(nav_group)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(30)

        self.search_chip = ToggleChip(f"{self.config.search_icon} Search", enabled=True)
        self.search_chip.setToolTip("Channel list and search")
        self.search_chip.clicked.connect(self.on_search_view_toggle)
        nav_layout.addWidget(self.search_chip)

        self.epg_chip = ToggleChip("📅 EPG", enabled=False)
        self.epg_chip.setToolTip("EPG — programme guide, watchlist, on-now")
        self.epg_chip.clicked.connect(self.on_special_view_toggle)
        nav_layout.addWidget(self.epg_chip)

        self.prefs_chip = ToggleChip(f"{self.config.preferences_icon} Recommended", enabled=False)
        self.prefs_chip.setToolTip("Personalised recommendations")
        self.prefs_chip.clicked.connect(self.on_preferences_view_toggle)
        nav_layout.addWidget(self.prefs_chip)

        self.discover_chip = ToggleChip(f"{self.config.discover_icon} Discover", enabled=False)
        self.discover_chip.setToolTip("Browse by genre, decade, actor, director")
        self.discover_chip.clicked.connect(self.on_discover_view_toggle)
        nav_layout.addWidget(self.discover_chip)

        layout.addStretch(1)
        layout.addWidget(nav_group)
        layout.addStretch(1)

        self._filter_chip = FilterChip("Exclusions")
        self._filter_chip.toggled_changed.connect(self._on_filter_toggle)
        self._filter_chip.open_dialog_requested.connect(self._open_global_filter_dialog)
        layout.addWidget(self._filter_chip)

        QTimer.singleShot(0, self._update_filter_btn_state)
        return bar

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
        
        # Search and filter controls
        self.search_controls = QWidget()
        controls_layout = QHBoxLayout(self.search_controls)
        controls_layout.addWidget(QLabel("Search:"))
        
        # All / Hidden tab toggle
        _tab_style = (
            "QPushButton { font-size: 11px; padding: 3px 10px;"
            " border: 1px solid #444; background: #2a2a2a; color: #777; }"
            "QPushButton:checked { background: #444; color: #fff; font-weight: bold; }"
            "QPushButton:hover:!checked { background: #333; }"
        )
        self._tab_all_btn = QPushButton("All")
        self._tab_all_btn.setCheckable(True)
        self._tab_all_btn.setChecked(True)
        self._tab_all_btn.setStyleSheet(
            _tab_style + "QPushButton { border-right: none;"
            " border-top-left-radius: 4px; border-bottom-left-radius: 4px; }"
        )
        self._tab_all_btn.setToolTip("Show all channels")
        self._tab_all_btn.clicked.connect(lambda: self._set_search_tab(False))
        controls_layout.addWidget(self._tab_all_btn)

        self._tab_hidden_btn = QPushButton(f"{self.config.hide_icon} Hidden")
        self._tab_hidden_btn.setCheckable(True)
        self._tab_hidden_btn.setChecked(False)
        self._tab_hidden_btn.setStyleSheet(
            _tab_style + "QPushButton { border-top-right-radius: 4px;"
            " border-bottom-right-radius: 4px; }"
        )
        self._tab_hidden_btn.setToolTip(
            "Show channels hidden via right-click or assigned to an excluded category"
        )
        self._tab_hidden_btn.clicked.connect(lambda: self._set_search_tab(True))
        controls_layout.addWidget(self._tab_hidden_btn)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter channels by name, category...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        controls_layout.addWidget(self.search_input)
        
        # Clear search button
        clear_btn = QPushButton(self.close_icon)
        clear_btn.setFixedWidth(30)
        clear_btn.setToolTip("Clear search")
        clear_btn.clicked.connect(lambda: self.search_input.clear())
        controls_layout.addWidget(clear_btn)
        
        self.content_layout.addWidget(self.search_controls)

        # ── Filter panel + inner splitter ─────────────────────────────────────
        from metatv.gui.filter_panel import FilterPanel
        self.filter_panel = FilterPanel(self.config)
        self.filter_panel.filter_changed.connect(self.on_filter_changed)
        self.filter_panel.settings_requested.connect(self.open_settings)
        self._filter_unmapped_prefixes: list[str] = []

        # list_area: holds banner + all content views (right side of inner splitter)
        list_area = QWidget()
        self._list_layout = QVBoxLayout(list_area)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)

        # Hidden-mode banner
        self._hidden_banner = QWidget()
        _hb_layout = QHBoxLayout(self._hidden_banner)
        _hb_layout.setContentsMargins(8, 4, 8, 4)
        _hb_layout.setSpacing(8)
        _hb_lbl = QLabel(
            f"{self.config.hide_icon}  Showing hidden and excluded channels — right-click to unhide"
        )
        _hb_lbl.setStyleSheet("color: #cc8800; font-size: 11px;")
        _hb_layout.addWidget(_hb_lbl)
        _hb_layout.addStretch()
        self._manage_cats_btn = QPushButton("📁 Manage Categories")
        self._manage_cats_btn.setFlat(True)
        self._manage_cats_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manage_cats_btn.setStyleSheet(
            "QPushButton { font-size: 11px; color: #4488ff; padding: 2px 8px;"
            " border: 1px solid #4488ff44; border-radius: 4px; }"
            "QPushButton:hover { color: #88aaff; border-color: #88aaff44; }"
        )
        self._manage_cats_btn.setToolTip("Browse and manage your user-defined categories")
        self._manage_cats_btn.clicked.connect(self._open_categories_dialog)
        _hb_layout.addWidget(self._manage_cats_btn)
        self._hidden_banner.setStyleSheet(
            "background: rgba(204,136,0,0.08); border-radius: 4px;"
        )
        self._hidden_banner.hide()
        self._list_layout.addWidget(self._hidden_banner)

        # Channels list
        self.channels_list = QListWidget()
        from PyQt6.QtWidgets import QAbstractItemView
        self.channels_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.channels_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channels_list.customContextMenuRequested.connect(self.show_channel_context_menu)
        self.channels_list.itemDoubleClicked.connect(self.play_channel)
        self.channels_list.currentItemChanged.connect(self.on_channel_selection_changed)
        self._list_layout.addWidget(self.channels_list)

        # Series tree view (hidden by default)
        self.series_tree = QTreeWidget()
        self.series_tree.setHeaderLabels(["Title", "Episode", "Runtime", "Rating"])
        self.series_tree.setColumnWidth(0, 400)
        self.series_tree.setColumnWidth(1, 80)
        self.series_tree.setColumnWidth(2, 80)
        self.series_tree.setColumnWidth(3, 80)
        self.series_tree.setExpandsOnDoubleClick(False)
        self.series_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.series_tree.customContextMenuRequested.connect(self.show_series_context_menu)
        self.series_tree.itemDoubleClicked.connect(self.play_series_item)
        self.series_tree.setVisible(False)
        self._list_layout.addWidget(self.series_tree)

        # EPG manager + view (hidden by default)
        self.epg_manager = EpgManager(self.db, self.config, self.notification_manager, parent=self)
        self.epg_view = EpgView(self.config, self.db, self.epg_manager, self)
        self.epg_view.play_channel_requested.connect(self.play_special_event)
        self.epg_view.status_message.connect(lambda msg: self.status_bar.showMessage(msg))
        self.epg_view.channel_selected.connect(self._on_view_channel_selected)
        self.epg_view.watchlist_changed.connect(self._refresh_watch_alerts)
        self.epg_view.setVisible(False)
        self._list_layout.addWidget(self.epg_view)

        # Preferences view (hidden by default)
        self.preferences_view = PreferencesView(self.db, self.config, self)
        self.preferences_view.playRequested.connect(self.play_channel_by_id)
        self.preferences_view.channelSelected.connect(self.show_channel_details_by_id)
        self.preferences_view.ratingRequested.connect(self._toggle_rating)
        self.preferences_view.notInterestedRequested.connect(self._not_interested)
        self.preferences_view.channelContextMenuRequested.connect(self._on_rec_channel_context_menu)
        self.preferences_view.setVisible(False)
        self._list_layout.addWidget(self.preferences_view)

        # Discover view (hidden by default)
        self.discover_view = DiscoverView(self.db, self.config, self.image_cache, self)
        self.discover_view.playRequested.connect(self.play_channel_by_id)
        self.discover_view.channelSelected.connect(self.show_channel_details_by_id)
        self.discover_view.channelContextMenuRequested.connect(self._on_rec_channel_context_menu)
        self.discover_view.setVisible(False)
        self._list_layout.addWidget(self.discover_view)

        self.epg_manager.start_notification_timer()
        self.epg_manager.refresh_finished.connect(self._refresh_watch_alerts)
        self._refresh_watch_alerts()

        # Provider editor (hidden by default)
        self.provider_editor = ProviderEditorView(self.db, self.config, self)
        self.provider_editor.done.connect(self.exit_provider_edit_mode)
        self.provider_editor.provider_saved.connect(self._on_provider_saved)
        self.provider_editor.provider_deleted.connect(self._on_provider_deleted)
        self.provider_editor.refresh_requested.connect(self.refresh_provider)
        self.provider_editor.setVisible(False)
        self._list_layout.addWidget(self.provider_editor)

        # Inner splitter: filter panel (left) | list area (right)
        self._inner_splitter = CollapsibleSplitter(Qt.Orientation.Horizontal)
        self._inner_splitter.addWidget(self.filter_panel)
        self._inner_splitter.addWidget(list_area)
        self._inner_splitter.setStretchFactor(0, 0)  # filter panel: fixed width
        self._inner_splitter.setStretchFactor(1, 1)  # list area: takes remaining space
        panel_w = getattr(self.config, 'filter_panel_width', 220)
        self._inner_splitter.setSizes([panel_w, max(300, 800 - panel_w)])
        self._inner_splitter.splitterMoved.connect(self._save_filter_panel_width)
        self.content_layout.addWidget(self._inner_splitter, 1)

        # Stats label below the splitter
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
        """Handle window resize to reposition notifications and lightbox."""
        super().resizeEvent(event)
        if hasattr(self, 'notification_widget'):
            self.notification_widget.reposition()
        if hasattr(self, '_lightbox') and self._lightbox.isVisible():
            self._lightbox.resize(self.size())

    def _show_similar_lightbox(
        self,
        channel_ids: list,
        index: int,
        origin_title: str,
    ) -> None:
        self._lightbox.resize(self.size())
        self._lightbox.show_preview(channel_ids, index, origin_title)
    
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
    
    def _hide_all_content_views(self) -> None:
        """Blank-slate all views. Call before activating any single view."""
        if self.epg_view.isVisible():
            self.epg_view.on_deactivate()
        if self.discover_view.isVisible():
            self.discover_view.on_deactivate()
        if self.preferences_view.isVisible():
            self.preferences_view.on_deactivate()
        self.channels_list.setVisible(False)
        self.series_tree.setVisible(False)
        self.epg_view.setVisible(False)
        self.preferences_view.setVisible(False)
        self.discover_view.setVisible(False)
        self.provider_editor.setVisible(False)
        self.search_controls.setVisible(False)
        self._hidden_banner.setVisible(False)
        if hasattr(self, "filter_panel"):
            self.filter_panel.setVisible(False)
        self._hidden_mode = False
        if hasattr(self, "_tab_all_btn"):
            self._tab_all_btn.setChecked(True)
            self._tab_hidden_btn.setChecked(False)
        self.back_button.setVisible(False)
        self.breadcrumb_label.setText("")

    def enter_provider_edit_mode(self, provider_id: str):
        """Switch center panel to provider editor for the given provider."""
        self._hide_all_content_views()
        self.provider_editor.setVisible(True)
        self.provider_editor.load_provider(provider_id)
        self.stats_label.setText("Editing provider — click a source to switch")
        self._in_provider_edit_mode = True
        self._deactivate_view_chips()

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

    def _maybe_rescan_prefixes(self) -> None:
        """Run a background prefix re-scan if the detector version is behind."""
        if self.config.prefix_detector_version >= CURRENT_DETECTOR_VERSION:
            return
        logger.info(
            f"Prefix detector version {self.config.prefix_detector_version} < "
            f"{CURRENT_DETECTOR_VERSION} — running background re-scan"
        )
        self._rescan_thread = _PrefixRescanThread(
            self.db, self.config.prefix_separators, parent=self
        )
        self._rescan_thread.finished.connect(self._on_prefix_rescan_done)
        self._rescan_thread.start()

    def _on_prefix_rescan_done(self, updated: int) -> None:
        logger.info(f"Prefix re-scan complete: {updated} channels updated")
        self.config.prefix_detector_version = CURRENT_DETECTOR_VERSION
        self.config.save()

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
                self.refreshing_providers.discard(provider_id)
                return
            
            # Convert to model
            provider = repos.providers.to_model(db_provider)
            
            # Show progress notification
            notif_id = self.notification_manager.show_progress(
                title=f"Refreshing {provider.name}",
                total=100
            )
            
            # Start loading in background thread
            load_thread = ProviderLoadThread(
                provider, self.db,
                separators=self.config.prefix_separators,
                language_groups=self.config.filter_language_groups,
                quality_groups=self.config.filter_quality_groups,
                platform_groups=self.config.filter_platform_groups,
                regional_groups=self.config.filter_regional_groups,
            )
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

            # Prefix stats were computed in the worker thread — just apply them
            stats = getattr(thread, 'prefix_stats', None)
            if stats:
                self._filter_unmapped_prefixes = stats.get('unmapped_prefixes', [])
                if hasattr(self, 'filter_panel'):
                    self.filter_panel.update_data(stats)
                logger.info(f"Filter stats: {stats['channels_with_prefix']:,} channels have prefixes")

            # Reload sidebar and channels
            self.load_providers()
            self.load_channels()
            # Re-check any failed streams now that content is fresh
            if hasattr(self, "stream_retry_manager"):
                self.stream_retry_manager.check_all_now()
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
    
    def refresh_all_providers(self) -> None:
        """Refresh channels from every active provider."""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider_ids = [p.id for p in repos.providers.get_all(active_only=True)]
        finally:
            session.close()
        for pid in provider_ids:
            self.refresh_provider(pid)

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
        """Toggle filter panel visibility via inner splitter collapse."""
        if not hasattr(self, '_inner_splitter'):
            return
        sizes = self._inner_splitter.sizes()
        if sizes[0] > 0:
            self._inner_splitter.setSizes([0, sum(sizes)])
            self.config.filter_section_visible = False
        else:
            w = getattr(self.config, 'filter_panel_width', 220)
            self._inner_splitter.setSizes([w, max(200, sum(sizes) - w)])
            self.config.filter_section_visible = True
        self.config.save()
    
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
    
    def _on_search_text_changed(self, text: str) -> None:
        """Handle search input changes — debounce to avoid per-keystroke DB queries."""
        self._bypass_tier1_filters = False  # new search term — cancel any bypass
        self._search_debounce.start()  # restart the 200ms timer on each keystroke

    def load_channels(self, provider_id=None):
        """Load channels from database into the list (non-blocking)."""
        from metatv.core.database import ChannelDB
        from metatv.core.filter_utils import get_active_content_type_filter

        # Stop any pending debounce timer so we don't queue a second load
        self._search_debounce.stop()

        # Show loading state immediately so the user knows something is happening
        self.channels_list.clear()
        self.all_channels = []
        self.status_bar.showMessage("Loading channels…")

        # --- All UI-state reads must happen here on the main thread ---
        filter_state = self.current_filter_state or (
            self.filter_panel.get_filter_state()
            if hasattr(self, 'filter_panel')
            else {}
        )

        # Filter panel provides pre-resolved prefix lists — use them directly.
        # Falls back to old group-resolution logic when filter_panel is unavailable.
        if '_language_prefixes' in filter_state:
            language_prefixes = filter_state['_language_prefixes'] or []
            region_prefixes   = filter_state['_region_prefixes']   or []
            platform_prefixes = filter_state['_platform_prefixes'] or []
            quality_prefixes  = filter_state['_quality_prefixes']  or []
        else:
            _all_lang_groups  = set(self.config.filter_language_groups.keys()) | (
                {"Other"} if self._filter_unmapped_prefixes else set()
            )
            _sel_lang_groups  = set(filter_state.get('language_groups', []))
            if _all_lang_groups and _sel_lang_groups >= _all_lang_groups:
                language_prefixes = []
            else:
                language_prefixes = []
                for group_name in _sel_lang_groups:
                    if group_name == "Other":
                        language_prefixes.extend(self._filter_unmapped_prefixes)
                    else:
                        language_prefixes.extend(
                            self.config.filter_language_groups.get(group_name, []))

            _all_qual_groups = set(self.config.filter_quality_groups.keys())
            _sel_qual_groups = set(filter_state.get('quality_groups', []))
            quality_prefixes = [] if _all_qual_groups and _sel_qual_groups >= _all_qual_groups else [
                p for g in _sel_qual_groups
                for p in self.config.filter_quality_groups.get(g, [])
            ]

            _all_plat_groups = set(self.config.filter_platform_groups.keys())
            _sel_plat_groups = set(filter_state.get('platform_groups', []))
            platform_prefixes = [] if _all_plat_groups and _sel_plat_groups >= _all_plat_groups else [
                p for g in _sel_plat_groups
                for p in self.config.filter_platform_groups.get(g, [])
            ]

            _all_region_groups = set(self.config.filter_regional_groups.keys())
            _sel_region_groups = set(filter_state.get('region_groups', []))
            region_prefixes = [] if _all_region_groups and _sel_region_groups >= _all_region_groups else [
                p for g in _sel_region_groups
                for p in self.config.filter_regional_groups.get(g, [])
            ]

        # Resolve provider filter on main thread (tiny queries)
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            active_providers = repos.providers.get_all(active_only=True)
            all_providers   = repos.providers.get_all()
        finally:
            session.close()

        active_provider_ids = [p.id for p in active_providers]
        force_adult_ids     = [p.id for p in all_providers if getattr(p, 'force_adult', False)]
        excluded_ids        = set(filter_state.get('excluded_provider_ids', []))

        if provider_id:
            target_provider_id = provider_id
        else:
            visible_ids = [pid for pid in active_provider_ids if pid not in excluded_ids]
            if len(visible_ids) == len(active_provider_ids) and len(visible_ids) == 1:
                target_provider_id = visible_ids[0]
            elif len(visible_ids) < len(active_provider_ids):
                target_provider_id = visible_ids if visible_ids else None
            else:
                target_provider_id = None

        # Build provider icon map (used later for display)
        show_provider_icon = (target_provider_id is None)
        provider_icon_map: dict = {}
        if show_provider_icon:
            for p in all_providers:
                provider_icon_map[p.id] = (getattr(p, "icon", "") or self.config.provider_icon)

        from metatv.core.filter_utils import get_excluded_prefixes, get_active_category_filter
        _filter_paused = self.config.global_filter_paused
        if _filter_paused:
            _global_excluded_prefixes: set = set()
        else:
            _cat_excluded, _ = get_active_category_filter(self.config)
            _global_excluded_prefixes = set(_cat_excluded or []) | get_excluded_prefixes(self.config)
        _search_text = (self.search_input.text().strip()
                        if hasattr(self, 'search_input') else "")
        # _bypass_tier1_filters: set when user clicks "Show filtered results" in the
        # zero-results state. Allows them to see what's hidden without changing settings.
        _bypassing = self._bypass_tier1_filters
        _genre_filters = filter_state.get('_genre_filters')
        params = dict(
            provider_id=target_provider_id,
            media_types=filter_state.get('media_types', ['live', 'movie', 'series']),
            language_prefixes=None if _bypassing else (language_prefixes or None),
            region_prefixes=None if _bypassing else (region_prefixes or None),
            quality_prefixes=None if _bypassing else (quality_prefixes or None),
            platform_prefixes=None if _bypassing else (platform_prefixes or None),
            genre_filters=None if _bypassing else _genre_filters,
            invert_prefix_filters=False,
            include_untagged=filter_state.get('include_untagged', True),
            include_untagged_quality=filter_state.get('include_untagged_quality', True),
            adult_mode=filter_state.get('adult_mode', 'hide'),
            force_adult_ids=force_adult_ids,
            # Global filter — bypassed when paused so the user can see everything
            source_categories=None if _filter_paused else get_active_content_type_filter(self.config),
            excluded_prefixes=_global_excluded_prefixes,
            excluded_user_categories=set() if _filter_paused else set(self.config.global_filter_excluded_user_categories),
            search_query=_search_text or None,
            page_size=self._search_page_size,
            show_provider_icon=show_provider_icon,
            provider_icon_map=provider_icon_map,
            given_provider_id=provider_id,
            hidden_only=self._hidden_mode,
            bypassing_tier1=_bypassing,
        )

        # Stamp a token so stale results from a previous query are discarded
        self._load_channels_token += 1
        token = self._load_channels_token
        self.executor.submit(self._bg_load_channels, params, token)

    def _bg_load_channels(self, params: dict, token: int) -> None:
        """Worker thread: run the heavy DB query, then signal back to main thread."""
        session = self.db.get_session()
        try:
            from metatv.core.database import ChannelDB
            repos = RepositoryFactory(session)

            force_adult_ids = params['force_adult_ids']
            hidden_only = params.get('hidden_only', False)
            _page_size = params.get('page_size', 5_000)
            if hidden_only:
                channels = repos.channels.get_hidden_channels(
                    excluded_user_categories=params.get('excluded_user_categories'),
                    search_query=params.get('search_query'),
                    provider_id=params['provider_id'],
                )
            else:
                channels = repos.channels.get_all(
                    provider_id=params['provider_id'],
                    media_types=params['media_types'],
                    language_prefixes=params['language_prefixes'],
                    region_prefixes=params.get('region_prefixes'),
                    quality_prefixes=params['quality_prefixes'],
                    platform_prefixes=params.get('platform_prefixes'),
                    genre_filters=params.get('genre_filters'),
                    invert_prefix_filters=params['invert_prefix_filters'],
                    include_untagged=params['include_untagged'],
                    include_untagged_quality=params.get('include_untagged_quality', True),
                    adult_mode=params['adult_mode'],
                    force_adult_provider_ids=force_adult_ids or None,
                    source_categories=params['source_categories'],
                    include_uncategorized_content_types=True,
                    hidden_only=False,
                    include_hidden=False,
                    search_query=params.get('search_query'),
                    limit=_page_size,
                )
            total = repos.channels.count(provider_id=params['provider_id'])
            has_adult = bool(force_adult_ids) or session.query(ChannelDB).filter(
                ChannelDB.is_adult == True
            ).limit(1).count() > 0
            if not hidden_only:
                excluded_prefixes = params.get('excluded_prefixes', set())
                if excluded_prefixes:
                    channels = [
                        c for c in channels
                        if c.detected_prefix not in excluded_prefixes
                        and c.detected_region not in excluded_prefixes
                    ]
                excluded_user_cats = params.get('excluded_user_categories', set())
                if excluded_user_cats:
                    channels = [
                        c for c in channels
                        if c.user_category not in excluded_user_cats
                    ]

            # When zero results + Tier 1 filters active, count what exists without
            # those filters so we can tell the user "X results are filtered out".
            filtered_out_count = 0
            tier1_active = any([
                params.get('language_prefixes'),
                params.get('region_prefixes'),
                params.get('quality_prefixes'),
                params.get('platform_prefixes'),
            ])
            if not hidden_only and len(channels) == 0 and tier1_active:
                unfiltered = repos.channels.get_all(
                    provider_id=params['provider_id'],
                    media_types=params.get('media_types'),
                    adult_mode=params.get('adult_mode', 'all'),
                    force_adult_provider_ids=force_adult_ids or None,
                    source_categories=params.get('source_categories'),
                    search_query=params.get('search_query'),
                    limit=_page_size,
                )
                # Apply global exclusions to the unfiltered set too
                if excluded_prefixes:
                    unfiltered = [
                        c for c in unfiltered
                        if c.detected_prefix not in excluded_prefixes
                        and c.detected_region not in excluded_prefixes
                    ]
                filtered_out_count = len(unfiltered)

            # get_all() now returns results sorted and limited — no extra sort needed
            params['total_channels']    = total
            params['has_adult']         = has_adult
            params['token']             = token
            params['filtered_out_count'] = filtered_out_count
            self._channels_loaded.emit(channels, params)
        except Exception as e:
            logger.error(f"Channel query failed: {e}")
        finally:
            session.close()

    def _on_channels_loaded(self, channels: list, params: dict) -> None:
        """Main thread: build the channel list UI from query results."""
        # Discard results from a superseded query
        if params.get('token') != self._load_channels_token:
            return

        total_channels    = params.get('total_channels', 0)
        has_adult         = params.get('has_adult', False)
        show_provider_icon = params.get('show_provider_icon', False)
        provider_icon_map  = params.get('provider_icon_map', {})
        given_provider_id  = params.get('given_provider_id')

        # Adult filter now lives in filter panel (no separate toggle needed)

        logger.info(f"=== Loading {len(channels):,} channels (filtered from {total_channels:,} total) ===")

        if not channels:
            logger.warning("No channels match current filters!")
            if params.get('hidden_only'):
                self.status_bar.showMessage("No hidden channels found")
                self.stats_label.setText("No hidden channels")
            else:
                filtered_out = params.get('filtered_out_count', 0)
                if filtered_out > 0:
                    # Results exist but are hidden by Tier 1 filters — show an
                    # actionable button so the user can expose them without touching settings.
                    from PyQt6.QtWidgets import QListWidgetItem, QPushButton, QWidget, QHBoxLayout
                    btn_item = QListWidgetItem()
                    btn_item.setFlags(Qt.ItemFlag.NoItemFlags)
                    btn_widget = QPushButton(
                        f"{filtered_out:,} result{'s' if filtered_out != 1 else ''} filtered  —  click to show"
                    )
                    btn_widget.setToolTip(
                        "Your current Category / Quality / Platform filters are hiding these results.\n"
                        "Click to temporarily show them. Filters are not changed.\n"
                        "Changing filters or searching again restores normal filtered view."
                    )
                    btn_widget.setStyleSheet(
                        "QPushButton { background: #3a3a1a; color: #e8d44d; border: 1px solid #7a7a30;"
                        " border-radius: 4px; padding: 8px 16px; font-size: 12px; }"
                        "QPushButton:hover { background: #4a4a22; border-color: #aaaa50; }"
                    )
                    btn_widget.clicked.connect(self._show_filtered_results)
                    self.channels_list.addItem(btn_item)
                    self.channels_list.setItemWidget(btn_item, btn_widget)
                    btn_item.setSizeHint(btn_widget.sizeHint())
                    self.status_bar.showMessage(
                        f"No results — {filtered_out:,} match{'es' if filtered_out == 1 else ''} hidden by current filters"
                    )
                    self.stats_label.setText(f"0 shown · {filtered_out:,} filtered")
                else:
                    self.status_bar.showMessage("No channels match — try a different search or check filter settings")
                    self.stats_label.setText(f"Showing 0 of {total_channels:,}")
            return

        # Track bypass state so filter_channels() can show the banner
        self._currently_bypassing = params.get('bypassing_tier1', False)

        for channel in channels:
            media_icon = self.get_media_type_icon(channel.media_type)
            fav_icon   = self.favorite_icon if channel.is_favorite else self.unfavorite_icon
            src_badge  = ""
            if show_provider_icon and channel.provider_id in provider_icon_map:
                src_badge = provider_icon_map[channel.provider_id] + " "

            _p = parse_channel_name(channel.name)
            prefix_str = f"[{_p.region}] " if _p.region else ""
            lang_str = f"[{_p.lang}] " if _p.lang else ""
            quality_str = f" [{channel.quality.upper()}]" if channel.quality and channel.quality != "unknown" else ""
            year_str = f" · {_p.year}" if _p.year else ""
            display_text = f"{src_badge}{media_icon}{fav_icon} {prefix_str}{lang_str}{_p.bare_name}{quality_str}{year_str}"
            if channel.category:
                display_text += f" [{channel.category}]"
            self.all_channels.append((display_text, channel))

        shown    = len(channels)
        if params.get('hidden_only'):
            self.stats_label.setText(f"{shown:,} hidden channel{'s' if shown != 1 else ''}")
            self.status_bar.showMessage(f"{shown:,} hidden channel{'s' if shown != 1 else ''} — right-click to unhide")
        else:
            panel_filtering = any([
                params.get('language_prefixes'),
                params.get('region_prefixes'),
                params.get('quality_prefixes'),
                params.get('platform_prefixes'),
            ])
            if panel_filtering:
                excluded = total_channels - shown
                self.stats_label.setText(
                    f"Showing {shown:,} of {total_channels:,} · {excluded:,} filtered out"
                )
            else:
                self.stats_label.setText(f"Showing {shown:,} of {total_channels:,} channels")
            if given_provider_id:
                self.status_bar.showMessage(f"{shown:,} channels from selected provider")
            else:
                self.status_bar.showMessage(f"{shown:,} channels from active providers")

        self.filter_channels()
    
    def filter_channels(self, _unused: str = "") -> None:
        """Render the currently-loaded channels into the list widget.

        Search filtering is now pushed to SQL (in load_channels), so this method
        only handles rendering. The _unused parameter is kept for any callers that
        still pass a text argument.
        """
        self.channels_list.setUpdatesEnabled(False)
        self.channels_list.clear()

        # If this is a bypass load, show a sticky banner at the top so the user
        # knows their normal filters are suspended for this result set.
        if self._currently_bypassing:
            from PyQt6.QtWidgets import QListWidgetItem as _LI
            banner = _LI("⚠  Showing results from filtered categories — filters suspended. Change search or filters to restore.")
            banner.setFlags(Qt.ItemFlag.NoItemFlags)
            banner.setForeground(self.channels_list.palette().color(
                self.channels_list.palette().ColorRole.Mid
            ))
            self.channels_list.addItem(banner)

        total = len(self.all_channels)
        shown = min(total, self.max_display_limit)

        for display_text, channel in self.all_channels[:shown]:
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, channel.id)
            self.channels_list.addItem(item)

        if shown < total:
            notice = QListWidgetItem(
                f"⚠  Showing first {shown:,} of {total:,} — refine search to see more"
            )
            notice.setFlags(Qt.ItemFlag.NoItemFlags)
            self.channels_list.addItem(notice)
            self.status_bar.showMessage(
                f"Showing {shown:,} of {total:,} channels — type to search"
            )
        elif total == self._search_page_size:
            # We hit the SQL page cap — there may be more in the DB
            notice = QListWidgetItem(
                f"⚠  Showing {total:,} channels — use search to narrow results"
            )
            notice.setFlags(Qt.ItemFlag.NoItemFlags)
            self.channels_list.addItem(notice)
            self.status_bar.showMessage(
                f"{total:,} channels loaded (page cap reached — search to narrow)"
            )
        elif total == 0:
            self.status_bar.showMessage("No channels match — try a different search or filter")
        else:
            self.status_bar.showMessage(f"{total:,} channels loaded")

        logger.debug(f"filter_channels: rendered {shown} of {total} items")
        self.channels_list.setUpdatesEnabled(True)
    
    def get_enabled_media_types(self) -> list:
        """Get list of enabled media types from the filter panel."""
        if hasattr(self, 'filter_panel'):
            return self.filter_panel.get_filter_state().get(
                'media_types', ['live', 'movie', 'series'])
        return ['live', 'movie', 'series']
    
    def _open_category_picker(self, channel_ids: list[str]) -> None:
        """Open the CategoryPickerDialog and assign the selected category to channel_ids."""
        from metatv.gui.category_picker_dialog import CategoryPickerDialog
        dlg = CategoryPickerDialog(self.db, self.config, len(channel_ids), self)
        if dlg.exec() != CategoryPickerDialog.DialogCode.Accepted:
            return

        category = dlg.selected_category()
        mood     = dlg.selected_mood()
        exclude  = dlg.add_to_exclusions()

        if not category:
            return

        # Global Exclusions — update config on main thread before submitting the worker
        # so the signal-triggered reload sees the updated exclusion set.
        if exclude and category not in self.config.global_filter_excluded_user_categories:
            self.config.global_filter_excluded_user_categories.append(category)
            self.config.save()
            self._update_filter_btn_state()

        # Assign in background — emit signal after commit so reload is guaranteed post-write
        def _do_assign():
            session = self.db.get_session()
            try:
                repos = RepositoryFactory(session)
                updated = repos.channels.assign_user_category(channel_ids, category, mood)
                logger.info(
                    f"Assigned {updated} channels to category {category!r} mood={mood!r}"
                )  # noqa
            finally:
                session.close()
            self._category_assigned.emit()

        self.executor.submit(_do_assign)

        # Notify the user
        n = len(channel_ids)
        excl_note = " (added to Global Exclusions)" if exclude else ""
        self.status_bar.showMessage(
            f"{n:,} channel{'s' if n != 1 else ''} → \"{category}\"{excl_note}"
        )

        if hasattr(self, "discover_view"):
            QTimer.singleShot(500, self.discover_view.reload)

    def _show_filtered_results(self) -> None:
        """Temporarily bypass Tier 1 filters to show what's being hidden.

        Called when the user clicks the "N results filtered" button in the zero-results
        state. Filters are not changed — next search or filter change restores normal view.
        """
        self._bypass_tier1_filters = True
        self.load_channels()

    def on_filter_changed(self):
        """Handle filter changes from FilterBar or media chips"""
        logger.info("Filter changed, reloading channels...")
        self._bypass_tier1_filters = False  # user changed filters — cancel any bypass
        self.current_filter_state = (
            self.filter_panel.get_filter_state()
            if hasattr(self, 'filter_panel')
            else {}
        )
        # Chip state drives provider filtering; sidebar selection is set separately
        # via on_provider_selected_new which calls load_channels(provider_id) directly.
        self.load_channels(None)
    
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
                platform_groups=self.config.filter_platform_groups,
                regional_groups=self.config.filter_regional_groups,
                excluded_user_categories=set(self.config.global_filter_excluded_user_categories),
            )

            self._filter_unmapped_prefixes = stats.get('unmapped_prefixes', [])
            # Populate the filter panel with live counts
            if hasattr(self, 'filter_panel'):
                self.filter_panel.update_data(stats)

            logger.info(f"Initialized filter stats: {stats['channels_with_prefix']:,} channels with prefixes")
            
        except Exception as e:
            logger.error(f"Failed to initialize filter stats: {e}")
        finally:
            session.close()
    
    # ---- Context menu shared infrastructure ------------------------------------

    def _show_context_menu_for(self, channel_id: str, gx: int, gy: int,
                               variant: str) -> None:
        """Fetch context data in background and show the menu on the main thread."""
        self.executor.submit(self._bg_fetch_ctx_data, channel_id, gx, gy, variant)

    def _bg_fetch_ctx_data(self, channel_id: str, gx: int, gy: int,
                           variant: str) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                return
            in_queue = repos.queue.is_queued(channel_id)
            rating = repos.ratings.get(channel.id)
        finally:
            session.close()
        self._ctx_data_ready.emit(channel, in_queue, rating, gx, gy, variant)

    def _on_ctx_data_ready(self, channel, in_queue: bool, rating,
                           gx: int, gy: int, variant: str) -> None:
        from PyQt6.QtCore import QPoint
        menu = self._build_channel_menu(channel, in_queue, rating, variant)
        menu.exec(QPoint(gx, gy))

    def _build_channel_menu(self, channel, in_queue: bool, rating, variant: str):
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        channel_id = channel.id
        menu = QMenu(self)

        play_act = QAction("Play", self)
        if variant == "history":
            play_act.triggered.connect(lambda: self.play_from_history_id(channel_id))
        elif variant == "favorites":
            play_act.triggered.connect(lambda: self.play_favorite_id(channel_id))
        else:
            play_act.triggered.connect(lambda: self.play_channel_by_id(channel_id))
        menu.addAction(play_act)

        menu.addSeparator()

        if channel.is_favorite:
            fav_act = QAction(f"Remove from Favorites ({self.unfavorite_icon})", self)
            fav_act.triggered.connect(lambda: self._toggle_favorite_by_id(channel_id, False))
        else:
            fav_act = QAction(f"Add to Favorites ({self.favorite_icon})", self)
            fav_act.triggered.connect(lambda: self._toggle_favorite_by_id(channel_id, True))
        menu.addAction(fav_act)

        queue_act = QAction(
            f"{self.config.queue_icon} {'Remove from Queue' if in_queue else 'Add to Queue'}", self
        )
        queue_act.triggered.connect(
            lambda: self._remove_from_queue(channel_id) if in_queue
            else self._add_to_queue(channel_id)
        )
        menu.addAction(queue_act)

        if variant == "history":
            menu.addSeparator()
            remove_act = QAction(f"Remove from History ({self.delete_icon})", self)
            remove_act.triggered.connect(lambda: self.remove_from_history(channel_id))
            menu.addAction(remove_act)
            hide_act = QAction(f"{self.hide_icon} Hide channel", self)
            hide_act.triggered.connect(lambda: self._hide_channel_from_history(channel_id))
            menu.addAction(hide_act)
        elif variant == "channel":
            menu.addSeparator()
            if channel.is_hidden:
                unhide_act = QAction(f"{self.config.hide_icon} Unhide", self)
                unhide_act.triggered.connect(lambda: self._unhide_channel(channel_id))
                menu.addAction(unhide_act)
            else:
                if channel.id in self.config.epg_watchlist_channels:
                    watch_act = QAction("Stop watching this channel", self)
                    watch_act.triggered.connect(lambda: self._unwatch_channel_from_list(channel.id))
                else:
                    watch_act = QAction("Watch this channel (EPG alerts)", self)
                    watch_act.triggered.connect(lambda: self._watch_channel_from_list(channel.id))
                menu.addAction(watch_act)
                track_act = QAction("Track keyword…", self)
                track_act.triggered.connect(lambda: self._prompt_track_from_list(channel.name))
                menu.addAction(track_act)
                hide_act = QAction(f"{self.config.hide_icon} Hide", self)
                hide_act.triggered.connect(lambda: self._hide_channel_from_recommendations(channel_id))
                menu.addAction(hide_act)

        if channel.media_type in ("movie", "series"):
            menu.addSeparator()
            like_act = QAction(f"{self.config.like_icon} Like", self)
            like_act.setCheckable(True)
            like_act.setChecked(rating == 1)
            like_act.triggered.connect(lambda checked, cid=channel_id: self._toggle_rating(cid, 1))
            menu.addAction(like_act)
            dislike_act = QAction(f"{self.config.dislike_icon} Dislike", self)
            dislike_act.setCheckable(True)
            dislike_act.setChecked(rating == -1)
            dislike_act.triggered.connect(lambda checked, cid=channel_id: self._toggle_rating(cid, -1))
            menu.addAction(dislike_act)

        # Category assignment — always available
        menu.addSeparator()
        cat_label = channel.user_category
        if cat_label:
            cat_act = QAction(
                f"{self.config.queue_icon} Category: {cat_label}  (change…)", self
            )
        else:
            cat_act = QAction(
                f"{self.config.queue_icon} Add to Category…", self
            )
        cat_act.setToolTip(
            "Assign this channel to a user-defined category.\n"
            "Categories appear as shelves in the Discover view."
        )
        cat_act.triggered.connect(lambda: self._open_category_picker([channel_id]))
        menu.addAction(cat_act)

        return menu

    # ---- Context menu entry points ------------------------------------------

    def show_history_context_menu(self, position, list_widget=None):
        if list_widget is None:
            if "history" in self.sidebar_sections:
                list_widget = self.sidebar_sections["history"].history_list
            else:
                return
        item = list_widget.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        gp = list_widget.mapToGlobal(position)
        self._show_context_menu_for(channel_id, gp.x(), gp.y(), "history")

    def _hide_channel_from_history(self, channel_id: str) -> None:
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.channels.set_hidden(channel_id, True)
            self.load_history()
            self.load_channels()
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
        from metatv.core.models import MediaType
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                if channel.media_type == MediaType.SERIES:
                    last_episode = repos.episodes.get_last_played(
                        series_id=channel.source_id,
                        provider_id=channel.provider_id
                    )
                    if last_episode:
                        logger.info(f"Playing last watched episode from history: {last_episode.title}")
                        self.play_episode(last_episode)
                    else:
                        logger.info("No episode history found, opening series view")
                        self.drill_into_series(channel)
                else:
                    self.play_media(channel)
        finally:
            session.close()
    
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
        if list_widget is None:
            if hasattr(self, 'favorites_list'):
                list_widget = self.favorites_list
            else:
                return
        item = list_widget.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        gp = list_widget.mapToGlobal(position)
        self._show_context_menu_for(channel_id, gp.x(), gp.y(), "favorites")

    def show_channel_context_menu(self, position):
        item = self.channels_list.itemAt(position)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return

        # Collect all selected channel IDs (multi-select aware)
        selected_ids = [
            i.data(Qt.ItemDataRole.UserRole)
            for i in self.channels_list.selectedItems()
            if i.data(Qt.ItemDataRole.UserRole)
        ]
        if not selected_ids:
            selected_ids = [item.data(Qt.ItemDataRole.UserRole)]

        channel_id = item.data(Qt.ItemDataRole.UserRole)
        gp = self.channels_list.mapToGlobal(position)

        if len(selected_ids) > 1:
            # Multi-select context menu — only show bulk actions
            self._show_multi_select_context_menu(selected_ids, gp)
        else:
            self._show_context_menu_for(channel_id, gp.x(), gp.y(), "channel")

    def _quick_assign_category(
        self,
        channel_ids: list[str],
        category: str,
        mood: str | None,
        exclude: bool,
    ) -> None:
        """Assign channel_ids to category immediately, no dialog."""
        # Update config on main thread first so the signal-triggered reload sees the exclusion.
        if exclude and category not in self.config.global_filter_excluded_user_categories:
            self.config.global_filter_excluded_user_categories.append(category)
            self.config.save()
            self._update_filter_btn_state()

        def _do_assign():
            session = self.db.get_session()
            try:
                repos = RepositoryFactory(session)
                repos.channels.assign_user_category(channel_ids, category, mood)
            finally:
                session.close()
            self._category_assigned.emit()

        self.executor.submit(_do_assign)

        n = len(channel_ids)
        excl_note = " (added to Global Exclusions)" if exclude else ""
        self.status_bar.showMessage(
            f"{n:,} channel{'s' if n != 1 else ''} → \"{category}\"{excl_note}"
        )

        if hasattr(self, "discover_view"):
            QTimer.singleShot(500, self.discover_view.reload)

    def _add_quick_pick_actions(self, menu, channel_ids: list[str]) -> None:
        """Add Trash / Watch Later / Explore quick-assign actions to menu."""
        from PyQt6.QtGui import QAction
        _picks = [
            ("🗑 Trash",       "Trash",       "dislike", True,
             "Assign to Trash — Dislike mood, added to Global Exclusions"),
            ("👀 Watch Later", "Watch Later", None,      False,
             "Assign to Watch Later — Neutral mood"),
            ("❓ Explore",     "Explore",     "curious", False,
             "Assign to Explore — Curious mood, surfaces more like this"),
        ]
        for label, name, mood, exclude, tip in _picks:
            act = QAction(label, self)
            act.setToolTip(tip)
            act.triggered.connect(
                lambda _, n=name, m=mood, ex=exclude:
                    self._quick_assign_category(channel_ids, n, m, ex)
            )
            menu.addAction(act)

    def _show_multi_select_context_menu(self, channel_ids: list[str], gp) -> None:
        """Context menu shown when multiple channels are selected."""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        n = len(channel_ids)

        self._add_quick_pick_actions(menu, channel_ids)
        menu.addSeparator()

        cat_action = menu.addAction(
            f"{self.config.queue_icon} Add {n:,} selected channel{'s' if n != 1 else ''} to Category…"
        )
        cat_action.triggered.connect(lambda: self._open_category_picker(channel_ids))
        cat_action.setToolTip("Assign a user-defined category to the selected channels")

        menu.exec(gp)
    
    def play_favorite(self, item):
        """Play a favorite channel"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        
        # Reuse existing play_channel logic
        self.play_channel(item)
    
    def play_favorite_id(self, channel_id: str):
        """Play a favorite channel by ID"""
        from metatv.core.models import MediaType
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if channel:
                if channel.media_type == MediaType.SERIES:
                    self.drill_into_series(channel)
                else:
                    self.play_media(channel)
        finally:
            session.close()
    
    def _apply_favorite_toggle(self, channel_id: str):
        """Toggle favorite in DB, show status bar message, refresh sidebar.

        Returns (channel, new_status) on success, or None if channel not found.
        """
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                return None
            new_status = repos.channels.toggle_favorite(channel_id)
            channel.is_favorite = new_status
        finally:
            session.close()

        status = "added to" if channel.is_favorite else "removed from"
        self.status_bar.showMessage(f"{channel.name} {status} favorites")
        logger.info(f"Toggled favorite for {channel.name}: {channel.is_favorite}")
        self.load_favorites()
        return channel, new_status

    def toggle_favorite(self, item):
        """Toggle favorite status of a channel"""
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return

        result = self._apply_favorite_toggle(channel_id)
        if not result:
            return
        channel, _ = result

        # Update the icon on the current item only (fast, no database query)
        current_text = item.text()
        if channel.is_favorite:
            updated_text = current_text.replace(self.unfavorite_icon, self.favorite_icon)
        else:
            updated_text = current_text.replace(self.favorite_icon, self.unfavorite_icon)
        item.setText(updated_text)

        # Also update in all_channels cache for filtering
        for i, (text, ch) in enumerate(self.all_channels):
            if ch.id == channel_id:
                ch.is_favorite = channel.is_favorite
                media_icon = self.get_media_type_icon(ch.media_type)
                fav_icon = self.favorite_icon if ch.is_favorite else self.unfavorite_icon
                display_text = f"{media_icon}{fav_icon} {ch.name}"
                if ch.category:
                    display_text += f" [{ch.category}]"
                if ch.quality and ch.quality != "unknown":
                    display_text += f" ({ch.quality})"
                self.all_channels[i] = (display_text, ch)
                break
    
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
        if not channel_id or channel_id == self._last_shown_channel_id:
            return
        self._last_shown_channel_id = channel_id

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
        from metatv.core.models import MediaType

        # Live channels have no TMDb/OMDb metadata — show basic info and return.
        # EPG agenda and channel icon are handled directly by the details pane.
        if getattr(channel, "media_type", None) == MediaType.LIVE:
            self.details_pane.set_provider_urls([])
            self.details_pane.show_channel(channel, metadata=None)
            return

        # Get provider URLs for image failover
        provider_urls = []
        try:
            session = self.db.get_session()
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(channel.provider_id)
            if provider_db and provider_db.urls:
                urls_data = parse_provider_urls(provider_db.urls)
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
        
        # Reuse the long-lived executor — creating a per-call pool leaks threads
        future = self.executor.submit(fetch_metadata)
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
        result = self._apply_favorite_toggle(channel_id)
        if not result:
            return
        channel, _ = result

        # Update details pane — but not while the lightbox has focus (D6)
        if not (hasattr(self, '_lightbox') and self._lightbox.isVisible()):
            self.update_details_pane_for_channel(channel)

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
        """Switch content area back to channel list view."""
        self.view_mode = "list"
        self._in_provider_edit_mode = False
        self._hide_all_content_views()
        self._deactivate_view_chips(self.search_chip)
        self.search_chip.blockSignals(True)
        self.search_chip.set_enabled(True)
        self.search_chip.blockSignals(False)

        self.channels_list.setVisible(True)
        self.search_controls.setVisible(True)
        if hasattr(self, "filter_panel"):
            self.filter_panel.setVisible(True)
        self.search_input.setEnabled(True)
        self.search_input.setPlaceholderText("Filter channels by name, category...")

        if hasattr(self, 'all_channels') and self.all_channels:
            total_channels = len(self.all_channels)
            shown = self.channels_list.count()
            for i in range(self.channels_list.count()):
                item = self.channels_list.item(i)
                if not item.data(Qt.ItemDataRole.UserRole):
                    shown -= 1
            filtered = total_channels - shown
            if filtered > 0:
                self.stats_label.setText(f"Showing {shown:,} of {total_channels:,} · {filtered:,} filtered out")
            else:
                self.stats_label.setText(f"Showing {shown:,} of {total_channels:,} channels")

        self.current_series = None
        self.series_data = None
        self.status_bar.showMessage("Returned to channel list")
    
    def switch_to_epg_view(self):
        """Switch content area to EPG view."""
        self.view_mode = "epg"
        self._hide_all_content_views()
        self.epg_view.setVisible(True)
        self.epg_view.on_activate()
        total = self.epg_manager.get_total_programmes(self.epg_view._provider_ids)
        self.stats_label.setText(f"{total:,} EPG programmes" if total else "EPG — fetching…")

    def play_special_event(self, channel):
        """Play a channel from a special content view."""
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
        """Handle channel selected from a content view."""
        if channel:
            self.details_pane.show_channel(channel)

    def _deactivate_view_chips(self, *keep) -> None:
        """Deactivate all view chips except those in keep."""
        for chip in (self.search_chip, self.epg_chip, self.prefs_chip,
                     self.discover_chip):
            if chip not in keep:
                chip.blockSignals(True)
                chip.set_enabled(False)
                chip.blockSignals(False)

    def on_special_view_toggle(self) -> None:
        if self.epg_chip.is_enabled():
            self._deactivate_view_chips(self.epg_chip)
            self.switch_to_epg_view()
        else:
            self.switch_to_list_view()

    def on_preferences_view_toggle(self) -> None:
        if self.prefs_chip.is_enabled():
            self._deactivate_view_chips(self.prefs_chip)
            self.switch_to_preferences_view()
        else:
            self.switch_to_list_view()

    def _update_filter_btn_state(self) -> None:
        """Sync FilterChip visual state with current filter config."""
        active = (
            bool(self.config.global_filter_excluded_categories)
            or bool(self.config.global_filter_excluded_content_types)
            or bool(self.config.global_filter_excluded_prefixes)
        )
        self._filter_chip.set_filter_state(active, self.config.global_filter_paused)

    def _on_filter_toggle(self, resume: bool) -> None:
        """FilterChip clicked while filters are set: resume=True → unpause, False → pause."""
        self.config.global_filter_paused = not resume
        self.config.save()
        self._update_filter_btn_state()
        self.load_channels()
        if hasattr(self, "discover_view"):
            self.discover_view.reload()
        if hasattr(self, "preferences_view"):
            self.preferences_view.refresh()
        self._refresh_recommended_section()

    def _open_global_filter_dialog(self) -> None:
        from metatv.gui.global_filter_dialog import GlobalFilterDialog
        dlg = GlobalFilterDialog(self.db, self.config, self)
        if dlg.exec() == GlobalFilterDialog.DialogCode.Accepted:
            # If the user configured filters, ensure they're unpaused so they take effect
            self.config.global_filter_paused = False
            self.config.save()
            self._update_filter_btn_state()
            self.load_channels()
            if hasattr(self, "discover_view"):
                self.discover_view.reload()
            if hasattr(self, "preferences_view"):
                self.preferences_view.refresh()
            self._refresh_recommended_section()

    def on_discover_view_toggle(self) -> None:
        if self.discover_chip.is_enabled():
            self._deactivate_view_chips(self.discover_chip)
            self.switch_to_discover_view()
        else:
            self.switch_to_list_view()

    def on_search_view_toggle(self) -> None:
        if self.search_chip.is_enabled():
            # Chip was just activated (ToggleChip self-toggles before emitting clicked)
            # → another view was active; switch to list view
            self.switch_to_list_view()
            self.load_channels()
        else:
            # User clicked Search while already in search mode — keep it active
            self.search_chip.blockSignals(True)
            self.search_chip.set_enabled(True)
            self.search_chip.blockSignals(False)

    def _set_search_tab(self, hidden: bool) -> None:
        """Switch the channel list between All and Hidden tabs."""
        self._tab_all_btn.setChecked(not hidden)
        self._tab_hidden_btn.setChecked(hidden)
        self._hidden_mode = hidden
        if hidden:
            self.view_mode = "hidden"
            self._hidden_banner.setVisible(True)
            self.stats_label.setText("Hidden channels")
            # Make sure the channel list view is active
            if self.view_mode not in ("hidden", "list"):
                self._hide_all_content_views()
                self.channels_list.setVisible(True)
                self.search_controls.setVisible(True)
        else:
            self.view_mode = "list"
            self._hidden_banner.setVisible(False)
        self.load_channels()

    def _open_categories_dialog(self) -> None:
        from metatv.gui.categories_dialog import CategoriesDialog
        dlg = CategoriesDialog(self.db, self.config, self)
        dlg.exec()
        # Refresh channel list in case any removals/reassignments happened
        self.load_channels()

    def on_hidden_view_toggle(self) -> None:
        # Legacy — kept for any callers; delegates to the new tab mechanism
        self._set_search_tab(True)

    def switch_to_preferences_view(self) -> None:
        """Switch content area to the Taste / Preferences dashboard."""
        self.view_mode = "preferences"
        self._hide_all_content_views()
        self.preferences_view.setVisible(True)
        self.stats_label.setText("Preference dashboard")
        self.preferences_view.on_activate()

    def switch_to_discover_view(self) -> None:
        """Switch content area to the Discovery browse view."""
        self.view_mode = "discover"
        self._hide_all_content_views()
        self.discover_view.setVisible(True)
        self.stats_label.setText("Discover")
        self.discover_view.on_activate()

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
        session = self.db.get_session()
        try:
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
                        season_item.setText(3, f"{self.rating_star_icon} {rating}")
                
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
                    watched_indicator = f"{self.watched_icon} " if episode.is_watched else ""
                    display_title = _clean_episode_title(
                        episode.title, episode.season_num, episode.episode_num, episode.series_name
                    )
                    episode_item.setText(0, f"  {self.episode_icon} {watched_indicator}{display_title}")
                    episode_item.setToolTip(0, episode.title)

                    # Episode number
                    episode_item.setText(1, f"E{episode.episode_num}")

                    # Duration — stored field first, fall back to raw_data["info"]["duration"]
                    dur_raw = episode.duration or (
                        (episode.raw_data or {}).get("info", {}).get("duration", "")
                    )
                    if dur_raw:
                        episode_item.setText(2, _format_episode_duration(dur_raw))
                    
                    # Rating from episode raw_data
                    if episode.raw_data and isinstance(episode.raw_data, dict):
                        info = episode.raw_data.get("info", {})
                        if isinstance(info, dict):
                            rating = info.get("rating", "")
                            if rating:
                                episode_item.setText(3, f"{self.rating_star_icon} {rating}")
                    
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
        finally:
            session.close()

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
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)

            repos.episodes.mark_played(episode.id)

            logger.info(f"Episode playback recorded: {episode.title}")
            logger.info(f"  Episode series_id: {episode.series_id}")
            logger.info(f"  Episode provider_id: {episode.provider_id}")

            parent_channel = repos.channels.get_by_source_id(
                provider_id=episode.provider_id,
                source_id=episode.series_id
            )

            if parent_channel:
                repos.channels.mark_played(parent_channel.id)
                logger.info(f"Updated parent series playback: {parent_channel.name} (play count: {parent_channel.play_count})")
            else:
                logger.warning(f"Could not find parent channel for episode. series_id={episode.series_id}, provider_id={episode.provider_id}")

            episodes_to_queue = []
            if self.config.autoplay_season_episodes and episode.season_id:
                all_episodes = repos.episodes.get_by_season(season_id=episode.season_id)
                episodes_to_queue = [
                    ep for ep in all_episodes
                    if ep.episode_num > episode.episode_num
                ]
                episodes_to_queue.sort(key=lambda ep: ep.episode_num)
                if episodes_to_queue:
                    episode_range = f"E{episodes_to_queue[0].episode_num}-E{episodes_to_queue[-1].episode_num}"
                    logger.info(f"Will queue {len(episodes_to_queue)} subsequent episodes: {episode_range}")
                    logger.debug(f"Queue list: {[f'E{ep.episode_num}: {ep.title}' for ep in episodes_to_queue]}")
        finally:
            session.close()
        
        # Update UI lists in real-time
        self.load_history()
        self.load_favorites()
        
        # Launch player with first episode
        self.launch_player_for_episode(episode.stream_url, episode.title, episodes_to_queue)
    
    def launch_player_for_episode(self, stream_url, title, queue_episodes=None):
        """Launch media player for an episode and queue subsequent episodes.

        Pre-flight validates the stream URL in a background thread before handing
        off to mpv, so text error responses (e.g. "not available") surface as an
        in-app notification rather than a black mpv window.
        """
        if not self.player_manager.is_available():
            logger.error("No media player available")
            self.status_bar.showMessage("Error: No media player found. Please install mpv.")
            return

        safe_title = title if not title.startswith("http") else "…"
        display_title = (safe_title[:55] + "…") if len(safe_title) > 55 else safe_title
        notif_id = self.notification_manager.show(
            title="Loading Episode",
            message=display_title,
            type="info",
            auto_dismiss_ms=6000,
        )

        def _preflight():
            ok, err = self.validate_stream_url(stream_url, timeout=6)
            return ok, err

        def _on_preflight_done(future):
            try:
                ok, err = future.result()
            except Exception as exc:
                logger.warning(f"Episode preflight check failed: {exc}")
                ok, err = True, None   # assume valid on unexpected errors

            if not ok:
                detail = err if err else "Stream did not respond"
                logger.warning(f"Episode stream unavailable: {title!r} — {detail}")
                self._episode_failed.emit(notif_id, title, detail, stream_url)
                return

            self._episode_ready.emit(notif_id, stream_url, title, queue_episodes)

        future = self.executor.submit(_preflight)
        future.add_done_callback(_on_preflight_done)

    def _on_episode_stream_unavailable(self, notif_id: str, title: str, detail: str, stream_url: str = "") -> None:
        from PyQt6.QtWidgets import QApplication
        from metatv.core.channel_name_utils import parse_channel_name
        # Dismiss the old "Checking stream" notif — safe even if it already auto-dismissed
        self.notification_manager.dismiss(notif_id)
        if title and not title.startswith("http"):
            p = parse_channel_name(title)
            safe_title = p.bare_name or title
        else:
            safe_title = ""
        _msg = f"{safe_title}\n{detail}".strip() if safe_title else detail
        self.notification_manager.show(
            title="Stream Unavailable",
            message=_msg,
            type="error",
            dismissible=True,
            auto_dismiss_seconds=None,
            actions=[("Copy Error", lambda t=title, u=stream_url, d=detail:
                QApplication.clipboard().setText(f"{t}\nURL: {u}\nError: {d}"))],
        )
        self.status_bar.showMessage(f"Stream unavailable: {title}")
        if stream_url and hasattr(self, "stream_retry_manager"):
            # Use stream_url as a stable ID for the retry entry
            self.stream_retry_manager.add_failure(stream_url, title, stream_url, detail)

    def _do_launch_episode(self, notif_id, stream_url, title, queue_episodes) -> None:
        """Actually launch mpv after a successful preflight check (called on main thread)."""
        self.notification_manager.dismiss(notif_id)
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
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            repos.episodes.mark_watched(episode.id, not episode.is_watched)
            logger.info(f"Toggled watched status for episode: {episode.title}")
        finally:
            session.close()
        
        # Refresh the tree to update display
        self.populate_series_tree()
    
    def validate_stream_url(self, url: str, timeout: int = 5) -> tuple[bool, str | None]:
        """Validate a stream URL by reading its first bytes.

        Returns ``(is_valid, error_message)``.  ``error_message`` is set when
        the server delivers a text error (e.g. "This channel is not available")
        instead of binary video data so the caller can surface it to the user.

        HEAD requests are unreliable for IPTV (servers often return 5xx on HEAD
        while serving fine on GET), so we use a streaming GET and read one chunk.
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
                    return False, f"HTTP {response.status_code}"
                chunk = next(response.iter_content(chunk_size=256), None)
                if chunk is None:
                    logger.warning(f"Stream URL returned no data")
                    return False, None
                # Detect text error messages (e.g. "This channel is not available")
                ct = response.headers.get("Content-Type", "").lower()
                is_text_ct = any(t in ct for t in ("text/", "application/json"))
                if is_text_ct or _looks_like_text(chunk):
                    msg = chunk.decode("utf-8", errors="replace").strip()
                    msg = msg.splitlines()[0][:160]   # first line, ≤160 chars
                    logger.warning(f"Stream URL returned text error: {msg!r}")
                    return False, msg or "Stream unavailable"
                logger.debug(f"Stream URL validated: HTTP {response.status_code}, got {len(chunk)} bytes")
                return True, None
        except requests.exceptions.Timeout:
            logger.warning(f"Stream URL validation timeout: {url}")
            return False, None
        except requests.exceptions.ConnectionError:
            logger.warning(f"Stream URL connection failed: {url}")
            return False, None
        except Exception as e:
            logger.warning(f"Stream URL validation error: {e}")
            return False, None
    
    def validate_and_failover_stream_url(
        self,
        stream_url: str,
        provider_id: str,
        source_id: str,
        media_type: str,
    ) -> tuple[str, str | None]:
        """Validate stream URL and try alternate provider URLs if needed.

        Returns ``(working_url, error_message)``.
        ``working_url`` is empty when all URLs fail; ``error_message`` is the
        server-provided text (e.g. "This channel is not available") or None.
        """
        ok, err_msg = self.validate_stream_url(stream_url)
        if ok:
            return stream_url, None

        logger.warning(f"Primary URL failed validation: {stream_url}")

        # If the primary URL returned a clear text error (e.g. "not available"),
        # skip alternate-URL probing — the error is content-level, not URL-level.
        if err_msg:
            return "", err_msg

        # Extract base URL from stream URL
        parsed = urlparse(stream_url)
        original_base = f"{parsed.scheme}://{parsed.netloc}"

        # Try alternate provider domains
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(provider_id)

            if not provider_db:
                logger.error(f"Provider not found: {provider_id}")
                return "", None

            provider_model = repos.providers.to_model(provider_db)
            candidate_bases = [u for u in provider_model.ordered_urls() if u.rstrip('/') != original_base]

            if not candidate_bases:
                logger.warning(f"Provider {provider_db.name} has no alternate URLs configured")
                logger.error("No working alternate URLs found")
                return "", None

            logger.info(f"Trying {len(candidate_bases)} alternate URL(s) for {provider_db.name} (reliability order)")

            raw_urls = parse_provider_urls(provider_db.urls)

            for alt_base in candidate_bases:
                new_stream_url = self.reconstruct_stream_url(stream_url, original_base, alt_base)
                logger.info(f"Trying: {new_stream_url}")

                url_entry = next((u for u in raw_urls if u.get('url', '').rstrip('/') == alt_base), None)
                alt_ok, alt_err = self.validate_stream_url(new_stream_url)
                if alt_ok:
                    logger.info("Alternate URL validated successfully")
                    if url_entry:
                        url_entry['success_count'] = url_entry.get('success_count', 0) + 1
                        url_entry['last_success'] = datetime.now().isoformat()
                        provider_db.urls = _json.dumps(raw_urls)
                        repos.providers.update(provider_db)
                        session.commit()
                    return new_stream_url, None
                else:
                    if url_entry:
                        url_entry['failure_count'] = url_entry.get('failure_count', 0) + 1
                        url_entry['last_failure'] = datetime.now().isoformat()
                        provider_db.urls = _json.dumps(raw_urls)
                        repos.providers.update(provider_db)
                        session.commit()
                    if alt_err:
                        return "", alt_err   # content-level error; stop trying

            logger.error("No working alternate URLs found")
            return "", None

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
            final_url, stream_err = self.validate_and_failover_stream_url(
                channel.stream_url,
                channel.provider_id,
                channel.source_id,
                channel.media_type
            )

            if not final_url:
                from PyQt6.QtWidgets import QApplication
                logger.error(f"All stream URLs failed validation for {channel.name}")
                self.status_bar.showMessage(f"Error: Stream unavailable for {channel.name}")
                detail = stream_err if stream_err else "All URLs failed (possibly geo-blocked)"
                self.notification_manager.dismiss(notif_id)
                from metatv.core.channel_name_utils import parse_channel_name as _pcn
                _p = _pcn(channel.name)
                _display = _p.bare_name or channel.name
                self.notification_manager.show(
                    title="Stream Unavailable",
                    message=f"{_display}\n{detail}",
                    type="error",
                    dismissible=True,
                    auto_dismiss_seconds=None,
                    actions=[("Copy Error", lambda n=channel.name, u=final_url, d=detail:
                        QApplication.clipboard().setText(f"{n}\nURL: {u}\nError: {d}"))],
                )
                if hasattr(self, "stream_retry_manager"):
                    self.stream_retry_manager.add_failure(
                        channel.id, channel.name, channel.stream_url, detail
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
                self._refresh_queue_section()
                
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
    
    def _save_filter_panel_width(self):
        """Persist filter panel width when inner splitter is moved."""
        try:
            sizes = self._inner_splitter.sizes()
            if sizes and sizes[0] > 0:
                self.config.filter_panel_width = sizes[0]
                self.config.save()
        except Exception:
            pass

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
            self.config.window_geometry = base64.b64encode(
                bytes(self.saveGeometry())
            ).decode("ascii")
        except Exception as e:
            logger.warning(f"Could not save window geometry: {e}")

        # Save splitter sizes one final time
        self.save_splitter_sizes()

        # Cleanup player resources
        self.player_manager.cleanup()

        # Stop retry manager background thread
        if hasattr(self, "stream_retry_manager"):
            self.stream_retry_manager.stop()

        # Shut down EPG timer and its worker pool
        if hasattr(self, "epg_manager"):
            self.epg_manager.shutdown()

        # Shut down image-fetch worker pool
        if hasattr(self, "image_cache"):
            self.image_cache.shutdown()

        # Shut down the main-window executor pool
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)

        # Close database
        self.db.close()
        event.accept()
