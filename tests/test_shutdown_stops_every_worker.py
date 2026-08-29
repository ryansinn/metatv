"""Closing the app must stop every view's loader, not four of them.

The owner, on 2026-08-29::

    fish: Job 1, './run.sh' terminated by signal SIGSEGV

and in the log a few minutes earlier, the same fault caught in Python rather
than in C++::

    ERROR | discover_workers:run:546 - DiscoverView loader error
    RuntimeError: wrapped C/C++ object of type _LoaderWorker has been deleted

A QObject destroyed while its worker is still inside ``run()`` is a RuntimeError
if Python happens to be on the stack and a SIGSEGV if it is not. Same fault,
two faces.

Two causes in ``closeEvent``:

1. It deactivated a **hand-written tuple of four** view names. Twelve views
   define ``on_deactivate``, so eight were never stopped.
2. It required ``isVisible()`` — backwards. A view that is not on screen but
   still has a loader running is exactly the one that needs stopping.

And it called ``executor.shutdown(wait=False)`` immediately before
``db.close()``, so workers could still be mid-query when the engine was
disposed under them. The owner's log shows worker output timestamped *after*
"Database connection closed".

The tests below are derived, not enumerated — which is the whole point, since an
enumeration is what failed.
"""

from __future__ import annotations

import ast
import pathlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
GUI = REPO / "metatv" / "gui"


class _View:
    """A stand-in content view that records whether it was deactivated."""

    def __init__(self, *, visible: bool = False, raises: bool = False) -> None:
        self._visible = visible
        self._raises = raises
        self.deactivated = False

    def isVisible(self) -> bool:  # noqa: N802 - Qt spelling
        return self._visible

    def on_deactivate(self) -> None:
        self.deactivated = True
        if self._raises:
            raise RuntimeError("this view's C++ side is already gone")


class _Host:
    """A plain object carrying the two methods under test.

    Deliberately NOT ``MainWindow.__new__``: on a half-built QObject PyQt
    raises ``RuntimeError`` from ordinary attribute access, which has aborted
    this suite before (see tests/conftest.py's teardown note).
    """

    def __init__(self, **attrs) -> None:
        from metatv.gui.main_window import MainWindow
        self.__dict__.update(attrs)
        self._deactivate_all_views = MainWindow._deactivate_all_views.__get__(self)
        self._await_background_pools = MainWindow._await_background_pools.__get__(self)


# ── the enumeration that failed ─────────────────────────────────────────────

def test_every_view_defining_on_deactivate_is_reachable_from_close():
    """Derived. The old code named four; this counts what actually exists.

    Not an assertion about the number — an assertion that nobody has to
    maintain a number.
    """
    defining = sorted(
        p.name for p in GUI.rglob("*.py")
        if any(
            isinstance(n, ast.FunctionDef) and n.name == "on_deactivate"
            for n in ast.walk(ast.parse(p.read_text()))
        )
    )
    assert len(defining) > 4, (
        "fewer views define on_deactivate than the old hand-written list "
        "assumed; re-read this test's premise"
    )

    src = (GUI / "main_window.py").read_text()
    assert '"discover_view", "preferences_view", "epg_view", "recipe_view"' not in src, (
        f"closeEvent still hand-lists four views while {len(defining)} define "
        "on_deactivate: " + ", ".join(defining)
    )


def test_a_hidden_view_is_still_deactivated():
    """THE assertion. The old gate skipped exactly the dangerous case."""
    hidden = _View(visible=False)
    host = _Host(discover_view=hidden)

    host._deactivate_all_views()

    assert hidden.deactivated, (
        "a hidden view was left running — it is the one whose loader outlives "
        "its widget, which is the SIGSEGV"
    )


def test_all_views_are_deactivated_not_a_chosen_few():
    views = {
        "discover_view": _View(visible=True),
        "epg_view": _View(visible=False),
        "explore_view": _View(visible=False),
        "ppv_view": _View(visible=False),
        "source_analytics_view": _View(visible=False),
    }
    host = _Host(**views)

    host._deactivate_all_views()

    missed = [n for n, v in views.items() if not v.deactivated]
    assert not missed, f"these views were never deactivated: {missed}"


