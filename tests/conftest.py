"""Shared fixtures for MetaTV tests."""

import os

# Headless by default: without this, every pytest-qt widget/dialog renders on the
# developer's live display — a full-suite run flashed real windows (including the
# What's New dialog paging all ~211 entries) on the owner's screen for 5-15s per
# run. Must be set before ANY Qt import. setdefault so an explicit
# QT_QPA_PLATFORM=xcb still allows deliberate windowed debugging.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import threading
import weakref
import uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

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


def _qt_snapshot() -> tuple[frozenset[int], "weakref.WeakSet"]:
    """Snapshot pre-existing top-level widgets + live threads before a test.

    Keys widgets by stable C++ address and threads by object identity held
    WEAKLY (never a strong reference), so it can never keep a would-be-garbage
    object alive and mask a leak.  Cheap and safe to call when Qt has never
    been imported (empty set).
    """
    qtwidgets = sys.modules.get("PyQt6.QtWidgets")
    widget_ids: frozenset[int] = frozenset()
    if qtwidgets is not None:
        app = qtwidgets.QApplication.instance()
        if app is not None:
            from PyQt6 import sip

            widget_ids = frozenset(
                a
                for a in (_widget_addr(w)
                          for w in qtwidgets.QApplication.topLevelWidgets()
                          if not sip.isdeleted(w))   # same hazard as the sweep
                if a is not None
            )
    # Threads are keyed by OBJECT IDENTITY in a WeakSet, never by ``ident``.
    # CPython hands a dead thread's ident straight to the next one — measured at
    # 200/200 in a tight loop — so ``t.ident in pre_idents`` calls a brand-new
    # thread pre-existing and skips it. That is a FALSE NEGATIVE in the guard
    # whose entire job is catching leaked threads, and it is why the sweep
    # reported an empty thread list on a CI shard where a pool happened to shut
    # down mid-test. A WeakSet keeps the no-strong-reference property the widget
    # half relies on: ``threading`` already holds every live thread, so an entry
    # survives exactly as long as its thread does.
    thread_objs: weakref.WeakSet = weakref.WeakSet(threading.enumerate())
    return widget_ids, thread_objs


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
    pre_threads: "weakref.WeakSet",
) -> _QtSweepReport:
    """Wait out owned QThreads, drain deferred deletes, report stray Qt resources.

    Only inspects widgets/threads that appeared *during* this test (identity diff
    vs the pre-test snapshot); pre-existing/persistent objects are never touched.
    Widgets are reported but not force-deleted — see the module note: deleting
    them re-triggers the ``~QThread`` abort this guard exists to prevent.
    """
    report = _QtSweepReport()
    main = threading.main_thread()

    from PyQt6 import sip

    qtwidgets = sys.modules.get("PyQt6.QtWidgets")
    app = qtwidgets.QApplication.instance() if qtwidgets is not None else None

    if app is not None:
        from PyQt6.QtCore import QCoreApplication, QEvent

        leaked = []
        # Identity + visibility are read HERE, while every wrapper is still
        # known-live, and never again afterwards.  Step 2's DeferredDelete drain
        # can destroy the C++ object underneath a wrapper, and probing a survivor
        # after the drain is unsafe at any level: sip.isdeleted is a
        # time-of-check/time-of-use test that answers False on reused memory, and
        # the segfault that follows it cannot be caught by `except`.  Full-suite
        # runs died on exactly that post-drain isVisible() call twice on
        # 2026-08-01 and again on 2026-08-15.  Read before the drain, report after.
        pre_drain: list[tuple[object, str, bool]] = []
        for w in qtwidgets.QApplication.topLevelWidgets():
            # sip.isdeleted() FIRST, and it is the only safe question to ask.
            # topLevelWidgets() can hand back a wrapper whose C++ object an
            # EARLIER test already destroyed; touching it — isVisible(), or even
            # unwrapinstance() — reads freed memory and the process dies inside
            # sip_api_get_address, which no `except` can catch. isdeleted()
            # answers from the wrapper alone and never dereferences.
            #
            # The comment above records moving isVisible() before the drain to
            # dodge this. That fixed the post-drain case only: a widget can
            # already be dead on arrival, which is why the crash kept happening
            # intermittently — roughly one run in three — always at teardown,
            # always AFTER every test had passed, so the run printed "N passed"
            # and then exited 139.
            if sip.isdeleted(w):
                continue
            addr = _widget_addr(w)
            if addr is not None and addr not in pre_widget_ids:
                leaked.append(w)
                pre_drain.append((w, type(w).__name__, w.isVisible()))

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
        # Everything reported here comes from the pre-drain snapshot above — no
        # attribute of a possibly-destroyed wrapper is touched.  sip.isdeleted is
        # used ONLY to label a corpse, never as a licence to probe a survivor.
        # "Visible" therefore means "visible when the test handed back control",
        # which is the signal this guard actually wants: a test that left a window
        # on screen, not one whose widget outlived the harness's own cleanup.
        from PyQt6 import sip as _sip
        for w, type_name, was_visible in pre_drain:
            if _sip.isdeleted(w):
                report.widgets.append(type_name + " (deferred-deleted)")
                continue
            report.widgets.append(type_name)
            if was_visible:
                report.visible.append(type_name)

    # 4) Report stray Python threads still alive (executor workers that outlived
    #    the test).  Owned QThreads waited out in step 1 have already ended here.
    for t in threading.enumerate():
        if t is main or not t.is_alive() or t in pre_threads:
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
    pre_widget_ids, pre_threads = _qt_snapshot()
    yield
    report = _qt_teardown_sweep(pre_widget_ids, pre_threads)
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



def destroy_widget(*widgets) -> None:
    """Actually free a parentless top-level. ``deleteLater()`` alone is NOT enough.

    A leaked top-level is repainted by every later ``apply_theme()``, and one
    per test is what segfaulted a CI shard (CLAUDE.md, "Delete parentless
    top-level widgets the test creates"). The posted ``DeferredDelete`` has to
    be pumped for the C++ object to go, and ``processEvents()`` does not pump
    it.

    Shared here because five test files had each written their own private
    ``_destroy``/drain — the shape CLAUDE.md names as the recurring failure
    ("an enumeration never sees what nobody remembered to add"). New tests
    import this one; the existing copies are a logged migration, not a
    rewrite-everything-now.

    Args:
        *widgets: Top-level widgets to hide, delete and drain. ``None`` and
            already-deleted wrappers are skipped, so a caller can pass whatever
            its rig built without guarding each one.
    """
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QApplication

    for widget in widgets:
        if widget is None or sip.isdeleted(widget):
            continue
        widget.hide()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def sidebar_config(**over):
    """A fake ``Config`` carrying every field a sidebar SECTION reads.

    Seven test files each hand-rolled their own ``SimpleNamespace(live_icon="L",
    movie_icon="M", …)``, so every new field a section learned to read broke all
    seven at once — which is exactly what happened when rows gained a density
    preference. One factory means the next field is added here, once.

    CLAUDE.md: repair a test double at the shared factory, never with a
    defensive ``getattr`` in production — a ``getattr`` fallback in the section
    would mask a real missing-config bug for every viewer.
    """
    base = {
        # Legacy emoji icon set — sidebar ROWS now use vector roles, but headers
        # and several menus still read these.
        "live_icon": "L", "movie_icon": "M", "series_icon": "S", "unknown_icon": "?",
        "like_icon": "+", "delete_icon": "x", "watched_icon": "v",
        "expand_icon": "v", "collapse_icon": ">",
        # Row shape (Settings → Interface → Sidebar rows).
        "sidebar_row_density": "compact",
        # Section behaviour.
        "filter_adult_mode": "all",
        "queue_filter_visible": False,
        "sidebar_section_states": {},
    }
    base.update(over)
    return SimpleNamespace(**base)

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


# ---------------------------------------------------------------------------
# SettingsDialog skeleton stubs
# ---------------------------------------------------------------------------

