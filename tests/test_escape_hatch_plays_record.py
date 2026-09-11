"""A play the user chose still counts, even if the pre-flight failed.

Owner, 2026-09-01: the stream's validation timed out, they chose **Play
Anyway**, the game played — and it never appeared in History. A third attempt
validated cleanly, took the normal path, and only then showed up. Their log:

    01:00:55.664  Marked channel as played: MLB 04 ... (count: 1)   <- validated
    01:17:48.596  All stream URLs failed validation
    01:17:52.790  MPVPlayer.play ...                                <- Play Anyway
                  (no mark_played at all)
    01:18:07.701  Marked channel as played: MLB 04 ... (count: 2)   <- validated

``mark_played`` lived only in ``_on_stream_ready``, the validated path. FOUR
call sites launch mpv without passing through it — Play Anyway, the
"Try <source>" siblings, reactivate-and-play, and episode playback.

PLAY-13 (2026-09-08): a follow-up audit found this docstring's "fixed" claim
was only 2 of 4 true at the time — Play Anyway and "Try <source>" called
``_record_play``; reactivate-and-play did not (its signature carried no
``channel_id`` at all) and stayed silently broken.
``TestReactivateAndPlayRecords`` below closes that gap. Episode playback is
covered separately in ``tests/test_episode_watch_tracking.py`` (it had the
mirror-image bug — recording BEFORE preflight validated, not never).

PLAY-15 (2026-09-11): the DB write ``_record_play`` used to submit
immediately is now deferred to ``host._pending_play_record``, committed only
once the playback-health watch sees the stream actually advance — see
``tests/test_play_count_needs_progress.py`` for that half.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _host():
    from metatv.gui.main_window_streaming import _StreamingMixin
    h = _StreamingMixin.__new__(_StreamingMixin)
    h.player_manager = MagicMock()
    h.player_manager.resolve_key.return_value = "key-1"
    h.executor = MagicMock()
    h._start_watch_capture = MagicMock()
    h.load_history = MagicMock()
    # PLAY-15: _play_and_record (routed through by the reactivate-and-play
    # escape hatch) arms the health watch — the real _start_playback_health
    # would build a QTimer(host) against this non-QObject double and raise.
    h._start_playback_health = MagicMock()
    return h


class TestEscapeHatchPlaysAreRecorded:

    def test_a_play_anyway_reaches_history(self, qapp):
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = _host()
        _StreamingMixin._record_play(h, "prov_123", "prov", False)

        # PLAY-15: the write is deferred until the health watch sees the
        # stream actually advance — it must NOT submit immediately.
        assert h.executor.submit.call_count == 0, (
            "the write ran immediately — a stream that never starts would "
            "still be counted as played")
        assert callable(h._pending_play_record), (
            "the play was never recorded — this is the Play Anyway that "
            "vanished from History")
        h._pending_play_record()
        assert h.executor.submit.call_count == 1
        args = h.executor.submit.call_args[0]
        assert args[1] == "prov_123", "recorded the wrong channel"
        # History itself now refreshes off the _bg_mark_played → notifier →
        # _on_history_changed chain, only AFTER the write commits (HIST-1) —
        # the old synchronous load_history() call here raced the DB commit.
        # That ordering is proven end-to-end in
        # tests/test_watch_capture_refresh.py; here we only assert the
        # notifier's home (watch capture) was armed before the write was
        # queued.
        assert h._start_watch_capture.call_count == 1, (
            "watch-capture (which wires the notifier the write emits on) "
            "was not armed")

    def test_watch_capture_is_registered_too(self, qapp):
        """Not just History — resume position depends on this as well."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = _host()
        _StreamingMixin._record_play(h, "prov_123", "prov", False)
        assert h._start_watch_capture.call_count == 1
        assert h._playing_channels == {"key-1": "prov_123"}

    def test_no_channel_id_is_a_no_op(self, qapp):
        """Some launch paths genuinely have no channel; they must not write."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = _host()
        _StreamingMixin._record_play(h, "", "prov", False)
        assert h.executor.submit.call_count == 0
        assert h.load_history.call_count == 0
        assert "_pending_play_record" not in h.__dict__

    def test_a_failure_never_costs_the_user_the_stream(self, qapp):
        """Bookkeeping must not raise into a play the user just started."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = _host()
        h.executor.submit.side_effect = RuntimeError("pool is shut down")
        _StreamingMixin._record_play(h, "c1", "p", False)  # must not raise

    def test_the_window_key_follows_force_new_window(self, qapp):
        """A second window is a different player instance, so a different key."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = _host()
        _StreamingMixin._record_play(h, "c1", "prov", True)
        h.player_manager.resolve_key.assert_called_once_with("prov", True)


class TestReactivateAndPlayRecords:
    """PLAY-13: reactivate-and-play was the one escape hatch that never called
    ``_record_play`` — its signature carried no ``channel_id`` at all, so it
    could not have, no matter what the ``_record_play`` docstring claimed.
    """

    def test_reactivate_and_play_records_on_success(self, qapp):
        from metatv.gui.main_window_streaming import _StreamingMixin
        from tests.conftest import wire_streaming_db
        h = _host()
        wire_streaming_db(h)   # session_scope raises -> reactivation degrades harmlessly
        h._refresh_provider_dependent_views = MagicMock()
        h._play_checked = MagicMock(return_value=True)

        _StreamingMixin._reactivate_and_play_sibling(
            h, "prov_x", "http://example.com/stream.ts", "Sibling Channel",
            False, "chan_sib_1",
        )

        h._play_checked.assert_called_once()
        _, kwargs = h._play_checked.call_args
        assert kwargs.get("channel_id") == "chan_sib_1", (
            "channel_id not threaded to _play_checked"
        )
        # PLAY-15: deferred, not immediate — but a launch that succeeded must
        # arm the watch, so the deferred record CAN eventually commit.
        h._start_playback_health.assert_called_once()
        assert h.executor.submit.call_count == 0
        assert callable(h._pending_play_record), (
            "reactivate-and-play launched mpv but never recorded the play — "
            "this is the gap the docstring claimed was already closed"
        )
        h._pending_play_record()
        assert h.executor.submit.call_count == 1
        args = h.executor.submit.call_args[0]
        assert args[1] == "chan_sib_1", "recorded the wrong channel"

    def test_reactivate_and_play_skips_recording_when_launch_fails(self, qapp):
        """No mpv launch, no play to record."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        from tests.conftest import wire_streaming_db
        h = _host()
        wire_streaming_db(h)
        h._refresh_provider_dependent_views = MagicMock()
        h._play_checked = MagicMock(return_value=False)

        _StreamingMixin._reactivate_and_play_sibling(
            h, "prov_x", "http://example.com/stream.ts", "Sibling Channel",
            False, "chan_sib_1",
        )

        assert h.executor.submit.call_count == 0

    def test_reactivate_and_play_with_no_channel_id_is_a_no_op_record(self, qapp):
        """A defensive default, never taken by the real caller (it always
        supplies the sibling's id) — must not crash and must not record."""
        from metatv.gui.main_window_streaming import _StreamingMixin
        from tests.conftest import wire_streaming_db
        h = _host()
        wire_streaming_db(h)
        h._refresh_provider_dependent_views = MagicMock()
        h._play_checked = MagicMock(return_value=True)

        _StreamingMixin._reactivate_and_play_sibling(
            h, "prov_x", "http://example.com/stream.ts", "Sibling Channel", False,
        )

        assert h.executor.submit.call_count == 0
