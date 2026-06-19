"""Behavioral tests for the enhanced Playback tab in SettingsDialog.

Tests pin the three behaviours that could regress:
1. Load: buffer_profile from config selects the right combo item.
2. Save: combo selection → config.buffer_profile written; config.default_cache_size reset to "auto".
3. User-agent display: read-only field shows stream_user_agent() at load time.

Widgets are constructed via __new__ (no real QDialog init) following the same
pattern used in test_diagnostics_dialog.py — real Qt widgets via the module-scoped
qapp fixture.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QComboBox, QLineEdit, QCheckBox, QSpinBox

from metatv.gui.settings_dialog import SettingsDialog
from metatv.core.http_headers import stream_user_agent


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeConfig:
    """Minimal config stub covering the fields touched by Playback-tab load/save."""

    def __init__(
        self,
        buffer_profile: str = "modest",
        default_cache_size: str = "auto",
        prebuffer_before_play: bool = False,
        prebuffer_wait_secs: int = 10,
        mpv_args_override_all: bool = False,
    ):
        self.preferred_player = "mpv"
        self.player_mode = "single-instance"
        self.autoplay_season_episodes = False
        self.close_player_when_finished = False
        self.network_timeout = 10
        self.reconnect_attempts = 3
        self.buffer_profile = buffer_profile
        self.default_cache_size = default_cache_size
        self.mpv_extra_args: list[str] = []
        self.prebuffer_before_play = prebuffer_before_play
        self.prebuffer_wait_secs = prebuffer_wait_secs
        self.mpv_args_override_all = mpv_args_override_all
        self.split_streams_by_source = False
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


def _bare_dialog(qapp) -> SettingsDialog:
    """Build a SettingsDialog skeleton via __new__ and wire only the Playback-tab
    widgets that _load_values / _save_values touch — avoids standing up the full
    QDialog hierarchy (tabs, button box, parent widget)."""
    from PyQt6.QtWidgets import QSpinBox
    from metatv.gui.settings_dialog import SettingsDialog
    import metatv.core.epg_utils as _epg

    dlg = SettingsDialog.__new__(SettingsDialog)

    # Player group
    dlg._player_combo = QComboBox()
    dlg._player_combo.addItems(["mpv", "vlc", "custom"])
    dlg._player_mode_combo = QComboBox()
    dlg._player_mode_combo.addItems(["Single instance", "Multiple instances"])
    dlg._autoplay_check = _bool_check(qapp)
    dlg._close_player_check = _bool_check(qapp)

    # New Buffering combo (mirrors _build_playback_tab)
    dlg._buffer_combo = QComboBox()
    dlg._buffer_combo.addItem("Reconnect only (no extra buffer)", userData="reconnect_only")
    dlg._buffer_combo.addItem("Modest (~10s buffer)", userData="modest")
    dlg._buffer_combo.addItem("Large (~30s buffer)", userData="large")

    # HTTP User-Agent read-only display
    dlg._user_agent_view = QLineEdit()
    dlg._user_agent_view.setReadOnly(True)

    # Network
    dlg._timeout_spin = QSpinBox()
    dlg._timeout_spin.setRange(1, 60)
    dlg._reconnect_spin = QSpinBox()
    dlg._reconnect_spin.setRange(0, 10)

    # MPV extra args
    dlg._mpv_args_input = QLineEdit()

    # Prebuffer controls
    dlg._prebuffer_check = QCheckBox()
    dlg._prebuffer_wait_spin = QSpinBox()
    dlg._prebuffer_wait_spin.setRange(1, 120)
    dlg._prebuffer_wait_spin.setSuffix(" s")

    # Override-all checkbox
    dlg._override_all_check = QCheckBox()

    # Split-streams checkbox (added in feat/split-streams-and-unified-menu)
    dlg._split_check = QCheckBox()

    # EPG interval combo (needed by _load_values)
    dlg._epg_interval_combo = QComboBox()
    for value, label in _epg.EPG_INTERVAL_CHOICES:
        dlg._epg_interval_combo.addItem(label, value)

    # Metadata — stubs to keep _load_values / _save_values happy
    dlg._meta_enabled_check = _bool_check(qapp)
    dlg._meta_autofetch_check = _bool_check(qapp)
    dlg._cache_ttl_spin = QSpinBox()
    dlg._cache_ttl_spin.setRange(1, 365)
    dlg._old_ttl_spin_alias = QSpinBox()
    dlg._cache_old_ttl_spin = dlg._old_ttl_spin_alias
    dlg._tmdb_key_input = QLineEdit()
    dlg._tmdb_lang_input = QLineEdit()
    dlg._omdb_key_input = QLineEdit()

    # Sidebar list widget (needed by _load_values / _save_values)
    from PyQt6.QtWidgets import QListWidget
    dlg._sidebar_list = QListWidget()

    return dlg


def _bool_check(qapp):
    from PyQt6.QtWidgets import QCheckBox
    return QCheckBox()


# --------------------------------------------------------------------------- #
# 1. Load: buffer_profile drives combo selection                               #
# --------------------------------------------------------------------------- #

def test_load_sets_buffer_combo_to_large(qapp):
    """Config with buffer_profile='large' must select the 'large' combo item."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(buffer_profile="large")
    dlg._load_values()

    assert dlg._buffer_combo.currentData() == "large"


