"""Downloading a VOD: resumable, per-source, and it yields to playback.

Every one of the owner's providers reports ``max_connections = 1``, so a
download and a playback on the same source are *always* in contention. The
connection rule is therefore the feature rather than a detail, and most of what
is asserted here is about who gets the slot and what happens to the loser.

The HTTP is real — a local server that honours ``Range`` — because the two
things most likely to be wrong are exactly the two a mock would paper over: the
byte offset a resume starts from, and what ``Content-Length`` means on a 206.
"""

from __future__ import annotations

import http.server
import pathlib
import socketserver
import threading
import time

import pytest

from metatv.core.config import Config
from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.database import Database, DownloadDB
from metatv.core.download_manager import (
    DownloadManager, DownloadProgress, safe_filename)


PAYLOAD = bytes(range(256)) * 2000          # ~512 KB with verifiable content


class _RangeServer:
    """A file server that honours Range — or refuses to, on request."""

    def __init__(self, payload: bytes, honour_range: bool = True) -> None:
        self.payload = payload
        self.honour_range = honour_range
        self.range_requests: list[str] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):    # noqa: N802 - quiet
                pass

            def do_GET(self):                # noqa: N802 - Qt-free HTTP API
                rng = self.headers.get("Range")
                if rng:
                    outer.range_requests.append(rng)
                if rng and outer.honour_range and rng.startswith("bytes="):
                    start = int(rng.split("=")[1].split("-")[0])
                    body = outer.payload[start:]
                    self.send_response(206)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header(
                        "Content-Range",
                        f"bytes {start}-{len(outer.payload) - 1}/{len(outer.payload)}")
                else:
                    body = outer.payload
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/movie.mp4"

    def stop(self) -> None:
        self._server.shutdown()


@pytest.fixture
def server():
    s = _RangeServer(PAYLOAD)
    yield s
    s.stop()


@pytest.fixture
def env(tmp_path):
    """A manager wired to a real database, a real library dir, and the arbiter."""
    config = Config(config_dir=tmp_path)
    config.download_dir = str(tmp_path / "library")
    db = Database(f"sqlite:///{tmp_path / 'dl.db'}")
    db.create_tables()
    accountant = ConnectionAccountant(lambda _p: 1)
    manager = DownloadManager(db, config, accountant)
    accountant.add_preempt_listener(manager.on_preempted)
    yield manager, db, config, accountant
    manager.shutdown()


def _run_until_done(manager, timeout=15.0):
    manager.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = manager.progress()
        if rows and all(r.state in ("completed", "failed") for r in rows):
            return rows
        time.sleep(0.05)
    return manager.progress()


# ── the queue ───────────────────────────────────────────────────────────────

def test_a_download_completes_with_the_right_bytes(env, server):
    manager, *_ = env
    manager.enqueue("ch1", "p1", "The Film (2024)", server.url)

    rows = _run_until_done(manager)

    assert rows[0].state == "completed"
    assert pathlib.Path(rows[0].dest_path).read_bytes() == PAYLOAD


def test_a_completed_download_reads_as_finished_not_a_quarter_done(env, server):
    """The progress flush is throttled to once a second; the LAST one is forced.

    Without that, a file whose final chunk arrived within a second of the
    previous flush finished on disk while the row still said 25% — a completed
    download rendering as a quarter-full bar.
    """
    manager, *_ = env
    manager.enqueue("ch1", "p1", "Film", server.url)

    rows = _run_until_done(manager)

    assert rows[0].downloaded_bytes == len(PAYLOAD)
    assert rows[0].fraction == 1.0


def test_asking_twice_for_the_same_film_queues_it_once(env, server):
    """A double-click is not a request for two copies."""
    manager, *_ = env
    assert manager.enqueue("ch1", "p1", "Film", server.url) is not None
    assert manager.enqueue("ch1", "p1", "Film", server.url) is None
    assert len(manager.progress()) == 1


def test_the_queue_survives_a_restart(env, server, tmp_path):
    """It is persisted, which is the point of a table rather than a list."""
    manager, db, config, accountant = env
    manager.enqueue("ch1", "p1", "Film", server.url)

    second = DownloadManager(db, config, accountant)
    assert [r.channel_id for r in second.progress()] == ["ch1"]


