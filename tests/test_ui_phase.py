"""A stall report has to name what was running, or it is only a timestamp.

``MainThreadWatchdog`` reports AFTER the block clears, and its own message said
so: *"whatever ran just before this line blocked the event loop"*. Every PERF
item in this project has therefore been attributed by reading gaps between
unrelated log lines and then arguing about them — and the last hypothesis
argued instead of measured was **wrong**: ``set_flat_items`` building one widget
per filter value was the leading suspect for a 1,349 ms stall, and building all
148 of the owner's values costs **35 ms** (0.24 ms per row, measured
2026-09-02). Virtualizing the filter panel would have been a large change
buying 2.6% of that stall.

A phase is a named span of main-thread work; the watchdog reports whichever was
open. These tests pin the three properties that make the report trustworthy:
the INNERMOST phase is named (the most specific true answer), a phase never
outlives its span (or it is blamed for everything after it), and the watchdog
still says something useful when no phase is open.
"""

from __future__ import annotations

import pathlib

import pytest

from metatv.gui import ui_phase as phase


@pytest.fixture(autouse=True)
def _clean():
    phase.reset()
    yield
    phase.reset()


# ── what is open ─────────────────────────────────────────────────────────────

def test_nothing_open_by_default():
    assert phase.current() is None
    assert phase.describe() == ""


def test_a_phase_is_open_only_inside_its_span():
    with phase.phase("load"):
        assert phase.current() == "load"
    assert phase.current() is None


def test_the_innermost_phase_is_the_one_reported():
    """The most specific TRUE answer. An outer "startup" tells you nothing a
    timestamp did not."""
    with phase.phase("startup"):
        with phase.phase("startup.filters"):
            assert phase.current() == "startup.filters"
        assert phase.current() == "startup"


def test_a_raise_still_closes_the_phase():
    """A phase left open by an exception is blamed for everything that follows
    it — worse than no attribution at all, because it reads as a measurement."""
    with pytest.raises(ValueError):
        with phase.phase("boom"):
            raise ValueError("x")
    assert phase.current() is None


def test_the_decorator_opens_and_closes_the_same_span():
    @phase.timed("decorated")
    def work():
        return phase.current()

    assert work() == "decorated"
    assert phase.current() is None


def test_the_decorator_keeps_the_function_it_wraps():
    @phase.timed("named")
    def documented(a, b=2):
        """Doc survives."""
        return a + b

    assert documented(1) == 3
    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Doc survives."


# ── what the watchdog prints ─────────────────────────────────────────────────

def test_describe_names_the_phase_and_how_long_it_has_been_open():
    """Both halves matter: a phase open 3 ms when a 2,000 ms stall is reported
    is a bystander, not the cause."""
    with phase.phase("filter-stats.applied"):
        text = phase.describe()
    assert "filter-stats.applied" in text
    assert "open" in text and "ms" in text


def test_describe_is_empty_when_nothing_is_open():
    """So the watchdog can fall back to its old wording rather than printing a
    confident blank."""
    assert phase.describe() == ""


def test_reset_drops_everything():
    with phase.phase("outer"):
        phase.reset()
        assert phase.current() is None


# ── the wiring ───────────────────────────────────────────────────────────────

def _src(rel: str) -> str:
    return (pathlib.Path(__file__).resolve().parent.parent / rel).read_text()


def test_the_watchdog_reports_the_phase():
    src = _src("metatv/gui/main_thread_watchdog.py")
    assert "_phase.describe()" in src, (
        "the stall report no longer names the phase — it is a timestamp again")


def test_the_watchdog_still_says_something_with_no_phase_open():
    """An empty describe() must not leave a dangling sentence."""
    src = _src("metatv/gui/main_thread_watchdog.py")
    assert "no phase open" in src


@pytest.mark.parametrize("rel,marker", [
    ("metatv/__main__.py", 'startup.MainWindow'),
    ("metatv/__main__.py", 'startup.show'),
    ("metatv/gui/main_window_channels.py", 'filter-stats.applied'),
])
def test_the_startup_suspects_are_instrumented(rel, marker):
    """The three spans the worklog names as unmeasured: window construction,
    the first show/paint, and applying the filter counts."""
    assert marker in _src(rel), f"{marker} is no longer a phase"
