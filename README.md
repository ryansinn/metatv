# MetaTV - IPTV Stream Organizer

A powerful, cross-platform IPTV stream organizer with advanced filtering, metadata integration, and flexible organization options.

## Current Features

### ✅ Implemented
- **Xtream API Support**: Full integration with Xtream-based IPTV providers
- **Series Management**: Browse seasons and episodes with hierarchical tree view
- **Favorites System**: Star your favorite series, movies, and streams
- **Watch History**: Tracks recently played content with last episode info
- **Smart Notifications**: Auto-dismissing progress notifications for background operations
- **Single-Instance mpv Player**: Persistent player window with IPC control
- **External Player Support**: Fallback to VLC, ffplay, or other players
- **Real-Time Search**: Filter channels as you type
- **SQLite Database**: Fast local caching of channels, seasons, and episodes
- **Background Loading**: Non-blocking UI with threaded data fetching
- **Collapsible Sidebar**: Favorites and History sections with persistent state
- **Context Menus**: Add/remove favorites with right-click

### 🚧 In Progress
- **Episode Auto-Queue**: Automatically queue next episodes in season
- **Browse Mode**: Category-based navigation with expandable groups
- **Language Filters**: Filter content by language prefix (EN, ES, FR, etc.)
- **Metadata Integration**: TMDb/OMDb enrichment for cast, ratings, descriptions

### 📋 Planned
- **Quality Filters**: Filter by resolution (4K, HD, SD)
- **Genre Filters**: Organize by genre from metadata
- **Preview Pane**: Rich metadata display with cover art
- **Resume Playback**: Continue from last position
- **Custom Collections**: User-created playlists and groups
- **Multi-Provider Support**: Manage multiple IPTV sources
- **Export/Import**: Backup and share configuration

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
# Clone repository (when public)
git clone https://github.com/yourusername/metatv.git
cd metatv

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run application
python -m metatv
```

## Usage

### First Run
1. Launch MetaTV: `python -m metatv`
2. Add IPTV Provider: Settings → Add Provider
3. Enter Xtream API credentials:
   - Name: Your provider name
   - URL: Provider base URL
   - Username: Your username
   - Password: Your password
4. Click "Refresh" to load channels

### Navigating Content

**Double-Click Actions:**
- **Series** → Load seasons and episodes
- **Season** → Expand/collapse episode list
- **Episode** → Play episode
- **Movie/Stream** → Play immediately
- **History Item** → Resume from last episode

**Right-Click Menus:**
- Add/Remove from Favorites
- Refresh series data (re-fetch from provider)

**Search:**
- Type in search box to filter channels in real-time
- Clear with × button or Esc key

### Favorites & History
- **Add to Favorites**: Right-click channel → "Add to Favorites"
- **View Favorites**: Sidebar → Favorites section
- **View History**: Sidebar → History section (shows last watched episode)

### Player Controls
- MetaTV uses mpv in a persistent window
- Control playback in mpv window (space to pause, q to close, etc.)
- Episodes play in same window without restart

## Configuration

### File Locations
- **Config**: `~/.config/metatv/config.yaml`
- **Database**: `~/.local/share/metatv/metatv.db`
- **Logs**: `~/.config/metatv/logs/`

### Settings
Edit `config.yaml` or use Settings dialog (future):

```yaml
playback:
  player: mpv
  use_single_instance: true
  autoplay_season_episodes: true

ui:
  sidebar:
    favorites_collapsed: false
    history_collapsed: false
```

## Development

### Project Structure
```
metatv/
├── metatv/
│   ├── core/           # Business logic
│   │   ├── config.py   # Configuration management
│   │   ├── database.py # SQLAlchemy models
│   │   ├── notifications.py # Notification system
│   │   └── provider_loader.py # Background data loading
│   ├── gui/            # PyQt6 UI
│   │   ├── main_window.py # Main application window
│   │   ├── sidebar_sections.py # Collapsible sections
│   │   └── notification_widget.py # Toast notifications
│   ├── providers/      # IPTV provider adapters
│   │   └── xtream.py   # Xtream API client
│   └── __main__.py     # Entry point
├── docs/               # Documentation
│   ├── xtream_api_schema.md # API reference
│   └── UI_UX_GUIDELINES.md # UI/UX standards
├── requirements.txt    # Python dependencies
└── ROADMAP.md         # Feature roadmap
```

### Architecture Principles
- **Clean Separation**: Core logic independent of UI
- **Async Operations**: Background threads for I/O
- **Database First**: Cache everything locally
- **Stateless Providers**: Providers fetch, core manages state
- **Event-Driven UI**: Signals/slots for loose coupling

See [UI/UX Guidelines](docs/UI_UX_GUIDELINES.md) for interaction patterns and standards.

## Contributing

MetaTV is under active development. Contributions welcome!

### Development Setup
```bash
# Install in development mode
pip install -e .

# Run with debug logging
python -m metatv --debug

# Check logs
tail -f ~/.config/metatv/logs/metatv_*.log
```

### Coding Standards
- Follow PEP 8 style guide
- Use type hints (Python 3.11+ syntax)
- Document public APIs with docstrings
- Keep functions focused and testable
- Refer to [UI/UX Guidelines](docs/UI_UX_GUIDELINES.md) for UI patterns

## Troubleshooting

### Player Not Found
```
Error: Player not found
```
Install mpv: `sudo apt install mpv` (Ubuntu/Debian) or `brew install mpv` (Mac)

### Connection Failed
```
Failed to connect to provider
```
- Verify URL, username, and password
- Check internet connection
- Try provider's web interface first

### No Episodes Showing
- Right-click series → "Refresh" to re-fetch data
- Check logs: `~/.config/metatv/logs/`
- Verify provider has episode data (some providers only list channels)

## License

GPL v3 - See [LICENSE](LICENSE) file

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features and development priorities.

## Support

- **Issues**: GitHub Issues (when repository is public)
- **Logs**: Check `~/.config/metatv/logs/` for errors
- **Config**: Located at `~/.config/metatv/config.yaml`
