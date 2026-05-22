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
- [x] **Sports/PPV/Events data investigation**: ✅ COMPLETE
  - Analyzed 284,347 channels: 117 PPV, 20 Live Events, 11,920 Sports
  - Database migration created and applied (003_add_special_content.py)
  - Detection logic implemented (metatv/core/special_content.py)
  - PPV view implemented with countdown timers
  - Ready to test PPV view in GUI!

### 🐛 Known Issues / Fixes Needed
- [x] **Notification auto-dismiss**: Fixed with parent chain walk-up, but needs refactoring (see below) ✅
- [ ] **Notification sizing**: Notifications appear too small on initial render
- [x] **Series playback**: Series now drill down into seasons/episodes with accordion UI ✅
- [x] **Series tree icons**: Removed duplicate collapse/expand icons, using native Qt arrows ✅
- [x] **Live stream validation**: HTTP HEAD checks before sending to player, automatic failover ✅
- [ ] **Series search**: Search functionality disabled in series view (could add episode/season search later)
- [ ] **Queued episode titles**: All queued episodes show first episode's title in mpv player
  - **Limitation**: mpv IPC doesn't support setting titles for queued playlist items
  - **Impact**: Episodes 2-10 in queue all display "Episode 1" title until they start playing
  - **Cause**: `set_property force-media-title` only affects currently playing file, not queued items
  - **Proper solution**: Implement MPV IPC event system (Phase 4) to listen for `playlist-pos` changes and set title when each file starts
  - **Priority**: Medium (doesn't affect playback, just title display)
  
  - [ ] **Queued episode history**: History only updates for first episode in queue, not subsequent auto-played episodes
  - **Limitation**: Currently only the manually-clicked episode is marked as played in history
  - **Impact**: If user clicks episode 5 and episodes 6-10 auto-play, only episode 5 shows in history
  - **Temporary workaround**: User can manually mark episodes as watched via context menu
  - **Proper solution**: Implement MPV IPC event system (Phase 4) to monitor playlist position changes
  - **Priority**: Medium (works for single episodes, enhancement needed for binge-watching)

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
  - **Feature**: Configurable auto-close behavior (`close_player_when_finished` config option)
    - When true (default): Player exits when stream finishes, restarts quickly on next play (~100ms)
    - When false: Player window stays open waiting for next stream (instant switching)
    - Implementation: Use `--idle=once` (quit when done) vs `--idle=yes` (stay open) in mpv
    - Single-instance mode reuses the same mpv process for speed regardless of setting
  - **Feature**: Multi-stream instance limiting (`max_player_instances` config option)
    - Enforces provider's simultaneous connection limits
    - 0 = Use provider's max_connections (respects terms of service)
    - 1 = Single player (default, fastest)
    - N = Allow N simultaneous streams
  - **Feature**: Auto-queue episode playback (`autoplay_season_episodes` config option)
    - Automatically queues all subsequent episodes in season
    - Example: Click episode 5 of 10 → plays 5, queues 6-10
    - Uses mpv IPC `loadfile append` for seamless playback
    - Status bar shows: \"Playing: Episode 5 (+5 queued)\"

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
- [ ] **Special Content Categories UI** (PPV, Live Events, Sports)
  - **Problem**: Sports, PPV, and event streams need different UX than regular channels
    - Time-sensitive content (games, matches, events with specific start times)
    - Need to show EPG/schedule information prominently
    - Different browsing patterns (by league, by date, by event type)
    - PPV content may have pricing/access information
    - Real-time status indicators (Live Now, Starting Soon, Ended)
  
  - **Data investigation** ✅ COMPLETE:
    - Analysis shows 9,313 sports channels, 8,548 PPV channels, 9,500 event channels
    - **PPV Pattern**: Date/time in channel name - `"End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | 8K EXCLUSIVE | US: SOCCER PPV 1"`
    - **Live Events Pattern**: `[EVENT]` or `[LIVE-EVENT]` tags in channel name
    - **Sports Pattern**: Broadcast networks (ESPN, Sky Sports), league channels, team channels
    - **Category structure**: TREX uses hashtag organizational headers (## SOCCER PPV, etc.)
    - **No structured fields**: Everything is in channel name/category, requires parsing
  
  - **Three-View Approach**:
    
    **1. PPV View** (🎯 Start Here - Easiest)
    - **Detection**: Channel name contains date pattern + "PPV" keyword
    - **UI**: 
      - Time-based grid layout sorted by event date
      - Parse event name, date/time, quality from channel name
      - Countdown timers for upcoming events
      - "Ended" badge for past events (may be replays)
      - Event poster/thumbnail from stream_icon
    - **Benefits**: Clear pattern in names, easy to parse, high user value
    
    **2. Live Events View** (🎪 Second Priority)
    - **Detection**: `[EVENT]` or `[LIVE-EVENT]` in channel name
    - **UI**:
      - "Happening Now" banner at top for currently live events
      - Grid layout with event posters
      - Real-time status indicators (Live Now, Starting Soon)
      - Filter by event type (concerts, sports events, special broadcasts)
    - **Benefits**: Easy tag-based detection, real-time focus
    
    **3. Sports View** (⚽ General Discovery - Multi-level Filtering)
    - **Detection**: All remaining sports channels (networks, leagues, teams)
    - **UI**: Three-level cascade filtering (same pattern as Language/Quality/Platform):
      ```
      [Sport ▾]        [League ▾]              [Team ▾]
      ☑ Soccer         ☑ Premier League        ☑ Man United
      ☑ Basketball     ☑ La Liga               ☑ Liverpool  
      ☐ Football       ☑ NBA                   ☐ Arsenal
      ☐ Baseball       ☐ NFL                   ☐ Real Madrid
      ```
    - **Smart cascade filtering**:
      - Select "Soccer" → League dropdown shows only soccer leagues
      - Select "Premier League" → Team dropdown shows only PL teams
      - Multiple selections at each level
      - Works like existing filter system (familiar UX)
    - **Channel list**: Shows filtered results with search
    - **Benefits**: Flexible discovery, consistent with existing UI patterns
  
  - **Detection logic**:
    ```python
    def detect_special_view(channel: ChannelDB) -> Optional[str]:
        name = channel.name.lower()
        
        # Priority 1: PPV (has date/time in name)
        # Pattern: "End | Event Name | all | 11-05-2026 | 09:37 (GMT) | ..."
        if 'ppv' in name and re.search(r'\d{2}-\d{2}-\d{4}', channel.name):
            return 'ppv'
        
        # Priority 2: Live Events (has [EVENT] tag)
        if '[event]' in name or '[live-event]' in name:
            return 'live_event'
        
        # Priority 3: General Sports (everything else with sports keywords)
        category_clean = channel.category.lstrip('#').strip().lower()
        sports_keywords = ['sport', 'football', 'soccer', 'nba', 'nfl', 'nhl', 'mlb',
                           'boxing', 'ufc', 'fight', 'racing', 'cricket', 'tennis',
                           'rugby', 'hockey', 'basketball', 'baseball', 'f1', 'moto',
                           'premier league', 'champions league', 'la liga', 'bundesliga',
                           'espn', 'sky sports', 'bein', 'tsn', 'fox sports']
        
        if any(kw in name or kw in category_clean for kw in sports_keywords):
            return 'sports'
        
        return None
    
    def parse_sport_metadata(channel: ChannelDB) -> dict:
        """Extract sport, league, team from channel name/category"""
        # Parse channel name for sport type, league, team
        # E.g., "EN| NBA: Lakers vs Celtics" → sport=Basketball, league=NBA, teams=[Lakers, Celtics]
        # E.g., "Premier League - Man United TV" → sport=Soccer, league=Premier League, team=Man United
        # Return: {'sport': str, 'league': str, 'team': str, 'vs_match': bool}
        pass
    ```
  
  - **Database changes**:
    - Add `special_view` column to ChannelDB: "ppv", "live_event", "sports", or NULL
    - Add `sport_type` column: "soccer", "basketball", "football", etc.
    - Add `league_name` column: "Premier League", "NBA", "NFL", etc.
    - Add `team_name` column: "Manchester United", "Lakers", etc.
    - Add `event_start_time` column (DateTime) - parsed from PPV channel names
    - Add `event_metadata` JSON column for additional parsed data
    - Migration to auto-detect and populate for existing channels
  
  - **Implementation Phases**:
    
    **Phase 1: PPV View** (2-3 hours) 🎯 ✅ COMPLETE
    - ✅ Create `detect_ppv_channel()` function (date pattern + "PPV" keyword)
    - ✅ Create `parse_ppv_event()` to extract event name, date/time, quality
    - ✅ Add database columns: `special_view`, `event_start_time`, `event_metadata`
    - ✅ Create migration (003_add_special_content.py) for PPV channels
    - ✅ Create PPVView widget with time-based grid layout
    - ✅ Add [💰 PPV (count)] toggle button with event count badge
    - ✅ Parse dates, show countdown timers
    - ✅ Sort by date (upcoming first)
    - ✅ Created `metatv/scripts/populate_special_content.py` utility script
    - ✅ Categorized existing channels: 117 PPV, 20 Events, 11,920 Sports
    - **Result**: PPV view ready to test in GUI! Launch MetaTV to see PPV events with countdown timers
    
    **Phase 2: Live Events View** (2-3 hours)
    - Create `detect_live_event_channel()` function ([EVENT] tag detection)
    - Update migration to populate live_event channels
    - Create LiveEventsView widget with "Happening Now" section
    - Add [🎪 Events] toggle button
    - Real-time status indicators
    - Grid layout with event posters
    
    **Phase 3: Sports View - Detection & Parsing** (3-4 hours)
    - Create `detect_sports_channel()` function (sports keywords)
    - Create `parse_sport_metadata()` to extract sport/league/team:
      - Build sport keyword mapping (basketball → NBA, soccer → Premier League, etc.)
      - Parse league from channel name ("EN| NBA:" → NBA)
      - Parse team from channel name ("Lakers vs Celtics" → Lakers, Celtics)
      - Handle broadcast networks (ESPN, Sky Sports)
    - Add database columns: `sport_type`, `league_name`, `team_name`
    - Update migration to populate sports metadata
    - Build unique lists: sports, leagues (per sport), teams (per league)
    
    **Phase 4: Sports View - UI & Filtering** (2-3 hours)
    - Create SportsView widget with three-level cascade filters
    - Add [⚽ Sports] toggle button
    - Implement FilterDropdown widgets (reuse existing component):
      - Sport dropdown (Soccer, Basketball, Football, etc.)
      - League dropdown (filtered by selected sports)
      - Team dropdown (filtered by selected sports + leagues)
    - Wire filter changes to channel list updates
    - Save filter state to config (persistent across restarts)
    - Channel list shows filtered results with search
    
    **Phase 5: EPG Integration** (Future - requires Phase 5 EPG system)
    - Parse EPG for sports schedule and metadata
    - Display team names, scores, match times in PPV/Events
    - Real-time "Live Now" status from EPG
    - Update countdowns based on EPG data
  
  - **Top-level UI**:
    ```
    [All] [Live] [Movies] [Series] | [💰 PPV] [🎪 Events] [⚽ Sports]
    
    When [⚽ Sports] selected:
    ┌─────────────────────────────────────────────────┐
    │ [Sport ▾] [League ▾] [Team ▾]    [Search...]   │
    ├─────────────────────────────────────────────────┤
    │ Channel List (filtered by selections)           │
    │ - Sky Sports Premier League                     │
    │ - ESPN NBA                                      │
    │ - Manchester United TV                          │
    └─────────────────────────────────────────────────┘
    ```
  
  - **Priority**: HIGH (Phase 2) - Sports/PPV users would greatly benefit
  - **Estimated total time**: 10-13 hours (spread across 5 phases)
  - **Start with**: PPV View (easiest, clearest pattern, high value)
  
  - **Future considerations**:
    - **Category-specific refresh triggers**: PPV/Events/Sports need more frequent refreshes than Movies/Series
    - **Auto-cleanup**: Remove ended PPV events after date passes (configurable retention)
    - **Live status detection**: Real-time "Live Now" indicators (requires EPG or API polling)
    - **Auto-categorization on refresh**: Run `populate_special_content.py` automatically during provider refresh
    - **Incremental updates**: Only categorize new/changed channels (track last_categorized timestamp)
    - **League/team parsing**: Extract sport type, league, team from channel names for Sports view filtering
  
- [ ] **Media type tabs/segmented control**
  - Dynamic tabs: All, Livestream, Series, Movies (discovered from DB)
  - Global search applies within active tab
  - Tab badges showing counts
  
- [ ] **Browse mode**
  - Hierarchical category organization using ## headers
  - **TREX providers**: Use hashtag-prefixed organizational headers to build category tree
  - Expandable/collapsible category groups (e.g., "## SPORTS" → list of sports channels)
  - Channel counts per category
  - Complement to search mode
  - Benefits: Natural browsing, discover content by category, understand provider structure

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

- [ ] **Episode title deduplication in series tree**
  - **Problem**: Episode titles often include redundant series name prefix
    - Example: All episodes show "The Rookie - " prefix when already in "The Rookie" season
    - Visual clutter when repeated 20+ times per season
    - Makes it harder to scan episode names quickly
  
  - **Current behavior**: Show full titles as provided by API (controlled by `show_full_episode_titles: true`)
  
  - **Requirements**:
    1. **Data analysis phase** (prerequisite)
       - Log episode `raw_data` JSON from 2-3 different providers (TREX, others)
       - Identify if providers separate `series_name` from `episode_title` fields
       - Check naming patterns for: Regular episodes, Specials, Movies, Crossovers
       - Document edge cases (multi-part episodes, anthology series, etc.)
    
    2. **Implementation approaches** (choose based on data analysis)
       - **Option A: Use provider fields** (if available)
         - Best: API provides separate `series_name` and `episode_title` fields
         - Display only `episode_title` in tree (series name is redundant)
         - Most reliable, no string manipulation needed
       
       - **Option B: Smart prefix detection** (if API only gives full titles)
         - Analyze all episode titles within a season
         - Find common prefix using longest common prefix algorithm
         - Only strip if prefix length > 5 characters (avoid false positives)
         - Show detected prefix at season level (e.g., season tooltip)
         - Preserve prefix for edge cases (crossovers, specials with different series names)
       
       - **Option C: Configuration flag** (if patterns are inconsistent)
         - Add `show_full_episode_titles` config option (✅ already added)
         - Default: `true` (current behavior, shows full titles)
         - When `false`: Apply smart deduplication (Option A or B)
         - Let users choose based on their provider data quality
    
    3. **Edge case handling**:
       - **Crossover episodes**: "Arrow vs Flash" - preserve different series name
       - **Specials**: May have completely different naming conventions
       - **Multi-part episodes**: "Title (Part 1)" - keep the part indicator
       - **Anthology series**: Different titles intentionally (no deduplication)
       - **Mixed seasons**: Some episodes with prefix, some without
    
    4. **UI considerations**:
       - Display stripped titles in tree view for cleaner appearance
       - Show full title in details pane for context
       - Tooltip on episode shows full original title
       - Season-level indicator if prefix was removed (subtle icon or tooltip)
    
    5. **Testing checklist**:
       - Regular series episodes (most common case)
       - Specials with different naming
       - Crossover episodes from multiple series
       - Anthology series (should not deduplicate)
       - Multiple providers (TREX, others) for consistency
       - Edge case: Episodes with no common prefix
       - Edge case: Very short common prefix (< 5 chars)
    
    6. **Implementation steps**:
       - Phase 1: Add debug logging to inspect `episode.raw_data` structure ⏳
       - Phase 2: Document provider data formats and patterns ⏳
       - Phase 3: Choose implementation approach based on findings ⏳
       - Phase 4: Implement chosen approach with config flag ⏳
       - Phase 5: Test with multiple providers and edge cases ⏳
       - Phase 6: Update default config value if deduplication proves reliable ⏳
  
  - **Files to modify**:
    - `metatv/core/provider_loader.py`: Check raw_data structure
    - `metatv/gui/main_window.py`: Apply deduplication in populate_series_tree()
    - `config.yaml.template`: Config option (✅ added)
    - `docs/SERIES_TITLE_DEDUPLICATION.md`: Document findings and patterns (create)
  
  - **Configuration**:
    - `show_full_episode_titles: true` (default) - Current behavior
    - `show_full_episode_titles: false` - Enable smart deduplication when ready
  
  - **Priority**: Low (Phase 2) - UX polish after core functionality stable
  - **Complexity**: Medium (depends on data structure consistency)
  - **Estimated time**: 3-4 hours (after data analysis phase)
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
  
- [x] **Playlist/Queue system** ✅
  - **Auto-queue subsequent episodes** ✅
    - When playing episode from season, queue all episodes after it in that season
    - Configuration: `autoplay_season_episodes` (bool, default: True)
    - Works with mpv single-instance IPC playlist commands
    - Example: Click episode 5 of 10 → plays 5 and queues 6-10 automatically
    - Status bar shows: "Playing: Episode 5 (+5 queued)"
  - [ ] **MPV IPC Event System** (cross-cutting feature)
    - **Purpose**: Monitor playback events for real-time history updates, progress tracking, completion detection
    - **Architecture**:
      - Background thread monitors mpv IPC socket for events
      - Observe `playlist-pos` property changes (when playlist advances)
      - Listen for `file-loaded` event (new episode starts)
      - Listen for `end-file` event (episode completes)
      - Emit Qt signals for thread-safe UI/database updates
    - **Implementation approach**:
      ```python
      # In MPVPlayer class:
      - _start_event_listener() - Background thread reading IPC socket
      - _observe_property("playlist-pos") - Track position changes
      - _observe_property("time-pos") - Track playback position for resume
      - Emit: playlist_position_changed(index) signal
      - Emit: file_loaded(filepath) signal
      - Emit: file_ended(reason) signal
      
      # In MainWindow:
      - Store episode_queue_map = {0: ep5_id, 1: ep6_id, ...} when queueing
      - Connect to playlist_position_changed signal
      - Update repos.episodes.mark_played(episode_queue_map[index])
      - Update history sidebar in real-time as episodes play
      - Auto-advance "Continue Watching" shelf
      ```
    - **Benefits**:
      - **Real-time history**: History updates as queued episodes play automatically
      - **Resume playback**: Track time-pos to resume from exact position
      - **Completion detection**: Know if episode was watched fully vs partially
      - **Queue visualization**: Show "Now Playing: E05" / "Up Next: E06"
      - **Skip detection**: Detect if user manually skips episodes in playlist
      - **Error handling**: Detect stream failures and trigger failover
    - **Challenges**:
      - Thread management (background thread + Qt signals for cross-thread communication)
      - Socket lifecycle (reconnect on disconnect, handle stale sockets)
      - Event filtering (ignore irrelevant events, debounce rapid changes)
      - State synchronization (ensure queue_map stays in sync with mpv playlist)
    - **Estimated complexity**: Medium (~150-200 lines)
    - **Estimated time**: 3-4 hours
    - **Dependencies**: Requires PyQt6 signals, threading.Thread, socket handling
    - **Testing**: Mock IPC events, verify database updates, test reconnection logic
  - [ ] Build custom episode queue (manual queue management UI)
  - [ ] Queue UI indicator (show "Up Next" in status bar with real-time updates)
  - [ ] Resume from last watched episode on series open (requires IPC event system)
  - [ ] Optional: Stop at season boundary or continue to next season

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
- [ ] **Resume playback from last position** (requires IPC event system)
  - Track `time-pos` property via mpv IPC events
  - Store watch_progress (seconds) in EpisodeDB on file-ended event
  - On play: Check if watch_progress > 30 seconds, prompt "Resume from X:XX?"
  - UI indicator: Progress bar overlay on episode items
- [ ] **Completion detection** (requires IPC event system)
  - Listen for `end-file` event with reason (eof, quit, error)
  - Compare time-pos to duration to determine completion percentage
  - Mark watched if > 90% completed
  - Mark partial if 10-90% completed (show resume option)
  - Mark unwatched if < 10% completed
- [ ] **Progress bars in UI**
  - Show watch progress as colored bar under episode items
  - Color coding: Green (completed), Yellow (in-progress), Gray (unwatched)
  - Percentage display on hover
  - Sync with database watch_progress field

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

- [x] **Core EPG infrastructure** ✅
  - `metatv/core/xmltv_parser.py` — streaming iterparse, handles 140MB+ feeds without loading into RAM; graceful recovery from truncated XML; `on_progress` callback for UI progress bars
  - `metatv/core/epg_manager.py` — background fetch/parse/store via `ThreadPoolExecutor(max_workers=1)` (serialised to avoid SQLite lock conflicts); progress notifications via queued signals (thread-safe); refresh only when `epg_data_end < now + N hours` (configurable per provider, default 48h); 60s watchlist notification timer
  - `metatv/core/repositories/epg.py` — queries: current programmes (On Now), watchlist upcoming/live, daily schedule, full-text search, channel recommendations, starting-soon (for notifications); all queries support optional `lang_code` suffix filter
  - `metatv/core/database.py` — `EpgProgramDB` table; `epg_last_fetched`, `epg_data_end`, `epg_refresh_hours_before` on ProviderDB; migrations applied
  - Channel matching: exact `epg_channel_id` first, then normalized display-name fuzzy fallback; ~4,600 of 6,664 ProSat XMLTV channels matched to playable streams
  - Provider editor: EPG URL field + "Refresh when data expires within N hours" spinbox (6–168h, default 48h)

- [x] **EPG view — watchlist-first UI** ⚠️ (`metatv/gui/epg_view.py`) — *functional, some rough edges*
  - **📅 EPG chip** in header bar; `switch_to_epg_view()` wired alongside PPV/Events/Sports; defaults to Browse tab when watchlist is empty
  - **📋 Watchlist tab**: always-visible keyword input with hint text; tracks show titles/keywords (e.g. "NHL", "Jeopardy"); live 🔴 / upcoming ⏰ per pattern; up to 3 next airings shown; add/remove patterns; auto-switches to Browse on open if no patterns set
  - **Recommendations**: channels with most watchlist-pattern matches in next 7 days; dismiss for 7 days; manage dismissed dialog
  - **📺 On Now tab**: QTreeWidget with columns Channel | Show | Progress (████░░) | Remaining; playable channels only; filler hidden by default; watchlist matches highlighted blue; double-click to play, single-click to show in details pane
  - **📅 Browse tab**: QTreeWidget with columns Time | Channel | Show | Duration; sortable columns with correct time sort (by UTC epoch, not display string); date picker (today + 5 days); time slot filter (all/morning/afternoon/prime time/late night); live search; region filter (top 10 country codes by frequency); watchlist matches bold/blue; double-click to play
  - All times displayed in **machine local timezone** (EPG stored as UTC; converted for display)
  - Region filter: top-10 two-letter country code suffixes from EPG channel IDs; "All" resets filter; actually filters all three tabs
  - In-app toast notifications when watchlist show starts within N minutes (configurable in config.yaml)
  - Progress bar notification during EPG fetch (indeterminate; updates every 10K programmes; auto-completes)

- [ ] **EPG known issues / rough edges**
  - On Now may show 0 results if the EPG data has gaps for the current UTC hour (overnight/early morning)
  - Watchlist recommendations are empty until at least one pattern is added
  - No persistence of which EPG tab was last active
  - Browse "All Day" for a full provider can be slow on first load (no pagination)
  - Watchlist airings only look 48h ahead; no way to browse further from the Watchlist tab
  - `epg_notification_minutes_before`, `epg_auto_refresh`, and `epg_filler_patterns` are config-file-only (no settings UI yet)

- [ ] **EPG content-type filter** *(consider for future sprint)*
  - **Context**: ProSat's XMLTV feed has **no `<category>` tags** — only `title`, `desc`, `start`, `stop`. Xtream also returns no category for ProSat channels. Standard XMLTV genre filtering is therefore not available from this provider.
  - **Viable approach**: Derive content type from the **matched channel's name** (reliable, structured) rather than programme title (inconsistent). Channel names consistently contain genre keywords:
    - Sports: `SPORT`, `ESPN`, `TSN`, `DAZN`, `MLB`, `NFL`, `NBA`, `NHL`, `SKY SPORTS`, `BEIN`
    - News: `NEWS`, `CNN`, `BBC`, `FOX NEWS`, `MSNBC`, `SKY NEWS`
    - Kids: `KIDS`, `CARTOON`, `DISNEY JR`, `NICK`, `JUNIOR`
    - Music: `MUSIC`, `MTV`, `VH1`, `MC MUSIC`
    - Movies/Premium: `MOVIE`, `CINEMA`, `HBO`, `CINEMAX`, `STARZ`
  - **Implementation**: Add `content_type` classification function in `xmltv_parser.py` or `epg_manager.py`. During channel matching in `_build_match_map()`, look up the matched `ChannelDB.name` and classify it. Store as a new column on `EpgProgramDB` or compute at query time by joining ChannelDB.
  - **UI**: Add a `[All Types ▼]` dropdown chip in the EPG header (alongside the existing language dropdown). Filter applies to all three tabs.
  - **Fallback for unmatched channels**: If `channel_db_id` is NULL (no playable stream found), fall back to keyword-scanning the XMLTV display-name directly using the same keyword lists.
  - **Note**: If a future provider supplies real `<category>` tags, parse them in `_parse_programme()` and store in a new `category` column on `EpgProgramDB`. The UI dropdown can then prefer real categories over inferred ones.

- [ ] **EPG data management UI** *(Settings dialog tab)*
  - Notification minutes-before (currently config-only)
  - Auto-refresh toggle + interval (currently config-only)
  - Filler patterns list (currently config-only, default: "No Game Today", "Off Air", "TBA")
  - "Refresh EPG now" button per provider
  - EPG coverage stats (% of channels with matched EPG data)

- [ ] **Compressed XMLTV support**
  - Many providers serve `.xml.gz` — add gzip decompression in `parse_xmltv_url()` via `gzip.open()` around the response stream
  - Check `Content-Encoding: gzip` header and decompress transparently

- [ ] **EPG data cleanup**
  - Auto-delete `EpgProgramDB` rows where `stop_time < now - 24h` (keep only recent history + future)
  - Run on startup or on refresh to prevent unbounded DB growth

### Content Discovery
- [x] **Preference-based recommendations** ✅
  - Attribute-weighted scoring (genres, directors, cast) + TF-IDF plot keywords
  - Like/Dislike ratings; favorites contribute implicit +0.5 signal
  - Sidebar section + full Preferences dashboard with attribute weight breakdown
  - Impression tracking and decay (−4%/impression, 40% floor)
  - Attribute muting (🙅 per attribute row) and keyword muting (clickable links)
  - Exclusions review panel with "Change your mind?" undo links
  - Smart exclusions: disliked, hidden, watched, favorited, and queued items all suppressed
- [ ] Related content suggestions
- [ ] Trending content (requires external data feed)

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

### Internationalisation (i18n)
- [ ] **UI language selection** — All labels, buttons, tooltips, and status messages translatable; user picks language in Settings (English default); candidates: Spanish, French, Arabic, Portuguese, Turkish
- [ ] **Qt Linguist / gettext pipeline** — Extract strings into `.ts`/`.po` files so community contributors can add translations without touching Python code
- [ ] **RTL layout support** — Mirror layout direction for Arabic/Hebrew; Qt has built-in `LayoutDirection::RightToLeft` support that needs to be enabled and tested
- [ ] **Locale-aware date/time formatting** — Time display (12h vs 24h), date order, and weekday names follow the selected locale rather than a hard-coded format string

---

## EPG — Future

- [ ] **Right-click context menu on On Now rows** — "Hide show globally", "Add to watchlist (global)", "Watch on [Channel] only", "Dismiss channel for 7 days"
- [ ] **Channel-specific watchlist** — `config.epg_channel_watchlist: dict[channel_db_id, list[str]]`; two-tier Watchlist tab showing global patterns + per-channel entries with priority channels rising to top
- [x] **Remaining column visual** — Replaced text with `QStyledItemDelegate` progress bar showing proportion aired; tooltip gives exact remaining time
- [ ] **Guide Channel player** — Embedded mpv player in EPG view (50/50 split), autoplay on channel browse with debounce, Autoplay On/Off toggle
- [ ] **Collapsible category groups in On Now** — Group rows by category prefix (parent items), allow collapsing/expanding groups; collapsed state persists in config; replaces the region filter dropdown
- [ ] **Configurable channel prefix patterns** — Settings screen to define custom delimiter rules (e.g., `"EPL:"` special case), rename/alias category codes, and mark prefixes as league vs. country; currently best-effort with static defaults
- [ ] **EPG accuracy flagging — suppress + diagnose** — Per-channel "flag EPG as unreliable" action (right-click or details pane button). Two effects:
  - **Operational**: flagged channels are excluded from watchlist matching and show "EPG data unreliable" in On Now / details pane instead of a potentially wrong show title — degrades gracefully rather than misleading the user
  - **Diagnostic**: stores structured mismatch reports locally (`epg_accuracy_flags.json`: `{channel_db_id, channel_name, epg_channel_id, matched_score, flagged_at, user_note?}`); flag visible in the details pane debug line and the 🚫 Hidden tab
- [ ] **AI-assisted EPG mismatch analysis** — Export accumulated flags to an LLM (Claude API) with context: channel name, matched EPG ID, sample of recent programme titles, fuzzy-match score. Model identifies the failure pattern (wrong feed linked, normalization mismatch, timezone offset, etc.) and suggests a corrected `epg_channel_id` mapping. Output shown in a review dialog; user accepts the fix or dismisses.

---

## Current Sprint Focus

**Completed (this sprint)**
- ✅ Impression tracking + score decay (rotates stale recs naturally)
- ✅ Attribute muting (🙅 per genre/director/actor row)
- ✅ Clickable keyword exclusion in Preferences dashboard
- ✅ Exclusions review panel with undo links
- ✅ Watch Queue exclusion from recommendations
- ✅ Sidebar collapse state fix (`_user_collapsed` flag)
- ✅ "Never Watched" rename in Watch Queue section

**Next Up**
- Discovery UI — 🧭 chip, genre/decade/director/actor shelves
- TMDb / OMDb metadata provider implementations (architecture already in place)
- Resume playback via mpv IPC event system
