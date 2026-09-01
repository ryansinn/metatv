"""Probe live event streams and record whether they carry a picture.

The reason this exists, in the owner's words: *"the data was unreliable and
inconsistent and there was hardly anything ever actually on those channels,
just dead air/black screens even when it said there was an event."* A listing
that promises a fight is worth nothing if the stream behind it is a black
rectangle, and the only way to know is to look.

**A probe spends the provider's one connection, so it is the lowest priority
thing in the app.** It never evicts anybody — not playback, not a download, not
a recording — and everything evicts it. That asymmetry is the whole scheduling
policy:

    playback / recording / download   take the slot from a probe
    a probe                           takes it from nobody, and waits

When something does take it, the in-flight probe is CANCELLED rather than
finished: ``probe_stream`` polls a stop event every 50 ms and kills ffmpeg, so
a Play press waits milliseconds rather than the ~18 s a full sample plus
timeout would cost. A cancelled probe records nothing — see below.

**Only a verdict about the PICTURE is evidence.** ``refused`` (the connection
was declined), ``gone`` (the host was not there), ``unknown`` (ffmpeg missing)
and ``cancelled`` (we gave the stream back) all say the probe never saw the
picture. Counting any of them would let ordinary viewing accumulate a dead
streak against a channel that is perfectly fine — and ``hide_dead_events``
would then hide it.

**Only what is on now is worth probing.** A fixture that starts in six hours
has nothing behind it yet, and a 24/7 channel is a different question from "is
this event actually streaming".
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import TYPE_CHECKING, Optional

from loguru import logger

from metatv.core.epg_utils import now_utc
from metatv.core.stream_probe import (FAILED_VERDICTS, LIVE, ProbeSettings,
                                      ffmpeg_available, probe_stream)

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.connection_accountant import ConnectionAccountant
    from metatv.core.database import Database

#: A probe evicts nobody. Stated as a constant so the asymmetry is greppable
#: rather than implied by an omitted argument.
PROBE_PREEMPTS: tuple[str, ...] = ()

#: How long a verdict stands before the channel is worth re-checking.
RECHECK_AFTER = timedelta(minutes=30)

#: How long after its start time an event is still "on" and worth probing.
LIVE_WINDOW = timedelta(hours=4)

#: Idle poll. Slow on purpose — nothing here is urgent, and every wake-up is a
#: chance to take a connection the user wants.
POLL_SECONDS = 20.0


class SignalCheckManager:
    """Runs probes one at a time, lowest priority, and records what they saw.

    One worker thread. Probes are serialised by the connection budget anyway —
    a second thread could only queue behind the first — and serialising them
    here keeps the "one probe in flight" invariant the cancel path relies on.
    """

    def __init__(self, db: "Database", config, accountant: "ConnectionAccountant"):
        self.db = db
        self.config = config
        self.accountant = accountant
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        #: Set when something takes our slot; ``probe_stream`` polls it and
        #: kills ffmpeg. Replaced per probe so a stale cancel cannot kill the
        #: next one.
        self._cancel = threading.Event()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the worker. Idempotent, and a no-op without ffmpeg."""
        if self._thread and self._thread.is_alive():
            return
        if not getattr(self.config, "signal_check_enabled", False):
            logger.debug("signal check: disabled — see Config.signal_check_enabled")
            return
        if not ffmpeg_available():
            logger.info("signal check: ffmpeg not installed — probing disabled")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="signal_check", daemon=True)
        self._thread.start()
        logger.debug("Signal check worker started")

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop, cancelling any probe in flight."""
        self._stop.set()
        self._cancel.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def on_preempted(self, provider_id: str, holder_id: str, kind: str) -> None:
        """Give the connection back immediately.

        Wired to the accountant's preempt callback. Killing the ffmpeg process
        is what makes a probe acceptable at all on a one-connection account.
        """
        if not holder_id.startswith("probe:"):
            return
        logger.debug("signal check: yielding {} on {}", holder_id, provider_id)
        self._cancel.set()

    # ── the worker ───────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                did_work = self._step()
            except Exception:                        # pragma: no cover - guard
                logger.exception("Signal check step failed")
                did_work = False
            if not did_work:
                self._wake.wait(POLL_SECONDS)
                self._wake.clear()

    def _step(self) -> bool:
        """Probe one channel. False when there is nothing to do."""
        row = self._next_candidate()
        if row is None:
            return False
        return self._probe(row)

    def _next_candidate(self) -> "dict | None":
        """The oldest-checked event that is on the air right now.

        Filtered in Python on the live-window test for the same reason the
        recorder is: the window is a comparison against a moving clock, not a
        column. The candidate set is small — events currently airing — not the
        whole catalogue.
        """
        from metatv.core.database import ChannelDB

        now = now_utc()
        cutoff = now - RECHECK_AFTER
        with self.db.session_scope() as session:
            rows = (
                session.query(ChannelDB)
                .filter(
                    ChannelDB.event_start_time.isnot(None),
                    ChannelDB.event_start_time <= now,
                    ChannelDB.event_start_time > now - LIVE_WINDOW,
                    (ChannelDB.signal_checked_at.is_(None)
                     | (ChannelDB.signal_checked_at < cutoff)),
                )
                .order_by(ChannelDB.signal_checked_at.asc().nulls_first())
                .limit(1).all()
            )
            if not rows:
                return None
            r = rows[0]
            return {"id": r.id, "provider_id": r.provider_id, "name": r.name,
                    "url": r.stream_url, "streak": r.signal_dead_streak or 0}

    def _probe(self, row: dict) -> bool:
        """Take the slot if it is free, probe, record. False if we could not."""
        holder = f"probe:{row['id']}"
        result = self.accountant.acquire(
            row["provider_id"], "probe", holder, preempt_kinds=PROBE_PREEMPTS)
        if not result.granted:
            return False                 # somebody is using the connection

        self._cancel = threading.Event()
        try:
            verdict = probe_stream(
                row["url"], ProbeSettings.from_config(self.config),
                cancel=self._cancel)
        finally:
            self.accountant.release(row["provider_id"], holder)

        self._record(row, verdict)
        return True

    def _record(self, row: dict, result) -> None:
        """Store the verdict, and move the streak ONLY on picture evidence.

        An inconclusive verdict still updates ``signal_checked_at`` — otherwise
        a channel whose provider keeps refusing would be retried every twenty
        seconds forever — but it must not touch the streak.
        """
        from metatv.core.database import ChannelDB

        with self.db.session_scope() as session:
            ch = session.get(ChannelDB, row["id"])
            if ch is None:
                return
            ch.signal_verdict = result.verdict
            ch.signal_checked_at = now_utc()
            if result.verdict == LIVE:
                ch.signal_dead_streak = 0
            elif result.verdict in FAILED_VERDICTS:
                ch.signal_dead_streak = (ch.signal_dead_streak or 0) + 1
        logger.debug("signal check: {} -> {} ({})",
                     row["name"][:50], result.verdict, result.detail)
