# MetaTV Roadmap

## Phase 1: Core Functionality (Current)

### ✅ Completed
- [x] Basic PyQt6 GUI with sidebar and content area
- [x] Xtream API client with async operations
- [x] Database with SQLAlchemy (channels, providers, metadata, filters, alerts)
- [x] Provider management (add, test, settings, multiple URLs)
- [x] Connection reliability tracking
- [x] External player integration (mpv, vlc, ffplay)
- [x] Single-instance mpv mode via IPC
- [x] Real-time search filtering
- [x] Notification system (toast notifications with progress)
- [x] Background thread management
- [x] Dynamic sidebar layout (sources minimal, favorites maximum space)
- [x] Favorites system with right-click context menu
- [x] History tracking (last 30 played items)
- [x] Playback recording (last_played, play_count)
- [x] Favorite status indicators (★ filled, ☆ outline)
- [x] Clear history functionality
- [x] Series data loading foundation (get_series() API call)

### 🔄 In Progress
- [ ] Test all new features (favorites, history, playback tracking)
- [ ] Verify series data loads correctly from TREX

### 🐛 Known Issues / Fixes Needed
- [x] **Notification auto-dismiss**: Fixed with parent chain walk-up, but needs refactoring (see below) ✅
- [ ] **Notification sizing**: Notifications appear too small on initial render
- [x] **Series playback**: Series now drill down into seasons/episodes with accordion UI ✅
- [x] **Series tree icons**: Removed duplicate collapse/expand icons, using native Qt arrows ✅
- [x] **Live stream validation**: HTTP HEAD checks before sending to player, automatic failover ✅
- [ ] **Series search**: Search functionality disabled in series view (could add episode/season search later)

### 🔧 Code Quality / Refactoring
- [x] **Notification system architecture** ✅
  - **Problem**: Circular dependency (Manager → Widget → Manager), timer logic in UI layer
  - **Solution**: Moved QTimer management to NotificationManager, widget is pure display
  - **Benefits**: Clean separation of concerns, easier testing, no parent chain lookup
  - **Completed**: NotificationManager owns timers, directly calls dismiss(), widget just displays
  
- [x] **Provider layer abstraction** ✅
  - **Problem**: Provider-specific logic hardcoded in provider_loader with if/else chains
  - **Solution**: Created ProviderPlugin base class, XtreamProvider implementation, provider factory
  - **Benefits**: Easy to add M3U/PLEX/Jellyfin support, UI/core agnostic to provider types
  - **Completed**: All provider interactions go through abstraction layer

- [x] **Repository pattern for data access** ✅
  - **Problem**: 29+ direct database queries scattered throughout GUI layer
  - **Solution**: Created RepositoryFactory with specialized repositories (Channel, Provider, Episode, Season, Filter, Alert)
  - **Structure**: metatv/core/repositories/ directory with separate files per repository (provider.py, channel.py, episode.py, season.py, filter.py, alert.py)
  - **Benefits**: Clean separation of business logic from UI, reusable queries, testable, supports future CLI/API, intuitive file organization
  - **Completed**: All GUI components use repository layer instead of direct session.query()

- [x] **Player abstraction layer** ✅
  - **Problem**: mpv process management embedded in UI, hard to test or add other players
  - **Solution**: Created PlayerPlugin base class, MPVPlayer implementation, PlayerManager facade
  - **Benefits**: Player-agnostic UI, easy to add VLC/ffplay, clean IPC handling, testable
  - **Completed**: MainWindow uses PlayerManager instead of direct mpv process management

- [x] **Channel filtering system** ✅
  - **Problem**: 200k+ unfiltered channels overwhelming to browse, need language/quality/platform filtering
  - **Solution**: Simple prefix extraction with customizable language groups, include-by-default philosophy
  - **UI**: Toggle chips (Live/Movies/Series), dropdown filters (Language/Quality/Platform), show excluded button
  - **Completed**: 
    - ✅ Database schema (detected_prefix column + migration)
    - ✅ Config structure with default language/quality/platform groups
    - ✅ Prefix detection utility (extract_prefix, categorize_prefix)
    - ✅ Filter utilities (matches_filter, compute_prefix_stats)
    - ✅ ChannelRepository filtering support (get_all with prefix filters)
    - ✅ FilterBar widget (ToggleChip, FilterDropdown components)
    - ✅ Complete design documentation (docs/FILTERING_DESIGN.md)
    - ✅ Integration guide (docs/FILTERING_INTEGRATION.md)
    - ✅ FilterBar wired into MainWindow layout
    - ✅ Filter change handler with channel reload
    - ✅ Prefix detection on provider refresh
    - ✅ Filter stats display with live updates
    - ✅ Collapsible filter section with persistent visibility state
    - ✅ Filter selections persist across application restarts
  - **Future**: 
    - Search within excluded results for large filtered datasets
    - Provider-level filtering (filter by source when multiple providers active)
    - Visual provider indicators in channel list

