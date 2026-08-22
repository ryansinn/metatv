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
    dlg._platform_name_style_combo = MagicMock()
    dlg._platform_name_style_combo.currentData.return_value = "auto"
    dlg._channel_thumbnails_check = MagicMock()
    dlg._channel_thumbnails_check.isChecked.return_value = True
    dlg._collapse_variants_check = MagicMock()
    dlg._collapse_variants_check.isChecked.return_value = False
    dlg._theme_combo = MagicMock()
    dlg._theme_combo.currentData.return_value = "Midnight"
    dlg._theme_combo.currentText.return_value = "Midnight"


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
    from metatv.gui.settings_dialog import _CHANNEL_DENSITY_CHOICES
    from metatv.gui.settings_dialog_tabs import _PLATFORM_NAME_STYLE_CHOICES
    from PyQt6.QtWidgets import QCheckBox, QComboBox

    dlg._channel_density_combo = QComboBox()
    for label, value in _CHANNEL_DENSITY_CHOICES:
        dlg._channel_density_combo.addItem(label, value)
    dlg._platform_name_style_combo = QComboBox()
    for label, value in _PLATFORM_NAME_STYLE_CHOICES:
        dlg._platform_name_style_combo.addItem(label, value)
    dlg._channel_thumbnails_check = QCheckBox()
    dlg._channel_thumbnails_check.setChecked(True)
    # Collapse-variants opt-in (#387) and the theme combo (#389) — same group,
    # so they live in this factory rather than eight duplicated stubs.
    dlg._collapse_variants_check = QCheckBox()
    dlg._collapse_variants_check.setChecked(False)
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
    "refresh_theme",
    "_apply_collapse_variants_setting",
    "_sync_split_toggle",
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


# ---------------------------------------------------------------------------
# MainWindow channel-render skeleton stubs
# ---------------------------------------------------------------------------

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
