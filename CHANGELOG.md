# Changelog

All notable changes to MetaTV will be documented in this file.

## [Unreleased]

### Added

- **Impression tracking and recommendation decay**
  - `rec_shown_count` and `rec_last_shown` columns on `ChannelDB`
  - `record_impressions()` in `preference_engine.py` increments count at most once per 60-minute window (prevents inflation on repeated list refreshes)
  - Score decay: −4% per impression, floor at 40% — ignored items rotate out naturally without disappearing
  - Impression count shown in recommendation tooltips

- **Attribute muting in Preferences dashboard**
  - 🙅 button after each genre, director, and actor row name — click to exclude that attribute from scoring; click again to restore
  - `muted_attributes` dict persisted in `config.yaml` (`genres`, `directors`, `actors`, `keywords` lists)
  - `score_candidates()` accepts `muted_attrs` parameter; muted entries are skipped during score accumulation
  - Muted rows rendered in gray with strikethrough in the weight breakdown

- **Clickable keyword exclusion**
  - Plot keywords in the Preferences dashboard rendered as clickable `<a href>` links
  - Clicking a keyword toggles it in `muted_attributes["keywords"]` and refreshes scoring
  - Muted keywords displayed with strikethrough; active keywords in normal color

- **Exclusions review panel**
  - Collapsible "What you've excluded" section at the bottom of the Preferences dashboard
  - Groups muted attributes by type (genres, directors, actors, keywords) and not-interested channel titles
  - Each row includes a "Change your mind?" link that restores the item and refreshes
  - Header badge shows total exclusion count

- **Watch Queue exclusion from recommendations**
  - Items currently in the Watch Queue are excluded from `score_candidates()` results
  - Prevents the same title from appearing in both the queue and the recommendations list
  - Completes the exclusion set: disliked, hidden, rec-suppressed, watched, favorited, and queued items are all excluded

- **`get_rec_suppressed()` repository method** on `ChannelRepository` — returns all not-interested channels ordered by name

- **Stop words expansion** in `preference_engine.py`
  - Added plot-pacing adverbs (`abruptly`, `suddenly`, `eventually`, etc.)
  - Added plot-arc verbs (`discover`, `reveal`, `escape`, `return`, etc.)
  - Added generic social/group nouns (`population`, `community`, `family`, etc.)
  - Added vague adjectives (`wealthy`, `dangerous`, `mysterious`, etc.)
  - Added broad nouns (`world`, `drama`, `journey`, `quest`, etc.)
  - Added hollow pronouns and determiners (`everything`, `something`, `anyone`, etc.)

### Changed

- **Watch Queue "Never Watched" section** — renamed from "Up Next" to "Never Watched" to better reflect that manual intervention is required to start playback
- **Sidebar collapse state** — user-set collapsed state is now preserved across `set_empty()` calls; a section the user explicitly collapses stays collapsed even when content is added; a section that auto-collapses because it became empty will auto-expand again when content returns (tracked via `_user_collapsed` flag on `CollapsibleSection`)

---

### Added (earlier)
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
