"""Record a live channel to disk — warn, count down, then take the connection.

Built to the decisions settled 2026-08-30 (design artifact "Catch, Keep,
Record"), which are not re-litigated here.

**Warn and take.** One connection per source means a recording and playback
cannot both have it, and the recording wins: a programme missed is gone, and
the viewer can watch the recording afterwards. What makes taking acceptable is
that it is never a surprise —

    if nothing is playing        the recording just starts, silently.
                                 An idle app is not interrupted.
    if you are watching          the countdown escalates at 10 min / 5 / 1
                                 / 30 s, and EVERY step can cancel the
                                 recording.

``preempt_playback`` is per-recording, so "take it" is the default and not a
law.

**The stop time is never frozen.** ``RecordingDB.effective_end`` is recomputed
on every tick from the guide window plus the signed offsets plus
``extend_seconds``, because a running recording can be extended in real time —
the one thing that saves an event that ran long. Offsets are signed: skipping a
pregame hour is ``-60 min`` on the start, as legitimate as ``+15`` on the end.

**Conflicts are found when you schedule, not when it starts.** Being told at
19:00 that two recordings want the same connection is useless; being told when
you add the second one is actionable.

**Recordings/ and Downloads/ are separate folders under the same root.**

**Direct HTTP GET, not mpv ``--stream-record``.** The recorder must not share an
mpv instance with the player. A dropped connection reconnects and APPENDS, so a
blip costs the blip rather than the recording. There is no Range request and no
resume: a live stream has no meaningful byte offset.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import requests
from loguru import logger

from metatv.core.download_manager import library_dir, safe_filename


def recordings_dir(config) -> "Path":
    """``<root>/Recordings`` — a sibling of Downloads, never the same folder.

    Settled 2026-08-30: "Separate folder, same root. Downloads/ and Recordings/
    side by side." A recording is a different KIND of thing from a saved film —
    it is dated, it may be partial, and it is the one a media server should not
    file as a movie.
    """
    return library_dir(config) / "Recordings"
from metatv.core.epg_utils import now_utc
from metatv.core.http_headers import STREAM_HTTP_HEADERS

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.connection_accountant import ConnectionAccountant
    from metatv.core.database import Database

#: Bytes per read. Matches the download manager for the same reason: big enough
#: not to be syscall-bound, small enough that a stop is felt at once.
CHUNK_BYTES = 256 * 1024

#: How often the scheduler looks for work.
POLL_SECONDS = 2.0

#: How long to wait before retrying a recording that could not get a slot.
#: Short, because the whole point is to catch the moment playback ends.
RETRY_SECONDS = 5.0

#: Kinds a recording may evict. It takes playback's slot too — that is the
#: settled rule, softened by the countdown rather than by yielding. A recording
#: with ``preempt_playback`` cleared falls back to ``_POLITE_PREEMPTS``.
RECORDING_PREEMPTS: tuple[str, ...] = ("download", "playback")

#: What a recording may evict when the user has told THIS one not to take the
#: stream. Downloads still yield — they lose nothing by waiting.
_POLITE_PREEMPTS: tuple[str, ...] = ("download",)

#: Seconds before the start at which the user is warned, longest first. Every
#: one of these is a chance to cancel, which is what makes taking acceptable.
COUNTDOWN_STEPS: tuple[int, ...] = (600, 300, 60, 30)

#: Terminal states — a row in one of these is never picked up again.
TERMINAL_STATES = ("completed", "failed", "cancelled")


@dataclass(frozen=True)
class ScheduleOutcome:
    """What scheduling did, including collisions the caller must resolve.

    ``conflicts`` is a list of ``(recording_id, title)`` already wanting this
    source's one connection for an overlapping window. Reported at SCHEDULE
    time by design — the caller offers to drop one while the user is still
    thinking about it, rather than discovering it at 19:00.
    """

    recording_id: "str | None"
    conflicts: "list[tuple[str, str]]" = field(default_factory=list)
    reason: str = ""

    @property
    def scheduled(self) -> bool:
        return self.recording_id is not None


@dataclass(frozen=True)
class RecordingProgress:
    """A snapshot for the UI. Plain data — never an ORM row across a thread."""

    recording_id: str
    channel_id: str
    channel_name: str
    programme_title: str
    state: str
    starts_at: datetime
    ends_at: datetime
    recorded_bytes: int
    dest_path: str
    error: Optional[str]
    waiting_for_slot: bool

    def elapsed_fraction(self, *, now: Optional[datetime] = None) -> float:
        """How far through its WINDOW this recording is, 0.0-1.0.

        Wall-clock, not bytes: a live stream has no total size, so the only
        honest progress bar is the clock. Takes ``now`` rather than reaching for
        it, so a caller can render a fixed moment and a test can pin one.
        """
        now = now or now_utc()
        span = (self.ends_at - self.starts_at).total_seconds()
        if span <= 0:
            return 1.0
        done = (now - self.starts_at).total_seconds()
        return max(0.0, min(1.0, done / span))


class RecordingManager:
    """Schedules and runs recordings, one worker thread, no Qt.

    Holds no widgets and imports no Qt: the GUI polls :meth:`progress` and the
    manager never reaches back. Same shape as ``DownloadManager`` so the two
    read as a pair.
    """

    def __init__(self, db: "Database", config,
                 accountant: "ConnectionAccountant",
                 *, on_conflict: Optional[Callable[[str, str], None]] = None,
                 on_countdown: Optional[Callable[[str, str, int], None]] = None):
        """
        Args:
            db: Database handle; every read/write goes through ``session_scope``.
            config: Supplies the library directory and the padding defaults.
            accountant: The ONE connection arbiter — the same instance the
                player and the downloader use, or the counts disagree.
            on_conflict: Called with ``(recording_id, channel_name)`` the FIRST
                time a recording cannot get a slot, so the UI can say so once.
                Called from the worker thread; the GUI side must marshal.
        """
        self.db = db
        self.config = config
        self.accountant = accountant
        self._on_conflict = on_conflict
        self._on_countdown = on_countdown
        #: recording_id -> the COUNTDOWN_STEPS already announced for it, so a
        #: ten-minute warning is given once rather than every two seconds.
        self._counted_down: dict[str, set[int]] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        #: recording_id -> True once the user has been told about a conflict,
        #: so a recording that retries for forty minutes notifies once.
        self._conflict_announced: set[str] = set()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler thread. Idempotent."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="recordings", daemon=True)
        self._thread.start()
        logger.debug("Recording scheduler started")

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the scheduler and let the in-flight write finish its chunk.

        Registered through ``MainWindow._register_cleanable``. A recording cut
        off by a quit keeps what it wrote — the file is a valid TS up to the
        last chunk, which is the best available answer to "the app closed".
        """
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    # ── public API ───────────────────────────────────────────────────────────

    def schedule(self, channel_id: str, provider_id: str, channel_name: str,
                 source_url: str, starts_at: datetime, ends_at: datetime,
                 *, programme_title: str = "",
                 pad_start_seconds: "int | None" = None,
                 pad_end_seconds: "int | None" = None,
                 preempt_playback: bool = True) -> "ScheduleOutcome":
        """Schedule a recording of a guide programme.

        Args:
            starts_at: The PROGRAMME's start, UTC-naive and unpadded. Padding is
                not folded in here — the offsets are stored beside it so the
                stop time stays computable, and extendable, later.
            ends_at: The programme's end, UTC-naive and unpadded.
            pad_start_seconds: Signed offset on the start; the configured
                default when omitted. Negative starts earlier.
            pad_end_seconds: Signed offset on the end. Positive runs over.
            preempt_playback: Whether this one may take the connection off
                playback after its countdown.

        Returns:
            A :class:`ScheduleOutcome`. ``conflicts`` is non-empty when another
            recording already wants this source's connection for an overlapping
            window — reported HERE rather than at start time, because being told
            at 19:00 that two recordings collide is useless and being told while
            adding the second one is actionable.
        """
        if ends_at <= starts_at:
            logger.warning("Refusing a recording that ends before it starts: "
                           "{} .. {}", starts_at, ends_at)
            return ScheduleOutcome(recording_id=None, reason="backwards window")

        from metatv.core.database import RecordingDB

        if pad_start_seconds is None:
            pad_start_seconds = int(self.config.recording_pad_start_seconds)
        if pad_end_seconds is None:
            pad_end_seconds = int(self.config.recording_pad_end_seconds)

        window_start = starts_at + timedelta(seconds=pad_start_seconds)
        window_end = ends_at + timedelta(seconds=pad_end_seconds)
        title = programme_title or channel_name
        dest = recordings_dir(self.config) / safe_filename(
            f"{title} {window_start:%Y-%m-%d %H%M}", source_url,
            default_suffix=".ts")

        with self.db.session_scope() as session:
            live = session.query(RecordingDB).filter(
                RecordingDB.state.notin_(TERMINAL_STATES)).all()

            for row in live:
                if (row.channel_id == channel_id
                        and row.programme_start == starts_at):
                    return ScheduleOutcome(recording_id=None,
                                           reason="already scheduled")

            # A conflict is same SOURCE (one connection) and overlapping window.
            # A different source is not a conflict at all — its connection is
            # its own.
            conflicts = [
                (row.id, row.programme_title or row.channel_name)
                for row in live
                if row.provider_id == provider_id
                and row.effective_start < window_end
                and window_start < row.effective_end
            ]

            recording_id = str(uuid.uuid4())
            session.add(RecordingDB(
                id=recording_id, channel_id=channel_id, provider_id=provider_id,
                channel_name=channel_name, programme_title=programme_title,
                source_url=source_url, dest_path=str(dest),
                programme_start=starts_at, programme_end=ends_at,
                pad_start_seconds=pad_start_seconds,
                pad_end_seconds=pad_end_seconds,
                preempt_playback=preempt_playback,
                state="scheduled"))
        self._wake.set()
        logger.info("Recording scheduled: {} {} .. {} ({} conflict(s))",
                    title, window_start, window_end, len(conflicts))
        return ScheduleOutcome(recording_id=recording_id, conflicts=conflicts)

    def extend(self, recording_id: str, seconds: int) -> "datetime | None":
        """Push a recording's stop time out (or in) while it runs.

        The reason the stop time is never frozen. Returns the new effective end,
        or None if the recording is gone. Accepts a negative value — stopping a
        recording early is the same operation.
        """
        from metatv.core.database import RecordingDB

        with self.db.session_scope() as session:
            row = session.get(RecordingDB, recording_id)
            if row is None:
                return None
            row.extend_seconds = int(row.extend_seconds) + int(seconds)
            new_end = row.effective_end
        self._wake.set()
        logger.info("Recording {} now ends {}", recording_id, new_end)
        return new_end

    def window_of(self, recording_id: str) -> "tuple[datetime, datetime] | None":
        """The EFFECTIVE window right now — offsets and any live extension.

        A caller that schedules a programme holds the guide's times, not these,
        so a notification built from the guide would promise a stop fifteen
        minutes before the recording actually stops. Recomputed on read rather
        than stored, so it stays right after ``extend``.
        """
        from metatv.core.database import RecordingDB

        with self.db.session_scope() as session:
            row = session.get(RecordingDB, recording_id)
            return ((row.effective_start, row.effective_end)
                    if row is not None else None)

    def cancel(self, recording_id: str) -> None:
        """Cancel a scheduled or running recording.

        A running one stops at its next chunk and keeps what it has: bytes on
        disk are a watchable programme, and deleting them would be a surprise.
        """
        self._set_state(recording_id, "cancelled")
        self._wake.set()

    def progress(self) -> list[RecordingProgress]:
        """Every non-terminal recording, newest window first. Safe from any thread."""
        from metatv.core.database import RecordingDB

        with self.db.session_scope() as session:
            rows = session.query(RecordingDB).filter(
                RecordingDB.state.notin_(TERMINAL_STATES)
            ).order_by(RecordingDB.starts_at.desc()).all()
            return [RecordingProgress(
                recording_id=r.id, channel_id=r.channel_id,
                channel_name=r.channel_name, programme_title=r.programme_title or "",
                state=r.state, starts_at=r.effective_start,
                ends_at=r.effective_end,
                recorded_bytes=r.recorded_bytes, dest_path=r.dest_path,
                error=r.error,
                waiting_for_slot=r.id in self._conflict_announced
                and r.state == "scheduled",
            ) for r in rows]

    # ── the scheduler ────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Poll for due work until shutdown."""
        while not self._stop.is_set():
            try:
                self._step()
            except Exception:                        # pragma: no cover - guard
                logger.exception("Recording scheduler step failed")
            self._wake.wait(POLL_SECONDS)
            self._wake.clear()

    def _step(self) -> None:
        """Retire dead windows, warn about imminent takes, then run what is due."""
        self._retire_missed()
        self._announce_countdowns()
        row = self._next_due()
        if row is None:
            return
        self._record(row)

    def _announce_countdowns(self) -> None:
        """Warn before a recording takes the connection off playback.

        Only when it MATTERS: if nothing is holding a playback slot on that
        source, an idle app is not interrupted and nothing is emitted. When
        something is playing, each threshold in ``COUNTDOWN_STEPS`` fires once,
        and every one of them is a chance for the user to cancel — which is
        what makes taking the stream acceptable rather than hostile.
        """
        from metatv.core.database import RecordingDB

        now = now_utc()
        with self.db.session_scope() as session:
            pending = [
                (r.id, r.programme_title or r.channel_name, r.provider_id,
                 r.effective_start)
                for r in session.query(RecordingDB).filter(
                    RecordingDB.state == "scheduled").all()
                if r.preempt_playback and r.effective_start > now
            ]

        for recording_id, title, provider_id, starts in pending:
            if not self._playback_holds(provider_id):
                continue
            remaining = (starts - now).total_seconds()
            crossed = [step for step in COUNTDOWN_STEPS if remaining <= step]
            if not crossed:
                continue
            # The TIGHTEST crossed step is the one worth saying. With 59s left
            # the honest warning is "in 1 minute", not "in 10 minutes" — which
            # is what a first-match loop over the steps announced.
            #
            # Only that step is marked spent. Marking every looser one too was
            # my first version and it is wrong: the single case where the two
            # differ is a guide start DRIFTING LATER after a warning fired, and
            # there the user should get the approach warnings again rather than
            # silence. A mutation test caught it as unjustifiable code.
            tightest = min(crossed)
            fired = self._counted_down.setdefault(recording_id, set())
            if tightest not in fired:
                fired.add(tightest)
                self._emit_countdown(recording_id, title, tightest)

    def _playback_holds(self, provider_id: str) -> bool:
        """Whether something is actually playing on this source right now."""
        return any(h.kind == "playback"
                   for h in self.accountant.holders(provider_id))

    def _emit_countdown(self, recording_id: str, title: str, seconds: int) -> None:
        if self._on_countdown is None:
            return
        try:
            self._on_countdown(recording_id, title, seconds)
        except Exception:                            # pragma: no cover - guard
            logger.exception("Recording countdown callback failed")

    def _retire_missed(self) -> None:
        """Fail any recording whose whole window went by without a slot.

        This is the honest end of "keep trying for the whole window": once
        ``ends_at`` is past there is nothing left to catch, and the row must
        stop being retried and start being a visible failure. A recording that
        got SOME bytes is completed, not failed — partial is the outcome the
        retry policy exists to produce.
        """
        from metatv.core.database import RecordingDB

        now = now_utc()
        with self.db.session_scope() as session:
            # Filtered in Python, not SQL: effective_end is computed from three
            # columns plus a live extension, so there is no column to compare.
            # The non-terminal set is small — it is what is scheduled, not history.
            candidates = session.query(RecordingDB).filter(
                RecordingDB.state.notin_(TERMINAL_STATES)).all()
            for row in [r for r in candidates if r.effective_end <= now]:
                if row.recorded_bytes > 0:
                    row.state = "completed"
                else:
                    row.state = "failed"
                    row.error = row.error or (
                        "The source's only connection was in use for the whole "
                        "programme.")
                self._conflict_announced.discard(row.id)

    def _next_due(self) -> Optional[dict]:
        """The earliest recording whose window contains now. Plain dict, not ORM."""
        from metatv.core.database import RecordingDB

        now = now_utc()
        with self.db.session_scope() as session:
            due = [r for r in session.query(RecordingDB).filter(
                RecordingDB.state.in_(("scheduled", "recording"))
            ).order_by(RecordingDB.programme_start).all()
                if r.effective_start <= now < r.effective_end]
            if not due:
                return None
            row = due[0]
            return {"id": row.id, "channel_id": row.channel_id,
                    "provider_id": row.provider_id,
                    "channel_name": row.channel_name,
                    "programme_title": row.programme_title or "",
                    "source_url": row.source_url, "dest_path": row.dest_path,
                    "preempt_playback": bool(row.preempt_playback),
                    "recorded_bytes": row.recorded_bytes}

    def _record(self, row: dict) -> None:
        """Hold a slot and write the stream to disk until the window closes.

        Appends rather than truncates: a reconnection inside the window costs
        the seconds it was down, not the minutes already on disk.
        """
        recording_id = row["id"]
        holder = f"recording:{recording_id}"
        # The countdown has already run by now, so taking the stream here is
        # the announced outcome rather than a surprise. A recording the user
        # told not to preempt still displaces downloads — they lose nothing.
        preempts = (RECORDING_PREEMPTS if row["preempt_playback"]
                    else _POLITE_PREEMPTS)
        result = self.accountant.acquire(
            row["provider_id"], "recording", holder, preempt_kinds=preempts)
        if not result.granted:
            # Only reachable for a polite recording, or a source at capacity
            # with something this one may not evict. It keeps trying for the
            # rest of its window — partial beats nothing.
            self._announce_conflict(recording_id, row["channel_name"])
            self._stop.wait(RETRY_SECONDS)
            return
        if result.preempted:
            logger.info("Recording {} took the connection from {}",
                        recording_id, list(result.preempted))
        self._counted_down.pop(recording_id, None)

        self._conflict_announced.discard(recording_id)
        self._set_state(recording_id, "recording")
        written = row["recorded_bytes"]
        dest = Path(row["dest_path"])
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            response = requests.get(row["source_url"], stream=True, timeout=30,
                                    headers=STREAM_HTTP_HEADERS)
            response.raise_for_status()
            with open(dest, "ab") as handle:
                for chunk in response.iter_content(CHUNK_BYTES):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    written += len(chunk)
                    if self._stop.is_set():
                        break
                    # Re-read, never cache: extend() may have moved the stop
                    # time since this loop began, and honouring a cached one is
                    # exactly the frozen-stop-time bug the design forbids.
                    ends_at = self._ends_at(recording_id)
                    if ends_at is None or now_utc() >= ends_at:
                        break
                    if self._state_of(recording_id) == "cancelled":
                        break
        except Exception as exc:
            logger.warning("Recording {} interrupted: {}", recording_id, exc)
            # NOT a failure: the window may still have time left, and the next
            # poll reconnects and appends. Only _retire_missed decides failure.
            self._flush(recording_id, written)
            return
        finally:
            self.accountant.release(row["provider_id"], holder)

        self._flush(recording_id, written)
        final_end = self._ends_at(recording_id)
        if final_end is not None and now_utc() >= final_end:
            self._set_state(recording_id, "completed")
            logger.info("Recording finished: {} ({} bytes)",
                        row["programme_title"] or row["channel_name"], written)

    def _announce_conflict(self, recording_id: str, channel_name: str) -> None:
        """Tell the user once that a recording is waiting, not silently lost."""
        if recording_id in self._conflict_announced:
            return
        self._conflict_announced.add(recording_id)
        if self._on_conflict is not None:
            try:
                self._on_conflict(recording_id, channel_name)
            except Exception:                        # pragma: no cover - guard
                logger.exception("Recording conflict callback failed")

    # ── row helpers ──────────────────────────────────────────────────────────

    def _ends_at(self, recording_id: str) -> "datetime | None":
        """The CURRENT stop time, including any live extension."""
        from metatv.core.database import RecordingDB

        with self.db.session_scope() as session:
            row = session.get(RecordingDB, recording_id)
            return row.effective_end if row is not None else None

    def _state_of(self, recording_id: str) -> str:
        from metatv.core.database import RecordingDB

        with self.db.session_scope() as session:
            row = session.get(RecordingDB, recording_id)
            return row.state if row else "cancelled"

    def _set_state(self, recording_id: str, state: str) -> None:
        from metatv.core.database import RecordingDB

        with self.db.session_scope() as session:
            row = session.get(RecordingDB, recording_id)
            if row is not None and row.state not in TERMINAL_STATES:
                row.state = state

    def _flush(self, recording_id: str, written: int) -> None:
        """Persist the byte count. Always called on the way out of a transfer.

        Unconditional, unlike the download manager's throttled flush — a
        recording writes for an hour and this runs once per reconnection, so
        there is nothing to throttle and nothing to swallow. (The throttle is
        exactly what made a finished download report 25%.)
        """
        from metatv.core.database import RecordingDB

        with self.db.session_scope() as session:
            row = session.get(RecordingDB, recording_id)
            if row is not None:
                row.recorded_bytes = written
