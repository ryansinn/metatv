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

## Coding Standards

### Logging
- **ALWAYS use loguru**: `from loguru import logger`
- **NEVER use standard logging**: `import logging` is deprecated
- Log levels:
  - `logger.debug()` - Detailed diagnostic information
  - `logger.info()` - General informational messages
  - `logger.warning()` - Warning messages for recoverable issues
  - `logger.error()` - Error messages with `exc_info=True` for tracebacks
- Example:
  ```python
  from loguru import logger
  
  logger.debug(f"Processing channel: {channel.name}")
  try:
      result = process()
  except Exception as e:
      logger.error(f"Failed to process: {e}", exc_info=True)
  ```

### Type Hints
- Use type hints for all function parameters and return values
- Import from `typing` module: `Optional`, `List`, `Dict`, etc.
- Example:
  ```python
  def get_channel(channel_id: str) -> Optional[ChannelDB]:
      return session.query(ChannelDB).filter_by(id=channel_id).first()
  ```

### Database Session Management
- Always use try/finally for session cleanup
- **NEVER use `with session` context manager** - it only handles transactions, not cleanup
- Pattern:
  ```python
  session = self.db.get_session()
  try:
      channel = session.query(ChannelDB).filter_by(id=channel_id).first()
      # ... use channel ...
      return result
  finally:
      session.close()
  ```

### Import Order
1. Standard library imports
2. Third-party imports (PyQt6, SQLAlchemy, requests, etc.)
3. Local imports (metatv modules)
4. Separate groups with blank lines
- Example:
  ```python
  import asyncio
  from typing import Optional, List
  
  from PyQt6.QtWidgets import QWidget
  from loguru import logger
  
  from metatv.core.database import ChannelDB
  from metatv.core.config import Config
  ```

### Qt Patterns
- Connect signals in `__init__` or setup methods
- Use `pyqtSignal` for custom signals
- Disconnect signals in cleanup methods
- Use `QTimer.singleShot()` for delayed operations
- Example:
  ```python
  class MyWidget(QWidget):
      # Define custom signals
      item_selected = pyqtSignal(str)
      
      def __init__(self):
          super().__init__()
          self.button.clicked.connect(self.on_button_clicked)
      
      def on_button_clicked(self):
          self.item_selected.emit("some_id")
  ```

### Error Handling
- Always catch specific exceptions when possible
- Use `exc_info=True` with logger.error() for tracebacks
- Show user-friendly messages in UI, detailed messages in logs
- Example:
  ```python
  try:
      result = provider.fetch_data()
  except requests.ConnectionError as e:
      logger.error(f"Connection failed: {e}", exc_info=True)
      self.show_error_message("Connection failed. Check your network.")
  except Exception as e:
      logger.error(f"Unexpected error: {e}", exc_info=True)
      self.show_error_message("An unexpected error occurred.")
  ```

### Documentation
- Use docstrings for all classes, methods, and functions
- Follow Google-style docstring format
- Example:
  ```python
  def fetch_metadata(self, channel_id: str, force_refresh: bool = False) -> Optional[MetadataResult]:
      """Fetch metadata for a channel
      
      Args:
          channel_id: Unique channel identifier
          force_refresh: If True, bypass cache and fetch fresh data
      
      Returns:
          MetadataResult with merged data from all providers, or None if not found
      
      Raises:
          DatabaseError: If database query fails
      """
  ```

### Async Operations
- Use ThreadPoolExecutor for blocking I/O (network requests, file operations)
- Use asyncio for async provider operations
- Keep UI responsive - never block the main thread
- Example:
  ```python
  from concurrent.futures import ThreadPoolExecutor
  
  def load_data_in_background(self):
      executor = ThreadPoolExecutor(max_workers=1)
      future = executor.submit(self.fetch_data)
      future.add_done_callback(self.on_data_loaded)
  ```

### File Organization
- One class per file (with helper classes as exceptions)
- Group related functionality in modules
- Keep files under 1000 lines when possible
- Structure:
  ```
  metatv/
  ├── core/           # Core business logic
  ├── gui/            # UI components
  ├── providers/      # Provider plugins
  ├── metadata_providers/  # Metadata plugins
  └── utils/          # Utility functions
  ```

## Configuration Files

- **Config**: `~/.config/metatv/config.yaml`
- **Database**: `~/.local/share/metatv/metatv.db`
- **Logs**: `~/.config/metatv/logs/metatv.log`

## Database Schema

