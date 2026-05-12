# Qt Threading Patterns for MetaTV

## Overview

Qt widgets are **NOT thread-safe**. Attempting to update UI elements from worker threads causes crashes, segfaults, and undefined behavior. This document covers the correct patterns for thread-safe GUI updates in MetaTV.

## The Golden Rule

**NEVER update Qt widgets from worker threads.**

Always marshal UI updates to the main thread using Qt's signal/slot mechanism.

## Why Threading Matters

### The Problem

```python
# ❌ WRONG: This will crash
def worker_thread_function(self):
    data = fetch_data_from_network()  # I/O operation
    self.label.setText(data)  # CRASH! UI update from worker thread
```

**What happens**:
- Qt widgets (QLabel, QPushButton, etc.) can only be accessed from the main thread
- Worker thread tries to call `setText()` on QLabel
- Qt detects cross-thread access
- Segmentation fault or undefined behavior

### Why We Need Threads

- **UI Responsiveness**: Blocking operations (network requests, file I/O) freeze the UI
- **User Experience**: Users expect instant feedback and smooth interactions
- **Background Tasks**: Metadata fetching, image downloads, database queries

### The Solution

Use Qt's **signal/slot mechanism** to marshal data from worker threads to the main thread:

1. Worker thread emits a **signal** with data
2. Signal crosses thread boundary safely
3. **Slot** (callback) runs on main thread
4. Slot updates UI widgets

## Core Pattern: pyqtSignal

### Basic Example

```python
from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtWidgets import QWidget, QLabel
from concurrent.futures import ThreadPoolExecutor
from loguru import logger

class MyWidget(QWidget):
    # Define signal in class scope (must be class attribute)
    data_loaded = pyqtSignal(str)  # Signal carries a string
    
    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.label = QLabel("Loading...")
        
        # Connect signal to slot (main thread receiver)
        self.data_loaded.connect(self._update_label)
    
    def fetch_data(self):
        """Start background operation"""
        # This runs on main thread - safe to update UI
        self.label.setText("Loading...")
        
        # Submit blocking task to worker thread
        future = self.executor.submit(self._fetch_data_blocking)
        future.add_done_callback(self._on_fetch_complete)
    
    def _fetch_data_blocking(self) -> str:
        """Runs in worker thread - do NOT touch UI here"""
        import requests
        response = requests.get("https://api.example.com/data")
        return response.text
    
    def _on_fetch_complete(self, future):
        """Runs in worker thread - still can't update UI"""
        try:
            result = future.result()
            # Emit signal to marshal data to main thread
            self.data_loaded.emit(result)
        except Exception as e:
            logger.error(f"Fetch failed: {e}", exc_info=True)
    
    def _update_label(self, text: str):
        """Slot - runs on main thread - safe to update UI"""
        self.label.setText(text)
```

### Signal Types

Signals can carry any Python object:

```python
from PyQt6.QtCore import pyqtSignal

class MyWidget(QWidget):
    # No arguments
    finished = pyqtSignal()
    
    # Single argument
    text_changed = pyqtSignal(str)
    
    # Multiple arguments
    metadata_loaded = pyqtSignal(str, object)  # channel_id, MetadataResult
    
    # Typed arguments
    progress_updated = pyqtSignal(int)  # int between 0-100
    
    # Any Python object
    data_ready = pyqtSignal(object)
```

### Connecting Signals

```python
class MyWidget(QWidget):
    data_ready = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        
        # Connect to method
        self.data_ready.connect(self.on_data_ready)
        
        # Connect to lambda
        self.data_ready.connect(lambda text: print(f"Got: {text}"))
        
        # Connect multiple slots
        self.data_ready.connect(self.update_ui)
        self.data_ready.connect(self.save_to_cache)
    
    def on_data_ready(self, text: str):
        self.label.setText(text)
```

## Real-World Example: Metadata Fetching

### Problem

