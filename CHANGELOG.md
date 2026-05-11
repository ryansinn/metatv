# Changelog

All notable changes to MetaTV will be documented in this file.

## [Unreleased]

### Added
- **Series navigation with accordion UI**
  - Double-click series to drill down into seasons and episodes
  - Tree view with expand/collapse for seasons
  - Back button and breadcrumb navigation
  - Episode playback with watch tracking
  - Mark episodes as watched/unwatched via context menu
  - SeasonDB and EpisodeDB database tables
  - SeriesLoadThread for background series loading
- **Configurable UI icons and indicators**
  - All media type icons (live, movie, series, season, episode)
  - All UI control icons (expand, collapse, play, loading, close, delete, etc.)
  - Notification icons (progress, success, error, warning, info)
  - Theme foundation (theme, accent_color, font settings for future use)
- Dynamic sidebar layout with stretch factors (Sources minimal, Favorites maximum space)
- Watch Alerts section in sidebar (placeholder)
- `provider_id` column to ChannelDB for tracking channel origin
- `cover_url` column to ChannelDB for future cover art display
- Alert system foundation (AlertPatternDB, AlertMatchDB tables)
- Alert scanner system for pattern matching (keyword, regex, quality, media_type)
- Filter preset system with TREX provider preset
- Series data loading support (get_series() API call)
- Multiple URL support per provider with priority ordering
- Connection reliability tracking (success/failure counts, reliability scores)
- Client IP tracking for blocked IP detection
- Dynamic media_type support (string-based, not enum)

### Changed
- MediaType from Enum to flexible string constants (supports any provider-specific types)
- Removed unused MediaType.VOD enum value
- Global Filters removed from sidebar (will be modal/page in future)
- Channel.source_id now stores original stream ID, Channel.provider_id stores provider reference

### Fixed
- Database schema includes provider_id, urls, refresh_schedule, last_refresh, cover_url columns
- Subprocess deadlock when launching players (changed PIPE to DEVNULL for stdout/stderr)
- Duplicate play_media definition
- Favorite icon updates now refresh all channel lists in real-time
- Clear history button properly updates database with synchronize_session parameter
- Notification auto-dismiss and manual dismiss with timer cleanup

### Refactored
- Provider loading logic moved from gui/dialogs.py to core/provider_loader.py
- Separated business logic from GUI layer

### Removed
- stream_builder.py (over-engineered, keeping it simple)

## [0.1.0] - Initial Development

### Added
- PyQt6 GUI with sidebar and content area
- Xtream Codes API client with async operations
- SQLAlchemy database with channels, providers, metadata, filters tables
- Provider management (add, test, settings, multiple URLs)
- Background thread management for non-blocking loads
- Real-time channel search filtering
- External player integration (mpv single-instance mode via IPC, vlc, ffplay)
- Notification system (bottom-right toast with progress tracking)
- Connection testing with status indicators (○ disabled, ● checking, ●✓ online, ⚠ offline)
- Provider settings dialog with URL priority management
- Channel double-click prevention during load
- Configuration management with YAML persistence (~/.config/metatv/config.yaml)
- Structured logging with rotation (loguru, 10MB rotation)
