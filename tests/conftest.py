"""Shared fixtures for MetaTV tests."""

import os
import sys
import threading
import uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, ChannelDB
from metatv.core.repositories.channel import ChannelRepository
from metatv.core.repositories.tag import _clear_tag_cache


@pytest.fixture(autouse=True)
def _clear_tag_id_cache():
    """Clear the process-level tag-id cache around every test.

    ``_TAG_ID_CACHE`` maps ``(type, value) → integer id``.  Each test that
    creates its own DB file gets fresh auto-increment ids starting at 1, so
    cached ids from a prior test would alias to the wrong rows in the new DB.
    Clearing before (and after, for safety) each test eliminates cross-test
    contamination without requiring every fixture to call ``_clear_tag_cache``
    manually.
    """
    _clear_tag_cache()
    yield
    _clear_tag_cache()


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path_factory, monkeypatch):
    """Redirect every ``Path.home()``-derived location to a throwaway tmp home.

    ``Config.config_dir`` / ``data_dir`` / ``cache_dir`` default to
    ``Path.home()/…`` and ``Config.load()``/``save()`` hardcode the same paths.
    Without this guard, any test that builds a default ``Config()`` and saves
    (e.g. the On-Now header-state test, ``test_epg_on_now_display``) silently
    overwrites the developer's **real** ``~/.config/metatv/config.yaml`` — wiping
    Global Exclusions, the What's-New cursor, and the migration version fields.
    The running app then re-runs migrations, re-shows old What's New, and loses
    curation. Patching ``Path.home`` makes touching the real config structurally
    impossible for every test (autouse), without each test having to remember to
    pass ``config_dir=tmp_path``.
    """
    fake_home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    yield


# ---------------------------------------------------------------------------
# Deterministic Qt teardown between tests
# ---------------------------------------------------------------------------
#
# ~120 test files share one lazily-created ``QApplication`` (each defines a
# ``qapp`` fixture returning ``QApplication.instance() or QApplication([])``)
# that no test ever destroys.  Many GUI tests build a widget/window that owns a
# background ``QThread`` worker (e.g. the QA-checklist git resolvers, the
# Discover shelf loaders) and never join it.  When such a test's references drop
# — its ``win`` local at return, or a later garbage-collection cycle under
# memory pressure — the *parentless* ``QThread`` wrapper is freed while its
# thread is **still running**, so ``~QThread`` calls ``qFatal``.  On PyQt6 +
# Python 3.14 that corrupts the Qt heap non-deterministically, surfacing as the
# rare (~4% under cold-pycache + load) ``SIGSEGV`` inside ``QObject::connect``
# in whatever unlucky test runs next (see PR #304).
#
# The guard below runs after every test and, *only if* Qt was actually touched:
#   1. waits out any still-running ``QThread`` owned by a top-level widget this
#      test created (so nothing is left to be destroyed-while-running), then
#   2. drains the deferred-delete queue deterministically at this quiescent
#      boundary (so ``deleteLater``-scheduled objects die here, not mid-next-test).
# It reports — but does **not** force-close or force-delete — leaked widgets:
# on this toolchain, force-deleting a widget collapses its worker's reference
# chain and re-triggers the very ``~QThread`` abort we are preventing (and
# ``processEvents`` during teardown fires half-torn-down timers/signals).  Every
# variant that deleted widgets crashed the suite; waiting the QThreads out and
# draining deferred deletes fixes the root cause without that risk.  Widgets
# left alive are inert once their threads are joined; they die safely at process
# exit.  The guard is a couple of ``sys.modules`` / ``enumerate`` lookups for
# tests that never imported Qt, so it does not slow the non-GUI portion.
#
# It REPORTS what it had to touch — per-test into ``_QT_TEARDOWN_LOG``
# (summarised at session end by ``pytest_terminal_summary``) and, for the
# dangerous cases (stray live Python threads, or — under
# ``METATV_QT_LEAK_STRICT=1`` — widgets left *visible*), as an immediate
# ``QtResourceLeakWarning`` — so genuinely leaky tests stay identifiable.