def mock_settings_recommendation_widgets(dlg) -> None:
    """MagicMock flavor of :func:`wire_settings_recommendation_widgets`.

    For skeletons that are deliberately Qt-free (all-MagicMock, no ``qapp``
    fixture) — constructing a real QWidget without a QApplication aborts the
    interpreter. Values mirror the shipped defaults via ``RecScoringSettings``
    so ``_save_values`` records "untouched" (None) for every dial, exactly as a
    fresh install would.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from unittest.mock import MagicMock

    from metatv.core.preference_engine import RecScoringSettings

    defaults = RecScoringSettings()

    def _stub(method: str, value):
        m = MagicMock()
        getattr(m, method).return_value = value
        return m

    dlg._rec_mix_auto_check = _stub("isChecked", True)     # Automatic, as shipped
    dlg._rec_mix_spin = _stub("value", 50)
    dlg._rec_mix_ratio_label = MagicMock()
    dlg._rec_genre_spin = _stub("value", defaults.genre_weight)
    dlg._rec_director_spin = _stub("value", defaults.director_weight)
    dlg._rec_actor_spin = _stub("value", defaults.actor_weight)
    dlg._rec_keyword_spin = _stub("value", defaults.keyword_weight)
    dlg._rec_actor_support_spin = _stub("value", defaults.actor_min_support)
    dlg._rec_diversity_spin = _stub("value", defaults.people_diversity_decay)
    dlg._rec_impression_spin = _stub("value", round(defaults.impression_decay * 100))
    dlg._rec_liked_cap_spin = _stub("value", defaults.liked_cap)


def wire_settings_recommendation_widgets(dlg) -> None:
    """Attach the Settings → Recommendations tab widgets to a skeleton dialog.

    Builds **real** Qt widgets, so the caller must already have a QApplication
    (the module ``qapp`` fixture). Qt-free skeletons want
    :func:`mock_settings_recommendation_widgets` instead.

    Six settings tests build ``SettingsDialog`` via ``__new__`` and hand-wire only
    the widgets ``_load_values``/``_save_values`` touch — so every tab added to the
    dialog breaks all six at once until each one grows the same stubs. Keeping this
    group in one factory makes the next tab a single edit here instead of six
    near-identical copies, and keeps the stubs honest: real Qt widgets with the
    same ranges as the production tab, so load/save round-trips behave the same.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox, QLineEdit, QSpinBox

    # Stubs open on the production defaults (Automatic mix), so a save-only
    # skeleton that never calls _load_values still writes what a fresh install
    # would: rec_media_mix = None rather than an accidental explicit 0%.
    dlg._rec_mix_auto_check = QCheckBox()
    dlg._rec_mix_auto_check.setChecked(True)
    dlg._rec_mix_spin = QSpinBox()
    dlg._rec_mix_spin.setRange(0, 100)
    dlg._rec_mix_spin.setValue(50)
    # Only setText/setVisible are called on the ratio label — a QLineEdit stub
    # satisfies both without needing the production QLabel.
    dlg._rec_mix_ratio_label = QLineEdit()
    for _name in ("_rec_genre_spin", "_rec_director_spin", "_rec_actor_spin",
                  "_rec_keyword_spin", "_rec_diversity_spin"):
        _spin = QDoubleSpinBox()
        _spin.setRange(0.0, 5.0)
        _spin.setDecimals(2)
        setattr(dlg, _name, _spin)
    dlg._rec_actor_support_spin = QSpinBox()
    dlg._rec_actor_support_spin.setRange(1, 10)
    dlg._rec_impression_spin = QSpinBox()
    dlg._rec_impression_spin.setRange(0, 20)
    dlg._rec_liked_cap_spin = QSpinBox()
    dlg._rec_liked_cap_spin.setRange(0, 10)


def mock_settings_epg_widgets(dlg) -> None:
    """MagicMock flavor of :func:`wire_settings_epg_widgets`.

    For skeletons that are deliberately Qt-free (all-MagicMock, no ``qapp``
    fixture) — constructing a real QWidget without a QApplication aborts the
    interpreter.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from unittest.mock import MagicMock

    def _stub(method: str, value):
        m = MagicMock()
        getattr(m, method).return_value = value
        return m

    dlg._epg_interval_combo = _stub("currentData", "3d")
    dlg._epg_hide_older_spin = _stub("value", 0)
    dlg._epg_scrubber_increment_combo = _stub("currentData", 30)
    dlg._epg_notify_minutes_spin = _stub("value", 15)
    dlg._epg_auto_refresh_check = _stub("isChecked", True)


def wire_settings_epg_widgets(dlg) -> None:
    """Attach the Settings → Metadata tab's EPG group widgets to a skeleton dialog.

    Builds **real** Qt widgets, so the caller must already have a QApplication
    (the module ``qapp`` fixture). Qt-free skeletons want
    :func:`mock_settings_epg_widgets` instead.

    Seven settings tests build ``SettingsDialog`` via ``__new__`` and hand-wire only
    the widgets ``_load_values``/``_save_values`` touch — so every widget added to
    the EPG group breaks all seven at once until each one grows the same stubs.
    Keeping this group in one factory (mirrors ``wire_settings_recommendation_widgets``)
    makes the next EPG widget a single edit here instead of seven near-identical
    copies.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from PyQt6.QtWidgets import QCheckBox, QComboBox, QSpinBox

    import metatv.core.epg_utils as _epg

    dlg._epg_interval_combo = QComboBox()
    for value, label in _epg.EPG_INTERVAL_CHOICES:
        dlg._epg_interval_combo.addItem(label, value)
    dlg._epg_hide_older_spin = QSpinBox()
    dlg._epg_hide_older_spin.setRange(0, 168)
    dlg._epg_scrubber_increment_combo = QComboBox()
    for _mins in _epg.EPG_SCRUBBER_INCREMENTS:
        dlg._epg_scrubber_increment_combo.addItem(f"{_mins} minutes", _mins)
    dlg._epg_notify_minutes_spin = QSpinBox()
    dlg._epg_notify_minutes_spin.setRange(5, 120)
    dlg._epg_notify_minutes_spin.setValue(15)
    dlg._epg_auto_refresh_check = QCheckBox()
    dlg._epg_auto_refresh_check.setChecked(True)


def mock_settings_theme_widget(dlg) -> None:
    """MagicMock flavor of :func:`wire_settings_theme_widget`.

    For skeletons that are deliberately Qt-free (all-MagicMock, no ``qapp``
    fixture) — constructing a real QWidget without a QApplication aborts the
    interpreter.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from unittest.mock import MagicMock

    dlg._theme_combo = MagicMock()
    dlg._theme_combo.currentData.return_value = "Midnight"


def wire_settings_theme_widget(dlg) -> None:
    """Attach the Settings → Interface tab's Appearance group's theme combo
    to a skeleton dialog (wave7/theme-system).

    Builds a **real** Qt widget, so the caller must already have a
    QApplication (the module ``qapp`` fixture). Qt-free skeletons want
    :func:`mock_settings_theme_widget` instead.

    Mirrors ``wire_settings_density_widget`` — any bare-skeleton test that
    calls the full ``_load_values``/``_save_values`` breaks once a new widget
    is added to ``_build_interface_tab`` until it grows a stub for it.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from PyQt6.QtWidgets import QComboBox

    from metatv.gui import theme_palettes

    dlg._theme_combo = QComboBox()
    for palette_name in theme_palettes.PALETTES:
        dlg._theme_combo.addItem(palette_name, palette_name)
    # Appearance group, beside the theme combo: hide-the-menu-bar-until-Alt.
    # Added here rather than guarded in production — PyQt raises RuntimeError
    # (not AttributeError) for attribute access on a __new__'d dialog, so a
    # hasattr guard would not absorb it and would mask a genuinely missing
    # widget in the real dialog.
    from PyQt6.QtWidgets import QCheckBox

    dlg._menu_auto_hide_check = QCheckBox()
    dlg._menu_auto_hide_check.setChecked(False)