- [x] **Stream validation and URL failover** ✅
  - **Problem**: Geo-blocking causes streams to fail, need automatic failover to alternate provider URLs
  - **Solution**: HTTP HEAD validation before playback, priority-based URL rotation
  - **Completed**:
    - ✅ validate_stream_url() - HTTP HEAD check with 3-second timeout
    - ✅ validate_and_failover_stream_url() - tries all provider URLs in priority order
    - ✅ reconstruct_stream_url() - swaps domain while keeping stream path
    - ✅ ProviderURL model with success/failure statistics tracking
    - ✅ Provider UI supports multiple URLs with add/remove/prioritize
    - ✅ Database JSON storage for provider URL list
    - ✅ Statistics updates on each validation attempt
  - **Future**:
    - Auto-disable failing URLs after threshold
    - Smart URL selection based on historical success rates
    - Client IP tracking for geo-blocking detection

- [x] **UI state persistence** ✅
  - **Problem**: Layout preferences (sidebar width, section heights, filter visibility) lost on restart
  - **Solution**: Comprehensive config-based state persistence system
  - **Completed**:
    - ✅ Sidebar width persistence (sidebar_width config field)
    - ✅ Sidebar section heights persistence (sidebar_section_sizes list)
    - ✅ Sidebar section collapsed states (sidebar_section_states dict)
    - ✅ Filter section visibility (filter_section_visible config field)
    - ✅ Filter selections (filter_enabled_media_types, filter_included_*)
    - ✅ Media type chip states
    - ✅ DESIGN.md documentation with standard patterns for all sections
  - **Pattern**: All UI sections save state on change, restore on startup
  
- [x] **Three-panel layout with collapsible splitters** ✅
  - **Problem**: Need details pane without losing screen space, manual resize cumbersome
  - **Solution**: Three-panel layout with click-to-collapse/expand functionality
  - **Completed**:
    - ✅ CollapsibleSplitter widget with click+drag resize and single-click collapse
    - ✅ Three-panel layout: [Left Sidebar | Center Content | Right Details Pane]
    - ✅ State persistence (widths saved to config)
    - ✅ Smooth transitions and visual affordances
  - **Benefits**: Quick show/hide of panels, efficient screen space usage

- [x] **Details/Preview Pane (Phase 1 MVP)** ✅
  - **Problem**: No way to view channel metadata without opening player
  - **Solution**: Right-side panel with progressive metadata loading
  - **Completed**:
    - ✅ Basic UI with poster, title, rating, year, genres, plot
    - ✅ Collapsible sections (Technical Details, Cast & Crew)
    - ✅ Play and Favorite buttons
    - ✅ Three-tier loading (Database cache → Provider → Future external APIs)
    - ✅ State persistence (width, visibility, collapsed sections)
    - ✅ Single-click selection from favorites/history
    - ✅ Qt threading fixes (pyqtSignal for cross-thread updates)
  - **Future**: Similar content, reviews, episode listings, trailer playback

- [x] **Metadata Provider Plugin System (Phase 1 MVP)** ✅
  - **Problem**: No centralized metadata management, hard to add new sources
  - **Solution**: Plugin architecture similar to ProviderPlugin/PlayerPlugin
  - **Completed**:
    - ✅ MetadataProviderPlugin base class with get_details() interface
    - ✅ MetadataResult dataclass with field merge() logic
    - ✅ ProviderMetadataProvider (extracts from Xtream raw_data)
    - ✅ MetadataManager with provider fallback chain
    - ✅ MetadataProviderRegistry with priority ordering
    - ✅ Database caching (MetadataDB table with cast/crew/ratings/etc.)
    - ✅ Config settings (enabled providers, priority, cache TTL)
    - ✅ Thread-safe fetching with background workers
  - **Future**: TMDbProvider, OMDbProvider, FanartTvProvider, TVDBProvider

