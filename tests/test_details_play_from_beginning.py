"""Regression test: the details-pane Play button starts from the BEGINNING.

#259 wired ``details_pane.play_requested`` to ``play_channel_by_id`` — but that path
honors the default ``playback_resume_mode='resume'``, so the explicit Play button
silently RESUMED instead of starting over (both Play and Resume resumed). The fix
routes Play through ``play_channel_from_beginning_by_id`` while Resume keeps
``play_channel_resume_by_id``. This executes the real ``_connect_details_play_signals``
wiring so a revert to the resume path fails the test.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _DetailsSignalsStub:
    """Minimal stand-in exposing the three play-related details signals."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal

        class _Sigs(QObject):
            play_requested = pyqtSignal(str)
            resume_requested = pyqtSignal(str)
            play_version_requested = pyqtSignal(str)

        self._o = _Sigs()
        self.play_requested = self._o.play_requested
        self.resume_requested = self._o.resume_requested
        self.play_version_requested = self._o.play_version_requested


def _host():
    from metatv.gui.main_window import MainWindow
    host = MainWindow.__new__(MainWindow)
    host.play_channel_by_id = MagicMock()
    host.play_channel_from_beginning_by_id = MagicMock()
    host.play_channel_resume_by_id = MagicMock()
    host.details_pane = _DetailsSignalsStub()
    return host


def test_play_button_routes_to_from_beginning(qapp):
    """play_requested must call play_channel_from_beginning_by_id, NOT the resume-aware path."""
    from metatv.gui.main_window import MainWindow
    host = _host()
    MainWindow._connect_details_play_signals(host)

    host.details_pane.play_requested.emit("ch1")

    host.play_channel_from_beginning_by_id.assert_called_once_with("ch1")
    host.play_channel_by_id.assert_not_called()  # the resume-honoring path must NOT fire for Play


def test_resume_button_routes_to_resume(qapp):
    """resume_requested must call play_channel_resume_by_id."""
    from metatv.gui.main_window import MainWindow
    host = _host()
    MainWindow._connect_details_play_signals(host)

    host.details_pane.resume_requested.emit("ch9")

    host.play_channel_resume_by_id.assert_called_once_with("ch9")
    host.play_channel_from_beginning_by_id.assert_not_called()


def test_variant_chip_uses_resume_aware_default(qapp):
    """play_version_requested keeps the resume-aware default (play_channel_by_id)."""
    from metatv.gui.main_window import MainWindow
    host = _host()
    MainWindow._connect_details_play_signals(host)

    host.details_pane.play_version_requested.emit("ch5")

    host.play_channel_by_id.assert_called_once_with("ch5")
