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
        recording_pad_start_seconds = -120
        recording_pad_end_seconds = 900
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

def test_a_recording_takes_the_connection_off_playback(accountant):
    """Settled 2026-08-30: warn and take. This is the take half.

    A programme missed is gone; a viewer interrupted can watch the recording
    afterwards. What makes it acceptable is the countdown, tested below — not
    the recording yielding, which was my earlier reading and was wrong.
    """
    assert accountant.acquire("p1", "playback", "watching-something").granted

    result = accountant.acquire("p1", "recording", "rec-1",
                                preempt_kinds=RECORDING_PREEMPTS)

    assert result.granted, "the recording did not take the stream"
    assert result.preempted == ("watching-something",)
    assert "playback" in RECORDING_PREEMPTS


def test_a_recording_takes_a_download_too(accountant):
    """A download loses only time, so it yields to everything."""
    assert accountant.acquire("p1", "download", "dl-1").granted
    result = accountant.acquire("p1", "recording", "rec-1",
                                preempt_kinds=RECORDING_PREEMPTS)
    assert result.granted
    assert result.preempted == ("dl-1",)


def test_a_polite_recording_leaves_playback_alone_but_still_takes_downloads(
        accountant):
    """`preempt_playback` is per-recording — "take it" is the default, not a law."""
    from metatv.core.recording_manager import _POLITE_PREEMPTS

    assert accountant.acquire("p1", "playback", "watching").granted
    assert not accountant.acquire("p1", "recording", "rec-1",
                                  preempt_kinds=_POLITE_PREEMPTS).granted
    assert "playback" not in _POLITE_PREEMPTS
    assert "download" in _POLITE_PREEMPTS, "a download loses nothing by waiting"


def test_playback_does_not_evict_a_recording(accountant):
    """The other direction stays closed: pressing Play must not kill a recording."""
    from metatv.core.player_manager import PLAYBACK_PREEMPTS

    assert accountant.acquire("p1", "recording", "rec-1").granted
    assert not accountant.acquire("p1", "playback", "play-1",
                                  preempt_kinds=PLAYBACK_PREEMPTS).granted
    assert "recording" not in PLAYBACK_PREEMPTS


# ── the retry window ────────────────────────────────────────────────────────

def test_a_polite_recording_that_is_blocked_waits_and_is_announced_once(
        manager, accountant, db):
    """Only a recording told NOT to take the stream can be blocked at all.

    It then waits out its window rather than failing at once — partial beats
    nothing — and the user hears about it once, not every five seconds for the
    length of a football match.
    """
    from metatv.core.database import RecordingDB

    seen = []
    manager._on_conflict = lambda rid, name: seen.append((rid, name))
    accountant.acquire("p1", "playback", "someone-watching")

    start, end = _window(minutes_from_now=-1)
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                           start, end, pad_start_seconds=0, pad_end_seconds=0,
                           preempt_playback=False).recording_id
    with db.session_scope() as session:
        assert session.get(RecordingDB, rid).preempt_playback is False

    manager._stop.set()          # so the retry wait returns at once
    manager._record(manager._next_due())
    manager._record(manager._next_due())

    assert seen == [(rid, "BBC One")], "announced once per recording, not per retry"
    assert manager._next_due() is not None, "the row must stay due and keep trying"


def test_a_window_that_passed_with_no_bytes_fails_visibly(manager, db):
    """A silent miss is the worst outcome — the row must end up visibly failed."""
    start, end = _window(minutes_from_now=-120)
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                           start, end, pad_start_seconds=0, pad_end_seconds=0).recording_id

    manager._retire_missed()

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        assert row.state == "failed"
        assert "connection" in row.error


def test_a_window_that_passed_with_bytes_is_completed_not_failed(manager, db):
    """Partial IS the success case the retry policy exists to produce."""
    start, end = _window(minutes_from_now=-120)
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                           start, end, pad_start_seconds=0, pad_end_seconds=0).recording_id
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
                           programme_title="The Match").recording_id

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        # The GUIDE window is stored unchanged; the offsets sit beside it.
        assert (row.programme_start, row.programme_end) == (start, end)
        assert row.pad_start_seconds == -120, "2 minutes early, per the spec"
        assert row.pad_end_seconds == 900, "15 minutes late — sport overruns"
        assert row.effective_start == start - timedelta(minutes=2)
        assert row.effective_end == end + timedelta(minutes=15)