- [x] **Image Caching System (Phase 1 MVP)** ✅
  - **Problem**: Re-downloading same images wastes bandwidth and slows UI
  - **Solution**: URL-based caching with LRU cleanup
  - **Completed**:
    - ✅ MD5 URL hashing for cache keys (~90% deduplication)
    - ✅ Local cache directory (~/.cache/metatv/images/)
    - ✅ LRU cleanup at 500MB limit
    - ✅ Image validation (magic bytes)
    - ✅ Async loading with Qt signals
    - ✅ URL failover support (tries multiple provider domains)
    - ✅ Poster fallback to logo_url for missing posters
    - ✅ Loading indicators ("Loading poster...")
  - **Future**: Perceptual hashing, thumbnail generation, WebP conversion

- [x] **Qt Threading Best Practices** ✅
  - **Problem**: UI updates from worker threads cause crashes (segfaults)
  - **Solution**: Always use Qt's signal/slot mechanism for cross-thread updates
  - **Completed**:
    - ✅ pyqtSignal for thread-safe communication
    - ✅ ThreadPoolExecutor for blocking I/O operations
    - ✅ QTimer.singleShot(0, ...) for delayed main-thread execution
    - ✅ Signal blocking during UI state restoration
  - **Documentation**: See docs/THREADING_PATTERNS.md

- [ ] **Episode history tracking**: Add debug logging to trace why parent channel lookup sometimes fails

### Documentation
- [x] **DESIGN.md**: UI state persistence patterns and implementation guidelines ✅
- [x] **FILTERING_DESIGN.md**: Complete filtering system architecture ✅
- [x] **FILTERING_INTEGRATION.md**: Step-by-step integration guide ✅
- [x] **UI_UX_GUIDELINES.md**: User experience principles ✅
- [x] **DETAILS_PANE_DESIGN.md**: Details pane architecture and progressive loading ✅
- [x] **METADATA_SYSTEM.md**: Metadata plugin system and provider chain ✅
- [x] **THREADING_PATTERNS.md**: Qt threading best practices ✅

## Phase 2: Essential Features

### Data Management
- [x] **Provider-agnostic data layer** ✅
  - Abstract series/season/episode data structures
  - Normalize provider-specific formats to internal models
  - Ensure UI components work with any provider type
  - Prepare for PLEX, Jellyfin, Emby, and other future providers
  - Adapter pattern for provider-specific API calls
  - **Implementation**: ProviderPlugin base class, XtreamProvider, provider factory/registry

### Metadata Enhancement (External Providers)
- [ ] **TMDbProvider** (The Movie Database)
  - Movies, series, cast, crew, posters, backdrops
  - API key configuration
  - Language selection
  - Include adult content option
  - Rate limit: 40 requests per 10 seconds
  - High-quality metadata and images
  
- [ ] **OMDbProvider** (Open Movie Database)
  - Alternative movie/series data, ratings
  - API key configuration
  - Poster URLs
  - IMDb/Rotten Tomatoes ratings
  - Simple API, good for ratings
  
- [ ] **FanartTvProvider** (High-quality artwork)
  - TV show logos, clearart, character art
  - Movie posters, backgrounds
  - API key required
  - Best for UI polish
  
- [ ] **TVDBProvider** (TV episode data)
  - Episode descriptions
  - Air dates
  - Episode thumbnails
  - Series/season/episode structure
  
- [ ] **Xtream VOD API Enhancement**
  - **Known limitation**: Current implementation only uses `get_vod_streams` (basic info)
  - **Solution**: Implement `get_vod_info` for full movie metadata
  - **Solution**: Implement `get_live_info` for live stream details
  - **Benefits**: Get complete metadata from provider (plot, cast, director, etc.)
  
- [ ] **Episode-level metadata extraction**
  - Extract episode metadata from series_info response
  - Display in details pane when episode selected
  - Show season/episode numbers, air dates, descriptions
  
- [ ] **Background metadata enrichment**
  - Queue-based async fetching for entire library
  - Progress tracking and cancellation
  - Smart caching with different TTLs
  - Conflict resolution (prefer higher-quality sources)
  
- [ ] **Plugin configuration UI**
  - Enable/disable metadata providers
  - Configure API keys (TMDb, OMDb, FanartTv, TVDB)
  - Set provider priority order
  - Test API key validity
  - Configure rate limits
  - Cache management (clear, refresh)
  - Test metadata provider connection
  
