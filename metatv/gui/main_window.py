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
    QTreeWidget, QListView, QMenuBar, QMenu,
    QCheckBox, QLineEdit
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
from metatv.gui.main_window_streaming import _StreamingMixin, _looks_like_text
from metatv.gui.main_window_nav import _NavMixin
from metatv.gui.main_window_metadata import _MetadataMixin
from metatv.gui.main_window_favorites import _FavoritesMixin
from metatv.gui.main_window_async import _AsyncMixin
from metatv.gui.main_window_providers import _ProviderMixin
from metatv.gui.main_window_series import _SeriesMixin
from metatv.gui.main_window_channels import _ChannelListMixin
from metatv.core.database import Database, SeasonDB, EpisodeDB
from metatv.core.repositories.provider import parse_provider_urls
from metatv.core.notifications import NotificationManager
from metatv.core.player_manager import PlayerManager
from metatv.gui.notification_widget import NotificationWidget
from metatv.gui.provider_editor import ProviderEditorView
from metatv.gui.sidebar_sections import (
    SourcesSection, WatchAlertsSection,
    HistorySection, FavoritesSection,
    RecommendedSection, WatchQueueSection,
)
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.filter_bar import ToggleChip, FilterChip
from metatv.gui.collapsible_splitter import CollapsibleSplitter
from metatv.gui.details_pane import DetailsPaneWidget
from metatv.gui.details_actions import ChannelActionState
from metatv.gui.details_versions import ChannelVersion
from metatv.gui.discover_view import DiscoverView
from metatv.gui.epg_view import EpgView
from metatv.gui.preferences_view import PreferencesView
from metatv.gui.source_analytics_view import SourceAnalyticsView
from metatv.core.epg_manager import EpgManager
from metatv.core.series_monitor import SeriesMonitorManager
from metatv.core.migration_manager import MigrationManager
from metatv.core.image_cache import ImageCache
from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
from metatv.metadata_providers.provider_metadata import ProviderMetadataProvider
from metatv.gui.sidebar.new_episodes import NewEpisodesSection
from metatv.gui.migration_progress_widget import MigrationProgressWidget

from metatv.core.preference_engine import version_score as _version_score
from metatv.gui.whats_new_dialog import WhatsNewDialog
import metatv.whats_new as _whats_new

_YEAR_IN_NAME = re.compile(r'\b(19[5-9]\d|20[0-2]\d)\b')


def _name_year(name: str) -> int | None:
    """Year explicitly in the channel name (not from metadata)."""
    m = _YEAR_IN_NAME.search(name)
    return int(m.group(1)) if m else None


def _version_years_compatible(name_a: str, name_b: str) -> bool:
    """Return False only when BOTH names carry explicit, differing years.

    If either name lacks a year the match is accepted — a no-year channel is
    assumed to be the same production. Only when both names have distinct years
    (e.g. (1979) vs (1985)) are they treated as different productions.
    """
    yr_a = _name_year(name_a)
    yr_b = _name_year(name_b)
    return yr_a is None or yr_b is None or yr_a == yr_b


from PyQt6.QtCore import pyqtSignal as _pyqtSignal
from PyQt6.QtGui import QMouseEvent


class _ClickableNavLabel(QLabel):
    """A QLabel variant that emits ``clicked`` on left mouse-press.

    Used for the playback-health readout in the bottom nav bar so the user
    can click to cycle between open player windows.  Does NOT replicate the
    clipboard behaviour of ``details_sections._ClickableLabel`` — it is purely
    a click-event bridge.
    """

    clicked = _pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)



