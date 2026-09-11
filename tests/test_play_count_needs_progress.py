"""A play is recorded only once playback actually advances — never on retry.

Owner, 2026-09-11, on a title that never played: "you can try to play
something that never plays, 6 times and it will count as having been played
6 times even though it's just struggling with getting it to playback at
all." The log showed "Marked channel as played: … (count: 1)" through
"(count: 6)" for a stream that "playback never started" every time.

``_StreamingMixin._record_play`` and ``_SeriesPlaybackMixin._record_episode_play``
used to submit/run the DB write the moment mpv accepted ``loadfile``. PLAY-15
instead hands the write to ``host._pending_play_record`` and
``playback_start_watch.on_loaded_tick`` commits it only the first time it sees
``time-pos`` genuinely advance — see that module's docstring tail. This file
proves the watch half of that contract directly against
``playback_start_watch``, independent of which caller filled the slot.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import metatv.gui.playback_start_watch as watch


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _host():
    """Same duck-typed host as test_playback_never_started.py::_host."""
    from tests.conftest import wire_status_method

    host = SimpleNamespace(
        status_bar=MagicMock(),
        notification_manager=MagicMock(),
        stream_retry_manager=MagicMock(),
        _provider_display_name=MagicMock(return_value="Test Source"),
    )
    wire_status_method(host)
    return host


def test_six_failed_plays_record_nothing(qapp):
    """The owner's exact report: retrying a title that never plays must not
    inflate its play count no matter how many times it is retried."""
    host = _host()
    mocks = []
    for i in range(6):
        watch.arm(host, watch.PlayAttempt(f"ch-{i}", f"T{i}", "http://x"))
        m = MagicMock()
        host._pending_play_record = m
        mocks.append(m)
        watch.on_playing(host)
        for _ in range(20):
            watch.on_loaded_tick(host, None, False, cache_duration=None)

    for m in mocks:
        m.assert_not_called()


def test_the_record_commits_on_the_first_advance(qapp):
    host = _host()
    watch.arm(host, watch.PlayAttempt("ch-1", "T1", "http://x"))
    m = MagicMock()
    host._pending_play_record = m

    watch.on_loaded_tick(host, 0.0, False, cache_duration=3.0)
    m.assert_not_called()

    watch.on_loaded_tick(host, 1.0, False, cache_duration=3.0)
    m.assert_called_once()

    # A further tick must not commit it again — it's popped, not just read.
    watch.on_loaded_tick(host, 2.0, False, cache_duration=3.0)
    m.assert_called_once()
    assert host.__dict__.get("_pending_play_record") is None


def test_arming_a_new_play_drops_the_unplayed_record(qapp):
    host = _host()
    watch.arm(host, watch.PlayAttempt("ch-a", "A", "http://a"))
    m_a = MagicMock()
    host._pending_play_record = m_a

    # A new play starts before the old one ever progressed.
    watch.arm(host, watch.PlayAttempt("ch-b", "B", "http://b"))
    assert host._pending_play_record is None

    watch.on_loaded_tick(host, 0.0, False, cache_duration=3.0)
    watch.on_loaded_tick(host, 1.0, False, cache_duration=3.0)
    m_a.assert_not_called()


def test_a_failing_record_does_not_take_out_the_poll(qapp):
    """Bookkeeping must never cost the user the progress the poll just found."""
    host = _host()
    watch.arm(host, watch.PlayAttempt("ch-1", "T1", "http://x"))
    host._pending_play_record = MagicMock(side_effect=RuntimeError("boom"))

    watch.on_loaded_tick(host, 0.0, False, cache_duration=3.0)
    watch.on_loaded_tick(host, 1.0, False, cache_duration=3.0)   # must not raise

    assert host._health_ever_progressed is True


def test_on_stream_ready_arms_before_it_records(qapp):
    """PLAY-15's ordering requirement: arm() clears the slot _record_play
    fills, so arming must happen first or the fill is immediately lost."""
    from metatv.gui.main_window_streaming import _StreamingMixin

    h = _StreamingMixin.__new__(_StreamingMixin)
    order = MagicMock()
    h._start_playback_health = order.arm
    h._record_play = order.record
    h._play_checked = MagicMock(return_value=True)
    h.status = MagicMock()
    h.loading_channels = set()
    h.player_manager = MagicMock()
    h._sidebar_shows_channel = MagicMock(return_value=False)
    h._provider_icons = {}
    h._lookup_provider_icon = MagicMock(return_value="")
    h.notification_manager = MagicMock()

    with patch("metatv.gui.main_window_streaming.QTimer"):
        _StreamingMixin._on_stream_ready(h, {
            "ok": True, "channel_id": "c", "channel_name": "n",
            "final_url": "u", "original_url": "u", "provider_id": "p",
        })

    assert [c[0] for c in order.mock_calls][:2] == ["arm", "record"]


def test_escape_hatch_arms_the_watch_then_records(qapp):
    """_play_and_record: the escape hatches' seam must arm before recording,
    and must do neither when the launch itself failed."""
    from metatv.gui.main_window_streaming import _StreamingMixin

    h = _StreamingMixin.__new__(_StreamingMixin)
    order = MagicMock()
    h._start_playback_health = order.arm
    h._record_play = order.record
    h._play_checked = MagicMock(return_value=True)

    ok = _StreamingMixin._play_and_record(h, "u", "n", "p", False, "c")

    assert ok is True
    order.arm.assert_called_once()
    attempt = order.arm.call_args[0][0]
    assert attempt.channel_id == "c"
    assert attempt.provider_id == "p"
    order.record.assert_called_once_with("c", "p", False)
    assert [c[0] for c in order.mock_calls][:2] == ["arm", "record"]

    order.reset_mock()
    h._play_checked = MagicMock(return_value=False)
    ok = _StreamingMixin._play_and_record(h, "u", "n", "p", False, "c")

    assert ok is False
    order.arm.assert_not_called()
    order.record.assert_not_called()
