"""The Windows pipe path of :class:`mpv_ipc.Connection` honours its timeout.

A pipe opened as a file has no read timeout, so before this a property query
against a hung mpv would block the caller forever. The Windows branch is driven
here on any platform: ``_is_windows`` is patched true, a plain temp file stands
in for the pipe (``open(addr, "r+b")`` works on both), and ``_pipe_available``
— the one Windows-only call — is replaced with a script.
"""

from __future__ import annotations

import time

import pytest

from metatv.core.players import mpv_ipc


@pytest.fixture
def pipe_conn(tmp_path, monkeypatch):
    stand_in = tmp_path / "pipe"
    stand_in.write_bytes(b'{"data": 1}\n')
    monkeypatch.setattr(mpv_ipc, "_is_windows", lambda: True)
    conn = mpv_ipc.connect(str(stand_in), timeout=0.2)
    yield conn
    conn.close()


def test_a_silent_pipe_raises_timeout_instead_of_blocking(pipe_conn, monkeypatch):
    monkeypatch.setattr(mpv_ipc, "_pipe_available", lambda pipe: 0)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        pipe_conn.recv(4096)
    elapsed = time.monotonic() - started
    assert 0.2 <= elapsed < 2.0, f"gave up after {elapsed:.2f}s, timeout was 0.2s"


def test_waiting_bytes_are_read_without_waiting(pipe_conn, monkeypatch):
    monkeypatch.setattr(mpv_ipc, "_pipe_available", lambda pipe: 4)
    assert pipe_conn.recv(4096) == b'{"da', "reads only what is waiting, so the read cannot block"


def test_a_closed_pipe_reads_as_eof_like_a_socket(pipe_conn, monkeypatch):
    monkeypatch.setattr(mpv_ipc, "_pipe_available", lambda pipe: None)
    assert pipe_conn.recv(4096) == b""


def test_data_arriving_mid_wait_is_returned(pipe_conn, monkeypatch):
    answers = iter([0, 0, 12])
    monkeypatch.setattr(mpv_ipc, "_pipe_available", lambda pipe: next(answers))
    assert pipe_conn.recv(4096) == b'{"data": 1}\n'
