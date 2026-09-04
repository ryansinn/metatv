"""Behavioral tests for the Settings dialog tab reorganization.

Pins three regressions that would break if the tabs were mis-arranged or a
widget's load/save wiring was dropped during the reorg:

1. Tab structure: exactly 5 tabs named
   every section declared in _SECTIONS, in order (derived, so it cannot go stale);
   no "Sidebar" tab.
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
    QSpinBox,
)

from metatv.gui.settings_dialog import SettingsDialog, _ALL_SIDEBAR_SECTIONS, _SECTIONS
from tests.conftest import (
    wire_settings_content_widgets,
    wire_settings_density_widget,
    wire_settings_downloads_widgets,
    wire_settings_epg_widgets,
    wire_settings_playback_widgets,
    wire_settings_recommendation_widgets,
    wire_settings_signal_widgets,
    wire_settings_theme_widget,
)


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
        self.signal_sample_seconds = 4
        self.signal_black_fraction = 0.5
        self.signal_black_pixel_threshold = 0.1
        self.signal_freeze_seconds = 2
        self.hide_dead_events = False
        self.signal_dead_streak_to_hide = 2
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
    # -- Content tab widgets -- (shared factory: CLAUDE.md — a duplicate found
    # while touching this exact spot is fixed here, not left as a second copy)
    wire_settings_content_widgets(dlg)

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

    # Playback Network group widgets
    wire_settings_playback_widgets(dlg)

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
    wire_settings_epg_widgets(dlg)

    # -- Recommendations tab widgets (scoring dials + shared media mix) --
    wire_settings_recommendation_widgets(dlg)

    # -- Interface tab widgets (Search + Sources + Sidebar) --
    dlg._remember_search_check = QCheckBox()
    dlg._refresh_all_inactive_check = QCheckBox()
    dlg._update_check_enabled_check = QCheckBox()
    dlg._sidebar_list = QListWidget()
    wire_settings_density_widget(dlg)
    wire_settings_signal_widgets(dlg)
    wire_settings_theme_widget(dlg)

    # -- Downloads tab widgets --
    wire_settings_downloads_widgets(dlg)

    return dlg


# --------------------------------------------------------------------------- #
# 1. Tab structure: 3 tabs, correct names, no "Sidebar" tab                   #
# --------------------------------------------------------------------------- #

def test_settings_dialog_nav_and_stack_agree(qapp):
    """The left nav and the page stack must carry one entry per declared section.

    Counted against ``_SECTIONS`` rather than a literal, which is what this
    assertion is actually for: ``_setup_ui`` pairs sections with builders using
    ``zip``, so a section declared without a builder is dropped **silently** and
    the nav and stack simply come up short. A hardcoded "== 5" cannot tell that
    apart from someone legitimately adding a sixth section — it just goes red
    and gets bumped to 6, which is how the check stops meaning anything.

    The floor keeps it honest if ``_SECTIONS`` is ever gutted.
    """
    cfg = _FakeConfig()
    dlg = SettingsDialog(cfg, parent=None)

    expected = len(_SECTIONS)
    assert expected >= 6
    assert dlg._nav.section_list.count() == expected, (
        "a declared section is missing from the nav — zip dropped it"
    )
    assert dlg._nav.stack.count() == expected, (
        "a declared section is missing from the page stack — zip dropped it"
    )

    dlg.close()


def test_settings_dialog_tab_names(qapp):
    """The nav must render EVERY declared section, in declared order.

    Derived from ``_SECTIONS`` rather than a hand-copied list of labels, because
    ``_setup_ui`` builds the nav with ``zip(_SECTIONS, builders)`` and **zip
    truncates silently**: declare a section and forget its builder and the
    section simply never appears, with nothing raised. A hardcoded label list
    cannot see that — it goes stale the moment a section is added, and its
    failure reads as "the list needs updating" rather than "a section vanished".

    The floor + anchors below keep it from passing vacuously on an empty or
    gutted ``_SECTIONS``.
    """
    cfg = _FakeConfig()
    dlg = SettingsDialog(cfg, parent=None)

    tab_titles = [dlg._nav.section_list.item(i).text()
                  for i in range(dlg._nav.section_list.count())]

    declared = [label for _sid, label, _builder in _SECTIONS]
    assert tab_titles == declared, (
        f"nav renders {tab_titles} but _SECTIONS declares {declared} — a section "
        f"was declared without a builder (zip truncated it), or the two are out of order"
    )
    assert len(tab_titles) >= 6
    assert tab_titles[0] == "Playback"
    assert "Content" in tab_titles

    dlg.close()


#: No settings page may be taller than this. **This number may only go DOWN.**
#:
#: Same direction as the code-health ratchet, and for the same reason: it needs
#: no theory of the right page height, only that pages must not keep growing.
#:
#: Set from measurement, 2026-09-01. Interface had reached **1138px** against a
#: ~600px norm for every other page — owner: "the settings->Interface is really
#: too tall/long ... it should be half that height, so break up whatever
#: settings sections are 'too tall'". Splitting Sidebar (418px, 39% of it, and
#: growing a row per sidebar section) and Watch Alerts onto their own pages took
#: Interface to 622px, in line with Metadata (607) and Recommendations (583).
#:
#: The ceiling sits just above Playback (768px), which is NOT split: 445px of it
#: is one cohesive "Player" group, and breaking a single idea across two pages
#: to satisfy a number would be worse than the height.
_MAX_PAGE_HEIGHT_PX = 800


def test_no_settings_page_is_too_tall(qapp):
    """The requirement behind the split, stated so it applies to future pages too.

    Replaces a test that asserted there must be no section named "Sidebar"
    because "its content moved into Interface". That merge is precisely what
    produced the 1138px page, and the owner has reversed it — so the rule is
    now the one that was actually wanted, and it holds for every page rather
    than naming one.
    """
    from metatv.gui.settings_dialog import _SECTIONS

    dlg = SettingsDialog(_FakeConfig(), parent=None)
    too_tall = []
    for _sid, label, builder in _SECTIONS:
        height = getattr(dlg, builder)().sizeHint().height()
        if height > _MAX_PAGE_HEIGHT_PX:
            too_tall.append(f"{label} ({height}px)")
    dlg.close()

    assert not too_tall, (
        f"settings pages over {_MAX_PAGE_HEIGHT_PX}px: {', '.join(too_tall)}. "
        "Split the page along a group boundary, or move a group to a page of "
        "its own — do not raise the ceiling.")


def test_the_sidebar_and_alerts_pages_exist_and_carry_their_groups(qapp):
    """The split actually moved the groups, rather than duplicating them."""
    from PyQt6.QtWidgets import QGroupBox

    from metatv.gui.settings_dialog import _SECTIONS

    dlg = SettingsDialog(_FakeConfig(), parent=None)
    # The pages are held in `built` while their titles are read: an unparented
    # QWidget is collected the moment the last Python reference drops, and its
    # QGroupBox children go with it — "wrapped C/C++ object has been deleted".
    built = {label: getattr(dlg, builder)() for _sid, label, builder in _SECTIONS}
    titles = {label: [g.title() for g in page.findChildren(QGroupBox)]
              for label, page in built.items()}
    dlg.close()

    assert "Sidebar" in titles["Sidebar"]
    assert "Watch Alerts" in titles["Watch Alerts"]
    assert "Sidebar" not in titles["Interface"], "the Sidebar group is on two pages"
    assert "Watch Alerts" not in titles["Interface"], "the Watch Alerts group is on two pages"


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