class QtResourceLeakWarning(UserWarning):
    """A test left Qt resources (widgets/threads) alive at teardown."""


@dataclass
class _QtSweepReport:
    """What a single post-test Qt sweep observed and had to quiesce."""

    widgets: list[str] = field(default_factory=list)  # top-levels left alive (reported)
    visible: list[str] = field(default_factory=list)  # subset that was still visible
    qthreads: list[str] = field(default_factory=list)  # running QThreads waited out
    threads: list[str] = field(default_factory=list)  # stray non-main Python threads
    threads_alive: list[str] = field(default_factory=list)  # still alive after a stop attempt

    @property
    def clean(self) -> bool:
        return not self.qthreads and not self.threads and not self.visible


# Session-wide record of every non-clean sweep: (test nodeid, report).
_QT_TEARDOWN_LOG: list[tuple[str, _QtSweepReport]] = []

# Running totals for the terminal summary (every leaked widget, even the benign
# non-visible majority that is not otherwise logged).
_QT_WIDGETS_ALIVE = 0
_QT_WIDGET_TESTS = 0

# Short join budget for a stray Python thread: long enough to reap one that is
# just finishing, short enough not to stall on an idle-but-alive executor worker.
_THREAD_JOIN_TIMEOUT = 0.15

# Budget to wait out a still-running QThread (git / off-thread I/O workers).
# Generous because destroying a running QThread is fatal (see the sweep), and
# these workers finish in tens of ms; wait() returns as soon as the thread ends.
_QTHREAD_WAIT_MS = 3000

# Safety valve for the attribute walk below (pathologically nested containers).
_QTHREAD_WALK_MAX_STEPS = 2000


def _widget_addr(widget) -> int | None:
    """Stable C++ address of a widget (``sip.unwrapinstance``), or ``None``.

    NOT ``id(widget)``: ``topLevelWidgets()`` hands back a *fresh* Python wrapper
    for any widget nothing else references, and those transient wrappers' ``id``s
    get recycled — so a snapshot ``id`` can collide with a later, unrelated
    widget and misclassify it.  The C++ address is stable for the lifetime of the
    object and unique among live objects, which is exactly the identity we want.
    """
    from PyQt6 import sip

    try:
        return sip.unwrapinstance(widget)
    except (TypeError, RuntimeError):
        return None  # already-deleted wrapper


def _qt_snapshot() -> tuple[frozenset[int], frozenset[int]]:
    """Snapshot pre-existing top-level widgets + live threads before a test.

    Keys widgets by stable C++ address and threads by ident (never a strong
    reference), so it can never keep a would-be-garbage object alive and mask a
    leak.  Cheap and safe to call when Qt has never been imported (empty set).
    """
    qtwidgets = sys.modules.get("PyQt6.QtWidgets")
    widget_ids: frozenset[int] = frozenset()
    if qtwidgets is not None:
        app = qtwidgets.QApplication.instance()
        if app is not None:
            widget_ids = frozenset(
                a
                for a in (_widget_addr(w) for w in qtwidgets.QApplication.topLevelWidgets())
                if a is not None
            )
    thread_idents = frozenset(t.ident for t in threading.enumerate())
    return widget_ids, thread_idents


def _owned_qthreads(widget: object) -> list:
    """Return the ``QThread`` instances a *widget* owns via its own attributes.

    The GUI workers here are *parentless* ``QThread`` subclasses stored directly
    on their owning widget — ``window._git_worker``, ``view._thread``, or inside
    a list attribute like ``window._log_workers``.  This walks the widget's own
    ``__dict__`` values (and hops through plain containers), which finds them
    cheaply (~0.02 ms) and by object identity — so it works even while the
    thread is still in C++ startup and invisible to ``threading.enumerate()``.

    Deliberately does **not** traverse into other objects/widgets/types: that
    reference graph is huge (>3k nodes for a real window) and, crucially, a
    worker owned only through a *nested* manager object cannot be freed by this
    test's references dropping the way a direct attribute can — so it is out of
    scope here (and would surface as a loud abort in testing if it mattered).
    """
    from PyQt6.QtCore import QThread

    try:
        attrs = vars(widget)
    except TypeError:
        return []  # a widget with no instance __dict__ can own no worker attr

    found: list = []
    seen: set[int] = set()
    stack = list(attrs.values())
    steps = 0
    while stack and steps < _QTHREAD_WALK_MAX_STEPS:
        steps += 1
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        if isinstance(obj, QThread):
            found.append(obj)
        elif isinstance(obj, (list, tuple, set, frozenset)):
            stack.extend(obj)
        elif isinstance(obj, dict):
            stack.extend(obj.values())
    return found


