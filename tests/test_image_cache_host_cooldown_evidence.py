"""IMG-2: a single connect timeout must not blacklist an image host.

Diagnosed from the owner's live log and profile store, not re-investigated
here. The log:

    07:21:08  ConnectTimeoutError(... 'Connection to image.tmdb.org timed
              out. (connect timeout=3.05)')
    07:21:09  Cached image from https://image.tmdb.org/... (three of them,
              one second later)
    07:33:08  cooldown: skipping https://image.tmdb.org/...
    07:33:08  cooldown: no candidate tried for ...
              Poster load failed for '...': cooldown: recently failed

One missed 3.05s connect blacklisted image.tmdb.org for 3 hours — persisted,
surviving every relaunch in between — one second before three downloads from
that same host succeeded. TMDb hosts most of the library's posters, so
Discover went blank. The fix: a host cooldown now requires
``_HOST_FAILURE_THRESHOLD`` CONSECUTIVE connect/connection failures against
that host (``_record_host_failure``), and any success is proof of life —
it resets the count and clears an active cooldown, in memory and in the
profile store (``_record_host_success``). The old persisted key
(``image_host_cooldowns``, written under the single-timeout policy) is
retired on load so it cannot resurrect a stale blacklist.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

import pytest
import requests

from metatv.core import profile_store
from metatv.core.database import Database
from metatv.core.image_cache import (
    ImageCache,
    _HOST_COOLDOWN_PROFILE_KEY,
    _HOST_COOLDOWN_PROFILE_KEY_V1,
    _HOST_FAILURE_THRESHOLD,
)


# A minimal, valid (per _verify_image's magic-byte + size check) PNG file —
# same fixture shape as the other image_cache test modules.
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
    """An ImageCache with no profile store bound — the tests that only care
    about in-memory behaviour don't need the extra Database fixture."""
    c = ImageCache(cache_dir=str(tmp_path / "cache"))
    yield c
    c.executor.shutdown(wait=True)


@pytest.fixture
def profile_db(tmp_path):
    """A REAL database on a tmp_path FILE, never :memory: — persistence
    behaviour (queued writes, read-back) needs a real file the writer
    thread and the test both see."""
    db = Database(f"sqlite:///{tmp_path / 'profile.db'}")
    db.create_tables()
    return db


@pytest.fixture
def bound_cache(profile_db, qapp, tmp_path):
    """An ImageCache constructed with a bound profile store — needed for
    every test that inspects persisted host cooldowns."""
    profile_store.bind(profile_db)
    c = ImageCache(cache_dir=str(tmp_path / "cache"))
    try:
        yield c
    finally:
        c.executor.shutdown(wait=True)
        profile_store.unbind()


# ── 1. one timeout does not blacklist a host ────────────────────────────────

def test_single_connect_timeout_does_not_cool_the_host(bound_cache, monkeypatch):
    """THE fix. Must FAIL against pre-IMG-2 main: there, the ConnectTimeout
    except-branch calls ``_set_cooldown(host, _HOST_COOLDOWN_S, persist=True)``
    directly on the FIRST failure, so ``_cooldown_active(host)`` would already
    be True here and the second url would be skipped, not tried."""
    cache = bound_cache
    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise requests.exceptions.ConnectTimeout(
            "Connection to image.tmdb.org timed out. (connect timeout=3.05)"
        )

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    url1 = "http://image.tmdb.org/a.jpg"
    url2 = "http://image.tmdb.org/b.jpg"  # same host, different file
    host = urlparse(url1).netloc

    cache._download_and_cache(url1)
    assert call_count == 1
    assert cache._host_failures.get(host) == 1, "one failure should be recorded, but not acted on"

    # No host cooldown at all — in memory or persisted.
    assert cache._cooldown_active(host) is False
    profile_store.flush()
    stored = profile_store.read_all().get(_HOST_COOLDOWN_PROFILE_KEY) or {}
    assert host not in stored, "a single timeout must never be persisted as a host cooldown"

    # A second url on the SAME host must actually be tried, not skipped.
    cache._download_and_cache(url2)
    assert call_count == 2, "a single timeout wrongly blacklisted the whole host"


# ── 2. three failures do ────────────────────────────────────────────────────

def test_three_consecutive_failures_cool_and_persist_the_host(bound_cache, monkeypatch):
    cache = bound_cache
    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    host = "dead.example.com"
    for i in range(_HOST_FAILURE_THRESHOLD):
        cache._download_and_cache(f"http://{host}/f{i}.jpg")
    assert call_count == _HOST_FAILURE_THRESHOLD

    assert cache._cooldown_active(host) is True

    profile_store.flush()
    stored = profile_store.read_all().get(_HOST_COOLDOWN_PROFILE_KEY) or {}
    assert host in stored
    assert stored[host] > time.time()


