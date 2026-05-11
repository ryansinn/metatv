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
    history_icon: str = "🕒"  # History indicator
    
    # Notification Icons
    notification_progress_icon: str = "⟳"  # Progress notification
    notification_success_icon: str = "✓"  # Success notification
    notification_error_icon: str = "✗"  # Error notification
    notification_warning_icon: str = "⚠"  # Warning notification
    notification_info_icon: str = "ℹ"  # Info notification
    
    # Theme & Appearance (for future theming system)
    theme: str = "auto"  # "light", "dark", "auto" (follows system)
    accent_color: str = "#4488ff"  # Primary accent color
    use_system_colors: bool = True  # Follow system color scheme
    font_family: str = ""  # Empty = system default
    font_size: int = 0  # 0 = system default
    
    # Sidebar Configuration
    sidebar_sections: list = Field(default_factory=lambda: ["alerts", "favorites", "history", "sources"])  # Order of sections
    sidebar_visible_sections: list = Field(default_factory=lambda: ["alerts", "favorites", "history", "sources"])  # Which sections to show
    sidebar_section_states: dict = Field(default_factory=dict)  # Collapsed state and heights per section
    sidebar_width: int = 300  # Width of sidebar in pixels
    sidebar_section_sizes: list = Field(default_factory=list)  # Heights of sidebar sections in pixels
    
    # Performance
    chunk_size: int = 1000  # Channels to process at once
    concurrent_requests: int = 5
    
    # External players
    preferred_player: str = "mpv"
    player_mode: str = "single-instance"  # "single-instance" or "multiple-instances"
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
    })
    filter_quality_groups: dict = Field(default_factory=lambda: {
        "4K / UHD": ["4K", "UHD", "8K", "2160P"],
        "HD": ["HD", "FHD", "1080P", "720P", "HDR", "HDR10", "HDR10+"],
        "SD": ["SD", "480P", "360P"],
    })
    filter_platform_groups: dict = Field(default_factory=lambda: {
        "Streaming": ["NETFLIX", "HBO", "HULU", "DISNEY", "DISNEY+", "AMAZON", "PRIME", "APPLE", "APPLETV", "PEACOCK", "PARAMOUNT", "PARAMOUNT+"],
        "Sports": ["ESPN", "DAZN", "PPV", "NBA", "NFL", "MLB", "NHL", "UFC", "WWE", "BEIN", "SKY SPORTS"],
        "News": ["CNN", "BBC", "FOX", "NBC", "CBS", "ABC", "MSNBC", "SKY NEWS", "AL JAZEERA", "FRANCE24"],
        "Kids": ["KIDS", "CARTOON", "DISNEY JUNIOR", "NICK", "NICKELODEON", "PBS KIDS"],
    })
    filter_included_languages: list = Field(default_factory=list)  # Empty = all included
    filter_included_qualities: list = Field(default_factory=list)  # Empty = all included
    filter_included_platforms: list = Field(default_factory=list)  # Empty = all included
    show_excluded_count: bool = True
    search_includes_filtered: bool = True
    
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
                return cls(**data)
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
