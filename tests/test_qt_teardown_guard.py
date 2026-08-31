"""Behavioral test for the deterministic Qt teardown guard in ``conftest.py``.

Exercises the real sweep that the autouse ``_qt_teardown_guard`` fixture runs
after every test.  The guard exists because many GUI tests build a widget that
owns a background ``QThread`` worker and never join it; when the test's
references drop, the parentless ``QThread`` is freed *while still running*, so
``~QThread`` aborts and corrupts the Qt heap on PyQt6 + Python 3.14 (the rare
``QObject::connect`` SIGSEGV in PR #304).

Each test drives the sweep directly and asserts the outcome that would break if
the guard regressed: it must wait out a still-running worker owned by a leaked
widget (so nothing is destroyed mid-run), drain the deferred-delete queue, leave
pre-existing widgets untouched, flag/join stray threads, and report — without
force-deleting — the widgets a test left alive.
"""

from __future__ import annotations

import threading
import time

import pytest
from PyQt6.QtCore import QThread

from tests.conftest import (  # the module under test is the shared conftest
    _QtSweepReport,
    _owned_qthreads,
    _qt_snapshot,
    _qt_teardown_sweep,
)


class _BlockingWorker(QThread):
    """A QThread that runs until interrupted (no wall-clock races).

    ``run()`` signals ``started_running`` then loops until the guard's
    ``requestInterruption()`` lands — so the worker is *guaranteed* still running
    when the sweep inspects it, and stops promptly when the sweep waits it out.
    """

    def __init__(self) -> None:
        super().__init__()
        self.started_running = threading.Event()

    def run(self) -> None:
        self.started_running.set()
        while not self.isInterruptionRequested():
            self.msleep(5)


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _is_deleted(widget) -> bool:
    """True once the underlying C++ object is gone (the sip wrapper raises)."""
    try:
        widget.objectName()
    except RuntimeError:
        return True
    return False


def test_sweep_reports_leaked_top_level_without_deleting(qapp):
    """A shown, parent-less widget is reported (and flagged visible) — not deleted.

    Force-deleting widgets re-triggers the ``~QThread`` abort on this toolchain,
    so the guard deliberately leaves them alive; here we prove it is recorded but
    the C++ object survives.
    """
    from PyQt6.QtWidgets import QWidget

    pre_ids, pre_threads = _qt_snapshot()  # snapshot BEFORE the leak
    leaked = QWidget()  # top-level, no parent — the classic suite leak
    leaked.show()
    try:
        report = _qt_teardown_sweep(pre_ids, pre_threads)

        assert "QWidget" in report.widgets  # reported as left-alive
        assert "QWidget" in report.visible  # flagged as still-visible (strong signal)
        assert not report.clean  # visible widget → worth surfacing
        assert not _is_deleted(leaked)  # NOT force-deleted (see module note)
    finally:
        leaked.close()
        leaked.deleteLater()


def test_sweep_drains_deferred_deletes(qapp):
    """A ``deleteLater``-scheduled widget is actually destroyed by the sweep.

    Deterministic deferred-delete draining is the second half of the fix: the
    C++ object dies here, at the boundary, not mid-next-test.
    """
    from PyQt6.QtWidgets import QWidget

    doomed = QWidget()
    pre_ids, pre_threads = _qt_snapshot()  # snapshot INCLUDES doomed (not a leak)
    doomed.deleteLater()  # scheduled, but not yet processed

    _qt_teardown_sweep(pre_ids, pre_threads)

    assert _is_deleted(doomed)  # the drain delivered the DeferredDelete event


def test_sweep_leaves_pre_existing_widgets_untouched(qapp):
    """Widgets that pre-date the snapshot must be spared (no cross-test stomping)."""
    from PyQt6.QtWidgets import QWidget

    survivor = QWidget()
    survivor.show()
    try:
        pre_ids, pre_threads = _qt_snapshot()  # snapshot INCLUDES survivor
        report = _qt_teardown_sweep(pre_ids, pre_threads)

        assert "QWidget" not in report.widgets  # not a leak of this test
        assert report.clean
        assert not _is_deleted(survivor)  # untouched, still alive
    finally:
        survivor.close()
        survivor.deleteLater()


def test_sweep_reports_nothing_when_clean(qapp):
    """No new widgets and no new threads → a clean report, nothing to surface."""
    pre_ids, pre_threads = _qt_snapshot()

    report = _qt_teardown_sweep(pre_ids, pre_threads)

    assert isinstance(report, _QtSweepReport)
    assert report.clean
    assert report.widgets == []
    assert report.threads == []
    assert report.qthreads == []


def test_sweep_flags_stray_daemon_thread(qapp):
    """A still-running (daemon) thread the test started is detected, not joined."""
    pre_ids, pre_threads = _qt_snapshot()
    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name="metatv-test-stray", daemon=True)
    t.start()
    try:
        report = _qt_teardown_sweep(pre_ids, pre_threads)

        assert "metatv-test-stray" in report.threads
        assert not report.clean
    finally:
        stop.set()
        t.join(timeout=2.0)


