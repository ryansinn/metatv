"""Image caching system - Phase 1: URL-based caching (MVP)"""
import hashlib
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Dict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QObject, pyqtSignal

from loguru import logger

from metatv.core import profile_store


# Negative-cache windows. Keyed at two grains because the two failure modes
# mean different things: a host that won't connect won't connect for ANY url
# on it, but an HTTP error status is about that one file, not the host.
#
# IMG-1: host cooldowns are persisted across relaunches (see __init__ and
# _set_cooldown's persist=True path) — a host that will not connect is dead
# for the evening, and a 10-minute in-memory-only window re-paid a fresh 5s
# connect timeout per dead-host image on every relaunch (owner log: the same
# three 51.158.145.100 urls timed out again 10 minutes after they had just
# cooled down). Url cooldowns are NOT persisted — a 404 is about one file,
# not worth remembering past this process, and persisting every broken
# poster url ever seen would grow unboundedly.
_HOST_COOLDOWN_S = 3 * 3600  # 3 hours: connect-timeout / connection error
_URL_COOLDOWN_S = 3600        # HTTP error status (e.g. 404): skip just that url

# Bounded in-memory pixmap LRU (PERF-19): paint() may only ever consult this —
# never disk. QPixmap construction and this dict are MAIN-THREAD-ONLY; see
# ``_store_resident``. 512 pixmaps at a poster-thumbnail size is a few MB, well
# inside the app's existing footprint, and comfortably covers a screen's worth
# of rows plus recent scroll history.
_RESIDENT_CAP = 512


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

        # Bounded pixmap LRU — the ONLY thing paint() may read
        # (get_image_resident). Written only from the main thread: QPixmap is
        # a GUI object, so never touch this from a worker.
        self._resident: "OrderedDict[str, QPixmap]" = OrderedDict()

        # Thread pool for async downloads
        self.executor = ThreadPoolExecutor(max_workers=4)

        # In-flight dedup: a url already being downloaded is never
        # resubmitted. The requester's own image_loaded/image_failed
        # connection still fires when the one in-flight download completes —
        # both signals are broadcast per-url.
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()

        # Negative cache: host or full url -> cooldown deadline. Wall-clock
        # (time.time()), not time.monotonic() — a cooldown is not precision
        # timing, a clock jump only shortens or lengthens a skip, and a wall
        # deadline is what IMG-1 can persist and compare against on the next
        # launch. Guarded by the same lock as _inflight.
        self._download_cooldowns: Dict[str, float] = {}

        # IMG-1: seed HOST cooldowns a previous run persisted (see
        # _set_cooldown's persist=True path), expired entries dropped. Url
        # entries are never persisted, so there is nothing to seed for them.
        # profile_store is bound before ImageCache is constructed (see
        # MainWindow.__init__: config.attach_profile_store(self.db) then
        # ImageCache(...)) — unbound (a bare ImageCache() in a test or
        # headless script), this is simply a no-op: the old always-fresh
        # behaviour, unchanged.
        if profile_store.is_bound():
            now = time.time()
            stored = profile_store.read_all().get("image_host_cooldowns") or {}
            self._download_cooldowns.update(
                {host: deadline for host, deadline in stored.items() if deadline > now}
            )

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

    def _store_resident(self, url: str, pixmap: QPixmap) -> None:
        """Insert/refresh *url* in the in-memory pixmap LRU, evicting the
        oldest entry while over ``_RESIDENT_CAP``.

        MAIN-THREAD-ONLY: QPixmap is a GUI object and this dict backs
        ``get_image_resident`` (paint's only accessor) — never call this from
        a worker thread. The one worker-fed writer is ``_on_image_ready``,
        which already marshals onto the main thread before touching QPixmap.
        """
        if pixmap is None or pixmap.isNull():
            return
        self._resident[url] = pixmap
        self._resident.move_to_end(url)
        while len(self._resident) > _RESIDENT_CAP:
            self._resident.popitem(last=False)

    def get_image_resident(self, url: str) -> Optional[QPixmap]:
        """Memory-only lookup — the ONLY image accessor paint code may call.

        Touches NO disk and never blocks: a hit returns the resident pixmap
        (and marks it most-recently-used), a miss returns ``None``. Call
        ``ensure_resident()`` on a miss to queue background hydration.
        """
        if not url:
            return None
        pixmap = self._resident.get(url)
        if pixmap is None:
            return None
        self._resident.move_to_end(url)
        return pixmap

    def get_image_sync(self, url: str) -> Optional[QPixmap]:
        """Get image from cache synchronously (no download)

        Returns cached image if available, None otherwise. Checks the
        resident pixmap LRU first (free); a miss there still falls through to
        disk, so this call CAN block on I/O — safe for callers off the paint
        path, never from paint() itself (use ``get_image_resident`` there).
        """
        if not url:
            return None

        resident = self.get_image_resident(url)
        if resident is not None:
            return resident

        # Check in-memory index first
        if url in self.cache_index:
            cache_path = self.cache_index[url]
            if cache_path.exists():
                pixmap = QPixmap(str(cache_path))
                self._store_resident(url, pixmap)
                return pixmap

        # Generate cache key from URL
        cache_key = self._url_to_cache_key(url)
        cache_path = self._get_cache_path(url, cache_key)

        # Check disk cache
        if cache_path.exists():
            if self._verify_image(cache_path):
                self.cache_index[url] = cache_path
                # Update access time for LRU
                cache_path.touch()
                pixmap = QPixmap(str(cache_path))
                self._store_resident(url, pixmap)
                return pixmap
            else:
                # Corrupted - remove
                logger.warning(f"Corrupted cached image removed: {cache_key}")
                cache_path.unlink()

        return None

    def ensure_resident(self, url: str, provider_urls: Optional[list] = None) -> None:
        """Queue background work so *url* becomes resident; never touches
        disk or the network on the CALLER's thread.

        Call this from paint-adjacent code on a ``get_image_resident`` miss
        instead of doing any IO there. Deduped through the same ``_inflight``
        set ``get_image_async`` uses, so a url already downloading — or
        already queued by a concurrent ``ensure_resident``/``get_image_async``
        call — is never resubmitted; its eventual ``image_loaded`` still
        broadcasts to every caller, this one included via the coalesced
        viewport repaint the channel list wires up.

        The worker is ``_download_and_cache`` itself: its own worker-start
        re-check already does exactly "on-disk hit -> emit the private
        signal, else download" (see its docstring) — the same fallback this
        method's docstring promises — so there is nothing new to write.

        Args:
            url: The image URL to make resident.
            provider_urls: Optional alternate provider hosts, forwarded to
                ``_download_and_cache`` on a disk miss.
        """
        if not url or self.get_image_resident(url) is not None:
            return

        with self._inflight_lock:
            if url in self._inflight:
                return
            self._inflight.add(url)

        self.executor.submit(self._download_and_cache, url, provider_urls)

    def get_image_async(self, url: str, provider_urls: Optional[list] = None):
        """Get image from cache or download it — never touches disk on the
        caller's thread.

        Emits image_loaded(url, pixmap) on success or image_failed(url, error) on failure.

        A resident-LRU hit is served synchronously (memory only, no I/O).
        Anything else — including an on-disk-but-not-resident hit — is handed
        to ``ensure_resident``, whose worker-start re-check already does the
        stat/decode off the caller's thread (PERF-19b: ``discover_card.
        request_image`` sampled a 3,110 ms main-thread stall from the old
        ``get_image_sync`` fallback here).

        Args:
            url: Primary image URL
            provider_urls: Optional list of alternative base URLs to try if primary fails
        """
        if not url:
            self.image_failed.emit(url, "Empty URL")
            return

        pixmap = self.get_image_resident(url)
        if pixmap is not None:
            self.image_loaded.emit(url, pixmap)
            return

        self.ensure_resident(url, provider_urls)

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
                    # (connect, read): the connect half is what a dead host
                    # burns — that is the half IMG-1's cooldown exists to
                    # avoid re-paying, so it is cut from 5s to just over the
                    # usual 3s TCP handshake ceiling; read gets more slack
                    # since a slow-but-alive host still gets its content.
                    response = requests.get(attempt_url, timeout=(3.05, 10), stream=True)
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
                    self._set_cooldown(host, _HOST_COOLDOWN_S, persist=True)
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
            if time.time() >= deadline:
                del self._download_cooldowns[key]
                return False
            return True

    def _set_cooldown(self, key: str, seconds: float, *, persist: bool = False) -> None:
        """Put *key* (a host or a full url) on the negative cache for *seconds*.

        Args:
            key: A host (bare netloc) or a full url.
            seconds: Cooldown length.
            persist: True only for a HOST cooldown (IMG-1) — a dead host is
                worth remembering across a relaunch, a single 404'd url is
                not. The snapshot is built under ``_inflight_lock`` (so it
                can't race a concurrent ``_set_cooldown``/prune) but the
                actual write is queued through ``profile_store.record``
                OUTSIDE the lock, so a slow/blocked writer thread never
                holds up a download worker.
        """
        if not key:
            return
        with self._inflight_lock:
            self._download_cooldowns[key] = time.time() + seconds
            snapshot = self._host_cooldowns_snapshot_locked() if persist else None
        if snapshot is not None:
            profile_store.record({"image_host_cooldowns": snapshot})

    def _host_cooldowns_snapshot_locked(self) -> Dict[str, float]:
        """Wall-clock deadlines for HOST-only cooldown entries, expired ones
        pruned. Caller must hold ``_inflight_lock``.

        A host key is a bare netloc (``urlparse(url).netloc``, e.g.
        ``"51.158.145.100"``); a url key is always a full url and so always
        contains ``"://"`` — that is what tells the two grains sharing
        ``_download_cooldowns`` apart, since (per this module's design) only
        one dict is kept rather than splitting host/url storage.
        """
        now = time.time()
        return {
            key: deadline
            for key, deadline in self._download_cooldowns.items()
            if "://" not in key and deadline > now
        }

    def _on_failed_main(self, url: str, error: str) -> None:
        """Main-thread slot: hand a failure to this url's subscribers."""
        self._dispatch(url, 1, url, error)

    def _on_image_ready(self, url: str, cache_path_str: str) -> None:
        """Main-thread slot: create QPixmap, make it resident, then notify.

        The only worker-fed writer of ``_resident`` — safe because this slot
        runs on the main thread (the worker only ever emits the path string).
        Subscribers first, then the broadcast — the broadcast still fires for
        the one-per-view listeners that use it.
        """
        pixmap = QPixmap(cache_path_str)
        self._store_resident(url, pixmap)
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
