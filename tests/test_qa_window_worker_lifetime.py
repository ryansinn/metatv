"""Closing the QA checklist window must leave none of its workers running.

A ``QThread`` destroyed while still running is an **abort**, not an exception:
``Abort trap: 6``, exit 134, no Python traceback from the C++ side. That is what
has been failing the macOS release build — **19 of the last 60 release runs** —
and the rolling build is the one the tester downloads::

    File ".../metatv/gui/qa_checklist_window.py", line 605 in run
    File ".../tests/conftest.py", line 295 in _qt_teardown_sweep
    Abort trap: 6

``QAChecklistWindow`` starts three kinds of worker and had **no ``closeEvent``
at all**, so nothing waited for any of them. The git-ref worker makes one
``git log`` subprocess per What's New entry — 402 of them, ~8.6 ms each, ~3.5 s
in total, longer on CI's colder disk — so it comfortably outlives the test that
opened the window.

The harness could not save it: ``conftest._owned_qthreads`` waits out threads
owned by a widget the SAME test leaked, and says so in its own docstring — "a
worker owned only through a nested manager object ... would surface as a loud
abort in testing if it mattered". It mattered. The right place for the fix is
the owner's cleanup path, which is this project's stated rule for background
threads, not a wider sweep in the harness.

These tests assert the invariant on the real window, on any platform: the abort
itself is macOS-flavoured, but "a worker is still running after close" is not.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QThread


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _Config:
    def __init__(self, config_dir: Path) -> None:
        self.qa_verified_id = 0
        self.qa_step_results: dict = {}
        self.qa_archived_ids: list = []
        self.qa_archived_collapsed = True
        self.qa_flagged_items: list = []
        self.qa_flagged_collapsed = False
        self.qa_addressed: dict = {}
        self.config_dir = config_dir

    def save(self) -> None:
        pass


def _entry(eid: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid, version="0.53.0", date="2026-08-28", title=f"Entry {eid}",
        items=("a",), test_steps=("do a thing", "expect a result"),
        addresses=(),
    )


@pytest.fixture()
def window(qapp, tmp_path):
    from metatv.gui.qa_checklist_window import QAChecklistWindow
    # Enough entries that the git worker is still walking them at close — the
    # real condition, not a contrived one.
    entries = [_entry(i) for i in range(1, 60)]
    win = QAChecklistWindow(_Config(tmp_path), entries)  # type: ignore[arg-type]
    yield win
    win.deleteLater()


def _workers(win) -> list[QThread]:
    """Discover the window's worker threads WITHOUT asking the window.

    Deliberately independent of ``_owned_workers``: if this used the production
    helper, the test would fail on the unfixed code with ``AttributeError`` —
    proving only that the method is missing, not that a thread was left running.
    The failure this file exists to catch has to be observable from outside.
    """
    found: list[QThread] = []
    for value in vars(win).values():
        for item in (value if isinstance(value, (list, tuple)) else [value]):
            if isinstance(item, QThread) and item not in found:
                found.append(item)
    return found


def test_no_worker_is_still_running_after_close(window):
    """THE assertion. Pre-fix a worker is mid-``git log`` when close returns."""
    window.close()

    running = [type(t).__name__ for t in _workers(window) if t.isRunning()]
    assert not running, (
        f"{running} still running after close — a QThread destroyed while "
        "running aborts the process (Abort trap: 6, exit 134)"
    )


def test_the_window_finds_workers_it_was_never_told_about(window, qapp):
    """The list of workers is derived, not hand-maintained.

    A hand-written list is exactly what goes stale when a fourth worker is
    added later, which is this project's most-repeated bug shape.
    """
    class _Sleeper(QThread):
        def run(self) -> None:
            while not self.isInterruptionRequested():
                self.msleep(5)

    extra = _Sleeper()
    window._an_attribute_nobody_registered = extra
    extra.start()
    try:
        assert extra in _workers(window), (
            "a worker stored on a new attribute was not discovered; the "
            "lookup is enumerating rather than deriving"
        )
        window.close()
        assert not extra.isRunning(), "close did not stop the undeclared worker"
    finally:
        extra.requestInterruption()
        extra.wait(2000)


def test_a_worker_in_a_list_attribute_is_found(window):
    """``_log_workers`` is a list, and lists are where workers hide."""
    class _Sleeper(QThread):
        def run(self) -> None:
            while not self.isInterruptionRequested():
                self.msleep(5)

    extra = _Sleeper()
    window._log_workers.append(extra)
    extra.start()
    try:
        assert extra in _workers(window)
        window.close()
        assert not extra.isRunning(), "a worker inside a list attribute was missed"
    finally:
        extra.requestInterruption()
        extra.wait(2000)


def test_close_returns_promptly_rather_than_waiting_out_the_whole_scan(window):
    """Interruption, not patience: the git worker checks between entries."""
    import time

    start = time.perf_counter()
    window.close()
    elapsed = time.perf_counter() - start

    assert elapsed < 1.5, (
        f"close took {elapsed:.2f}s — it is waiting out the scan instead of "
        "interrupting it, which would freeze the UI on every close"
    )


def test_the_git_worker_honours_an_interruption_request(qapp, tmp_path):
    """The contract the test harness already depends on, now actually kept.

    ``tests/conftest.py``'s sweep calls ``requestInterruption()`` and then waits
    ``_QTHREAD_WAIT_MS`` (3 s), on the stated assumption that "these workers
    finish in tens of ms". The git worker takes ~3.5 s for the 402 entries in
    the tree and never checked the flag, so the request was ignored, the budget
    expired, and the sweep drained deferred deletes around a live thread.
    """
    import time

    import metatv.whats_new as wn
    from metatv.gui.qa_checklist_window import _GitRefWorker

    entries_dir = str(Path(wn.__file__).parent / "entries")
    worker = _GitRefWorker(list(range(1, 400)), entries_dir)
    worker.start()
    try:
        while not worker.isRunning():
            time.sleep(0.005)
        worker.requestInterruption()
        stopped = worker.wait(1000)
    finally:
        worker.requestInterruption()
        worker.wait(5000)

    assert stopped, (
        "the worker ignored requestInterruption() and ran on — this is what "
        "times out the harness's 3 s budget and ends in Abort trap: 6"
    )
