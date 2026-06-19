# MetaTV — a lean, native media manager + companion player

A lean, native cross-platform desktop app for curating and playing your media: a powerful management UI (multi-source, advanced filtering, metadata enrichment, personalized recommendations, discovery) paired with simple, out-of-the-way mpv playback — designed to live as an ambient companion on a working PC.

## Current Features

### ✅ Implemented

**Providers & Streaming**
- **Multi-Provider Support**: Manage multiple IPTV sources with priority-based URL failover
- **Xtream API Support**: Full integration with Xtream-based IPTV providers
- **Stream Validation**: Automatic URL health checks with geo-blocking failover
- **Single-Instance mpv Player**: Persistent player window with IPC control
- **External Player Support**: Fallback to VLC, ffplay, or other players
- **Auto-Reconnect & Buffer Profiles**: mpv auto-reconnects after brief network drops; selectable buffering (reconnect-only / modest / large) plus optional pre-buffer-before-play, all in Settings → Playback
- **Stream Diagnostics**: one-click Diagnose probes a troubled stream (is it the provider or your connection?) and applies the recommended tuning; consistent HTTP User-Agent across validation, diagnostics, ffprobe, and mpv (fixes UA-gated providers)
- **Split Streams**: optionally give each source its own player window — watch two sources at once; "Play in New Window" from any channel; click the live playback-health readout (buffer · speed · dropped frames) to cycle open windows
- **Episode Auto-Queue**: Automatically queue subsequent episodes in a season

**Content Organization**
- **Series Management**: Browse seasons and episodes with hierarchical tree view
- **Favorites System**: Star your favorite series, movies, and streams (Continue Watching / Never Watched sections)
- **Watch History**: Tracks recently played content with last episode info
- **Watch Queue**: Ordered manual queue with "Continue Watching" / "Up Next" sections, persists across restarts, Clear All / Clear Watched

**Discovery & Recommendations**
- **Preference-Based Recommendations**: Attribute-weighted scoring (genres, directors, cast) combined with TF-IDF plot keyword matching; sidebar section + full Preferences dashboard with weight breakdown
- **Like / Dislike Ratings**: Rate movies and series; signals feed directly into the recommendation engine
- **Impression Tracking & Decay**: Items shown repeatedly without engagement gradually decay in score (−4% per impression, 40% floor) so the list rotates naturally
- **Attribute Muting**: Click 🙅 next to any genre, director, or actor to exclude that attribute from scoring; click again to restore
- **Clickable Keyword Exclusion**: Plot keywords in the Preferences dashboard are clickable links — click to mute/restore individual keywords from the TF-IDF signal
- **Exclusions Review Panel**: Collapsible panel at the bottom of the Preferences dashboard lists everything excluded (muted attributes and not-interested titles) with "Change your mind?" links to undo each
- **Not Interested**: Suppress a title from recommendations without hiding it from browsing
- **Hide Channel**: Remove content from all views permanently
- **Content Preference Signals**: ▲/▼ indicators on cast and director names in the details pane
- **Smart Recommendation Exclusions**: Disliked, hidden, watched, favorited, and Watch Queue items are all automatically excluded from recommendations — only unengaged content surfaces

**EPG & Alerts**
- **EPG System**: XMLTV feed parsing (140 MB+ supported), background fetch, channel matching
- **EPG Watchlist**: Keyword-based pattern matching; live 🔴 and upcoming ⏰ alerts in sidebar
- **EPG On Now / Browse**: See what's airing now or browse the full schedule by channel/time
- **Auto-Relink (no manual Refresh)**: watchlist and Watch Alerts populate automatically — channel↔guide links are rebuilt on launch from existing data, without re-downloading the feed
- **Active-Source Scoping**: On Now and watchlist surfaces show only your enabled, non-expired sources; categories read from stored fields (no render-time re-parsing)
- **EPG Events Tab**: platform live-events surfaced in Timeline / By-Network sub-views
- **EPG Discover**: actionable recommendation rows — add to My Channels, Play, and expand to see upcoming matches
- **Persistent On Now Columns**: drag to reorder; layout remembered across restarts

