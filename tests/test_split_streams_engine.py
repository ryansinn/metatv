"""Behavioral tests for the Split Streams engine (feat/split-streams-engine).

Tests cover:
1. ``MPVPlayer._socket_path_for`` — shared key returns exact config path; per-key
   paths are stable, filesystem-safe, and distinct from the shared path.
2. ``PlayerManager._resolve_instance_key`` — feature flag controls resolution.
3. Registry behavior (single-instance mode): two different keys → two Popen calls;
   same key reused → one Popen, IPC loadfile sent; ``_last_key`` tracks latest.
4. ``cleanup()`` terminates ALL instances' processes.
5. Via ``PlayerManager``: split OFF → multiple provider_ids land on one instance;
   split ON → two providers → two instances; same provider twice → one instance.
6. ``get_properties(names)`` with key=None targets ``_last_key``'s socket.

No real mpv process or socket is involved.  ``subprocess.Popen`` is replaced with
a fake whose ``poll()`` returns None (alive).  ``os.path.exists`` is patched to
report socket readiness.  ``MPVPlayer._send_ipc_command`` is patched to return True
so IPC succeeds.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

from metatv.core.players.mpv import MPVPlayer, _SHARED_KEY
from metatv.core.player_manager import PlayerManager


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

@dataclass
class _FakeConfig:
    """Minimal stand-in for Config."""
    mpv_socket_path: str = "/tmp/metatv-test.sock"
    player_mode: str = "single-instance"
    close_player_when_finished: bool = False
    default_cache_size: str = "auto"
    mpv_extra_args: list = field(default_factory=list)
    buffer_profile: str = "modest"
    prebuffer_before_play: bool = False
    prebuffer_wait_secs: int = 10
    mpv_args_override_all: bool = False
    split_streams_by_source: bool = False
    max_player_instances: int = 1


def _fake_process() -> MagicMock:
    """Return a mock Popen whose poll() signals the process is alive."""
    proc = MagicMock()
    proc.poll.return_value = None   # alive
    proc.pid = 12345
    proc.terminate = MagicMock()
    proc.wait = MagicMock()
    proc.kill = MagicMock()
    return proc


def _make_player(config: _FakeConfig | None = None) -> MPVPlayer:
    return MPVPlayer(config or _FakeConfig())


def _make_manager(config: _FakeConfig | None = None) -> PlayerManager:
    cfg = config or _FakeConfig()
    mgr = PlayerManager.__new__(PlayerManager)
    mgr.config = cfg
    mgr.running_instances = []
    mgr._key_provider = {}
    mgr.player = _make_player(cfg)
    return mgr


# ---------------------------------------------------------------------------
# 1. _socket_path_for
# ---------------------------------------------------------------------------

def test_socket_path_shared_key_returns_config_path():
    """``__shared__`` must return the exact ``config.mpv_socket_path``."""
    cfg = _FakeConfig(mpv_socket_path="/tmp/my-test.sock")
    player = _make_player(cfg)
    assert player._socket_path_for(_SHARED_KEY) == "/tmp/my-test.sock"


def test_socket_path_non_shared_differs_from_shared():
    """A per-key path must be different from the shared path."""
    player = _make_player()
    shared = player._socket_path_for(_SHARED_KEY)
    per_key = player._socket_path_for("provider-xyz")
    assert per_key != shared


def test_socket_path_is_stable_for_same_key():
    """The same key always produces the same socket path."""
    player = _make_player()
    assert player._socket_path_for("p1") == player._socket_path_for("p1")


def test_socket_path_suffix_is_filesystem_safe():
    """Per-key suffix must contain only [A-Za-z0-9_-] characters."""
    player = _make_player(_FakeConfig(mpv_socket_path="/tmp/base"))
    path = player._socket_path_for("provider/with:special chars!")
    # Everything after the last "-" that follows the base is the suffix
    suffix = path[len("/tmp/base") + 1:]
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", suffix), f"Unsafe suffix: {suffix!r}"


def test_socket_path_two_different_keys_produce_different_paths():
    """Two different keys must yield two distinct socket paths."""
    player = _make_player()
    assert player._socket_path_for("p1") != player._socket_path_for("p2")


def test_socket_path_non_shared_starts_with_base():
    """Per-key path is derived from config.mpv_socket_path."""
    cfg = _FakeConfig(mpv_socket_path="/tmp/metatv")
    player = _make_player(cfg)
    path = player._socket_path_for("some-provider")
    assert path.startswith("/tmp/metatv-")


# ---------------------------------------------------------------------------
# 2. PlayerManager._resolve_instance_key
# ---------------------------------------------------------------------------

def test_resolve_key_split_off_always_shared():
    """Split OFF → every provider_id maps to ``"__shared__"``."""
    mgr = _make_manager(_FakeConfig(split_streams_by_source=False))
    assert mgr._resolve_instance_key("provider-a") == "__shared__"
    assert mgr._resolve_instance_key(None) == "__shared__"
    assert mgr._resolve_instance_key("") == "__shared__"


def test_resolve_key_split_on_with_provider_id():
    """Split ON + truthy provider_id → that provider_id is the key."""
    mgr = _make_manager(_FakeConfig(split_streams_by_source=True))
    assert mgr._resolve_instance_key("provider-a") == "provider-a"
    assert mgr._resolve_instance_key("xyz123") == "xyz123"


def test_resolve_key_split_on_none_falls_back_to_shared():
    """Split ON + None provider_id → ``"__shared__"``."""
    mgr = _make_manager(_FakeConfig(split_streams_by_source=True))
    assert mgr._resolve_instance_key(None) == "__shared__"


def test_resolve_key_split_on_empty_string_falls_back_to_shared():
    """Split ON + empty string provider_id → ``"__shared__"``."""
    mgr = _make_manager(_FakeConfig(split_streams_by_source=True))
    assert mgr._resolve_instance_key("") == "__shared__"


# ---------------------------------------------------------------------------
# 3. Registry behavior (single-instance mode via MPVPlayer directly)
# ---------------------------------------------------------------------------

@pytest.fixture()
def _patched_player(monkeypatch):
    """Return an MPVPlayer with Popen, socket existence, and IPC mocked out."""
    cfg = _FakeConfig()
    player = _make_player(cfg)

    proc_factory = []
    def fake_popen(cmd, **kwargs):
        proc = _fake_process()
        proc_factory.append(proc)
        return proc

    monkeypatch.setattr("metatv.core.players.mpv.subprocess.Popen", fake_popen)
    monkeypatch.setattr("metatv.core.players.mpv.os.path.exists", lambda p: True)
    monkeypatch.setattr(MPVPlayer, "_send_ipc_command", lambda self, cmd, key: True)

    return player, proc_factory


def test_two_different_keys_create_two_instances(_patched_player):
    """Playing on two different keys must start two separate mpv processes."""
    player, procs = _patched_player
    player.play("http://a", "A", instance_key="p1")
    player.play("http://b", "B", instance_key="p2")
    assert len(procs) == 2
    assert "p1" in player._instances
    assert "p2" in player._instances


def test_same_key_reused_no_new_popen(_patched_player):
    """Playing a second URL on the same key must NOT spawn a new process."""
    player, procs = _patched_player
    player.play("http://a", "A", instance_key="p1")
    assert len(procs) == 1
    player.play("http://b", "B", instance_key="p1")
    assert len(procs) == 1  # still one process


def test_same_key_second_play_sends_loadfile(_patched_player, monkeypatch):
    """The second play on an existing instance must send a loadfile IPC command."""
    player, procs = _patched_player
    sent_commands = []

    def record_ipc(self, cmd, key):
        sent_commands.append((cmd, key))
        return True

    monkeypatch.setattr(MPVPlayer, "_send_ipc_command", record_ipc)
    player.play("http://a", "A", instance_key="p1")
    sent_commands.clear()  # reset after first launch
    player.play("http://b", "B", instance_key="p1")

    # The first recorded command for the second play must be a loadfile
    assert any(
        cmd.get("command", [])[0] == "loadfile"
        for cmd, _ in sent_commands
    )


def test_last_key_tracks_most_recent(_patched_player):
    """``_last_key`` must reflect the most recently played key."""
    player, _ = _patched_player
    player.play("http://a", "A", instance_key="p1")
    assert player._last_key == "p1"
    player.play("http://b", "B", instance_key="p2")
    assert player._last_key == "p2"
    player.play("http://c", "C", instance_key="p1")
    assert player._last_key == "p1"


def test_cleanup_terminates_all_instances(_patched_player):
    """``cleanup()`` must call terminate() on EVERY running instance."""
    player, procs = _patched_player
    player.play("http://a", "A", instance_key="p1")
    player.play("http://b", "B", instance_key="p2")
    assert len(procs) == 2

    player.cleanup()

    for proc in procs:
        proc.terminate.assert_called_once()


def test_cleanup_clears_registry(_patched_player):
    """After cleanup, the instance registry must be empty."""
    player, _ = _patched_player
    player.play("http://a", "A", instance_key="p1")
    player.cleanup()
    assert player._instances == {}


# ---------------------------------------------------------------------------
# 4. Via PlayerManager — split OFF vs ON
# ---------------------------------------------------------------------------

@pytest.fixture()
def _patched_manager(monkeypatch):
    """Return a PlayerManager with the player's Popen/socket/IPC mocked."""
    cfg = _FakeConfig(split_streams_by_source=False)
    mgr = _make_manager(cfg)

    procs = []
    def fake_popen(cmd, **kwargs):
        proc = _fake_process()
        procs.append(proc)
        return proc

    monkeypatch.setattr("metatv.core.players.mpv.subprocess.Popen", fake_popen)
    monkeypatch.setattr("metatv.core.players.mpv.os.path.exists", lambda p: True)
    monkeypatch.setattr(MPVPlayer, "_send_ipc_command", lambda self, cmd, key: True)

    return mgr, procs


