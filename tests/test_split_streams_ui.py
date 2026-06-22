"""Behavioral tests for Split Streams UI (feat/split-streams-and-unified-menu).

Covers the main-thread halves and config round-trips that would regress:

1. ``PlayerManager._resolve_instance_key`` with ``force_split`` param.
2. ``PlayerManager.play(..., force_new_window=True)`` resolves to provider key
   even when ``split_streams_by_source`` is False.
3. ``PlayerManager.active_keys()`` passthrough (and [] when player is None).
4. ``_on_health_readout_clicked`` cycling logic on the main-thread slot.
5. ``SettingsDialog`` round-trip for ``split_streams_by_source``.
6. ``_on_playback_health_ready`` multi-window position marker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.player_manager import PlayerManager
from metatv.gui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

@dataclass
class _FakeConfig:
    """Minimal config stub for PlayerManager tests."""
    mpv_socket_path: str = "/tmp/metatv-test-split.sock"
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


def _make_manager(split: bool = False) -> PlayerManager:
    """Build a PlayerManager via __new__ with a fake player; no real mpv."""
    cfg = _FakeConfig(split_streams_by_source=split)
    mgr = PlayerManager.__new__(PlayerManager)
    mgr.config = cfg
    mgr.running_instances = []
    mgr._key_provider = {}
    mgr.player = None  # overridden per-test as needed
    return mgr


class _FakePlayer:
    """Fake MPVPlayer that captures play() calls."""

    def __init__(self, keys: list[str] | None = None, last_key: str | None = None):
        self._active_keys = keys if keys is not None else []
        self._last_key = last_key
        self.play_calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    def play(self, url: str, title: str, instance_key: str = "__shared__") -> bool:
        self.play_calls.append({"url": url, "title": title, "instance_key": instance_key})
        return True

    def active_keys(self) -> list[str]:
        return list(self._active_keys)

    def cleanup(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fakes for main-thread slot tests
# ---------------------------------------------------------------------------

class _FakeLabel:
    def __init__(self):
        self.text = None
        self.visible = False
        self.tooltip = None

    def setText(self, t):
        self.text = t

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def setToolTip(self, t):
        self.tooltip = t


class _FakeTimer:
    def __init__(self):
        self.stopped = False
        self._active = True

    def stop(self):
        self.stopped = True
        self._active = False

    def isActive(self):
        return self._active


class _FakeExecutor:
    def __init__(self):
        self.submits: list[tuple] = []

    def submit(self, fn, *args):
        self.submits.append((fn, args))
        return MagicMock()


class _FakePlayerMgr:
    """Fake PlayerManager for main-window slot tests."""

    def __init__(self, keys: list[str] | None = None, last_key: str | None = None,
                 providers: dict | None = None):
        self._keys = keys if keys is not None else []
        self.player = SimpleNamespace(_last_key=last_key)
        self._providers = providers or {}

    def active_keys(self) -> list[str]:
        return list(self._keys)

    def is_running(self, key=None) -> bool:
        return bool(self._keys)

    def provider_for_key(self, key=None):
        return self._providers.get(key) if key is not None else None


# ---------------------------------------------------------------------------
# 1. _resolve_instance_key with force_split
# ---------------------------------------------------------------------------

def test_resolve_force_split_true_with_provider_returns_provider():
    """force_split=True + provider 'p1' → 'p1' even when split flag is OFF."""
    mgr = _make_manager(split=False)
    assert mgr._resolve_instance_key("p1", force_split=True) == "p1"


def test_resolve_force_split_false_split_off_with_provider_returns_shared():
    """force_split=False + split OFF + provider 'p1' → '__shared__'."""
    mgr = _make_manager(split=False)
    assert mgr._resolve_instance_key("p1", force_split=False) == "__shared__"


def test_resolve_force_split_true_provider_none_returns_shared():
    """force_split=True + provider None → '__shared__' (no provider to key on)."""
    mgr = _make_manager(split=False)
    assert mgr._resolve_instance_key(None, force_split=True) == "__shared__"


def test_resolve_force_split_true_provider_empty_returns_shared():
    """force_split=True + empty string provider → '__shared__'."""
    mgr = _make_manager(split=False)
    assert mgr._resolve_instance_key("", force_split=True) == "__shared__"


def test_resolve_split_on_no_force_still_returns_provider():
    """Split ON + force_split=False + provider → provider (normal split behavior)."""
    mgr = _make_manager(split=True)
    assert mgr._resolve_instance_key("p1", force_split=False) == "p1"


# ---------------------------------------------------------------------------
# 2. PlayerManager.play with force_new_window
# ---------------------------------------------------------------------------

def test_play_force_new_window_uses_provider_key_when_split_off():
    """play(..., force_new_window=True) → instance_key='p1' even with split OFF."""
    mgr = _make_manager(split=False)
    fake_player = _FakePlayer()
    mgr.player = fake_player
    mgr.config.max_player_instances = -1  # unlimited

    result = mgr.play("http://stream", "Test", provider_id="p1", force_new_window=True)

    assert result is True
    assert len(fake_player.play_calls) == 1
    assert fake_player.play_calls[0]["instance_key"] == "p1"


def test_play_no_force_split_off_uses_shared():
    """play(..., force_new_window=False) with split OFF → instance_key='__shared__'."""
    mgr = _make_manager(split=False)
    fake_player = _FakePlayer()
    mgr.player = fake_player
    mgr.config.max_player_instances = -1

    result = mgr.play("http://stream", "Test", provider_id="p1", force_new_window=False)

    assert result is True
    assert fake_player.play_calls[0]["instance_key"] == "__shared__"


# ---------------------------------------------------------------------------
# 3. active_keys() passthrough
# ---------------------------------------------------------------------------

def test_active_keys_delegates_to_player():
    """active_keys() must return the player's active key list."""
    mgr = _make_manager()
    mgr.player = _FakePlayer(keys=["p1", "p2"])
    assert mgr.active_keys() == ["p1", "p2"]


