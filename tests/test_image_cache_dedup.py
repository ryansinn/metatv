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

from metatv.core.image_cache import ImageCache, _HOST_COOLDOWN_S


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