# ── 3. success clears everything ────────────────────────────────────────────

def test_success_resets_the_failure_counter(cache, monkeypatch):
    """After two failures, one success must reset the counter — not merely
    remove a cooldown, which was never set in the first place (threshold is
    3). A third, later failure proves the reset by NOT immediately cooling
    the host."""
    import itertools

    outcomes = itertools.chain(["fail", "fail", "success", "fail"], itertools.repeat("fail"))
    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if next(outcomes) == "fail":
            raise requests.exceptions.ConnectionError("connection refused")
        return _FakeResponse(content=_VALID_PNG_BYTES)

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    host = "flaky.example.com"
    cache._download_and_cache(f"http://{host}/f1.jpg")  # failure 1
    cache._download_and_cache(f"http://{host}/f2.jpg")  # failure 2
    assert cache._host_failures.get(host) == 2

    cache._download_and_cache(f"http://{host}/s.jpg")  # success — resets
    assert cache._host_failures.get(host) == 0

    cache._download_and_cache(f"http://{host}/f3.jpg")  # 1st failure post-reset
    assert cache._host_failures.get(host) == 1
    assert cache._cooldown_active(host) is False, (
        "the host cooled down after only 1 failure — the counter did not reset"
    )

    before = call_count
    cache._download_and_cache(f"http://{host}/v.jpg")  # must still be tried
    assert call_count == before + 1, "the host was wrongly cooled after only 1 failure post-reset"


def test_success_clears_an_active_cooldown_in_memory_and_persisted(bound_cache, monkeypatch):
    cache = bound_cache

    def fake_get(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    host = "unstable.example.com"
    for i in range(_HOST_FAILURE_THRESHOLD):
        cache._download_and_cache(f"http://{host}/f{i}.jpg")
    assert cache._cooldown_active(host) is True

    profile_store.flush()
    stored = profile_store.read_all().get(_HOST_COOLDOWN_PROFILE_KEY) or {}
    assert host in stored, "sanity: the cooldown really was persisted"

    # A success (proof of life) must remove the cooldown from both places.
    cache._record_host_success(host)

    assert cache._cooldown_active(host) is False
    profile_store.flush()
    stored_after = profile_store.read_all().get(_HOST_COOLDOWN_PROFILE_KEY) or {}
    assert host not in stored_after, "the persisted cooldown must be cleared too"


# ── 4. old key is retired ───────────────────────────────────────────────────

def test_v1_persisted_cooldown_key_is_retired_on_load(profile_db, qapp, tmp_path):
    """Entries the OLD (single-timeout) policy wrote must never come back —
    honouring them would keep a host blacked out for hours after this fix
    ships."""
    host = "old-format.example.com"
    profile_store.bind(profile_db)
    try:
        profile_store.record({_HOST_COOLDOWN_PROFILE_KEY_V1: {host: time.time() + 999_999}})
        profile_store.flush()

        cache = ImageCache(cache_dir=str(tmp_path / "cache"))
        try:
            assert cache._cooldown_active(host) is False

            profile_store.flush()
            stored_all = profile_store.read_all()
            assert _HOST_COOLDOWN_PROFILE_KEY_V1 not in stored_all, (
                "the v1 key must be deleted, not just ignored, so it can't "
                "come back on a later launch either"
            )
        finally:
            cache.executor.shutdown(wait=True)
    finally:
        profile_store.unbind()


# ── 5. the per-url 404 path is untouched ────────────────────────────────────

def test_url_level_404_never_touches_the_host_failure_count(cache, monkeypatch):
    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _FakeResponse(status_ok=False)

    monkeypatch.setattr("metatv.core.image_cache.requests.get", fake_get)

    host = "cdn.example.com"
    url1 = f"http://{host}/missing.jpg"
    url2 = f"http://{host}/other.jpg"

    for _ in range(_HOST_FAILURE_THRESHOLD + 2):  # well past the host threshold, if it counted
        cache._download_and_cache(url1)
    # Only the FIRST attempt reaches the network — later ones are skipped by
    # url1's OWN cooldown, never the host's.
    assert call_count == 1
    assert cache._host_failures.get(host, 0) == 0

    cache._download_and_cache(url2)
    assert call_count == 2, "a 404 on one file wrongly cooled the whole host"