**Special Content**
- **PPV View**: Pay-per-view event detection with countdown timers
- **Live Events View**: Dedicated view for detected live events
- **Sports View**: Sports channels with sport/league filtering

**Details Pane**
- **Rich Metadata Display**: Posters, cast, ratings, plot, technical details, and content rating
- **Metadata Provider System**: Plugin chain for enriching channels with structured data
- **Image Caching**: Async poster/backdrop loading with LRU cache (500 MB)

**Filtering & Search**
- **Real-Time Search**: Filter channels as you type
- **Advanced Filtering**: Prefix detection for language, quality, and platform grouping
- **Language / Quality / Platform Filters**: EN, ES, 4K, HD, Netflix, etc.
- **Collapsible Filter Section**: Expandable filter controls with persistent visibility state
- **Per-Source Filter Toggle**: click a source in the sidebar to filter the list to it; click it again to clear back to all sources

**UI & Platform**
- **Smart Notifications**: Auto-dismissing progress notifications for background operations
- **SQLite Database**: Fast local caching with background loading and WAL mode
- **Persistent UI State**: All sidebar sizes, section states, and filter selections remembered
- **Resizable Sections**: Draggable sidebar sections with saved heights
- **Unified Context-Menu Registry**: one consistent right-click action set (Play, Play in New Window, Favorite, Queue, rate, hide…) across every channel surface — list, history, favorites, sidebar sections, and EPG
- **What's New**: in-app changelog shown once after each update (and from the Help menu) — a navigable carousel stepping through releases
- **Async-Read Architecture**: heavy DB reads run off the UI thread via a single `_run_query` seam + frozen DTOs, keeping the window responsive on 240k+ channel libraries
- **Repository Pattern**: Clean data access layer separating business logic from UI
- **Player / Provider Abstraction**: Plugin-based systems ready for additional backends

### 🚧 In Progress
- **TMDb / OMDb Metadata Providers**: Architecture complete; external provider implementations pending
- **Resume Playback**: Continue from last position (requires mpv IPC event system)

### 📋 Planned
- **Missing Episode Detection**: Detect and surface gaps when a provider is missing episodes
- **De-duplication**: Group quality variants (reduce channel count to unique titles)
- **Genre Filters**: Organize by genre from metadata
- **Custom Collections**: User-created playlists and groups
- **Export / Import**: Backup and share configuration

## Tech Stack

- **Language**: Python 3.11+
- **GUI**: PyQt6 (GPL-compatible)
- **Database**: SQLite with SQLAlchemy 2.0+ ORM
- **Logging**: loguru with rotation
- **Configuration**: YAML with pydantic validation
- **Player**: mpv with JSON IPC protocol
- **License**: GPL v3

## Installation

### Prerequisites
- Python 3.11 or higher
- mpv player (recommended) or VLC

### Setup

```bash
git clone https://github.com/yourusername/metatv.git
cd metatv

python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

pip install -r requirements.txt
python -m metatv
```

## Usage

### First Run
1. Launch MetaTV: `python -m metatv` or `./run.sh`
2. Add an IPTV provider via the **+** button in the Sources sidebar section
3. Enter your Xtream API credentials and click **Refresh** to load channels

### Navigating Content

**Double-Click Actions:**
- **Series** → Load seasons and episodes
- **Season** → Expand/collapse episode list
- **Episode / Movie / Stream** → Play immediately
- **History Item** → Resume from last episode

**Right-Click Menus:**
- Add/Remove from Favorites or Watch Queue
- Like / Dislike (drives recommendations)
- Not Interested / Hide Channel
- Refresh series data

**Search:**
- Type in the search box to filter channels in real-time
- Clear with × or Esc

