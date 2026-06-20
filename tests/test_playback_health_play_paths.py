"""Every play path must arm the live playback-health readout.

Regression guard for the blank-stats bug: the readout (buffer/bitrate/drops in
the bottom nav) is driven by ``_start_playback_health()``. It used to be armed
only by the channel-list path (``play_media`` → ``_on_stream_ready``); the EPG
"play this channel" action went through a stripped-down ``play_special_event``
duplicate, and the episode path through ``_do_launch_episode`` — neither armed
the readout, so playing a special event or an episode left the stats blank.

``play_special_event`` is now deleted (EPG routes through ``play_media``), and
the episode path arms the readout directly. These tests execute the two
main-thread slots that finish a launch and assert the readout is armed on
success.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _bare_window(qapp):
    """A MainWindow shell with the attributes the launch slots touch mocked."""
    from metatv.gui import main_window as mw_module

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.player_manager = MagicMock()
    win.player_manager.play.return_value = True          # play succeeds
    win.executor = MagicMock()                           # _bg_mark_played submit → no-op
    win.status_bar = MagicMock()
    win.notification_manager = MagicMock()
    win.loading_channels = set()
    win.stream_retry_manager = MagicMock()               # failure path records here
    win.load_history = MagicMock()
    win.load_favorites = MagicMock()
    win._refresh_queue_section = MagicMock()
    win._start_playback_health = MagicMock()             # the thing under test
    return win


def test_on_stream_ready_arms_health_readout_on_success(qapp):
    """play_media's completion slot (the chokepoint EPG now uses) arms the readout."""
    win = _bare_window(qapp)

    win._on_stream_ready({
        "channel_id": "c1",
        "channel_name": "SA| SUPERSPORT FOOTBALL FHD",
        "final_url": "http://host/live/1.ts",
        "original_url": "http://host/live/1.ts",
        "provider_id": "p1",
        "notif_id": "n1",
        "ok": True,
    })

    win._start_playback_health.assert_called_once()


def test_on_stream_ready_does_not_arm_on_failure(qapp):
    """A failed validation must NOT arm the readout (nothing is playing)."""
    win = _bare_window(qapp)

    win._on_stream_ready({
        "channel_id": "c1",
        "channel_name": "Dead Channel",
        "final_url": "",
        "original_url": "http://host/dead.ts",
        "stream_err": "all URLs failed",
        "notif_id": "n1",
        "ok": False,
    })

    win._start_playback_health.assert_not_called()


def test_do_launch_episode_arms_health_readout(qapp):
    """The episode path arms the readout when mpv accepts the stream."""
    win = _bare_window(qapp)

    win._do_launch_episode("n1", "http://host/ep1.ts", "Show S01E01", queue_episodes=None)

    win.player_manager.play.assert_called_once()
    win._start_playback_health.assert_called_once()


def test_do_launch_episode_does_not_arm_when_play_fails(qapp):
    """If mpv refuses the stream, the readout is not armed."""
    win = _bare_window(qapp)
    win.player_manager.play.return_value = False

    win._do_launch_episode("n1", "http://host/ep1.ts", "Show S01E01", queue_episodes=None)

    win._start_playback_health.assert_not_called()


def test_play_special_event_is_gone():
    """The legacy duplicate path is removed — EPG must route through play_media."""
    from metatv.gui.main_window import MainWindow
    assert not hasattr(MainWindow, "play_special_event"), (
        "play_special_event was deleted; EPG play routes through play_media"
    )
