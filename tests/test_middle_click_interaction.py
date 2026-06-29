"""Behavioral tests for the configurable middle-click action + Settings Interaction tab.

Covered behaviors
-----------------
Registry (gui.middle_click_actions):
1. Each registered action key maps to a real MainWindow play method.
2. The default key is the first entry and matches Config.middle_click_action.
3. An unknown key resolves to the default action (no crash on stale config).

Settings → Interaction tab (real SettingsDialog):
4. The tab is present and the middle-click combo is populated from the registry.
5. Load: config.middle_click_action / playback_resume_mode select the right items.
6. Save: combo selections write both fields back to config and persist.

Dispatch (_on_channel_middle_clicked):
7. The handler resolves config.middle_click_action through the registry and calls
   the mapped play method for the clicked channel id.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# 1–3. Registry is the single source of truth
# ---------------------------------------------------------------------------

def test_registry_keys_map_to_real_mainwindow_methods():
    """Every registry method name must exist as a play method on MainWindow."""
    from metatv.gui.main_window import MainWindow
    from metatv.gui.middle_click_actions import MIDDLE_CLICK_ACTIONS

    assert MIDDLE_CLICK_ACTIONS, "registry must not be empty"
    for action in MIDDLE_CLICK_ACTIONS:
        assert callable(getattr(MainWindow, action.method, None)), (
            f"action {action.key!r} -> missing MainWindow method {action.method!r}"
        )


def test_registry_initial_entries_map_to_expected_methods():
    """The two seeded actions map to the documented play paths."""
    from metatv.gui.middle_click_actions import middle_click_action

    assert middle_click_action("playback_position").method == "play_channel_resume_by_id"
    assert (
        middle_click_action("endless_buffer").method
        == "play_channel_open_ended_buffer_by_id"
    )


def test_registry_default_matches_config_default():
    """The default key is the first entry AND the Config field default."""
    from metatv.core.config import Config
    from metatv.gui.middle_click_actions import (
        DEFAULT_MIDDLE_CLICK_ACTION,
        MIDDLE_CLICK_ACTIONS,
    )

    assert DEFAULT_MIDDLE_CLICK_ACTION == MIDDLE_CLICK_ACTIONS[0].key
    assert Config().middle_click_action == DEFAULT_MIDDLE_CLICK_ACTION


def test_registry_unknown_key_falls_back_to_default():
    """A stale/unknown key resolves to the default action rather than raising."""
    from metatv.gui.middle_click_actions import (
        DEFAULT_MIDDLE_CLICK_ACTION,
        middle_click_action,
    )

    assert middle_click_action("removed_action").key == DEFAULT_MIDDLE_CLICK_ACTION


# ---------------------------------------------------------------------------
# 4–6. Settings → Interaction tab (real dialog round-trip)
# ---------------------------------------------------------------------------

class _FakeConfig:
    """Complete config stub so the real SettingsDialog builds + loads cleanly."""

    def __init__(
        self,
        playback_resume_mode: str = "resume",
        middle_click_action: str = "playback_position",
    ):
        self.preferred_player = "mpv"
        self.player_mode = "single-instance"
        self.autoplay_season_episodes = False
        self.playback_resume_mode = playback_resume_mode
        self.middle_click_action = middle_click_action
        self.prompt_after_autoplay = True
        self.watch_complete_threshold = 0.9
        self.watch_partial_threshold = 0.10
        self.close_player_when_finished = False
        self.network_timeout = 10
        self.reconnect_attempts = 3
        self.buffer_profile = "modest"
        self.default_cache_size = "auto"
        self.mpv_extra_args: list[str] = []
        self.prebuffer_before_play = False
        self.prebuffer_wait_secs = 10
        self.mpv_args_override_all = False
        self.split_streams_by_source = False
        self.remember_search = True
        self.refresh_all_includes_inactive = True
        self.epg_default_refresh_interval = "3d"
        self.epg_browse_hide_older_than_hours = 24
        self.metadata_enabled = True
        self.metadata_auto_fetch = False
        self.metadata_cache_ttl_days = 30
        self.metadata_old_content_ttl_days = 90
        self.metadata_tmdb_api_key = ""
        self.metadata_tmdb_language = "en-US"
        self.metadata_omdb_api_key = ""
        self.sidebar_sections: list[str] = []
        self.sidebar_visible_sections: list[str] = []
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


def test_interaction_tab_combo_populated_from_registry(qapp):
    """The middle-click combo lists exactly the registry's actions, in order."""
    from metatv.gui.settings_dialog import SettingsDialog
    from metatv.gui.middle_click_actions import MIDDLE_CLICK_ACTIONS

    dlg = SettingsDialog(_FakeConfig(), parent=None)
    keys = [
        dlg._middle_click_combo.itemData(i)
        for i in range(dlg._middle_click_combo.count())
    ]
    assert keys == [a.key for a in MIDDLE_CLICK_ACTIONS]
    dlg.close()


