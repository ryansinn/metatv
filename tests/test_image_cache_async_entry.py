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
from typing import Callable, NamedTuple

import pytest
import requests
from PyQt6.QtGui import QPixmap

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
    touches: ``raise_for_status()`` and ``.content``. Same shape as the sibling
    copy in ``test_image_cache_dedup.py`` (status_ok added here so this file's
    IMG-4 contract test can also drive the failure branch).
    """

    def __init__(self, content: bytes = b"", status_ok: bool = True) -> None:
        self.content = content
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise requests.exceptions.HTTPError("404 Client Error: Not Found")


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
    """The connect half is what a dead host burns — cut from the original 5s.
    IMG-2 widened it again, from 3.05s to 6.05s, after a single marginal
    connect to a live CDN (image.tmdb.org) was mistaken for a dead host; the
    read half keeps its own, larger slack."""
    captured: dict = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(content=_VALID_PNG_BYTES)

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    # Driven directly (no executor): a plain method, worker-free path.
    cache._download_and_cache("http://example.com/timeout-check.jpg")

    assert captured.get("timeout") == (6.05, 10)


# ── IMG-3: a resident-cache hit must notify subscribe() callers too ────────
#
# Moved here from tests/test_image_cache_resident_notifies_subscribers.py
# (IMG-4): that file's own docstring said it tests "the async image-cache
# entry point" — this file's docstring, verbatim — so it belongs here, not
# in a file of its own. Assertions and docstrings preserved verbatim; only
# their home changed.

class _Subscriber:
    """A subscribe() caller. Must be a BOUND METHOD holder — subscribe keeps
    a WeakMethod, so a lambda would be collected immediately."""

    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.failed: list[str] = []

    def on_loaded(self, url: str, pixmap) -> None:
        self.loaded.append(url)

    def on_failed(self, url: str, error: str) -> None:
        self.failed.append(error)


def _resident_cache(tmp_path, url: str) -> ImageCache:
    """An ImageCache whose resident LRU already holds a real pixmap for *url*."""
    cache = ImageCache(cache_dir=str(tmp_path))
    pixmap = QPixmap(4, 4)
    pixmap.fill()
    cache._store_resident(url, pixmap)
    assert cache.get_image_resident(url) is not None, "precondition: url is resident"
    return cache


def test_resident_hit_notifies_the_subscriber(tmp_path, qapp):
    """The bug: a resident hit served only the broadcast, so a subscribed card
    was never told and stayed on its placeholder."""
    url = "https://image.tmdb.org/t/p/w154/poster.jpg"
    cache = _resident_cache(tmp_path, url)

    sub = _Subscriber()
    cache.subscribe(url, sub.on_loaded, sub.on_failed)
    cache.get_image_async(url)

    assert sub.loaded == [url], (
        "a resident-cache hit must reach subscribe() callers — a Discover card "
        "uses subscribe(), not the image_loaded broadcast"
    )
    assert sub.failed == [], "a resident hit is a success, never a failure"


def test_resident_hit_still_broadcasts(tmp_path, qapp):
    """The one-per-view listeners (details pane, lightbox, trail map) use the
    broadcast — fixing the subscriber path must not cost them their signal."""
    url = "https://image.tmdb.org/t/p/w154/poster.jpg"
    cache = _resident_cache(tmp_path, url)

    seen: list[str] = []
    cache.image_loaded.connect(lambda u, p: seen.append(u))
    cache.get_image_async(url)

    assert seen == [url], "the image_loaded broadcast must still fire on a resident hit"


def test_resident_hit_forgets_the_subscription(tmp_path, qapp):
    """Subscriptions are one-shot (``_dispatch`` pops them). A second request
    must not re-notify a subscriber that has already been served."""
    url = "https://image.tmdb.org/t/p/w154/poster.jpg"
    cache = _resident_cache(tmp_path, url)

    sub = _Subscriber()
    cache.subscribe(url, sub.on_loaded, sub.on_failed)
    cache.get_image_async(url)
    cache.get_image_async(url)

    assert sub.loaded == [url], "the subscription is one-shot; it must not fire twice"


# ── IMG-4: the delivery-SEAM contract, parameterized over every route ──────
#
# Three bugs in one week shared a shape: a new delivery route was added
# beside an old one and only SOME consumers were wired into it. IMG-3 fixed
# exactly one hole (the resident-LRU fast path was broadcast-only, so a
# subscribe() caller — every Discover card — was never told). Per-path tests
# could not see that hole, because no single test asked the question at the
# SEAM: for every route an image request can resolve through, do BOTH
# delivery channels fire?
#
# This is that seam test. A future route is added as a row in _ROUTES (or,
# if its shape doesn't fit the single-subscriber/single-trigger table below,
# as a sibling test near the two below it) — never as a new copy of this
# file.

class _Route(NamedTuple):
    """One way an image request can resolve.

    Attributes:
        id: Parametrize id — also used to build a unique per-route url.
        url: The url to request. Only the "empty_url" route overrides this
            (to the empty string) rather than deriving it from ``id``.
        setup: Arranges cache/monkeypatch state so ``trigger`` resolves this
            route.
        trigger: Calls the entry point under test.
        expected: "loaded" or "failed" — which subscriber callback and which
            broadcast signal must fire.
    """

    id: str
    url: str
    setup: Callable[[ImageCache, str, "pytest.MonkeyPatch"], None]
    trigger: Callable[[ImageCache, str], None]
    expected: str


def _route_setup_resident_hit(cache: ImageCache, url: str, monkeypatch) -> None:
    """1. Pixmap already in the resident LRU."""
    pixmap = QPixmap(4, 4)
    pixmap.fill()
    cache._store_resident(url, pixmap)


def _route_setup_disk_hit(cache: ImageCache, url: str, monkeypatch) -> None:
    """2. File already in the cache dir, not resident — the worker-start
    re-check inside ``_download_and_cache`` (see ``ensure_resident``)."""
    cache_key = cache._url_to_cache_key(url)
    cache_path = cache._get_cache_path(url, cache_key)
    cache_path.write_bytes(_VALID_PNG_BYTES)

    def _no_network(*a, **k):
        raise AssertionError("a disk hit must never reach the network")

    monkeypatch.setattr("metatv.core.image_cache.requests.get", _no_network)


def _route_setup_fresh_download(cache: ImageCache, url: str, monkeypatch) -> None:
    """3. Not resident, not on disk — a (mocked) download succeeds."""
    monkeypatch.setattr(
        "metatv.core.image_cache.requests.get",
        lambda *a, **k: _FakeResponse(content=_VALID_PNG_BYTES),
    )


def _route_setup_download_failure(cache: ImageCache, url: str, monkeypatch) -> None:
    """4. Every candidate url fails (a single candidate here: no provider_urls)."""
    monkeypatch.setattr(
        "metatv.core.image_cache.requests.get",
        lambda *a, **k: _FakeResponse(status_ok=False),
    )


def _route_setup_cooldown_skip(cache: ImageCache, url: str, monkeypatch) -> None:
    """5. The url is already in cooldown, so no candidate is even tried —
    the "cooldown: no candidate tried" path."""
    cache._set_cooldown(url, 3600)

    def _no_network(*a, **k):
        raise AssertionError("a cooled-down url must never reach the network")

    monkeypatch.setattr("metatv.core.image_cache.requests.get", _no_network)


def _route_setup_noop(cache: ImageCache, url: str, monkeypatch) -> None:
    """6. Empty url — nothing to arrange; ``get_image_async`` fails before
    touching any cache state."""


def _trigger_get_image_async(cache: ImageCache, url: str) -> None:
    cache.get_image_async(url)


_ROUTES = [
    _Route("resident_hit", "http://example.com/route-resident-hit.jpg",
           _route_setup_resident_hit, _trigger_get_image_async, "loaded"),
    _Route("disk_hit", "http://example.com/route-disk-hit.jpg",
           _route_setup_disk_hit, _trigger_get_image_async, "loaded"),
    _Route("fresh_download", "http://example.com/route-fresh-download.jpg",
           _route_setup_fresh_download, _trigger_get_image_async, "loaded"),
    _Route("download_failure", "http://example.com/route-download-failure.jpg",
           _route_setup_download_failure, _trigger_get_image_async, "failed"),
    _Route("cooldown_skip", "http://example.com/route-cooldown-skip.jpg",
           _route_setup_cooldown_skip, _trigger_get_image_async, "failed"),
    _Route("empty_url", "", _route_setup_noop, _trigger_get_image_async, "failed"),
]


@pytest.mark.parametrize("route", _ROUTES, ids=[r.id for r in _ROUTES])
def test_every_delivery_route_notifies_subscriber_and_broadcast(
    route: _Route, cache: ImageCache, monkeypatch, qtbot
) -> None:
    """THE contract. For every route an image request can resolve through,
    BOTH the per-url subscribe() callback and the corresponding broadcast
    signal must fire — and a subscription is one-shot.

    In-flight dedup (route 7) and a direct ``ensure_resident`` call (route 8)
    don't fit this single-subscriber/single-trigger table and are covered
    right below by ``test_inflight_dedup_notifies_every_waiting_subscriber``
    and ``test_ensure_resident_direct_call_notifies_subscriber``.
    """
    route.setup(cache, route.url, monkeypatch)

    sub = _Subscriber()
    cache.subscribe(route.url, sub.on_loaded, sub.on_failed)

    target_signal = cache.image_loaded if route.expected == "loaded" else cache.image_failed
    with qtbot.waitSignal(target_signal, timeout=5000) as blocker:
        route.trigger(cache, route.url)

    assert blocker.args[0] == route.url, f"{route.id}: broadcast fired for the wrong url"

    if route.expected == "loaded":
        assert sub.loaded == [route.url], f"{route.id}: subscribe() caller was never notified"
        assert sub.failed == []
    else:
        assert sub.failed, f"{route.id}: subscribe() caller was never notified of the failure"
        assert sub.loaded == []

    # One-shot: a second request for the same url must not re-notify a
    # subscriber that has already been served.
    loaded_before, failed_before = list(sub.loaded), list(sub.failed)
    route.trigger(cache, route.url)
    qtbot.wait(150)  # let any queued worker-thread signal reach the main loop
    assert sub.loaded == loaded_before, f"{route.id}: subscriber was re-notified (on_loaded)"
    assert sub.failed == failed_before, f"{route.id}: subscriber was re-notified (on_failed)"


def test_inflight_dedup_notifies_every_waiting_subscriber(cache, monkeypatch, qtbot) -> None:
    """7. A second subscribe() + get_image_async for a url whose download is
    already in progress must still be notified when it completes — dedup
    must never cost a waiting caller its notification."""
    url = "http://example.com/route-inflight-dedup.jpg"
    release = threading.Event()
    call_count = 0
    lock = threading.Lock()

    def fake_get(*a, **k):
        nonlocal call_count
        with lock:
            call_count += 1
        release.wait(timeout=5)
        return _FakeResponse(content=_VALID_PNG_BYTES)

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    sub1 = _Subscriber()
    sub2 = _Subscriber()
    cache.subscribe(url, sub1.on_loaded, sub1.on_failed)
    cache.get_image_async(url)  # starts the (blocked) download

    cache.subscribe(url, sub2.on_loaded, sub2.on_failed)
    cache.get_image_async(url)  # in-flight: must not submit a second download

    with qtbot.waitSignal(cache.image_loaded, timeout=5000):
        release.set()

    assert call_count == 1, "in-flight dedup resubmitted the same download"
    assert sub1.loaded == [url], "the FIRST waiting subscriber was never notified"
    assert sub2.loaded == [url], "the SECOND waiting subscriber (in-flight dedup) was never notified"


def test_ensure_resident_direct_call_notifies_subscriber(cache, monkeypatch, qtbot) -> None:
    """8. The paint-adjacent entry point, called directly rather than through
    get_image_async, with a subscriber already registered."""
    url = "http://example.com/route-ensure-resident-direct.jpg"
    monkeypatch.setattr(
        "metatv.core.image_cache.requests.get",
        lambda *a, **k: _FakeResponse(content=_VALID_PNG_BYTES),
    )

    sub = _Subscriber()
    cache.subscribe(url, sub.on_loaded, sub.on_failed)

    with qtbot.waitSignal(cache.image_loaded, timeout=5000) as blocker:
        cache.ensure_resident(url)

    assert blocker.args[0] == url
    assert sub.loaded == [url], "ensure_resident() called directly never reached the subscriber"
    assert sub.failed == []

    # One-shot: the pixmap is resident now, so a second direct call is a
    # silent no-op — assert the OUTCOME (no re-notification), not the
    # early-return mechanism that happens to produce it.
    cache.ensure_resident(url)
    qtbot.wait(150)
    assert sub.loaded == [url]