def test_load_sets_buffer_combo_to_modest(qapp):
    """Default 'modest' profile selects the 'modest' combo item."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(buffer_profile="modest")
    dlg._load_values()

    assert dlg._buffer_combo.currentData() == "modest"


def test_load_sets_buffer_combo_to_reconnect_only(qapp):
    """'reconnect_only' profile is selectable via load."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(buffer_profile="reconnect_only")
    dlg._load_values()

    assert dlg._buffer_combo.currentData() == "reconnect_only"


def test_load_unknown_profile_falls_back_to_modest(qapp):
    """An unrecognised buffer_profile string must fall back to the 'modest' item."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(buffer_profile="nonexistent_value")
    dlg._load_values()

    assert dlg._buffer_combo.currentData() == "modest"


# --------------------------------------------------------------------------- #
# 2. Save: combo → config.buffer_profile; default_cache_size reset to "auto"  #
# --------------------------------------------------------------------------- #

def test_save_writes_buffer_profile_and_resets_cache_size(qapp):
    """Selecting 'reconnect_only' and saving must write buffer_profile and
    unconditionally set default_cache_size to 'auto'."""
    dlg = _bare_dialog(qapp)
    cfg = _FakeConfig(buffer_profile="modest", default_cache_size="100M")
    dlg.config = cfg
    dlg._load_values()

    # Switch to reconnect_only
    idx = dlg._buffer_combo.findData("reconnect_only")
    dlg._buffer_combo.setCurrentIndex(idx)

    dlg._save_values()

    assert cfg.buffer_profile == "reconnect_only"
    assert cfg.default_cache_size == "auto"
    assert cfg.save_calls == 1


def test_save_large_profile(qapp):
    """'large' profile is persisted correctly."""
    dlg = _bare_dialog(qapp)
    cfg = _FakeConfig(buffer_profile="modest")
    dlg.config = cfg
    dlg._load_values()

    idx = dlg._buffer_combo.findData("large")
    dlg._buffer_combo.setCurrentIndex(idx)
    dlg._save_values()

    assert cfg.buffer_profile == "large"
    assert cfg.default_cache_size == "auto"


# --------------------------------------------------------------------------- #
# 3. User-agent display: read-only field shows stream_user_agent()             #
# --------------------------------------------------------------------------- #

def test_user_agent_field_shows_canonical_string(qapp):
    """_user_agent_view must display the canonical user-agent string after load."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig()
    dlg._load_values()

    assert dlg._user_agent_view.text() == stream_user_agent()


