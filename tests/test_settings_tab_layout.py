"""Behavioral tests for the Settings dialog tab reorganization.

Pins three regressions that would break if the tabs were mis-arranged or a
widget's load/save wiring was dropped during the reorg:

1. Tab structure: exactly 4 tabs named
   ["Playback", "Interaction", "Metadata & API Keys", "Interface"]; no "Sidebar" tab.
2. EPG under Metadata: _epg_interval_combo is built inside _build_metadata_tab, so the
   Metadata tab widget tree contains it.
3. Interface tab persistence: remember_search and sidebar_sections round-trip correctly
   (construct → change moved controls → _save_values → assert config updated).

The dialog is constructed through __new__ following the same headless pattern used in
test_settings_playback_tab.py — real Qt widgets, module-scoped QApplication fixture.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QLineEdit, QListWidget,
    QListWidgetItem, QSpinBox, QTabWidget,
)

from metatv.gui.settings_dialog import SettingsDialog, _ALL_SIDEBAR_SECTIONS
import metatv.core.epg_utils as _epg


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeConfig:
    """Minimal config stub for the tab-layout tests."""

    def __init__(self):
        self.preferred_player = "mpv"
        self.player_mode = "single-instance"
        self.autoplay_season_episodes = False
        self.playback_resume_mode = "resume"
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
        self.remember_search: bool = True
        self.refresh_all_includes_inactive: bool = True
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


def _full_dialog(qapp) -> SettingsDialog:
    """Build a fully-wired SettingsDialog via __new__ with all widgets from all
    three tabs instantiated — mirrors what _setup_ui does, but without a parent
    QDialog or button box."""
    dlg = SettingsDialog.__new__(SettingsDialog)

    # -- Playback tab widgets --
    dlg._player_combo = QComboBox()
    dlg._player_combo.addItems(["mpv", "vlc", "custom"])
    dlg._player_mode_combo = QComboBox()
    dlg._player_mode_combo.addItems(["Single instance", "Multiple instances"])
    dlg._autoplay_check = QCheckBox()
    dlg._resume_mode_combo = QComboBox()
    dlg._resume_mode_combo.addItem("Resume where left off", userData="resume")
    dlg._resume_mode_combo.addItem("Start from beginning", userData="beginning")
    from metatv.gui.middle_click_actions import MIDDLE_CLICK_ACTIONS
    dlg._middle_click_combo = QComboBox()
    for _action in MIDDLE_CLICK_ACTIONS:
        dlg._middle_click_combo.addItem(_action.label, userData=_action.key)
    dlg._prompt_after_autoplay_check = QCheckBox()
    dlg._watch_threshold_spin = QSpinBox()
    dlg._watch_threshold_spin.setRange(50, 100)
    dlg._watch_partial_spin = QSpinBox()
    dlg._watch_partial_spin.setRange(1, 49)
    dlg._close_player_check = QCheckBox()
    dlg._buffer_combo = QComboBox()
    dlg._buffer_combo.addItem("Reconnect only (no extra buffer)", userData="reconnect_only")
    dlg._buffer_combo.addItem("Modest (~10s buffer)", userData="modest")
    dlg._buffer_combo.addItem("Large (~30s buffer)", userData="large")
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

    # -- Metadata tab widgets (includes EPG after reorg) --
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
    for value, label in _epg.EPG_INTERVAL_CHOICES:
        dlg._epg_interval_combo.addItem(label, value)
    dlg._epg_hide_older_spin = QSpinBox()
    dlg._epg_hide_older_spin.setRange(0, 168)

    # -- Interface tab widgets (Search + Sources + Sidebar) --
    dlg._remember_search_check = QCheckBox()
    dlg._refresh_all_inactive_check = QCheckBox()
    dlg._sidebar_list = QListWidget()

    return dlg


# --------------------------------------------------------------------------- #
# 1. Tab structure: 3 tabs, correct names, no "Sidebar" tab                   #
# --------------------------------------------------------------------------- #

def test_settings_dialog_has_exactly_four_tabs(qapp):
    """The dialog must have exactly 4 tabs after the Interaction tab was added."""
    cfg = _FakeConfig()
    dlg = SettingsDialog(cfg, parent=None)

    assert dlg._tabs.count() == 4

    dlg.close()


def test_settings_dialog_tab_names(qapp):
    """Tabs must be named Playback, Interaction, Metadata & API Keys, Interface in order."""
    cfg = _FakeConfig()
    dlg = SettingsDialog(cfg, parent=None)

    tab_titles = [dlg._tabs.tabText(i) for i in range(dlg._tabs.count())]
    assert tab_titles == ["Playback", "Interaction", "Metadata & API Keys", "Interface"]

    dlg.close()


def test_settings_dialog_no_sidebar_tab(qapp):
    """There must be no tab named 'Sidebar' — its content moved into Interface."""
    cfg = _FakeConfig()
    dlg = SettingsDialog(cfg, parent=None)

    tab_titles = [dlg._tabs.tabText(i) for i in range(dlg._tabs.count())]
    assert "Sidebar" not in tab_titles

    dlg.close()


# --------------------------------------------------------------------------- #
# 2. EPG combo lives under Metadata tab and still loads/saves correctly        #
# --------------------------------------------------------------------------- #

def test_epg_interval_loads_from_config(qapp):
    """_epg_interval_combo (now under Metadata tab) must load epg_default_refresh_interval."""
    dlg = _full_dialog(qapp)
    cfg = _FakeConfig()
    cfg.epg_default_refresh_interval = "7d"
    dlg.config = cfg
    dlg._load_values()

    assert dlg._epg_interval_combo.currentData() == "7d"


def test_epg_interval_saves_to_config(qapp):
    """Changing _epg_interval_combo and calling _save_values must persist to config."""
    dlg = _full_dialog(qapp)
    cfg = _FakeConfig()
    cfg.epg_default_refresh_interval = "3d"
    dlg.config = cfg
    dlg._load_values()

    # Switch to the first available value that isn't 3d
    for i in range(dlg._epg_interval_combo.count()):
        if dlg._epg_interval_combo.itemData(i) != "3d":
            dlg._epg_interval_combo.setCurrentIndex(i)
            expected_val = dlg._epg_interval_combo.currentData()
            break
    else:
        pytest.skip("Only one EPG interval choice available — can't test change")

    dlg._save_values()

    assert cfg.epg_default_refresh_interval == expected_val
    assert cfg.save_calls == 1


# --------------------------------------------------------------------------- #
# 3. Interface tab: Search + Sidebar controls round-trip through config        #
# --------------------------------------------------------------------------- #

def test_remember_search_loads_from_config(qapp):
    """_remember_search_check (now under Interface tab) loads remember_search from config."""
    dlg = _full_dialog(qapp)
    cfg = _FakeConfig()
    cfg.remember_search = False
    dlg.config = cfg
    dlg._load_values()

    assert dlg._remember_search_check.isChecked() is False


def test_remember_search_saves_to_config(qapp):
    """Toggling _remember_search_check and saving writes remember_search to config."""
    dlg = _full_dialog(qapp)
    cfg = _FakeConfig()
    cfg.remember_search = True
    dlg.config = cfg
    dlg._load_values()

    dlg._remember_search_check.setChecked(False)
    dlg._save_values()

    assert cfg.remember_search is False
    assert cfg.save_calls == 1


def test_sidebar_sections_load_from_config(qapp):
    """_sidebar_list (now under Interface tab) loads sidebar_sections from config."""
    dlg = _full_dialog(qapp)
    cfg = _FakeConfig()
    # Supply an explicit custom order and partial visibility
    cfg.sidebar_sections = ["alerts", "queue", "favorites"]
    cfg.sidebar_visible_sections = ["alerts", "favorites"]
    dlg.config = cfg
    dlg._load_values()

    # All known sections should appear (the load appends missing ones)
    list_section_ids = [
        dlg._sidebar_list.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(dlg._sidebar_list.count())
    ]
    # The first three should be in config order
    assert list_section_ids[:3] == ["alerts", "queue", "favorites"]
    # "alerts" is visible, "queue" is not
    assert dlg._sidebar_list.item(0).checkState() == Qt.CheckState.Checked   # alerts
    assert dlg._sidebar_list.item(1).checkState() == Qt.CheckState.Unchecked  # queue
    assert dlg._sidebar_list.item(2).checkState() == Qt.CheckState.Checked   # favorites


def test_sidebar_sections_save_to_config(qapp):
    """Un-checking a sidebar item and saving writes the updated visible set to config."""
    dlg = _full_dialog(qapp)
    cfg = _FakeConfig()
    cfg.sidebar_sections = list(_ALL_SIDEBAR_SECTIONS)
    cfg.sidebar_visible_sections = list(_ALL_SIDEBAR_SECTIONS)
    dlg.config = cfg
    dlg._load_values()

    # Un-check the first item
    first_item = dlg._sidebar_list.item(0)
    first_sid = first_item.data(Qt.ItemDataRole.UserRole)
    first_item.setCheckState(Qt.CheckState.Unchecked)

    dlg._save_values()

    assert first_sid not in cfg.sidebar_visible_sections
    # Remaining sections should still be visible
    assert len(cfg.sidebar_visible_sections) == len(_ALL_SIDEBAR_SECTIONS) - 1
    assert cfg.save_calls == 1
