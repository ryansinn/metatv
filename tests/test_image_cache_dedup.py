"""Three measured duplicate-work bugs in the image cache, all from the same
runtime log (owner, 2026-09-02 13:21):

1. Two ``get_image_async`` calls for the same url 7ms apart both missed the
   disk check and both submitted downloads — the same cache key got written
   twice, simultaneously.
2. A duplicate request that sat queued behind a busy pool (workers occupied
   by a dead host's 5s timeouts) ran 8 seconds later and re-downloaded a
   file that had already landed on disk 7 seconds earlier.
3. A dead image host ate three 5-second connect-timeouts at every launch and
   was re-attempted within the same minute — no negative cache, so the pool
   kept re-learning the same fact and built the queue backlog behind bug 2.

No real network anywhere: ``requests.get`` is monkeypatched in the module
that imports it (``metatv.core.image_cache.requests.get``).
"""

import threading

import pytest
import requests
from PyQt6.QtGui import QPixmap

from metatv.core.image_cache import ImageCache, _HOST_COOLDOWN_S, _RESIDENT_CAP


# A minimal, valid (per _verify_image's magic-byte + size check) PNG file:
# the 8-byte PNG signature padded past the 100-byte size floor.
_VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


class _FakeResponse:
    """Stands in for ``requests.Response`` — only what ``_download_and_cache``
    touches: ``raise_for_status()`` and ``.content``.
    """

    def __init__(self, content: bytes = b"", status_ok: bool = True) -> None:
        self.content = content
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise requests.exceptions.HTTPError("404 Client Error: Not Found")


@pytest.fixture
def cache(qapp, tmp_path):
    c = ImageCache(cache_dir=str(tmp_path))
    yield c
    c.executor.shutdown(wait=True)


# ── bug 1: in-flight dedup ──────────────────────────────────────────────────

def test_concurrent_requests_download_once(cache, qtbot, monkeypatch) -> None:
    """THE fix for bug 1. Pre-fix, two async calls for the same url both
    missed the sync check and both submitted a download."""
    call_count = 0
    count_lock = threading.Lock()
    release = threading.Event()

    def fake_get(url, timeout=5, stream=True):
        nonlocal call_count
        with count_lock:
            call_count += 1
        release.wait(timeout=5)
        return _FakeResponse(content=_VALID_PNG_BYTES)

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    url = "http://example.com/poster.jpg"

    with qtbot.waitSignal(cache._image_ready, timeout=5000):
        cache.get_image_async(url)
        cache.get_image_async(url)  # the 7ms-apart duplicate from the log
        release.set()

    assert call_count == 1, "the duplicate request downloaded the same url again"


# ── bug 2: worker-start disk re-check ───────────────────────────────────────

def test_queued_job_skips_download_when_file_already_cached(cache, monkeypatch) -> None:
    """THE fix for bug 2. A job that runs after the file already landed on
    disk (e.g. it sat queued behind a busy pool) must not re-download."""
    url = "http://example.com/poster2.jpg"
    cache_key = cache._url_to_cache_key(url)
    cache_path = cache._get_cache_path(url, cache_key)
    cache_path.write_bytes(_VALID_PNG_BYTES)

    def fake_get(*args, **kwargs):
        raise AssertionError("network was hit despite the file already being cached")

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    received = []
    cache._image_ready.connect(lambda u, p: received.append((u, p)))

    cache._download_and_cache(url)

    assert received == [(url, str(cache_path))]


# ── bug 3: negative cache ───────────────────────────────────────────────────

def test_connect_failure_puts_the_host_on_cooldown(cache, monkeypatch) -> None:
    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    url1 = "http://51.158.145.100/a.jpg"
    url2 = "http://51.158.145.100/b.jpg"  # same host, different file

    cache._download_and_cache(url1)
    assert call_count == 1

    cache._download_and_cache(url2)
    assert call_count == 1, "a different url on a cooled-down host was still attempted"


def test_http_404_cools_only_that_url(cache, monkeypatch) -> None:
    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _FakeResponse(status_ok=False)

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    url1 = "http://cdn.example.com/missing.jpg"
    url2 = "http://cdn.example.com/other.jpg"  # same host, different file

    cache._download_and_cache(url1)
    assert call_count == 1

    cache._download_and_cache(url1)
    assert call_count == 1, "the same 404'd url was retried within its cooldown"

    cache._download_and_cache(url2)
    assert call_count == 2, "a different url on the same host was wrongly cooled down too"


