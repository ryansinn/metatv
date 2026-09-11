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
* loaded but genuinely OPENING (no ``time-pos``, no ``demuxer-cache-duration``
  at all yet — mpv is mid ``reconnect_delay_max`` backoff against a source
  still counting the previous stream, PLAY-10) for :data:`OPENING_AFTER_TICKS`
  ticks → the play FAILED. Counted separately from FROZEN below so a same-
  provider switch's retry schedule (~+1,+3,+7,+15,+23s) has room to land
  before this reports.
* loaded, has a numeric ``time-pos``, and it never advances for
  :data:`STALLED_AFTER_TICKS` ticks → the play FAILED; user pause holds the
  counter. Unchanged from before OPENING was split out.
* loaded once and now idle → the player was closed, which is the existing
  behaviour and stays untouched.

``path`` rather than ``time-pos`` is deliberate. mpv is launched with
``--cache-pause-initial=yes --cache-pause-wait=10``, so a perfectly healthy
stream sits paused with no position for the first several seconds; ``path`` is
set the moment ``loadfile`` is accepted. Judging on position would call every
slow-opening stream a failure — the false positive that would make this feature
worse than the silence it replaces.

**Deferred play recording (PLAY-15).** A play used to be recorded — play
count, last-played, History — the moment mpv accepted the ``loadfile``, so a
title that never produced a frame still counted, once per retry (owner,
2026-09-11: six failed attempts logged "count: 1" through "count: 6"). The
caller now hands the DB-write closure to ``host._pending_play_record`` instead
of running it: :func:`arm` clears it along with the rest of the play's state
(a play that never progressed never gets recorded, matching the "previous
play … never progressed" log line above), and :func:`on_loaded_tick` pops and
calls it the moment ``_health_ever_progressed`` first becomes True — wrapped
in its own try/except, since a bookkeeping failure here must not take out the
poll that just found the progress.

**A drop mid-play is not the film ending (PLAY-17).** Owner's log, 2026-09-11
04:02-04:05: a movie played from 04:03:35, the origin closed the connection at
04:04:01, ffmpeg's reconnects were all refused for 60s, the buffer ran dry,
and mpv hit EOF and exited — with ``--idle=once`` — 157s into a feature-length
file. The app read that exactly like the film ending: no report, no resume,
window gone. :func:`on_loaded_tick` now tracks the last known ``time-pos`` and
``duration`` for the whole play, even after it has progressed, and
:func:`resume_after_drop` compares them: a play that ends more than
:data:`DROP_END_MARGIN_S` short of its own duration did not finish — it
dropped — and gets replayed from a few seconds before the cut, up to
:data:`MAX_DROP_RESUMES` times, before the user is told and left in control.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple, Optional

#: Read through ``host.__dict__`` rather than ``getattr(host, name, default)``.
#: The host is often a ``MainWindow.__new__`` test double, and touching a
#: missing attribute on a half-built QObject raises **RuntimeError**, not
#: AttributeError — so the default is never reached and the read that was meant
#: to be safe is the thing that explodes. ``__dict__.get`` is also the idiom the
#: surrounding module already uses for lazily-created per-play state.

from loguru import logger
from PyQt6.QtCore import QTimer

from metatv.core import epg_utils
from metatv.core.players.mpv import RECONNECT_DELAY_MAX_S, STREAM_IO_TIMEOUT_S
from metatv.core.players.mpv_log_tap import STREAM_EXIT_REASONS

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

#: Consecutive loaded-but-frozen probes before a play is declared stalled.
#:
#: ~16s at POLL_MS. Must comfortably exceed mpv's --cache-pause-wait=10 (see
#: the launch flags in core/players/mpv.py): a healthy slow stream sits in
#: initial cache-pause with no position for up to ~10s and must not be called
#: broken. A local bench (2026-09-02) showed a 20 KB/s stream starting inside
#: three seconds under these flags, so 16s of zero progress is not "slow".
STALLED_AFTER_TICKS = 8


def ffmpeg_retry_window_s(delay_max: int) -> int:
    """How long ffmpeg's own ``reconnect_delay_max`` backoff runs before it
    gives up, in seconds.

    ffmpeg's rule (measured 2026-09-11, see tests/test_reconnect_window.py):
    the delay starts at 0, after each failed attempt ``delay = 1 + 2*delay``,
    and it stops once that next delay would exceed ``delay_max``. The total is
    the sum of every attempt's delay actually taken.
    """
    d, total = 0, 0
    while d <= delay_max:
        total += d
        d = 1 + 2 * d
    return total


#: Consecutive loaded-but-still-OPENING probes (no ``time-pos``, no
#: ``demuxer-cache-duration`` — no demuxer data has arrived at all) before a
#: play is declared failed.
#:
#: This verdict used to land at 20 ticks (40s) — INSIDE mpv's own retry
#: window — on the theory that the verdict could tell the user while mpv kept
#: trying underneath it. It doesn't work that way in practice: owner's log,
#: 2026-09-11 03:45 — mpv connected at 03:47:11 after retrying at
#: :39/:59/03:46:21/:44 (PLAY-14's own +0,+0,+1,+4,+11,+26,+57s schedule), but
#: the 40s verdict fired at 03:45:56, called it "never started", showed the
#: failure toast, and logged a play failure — for a stream that then played.
#: The verdict must land AFTER mpv has actually given up: mpv's scheduled
#: retries (:func:`ffmpeg_retry_window_s`) plus one more full socket timeout
#: for whichever attempt was in flight when the schedule ended, plus 10s
#: slack, in ticks.
OPENING_AFTER_TICKS = (
    (ffmpeg_retry_window_s(RECONNECT_DELAY_MAX_S) + STREAM_IO_TIMEOUT_S + 10)
    // (POLL_MS // 1000)
)

#: Minimum time-pos increase (seconds) that counts as real progress — guards
#: against float jitter between two probes of a genuinely frozen position.
_PROGRESS_EPSILON = 0.25

#: How far short of the file's own ``duration`` a play can end and still count
#: as the film genuinely finishing rather than the source dropping it. See
#: :func:`dropped_mid_stream`. A live stream has no duration and never trips
#: this; a resume past the real end ends the file at once and also never
#: trips it (duration - last_pos is then <= 0).
DROP_END_MARGIN_S = 60

#: Automatic mid-stream resumes (see :func:`resume_after_drop`) one play's
#: lineage gets before the app stops retrying on its own and tells the user
#: instead. A source that drops every minute gets three tries, not infinite.
MAX_DROP_RESUMES = 3


class PlayAttempt(NamedTuple):
    """What a failure report needs to name the thing that did not play."""

    channel_id: str
    channel_name: str
    stream_url: str
    #: The resume offset this play was launched with, or 0. Carried because it
    #: is the most likely cause of the second failure shape below, and because
    #: "it may be resuming past the end" is something the user can act on.
    resume_seconds: int = 0
    #: The fixture's parsed start time (UTC-naive), or None for anything that
    #: isn't a dated sports/PPV event. A pre-start play of one is the OTHER
    #: likely cause of "it never started" — see :func:`prestart_detail`.
    event_start_time: "datetime | None" = None
    #: True when this play IS the one automatic retry (see :func:`retry_candidate`)
    #: — a retry that exits the same way is reported but never retried again.
    retry: bool = False
    #: The channel's provider, so the OPENING/FROZEN waiting line (PLAY-12) can
    #: name which source it's waiting on via ``host._provider_display_name``.
    #: None for callers with no provider to hand (falls back to a generic noun).
    provider_id: "str | None" = None
    #: How many automatic mid-stream drop-resumes (:func:`resume_after_drop`)
    #: this play's lineage has already used — capped at :data:`MAX_DROP_RESUMES`.
    drop_resumes: int = 0


#: How long the retry waits after the player exited while opening. The
#: one-connection panels measured in #635 keep counting a closed connection for
#: 14-26 s; the owner's second click at +32 s played (2026-09-06 10:12).
RETRY_AFTER_EXIT_MS = 20_000


def arm(host: Any, attempt: "Optional[PlayAttempt]" = None) -> None:
    """Begin watching the play that is starting now.

    Args:
        host: The MainWindow-family object holding the probe state.
        attempt: What was launched, for the failure report. None from callers
            that have no identity to hand (episode playback), which still get
            the counters reset — they simply report nothing if it fails.
    """
    prev = host.__dict__.get("_health_attempt")
    if (prev is not None and not host.__dict__.get("_health_ever_progressed")
            and not host.__dict__.get("_health_reported")):
        # Not a toast — switching titles mid-open is normal — but the log must
        # say the previous play never got going (2026-09-06: it did not).
        logger.info("previous play {!r} never progressed before this one", prev.channel_name)
    host._health_idle_ticks = 0
    host._health_ever_played = False
    host._health_reported = False
    host._health_attempt = attempt
    host._health_last_time_pos = None
    host._health_stalled_ticks = 0
    host._health_opening_ticks = 0
    host._health_ever_progressed = False
    host._health_last_duration = None
    # PLAY-17: a stale scheduled-replay identity must not survive onto a new
    # play — see :func:`replay`.
    host._scheduled_replay = None
    # PLAY-15: the previous play's DB-write closure, if any, is dropped here —
    # it never progressed, so it must never be recorded.
    host._pending_play_record = None


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


def _push_waiting_line(host: Any, ticks: int) -> None:
    """Name what a silent OPENING/FROZEN wait is actually doing (PLAY-12).

    From the 2nd tick (4s) onward — before that, a fast-opening stream would
    flash a line it never needed. Stops once the tick's own failure verdict
    has reported (:func:`_report_never_started` sets ``_health_reported`` and
    owns the status bar from there). The :data:`OPENING_AFTER_TICKS`/
    :data:`STALLED_AFTER_TICKS` reports are unchanged — this only fills the
    silent gap before them, which is the delay the owner saw as an
    unexplained spinner.
    """
    if ticks < 2 or host.__dict__.get("_health_reported"):
        return
    attempt = host.__dict__.get("_health_attempt")
    pid = getattr(attempt, "provider_id", None) if attempt else None
    source = host._provider_display_name(pid) if pid else "the source"
    verb = ("free the previous stream" if host.__dict__.get("_switch_same_provider")
            else "answer")
    seconds = ticks * (POLL_MS // 1000)
    try:
        host.status(f"Waiting for {source} to {verb}… {seconds}s", ms=0)   # a countdown, not a warning
    except Exception:                                    # pragma: no cover
        logger.exception("could not update the status bar")


def on_loaded_tick(host: Any, time_pos: Any, paused: bool, cache_duration: Any = None,
                    duration: Any = None) -> None:
    """Judge whether a LOADED file is actually OPENING, progressing, or frozen.

    Called on every probe tick that carries a loaded ``path`` (the same ticks
    that feed :func:`on_playing`). Two shapes of "it never played" hide behind
    that one ``path`` check, and PLAY-10 is the conflation between them:

    * OPENING — no ``time-pos`` AND no ``cache_duration``: no demuxer data has
      arrived at all, e.g. mpv mid ``reconnect_delay_max`` backoff against a
      source still counting the previous stream. Counted in
      ``_health_opening_ticks``, reported at :data:`OPENING_AFTER_TICKS`.
    * FROZEN — a numeric ``time-pos`` that never increases: mpv accepted the
      file, video output may even have painted a garbage frame, but playback
      never actually advances (owner, 2026-09-02: black with a green bar, no
      message). Counted in ``_health_stalled_ticks``, reported at
      :data:`STALLED_AFTER_TICKS` — unchanged from before OPENING existed.

    A ``time-pos`` of None with a *present* ``cache_duration`` means data IS
    arriving even though no position has landed yet — neither shape, so it
    counts toward neither counter; it is not "no data at all" and it is not a
    frozen numeric reading.

    Progress means an INCREASE between two numeric readings — a single frozen
    reading (e.g. 0.0 from one decoded garbage frame) is not progress. A
    user-paused player holds BOTH counters: a frozen or absent position proves
    nothing while they hold it. Once real progress is seen the watch disarms
    for the rest of the play and the status bar's waiting line is cleared.

    PLAY-12: both counted branches also push a "still waiting" status-bar line
    via :func:`_push_waiting_line` from their 2nd tick onward, so the owner's
    "it's just hanging" silence now counts and names what it's waiting on. The
    OPENING_AFTER_TICKS/STALLED_AFTER_TICKS reports below are unchanged — they
    are the failure verdicts; this only fills the gap before them.

    Deliberately NOT consulted by :func:`on_player_gone` or the idle path:
    closing a just-loaded stream within its first seconds must stay silent —
    the negative case the whole module is built around.

    Args:
        host: The MainWindow-family object holding the probe state.
        time_pos: mpv's ``time-pos`` property (float, or None/absent).
        paused: mpv's ``pause`` property.
        cache_duration: mpv's ``demuxer-cache-duration`` property from the
            same probe tick — the signal that distinguishes OPENING (None)
            from "data is arriving, position just isn't set yet" (present).
        duration: mpv's ``duration`` property (the file's total length, or
            None for a live stream) from the same probe tick. Tracked in
            ``host._health_last_duration`` alongside ``time_pos`` on every
            numeric reading — including after this play has progressed, when
            the rest of this function is a no-op — so :func:`resume_after_drop`
            always has the position and duration as of the last live tick,
            whenever the player later vanishes (PLAY-17).
    """
    if host.__dict__.get("_health_ever_progressed"):
        if isinstance(time_pos, (int, float)):
            host._health_last_time_pos = float(time_pos)
            host._health_last_duration = (
                float(duration) if isinstance(duration, (int, float)) else None)
        return
    last = host.__dict__.get("_health_last_time_pos")
    if isinstance(time_pos, (int, float)):
        if last is not None and time_pos > last + _PROGRESS_EPSILON:
            host._health_ever_progressed = True
            host._health_last_time_pos = float(time_pos)
            host._health_last_duration = (
                float(duration) if isinstance(duration, (int, float)) else None)
            try:
                host.status_bar.clearMessage()   # progress seen — the wait is over
            except Exception:                                    # pragma: no cover
                logger.exception("could not clear the status bar")
            # PLAY-15: only now — playback actually advanced — does the play
            # get recorded. host.__dict__ (this module's idiom) so a double
            # that never set the attribute is treated as "nothing pending".
            commit = host.__dict__.pop("_pending_play_record", None)
            if commit is not None:
                try:
                    commit()
                except Exception:
                    logger.exception("could not record the play")
            # A stream that PLAYED is stronger evidence than a probe's "back
            # online" — it must not stay flagged/degraded/dead in the retry
            # ledger, whatever the verdict said up to 60s earlier.
            # _report_never_started may already have fired for THIS play (a
            # FROZEN/STALLED report can precede progress) — this is exactly
            # the case that must clear.
            att = host.__dict__.get("_health_attempt")
            if att is not None:
                try:
                    host.stream_retry_manager.remove_by_channel(att.channel_id)
                except Exception:
                    logger.exception("could not clear the failure record")
            return
        host._health_last_time_pos = float(time_pos)
        host._health_last_duration = (
            float(duration) if isinstance(duration, (int, float)) else None)
    if paused:
        return

    if time_pos is None:
        if cache_duration:
            return   # data is arriving; neither OPENING nor FROZEN applies
        ticks = host.__dict__.get("_health_opening_ticks", 0) + 1
        host._health_opening_ticks = ticks
        _push_waiting_line(host, ticks)
        if ticks == OPENING_AFTER_TICKS:
            _report_never_started(host, opening=True)
        return

    ticks = host.__dict__.get("_health_stalled_ticks", 0) + 1
    host._health_stalled_ticks = ticks
    _push_waiting_line(host, ticks)
    if ticks == STALLED_AFTER_TICKS:
        _report_never_started(host, stalled=True)


def dropped_mid_stream(last_pos: Any, duration: Any, margin: int = DROP_END_MARGIN_S) -> bool:
    """True when a play ended more than *margin* seconds short of its own
    duration — evidence the SOURCE dropped it, not that the file finished.

    Both must be numeric: a live stream carries no ``duration`` (always
    False), and a resume position past the real end makes ``duration -
    last_pos`` zero or negative (also False) — that shape is the OTHER known
    cause of an instant exit and already has its own message.

    Args:
        last_pos: The play's last known ``time-pos``, or None/absent.
        duration: The file's total length, or None/absent for live.
        margin: How many seconds short of *duration* still counts as
            "finished" rather than "dropped". Defaults to
            :data:`DROP_END_MARGIN_S`.
    """
    if not isinstance(last_pos, (int, float)) or not isinstance(duration, (int, float)):
        return False
    return duration - last_pos > margin


def resume_after_drop(host: Any, exit_reason: "str | None" = None) -> bool:
    """A progressed play whose stream dropped: replay from just before the cut.

    Owner's log, 2026-09-11 04:02-04:05: mpv played a movie for 86s, the
    origin closed the connection, ffmpeg's reconnects were all refused for
    60s, the buffer ran dry, and mpv exited on EOF 157s into a feature-length
    film — read by the rest of this module as the film ending. This is the
    fix: a progressed play (:func:`on_loaded_tick` proved video actually
    arrived) that exits on the stream-ended signature
    (``STREAM_EXIT_REASONS``) far short of its own known ``duration``
    (:func:`dropped_mid_stream`) gets replayed automatically, from five
    seconds before the last position seen, up to :data:`MAX_DROP_RESUMES`
    times per play lineage — then the user is told and left in control.

    Called from :func:`on_player_gone` (a real process exit) and from
    :func:`on_idle_tick`'s first tick after a progressed play (``--idle=yes``
    keeps mpv open with nothing loaded instead of exiting, so there is no
    process-gone event to hook there).

    Returns:
        True when a resume was scheduled (the caller's own report/retry logic
        must not also run); False when this play never progressed, the exit
        wasn't the stream-ended signature, the gap is within *margin* of the
        real end (a live stream, or a genuine finish), or the automatic-resume
        cap has already been used up for this lineage.
    """
    if not host.__dict__.get("_health_ever_progressed"):
        return False
    if exit_reason not in STREAM_EXIT_REASONS:
        return False
    last_pos = host.__dict__.get("_health_last_time_pos")
    if not dropped_mid_stream(last_pos, host.__dict__.get("_health_last_duration")):
        return False
    att = host.__dict__.get("_health_attempt")
    if att is None:
        return False   # nothing to name or re-read — episode playback, no identity
    pos = max(0, int(last_pos) - 5)
    m, ss = pos // 60, f"{pos % 60:02d}"
    if att.drop_resumes >= MAX_DROP_RESUMES:
        host.status(
            f"{att.channel_name}: the stream dropped again at {m}:{ss} — not "
            f"resuming automatically ({MAX_DROP_RESUMES} times already); play it "
            "to pick up from there", ms=0, level="warn")
        logger.warning("stream dropped mid-play for {!r} at {}s of {}s ({}) — "
                       "{} automatic resumes already used, giving up", att.channel_name,
                       last_pos, host._health_last_duration, exit_reason, att.drop_resumes)
        try:
            host.notification_manager.show(
                title="Stream keeps dropping",
                message=(f"{att.channel_name} dropped again at {m}:{ss}. It has been "
                         f"resumed automatically {MAX_DROP_RESUMES} times already — play "
                         "it again to pick up from there."),
                type="warning",
                auto_dismiss_ms=8000,
            )
        except Exception:                                    # pragma: no cover
            logger.exception("could not show the drop-cap notification")
        return False
    host.status(
        f"{att.channel_name}: the stream dropped at {m}:{ss} — resuming in "
        f"{RETRY_AFTER_EXIT_MS // 1000}s", ms=0, level="warn")
    logger.warning("stream dropped mid-play for {!r} at {}s of {}s ({}) — resuming",
                   att.channel_name, last_pos, host._health_last_duration, exit_reason)
    resumed = att._replace(resume_seconds=pos, drop_resumes=att.drop_resumes + 1)
    host._scheduled_replay = resumed
    QTimer.singleShot(RETRY_AFTER_EXIT_MS, lambda: replay(host, resumed))
    return True


def on_player_gone(host: Any, exit_reason: "str | None" = None) -> bool:
    """The last player window disappeared. Returns True if that was a failure.

    *exit_reason* is mpv's own ``Exiting... (reason)`` line, captured by
    ``core/players/mpv_log_tap.py``. It is what separates the two shapes that
    used to be one: a LOADED file the user closed (``Quit``, silent — the
    negative case this module is built around) from a loaded file whose
    stream gave mpv nothing and ended the process (``End of file`` /
    ``Errors when loading file`` while still OPENING — reported, and the one
    shape :func:`retry_candidate` retries). 2026-09-06 10:11: a cold play on
    a one-connection source did exactly that inside 30 s, and the old
    "it loaded, so it played" rule kept it silent.

    The OTHER shape of "it never played", and the one the idle counter above
    cannot see: mpv runs with ``--idle=once`` when the user has asked it to
    close when finished, so a file that ends immediately makes the whole
    process EXIT. There is then no instance to probe, the health poll stops,
    and nothing was ever reported.

    Reproduced locally 2026-09-02 against a range-capable server with the app's
    exact flags: ``loadfile … start=90`` on a 60-second file ends the file at
    once and mpv is gone within a second. A resume position past the real end
    does that — and playback carries one on every part-watched title.

    (The slow-server theory was tested at the same time and is NOT this: with
    ``--cache-pause-initial=yes --cache-pause-wait=10`` a 20 KB/s stream starts
    inside three seconds.)

    Checked FIRST, ahead of every branch below (PLAY-17): a progressed play
    that dropped mid-stream is neither "the user closed it" nor "never
    started" — see :func:`resume_after_drop`. When it schedules a resume this
    returns True so the caller's own retry logic does not ALSO fire (its own
    ``retry_candidate`` requires ``_health_stream_exit``, which a progressed
    play never sets, so it is harmless either way — this just keeps the two
    paths explicit rather than relying on that).
    """
    if resume_after_drop(host, exit_reason):
        return True
    if host.__dict__.get("_health_ever_progressed"):
        return False               # it played, then the user closed it
    if (host.__dict__.get("_health_ever_played")
            and exit_reason not in STREAM_EXIT_REASONS):
        return False               # loaded, then closed (or reason unknown) — silent
    return _report_never_started(host, exited=True, exit_reason=exit_reason)


def schedule_retry(host: Any) -> bool:
    """After a reported stream-ended exit: tell the user and replay ONCE later.

    Waits :data:`RETRY_AFTER_EXIT_MS` (the source's connection lag) and then
    replays through ``host.play_media(..., skip_probe=True)`` — the probe is the
    extra connection a one-connection source would refuse again. Returns True
    when a retry was scheduled.
    """
    att = retry_candidate(host)
    if att is None:
        return False
    host.status(
        f"{att.channel_name}: the stream closed before it started — retrying in "
        f"{RETRY_AFTER_EXIT_MS // 1000}s", ms=0, level="warn")
    host._scheduled_replay = att
    QTimer.singleShot(RETRY_AFTER_EXIT_MS, lambda: replay(host, att))
    return True


def replay(host: Any, attempt: PlayAttempt) -> None:
    """The scheduled retry: re-read the title off-thread, then play it probe-free.

    Skipped unless ``attempt`` is BOTH the exact object the retry was
    scheduled for (``host._scheduled_replay``) AND still names the play the
    host is watching (by ``channel_id`` — PLAY-17's drop-resume schedules a
    ``_replace()``d COPY of the live ``PlayAttempt``, never the original
    object, so an object-identity check against ``host._health_attempt``
    alone would reject every legitimate drop-resume). The 20s delay is long
    enough for the user to have started something else in the meantime, and a
    stale retry must not replace it (2026-09-11 02:12: title A's scheduled
    retry fired at 02:12:41 and replaced title B, which the user had played at
    02:12:26, six seconds after A's retry was scheduled). :func:`arm` clears
    ``_scheduled_replay`` on every new play, which is what makes the skip work.
    """
    current = host.__dict__.get("_health_attempt")
    scheduled = host.__dict__.get("_scheduled_replay")
    if (scheduled is not attempt or current is None
            or current.channel_id != attempt.channel_id):
        logger.info("retry for {!r} skipped — {!r} has been played since",
                    attempt.channel_name, getattr(current, "channel_name", "another title"))
        return
    logger.info("retrying {!r} once after the player exited while opening", attempt.channel_name)
    host._run_query(
        lambda repos: repos.channels.get_playable_dto(attempt.channel_id),
        lambda ch: ch is not None and host.play_media(
            ch, start_override=attempt.resume_seconds or None, skip_probe=True,
            drop_resumes=attempt.drop_resumes),
        on_error=lambda e: _on_replay_failed(host, attempt, e),
    )


def _on_replay_failed(host: Any, attempt: PlayAttempt, exc: Exception) -> None:
    """The scheduled retry's own re-read raised — say so, rather than leaving
    the user staring at "retrying in Xs" with nothing then happening."""
    logger.warning(f"Retry for {attempt.channel_name!r} failed: {exc}")
    host.status(
        f"{attempt.channel_name}: retry failed — couldn't reload the channel",
        ms=0, level="error")


def retry_candidate(host: Any) -> "Optional[PlayAttempt]":
    """The attempt to replay once, or None — only after :func:`on_player_gone`
    reported a stream-ended exit, and never for a play that already IS the retry."""
    att = host.__dict__.get("_health_attempt")
    if att is None or att.retry or not host.__dict__.get("_health_stream_exit"):
        return None
    return att


def on_idle_tick(host: Any) -> bool:
    """Count one "nothing loaded" probe. Returns True when polling should stop.

    Reports the failure exactly once, on the tick that crosses the threshold —
    a report every 2s for as long as the window sits there would be its own bug.

    PLAY-17: with ``--idle=yes`` (``close_player_when_finished`` off) mpv
    stays running with nothing loaded after EOF instead of exiting, so
    :func:`on_player_gone` — which needs a vanished PROCESS — never fires for
    a drop. The FIRST idle tick after a progressed play is the equivalent
    event here; ``exit_reason`` is synthesised as ``"End of file"`` (the drop
    signature :func:`resume_after_drop` keys on) because there is no real exit
    line to read — mpv's own idle state, right after a play that was
    genuinely advancing with no user action in between, is itself the
    evidence.
    """
    ticks = host.__dict__.get("_health_idle_ticks", 0) + 1
    host._health_idle_ticks = ticks

    if ticks == 1 and host.__dict__.get("_health_ever_progressed"):
        resume_after_drop(host, "End of file")

    if ticks == FAILED_AFTER_TICKS and not host.__dict__.get("_health_ever_played"):
        _report_never_started(host)

    return ticks >= STOP_POLLING_AFTER_TICKS


def prestart_detail(event_start: "datetime | None", now: "datetime") -> "str | None":
    """The pre-start explanation, or None when it doesn't apply.

    Single chokepoint for the one detail line both "a fixture played before
    its start" surfaces need — the pre-flight failure toast
    (``main_window_streaming._on_stream_ready``) and the never-started report
    below. Two hand-rolled copies of this sentence is exactly what the
    chokepoint rules forbid.

    ``now`` is injected, never read from the clock in here (the injected-clock
    rule) — callers pass ``epg_utils.now_utc()``.

    Args:
        event_start: The fixture's UTC-naive start time, or None for anything
            that isn't a dated event.
        now: The current UTC-naive instant.

    Returns:
        The detail sentence naming the local start time, or None when there is
        no event start or it has already begun.
    """
    if event_start is None or event_start <= now:
        return None
    start_local = epg_utils.to_local(event_start)
    return f"This event hasn't started — scheduled for {start_local:%H:%M}."


def _report_never_started(host: Any, *, exited: bool = False, stalled: bool = False,
                           opening: bool = False, exit_reason: "str | None" = None) -> bool:
    """Tell the user, and put it in the retry ledger. Returns whether it did.

    Reports at most once per play: both callers can fire for the same failure,
    and two toasts for one click is its own bug.

    Wrapped in its own try: a stream that failed to play must not also take out
    the polling loop that noticed.
    """
    if host.__dict__.get("_health_reported"):
        return False
    host.__dict__["_health_reported"] = True
    attempt = host.__dict__.get("_health_attempt")
    name = attempt.channel_name if attempt else "that channel"
    resume = getattr(attempt, "resume_seconds", 0) or 0
    stream_exit = exited and exit_reason in STREAM_EXIT_REASONS
    host.__dict__["_health_stream_exit"] = stream_exit
    if exited:
        logger.warning("playback never started for {!r} — the player exited "
                       "without playing anything (reason={!r}, resume={}s)",
                       name, exit_reason, resume)
    elif stalled:
        logger.warning("playback never started for {!r} — a file loaded but playback "
                       "never advanced within {}s (resume={}s)", name, STALLED_AFTER_TICKS * 2, resume)
    elif opening:
        logger.warning("playback never started for {!r} — mpv never received any "
                       "demuxer data within {}s (resume={}s)", name, OPENING_AFTER_TICKS * 2, resume)
    else:
        logger.warning(
            "playback never started for {!r} — mpv accepted the file and loaded "
            "nothing within {}s", name, FAILED_AFTER_TICKS * 2)
    try:
        host.status(f"Nothing is playing: {name}", ms=0, level="warn")
    except Exception:                                    # pragma: no cover
        logger.exception("could not update the status bar")
    try:
        # A pre-start fixture wins over every other guess — it is the one case
        # the app can actually EXPLAIN rather than speculate about, so it takes
        # precedence over the resume-position detail below when both apply.
        event_start = getattr(attempt, "event_start_time", None)
        prestart = prestart_detail(event_start, epg_utils.now_utc())
        # A same-provider switch that timed out mid-OPENING names the actual
        # cause (the source counting the previous stream) rather than the
        # generic "busy or dead" guess — see gui/stream_switch.py (PLAY-10).
        same_provider_switch = opening and host.__dict__.get("_switch_same_provider")
        # A resume is named explicitly when there was one: a saved position
        # past the real end of the file ends it instantly, which is the one
        # cause of this the USER can do something about (play from the start).
        detail = (
            f"The player exited while still opening the stream ({exit_reason}); "
            "the source most likely refused a second connection it was still "
            f"counting. Retrying once in {RETRY_AFTER_EXIT_MS // 1000}s."
            if stream_exit and attempt is not None and not attempt.retry else
            "The source was still counting the previous stream; it did not "
            "free the connection in time." if same_provider_switch else
            prestart if prestart is not None else
            "The source may be busy or the stream dead."
            if not resume else
            f"It was resuming at {resume // 60}m{resume % 60:02d}s — if "
            "that is past the end of this file, playing from the start "
            "will work.")
        message = (f"{name} loaded but never began playing. {detail}"
                   if stalled else
                   f"{name} was accepted by the source but no video arrived. {detail}")
        host.notification_manager.show(
            title="Stream did not start",
            message=message,
            type="warning",
            auto_dismiss_ms=8000,
        )
    except Exception:                                    # pragma: no cover
        logger.exception("could not show the failure notification")
    if attempt is None:
        return True
    try:
        host.stream_retry_manager.add_failure(
            attempt.channel_id, attempt.channel_name, attempt.stream_url,
            "playback never started")
    except Exception:                                    # pragma: no cover
        logger.exception("could not record the failed play")
    return True


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