Fetching metadata from external APIs is slow (100-500ms per request). Doing this on the main thread freezes the UI.

### Solution

```python
from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtWidgets import QWidget
from concurrent.futures import ThreadPoolExecutor
from metatv.core.metadata_manager import MetadataManager
from metatv.metadata_providers.base import MetadataResult
from loguru import logger
from typing import Optional

class MainWindow(QWidget):
    # Signal for thread-safe metadata updates
    metadata_loaded = pyqtSignal(str, object)  # channel_id, MetadataResult
    
    def __init__(self):
        super().__init__()
        
        # Thread pool for background tasks
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="MetaTV")
        
        # Connect signal to UI updater
        self.metadata_loaded.connect(self._update_details_with_metadata)
        
        self.metadata_manager = MetadataManager(config, session)
    
    def on_channel_selected(self, channel_id: str):
        """User clicks a channel"""
        # Immediate UI feedback (main thread)
        self.details_pane.show_loading_state()
        
        # Start background fetch
        future = self.executor.submit(self._fetch_metadata, channel_id)
        future.add_done_callback(lambda f: self._on_metadata_done(f, channel_id))
    
    def _fetch_metadata(self, channel_id: str) -> Optional[MetadataResult]:
        """Worker thread - blocking I/O operation
        
        IMPORTANT: Do NOT update UI widgets here!
        """
        logger.debug(f"Fetching metadata for {channel_id} on worker thread")
        
        try:
            # This may take 100-500ms (network request)
            metadata = self.metadata_manager.get_metadata(channel_id)
            return metadata
        except Exception as e:
            logger.error(f"Metadata fetch failed: {e}", exc_info=True)
            return None
    
    def _on_metadata_done(self, future, channel_id: str):
        """Worker thread - future callback
        
        IMPORTANT: Still on worker thread - can't update UI!
        """
        try:
            metadata = future.result()
            
            # Emit signal to marshal to main thread
            # This is the ONLY safe way to get data to UI
            self.metadata_loaded.emit(channel_id, metadata)
            
        except Exception as e:
            logger.error(f"Error processing metadata: {e}", exc_info=True)
    
    def _update_details_with_metadata(self, channel_id: str, metadata: Optional[MetadataResult]):
        """Main thread - slot receiver
        
        NOW it's safe to update UI widgets!
        """
        if metadata:
            logger.debug(f"Updating UI with metadata for {channel_id}")
            self.details_pane.show_metadata(metadata)
        else:
            self.details_pane.show_error("No metadata available")
```

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                       MAIN THREAD                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  on_channel_selected(channel_id)                            │
│  ├─ details_pane.show_loading_state() ✅ Safe (main thread)│
│  └─ executor.submit(_fetch_metadata) → launches worker      │
│                                                              │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      WORKER THREAD                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  _fetch_metadata(channel_id)                                │
│  ├─ metadata_manager.get_metadata() ✅ Safe (I/O operation) │
│  └─ returns MetadataResult                                  │
│                                                              │
│  _on_metadata_done(future, channel_id)                      │
│  ├─ result = future.result()                                │
│  └─ metadata_loaded.emit(channel_id, result) ← SIGNAL       │
│                                                              │
└──────────────────────────────┬───────────────────────────────┘
                               │ Signal crosses thread boundary
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       MAIN THREAD                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  _update_details_with_metadata(channel_id, metadata)        │
│  └─ details_pane.show_metadata(metadata) ✅ Safe (main)     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Async Image Loading

Images are downloaded from remote servers (slow). Use signals to update UI when ready.

