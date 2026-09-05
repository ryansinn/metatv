"""mpv's own stderr must reach our log — it was silently DEVNULL'd (PLAY-10).

Both mpv Popen sites used to run with ``stderr=subprocess.DEVNULL``, so the
exact "HTTP error 500" / "Will reconnect at 0 in Ns" lines ffmpeg emits during
a same-provider-switch retry backoff never reached the app log. ``start_log_tap``
is the one place a launched process's stderr is piped and read.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

from loguru import logger

from metatv.core.players.mpv_log_tap import start_log_tap


class _ListSink:
    """A loguru sink that appends every formatted record's `extra`/level/message.

    loguru's ``logger.add`` accepts a plain callable sink; storing structured
    fields (not just the formatted string) makes the level assertion exact
    rather than a string-sniff of the rendered line.
    """

    def __init__(self) -> None:
        self.records: list[dict] = []

    def __call__(self, message) -> None:
        record = message.record
        self.records.append({
            "level": record["level"].name,
            "text": record["message"],
        })


def _fake_process(lines: list[bytes]) -> MagicMock:
    """A Popen-like double whose stderr is a real BytesIO — a real byte stream,
    not a MagicMock, so ``readline()`` genuinely hits EOF (``b""``) at the end."""
    proc = MagicMock()
    proc.stderr = io.BytesIO(b"".join(lines))
    return proc


def test_every_line_reaches_the_log_tagged_with_the_key():
    sink = _ListSink()
    handler_id = logger.add(sink, level="DEBUG", format="{message}")
    try:
        proc = _fake_process([
            b"opening stream\n",
            b"HTTP error 500 Internal Server Error\n",
            b"Will reconnect at 0 in 1 second(s).\n",
        ])
        thread = start_log_tap(proc, "prov-1")
        thread.join(timeout=5)
        assert not thread.is_alive(), "log tap thread did not finish on EOF"
    finally:
        logger.remove(handler_id)

    assert len(sink.records) == 3
    assert all("mpv[prov-1]" in r["text"] for r in sink.records)
    assert "opening stream" in sink.records[0]["text"]
    assert sink.records[0]["level"] == "DEBUG"


def test_the_http_error_line_is_escalated_to_warning():
    sink = _ListSink()
    handler_id = logger.add(sink, level="DEBUG", format="{message}")
    try:
        proc = _fake_process([
            b"opening stream\n",
            b"HTTP error 500 Internal Server Error\n",
            b"Will reconnect at 0 in 1 second(s).\n",
        ])
        thread = start_log_tap(proc, "prov-1")
        thread.join(timeout=5)
    finally:
        logger.remove(handler_id)

    levels = [r["level"] for r in sink.records]
    assert levels == ["DEBUG", "WARNING", "WARNING"], (
        "the 500 line, and the reconnect line, must both escalate to WARNING")


def test_the_thread_is_a_daemon_and_is_never_joined_by_the_caller():
    """Shutdown must not wait on a stream that may still be reconnecting."""
    proc = _fake_process([b"one line\n"])
    thread = start_log_tap(proc, "prov-1")
    assert thread.daemon is True
    thread.join(timeout=5)   # test-only wait; production never joins it


def test_a_none_stderr_ends_the_pump_immediately_without_raising():
    proc = MagicMock()
    proc.stderr = None
    thread = start_log_tap(proc, "prov-1")
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_a_misbehaving_stderr_double_does_not_spin_forever():
    """Regression: an unconfigured MagicMock process's ``.stderr`` auto-vivifies
    a MagicMock whose ``readline()`` never returns the ``b""`` EOF sentinel —
    several existing mpv tests patch ``subprocess.Popen`` with exactly this
    shape. The pump must recognize a non-bytes read as "not a real stream" and
    stop, rather than spinning the daemon thread forever."""
    proc = MagicMock()  # proc.stderr.readline() returns a fresh MagicMock, not bytes
    thread = start_log_tap(proc, "Title")
    thread.join(timeout=5)
    assert not thread.is_alive(), "the pump spun forever against a mock stderr"


def test_empty_lines_are_skipped():
    sink = _ListSink()
    handler_id = logger.add(sink, level="DEBUG", format="{message}")
    try:
        proc = _fake_process([b"\n", b"\n", b"real line\n"])
        thread = start_log_tap(proc, "prov-1")
        thread.join(timeout=5)
    finally:
        logger.remove(handler_id)

    assert len(sink.records) == 1
    assert "real line" in sink.records[0]["text"]