### Recommendations
Rate movies and series with 👍/👎 buttons in the details pane. The preference engine learns your taste from genres, directors, and cast, then surfaces personalized recommendations in the sidebar and the **Recommended** dashboard (click the 🎯 chip).

In the Preferences dashboard you can:
- Click **🙅** next to any genre, director, or actor to mute it from scoring
- Click any plot keyword to mute/restore it as a recommendation signal
- See everything you've excluded in the **Exclusions** panel at the bottom, with one-click undo links

The engine automatically excludes content you've disliked, hidden, watched, favorited, or added to the Watch Queue. Items that keep appearing without a reaction are gently deprioritized so new content rotates in.

### Watch Queue
Right-click any channel → **Add to Queue**. The queue persists across restarts and splits into **Continue Watching** (previously started) and **Never Watched** (never played). Items in the queue are automatically excluded from recommendations — no need to manage both lists.

### EPG / Watch Alerts
Add show title patterns to the watchlist (+ Watchlist button in the details pane when a live channel is selected). The Watch Alerts sidebar section shows live and upcoming airings matching your patterns.

## Configuration

### File Locations
- **Config**: `~/.config/metatv/config.yaml`
- **Database**: `~/.local/share/metatv/metatv.db`
- **Logs**: `~/.config/metatv/logs/`
- **Image cache**: `~/.cache/metatv/images/`

### Key Settings
```yaml
playback:
  player: mpv
  use_single_instance: true
  autoplay_season_episodes: true
```

## Development

### Project Structure
```
metatv/
├── metatv/
│   ├── core/                    # Business logic (no UI dependencies)
│   │   ├── config.py            # Pydantic config
│   │   ├── database.py          # SQLAlchemy models + connection
│   │   ├── preference_engine.py # Attribute-weight + TF-IDF recommendations
│   │   ├── epg_manager.py       # EPG fetch/parse/store
│   │   ├── metadata_manager.py  # Metadata provider chain
│   │   ├── special_content.py   # PPV/Events/Sports detection
│   │   └── repositories/        # Data access layer
│   │       ├── channel.py
│   │       ├── epg.py
│   │       ├── queue.py         # Watch queue CRUD
│   │       └── provider.py
│   ├── gui/                     # PyQt6 UI components
│   │   ├── main_window.py       # Three-panel main window
│   │   ├── sidebar_sections.py  # Collapsible sidebar sections
│   │   ├── details_pane.py      # Right panel with metadata
│   │   ├── preferences_view.py  # Preference dashboard + recommendations
│   │   ├── epg_view.py          # EPG: Watchlist / On Now / Browse
│   │   ├── events_view.py       # Live events view
│   │   ├── sports_view.py       # Sports events view
│   │   └── sports_filter_bar.py # Sport/league filter chips
│   ├── providers/               # IPTV source plugins
│   │   └── xtream.py
│   └── metadata_providers/      # Metadata enrichment plugins
│       └── provider.py
├── docs/                        # Architecture and design docs
└── ROADMAP.md
```

### Architecture Principles
- **Clean Separation**: Core logic independent of UI
- **Async Operations**: Background threads for all blocking I/O
- **Database First**: Cache everything locally in SQLite
- **Event-Driven UI**: Qt signals/slots for loose coupling
- **Plugin-Based**: Providers, players, and metadata sources are swappable

See [CLAUDE.md](CLAUDE.md) for coding rules and [docs/](docs/) for design documents.

## Troubleshooting

### Player Not Found
Install mpv: `sudo apt install mpv` (Ubuntu/Debian) or `brew install mpv` (Mac)

### Connection Failed
- Verify URL, username, and password
- Check internet connection
- Try the provider's web interface first

### No Episodes Showing
- Right-click the series → **Refresh** to re-fetch from provider
- Check logs at `~/.config/metatv/logs/`

## License

GPL v3 — See [LICENSE](LICENSE) file.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features and development priorities.