- [ ] **Developer documentation**
  - Plugin development guide
  - MetadataProviderPlugin interface documentation
  - Example plugin implementation
  - Testing framework for plugins
  - Plugin packaging/distribution guide
  
- [ ] **Channel name parser**
  - Extract title, year, season/episode from channel names
  - Detect quality markers (ᴴᴰ, ᴿᴬᵂ, ⁶⁰ᶠᵖˢ, ᵁᴴᴰ)
  - Strip ## category headers
  - Platform detection (NETFLIX, HBO, etc.)

- [ ] **De-duplication system**
  - Group quality variants of same content
  - Show as single item with quality selector
  - Reduce 240k channels to ~20-30k unique titles

### UI Enhancements
- [ ] **Media type tabs/segmented control**
  - Dynamic tabs: All, Livestream, Series, Movies (discovered from DB)
  - Global search applies within active tab
  - Tab badges showing counts
  
- [ ] **Browse mode**
  - Hierarchical category organization using ## headers
  - Expandable/collapsible category groups
  - Channel counts per category
  - Complement to search mode

- [ ] **Details/Preview pane** (right side panel)
  - **See**: docs/DETAILS_PANE_DESIGN.md for full specification
  - **Progressive loading**: Show cached data immediately (0ms), fetch enriched data in background
  - **Three-tier system**: Database cache → Provider metadata → Enriched metadata (TMDb/OMDb)
  - **Section-specific loading**: Spinners for poster, cast, plot, similar content as they load
  - **Collapsible sections**: Cast & Crew, Technical Details, Similar Content, Reviews
  - **Smart caching**: MetadataDB with TTL-based freshness, background refresh worker
  - **Image caching**: Local cache for posters/backdrops (500MB limit)
  - **Content display**:
    - Large poster/cover art
    - Title, year, rating (stars + numeric)
    - Genre tags
    - Plot/description
    - Cast & crew list (with photos - future)
    - Technical specs (resolution, codec, bitrate)
    - Similar content recommendations
    - Play/Favorite buttons
  - **Live TV variant**: Channel logo, EPG data, current program, schedule
  - **State persistence**: Width, visibility, collapsed sections
  - **Toggleable**: Show/hide via button or keyboard shortcut
  - **Responsive**: Minimum width 300px, maximum 500px, draggable divider

- [ ] **Image Cache Optimization**
  - **Phase 1: URL-Based Image Caching (MVP)** ⭐ *Implement First*
    - **Implementation**: Hash image URLs (MD5) to create cache keys
    - **Cache directory**: `~/.cache/metatv/images/{hash}.{ext}`
    - **Automatic deduplication**: Same URL = same file (90% reduction)
    - **Image validation**: Verify magic bytes before saving
    - **LRU cleanup**: When cache > 500MB, delete oldest accessed files
    - **Statistics tracking**: Cache size, hit/miss rate, disk usage
    - **Async downloads**: Non-blocking image fetching with progress
    - **Error handling**: Fallback to placeholder, retry logic
    - **Estimated impact**: ~240k images → ~24k unique (~3GB → ~300MB)
    - **Complexity**: Low (~120 lines of code)
    - **Implementation time**: ~2-3 hours
    - **Code location**: `metatv/core/image_cache.py` with `ImageCache` class
  
  - [ ] **Phase 2: Content-Based Deduplication (Optimization)** 📋 *Roadmap*
    - **Implementation**: Hash image content (SHA-256) after download
    - **Database**: ImageCacheDB table (url_hash, content_hash, path, size, last_access)
    - **Smart lookup**: Check URL hash first (fast), then content hash (catch duplicates)
    - **Cross-provider deduplication**: Same image from different CDNs = one file
    - **Reflink on supported filesystems**: Btrfs/XFS/APFS save disk via COW
    - **ETag validation**: HTTP ETag headers to detect unchanged images
    - **Background migration**: Convert Phase 1 cache to Phase 2 gradually
    - **Statistics**: Show duplicate detection savings
    - **Estimated impact**: ~24k → ~12k unique (~300MB → ~150MB, 5% additional reduction)
    - **Complexity**: Medium (~150 lines of code + database migration)
    - **Implementation time**: ~4-6 hours
    - **Best for**: Users with multiple providers, large collections (50k+ channels)
  
  - [ ] **Phase 3: Perceptual Hash Deduplication (Advanced)** 🔬 *Optional*
    - **Implementation**: Perceptual hashing (pHash, dHash) to detect similar images
    - **Use case**: Different resolutions, crops, watermarks of same image
    - **Comparison threshold**: Hamming distance < 10 = "similar enough"
    - **UI option**: Show original or "best quality" version
    - **Library**: Pillow + imagehash Python library
    - **Performance**: Hash computation on download (~50ms per image)
    - **Database extension**: Add `phash` column to ImageCacheDB
    - **Background worker**: Compute phashes for existing cache
    - **Estimated impact**: ~12k → ~6-8k unique (~150MB → ~100MB, 2% additional reduction)
    - **Complexity**: High (~100 lines of code + dependencies)
    - **Implementation time**: ~6-8 hours
    - **Best for**: Maximum storage optimization, slow network connections
    - **Trade-off**: CPU cost vs disk/bandwidth savings (usually not worth it)