def test_one_failing_view_does_not_strand_the_others():
    """A bad teardown must not take the rest of the shutdown with it."""
    bad = _View(raises=True)
    good = _View()
    host = _Host(discover_view=bad, epg_view=good)

    host._deactivate_all_views()

    assert good.deactivated, "a raising view stopped the next one being asked"


def test_a_non_view_attribute_is_left_alone():
    """The derivation must not call on_deactivate on anything that has one."""
    class _NotAView:
        def __init__(self): self.deactivated = False
        def on_deactivate(self): self.deactivated = True

    manager = _NotAView()
    host = _Host(epg_manager=manager, discover_view=_View())

    host._deactivate_all_views()

    assert not manager.deactivated, (
        "a manager was deactivated as if it were a view; managers are stopped "
        "through the cleanup registry, and doing both would stop them twice"
    )


# ── the pool that outlived the database ─────────────────────────────────────

def test_in_flight_work_finishes_before_close_returns():
    """THE other assertion. The database is closed on the next line."""
    executor = ThreadPoolExecutor(max_workers=2)
    finished = threading.Event()

    def _slow():
        time.sleep(0.3)
        finished.set()

    executor.submit(_slow)
    host = _Host(executor=executor)

    host._await_background_pools()

    assert finished.is_set(), (
        "close returned while a worker was still running — the next statement "
        "disposes the database engine under it"
    )


def test_queued_work_is_cancelled_rather_than_waited_for():
    """What makes the wait short enough to be acceptable.

    Two halves, in the order closeEvent runs them: the cleanup registry calls
    ``shutdown(wait=False, cancel_futures=True)``, then the waiter joins. The
    cancel is what keeps the join bounded by one task rather than a backlog.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    ran = []
    gate = threading.Event()

    executor.submit(lambda: gate.wait(2))
    for i in range(20):
        executor.submit(lambda i=i: ran.append(i))

    host = _Host(executor=executor)
    executor.shutdown(wait=False, cancel_futures=True)   # what the registry does
    gate.set()
    started = time.perf_counter()
    host._await_background_pools()
    elapsed = time.perf_counter() - started

    assert len(ran) < 20, "queued work was executed instead of cancelled"
    assert elapsed < 5, f"close waited {elapsed:.1f}s for work it should have dropped"


def test_the_registered_shutdown_cancels_queued_work():
    """The cancel must be at the registration point, and there only.

    Two call sites shutting the same pool down is two owners for one pool —
    and the existing close-event suite counts the calls, which is how the
    duplicate was caught.
    """
    src = (GUI / "main_window.py").read_text()
    tree = ast.parse(src)

    shutdowns = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "shutdown"
        and isinstance(n.func.value, ast.Attribute)
        and n.func.value.attr == "executor"
    ]
    assert len(shutdowns) == 1, (
        f"the background pool is shut down from {len(shutdowns)} places; it "
        "has one owner"
    )
    kwargs = {kw.arg for kw in shutdowns[0].keywords}
    assert "cancel_futures" in kwargs, (
        "queued work is not cancelled, so the close waits out a whole backlog"
    )


def test_the_budget_exceeds_the_slowest_query_a_worker_runs():
    """A budget written for millisecond queries is a budget that expires.

    The channel-list load with variant collapsing measures ~6 s on the owner's
    library. A 5 s wait would end because it ran out, not because the work
    finished — and then the engine is disposed under a live worker anyway.
    """
    from metatv.gui.main_window import _SHUTDOWN_POOL_WAIT_S

    assert _SHUTDOWN_POOL_WAIT_S > 6.0, (
        "the shutdown budget is below the slowest measured worker query"
    )


def test_no_executor_is_not_an_error():
    """A window torn down before setup completed still has to close."""
    _Host()._await_background_pools()


@pytest.mark.parametrize("name", ["_deactivate_all_views", "_await_background_pools"])
def test_close_event_actually_calls_them(name):
    """Both helpers must be reached from closeEvent, before db.close()."""
    src = (GUI / "main_window.py").read_text()
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "closeEvent"
    )
    called = [
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    ]
    assert name in called, f"closeEvent never calls {name}"
    assert called.index(name) < called.index("close"), (
        f"{name} runs after db.close(), which is the ordering that crashes"
    )
