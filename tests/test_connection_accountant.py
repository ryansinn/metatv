"""Unit tests for the Wave 5 connection accountant (foundation slice).

Covers:
1. ConnectionAccountant: acquire/release/capacity/in_use/holders/preview,
   idempotent re-acquire, unlimited-capacity sentinel, resolver-error fallback.
2. reconcile() releases holders whose key is no longer alive, and a freed
   slot becomes available to a new acquire.
3. Thread-safety smoke: concurrent acquire/release never lets in_use exceed
   capacity and never raises.
4. PlayerManager lifecycle: play() registers a holder, a second window for a
   provider already at capacity is denied, stop() releases the holder, and a
   crashed (never-stopped) instance is swept up by the next play()'s reconcile.
5. The one shared _StreamingMixin helper (_provider_max_connections /
   _play_checked) resolves the REAL provider max_connections from the DB and
   threads it into player_manager.play() — the "one helper, not five copies"
   requirement.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from metatv.core.connection_accountant import AcquireResult, ConnectionAccountant, Holder


def _fixed_capacity(n: int):
    return lambda provider_id: n


# ---------------------------------------------------------------------------
# 1. ConnectionAccountant — acquire / release / capacity / holders / preview
# ---------------------------------------------------------------------------

def test_acquire_grants_first_holder_under_capacity():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(2))
    result = acc.acquire("prov-a", "playback", "key1")
    assert result.granted is True
    assert result.capacity == 2
    assert result.holders == ("key1",)
    assert acc.in_use("prov-a") == 1


def test_acquire_second_distinct_holder_within_capacity_granted():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(2))
    acc.acquire("prov-a", "playback", "key1")
    result = acc.acquire("prov-a", "playback", "key2")
    assert result.granted is True
    assert acc.in_use("prov-a") == 2


def test_acquire_third_holder_exceeds_capacity_denied_state_unchanged():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(2))
    acc.acquire("prov-a", "playback", "key1")
    acc.acquire("prov-a", "playback", "key2")
    result = acc.acquire("prov-a", "playback", "key3")
    assert result.granted is False
    assert result.capacity == 2
    assert set(result.holders) == {"key1", "key2"}
    assert acc.in_use("prov-a") == 2  # key3 was NOT registered


def test_acquire_reacquire_same_holder_idempotent_no_double_count():
    """A reused window (same key) replaying the same provider never double-counts."""
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1))
    acc.acquire("prov-a", "playback", "key1")
    result = acc.acquire("prov-a", "playback", "key1")
    assert result.granted is True
    assert acc.in_use("prov-a") == 1


def test_capacity_zero_from_resolver_means_unlimited():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(0))
    for i in range(10):
        assert acc.acquire("prov-a", "playback", f"key{i}").granted is True
    assert acc.in_use("prov-a") == 10


def test_capacity_resolver_exception_falls_back_to_one():
    def _boom(provider_id):
        raise RuntimeError("resolver blew up")

    acc = ConnectionAccountant(capacity_resolver=_boom)
    assert acc.capacity("prov-a") == 1


def test_release_frees_a_slot_for_a_subsequent_acquire():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1))
    acc.acquire("prov-a", "playback", "key1")
    assert acc.acquire("prov-a", "playback", "key2").granted is False

    acc.release("prov-a", "key1")

    assert acc.in_use("prov-a") == 0
    assert acc.acquire("prov-a", "playback", "key2").granted is True


def test_release_unknown_holder_is_a_noop():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1))
    acc.release("prov-a", "nope")  # must not raise
    assert acc.in_use("prov-a") == 0


def test_holders_returns_id_and_kind():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(2))
    acc.acquire("prov-a", "playback", "key1")
    assert acc.holders("prov-a") == [Holder(holder_id="key1", kind="playback")]


def test_preview_would_exceed_does_not_mutate_state():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1))
    acc.acquire("prov-a", "playback", "key1")

    result = acc.preview("prov-a", "key2")

    assert result.granted is False
    assert acc.in_use("prov-a") == 1  # key2 was NOT registered by preview
    # A real acquire() right after must still see the same (unexceeded) state.
    assert acc.acquire("prov-a", "playback", "key2").granted is False


def test_preview_grants_for_an_already_registered_holder():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1))
    acc.acquire("prov-a", "playback", "key1")
    assert acc.preview("prov-a", "key1").granted is True


# ---------------------------------------------------------------------------
# 2. reconcile() — dead-holder sweep
# ---------------------------------------------------------------------------

def test_reconcile_releases_holders_not_in_alive_set():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(5))
    acc.acquire("prov-a", "playback", "key1")
    acc.acquire("prov-a", "playback", "key2")
    acc.acquire("prov-b", "playback", "key3")

    released = acc.reconcile(alive_holder_ids=["key1"])

    assert set(released) == {("prov-a", "key2"), ("prov-b", "key3")}
    assert acc.in_use("prov-a") == 1
    assert acc.in_use("prov-b") == 0


def test_reconcile_keeps_all_alive_holders():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(5))
    acc.acquire("prov-a", "playback", "key1")
    released = acc.reconcile(alive_holder_ids=["key1", "key2"])
    assert released == []
    assert acc.in_use("prov-a") == 1


def test_reconcile_freed_slot_allows_new_acquire():
    """A dead holder's slot becomes available to a NEW acquire after reconcile."""
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1))
    acc.acquire("prov-a", "playback", "key1")
    assert acc.acquire("prov-a", "playback", "key2").granted is False

    acc.reconcile(alive_holder_ids=[])  # key1's mpv process died

    assert acc.acquire("prov-a", "playback", "key2").granted is True


