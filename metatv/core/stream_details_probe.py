"""Measure a stream without playing it for the user ("Get details", PLAYED-2).

Runs a short, invisible mpv (no video or audio output) against the stream,
reads the same properties a real play is captured from, and returns the same
record — :func:`metatv.core.stream_info.parse_mpv` — so a probed channel and a
played one are described identically. mpv rather than ffmpeg: mpv is
MetaTV's one hard dependency, ffmpeg is optional.

Blocking: it holds the provider's connection for its whole run. Call it from
a worker, and only after the connection accountant has granted a slot.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import uuid

from loguru import logger

from metatv.core.players.mpv import _base_stream_args, _resolve_mpv_binary
from metatv.core.stream_info import MPV_PROPS, parse_mpv

#: How long to keep reading after the tracks appear, so mpv's bitrate
#: estimate has something to average.
SETTLE_SECONDS = 6.0
#: Give up if the stream has produced no tracks by then.
OPEN_TIMEOUT_SECONDS = 20.0


class _Ipc:
    """A minimal JSON-IPC client for one mpv socket."""

    def __init__(self, path: str):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(3.0)
        self.sock.connect(path)
        self.buf = b""
        self.next_id = 0

    def get(self, name: str):
        self.next_id += 1
        rid = self.next_id
        self.sock.sendall(json.dumps(
            {"command": ["get_property", name], "request_id": rid}).encode() + b"\n")
        while True:
            while b"\n" not in self.buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("mpv closed the socket")
                self.buf += chunk
            line, self.buf = self.buf.split(b"\n", 1)
            msg = json.loads(line)
            if msg.get("request_id") == rid:        # skip unsolicited events
                return msg.get("data") if msg.get("error") == "success" else None

    def quit(self) -> None:
        try:
            self.sock.sendall(b'{"command": ["quit"]}\n')
        except OSError:
            pass
        self.sock.close()


def _mpv_error(proc: subprocess.Popen) -> str:
    """mpv's own last error line, for the log ("" while it is still running)."""
    if proc.poll() is None or proc.stderr is None:
        return ""
    lines = [ln.strip() for ln in proc.stderr.read().splitlines() if ln.strip()]
    return f": {lines[-1]}" if lines else ""


def probe_details(url: str, *, cancel: "threading.Event | None" = None) -> "dict | None":
    """Open *url* in a headless mpv and return its stream record.

    Args:
        url: The playable stream URL.
        cancel: Set to abandon the probe early (mpv is killed).

    Returns:
        A :func:`parse_mpv` record, or None when the stream never produced
        tracks (refused, offline, timed out, cancelled).
    """
    sock_path = os.path.join(tempfile.gettempdir(), f"mpv-metatv-probe-{uuid.uuid4().hex[:8]}")
    cmd = [_resolve_mpv_binary(), "--no-config", "--idle=no", "--vo=null", "--ao=null",
           "--force-window=no", "--msg-level=all=error", f"--input-ipc-server={sock_path}",
           *_base_stream_args(), url]
    # stderr kept (errors only) so a failed probe can say WHY mpv gave up.
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, errors="replace")
    ipc = None
    try:
        deadline = time.monotonic() + OPEN_TIMEOUT_SECONDS
        while not os.path.exists(sock_path):
            if proc.poll() is not None or time.monotonic() > deadline:
                logger.info("stream probe: mpv {} before opening its IPC socket{}",
                            f"exited ({proc.returncode})" if proc.poll() is not None
                            else "timed out", _mpv_error(proc))
                return None
            time.sleep(0.1)
        ipc = _Ipc(sock_path)
        loaded_at = None
        while True:
            if cancel is not None and cancel.is_set():
                logger.info("stream probe: cancelled (playback took the connection)")
                return None
            if proc.poll() is not None:
                logger.info("stream probe: mpv exited ({}) before the stream produced tracks"
                            " — refused or unreachable{}", proc.returncode, _mpv_error(proc))
                return None
            now = time.monotonic()
            if loaded_at is None:
                if ipc.get("track-list"):
                    loaded_at = now
                elif now > deadline:
                    logger.info("stream probe: no tracks after {}s", OPEN_TIMEOUT_SECONDS)
                    return None
            elif now - loaded_at >= SETTLE_SECONDS:
                return parse_mpv({name: ipc.get(name) for name in MPV_PROPS})
            time.sleep(0.5)
    except (OSError, ValueError) as exc:
        logger.info("stream probe failed: {}", exc)
        return None
    finally:
        if ipc is not None:
            ipc.quit()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            os.unlink(sock_path)
        except OSError:
            pass
