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
from loguru import logger

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
    """Past RECONCILE_GRACE_S, reconcile() sweeps whatever isn't in the alive set."""
    now = [0.0]
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(5), clock=lambda: now[0])
    acc.acquire("prov-a", "playback", "key1")
    acc.acquire("prov-a", "playback", "key2")
    acc.acquire("prov-b", "playback", "key3")
    now[0] += ConnectionAccountant.RECONCILE_GRACE_S + 1

    released = acc.reconcile(alive_holder_ids=["key1"])

    assert set(released) == {("prov-a", "key2"), ("prov-b", "key3")}
    assert acc.in_use("prov-a") == 1
    assert acc.in_use("prov-b") == 0


def test_reconcile_keeps_a_holder_younger_than_the_grace_period():
    """A holder registered moments ago must survive even if it's not 'alive' yet.

    This is the newborn-holder case RECONCILE_GRACE_S exists for: a play
    registers its holder before mpv's process exists, so a probe/alive-set
    taken in that window would wrongly call it dead.
    """
    now = [0.0]
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(5), clock=lambda: now[0])
    acc.acquire("prov-a", "playback", "key1")

    now[0] += ConnectionAccountant.RECONCILE_GRACE_S - 1
    released = acc.reconcile(alive_holder_ids=[])

    assert released == []
    assert acc.in_use("prov-a") == 1


def test_reconcile_keeps_all_alive_holders():
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(5))
    acc.acquire("prov-a", "playback", "key1")
    released = acc.reconcile(alive_holder_ids=["key1", "key2"])
    assert released == []
    assert acc.in_use("prov-a") == 1


def test_reconcile_freed_slot_allows_new_acquire():
    """A dead holder's slot becomes available to a NEW acquire after reconcile."""
    now = [0.0]
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1), clock=lambda: now[0])
    acc.acquire("prov-a", "playback", "key1")
    assert acc.acquire("prov-a", "playback", "key2").granted is False

    now[0] += ConnectionAccountant.RECONCILE_GRACE_S + 1
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
    """A process that dies WITHOUT stop() being called leaks no slot forever.

    Past RECONCILE_GRACE_S — the clock is injected so this test proves the
    sweep without sleeping for it.
    """
    now = [0.0]
    pm = _make_player_manager(_Cfg(split_streams_by_source=False, max_player_instances=0))
    pm.connection_accountant._clock = lambda: now[0]
    pm.play("http://a", "A", provider_id="prov-a", provider_max_connections=1)
    pm.play(
        "http://b", "B", provider_id="prov-b", provider_max_connections=1,
        force_new_window=True,
    )
    assert pm.connection_accountant.in_use("prov-b") == 1

    # Simulate the second window's mpv process crashing (no stop() call).
    pm.player.kill("prov-b")
    now[0] += ConnectionAccountant.RECONCILE_GRACE_S + 1

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


# ---------------------------------------------------------------------------
# 6. Liveness probe self-heal (DL-7) — acquire() sweeps a dead holder itself
#
# The reported bug: the user closes the player, the playback holder stays
# registered (nothing ever told the accountant mpv died), and every download
# acquire on that provider hits the capacity-full branch forever — silently,
# because that branch logged nothing. set_liveness_probe() lets acquire()
# check for itself instead of waiting for the next play()/stop() to reconcile.
# ---------------------------------------------------------------------------

def test_acquire_self_heals_a_dead_holder_past_the_grace_period():
    """The self-heal mechanism, isolated from the (separately-tested) cooldown.

    A holder is registered at t=0 and the probe says it's dead from the start
    (its process is already gone). A download acquire at t=5 is still refused
    — the grace period protects a holder that might just be newborn. At t=11
    (past RECONCILE_GRACE_S) the same acquire sweeps it and is granted.

    Registered as ``"monitor"`` rather than ``"playback"`` deliberately: a
    playback acquire also arms the 60s provider cooldown
    (``test_provider_cooldown.py`` covers that mechanism on its own), which
    would otherwise refuse every download here for a DIFFERENT reason and
    hide what this test exists to prove. ``test_player_manager_wires_the_
    liveness_probe_for_self_heal`` below reproduces the real playback+download
    scenario including that cooldown window.

    Pre-fix (no self-heal in acquire(), no probe param at all) the t=11 case
    stays refused forever — nothing but a play()/stop() call ever reconciles.
    """
    now = [0.0]
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1), clock=lambda: now[0])
    acc.acquire("p1", "monitor", "stale-monitor")
    acc.set_liveness_probe(lambda: [])  # its process is gone; nothing is alive

    now[0] = 5.0
    still_refused = acc.acquire("p1", "download", "dl-1")
    assert still_refused.granted is False, "grace must protect a holder this young"
    assert acc.in_use("p1") == 1

    now[0] = 11.0
    granted = acc.acquire("p1", "download", "dl-1")
    assert granted.granted is True
    assert acc.holders("p1") == [Holder(holder_id="dl-1", kind="download")]