# ---------------------------------------------------------------------------
# 3. Thread-safety smoke
# ---------------------------------------------------------------------------

def test_thread_safety_smoke_concurrent_acquire_release():
    """Hammer acquire/release from many threads.

    capacity must never be observed exceeded and no exception may propagate
    from a race — proves the lock actually serializes state mutation.
    """
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(3))
    errors: list[Exception] = []
    max_observed: list[int] = []
    observe_lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            key = f"key{i}"
            for _ in range(200):
                acc.acquire("prov-a", "playback", key)
                with observe_lock:
                    max_observed.append(acc.in_use("prov-a"))
                acc.release("prov-a", key)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert max(max_observed) <= 3
    assert acc.in_use("prov-a") == 0


# ---------------------------------------------------------------------------
# 4. PlayerManager lifecycle: play() -> acquire, stop() -> release, reconcile
# ---------------------------------------------------------------------------

@dataclass
class _Cfg:
    mpv_socket_path: str = "/tmp/metatv-test-acct.sock"
    player_mode: str = "single-instance"
    close_player_when_finished: bool = False
    default_cache_size: str = "auto"
    mpv_extra_args: list = field(default_factory=list)
    buffer_profile: str = "modest"
    prebuffer_before_play: bool = False
    prebuffer_wait_secs: int = 10
    mpv_args_override_all: bool = False
    split_streams_by_source: bool = True
    max_player_instances: int = 0  # 0 = defer to the provider's own max


class _StubPlayer:
    """Minimal fake MPVPlayer: tracks alive keys without spawning anything."""

    def __init__(self) -> None:
        self._keys: set[str] = set()
        self.play_calls: list[dict] = []

    def play(self, url, title, instance_key="__shared__", start_seconds=0, open_ended_buffer=False, **kwargs):
        self._keys.add(instance_key)
        self.play_calls.append({"url": url, "title": title, "instance_key": instance_key})
        return True

    def active_keys(self) -> list[str]:
        return list(self._keys)

    def stop(self, key=None) -> bool:
        if key is not None:
            self._keys.discard(key)
        return True

    def kill(self, key: str) -> None:
        """Test-only: simulate a crashed process — dies WITHOUT going through stop()."""
        self._keys.discard(key)


