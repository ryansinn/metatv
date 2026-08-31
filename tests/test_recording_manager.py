"""Recording engine — the priority inversion, the retry window, and the clock.

The one thing worth testing hardest is the asymmetry with downloads: a download
that playback evicts must resume, and a recording that playback would evict must
NOT be evicted at all. Both halves are asserted here against the same
accountant, because a test that only builds a recording cannot tell a correct
rule from an accountant that never preempts anything.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.database import Database, RecordingDB
from metatv.core.epg_utils import now_utc
from metatv.core.recording_manager import (RECORDING_PREEMPTS, RecordingManager,
                                           RecordingProgress)


@pytest.fixture
def db(tmp_path):
    """A real Database on a real file — CLAUDE.md forbids :memory: for session work."""
    database = Database(f"sqlite:///{tmp_path / 'rec.db'}")
    database.create_tables()
    return database


@pytest.fixture
def config(tmp_path):
    class _Config:
        download_dir = str(tmp_path / "library")
        recording_pad_start_seconds = 60
        recording_pad_end_seconds = 300
    return _Config()


@pytest.fixture
def accountant():
    return ConnectionAccountant(capacity_resolver=lambda _pid: 1)


@pytest.fixture
def manager(db, config, accountant):
    return RecordingManager(db, config, accountant)


def _window(minutes_from_now=0, length=30):
    """A window relative to the REAL clock.

    A hard-coded date is not "currently airing" for all but one moment of one
    day — the scheduler compares against ``now_utc()``, so the fixture has to
    as well or every due-window test is testing the wrong branch.
    """
    start = now_utc() + timedelta(minutes=minutes_from_now)
    return start.replace(microsecond=0), (start + timedelta(minutes=length)).replace(microsecond=0)


# ── the priority inversion ──────────────────────────────────────────────────

def test_a_recording_evicts_a_download_but_playback_does_not_evict_it(accountant):
    """The whole design in one test.

    Downloads and recordings sit on opposite sides of the recoverability axis:
    a paused download loses time, a paused recording loses the content. So a
    recording takes a download's slot, and playback — which evicts downloads —
    leaves a recording alone.
    """
    from metatv.core.player_manager import PLAYBACK_PREEMPTS

    assert accountant.acquire("p1", "download", "dl-1").granted

    # A recording takes the slot off a download.
    result = accountant.acquire("p1", "recording", "rec-1",
                                preempt_kinds=RECORDING_PREEMPTS)
    assert result.granted, "a recording must be able to displace a download"
    assert result.preempted == ("dl-1",), "the download must be the evicted holder"

    # Playback now finds the slot held by a recording and does NOT take it.
    playback = accountant.acquire("p1", "playback", "play-1",
                                  preempt_kinds=PLAYBACK_PREEMPTS)
    assert not playback.granted, (
        "playback evicted a recording — those minutes are unrecoverable")
    assert "recording" not in PLAYBACK_PREEMPTS


def test_a_recording_does_not_evict_playback_either(accountant):
    """Yanking the stream from someone who is watching is not on the table."""
    assert accountant.acquire("p1", "playback", "play-1").granted
    result = accountant.acquire("p1", "recording", "rec-1",
                                preempt_kinds=RECORDING_PREEMPTS)
    assert not result.granted
    assert "playback" not in RECORDING_PREEMPTS


# ── the retry window ────────────────────────────────────────────────────────

def test_a_blocked_recording_keeps_its_row_and_is_announced_once(manager, accountant):
    """Partial beats nothing: it waits for the slot rather than failing at once.

    And the user hears about it exactly once, not every five seconds for the
    length of a football match.
    """
    seen = []
    manager._on_conflict = lambda rid, name: seen.append((rid, name))
    accountant.acquire("p1", "playback", "someone-watching")

    start, end = _window(minutes_from_now=-1)
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                           start, end, pad=False)

    manager._stop.set()          # so the retry wait returns at once
    manager._record(manager._next_due())
    manager._record(manager._next_due())

    assert seen == [(rid, "BBC One")], "announced once per recording, not per retry"
    assert manager._next_due() is not None, "the row must stay due and keep trying"


def test_a_window_that_passed_with_no_bytes_fails_visibly(manager, db):
    """A silent miss is the worst outcome — the row must end up visibly failed."""
    start, end = _window(minutes_from_now=-120)
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                           start, end, pad=False)

    manager._retire_missed()

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        assert row.state == "failed"
        assert "connection" in row.error


def test_a_window_that_passed_with_bytes_is_completed_not_failed(manager, db):
    """Partial IS the success case the retry policy exists to produce."""
    start, end = _window(minutes_from_now=-120)
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                           start, end, pad=False)
    with db.session_scope() as session:
        session.get(RecordingDB, rid).recorded_bytes = 4096

    manager._retire_missed()

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        assert row.state == "completed", "40 recorded minutes is not a failure"
        assert row.error is None


# ── scheduling ──────────────────────────────────────────────────────────────

def test_padding_is_applied_once_at_schedule_time(manager, db):
    """Broadcasters overrun. The stored window is the literal one honoured."""
    start, end = _window()
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end,
                           programme_title="The Match", pad=True)

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        assert row.starts_at == start - timedelta(seconds=60)
        assert row.ends_at == end + timedelta(seconds=300)


def test_record_for_n_minutes_is_not_padded(manager, db):
    """The user already said what they meant; padding would contradict them."""
    start, end = _window()
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end,
                           pad=False)

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        assert (row.starts_at, row.ends_at) == (start, end)


def test_the_same_programme_is_not_scheduled_twice(manager):
    start, end = _window()
    first = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end)
    second = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end)
    assert first is not None
    assert second is None, "a double-click must not produce two recordings"


def test_a_backwards_window_is_refused(manager):
    start, end = _window()
    assert manager.schedule("c1", "p1", "BBC One", "u", end, start) is None


def test_a_cancelled_window_does_not_block_rescheduling(manager):
    """Cancel then change your mind — the clash check must ignore terminal rows."""
    start, end = _window()
    first = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end)
    manager.cancel(first)
    assert manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                            start, end) is not None


# ── progress is wall-clock, because a live stream has no total ──────────────

def test_progress_fraction_is_the_clock_not_the_bytes():
    start = datetime(2026, 8, 31, 20, 0)
    p = RecordingProgress(
        recording_id="r", channel_id="c", channel_name="BBC One",
        programme_title="The Match", state="recording", starts_at=start,
        ends_at=start + timedelta(minutes=60), recorded_bytes=0,
        dest_path="/tmp/x.ts", error=None, waiting_for_slot=False)

    assert p.elapsed_fraction(now=start) == 0.0
    assert p.elapsed_fraction(now=start + timedelta(minutes=15)) == 0.25
    assert p.elapsed_fraction(now=start + timedelta(minutes=90)) == 1.0, "clamped"
    assert p.elapsed_fraction(now=start - timedelta(minutes=5)) == 0.0, "clamped"


def test_progress_fraction_takes_now_rather_than_reaching_for_it():
    """An injected clock must not be second-guessed underneath.

    Three bugs of exactly this shape were found in one day — one silently
    deleted 29.75 days instead of 30 — so the seam is asserted, not assumed.
    """
    start = datetime(2026, 8, 31, 20, 0)
    p = RecordingProgress(
        recording_id="r", channel_id="c", channel_name="c", programme_title="",
        state="recording", starts_at=start, ends_at=start + timedelta(hours=1),
        recorded_bytes=0, dest_path="", error=None, waiting_for_slot=False)

    import metatv.core.recording_manager as module

    called = []
    original = module.now_utc
    module.now_utc = lambda: called.append(1) or datetime(2026, 1, 1)
    try:
        assert p.elapsed_fraction(now=start + timedelta(minutes=30)) == 0.5
        assert called == [], "reached for the real clock despite being given one"
    finally:
        module.now_utc = original


def test_progress_survives_a_zero_length_window():
    """Division by zero on an edge case is a crash in a list refresh."""
    start = datetime(2026, 8, 31, 20, 0)
    p = RecordingProgress(
        recording_id="r", channel_id="c", channel_name="c", programme_title="",
        state="recording", starts_at=start, ends_at=start, recorded_bytes=0,
        dest_path="", error=None, waiting_for_slot=False)
    assert p.elapsed_fraction(now=start) == 1.0


# ── a real capture off an endless stream ────────────────────────────────────

#: Bytes per write and the pause between them — about 1.2 MB/s.
#: Throttled deliberately. An unthrottled loopback handler writes at hundreds
#: of MB/s, and an early run of this test left a 2.2 GB capture in the pytest
#: tmpdir and filled a 24 GB tmpfs. The rate still has to clear
#: ``CHUNK_BYTES`` several times inside the window, or the recorder sits
#: blocked in ``iter_content`` and never reaches its deadline check — which
#: would make the test pass for the wrong reason.
_SERVE_CHUNK = 64 * 1024
_SERVE_DELAY = 0.05

#: The handler gives up after this long no matter what. A live stream really is
#: endless, but a test that models one faithfully HANGS when the deadline check
#: regresses, and a hung test is a twenty-minute CI timeout with no message
#: instead of a failure that names the bug. With this cap the same regression
#: comes back as an elapsed-time assertion, in seconds.
_SERVE_LIMIT = 10.0


class _EndlessHandler(BaseHTTPRequestHandler):
    """A live channel: no Content-Length, no end, until the client walks away."""

    def do_GET(self):                                # noqa: N802 - BaseHTTPRequestHandler API
        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.end_headers()
        packet = (b"\x47" + b"\x00" * 187) * (_SERVE_CHUNK // 188)
        deadline = time.monotonic() + _SERVE_LIMIT
        try:
            while time.monotonic() < deadline:
                self.wfile.write(packet)
                self.wfile.flush()
                time.sleep(_SERVE_DELAY)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):                    # noqa: D102 - silence the server
        pass


@pytest.fixture
def endless_server():
    server = HTTPServer(("127.0.0.1", 0), _EndlessHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/live.ts"
    server.shutdown()


def test_a_recording_captures_bytes_and_stops_at_its_deadline(
        manager, db, accountant, endless_server, tmp_path):
    """The end-to-end claim: real socket, real file, and the clock stops it.

    A live stream never ends by itself, so "stops at the deadline" is the only
    thing that makes a recording terminate at all — a manager that ignored
    ``ends_at`` would hang here rather than fail an assertion, which is why the
    window is seconds and the test is not marked slow.
    """
    start = now_utc() - timedelta(seconds=1)
    end = start + timedelta(seconds=3)
    rid = manager.schedule("c1", "p1", "BBC One", endless_server,
                           start, end, pad=False)

    began = time.monotonic()
    manager._record(manager._next_due())
    elapsed = time.monotonic() - began

    # The clock is what ended this, not the server running out. The stub serves
    # for _SERVE_LIMIT seconds, so a recorder that ignored ends_at would return
    # only when the source quit — and this is the assertion that says so.
    assert elapsed < _SERVE_LIMIT / 2, (
        f"_record ran {elapsed:.1f}s for a 3s window — ends_at is not stopping it")

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        assert row.state == "completed", f"did not finish cleanly: {row.error}"
        assert row.recorded_bytes > 0, "recorded nothing off a stream of bytes"

    dest = tmp_path / "library"
    captured = list(dest.glob("*.ts"))
    assert captured, "no .ts file was written to the library"
    size = captured[0].stat().st_size
    assert size > 0
    # The deadline STOPPED it, rather than the test happening to finish. A
    # recorder that ignored ends_at would run until the server or the disk gave
    # out, so an upper bound is the assertion that the clock is what ended this.
    assert size < 32 * 1024 * 1024, (
        f"captured {size} bytes in a 3s window — the deadline is not stopping it")
    assert accountant.holders("p1") == [], "the connection slot was never released"


def test_a_reconnection_appends_rather_than_truncating(
        manager, db, endless_server, tmp_path):
    """A blip must cost the blip, not the minutes already on disk.

    Opening the file with ``"wb"`` instead of ``"ab"`` is a one-character bug
    that silently discards everything recorded before a dropped connection.
    """
    start = now_utc() - timedelta(seconds=1)
    end = start + timedelta(seconds=2)
    rid = manager.schedule("c1", "p1", "BBC One", endless_server,
                           start, end, pad=False)
    with db.session_scope() as session:
        dest = Path(session.get(RecordingDB, rid).dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"EARLIER" * 100)               # what a first pass recorded
    manager._flush(rid, dest.stat().st_size)

    row = manager._next_due()
    row["ends_at"] = now_utc() + timedelta(seconds=2)   # reopen the window
    manager._record(row)

    assert dest.read_bytes().startswith(b"EARLIER"), (
        "the reconnection truncated the file and lost the first pass")
    with db.session_scope() as session:
        assert session.get(RecordingDB, rid).recorded_bytes > 700