class MainWindow(_ProviderMixin, _SeriesMixin, _ChannelListMixin, _StreamingMixin, _NavMixin, _MetadataMixin, _FavoritesMixin, _AsyncMixin, QMainWindow):
    """Main application window"""
    
    # Signal for thread-safe metadata updates (channel_id, metadata)
    metadata_loaded = pyqtSignal(object, object)
    _category_assigned = pyqtSignal()               # emitted from worker after category DB write commits
    _versions_loaded = pyqtSignal(str, list)         # (channel_id, list[ChannelVersion]) — versions worker → main thread
    _similar_titles_loaded = pyqtSignal(str, list)   # (channel_id, list[ChannelVersion]) — similar titles worker → main thread
    _action_state_loaded = pyqtSignal(object)        # ChannelActionState — action state worker → main thread
    # Episode preflight results — emitted from done callback, connected to main-thread slots.
    # QTimer.singleShot from a non-main thread is unreliable; signals are always safe.
    _episode_ready  = pyqtSignal(str, str, str, object)  # notif_id, url, title, queue_episodes
    _episode_failed = pyqtSignal(str, str, str, str)     # notif_id, title, detail, stream_url
    # Context menu async fetch: (ChannelMenuContext, gx, gy)
    _ctx_data_ready = pyqtSignal(object, int, int)
    # Stream validation result: emitted from background thread after validate_and_failover
    _stream_ready = pyqtSignal(object)  # dict with final_url, stream_err, channel state
    # Generic async-read seam (_AsyncMixin): worker emits this; _on_query_result dispatches
    _query_result = pyqtSignal(object)
    # Playback-health probe result: worker (executor) emits the mpv props dict (or None);
    # _on_playback_health_ready updates the nav-bar label on the main thread.
    _playback_health_ready = pyqtSignal(object)
    # Queue-end detected from off-thread: list of episode ids that were auto-advanced
    # (last_played_via='queue'). Emitted only when >0 episodes were queue-watched so
    # the main thread can show the "Still here?" confirmation prompt.
    _queue_end_detected = pyqtSignal(object)  # list[str] — auto-advanced episode ids
    
    def __init__(self, config: Config, config_recovered: bool = False):
        super().__init__()
        self.config = config
        self.notification_manager = NotificationManager(
            max_visible=config.max_stacked_notifications
        )

        # Show notification if config was recovered from backup
        if config_recovered:
            self.notification_manager.show(
                "Config was empty/corrupt, restored from backup",
                duration_ms=5000
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
        # all_channels is kept as a parallel list for legacy callers (filter_channels,
        # favorites toggle in all_channels cache).  With the virtualized model it is
        # no longer the primary data source; channel_model is.
        self.all_channels = []  # List of (display_text, ChannelListDTO)
        # Page size for the virtualized model's initial SQL fetch and incremental pages.
        # Chosen to be small enough to land quickly and large enough that the user
        # rarely triggers a second page for average-sized categories.
        self._search_page_size = 1_000   # First page / subsequent pages

        # When True, Tier 1 filters (language/quality/platform) are bypassed for one
        # load — so the user can see what exists in filtered categories without having
        # to open the filter bar and change settings. Cleared on next filter change.
        self._bypass_tier1_filters: bool = False
        self._currently_bypassing: bool = False  # set after load completes, read by filter_channels

        # Details-pane context filters — set when user clicks a genre or person chip.
        # At most one is active at a time; both are cleared by the chip's dismiss button.
        self._details_genre_filter: str | None = None
        self._details_person_filter: str | None = None

        # Debounce timer for search input → avoids a DB query per keystroke
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(200)
        self._search_debounce.timeout.connect(self.load_channels)
        
        # Filter state
        self.current_filter_state = None
        
        # Cleanup registry — callables called in closeEvent; register new managers here
        # so additions can't be silently forgotten (see CLAUDE.md "closeEvent cleanup").
        self._cleanables: list[tuple[str, callable]] = []

        # Player management
        self.player_manager = PlayerManager(config)
        self._register_cleanable("player_manager", self.player_manager.cleanup)
        self.loading_channels = set()  # Track channels being loaded

        # Playback-health readout state: None = follow the most-recently-used window;
        # set to a provider_id key to pin the readout to a specific open player window.
        self._health_view_key: str | None = None
        # provider_id → source glyph, warmed at play time so the readout can label
        # which stream its data refers to without per-tick DB reads.
        self._provider_icons: dict[str, str] = {}
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
        self._register_cleanable("image_cache", self.image_cache.shutdown)

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
        self._register_cleanable("stream_retry_manager", self.stream_retry_manager.stop)

        # Series monitor — checks monitored series for new episodes after each provider refresh
        # and on startup.  Constructed before setup_ui() so the sidebar section can connect.
        self.series_monitor = SeriesMonitorManager(
            self.db, self.config,
            notifications=None,  # injected after NotificationManager is set up
            parent=self,
        )
        self._register_cleanable("series_monitor", self.series_monitor.shutdown)

        # Migration manager — runs one-time background migrations sequentially.
        # Registered for clean cancellation on closeEvent before the pool drains.
        self.migration_manager = MigrationManager(self.config, self.db, parent=self)
        from metatv.core.migrations.prefix_rescan import PrefixRescanTask
        self.migration_manager.register(PrefixRescanTask(self.db))
        from metatv.core.migrations.metadata_rescan import MetadataRescanTask
        self.migration_manager.register(MetadataRescanTask(self.db, self.metadata_manager))
        self._register_cleanable("migration_manager", self.migration_manager.shutdown)

        self.setup_ui()
        self.setup_notifications()

        # Initialize before load_channels() which uses these
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._register_cleanable("executor", lambda: self.executor.shutdown(wait=False))
        self._load_channels_token: list[int] = [0]
        self._epg_count_token: list[int] = [0]
        self._filter_stats_token: list[int] = [0]
        self._hidden_mode: bool = False
        self._last_shown_channel_id: str | None = None
        self.metadata_loaded.connect(self._update_details_with_metadata)
        self._category_assigned.connect(self.load_channels)
        self._episode_ready.connect(self._do_launch_episode)
        self._episode_failed.connect(self._on_episode_stream_unavailable)
        self._ctx_data_ready.connect(self._on_ctx_data_ready)
        self._stream_ready.connect(self._on_stream_ready)
        self._query_result.connect(self._on_query_result)
        self._playback_health_ready.connect(self._on_playback_health_ready)
        self._queue_end_detected.connect(self._on_queue_end_detected)

        self.stream_retry_manager.stream_online.connect(self._on_stream_back_online)
        self.stream_retry_manager.retry_list_changed.connect(self._refresh_alerts_retry_section)
        self.stream_retry_manager.start()
        self._refresh_alerts_retry_section()  # restore persisted entries on startup

        self.load_providers()
        self.load_favorites()
        self.load_history()
        self._refresh_queue_section()
        self._refresh_recommended_section()

        # Auto-load channels from all active providers on startup.
        # restore_search_state() handles the load if a saved state exists; otherwise fall back.
        if not self.restore_search_state():
            self.load_channels()

        # Initialize filter statistics
        self.initialize_filter_stats()

        # Test provider connections in background
        self.test_all_providers()

        # MigrationManager: run any pending one-time background migrations.
        # Deferred 1 s so channels load and the UI paints before the worker starts.
        QTimer.singleShot(1000, self.migration_manager.run_pending)

        # Show What's New dialog after the window paints (deferred, idempotent)
        self._whats_new_checked: bool = False
        QTimer.singleShot(0, self.maybe_show_whats_new)

        # Series monitor startup check — runs after channels are loaded (deferred 0ms
        # yields to the event loop so channel load and UI paint happen first).
        QTimer.singleShot(0, self.series_monitor.check_all)

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
        self.details_pane.monitor_toggled.connect(self._on_details_monitor_toggled)
        self.details_pane.unhide_requested.connect(self._unhide_channel)
        self.details_pane.channel_versions_requested.connect(self._fetch_channel_versions)
        self.details_pane.version_selected.connect(self.show_channel_details_by_id)
        self.details_pane.prefix_block_requested.connect(self._on_prefix_block)
        self.details_pane.prefix_unblock_requested.connect(self._on_prefix_unblock)
        self.details_pane.prefix_name_saved.connect(self._on_prefix_name_saved)
        self.details_pane.manage_filters_requested.connect(self.manage_filters)
        self.details_pane.genre_filter_requested.connect(self._on_genre_filter_requested)
        self.details_pane.person_filter_requested.connect(self._on_person_filter_requested)
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

        # Poster lightbox — full-res image overlay, hidden by default
        from metatv.gui.poster_lightbox import PosterLightbox
        self._poster_lightbox = PosterLightbox(self)
        self.details_pane.poster_enlarged.connect(self._poster_lightbox.show_pixmap)

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
        whats_new_action = QAction(f"{_icons.whats_new_icon}  What's New", self)
        whats_new_action.setToolTip("See what changed in recent updates")
        whats_new_action.triggered.connect(self.show_whats_new)
        help_menu.addAction(whats_new_action)
        help_menu.addSeparator()
        help_menu.addAction("&About", self.show_about)
    
    def create_sidebar(self) -> QWidget:
        """Create modular sidebar with resizable sections"""
        self.sidebar_splitter = QSplitter(Qt.Orientation.Vertical)
        self.sidebar_sections = {}

        # Determine full ordered list: saved order first, then any new sections not yet in it
        _known = ["new_episodes", "alerts", "recommended", "queue", "favorites", "history", "sources"]
        ordered = list(self.config.sidebar_sections or _known)
        for sid in _known:
            if sid not in ordered:
                ordered.append(sid)

        visible_ids = set(self.config.sidebar_visible_sections or ordered)

        # Create ALL sections (visible and hidden) so live reordering works
        for section_id in ordered:
            section = self.create_section(section_id)
            if section:
                self.sidebar_sections[section_id] = section
                self.sidebar_splitter.addWidget(section)
                section.setVisible(section_id in visible_ids)
                section.restore_state()

        # Register executor shutdown for every section that owns a thread pool
        for sid, section in self.sidebar_sections.items():
            if hasattr(section, "_executor"):
                self._register_cleanable(
                    f"sidebar_{sid}_executor",
                    lambda ex=section._executor: ex.shutdown(wait=False),
                )

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
        outer_layout.addWidget(self.sidebar_splitter, 1)  # stretch=1: bounded to outer height

        settings_btn = QPushButton(f"{self.config.settings_icon} Settings")
        settings_btn.setFlat(True)
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip("Open application settings (Ctrl+,)")
        settings_btn.setStyleSheet(_theme.FLAT_NAV_BTN)
        settings_btn.clicked.connect(self.open_settings)
        outer_layout.addWidget(settings_btn)

        return outer
    
    def create_section(self, section_id: str):
        """Create a sidebar section by ID"""
        if section_id == "new_episodes":
            section = NewEpisodesSection(self.config, self)
            section.seriesClicked.connect(self.show_channel_details_by_id)
            section.markSeenClicked.connect(self._on_mark_series_seen)
            section.manageRequested.connect(self._open_monitored_dialog)
            self.series_monitor.new_episodes_found.connect(
                lambda _cid, _n: section.refresh()
            )
            return section

        elif section_id == "sources":
            section = SourcesSection(self.config, self.db, self)
            section.providerSelected.connect(self.on_provider_selected_new)
            section.providerRefreshClicked.connect(self.refresh_provider)
            section.providerEditClicked.connect(self.enter_provider_edit_mode)
            section.providerAnalyzeClicked.connect(self.enter_provider_analytics_mode)
            section.providerToggleClicked.connect(self.toggle_provider_active)
            section.providerEpgRefreshClicked.connect(self._on_provider_epg_refresh)
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
            section.searchRequested.connect(self.search_for_title)
            section.clearUnavailableClicked.connect(
                lambda: self._clear_unavailable_favorites(section)
            )
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
            section.searchRequested.connect(self.search_for_title)
            section.clearUnavailableClicked.connect(
                lambda: self._clear_unavailable_queue(section)
            )
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

    # ------------------------------------------------------------------
    # Series monitor helpers
    # ------------------------------------------------------------------

    def _refresh_new_episodes_section(self) -> None:
        """Refresh the New Episodes sidebar section."""
        section = self.sidebar_sections.get("new_episodes")
        if section:
            section.refresh()

    def _open_monitored_dialog(self) -> None:
        """Open the 'Episode Alerts' management dialog (see-all + stop alerts)."""
        from metatv.gui.monitored_series_dialog import MonitoredSeriesDialog
        dlg = MonitoredSeriesDialog(self.config, self)
        dlg.changed.connect(self._refresh_new_episodes_section)
        dlg.exec()

    def _monitor_series(self, channel_id: str) -> None:
        """Start a new-episode alert for a series.

        Reads the channel from the DB to populate the config entry, then
        tells SeriesMonitorManager to compute and store the baseline episode count.
        """
        with self.db.session_scope(commit=False) as session:
            from metatv.core.repositories import RepositoryFactory
            repos = RepositoryFactory(session)
            channel = repos.channels.get_by_id(channel_id)
            if not channel:
                logger.warning(f"_monitor_series: channel {channel_id} not found")
                return
            entry = {
                "series_channel_id": channel_id,
                "source_id": channel.source_id or "",
                "provider_id": channel.provider_id or "",
                "title": channel.name or "",
                "baseline_episode_count": None,  # None = not yet established (set by set_baseline)
                "unseen_new": 0,
                "last_checked": None,
            }

        self.config.add_monitored_series(entry)
        self.series_monitor.set_baseline(channel_id)
        self._refresh_new_episodes_section()

    def _unmonitor_series(self, channel_id: str) -> None:
        """Stop the new-episode alert for a series."""
        self.config.remove_monitored_series(channel_id)
        self._refresh_new_episodes_section()

    def _on_details_monitor_toggled(self, channel_id: str) -> None:
        """Toggle the new-episode alert from the details-pane Alert button."""
        if self.config.is_series_monitored(channel_id):
            self._unmonitor_series(channel_id)
        else:
            self._monitor_series(channel_id)

    def _on_mark_series_seen(self, channel_id: str) -> None:
        """Clear unseen count for the given series (main thread)."""
        self.config.clear_unseen(channel_id)
        self._refresh_new_episodes_section()

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

    def _create_bottom_nav_bar(self) -> QWidget:
        """Build the full-width bottom tab bar with nav chips and Exclusions control."""
        bar = QWidget()
        bar.setObjectName("bottomNavBar")
        bar.setStyleSheet(
            f"#bottomNavBar {{ background: {_theme.COLOR_BG_BAR}; border-top: 1px solid {_theme.COLOR_LINE}; }}"
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

        # Diagnose action — far-left, mirrors the Exclusions chip on the right
        self._diagnose_btn = QPushButton(_icons.diagnose_icon)
        self._diagnose_btn.setFlat(True)
        self._diagnose_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._diagnose_btn.setToolTip(
            "Diagnose stream quality of the selected channel — "
            "is buffering your provider or your connection?"
        )
        self._diagnose_btn.setStyleSheet(_theme.FLAT_NAV_BTN)
        self._diagnose_btn.clicked.connect(self.on_diagnose_clicked)
        layout.addWidget(self._diagnose_btn)

        # Split-streams toggle — one player window per source when ON.
        self._split_toggle_btn = QPushButton(f"{_icons.split_icon} Split")
        self._split_toggle_btn.setCheckable(True)
        self._split_toggle_btn.setChecked(
            getattr(self.config, "split_streams_by_source", False)
        )
        self._split_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._split_toggle_btn.setStyleSheet(_theme.NAV_TOGGLE_BTN)
        self._split_toggle_btn.setToolTip(
            "Split streams — keep one player window per source.\n"
            "Off: each play replaces the shared window.\n"
            "On: a different source opens in its own window."
        )
        self._split_toggle_btn.toggled.connect(self.on_split_toggle_clicked)
        layout.addWidget(self._split_toggle_btn)

        # Live playback-health readout — only visible while mpv is actively playing.
        self._playback_health_label = _ClickableNavLabel("")
        self._playback_health_label.setToolTip(
            "Live playback health (buffer · download speed · dropped frames)"
        )
        self._playback_health_label.setStyleSheet(_theme.NAV_HEALTH)
        self._playback_health_label.hide()
        self._playback_health_label.clicked.connect(self._on_health_readout_clicked)
        layout.addWidget(self._playback_health_label)

        layout.addStretch(1)
        layout.addWidget(nav_group)
        layout.addStretch(1)

        self._filter_chip = FilterChip("Exclusions")
        self._filter_chip.toggled_changed.connect(self._on_filter_toggle)
        self._filter_chip.open_dialog_requested.connect(self._open_global_filter_dialog)
        layout.addWidget(self._filter_chip)

        QTimer.singleShot(0, self._update_filter_btn_state)
        return bar

    def on_diagnose_clicked(self) -> None:
        """Diagnose the currently-selected channel's stream (nav-bar action)."""
        channel = getattr(self.details_pane, "current_channel", None)
        if channel is None:
            self.notification_manager.show(
                title="No channel selected",
                message="Select a channel to diagnose its stream.",
                type="info",
                dismissible=True,
                auto_dismiss_seconds=5,
            )
            return
        self.diagnose_channel_by_id(channel.id)

    def on_split_toggle_clicked(self, checked: bool) -> None:
        """Toggle the split-streams feature from the nav-bar button.

        Persists the new state to config and shows a brief status-bar message.
        """
        self.config.split_streams_by_source = checked
        self.config.save()
        msg = (
            "Split streams: on — one window per source"
            if checked
            else "Split streams: off — shared window"
        )
        self.status_bar.showMessage(msg, 4000)

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
            f"QPushButton {{ font-size: {_theme.FONT_MD}; padding: 3px 10px;"
            f" border: 1px solid {_theme.COLOR_BORDER}; background: {_theme.COLOR_LINE_DARK}; color: {_theme.COLOR_DISABLED}; }}"
            f"QPushButton:checked {{ background: {_theme.COLOR_BORDER}; color: {_theme.COLOR_TEXT_HI}; font-weight: bold; }}"
            f"QPushButton:hover:!checked {{ background: {_theme.COLOR_LINE}; }}"
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

        # Context filter chip — hidden until a details-pane genre/person filter is active
        self._context_filter_chip = QWidget()
        self._context_filter_chip.hide()
        self._context_filter_chip.setStyleSheet(_theme.CONTEXT_FILTER_CHIP)
        _cfc_layout = QHBoxLayout(self._context_filter_chip)
        _cfc_layout.setContentsMargins(6, 2, 6, 2)
        _cfc_layout.setSpacing(4)
        self._context_filter_label = QLabel()
        self._context_filter_label.setStyleSheet(_theme.CONTEXT_FILTER_CHIP_LABEL)
        _cfc_layout.addWidget(self._context_filter_label)
        _cfc_dismiss = QPushButton("✕")
        _cfc_dismiss.setFixedSize(16, 16)
        _cfc_dismiss.setFlat(True)
        _cfc_dismiss.setToolTip("Clear filter")
        _cfc_dismiss.setStyleSheet(_theme.CONTEXT_FILTER_CHIP_BTN)
        _cfc_dismiss.clicked.connect(self._clear_context_filter)
        _cfc_layout.addWidget(_cfc_dismiss)
        controls_layout.addWidget(self._context_filter_chip)

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
        _hb_lbl.setStyleSheet(f"color: {_theme.COLOR_ACCENT_BROWN}; font-size: {_theme.FONT_MD};")
        _hb_layout.addWidget(_hb_lbl)
        _hb_layout.addStretch()
        self._manage_cats_btn = QPushButton("📁 Manage Categories")
        self._manage_cats_btn.setFlat(True)
        self._manage_cats_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manage_cats_btn.setStyleSheet(
            f"QPushButton {{ font-size: {_theme.FONT_MD}; color: {_theme.COLOR_ACCENT_BLUE}; padding: 2px 8px;"
            f" border: 1px solid {_theme.OVERLAY_BLUE_25}; border-radius: 4px; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_BLUE_2}; border-color: {_theme.OVERLAY_BLUE_LT_25}; }}"
        )
        self._manage_cats_btn.setToolTip("Browse and manage your user-defined categories")
        self._manage_cats_btn.clicked.connect(self._open_categories_dialog)
        _hb_layout.addWidget(self._manage_cats_btn)
        self._hidden_banner.setStyleSheet(
            f"background: {_theme.OVERLAY_BROWN_08}; border-radius: 4px;"
        )
        self._hidden_banner.hide()
        self._list_layout.addWidget(self._hidden_banner)

        # Banner strip — shown above the channel list for transient states:
        # loading placeholder, "N filtered" actionable button, bypass banner.
        # Hidden by default; _ChannelListMixin shows/hides it as needed.
        self._channel_banner = QLabel()
        self._channel_banner.setVisible(False)
        self._channel_banner.setWordWrap(True)
        self._channel_banner.setStyleSheet(
            f"QLabel {{ color: {_theme.COLOR_MUTED}; padding: 4px 8px;"
            f" font-size: {_theme.FONT_MD}; }}"
        )
        self._list_layout.addWidget(self._channel_banner)

        # Banner strip for the "N filtered — click to show" actionable button.
        # A QPushButton rather than a label so it is keyboard-focusable and
        # respects the theme's pointer cursor.  Hidden by default.
        self._channel_filter_btn = QPushButton()
        self._channel_filter_btn.setVisible(False)
        self._channel_filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._channel_filter_btn.setStyleSheet(
            f"QPushButton {{ background: {_theme.COLOR_BANNER_YEL_BG}; color: {_theme.COLOR_BANNER_YEL_FG};"
            f" border: 1px solid {_theme.COLOR_BANNER_YEL_BORDER}; border-radius: 4px;"
            f" padding: 8px 16px; font-size: {_theme.FONT_LG}; }}"
            f"QPushButton:hover {{ background: {_theme.COLOR_BANNER_YEL_BG_HOVER};"
            f" border-color: {_theme.COLOR_BANNER_YEL_BORDER_HOVER}; }}"
        )
        self._channel_filter_btn.setToolTip(
            "Your current Category / Quality / Platform filters are hiding these results.\n"
            "Click to temporarily show them. Filters are not changed.\n"
            "Changing filters or searching again restores normal filtered view."
        )
        self._channel_filter_btn.clicked.connect(self._show_filtered_results)
        self._list_layout.addWidget(self._channel_filter_btn)

        # Virtualized channel list — QListView backed by ChannelListModel
        from metatv.gui.channel_list_model import ChannelListModel
        from PyQt6.QtWidgets import QAbstractItemView
        self.channel_model = ChannelListModel(self)
        # Wire page requests from the model through the async seam.
        # The lambda captures self (MainWindow) so it can call _run_query.
        self.channel_model.page_requested.connect(self._on_channel_page_requested)
        self.channels_list = QListView()
        self.channels_list.setModel(self.channel_model)
        self.channels_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.channels_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channels_list.customContextMenuRequested.connect(self.show_channel_context_menu)
        self.channels_list.doubleClicked.connect(self._on_channel_double_clicked)
        self.channels_list.selectionModel().currentChanged.connect(
            self.on_channel_selection_changed
        )
        self._list_layout.addWidget(self.channels_list)

        # Series tree view (hidden by default)
        self.series_tree = QTreeWidget()
        self.series_tree.setHeaderLabels(["Title", "Episode", "Runtime", "Rating"])
        self.series_tree.setColumnWidth(0, 400)
        self.series_tree.setColumnWidth(1, 80)
        self.series_tree.setColumnWidth(2, 80)
        self.series_tree.setColumnWidth(3, 80)
        self.series_tree.setExpandsOnDoubleClick(False)
        # ExtendedSelection enables Shift+click / Ctrl+click multi-select for batch
        # Mark-as-Watched operations (context menu acts on all selected episodes).
        self.series_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.series_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.series_tree.customContextMenuRequested.connect(self.show_series_context_menu)
        self.series_tree.itemDoubleClicked.connect(self.play_series_item)
        self.series_tree.setVisible(False)
        self._list_layout.addWidget(self.series_tree)

        # EPG manager + view (hidden by default)
        self.epg_manager = EpgManager(self.db, self.config, self.notification_manager, parent=self)
        self._register_cleanable("epg_manager", self.epg_manager.shutdown)

        # Inject the now-constructed notification_manager into series_monitor
        # (constructed earlier in __init__ before setup_ui, before notifications existed)
        self.series_monitor.notifications = self.notification_manager
        # Provider IDs that should get a one-time EPG fetch once their channel load
        # completes — populated by AddProviderDialog when "Enable EPG" is checked.
        self._epg_fetch_after_add: set[str] = set()
        self.epg_view = EpgView(self.config, self.db, self.epg_manager, self)
        # EPG "play this channel" routes through the one rich play chokepoint
        # (play_media) — same as the channel list — so it gets URL failover, the
        # buffering notification, live list refreshes, and the playback-health
        # readout. There is nothing special about a "special event" stream; the
        # old play_special_event was a stripped-down duplicate that silently
        # dropped all of the above (most visibly the live stats readout).
        self.epg_view.play_channel_requested.connect(self.play_media)
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
        # Recolor the sidebar EPG indicator (and clear its spinner) when a fetch ends.
        self.epg_manager.refresh_finished.connect(self._on_provider_epg_refreshed)
        self.epg_manager.refresh_error.connect(self._on_provider_epg_refreshed)
        self._refresh_watch_alerts()

        # Provider editor (hidden by default)
        self.provider_editor = ProviderEditorView(self.db, self.config, self.epg_manager, self)
        self.provider_editor.done.connect(self.exit_provider_edit_mode)
        self.provider_editor.provider_saved.connect(self._on_provider_saved)
        self.provider_editor.provider_deleted.connect(self._on_provider_deleted)
        self.provider_editor.refresh_requested.connect(self.refresh_provider)
        self.provider_editor.account_info_updated.connect(self._on_account_info_updated)
        self.provider_editor.setVisible(False)
        self._list_layout.addWidget(self.provider_editor)

        # Source analytics view (hidden by default)
        self.source_analytics = SourceAnalyticsView(self)
        self.source_analytics.done.connect(self.exit_provider_analytics_mode)
        self.source_analytics.setVisible(False)
        self._list_layout.addWidget(self.source_analytics)

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
        self.stats_label.setStyleSheet(f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_LG};")
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

        # Migration progress overlay — same overlay lane as notifications.
        # Connect MigrationManager's public signals (already on main thread).
        self.migration_progress_widget = MigrationProgressWidget(self.centralWidget())
        self.migration_manager.task_started.connect(
            self.migration_progress_widget.on_task_started
        )
        self.migration_manager.task_progress.connect(
            self.migration_progress_widget.on_task_progress
        )
        self.migration_manager.task_finished.connect(
            self.migration_progress_widget.on_task_finished
        )
        self.migration_manager.all_finished.connect(
            self.migration_progress_widget.on_all_finished
        )
        # When migrations finish, reload the channel list (same as old _on_prefix_rescan_done)
        self.migration_manager.all_finished.connect(self.load_channels)

        # Listen for notification changes
        self.notification_manager.add_listener(self.update_notifications)

        # Test notification (remove later)
        # self.show_test_notification()
    
    def update_notifications(self, notifications):
        """Update notification widget"""
        self.notification_widget.update_notifications(notifications)
    
    def resizeEvent(self, event):
        """Handle window resize to reposition notifications and lightbox."""
        super().resizeEvent(event)
        if hasattr(self, 'notification_widget'):
            self.notification_widget.reposition()
        if hasattr(self, 'migration_progress_widget') and self.migration_progress_widget.isVisible():
            self.migration_progress_widget.reposition()
        if hasattr(self, '_lightbox') and self._lightbox.isVisible():
            self._lightbox.resize(self.size())
        if hasattr(self, '_poster_lightbox') and self._poster_lightbox.isVisible():
            self._poster_lightbox.resize(self.size())

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
    def refresh_channels(self):
        """Refresh channel list"""
        self.status_bar.showMessage("Refreshing channels...")
        logger.info("Refreshing channels")
        self.load_providers()

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
        dialog.settings_applied.connect(self._apply_sidebar_visibility)
        dialog.exec()
        self._apply_sidebar_visibility()
        # Re-sync the nav-bar Split toggle in case the user changed the setting
        # via the Settings dialog's Playback tab checkbox.
        if hasattr(self, "_split_toggle_btn"):
            self._split_toggle_btn.blockSignals(True)
            self._split_toggle_btn.setChecked(
                getattr(self.config, "split_streams_by_source", False)
            )
            self._split_toggle_btn.blockSignals(False)

    def _apply_sidebar_visibility(self) -> None:
        """Reorder and show/hide sidebar sections immediately from config."""
        ordered_ids = list(self.config.sidebar_sections or self.sidebar_sections.keys())
        visible_ids = set(self.config.sidebar_visible_sections or ordered_ids)

        # Reorder: insertWidget moves an already-present widget to position i
        for i, sid in enumerate(ordered_ids):
            section = self.sidebar_sections.get(sid)
            if section is not None:
                self.sidebar_splitter.insertWidget(i, section)

        # Apply visibility
        for sid, section in self.sidebar_sections.items():
            section.setVisible(sid in visible_ids)
    
    def show_about(self):
        """Show about dialog"""
        logger.info("Show about")

    # ------------------------------------------------------------------
    # What's New
    # ------------------------------------------------------------------

    def _whats_new_unseen(self) -> list:
        """Return changelog entries newer than the user's last-seen cursor.

        Extracted for testability — callers can assert the decision without
        constructing or exec-ing the modal dialog.
        """
        return _whats_new.entries_since(self.config.last_seen_whats_new_id)

    def show_whats_new(self) -> None:
        """Open the What's New dialog with the full changelog (on-demand viewer).

        Also advances the seen cursor to the latest entry and saves config,
        so the auto-show guard treats it as seen.
        """
        entries = sorted(_whats_new.WHATS_NEW, key=lambda e: e.id, reverse=True)
        dlg = WhatsNewDialog(entries, self)
        dlg.exec()
        self.config.last_seen_whats_new_id = _whats_new.latest_id()
        self.config.save()

    def maybe_show_whats_new(self) -> None:
        """Show the What's New dialog once if there are unseen entries.

        Idempotent: guarded by ``_whats_new_checked`` so it cannot fire twice
        even if called from multiple code paths.  After showing, advances the
        cursor and saves config so it will not appear again until new entries
        are added.
        """
        if self._whats_new_checked:
            return
        self._whats_new_checked = True

        unseen = self._whats_new_unseen()
        if not unseen:
            return

        dlg = WhatsNewDialog(unseen, self)
        dlg.exec()
        self.config.last_seen_whats_new_id = _whats_new.latest_id()
        self.config.save()
    
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
    
    def _register_cleanable(self, name: str, fn: callable) -> None:
        """Register a cleanup callable for closeEvent. Call this after creating each manager."""
        self._cleanables.append((name, fn))

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

        # Shut down all registered managers (registered in __init__ / setup_ui via
        # _register_cleanable — new managers must be registered there, not added here).
        for _name, _fn in getattr(self, "_cleanables", []):
            try:
                _fn()
            except Exception as e:
                logger.warning(f"Cleanup of {_name} failed: {e}")

        # Stop background work owned by the active content view (its on_deactivate
        # quits loader threads); _hide_all_content_views only runs on view switches,
        # not on app close, so do it explicitly here.
        for _attr in ("discover_view", "preferences_view", "epg_view"):
            _view = getattr(self, _attr, None)
            if _view is not None and _view.isVisible():
                _view.on_deactivate()
        # PreferencesView owns a long-lived executor that on_deactivate does not stop.
        _prefs = getattr(self, "preferences_view", None)
        if _prefs is not None and hasattr(_prefs, "_executor"):
            _prefs._executor.shutdown(wait=False)

        # Close database
        self.db.close()
        event.accept()