- [ ] **Filter system modal/page**
  - Full-screen filter interface
  - Apply filter presets (4K, HD, Sports, Kids, etc.)
  - Combine multiple filters
  - Show active filter count
  - **Future**: Search within excluded results (for 50k+ filtered items)

### Watch Alerts System
- [ ] **Alert pattern management**
  - Create alerts (keyword, regex, genre, actor, quality, media_type)
  - Alert list in sidebar with match counts
  - Scan new channels after provider refresh
  - Notification when new matches found
  
- [ ] **Alert UI**
  - Add/edit/delete alert patterns
  - View matched channels per alert
  - Mark alerts as viewed
  - Smart defaults (New Releases, 4K Content, etc.)

## Phase 3: Favorites as "Manicured Garden"

### Advanced Favorites
- [ ] **Bookshelf UI for favorites**
  - Grid/card view with cover art from metadata
  - Horizontal scrolling carousels per category
  - Visual discovery interface
  
- [ ] **Auto-organized shelves**
  - Continue Watching (by recent play)
  - Never Watched (favorited but not played)
  - By genre (Action, Comedy, Sports, Kids, etc.)
  - By quality (4K content gets its own shelf)
  - By content type (Live Sports, Documentaries, 24/7 streams)
  
- [ ] **Smart shelves**
  - Recently Favorited
  - Most Watched
  - Highly Rated (from metadata)
  - By decade (90s Classics, 2020s, etc.)

### Export/Import
- [ ] Export favorites to file
- [ ] Import favorites from file
- [ ] Sync favorites across providers
- [ ] Backup/restore user data

## Phase 4: Series & Episodes

### Series Structure
- [x] Parse series structure from Xtream API
  - Call `get_series_info(series_id)` for episodes
  - Store season_number, episode_number in SeasonDB and EpisodeDB
  - Build parent-child relationships
  
- [x] **Episode navigation**
  - Show season/episode list for series in tree view
  - Accordion UI with expand/collapse for seasons
  - Mark episodes as watched via context menu
  - Breadcrumb navigation with back button

- [ ] **Episode/Season level favorites**
  - Add `is_favorite` to EpisodeDB and SeasonDB tables
  - Right-click episode/season → "Add to Favorites"
  - Favorites sidebar shows individual episodes when favorited
  - Double-click favorited episode → play it directly
  - Double-click favorited season → open series view, expand that season
  - Double-click favorited series → open series view (current behavior)
  - Icon indicators in series tree for favorited items

- [ ] **Smart caching & background updates**
  - **Instant Display**: Show cached series/episodes from database immediately (no loading wait)
  - **Background Refresh**: Check API in background for new episodes
  - **Stale Detection**: Track last_refresh timestamp per series
  - **Incremental Updates**: Only fetch new episodes, not entire series
  - **Visual Indicators**: Show "Checking for updates..." subtly, update badge count when new episodes found
  - **Configurable TTL**: Settings for cache lifetime (1 hour, 1 day, 1 week, manual only)
  - **Benefits**: Responsive UI, reduced API calls, better UX for browsing
  
- [ ] **Playlist/Queue system**
  - **Auto-queue subsequent episodes** (configurable, default: on)
    - When playing episode from season, queue all episodes after it in that season
    - Configuration: `autoplay_season_episodes` (bool, default: True)
    - Works with mpv single-instance IPC playlist commands
    - Optional: Stop at season boundary or continue to next season
  - Build custom episode queue
  - Send playlist to mpv via IPC (loadfile append)
  - Listen for mpv IPC events (end-file) to track completion
  - Auto-advance to next episode in queue
  - Queue UI indicator (show "Up Next" in status bar)
  - Resume from last watched episode on series open