def mock_settings_density_widget(dlg) -> None:
    """MagicMock flavor of :func:`wire_settings_density_widget`.

    For skeletons that are deliberately Qt-free (all-MagicMock, no ``qapp``
    fixture) — constructing a real QWidget without a QApplication aborts the
    interpreter.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from unittest.mock import MagicMock

    dlg._channel_density_combo = MagicMock()
    dlg._channel_density_combo.currentData.return_value = "comfy"
    dlg._sidebar_density_combo = MagicMock()
    dlg._sidebar_density_combo.currentData.return_value = "compact"
    dlg._alerts_show_idle_check = MagicMock()
    dlg._alerts_show_idle_check.isChecked.return_value = False
    dlg._series_interval_spin = MagicMock()
    dlg._series_interval_spin.value.return_value = 60
    dlg._platform_name_style_combo = MagicMock()
    dlg._platform_name_style_combo.currentData.return_value = "auto"
    dlg._channel_thumbnails_check = MagicMock()
    dlg._channel_thumbnails_check.isChecked.return_value = True
    dlg._collapse_variants_check = MagicMock()
    dlg._collapse_variants_check.isChecked.return_value = False
    dlg._theme_combo = MagicMock()
    dlg._theme_combo.currentData.return_value = "Midnight"
    dlg._theme_combo.currentText.return_value = "Midnight"
    dlg._menu_auto_hide_check = MagicMock()
    dlg._menu_auto_hide_check.isChecked.return_value = False


def wire_watch_alerts_headings(section) -> None:
    """Give a ``__new__``'d WatchAlertsSection its three group headings.

    They are ``GroupHeading`` widgets, not ``QPushButton``s — a heading is two
    toned (muted label, bright count) and a button's single ``setText`` cannot
    express that. A skeleton that assigns a QPushButton here fails on
    ``set_count``, which is the shape the real widget exposes.
    """
    from metatv.gui.sidebar.base import GroupHeading

    section._epg_toggle = GroupHeading("EPG", interactive=True)
    section._vod_toggle = GroupHeading("Movies & Series", interactive=True)
    section._retry_toggle = GroupHeading("Stream Monitoring", interactive=True)


def wire_watch_alerts_group_state(section) -> None:
    """Give a ``__new__``'d WatchAlertsSection the group-collapse flags.

    ``refresh_vod_rules`` reads ``_keyword_collapsed`` and ``_series_collapsed``
    to decide whether each group's rows are drawn. On a skeleton built with
    ``__new__`` those attributes do not exist, and PyQt raises **RuntimeError**
    for a missing attribute on an object whose C++ super-init never ran — not
    the AttributeError a ``getattr`` default would absorb. So the guard cannot
    live in production; it lives here, once, per CLAUDE.md.

    Replaces the hand-rolled ``section._vod_collapsed = False`` that five test
    files each carried. That flag belonged to the "Movies & Series" wrapper,
    which was dissolved when it started reading as a peer of the two groups it
    contained.

    Args:
        section: A ``WatchAlertsSection`` built via ``__new__``.
    """
    section._keyword_collapsed = False
    section._series_collapsed = False


def wire_settings_density_widget(dlg) -> None:
    """Attach the Settings → Interface tab's Channel List group widgets (row
    density combo + "Show thumbnails in lists" checkbox) to a skeleton dialog.

    Builds **real** Qt widgets, so the caller must already have a
    QApplication (the module ``qapp`` fixture). Qt-free skeletons want
    :func:`mock_settings_density_widget` instead.

    Mirrors ``wire_settings_recommendation_widgets`` et al: any bare-skeleton
    test that calls the full ``_load_values``/``_save_values`` breaks once a
    new widget is added to ``_build_interface_tab``'s Channel List group until
    it grows a stub for it — keeping this group in its own factory means the
    next Channel List widget is a single line here instead of eight near-
    identical copies across every test file that builds a bare skeleton.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from metatv.gui.settings_dialog_tabs import _CHANNEL_DENSITY_CHOICES
    from metatv.gui.settings_dialog_tabs import (
        _PLATFORM_NAME_STYLE_CHOICES, _SIDEBAR_DENSITY_CHOICES,
    )
    from PyQt6.QtWidgets import QCheckBox, QComboBox, QSpinBox

    dlg._channel_density_combo = QComboBox()
    for label, value in _CHANNEL_DENSITY_CHOICES:
        dlg._channel_density_combo.addItem(label, value)
    # Sidebar row density (Settings -> Interface -> Sidebar). Here rather than
    # in nine test files, which is what this factory's docstring promises and
    # what adding it anywhere else costs: one widget on the dialog and not on
    # the double broke 43 tests across 9 files at once.
    dlg._sidebar_density_combo = QComboBox()
    for label, value in _SIDEBAR_DENSITY_CHOICES:
        dlg._sidebar_density_combo.addItem(label, value)
    dlg._alerts_show_idle_check = QCheckBox()
    dlg._alerts_show_idle_check.setChecked(False)
    dlg._series_interval_spin = QSpinBox()
    dlg._series_interval_spin.setRange(0, 1440)
    dlg._series_interval_spin.setValue(60)
    dlg._platform_name_style_combo = QComboBox()
    for label, value in _PLATFORM_NAME_STYLE_CHOICES:
        dlg._platform_name_style_combo.addItem(label, value)
    dlg._channel_thumbnails_check = QCheckBox()
    dlg._channel_thumbnails_check.setChecked(True)
    # Collapse-variants opt-in (#387) and the theme combo (#389) — same group,
    # so they live in this factory rather than eight duplicated stubs.
    dlg._collapse_variants_check = QCheckBox()
    dlg._collapse_variants_check.setChecked(False)
    dlg._menu_auto_hide_check = QCheckBox()
    dlg._menu_auto_hide_check.setChecked(False)
    try:
        from metatv.gui.theme_palettes import PALETTES as _PALETTES
    except Exception:
        _PALETTES = {"Midnight": {}}
    dlg._theme_combo = QComboBox()
    for _name in _PALETTES:
        dlg._theme_combo.addItem(_name, _name)


def mock_settings_playback_widgets(dlg) -> None:
    """MagicMock flavor of :func:`wire_settings_playback_widgets`.

    For skeletons that are deliberately Qt-free (all-MagicMock, no ``qapp``
    fixture) — constructing a real QWidget without a QApplication aborts the
    interpreter.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from unittest.mock import MagicMock

    def _stub(method: str, value):
        m = MagicMock()
        getattr(m, method).return_value = value
        return m

    dlg._recheck_failed_on_refresh_check = _stub("isChecked", True)


def wire_style_menu_actions(host) -> None:
    """Attach the Style menu's action groups to a skeleton MainWindow.

    ``_apply_channel_list_density`` ends by re-reading the Style menu's ticks
    from config (``_sync_style_menu_state``), so any skeleton host driving that
    seam needs the groups to exist. Real ``QActionGroup``/``QAction`` objects,
    so the caller needs a ``QApplication``.

    Repairing it here rather than with a ``hasattr`` in production is the point:
    in the real window ``_build_style_menu`` always runs during ``setup_ui``,
    long before anything can apply a density, so a production guard would only
    hide a genuine init-order bug.

    Args:
        host: A ``MainWindow``-shaped double (``__new__``/``SimpleNamespace``).
    """
    from PyQt6.QtGui import QAction, QActionGroup

    def _group(values):
        group = QActionGroup(None)
        group.setExclusive(True)
        for value in values:
            action = QAction(value, None, checkable=True)
            action.setData(value)
            group.addAction(action)
        return group

    from metatv.gui.main_window import MainWindow

    host._theme_action_group = _group(["Midnight", "Graphite", "Daylight"])
    host._density_action_group = _group(["compact", "comfy", "comfy_plus"])
    host._platform_action_group = _group(["auto", "full", "short"])
    host._thumbs_action = QAction("Poster thumbnails", None, checkable=True)
    # Bind the REAL sync, not a stub: a host driving the density seam should
    # exercise the tick-syncing it now does, otherwise this factory would hide
    # the very regression the seam was changed to prevent.
    host._sync_style_menu_state = MainWindow._sync_style_menu_state.__get__(host)


# Every handler MainWindow connects to ``SettingsDialog.settings_applied``.
# Hand-listing these on each test double is what made three separate slices go
# red (#380/#383 density, #387 collapse-variants, #389 theme) — each time the
# fix was one more stub in one more file. One factory instead.
_SETTINGS_APPLIED_HOOKS = (
    "_apply_sidebar_visibility",
    "_refresh_recommendation_views",
    "_apply_channel_list_density",
    "_apply_sidebar_row_density",
    "refresh_theme",
    "_apply_collapse_variants_setting",
    "_apply_adult_mode_setting",
    "_sync_split_toggle",
    "_apply_menu_bar_setting",
    "_refresh_vod_alerts_section",
    "_restart_series_monitor_scheduler",
)


def wire_settings_dialog_hooks(host, **overrides) -> None:
    """Attach no-op stubs for every ``settings_applied`` handler to *host*.

    ``MainWindow.open_settings`` connects each of these before showing the
    dialog, so a skeleton host missing one raises as soon as OK or Apply fires.

    Args:
        host: A ``MainWindow``-shaped double.
        **overrides: Replace a hook with a real callable (e.g. a recorder) —
            anything not overridden becomes a no-op.
    """
    for name in _SETTINGS_APPLIED_HOOKS:
        setattr(host, name, overrides.get(name, lambda *a, **k: None))
    for name, fn in overrides.items():
        setattr(host, name, fn)


def wire_settings_playback_widgets(dlg) -> None:
    """Attach the Settings → Playback tab's Network group widgets to a skeleton dialog.

    Builds **real** Qt widgets, so the caller must already have a QApplication
    (the module ``qapp`` fixture). Qt-free skeletons want
    :func:`mock_settings_playback_widgets` instead.

    Six settings tests build ``SettingsDialog`` via ``__new__`` and hand-wire only
    the widgets ``_load_values``/``_save_values`` touch — so every widget added to
    the Playback Network group breaks all six at once until each one grows the same
    stubs. Keeping this group in one factory (mirrors ``wire_settings_recommendation_widgets``)
    makes the next Playback widget a single edit here instead of six near-identical copies.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from PyQt6.QtWidgets import QCheckBox

    dlg._recheck_failed_on_refresh_check = QCheckBox()
    dlg._recheck_failed_on_refresh_check.setChecked(True)


def wire_settings_content_widgets(dlg) -> None:
    """Attach the Settings → Content tab's widgets to a skeleton dialog.

    Same shape, and same reason, as :func:`wire_settings_playback_widgets`:
    ``_load_values``/``_save_values`` touch every tab's widgets, so a skeleton
    ``SettingsDialog.__new__`` missing one raises the moment either runs. And it
    raises loudly rather than quietly — the skeleton never ran ``QDialog.__init__``,
    so sip raises ``RuntimeError: super-class __init__() of type SettingsDialog
    was never called`` instead of the ``AttributeError`` a ``hasattr`` guard
    would absorb.

    Adding ``_adult_mode_combo`` to the Content tab broke **37 tests across six
    files** that the PR never touched — the exact blind spot the local
    ``--quick`` gate has by construction, and CI caught it. One factory makes
    the next Content widget a single edit here.

    Args:
        dlg: A ``SettingsDialog`` built via ``__new__`` (no ``__init__`` run).
    """
    from PyQt6.QtWidgets import QComboBox

    dlg._adult_mode_combo = QComboBox()
    dlg._adult_mode_combo.addItem("Show everything", userData="all")
    dlg._adult_mode_combo.addItem("Hide adult content", userData="hide")
    dlg._adult_mode_combo.addItem("Show only adult content", userData="only")


