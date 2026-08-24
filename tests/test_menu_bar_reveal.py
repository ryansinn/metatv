"""The menu bar, optionally hidden until Alt — and the way back.

This behaviour was built once and reversed by the owner: *"leave the menu
visible, because otherwise it's fucked on other platforms."* It returns only as
an opt-in, refused on macOS, with an off-switch that is reachable **while the
menu bar is hidden** — because a setting whose only off-switch is behind the
thing it switched off is a trap, and that is the failure mode worth testing.
"""

from __future__ import annotations

import pathlib

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from metatv.gui import menu_bar_reveal


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    from PyQt6.QtWidgets import QApplication

    home = tmp_path_factory.mktemp("home")
    for sub in (".config/metatv", ".local/share/metatv", ".cache/metatv"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    real_home = pathlib.Path.home
    pathlib.Path.home = staticmethod(lambda: home)

    app = QApplication.instance() or QApplication([])
    from metatv.core.config import Config
    from metatv.core.migration_manager import MigrationManager
    from metatv.gui.main_window import MainWindow

    real_run = MigrationManager.run_pending
    MigrationManager.run_pending = lambda self, *a, **k: None

    config, _ = Config.load()
    win = MainWindow(config)
    win.resize(1280, 800)
    win.show()
    app.processEvents()
    try:
        yield win
    finally:
        win.close()
        app.processEvents()
        MigrationManager.run_pending = real_run
        pathlib.Path.home = real_home


@pytest.fixture(autouse=True)
def _visible_again(window):
    """Every test leaves the menu bar visible — a broken one strands the rest."""
    yield
    window.set_menu_bar_auto_hide(False)


def _alt(window):
    window.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier))
    window.keyReleaseEvent(QKeyEvent(
        QKeyEvent.Type.KeyRelease, Qt.Key.Key_Alt, Qt.KeyboardModifier.NoModifier))


def test_the_menu_bar_is_visible_by_default(window):
    """The owner's reversal is the DEFAULT, not merely the recommendation."""
    assert not window.config.menu_bar_auto_hide
    assert window.menuBar().isVisible()


def test_turning_it_on_hides_the_bar_and_alt_brings_it_back(window):
    window.set_menu_bar_auto_hide(True)
    assert not window.menuBar().isVisible(), "the setting did not apply"

    _alt(window)
    assert window.menuBar().isVisible(), "Alt did not reveal the menu bar"

    _alt(window)
    assert not window.menuBar().isVisible(), "Alt did not hide it again"


def test_escape_closes_a_bar_revealed_by_accident(window):
    window.set_menu_bar_auto_hide(True)
    _alt(window)
    assert window.menuBar().isVisible()

    window.keyReleaseEvent(QKeyEvent(
        QKeyEvent.Type.KeyRelease, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not window.menuBar().isVisible()


def test_alt_as_a_mnemonic_does_not_also_toggle(window):
    """Alt+F opens File. It must not ALSO flip the bar out from under it."""
    window.set_menu_bar_auto_hide(True)
    window.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier))
    window.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier))
    window.keyReleaseEvent(QKeyEvent(
        QKeyEvent.Type.KeyRelease, Qt.Key.Key_Alt, Qt.KeyboardModifier.NoModifier))

    assert not window.menuBar().isVisible(), (
        "Alt+F toggled the bar — the release handler ignored that another key "
        "was pressed in between"
    )


def test_turning_it_off_restores_the_bar_even_while_hidden(window):
    """Nobody may be left with no menu."""
    window.set_menu_bar_auto_hide(True)
    assert not window.menuBar().isVisible()

    window.set_menu_bar_auto_hide(False)
    assert window.menuBar().isVisible()


# ── The escape hatch ─────────────────────────────────────────────────────────

def test_the_off_switch_lives_in_the_menu_the_header_can_open(window):
    """The whole reason this is safe to ship.

    The header's Tools button opens the menu bar's OWN Tools menu, so an entry
    there is reachable with the bar hidden. Assert it is in that exact menu —
    not merely that an action exists somewhere.
    """
    action = window._menu_always_visible_action
    assert action in window._tools_menu.actions(), (
        "the off-switch is not in the Tools menu — with the bar hidden there "
        "would be no way back to it"
    )


def test_the_tools_toggle_turns_auto_hide_off(window):
    window.set_menu_bar_auto_hide(True)
    assert not window.menuBar().isVisible()

    window._menu_always_visible_action.setChecked(True)   # "always visible"

    assert not window.config.menu_bar_auto_hide
    assert window.menuBar().isVisible()


def test_the_tools_tick_is_read_from_the_setting_not_a_cached_flag(window):
    window.set_menu_bar_auto_hide(True)
    window.sync_menu_bar_actions()
    assert window._menu_always_visible_action.isChecked() is False

    window.set_menu_bar_auto_hide(False)
    window.sync_menu_bar_actions()
    assert window._menu_always_visible_action.isChecked() is True


def test_settings_and_the_tools_toggle_drive_the_same_setting(window):
    """Two surfaces, one seam — they cannot disagree."""
    window.set_menu_bar_auto_hide(True)
    assert window.config.menu_bar_auto_hide is True
    assert window._menu_always_visible_action.isChecked() is False

    window._menu_always_visible_action.setChecked(True)
    assert window.config.menu_bar_auto_hide is False


# ── The platform guard ───────────────────────────────────────────────────────

def test_macos_cannot_turn_it_on_however_config_is_written(monkeypatch, window):
    """The guard is in the code path, not in the settings UI.

    A UI-only guard is one a future call site routes around. On macOS the menu
    bar is the system bar; there is nothing in the window to hide.
    """
    monkeypatch.setattr(menu_bar_reveal.sys, "platform", "darwin")
    window.config.menu_bar_auto_hide = True          # as if carried in config
    assert window.menu_bar_auto_hide() is False
    window.apply_menu_bar_auto_hide()
    assert window.menuBar().isVisible(), "the menu bar was hidden on macOS"


def test_alt_does_nothing_when_the_setting_is_off(window):
    """No surprise behaviour for the default user."""
    assert not window.config.menu_bar_auto_hide
    _alt(window)
    assert window.menuBar().isVisible()
