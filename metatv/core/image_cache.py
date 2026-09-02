"""Image caching system - Phase 1: URL-based caching (MVP)"""
import hashlib
import threading
import time
from pathlib import Path
from typing import Optional, Dict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QObject, pyqtSignal

from loguru import logger


# Negative-cache windows (in-memory only; reset every launch). Keyed at two
# grains because the two failure modes mean different things: a host that
# won't connect won't connect for ANY url on it, but an HTTP error status is
# about that one file, not the host.
_HOST_COOLDOWN_S = 600   # connect-timeout / connection error: skip the host
_URL_COOLDOWN_S = 3600   # HTTP error status (e.g. 404): skip just that url


class ImageCache(QObject):
    """Cache poster/backdrop images locally - Phase 1 MVP
    
    Strategy: Hash URL to create cache key. Same URL = same cached file.
    Benefits: ~90% reduction in storage, handles TMDb poster reuse across variants
    Cache size: ~300MB for ~30k unique images
    """
    
    # Public signals
    image_loaded = pyqtSignal(str, QPixmap)  # url, pixmap
    image_failed = pyqtSignal(str, str)       # url, error_message

    # Private signal: worker emits (url, cache_path_str); main thread creates QPixmap
    _image_ready = pyqtSignal(str, str)
    
    def __init__(self, cache_dir: str = "~/.cache/metatv/images", 
                 max_size_mb: int = 500):
        super().__init__()
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_mb = max_size_mb
        
        # In-memory index: url -> cache_path mapping
        self.cache_index: Dict[str, Path] = {}
        
        # Thread pool for async downloads
        self.executor = ThreadPoolExecutor(max_workers=4)

        # In-flight dedup: a url already being downloaded is never
        # resubmitted. The requester's own image_loaded/image_failed
        # connection still fires when the one in-flight download completes —
        # both signals are broadcast per-url.
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()

        # Negative cache: host or full url -> cooldown deadline
        # (time.monotonic()). Guarded by the same lock as _inflight.
        self._download_cooldowns: Dict[str, float] = {}

        # Marshal pixmap creation to the main thread
        self._image_ready.connect(self._on_image_ready)

        # url -> [WeakMethod(on_loaded), …] for callers that want ONLY their
        # own image. See subscribe().
        self._subscribers: "dict[str, list[tuple]]" = {}

        # Failure arrives from a worker thread; this hop puts the subscriber
        # callbacks back on the main thread before any widget is touched.
        self.image_failed.connect(self._on_failed_main)

        logger.info(f"Image cache initialized: {self.cache_dir}")
    
    def subscribe(self, url: str, on_loaded, on_failed=None) -> None:
        """Deliver *url*'s result to these callbacks and nobody else.

        Why this exists instead of the ``image_loaded`` signal
        -----------------------------------------------------
        ``image_loaded`` is a BROADCAST. That is right for the handful of
        one-per-view listeners (details pane, lightbox, trail map, channel-list
        thumbnails) — each connects once and lives as long as its view.

        A Discover shelf connects it PER CARD. With N cards waiting for
        posters, every arriving image invokes the slot on all N of them and
        N-1 immediately return on a url mismatch, so filling a screen of
        posters costs N² slot dispatches. Measured, dispatch alone, before a
        single pixel is decoded:

              50 cards ->    0.6 ms
             200 cards ->    9.2 ms
             400 cards ->   38.4 ms
             800 cards ->  157.3 ms

        That is precisely the owner's report — scrolling INTO unloaded posters
        is choppy, scrolling back over loaded ones is smooth, because a card
        drops out of the fan-out once its image arrives.

        Callbacks are held as weak references. A card destroyed while its
        poster is still downloading is simply skipped; a strong reference here
        would keep dead widgets alive and then raise ``RuntimeError`` when the
        underlying C++ object had already gone.

        Args:
            url: The image URL this caller is waiting for.
            on_loaded: ``(url, QPixmap)`` — a BOUND METHOD, not a lambda; a
                lambda has no other referent and would be collected at once.
            on_failed: Optional ``(url, error)``.
        """
        import weakref

        entry = (
            weakref.WeakMethod(on_loaded),
            weakref.WeakMethod(on_failed) if on_failed is not None else None,
        )
        self._subscribers.setdefault(url, []).append(entry)

    def _dispatch(self, url: str, index: int, *args) -> None:
        """Call this url's subscribers, then forget them.

        Args:
            url: The image URL.
            index: 0 for the loaded callback, 1 for the failed one.
            *args: Passed through to each live callback.
        """
        for entry in self._subscribers.pop(url, ()):
            ref = entry[index]
            if ref is None:
                continue
            callback = ref()          # None once the widget has been destroyed
            if callback is not None:
                callback(*args)

    def get_image_sync(self, url: str) -> Optional[QPixmap]:
        """Get image from cache synchronously (no download)
        
        Returns cached image if available, None otherwise.
        Use this for immediate display without blocking.
        """
        if not url:
            return None
        
        # Check in-memory index first
        if url in self.cache_index:
            cache_path = self.cache_index[url]
            if cache_path.exists():
                return QPixmap(str(cache_path))
        
        # Generate cache key from URL
        cache_key = self._url_to_cache_key(url)
        cache_path = self._get_cache_path(url, cache_key)
        
        # Check disk cache
        if cache_path.exists():
            if self._verify_image(cache_path):
                self.cache_index[url] = cache_path
                # Update access time for LRU
                cache_path.touch()
                return QPixmap(str(cache_path))
            else:
                # Corrupted - remove
                logger.warning(f"Corrupted cached image removed: {cache_key}")
                cache_path.unlink()
        
        return None
    
    def get_image_async(self, url: str, provider_urls: Optional[list] = None):
        """Get image from cache or download asynchronously
        
        Emits image_loaded(url, pixmap) on success or image_failed(url, error) on failure.
        
        Args:
            url: Primary image URL
            provider_urls: Optional list of alternative base URLs to try if primary fails
        """
        if not url:
            self.image_failed.emit(url, "Empty URL")
            return
        
        # Try sync first
        pixmap = self.get_image_sync(url)
        if pixmap:
            self.image_loaded.emit(url, pixmap)
            return

        # In-flight dedup: two callers racing for the same url (measured 7ms
        # apart) both miss the sync check above; only the first submits a
        # download. The second's own image_loaded/image_failed connection
        # still fires — both signals are broadcasts keyed by url — when the
        # one in-flight download completes.
        with self._inflight_lock:
            if url in self._inflight:
                logger.debug(f"Already downloading, skipping duplicate: {url}")
                return
            self._inflight.add(url)

        # Download in thread pool with failover support
        self.executor.submit(self._download_and_cache, url, provider_urls)

    def _download_and_cache(self, url: str, provider_urls: Optional[list] = None):
        """Download image and cache it (runs in thread pool)

        Tries multiple provider URLs if provided, similar to stream validation.
        """
        try:
            # Generate cache key from original URL (for consistency)
            cache_key = self._url_to_cache_key(url)
            cache_path = self._get_cache_path(url, cache_key)

            # Worker-start re-check: this job may have sat queued behind a
            # busy pool long enough for another in-flight download of the
            # same url to have already landed the file on disk.
            if cache_path.exists() and self._verify_image(cache_path):
                self.cache_index[url] = cache_path
                self._image_ready.emit(url, str(cache_path))
                return

            urls_to_try = [url]

            # Add reconstructed URLs from provider domains
            if provider_urls:
                original_parsed = urlparse(url)

                for provider_url in provider_urls:
                    provider_parsed = urlparse(provider_url)
                    # Reconstruct with provider domain but keep original path
                    reconstructed = f"{provider_parsed.scheme}://{provider_parsed.netloc}{original_parsed.path}"
                    if reconstructed != url and reconstructed not in urls_to_try:
                        urls_to_try.append(reconstructed)

            last_error = None

            # Try each URL in order
            for attempt_url in urls_to_try:
                host = urlparse(attempt_url).netloc
                if self._cooldown_active(host) or self._cooldown_active(attempt_url):
                    logger.debug(f"cooldown: skipping {attempt_url}")
                    last_error = "cooldown: recently failed"
                    continue  # Try next URL

                try:
                    logger.debug(f"Trying to download image from: {attempt_url}")
                    response = requests.get(attempt_url, timeout=5, stream=True)
                    response.raise_for_status()

                    # Write to disk
                    cache_path.write_bytes(response.content)

                    # Verify it's a valid image
                    if not self._verify_image(cache_path):
                        cache_path.unlink()
                        error_msg = "Invalid image format"
                        logger.warning(f"Downloaded invalid image from {attempt_url}")
                        last_error = error_msg
                        continue  # Try next URL

                    # Update in-memory index
                    self.cache_index[url] = cache_path

                    # Marshal pixmap creation to the main thread via _image_ready signal
                    logger.info(f"Cached image from {attempt_url} (key: {cache_key})")
                    self._image_ready.emit(url, str(cache_path))

                    # Check cache size and cleanup if needed
                    self._cleanup_if_needed()

                    return  # Success!

                except requests.exceptions.HTTPError as e:
                    # The connection is fine; this file is the problem. Cool
                    # down just this url, not the whole host.
                    logger.debug(f"HTTP error downloading from {attempt_url}: {e}")
                    last_error = str(e)
                    self._set_cooldown(attempt_url, _URL_COOLDOWN_S)
                    continue  # Try next URL
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    # A host that won't connect won't connect for any url on
                    # it — cool down the host.
                    logger.debug(f"Failed to connect to {host or attempt_url}: {e}")
                    last_error = str(e)
                    self._set_cooldown(host, _HOST_COOLDOWN_S)
                    continue  # Try next URL
                except requests.RequestException as e:
                    logger.debug(f"Failed to download from {attempt_url}: {e}")
                    last_error = str(e)
                    continue  # Try next URL
                except Exception as e:
                    logger.error(f"Unexpected error downloading from {attempt_url}: {e}")
                    last_error = str(e)
                    continue  # Try next URL

            # All URLs failed
            logger.warning(f"Failed to download image from all {len(urls_to_try)} URLs")
            # Emit only. The subscriber dispatch happens in _on_failed_main, a
            # slot on this object — which lives on the main thread, so Qt queues
            # the emission and the callbacks run there. Calling _dispatch here
            # would run widget code on this worker thread.
            self.image_failed.emit(url, last_error or "All download attempts failed")
        finally:
            with self._inflight_lock:
                self._inflight.discard(url)

    def _cooldown_active(self, key: str) -> bool:
        """True if *key* (a host or a full url) is still within its cooldown.

        An expired entry is dropped here, on the next lookup that consults
        it — nothing else prunes ``_download_cooldowns``.
        """
        if not key:
            return False
        with self._inflight_lock:
            deadline = self._download_cooldowns.get(key)
            if deadline is None:
                return False
            if time.monotonic() >= deadline:
                del self._download_cooldowns[key]
                return False
            return True

    def _set_cooldown(self, key: str, seconds: float) -> None:
        """Put *key* (a host or a full url) on the negative cache for *seconds*."""
        if not key:
            return
        with self._inflight_lock:
            self._download_cooldowns[key] = time.monotonic() + seconds

    def _on_failed_main(self, url: str, error: str) -> None:
        """Main-thread slot: hand a failure to this url's subscribers."""
        self._dispatch(url, 1, url, error)

    def _on_image_ready(self, url: str, cache_path_str: str) -> None:
        """Main-thread slot: create QPixmap, then notify.

        Subscribers first, then the broadcast — the broadcast still fires for
        the one-per-view listeners that use it.
        """
        pixmap = QPixmap(cache_path_str)
        self._dispatch(url, 0, url, pixmap)
        self.image_loaded.emit(url, pixmap)

    def _url_to_cache_key(self, url: str) -> str:
        """Generate cache key from URL using MD5 hash"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def _get_cache_path(self, url: str, cache_key: str) -> Path:
        """Get cache file path with appropriate extension"""
        # Try to detect extension from URL
        url_lower = url.lower()
        if '.png' in url_lower or 'image/png' in url_lower:
            ext = 'png'
        elif '.gif' in url_lower:
            ext = 'gif'
        elif '.webp' in url_lower:
            ext = 'webp'
        else:
            ext = 'jpg'  # Default to jpg
        
        return self.cache_dir / f"{cache_key}.{ext}"
    
    def _verify_image(self, path: Path) -> bool:
        """Quick validation - check file size and magic bytes"""
        try:
            if path.stat().st_size < 100:  # Too small
                return False
            
            # Check magic bytes for common image formats
            magic = path.read_bytes()[:12]
            
            # JPEG: FF D8 FF
            if magic[:3] == b'\xff\xd8\xff':
                return True
            
            # PNG: 89 50 4E 47
            if magic[:4] == b'\x89PNG':
                return True
            
            # GIF: 47 49 46 38
            if magic[:4] in (b'GIF87', b'GIF89'):
                return True
            
            # WebP: 52 49 46 46 ... 57 45 42 50
            if magic[:4] == b'RIFF' and magic[8:12] == b'WEBP':
                return True
            
            return False
        except OSError:
            return False  # silent: unreadable or truncated file is not a valid image
    
    def _cleanup_if_needed(self):
        """LRU cleanup if cache exceeds max size"""
        stats = self.get_cache_stats()
        
        if stats['total_size_mb'] > self.max_size_mb:
            logger.info(f"Cache size {stats['total_size_mb']:.1f}MB exceeds limit "
                       f"{self.max_size_mb}MB, cleaning up...")
            
            # Get all files with access times
            files = list(self.cache_dir.glob("*"))
            files_with_atime = [(f, f.stat().st_atime) for f in files if f.is_file()]
            
            # Sort by access time (oldest first)
            files_with_atime.sort(key=lambda x: x[1])
            
            # Delete oldest 20% of files
            num_to_delete = len(files_with_atime) // 5
            for file_path, _ in files_with_atime[:num_to_delete]:
                try:
                    file_path.unlink()
                    # Remove from in-memory index
                    self.cache_index = {url: path for url, path in self.cache_index.items() 
                                       if path != file_path}
                except Exception as e:
                    logger.warning(f"Failed to delete cache file {file_path}: {e}")
            
            logger.info(f"Deleted {num_to_delete} oldest cache files")
    
    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        if not self.cache_dir.exists():
            return {
                "total_files": 0,
                "total_size": 0,
                "total_size_mb": 0.0,
                "cache_dir": str(self.cache_dir)
            }
        
        files = list(self.cache_dir.glob("*"))
        total_size = sum(f.stat().st_size for f in files if f.is_file())
        
        return {
            "total_files": len(files),
            "total_size": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "cache_dir": str(self.cache_dir),
            "max_size_mb": self.max_size_mb
        }
    
    def clear_cache(self):
        """Clear all cached images"""
        if not self.cache_dir.exists():
            return
        
        count = 0
        for file_path in self.cache_dir.glob("*"):
            if file_path.is_file():
                try:
                    file_path.unlink()
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")
        
        self.cache_index.clear()
        logger.info(f"Cleared {count} cached images")
    
    def shutdown(self):
        """Shutdown the executor"""
        self.executor.shutdown(wait=False)