# ---------------------------------------------------------------------------
# MainWindow channel-render skeleton stubs
# ---------------------------------------------------------------------------

def first_chip_row(list_widget):
    """The first CHANNEL row in a sidebar list, skipping any group heading.

    Three test modules defined this as "the first item that has a widget",
    which was right while headings were plain item text. History now renders
    ``GroupHeading`` widgets ("Today", "Older") through ``setItemWidget``, so
    that definition returns a HEADING and every assertion about the row then
    fails somewhere far away — ``AttributeError: 'NoneType' object has no
    attribute 'text'``, in a file the change never touched.

    A heading is identified by its bucket role rather than by widget type, so a
    section that grows a different heading widget still works.

    Args:
        list_widget: A ``QListWidget`` populated by a sidebar section.

    Returns:
        The first row widget, or ``None`` when the list holds no channel rows.
    """
    from PyQt6.QtCore import Qt

    role_bucket = Qt.ItemDataRole.UserRole + 8
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        if item.data(role_bucket) is not None:
            continue                      # a time-group heading, not a row
        widget = list_widget.itemWidget(item)
        if widget is not None:
            return widget
    return None


def wire_channel_banner_widgets(win) -> None:
    """Attach the banner widgets ``_hide_channel_banners`` resets to a skeleton window.

    Four test modules build ``MainWindow`` via ``__new__`` and hand-wire only the
    widgets the channel-render path touches. ``_hide_channel_banners()`` is the
    single reset point every render pass starts from, so **every** banner added
    there breaks all four at once — and it fails loudly rather than quietly: a
    skeleton ``MainWindow`` never ran ``QMainWindow.__init__``, so an attribute
    missing from ``__dict__`` does not raise the ``AttributeError`` that
    ``hasattr`` would absorb. sip raises ``RuntimeError: super-class __init__()
    of type MainWindow was never called`` instead, and the guard itself explodes.
    Keeping the group in one factory (mirrors ``wire_settings_playback_widgets``)
    makes the next banner a single edit here instead of four near-identical copies.

    Builds **real** Qt widgets, so the caller must already have a QApplication.

    Args:
        win: A ``MainWindow`` built via ``__new__`` (no ``__init__`` run).
    """
    from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

    win._channel_banner = QLabel()
    # Unparented so isVisible() reflects each widget's own flag in a headless env.
    win._channel_filter_bar = QWidget()
    win._channel_exclusion_btn = QPushButton()
    win._channel_filter_btn = QPushButton()
    # Segment 5 of the transparency bar. Guarded by __dict__.get in production
    # (so its absence is survivable), but wired here so a test can assert the
    # adult-gate notice actually renders instead of silently no-opping.
    win._channel_adult_btn = QPushButton()
    win._no_sources_banner = QWidget()


def wire_hide_channel_banners(host) -> None:
    """Give a skeleton nav host the ``_hide_channel_banners`` method.

    ``_NavMixin._hide_all_content_views()`` resets the channel-render banners
    (the "N hidden by Global Exclusions" bar and friends) because they live in
    ``_list_layout`` rather than inside any view, so blanking the views alone
    used to leave them stranded over an unrelated view. The method itself is
    defined on ``_ChannelListMixin``; the real ``MainWindow`` inherits both
    mixins, but the several test modules that exercise navigation build a
    ``_NavMixin`` (or a hand-rolled ``_FakeHost``) in isolation and therefore
    do not get it.

    Binds the REAL implementation rather than a ``MagicMock`` so the banners
    are genuinely hidden and a regression in that method still surfaces through
    the nav tests. It is safe on a bare skeleton: the method guards each widget
    with ``self.__dict__.get`` — not ``hasattr``, which does not absorb the
    ``RuntimeError`` PyQt raises for attribute access on a ``__new__``'d
    ``MainWindow``.

    Kept here rather than repeated per module for the same reason as
    ``wire_channel_banner_widgets``: the next widget added to that reset point
    breaks every one of these hosts at once, and one factory makes that a
    single edit.

    Args:
        host: Any object standing in for ``MainWindow`` in a nav test.
    """
    from metatv.gui.main_window_channels import _ChannelListMixin

    host._hide_channel_banners = _ChannelListMixin._hide_channel_banners.__get__(host)


def wire_header_search_sync(host) -> None:
    """Give a skeleton nav host ``_sync_header_search_visibility``.

    The V3 header owns the search box, and the three places that show/hide the
    content-area controls row now keep the header's box in step with it — the
    box filters the channel list, so it is meaningless on EPG, Recommended,
    Discover and Recipe.

    Those three call sites live in ``_NavMixin``; the method lives on
    ``MainWindow``. The real window has both, but the nav tests build a bare
    ``_NavMixin`` via ``__new__`` and therefore do not — which is the same
    shape of break CLAUDE.md records for ``_hide_channel_banners``, and the
    same fix: repair at this factory, never with a ``hasattr`` guard in
    production, which would mask a genuinely missing method in the real window.

    Binds the REAL implementation, so a regression in it still surfaces here.
    It is safe on a skeleton: the method guards with ``hasattr(self,
    "search_input")`` on a plain attribute the skeleton simply lacks.

    Args:
        host: Any object standing in for ``MainWindow`` in a nav test.
    """
    from metatv.gui.main_window import MainWindow

    host._sync_header_search_visibility = (
        MainWindow._sync_header_search_visibility.__get__(host)
    )


def wire_filter_chip_host(host) -> None:
    """Give a skeleton host the filter-chip methods ``MainWindow`` mixes in.

    Same shape of break as ``wire_header_search_sync`` above, and the same fix.
    Two families of skeleton need this:

    * the nav tests, which build a bare ``_NavMixin`` via ``__new__`` — the
      channel-list restore path now asks ``_apply_filter_ui_mode`` which
      presentation is current, instead of forcing the Includes column visible;
    * the Layout-menu tests, which hang real menu handlers on a plain
      ``QMainWindow`` — the menu now carries a "Filters as chips" entry, and
      building the menu connects it.

    Binds the REAL implementations, so a regression in them still surfaces in
    those files. They are safe on a skeleton: every one reaches its
    collaborators through ``self.__dict__.get`` (PyQt raises ``RuntimeError``,
    not ``AttributeError``, for attribute access on a ``__new__``'d QObject, so
    ``hasattr`` would not absorb it) and returns early when the panel is absent.

    Args:
        host: Any object standing in for ``MainWindow``.
    """
    from metatv.gui.filter_chip_host import _FilterChipHostMixin

    # These methods ask config which presentation is current. A skeleton built
    # by ``__new__`` has no config at all, so supply a minimal stand-in rather
    # than teaching production code to cope with a host that has none — the
    # real window always does.
    if "config" not in host.__dict__:
        host.config = SimpleNamespace(
            filter_ui_mode="chips",
            filter_section_visible=True,
            filter_panel_width=220,
            save=lambda: None,
        )

    for name in (
        "filter_ui_mode", "toggle_filter_ui_mode", "_apply_filter_ui_mode",
        "_shut_column_at_launch", "_set_filter_panel_width",
        "_sync_filter_chips", "_on_filter_chip_removed",
        "_on_filter_chip_add", "_on_filter_chip_clear",
    ):
        setattr(host, name, getattr(_FilterChipHostMixin, name).__get__(host))


def wire_shutdown_flag(host):
    """Set the shutdown flag ``MainWindow.__init__`` sets, on a bare skeleton.

    ``validate_and_failover_stream_url`` (main_window_streaming.py),
    ``_on_preflight_done`` (main_window_series.py), and ``on_metadata_loaded``
    (main_window_metadata.py) all read ``self._shutting_down`` — set ``False``
    in ``MainWindow.__init__``, ``True`` by ``closeEvent`` — to abandon
    in-flight background work rather than emit a Qt signal into a destroyed
    window or query a closed database. A skeleton built via
    ``Mixin.__new__(Mixin)`` never runs ``__init__`` and therefore lacks the
    attribute, so any test that drives one of those three real methods needs
    it wired in first — here, once, rather than duplicated across every test
    module's local ``_make_mixin``/``_build_launch_host`` helper (mirrors
    ``wire_channel_banner_widgets`` above).

    Args:
        host: Any skeleton test double standing in for ``MainWindow`` or one
            of its mixins (``_StreamingMixin``, ``_SeriesMixin``, ...).

    Returns:
        The same host, so callers can chain
        (``obj = wire_shutdown_flag(Cls.__new__(Cls))``).
    """
    host._shutting_down = False
    return host