- **providers**: IPTV provider credentials and status
- **channels**: All channels from all providers
- **metadata**: Media metadata (actors, plot, etc.)
- **filters**: User-defined filter rules

## Metadata System

### Plugin Architecture
MetaTV uses a plugin-based metadata system similar to provider and player plugins.

**Base Class**: `MetadataProviderPlugin` in `metatv/metadata_providers/base.py`
- Abstract base class defining the interface
- All metadata providers must inherit from this class
- Core method: `get_details(channel: ChannelDB, session) -> Optional[MetadataResult]`

**MetadataResult**: Dataclass containing all metadata fields
- Fields: title, year, plot, poster_url, cast, crew, director, genres, rating, runtime, etc.
- `merge(other)` method: Intelligently merges data from multiple providers
- `confidence` score: Higher confidence data preferred during merge

**Provider Chain**: Configured via `metadata_provider_priority` in config
- Tries providers in order until sufficient data found
- Example: `["provider", "tmdb", "omdb"]`
- First provider with data wins (per field)

### Built-in Providers

**ProviderMetadataProvider**: Extracts from Xtream API `raw_data` field
- Zero latency (already cached in database)
- Supports: title, year, plot, poster, cast, rating, genres
- Poster fallback chain: cover → movie_image → logo_url
- Always try first before external APIs

**Future Providers**:
- TMDbProvider: The Movie Database API
- OMDbProvider: Open Movie Database API
- FanartTvProvider: High-quality artwork
- TVDBProvider: TV episode data

### Creating a Metadata Provider

1. Create new file in `metatv/metadata_providers/your_provider.py`
2. Inherit from `MetadataProviderPlugin`
3. Implement required methods:
   ```python
   from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult
   from metatv.core.database import ChannelDB
   from loguru import logger
   
   class YourProvider(MetadataProviderPlugin):
       @property
       def name(self) -> str:
           return "your_provider"
       
       @property
       def display_name(self) -> str:
           return "Your Provider"
       
       @property
       def supported_media_types(self) -> list[str]:
           return ["live", "movie", "series"]
       
       def get_details(self, channel: ChannelDB, session) -> Optional[MetadataResult]:
           """Fetch metadata for a channel"""
           try:
               # Fetch from your API
               data = self.fetch_from_api(channel.name)
               
               return MetadataResult(
                   title=data.get("title"),
                   year=data.get("year"),
                   plot=data.get("plot"),
                   poster_url=data.get("poster"),
                   cast=[{"name": name, "character": None} for name in data.get("cast", [])],
                   confidence=0.9  # 0.0-1.0, higher = more reliable
               )
           except Exception as e:
               logger.error(f"Failed to fetch metadata: {e}", exc_info=True)
               return None
   ```

4. Register in `MetadataProviderRegistry` (auto-discovery in future)
5. Add to config: `metadata_enabled_providers: ["your_provider"]`

### Metadata Caching

**Database Table**: `metadata` (MetadataDB model)
- Stores enriched metadata from all providers
- TTL-based expiration (default: 30 days)
- JSON fields for cast/crew arrays

**Cache Key**: `channel_id` (primary key)
- One metadata record per channel
- Updated when cache expires or force_refresh=True

**JSON Storage**: Use manual json.dumps()/loads() for SQLite
```python
import json

# Saving
metadata.cast = json.dumps(result.cast)
metadata.crew = json.dumps(result.crew)
session.commit()

# Loading
cast = json.loads(metadata.cast) if metadata.cast else []
crew = json.loads(metadata.crew) if metadata.crew else []
```

**Important**: Do NOT use SQLAlchemy's JSON type with SQLite - it has compatibility issues.

### Thread-Safe Metadata Fetching

Metadata fetching is I/O-bound and should never block the UI:

```python
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import pyqtSignal, QObject

class MainWindow(QWidget):
    # Define signal for cross-thread communication
    metadata_loaded = pyqtSignal(object, object)  # channel_id, metadata
    
    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.metadata_loaded.connect(self._update_ui_with_metadata)
    
    def load_metadata(self, channel_id: str):
        """Start background metadata fetch"""
        future = self.executor.submit(self._fetch_metadata, channel_id)
        future.add_done_callback(lambda f: self._on_metadata_done(f, channel_id))
    
    def _fetch_metadata(self, channel_id: str) -> Optional[MetadataResult]:
        """Runs in worker thread - do NOT update UI here"""
        return self.metadata_manager.get_metadata(channel_id)
    
    def _on_metadata_done(self, future, channel_id: str):
        """Called when fetch completes - still in worker thread"""
        try:
            metadata = future.result()
            # Emit signal to marshal to main thread
            self.metadata_loaded.emit(channel_id, metadata)
        except Exception as e:
            logger.error(f"Metadata fetch failed: {e}", exc_info=True)
    
    def _update_ui_with_metadata(self, channel_id: str, metadata: MetadataResult):
        """Runs on main thread - safe to update UI"""
        self.details_pane.show_metadata(metadata)
```

