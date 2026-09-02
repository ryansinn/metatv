"""A stream that never starts must not read as a successful play.

Owner, 2026-09-02: *"the stream didn't start, it's just hanging"* — and the log
above that report is a complete success path. ``_send_ipc_command`` returns True
on any reply at all, so a ``loadfile`` mpv accepted and then did nothing with
produced: "Playing: <name>" in the status bar on a 2s timer, ``mark_played``
with ``count: 3``, and the notification auto-dismissed. Nothing anywhere asked
whether video had arrived.

The signal already existed and was being read as a different fact. The
playback-health probe treats an empty ``path`` as "idle — the user closed the
player". Immediately after a launch that same reading means the file never
loaded. One bit of memory — *has this play ever had a loaded file?* — separates
them, and that bit is what these tests pin.

The most important test here is the NEGATIVE one: a play that started and then
went idle must stay silent. A detector that cries wolf every time someone closes
the player would be worse than the silence it replaces.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.gui import playback_start_watch as watch
from metatv.gui.playback_start_watch import (
    FAILED_AFTER_TICKS,
    STOP_POLLING_AFTER_TICKS,
    PlayAttempt,
)


ATTEMPT = PlayAttempt("p_123", "MLB 04 | Mariners x Red Sox", "http://x/1.ts")


def _host():
    """A duck-typed host — the module takes ``host`` and touches only these.

    Deliberately not a ``MainWindow.__new__``: this module's contract IS the
    small attribute surface below, so a real window would test Qt rather than
    the rule. Anything it reaches for that is missing raises here rather than
    being silently absorbed.
    """
    return SimpleNamespace(
        status_bar=MagicMock(),
        notification_manager=MagicMock(),
        stream_retry_manager=MagicMock(),
    )


# ── the bit of memory ────────────────────────────────────────────────────────

def test_arm_clears_the_previous_play(host=None):
    host = _host()
    host._health_ever_played = True
    host._health_idle_ticks = 99
    watch.arm(host, ATTEMPT)
    assert host._health_ever_played is False
    assert host._health_idle_ticks == 0
    assert host._health_attempt is ATTEMPT


def test_on_playing_is_true_only_the_first_time():
    """This is what lets "Playing:" be announced once, when it is TRUE —
    rather than on a timer that fired whether or not anything played."""
    host = _host()
    watch.arm(host, ATTEMPT)
    assert watch.on_playing(host) is True
    assert watch.on_playing(host) is False
    assert watch.on_playing(host) is False


def test_a_loaded_file_clears_the_idle_count():
    host = _host()
    watch.arm(host, ATTEMPT)
    watch.on_idle_tick(host)
    watch.on_idle_tick(host)
    watch.on_playing(host)
    assert host._health_idle_ticks == 0


# ── the failure it exists to catch ───────────────────────────────────────────

def test_a_play_that_never_starts_is_reported():
    host = _host()
    watch.arm(host, ATTEMPT)
    for _ in range(FAILED_AFTER_TICKS):
        watch.on_idle_tick(host)

    host.status_bar.showMessage.assert_called_once()
    assert ATTEMPT.channel_name in host.status_bar.showMessage.call_args[0][0]
    host.notification_manager.show.assert_called_once()
    host.stream_retry_manager.add_failure.assert_called_once_with(
        ATTEMPT.channel_id, ATTEMPT.channel_name, ATTEMPT.stream_url,
        "playback never started")


def test_it_is_reported_exactly_once_however_long_the_window_sits_there():
    """A report every 2s for as long as mpv idles would be its own bug."""
    host = _host()
    watch.arm(host, ATTEMPT)
    for _ in range(STOP_POLLING_AFTER_TICKS * 3):
        watch.on_idle_tick(host)
    assert host.notification_manager.show.call_count == 1
    assert host.stream_retry_manager.add_failure.call_count == 1


def test_nothing_is_reported_before_the_threshold():
    """One probe that raced the launch must not condemn a working stream."""
    host = _host()
    watch.arm(host, ATTEMPT)
    for _ in range(FAILED_AFTER_TICKS - 1):
        watch.on_idle_tick(host)
    host.notification_manager.show.assert_not_called()
    host.stream_retry_manager.add_failure.assert_not_called()


# ── the false positive that would make this worse than silence ───────────────

def test_closing_a_player_that_WAS_playing_reports_nothing():
    """The whole point of the memory bit.

    Same empty ``path``, opposite meaning. Without ``_health_ever_played`` this
    fires every single time the user closes mpv, which is the most common event
    in the app.
    """
    host = _host()
    watch.arm(host, ATTEMPT)
    watch.on_playing(host)                      # video arrived
    for _ in range(STOP_POLLING_AFTER_TICKS * 2):
        watch.on_idle_tick(host)                # then the user closed it
    host.notification_manager.show.assert_not_called()
    host.stream_retry_manager.add_failure.assert_not_called()
    host.status_bar.showMessage.assert_not_called()


def test_a_play_with_no_identity_still_tells_the_user_but_logs_no_failure():
    """Episode playback arms without a PlayAttempt. It must not crash, must
    still say something, and must not invent a channel id for the ledger."""
    host = _host()
    watch.arm(host, None)
    for _ in range(FAILED_AFTER_TICKS):
        watch.on_idle_tick(host)
    host.notification_manager.show.assert_called_once()
    host.stream_retry_manager.add_failure.assert_not_called()


def test_polling_stops_only_after_the_longer_threshold():
    host = _host()
    watch.arm(host, ATTEMPT)
    results = [watch.on_idle_tick(host) for _ in range(STOP_POLLING_AFTER_TICKS)]
    assert results[-1] is True
    assert not any(results[:-1]), "polling stopped early"
    assert FAILED_AFTER_TICKS < STOP_POLLING_AFTER_TICKS, (
        "the failure must be reported before polling gives up, or it never is")


def test_a_broken_notification_does_not_take_out_the_poll():
    """A stream that failed must not also kill the loop that noticed."""
    host = _host()
    host.notification_manager.show.side_effect = RuntimeError("boom")
    watch.arm(host, ATTEMPT)
    for _ in range(FAILED_AFTER_TICKS):
        watch.on_idle_tick(host)
    host.stream_retry_manager.add_failure.assert_called_once()


# ── the wiring, because a rule nobody calls is not a rule ────────────────────

HOST_SRC = (pathlib.Path(__file__).resolve().parent.parent
            / "metatv" / "gui" / "main_window_streaming.py").read_text()


def test_the_unconditional_playing_claim_is_gone():
    """It announced "Playing:" on a 2s timer regardless of what mpv did — the
    single line that made a hung stream look like a successful one."""
    assert 'showMessage(f"Playing: {channel_name}")' not in HOST_SRC, (
        "the 2s unconditional \"Playing:\" timer is back")


@pytest.mark.parametrize("call", [
    "_startwatch.on_idle_tick(self)",
    "_startwatch.on_playing(self)",
    "_startwatch.start_polling(self, attempt)",
])
def test_the_host_actually_calls_the_watch(call):
    assert call in HOST_SRC, f"main_window_streaming no longer calls {call}"


def test_the_play_path_names_what_it_launched():
    """Without the PlayAttempt the failure can be shown but never recorded."""
    assert "_startwatch.PlayAttempt(channel_id, channel_name, final_url)" in HOST_SRC


# ── the read that must not explode ───────────────────────────────────────────

def test_every_read_survives_a_half_built_qobject_host():
    """``getattr(host, name, default)`` is unusable here, and silently so.

    The host is often a ``MainWindow.__new__`` double. Touching a missing
    attribute on a half-built QObject raises **RuntimeError**, not
    AttributeError — so the default is never reached and the read that was meant
    to be safe is the thing that explodes. This exact shape has now cost four
    separate batches; it caught this module too, in
    ``test_playback_health``, after the unit tests above were green.

    Written against the REAL class rather than a stand-in, because the whole
    behaviour belongs to Qt's ``__getattr__`` and a plain object cannot
    reproduce it.
    """
    from metatv.gui.main_window import MainWindow

    host = MainWindow.__new__(MainWindow)
    host.status_bar = MagicMock()
    host.notification_manager = MagicMock()
    host.stream_retry_manager = MagicMock()

    # Never armed: every counter is absent. Each of these must answer, not raise.
    assert watch.on_playing(host) is True
    assert watch.on_idle_tick(host) is False

    watch.arm(host, ATTEMPT)
    for _ in range(FAILED_AFTER_TICKS):
        watch.on_idle_tick(host)
    host.stream_retry_manager.add_failure.assert_called_once()
