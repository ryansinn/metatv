"""Record a live channel to disk on a schedule — and never yield the slot.

**The priority rule is inverted from downloads, and that inversion is the whole
design.** A paused download loses nothing: it resumes at the byte it reached and
the file is identical. A paused recording loses the minutes it was paused for,
and those minutes are not coming back. So recordings sit on the other side of
the recoverability axis:

===================  =========================  ==========================
                     Download                   Recording
===================  =========================  ==========================
Evicted by playback  yes — resumes by itself    **no**
Evicts downloads     no                         **yes**
Evicts playback      no                         no — see below
Interruption costs   time                       **the content**
===================  =========================  ==========================

**Why a recording does not evict playback either.** Yanking the stream out from
under someone who is sitting there watching is the most hostile thing a media
app can do, and it would arrive with no warning at a programme boundary. Instead
a recording that cannot get a slot KEEPS TRYING for its whole window: stop
watching twenty minutes in and the last forty minutes are recorded. Partial beats
nothing, and it beats a stolen stream. The user is told once, when the first
attempt fails, so a silent miss is impossible.

**Why a direct HTTP GET and not mpv ``--stream-record``.** Same conclusion as
downloads, different reason. There, resume settled it. Here it is ownership: the
recorder must not share an mpv instance with the player, and spawning a second
one purely to write bytes to a file buys a process, a socket and an instance-key
collision to solve nothing. A live Xtream URL is an endless MPEG-TS — reading it
until a deadline IS the recording.

There is no Range request and no resume: a live stream has no meaningful byte
offset, and a reconnection starts from "now" whatever we ask for. A dropped
connection inside the window reconnects and APPENDS, so a blip costs the blip
rather than the recording.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import requests
from loguru import logger

from metatv.core.download_manager import library_dir, safe_filename
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

#: Kinds a recording may evict. Downloads yield to us; playback does not.
RECORDING_PREEMPTS: tuple[str, ...] = ("download",)

#: Terminal states — a row in one of these is never picked up again.
TERMINAL_STATES = ("completed", "failed", "cancelled")


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
                 *, on_conflict: Optional[Callable[[str, str], None]] = None):
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
                 *, programme_title: str = "", pad: bool = True) -> Optional[str]:
        """Schedule a recording. Returns its id, or None if it duplicates one.

        Args:
            starts_at: UTC-naive, like every other time in this codebase
                (CLAUDE.md: EPG times are UTC-naive; convert for display only).
            ends_at: UTC-naive. Must be after ``starts_at``.
            pad: Apply the configured lead-in/run-over. True for a programme
                picked from the EPG — broadcasters overrun and clocks disagree.
                False for "record for exactly N minutes", where the user has
                already said what they mean.

        Returns:
            The new recording's id, or ``None`` if an identical window on this
            channel is already scheduled.
        """
        if ends_at <= starts_at:
            logger.warning("Refusing a recording that ends before it starts: "
                           "{} .. {}", starts_at, ends_at)
            return None
        if pad:
            starts_at -= timedelta(
                seconds=int(getattr(self.config, "recording_pad_start_seconds", 60)))
            ends_at += timedelta(
                seconds=int(getattr(self.config, "recording_pad_end_seconds", 300)))

        from metatv.core.database import RecordingDB

        title = programme_title or channel_name
        dest = library_dir(self.config) / safe_filename(
            f"{title} {starts_at:%Y-%m-%d %H%M}", source_url, default_suffix=".ts")

        with self.db.session_scope() as session:
            clash = session.query(RecordingDB).filter(
                RecordingDB.channel_id == channel_id,
                RecordingDB.starts_at == starts_at,
                RecordingDB.state.notin_(TERMINAL_STATES),
            ).first()
            if clash is not None:
                return None
            recording_id = str(uuid.uuid4())
            session.add(RecordingDB(
                id=recording_id, channel_id=channel_id, provider_id=provider_id,
                channel_name=channel_name, programme_title=programme_title,
                source_url=source_url, dest_path=str(dest),
                starts_at=starts_at, ends_at=ends_at, state="scheduled"))
        self._wake.set()
        logger.info("Recording scheduled: {} {} .. {}", title, starts_at, ends_at)
        return recording_id

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
                state=r.state, starts_at=r.starts_at, ends_at=r.ends_at,
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
        """Retire windows that have passed, then run whatever is due now."""
        self._retire_missed()
        row = self._next_due()
        if row is None:
            return
        self._record(row)

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
            for row in session.query(RecordingDB).filter(
                RecordingDB.ends_at <= now,
                RecordingDB.state.notin_(TERMINAL_STATES),
            ).all():
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
            row = session.query(RecordingDB).filter(
                RecordingDB.starts_at <= now,
                RecordingDB.ends_at > now,
                RecordingDB.state.in_(("scheduled", "recording")),
            ).order_by(RecordingDB.starts_at).first()
            if row is None:
                return None
            return {"id": row.id, "channel_id": row.channel_id,
                    "provider_id": row.provider_id,
                    "channel_name": row.channel_name,
                    "programme_title": row.programme_title or "",
                    "source_url": row.source_url, "dest_path": row.dest_path,
                    "ends_at": row.ends_at,
                    "recorded_bytes": row.recorded_bytes}

    def _record(self, row: dict) -> None:
        """Hold a slot and write the stream to disk until the window closes.

        Appends rather than truncates: a reconnection inside the window costs
        the seconds it was down, not the minutes already on disk.
        """
        recording_id = row["id"]
        holder = f"recording:{recording_id}"
        result = self.accountant.acquire(
            row["provider_id"], "recording", holder,
            preempt_kinds=RECORDING_PREEMPTS)
        if not result.granted:
            self._announce_conflict(recording_id, row["channel_name"])
            self._stop.wait(RETRY_SECONDS)
            return

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
                    if self._stop.is_set() or now_utc() >= row["ends_at"]:
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
        if now_utc() >= row["ends_at"]:
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
