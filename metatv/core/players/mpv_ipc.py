"""How MetaTV reaches a running mpv — the one place that knows the transport.

mpv's JSON IPC (``--input-ipc-server``) is a Unix domain socket on Linux and
macOS and a named pipe on Windows. The protocol on top is identical, so the
player and the stream-details probe both talk to mpv through this module and
never touch ``socket``/pipes themselves.

The address is derived here, not configured: it is an implementation detail no
user should set, and the old ``/tmp`` default was shared by every user on the
machine. Sockets now live in the per-user :func:`app_paths.runtime_dir`.
"""

from __future__ import annotations

import os
import socket
import sys

from metatv.core import app_paths

_PREFIX = "mpv-metatv-"


def _is_windows() -> bool:
    return sys.platform == "win32"


def address(name: str) -> str:
    """The IPC address for the mpv instance called *name*.

    Args:
        name: A short ``[A-Za-z0-9_-]`` label, unique per live instance.

    Returns:
        A named-pipe path on Windows, else a socket path in the runtime dir.
    """
    if _is_windows():
        return rf"\\.\pipe\{_PREFIX}{name}"
    return str(app_paths.runtime_dir() / f"{_PREFIX}{name}")


def is_ready(addr: str) -> bool:
    """True once mpv is listening on *addr*."""
    if _is_windows():
        # A pipe has no file to stat; opening a client end and closing it again
        # is harmless — mpv serves each connection independently.
        try:
            with open(addr, "r+b", buffering=0):
                return True
        except OSError:
            return False
    return os.path.exists(addr)


def discard(addr: str) -> bool:
    """Remove a stale socket file left by a previous mpv. No-op for a pipe.

    Returns:
        True when a file was removed.

    Raises:
        OSError: The file exists but could not be removed.
    """
    if _is_windows() or not os.path.exists(addr):
        return False
    os.remove(addr)
    return True


class Connection:
    """One client connection to an mpv IPC server.

    Raises the same exceptions on every platform for the cases callers handle:
    ``FileNotFoundError`` when nothing is listening and ``TimeoutError`` (alias
    ``socket.timeout``) when a read stalls. A Windows pipe opened as a file has
    no read timeout, so *timeout* applies on Unix only.
    """

    def __init__(self, addr: str, timeout: float):
        if _is_windows():
            self._sock = None
            self._pipe = open(addr, "r+b", buffering=0)
        else:
            self._pipe = None
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(timeout)
            try:
                self._sock.connect(addr)
            except BaseException:
                self._sock.close()
                raise

    def sendall(self, data: bytes) -> None:
        if self._pipe is not None:
            self._pipe.write(data)
        else:
            self._sock.sendall(data)

    def recv(self, size: int) -> bytes:
        if self._pipe is not None:
            return self._pipe.read(size) or b""
        return self._sock.recv(size)

    def close(self) -> None:
        (self._pipe or self._sock).close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def connect(addr: str, timeout: float = 2.0) -> Connection:
    """Open a :class:`Connection` to the mpv listening on *addr*."""
    return Connection(addr, timeout)