def test_cooldown_expires(cache, monkeypatch) -> None:
    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    fake_now = [1_000.0]
    monkeypatch.setattr("metatv.core.image_cache.time.monotonic", lambda: fake_now[0])

    url = "http://51.158.145.100/a.jpg"

    cache._download_and_cache(url)
    assert call_count == 1

    fake_now[0] += _HOST_COOLDOWN_S + 1  # step past the deadline
    cache._download_and_cache(url)
    assert call_count == 2, "the host was still on cooldown after its window expired"


# ── PERF-19: resident pixmap cache — paint() may only ever consult memory ──
#
# The owner's live run sampled ``ChannelListDelegate._paint_thumbnail`` at a
# 567ms stall (worst 2,705ms across 8 stalls in one launch), because
# ``get_image_sync`` did a disk read + JPEG decode ON THE MAIN THREAD from
# inside ``paint()``. ``get_image_resident`` is the fix: a bounded in-memory
# LRU that paint code may call, backed by NO disk access at all.

def _make_real_png_bytes() -> bytes:
    """A genuinely decodable PNG — unlike ``_VALID_PNG_BYTES`` above (which
    only satisfies ``_verify_image``'s magic-byte + size check), this one
    must survive an actual ``QPixmap`` decode: ``ensure_resident`` stores
    nothing when the decode comes back null (``_store_resident`` guards on
    ``isNull()``), so a fake-but-"valid" file would silently fail this test's
    real assertion instead of proving the resident path."""
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QImage
    import random

    image = QImage(16, 16, QImage.Format.Format_RGB32)
    rng = random.Random(0)
    for y in range(16):
        for x in range(16):
            image.setPixel(x, y, rng.randrange(1 << 24))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def test_get_image_resident_never_touches_disk(cache, monkeypatch) -> None:
    """A resident-cache miss must not touch disk at all — ``Path.exists`` is
    monkeypatched to explode if paint's own accessor ever reaches it."""

    def _boom(self):
        raise AssertionError("get_image_resident touched disk")

    monkeypatch.setattr("metatv.core.image_cache.Path.exists", _boom)

    url = "http://example.com/resident.jpg"
    assert cache.get_image_resident(url) is None  # miss: no raise, no disk

    pixmap = QPixmap(4, 4)
    cache._store_resident(url, pixmap)
    assert cache.get_image_resident(url) is pixmap  # hit: still no disk


def test_resident_lru_evicts_oldest_over_cap(cache) -> None:
    """Storing more than ``_RESIDENT_CAP`` entries keeps exactly the cap and
    evicts the OLDEST first — an unbounded dict here would leak forever on a
    long scroll through a 785k-row library."""
    urls = [f"http://example.com/{i}.jpg" for i in range(_RESIDENT_CAP + 5)]
    for url in urls:
        cache._store_resident(url, QPixmap(2, 2))

    assert len(cache._resident) == _RESIDENT_CAP
    for stale in urls[:5]:
        assert cache.get_image_resident(stale) is None, f"{stale} should have been evicted"
    for fresh in urls[-5:]:
        assert cache.get_image_resident(fresh) is not None, f"{fresh} should still be resident"


def test_ensure_resident_promotes_an_on_disk_hit(cache, qtbot) -> None:
    """A url already cached on disk (but not yet resident) becomes resident
    via ``ensure_resident`` — background work, main-thread pixmap decode,
    ``image_loaded`` broadcast, exactly the private-signal chokepoint the
    download path already uses."""
    url = "http://example.com/disk-cached.jpg"
    cache_key = cache._url_to_cache_key(url)
    cache_path = cache._get_cache_path(url, cache_key)
    cache_path.write_bytes(_make_real_png_bytes())

    assert cache.get_image_resident(url) is None  # not resident yet

    with qtbot.waitSignal(cache.image_loaded, timeout=5000):
        cache.ensure_resident(url)

    assert cache.get_image_resident(url) is not None


def test_ensure_resident_dedupes_against_inflight(cache, monkeypatch) -> None:
    """A second ``ensure_resident`` call for a url already in flight submits
    nothing extra — the same ``_inflight`` set ``get_image_async`` uses."""
    url = "http://example.com/inflight.jpg"
    submitted = []

    def _recording_submit(fn, *args, **kwargs):
        submitted.append((fn, args))
        # Don't run it — the point is to observe whether a SECOND call
        # submits again while the first is still (nominally) in flight.
        return None

    monkeypatch.setattr(cache.executor, "submit", _recording_submit)

    cache.ensure_resident(url)
    cache.ensure_resident(url)

    assert len(submitted) == 1, "a second ensure_resident for an in-flight url resubmitted work"
