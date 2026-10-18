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

import functools
import os
import socket
import sys
import time

from metatv.core import app_paths

_PREFIX = "mpv-metatv-"

#: How often a pipe read checks for data while waiting out its timeout.
_PIPE_POLL_S = 0.01


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


def _pipe_available(pipe) -> "int | None":
    """Bytes waiting in a Windows pipe, or None once mpv has closed its end.

    ``PeekNamedPipe`` never blocks, which is what lets :meth:`Connection.recv`
    honour a timeout: a pipe opened as a file has none, so a plain read on a
    hung mpv would freeze the caller (the UI thread, for a property query).
    """
    import ctypes
    import msvcrt
    from ctypes import wintypes

    available = wintypes.DWORD(0)
    handle = msvcrt.get_osfhandle(pipe.fileno())
    if not _peek_named_pipe()(handle, None, 0, None, ctypes.byref(available), None):
        return None
    return available.value


@functools.cache
def _peek_named_pipe():
    """kernel32's ``PeekNamedPipe``, bound once (Windows only)."""
    import ctypes
    from ctypes import wintypes

    peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                     wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPDWORD]
    peek.restype = wintypes.BOOL
    return peek


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
    ``socket.timeout``) when a read stalls past *timeout*. A socket enforces it
    itself; a Windows pipe has no read timeout, so :meth:`recv` polls
    :func:`_pipe_available` instead. Writes are not timed: commands are small
    and mpv drains them.
    """

    def __init__(self, addr: str, timeout: float):
        self._timeout = timeout
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
        if self._pipe is None:
            return self._sock.recv(size)
        deadline = time.monotonic() + self._timeout
        while True:
            available = _pipe_available(self._pipe)
            if available is None:  # mpv closed its end: EOF, as a socket reports it
                return b""
            if available:
                return self._pipe.read(min(size, available)) or b""
            if time.monotonic() >= deadline:
                raise TimeoutError(f"mpv sent nothing for {self._timeout}s")
            time.sleep(_PIPE_POLL_S)

    def close(self) -> None:
        (self._pipe or self._sock).close()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def connect(addr: str, timeout: float = 2.0) -> Connection:
    """Open a :class:`Connection` to the mpv listening on *addr*."""
    return Connection(addr, timeout)