def test_record_for_n_minutes_is_not_padded(manager, db):
    """The user already said what they meant; padding would contradict them."""
    start, end = _window()
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end,
                           pad_start_seconds=0, pad_end_seconds=0).recording_id

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        assert (row.effective_start, row.effective_end) == (start, end)


def test_the_same_programme_is_not_scheduled_twice(manager):
    start, end = _window()
    first = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end)
    second = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end)
    assert first.scheduled
    assert not second.scheduled, "a double-click must not produce two recordings"
    assert second.reason == "already scheduled"


def test_a_backwards_window_is_refused(manager):
    start, end = _window()
    assert not manager.schedule("c1", "p1", "BBC One", "u", end, start).scheduled


def test_a_cancelled_window_does_not_block_rescheduling(manager):
    """Cancel then change your mind — the clash check must ignore terminal rows."""
    start, end = _window()
    first = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                             start, end).recording_id
    manager.cancel(first)
    assert manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                            start, end).scheduled


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
                           start, end, pad_start_seconds=0, pad_end_seconds=0).recording_id

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

    dest = tmp_path / "library" / "Recordings"
    captured = list(dest.glob("*.ts"))
    assert not list((tmp_path / "library").glob("*.ts")), (
        "a recording landed beside the downloads instead of in Recordings/")
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
                           start, end, pad_start_seconds=0, pad_end_seconds=0).recording_id
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


# ── the two engines against one accountant ──────────────────────────────────

def test_a_recording_actually_pauses_a_running_download(db, config, accountant,
                                                        endless_server):
    """End to end, not just at the accountant.

    Each engine's own tests prove its half. Neither proves the WIRING — that the
    accountant's preempt callback reaches DownloadManager.on_preempted and moves
    the row. That wiring lives in one line of _setup_downloads(), which is
    exactly the kind of line a refactor drops silently, so it is asserted here
    against real managers rather than mocks.
    """
    from metatv.core.database import DownloadDB
    from metatv.core.download_manager import DownloadManager

    downloads = DownloadManager(db, config, accountant)
    recordings = RecordingManager(db, config, accountant)
    accountant._on_preempt = downloads.on_preempted

    # A download holding p1's only slot, exactly as the scheduler leaves it.
    download_id = "dl-under-way"
    with db.session_scope() as session:
        session.add(DownloadDB(
            id=download_id, channel_id="c9", provider_id="p1",
            channel_name="A Movie", source_url=endless_server,
            dest_path=str(tmp := Path(config.download_dir) / "movie.mp4"),
            state="running", downloaded_bytes=1024))
    assert accountant.acquire("p1", "download", download_id).granted
    assert str(tmp)

    start = now_utc() - timedelta(seconds=1)
    rid = recordings.schedule("c1", "p1", "BBC One", endless_server,
                              start, start + timedelta(seconds=2),
                              pad_start_seconds=0, pad_end_seconds=0).recording_id
    recordings._record(recordings._next_due())

    with db.session_scope() as session:
        parked = session.get(DownloadDB, download_id)
        assert parked.state == "paused", (
            "the recording took the slot but the download never heard about it")
        assert parked.paused_by_playback is True, (
            "parked as a USER pause — it would never resume by itself")
        assert parked.downloaded_bytes == 1024, "progress was discarded"
        assert session.get(RecordingDB, rid).recorded_bytes > 0


def test_window_of_reports_the_padded_window_not_the_guides(manager):
    """What a notification must quote.

    The caller holds the guide's times; schedule() padded them. A message built
    from the caller's copy promises a stop five minutes before the recording
    actually stops.
    """
    start, end = _window()
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end,
                           programme_title="The Match").recording_id

    stored = manager.window_of(rid)

    assert stored == (start - timedelta(minutes=2), end + timedelta(minutes=15))
    assert stored[1] != end, "returned the caller's own unpadded value"
    assert manager.window_of("no-such-id") is None


# ── warn and take: the countdown is what makes taking acceptable ────────────

def test_no_countdown_when_nothing_is_playing(manager, accountant):
    """"Notify only when it matters" — an idle app is never interrupted."""
    seen = []
    manager._on_countdown = lambda rid, title, secs: seen.append(secs)
    start = now_utc() + timedelta(seconds=20)
    manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                     start, start + timedelta(minutes=30),
                     pad_start_seconds=0, pad_end_seconds=0)

    manager._announce_countdowns()

    assert seen == [], "warned about taking a stream nobody was watching"


