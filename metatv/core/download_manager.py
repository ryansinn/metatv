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
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
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

#: Bytes between free-space checks inside the transfer loop. A statvfs per
#: 256 KB chunk would be thousands of syscalls a second for a number that moves
#: slowly; per 64 MB it is a few a minute and still catches the floor well
#: before the disk is actually full.
_SPACE_CHECK_BYTES = 64 * 1024 * 1024

#: Terminal states — a row in one of these is never picked up again.
TERMINAL_STATES = ("completed", "failed")

#: How far back the transfer-rate ring looks. Long enough to smooth out a
#: single slow/fast chunk, short enough that the reading reflects NOW rather
#: than an average since the download started (which would recover slowly
#: after a network stall).
_RATE_WINDOW_SECONDS = 5.0


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
    #: Why this row is not transferring right now, or None when it needs no
    #: explanation (running, or a terminal row). See ``DownloadManager._reason_for``.
    reason: Optional[str] = None
    #: Recent throughput, or None when there are not yet enough samples (or the
    #: row is not running). Derived from an in-memory ring, never stored.
    bytes_per_second: Optional[float] = None
    #: Seconds remaining at the current rate, or None when the total is
    #: unknown or the rate cannot yet be measured.
    eta_seconds: Optional[int] = None
    #: When the row last changed state/progress (UTC-naive) — the completion
    #: time a history heading buckets a finished row by.
    updated_at: Optional[datetime] = None
    #: The provider's configured name, denormalized here the same way
    #: ``channel_name`` is, so a caller never needs a second DB round trip to
    #: label a connection-gate line.
    provider_name: str = ""
    #: A history-group "forget" set this instead of deleting the row (see
    #: ``clear_history_group``) — the Downloaded scope keeps reading
    #: ``state``, so a cleared row still counts while its file exists. The
    #: section's History groups skip a row with this set; the queue/"In
    #: progress" list never contains one (only terminal rows are ever hidden).
    history_cleared: bool = False

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


