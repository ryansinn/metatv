"""Did the stream the user just asked for actually start?

The app could not tell. ``_send_ipc_command`` returns True on any reply at all,
so a ``loadfile`` mpv accepted and then did nothing with read as success: the
status bar announced "Playing: <name>" on a two-second timer regardless, the
channel's play count was incremented, and the failure toast never fired. Owner,
2026-09-02: *"the stream didn't start, it's just hanging"* — with a complete
success path in the log above it.

**The signal already existed and was being read as something else.** The
playback-health probe polls mpv every 2s and treats an empty ``path`` as "idle
— the user closed the player". Right after a launch that is not what it means:
it means the file never loaded at all. Same reading, two different facts, and
only the elapsed history since the play separates them.

So the rule here is one bit of memory — *has this play ever had a loaded file?*
— and everything else follows from it:

* never loaded, and the probe has said so for :data:`FAILED_AFTER_TICKS` ticks
  → the play FAILED, and the user is told.
* loaded once and now idle → the player was closed, which is the existing
  behaviour and stays untouched.

``path`` rather than ``time-pos`` is deliberate. mpv is launched with
``--cache-pause-initial=yes --cache-pause-wait=10``, so a perfectly healthy
stream sits paused with no position for the first several seconds; ``path`` is
set the moment ``loadfile`` is accepted. Judging on position would call every
slow-opening stream a failure — the false positive that would make this feature
worse than the silence it replaces.
"""

from __future__ import annotations

from typing import Any, NamedTuple, Optional

#: Read through ``host.__dict__`` rather than ``getattr(host, name, default)``.
#: The host is often a ``MainWindow.__new__`` test double, and touching a
#: missing attribute on a half-built QObject raises **RuntimeError**, not
#: AttributeError — so the default is never reached and the read that was meant
#: to be safe is the thing that explodes. ``__dict__.get`` is also the idiom the
#: surrounding module already uses for lazily-created per-play state.

from loguru import logger
from PyQt6.QtCore import QTimer

#: How often the health probe runs. The two thresholds below are counted in
#: these ticks, so they move together if this does.
POLL_MS = 2000

#: Consecutive "nothing loaded" probes before a play is declared failed.
#:
#: The probe ticks every 2s, so this is ~10s. It does not need to cover
#: buffering — ``path`` is set as soon as mpv accepts the file — but it does
#: need to cover mpv's own startup, the socket appearing, and one probe that
#: raced the launch. Cheap to be generous: the cost of waiting is a later
#: message, and the cost of being early is calling a working stream broken.
FAILED_AFTER_TICKS = 5

#: Idle probes before polling stops entirely. Pre-existing behaviour (~16s),
#: kept here so the two thresholds are visible next to each other rather than
#: one being a bare literal in a slot.
STOP_POLLING_AFTER_TICKS = 8


class PlayAttempt(NamedTuple):
    """What a failure report needs to name the thing that did not play."""

    channel_id: str
    channel_name: str
    stream_url: str


def arm(host: Any, attempt: "Optional[PlayAttempt]" = None) -> None:
    """Begin watching the play that is starting now.

    Args:
        host: The MainWindow-family object holding the probe state.
        attempt: What was launched, for the failure report. None from callers
            that have no identity to hand (episode playback), which still get
            the counters reset — they simply report nothing if it fails.
    """
    host._health_idle_ticks = 0
    host._health_ever_played = False
    host._health_attempt = attempt


def on_playing(host: Any) -> bool:
    """Record that a file is loaded. Returns True the FIRST time per play.

    The first-time bit is what lets the caller announce "Playing:" once, when
    it is true, instead of on a timer that fires whether or not anything
    happened.
    """
    host._health_idle_ticks = 0
    first = not host.__dict__.get("_health_ever_played", False)
    host._health_ever_played = True
    return first


def on_idle_tick(host: Any) -> bool:
    """Count one "nothing loaded" probe. Returns True when polling should stop.

    Reports the failure exactly once, on the tick that crosses the threshold —
    a report every 2s for as long as the window sits there would be its own bug.
    """
    ticks = host.__dict__.get("_health_idle_ticks", 0) + 1
    host._health_idle_ticks = ticks

    if ticks == FAILED_AFTER_TICKS and not host.__dict__.get("_health_ever_played"):
        _report_never_started(host)

    return ticks >= STOP_POLLING_AFTER_TICKS


def _report_never_started(host: Any) -> None:
    """Tell the user, and put it in the retry ledger.

    Wrapped in its own try: a stream that failed to play must not also take out
    the polling loop that noticed.
    """
    attempt = host.__dict__.get("_health_attempt")
    name = attempt.channel_name if attempt else "that channel"
    logger.warning(
        "playback never started for {!r} — mpv accepted the file and loaded "
        "nothing within {}s", name, FAILED_AFTER_TICKS * 2)
    try:
        host.status_bar.showMessage(f"Nothing is playing: {name}")
    except Exception:                                    # pragma: no cover
        logger.exception("could not update the status bar")
    try:
        host.notification_manager.show(
            title="Stream did not start",
            message=(f"{name} was accepted by the source but no video arrived. "
                     "The source may be busy or the stream dead."),
            type="warning",
            auto_dismiss_ms=8000,
        )
    except Exception:                                    # pragma: no cover
        logger.exception("could not show the failure notification")
    if attempt is None:
        return
    try:
        host.stream_retry_manager.add_failure(
            attempt.channel_id, attempt.channel_name, attempt.stream_url,
            "playback never started")
    except Exception:                                    # pragma: no cover
        logger.exception("could not record the failed play")


def start_polling(host: Any, attempt: "Optional[PlayAttempt]" = None) -> None:
    """Start (or resume) the 2s playback-health poll, armed for this play.

    Lives here rather than on the host because arming the watch and starting
    the poll that feeds it are one act — splitting them is how the counters
    ended up reset in one place and read in another.

    Lazily creates the QTimer on first use and registers its stop() with the
    cleanup registry exactly once. Safe to call on every play.

    Args:
        host: The MainWindow-family object that owns the timer.
        attempt: What was launched, for the failure report; see :func:`arm`.
    """
    if host.__dict__.get("_playback_health_timer") is None:
        host._playback_health_timer = QTimer(host)
        host._playback_health_timer.setInterval(POLL_MS)
        host._playback_health_timer.timeout.connect(host._playback_health_tick)
        host._health_query_inflight = False
        host._register_cleanable(
            "playback_health_timer", host._playback_health_timer.stop)

    arm(host, attempt)
    # A new play always follows the most-recently-used window. Without this, a
    # readout the user clicked to cycle (pinning _health_view_key to some
    # window) stays pinned forever — so after that window goes idle or they play
    # elsewhere, the readout keeps polling the stale/idle instance and shows
    # nothing. Reset to "follow latest" on every play.
    host._health_view_key = None
    if not host._playback_health_timer.isActive():
        host._playback_health_timer.start()