def wire_watch_queue_section(sec, rendered: list) -> None:
    """Attach what ``WatchQueueSection._populate_rows`` touches to a skeleton section.

    ``_populate_rows`` is the queue's single render path, so a test that wants to
    assert ordering has to reach it — but the section is normally built by the
    sidebar and a ``__new__`` shell never ran ``QWidget.__init__``. Missing
    attributes then raise ``RuntimeError: super-class __init__() ... was never
    called`` rather than the ``AttributeError`` a ``hasattr`` guard absorbs, so
    the failure lands inside the method under test rather than in setup.

    Kept here rather than in the test module because every future assertion about
    queue rendering needs the same shell, and CLAUDE.md's rule is that skeleton
    hosts are repaired at the shared factory — never with defensive getattr in
    production code, which would mask real bugs.

    Args:
        sec: A ``WatchQueueSection`` built via ``__new__`` (no ``__init__`` run).
        rendered: List the stubs append to — ``("HEADER", text)`` / ``("ROW", name)``
            tuples in render order, which is what the caller asserts on.
    """
    class _List:
        def clear(self):
            rendered.clear()

        def addItem(self, item):
            rendered.append(item)

        def count(self):
            return len(rendered)

    class _Item:
        """Stand-in for the QListWidgetItem the real builders return.

        ``_populate_rows`` now hands every header and row it creates to the
        find-in-queue filter, which calls ``setHidden``/``setText`` on them. The
        stubs therefore have to RETURN something item-shaped: returning None
        made the filter pass fail inside the method under test.
        """

        def __init__(self, text=""):
            self._text = text
            self._hidden = False

        def setHidden(self, hidden):
            self._hidden = hidden

        def isHidden(self):
            return self._hidden

        def setText(self, text):
            self._text = text

        def text(self):
            return self._text

    def _header(text):
        rendered.append(("HEADER", text))
        return _Item(text)

    def _row(e):
        rendered.append(("ROW", e.channel_name))
        return _Item(e.channel_name)

    sec._list = _List()
    wire_watch_queue_filter(sec)
    sec._add_header = _header
    sec._add_entry_item = _row
    sec.update_new_match_count = lambda *a, **k: None
    sec.set_empty = lambda *a, **k: None


def wire_watch_queue_filter(sec) -> None:
    """Attach the find-in-queue state ``WatchQueueSection._populate_rows`` needs.

    Every render ends by re-applying the live filter text, so ANY skeleton
    section that reaches ``_populate_rows`` needs an unfiltered box and the
    group bookkeeping — including the several test modules that build their own
    ``__new__`` shell around a REAL ``QListWidget`` to assert on rendered rows.

    Split out from :func:`wire_watch_queue_section` (which supplies a fake list)
    so those real-widget hosts can call just this part. CLAUDE.md's rule holds
    either way: skeleton hosts are repaired at the shared factory, never with
    defensive ``getattr`` in production code.
    """
    sec._filter = SimpleNamespace(text=lambda: "")
    sec._groups = []


# ---------------------------------------------------------------------------
# ChannelStateBus test host
# ---------------------------------------------------------------------------

def attach_channel_state_bus(host, reread=None):
    """Give a ``MainWindow`` test double the ``ChannelStateBus`` its mutations publish to.

    Every per-channel mutation handler (``_toggle_rating``,
    ``_toggle_favorite_by_id``, ``_not_interested``) now ends in
    ``self.channel_state_bus.publish(...)``, so ANY test double that drives one
    of those real methods needs the attribute or dies with ``AttributeError`` --
    which is what happened to ``test_details_rating_row.py``'s ``SimpleNamespace``
    host. Guarding the production call with ``hasattr`` would hide a genuinely
    missing bus at runtime, so the repair lives here in the shared factory
    instead (CLAUDE.md: "repair at the shared factory, never with defensive
    getattr/hasattr in production").

    Safe on a ``SimpleNamespace`` host: only ``subscribe()`` needs a weakly
    referenceable owner, and this wires a bus with no subscribers.

    Args:
        host: The test double to wire.
        reread: Optional tier-2 authoritative re-read, invoked with a
            ``channel_id``. Defaults to a no-op, which is what a test that only
            asserts the mutation's own DB effect wants.

    Returns:
        The same host, so callers can chain.
    """
    from metatv.gui.channel_state_bus import ChannelStateBus

    host.channel_state_bus = ChannelStateBus(reread=reread or (lambda channel_id: None))
    return host


def make_channel_state_bus_host(db_obj):
    """Build a MainWindow stand-in wired for ChannelStateBus tests.

    Binds the REAL ``_FavoritesMixin``/``_MetadataMixin`` mutation and
    action-state methods to a bare host object instead of a
    ``MainWindow.__new__()`` skeleton — no QObject is involved, so there is
    nothing for a future ``MainWindow.__init__`` addition to leave stranded
    (the ``RuntimeError``-not-``AttributeError`` trap ``wire_channel_banner_widgets``
    above describes). Mirrors the ``SimpleNamespace`` + unbound-mixin-method
    pattern ``test_provider_delete_offthread.py``'s ``_seam_self`` uses to drive
    the real off-thread seam deterministically — except the host is a plain
    class instance, not a ``SimpleNamespace``: ``ChannelStateBus.subscribe``
    holds callbacks via ``weakref.WeakMethod``, and ``types.SimpleNamespace``
    does not support being weakly referenced (``TypeError: cannot create weak
    reference to 'types.SimpleNamespace' object``), so a real subscription
    would fail before the seam even runs.

    Covers every per-channel mutation handler that publishes to the bus as of
    phase 2 (#312): rating (``_toggle_rating``), favorite (``_toggle_favorite_by_id``,
    ``_apply_favorite_toggle`` + ``toggle_favorite_by_id``), suppression
    (``_not_interested``), hidden (``_hide_channel_from_history``,
    ``_hide_channel_from_alerts``, ``_hide_channel_from_recommendations``,
    ``_unhide_channel``), and queue (``_add_to_queue``, ``_remove_from_queue``,
    ``_on_details_queue_toggle``).
    List-membership refreshes those handlers call (``load_favorites``,
    ``load_history``, ``load_channels``, ``_refresh_watch_alerts``,
    ``_refresh_queue_section``, ``_remove_sidebar_row``) are wired as inert
    no-op doubles here — they're a different grain than the bus and this host
    only needs them to exist, not to do anything.

    The fake executor runs submitted work inline, so ``ChannelStateBus``'s
    tier-2 authoritative reread (which submits to ``self.executor``, exactly as
    production does) resolves synchronously; the fake ``_action_state_loaded``
    "signal" calls the slot directly in place of the real cross-thread Qt
    signal emit.

    Args:
        db_obj: A real ``Database`` (CLAUDE.md: tests use a real ``Database``
            on a ``tmp_path`` file, never ``:memory:``).

    Returns:
        A host object with a real ``channel_state_bus``, the real mutation
        handlers bound, and ``details_pane`` as a recording double exposing
        ``applied_states`` (the ``ChannelActionState`` objects
        ``apply_action_state`` received, in call order).
    """
    from metatv.gui.channel_state_bus import ChannelStateBus
    from metatv.gui.main_window_favorites import _FavoritesMixin
    from metatv.gui.main_window_metadata import _MetadataMixin

    class _InlineExecutor:
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return None

    class _DetailsPaneDouble:
        def __init__(self):
            self.applied_states = []

        def apply_action_state(self, state):
            self.applied_states.append(state)

    class _Host:
        """Plain class (not SimpleNamespace) so it supports weakref.WeakMethod."""

    host = _Host()
    host.db = db_obj
    host.executor = _InlineExecutor()
    host.view_mode = "channels"
    host.config = SimpleNamespace(epg_link_blocklist=[])
    host.preferences_view = SimpleNamespace(refresh=lambda: None)
    host._refresh_recommended_section = lambda: None
    host.details_pane = _DetailsPaneDouble()

    # Inert list-membership-refresh doubles — a different grain than the bus;
    # these handlers call them alongside (never instead of) publish(), and this
    # host only needs them to exist, not to render anything.
    host.load_favorites = lambda: None
    host.load_history = lambda: None
    host.load_channels = lambda: None
    host._refresh_watch_alerts = lambda: None
    host._refresh_queue_section = lambda: None
    host._remove_sidebar_row = lambda section_key, key: None
    host.status_bar = SimpleNamespace(showMessage=lambda *a, **k: None)

    host._toggle_rating = _FavoritesMixin._toggle_rating.__get__(host)
    host._toggle_favorite_by_id = _FavoritesMixin._toggle_favorite_by_id.__get__(host)
    host._not_interested = _FavoritesMixin._not_interested.__get__(host)
    host._on_channel_state_echo = _FavoritesMixin._on_channel_state_echo.__get__(host)
    host._apply_favorite_toggle = _FavoritesMixin._apply_favorite_toggle.__get__(host)
    host.toggle_favorite_by_id = _FavoritesMixin.toggle_favorite_by_id.__get__(host)
    host._hide_channel_from_history = _FavoritesMixin._hide_channel_from_history.__get__(host)
    host._hide_channel_from_alerts = _FavoritesMixin._hide_channel_from_alerts.__get__(host)
    host._add_to_queue = _FavoritesMixin._add_to_queue.__get__(host)
    host._remove_from_queue = _FavoritesMixin._remove_from_queue.__get__(host)
    host._on_details_queue_toggle = _FavoritesMixin._on_details_queue_toggle.__get__(host)
    host._on_action_state_requested = _MetadataMixin._on_action_state_requested.__get__(host)
    host._bg_fetch_action_state = _MetadataMixin._bg_fetch_action_state.__get__(host)
    host._on_action_state_loaded = _MetadataMixin._on_action_state_loaded.__get__(host)
    host._hide_channel_from_recommendations = (
        _MetadataMixin._hide_channel_from_recommendations.__get__(host)
    )
    host._unhide_channel = _MetadataMixin._unhide_channel.__get__(host)

    host._action_state_loaded = SimpleNamespace(
        emit=lambda state: host._on_action_state_loaded(state)
    )

    host.channel_state_bus = ChannelStateBus(reread=host._on_action_state_requested)
    host.channel_state_bus.subscribe(host._on_channel_state_echo)

    return host


