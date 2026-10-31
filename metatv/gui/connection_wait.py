"""Wait for a source to free a connection, then start the title (Source Analytics Q7).

A source at its connection limit refuses a play with HTTP 458/509. When MetaTV
itself holds nothing from that source, the slot is almost always a stream that
just ended and that the source is still counting — the owner timed TREX holding
one for ~22 minutes. Instead of a dead-end "Stream did not start", the user gets
a wait: the account endpoint (which uses no stream slot) is checked every
:data:`POLL_MS`, the title starts on its own when ``active_cons`` drops below
``max_connections``, and the wait is recorded so the Analytics tab can say how
long this source usually takes to free up.

One wait at a time per host. Starting any other play cancels it (``arm`` calls
:func:`cancel`), and so does the notification's Cancel button. The account
check reuses ``FetchAccountInfoThread`` — the editor's own fetch path — so URL
cycling and its outcome recording stay in one place.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from PyQt6.QtCore import QObject, QTimer
from loguru import logger

from metatv.core.repositories import RepositoryFactory

#: How often the account endpoint is checked while waiting (owner, Q7: 30 s).
POLL_MS = 30_000
#: Past this the source is not merely counting an ended stream; stop waiting.
GIVE_UP_AFTER_S = 60 * 60

#: Cancelled waits whose account check is still out: a QThread whose Python
#: wrapper is collected while it runs takes the process down, so the wait that
#: owns it stays referenced until the check returns.
_RETIRED: set = set()


def minutes_text(seconds: float) -> str:
    """A wait as people say it: "under a minute", "22 min"."""
    return "under a minute" if seconds < 60 else f"{round(seconds / 60)} min"


class _Wait(QObject):
    """One wait: the poll timer, the in-flight account check, the notification."""

    def __init__(self, host: Any, attempt: Any, source: str) -> None:
        super().__init__()
        self.host, self.attempt, self.source = host, attempt, source
        self.refused_at = datetime.utcnow()
        self.started = time.monotonic()
        self.notif_id: str | None = None
        self._thread = None
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.poll)

    def poll(self) -> None:
        if self._thread is not None:            # the previous check is still out
            return
        if time.monotonic() - self.started > GIVE_UP_AFTER_S:
            self._give_up()
            return
        from metatv.gui.provider_editor import FetchAccountInfoThread
        try:
            with self.host.db.session_scope(commit=False) as session:
                repos = RepositoryFactory(session)
                provider = repos.providers.to_model(repos.providers.get_by_id(self.attempt.provider_id))
        except Exception:
            logger.opt(exception=True).warning("connection wait: could not load the source")
            return
        self._thread = FetchAccountInfoThread(provider)
        self._thread.finished.connect(self.on_checked)
        self._thread.start()

    def on_checked(self, success: bool, info: Any) -> None:
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.wait(2000)                   # run() has emitted; let it return
        _RETIRED.discard(self)
        if self.host.__dict__.get("_connection_wait") is not self:   # cancelled meanwhile
            return
        if not success or not isinstance(info, dict):
            logger.info("connection wait: account check failed ({}); trying again", info)
            return
        in_use, limit = info.get("active_cons", 0), info.get("max_connections", 1)
        logger.info("connection wait on {}: {} of {} connections in use", self.source, in_use, limit)
        if in_use < limit:
            self._freed()

    def _freed(self) -> None:
        cancel(self.host)
        seconds = int((datetime.utcnow() - self.refused_at).total_seconds())
        pid, refused_at = self.attempt.provider_id, self.refused_at
        try:
            self.host._run_query(lambda repos: repos.playback_events.record_hold(pid, refused_at, seconds),
                                 lambda _r: None, commit=True,
                                 on_error=lambda e: logger.warning("could not record the hold: {}", e))
        except Exception:
            logger.exception("could not record the connection hold")
        self.host.status(f"{self.source} freed a connection after {minutes_text(seconds)} — "
                         f"starting {self.attempt.channel_name}", ms=6000)
        self.host.play_channel_by_id(self.attempt.channel_id)

    def _give_up(self) -> None:
        cancel(self.host)
        self.host.notification_manager.show(
            title="Stopped waiting for a connection",
            message=f"{self.source} still had every connection in use after "
                    f"{minutes_text(GIVE_UP_AFTER_S)}. Try {self.attempt.channel_name} again later.",
            type="warning", auto_dismiss_ms=10000)


def begin(host: Any, attempt: Any) -> bool:
    """Start waiting for a free connection on *attempt*'s source. Returns whether it did.

    Declines (and the caller shows its usual failure toast) for a play with no
    channel identity, and when MetaTV is itself streaming from the source — then
    the slot is ours, and waiting would wait on ourselves.
    """
    if attempt is None or not attempt.provider_id or not attempt.record_failure:
        return False
    pid = attempt.provider_id
    try:
        key = host.player_manager.resolve_key(pid)
        ours = [h for h in host.player_manager.connection_accountant.holders(pid) if h.holder_id != key]
    except Exception:
        logger.opt(exception=True).debug("connection wait: could not read our own connections")
        return False
    if ours:
        return False
    cancel(host)
    source = host._provider_display_name(pid)
    wait = _Wait(host, attempt, source)
    host._connection_wait = wait
    wait.notif_id = host.notification_manager.show(
        title=f"Waiting for a connection on {source}",
        message=f"{source} has every connection in use — usually a stream that just ended "
                f"and is still being counted. Checking every {POLL_MS // 1000} s; "
                f"{attempt.channel_name} starts as soon as one frees up.",
        type="info", dismissible=False, actions=[("Cancel", lambda: cancel(host))])
    host.status(f"Waiting for a free connection on {source} to start {attempt.channel_name}…", ms=0)
    wait.timer.start()
    return True


def cancel(host: Any) -> None:
    """Stop the host's wait, if any, and take its notification down."""
    wait = host.__dict__.pop("_connection_wait", None)
    if wait is None:
        return
    wait.timer.stop()
    if wait._thread is not None:
        _RETIRED.add(wait)
    if wait.notif_id is not None:
        host.notification_manager.dismiss(wait.notif_id)
