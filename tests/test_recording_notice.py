"""The persistent "recording in progress" notice (Catch, Keep, Record Q1).

Settled 2026-08-30: "While recording, one persistent notification carries
elapsed, remaining, disk used and free, the programme, and a Watch button."
``MainWindow._refresh_recording_notifications`` (main_window_downloads.py) is
the chokepoint — one card per actively-recording row, UPDATED in place each
tick (never re-``show``n), dismissed the moment the row leaves the recording
state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ProviderDB
from metatv.core.recording_manager import RecordingProgress
from tests.conftest import make_downloads_mixin_host

NOW = datetime(2026, 9, 5, 19, 0, 0)


class _Config:
    """Only what recordings_dir()/library_dir() read."""
    def __init__(self, tmp_path):
        self.download_dir = str(tmp_path / "library")


@pytest.fixture()
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'notice.db'}")
    database.create_tables()
    with database.session_scope() as session:
        session.add(ProviderDB(id="p1", name="Shark", type="xtream", url="http://x"))
    return database


@pytest.fixture()
def host(db, tmp_path):
    return make_downloads_mixin_host(db, _Config(tmp_path))


def _recording(**kw) -> RecordingProgress:
    base = {
        "recording_id": "r1", "channel_id": "c1", "channel_name": "BBC One",
        "programme_title": "The Match", "state": "recording",
        "starts_at": NOW - timedelta(hours=1), "ends_at": NOW + timedelta(hours=1),
        "recorded_bytes": 2_000_000_000, "dest_path": "/lib/Recordings/x.ts",
        "error": None, "waiting_for_slot": False, "provider_id": "p1",
        "programme_end": NOW + timedelta(minutes=45),
    }
    base.update(kw)
    return RecordingProgress(**base)


def test_a_recording_row_shows_one_persistent_non_dismissible_notice(host):
    host._refresh_recording_notifications([_recording()], now=NOW)

    host.notification_manager.show.assert_called_once()
    kwargs = host.notification_manager.show.call_args.kwargs
    assert kwargs["dismissible"] is False, "Q1: persistent, not auto-closing"
    assert "RECORDING" in kwargs["title"]
    assert "The Match" in kwargs["title"]
    assert "1:00:00" in kwargs["message"], "elapsed H:MM:SS"
    assert "GB used" in kwargs["message"] and "GB free" in kwargs["message"]
    assert "Shark" in kwargs["message"], "names the SOURCE, not the channel"


def test_the_two_actions_are_watch_keep_open_and_stop_dismissing(host):
    host._refresh_recording_notifications([_recording()], now=NOW)
    actions = host.notification_manager.show.call_args.kwargs["actions"]
    assert [a[0] for a in actions] == ["Watch", "Stop"]

    watch_label, watch_cb, watch_keep_open = actions[0]
    assert watch_keep_open is True, "Watch must not close the persistent card"
    assert len(actions[1]) == 2, "Stop is the DEFAULT (dismissing) 2-tuple shape"
    stop_cb = actions[1][1]

    # The callbacks are closures over THIS recording_id and route to the real
    # _watch_recording/_cancel_recording — patched here only to isolate the
    # routing from those methods' own (separately covered) behaviour.
    host._watch_recording = MagicMock()
    watch_cb()
    host._watch_recording.assert_called_once_with("r1")

    host._cancel_recording = MagicMock()
    stop_cb()
    host._cancel_recording.assert_called_once_with("r1")


def test_a_second_tick_updates_the_same_card_rather_than_showing_a_new_one(host):
    """Q1's "persistent" means ONE card across ticks — update, not re-show."""
    host.notification_manager.show.return_value = "notif-abc"
    host._refresh_recording_notifications([_recording()], now=NOW)
    host.notification_manager.show.assert_called_once()

    later = _recording(recorded_bytes=3_000_000_000)
    host._refresh_recording_notifications([later], now=NOW)

    host.notification_manager.show.assert_called_once(), "still only ONE show() ever"
    host.notification_manager.update.assert_called_once()
    assert host.notification_manager.update.call_args.args[0] == "notif-abc"


def test_the_card_is_dismissed_once_the_recording_stops(host):
    host.notification_manager.show.return_value = "notif-abc"
    host._refresh_recording_notifications([_recording()], now=NOW)

    host._refresh_recording_notifications([_recording(state="completed")])

    host.notification_manager.dismiss.assert_called_once_with("notif-abc")
    assert host._recording_notif_ids == {}


def test_a_scheduled_not_yet_recording_row_shows_no_notice(host):
    """Only state == "recording" gets the persistent card — "scheduled" is the
    Rec-column indicator's job, not a notification."""
    host._refresh_recording_notifications([_recording(state="scheduled")])
    host.notification_manager.show.assert_not_called()
