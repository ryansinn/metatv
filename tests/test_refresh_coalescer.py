"""Behavioral tests for RefreshCoalescer (REC-LAG).

Guards the fix for owner log 2026-09-03 04:39-04:43: main_window.py wired
TmdbEnrichmentManager.collapses_found DIRECTLY to
MainWindow._refresh_provider_dependent_views, so a 40-title enrichment batch
every ~5s ran the full canonical refresh cascade in a five-second loop for the
whole run (107 stalls, worst 8,738ms). RefreshCoalescer sits at that one
connection and debounces bursts to a single refresh at quiet, cap, or drain.

Timer durations are the module constants QUIET_MS / MAX_LATENCY_MS, shrunk
here via monkeypatch so the suite runs in milliseconds — RefreshCoalescer
reads them by name at call time (never captures them at construction), so
shrinking before constructing the coalescer is enough.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QObject

from metatv.gui import refresh_coalescer as rc


@pytest.fixture()
def _shrunk_timers(monkeypatch):
    """Shrink the quiet/cap windows to milliseconds for a fast, deterministic suite."""
    monkeypatch.setattr(rc, "QUIET_MS", 60)
    monkeypatch.setattr(rc, "MAX_LATENCY_MS", 300)


def _host() -> QObject:
    """A bare QObject standing in for MainWindow — just needs _register_cleanable.

    Qt parents own their children at the C++ level: a ``QTimer(self)`` dies the
    moment ``self``'s parent (``host``) is garbage-collected. Every test below
    keeps its own ``host`` alive as a local variable for exactly this reason —
    dropping it (e.g. passing ``_host()`` inline) reproduces "wrapped C/C++
    object of type QTimer has been deleted" on the very next timer call.
    """
    host = QObject()
    host._register_cleanable = lambda name, fn: None
    return host


def test_burst_coalesces_to_one_refresh_after_quiet(qtbot, _shrunk_timers):
    """10 collapses in quick succession over a simulated burst → ONE refresh, after quiet."""
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))

    for _ in range(10):
        coalescer.on_collapse(1)
        qtbot.wait(5)  # well inside the shrunk quiet window — keeps restarting it

    assert calls == [], "must not refresh mid-burst"

    qtbot.wait(rc.QUIET_MS + 50)  # let the burst go quiet

    assert calls == [None]


def test_continuous_collapses_hit_the_max_latency_cap_then_restart(qtbot, _shrunk_timers):
    """Collapses that never go quiet still refresh once, at the cap — then the cycle restarts."""
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))

    step_ms = rc.QUIET_MS // 2  # always inside the quiet window — never fires from quiet
    deadline_ms = rc.MAX_LATENCY_MS + 200
    elapsed = 0
    while elapsed < deadline_ms and not calls:
        coalescer.on_collapse(1)
        qtbot.wait(step_ms)
        elapsed += step_ms

    assert calls == [None], "must fire exactly once, at the cap"

    # The cycle restarts: a fresh collapse arms a new pending cycle from scratch.
    coalescer.on_collapse(1)
    qtbot.wait(rc.QUIET_MS + 50)

    assert calls == [None, None]


def test_settled_flushes_pending_immediately_and_clears_timers(qtbot, _shrunk_timers):
    """enrichment_settled with a pending collapse refreshes NOW, no wait for quiet."""
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))

    coalescer.on_collapse(1)
    assert calls == []  # not yet — still inside the quiet window

    coalescer.on_settled()
    assert calls == [None]  # immediate — no processEvents/wait needed

    # Both timers were stopped by the flush: waiting past the (shrunk) quiet
    # window must not produce a second, redundant refresh.
    qtbot.wait(rc.QUIET_MS + 50)
    assert calls == [None]


def test_settled_with_nothing_pending_does_not_refresh(qtbot, _shrunk_timers):
    """enrichment_settled with NOTHING pending (a drain that resolved nothing) is a no-op."""
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))

    coalescer.on_settled()

    assert calls == []


def test_stop_cancels_a_pending_refresh_without_firing(qtbot, _shrunk_timers):
    """The cleanup-registry hook (stop()) cancels outstanding timers silently."""
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))

    coalescer.on_collapse(1)
    coalescer.stop()

    qtbot.wait(rc.QUIET_MS + 50)

    assert calls == []


def test_constructor_registers_its_own_cleanup():
    """RefreshCoalescer self-registers stop() via the host's cleanup registry."""
    registered: list = []
    host = QObject()
    host._register_cleanable = lambda name, fn: registered.append((name, fn))

    coalescer = rc.RefreshCoalescer(host, lambda: None)

    assert len(registered) == 1
    name, fn = registered[0]
    assert name == "enrichment_refresh_coalescer"
    assert fn == coalescer.stop