def test_the_filename_is_the_users_name_with_the_urls_extension():
    assert safe_filename("The Film (2024)", "http://x/y/1.mkv") == "The Film _2024_.mkv"
    assert safe_filename("a/b:c", "http://x/y/1.mp4") == "a_b_c.mp4"
    assert safe_filename("", "http://x/y/1.mp4") == "download.mp4"
    assert safe_filename("no ext", "http://x/y/1") == "no ext.mp4"


# ── resume ──────────────────────────────────────────────────────────────────

def test_a_partial_file_resumes_instead_of_restarting(env, server):
    """The reason this is an HTTP GET and not mpv --stream-record."""
    manager, db, *_ = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)

    with db.session_scope(commit=False) as session:
        dest = session.query(DownloadDB).filter_by(id=download_id).one().dest_path
    pathlib.Path(dest).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(dest + ".part").write_bytes(PAYLOAD[:200_000])

    rows = _run_until_done(manager)

    assert rows[0].state == "completed"
    assert server.range_requests == ["bytes=200000-"], "it must ask to resume"
    assert pathlib.Path(rows[0].dest_path).read_bytes() == PAYLOAD, (
        "resuming must produce the same file, not a spliced one"
    )


def test_the_total_is_the_whole_file_not_the_range_length(env, server):
    """``Content-Length`` on a 206 is the length of the RANGE.

    Taken at face value it is smaller than what is already on disk, so a resumed
    download reports over 100% and the bar runs off the end.
    """
    manager, db, *_ = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    with db.session_scope(commit=False) as session:
        dest = session.query(DownloadDB).filter_by(id=download_id).one().dest_path
    pathlib.Path(dest).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(dest + ".part").write_bytes(PAYLOAD[:200_000])

    rows = _run_until_done(manager)

    assert rows[0].total_bytes == len(PAYLOAD)
    assert rows[0].fraction == 1.0


def test_a_server_that_ignores_range_restarts_rather_than_corrupting(tmp_path):
    """Appending a full body to a partial file makes a file that plays wrong.

    Silent corruption is the worst outcome here — it looks like a successful
    download until you watch it.
    """
    server = _RangeServer(PAYLOAD, honour_range=False)
    try:
        config = Config(config_dir=tmp_path)
        config.download_dir = str(tmp_path / "library")
        db = Database(f"sqlite:///{tmp_path / 'dl.db'}")
        db.create_tables()
        manager = DownloadManager(db, config, ConnectionAccountant(lambda _p: 1))
        download_id = manager.enqueue("ch1", "p1", "Film", server.url)

        with db.session_scope(commit=False) as session:
            dest = session.query(DownloadDB).filter_by(id=download_id).one().dest_path
        pathlib.Path(dest).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(dest + ".part").write_bytes(PAYLOAD[:200_000])

        rows = _run_until_done(manager)
        manager.shutdown()

        assert rows[0].state == "completed"
        assert pathlib.Path(rows[0].dest_path).read_bytes() == PAYLOAD, (
            "the partial must be discarded, not appended to"
        )
    finally:
        server.stop()


# ── the connection rule ─────────────────────────────────────────────────────

def test_a_download_holds_a_slot_and_gives_it_back(env, server):
    manager, _db, _config, accountant = env
    manager.enqueue("ch1", "p1", "Film", server.url)

    _run_until_done(manager)

    assert accountant.in_use("p1") == 0, "a finished download must not hold a slot"


def test_playback_preempts_a_running_download(env, server):
    """The eviction path, end to end through the real accountant."""
    manager, _db, _config, accountant = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    accountant.acquire("p1", "download", download_id)

    manager.on_preempted("p1", download_id, "download")

    row = manager.progress()[0]
    assert row.state == "paused"
    assert row.paused_by_playback is True, (
        "it must be marked as playback's doing, so it can come back by itself"
    )


