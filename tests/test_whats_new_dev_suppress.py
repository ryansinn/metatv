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
    monkeypatch.setattr("metatv.gui.main_window._dev_mode_enabled", lambda: False)
    with patch("metatv.gui.main_window.WhatsNewDialog") as Dlg:
        Dlg.return_value.exec = MagicMock()
        win.maybe_show_whats_new()
    Dlg.assert_called_once()  # a genuine unseen cursor still surfaces the dialog