def _make_player_manager(config: _Cfg | None = None):
    from metatv.core.player_manager import PlayerManager
    from tests.conftest import wire_player_manager_key_maps

    pm = PlayerManager.__new__(PlayerManager)
    pm.config = config or _Cfg()
    wire_player_manager_key_maps(pm)
    pm._init_connection_accounting()
    pm.player = _StubPlayer()
    return pm


def test_play_registers_a_connection_accountant_holder():
    pm = _make_player_manager()
    assert pm.play("http://a", "A", provider_id="prov-a", provider_max_connections=1) is True
    assert pm.connection_accountant.in_use("prov-a") == 1
    holders = pm.connection_accountant.holders("prov-a")
    assert holders == [Holder(holder_id="prov-a", kind="playback")]


def test_second_window_same_provider_over_capacity_is_denied():
    """A genuinely separate window for a provider already at capacity is denied.

    Split OFF + force_new_window=True opens a SEPARATE window (keyed by
    provider_id) alongside the shared window already playing that provider —
    the one path this slice can reach the would_exceed branch through.
    """
    pm = _make_player_manager(_Cfg(split_streams_by_source=False, max_player_instances=0))

    assert pm.play("http://a", "A", provider_id="prov-a", provider_max_connections=1) is True
    result = pm.play(
        "http://b", "B", provider_id="prov-a", provider_max_connections=1,
        force_new_window=True,
    )

    assert result is False
    # The underlying player was never asked to launch the second window.
    assert len(pm.player.play_calls) == 1
    assert pm.connection_accountant.in_use("prov-a") == 1


def test_check_capacity_previews_the_same_denial_without_mutating():
    pm = _make_player_manager(_Cfg(split_streams_by_source=False, max_player_instances=0))
    pm.play("http://a", "A", provider_id="prov-a", provider_max_connections=1)

    preview = pm.check_capacity("prov-a", 1, force_new_window=True)

    assert preview is not None
    assert preview.granted is False
    assert preview.holders == ("__shared__",)
    # Still just the one holder — check_capacity must not have acquired anything.
    assert pm.connection_accountant.in_use("prov-a") == 1


def test_stop_releases_the_accountant_holder():
    pm = _make_player_manager()  # split ON -> key == provider_id
    pm.play("http://a", "A", provider_id="prov-a", provider_max_connections=1)
    assert pm.connection_accountant.in_use("prov-a") == 1

    pm.stop(key="prov-a")

    assert pm.connection_accountant.in_use("prov-a") == 0
    # The slot is available again immediately (no reconcile round-trip needed).
    assert pm.play("http://b", "B", provider_id="prov-a", provider_max_connections=1) is True


def test_crashed_instance_is_swept_by_next_plays_reconcile():
    """A process that dies WITHOUT stop() being called leaks no slot forever."""
    pm = _make_player_manager(_Cfg(split_streams_by_source=False, max_player_instances=0))
    pm.play("http://a", "A", provider_id="prov-a", provider_max_connections=1)
    pm.play(
        "http://b", "B", provider_id="prov-b", provider_max_connections=1,
        force_new_window=True,
    )
    assert pm.connection_accountant.in_use("prov-b") == 1

    # Simulate the second window's mpv process crashing (no stop() call).
    pm.player.kill("prov-b")

    # Any subsequent play() reconciles dead holders at its top before acting.
    pm.play("http://c", "C", provider_id="prov-c", provider_max_connections=1, force_new_window=True)

    assert pm.connection_accountant.in_use("prov-b") == 0


def test_replacing_a_reused_key_with_a_different_provider_releases_the_old_one():
    """A key reused for a NEW provider (split OFF, shared window) releases the old slot."""
    pm = _make_player_manager(_Cfg(split_streams_by_source=False, max_player_instances=0))
    pm.play("http://a", "A", provider_id="prov-a", provider_max_connections=1)
    assert pm.connection_accountant.in_use("prov-a") == 1

    pm.play("http://b", "B", provider_id="prov-b", provider_max_connections=1)

    assert pm.connection_accountant.in_use("prov-a") == 0
    assert pm.connection_accountant.in_use("prov-b") == 1