def test_a_playback_pause_resumes_itself_but_a_user_pause_does_not(env, server):
    """The distinction the ``paused_by_playback`` column exists for.

    A download the user paused staying paused is the whole point of pausing it.
    """
    manager, _db, _config, accountant = env
    first = manager.enqueue("ch1", "p1", "One", server.url)
    manager.on_preempted("p1", first, "download")
    manager.pause(first)                       # then the user pauses it too
    assert manager.progress()[0].paused_by_playback is False

    manager._resume_anything_playback_freed()
    assert manager.progress()[0].state == "paused", "a user pause is not undone"

    manager.on_preempted("p1", first, "download")
    manager._resume_anything_playback_freed()
    assert manager.progress()[0].state == "queued", "playback's pause is undone"


def test_a_busy_provider_does_not_block_another_source(env, server):
    """Per-source, not global: downloads on B run while you watch A."""
    manager, _db, _config, accountant = env
    manager.enqueue("chA", "pA", "A", server.url)
    manager.enqueue("chB", "pB", "B", server.url)
    accountant.acquire("pA", "playback", "someone-watching-A")

    rows = {r.channel_id: r for r in _run_until_done(manager, timeout=8.0)}

    assert rows["chB"].state == "completed", "B must not wait behind a busy A"
    assert rows["chA"].state != "completed", "A's slot is taken by playback"


def test_the_global_pause_stops_everything(env, server):
    manager, _db, config, _accountant = env
    config.downloads_paused = True
    manager.enqueue("ch1", "p1", "Film", server.url)

    manager.start()
    time.sleep(0.5)

    assert manager.progress()[0].state == "queued", "nothing runs while paused"


# ── failure and cancellation ────────────────────────────────────────────────

def test_an_unreachable_url_fails_the_row_and_frees_the_slot(env):
    manager, _db, _config, accountant = env
    manager.enqueue("ch1", "p1", "Film", "http://127.0.0.1:1/nope.mp4")

    rows = _run_until_done(manager, timeout=20.0)

    assert rows[0].state == "failed"
    assert rows[0].error, "a failure the user cannot see is a failure they cannot fix"
    assert accountant.in_use("p1") == 0, "a failed download must not hold the slot"


def test_cancelling_removes_the_row_and_the_partial_file(env, server):
    manager, db, *_ = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    with db.session_scope(commit=False) as session:
        dest = session.query(DownloadDB).filter_by(id=download_id).one().dest_path
    pathlib.Path(dest).parent.mkdir(parents=True, exist_ok=True)
    partial = pathlib.Path(dest + ".part")
    partial.write_bytes(b"half a film")

    manager.cancel(download_id)

    assert manager.progress() == []
    assert not partial.exists(), "a cancelled download must not leave bytes behind"


def test_progress_crosses_the_thread_boundary_as_plain_data(env, server):
    """Never an ORM row: the caller reads it on the main thread, after the
    session closed (CLAUDE.md: ORM objects must not outlive their session)."""
    manager, *_ = env
    manager.enqueue("ch1", "p1", "Film", server.url)
    row = manager.progress()[0]
    assert isinstance(row, DownloadProgress)
    assert row.channel_name == "Film"


def test_an_unknown_total_reports_no_fraction_rather_than_zero(env):
    """None lets a caller draw an indeterminate bar; 0.0 reads as stalled."""
    row = DownloadProgress(
        id="x", channel_id="c", channel_name="n", provider_id="p", state="running",
        downloaded_bytes=500, total_bytes=None, dest_path="/tmp/x", error=None,
        paused_by_playback=False)
    assert row.fraction is None


# ── reason: why a row is not moving right now ──────────────────────────────

def test_queued_reason_names_the_connection_gate(env, server):
    """The queue explains itself: which source, how many slots, all in use."""
    manager, _db, _config, accountant = env
    accountant.acquire("p1", "playback", "someone-watching")  # the only slot
    manager.enqueue("ch1", "p1", "Film", server.url)

    row = manager.progress()[0]
    assert row.state == "queued"
    assert row.reason == (
        "Queued — this source allows 1 connection and it is in use."), row.reason


def test_global_pause_reason_explains_a_queued_row(env, server):
    """'Pause all downloads' sets the flag; every queued row's reason says so."""
    manager, _db, config, _accountant = env
    config.downloads_paused = True
    manager.enqueue("ch1", "p1", "Film", server.url)

    row = manager.progress()[0]
    assert row.state == "queued"
    assert row.reason == "Paused — downloads are paused"