def test_user_agent_field_is_read_only(qapp):
    """_user_agent_view must be read-only (informational display only)."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig()
    dlg._load_values()

    assert dlg._user_agent_view.isReadOnly() is True


# --------------------------------------------------------------------------- #
# 4. Load: prebuffer + override-all controls reflect config                    #
# --------------------------------------------------------------------------- #

def test_load_prebuffer_check_reflects_config_true(qapp):
    """prebuffer_before_play=True → _prebuffer_check is checked after load."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(prebuffer_before_play=True)
    dlg._load_values()

    assert dlg._prebuffer_check.isChecked() is True


def test_load_prebuffer_check_reflects_config_false(qapp):
    """prebuffer_before_play=False (default) → _prebuffer_check is unchecked after load."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(prebuffer_before_play=False)
    dlg._load_values()

    assert dlg._prebuffer_check.isChecked() is False


def test_load_prebuffer_wait_spin_reflects_config(qapp):
    """prebuffer_wait_secs=25 in config → spin shows 25 after load."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(prebuffer_wait_secs=25)
    dlg._load_values()

    assert dlg._prebuffer_wait_spin.value() == 25


def test_load_override_all_check_reflects_config_true(qapp):
    """mpv_args_override_all=True → _override_all_check is checked after load."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(mpv_args_override_all=True)
    dlg._load_values()

    assert dlg._override_all_check.isChecked() is True


def test_load_override_all_check_reflects_config_false(qapp):
    """mpv_args_override_all=False (default) → _override_all_check is unchecked after load."""
    dlg = _bare_dialog(qapp)
    dlg.config = _FakeConfig(mpv_args_override_all=False)
    dlg._load_values()

    assert dlg._override_all_check.isChecked() is False


# --------------------------------------------------------------------------- #
# 5. Save: new widgets write back to config                                    #
# --------------------------------------------------------------------------- #

def test_save_prebuffer_before_play_written(qapp):
    """Checking _prebuffer_check and saving writes prebuffer_before_play=True to config."""
    dlg = _bare_dialog(qapp)
    cfg = _FakeConfig(prebuffer_before_play=False)
    dlg.config = cfg
    dlg._load_values()

    dlg._prebuffer_check.setChecked(True)
    dlg._save_values()

    assert cfg.prebuffer_before_play is True
    assert cfg.save_calls == 1


def test_save_prebuffer_wait_secs_written(qapp):
    """Changing _prebuffer_wait_spin to 35 and saving writes prebuffer_wait_secs=35."""
    dlg = _bare_dialog(qapp)
    cfg = _FakeConfig(prebuffer_wait_secs=10)
    dlg.config = cfg
    dlg._load_values()

    dlg._prebuffer_wait_spin.setValue(35)
    dlg._save_values()

    assert cfg.prebuffer_wait_secs == 35


def test_save_override_all_written(qapp):
    """Checking _override_all_check and saving writes mpv_args_override_all=True."""
    dlg = _bare_dialog(qapp)
    cfg = _FakeConfig(mpv_args_override_all=False)
    dlg.config = cfg
    dlg._load_values()

    dlg._override_all_check.setChecked(True)
    dlg._save_values()

    assert cfg.mpv_args_override_all is True
    assert cfg.save_calls == 1


def test_save_all_three_new_fields_together(qapp):
    """All three new fields are saved correctly in a single _save_values call."""
    dlg = _bare_dialog(qapp)
    cfg = _FakeConfig(prebuffer_before_play=False, prebuffer_wait_secs=10, mpv_args_override_all=False)
    dlg.config = cfg
    dlg._load_values()

    dlg._prebuffer_check.setChecked(True)
    dlg._prebuffer_wait_spin.setValue(20)
    dlg._override_all_check.setChecked(True)
    dlg._save_values()

    assert cfg.prebuffer_before_play is True
    assert cfg.prebuffer_wait_secs == 20
    assert cfg.mpv_args_override_all is True
