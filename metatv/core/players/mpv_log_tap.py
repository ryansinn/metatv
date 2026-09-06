"""Surface mpv's own stderr into our log — it was silently discarded.

PLAY-10 (2026-09-05): both mpv launch sites in ``mpv.py`` ran with
``stderr=subprocess.DEVNULL``, so none of mpv's own diagnostics — the exact
"HTTP error 500", "Will reconnect at 0 in Ns" lines ffmpeg emits during the
same-provider-switch retry backoff this slice fixes — ever reached the app
log. A user report ("it's just hanging") had a complete picture sitting in a
process nobody was reading.

:func:`start_log_tap` is the one place a launched mpv process's stderr is
piped and read; both Popen sites in ``mpv.py`` call it right after launch,
each passing ``--msg-level=all=warn`` on the command line first so the volume
stays small — see the option's exact choice in the PR body.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import NamedTuple

from loguru import logger


class ExitRecord(NamedTuple):
    """How an mpv process ended — the evidence the playback watchdog lacked.

    An mpv that exits while still OPENING (loaded a path, never got demuxer
    data) looks exactly like a user closing a just-loaded window unless the
    reason is known: mpv prints ``Exiting... (Quit)`` for a user close and
    ``Exiting... (End of file)`` / ``(Errors when loading file)`` for a stream
    that gave it nothing — at ``cplayer=info``, which is why the launch sites
    raise that one domain above ``all=warn``. Owner log 2026-09-06 10:11: a
    cold play on a one-connection source died this way inside 30 s with no
    warning line, no report, and no retry.
    """
    reason: str | None
    returncode: int | None
    elapsed_s: float


#: ``Exiting... (End of file)`` → ``End of file``.
_EXIT_RE = re.compile(r"Exiting\.\.\. \((?P<reason>[^)]*)\)")

#: Reasons that mean the STREAM ended the process, not the user.
STREAM_EXIT_REASONS: frozenset[str] = frozenset({
    "End of file", "Errors when loading file", "Some errors happened",
})

_exits: dict[str, ExitRecord] = {}
_exits_lock = threading.Lock()


def last_exit(key: str) -> "ExitRecord | None":
    """The recorded end of the last process launched under *key*, if any."""
    with _exits_lock:
        return _exits.get(key)


def clear_exit(key: str) -> None:
    """Forget *key*'s previous exit — called by the launch sites before Popen."""
    with _exits_lock:
        _exits.pop(key, None)

#: Substrings (case-insensitive) that escalate a tapped line to WARNING —
#: mpv/ffmpeg's own trouble signals, not routine playback chatter. Deliberately
#: overlapping ("error" already covers "HTTP error"): each is named because the
#: PR that added this enumerated them, not because they're mutually exclusive.
_WARNING_MARKERS = (
    "http error", "failed to open", "connection refused", "reconnect", "error",
)


def start_log_tap(proc: "subprocess.Popen", key: str) -> threading.Thread:
    """Start a daemon thread that logs *proc*'s stderr, tagged with *key*.

    Never joined by the caller: shutdown must not wait on a stream that may
    still be reconnecting. The thread exits on its own once ``proc.stderr``
    hits EOF (the process died or closed the pipe).

    Args:
        proc: The launched mpv process. ``proc.stderr`` must be a readable
            byte stream (the caller passes ``stderr=subprocess.PIPE``, or a
            test double such as ``io.BytesIO``) — anything whose ``readline()``
            doesn't yield ``bytes`` (e.g. an unconfigured ``MagicMock`` process
            double in a test) ends the pump immediately rather than spinning:
            a real pipe's EOF sentinel (``b""``) is itself ``bytes``, so this
            never fires against genuine mpv output.
        key: Instance key this process belongs to — or, for the standalone
            no-IPC launch that has no instance key, the play's title. Included
            in every log line so a multi-window session's mpv chatter is
            traceable to the process that produced it.

    Returns:
        The started daemon thread.
    """
    started = time.monotonic()
    reason: str | None = None

    def _record_exit() -> None:
        poll = getattr(proc, "poll", None)
        rc = poll() if callable(poll) else None
        rec = ExitRecord(reason, rc if isinstance(rc, int) else None,
                         round(time.monotonic() - started, 1))
        with _exits_lock:
            _exits[key] = rec
        logger.info("mpv[{}] exited rc={} after {}s ({})", key, rec.returncode,
                    rec.elapsed_s, reason or "no exit reason seen")

    def _pump() -> None:
        nonlocal reason
        try:
            stderr = proc.stderr
            if stderr is None:
                return
            for raw_line in iter(stderr.readline, b""):
                if not isinstance(raw_line, (bytes, bytearray)):
                    break   # not a real byte stream — see Args note above
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                m = _EXIT_RE.search(line)
                if m:
                    reason = m.group("reason")
                if any(marker in line.lower() for marker in _WARNING_MARKERS):
                    logger.warning("mpv[{}] {}", key, line)
                else:
                    logger.debug("mpv[{}] {}", key, line)
            _record_exit()
        except Exception:
            logger.exception("mpv log tap for [{}] crashed", key)

    thread = threading.Thread(target=_pump, name=f"mpv-log-tap-{key}", daemon=True)
    thread.start()
    return thread