def _wait_out_qthread(qthread, report: _QtSweepReport, seen_ids: set[int]) -> None:
    """Finish one still-running ``QThread`` so it can never be destroyed mid-run.

    Destroying a ``QThread`` that is **still running** makes Qt call ``qFatal``
    → ``SIGABRT`` — the exact corruption this guard prevents (observed ~25% of
    the time on the QA-checklist tests before this step existed).  Waiting it out
    now means that whenever the test's references to its owning widget drop, the
    thread is already finished and its destruction is safe.
    """
    if id(qthread) in seen_ids:
        return
    seen_ids.add(id(qthread))
    try:
        if not qthread.isRunning():
            return
        name = type(qthread).__name__
        report.qthreads.append(name)
        qthread.requestInterruption()
        qthread.quit()  # harmless no-op for run()-only workers with no event loop
        if not qthread.wait(_QTHREAD_WAIT_MS):
            report.threads_alive.append(name)
    except RuntimeError:
        pass  # a wrapper whose C++ object is already gone


def _qt_teardown_sweep(
    pre_widget_ids: frozenset[int],
    pre_thread_idents: frozenset[int],
) -> _QtSweepReport:
    """Wait out owned QThreads, drain deferred deletes, report stray Qt resources.

    Only inspects widgets/threads that appeared *during* this test (identity diff
    vs the pre-test snapshot); pre-existing/persistent objects are never touched.
    Widgets are reported but not force-deleted — see the module note: deleting
    them re-triggers the ``~QThread`` abort this guard exists to prevent.
    """
    report = _QtSweepReport()
    main = threading.main_thread()

    qtwidgets = sys.modules.get("PyQt6.QtWidgets")
    app = qtwidgets.QApplication.instance() if qtwidgets is not None else None

    if app is not None:
        from PyQt6.QtCore import QCoreApplication, QEvent

        leaked = []
        for w in qtwidgets.QApplication.topLevelWidgets():
            addr = _widget_addr(w)
            if addr is not None and addr not in pre_widget_ids:
                leaked.append(w)

        # 1) Wait out any still-running QThread owned by a widget this test
        #    created, so the thread cannot be destroyed-while-running when the
        #    test's references drop.  Scoped to each widget's own (small)
        #    attribute graph — cheap, never a heap scan.
        seen_qthreads: set[int] = set()
        for w in leaked:
            for qthread in _owned_qthreads(w):
                _wait_out_qthread(qthread, report, seen_qthreads)

        # 2) Drain deferred deletions deterministically at this quiescent
        #    boundary, so deleteLater-scheduled C++ objects die here rather than
        #    mid-next-test.  Safe now that owned QThreads have been waited out.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        # 3) Record the top-levels this test left alive (informational only).
        for w in leaked:
            try:
                report.widgets.append(type(w).__name__)
                if w.isVisible():
                    report.visible.append(type(w).__name__)
            except Exception:  # a wrapper whose C++ object is already gone
                pass

    # 4) Report stray Python threads still alive (executor workers that outlived
    #    the test).  Owned QThreads waited out in step 1 have already ended here.
    for t in threading.enumerate():
        if t is main or not t.is_alive() or t.ident in pre_thread_idents:
            continue
        report.threads.append(t.name)
        if not t.daemon:
            t.join(_THREAD_JOIN_TIMEOUT)
            if t.is_alive():
                report.threads_alive.append(t.name)

    return report