def test_playback_pause_reason_is_the_long_explanation(env, server):
    manager, *_ = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    manager.on_preempted("p1", download_id, "download")

    row = manager.progress()[0]
    assert row.state == "paused"
    assert "Resumes when playback stops" in row.reason


def test_user_pause_reason_is_plain(env, server):
    """A user pause with nothing else going on just says "Paused"."""
    manager, *_ = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    manager.pause(download_id)

    row = manager.progress()[0]
    assert row.reason == "Paused"


def test_failed_reason_is_the_error(env):
    manager, *_ = env
    manager.enqueue("ch1", "p1", "Film", "http://127.0.0.1:1/nope.mp4")

    rows = _run_until_done(manager, timeout=20.0)

    assert rows[0].state == "failed"
    assert rows[0].reason == rows[0].error


def test_running_and_completed_rows_carry_no_reason(env, server):
    """A moving/finished row needs no explanation — only a stuck one does."""
    manager, *_ = env
    manager.enqueue("ch1", "p1", "Film", server.url)

    rows = _run_until_done(manager)

    assert rows[0].state == "completed"
    assert rows[0].reason is None


# ── speed and ETA: derived from a RECENT ring, never the whole lifetime ────

def test_rate_and_eta_are_derived_from_the_injected_clock(env, server):
    """Never sleep for this: the clock is injected precisely so a test need not."""
    manager, db, _config, _accountant = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    fake_now = [1_000.0]
    manager._clock = lambda: fake_now[0]

    manager._record_rate_sample(download_id, 200_000)
    fake_now[0] += 2.0
    manager._record_rate_sample(download_id, 400_000)  # +200,000 B / 2s

    with db.session_scope() as session:
        row = session.query(DownloadDB).filter_by(id=download_id).one()
        row.state = "running"
        row.total_bytes = 1_000_000
        row.downloaded_bytes = 400_000

    row = manager.progress()[0]
    assert row.bytes_per_second == pytest.approx(100_000, rel=0.01)
    assert row.eta_seconds == 6, "600,000 bytes left at 100,000 B/s"


def test_a_single_sample_reports_no_rate_yet(env, server):
    """One point has no slope — None, not a divide-by-zero or a guess."""
    manager, db, _config, _accountant = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    manager._clock = lambda: 1_000.0
    manager._record_rate_sample(download_id, 200_000)

    with db.session_scope() as session:
        row = session.query(DownloadDB).filter_by(id=download_id).one()
        row.state = "running"
        row.total_bytes = 1_000_000

    row = manager.progress()[0]
    assert row.bytes_per_second is None
    assert row.eta_seconds is None


def test_the_rate_ring_forgets_samples_older_than_its_window(env, server):
    """A sample from ten seconds ago says nothing about the speed right now."""
    manager, db, _config, _accountant = env
    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    fake_now = [1_000.0]
    manager._clock = lambda: fake_now[0]
    manager._record_rate_sample(download_id, 0)
    fake_now[0] += 10.0   # older than the ring's ~5s window
    manager._record_rate_sample(download_id, 500_000)

    with db.session_scope() as session:
        row = session.query(DownloadDB).filter_by(id=download_id).one()
        row.state = "running"
        row.total_bytes = 1_000_000

    row = manager.progress()[0]
    assert row.bytes_per_second is None, "only one sample remains inside the window"


# ── history (terminal rows) — hiding the LEDGER, never the file, never the row ─

def test_clear_history_group_hides_only_rows_inside_the_window(env, server):
    manager, db, _config, _accountant = env
    from datetime import datetime, timedelta

    manager.enqueue("recent", "p1", "Recent Film", server.url)
    manager.enqueue("old", "p1", "Old Film", server.url)
    now = datetime.utcnow()
    with db.session_scope() as session:
        for row in session.query(DownloadDB).all():
            row.state = "completed"
            row.updated_at = now if row.channel_id == "recent" else now - timedelta(days=40)

    count, snapshot = manager.clear_history_group(now - timedelta(hours=1), None)

    assert count == 1
    by_channel = {r.channel_id: r for r in manager.progress()}
    assert set(by_channel) == {"recent", "old"}, "clearing history must never remove the row"
    assert by_channel["recent"].history_cleared is True
    assert by_channel["old"].history_cleared is False, "a row outside the window must stay visible"
    assert snapshot[0]["channel_id"] == "recent"