```python
from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QPixmap
from concurrent.futures import ThreadPoolExecutor
import requests
from loguru import logger

class ImageCache(QObject):
    # Signals for async results
    image_loaded = pyqtSignal(str, object)  # url, QPixmap
    image_failed = pyqtSignal(str, str)     # url, error_message
    
    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ImageCache")
    
    def get_image_async(self, url: str):
        """Start async image download"""
        self.executor.submit(self._download_and_cache, url)
    
    def _download_and_cache(self, url: str):
        """Worker thread - downloads image"""
        try:
            logger.debug(f"Downloading image: {url}")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            # Load QPixmap from bytes
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            
            if pixmap.isNull():
                self.image_failed.emit(url, "Invalid image data")
            else:
                # Emit signal with QPixmap
                self.image_loaded.emit(url, pixmap)
        
        except Exception as e:
            logger.error(f"Image download failed: {e}", exc_info=True)
            self.image_failed.emit(url, str(e))


class DetailsPane(QWidget):
    def __init__(self):
        super().__init__()
        self.image_cache = ImageCache()
        
        # Connect image cache signals
        self.image_cache.image_loaded.connect(self._on_image_loaded)
        self.image_cache.image_failed.connect(self._on_image_failed)
        
        self.poster_label = QLabel("No poster")
    
    def load_poster(self, url: str):
        """Load poster asynchronously"""
        # Immediate UI feedback
        self.poster_label.setText("Loading poster...")
        
        # Start async download
        self.image_cache.get_image_async(url)
    
    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        """Main thread - safe to update UI"""
        logger.debug(f"Image loaded: {url}")
        self.poster_label.setPixmap(pixmap)
    
    def _on_image_failed(self, url: str, error: str):
        """Main thread - safe to update UI"""
        logger.warning(f"Image failed: {url} - {error}")
        self.poster_label.setText("No poster available")
```

## Common Threading Pitfalls

### Pitfall 1: Direct Widget Access

❌ **WRONG**:
```python
def worker_thread_func(self):
    data = fetch_data()
    self.label.setText(data)  # CRASH! Widget access from worker thread
```

✅ **CORRECT**:
```python
data_ready = pyqtSignal(str)

def worker_thread_func(self):
    data = fetch_data()
    self.data_ready.emit(data)  # Signal crosses thread boundary

def on_data_ready(self, data: str):
    self.label.setText(data)  # Safe - on main thread
```

### Pitfall 2: Calling Widget Methods

❌ **WRONG**:
```python
def worker_thread_func(self):
    results = process_data()
    self.table.populate_rows(results)  # CRASH! Method call on widget
```

✅ **CORRECT**:
```python
results_ready = pyqtSignal(list)

def worker_thread_func(self):
    results = process_data()
    self.results_ready.emit(results)

def on_results_ready(self, results: list):
    self.table.populate_rows(results)  # Safe - on main thread
```

### Pitfall 3: Returning Widgets from Threads

❌ **WRONG**:
```python
def worker_thread_func(self) -> QLabel:
    label = QLabel("Hello")  # CRASH! QObject created on wrong thread
    return label
```

✅ **CORRECT**:
```python
def worker_thread_func(self) -> str:
    return "Hello"  # Return data, not widgets

def on_data_ready(self, text: str):
    label = QLabel(text)  # Create widget on main thread
```

### Pitfall 4: Forgetting to Connect Signals

❌ **WRONG**:
```python
class MyWidget(QWidget):
    data_ready = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        # Forgot to connect signal!
    
    def fetch_data(self):
        self.executor.submit(self._fetch)
    
    def _fetch(self):
        data = get_data()
        self.data_ready.emit(data)  # Emits but nothing listening
```

✅ **CORRECT**:
```python
class MyWidget(QWidget):
    data_ready = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        # Connect signal to slot
        self.data_ready.connect(self._on_data_ready)
    
    def _on_data_ready(self, data: str):
        self.label.setText(data)
```

### Pitfall 5: Signal Arguments Don't Match

❌ **WRONG**:
```python
data_ready = pyqtSignal(str)  # Expects string

def worker_func(self):
    self.data_ready.emit(123)  # Emits int - type mismatch

def on_data_ready(self, data: str):
    # May work, may crash, undefined behavior
    pass
```