def test_interaction_tab_loads_both_fields(qapp):
    """Load: both combos reflect the config values (double-click + middle-click)."""
    from metatv.gui.settings_dialog import SettingsDialog

    cfg = _FakeConfig(playback_resume_mode="beginning", middle_click_action="endless_buffer")
    dlg = SettingsDialog(cfg, parent=None)

    assert dlg._resume_mode_combo.currentData() == "beginning"
    assert dlg._middle_click_combo.currentData() == "endless_buffer"
    dlg.close()


def test_interaction_tab_saves_both_fields(qapp):
    """Save: changing both combos writes playback_resume_mode + middle_click_action."""
    from metatv.gui.settings_dialog import SettingsDialog

    cfg = _FakeConfig(playback_resume_mode="resume", middle_click_action="playback_position")
    dlg = SettingsDialog(cfg, parent=None)

    dlg._resume_mode_combo.setCurrentIndex(dlg._resume_mode_combo.findData("beginning"))
    dlg._middle_click_combo.setCurrentIndex(
        dlg._middle_click_combo.findData("endless_buffer")
    )
    dlg._save_values()

    assert cfg.playback_resume_mode == "beginning"
    assert cfg.middle_click_action == "endless_buffer"
    assert cfg.save_calls == 1
    dlg.close()


def test_interaction_tab_load_unknown_middle_click_falls_back(qapp):
    """An unknown stored middle_click_action falls back to the default combo item."""
    from metatv.gui.settings_dialog import SettingsDialog
    from metatv.gui.middle_click_actions import DEFAULT_MIDDLE_CLICK_ACTION

    dlg = SettingsDialog(_FakeConfig(middle_click_action="gone"), parent=None)
    assert dlg._middle_click_combo.currentData() == DEFAULT_MIDDLE_CLICK_ACTION
    dlg.close()


# ---------------------------------------------------------------------------
# 7. Dispatch resolves through the registry
# ---------------------------------------------------------------------------

def _index(channel_id):
    idx = MagicMock()
    idx.data.return_value = channel_id
    return idx


def _channels_host(action_key: str):
    from metatv.gui.main_window_channels import _ChannelListMixin
    host = _ChannelListMixin.__new__(_ChannelListMixin)
    host.config = MagicMock()
    host.config.middle_click_action = action_key
    host.play_channel_resume_by_id = MagicMock()
    host.play_channel_open_ended_buffer_by_id = MagicMock()
    return host


def test_dispatch_calls_registry_mapped_method(qapp):
    """_on_channel_middle_clicked dispatches the mapped method per the registry."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    host = _channels_host("endless_buffer")
    _ChannelListMixin._on_channel_middle_clicked(host, _index("ch9"))
    host.play_channel_open_ended_buffer_by_id.assert_called_once_with("ch9")
    host.play_channel_resume_by_id.assert_not_called()
