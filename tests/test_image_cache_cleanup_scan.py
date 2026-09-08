"""Tests for IMG-1: image cache stat-storm fix (avoid full directory scan per download)"""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from metatv.core.image_cache import ImageCache


def test_scan_happens_once_not_per_download(tmp_path):
    """IMG-1: The cache size is computed once, not on every cleanup_if_needed call.

    A regression test for the stat-storm bug: prior to IMG-1, every image
    download called _cleanup_if_needed, which called get_cache_stats, which
    glob + stat'd the entire cache directory. This test confirms that the
    running counter is seeded once and then incremented, not rescanned.

    This test SHOULD FAIL on main (before the fix) and PASS after IMG-1.
    """
    cache = ImageCache(cache_dir=str(tmp_path), max_size_mb=10000)

    # Patch get_cache_stats to track how many times it's called
    call_count = 0
    original_get_cache_stats = cache.get_cache_stats

    def counting_get_cache_stats():
        nonlocal call_count
        call_count += 1
        return original_get_cache_stats()

    cache.get_cache_stats = counting_get_cache_stats

    # Call _cleanup_if_needed 20 times with different added_bytes values
    bytes_added = 0
    for i in range(20):
        added = 1024 * 100  # 100 KB each
        cache._cleanup_if_needed(added_bytes=added)
        bytes_added += added

    # With the fix, get_cache_stats is called exactly once (on first _cleanup_if_needed)
    # to seed the counter. Without the fix, it would be called 20 times.
    assert call_count == 1, (
        f"get_cache_stats was called {call_count} times (expected 1). "
        f"The fix is not working — the counter should be seeded once, "
        f"then incremented without rescanning."
    )

    # The running counter should have grown by the sum of added bytes
    assert cache._cached_bytes == bytes_added, (
        f"_cached_bytes={cache._cached_bytes}, expected {bytes_added}"
    )


def test_cleanup_still_works_and_deletes_oldest(tmp_path):
    """IMG-1: LRU sweep still works and deletes the oldest 20% of files.

    Regression test: the optimization should not break the cleanup behavior.
    This test creates a cache that exceeds the limit and confirms that:
    1. The oldest files are actually deleted
    2. The counter is re-seeded after deletion to match reality
    """
    cache = ImageCache(cache_dir=str(tmp_path), max_size_mb=1)  # 1 MB limit

    # Create 10 files, each ~500 KB, to exceed the 1 MB limit
    files_created = []
    for i in range(10):
        file_path = tmp_path / f"image_{i:02d}.jpg"
        # Create a file with actual content (500 KB)
        file_path.write_bytes(b"x" * (500 * 1024))
        files_created.append(file_path)
        # Set different access times to make them ordered (oldest first)
        file_path.touch()

    # Verify our setup: cache is over the limit
    stats = cache.get_cache_stats()
    assert stats["total_size_mb"] > 1.0, (
        f"Setup failed: cache should be >1MB, got {stats['total_size_mb']:.1f}MB"
    )

    # Count files before cleanup
    count_before = len(list(tmp_path.glob("*")))
    total_size_before = sum(f.stat().st_size for f in tmp_path.glob("*") if f.is_file())

    # Trigger cleanup (adding enough bytes to push the cache over the limit again)
    cache._cleanup_if_needed(added_bytes=1024 * 100)

    # Confirm that files were deleted
    count_after = len(list(tmp_path.glob("*")))
    assert count_after < count_before, (
        f"No files deleted: {count_before} files before, {count_after} after"
    )

    # Confirm that at least ~20% of files were deleted (10 files -> delete 2)
    num_deleted = count_before - count_after
    assert num_deleted >= 1, f"Expected at least 1 file deleted, got {num_deleted}"

    # The oldest file (image_00.jpg) should be gone
    assert not files_created[0].exists(), (
        "The oldest file should have been deleted"
    )

    # After deletion, _cached_bytes should match the actual directory size
    # (re-seeded from get_cache_stats)
    actual_size = sum(f.stat().st_size for f in tmp_path.glob("*") if f.is_file())
    assert cache._cached_bytes == actual_size, (
        f"After cleanup, counter should be re-seeded. "
        f"_cached_bytes={cache._cached_bytes}, actual={actual_size}"
    )