# ---------------------------------------------------------------------------
# 5. _StreamingMixin: one helper resolves the REAL provider max, threaded
#    into player_manager.play() by every call site.
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'accountant.db'}")
    d.create_tables()
    yield d
    d.close()


def _insert_provider(db, provider_id: str, max_connections: int) -> None:
    from metatv.core.database import ProviderDB
    with db.session_scope() as session:
        session.add(ProviderDB(
            id=provider_id, name="Test Source", type="xtream",
            url="http://example.com", is_active=True, urls=[],
            max_connections=max_connections,
        ))


def test_provider_max_connections_resolves_real_db_value(db):
    from metatv.gui.main_window_streaming import _StreamingMixin
    _insert_provider(db, "prov-a", max_connections=3)

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db

    assert host._provider_max_connections("prov-a") == 3


def test_provider_max_connections_falls_back_to_one_for_unknown_provider(db):
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db

    assert host._provider_max_connections("no-such-provider") == 1


def test_play_checked_threads_real_provider_max_into_player_manager_play(db):
    """The one shared helper — not a copy per call site — resolves the real max."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    _insert_provider(db, "prov-a", max_connections=2)

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.player_manager = MagicMock()
    host.player_manager.check_capacity.return_value = AcquireResult(
        granted=True, provider_id="prov-a", capacity=2, holders=(),
    )
    host.player_manager.play.return_value = True

    result = host._play_checked("http://x", "Title", provider_id="prov-a")

    assert result is True
    host.player_manager.check_capacity.assert_called_once_with("prov-a", 2, force_new_window=False)
    host.player_manager.play.assert_called_once_with(
        "http://x", "Title",
        provider_id="prov-a",
        provider_max_connections=2,
        force_new_window=False,
        start_seconds=0,
        open_ended_buffer=False,
        deep_buffer=False,
        channel_id="",
    )


def test_play_checked_shows_warning_and_returns_false_when_capacity_would_be_exceeded(db):
    from metatv.gui.main_window_streaming import _StreamingMixin
    _insert_provider(db, "prov-a", max_connections=1)

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.player_manager = MagicMock()
    host.player_manager.check_capacity.return_value = AcquireResult(
        granted=False, provider_id="prov-a", capacity=1, holders=("__shared__",),
    )
    host.notification_manager = MagicMock()

    result = host._play_checked("http://x", "Title", provider_id="prov-a", force_new_window=True)

    assert result is False
    host.player_manager.play.assert_not_called()
    host.notification_manager.show.assert_called_once()
    kwargs = host.notification_manager.show.call_args.kwargs
    assert kwargs["title"] == "Connection Limit Reached"
    labels = [label for label, _cb in kwargs["actions"]]
    assert "Play anyway (replace oldest)" in labels
    assert "Cancel" in labels


def test_play_checked_replace_oldest_action_stops_then_replays(db):
    from metatv.gui.main_window_streaming import _StreamingMixin
    _insert_provider(db, "prov-a", max_connections=1)

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.player_manager = MagicMock()
    host.player_manager.check_capacity.return_value = AcquireResult(
        granted=False, provider_id="prov-a", capacity=1, holders=("__shared__",),
    )
    host.notification_manager = MagicMock()

    host._play_checked("http://x", "Title", provider_id="prov-a", force_new_window=True)

    kwargs = host.notification_manager.show.call_args.kwargs
    actions = dict(kwargs["actions"])
    actions["Play anyway (replace oldest)"]()

    host.player_manager.stop.assert_called_once_with(key="__shared__")
    host.player_manager.play.assert_called_once()
    _, play_kwargs = host.player_manager.play.call_args
    assert play_kwargs["provider_id"] == "prov-a"
    assert play_kwargs["provider_max_connections"] == 1