**Rule**: NEVER update Qt widgets from worker threads - always use signals.

## Image Caching System

### Phase 1: URL-Based Caching (Current)

**Cache Directory**: `~/.cache/metatv/images/`
- MD5 hash of URL as filename
- ~90% deduplication (different domains, same path)
- LRU cleanup when cache exceeds 500MB

**Cache Key**: MD5(url)
```python
import hashlib

def get_cache_path(url: str) -> Path:
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return cache_dir / f"{url_hash}.jpg"
```

**Image Validation**: Check magic bytes to verify image type
```python
def validate_image(file_path: Path) -> bool:
    """Check if file is a valid image"""
    with open(file_path, "rb") as f:
        header = f.read(12)
        # Check for JPEG, PNG, GIF, WebP magic bytes
        return (header[:2] == b'\xff\xd8' or  # JPEG
                header[:8] == b'\x89PNG\r\n\x1a\n' or  # PNG
                header[:6] in (b'GIF87a', b'GIF89a') or  # GIF
                header[8:12] == b'WEBP')  # WebP
```

### URL Failover

Some providers serve images on multiple domains. ImageCache tries alternate URLs:

```python
def get_image_async(self, url: str, provider_urls: list[str] = None):
    """Try primary URL, then reconstruct with provider domains"""
    # Try original URL first
    pixmap = self._download_image(url)
    if pixmap:
        return pixmap
    
    # Try alternate domains
    if provider_urls:
        for provider_url in provider_urls:
            alternate_url = self._reconstruct_url(url, provider_url)
            pixmap = self._download_image(alternate_url)
            if pixmap:
                return pixmap
    
    return None

def _reconstruct_url(self, original_url: str, provider_url: str) -> str:
    """Swap domain but keep path"""
    from urllib.parse import urlparse
    
    parsed_original = urlparse(original_url)
    parsed_provider = urlparse(provider_url)
    
    return f"{parsed_provider.scheme}://{parsed_provider.netloc}{parsed_original.path}"
```

### Async Image Loading Pattern

```python
from PyQt6.QtCore import pyqtSignal, QObject

class ImageCache(QObject):
    # Signals for async results
    image_loaded = pyqtSignal(str, object)  # url, QPixmap
    image_failed = pyqtSignal(str, str)     # url, error_message
    
    def get_image_async(self, url: str, provider_urls: list[str] = None):
        """Start async image fetch"""
        self.executor.submit(self._download_and_cache, url, provider_urls)
    
    def _download_and_cache(self, url: str, provider_urls: list[str]):
        """Worker thread - downloads and caches image"""
        try:
            pixmap = self._try_urls(url, provider_urls)
            if pixmap:
                self.image_loaded.emit(url, pixmap)
            else:
                self.image_failed.emit(url, "All URLs failed")
        except Exception as e:
            logger.error(f"Image download failed: {e}", exc_info=True)
            self.image_failed.emit(url, str(e))

# Usage in UI
class DetailsPane(QWidget):
    def __init__(self):
        super().__init__()
        self.image_cache.image_loaded.connect(self._on_image_loaded)
    
    def load_poster(self, url: str, provider_urls: list[str]):
        self.poster_label.setText("Loading poster...")
        self.image_cache.get_image_async(url, provider_urls)
    
    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        """Main thread - safe to update UI"""
        self.poster_label.setPixmap(pixmap)
```

### Phase 2: Perceptual Hashing (Future)
- Calculate perceptual hash (pHash) of image content
- Detect duplicate images regardless of URL
- Near-perfect deduplication
- Thumbnail generation
- WebP conversion for smaller sizes

## Qt Threading Best Practices

### The Golden Rule
**NEVER update Qt widgets from worker threads**. Always marshal UI updates to the main thread using signals.

### Why Threading Matters
- Qt widgets are NOT thread-safe
- Updating UI from worker threads causes segfaults/crashes
- Only the main thread can safely update widgets
- Use Qt's signal/slot mechanism for cross-thread communication

### Correct Pattern: pyqtSignal