### Playback Tracking
- [x] Watch progress tracking basics (last_played, play_count)
- [x] Mark as watched/unwatched
- [x] History shows last played episode for series (S03E01 format)
- [x] Double-click series in history → plays last episode (consistent with movies/live)
- [ ] **"Play Next Episode" button in history**
  - Show ">>" button next to series in history sidebar
  - Tooltip: "Play next episode"
  - Finds next unwatched episode after last played
  - If all watched, plays next in sequence (S03E02 after S03E01)
- [ ] Resume playback from last position (watch_progress seconds)
- [ ] Completion detection (watched vs partial)
- [ ] Progress bars in UI

## Phase 5: Advanced Features

### Multi-Domain Resilience
- [ ] Automatic failover to secondary provider URLs
- [ ] Track which URLs work per client IP
- [ ] Warn when all provider URLs fail (VPN issue detection)
- [ ] Manual URL testing from settings

### Performance
- [ ] Optimize channel list rendering (virtualization)
- [ ] Background metadata fetching
- [ ] Cache management
- [ ] Database indexes and query optimization

### EPG (Electronic Program Guide) System
- [ ] **EPG plugin architecture**
  - **Base class**: `EPGProviderPlugin` abstract interface
  - **Core methods**: `get_program_guide()`, `get_current_program()`, `get_schedule()`, `search_programs()`
  - **Plugin registry**: Auto-discover EPG providers from `metatv/epg_providers/` directory
  - **Data model**: ProgramDB table (program_id, channel_id, title, start_time, end_time, description, category)
  - **Caching**: Local SQLite storage with automatic refresh
  - **Channel matching**: Link EPG data to channels via epg_channel_id
  
- [ ] **Built-in EPG providers**
  - **XtreamEPGProvider**: Use provider's EPG endpoint
    - Endpoint: `/player_api.php?username=X&password=Y&action=get_simple_data_table&stream_id=Z`
    - Parse XML/JSON EPG data
    - Auto-refresh every 4-6 hours
  - **XMLTV Provider**: Standard XMLTV format support
    - File-based or URL-based XMLTV
    - Parser for compressed formats (.gz, .xz)
    - Configurable refresh schedule
  - **M3U EPG**: Extract EPG URLs from M3U playlists
    - Parse #EXTINF tags for EPG references
    - Support TVG attributes
  
- [ ] **EPG UI features**
  - **Live TV "Now Playing" view**: Grid showing current programs
  - **Channel details pane**: Current + next program for selected channel
  - **Timeline view**: Horizontal program schedule with time slots
  - **Genre filtering**: Filter live TV by EPG genre
  - **Program search**: Search EPG data across all channels
  - **Reminders**: Alert when favorite programs air
  - **Recording markers**: Visual indicators for programs to record (future)
  
- [ ] **EPG configuration**
  - Enable/disable EPG providers
  - Configure EPG URLs
  - Set refresh schedule (hourly, every 6h, daily, manual)
  - EPG timezone settings
  - Cache size limits
  - Match EPG to channels (auto + manual mapping)
  
- [ ] **EPG data management**
  - Auto-cleanup of old program data (keep 7 days history, 7 days future)
  - Background refresh worker
  - Manual refresh trigger
  - EPG coverage statistics (% of channels with EPG data)
  - Missing EPG detection and reporting

### Content Discovery
- [ ] Recommendations based on watch history
- [ ] Related content suggestions
- [ ] Trending content

### UI Polish
- [ ] Dark mode / themes
- [ ] Keyboard shortcuts
- [ ] Grid view option for channel list
- [ ] Detail panel with metadata
- [ ] Poster/backdrop display
- [ ] Player controls in app (embedded player option)

## Phase 6: Polish & Distribution

### Configuration System Redesign
- [ ] **Settings page architecture**
  - **Layout transformation**: Sidebar → Settings navigation, Content area → Setting controls, Details pane → Contextual help
  - **Main layout change**:
    ```
    ┌─────────────────────────────────────────────────────────┐
    │  [Settings Mode Active]                          [Done] │
    ├──────────────┬────────────────────────┬─────────────────┤
    │ Navigation   │  Setting Controls      │  Contextual Help│
    │              │                        │                 │
    │ ▸ General    │  [Control Panel]       │  Detailed docs  │
    │ ▸ Providers  │                        │  for current    │
    │ ▸ Players    │  Setting widgets       │  setting        │
    │ ▸ Metadata   │  based on selected     │  section        │
    │ ▸ EPG        │  navigation item       │                 │
    │ ▸ Filters    │                        │  Examples,      │
    │ ▸ Display    │                        │  warnings,      │
    │ ▸ Keyboard   │                        │  related        │
    │ ▸ Advanced   │                        │  settings       │
    │              │                        │                 │
    └──────────────┴────────────────────────┴─────────────────┘
    ```
  