✅ **CORRECT**:
```python
data_ready = pyqtSignal(object)  # Accept any type

def worker_func(self):
    self.data_ready.emit(123)  # Works

def on_data_ready(self, data):
    if isinstance(data, int):
        # Handle appropriately
        pass
```

## Advanced Patterns

### Pattern 1: QTimer for Delayed Main Thread Execution

Use `QTimer.singleShot()` to defer execution on the main thread:

```python
from PyQt6.QtCore import QTimer

# Execute on next event loop iteration (0ms delay)
QTimer.singleShot(0, lambda: self.update_ui())

# Execute after 1 second
QTimer.singleShot(1000, lambda: self.show_notification("Done!"))

# Common use: Delay UI update until after initialization
def __init__(self):
    super().__init__()
    # Setup UI...
    
    # Restore state after UI is fully initialized
    QTimer.singleShot(0, self.restore_state)
```

### Pattern 2: Blocking Signals During State Restoration

When programmatically setting widget state, block signals to prevent unwanted triggers:

```python
def restore_state(self):
    """Restore UI state from config without triggering signals"""
    # Get enabled media types from config
    enabled_types = self.config.filter_enabled_media_types or ["live", "movie", "series"]
    
    # Block signals during restoration
    for chip in self.media_chips:
        chip.blockSignals(True)  # Disable signal emission
        
        is_enabled = chip.media_type in enabled_types
        chip.set_enabled(is_enabled)
        
        chip.blockSignals(False)  # Re-enable signals
    
    # Connect signals AFTER state restored
    for chip in self.media_chips:
        chip.toggled.connect(self.on_chip_toggled)
```

**Why this matters**:
- Without `blockSignals()`, setting state triggers `toggled` signal
- Signal handlers may save state to config
- Saving wrong state during restoration causes bugs
- Blocking prevents this cycle

### Pattern 3: Progress Updates

Emit progress signals from worker threads:

```python
from PyQt6.QtCore import pyqtSignal

class DataLoader(QObject):
    progress_updated = pyqtSignal(int, int)  # current, total
    load_complete = pyqtSignal(list)
    
    def load_data(self, items: list):
        """Worker thread"""
        results = []
        total = len(items)
        
        for i, item in enumerate(items):
            result = process_item(item)
            results.append(result)
            
            # Emit progress
            self.progress_updated.emit(i + 1, total)
        
        self.load_complete.emit(results)

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.loader = DataLoader()
        
        self.loader.progress_updated.connect(self._on_progress)
        self.loader.load_complete.connect(self._on_complete)
        
        self.progress_bar = QProgressBar()
    
    def _on_progress(self, current: int, total: int):
        """Main thread - update progress bar"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
    
    def _on_complete(self, results: list):
        """Main thread - handle results"""
        self.progress_bar.hide()
        self.display_results(results)
```

### Pattern 4: Error Handling Across Threads

Communicate errors via signals:

```python
from PyQt6.QtCore import pyqtSignal

class Worker(QObject):
    finished = pyqtSignal(object)  # Success result
    error = pyqtSignal(str, str)   # error_type, error_message
    
    def do_work(self):
        """Worker thread"""
        try:
            result = risky_operation()
            self.finished.emit(result)
        
        except ConnectionError as e:
            self.error.emit("connection", str(e))
        
        except ValueError as e:
            self.error.emit("validation", str(e))
        
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            self.error.emit("unknown", str(e))

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = Worker()
        
        self.worker.finished.connect(self._on_success)
        self.worker.error.connect(self._on_error)
    
    def _on_success(self, result):
        """Main thread - handle success"""
        self.display_result(result)
    
    def _on_error(self, error_type: str, message: str):
        """Main thread - handle error"""
        if error_type == "connection":
            self.show_error("Connection failed. Check your network.")
        elif error_type == "validation":
            self.show_error(f"Invalid data: {message}")
        else:
            self.show_error("An unexpected error occurred.")
```

### Pattern 5: ThreadPoolExecutor Best Practices

