"""Behavioral tests for the live playback-health indicator (feat/playback-health).

Covers the four halves that actually regress:

1. ``format_playback_health`` — the pure nav-bar string builder (units, placeholders,
   well-formedness with None inputs, leading play glyph).
2. ``MPVPlayer.get_property`` — event-line skipping, request_id matching, error/None
   handling, and never-raises on a socket exception (fake unix socket).
3. ``MainWindow._on_playback_health_ready`` — the main-thread result slot: playing →
   label text + show + counters reset; idle → hide + idle-tick increment + grace stop;
   None probe → treated as idle, no crash.
4. ``MainWindow._playback_health_tick`` — the main-thread tick: process gone → hide +
   stop, no submit; running + not in-flight → one executor submit + in-flight set.

The worker half (``_bg_query_playback_health``) is a try/except around a manager call;
the slots above are where the behavior lives, so those are executed directly via
``MainWindow.__new__`` with only the attributes each method touches.
"""
from __future__ import annotations

import json
import socket

import pytest

from metatv.gui import icons as _icons
from metatv.gui.main_window import MainWindow
from metatv.gui.main_window_streaming import format_playback_health


# ---------------------------------------------------------------------------
# 1. format_playback_health — pure formatter
# ---------------------------------------------------------------------------

def test_format_playback_health_full():
    # 775000 bytes/sec * 8 / 1e6 = 6.2 Mbps
    s = format_playback_health(18.4, 775000, 0)
    assert "18s buffer" in s        # int(round(18.4)) == 18
    assert "6.2 Mbps" in s
    assert "0 drops" in s
    assert s.startswith(_icons.play_icon)
    assert " · " in s


def test_format_playback_health_rounds_buffer_and_speed():
    s = format_playback_health(17.6, 1_000_000, 12)
    assert "18s buffer" in s        # rounds up
    assert "8.0 Mbps" in s          # 1e6 * 8 / 1e6 == 8.0
    assert "12 drops" in s


def test_format_playback_health_all_none_is_well_formed():
    s = format_playback_health(None, None, None)
    assert "—" in s                 # placeholders present, no crash
    assert "buffer" in s and "Mbps" in s and "drops" in s
    assert s.startswith(_icons.play_icon)
    # Still a single well-formed " · "-joined line.
    assert s.count(" · ") == 2


# ---------------------------------------------------------------------------
# 2. MPVPlayer.get_property — IPC reply parsing
# ---------------------------------------------------------------------------

class _FakeSocket:
    """Stand-in for a unix socket: records sent bytes, replays canned recv chunks.

    ``recv_for`` is a callable that, given the request_id the player sent, returns
    the bytes to deliver (so the reply can echo whatever id was used). The chunks
    are returned one recv() at a time, then b"" (closed) to end the read loop.
    """

    def __init__(self, recv_for):
        self._recv_for = recv_for
        self._chunks: list[bytes] = []
        self._idx = 0
        self.closed = False

    def settimeout(self, t):
        pass

    def connect(self, path):
        pass

    def sendall(self, data):
        # Parse the command we were sent to learn the request_id, then build the
        # canned reply stream from it.
        msg = json.loads(data.decode("utf-8").strip())
        rid = msg.get("request_id")
        self._chunks = list(self._recv_for(rid))

    def recv(self, n):
        if self._idx >= len(self._chunks):
            return b""  # socket closed — ends the read loop
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk

    def close(self):
        self.closed = True


def _make_player():
    from types import SimpleNamespace
    from metatv.core.players.mpv import MPVPlayer

    cfg = SimpleNamespace(
        mpv_socket_path="/tmp/does-not-matter.sock",
        player_mode="single-instance",
    )
    return MPVPlayer(cfg)


def test_get_property_skips_event_line_and_matches_request_id(monkeypatch):
    player = _make_player()

    def recv_for(rid):
        # An async event line (no request_id) precedes the matching reply.
        return [
            b'{"event":"playback-restart"}\n'
            b'{"data":18.4,"request_id":' + str(rid).encode() + b',"error":"success"}\n'
        ]

    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: _FakeSocket(recv_for)
    )
    assert player.get_property("demuxer-cache-duration") == 18.4


def test_get_property_skips_nonmatching_request_id(monkeypatch):
    player = _make_player()

    def recv_for(rid):
        # First a reply to a *different* request, then ours.
        return [
            b'{"data":"stale","request_id":1,"error":"success"}\n'
            b'{"data":42,"request_id":' + str(rid).encode() + b',"error":"success"}\n'
        ]

    monkeypatch.setattr(socket, "socket", lambda *a, **k: _FakeSocket(recv_for))
    assert player.get_property("frame-drop-count") == 42