# ═══════════════════════════════════════════════════════════════════════════
# V3 channel-row paint harness
#
# Every row test drives the REAL ``ChannelRowDelegate.paint`` through a REAL
# model index — never a density-specific private painter and never a MagicMock
# index. That matters twice over: ``paint`` is where ``row_layout`` is called
# and where selection/hover reach the row at all, so a test that skips it can
# assert neither the geometry nor the state behaviour it claims to.
#
# Two capture modes, because "rendered appearance" means two different things:
#
#   ``paint_channel_row``  — GEOMETRY. Intercepts the delegate's two draw
#       chokepoints and records the QRect handed to each, so a test can assert
#       where something landed.
#   ``render_channel_row`` — PIXELS. Paints onto a real QPixmap and hands back
#       an image, so a test can assert the colour that actually reached the
#       screen (chrome fills, the marker bar) rather than the token that was
#       supposed to produce it.
# ═══════════════════════════════════════════════════════════════════════════

#: Every role the V3 row reads, with a value that renders. Tests override just
#: the fields they are about — one dict, so a role added to the row later shows
#: up in every test's data instead of being silently absent from most of them.
ROW_ROLE_DEFAULTS: dict[str, object] = {
    "ROW_KIND_ROLE": "channel",
    "MEDIA_KIND_ROLE": "movie",
    "TITLE_ROLE": "The Murky Stream",
    "YEAR_ROLE": "2024",
    "GENRES_ROLE": ("Drama", "Thriller"),
    "GENRE_ROLE": "Drama",
    "COLLECTION_ROLE": "KOREAN DRAMA",
    "CATEGORY_ROLE": "KR | KOREAN DRAMA",
    "QUALITY_TOKEN_ROLE": "4K",
    "LANGUAGE_ROLE": "KR",
    "PRIMARY_LANGUAGE_ROLE": "EN",
    "SECONDARY_LANGUAGE_ROLE": "",
    "SUBTITLE_MARKER_ROLE": "",
    "VARIANT_COUNT_ROLE": 1,
    "POSTER_URL_ROLE": "",
    "PLOT_ROLE": "",
    "FAV_GLYPH_ROLE": "",
    "PLAYBACK_GLYPH_ROLE": "",
    "PLAYBACK_GLYPH_COLOR_ROLE": None,
    "MATCH_MARKER_ROLE": "",
    # Sports facets. EMPTY by default on purpose: every existing row here is a
    # movie, and a non-empty sport would add a cell to its meta line and move
    # the geometry every other test in this file measures. Empty means "no
    # cell", so the default row is byte-identical and a sports test overrides.
    "SPORT_ROLE": "",
    "LEAGUE_ROLE": "",
}


def row_model(*rows, **overrides):
    """A real one-column list model over *rows* (dicts of role-name → value).

    Called with no rows, yields a single row from :data:`ROW_ROLE_DEFAULTS`
    updated with **overrides — the common case.
    """
    from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt

    import metatv.gui.channel_list_delegate as _d

    records = [dict(ROW_ROLE_DEFAULTS, **r) for r in rows] or [
        dict(ROW_ROLE_DEFAULTS, **overrides)
    ]
    lookup = {getattr(_d, name): name for name in ROW_ROLE_DEFAULTS}

    class _Model(QAbstractListModel):
        def rowCount(self, parent=QModelIndex()):  # noqa: N802
            return len(records)

        def data(self, index, role=Qt.ItemDataRole.DisplayRole):
            name = lookup.get(role)
            return records[index.row()].get(name) if name else None

    return _Model()


class PaintedRow:
    """What one row's ``paint()`` actually drew, with geometry."""

    def __init__(self) -> None:
        #: (rect, text, colour, font) per plain text run.
        self.texts: list = []
        #: (rect, _Cell) per cell — meta segments and rail chips alike.
        self.cells: list = []

    @property
    def all_foregrounds(self) -> list:
        return [c for _, _, c, _ in self.texts] + [cell.fg for _, cell in self.cells]

    def cell(self, text: str):
        """The cell whose text is *text*, or None."""
        return next((c for _, c in self.cells if c.text == text), None)

    def rect_of(self, text: str):
        """Painted rect for *text*, whether it was drawn as a run or a cell."""
        for rect, drawn, _, _ in self.texts:
            if drawn == text:
                return rect
        for rect, cell in self.cells:
            if cell.text == text:
                return rect
        raise AssertionError(
            f"{text!r} was never painted; painted: "
            f"{[t for _, t, _, _ in self.texts] + [c.text for _, c in self.cells]}"
        )

    def painted(self, text: str) -> bool:
        try:
            self.rect_of(text)
        except AssertionError:
            return False
        return True


def _row_option(rect, *, selected=False, hovered=False):
    from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem

    from metatv.gui import theme as _theme

    opt = QStyleOptionViewItem()
    opt.rect = rect
    opt.state = QStyle.StateFlag.State_Enabled
    if selected:
        opt.state |= QStyle.StateFlag.State_Selected
    if hovered:
        opt.state |= QStyle.StateFlag.State_MouseOver
    opt.palette = _theme.qt_palette()
    return opt


def paint_channel_row(delegate, index, *, rect=None, selected=False, hovered=False,
                      density=None) -> PaintedRow:
    """Run the REAL ``paint()`` and record every rect it drew into."""
    from unittest.mock import MagicMock

    from PyQt6.QtCore import QRect

    if density is not None:
        delegate.set_density(density)
    rect = rect if rect is not None else QRect(0, 0, 620, 68)

    out = PaintedRow()
    original_text, original_cell = delegate._draw_text, delegate._paint_cell
    delegate._draw_text = (
        lambda p, r, text, color, font: out.texts.append((QRect(r), text, color, font))
    )
    delegate._paint_cell = lambda p, r, cell, font: out.cells.append((QRect(r), cell))
    try:
        delegate.paint(MagicMock(), _row_option(rect, selected=selected, hovered=hovered),
                       index)
    finally:
        delegate._draw_text, delegate._paint_cell = original_text, original_cell
    return out


def render_channel_row(delegate, index, *, rect=None, selected=False, hovered=False,
                       density=None, background=None):
    """Paint one row onto a real ``QPixmap`` and return its ``QImage``.

    The background is filled first, because the row paints only its own chrome —
    a transparent pixmap would make every "what colour is this pixel" assertion
    a measurement of nothing.
    """
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QColor, QPainter, QPixmap

    from metatv.gui import theme as _theme

    if density is not None:
        delegate.set_density(density)
    rect = rect if rect is not None else QRect(0, 0, 620, 68)
    pixmap = QPixmap(rect.width(), rect.height())
    pixmap.fill(QColor(background if background is not None else _theme.COLOR_BG_DEEP))
    painter = QPainter(pixmap)
    try:
        delegate.paint(painter, _row_option(rect, selected=selected, hovered=hovered), index)
    finally:
        painter.end()
    return pixmap.toImage()


def wire_nav_host(host) -> None:
    """Give a bare ``_NavMixin`` double the cross-cutting bits every switch touches.

    ``_hide_all_content_views`` is the seam EVERY view switch passes through, so
    anything it reaches becomes a requirement of every nav double at once — and
    the doubles are hand-built, one per test file, each listing the attributes
    its own test happened to need. Adding one line to that seam therefore breaks
    a dozen files that never mentioned it: clearing the stale status line
    (#490) took out 42 tests across nine files, none of which the PR touched.

    So the attributes live HERE, in one helper the builders call, exactly as
    ``wire_channel_banner_widgets`` and ``wire_hide_channel_banners`` already
    do. The alternative — a ``hasattr`` guard in ``_hide_all_content_views`` —
    is forbidden for a good reason: on a ``__new__``'d QObject ``hasattr``
    raises ``RuntimeError`` rather than returning False, so the guard explodes
    where it is most needed.

    Safe to call on a double that already set some of these: nothing is
    overwritten, so a test that wants its own spy keeps it.

    Args:
        host: A ``_NavMixin`` (or ``_FakeHost``) built without
            ``MainWindow.__init__``.
    """
    from unittest.mock import MagicMock

    # The status line. Cleared on every switch so a view never wears the
    # previous view's message.
    if "status_bar" not in host.__dict__:
        host.status_bar = MagicMock()

    # The series Back/breadcrumb bar. Hidden as a UNIT outside series view —
    # it used to be added to the content column unconditionally with only its
    # contents hidden, which cost every other view a blank row.
    if "_series_nav_bar" not in host.__dict__:
        host._series_nav_bar = MagicMock()
    if "back_button" not in host.__dict__:
        host.back_button = MagicMock()
    if "breadcrumb_label" not in host.__dict__:
        host.breadcrumb_label = MagicMock()
    if "series_icon" not in host.__dict__:
        host.series_icon = "S"