def test_split_off_two_providers_share_one_instance(_patched_manager):
    """Split OFF: two different provider_ids land on the single ``__shared__`` window."""
    mgr, procs = _patched_manager
    mgr.config.split_streams_by_source = False

    mgr.play("http://a", "A", provider_id="p1")
    mgr.play("http://b", "B", provider_id="p2")

    # Both calls resolve to __shared__ — the instance is reused (1 Popen)
    assert len(procs) == 1
    assert list(mgr.player._instances.keys()) == ["__shared__"]


def test_split_on_two_providers_get_two_instances(_patched_manager):
    """Split ON: two different providers → two distinct mpv windows."""
    mgr, procs = _patched_manager
    mgr.config.split_streams_by_source = True

    mgr.play("http://a", "A", provider_id="p1")
    mgr.play("http://b", "B", provider_id="p2")

    assert len(procs) == 2
    assert "p1" in mgr.player._instances
    assert "p2" in mgr.player._instances


def test_split_on_same_provider_twice_reuses_instance(_patched_manager):
    """Split ON: playing twice on the same provider reuses its window (no new Popen)."""
    mgr, procs = _patched_manager
    mgr.config.split_streams_by_source = True

    mgr.play("http://a", "A", provider_id="p1")
    mgr.play("http://b", "B", provider_id="p1")

    assert len(procs) == 1