def test_restore_history_snapshot_undoes_a_clear_without_touching_the_file(env, server):
    """Undo un-hides the ledger row; the file was never touched either way."""
    manager, db, _config, _accountant = env
    from datetime import datetime

    download_id = manager.enqueue("ch1", "p1", "Film", server.url)
    with db.session_scope() as session:
        row = session.query(DownloadDB).filter_by(id=download_id).one()
        row.state = "completed"
        row.updated_at = datetime.utcnow()
        dest = pathlib.Path(row.dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"a finished film")

    count, snapshot = manager.clear_history_group(None, None)
    assert count == 1
    rows = manager.progress()
    assert len(rows) == 1 and rows[0].history_cleared is True, "hidden, never deleted"
    assert dest.exists(), "clearing HISTORY must never touch the file"

    restored = manager.restore_history_snapshot(snapshot)
    assert restored == 1
    rows = manager.progress()
    assert len(rows) == 1 and rows[0].id == download_id and rows[0].state == "completed"
    assert rows[0].history_cleared is False
    assert dest.exists()


def test_clear_history_group_leaves_active_rows_alone(env, server):
    """Only completed/failed rows are history — a running download is not it."""
    manager, db, _config, _accountant = env
    manager.enqueue("ch1", "p1", "Film", server.url)  # stays "queued"

    count, _snapshot = manager.clear_history_group(None, None)

    assert count == 0
    assert manager.progress()[0].state == "queued"
    assert manager.progress()[0].history_cleared is False


# ── the connection-gate summary (section header) ───────────────────────────

def test_connection_gate_lines_names_the_blocked_provider(env, server):
    from metatv.core.database import ProviderDB

    manager, db, _config, accountant = env
    with db.session_scope() as session:
        session.add(ProviderDB(id="p1", name="My IPTV", type="xtream", url="http://x"))
    accountant.acquire("p1", "playback", "someone-watching")
    manager.enqueue("ch1", "p1", "Film", server.url)

    assert manager.connection_gate_lines() == [
        "My IPTV · 1 of 1 connections in use"]


def test_connection_gate_lines_is_empty_when_nothing_is_waiting(env, server):
    manager, *_ = env
    manager.enqueue("ch1", "p1", "Film", server.url)  # no one else holds p1

    assert manager.connection_gate_lines() == []


# ── the menu action that starts it ──────────────────────────────────────────

def test_the_download_action_is_registered_and_vod_only():
    """A live channel has no end to download TO — recording it is a different
    feature with a different priority rule."""
    from types import SimpleNamespace

    from metatv.gui.channel_menu import ACTIONS, SURFACE_LAYOUTS

    action = ACTIONS["download"]
    assert "download" in SURFACE_LAYOUTS["channel"], "registered but never shown"

    def ctx(media_type):
        return SimpleNamespace(is_single=True, channel_found=True, media_type=media_type)

    assert action.applies(ctx("movie")) is True
    assert action.applies(ctx("series")) is True
    assert action.applies(ctx("live")) is False


def test_the_download_action_has_a_handler():
    """A menu entry with no handler is a dead click.

    Read out of main_window_channels' handler map by source, because building a
    MainWindow to check one dict key is a subprocess for a string.
    """
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "metatv" / "gui" / "main_window_channels.py").read_text()
    assert '"download": lambda: self.download_channel_by_id(cid),' in source


def test_the_download_icon_resolves(qapp):
    """Verified with a QApplication present.

    Without one qtawesome answers for a font it has not loaded and reports
    icons that do not exist — which is how ``mdi6.judo`` got written down.
    """
    import qtawesome

    from metatv.gui.icons import VECTOR_KEYS

    qtawesome.icon(VECTOR_KEYS["download"])
