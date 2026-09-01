"""Save a VOD to the local library — queued, resumable, and connection-aware.

**Why a direct HTTP GET and not mpv ``--stream-record``.** Xtream VOD URLs are
static files (``/movie/<user>/<pass>/<id>.mkv``), so a byte range can be asked
for — and a download that playback preempts has to CONTINUE rather than start
again. ``--stream-record`` cannot resume, which settles the mechanism. (The
ephemeral deep cache still uses it; that one is thrown away, so restarting costs
nothing.)

**The connection rule is the feature, not a detail.** Every one of the owner's
providers reports ``max_connections = 1``, so a download and a playback on the
same source are always in contention. Slots come from the one
:class:`ConnectionAccountant` — never a second counter that could disagree with
the player — with ``kind="download"``, and playback evicts us through the
``preempt_kinds`` seam. Preemption is not failure: the row goes to ``paused``
with ``paused_by_playback`` set, and comes back on its own when the slot frees.

**Per-source, not global.** A download on source B keeps running while you watch
source A. The scheduler asks the accountant per provider, so that falls out
rather than being special-cased.

Headers come from :mod:`metatv.core.http_headers`, the same ones mpv plays with.
A provider that gates on User-Agent will 403 a bare request, and that bug class
has already cost this project once.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import requests
from loguru import logger


from metatv.core.http_headers import STREAM_HTTP_HEADERS

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.connection_accountant import ConnectionAccountant
    from metatv.core.database import Database

#: A background poll (``kind="monitor"``) is the one holder a download may
#: evict: it is a catch-up check that can wait, while a download the user
#: asked for cannot. Downloads never evict playback or a recording.
DOWNLOAD_PREEMPTS: tuple[str, ...] = ("monitor",)

#: Bytes per read. Large enough that the loop is not syscall-bound, small enough
#: that a pause is felt immediately rather than one chunk later.
CHUNK_BYTES = 256 * 1024

#: How often the scheduler looks for work when idle.
POLL_SECONDS = 2.0

#: Terminal states — a row in one of these is never picked up again.
TERMINAL_STATES = ("completed", "failed")


@dataclass(frozen=True)
class DownloadProgress:
    """A snapshot for the UI. Plain data — never an ORM row across a thread."""

    id: str
    channel_id: str
    channel_name: str
    provider_id: str
    state: str
    downloaded_bytes: int
    total_bytes: Optional[int]
    dest_path: str
    error: Optional[str]
    paused_by_playback: bool

    @property
    def fraction(self) -> Optional[float]:
        """0.0-1.0, or None when the server never said how big the file is.

        None rather than 0.0 so a caller can render an indeterminate bar instead
        of one frozen at the left edge, which reads as broken.
        """
        if not self.total_bytes:
            return None
        return min(1.0, self.downloaded_bytes / self.total_bytes)


def library_dir(config) -> Path:
    """Where finished downloads live, expanded and created on demand."""
    raw = getattr(config, "download_dir", None) or "~/Videos/MetaTV"
    path = Path(os.path.expanduser(str(raw)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str, url: str, *, default_suffix: str = ".mp4") -> str:
    """A filename from the channel name, keeping the URL's extension.

    The name is the user's handle for the file, so it is what goes on disk —
    but a provider name can contain anything, including separators.

    Args:
        default_suffix: Used when the URL carries no extension. ``.mp4`` suits a
            VOD; a recording passes ``.ts``, because what it captures off a live
            channel IS an MPEG transport stream and calling it ``.mp4`` would be
            a lie players have to guess their way out of.
    """
    suffix = Path(url.split("?")[0]).suffix or default_suffix
    cleaned = "".join(c if (c.isalnum() or c in " ._-") else "_" for c in name).strip()
    cleaned = " ".join(cleaned.split()) or "download"
    return f"{cleaned[:120]}{suffix}"


class DownloadManager:
    """Queue, scheduler and worker for VOD downloads.

    One worker thread. Downloads are I/O-bound and the provider allows one
    connection anyway, so a pool would add contention without adding throughput.
    """

    def __init__(self, db: "Database", config,
                 accountant: "ConnectionAccountant",
                 on_change: Optional[Callable[[], None]] = None) -> None:
        """
        Args:
            db: Where the queue is persisted, so it survives a restart.
            config: Read for the library dir and the global pause.
            accountant: The ONE per-provider connection arbiter.
            on_change: Called (from the worker thread) whenever a row's state or
                progress moves, so a view can refresh. Qt callers must marshal
                to the main thread themselves — this module knows no Qt.
        """
        self._db = db
        self._config = config
        self._accountant = accountant
        self._on_change = on_change

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        #: id of the row the worker is transferring right now, if any.
        self._active_id: Optional[str] = None
        #: Set when the accountant evicts us mid-transfer.
        self._preempted = threading.Event()

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Begin scheduling. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="downloads", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the worker and leave the in-flight row resumable.

        Registered through ``_register_cleanable`` by the host, never by hand-
        editing closeEvent (CLAUDE.md: the cleanup registry).
        """
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    # ── queue API ───────────────────────────────────────────────────────────

    def enqueue(self, channel_id: str, provider_id: str, channel_name: str,
                source_url: str) -> Optional[str]:
        """Queue a VOD. Returns its id, or None if it is already queued or done.

        De-duplicated on channel_id: asking twice for the same film is a
        double-click, not a request for two copies.
        """
        from metatv.core.database import DownloadDB

        with self._db.session_scope() as session:
            existing = (session.query(DownloadDB)
                        .filter(DownloadDB.channel_id == channel_id)
                        .filter(DownloadDB.state != "failed")
                        .first())
            if existing is not None:
                return None
            position = (session.query(DownloadDB).count() or 0)
            row_id = str(uuid.uuid4())
            session.add(DownloadDB(
                id=row_id,
                channel_id=channel_id,
                provider_id=provider_id,
                channel_name=channel_name or channel_id,
                source_url=source_url,
                dest_path=str(library_dir(self._config)
                              / safe_filename(channel_name or channel_id, source_url)),
                state="queued",
                position=position,
            ))
        self._notify()
        self._wake.set()
        return row_id

    def pause(self, download_id: str) -> None:
        """Pause a download at the user's request (not a preemption)."""
        self._set_state(download_id, "paused", paused_by_playback=False)
        if self._active_id == download_id:
            self._preempted.set()          # stop the transfer loop promptly

    def resume(self, download_id: str) -> None:
        self._set_state(download_id, "queued", paused_by_playback=False)
        self._wake.set()

    def cancel(self, download_id: str) -> None:
        """Remove a download and its partial file."""
        from metatv.core.database import DownloadDB

        if self._active_id == download_id:
            self._preempted.set()
        with self._db.session_scope() as session:
            row = session.query(DownloadDB).filter_by(id=download_id).first()
            if row is None:
                return
            partial = Path(row.dest_path + ".part")
            session.delete(row)
        partial.unlink(missing_ok=True)
        self._notify()

    def progress(self) -> list[DownloadProgress]:
        """Every download, queue order. DTOs — never ORM rows across the seam."""
        from metatv.core.database import DownloadDB

        with self._db.session_scope(commit=False) as session:
            rows = (session.query(DownloadDB)
                    .order_by(DownloadDB.position, DownloadDB.created_at).all())
            return [DownloadProgress(
                id=r.id, channel_id=r.channel_id, channel_name=r.channel_name,
                provider_id=r.provider_id, state=r.state,
                downloaded_bytes=r.downloaded_bytes or 0, total_bytes=r.total_bytes,
                dest_path=r.dest_path, error=r.error,
                paused_by_playback=bool(r.paused_by_playback),
            ) for r in rows]

    # ── preemption ──────────────────────────────────────────────────────────

    def on_preempted(self, provider_id: str, holder_id: str, kind: str) -> None:
        """Called BY the accountant when playback takes our slot.

        Wired as its ``on_preempt`` callback. Marked ``paused_by_playback`` so
        the scheduler knows to resume it by itself later — a user pause must
        never come back on its own.
        """
        if kind != "download":
            return
        # Not "to playback": recordings preempt downloads as well, and the
        # accountant reports the EVICTED holder's kind, not the preemptor's.
        logger.info("download {} yielded its slot on {}", holder_id, provider_id)
        self._set_state(holder_id, "paused", paused_by_playback=True)
        if self._active_id == holder_id:
            self._preempted.set()

    # ── the worker ──────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self._step()
            except Exception:
                logger.exception("download scheduler step failed")
                worked = False
            if not worked:
                self._wake.wait(POLL_SECONDS)
                self._wake.clear()

    def _step(self) -> bool:
        """Do one unit of work. Returns True if something was transferred."""
        if getattr(self._config, "downloads_paused", False):
            return False
        self._resume_anything_playback_freed()
        row = self._next_runnable()
        if row is None:
            return False
        return self._transfer(row)

    def _next_runnable(self) -> Optional[dict]:
        """The first queued row whose provider has a slot we can take.

        Per-source: a busy provider is skipped rather than blocking the queue,
        so a download on B runs while A is playing.
        """
        from metatv.core.database import DownloadDB

        with self._db.session_scope(commit=False) as session:
            rows = (session.query(DownloadDB)
                    .filter(DownloadDB.state == "queued")
                    .order_by(DownloadDB.position, DownloadDB.created_at).all())
            candidates = [{
                "id": r.id, "provider_id": r.provider_id, "url": r.source_url,
                "dest": r.dest_path, "downloaded": r.downloaded_bytes or 0,
            } for r in rows]

        for row in candidates:
            granted = self._accountant.acquire(
                row["provider_id"], "download", row["id"],
                preempt_kinds=DOWNLOAD_PREEMPTS)
            if granted.granted:
                return row
        return None

    def _resume_anything_playback_freed(self) -> None:
        """Re-queue rows that playback paused, once its provider is free again."""
        from metatv.core.database import DownloadDB

        with self._db.session_scope() as session:
            rows = (session.query(DownloadDB)
                    .filter(DownloadDB.state == "paused")
                    .filter(DownloadDB.paused_by_playback.is_(True)).all())
            for row in rows:
                busy = any(h.kind != "download"
                           for h in self._accountant.holders(row.provider_id))
                if not busy:
                    row.state = "queued"
                    row.paused_by_playback = False

    def _transfer(self, row: dict) -> bool:
        """Stream one file to disk, resuming from whatever is already there."""
        download_id = row["id"]
        dest = Path(row["dest"])
        partial = Path(str(dest) + ".part")
        self._active_id = download_id
        self._preempted.clear()
        self._set_state(download_id, "running", paused_by_playback=False)

        try:
            have = partial.stat().st_size if partial.exists() else 0
            headers = dict(STREAM_HTTP_HEADERS)
            if have:
                # Resume. The server may ignore it (200 instead of 206), which
                # is handled below rather than assumed away.
                headers["Range"] = f"bytes={have}-"

            with requests.get(row["url"], headers=headers, stream=True,
                              timeout=(10, 60)) as response:
                response.raise_for_status()
                if have and response.status_code != 206:
                    # Range refused: start over rather than append to a file the
                    # server is sending from byte zero, which would corrupt it.
                    logger.info("download {}: server ignored Range, restarting", download_id)
                    have = 0
                    partial.unlink(missing_ok=True)

                total = self._content_total(response, have)
                self._set_total(download_id, total)

                mode = "ab" if have else "wb"
                written = have
                with open(partial, mode) as handle:
                    for chunk in response.iter_content(CHUNK_BYTES):
                        if self._stop.is_set() or self._preempted.is_set():
                            # Force: this byte count is what the resume starts
                            # from, so losing it to the throttle re-downloads
                            # up to a second of file.
                            self._flush_progress(download_id, written, force=True)
                            return False
                        if not chunk:
                            continue
                        handle.write(chunk)
                        written += len(chunk)
                        self._flush_progress(download_id, written)

            self._flush_progress(download_id, written, force=True)
            partial.replace(dest)
            self._set_state(download_id, "completed")
            logger.info("download complete: {}", dest)
            return True

        except Exception as exc:
            logger.exception("download {} failed", download_id)
            self._set_state(download_id, "failed", error=str(exc)[:500])
            return False
        finally:
            self._accountant.release(row["provider_id"], download_id)
            self._active_id = None

    @staticmethod
    def _content_total(response, already_have: int) -> Optional[int]:
        """Total file size, accounting for a partial response.

        ``Content-Length`` on a 206 is the length of the RANGE, not the file, so
        a resumed download would otherwise report a total smaller than what is
        already on disk and show as over 100%.
        """
        length = response.headers.get("Content-Length")
        if not length:
            return None
        try:
            size = int(length)
        except ValueError:
            return None
        return size + already_have if response.status_code == 206 else size

    # ── persistence helpers ─────────────────────────────────────────────────

    def _set_state(self, download_id: str, state: str, *,
                   paused_by_playback: Optional[bool] = None,
                   error: Optional[str] = None) -> None:
        from metatv.core.database import DownloadDB

        with self._db.session_scope() as session:
            row = session.query(DownloadDB).filter_by(id=download_id).first()
            if row is None:
                return
            row.state = state
            if paused_by_playback is not None:
                row.paused_by_playback = paused_by_playback
            if error is not None:
                row.error = error
        self._notify()

    def _set_total(self, download_id: str, total: Optional[int]) -> None:
        from metatv.core.database import DownloadDB

        if total is None:
            return
        with self._db.session_scope() as session:
            row = session.query(DownloadDB).filter_by(id=download_id).first()
            if row is not None:
                row.total_bytes = total

    def _flush_progress(self, download_id: str, written: int, *,
                        force: bool = False) -> None:
        """Persist byte progress, at most once a second unless *force*.

        Every chunk would be a write per 256 KB — on a 4 GB film that is 16,000
        commits competing for SQLite's single writer, which this project has
        already been bitten by once today.

        ``force`` exists because the throttle swallowed the FINAL write: a
        download whose last chunk arrived within a second of the previous flush
        finished on disk while the row still said 25%, so the UI showed a
        completed file a quarter done. Every exit from the transfer loop —
        finished, paused, preempted — flushes unconditionally.
        """
        from metatv.core.database import DownloadDB

        now = time.monotonic()
        last = getattr(self, "_last_flush", 0.0)
        if not force and now - last < 1.0:
            return
        self._last_flush = now
        with self._db.session_scope() as session:
            row = session.query(DownloadDB).filter_by(id=download_id).first()
            if row is not None:
                row.downloaded_bytes = written
        self._notify()

    def _notify(self) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change()
        except Exception:
            logger.exception("download on_change callback failed")