def test_the_countdown_escalates_and_each_step_fires_once(
        manager, accountant, monkeypatch):
    """10 min / 5 / 1 / 30 s, once each — not every two seconds for a match.

    One recording, a moving clock. Re-scheduling at each distance would give a
    new id and reset the fired-step memory, which is the very thing under test.
    """
    import metatv.core.recording_manager as module
    from metatv.core.recording_manager import COUNTDOWN_STEPS

    assert COUNTDOWN_STEPS == (600, 300, 60, 30)
    accountant.acquire("p1", "playback", "watching")

    seen = []
    manager._on_countdown = lambda rid, title, secs: seen.append(secs)
    start = now_utc() + timedelta(hours=2)
    manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                     start, start + timedelta(minutes=30),
                     pad_start_seconds=0, pad_end_seconds=0)

    for gap, expected in ((700, None), (590, 600), (580, None), (400, None),
                          (290, 300), (100, None), (55, 60), (40, None),
                          (28, 30), (5, None)):
        monkeypatch.setattr(module, "now_utc",
                            lambda g=gap: start - timedelta(seconds=g))
        before = len(seen)
        manager._announce_countdowns()
        fired = seen[before:]
        assert fired == ([expected] if expected else []), (
            f"at {gap}s left, expected {expected}, got {fired}")

    assert seen == [600, 300, 60, 30]


def test_a_late_start_warns_with_the_tightest_step_not_the_loosest(
        manager, accountant, monkeypatch):
    """Open the app 28 seconds before a recording takes your stream.

    Every step has been crossed at once, so a naive loop announces "in 10
    minutes". The only useful sentence is "in 30 seconds", and it is said once.
    """
    import metatv.core.recording_manager as module

    accountant.acquire("p1", "playback", "watching")
    seen = []
    manager._on_countdown = lambda rid, title, secs: seen.append(secs)
    start = now_utc() + timedelta(hours=2)
    manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                     start, start + timedelta(minutes=30),
                     pad_start_seconds=0, pad_end_seconds=0)

    monkeypatch.setattr(module, "now_utc", lambda: start - timedelta(seconds=28))
    manager._announce_countdowns()
    monkeypatch.setattr(module, "now_utc", lambda: start - timedelta(seconds=20))
    manager._announce_countdowns()

    assert seen == [30], f"announced a step other than the tightest: {seen}"


def test_a_start_that_drifts_later_warns_again(manager, accountant, monkeypatch):
    """Guide start times move after you schedule; the spec says re-check.

    If a recording that was 30 seconds away becomes 15 minutes away, the user
    who already got the 30-second warning should get the approach warnings for
    the NEW time rather than silence.
    """
    import metatv.core.recording_manager as module
    from metatv.core.database import RecordingDB

    accountant.acquire("p1", "playback", "watching")
    seen = []
    manager._on_countdown = lambda rid, title, secs: seen.append(secs)
    start = now_utc() + timedelta(hours=2)
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                           start, start + timedelta(minutes=30),
                           pad_start_seconds=0, pad_end_seconds=0).recording_id

    monkeypatch.setattr(module, "now_utc", lambda: start - timedelta(seconds=28))
    manager._announce_countdowns()
    assert seen == [30]

    # The guide moves the programme half an hour out.
    with manager.db.session_scope() as session:
        session.get(RecordingDB, rid).programme_start = start + timedelta(minutes=30)

    manager._announce_countdowns()          # now ~30 min away: nothing crossed
    monkeypatch.setattr(module, "now_utc",
                        lambda: start + timedelta(minutes=30) - timedelta(seconds=590))
    manager._announce_countdowns()

    assert seen == [30, 600], "a drifted start went silent instead of re-warning"


def test_a_countdown_step_is_not_repeated_on_the_next_tick(manager, accountant):
    """The scheduler ticks every 2s; the ten-minute warning must fire once."""
    accountant.acquire("p1", "playback", "watching")
    seen = []
    manager._on_countdown = lambda rid, title, secs: seen.append(secs)
    start = now_utc() + timedelta(seconds=59)
    manager.schedule("c1", "p1", "BBC One", "http://x/live.ts",
                     start, start + timedelta(minutes=30),
                     pad_start_seconds=0, pad_end_seconds=0)

    manager._announce_countdowns()
    manager._announce_countdowns()
    manager._announce_countdowns()

    assert seen == [60], f"repeated the warning: {seen}"


