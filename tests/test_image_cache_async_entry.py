"""PERF-19b: ``get_image_async`` must never probe disk on the caller's thread.

Owner log, 2026-09-03 02:57: ``discover_card.request_image`` sampled a
3,110 ms stall on the MAIN thread — ``get_image_async`` fell through to
``get_image_sync``, which stats and decodes an on-disk file inline on a
resident-LRU miss.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from metatv.core.image_cache import ImageCache


# A minimal, valid (per _verify_image's magic-byte + size check) PNG file —
# same fixture shape as tests/test_image_cache_dedup.py's _VALID_PNG_BYTES.
# Not a genuinely decodable image, which this test doesn't need: it only
# asserts the image_loaded broadcast and thread identity, never pixel content.
_VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture
def cache(qapp, tmp_path):
    c = ImageCache(cache_dir=str(tmp_path / "cache"))
    yield c
    c.executor.shutdown(wait=True)


def test_get_image_async_does_not_probe_disk_on_caller_thread(cache, qtbot, monkeypatch):
    """THE fix. Pre-fix, ``get_image_async`` called ``get_image_sync`` first,
    which on a resident-LRU miss stats and decodes an on-disk file inline —
    3,110 ms sampled on the main thread (owner log, ``discover_card.
    request_image``). The url here is on disk but deliberately NOT resident,
    which is exactly the case that used to fall through to the sync path.
    """
    url = "http://example.com/perf19b.jpg"
    cache_key = cache._url_to_cache_key(url)
    cache_path = cache._get_cache_path(url, cache_key)
    cache_path.write_bytes(_VALID_PNG_BYTES)  # ON DISK, not resident

    assert cache.get_image_resident(url) is None  # sanity: a genuine miss

    caller_name = threading.current_thread().name
    probed_on: list[str] = []
    original_exists = Path.exists

    def _recording_exists(self, *a, **kw):
        probed_on.append(threading.current_thread().name)
        return original_exists(self, *a, **kw)

    monkeypatch.setattr("metatv.core.image_cache.Path.exists", _recording_exists)

    with qtbot.waitSignal(cache.image_loaded, timeout=5000) as blocker:
        cache.get_image_async(url)  # must return WITHOUT probing disk here

    assert blocker.args[0] == url, "image_loaded fired for the wrong url"

    assert probed_on, "the disk probe never ran at all — this test proves nothing"
    assert caller_name not in probed_on, (
        f"get_image_async probed disk on the caller's thread ({caller_name!r}); "
        f"probes actually ran on: {probed_on}"
    )