#: Holds the QApplication for the whole process. See _bundled_ui_font.
_SESSION_QAPP = None


@pytest.fixture(scope="session", autouse=True)
def _bundled_ui_font():
    """Measure the font the APP renders, not the platform's default.

    Every widget test that asserts a width, a height or an elision is measuring
    text, and text metrics are a property of the FACE. Without this the suite
    measured whatever face the platform happened to default to — and the same
    token rendered three different heights across three machines:

        dev Linux 18px   ·   macOS CI 16px   ·   Ubuntu CI 15px

    which is why a pixel floor written on one machine failed on the other two,
    twice, and why two width assertions passed locally and failed in CI on
    their first run.

    ``__main__.py`` calls ``apply_ui_font`` before constructing anything, so
    Inter is what the app actually draws with. Tests that measured Sans Serif
    were measuring an app that does not exist. This makes the suite both
    deterministic AND more faithful, which is a rare pairing.

    Session-scoped and autouse: the application font is process-global, so it
    must be set before the first widget is constructed and it never needs
    setting twice. A no-op if the bundled face fails to load — a missing
    typeface should cost determinism, not the whole suite.
    """
    from PyQt6.QtWidgets import QApplication

    from metatv.gui import fonts as _fonts

    global _SESSION_QAPP
    # PINNED to a module global, and that is not decoration. A local here is the
    # last strong Python reference to the QApplication, so finalising this
    # generator at session end destroys the C++ QApplication while other Qt
    # wrappers are still alive. The next wrapper touched calls
    # sip_api_get_address on freed memory and the process dies with SIGSEGV —
    # AFTER every test has passed, so the run reports "N passed" and then exits
    # 139. It is intermittent because it depends on garbage-collection order.
    #
    # Cost three CI shards and two PRs before the C stack named it.
    _SESSION_QAPP = QApplication.instance() or QApplication([])
    _fonts.apply_ui_font(_SESSION_QAPP)
    yield

    # ORDERED SHUTDOWN, because interpreter finalization is not ordered.
    #
    # The suite crashed with SIGSEGV *after every test passed* — the run printed
    # "N passed" and then exited 139. The C stack had NO Python frame and sat
    # under Py_RunMain, i.e. inside interpreter finalization, in Qt destructor
    # territory: module globals are cleared in arbitrary order, so the
    # QApplication can be destroyed while other Qt objects still exist, and the
    # first one destroyed afterwards dereferences a dead application.
    #
    # Three earlier fixes all targeted fixture teardown and all failed, because
    # this crash is not in a fixture. Doing the teardown HERE — in a session
    # fixture, which runs before finalization — makes the order explicit
    # instead of leaving it to whatever order the interpreter picks.
    from PyQt6 import sip

    for widget in QApplication.topLevelWidgets():
        if not sip.isdeleted(widget):
            sip.delete(widget)          # per-object; never a global event flush
    _SESSION_QAPP.processEvents()
    _SESSION_QAPP = None                # release ours before finalization runs


def make_provider_load_thread(db, provider_id: str, provider_name: str = "Test Source"):
    """A ``ProviderLoadThread`` skeleton for driving its worker-thread methods.

    ``__new__`` skips ``QThread.__init__``, which is what makes the object cheap
    and also what makes ``self.progress.emit`` raise ``RuntimeError`` — the
    class absorbs that in ``_try_emit_progress`` specifically for this path.

    It lives here rather than in each test file because the alternative is a
    hand-rolled stub per suite, and a hand-rolled stub is missing whatever the
    method under test touches next (CLAUDE.md: "Test doubles that skip
    ``__init__`` — wire them from ``tests/conftest.py``"). A ``SimpleNamespace``
    fails immediately on ``_try_emit_progress``; the real class does not.

    Args:
        db: A ``Database`` instance the method should read and write.
        provider_id: The ``ProviderDB.id`` whose channels are in scope.
        provider_name: Only used in log lines.

    Returns:
        A ``ProviderLoadThread`` with ``db`` and ``provider`` set.
    """
    from unittest.mock import MagicMock

    from metatv.core.provider_loader import ProviderLoadThread

    provider = MagicMock()
    provider.id = provider_id
    provider.name = provider_name

    thread = ProviderLoadThread.__new__(ProviderLoadThread)
    thread.db = db
    thread.provider = provider
    return thread


def wire_sidebar_membership(host, *, shows: bool = False) -> None:
    """Give a skeleton playback host the sidebar-membership seam a play now uses.

    Starting playback used to rebuild Favorites and the Watch Queue every time,
    for a channel that was usually in neither — the owner's "the watch queue
    completely reloads when switching content not even in the watch queue". It
    now asks ``_sidebar_shows_channel`` first.

    That method lives on ``_FavoritesMixin``, beside ``_remove_sidebar_row``
    which answers the same question for deletions. A real ``MainWindow`` has
    both mixins; a hand-built ``_StreamingMixin.__new__`` double has only one,
    so the seam is missing and the play path dies with ``AttributeError``. That
    is the same shape as ``wire_nav_host``: a cross-cutting seam whose
    requirements land on every hand-built double at once, three test files here
    that the change never touched.

    Wired HERE rather than guarded in production, because a ``hasattr`` on a
    ``__new__``'d QObject raises ``RuntimeError`` instead of returning False —
    the guard would explode where it was meant to protect.

    Args:
        host: The skeleton host to wire.
        shows: What the seam should answer. False (the default) is the common
            case — the channel is in neither list — and is what keeps a test
            from asserting against an incidental rebuild.
    """
    # Assigned outright, never via getattr/hasattr: on a ``__new__``'d QObject
    # BOTH raise ``RuntimeError`` rather than reporting absence, so a "read the
    # existing value if there is one" helper explodes on exactly the doubles it
    # exists to serve. (Written that way first; six tests said so.)
    host.sidebar_sections = {}
    host._sidebar_shows_channel = lambda section_key, channel_id: shows
    host.load_favorites = lambda: None
    host._refresh_queue_section = lambda: None


def make_channel_double(**overrides: object) -> "MagicMock":
    """A Channel-like double for the `_store_channels` bulk-upsert path.

    Why this is derived and not hand-listed
    ---------------------------------------
    A bare ``MagicMock()`` answers *every* attribute with another MagicMock,
    which SQLite cannot bind. So the moment `_CATALOG_COLS` gains a column, any
    double that did not happen to set that attribute dies with
    ``Error binding parameter N: type 'MagicMock' is not supported`` — and the
    double never warned anybody, because a mock's whole job is to say yes.

    That already happened once. ``test_channel_bulk_upsert.py`` carried the
    line ``ch.detected_tmdb_id = detected_tmdb_id`` under the comment *"explicit
    here so the mock is bindable"* — one file patched, the trap left armed, and
    three files' worth of it went red when ``epg_channel_id`` was added.

    So the defaults are read from ``_CATALOG_COLS`` itself: every column gets a
    bindable ``None`` unless named below. A column added tomorrow is covered
    the day it is added, by the same tuple production reads. This is CLAUDE.md's
    shared-factory rule and its derived-guard rule pointing the same way.

    Args:
        **overrides: Any channel attribute to set explicitly. ``quality`` is
            special-cased: pass the string (``quality="hd"``) and it is wrapped
            in the ``.value`` shape production reads.

    Returns:
        The configured double.
    """
    from unittest.mock import MagicMock

    from metatv.core.provider_loader import _CATALOG_COLS

    ch = MagicMock()
    for col in _CATALOG_COLS:
        setattr(ch, col, None)

    ch.raw_data = {}
    ch.media_type = "live"
    ch.stream_url = "http://example.com/stream"
    ch.category = "General"
    ch.category_id = "cat1"
    ch.logo_url = ""
    ch.name = "Test Channel"

    quality = overrides.pop("quality", "hd")
    ch.quality = MagicMock()
    ch.quality.value = quality

    for key, value in overrides.items():
        setattr(ch, key, value)
    return ch


def wire_details_action_buttons(poster, action_bar) -> None:
    """Reparent every _ActionBar button into its _PosterSection slot.

    The one place the argument list lives. Four test files each hand-wrote this
    call, so adding a twelfth button broke four files at once and the fix was
    the same edit copied four times — the enumeration failure CLAUDE.md names,
    in test clothing.

    Passing ``**vars``-style would hide a genuinely missing button, so the names
    stay explicit; they are just written once.

    Args:
        poster: A ``_PosterSection``.
        action_bar: An ``_ActionBar`` whose buttons get reparented into it.
    """
    poster.set_action_buttons(
        favorite=action_bar.favorite_button,
        play=action_bar.play_button,
        resume=action_bar.resume_button,
        queue=action_bar.queue_button,
        trailer=action_bar.trailer_button,
        like=action_bar.like_button,
        not_interested=action_bar.not_interested_button,
        dislike=action_bar.dislike_button,
        watchlist=action_bar.watchlist_button,
        monitor=action_bar.monitor_button,
        clear_epg_link=action_bar.clear_epg_link_button,
        hide=action_bar.hide_button,
    )


