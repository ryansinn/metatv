"""``maybe_show_whats_new`` must not auto-replay the changelog under METATV_DEV.

The dev/QA harness launches the app to exercise features and routinely runs a
fresh isolated config (``last_seen_whats_new_id == 0``), which would otherwise
pop every historical What's New entry (~180) on every launch. The auto-dialog is
suppressed in dev mode; the Help menu entry still works.

These exercise the method directly on a ``__new__``'d window (the heavy
``__init__`` is irrelevant to this branch), so no full construction is needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PyQt6")

from metatv.gui.main_window import MainWindow


def _bare_window() -> MainWindow:
    win = MainWindow.__new__(MainWindow)  # skip __init__; only maybe_show_whats_new matters
    win._whats_new_checked = False
    win.config = MagicMock()
    win.config.last_seen_whats_new_id = 0  # fresh cursor → every entry is "unseen"
    return win


def test_auto_dialog_suppressed_in_dev_mode(monkeypatch):
    win = _bare_window()
    monkeypatch.setattr("metatv.gui.main_window._dev_mode_enabled", lambda: True)
    with patch("metatv.gui.main_window.WhatsNewDialog") as Dlg:
        win.maybe_show_whats_new()
    Dlg.assert_not_called()  # dev harness must never replay the historical changelog


def test_auto_dialog_shows_for_real_users_when_unseen(monkeypatch):
    win = _bare_window()
    # A real user mid-upgrade: non-zero cursor with unseen entries above it.
    # (Cursor 0 is now the fresh-install fast-forward case — tested below.)
    win.config.last_seen_whats_new_id = 1
    monkeypatch.setattr("metatv.gui.main_window._dev_mode_enabled", lambda: False)
    with patch("metatv.gui.main_window.WhatsNewDialog") as Dlg:
        Dlg.return_value.exec = MagicMock()
        win.maybe_show_whats_new()
    Dlg.assert_called_once()  # a genuine unseen cursor still surfaces the dialog


def test_fresh_config_fast_forwards_without_dialog(monkeypatch):
    """Normal mode + cursor 0 (just-created config) → no replay; cursor jumps to latest."""
    monkeypatch.delenv("METATV_DEV", raising=False)
    win = _bare_window()
    with patch("metatv.gui.main_window.WhatsNewDialog") as dlg, \
         patch("metatv.gui.main_window._whats_new.latest_id", return_value=213):
        win.maybe_show_whats_new()
    dlg.assert_not_called()
    assert win.config.last_seen_whats_new_id == 213
    win.config.save.assert_called_once()


def test_upgrade_delta_still_shows(monkeypatch):
    """Non-zero cursor with unseen entries keeps showing the delta dialog."""
    monkeypatch.delenv("METATV_DEV", raising=False)
    win = _bare_window()
    win.config.last_seen_whats_new_id = 200
    win._whats_new_unseen = MagicMock(return_value=[MagicMock()])
    with patch("metatv.gui.main_window.WhatsNewDialog") as dlg:
        dlg.return_value.exec.return_value = None
        win.maybe_show_whats_new()
    dlg.assert_called_once()
