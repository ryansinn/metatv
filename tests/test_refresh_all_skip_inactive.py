"""Behavioral tests for "Refresh All skips inactive sources" feature.

Four concrete regressions guarded here:

1. With ``refresh_all_includes_inactive=False``, ``refresh_all_providers()``
   enqueues ONLY active providers — an inactive one is skipped.
2. With ``refresh_all_includes_inactive=True`` (default), ALL providers are
   enqueued regardless of is_active.
3. ``refresh_all_includes_inactive`` round-trips through Config save/load.
4. The settings checkbox reads and writes the config field correctly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal QApplication fixture (needed for QCheckBox in test 4)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


# ---------------------------------------------------------------------------
# Helpers — fake provider rows
# ---------------------------------------------------------------------------

def _fake_provider(pid: str, name: str, is_active: bool) -> MagicMock:
    p = MagicMock()
    p.id = pid
    p.name = name
    p.is_active = is_active
    return p


# ---------------------------------------------------------------------------
# Tests 1 & 2: refresh_all_providers() enqueue filter
# ---------------------------------------------------------------------------

class _FakeRefreshAllWindow:
    """Minimal stub that exposes the mixin method under test."""

    def __init__(self, config, providers: list):
        self.config = config
        self._providers = providers
        self._enqueued: list[tuple[str, str]] = []

        # Fake DB + session machinery
        session = MagicMock()
        repos = MagicMock()
        repos.providers.get_all.side_effect = self._get_all
        factory = MagicMock(return_value=repos)

        db = MagicMock()
        db.get_session.return_value = session
        self.db = db
        self._factory = factory

        # Fake refresh_queue_manager
        rqm = MagicMock()
        rqm.enqueue.side_effect = lambda pid, name: self._enqueued.append((pid, name))
        self.refresh_queue_manager = rqm

    def _get_all(self, active_only: bool = False):
        if active_only:
            return [p for p in self._providers if p.is_active]
        return list(self._providers)

    def refresh_all_providers(self):
        # Import and call the real method — bound to this stub instance
        from metatv.gui.main_window_providers import _ProviderMixin
        with patch("metatv.gui.main_window_providers.RepositoryFactory", self._factory):
            _ProviderMixin.refresh_all_providers(self)


def test_refresh_all_skips_inactive_when_setting_is_false():
    """With refresh_all_includes_inactive=False, inactive providers are NOT enqueued."""
    cfg = MagicMock()
    cfg.refresh_all_includes_inactive = False

    active = _fake_provider("p-active", "Active Source", is_active=True)
    inactive = _fake_provider("p-inactive", "Inactive Source", is_active=False)

    win = _FakeRefreshAllWindow(cfg, [active, inactive])
    win.refresh_all_providers()

    enqueued_ids = [pid for pid, _ in win._enqueued]
    assert "p-active" in enqueued_ids, "Active provider must be enqueued"
    assert "p-inactive" not in enqueued_ids, "Inactive provider must NOT be enqueued when setting is False"


def test_refresh_all_includes_inactive_when_setting_is_true():
    """With refresh_all_includes_inactive=True (default), ALL providers are enqueued."""
    cfg = MagicMock()
    cfg.refresh_all_includes_inactive = True

    active = _fake_provider("p-active", "Active Source", is_active=True)
    inactive = _fake_provider("p-inactive", "Inactive Source", is_active=False)

    win = _FakeRefreshAllWindow(cfg, [active, inactive])
    win.refresh_all_providers()

    enqueued_ids = [pid for pid, _ in win._enqueued]
    assert "p-active" in enqueued_ids, "Active provider must be enqueued"
    assert "p-inactive" in enqueued_ids, "Inactive provider MUST be enqueued when setting is True"


def test_refresh_all_default_behaviour_includes_inactive():
    """If the config attribute is missing (legacy), default True means all providers enqueued."""
    # Simulate a config object that doesn't have the field (getattr fallback)
    cfg = object()  # has no refresh_all_includes_inactive attribute

    active = _fake_provider("p-active", "Active", is_active=True)
    inactive = _fake_provider("p-inactive", "Inactive", is_active=False)

    win = _FakeRefreshAllWindow(cfg, [active, inactive])
    win.refresh_all_providers()

    enqueued_ids = [pid for pid, _ in win._enqueued]
    assert "p-inactive" in enqueued_ids, (
        "Absent attribute must default to True (include inactive) for backward compat"
    )


# ---------------------------------------------------------------------------
# Test 3: Config field round-trips through save/load
# ---------------------------------------------------------------------------

def test_config_refresh_all_includes_inactive_roundtrip(tmp_path):
    """refresh_all_includes_inactive persists to YAML and loads back correctly."""
    from metatv.core.config import Config

    # --- save False ---
    cfg = Config(config_dir=tmp_path, data_dir=tmp_path, cache_dir=tmp_path)
    cfg.refresh_all_includes_inactive = False
    cfg.save()

    # Reload from disk
    loaded_data = __import__("yaml").safe_load((tmp_path / "config.yaml").read_text())
    assert "refresh_all_includes_inactive" in loaded_data, (
        "Field must be present in saved YAML"
    )
    assert loaded_data["refresh_all_includes_inactive"] is False

    reloaded = Config(**loaded_data)
    assert reloaded.refresh_all_includes_inactive is False, (
        "False value must survive save → load"
    )

    # --- save True ---
    cfg.refresh_all_includes_inactive = True
    cfg.save()
    loaded_data2 = __import__("yaml").safe_load((tmp_path / "config.yaml").read_text())
    assert loaded_data2["refresh_all_includes_inactive"] is True


# ---------------------------------------------------------------------------
# Test 4: Settings checkbox reads and writes the config field
# ---------------------------------------------------------------------------

def test_settings_checkbox_loads_from_config(qapp):
    """_refresh_all_inactive_check.isChecked() must reflect config.refresh_all_includes_inactive."""
    from PyQt6.QtWidgets import QCheckBox
    from metatv.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog.__new__(SettingsDialog)
    # Provide all widgets _load_values touches (minimal set for this test)
    _wire_minimal_dialog(dlg, qapp)

    # Load with False
    cfg = _minimal_config(refresh_all_includes_inactive=False)
    dlg.config = cfg
    dlg._load_values()
    assert dlg._refresh_all_inactive_check.isChecked() is False

    # Load with True
    cfg2 = _minimal_config(refresh_all_includes_inactive=True)
    dlg.config = cfg2
    dlg._load_values()
    assert dlg._refresh_all_inactive_check.isChecked() is True


def test_settings_checkbox_saves_to_config(qapp):
    """Changing _refresh_all_inactive_check and calling _save_values writes the config field."""
    from metatv.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog.__new__(SettingsDialog)
    _wire_minimal_dialog(dlg, qapp)

    cfg = _minimal_config(refresh_all_includes_inactive=True)
    dlg.config = cfg
    dlg._load_values()

    # Toggle the checkbox to False
    dlg._refresh_all_inactive_check.setChecked(False)
    dlg._save_values()

    assert cfg.refresh_all_includes_inactive is False, (
        "Unchecking must write False to config"
    )
    assert cfg.save_calls >= 1


# ---------------------------------------------------------------------------
# Helpers for dialog tests
# ---------------------------------------------------------------------------

def _minimal_config(*, refresh_all_includes_inactive: bool = True):
    """Minimal config stub that satisfies _load_values and _save_values."""

    class _Cfg:
        preferred_player = "mpv"
        player_mode = "single-instance"
        autoplay_season_episodes = True
        playback_resume_mode = "resume"
        prompt_after_autoplay = True
        watch_complete_threshold = 0.9
        watch_partial_threshold = 0.10
        close_player_when_finished = True
        network_timeout = 30
        reconnect_attempts = 3
        buffer_profile = "modest"
        default_cache_size = "auto"
        mpv_extra_args: list = []
        prebuffer_before_play = False
        prebuffer_wait_secs = 10
        mpv_args_override_all = False
        split_streams_by_source = False
        remember_search = True
        epg_default_refresh_interval = "3d"
        metadata_enabled = True
        metadata_auto_fetch = True
        metadata_cache_ttl_days = 30
        metadata_old_content_ttl_days = 90
        metadata_tmdb_api_key = ""
        metadata_tmdb_language = "en-US"
        metadata_omdb_api_key = ""
        sidebar_sections: list = []
        sidebar_visible_sections: list = []
        save_calls: int = 0

        def save(self):
            self.save_calls += 1

    c = _Cfg()
    c.refresh_all_includes_inactive = refresh_all_includes_inactive
    return c


def _wire_minimal_dialog(dlg, qapp):
    """Attach all widget attributes that _load_values and _save_values touch."""
    from PyQt6.QtWidgets import (
        QCheckBox, QComboBox, QLineEdit, QListWidget, QSpinBox,
    )
    from metatv.core.epg_utils import EPG_INTERVAL_CHOICES

    # Playback
    dlg._player_combo = QComboBox()
    dlg._player_combo.addItems(["mpv", "vlc", "custom"])
    dlg._player_mode_combo = QComboBox()
    dlg._player_mode_combo.addItems(["Single instance", "Multiple instances"])
    dlg._autoplay_check = QCheckBox()
    dlg._resume_mode_combo = QComboBox()
    dlg._resume_mode_combo.addItem("Resume", userData="resume")
    dlg._resume_mode_combo.addItem("Beginning", userData="beginning")
    dlg._prompt_after_autoplay_check = QCheckBox()
    dlg._watch_threshold_spin = QSpinBox()
    dlg._watch_threshold_spin.setRange(50, 100)
    dlg._watch_partial_spin = QSpinBox()
    dlg._watch_partial_spin.setRange(1, 49)
    dlg._close_player_check = QCheckBox()
    dlg._buffer_combo = QComboBox()
    dlg._buffer_combo.addItem("Modest", userData="modest")
    dlg._user_agent_view = QLineEdit()
    dlg._user_agent_view.setReadOnly(True)
    dlg._timeout_spin = QSpinBox()
    dlg._timeout_spin.setRange(1, 60)
    dlg._reconnect_spin = QSpinBox()
    dlg._reconnect_spin.setRange(0, 10)
    dlg._mpv_args_input = QLineEdit()
    dlg._prebuffer_check = QCheckBox()
    dlg._prebuffer_wait_spin = QSpinBox()
    dlg._prebuffer_wait_spin.setRange(1, 120)
    dlg._override_all_check = QCheckBox()
    dlg._split_check = QCheckBox()

    # Metadata + EPG
    dlg._meta_enabled_check = QCheckBox()
    dlg._meta_autofetch_check = QCheckBox()
    dlg._cache_ttl_spin = QSpinBox()
    dlg._cache_ttl_spin.setRange(1, 365)
    dlg._cache_old_ttl_spin = QSpinBox()
    dlg._cache_old_ttl_spin.setRange(1, 365)
    dlg._tmdb_key_input = QLineEdit()
    dlg._tmdb_lang_input = QLineEdit()
    dlg._omdb_key_input = QLineEdit()
    dlg._epg_interval_combo = QComboBox()
    for value, label in EPG_INTERVAL_CHOICES:
        dlg._epg_interval_combo.addItem(label, value)

    # Interface
    dlg._remember_search_check = QCheckBox()
    dlg._refresh_all_inactive_check = QCheckBox()
    dlg._sidebar_list = QListWidget()
