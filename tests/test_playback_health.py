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
        self.tooltip = None

    def setText(self, t):
        self.text = t

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def setToolTip(self, t):
        self.tooltip = t


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
    def __init__(self, running=True, keys=None, last_key=None, providers=None):
        from types import SimpleNamespace

        self._running = running
        self._keys = keys if keys is not None else []
        # Real MPVPlayer exposes ._last_key; the readout reaches through to it.
        self.player = SimpleNamespace(_last_key=last_key)
        self._providers = providers or {}  # instance key → provider_id

    def is_running(self, key=None):
        return self._running

    def last_exit_reason(self, key=None):
        return None

    def active_keys(self):
        return list(self._keys)

    def provider_for_key(self, key=None):
        if key is None:
            return None
        return self._providers.get(key)


# ---------------------------------------------------------------------------
# 3. _on_playback_health_ready — main-thread result slot
#
# The slot now receives a ``(key, props)`` tuple instead of bare props.
# ---------------------------------------------------------------------------

def _host_for_result(keys=None, last_key=None, providers=None, icons=None):
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_timer = _FakeTimer()
    host._health_query_inflight = True
    host._health_idle_ticks = 0
    host._provider_icons = icons or {}
    host.player_manager = _FakePlayerManager(
        running=True, keys=keys or [], last_key=last_key, providers=providers
    )
    return host


def test_on_playback_health_ready_playing_sets_text_and_shows():
    host = _host_for_result(keys=["__shared__"])
    props = {
        "path": "http://stream/url",
        "demuxer-cache-duration": 18.4,
        "cache-speed": 775000,
        "frame-drop-count": 0,
    }
    MainWindow._on_playback_health_ready(host, (None, props))

    assert host._playback_health_label.visible is True
    assert "18s buffer" in host._playback_health_label.text
    assert "6.2 Mbps" in host._playback_health_label.text
    assert "0 drops" in host._playback_health_label.text
    assert host._health_idle_ticks == 0
    assert host._health_query_inflight is False
    assert host._playback_health_timer.stopped is False


def test_on_playback_health_ready_idle_hides_and_counts():
    host = _host_for_result()
    MainWindow._on_playback_health_ready(host, (None, {"path": None}))

    assert host._playback_health_label.visible is False
    assert host._health_idle_ticks == 1
    assert host._health_query_inflight is False
    assert host._playback_health_timer.stopped is False  # not yet at grace


def test_on_playback_health_ready_idle_grace_stops_timer():
    host = _host_for_result()
    host._health_idle_ticks = 7  # next idle tick reaches the grace threshold (8)
    MainWindow._on_playback_health_ready(host, (None, {"path": None}))

    assert host._health_idle_ticks == 8
    assert host._playback_health_timer.stopped is True


def test_on_playback_health_ready_none_treated_as_idle():
    host = _host_for_result()
    MainWindow._on_playback_health_ready(host, (None, None))  # probe failure → idle, no crash

    assert host._playback_health_label.visible is False
    assert host._health_idle_ticks == 1
    assert host._health_query_inflight is False


_PLAYING = {
    "path": "http://stream/url",
    "demuxer-cache-duration": 18.4,
    "cache-speed": 775000,
    "frame-drop-count": 0,
}


def test_on_playback_health_ready_single_prefixes_source_icon():
    """One window: the readout leads with the source glyph (which stream), no [i/n]."""
    host = _host_for_result(
        keys=["__shared__"],
        last_key="__shared__",
        providers={"__shared__": "p1"},
        icons={"p1": "🔵"},
    )
    MainWindow._on_playback_health_ready(host, ("__shared__", _PLAYING))

    text = host._playback_health_label.text
    assert text.startswith("🔵 ")          # source glyph leads
    assert "[" not in text                 # no position marker for a single window
    assert "18s buffer" in text


def test_on_playback_health_ready_multi_shows_index_and_source_icon():
    """Two windows: [i/n] count/position AND the per-stream source glyph."""
    host = _host_for_result(
        keys=["p1", "p2"],
        providers={"p1": "p1", "p2": "p2"},  # split on → key IS provider_id
        icons={"p1": "🔵", "p2": "🔴"},
    )
    MainWindow._on_playback_health_ready(host, ("p2", _PLAYING))

    text = host._playback_health_label.text
    assert text.startswith("[2/2] 🔴 ")     # position + the glyph for THIS stream
    assert "18s buffer" in text
    assert "cycle between 2" in host._playback_health_label.tooltip