def test_stray_thread_is_flagged_even_when_it_recycles_a_dead_ident(qapp):
    """The bug this guard had: CPython hands a dead thread's ident to the next one.

    Keyed by ``t.ident``, a brand-new thread that reuses a just-dead thread's
    ident reads as pre-existing and is skipped — the sweep reports a clean run
    while a thread leaks. Measured at 200/200 in a tight start/join loop, and it
    failed a CI shard twice where a pool shut down mid-test.

    The reuse is forced deterministically: the doomed thread is held alive with
    an Event so it is genuinely captured by the snapshot, released, and only then
    are the strays started. Against the ident-keyed snapshot the count assertion
    fails; against object identity it passes.
    """
    release = threading.Event()
    doomed = threading.Thread(target=release.wait, name="metatv-test-doomed")
    doomed.start()
    while doomed.ident is None:          # started, and visible to enumerate()
        time.sleep(0.001)
    assert doomed in threading.enumerate(), "doomed thread must be live at snapshot"

    pre_ids, pre_threads = _qt_snapshot()   # captures doomed
    doomed_ident = doomed.ident
    release.set()
    doomed.join(timeout=2.0)                # now its ident is free for reuse
    assert not doomed.is_alive()

    stop = threading.Event()
    strays: list[threading.Thread] = []
    try:
        # Start several so at least one lands on the freed ident.
        for _ in range(6):
            t = threading.Thread(target=stop.wait, name="metatv-test-stray", daemon=True)
            t.start()
            strays.append(t)
        if not any(t.ident == doomed_ident for t in strays):
            pytest.skip("no stray recycled the freed ident on this run")

        report = _qt_teardown_sweep(pre_ids, pre_threads)

        assert report.threads.count("metatv-test-stray") == len(strays), (
            f"expected all {len(strays)} strays reported, got "
            f"{report.threads.count('metatv-test-stray')} — an ident-keyed "
            "snapshot silently drops whichever stray recycled a dead ident"
        )
        assert not report.clean
    finally:
        stop.set()
        for t in strays:
            t.join(timeout=2.0)


def test_a_thread_alive_at_snapshot_is_never_reported(qapp):
    """The other direction: object identity must still treat pre-existing as pre-existing."""
    stop = threading.Event()
    incumbent = threading.Thread(target=stop.wait, name="metatv-test-incumbent", daemon=True)
    incumbent.start()
    try:
        pre_ids, pre_threads = _qt_snapshot()   # taken AFTER it started
        report = _qt_teardown_sweep(pre_ids, pre_threads)
        assert "metatv-test-incumbent" not in report.threads
    finally:
        stop.set()
        incumbent.join(timeout=2.0)


def test_sweep_joins_finishing_non_daemon_thread(qapp):
    """A non-daemon thread that finishes quickly is reaped within the join budget."""
    pre_ids, pre_threads = _qt_snapshot()
    t = threading.Thread(target=lambda: time.sleep(0.02), name="metatv-test-finishing")
    t.start()

    report = _qt_teardown_sweep(pre_ids, pre_threads)

    assert "metatv-test-finishing" in report.threads
    assert "metatv-test-finishing" not in report.threads_alive  # joined successfully
    assert not t.is_alive()


def test_owned_qthreads_finds_direct_and_container_workers(qapp):
    """The attribute walk finds workers held directly and behind a container hop."""
    from PyQt6.QtWidgets import QWidget

    host = QWidget()
    host._worker = QThread()  # direct attribute
    host._worker_list = [QThread()]  # ...and one behind a list hop
    host._nested = {"k": QThread()}  # ...and one behind a dict hop
    try:
        found = _owned_qthreads(host)
        assert len(found) == 3  # all three reachable via the widget's own attrs
        assert all(isinstance(q, QThread) for q in found)
    finally:
        host.close()


def test_sweep_waits_out_worker_owned_by_leaked_widget(qapp):
    """The real crash path: a top-level widget owns a running, parentless QThread.

    If the worker were still running when the test's references drop, ``~QThread``
    would ``qFatal`` (the ~25% SIGABRT before this guard).  The sweep must wait
    the worker out — proven here by the worker having finished, the process
    surviving, and the widget being reported but left alive.
    """
    from PyQt6.QtWidgets import QWidget

    pre_ids, pre_threads = _qt_snapshot()
    host = QWidget()  # top-level → leaked → its attribute graph is walked
    host._worker = _BlockingWorker()  # parentless QThread owned only by this widget
    host._worker.start()
    host.show()
    assert host._worker.started_running.wait(2.0)  # deterministically running now

    report = _qt_teardown_sweep(pre_ids, pre_threads)

    assert "_BlockingWorker" in report.qthreads  # waited out, not abandoned
    assert report.threads_alive == []  # finished within the budget
    assert not host._worker.isRunning()  # safe to destroy now
    assert "QWidget" in report.widgets  # reported (not deleted)
    host.close()  # explicit cleanup for this test's own hygiene


def test_sweep_is_noop_before_qt_imported():
    """Snapshot/sweep are safe and cheap when Qt was never touched.

    Guards the fast path for the non-GUI portion of the suite: the sweep must
    not raise when there is no ``QApplication`` to do work against.
    """
    pre_ids, pre_threads = _qt_snapshot()
    report = _qt_teardown_sweep(pre_ids, pre_threads)
    assert report.clean