def test_get_property_error_reply_returns_none(monkeypatch):
    player = _make_player()

    def recv_for(rid):
        return [
            b'{"request_id":' + str(rid).encode()
            + b',"error":"property unavailable"}\n'
        ]

    monkeypatch.setattr(socket, "socket", lambda *a, **k: _FakeSocket(recv_for))
    assert player.get_property("cache-speed") is None


def test_get_property_socket_exception_returns_none(monkeypatch):
    player = _make_player()

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(socket, "socket", boom)
    assert player.get_property("path") is None  # never raises


def test_get_properties_maps_each_name(monkeypatch):
    player = _make_player()

    def recv_for(rid):
        return [
            b'{"data":7,"request_id":' + str(rid).encode() + b',"error":"success"}\n'
        ]

    monkeypatch.setattr(socket, "socket", lambda *a, **k: _FakeSocket(recv_for))
    out = player.get_properties(["a", "b"])
    assert out == {"a": 7, "b": 7}


# ---------------------------------------------------------------------------
# Fakes for MainWindow main-thread slot tests
# ---------------------------------------------------------------------------

class _FakeLabel:
    def __init__(self):
        self.text = None
        self.visible = False

    def setText(self, t):
        self.text = t

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class _FakeTimer:
    def __init__(self):
        self.stopped = False
        self._active = True

    def stop(self):
        self.stopped = True
        self._active = False

    def isActive(self):
        return self._active


class _FakeExecutor:
    def __init__(self):
        self.submits = []

    def submit(self, fn, *args):
        self.submits.append((fn, args))


class _FakePlayerManager:
    def __init__(self, running=True):
        self._running = running

    def is_running(self):
        return self._running


# ---------------------------------------------------------------------------
# 3. _on_playback_health_ready — main-thread result slot
# ---------------------------------------------------------------------------

def _host_for_result():
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_timer = _FakeTimer()
    host._health_query_inflight = True
    host._health_idle_ticks = 0
    return host


def test_on_playback_health_ready_playing_sets_text_and_shows():
    host = _host_for_result()
    props = {
        "path": "http://stream/url",
        "demuxer-cache-duration": 18.4,
        "cache-speed": 775000,
        "frame-drop-count": 0,
    }
    MainWindow._on_playback_health_ready(host, props)

    assert host._playback_health_label.visible is True
    assert "18s buffer" in host._playback_health_label.text
    assert "6.2 Mbps" in host._playback_health_label.text
    assert "0 drops" in host._playback_health_label.text
    assert host._health_idle_ticks == 0
    assert host._health_query_inflight is False
    assert host._playback_health_timer.stopped is False


def test_on_playback_health_ready_idle_hides_and_counts():
    host = _host_for_result()
    MainWindow._on_playback_health_ready(host, {"path": None})

    assert host._playback_health_label.visible is False
    assert host._health_idle_ticks == 1
    assert host._health_query_inflight is False
    assert host._playback_health_timer.stopped is False  # not yet at grace


def test_on_playback_health_ready_idle_grace_stops_timer():
    host = _host_for_result()
    host._health_idle_ticks = 7  # next idle tick reaches the grace threshold (8)
    MainWindow._on_playback_health_ready(host, {"path": None})

    assert host._health_idle_ticks == 8
    assert host._playback_health_timer.stopped is True


def test_on_playback_health_ready_none_treated_as_idle():
    host = _host_for_result()
    MainWindow._on_playback_health_ready(host, None)  # probe failure → idle, no crash

    assert host._playback_health_label.visible is False
    assert host._health_idle_ticks == 1
    assert host._health_query_inflight is False


# ---------------------------------------------------------------------------
# 4. _playback_health_tick — main-thread tick
# ---------------------------------------------------------------------------

def test_tick_process_gone_hides_and_stops_no_submit():
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_label.visible = True
    host._playback_health_timer = _FakeTimer()
    host.executor = _FakeExecutor()
    host.player_manager = _FakePlayerManager(running=False)
    host._health_query_inflight = False

    MainWindow._playback_health_tick(host)

    assert host._playback_health_label.visible is False
    assert host._playback_health_timer.stopped is True
    assert host.executor.submits == []  # no probe submitted


def test_tick_running_submits_once_and_sets_inflight():
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_timer = _FakeTimer()
    host.executor = _FakeExecutor()
    host.player_manager = _FakePlayerManager(running=True)
    host._health_query_inflight = False

    MainWindow._playback_health_tick(host)

    assert host._health_query_inflight is True
    assert len(host.executor.submits) == 1
    assert host.executor.submits[0][0] == host._bg_query_playback_health


def test_tick_skips_when_already_inflight():
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_timer = _FakeTimer()
    host.executor = _FakeExecutor()
    host.player_manager = _FakePlayerManager(running=True)
    host._health_query_inflight = True  # a probe is already running

    MainWindow._playback_health_tick(host)

    assert host.executor.submits == []  # did not pile up