def test_on_playback_health_ready_unknown_source_omits_glyph():
    """No cached glyph for the source → readout is still well-formed (no leading space)."""
    host = _host_for_result(keys=["__shared__"], last_key="__shared__")
    MainWindow._on_playback_health_ready(host, ("__shared__", _PLAYING))

    assert host._playback_health_label.text.startswith(_icons.play_icon)


# ---------------------------------------------------------------------------
# 4. _playback_health_tick — main-thread tick
# ---------------------------------------------------------------------------

def test_tick_process_gone_hides_and_stops_no_submit():
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_label.visible = True
    host._playback_health_timer = _FakeTimer()
    host.executor = _FakeExecutor()
    host.player_manager = _FakePlayerManager(running=False, keys=[])
    host._health_query_inflight = False
    host._health_view_key = None

    MainWindow._playback_health_tick(host)

    assert host._playback_health_label.visible is False
    assert host._playback_health_timer.stopped is True
    assert host.executor.submits == []  # no probe submitted


def test_tick_running_submits_once_and_sets_inflight():
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_timer = _FakeTimer()
    host.executor = _FakeExecutor()
    host.player_manager = _FakePlayerManager(running=True, keys=["__shared__"])
    host._health_query_inflight = False
    host._health_view_key = None

    MainWindow._playback_health_tick(host)

    assert host._health_query_inflight is True
    assert len(host.executor.submits) == 1
    assert host.executor.submits[0][0] == host._bg_query_playback_health


def test_tick_skips_when_already_inflight():
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_timer = _FakeTimer()
    host.executor = _FakeExecutor()
    host.player_manager = _FakePlayerManager(running=True, keys=["__shared__"])
    host._health_query_inflight = True  # a probe is already running
    host._health_view_key = None

    MainWindow._playback_health_tick(host)

    assert host.executor.submits == []  # did not pile up


def test_tick_closing_one_window_keeps_readout_on_survivor():
    """Regression: closing the most-recent window must not blank the readout.

    Two windows were open (p1, p2); the user closes p2 — the most-recently-used
    one — so active_keys() drops to [p1] but the player's stale _last_key still
    points at the dead p2. The tick must keep polling (not hide/stop) and probe a
    *live* key (p1), not None/p2 which would resolve to the dead window and read
    as idle.
    """
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_label.visible = True
    host._playback_health_timer = _FakeTimer()
    host.executor = _FakeExecutor()
    host.player_manager = _FakePlayerManager(
        running=True, keys=["p1"], last_key="p2"  # p2 closed; _last_key stale
    )
    host._health_query_inflight = False
    host._health_view_key = None

    MainWindow._playback_health_tick(host)

    assert host._playback_health_label.visible is True   # not blanked
    assert host._playback_health_timer.stopped is False  # still polling
    assert len(host.executor.submits) == 1
    assert host.executor.submits[0][1] == ("p1",)        # probes the LIVE key


def test_resolve_health_key_falls_back_to_live_key_when_pin_dead():
    """A pinned view whose window closed falls back to a live key, never returns dead."""
    host = MainWindow.__new__(MainWindow)
    host.player_manager = _FakePlayerManager(keys=["p1"], last_key="p2")
    host._health_view_key = "p2"  # was pinned to the now-closed window
    assert MainWindow._resolve_health_key(host, ["p1"]) == "p1"


# ---------------------------------------------------------------------------
# 5. _start_playback_health resets the readout view-key (stale-pin regression)
# ---------------------------------------------------------------------------

def test_start_playback_health_resets_view_key():
    """A new play follows the latest window: _health_view_key resets to None.

    Regression: clicking the readout to cycle pins _health_view_key to a window;
    it was never reset, so after that window went idle / the user played
    elsewhere the readout kept polling the stale instance and showed nothing.
    """
    host = MainWindow.__new__(MainWindow)
    host._playback_health_timer = _FakeTimer()      # already active → no start()
    host._health_query_inflight = False
    host._health_view_key = "stale-provider-key"     # pinned by a prior readout click
    host._start_playback_health()
    assert host._health_view_key is None, (
        "_start_playback_health must reset the pinned view-key so a new play "
        "follows the most-recently-used window"
    )


# ---------------------------------------------------------------------------
# Wiring test: on_loaded_tick is called on every loaded probe
# ---------------------------------------------------------------------------