def test_active_keys_returns_empty_when_player_none():
    """active_keys() must return [] when player is None (no player available)."""
    mgr = _make_manager()
    mgr.player = None
    assert mgr.active_keys() == []


def test_active_keys_empty_when_no_running_instances():
    """active_keys() returns [] from a player with no running instances."""
    mgr = _make_manager()
    mgr.player = _FakePlayer(keys=[])
    assert mgr.active_keys() == []


# ---------------------------------------------------------------------------
# 4. _on_health_readout_clicked — cycling logic
# ---------------------------------------------------------------------------

def _host_for_click(keys: list[str], last_key: str | None = None) -> MainWindow:
    host = MainWindow.__new__(MainWindow)
    host.player_manager = _FakePlayerMgr(keys=keys, last_key=last_key)
    host.executor = _FakeExecutor()
    host._health_view_key = None
    host._health_query_inflight = False
    host._health_querying_key = None
    return host


def test_click_single_key_is_noop():
    """With a single open player, clicking the readout must not change _health_view_key."""
    host = _host_for_click(keys=["__shared__"], last_key="__shared__")
    MainWindow._on_health_readout_clicked(host)
    assert host._health_view_key is None
    assert host.executor.submits == []


def test_click_advances_to_second_key():
    """With two open players and _health_view_key=None (follow latest), clicking advances to 'p2'."""
    host = _host_for_click(keys=["p1", "p2"], last_key="p1")
    MainWindow._on_health_readout_clicked(host)
    assert host._health_view_key == "p2"


def test_click_wraps_from_last_to_first():
    """From 'p2' (the last key), clicking must wrap around to 'p1'."""
    host = _host_for_click(keys=["p1", "p2"], last_key="p1")
    # First click → advances to p2
    MainWindow._on_health_readout_clicked(host)
    assert host._health_view_key == "p2"
    # Second click → wraps back to p1
    MainWindow._on_health_readout_clicked(host)
    assert host._health_view_key == "p1"


def test_click_submits_immediate_probe():
    """After advancing the key, an immediate background probe must be submitted."""
    host = _host_for_click(keys=["p1", "p2"], last_key="p1")
    MainWindow._on_health_readout_clicked(host)
    # One probe submitted for the newly-selected key.
    assert len(host.executor.submits) == 1


