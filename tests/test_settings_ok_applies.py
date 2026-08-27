"""OK applies the settings it saved, and the Style menu keeps up.

The report (owner, UX-testing 2026-08-21), reproduced end to end below:

    changing the results style (comfy, etc) in Settings and clicking OK doesn't
    seem to apply the setting. and then the top menu style doesn't update, and
    changing to the same results style from the top menu does nothing —
    presumably because the system thinks it's already set to that style.
    changing to another style with the top menu then does change it.

Two separate defects, and the second is what made the first look permanent.

1. **OK saved without applying.** ``settings_applied`` was documented as
   "emitted on Apply (not OK — OK closes the dialog)", and the host compensated
   by re-running some handlers after ``exec()`` returned. It re-ran three of the
   five it had connected, so OK silently dropped row density, poster
   thumbnails, platform-name style and collapse-variants. Apply worked; OK did
   not — which is backwards, since OK is the button that reads as "commit".

2. **The Style menu never re-read config.** Its actions were checked once at
   construction. After Settings changed the value the menu still showed the old
   one ticked, and picking the value Settings had actually set hit the
   ``if config == value: return`` early-return in ``_set_density_from_menu`` and
   did nothing at all. Picking a *different* value worked, which is exactly the
   "then it starts working" the report describes.

Both are the same shape: a hand-maintained list standing in for the thing it
was copied from. The fix deletes both lists rather than extending them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from metatv.gui.main_window import MainWindow
from metatv.gui.settings_dialog import SettingsDialog
from tests.conftest import wire_style_menu_actions


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _config(tmp_path):
    from metatv.core.config import Config
    return Config(config_dir=tmp_path)


def _host(qapp, config):
    """A MainWindow-shaped double carrying the real density + menu seams."""
    from metatv.gui.channel_list_delegate import ChannelRowDelegate

    host = SimpleNamespace(config=config)
    host._channel_row_delegate = ChannelRowDelegate()
    host.channel_model = SimpleNamespace(
        layoutChanged=SimpleNamespace(emit=lambda: host._emitted.append(True))
    )
    host._emitted = []
    wire_style_menu_actions(host)
    host._apply_channel_list_density = (
        MainWindow._apply_channel_list_density.__get__(host)
    )
    host._set_density_from_menu = MainWindow._set_density_from_menu.__get__(host)
    return host


def _checked(group) -> str | None:
    for action in group.actions():
        if action.isChecked():
            return action.data()
    return None


# ---------------------------------------------------------------------------
# 1. OK applies (the reported bug)
# ---------------------------------------------------------------------------

def test_ok_emits_settings_applied_so_the_change_takes_effect(qapp, tmp_path):
    """FAILS pre-fix: ``_accept`` called ``_save_values`` and closed, silently."""
    dlg = SettingsDialog.__new__(SettingsDialog)
    SettingsDialog.__init__(dlg, _config(tmp_path), None)

    fired: list[bool] = []
    dlg.settings_applied.connect(lambda: fired.append(True))
    dlg._accept()

    assert fired == [True], (
        "OK must apply what it saved — Apply-only means the button that reads "
        "as 'commit' is the weaker of the two"
    )


def test_ok_and_apply_agree(qapp, tmp_path):
    """Whatever OK does, Apply does — they differ only in closing the dialog."""
    dlg = SettingsDialog.__new__(SettingsDialog)
    SettingsDialog.__init__(dlg, _config(tmp_path), None)

    fired: list[str] = []
    dlg.settings_applied.connect(lambda: fired.append("x"))
    dlg._apply()
    after_apply = len(fired)
    dlg._accept()

    assert after_apply == 1 and len(fired) == 2


def test_the_density_the_dialog_saved_reaches_the_delegate(qapp, tmp_path):
    """The full reported path: pick a density, click OK, list re-renders.

    FAILS pre-fix — the config value changed and the delegate never heard.
    """
    config = _config(tmp_path)
    config.channel_list_density = "comfy"
    host = _host(qapp, config)
    host._channel_row_delegate.set_density("comfy")

    dlg = SettingsDialog.__new__(SettingsDialog)
    SettingsDialog.__init__(dlg, config, None)
    dlg.settings_applied.connect(lambda: host._apply_channel_list_density())

    idx = dlg._channel_density_combo.findData("compact")
    assert idx >= 0, "the Interface tab must offer Compact"
    dlg._channel_density_combo.setCurrentIndex(idx)
    dlg._accept()

    assert config.channel_list_density == "compact"
    assert host._channel_row_delegate.density == "compact", (
        "OK saved the density but never applied it — the list kept the old rows"
    )


# ---------------------------------------------------------------------------
# 2. The Style menu keeps up (what made it look permanently stuck)
# ---------------------------------------------------------------------------

def test_the_style_menu_reflects_a_density_set_from_settings(qapp, tmp_path):
    """FAILS pre-fix: menu ticks were set once at construction and never re-read."""
    config = _config(tmp_path)
    config.channel_list_density = "comfy"
    host = _host(qapp, config)
    for action in host._density_action_group.actions():
        action.setChecked(action.data() == "comfy")

    config.channel_list_density = "compact"   # as Settings would have saved it
    host._apply_channel_list_density()

    assert _checked(host._density_action_group) == "compact"


def test_picking_the_value_settings_set_is_not_a_dead_click(qapp, tmp_path):
    """The exact sequence from the report.

    Settings sets Compact but (pre-fix) nothing applies and the menu still says
    Comfy. The user picks Compact from the menu to make it take — and gets
    nothing, because config already says "compact" so the handler early-returns.
    With the menu synced, Compact is already ticked: there is no dead click to
    make, and the list is already Compact.
    """
    config = _config(tmp_path)
    config.channel_list_density = "comfy"
    host = _host(qapp, config)
    host._channel_row_delegate.set_density("comfy")

    # Settings → Compact → OK.
    config.channel_list_density = "compact"
    host._apply_channel_list_density()

    assert host._channel_row_delegate.density == "compact"
    assert _checked(host._density_action_group) == "compact", (
        "the menu must already show Compact, so the user never reaches for the "
        "no-op click that made this look broken"
    )

    # And the menu still works normally from there.
    host._set_density_from_menu("comfy_plus")
    assert host._channel_row_delegate.density == "comfy_plus"
    assert _checked(host._density_action_group) == "comfy_plus"


def test_thumbnails_and_platform_style_ticks_also_follow_config(qapp, tmp_path):
    """Every Style-menu entry is a view of config, not just density."""
    config = _config(tmp_path)
    config.channel_list_thumbnails = True
    config.platform_name_style = "auto"
    host = _host(qapp, config)
    host._thumbs_action.setChecked(True)

    config.channel_list_thumbnails = False
    config.platform_name_style = "short"
    host._apply_channel_list_density()

    assert host._thumbs_action.isChecked() is False
    assert _checked(host._platform_action_group) == "short"


def test_syncing_the_thumbnail_tick_does_not_re_enter_its_handler(qapp, tmp_path):
    """Signals are blocked while syncing — the view must not drive the model.

    This targets the thumbnails action specifically, because it is the one
    where the block is load-bearing: it is connected to ``toggled``, which
    ``setChecked`` DOES emit. Without the block, syncing it to a changed value
    calls ``_set_thumbnails_from_menu``, which writes config and calls
    ``_apply_channel_list_density`` — straight back into this sync.

    (The radio groups are connected to ``triggered``, which ``setChecked`` does
    not emit, so their block is belt-and-braces rather than load-bearing. Said
    plainly here so nobody reads this test as proving something it does not.)
    """
    config = _config(tmp_path)
    config.channel_list_thumbnails = True
    host = _host(qapp, config)
    host._thumbs_action.setChecked(True)

    calls: list[bool] = []
    host._set_thumbnails_from_menu = calls.append
    host._thumbs_action.toggled.connect(host._set_thumbnails_from_menu)

    config.channel_list_thumbnails = False   # as Settings would have saved it
    host._apply_channel_list_density()

    assert host._thumbs_action.isChecked() is False, "the tick must follow config"
    assert calls == [], (
        f"syncing the tick re-entered its own handler: {calls} — that write "
        f"loops back into _apply_channel_list_density"
    )


# ---------------------------------------------------------------------------
# 3. The connections ARE the list
# ---------------------------------------------------------------------------

def test_every_settings_applied_handler_exists_on_main_window():
    """The conftest factory and MainWindow must name the same hooks.

    The bug underneath both defects was a hand-written list that fell behind
    the connections it mirrored. This asserts the remaining list — the test
    factory's — still matches reality, so a hook renamed in production shows up
    here instead of as a mysteriously dead setting.
    """
    from tests.conftest import _SETTINGS_APPLIED_HOOKS

    missing = [h for h in _SETTINGS_APPLIED_HOOKS if not hasattr(MainWindow, h)]
    assert not missing, (
        f"these hooks no longer exist on MainWindow: {missing} — update "
        f"_SETTINGS_APPLIED_HOOKS in tests/conftest.py"
    )


def test_open_settings_connects_every_hook_it_needs(qapp):
    """``open_settings`` must connect each hook the factory stubs.

    Reads the source rather than running the dialog: the point is that the set
    of connections has not quietly diverged from the set every test double
    prepares for.
    """
    import inspect

    from tests.conftest import _SETTINGS_APPLIED_HOOKS

    src = inspect.getsource(MainWindow.open_settings)
    unconnected = [
        h for h in _SETTINGS_APPLIED_HOOKS
        if f"settings_applied.connect(self.{h})" not in src
    ]
    assert not unconnected, (
        f"connected nowhere in open_settings: {unconnected}"
    )
