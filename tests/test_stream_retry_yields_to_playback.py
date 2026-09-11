"""The failed-streams re-check must not open a second connection to a source
while a player window is open.

``StreamRetryManager``'s background probe (``_check_due`` -> ``_run_checks``)
calls ``validate_fn`` — a REAL stream connection — every 2 minutes for any due
entry. On the owner's one-connection panel (#635) that is the SECOND
connection, and the panel then refuses the user's own stream for 14-26s. It
fired mid-play on 2026-09-11 03:46:19. PLAY-16 gates the probe on whether a
player is currently running; ``check_all_now`` (the user's explicit "check
now" button) is deliberately NOT gated — that click is the user asking for it
right now.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from metatv.core.stream_retry_manager import StreamRetryManager


def test_the_probe_defers_while_a_player_is_running(qapp):
    running = [True]
    mgr = StreamRetryManager(
        db=MagicMock(),
        validate_fn=MagicMock(),
        player_is_running=lambda: running[0],
    )
    mgr._executor = MagicMock()

    mgr._check_due()

    mgr._executor.submit.assert_not_called()
    assert mgr._busy is False

    running[0] = False
    mgr._check_due()

    mgr._executor.submit.assert_called_once()


def test_check_all_now_is_not_gated_by_playback(qapp):
    """The user's explicit "check now" button always runs, player or not."""
    running = [True]
    mgr = StreamRetryManager(
        db=MagicMock(),
        validate_fn=MagicMock(),
        player_is_running=lambda: running[0],
    )
    mgr._executor = MagicMock()

    mgr.check_all_now()

    mgr._executor.submit.assert_called_once()