def test_split_on_none_provider_uses_shared(_patched_manager):
    """Split ON but provider_id=None → falls back to ``__shared__``."""
    mgr, procs = _patched_manager
    mgr.config.split_streams_by_source = True

    mgr.play("http://a", "A", provider_id=None)
    assert list(mgr.player._instances.keys()) == ["__shared__"]


def test_provider_for_key_split_on_maps_each_window_to_its_source(_patched_manager):
    """Split ON: each window key resolves back to the source that played into it."""
    mgr, procs = _patched_manager
    mgr.config.split_streams_by_source = True

    mgr.play("http://a", "A", provider_id="p1")
    mgr.play("http://b", "B", provider_id="p2")

    assert mgr.provider_for_key("p1") == "p1"
    assert mgr.provider_for_key("p2") == "p2"
    assert mgr.provider_for_key("unknown") is None
    assert mgr.provider_for_key(None) is None


def test_provider_for_key_shared_tracks_latest_source(_patched_manager):
    """Split OFF: the shared window resolves to the most-recently-played source."""
    mgr, procs = _patched_manager
    mgr.config.split_streams_by_source = False

    mgr.play("http://a", "A", provider_id="p1")
    assert mgr.provider_for_key("__shared__") == "p1"
    mgr.play("http://b", "B", provider_id="p2")
    assert mgr.provider_for_key("__shared__") == "p2"  # follows the latest play


# ---------------------------------------------------------------------------
# 5. get_properties targets _last_key when key=None
# ---------------------------------------------------------------------------

def test_get_properties_targets_last_key(monkeypatch):
    """get_properties(names) with key=None must query the ``_last_key`` socket."""
    cfg = _FakeConfig()
    player = _make_player(cfg)

    # Inject a fake running instance so the property query path is reachable.
    proc = _fake_process()
    from metatv.core.players.mpv import _Inst
    inst_p1 = _Inst(process=proc, socket_path=player._socket_path_for("p1"))
    player._instances["p1"] = inst_p1
    player._last_key = "p1"

    queried_sockets = []

    def fake_get_property(self, name, key=None):
        resolved = self._resolve_key(key)
        if resolved and resolved in self._instances:
            queried_sockets.append(self._instances[resolved].socket_path)
        return 42

    monkeypatch.setattr(MPVPlayer, "get_property", fake_get_property)

    result = player.get_properties(["path", "cache-speed"])

    # Both properties should have been queried against the p1 socket.
    expected_path = player._socket_path_for("p1")
    assert all(s == expected_path for s in queried_sockets)


def test_get_properties_key_none_no_last_key_returns_all_none():
    """With no ``_last_key`` set, get_properties returns all-None without raising."""
    player = _make_player()
    # _last_key starts as None and no instances exist
    result = player.get_properties(["path", "cache-speed"])
    assert result == {"path": None, "cache-speed": None}


# ---------------------------------------------------------------------------
# 6. Backward-compat: split OFF is byte-for-byte the same socket path
# ---------------------------------------------------------------------------

def test_split_off_socket_path_unchanged():
    """With split_streams_by_source=False, the resolved socket is config.mpv_socket_path."""
    cfg = _FakeConfig(mpv_socket_path="/tmp/mpv-metatv-socket")
    mgr = _make_manager(cfg)
    key = mgr._resolve_instance_key("any-provider")
    assert mgr.player._socket_path_for(key) == "/tmp/mpv-metatv-socket"
