"""Configuration management"""

from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field
from loguru import logger


class Config(BaseModel):
    """Application configuration"""
    
    # Paths
    config_dir: Path = Field(default_factory=lambda: Path.home() / ".config" / "metatv")
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".local" / "share" / "metatv")
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "metatv")
    
    # Database
    database_url: str = Field(default="")
    
    # UI Settings
    notification_position: str = "bottom-right"
    max_stacked_notifications: int = 3
    
    # UI Icons/Indicators
    favorite_icon: str = "★"  # Filled star - is favorited
    unfavorite_icon: str = "☆"  # Outline star - not favorited
    live_icon: str = "📡"  # Live broadcast indicator
    movie_icon: str = "🎬"  # Movie indicator
    series_icon: str = "📺"  # TV series indicator
    season_icon: str = "📁"  # Season folder indicator
    episode_icon: str = "▶"  # Episode indicator
    unknown_icon: str = "❓"  # Unknown media type
    
    # UI Control Icons
    expand_icon: str = ">"  # Collapsed state (accordion/tree)
    collapse_icon: str = "⌄"  # Expanded state (accordion/tree)
    play_icon: str = "▶"  # Play button/indicator
    loading_icon: str = "⟳"  # Loading/buffering indicator
    close_icon: str = "×"  # Close/dismiss button
    delete_icon: str = "🗑"  # Delete/clear button
    refresh_icon: str = "⟳"  # Refresh button
    settings_icon: str = "⚙"  # Settings button
    search_icon: str = "🔍"  # Search indicator
    filter_icon: str = "⚡"  # Filter/preset indicator
    history_icon: str = "🕒"            # History indicator
    provider_icon: str = "📡"          # Provider / source section
    watch_alerts_icon: str = "⚠"      # Alerts section
    stream_retry_pending_icon: str = "🔴"  # Stream retry — awaiting re-check
    stream_retry_online_icon:  str = "🟢"  # Stream retry — back online
    info_icon: str = "ℹ"
    watchlist_icon: str = "⏰"         # Watchlist tab
    live_indicator_icon: str = "🔴"    # On Now / live indicator
    calendar_icon: str = "📅"          # Browse / calendar tab
    discover_icon: str = "✨"          # Discover tab
    move_up_icon: str = "▲"            # Move item up in list
    move_down_icon: str = "▼"          # Move item down in list
    visibility_toggle_icon: str = "👁" # Show/hide password toggle
    watched_icon: str = "✓"            # Watched / completed indicator
    rating_star_icon: str = "★"        # Star used in content rating display
    like_icon: str = "👍"              # Like / positive rating
    dislike_icon: str = "👎"           # Dislike / negative rating
    not_interested_icon: str = "🙅"    # Not Interested — suppress from recommendations only
    hide_icon: str = "🚫"              # Hide channel from all views
    preferences_icon: str = "🎯"       # Preferences / Recommended dashboard
    preferred_version_icon: str = "🎯" # Best-match version indicator (distinct semantic from favorites ★)
    queue_icon: str = "📋"             # Watch Queue section / action
    pin_icon: str = "📌"               # Pin shelf to top in Discover
    manage_icon: str = "⚙"            # Manage / settings button

    # Global content category filter (applies to discovery + recommendations)
    # Category group names from filter_language_groups (e.g. ["English", "French"])
    # Empty list = no filter (all categories shown)
    global_filter_included_categories: list = Field(default_factory=list)
    global_filter_include_uncategorized: bool = True  # show content with no detected_prefix
    global_filter_icon: str = "fa5s.filter"  # qtawesome key — resolved via icon_utils.resolve_icon()
    # Explicit prefix blocklist — always hidden everywhere, regardless of the allowlist above.
    # Written by the "Block [PREFIX]" quick action in the Other Versions panel.
    global_filter_excluded_prefixes: list = Field(default_factory=list)

    # Prefix detection settings
    # Separators tried in order when extracting the prefix code from a channel name.
    # Longer/more-specific patterns should come first (e.g. " ★ " before "★").
    prefix_separators: list = Field(
        default_factory=lambda: [" ★ ", "★", " | ", "| ", "|", ": ", ":", " - "]
    )
    prefix_bracket_enabled: bool = True  # extract [XX] bracket format
    # Bump CURRENT_DETECTOR_VERSION in main_window.py to trigger a one-time auto-rescan
    # for all users the next time they launch the app.
    prefix_detector_version: int = 0
    # Whether to show content whose prefix code didn't match any named language group.
    # True = include "Other" content; False = hide it. Controlled by the filter dialog.
    global_filter_include_other_prefixes: bool = True

    # Discover view zone persistence
    # shelf keys: "recently_added", "top_movies", "top_series", "genre:Drama", "decade:1990", etc.
    discover_pinned_shelves: list = Field(default_factory=list)
    discover_expanded_shelves: list = Field(default_factory=list)
    discover_collapsed_shelves: list = Field(default_factory=list)
    discover_hidden_shelves: list = Field(default_factory=list)
    discover_shelf_order: list = Field(default_factory=list)  # manual order within expanded zone
    discover_more_expanded: bool = False  # "More Categories" accordion — collapsed by default

    # Recommended view state
    preferences_attributes_expanded: bool = False  # collapsed by default
    muted_attributes: dict = Field(default_factory=lambda: {
        "genres": [], "directors": [], "actors": [], "keywords": []
    })
    rec_dedupe_overrides: list = Field(default_factory=list)
    # channel_ids that bypass title-based dedup ("not the same show" user override)
    
    # Notification Icons
    notification_progress_icon: str = "⟳"  # Progress notification
    notification_success_icon: str = "✓"  # Success notification
    notification_error_icon: str = "✗"  # Error notification
    notification_warning_icon: str = "⚠"  # Warning notification
    notification_info_icon: str = ""   # Info notification (no icon by default)
    
    # Theme & Appearance (for future theming system)
    theme: str = "auto"  # "light", "dark", "auto" (follows system)
    accent_color: str = "#4488ff"  # Primary accent color
    use_system_colors: bool = True  # Follow system color scheme
    font_family: str = ""  # Empty = system default
    font_size: int = 0  # 0 = system default
    
    # Sidebar Configuration
    sidebar_sections: list = Field(default_factory=lambda: ["alerts", "queue", "recommended", "favorites", "history", "sources"])
    sidebar_visible_sections: list = Field(default_factory=lambda: ["alerts", "queue", "recommended", "favorites", "history", "sources"])
    sidebar_section_states: dict = Field(default_factory=dict)  # Collapsed state and heights per section
    sidebar_width: int = 340  # Width of sidebar in pixels
    window_geometry: str = ""  # Base64-encoded QByteArray from saveGeometry()
    sidebar_section_sizes: list = Field(default_factory=list)  # Heights of sidebar sections in pixels
    
    # Performance
    chunk_size: int = 1000  # Channels to process at once
    concurrent_requests: int = 5
    
    # External players
    preferred_player: str = "mpv"
    player_mode: str = "single-instance"  # "single-instance" or "multiple-instances"
    close_player_when_finished: bool = True  # Close player when stream finishes (mpv --keep-open=no)
    max_player_instances: int = 1  # Max player instances (0 = use provider's max_connections, -1 = unlimited)
    player_args: dict = Field(default_factory=dict)
    
    # MPV-specific settings
    mpv_socket_path: str = "/tmp/mpv-metatv-socket"
    mpv_extra_args: list = Field(default_factory=list)  # Additional args like ["--cache=yes", "--demuxer-max-bytes=50M"]
    
    # VLC-specific settings
    vlc_extra_args: list = Field(default_factory=list)  # Additional args like ["--network-caching=3000"]
    
    # Playback settings
    default_cache_size: str = "auto"  # "auto" or size like "50M", "100M"
    network_timeout: int = 30  # seconds
    reconnect_attempts: int = 3
    autoplay_season_episodes: bool = True  # Auto-queue subsequent episodes when playing from season
    
    # Filtering settings
    filters_enabled: bool = True
    filter_section_visible: bool = True  # Whether filter section is expanded/collapsed
    filter_default_mode: str = "include_all"  # "include_all" or "exclude_all"
    filter_media_types: list = Field(default_factory=lambda: ["live", "movies", "series"])  # Which media types to show
    filter_enabled_media_types: list = Field(default_factory=lambda: ["live", "movie", "series"])  # User's current selection
    filter_language_groups: dict = Field(default_factory=lambda: {
        "English": ["EN", "UK", "US", "AU", "CA", "NZ", "IE"],
        "Arabic": ["AR", "AE", "SA", "EG", "MA", "TN", "DZ", "LB", "JO", "IQ", "KW", "QA", "BH", "OM", "YE", "PS"],
        "Spanish": ["ES", "MX", "AR", "CO", "CL", "PE", "VE", "EC", "GT", "CU", "BO", "DO", "HN", "PY", "SV", "NI", "CR", "PA", "UY"],
        "French": ["FR", "BE", "CH", "CA", "LU", "MC"],
        "German": ["DE", "AT", "CH", "LI"],
        "Italian": ["IT", "CH", "SM", "VA"],
        "Portuguese": ["PT", "BR"],
        "Turkish": ["TR", "CY"],
        "Russian": ["RU", "BY", "KZ", "KG", "TJ", "TM", "UZ"],
        "Indian": ["IN", "HI", "TA", "TE", "ML", "KN", "BN", "MR", "GU", "PA"],
        "Chinese": ["CN", "HK", "TW", "SG"],
        "Japanese": ["JP"],
        "Korean": ["KR"],
        "Greek": ["GR", "CY"],
        "Dutch": ["NL", "BE"],
        "Polish": ["PL"],
        "Swedish": ["SE"],
        "Norwegian": ["NO"],
        "Danish": ["DK"],
        "Finnish": ["FI"],
        "Czech": ["CZ"],
        "Romanian": ["RO"],
        "Hungarian": ["HU"],
        "Thai": ["TH"],
        "Vietnamese": ["VN"],
        "Indonesian": ["ID"],
        "Filipino": ["PH"],
        "Persian/Iranian": ["IR", "FA"],
        "Albanian": ["AL", "ALB"],
        "Latin American": ["LAT", "LATS"],
        "Streaming": ["NF", "SC", "TM"],
    })
    filter_quality_groups: dict = Field(default_factory=lambda: {
        "4K / UHD": ["4K", "UHD", "8K", "2160P"],
        "HD": ["HD", "FHD", "1080P", "720P", "HDR", "HDR10", "HDR10+"],
        "HQ": ["HQ"],
        "SD": ["SD", "480P", "360P"],
        "LQ": ["LQ", "LD"],
        "CAM / Pre-release": ["CAM", "HDTS", "CAMRIP", "TSCAM"],
    })
    filter_platform_groups: dict = Field(default_factory=lambda: {
        "Streaming": ["NETFLIX", "HBO", "HULU", "DISNEY", "DISNEY+", "AMAZON", "PRIME", "APPLE", "APPLETV", "PEACOCK", "PARAMOUNT", "PARAMOUNT+"],
        "Sports": ["ESPN", "DAZN", "PPV", "NBA", "NFL", "MLB", "NHL", "UFC", "WWE", "BEIN", "SKY SPORTS"],
        "News": ["CNN", "BBC", "FOX", "NBC", "CBS", "ABC", "MSNBC", "SKY NEWS", "AL JAZEERA", "FRANCE24"],
        "Kids": ["KIDS", "CARTOON", "DISNEY JUNIOR", "NICK", "NICKELODEON", "PBS KIDS"],
    })
    filter_included_languages: list = Field(default_factory=list)  # Empty = all included
    filter_included_qualities: list = Field(default_factory=list)  # Empty = all included
    filter_include_untagged: bool = True   # Show channels with no detected_prefix
    filter_adult_mode: str = "hide"        # "all", "hide", or "only"
    show_excluded_count: bool = True
    search_includes_filtered: bool = True
    
    # Metadata provider settings
    metadata_enabled: bool = True  # Enable metadata fetching
    metadata_cache_ttl_days: int = 30  # Fresh content cache lifetime
    metadata_old_content_ttl_days: int = 90  # Old content (>2 years) cache lifetime
    metadata_auto_fetch: bool = True  # Automatically fetch on channel selection
    metadata_background_refresh: bool = False  # Background refresh of stale metadata (Phase 3)
    
    # Metadata provider configuration
    metadata_provider_priority: list = Field(default_factory=lambda: ["provider", "tmdb", "omdb"])  # Provider priority order
    metadata_enabled_providers: list = Field(default_factory=lambda: ["provider"])  # Which providers are enabled
    
    # Provider-specific API keys and settings
    metadata_tmdb_api_key: str = ""  # TMDb API key
    metadata_tmdb_language: str = "en-US"  # TMDb language
    metadata_tmdb_include_adult: bool = False  # Include adult content
    
    metadata_omdb_api_key: str = ""  # OMDb API key
    
    # Image caching settings
    image_cache_enabled: bool = True  # Enable image caching
    image_cache_dir: str = "~/.cache/metatv/images"  # Image cache directory
    image_cache_max_size_mb: int = 500  # Maximum cache size in MB
    
    # Content category groups — maps raw source_category labels (from ## headers ##) to
    # normalized display names used in the Global Filter and Discovery shelves.
    # Keys are the normalized type name shown in the UI; values are lists of raw labels
    # exactly as they appear in the provider's ## header ## strings (case-insensitive match).
    content_category_groups: dict = Field(default_factory=lambda: {
        "Sports":        ["SPORTS NETWORK", "SOCCER PPV", "NBA LIVE EVENTS", "NBA TEAMS",
                          "NBA LEAGUE REPLAY", "NHL LIVE EVENTS", "NHL TEAMS", "NFL LIVE EVENTS",
                          "NFL LEAGUE REPLAY", "USA NCAA LIVE", "DAZN PPV US", "FIFA+ PPV",
                          "NBA PASS PPV", "BALLY NETWORK", "B1G+ PPV"],
        "Entertainment": ["ENTERTAINMENT", "SPECTRUM NETWORK", "BEIN CINEMA"],
        "News":          ["NEWS NETWORK"],
        "Kids":          ["KIDS NETWORK"],
        "Movies":        ["MOVIES NETWORK", "PRIME", "TUBI", "PARAMOUNT+ PPV"],
        "Religious":     ["BIBLICAL/RELIGIOUS"],
        "Relaxation":    ["RELAX", "RELAX 4K", "RELAX UHD"],
    })
    # Which content types to include (empty = all shown; mirrors global_filter_included_categories)
    global_filter_included_content_types: list = Field(default_factory=list)

    # Sports / Events view filter state persistence
    # Keyword definitions (sport_keywords, league_keywords) live in:
    #   ~/.config/metatv/sports_definitions.yaml
    # That file is created on first run and is freely editable.
    sports_filter_state: dict = Field(default_factory=dict)
    events_filter_state: dict = Field(default_factory=dict)

    # EPG settings
    epg_watchlist_patterns: list = Field(default_factory=list)
    # e.g. ["NHL", "Jeopardy!", "MasterChef Canada"]
    epg_watchlist_channels: list = Field(default_factory=list)
    # channel_db_ids pinned to watchlist (MY CHANNELS section)
    epg_dismissed_channels: dict = Field(default_factory=dict)
    # {channel_db_id: iso_timestamp_dismissed_until}
    epg_notification_minutes_before: int = 15
    epg_auto_refresh: bool = True
    epg_refresh_interval_hours: int = 24
    epg_hide_filler: bool = True
    epg_filler_patterns: list = Field(default_factory=lambda: [
        "No Game Today", "No Event Today", "Off Air",
        "Sign Off", "No Programme", "TBA",
    ])
    epg_hidden_titles: list = Field(default_factory=list)
    epg_hidden_channels: list = Field(default_factory=list)
    epg_hidden_prefixes: list = Field(default_factory=list)
    epg_category_overrides: dict = Field(default_factory=dict)  # channel_db_id → category code
    epg_filter_state: dict = Field(default_factory=dict)

    # Details pane UI settings
    details_pane_visible: bool = False  # Show/hide details pane
    details_pane_width: int = 400  # Width of details pane in pixels
    details_pane_collapsed_sections: list = Field(default_factory=list)  # Which sections are collapsed

    # Version preference settings (used in "Other Versions" section of details pane)
    preferred_version_prefixes: list = Field(default_factory=list)
    # Ordered prefix codes, e.g. ["EN", "US"] — first match wins (+10 per rank position)
    preferred_version_quality: str = ""
    # Quality marker to prefer, e.g. "1080p", "4K", "HD" — matched against channel name
    preferred_version_provider_ids: list = Field(default_factory=list)
    # Ordered provider UUIDs — prefer content from this provider (+5 per rank position)

    # User-defined human-readable names for prefix codes (e.g. {"KU": "Kurdish", "EAR": "Early Release"})
    # Checked first in _resolve_category_name(), before the built-in lookup tables.
    category_name_overrides: dict = Field(default_factory=dict)
    
    def _inject_new_sections(self) -> None:
        """Insert newly added sidebar sections into existing configs that predate them."""
        new_sections = ["queue", "recommended"]
        changed = False
        for sid in new_sections:
            if sid not in self.sidebar_sections:
                # Insert after "alerts" if present, otherwise at index 0
                idx = self.sidebar_sections.index("alerts") + 1 if "alerts" in self.sidebar_sections else 0
                self.sidebar_sections.insert(idx, sid)
                changed = True
            if sid not in self.sidebar_visible_sections:
                idx = self.sidebar_visible_sections.index("alerts") + 1 if "alerts" in self.sidebar_visible_sections else 0
                self.sidebar_visible_sections.insert(idx, sid)
                changed = True
        if changed:
            self.save()

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from file or create default"""
        config_dir = Path.home() / ".config" / "metatv"
        config_file = config_dir / "config.yaml"
        
        if config_file.exists():
            try:
                with open(config_file) as f:
                    data = yaml.safe_load(f) or {}
                logger.info(f"Loaded config from {config_file}")
                config = cls(**data)
                config._inject_new_sections()
                return config
            except Exception as e:
                logger.error(f"Failed to load config: {e}")

        # Create default config
        config = cls()
        config.save()
        return config
    
    def save(self):
        """Save configuration to file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Set database URL if not set
        if not self.database_url:
            db_path = self.data_dir / "metatv.db"
            self.database_url = f"sqlite:///{db_path}"
        
        config_file = self.config_dir / "config.yaml"
        
        # Convert to dict, handling Path objects
        data = self.model_dump()
        for key, value in data.items():
            if isinstance(value, Path):
                data[key] = str(value)
        
        with open(config_file, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
        
        logger.info(f"Saved config to {config_file}")