- [ ] **Settings sections** (left navigation)
  - **General**: App behavior, startup, language, theme
  - **Providers**: Add/edit/remove IPTV providers, test connections, URL management
  - **Players**: Select default player (mpv/VLC/ffplay), configure player args, IPC settings
  - **Metadata Providers**: Enable/disable, API keys, priority order, cache settings
  - **EPG Providers**: Enable/disable, EPG URLs, refresh schedule, timezone
  - **Filters**: Default filter state, language groups, quality groups, platform groups
  - **Display**: UI scale, font size, details pane position, theme
  - **Keyboard**: Custom keyboard shortcuts
  - **Notifications**: Auto-dismiss timers, notification position
  - **Performance**: Cache limits, concurrent requests, database optimization
  - **Advanced**: Debug logging, experimental features, config file location
  
- [ ] **Contextual help pane** (right side)
  - **Purpose**: Detailed explanation of currently selected setting
  - **Content types**:
    - **Description**: What this setting does
    - **Usage**: How to use/configure it
    - **Examples**: Common configurations with screenshots
    - **Related settings**: Links to related configuration options
    - **Troubleshooting**: Common issues and solutions
    - **Performance impact**: Does this affect speed/memory?
    - **Default value**: What's the default and why
  - **Dynamic content**: Updates as user navigates settings sections
  - **Rich formatting**: Markdown support, code blocks, images
  - **Search**: Full-text search across help content
  
- [ ] **Settings UI patterns**
  - **Form validation**: Real-time validation with error messages
  - **Test buttons**: Test API keys, test connections, test commands
  - **Reset to default**: Per-setting and per-section reset buttons
  - **Import/Export**: Export settings to JSON, import from file
  - **Dirty state tracking**: Unsaved changes indicator
  - **Apply vs OK**: Apply keeps settings open, OK closes
  - **Keyboard navigation**: Tab through fields, Ctrl+S to save
  
- [ ] **Settings persistence**
  - Auto-save on change (with debounce)
  - Manual save button for batch changes
  - Settings backup/restore
  - Migration system for config file format changes
  - Validation before save (catch errors early)
  
- [ ] **Settings search**
  - Global search box in settings mode
  - Search by setting name, description, keyword
  - Jump to matching settings
  - Highlight search terms in results

### Quality of Life  
- [ ] Multi-language support (i18n)
- [ ] Accessibility improvements
- [ ] Error recovery and user feedback
- [ ] Help documentation

### Platform Support
- [ ] Windows packaging
- [ ] macOS packaging  
- [ ] Linux AppImage/Flatpak
- [ ] Plugin system for community providers

### Advanced Providers
- [ ] M3U playlist support
- [ ] Other IPTV protocols
- [ ] Local media library integration
- [ ] Generic stream source support

## Research & Future Ideas

### Content Organization
- [ ] Machine learning for content categorization
- [ ] Automatic language detection
- [ ] Content quality scoring
- [ ] Duplicate detection improvements

### Social Features
- [ ] Share favorites lists
- [ ] Community ratings
- [ ] Comments/reviews
- [ ] Watch parties (sync playback)

### Advanced Playback
- [ ] Picture-in-picture mode
- [ ] Multi-view (watch multiple streams)
- [ ] Recording/DVR functionality
- [ ] Chromecast/AirPlay support

---

## Current Sprint Focus

**Priority 1: Test Recent Changes**
- Favorites system (add/remove, context menus)
- History tracking (playback recording, clear history)
- Favorite status display (★ vs ☆)
- Real-time UI updates

**Priority 2: Essential Missing Features**
- Media type tabs (All, Livestream, Series, Movies)
- TMDb metadata integration (for bookshelf UI)
- Filter preset integration into GUI

**Priority 3: Favorites Bookshelf**
- Grid/card view prototype
- Cover art display
- Carousel layout
- Auto-organized shelves