def destination_for(session, config, channel_id: str, channel_name: str,
                    source_url: str) -> Path:
    """The absolute path this download should be written to.

    Reads the channel's stored ``detected_*`` fields through
    ``download_naming.facts_from_channel``. A channel row that cannot be found
    — a queue entry outliving its channel — falls back to the flat name built
    from what the caller already handed us, rather than failing the enqueue.

    Takes the caller's session rather than opening one: ``enqueue`` is already
    inside a write transaction, and a second connection here would be a second
    writer against a single-writer database for no reason.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.download_naming import (
        LAYOUT_TREE, MediaFacts, facts_from_channel, relative_path)

    suffix = Path(source_url.split("?")[0]).suffix or ".mp4"
    channel = session.query(ChannelDB).filter(ChannelDB.id == channel_id).first()
    facts = (facts_from_channel(channel) if channel is not None
             else MediaFacts(name=channel_name))
    layout = getattr(config, "download_layout", LAYOUT_TREE) or LAYOUT_TREE
    return library_dir(config) / relative_path(facts, suffix, layout)


class DownloadManager:
    """Queue, scheduler and worker for VOD downloads.

    One worker thread. Downloads are I/O-bound and the provider allows one
    connection anyway, so a pool would add contention without adding throughput.
    """

    def __init__(self, db: "Database", config,
                 accountant: "ConnectionAccountant",
                 on_change: Optional[Callable[[], None]] = None, *,
                 clock: "Optional[Callable[[], float]]" = None) -> None:
        """
        Args:
            db: Where the queue is persisted, so it survives a restart.
            config: Read for the library dir and the global pause.
            accountant: The ONE per-provider connection arbiter.
            on_change: Called (from the worker thread) whenever a row's state or
                progress moves, so a view can refresh. Qt callers must marshal
                to the main thread themselves — this module knows no Qt.
            clock: Injected so a test can drive the transfer-rate ring without
                sleeping — never read the real clock underneath a caller-
                supplied one (this bug has shipped from this codebase before).
        """
        self._db = db
        self._config = config
        self._accountant = accountant
        self._on_change = on_change
        self._clock = clock or time.monotonic

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        #: id of the row the worker is transferring right now, if any.
        self._active_id: Optional[str] = None
        #: Set when the accountant evicts us mid-transfer.
        self._preempted = threading.Event()
        #: download_id -> recent (monotonic_ts, bytes_written) samples, for the
        #: UI's speed/ETA readout. Guarded by ``_lock`` — written by the worker
        #: thread inside ``_transfer``, read by ``progress()`` from whichever
        #: thread the caller (the UI's refresh tick) runs on.
        self._rate_samples: dict[str, "deque[tuple[float, int]]"] = {}

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
                dest_path=str(destination_for(
                    session, self._config, channel_id,
                    channel_name or channel_id, source_url)),
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

    # ── history (terminal rows) ─────────────────────────────────────────────
    #
    # A download's ROW is what the Downloaded scope (channel_downloads.
    # predicate) reads too — it derives "downloaded" from state=="completed"
    # plus the file existing on disk, on this same table. So clearing a
    # group must HIDE rows from the section's history, never delete them:
    # deleting would make a still-present file vanish from the Downloaded
    # scope, which is exactly the bug this shape exists to avoid. Mirrors
    # ``channel_history.clear_history_in_range``/``restore_history_snapshot``
    # (same half-open ``[not_before, not_after)`` window, same snapshot-then-
    # Undo shape) with a flag flip instead of a delete/re-insert. The FILE on
    # disk, the row itself, and the Downloaded scope are never touched by
    # either method — only ``history_cleared``.

    #: Columns snapshotted (and restored) by a group clear/Undo — everything
    #: needed to reconstruct an equivalent row, in ``DownloadDB.__init__`` order.
    _SNAPSHOT_COLUMNS: tuple[str, ...] = (
        "id", "channel_id", "provider_id", "channel_name", "source_url",
        "dest_path", "state", "paused_by_playback", "total_bytes",
        "downloaded_bytes", "error", "position", "created_at", "updated_at",
    )

    def clear_history_group(
        self, not_before: Optional[datetime], not_after: Optional[datetime]
    ) -> "tuple[int, list[dict]]":
        """Hide terminal (completed/failed) rows whose ``updated_at`` falls
        inside a half-open UTC-naive window — one history heading's "forget".

        Args:
            not_before: Inclusive lower bound (UTC-naive), or None for
                unbounded. Callers convert a LOCAL bucket boundary via
                ``epg_utils.to_utc_naive`` before calling this — the same
                UTC-naive frame ``updated_at`` is stored in.
            not_after: Exclusive upper bound (UTC-naive), or None for
                unbounded. Passing ``(None, None)`` hides every terminal row —
                the overflow's "Clear download history" bulk action.

        Returns:
            ``(count, snapshot)``: how many rows were hidden, and a plain-dict
            snapshot of each — never ORM rows — so the caller can offer Undo
            via :meth:`restore_history_snapshot`. Already-hidden rows are
            skipped, so re-clearing an emptied group reports 0.
        """
        from metatv.core.database import DownloadDB

        with self._db.session_scope() as session:
            query = session.query(DownloadDB).filter(
                DownloadDB.state.in_(TERMINAL_STATES),
                DownloadDB.history_cleared.is_(False))
            if not_before is not None:
                query = query.filter(DownloadDB.updated_at >= not_before)
            if not_after is not None:
                query = query.filter(DownloadDB.updated_at < not_after)
            rows = query.all()
            snapshot = [
                {col: getattr(row, col) for col in self._SNAPSHOT_COLUMNS}
                for row in rows
            ]
            count = len(rows)
            for row in rows:
                row.history_cleared = True
        self._notify()
        return count, snapshot

    def restore_history_snapshot(self, snapshot: "list[dict]") -> int:
        """Undo a group clear — un-hide rows nobody has re-queued since.

        Skips any id no longer present (the same download was cancelled out
        from under the snapshot) rather than raising — Undo restores
        everything else it safely can.

        Args:
            snapshot: As returned by :meth:`clear_history_group`.

        Returns:
            How many rows were actually restored.
        """
        from metatv.core.database import DownloadDB

        restored = 0
        with self._db.session_scope() as session:
            for data in snapshot:
                row = session.query(DownloadDB).filter_by(id=data["id"]).first()
                if row is None:
                    continue
                row.history_cleared = False
                restored += 1
        self._notify()
        logger.info("Restored {} download(s) from a history-clear snapshot", restored)
        return restored

    def connection_gate_lines(self) -> list[str]:
        """One line per provider currently gating a queued/running download.

        The section-header counterpart to a row's own ``reason``: "<provider>
        · 1 of 1 connections in use" for every provider with a non-unlimited
        capacity that is actually full right now. Empty when nothing is
        waiting on a connection.
        """
        from metatv.core.database import DownloadDB, ProviderDB

        with self._db.session_scope(commit=False) as session:
            provider_ids = {
                r[0] for r in session.query(DownloadDB.provider_id)
                .filter(DownloadDB.state.in_(("queued", "running"))).all()
            }
            if not provider_ids:
                return []
            names = {
                p.id: p.name for p in
                session.query(ProviderDB.id, ProviderDB.name)
                .filter(ProviderDB.id.in_(provider_ids)).all()
            }

        lines = []
        for provider_id in sorted(provider_ids):
            cap = self._accountant.capacity(provider_id)
            if not cap:
                continue  # unlimited never gates
            in_use = self._accountant.in_use(provider_id)
            if in_use <= 0:
                continue  # nothing is actually holding this source right now
            name = names.get(provider_id, provider_id)
            lines.append(f"{name} · {in_use} of {cap} connections in use")
        return lines

    def progress(self) -> list[DownloadProgress]:
        """Every download, queue order. DTOs — never ORM rows across the seam."""
        from metatv.core.database import DownloadDB, ProviderDB

        with self._db.session_scope(commit=False) as session:
            rows = (session.query(DownloadDB)
                    .order_by(DownloadDB.position, DownloadDB.created_at).all())
            provider_ids = {r.provider_id for r in rows}
            names = ({} if not provider_ids else {
                p.id: p.name for p in
                session.query(ProviderDB.id, ProviderDB.name)
                .filter(ProviderDB.id.in_(provider_ids)).all()
            })
            out = []
            for r in rows:
                rate = eta = None
                if r.state == "running":
                    rate, eta = self._rate_and_eta(
                        r.id, r.total_bytes, r.downloaded_bytes or 0)
                out.append(DownloadProgress(
                    id=r.id, channel_id=r.channel_id, channel_name=r.channel_name,
                    provider_id=r.provider_id, state=r.state,
                    downloaded_bytes=r.downloaded_bytes or 0, total_bytes=r.total_bytes,
                    dest_path=r.dest_path, error=r.error,
                    paused_by_playback=bool(r.paused_by_playback),
                    reason=self._reason_for(r),
                    bytes_per_second=rate, eta_seconds=eta,
                    updated_at=r.updated_at,
                    provider_name=names.get(r.provider_id, ""),
                    history_cleared=bool(r.history_cleared),
                ))
            return out

    def _reason_for(self, r) -> Optional[str]:
        """Why *r* is not transferring right now, or None (running, terminal).

        One reader for every non-running state, so "why is this row not
        moving" is answered the same way whether the row is queued, paused, or
        failed — never re-derived per call site.
        """
        if r.state == "failed":
            return r.error
        if r.state == "paused":
            if r.paused_by_playback:
                return ("Paused automatically — you started watching "
                        "something. Resumes when playback stops.")
            if getattr(self._config, "downloads_paused", False):
                return "Paused — downloads are paused"
            return "Paused"
        if r.state == "queued":
            if getattr(self._config, "downloads_paused", False):
                return "Paused — downloads are paused"
            cap = self._accountant.capacity(r.provider_id)
            in_use = self._accountant.in_use(r.provider_id)
            if cap and in_use >= cap:
                conn = "connection" if cap == 1 else "connections"
                return f"Queued — this source allows {cap} {conn} and it is in use."
        return None

    def _rate_and_eta(
        self, download_id: str, total_bytes: Optional[int], downloaded_bytes: int
    ) -> "tuple[Optional[float], Optional[int]]":
        """Recent bytes/second and, when the total is known, seconds remaining.

        Derived from the in-memory sample ring rather than from the download's
        whole lifetime average, which recovers slowly after a stall and reports
        a speed that has nothing to do with what is happening right now.
        """
        with self._lock:
            samples = list(self._rate_samples.get(download_id, ()))
        if len(samples) < 2:
            return None, None
        (t0, b0), (t1, b1) = samples[0], samples[-1]
        elapsed = t1 - t0
        if elapsed <= 0:
            return None, None
        rate = (b1 - b0) / elapsed
        if rate <= 0:
            return None, None
        eta = None
        if total_bytes:
            remaining = max(0, total_bytes - downloaded_bytes)
            eta = int(remaining / rate)
        return rate, eta

    def _record_rate_sample(self, download_id: str, written: int) -> None:
        """Append one (now, bytes) sample and drop anything older than the window."""
        now = self._clock()
        with self._lock:
            dq = self._rate_samples.setdefault(download_id, deque())
            dq.append((now, written))
            while dq and now - dq[0][0] > _RATE_WINDOW_SECONDS:
                dq.popleft()

    def _clear_rate_samples(self, download_id: str) -> None:
        with self._lock:
            self._rate_samples.pop(download_id, None)

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

    def _space_shortfall(self, need_bytes: Optional[int] = None) -> Optional[str]:
        """Why the disk cannot take (more of) this download, or None if it can.

        Settled: a free-space FLOOR with a policy for what happens when it is
        hit — stop immediately, or finish the current download and then stop.
        The second is only honoured when the remaining bytes actually fit
        inside the floor, *"so it is a real check, not a preference — if it
        does not fit, it stops immediately whatever the setting says, and the
        row says so."* Returning the reason rather than a bool is what lets the
        row say it.

        Args:
            need_bytes: Bytes still to write for the download in flight, or
                None when asking whether a NEW one may start.
        """
        floor_gb = float(getattr(self._config, "download_free_space_floor_gb", 0) or 0)
        if floor_gb <= 0:
            return None
        floor = int(floor_gb * 1024 ** 3)

        try:
            free = shutil.disk_usage(library_dir(self._config)).free
        except OSError:
            # An unreadable destination is the storage layer's problem to
            # report, not a reason to refuse every download.
            logger.exception("download: could not read free space")
            return None

        headroom = free - floor
        if headroom >= 0 and need_bytes is None:
            return None

        human_floor = f"{floor_gb:g} GB"
        if need_bytes is None:
            return (f"Not enough disk space — free space is already below your "
                    f"{human_floor} floor.")

        policy = getattr(self._config, "download_space_policy", "finish_current")
        if policy == "finish_current" and need_bytes <= headroom:
            return None
        if policy == "finish_current":
            return (f"Stopped — finishing this download would take free space "
                    f"below your {human_floor} floor.")
        return f"Stopped — free space reached your {human_floor} floor."

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

        shortfall = self._space_shortfall()
        if shortfall is not None and candidates:
            # Report it on the row that WOULD have started, so the queue
            # explains itself instead of looking stalled.
            self._set_state(candidates[0]["id"], "failed", error=shortfall)
            logger.warning("download: {}", shortfall)
            return None

        for row in candidates:
            # DL-7: acquire() self-heals a dead playback holder on its own via
            # the accountant's registered liveness probe (see
            # ConnectionAccountant.set_liveness_probe / RECONCILE_GRACE_S) —
            # this loop stays a plain poll; never add a timer here to chase
            # the same problem a second way.
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
        self._clear_rate_samples(download_id)
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
                last_space_check = have
                # The tree layout puts the file inside Movies/ or
                # Series/Show/Season NN/, none of which exist until something
                # is filed there. library_dir() only makes the root.
                partial.parent.mkdir(parents=True, exist_ok=True)
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
                        self._record_rate_sample(download_id, written)
                        self._flush_progress(download_id, written)

                        # Free space is checked against the DISK, not against
                        # what we have written, because anything else on the
                        # machine is consuming it too. Once per ~64 MB: often
                        # enough that the floor means something, rare enough
                        # that a statvfs is not in the byte loop.
                        if written - last_space_check >= _SPACE_CHECK_BYTES:
                            last_space_check = written
                            remaining = (total - written) if total else None
                            shortfall = self._space_shortfall(remaining or 0)
                            if shortfall is not None:
                                self._flush_progress(
                                    download_id, written, force=True)
                                self._set_state(download_id, "failed",
                                                error=shortfall)
                                logger.warning("download {}: {}",
                                               download_id, shortfall)
                                return False

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
            self._clear_rate_samples(download_id)

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
