"""Waiting out a source's connection limit, then starting the title (Source Analytics Q7).

A 458/509 while MetaTV holds nothing from the source is a stream the source is
still counting. The wait checks the account endpoint, starts the title when a
connection frees, records how long that took, and the Analytics tab reports it.
Real ``Database`` on a ``tmp_path`` file; the account check is a fake thread that
answers at once, so the real ``poll`` → ``on_checked`` path runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from metatv.core.database import Database, ProviderDB
from metatv.core.playback_models import ConnectionHoldDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui import connection_wait
from metatv.gui import playback_start_watch as watch
from metatv.gui.playback_start_watch import FAILED_AFTER_TICKS, PlayAttempt

ATTEMPT = PlayAttempt("ch-1", "Futurama S01E01", "http://x/1.ts", provider_id="trex")


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    with d.session_scope() as s:
        s.add(ProviderDB(id="trex", name="TREX", type="xtream", url="http://t", username="u",
                         password="p", max_connections=1, account_active_cons=1))
    yield d
    d.close()


def _host(db, *, ours=()):
    def run_query(fn, on_result, commit=False, on_error=None, **_kw):
        with db.session_scope() as s:
            on_result(fn(RepositoryFactory(s)))
    host = SimpleNamespace(db=db, notification_manager=MagicMock(), status=MagicMock(),
                           play_channel_by_id=MagicMock(), _run_query=run_query,
                           stream_retry_manager=MagicMock(),
                           _provider_display_name=lambda pid: "TREX")
    host.notification_manager.show.return_value = "notif-wait"
    host.player_manager = MagicMock()
    host.player_manager.resolve_key.return_value = "trex-key"
    host.player_manager.connection_accountant.holders.return_value = [
        SimpleNamespace(holder_id=h) for h in ours]
    return host


class _FakeAccountThread(QObject):
    """Stands in for FetchAccountInfoThread: answers on start() with the next reply."""
    finished = pyqtSignal(bool, object)
    replies: list = []

    def __init__(self, provider):
        super().__init__()

    def start(self):
        self.finished.emit(True, _FakeAccountThread.replies.pop(0))

    def wait(self, _ms):
        return True


@pytest.fixture()
def fake_account(monkeypatch):
    monkeypatch.setattr("metatv.gui.provider_editor.FetchAccountInfoThread", _FakeAccountThread)
    return _FakeAccountThread.replies


def _refuse(host):
    with patch("metatv.gui.playback_start_watch._http_refusal", return_value=509):
        watch.arm(host, ATTEMPT)
        for _ in range(FAILED_AFTER_TICKS):
            watch.on_idle_tick(host)


def test_a_refusal_starts_a_wait_instead_of_the_failure_toast(qapp, db):
    host = _host(db)
    _refuse(host)
    wait = host._connection_wait
    titles = [c.kwargs["title"] for c in host.notification_manager.show.call_args_list]
    assert titles == ["Waiting for a connection on TREX"], "no 'Stream did not start' alongside"
    kwargs = host.notification_manager.show.call_args.kwargs
    assert kwargs["dismissible"] is False and kwargs["actions"][0][0] == "Cancel"
    assert wait.timer.isActive() and wait.timer.interval() == 30_000
    host.stream_retry_manager.add_failure.assert_not_called()
    connection_wait.cancel(host)


def test_when_metatv_itself_holds_the_source_it_does_not_wait(qapp, db):
    host = _host(db, ours=["trex-other-window"])
    _refuse(host)
    assert "_connection_wait" not in host.__dict__
    assert host.notification_manager.show.call_args.kwargs["title"] == "Stream did not start"


def test_a_freed_connection_starts_the_title_and_records_the_hold(qapp, db, fake_account):
    host = _host(db)
    _refuse(host)
    wait = host._connection_wait
    wait.refused_at -= timedelta(minutes=22)
    fake_account[:] = [{"active_cons": 1, "max_connections": 1}]
    wait.poll()                                    # still full: keeps waiting
    host.play_channel_by_id.assert_not_called()
    assert host._connection_wait is wait
    fake_account[:] = [{"active_cons": 0, "max_connections": 1}]
    wait.poll()
    host.play_channel_by_id.assert_called_once_with("ch-1")
    host.notification_manager.dismiss.assert_called_with("notif-wait")
    assert "_connection_wait" not in host.__dict__
    with db.session_scope(commit=False) as s:
        [hold] = s.query(ConnectionHoldDB).all()
        assert (hold.provider_id, 22 * 60 <= hold.seconds < 23 * 60) == ("trex", True)
    assert "22 min" in host.status.call_args.args[0]


def test_cancel_stops_the_wait_and_a_late_answer_is_ignored(qapp, db, fake_account):
    host = _host(db)
    _refuse(host)
    wait = host._connection_wait
    cancel_cb = host.notification_manager.show.call_args.kwargs["actions"][0][1]
    cancel_cb()
    assert not wait.timer.isActive() and "_connection_wait" not in host.__dict__
    wait.on_checked(True, {"active_cons": 0, "max_connections": 1})
    host.play_channel_by_id.assert_not_called()


def test_starting_another_play_cancels_the_wait(qapp, db):
    host = _host(db)
    _refuse(host)
    wait = host._connection_wait
    watch.arm(host, PlayAttempt("ch-2", "Something else", "http://x/2.ts", provider_id="trex"))
    assert not wait.timer.isActive() and "_connection_wait" not in host.__dict__


def test_it_gives_up_after_an_hour(qapp, db, fake_account):
    host = _host(db)
    _refuse(host)
    wait = host._connection_wait
    wait.started -= connection_wait.GIVE_UP_AFTER_S + 1
    wait.poll()
    assert "_connection_wait" not in host.__dict__
    assert host.notification_manager.show.call_args.kwargs["title"] == "Stopped waiting for a connection"
    host.play_channel_by_id.assert_not_called()


def test_connections_summary_and_provider_delete(db):
    now = datetime(2026, 10, 31, 20, 0)
    with db.session_scope() as s:
        repo = RepositoryFactory(s).playback_events
        for secs in (600, 1320, 1500):
            repo.record_hold("trex", now, secs)
    with db.session_scope(commit=False) as s:
        c = RepositoryFactory(s).playback_events.connections("trex")
    assert (c.limit, c.in_use, c.waits, c.median_seconds, c.longest_seconds) == (1, 1, 3, 1320, 1500)
    with db.session_scope() as s:
        RepositoryFactory(s).playback_events.delete_for_provider("trex")
    with db.session_scope(commit=False) as s:
        assert s.query(ConnectionHoldDB).count() == 0
