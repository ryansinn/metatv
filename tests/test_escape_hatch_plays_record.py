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
"Try <source>" siblings, reactivate-and-play, and episode playback — and none
recorded anything, so a channel watched through any of them never reached
History, never bumped its play count and never registered for watch-progress
capture.
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
    return h


class TestEscapeHatchPlaysAreRecorded:

    def test_a_play_anyway_reaches_history(self, qapp):
        from metatv.gui.main_window_streaming import _StreamingMixin
        h = _host()
        _StreamingMixin._record_play(h, "prov_123", "prov", False)

        assert h.executor.submit.call_count == 1, (
            "the play was never recorded — this is the Play Anyway that "
            "vanished from History")
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
