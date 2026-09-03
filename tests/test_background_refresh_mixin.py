"""Behavioral tests for BackgroundRefreshMixin (B8-5).

The mixin is the single shared skeleton that Favorites/History/Queue compose instead of
each hand-rolling the executor + signal + try/except/emit-None + clear/dispatch. These
pin the skeleton directly: a failing load emits None (not a swallowed blank), None renders
a visible error row, and success dispatches to _populate_rows.

Also covers the MIG-1 migration gate: ``refresh()`` deferring to a running migration
pass instead of contending for the SQLite writer turn, and the ``MigrationManager``
wiring that flips ``migration_gate`` on/off around a pass (its read side lives in
``metatv/core/migration_gate.py``, its write side in ``metatv/core/migration_manager.py``).
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QListWidget

from metatv.core import migration_gate
from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
from metatv.gui.sidebar.base import CollapsibleSection, ScrollPreservingMixin
from tests.conftest import destroy_widget


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSection(BackgroundRefreshMixin, ScrollPreservingMixin, QObject):
    """Minimal section: real signal + list, scripted load, records populate/error calls.

    Composes ``ScrollPreservingMixin`` exactly as the real ``CollapsibleSection``
    does — the refresh mixin calls into it to keep the user's place across the
    clear-and-repopulate, so a host without it is not the real MRO.
    """

    def reapply_row_budget(self) -> None:
        """The refresh mixin fits the rows to the section after every populate.

        A double that stands in for a section has to answer it — the real
        ``CollapsibleSection`` provides it, and leaving it off makes this host
        a different MRO from the one under test.
        """

    _data_ready = pyqtSignal(object)

    def __init__(self, load_result=None, raise_exc=False):
        super().__init__()
        self._list = QListWidget()
        self._load_result = load_result
        self._raise_exc = raise_exc
        self.populated = None
        self.error_msg = None

    def _refresh_list(self):
        return self._list

    def _load_error_message(self):
        return "Couldn't load thing"

    def _load_rows(self):
        if self._raise_exc:
            raise RuntimeError("db boom")
        return self._load_result

    def _populate_rows(self, rows):
        self.populated = rows
        for r in rows:
            self._list.addItem(str(r))

    def show_load_error(self, lst, msg):   # provided by CollapsibleSection in real sections
        self.error_msg = msg
        lst.addItem(msg)


def test_bg_refresh_emits_none_on_load_failure(qapp):
    """A raising _load_rows must emit None — failure is signaled, never swallowed."""
    sec = _FakeSection(raise_exc=True)
    captured = []
    sec._data_ready.connect(captured.append)
    sec._bg_refresh()
    assert captured == [None]


def test_on_data_ready_none_shows_error_row_not_blank(qapp):
    sec = _FakeSection()
    sec._on_data_ready(None)
    assert sec.error_msg == "Couldn't load thing"
    assert sec.populated is None
    assert sec._list.count() == 1   # the visible error row


def test_on_data_ready_success_dispatches_to_populate(qapp):
    sec = _FakeSection()
    sec._on_data_ready(["a", "b", "c"])
    assert sec.populated == ["a", "b", "c"]
    assert sec.error_msg is None
    assert sec._list.count() == 3


def test_on_data_ready_clears_before_render(qapp):
    """Each render starts from a clean list (no torn/stale rows)."""
    sec = _FakeSection()
    sec._list.addItem("stale")
    sec._on_data_ready(["only"])
    assert sec._list.count() == 1
    assert sec._list.item(0).text() == "only"


# ---------------------------------------------------------------------------
# Migration gate (MIG-1) — refresh() defers to a running migration pass instead
# of contending for the SQLite writer turn.
# ---------------------------------------------------------------------------

def _stub_collapsible_state(obj) -> None:
    """Give a CollapsibleSection-derived object the minimal attrs set_empty() reads."""
    obj.is_empty = True
    obj.is_collapsed = False
    obj._user_collapsed = False


def _make_real_section(qapp):
    """A real BackgroundRefreshMixin + CollapsibleSection, executor swapped for a
    MagicMock so no worker thread actually runs.

    Needed instead of ``_FakeSection`` above because these tests exercise the REAL
    ``show_loading``/``set_empty``/``QTimer(self)`` parenting ``CollapsibleSection``
    provides — same pattern as ``tests/test_loading_indicators.py``'s
    ``_make_mixin_section``. Unlike that helper, this one also connects a real
    signal and parents a real ``QTimer(self)``, both of which need an actual
    (not skipped) QObject C++ base — ``QFrame.__init__`` is called directly
    rather than the full, widget-heavy ``CollapsibleSection.__init__`` (header/
    content layout, theme styling), which this test has no use for.
    """
    from PyQt6.QtWidgets import QFrame

    class _Section(BackgroundRefreshMixin, CollapsibleSection):
        _data_ready = pyqtSignal(object)

        def reapply_row_budget(self) -> None:
            """No-op — this double skips CollapsibleSection's real init chain
            (see the class docstring), so the real RowBudgetMixin geometry
            logic has nothing valid to measure. Same shape as _FakeSection's
            override above."""

        def _refresh_list(self):
            return self._list

        def _load_error_message(self):
            return "Couldn't load things"

        def _populate_rows(self, rows):
            for r in rows:
                self._list.addItem(str(r))
            self.set_empty(not rows)

    sec = _Section.__new__(_Section)
    QFrame.__init__(sec)  # real QObject base — signals/QTimer(self) need this
    _stub_collapsible_state(sec)
    sec._list = QListWidget()
    sec.set_empty = lambda *a, **k: None  # avoid splitter geometry in headless test
    sec._init_background_refresh()
    sec._executor = MagicMock()  # don't actually run the worker
    return sec


@pytest.fixture()
def _gate_reset():
    """Migration-manager-wiring tests drive the REAL global gate — start and end clear."""
    migration_gate._set_running(False)
    yield
    migration_gate._set_running(False)


def test_refresh_defers_when_migration_running(qapp, monkeypatch):
    """Gate on: refresh() must not submit the query, must render the waiting
    row, and must arm exactly one retry timer even across a second refresh()."""
    sec = _make_real_section(qapp)
    monkeypatch.setattr(migration_gate, "is_running", lambda: True)

    sec.refresh()

    sec._executor.submit.assert_not_called()
    assert sec._list.count() == 1
    assert "Waiting for the library update" in sec._list.item(0).text()
    timer = sec._migration_retry_timer
    assert timer is not None and timer.isActive()

    # A second refresh() call while still waiting must not arm a second timer.
    sec.refresh()
    assert sec._migration_retry_timer is timer
    sec._executor.submit.assert_not_called()

    timer.stop()  # tidy — avoid a stray real 3s fire mid-suite
    destroy_widget(sec, sec._list)


def test_refresh_retries_and_loads_once_gate_clears(qapp, monkeypatch):
    """Gate clears: the retry timer firing re-enters refresh(), which this
    time submits the real query and, once the worker's result lands, renders it
    (recorder pattern via the mocked executor + a direct _on_data_ready call)."""
    sec = _make_real_section(qapp)
    monkeypatch.setattr(migration_gate, "is_running", lambda: True)

    sec.refresh()
    sec._executor.submit.assert_not_called()
    timer = sec._migration_retry_timer
    assert timer is not None

    monkeypatch.setattr(migration_gate, "is_running", lambda: False)
    timer.timeout.emit()  # fire the retry directly rather than waiting 3s

    assert sec._migration_retry_timer is None
    sec._executor.submit.assert_called_once_with(sec._bg_refresh)

    # Simulate the worker's result landing on the signal — proves the deferred
    # refresh reaches a real render, not just a resubmission.
    sec._on_data_ready(["row-a", "row-b"])
    texts = [sec._list.item(i).text() for i in range(sec._list.count())]
    assert texts == ["row-a", "row-b"]
    destroy_widget(sec, sec._list)


class _TrivialTask:
    """A migration task that completes immediately — for gate wiring tests.

    ``run()`` records the gate's state AT THE MOMENT THE TASK EXECUTES — the
    only deterministic observation point. The first version of the flips test
    sampled the gate from a ``task_started`` lambda instead, but that signal
    is QUEUED (worker → main thread): with a microsecond task, the pass is
    over and the gate already OFF by the time the main loop delivers it. The
    slice run and CI happened to interleave favourably; the full local suite
    (9,818 tests of scheduler load) delivered it late every time — the wrap
    gate of 2026-09-03 went red on exactly that race.
    """

    id = "trivial"
    label = "Trivial task"

    def __init__(self) -> None:
        self.gate_seen_in_run: list[bool] = []

    def needs_run(self, config) -> bool:
        return True

    def run(self, progress_cb, is_cancelled) -> None:
        self.gate_seen_in_run.append(migration_gate.is_running())
        progress_cb(1, 1)

    def on_completed(self, config) -> None:
        """No-op — without it the manager logs a noisy on_completed ERROR."""


class _BlockingTask:
    """A migration task that blocks (checking ``is_cancelled``) until released.

    Lets a test deterministically observe the gate mid-run without racing a
    real sleep: the main thread waits on ``started`` rather than guessing timing.
    """

    id = "blocking"
    label = "Blocking task"

    def __init__(self) -> None:
        self.started = threading.Event()

    def needs_run(self, config) -> bool:
        return True

    def run(self, progress_cb, is_cancelled) -> None:
        self.started.set()
        for _ in range(500):  # bounded: 500 * 10ms = 5s max
            if is_cancelled():
                return
            time.sleep(0.01)


class _FakeMigrationConfig:
    def save(self) -> None:
        pass


def test_migration_manager_flips_gate_on_start_and_off_at_all_done(qapp, _gate_reset):
    """The manager — not a mock of it — is what this gate has to be correct
    against: ON at the exact point the (only) task starts, OFF once
    ``all_finished`` fires. Mirrors the "starting task"/"all tasks done" log
    lines in ``MigrationManager._run_all``."""
    from metatv.core.migration_manager import MigrationManager

    mgr = MigrationManager(_FakeMigrationConfig(), MagicMock())
    task = _TrivialTask()
    mgr.register(task)

    loop = QEventLoop()
    mgr.all_finished.connect(loop.quit)
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(3000)

    assert not migration_gate.is_running()
    mgr.run_pending()
    loop.exec()
    guard.stop()

    assert task.gate_seen_in_run == [True], "gate must be ON while the task runs"
    assert not migration_gate.is_running(), "gate must be OFF after all_finished"


def test_migration_manager_shutdown_clears_gate_mid_run(qapp, _gate_reset):
    """shutdown() mid-run must clear the gate even though the task never
    reached its normal completion — a reader must never wait forever."""
    from metatv.core.migration_manager import MigrationManager

    mgr = MigrationManager(_FakeMigrationConfig(), MagicMock())
    task = _BlockingTask()
    mgr.register(task)

    mgr.run_pending()
    assert task.started.wait(timeout=3.0), "task never started"
    assert migration_gate.is_running(), "gate must be ON while the task is mid-run"

    mgr.shutdown()  # cancels + drains: blocks until the task's is_cancelled() check returns

    assert not migration_gate.is_running(), "shutdown must clear the gate even mid-run"