@pytest.fixture(autouse=True)
def _unbind_watchlist_store():
    """Detach the watch list from any database between tests.

    ``metatv.core.watchlist`` holds its ``Database`` in a MODULE-level binding,
    set once by ``MainWindow.__init__``. That is deliberate — the twenty-four
    call sites hold a ``Config`` and not all can reach a ``Database`` — but it
    means one test constructing a MainWindow leaves every LATER test reading
    that (empty) database instead of the config list it just populated.

    Found exactly that way: eight tests across two files passed alone and failed
    in a batch. Unbinding per test is the price of the binding, and it belongs
    here rather than repeated in every file that builds a window.

    The write-error handler is cleared for the same reason and a sharper one:
    ``MainWindow.__init__`` installs a ``WatchlistWriteNotifier``'s bound signal
    there, and a bound signal whose QObject has been torn down is a SEGFAULT
    when the next test's failed write emits into it — not an exception a test
    can report.
    """
    from metatv.core import watchlist

    watchlist.unbind()
    watchlist.set_write_error_handler(None)
    yield
    watchlist.unbind()
    watchlist.set_write_error_handler(None)


@pytest.fixture(autouse=True)
def _unbind_profile_store():
    """Detach the profile store from any database between tests.

    The same shape as ``_unbind_watchlist_store`` above, and it failed the same
    way before this existed: ``test_filter_opt_out`` and ``test_config_save_cost``
    passed alone and failed in the full suite, because ``test_app_header``
    constructs a real MainWindow, which calls ``attach_profile_store`` and leaves
    the store bound.

    The consequence is sharper here than for the watch list, which is why this
    is not optional. Once the store owns a key, ``Config.save`` deliberately
    keeps that key OUT of ``config.yaml`` — so a leaked binding does not merely
    make later tests read an empty database, it makes their ``save()`` silently
    drop 34 fields from the file they then read back. The failure surfaces as a
    round-trip assertion in a file that has nothing to do with any of this.

    ``unbind`` and not ``shutdown``: shutdown drains the writer but deliberately
    keeps ``_db`` and the owned set, because a late save in a closing app must
    still persist correctly. Only ``unbind`` clears the ownership, which is
    exactly what a test boundary needs and what a running app must never do.
    """
    from metatv.core import profile_store

    profile_store.unbind()
    yield
    profile_store.unbind()


def wire_epg_manager_skeleton(mgr, db, *, accountant=None) -> None:
    """Give an ``EpgManager.__new__`` double the fields its fetch path reads.

    ``EpgManager`` is a ``QObject``, so a double built with ``__new__`` never
    ran ``super().__init__()`` — and PyQt answers attribute access on such an
    object with ``RuntimeError: super-class __init__() ... was never called``,
    NOT the ``AttributeError`` a ``hasattr``/``getattr`` guard would absorb.
    The guard itself explodes, which is why the repair belongs here and never
    in production code.

    That is exactly how enrolling EPG in the connection accountant turned
    ``test_a_403_on_the_first_host_advances_and_is_remembered`` red on both
    platforms: ``_resolve_and_fetch_guide`` grew a ``_acquire_slot`` call,
    ``_acquire_slot`` reads ``self._accountant``, and the double set only
    ``db`` and ``_shutting_down``.

    One factory rather than per-module wiring, for the reason the sibling
    helpers exist: the NEXT field the fetch path acquires breaks every one of
    these doubles at once, and this makes that a single edit.

    Args:
        mgr: An ``EpgManager.__new__(EpgManager)`` skeleton.
        db: The ``Database`` the fetch path should read through.
        accountant: Optional ``ConnectionAccountant``. ``None`` (the default)
            is the documented headless case — ``_acquire_slot`` then grants
            unconditionally, so a test that is not about arbitration does not
            have to build one.
    """
    mgr.db = db
    mgr._shutting_down = False
    mgr._accountant = accountant
def wire_settings_signal_widgets(dlg) -> None:
    """Attach the Settings → Signal checking tab's widgets to a skeleton dialog.

    Same shape and same reason as its siblings: ``_load_values`` and
    ``_save_values`` touch every tab, so a skeleton missing one widget raises
    the moment either runs — and raises ``RuntimeError``, not the
    ``AttributeError`` a ``hasattr`` guard would absorb, because the skeleton
    never ran ``QDialog.__init__``. Adding ``_adult_mode_combo`` to the Content
    tab once broke 37 tests across six files this way.

    Args:
        dlg: A ``SettingsDialog.__new__`` skeleton.
    """
    from PyQt6.QtWidgets import QCheckBox, QSpinBox

    dlg._signal_sample_spin = QSpinBox()
    dlg._signal_sample_spin.setRange(1, 30)
    dlg._signal_black_spin = QSpinBox()
    dlg._signal_black_spin.setRange(10, 100)
    dlg._signal_pixel_spin = QSpinBox()
    dlg._signal_pixel_spin.setRange(1, 50)
    dlg._signal_freeze_spin = QSpinBox()
    dlg._signal_freeze_spin.setRange(1, 30)
    dlg._hide_dead_check = QCheckBox()
    dlg._signal_streak_spin = QSpinBox()
    dlg._signal_streak_spin.setRange(1, 10)


def wire_settings_widgets(dlg) -> None:
    """Attach EVERY settings tab's widgets to a skeleton dialog.

    Eight test files list the per-tab factories by hand, so a seventh tab meant
    editing all eight — and a file that missed the edit failed on a tab it had
    nothing to do with. This is the one call a NEW test should use; the existing
    hand-listed runs are left alone deliberately (collapsing them safely needs
    per-file import surgery, logged in the ledger rather than done with a
    regex that broke three files when tried).

    Args:
        dlg: A ``SettingsDialog.__new__`` skeleton.
    """
    wire_settings_playback_widgets(dlg)
    wire_settings_content_widgets(dlg)
    wire_settings_epg_widgets(dlg)
    wire_settings_recommendation_widgets(dlg)
    wire_settings_theme_widget(dlg)
    wire_settings_density_widget(dlg)
    wire_settings_signal_widgets(dlg)


def settings_config_double(**overrides):
    """A config for a Settings-dialog test that CANNOT drift from the model.

    ``_load_values`` and ``_save_values`` touch every field the dialog knows
    about, so a hand-written stub class breaks the day a tab gains a setting —
    on a test that has nothing to do with that tab. Five such stubs
    (``_FakeConfig``, ``_FakeDlgConfig``, ``_FakeSettingsConfig``,
    ``_FakeThresholdConfig``, ``_Cfg``) went red together when the Signal
    checking tab was added, in files that never mentioned signals.

    A real :class:`Config` cannot have that problem: pydantic fills every
    declared default, so a field added tomorrow is present here the same day.
    The autouse ``_isolate_user_config`` fixture already redirects
    ``Path.home()``, so constructing one touches no real user data.

    Args:
        **overrides: Any field to set explicitly.

    Returns:
        A real ``Config``.
    """
    from metatv.core.config import Config

    return Config(**overrides)


def wire_watchlist_card_host(host) -> None:
    """Give a stand-in host what ``_make_watchlist_item`` needs for the rule row.

    WL-1 slice 2 hung the Option B rule editor under each pattern card, so the
    card now reaches two more things on its host: ``_rule_counts`` (filled by
    the background read, empty until it lands) and ``_attach_rule_editor``.

    Two test files build such a host with ``SimpleNamespace``, which is exactly
    the "N copies" shape CLAUDE.md says to repair at the shared factory rather
    than with ``getattr`` defaults in production — a card that silently skipped
    its editor because an attribute was missing would hide the feature instead
    of failing.

    The bound method is taken off the real mixin, so a host wired here exercises
    the SAME code the app runs; only the state it reads is supplied.
    """
    from metatv.gui.epg_watchlist_mixin import _EpgWatchlistMixin

    host._rule_counts = {}
    host._attach_rule_editor = _EpgWatchlistMixin._attach_rule_editor.__get__(host)
    host._on_rule_changed = _EpgWatchlistMixin._on_rule_changed.__get__(host)


def with_programme_render_fields(cls):
    """Give a fake EPG programme class the fields the render path reads.

    WL-1 slice 2 let a watch rule search the programme DESCRIPTION, so the
    highlight test in Browse and On Now now passes ``prog.description`` and
    ``prog.is_live`` to the matcher. Three test files carry their own
    ``_FakeProg``/``_FakeProgram`` stub and 34 tests went red on the missing
    attribute.

    Fixed here rather than by adding a line to each stub — CLAUDE.md is
    explicit that this shape gets repaired at the shared factory, and equally
    explicit that it must NOT be papered over with ``getattr`` defaults in the
    render code, which would hide a real ``EpgProgramDB`` losing a column.

    Class-level defaults, so a stub whose ``__init__`` sets the field
    explicitly still wins.
    """
    for name, default in (("description", ""), ("is_live", False),
                          ("is_new", False)):
        if not hasattr(cls, name):
            setattr(cls, name, default)
    return cls
