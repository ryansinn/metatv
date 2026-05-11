# MetaTV Development Guide

## Project Structure

```
metatv/
├── metatv/              # Main application package
│   ├── core/           # Core functionality
│   │   ├── config.py   # Configuration management
│   │   ├── database.py # Database models and connection
│   │   ├── models.py   # Data models (Channel, Provider, etc.)
│   │   └── notifications.py  # Notification system
│   ├── providers/      # Provider plugins
│   │   ├── base.py     # Base plugin interface
│   │   └── xtream.py   # Xtream API client
│   ├── gui/            # User interface
│   │   ├── main_window.py    # Main application window
│   │   ├── dialogs.py        # Dialogs (add provider, etc.)
│   │   └── notification_widget.py  # Toast notifications
│   ├── __init__.py
│   └── __main__.py     # Application entry point
├── venv/               # Virtual environment
├── requirements.txt    # Python dependencies
├── run.sh             # Launch script
└── README.md          # Project documentation
```

## Running the Application

### Option 1: Using the launch script
```bash
./run.sh
```

### Option 2: Direct Python execution
```bash
venv/bin/python -m metatv
```

### Option 3: With fish shell
```bash
venv/bin/python -m metatv
```

## Features Implemented

### Core Features
- ✅ Python + PyQt6 architecture
- ✅ SQLite database with SQLAlchemy ORM
- ✅ Configuration management
- ✅ Plugin-based provider system
- ✅ Xtream API client with async support
- ✅ Non-blocking background operations
- ✅ Progress notification system
- ✅ Main GUI window with sidebar

### Xtream Provider
- ✅ Connection testing with diagnostic steps
- ✅ Progressive channel loading
- ✅ Background data fetching
- ✅ Live TV support
- ✅ VOD support
- ✅ Category support

### User Interface
- ✅ Main window with source/filter/favorites sidebar
- ✅ Add provider dialog with connection testing
- ✅ Bottom-right toast notifications
- ✅ Progress tracking with live updates
- ✅ Non-blocking UI during data loading

## Testing with Your Xtream Provider

1. Launch the application: `./run.sh`
2. Click "Add Provider" button
3. Fill in your Xtream credentials:
   - Name: Any name you want
   - Type: Xtream
   - URL: Your provider's URL (e.g., `http://example.com:8000`)
   - Username: Your username
   - Password: Your password
4. Click "Test Connection" to verify credentials
5. Click "Add Provider" to start loading channels
6. Watch the progress notification in bottom-right corner
7. Channels will appear as they load (non-blocking)

## What Happens When You Add a Provider

1. **DNS Resolution**: Checks if domain resolves
2. **TCP Connection**: Tests if server is reachable
3. **Authentication**: Validates credentials
4. **Category Fetch**: Gets available categories
5. **Channel Loading**: Progressively loads all channels in background
6. **Database Storage**: Stores channels in local SQLite database
7. **UI Update**: Updates channel list as data loads

## Next Steps (Not Yet Implemented)

- [ ] Channel list display and search
- [ ] Filter system (global and per-source)
- [ ] External player integration (mpv, VLC)
- [ ] Metadata fetching (TMDb, OMDb)
- [ ] Favorites system
- [ ] EPG support
- [ ] Export/import configuration
- [ ] Preset filter library
- [ ] Diagnostic tools

## Development

### Adding a New Provider Type

1. Create new file in `metatv/providers/`
2. Inherit from `ProviderPlugin` base class
3. Implement required methods:
   - `test_connection()`
   - `fetch_channels()`
   - `get_categories()`
4. Register in provider registry

### Adding a Metadata Provider

1. Create plugin in `metatv/metadata/`
2. Implement `MetadataProvider` interface
3. Add to metadata provider registry

## Configuration Files

- **Config**: `~/.config/metatv/config.yaml`
- **Database**: `~/.local/share/metatv/metatv.db`
- **Logs**: `~/.config/metatv/logs/metatv.log`

## Database Schema

- **providers**: IPTV provider credentials and status
- **channels**: All channels from all providers
- **metadata**: Media metadata (actors, plot, etc.)
- **filters**: User-defined filter rules

## Troubleshooting

### App won't start
- Check logs: `~/.config/metatv/logs/metatv.log`
- Verify PyQt6 is installed: `venv/bin/python -c "import PyQt6"`

### Connection test fails
- Verify URL format (include port)
- Check internet connection
- Try with curl: `curl http://yourprovider.com:8000/player_api.php?username=X&password=Y`

### Channels not loading
- Check notification for errors
- View logs for detailed error messages
- Verify provider is active