def test_click_does_not_pile_up_when_inflight():
    """If a probe is already in-flight, the click must NOT submit another."""
    host = _host_for_click(keys=["p1", "p2"], last_key="p1")
    host._health_query_inflight = True
    MainWindow._on_health_readout_clicked(host)
    # Key still advances...
    assert host._health_view_key == "p2"
    # ...but no extra submit.
    assert host.executor.submits == []


# ---------------------------------------------------------------------------
# 5. SettingsDialog round-trip for split_streams_by_source
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeDlgConfig:
    """Minimal SettingsDialog config stub including split_streams_by_source."""

    def __init__(self, split: bool = False):
        self.preferred_player = "mpv"
        self.player_mode = "single-instance"
        self.autoplay_season_episodes = False
        self.watch_complete_threshold = 0.9
        self.close_player_when_finished = False
        self.network_timeout = 10
        self.reconnect_attempts = 3
        self.buffer_profile = "modest"
        self.default_cache_size = "auto"
        self.mpv_extra_args: list[str] = []
        self.prebuffer_before_play = False
        self.prebuffer_wait_secs = 10
        self.mpv_args_override_all = False
        self.split_streams_by_source = split
        self.epg_default_refresh_interval = "3d"
        self.metadata_enabled = True
        self.metadata_auto_fetch = False
        self.metadata_cache_ttl_days = 30
        self.metadata_old_content_ttl_days = 90
        self.metadata_tmdb_api_key = ""
        self.metadata_tmdb_language = "en-US"
        self.metadata_omdb_api_key = ""
        self.sidebar_sections: list[str] = []
        self.sidebar_visible_sections: list[str] = []
        self.save_calls: int = 0

    def save(self) -> None:
        self.save_calls += 1


def _bare_split_dialog(qapp, split: bool = False):
    """Build a SettingsDialog skeleton via __new__ with only split-relevant widgets."""
    from PyQt6.QtWidgets import (
        QCheckBox, QComboBox, QSpinBox, QLineEdit, QListWidget
    )
    from metatv.gui.settings_dialog import SettingsDialog
    import metatv.core.epg_utils as _epg
    from metatv.core.http_headers import stream_user_agent

    dlg = SettingsDialog.__new__(SettingsDialog)
    dlg.config = _FakeDlgConfig(split=split)

    # Playback group widgets (all needed by _load_values / _save_values)
    dlg._player_combo = QComboBox()
    dlg._player_combo.addItems(["mpv", "vlc", "custom"])
    dlg._player_mode_combo = QComboBox()
    dlg._player_mode_combo.addItems(["Single instance", "Multiple instances"])
    dlg._autoplay_check = QCheckBox()

    # Watch-completion threshold (Slice 2)
    dlg._watch_threshold_spin = QSpinBox()
    dlg._watch_threshold_spin.setRange(50, 100)
    dlg._watch_threshold_spin.setSuffix("%")

    dlg._close_player_check = QCheckBox()

    dlg._buffer_combo = QComboBox()
    dlg._buffer_combo.addItem("Reconnect only (no extra buffer)", userData="reconnect_only")
    dlg._buffer_combo.addItem("Modest (~10s buffer)", userData="modest")
    dlg._buffer_combo.addItem("Large (~30s buffer)", userData="large")

    dlg._prebuffer_check = QCheckBox()
    dlg._prebuffer_wait_spin = QSpinBox()
    dlg._prebuffer_wait_spin.setRange(1, 120)
    dlg._prebuffer_wait_spin.setSuffix(" s")
    dlg._override_all_check = QCheckBox()
    dlg._split_check = QCheckBox()  # the widget under test
    dlg._user_agent_view = QLineEdit()
    dlg._user_agent_view.setReadOnly(True)
    dlg._mpv_args_input = QLineEdit()

    dlg._timeout_spin = QSpinBox()
    dlg._timeout_spin.setRange(1, 60)
    dlg._reconnect_spin = QSpinBox()
    dlg._reconnect_spin.setRange(0, 10)

    dlg._epg_interval_combo = QComboBox()
    for value, label in _epg.EPG_INTERVAL_CHOICES:
        dlg._epg_interval_combo.addItem(label, value)

    dlg._meta_enabled_check = QCheckBox()
    dlg._meta_autofetch_check = QCheckBox()
    dlg._cache_ttl_spin = QSpinBox()
    dlg._cache_ttl_spin.setRange(1, 365)
    dlg._cache_old_ttl_spin = QSpinBox()
    dlg._cache_old_ttl_spin.setRange(1, 365)
    dlg._tmdb_key_input = QLineEdit()
    dlg._tmdb_lang_input = QLineEdit()
    dlg._omdb_key_input = QLineEdit()
    dlg._sidebar_list = QListWidget()

    return dlg


