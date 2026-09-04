"""PERF-19b + IMG-1: the async image-cache entry point stops probing disk on
the caller's thread, and a dead image host's cooldown survives a relaunch.

Both bugs came off the SAME owner log (2026-09-03 02:57-03:07):

* ``discover_card.request_image`` sampled a 3,110 ms stall on the MAIN
  thread — ``get_image_async`` fell through to ``get_image_sync``, which
  stats and decodes an on-disk file inline on a resident-LRU miss.
* the same three ``51.158.145.100`` image urls timed out again at 03:07,
  ten minutes after they had just cooled down at 02:57 — the negative cache
  is in-memory only, so every relaunch re-pays a fresh 5s connect timeout
  per dead host per row the restored view shows.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from metatv.core import profile_store
from metatv.core.database import Database
from metatv.core.image_cache import ImageCache


# A minimal, valid (per _verify_image's magic-byte + size check) PNG file —
# same fixture shape as tests/test_image_cache_dedup.py's _VALID_PNG_BYTES.
# Not a genuinely decodable image, which these tests don't need: they only
# assert the image_loaded broadcast, thread identity, and stored deadlines,
# never pixel content.
_VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


class _FakeResponse:
    """Stands in for ``requests.Response`` — only what ``_download_and_cache``
    touches: ``raise_for_status()`` and ``.content``.
    """

    def __init__(self, content: bytes = b"") -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def cache(qapp, tmp_path):
    c = ImageCache(cache_dir=str(tmp_path / "cache"))
    yield c
    c.executor.shutdown(wait=True)


@pytest.fixture
def profile_db(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'profile.db'}")
    db.create_tables()
    return db


# ── PERF-19b: get_image_async never probes disk on the caller's thread ─────

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


# ── IMG-1: dead-host cooldowns persist across a relaunch ───────────────────

def test_a_persisted_host_cooldown_survives_a_relaunch(profile_db, qapp, tmp_path):
    """THE fix. Pre-fix, ``_download_cooldowns`` is purely in-memory, so a
    fresh ``ImageCache`` (a relaunch) always starts with an empty negative
    cache and re-pays a fresh 5s connect timeout for a host the previous run
    already proved dead."""
    profile_store.bind(profile_db)
    try:
        cache_a = ImageCache(cache_dir=str(tmp_path / "a"))
        cache_a._set_cooldown("dead.host", 3600, persist=True)
        profile_store.flush()
        cache_a.executor.shutdown(wait=True)

        cache_b = ImageCache(cache_dir=str(tmp_path / "b"))
        try:
            assert cache_b._cooldown_active("dead.host") is True
        finally:
            cache_b.executor.shutdown(wait=True)
    finally:
        profile_store.unbind()


def test_an_expired_stored_cooldown_is_not_loaded(profile_db, qapp, tmp_path):
    """A relaunch must not resurrect a cooldown that has already lapsed."""
    profile_store.bind(profile_db)
    try:
        profile_store.record({"image_host_cooldowns": {"old.host": time.time() - 100}})
        profile_store.flush()

        cache = ImageCache(cache_dir=str(tmp_path / "c"))
        try:
            assert cache._cooldown_active("old.host") is False
            assert "old.host" not in cache._download_cooldowns
        finally:
            cache.executor.shutdown(wait=True)
    finally:
        profile_store.unbind()


def test_a_url_level_cooldown_is_not_persisted(profile_db, qapp, tmp_path):
    """A single 404'd file is not worth remembering past this process — only
    HOST cooldowns (``persist=True``) are ever written to the profile store."""
    profile_store.bind(profile_db)
    try:
        cache_a = ImageCache(cache_dir=str(tmp_path / "a"))
        cache_a._set_cooldown("http://example.com/broken.jpg", 3600)  # persist=False (default)
        profile_store.flush()
        cache_a.executor.shutdown(wait=True)

        cache_b = ImageCache(cache_dir=str(tmp_path / "b"))
        try:
            assert cache_b._cooldown_active("http://example.com/broken.jpg") is False
        finally:
            cache_b.executor.shutdown(wait=True)
    finally:
        profile_store.unbind()


def test_download_uses_a_short_connect_long_read_timeout(cache, monkeypatch):
    """The connect half is what a dead host burns — cut from 5s to just over
    the usual TCP handshake ceiling; the read half keeps more slack."""
    captured: dict = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(content=_VALID_PNG_BYTES)

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    # Driven directly (no executor): a plain method, worker-free path.
    cache._download_and_cache("http://example.com/timeout-check.jpg")

    assert captured.get("timeout") == (3.05, 10)