```python
from concurrent.futures import ThreadPoolExecutor
import atexit

class MyClass:
    def __init__(self):
        # Create executor with thread naming
        self.executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="MetaTV"
        )
        
        # Register cleanup
        atexit.register(self.shutdown)
    
    def shutdown(self):
        """Clean shutdown - wait for threads to finish"""
        logger.info("Shutting down thread pool...")
        self.executor.shutdown(wait=True, cancel_futures=False)
    
    def submit_task(self, func, *args, **kwargs):
        """Submit task with error handling"""
        future = self.executor.submit(func, *args, **kwargs)
        future.add_done_callback(self._handle_task_done)
        return future
    
    def _handle_task_done(self, future):
        """Handle task completion or error"""
        try:
            result = future.result()  # Raises if task raised
            logger.debug(f"Task completed: {result}")
        except Exception as e:
            logger.error(f"Task failed: {e}", exc_info=True)
```

## Debugging Threading Issues

### Symptoms

- Random crashes or segfaults
- "QObject::connect: Cannot queue arguments" warnings
- UI freezes
- Inconsistent behavior (works sometimes, crashes others)

### Debugging Tools

**1. Thread Name Logging**:
```python
import threading
from loguru import logger

def log_thread_info(message: str):
    thread_name = threading.current_thread().name
    logger.debug(f"[{thread_name}] {message}")

# In your code
log_thread_info("Fetching metadata...")
```

**2. Qt Debug Mode**:
```bash
# Run with Qt debugging
QT_DEBUG_PLUGINS=1 python -m metatv

# Enable Qt warnings
export QT_LOGGING_RULES="*.debug=true"
```

**3. Stack Trace Analysis**:
```python
import traceback
from loguru import logger

try:
    # Your code
    pass
except Exception as e:
    logger.error(f"Error: {e}")
    logger.error(traceback.format_exc())
```

### Common Warning Messages

**"QObject::setParent: Cannot set parent, new parent is in a different thread"**
- You created a QObject in a worker thread
- Solution: Create all QObjects on main thread

**"QPixmap: It is not safe to use pixmaps outside the GUI thread"**
- You created/modified QPixmap in worker thread
- Solution: Load image data in worker, create QPixmap on main thread

**"QObject::connect: Cannot queue arguments of type 'MyType'"**
- Signal carries unregistered custom type
- Solution: Use `pyqtSignal(object)` or register type with `qRegisterMetaType`

### Verification Checklist

Before shipping code with threading:

- [ ] All widget updates go through signals?
- [ ] No QWidget/QPixmap creation in worker threads?
- [ ] All signals connected in `__init__`?
- [ ] ThreadPoolExecutor properly shut down?
- [ ] Error handling for all background tasks?
- [ ] Progress feedback for long-running operations?
- [ ] Tested under load (many rapid requests)?
- [ ] No UI freezes during blocking operations?

## Summary

### Do's ✅

- **DO** use `pyqtSignal` for cross-thread communication
- **DO** emit signals from worker threads
- **DO** update UI in slots on main thread
- **DO** use `ThreadPoolExecutor` for blocking I/O
- **DO** handle errors in worker threads
- **DO** provide progress feedback for long operations
- **DO** block signals during state restoration
- **DO** shut down executor cleanly

### Don'ts ❌

- **DON'T** update widgets from worker threads
- **DON'T** create QObjects in worker threads
- **DON'T** call widget methods from worker threads
- **DON'T** return widgets from worker functions
- **DON'T** forget to connect signals
- **DON'T** block the main thread
- **DON'T** ignore threading errors
- **DON'T** assume thread safety without signals

### When in Doubt

If you're not sure if something is thread-safe:
1. **Assume it's NOT thread-safe**
2. **Use a signal to marshal to main thread**
3. **Test thoroughly with rapid operations**
4. **Check logs for Qt warnings**

Following these patterns ensures a stable, responsive MetaTV application.