def test_split_check_load_reflects_config_false(qapp):
    """_split_check must be unchecked after _load_values() when config is False."""
    dlg = _bare_split_dialog(qapp, split=False)
    dlg._load_values()
    assert dlg._split_check.isChecked() is False


def test_split_check_load_reflects_config_true(qapp):
    """_split_check must be checked after _load_values() when config is True."""
    dlg = _bare_split_dialog(qapp, split=True)
    dlg._load_values()
    assert dlg._split_check.isChecked() is True


def test_split_check_save_writes_true_to_config(qapp):
    """Checking _split_check and calling _save_values() must write True to config."""
    dlg = _bare_split_dialog(qapp, split=False)
    dlg._load_values()
    dlg._split_check.setChecked(True)
    dlg._save_values()
    assert dlg.config.split_streams_by_source is True
    assert dlg.config.save_calls == 1


def test_split_check_save_writes_false_to_config(qapp):
    """Unchecking _split_check and calling _save_values() must write False to config."""
    dlg = _bare_split_dialog(qapp, split=True)
    dlg._load_values()
    dlg._split_check.setChecked(False)
    dlg._save_values()
    assert dlg.config.split_streams_by_source is False


# ---------------------------------------------------------------------------
# 6. _on_playback_health_ready — multi-window position marker
# ---------------------------------------------------------------------------

def _host_for_health(keys: list[str], last_key: str | None = None) -> MainWindow:
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_timer = _FakeTimer()
    host._health_query_inflight = True
    host._health_idle_ticks = 0
    host._provider_icons = {}
    host.player_manager = _FakePlayerMgr(keys=keys, last_key=last_key)
    return host


def test_health_ready_multi_window_shows_position_marker():
    """Two open windows: _on_playback_health_ready prepends '[i/n]' marker."""
    host = _host_for_health(keys=["p1", "p2"], last_key="p1")
    props = {
        "path": "http://stream/url",
        "demuxer-cache-duration": 3.0,
        "cache-speed": 1_000_000,
        "frame-drop-count": 0,
    }
    # key="p2" (the second player is being shown)
    MainWindow._on_playback_health_ready(host, ("p2", props))

    assert host._playback_health_label.visible is True
    text = host._playback_health_label.text
    # Should start with a [i/n] marker
    assert text.startswith("["), f"Expected '[' prefix, got: {text!r}"
    assert "/" in text[:8], f"Expected 'i/n' fraction near start, got: {text!r}"


def test_health_ready_single_window_no_marker():
    """Single open window: no position marker in the label text."""
    host = _host_for_health(keys=["__shared__"], last_key="__shared__")
    props = {
        "path": "http://stream/url",
        "demuxer-cache-duration": 5.0,
        "cache-speed": 500_000,
        "frame-drop-count": 1,
    }
    MainWindow._on_playback_health_ready(host, (None, props))

    text = host._playback_health_label.text
    assert not text.startswith("["), f"Unexpected '[' prefix in single-window case: {text!r}"
    assert host._playback_health_label.visible is True


def test_health_ready_multi_window_label_is_shown():
    """Multi-window health readout is visible (not hidden)."""
    host = _host_for_health(keys=["p1", "p2"], last_key="p2")
    props = {
        "path": "http://x",
        "demuxer-cache-duration": 3.0,
        "cache-speed": 1000,
        "frame-drop-count": 0,
    }
    MainWindow._on_playback_health_ready(host, ("p2", props))
    assert host._playback_health_label.visible is True
