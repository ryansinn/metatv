"""Image caching system - Phase 1: URL-based caching (MVP)"""
import hashlib
from pathlib import Path
from typing import Optional, Dict
import asyncio
from concurrent.futures import ThreadPoolExecutor

import requests
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QObject, pyqtSignal

from loguru import logger


class ImageCache(QObject):
    """Cache poster/backdrop images locally - Phase 1 MVP
    
    Strategy: Hash URL to create cache key. Same URL = same cached file.
    Benefits: ~90% reduction in storage, handles TMDb poster reuse across variants
    Cache size: ~300MB for ~30k unique images
    """
    
    # Signals for async operations
    image_loaded = pyqtSignal(str, QPixmap)  # url, pixmap
    image_failed = pyqtSignal(str, str)  # url, error_message
    
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
        
        logger.info(f"Image cache initialized: {self.cache_dir}")
    
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
        
        # Download in thread pool with failover support
        self.executor.submit(self._download_and_cache, url, provider_urls)
    
    def _download_and_cache(self, url: str, provider_urls: Optional[list] = None):
        """Download image and cache it (runs in thread pool)
        
        Tries multiple provider URLs if provided, similar to stream validation.
        """
        urls_to_try = [url]
        
        # Add reconstructed URLs from provider domains
        if provider_urls:
            from urllib.parse import urlparse
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
            try:
                logger.debug(f"Trying to download image from: {attempt_url}")
                response = requests.get(attempt_url, timeout=5, stream=True)
                response.raise_for_status()
                
                # Generate cache key from original URL (for consistency)
                cache_key = self._url_to_cache_key(url)
                cache_path = self._get_cache_path(url, cache_key)
                
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
                
                # Load and emit
                pixmap = QPixmap(str(cache_path))
                logger.info(f"Cached image from {attempt_url} (key: {cache_key})")
                self.image_loaded.emit(url, pixmap)
                
                # Check cache size and cleanup if needed
                self._cleanup_if_needed()
                
                return  # Success!
                
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
        self.image_failed.emit(url, last_error or "All download attempts failed")
    
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
        except Exception:
            return False
    
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