@pytest.fixture(autouse=True)
def _qt_teardown_guard(request):
    """Deterministically quiesce Qt state after every test (see module note)."""
    global _QT_WIDGETS_ALIVE, _QT_WIDGET_TESTS
    pre_widget_ids, pre_thread_idents = _qt_snapshot()
    yield
    report = _qt_teardown_sweep(pre_widget_ids, pre_thread_idents)
    if report.widgets:
        _QT_WIDGETS_ALIVE += len(report.widgets)
        _QT_WIDGET_TESTS += 1
    # Log any sweep that touched a QThread, a stray Python thread, or left a
    # widget visible — the signals worth surfacing (the non-visible leaked-widget
    # majority is expected and only tallied for the summary total above).
    if not report.clean:
        _QT_TEARDOWN_LOG.append((request.node.nodeid, report))
    if report.threads:
        detail = f"{request.node.nodeid}: left Python thread(s) running after test: {report.threads}"
        if report.threads_alive:
            detail += f" (still alive after {_THREAD_JOIN_TIMEOUT}s join: {report.threads_alive})"
        warnings.warn(detail, QtResourceLeakWarning, stacklevel=2)
    if report.visible and os.environ.get("METATV_QT_LEAK_STRICT"):
        warnings.warn(
            f"{request.node.nodeid}: left visible top-level widget(s): {report.visible}",
            QtResourceLeakWarning,
            stacklevel=2,
        )


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Summarise what the Qt teardown guard observed (leaky tests, one block)."""
    tr = terminalreporter
    total_qthreads = sum(len(r.qthreads) for _, r in _QT_TEARDOWN_LOG)
    total_visible = sum(len(r.visible) for _, r in _QT_TEARDOWN_LOG)
    qthread_tests = [(n, r) for n, r in _QT_TEARDOWN_LOG if r.qthreads]
    thread_tests = [(n, r) for n, r in _QT_TEARDOWN_LOG if r.threads]
    if not (_QT_WIDGET_TESTS or qthread_tests or thread_tests):
        return
    tr.write_sep("=", "Qt teardown guard", cyan=True)
    tr.write_line(
        f"{_QT_WIDGETS_ALIVE} top-level widget(s) left alive across "
        f"{_QT_WIDGET_TESTS} test(s) (reported, not force-deleted — see conftest note); "
        f"{total_visible} left visible"
    )
    if qthread_tests:
        tr.write_line(
            f"waited out running QThread(s) in {len(qthread_tests)} test(s) "
            f"({total_qthreads} total) — these tests do not join their workers:"
        )
        for nodeid, r in qthread_tests[:8]:
            stuck = (
                f" (did NOT finish in {_QTHREAD_WAIT_MS}ms: {r.threads_alive})"
                if r.threads_alive
                else ""
            )
            tr.write_line(f"  {nodeid}: {sorted(set(r.qthreads))}{stuck}")
    if thread_tests:
        tr.write_line(f"{len(thread_tests)} test(s) left stray Python thread(s):")
        for nodeid, r in thread_tests:
            alive = f" (alive after join: {r.threads_alive})" if r.threads_alive else ""
            tr.write_line(f"  {nodeid}: {r.threads}{alive}")


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite session — isolated per test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(scope="function")
def repo(db_session):
    return ChannelRepository(db_session)


_counter = 0


def make_channel(
    session,
    name: str,
    detected_prefix: str | None = None,
    detected_quality: str | None = None,
    detected_region: str | None = None,
    media_type: str = "live",
    is_hidden: bool = False,
    provider_id: str = "test",
    **kwargs,
) -> ChannelDB:
    """Insert a minimal ChannelDB row and return it."""
    global _counter
    _counter += 1
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(_counter),
        provider_id=provider_id,
        name=name,
        detected_prefix=detected_prefix,
        detected_quality=detected_quality,
        detected_region=detected_region,
        media_type=media_type,
        is_hidden=is_hidden,
        **kwargs,
    )
    session.add(ch)
    session.flush()
    return ch
