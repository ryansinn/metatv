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
    """Shrink the quiet/cap/floor windows to ms for a fast, deterministic suite."""
    monkeypatch.setattr(rc, "QUIET_MS", 60)
    monkeypatch.setattr(rc, "MAX_LATENCY_MS", 300)
    # MIN_INTERVAL_MS is bound from QUIET_MS at import, so shrinking QUIET_MS
    # alone would leave the floor at its real 60s and hold every settle here.
    monkeypatch.setattr(rc, "MIN_INTERVAL_MS", 60)


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


# ---------------------------------------------------------------------------
# The settle floor — owner log 2026-09-09 17:31-17:32, "the discover just keeps
# reloading and refreshing". on_settled fired outright, bypassing both timers,
# and enrichment_settled is emitted at the end of EVERY drain — in the same
# finally block that emits the collapses_found which had just armed the quiet
# window. Measured cadence was 42s between full cascades, which a 60s quiet
# timer cannot produce.
# ---------------------------------------------------------------------------

def _fixed_clock(coalescer):
    """Drive the coalescer's monotonic clock by hand. Returns an advance()."""
    state = {"ms": 1_000_000.0}
    coalescer._now_ms = lambda: state["ms"]

    def advance(ms):
        state["ms"] += ms
    return advance


def test_back_to_back_settles_do_not_out_pace_the_quiet_policy(qtbot, _shrunk_timers):
    """THE reported bug: a settle per drain must not refresh faster than QUIET_MS.

    Reproduces the drain cadence from the owner's log — collapse then settle,
    twice, with less than the floor between them. Against the pre-fix code this
    fires TWICE (once per drain); it must fire once.
    """
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))
    advance = _fixed_clock(coalescer)

    # Drain 1: propagation arms the window, the same finally block settles.
    coalescer.on_collapse(1)
    coalescer.on_settled()
    assert calls == [None], "the first settle of a session should still be prompt"

    # Drain 2 arriving at 0.7x the floor — in production that is the 42s
    # cadence measured in the log against the real 60s floor. Expressed as a
    # fraction so the test tracks the constant instead of a wall-clock number
    # the fixture has shrunk out from under it.
    advance(rc.MIN_INTERVAL_MS * 0.7)
    coalescer.on_collapse(1)
    coalescer.on_settled()

    assert calls == [None], (
        "a second drain 42s after the last refresh re-ran the whole cascade — "
        "the settle path is out-pacing the quiet window it is supposed to honour"
    )


def test_a_held_settle_still_lands_when_the_floor_expires(qtbot, _shrunk_timers):
    """Held, never dropped: the refresh is delayed to the floor, not discarded."""
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))
    advance = _fixed_clock(coalescer)

    coalescer.on_collapse(1)
    coalescer.on_settled()
    assert calls == [None]

    # A settle 10ms into a 60ms floor: held now...
    advance(10)
    coalescer.on_collapse(1)
    coalescer.on_settled()
    assert calls == [None]

    # ...and lands on its own once the floor has passed.
    qtbot.waitUntil(lambda: len(calls) == 2, timeout=1000)


def test_the_first_settle_after_a_long_quiet_is_still_immediate(qtbot, _shrunk_timers):
    """The behaviour on_settled exists for is preserved once the floor is clear."""
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))
    advance = _fixed_clock(coalescer)

    coalescer.on_collapse(1)
    coalescer.on_settled()
    assert calls == [None]

    # Well past the floor — no holding, no waiting on a timer.
    advance(rc.MIN_INTERVAL_MS * 3)
    coalescer.on_collapse(1)
    coalescer.on_settled()

    assert calls == [None, None]


def test_repeated_settles_inside_the_floor_land_exactly_once(qtbot, _shrunk_timers):
    """Five settles inside one floor window collapse to a single delayed refresh."""
    calls: list = []
    host = _host()
    coalescer = rc.RefreshCoalescer(host, lambda: calls.append(None))
    advance = _fixed_clock(coalescer)

    coalescer.on_collapse(1)
    coalescer.on_settled()
    assert calls == [None]

    for _ in range(5):
        advance(5)
        coalescer.on_collapse(1)
        coalescer.on_settled()
    assert calls == [None], "no settle inside the floor may fire"

    qtbot.waitUntil(lambda: len(calls) == 2, timeout=1000)
    qtbot.wait(rc.QUIET_MS + 50)
    assert len(calls) == 2, "the held settle must land once, not once per settle"