def test_on_playback_health_ready_calls_on_loaded_tick():
    """A loaded probe with path and time-pos calls on_loaded_tick with the values."""
    import unittest.mock as mock
    from metatv.gui import playback_start_watch

    # Monkeypatch on_loaded_tick in its defining module
    with mock.patch.object(playback_start_watch, 'on_loaded_tick') as mock_tick:
        host = _host_for_result(keys=["__shared__"])
        props = {
            "path": "http://stream/url",
            "demuxer-cache-duration": 18.4,
            "cache-speed": 775000,
            "frame-drop-count": 0,
            "time-pos": 42.0,
            "pause": False,
        }
        MainWindow._on_playback_health_ready(host, (None, props))

        # Verify on_loaded_tick was called with the host, time-pos, and pause flag
        mock_tick.assert_called_once()
        call_args = mock_tick.call_args
        assert call_args[0][0] is host  # first arg is host
        assert call_args[0][1] == 42.0  # time-pos
        assert call_args[0][2] is False  # pause


# ── 2026-09-06: an mpv that exited while opening is retried once ────────────

from unittest.mock import MagicMock, patch  # noqa: E402 — local to this section
from tests.conftest import wire_status_method

class _FakePlayerManagerWithExit(_FakePlayerManager):
    def __init__(self, reason, **kw):
        super().__init__(**kw)
        self._reason = reason

    def last_exit_reason(self, key=None):
        return self._reason


def _gone_host(reason, *, retry_attempt=False, progressed=False):
    from metatv.gui import playback_start_watch as watch
    host = MainWindow.__new__(MainWindow)
    host._playback_health_label = _FakeLabel()
    host._playback_health_timer = _FakeTimer()
    host.executor = _FakeExecutor()
    host.player_manager = _FakePlayerManagerWithExit(reason, running=False, keys=[])
    host._health_query_inflight = False
    host._health_view_key = None
    host.status_bar = MagicMock()
    wire_status_method(host)
    host.notification_manager = MagicMock()
    host.stream_retry_manager = MagicMock()
    watch.arm(host, watch.PlayAttempt("ch-1", "Title", "http://x/1.mkv", retry=retry_attempt))
    watch.on_playing(host)
    if progressed:
        # PLAY-17: real video arrived, then the source dropped it far short
        # of its own known duration.
        watch.on_loaded_tick(host, 0.0, False, duration=5400)
        watch.on_loaded_tick(host, 300.0, False, duration=5400)
    else:
        watch.on_loaded_tick(host, None, False, cache_duration=None)   # loaded, OPENING
    return host


def test_tick_schedules_one_retry_when_the_stream_ended_the_player():
    host = _gone_host("End of file")
    with patch("metatv.gui.playback_start_watch.QTimer.singleShot") as shot:
        MainWindow._playback_health_tick(host)
    shot.assert_called_once()
    delay, _cb = shot.call_args[0]
    assert delay >= 10_000, "the retry must wait out the source's connection lag"
    host.status_bar.showMessage.assert_called()
    assert "retrying" in host.status_bar.showMessage.call_args[0][0]


def test_tick_does_not_retry_a_retry():
    host = _gone_host("End of file", retry_attempt=True)
    with patch("metatv.gui.playback_start_watch.QTimer.singleShot") as shot:
        MainWindow._playback_health_tick(host)
    shot.assert_not_called()
    host.notification_manager.show.assert_called_once()   # still reported


def test_tick_does_not_retry_a_user_close():
    host = _gone_host("Quit")
    with patch("metatv.gui.playback_start_watch.QTimer.singleShot") as shot:
        MainWindow._playback_health_tick(host)
    shot.assert_not_called()
    host.notification_manager.show.assert_not_called()


# ── PLAY-17: a mid-play drop resumes instead of falling into the never- ─────
# started retry — same tick, different verdict, once progress is on record.

def test_tick_resumes_a_mid_play_drop_instead_of_the_never_started_retry():
    host = _gone_host("End of file", progressed=True)
    with patch("metatv.gui.playback_start_watch.QTimer.singleShot") as shot:
        MainWindow._playback_health_tick(host)
    shot.assert_called_once()
    never_started = [
        c for c in host.notification_manager.show.call_args_list
        if c.kwargs.get("title") == "Stream did not start"
    ]
    assert not never_started, "the drop must not also read as a never-started play"