```python
from PyQt6.QtCore import pyqtSignal, QObject
from concurrent.futures import ThreadPoolExecutor

class MyWidget(QWidget):
    # Define signal in class scope
    data_ready = pyqtSignal(object)  # Accepts any Python object
    
    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Connect signal to slot (main thread receiver)
        self.data_ready.connect(self._update_ui)
    
    def fetch_data(self):
        """Start background operation"""
        self.status_label.setText("Loading...")  # OK - on main thread
        future = self.executor.submit(self._fetch_data_blocking)
        future.add_done_callback(self._on_fetch_done)
    
    def _fetch_data_blocking(self) -> dict:
        """Worker thread - do NOT touch UI here"""
        # Blocking I/O operations safe here
        result = requests.get("https://api.example.com/data").json()
        return result
    
    def _on_fetch_done(self, future):
        """Worker thread - still can't update UI"""
        try:
            data = future.result()
            # Emit signal to marshal to main thread
            self.data_ready.emit(data)
        except Exception as e:
            logger.error(f"Fetch failed: {e}", exc_info=True)
    
    def _update_ui(self, data: dict):
        """Main thread - safe to update UI"""
        self.result_label.setText(data["message"])
        self.table.populate(data["items"])
```

### Common Threading Pitfalls

❌ **WRONG**: Update widget directly from worker thread
```python
def worker_thread_func(self):
    data = fetch_data()
    self.label.setText(data)  # CRASH! Not on main thread
```

❌ **WRONG**: Call widget methods from worker thread
```python
def worker_thread_func(self):
    result = process_data()
    self.update_table(result)  # CRASH! Widget method on wrong thread
```

✅ **CORRECT**: Use signal to marshal to main thread
```python
data_ready = pyqtSignal(object)

def worker_thread_func(self):
    data = fetch_data()
    self.data_ready.emit(data)  # Signal crosses thread boundary safely

def on_data_ready(self, data):
    self.label.setText(data)  # On main thread - safe
```

### Delayed Main Thread Execution

Sometimes you need to defer execution on the main thread:

```python
from PyQt6.QtCore import QTimer

# Execute after 0ms (next event loop iteration)
QTimer.singleShot(0, lambda: self.update_ui())

# Execute after delay
QTimer.singleShot(1000, lambda: self.show_notification("Done!"))
```

### Signal Blocking During State Restoration

When restoring UI state, block signals to prevent unwanted triggers:

```python
def restore_state(self):
    """Restore UI state from config without triggering signals"""
    for chip in self.media_chips:
        chip.blockSignals(True)  # Disable signals
        chip.set_enabled(config.is_enabled(chip.media_type))
        chip.blockSignals(False)  # Re-enable signals
    
    # Connect signals AFTER state restored
    for chip in self.media_chips:
        chip.toggled.connect(self.on_chip_toggled)
```

### ThreadPoolExecutor Best Practices

```python
from concurrent.futures import ThreadPoolExecutor

class MyClass:
    def __init__(self):
        # Create executor with limited workers
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="MetaTV")
    
    def shutdown(self):
        """Clean shutdown"""
        self.executor.shutdown(wait=True)
    
    def submit_task(self, func, *args):
        """Submit task and handle errors"""
        future = self.executor.submit(func, *args)
        future.add_done_callback(self._handle_result)
        return future
    
    def _handle_result(self, future):
        """Handle task completion"""
        try:
            result = future.result()  # Raises if task raised
            self.process_result(result)
        except Exception as e:
            logger.error(f"Task failed: {e}", exc_info=True)
```

### Debugging Threading Issues

**Symptoms**:
- Random crashes/segfaults
- "QObject::connect: Cannot queue arguments of type 'X'" warnings
- UI freezes
- Inconsistent behavior

**Solutions**:
- Add logging with thread IDs: `logger.debug(f"Thread: {threading.current_thread().name}")`
- Use Qt's debug mode: `QT_DEBUG_PLUGINS=1`
- Check stack traces for cross-thread widget access
- Verify all UI updates go through signals

**Tools**:
```python
import threading

def log_thread():
    thread_id = threading.current_thread().name
    logger.debug(f"Running on thread: {thread_id}")
```

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

### Segfaults/Crashes
- Check if UI widgets updated from worker threads
- Verify all cross-thread communication uses pyqtSignal
- Look for missing signal/slot connections
- Review logs for Qt warnings

### Images not loading
- Check cache directory: `~/.cache/metatv/images/`
- Verify URL is accessible
- Check logs for download errors
- Try URL failover with provider domains