# ── the live extend, and why the stop time is never frozen ──────────────────

def test_extending_a_running_recording_moves_its_stop_time(manager, db):
    """"The live extend is the one that saves an event."

    A frozen stop time makes this impossible, which is why effective_end is
    computed from three columns on every read rather than stored.
    """
    start, end = _window()
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end,
                           pad_start_seconds=0, pad_end_seconds=0).recording_id

    new_end = manager.extend(rid, 20 * 60)

    assert new_end == end + timedelta(minutes=20)
    assert manager.window_of(rid)[1] == end + timedelta(minutes=20)


def test_a_negative_extension_ends_a_recording_early(manager):
    """Stopping early is the same operation — the offsets are signed throughout."""
    start, end = _window()
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end,
                           pad_start_seconds=0, pad_end_seconds=0).recording_id

    assert manager.extend(rid, -10 * 60) == end - timedelta(minutes=10)


def test_a_negative_start_offset_records_from_before_the_programme(manager, db):
    """Signed both ways: skipping a pregame hour is -3600 on the start."""
    from metatv.core.database import RecordingDB

    start, end = _window()
    rid = manager.schedule("c1", "p1", "BBC One", "http://x/live.ts", start, end,
                           pad_start_seconds=3600, pad_end_seconds=0).recording_id

    with db.session_scope() as session:
        row = session.get(RecordingDB, rid)
        assert row.effective_start == start + timedelta(hours=1), (
            "a positive start offset must start LATER, not record extra")


# ── conflicts, found while the user can still act on them ──────────────────

def test_an_overlapping_recording_on_one_source_is_reported_at_schedule_time(
        manager):
    """"Detect at schedule time, not at start time. Offer to drop one."

    Being told at 19:00 that two recordings want one connection is useless.
    """
    start, end = _window()
    manager.schedule("c1", "p1", "BBC One", "http://x/1.ts", start, end,
                     programme_title="The Match",
                     pad_start_seconds=0, pad_end_seconds=0)

    clash = manager.schedule("c2", "p1", "ITV", "http://x/2.ts",
                             start + timedelta(minutes=10), end,
                             programme_title="The Other Match",
                             pad_start_seconds=0, pad_end_seconds=0)

    assert clash.scheduled, "the second is still scheduled — the user chooses"
    assert [name for _rid, name in clash.conflicts] == ["The Match"]


def test_a_different_source_is_not_a_conflict(manager):
    """Each provider has its own connection; two sources at once is fine."""
    start, end = _window()
    manager.schedule("c1", "p1", "BBC One", "http://x/1.ts", start, end,
                     pad_start_seconds=0, pad_end_seconds=0)
    other = manager.schedule("c2", "p2", "ITV", "http://x/2.ts", start, end,
                             pad_start_seconds=0, pad_end_seconds=0)

    assert other.scheduled
    assert other.conflicts == []


def test_back_to_back_recordings_do_not_conflict(manager):
    """Touching windows are not overlapping ones — off-by-one here nags forever."""
    start, end = _window(length=30)
    manager.schedule("c1", "p1", "BBC One", "http://x/1.ts", start, end,
                     pad_start_seconds=0, pad_end_seconds=0)
    following = manager.schedule("c2", "p1", "ITV", "http://x/2.ts",
                                 end, end + timedelta(minutes=30),
                                 pad_start_seconds=0, pad_end_seconds=0)

    assert following.conflicts == []


def test_the_default_padding_creates_a_conflict_that_bare_windows_would_not(
        manager):
    """The offsets are part of the conflict question, not decoration.

    Two programmes an hour apart do not overlap; with a 15-minute run-over and
    a 2-minute lead-in they can. Comparing guide windows would miss it.
    """
    start, end = _window(length=60)
    manager.schedule("c1", "p1", "BBC One", "http://x/1.ts", start, end,
                     programme_title="First")

    following = manager.schedule("c2", "p1", "ITV", "http://x/2.ts",
                                 end + timedelta(minutes=5),
                                 end + timedelta(minutes=65),
                                 programme_title="Second")

    assert [n for _r, n in following.conflicts] == ["First"], (
        "the 15-minute run-over overlaps the next programme and was missed")
