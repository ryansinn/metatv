"""Tools ▸ Open config folder — the only in-app route to config.yaml and the logs.

Support questions repeatedly need one of two files: ``config.yaml`` (which holds
the migration versions, so it says whether a one-time pass actually ran) and the
logs beside it. Until this action there was no way to reach either from the app;
a user had to be told a hidden path and find it themselves.

The FOLDER is opened rather than the file. A ``.yaml`` has no registered handler
on many systems — opening it can silently do nothing — the logs live in the same
directory, and revealing a directory cannot drop an editor onto a file the user
did not mean to change.
"""

from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.config import Config
from metatv.gui import icons as _icons
from metatv.gui.main_window import MainWindow


@pytest.fixture()
def host(tmp_path):
    """A MainWindow skeleton carrying only what the handler touches."""
    mw = MainWindow.__new__(MainWindow)
    mw.config = Config(config_dir=tmp_path / "cfg")
    mw.notification_manager = MagicMock()
    return mw


def test_it_opens_the_config_directory(host):
    with patch("PyQt6.QtGui.QDesktopServices.openUrl", return_value=True) as opened:
        host.open_config_folder()
    assert opened.called, "nothing was opened"
    url = opened.call_args[0][0]
    assert url.toLocalFile().rstrip("/") == str(host.config.config_dir).rstrip("/"), (
        f"opened {url.toLocalFile()!r}, expected the config dir"
    )


def test_it_opens_the_folder_not_the_yaml(host):
    """A .yaml often has no handler; the logs are in the folder anyway."""
    with patch("PyQt6.QtGui.QDesktopServices.openUrl", return_value=True) as opened:
        host.open_config_folder()
    assert not opened.call_args[0][0].toLocalFile().endswith(".yaml")


def test_a_missing_config_folder_is_created_first(host):
    """Opening a path that does not exist yet would just fail."""
    assert not host.config.config_dir.exists()
    with patch("PyQt6.QtGui.QDesktopServices.openUrl", return_value=True):
        host.open_config_folder()
    assert host.config.config_dir.exists()


def test_when_no_file_manager_answers_the_path_is_shown(host):
    """The path is the useful half — never fail silently.

    Headless sessions, minimal desktops and sandboxes all return False here.
    """
    with patch("PyQt6.QtGui.QDesktopServices.openUrl", return_value=False):
        host.open_config_folder()
    assert host.notification_manager.show.called, (
        "the action did nothing and said nothing"
    )
    message = host.notification_manager.show.call_args[0][0]
    assert str(host.config.config_dir) in message, (
        f"the notification must name the path; got {message!r}"
    )


def test_success_does_not_also_nag(host):
    with patch("PyQt6.QtGui.QDesktopServices.openUrl", return_value=True):
        host.open_config_folder()
    assert not host.notification_manager.show.called


def test_an_unwritable_config_dir_still_reports_the_path(host, monkeypatch):
    """mkdir failing must not abort before the user learns where to look."""
    def boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(pathlib.Path, "mkdir", boom)
    with patch("PyQt6.QtGui.QDesktopServices.openUrl", return_value=False):
        host.open_config_folder()          # must not raise
    assert host.notification_manager.show.called


def test_the_action_uses_the_shared_icon_registry():
    """No literal glyph in widget code (CLAUDE.md)."""
    assert _icons.config_folder_icon, "the icon must be defined in icons.py"
    src = pathlib.Path(
        MainWindow.__module__.replace(".", "/") + ".py"
    )
    text = src.read_text(encoding="utf-8")
    assert "config_folder_icon" in text
    assert "📂" not in text, "the glyph belongs in icons.py, not the menu code"