def test_acquire_never_sweeps_a_holder_the_probe_reports_alive():
    """Downloads must never evict a playback holder that is genuinely alive."""
    now = [0.0]
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1), clock=lambda: now[0])
    acc.acquire("p1", "playback", "__shared__")
    acc.set_liveness_probe(lambda: ["__shared__"])  # mpv is still running

    now[0] = 100.0  # well past the grace period
    result = acc.acquire("p1", "download", "dl-1")

    assert result.granted is False
    assert acc.holders("p1") == [Holder(holder_id="__shared__", kind="playback")]


def test_refusal_logs_once_and_grant_after_waiting_logs_once():
    """'Say why, once' — a poller retrying every couple seconds doesn't spam.

    "monitor" as the blocker, not "playback", for the same reason as the test
    above: isolates the capacity-refusal log path from the cooldown's own
    (separately-tested) debug log.
    """
    now = [0.0]
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1), clock=lambda: now[0])
    acc.acquire("p1", "monitor", "stale-monitor")
    acc.set_liveness_probe(lambda: [])

    lines: list[str] = []
    sink_id = logger.add(lines.append, level="DEBUG", format="{message}")
    try:
        now[0] = 2.0
        acc.acquire("p1", "download", "dl-1")
        now[0] = 4.0
        acc.acquire("p1", "download", "dl-1")
        now[0] = 6.0
        acc.acquire("p1", "download", "dl-1")
        now[0] = 11.0
        result = acc.acquire("p1", "download", "dl-1")
    finally:
        logger.remove(sink_id)

    assert result.granted is True
    busy_lines = [line for line in lines if "Connection busy on p1: dl-1" in line]
    free_lines = [line for line in lines if "Connection free on p1: dl-1" in line]
    assert len(busy_lines) == 1, f"refusal logged more than once: {busy_lines}"
    assert len(free_lines) == 1, f"grant-after-wait logged more than once: {free_lines}"


def test_cooldown_refusal_is_never_retried_by_the_probe():
    """A dead holder cannot change the provider's own reaper lag — no self-heal here."""
    now = [0.0]
    acc = ConnectionAccountant(capacity_resolver=_fixed_capacity(1), clock=lambda: now[0])
    acc.set_liveness_probe(lambda: [])  # would report EVERYTHING dead if consulted
    acc.note_foreground_use("p1")

    result = acc.acquire("p1", "monitor", "poller-1")

    assert result.granted is False, "the cooldown branch must not be swept by the probe"


# ---------------------------------------------------------------------------
# 7. PlayerManager wires the probe (DL-7)
# ---------------------------------------------------------------------------

def test_player_manager_wires_the_liveness_probe_for_self_heal():
    """End to end through the real object graph DownloadManager shares.

    A window's mpv process is killed without stop() ever being called (the
    reported bug: the user closes the player). A download's acquire() on the
    SAME accountant — with no explicit reconcile from PlayerManager in
    between — still self-heals once the grace period has passed, because
    ``_wire_liveness_probe`` registered ``pm.player.active_keys``.

    Advances past the 60s provider cooldown too (a real ``play()`` arms it) —
    the owner's own log shows the cooldown countdown finishing and the
    refusal persisting silently after that, which is the state this fix
    targets.
    """
    now = [0.0]
    pm = _make_player_manager(_Cfg(split_streams_by_source=False, max_player_instances=0))
    pm.connection_accountant._clock = lambda: now[0]
    pm._wire_liveness_probe()

    assert pm.play("http://a", "A", provider_id="prov-a", provider_max_connections=1) is True
    pm.player.kill("__shared__")  # the user closed the player; no stop() call
    now[0] += ConnectionAccountant.PROVIDER_COOLDOWN_S + ConnectionAccountant.RECONCILE_GRACE_S + 1

    result = pm.connection_accountant.acquire("prov-a", "download", "dl-1")

    assert result.granted is True, "a queued download must start once the player is closed"
    assert pm.connection_accountant.holders("prov-a") == [
        Holder(holder_id="dl-1", kind="download")]
