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
- [ ] Delete old database to apply schema changes (provider_id column)
- [ ] Verify series data loads correctly from TREX

### 🐛 Known Issues / Fixes Needed
- [x] **Notification auto-dismiss**: Fixed with parent chain walk-up, but needs refactoring (see below) ✅
- [ ] **Notification sizing**: Notifications appear too small on initial render
- [x] **Series playback**: Series now drill down into seasons/episodes with accordion UI ✅
- [x] **Series tree icons**: Removed duplicate collapse/expand icons, using native Qt arrows ✅
- [ ] **Live stream validation**: Ensure live stream URLs are properly constructed and playable
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
  - **Future**: 
    - Search within excluded results for large filtered datasets
    - Provider-level filtering (filter by source when multiple providers active)
    - Visual provider indicators in channel list
  
- [ ] **Episode history tracking**: Add debug logging to trace why parent channel lookup sometimes fails

## Phase 2: Essential Features

### Data Management
- [x] **Provider-agnostic data layer** ✅
  - Abstract series/season/episode data structures
  - Normalize provider-specific formats to internal models
  - Ensure UI components work with any provider type
  - Prepare for PLEX, Jellyfin, Emby, and other future providers
  - Adapter pattern for provider-specific API calls
  - **Implementation**: ProviderPlugin base class, XtreamProvider, provider factory/registry
  
- [ ] **TMDb/OMDb metadata integration**
  - Plugin-based metadata provider system
  - Auto-match channels to metadata by name/year parsing
  - Store in MetadataDB with foreign keys
  - Display poster, plot, cast in detail panel
  - Search by actors, year, genre
  
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

- [ ] **Preview/Detail pane** (right side panel)
  - Show full metadata for selected item
  - Cover art/poster image
  - Plot/description
  - Cast & crew
  - Air date, runtime, rating
  - Technical details (quality, codec, bitrate)
  - Similar/related content suggestions
  - Toggleable visibility

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

### Content Discovery
- [ ] EPG integration ("Live Now" view)
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

### Quality of Life
- [ ] Settings page
  - Player preferences
  - Refresh schedules
  - Notification preferences
  - Cache management
  
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
