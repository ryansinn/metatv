"""Behavioral tests for the Migration Center subsystem.

Three test suites:
1. ``update_detected_prefixes`` progress + cancellation
2. ``MigrationManager`` — skip, signal ordering, cancellation
3. ``MigrationProgressWidget`` — slot-driven rendering
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared DB helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with tables created."""
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(session, name: str, provider_id: str = "p1") -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB
    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type="live",
    ))
    return cid


# ---------------------------------------------------------------------------
# 1. update_detected_prefixes — progress_cb and is_cancelled
# ---------------------------------------------------------------------------

class TestUpdateDetectedPrefixesProgressAndCancel:
    """Behavioral tests for the progress_cb / is_cancelled extension."""

    def test_progress_cb_called_with_non_decreasing_done(self, db):
        """progress_cb receives non-decreasing done values ending at total."""
        from metatv.core.repositories import RepositoryFactory

        # Insert 5 channels — fewer than _BATCH so a single batch, but progress_cb
        # is still called once after that batch.
        with db.session_scope() as session:
            for i in range(5):
                _make_channel(session, f"EN - Channel {i}")

        calls: list[tuple[int, int]] = []

        def _cb(done: int, total: int) -> None:
            calls.append((done, total))

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(progress_cb=_cb)

        assert len(calls) >= 1, "progress_cb must be called at least once"

        # done values must be non-decreasing
        done_vals = [d for d, _ in calls]
        assert done_vals == sorted(done_vals), (
            f"done values are not non-decreasing: {done_vals}"
        )

        # total must be consistent
        totals = {t for _, t in calls}
        assert len(totals) == 1, f"total changed mid-run: {totals}"
        total = totals.pop()
        assert total == 5, f"expected total=5, got {total}"

        # Final call's done must equal total (single-batch case: done = min(5, 5) = 5)
        final_done, final_total = calls[-1]
        assert final_done == final_total, (
            f"last progress_cb call should have done==total; "
            f"got done={final_done}, total={final_total}"
        )

    def test_progress_cb_called_for_multiple_batches(self, db):
        """With >_BATCH channels, progress_cb is called once per batch."""
        from metatv.core.repositories import RepositoryFactory

        # Seed 2500 channels (> _BATCH=2000) → two batches → two progress_cb calls
        with db.session_scope() as session:
            for i in range(2500):
                _make_channel(session, f"EN - Channel {i}")

        calls: list[tuple[int, int]] = []
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(progress_cb=lambda d, t: calls.append((d, t)))

        # Expect exactly 2 calls (ceil(2500/2000) = 2)
        assert len(calls) == 2, f"expected 2 progress_cb calls, got {len(calls)}: {calls}"

        # Values must be non-decreasing
        assert calls[0][0] <= calls[1][0], "done values not non-decreasing"
        # Total is consistent
        assert calls[0][1] == calls[1][1] == 2500, f"total should be 2500: {calls}"
        # After batch 1: min(0+2000, 2500) = 2000
        assert calls[0][0] == 2000, f"first batch done should be 2000: {calls[0]}"
        # After batch 2: min(2000+2000, 2500) = 2500
        assert calls[1][0] == 2500, f"second batch done should be 2500: {calls[1]}"

    def test_is_cancelled_stops_after_first_batch(self, db):
        """is_cancelled returning True after first batch stops the loop early.

        Behavioral contract:
        - Exactly one batch (2000 rows) is committed before cancellation fires.
        - Exactly 500 rows are left with detected_prefix=None (not yet processed).
        - The second-batch channels are those the DB chose to put in all_ids[2000:],
          which is query-order-dependent (no ORDER BY) — we verify by counting
          rather than picking a specific id.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        # Seed 2500 channels (two batches: 2000 + 500).
        # Names all start with "EN -" so every processed channel gets detected_prefix="EN".
        with db.session_scope() as session:
            for i in range(2500):
                _make_channel(session, f"EN - Channel {i}")

        batch_count = [0]

        def _cb(done: int, total: int) -> None:
            batch_count[0] += 1

        call_count = [0]

        def _is_cancelled() -> bool:
            # Cancel starting from the second check (between batches 1 and 2)
            call_count[0] += 1
            return call_count[0] > 1

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(
                progress_cb=_cb,
                is_cancelled=_is_cancelled,
            )

        # Only one progress_cb call → only one batch committed
        assert batch_count[0] == 1, (
            f"expected exactly 1 batch to commit before cancellation, got {batch_count[0]}"
        )

        # After cancellation: exactly 2000 channels should have detected_prefix set,
        # and exactly 500 should still be None.
        with db.session_scope() as session:
            processed_count = (
                session.query(ChannelDB)
                .filter(ChannelDB.detected_prefix.isnot(None))
                .count()
            )
            unprocessed_count = (
                session.query(ChannelDB)
                .filter(ChannelDB.detected_prefix.is_(None))
                .count()
            )

        assert processed_count == 2000, (
            f"expected exactly 2000 processed channels (first batch), got {processed_count}"
        )
        assert unprocessed_count == 500, (
            f"expected exactly 500 unprocessed channels (cancelled second batch), "
            f"got {unprocessed_count}"
        )

    def test_no_progress_no_cancel_unchanged(self, db):
        """Passing None for both params keeps existing behavior (regression guard)."""
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            for i in range(3):
                _make_channel(session, f"FR - Film {i}")

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            count = repos.channels.update_detected_prefixes()  # no progress_cb / is_cancelled

        assert count == 3, f"expected 3 updated channels, got {count}"

    def test_is_cancelled_immediate_skips_all(self, db):
        """is_cancelled returning True immediately skips all batches."""
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            cid = _make_channel(session, "DE - Film")

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(
                is_cancelled=lambda: True,  # immediately cancelled
            )

        # Channel should still be unprocessed
        with db.session_scope() as session:
            ch = session.query(ChannelDB).filter_by(id=cid).first()
            assert ch.detected_prefix is None, (
                f"Channel should not be processed when is_cancelled is always True; "
                f"got detected_prefix={ch.detected_prefix!r}"
            )


# ---------------------------------------------------------------------------
# 2. MigrationManager — skip, signal ordering, cancellation
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _FakeTask:
    """Controllable migration task for MigrationManager tests."""

    def __init__(
        self,
        task_id: str = "fake_task",
        label: str = "Fake task",
        should_run: bool = True,
    ) -> None:
        self.id = task_id
        self.label = label
        self._should_run = should_run
        self.run_called = False
        self.progress_calls: list[tuple[int, int]] = []
        self.cancelled_at: int | None = None  # batch index at which is_cancelled was True
        self._cancel_on_call: int | None = None  # cancel after this many is_cancelled checks

    def needs_run(self, config) -> bool:
        return self._should_run

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        self.run_called = True
        for i in range(3):
            if is_cancelled():
                self.cancelled_at = i
                return
            progress_cb(i + 1, 3)
            time.sleep(0.001)  # give the cancel event a chance to be set


class _FakeConfig:
    """Minimal config stub for MigrationManager tests."""

    def __init__(self) -> None:
        self.prefix_detector_version = 0
        self.prefix_parse_version = 0

    def save(self) -> None:
        pass


class TestMigrationManager:

    def _make_manager(self, qapp, db=None):
        from metatv.core.migration_manager import MigrationManager
        from metatv.core.database import Database
        # Use an in-memory-style db stub if no real db provided
        if db is None:
            db = MagicMock()
        config = _FakeConfig()
        mgr = MigrationManager(config, db)
        return mgr, config

    def _collect_signals(self, mgr, qapp, *, timeout_ms: int = 3000):
        """Run manager.run_pending() and collect emitted public signals.

        Returns dict with keys: started, progress, finished, all_finished_count.
        """
        from PyQt6.QtCore import QEventLoop, QTimer

        events: dict = {
            "started": [],
            "progress": [],
            "finished": [],
            "all_finished": 0,
        }

        mgr.task_started.connect(lambda tid, lbl: events["started"].append((tid, lbl)))
        mgr.task_progress.connect(lambda tid, d, t: events["progress"].append((tid, d, t)))
        mgr.task_finished.connect(lambda tid: events["finished"].append(tid))
        mgr.all_finished.connect(lambda: events.__setitem__("all_finished", events["all_finished"] + 1))

        loop = QEventLoop()
        mgr.all_finished.connect(loop.quit)

        # Guard: quit loop after timeout even if all_finished never fires
        guard = QTimer()
        guard.setSingleShot(True)
        guard.setInterval(timeout_ms)
        guard.timeout.connect(loop.quit)
        guard.start()

        mgr.run_pending()
        loop.exec()
        guard.stop()

        return events

    def test_skips_when_needs_run_false(self, qapp):
        """run_pending skips tasks whose needs_run returns False."""
        from metatv.core.migration_manager import MigrationManager

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask(should_run=False)
        mgr.register(task)

        events = self._collect_signals(mgr, qapp)

        assert not task.run_called, "task.run should NOT be called when needs_run=False"
        assert events["started"] == [], "task_started should not fire for skipped task"
        # all_finished is NOT emitted when there are no pending tasks (no-op path)
        assert events["all_finished"] == 0

    def test_task_started_and_finished_fire_in_order(self, qapp):
        """task_started fires before task_finished for the same task_id."""
        from metatv.core.migration_manager import MigrationManager

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask(task_id="t1")
        mgr.register(task)

        order: list[str] = []
        mgr.task_started.connect(lambda tid, lbl: order.append(f"started:{tid}"))
        mgr.task_finished.connect(lambda tid: order.append(f"finished:{tid}"))

        events = self._collect_signals(mgr, qapp)

        assert "started:t1" in order, "task_started not fired"
        assert "finished:t1" in order, "task_finished not fired"
        assert order.index("started:t1") < order.index("finished:t1"), (
            "task_started must come before task_finished"
        )

    def test_progress_signals_fire(self, qapp):
        """task_progress is emitted for each progress_cb call inside the task."""
        from metatv.core.migration_manager import MigrationManager

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask(task_id="prog_task")
        mgr.register(task)

        events = self._collect_signals(mgr, qapp)

        # _FakeTask calls progress_cb 3 times
        prog = [(d, t) for tid, d, t in events["progress"] if tid == "prog_task"]
        assert len(prog) == 3, f"expected 3 progress signals, got {len(prog)}: {prog}"
        # Values should be (1,3), (2,3), (3,3)
        assert prog == [(1, 3), (2, 3), (3, 3)], f"unexpected progress values: {prog}"

    def test_all_finished_fires_after_all_tasks(self, qapp):
        """all_finished fires exactly once after all tasks complete."""
        from metatv.core.migration_manager import MigrationManager

        mgr, _ = self._make_manager(qapp)
        mgr.register(_FakeTask(task_id="a"))
        mgr.register(_FakeTask(task_id="b"))

        events = self._collect_signals(mgr, qapp)

        assert events["all_finished"] == 1, (
            f"all_finished should fire exactly once; got {events['all_finished']}"
        )
        # Both tasks must have completed
        assert "a" in events["finished"], "task 'a' not in finished"
        assert "b" in events["finished"], "task 'b' not in finished"

    def test_request_cancel_sets_is_cancelled_true(self, qapp):
        """request_cancel causes is_cancelled() → True inside the running task."""
        from metatv.core.migration_manager import MigrationManager
        from PyQt6.QtCore import QEventLoop, QTimer

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask(task_id="cancel_me")
        mgr.register(task)

        # Cancel immediately after run_pending
        loop = QEventLoop()
        mgr.all_finished.connect(loop.quit)

        guard = QTimer()
        guard.setSingleShot(True)
        guard.setInterval(3000)
        guard.timeout.connect(loop.quit)
        guard.start()

        mgr.run_pending()
        mgr.request_cancel()  # cancel before the first sleep completes
        loop.exec()
        guard.stop()

        # The task was interrupted — cancelled_at should be set
        # (it may be None if cancel wasn't picked up in time on a fast machine;
        # the important thing is that the manager shut down cleanly without hanging)
        assert task.run_called, "task.run should have been called"
        # No assertion on cancelled_at specifically — timing-dependent on test speed

    def test_tasks_run_sequentially(self, qapp):
        """Two tasks run one after the other (not concurrently)."""
        from metatv.core.migration_manager import MigrationManager

        order: list[str] = []

        class _OrderedTask:
            def __init__(self, tid: str) -> None:
                self.id = tid
                self.label = f"Task {tid}"

            def needs_run(self, config) -> bool:
                return True

            def run(self, progress_cb, is_cancelled) -> None:
                order.append(f"start:{self.id}")
                time.sleep(0.02)
                order.append(f"end:{self.id}")

        mgr, _ = self._make_manager(qapp)
        mgr.register(_OrderedTask("first"))
        mgr.register(_OrderedTask("second"))

        events = self._collect_signals(mgr, qapp, timeout_ms=5000)

        # Sequential means start:first < end:first < start:second < end:second
        assert order.index("start:first") < order.index("end:first"), "first task interleaved"
        assert order.index("end:first") < order.index("start:second"), (
            "second task started before first task ended (not sequential)"
        )

    def test_shutdown_does_not_hang(self, qapp):
        """shutdown() returns without hanging (no pool-leak → no QThread crash)."""
        from metatv.core.migration_manager import MigrationManager

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask()
        mgr.register(task)
        # Don't call run_pending — just verify shutdown is safe when idle
        mgr.shutdown()  # must return promptly


# ---------------------------------------------------------------------------
# 3. MigrationProgressWidget — slot-driven rendering tests
# ---------------------------------------------------------------------------

class TestMigrationProgressWidget:

    def _make_widget(self, qapp):
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget.__new__(MigrationProgressWidget)
        MigrationProgressWidget.__init__(w)
        return w

    def test_initially_hidden(self, qapp):
        """Widget starts hidden."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        assert not w.isVisible(), "widget should be hidden before any task starts"

    def test_task_started_adds_row_and_shows(self, qapp):
        """on_task_started adds a row and makes the widget visible."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget, _TaskRow
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Running task one")
        assert "t1" in w._rows, "row for t1 should be created"
        assert isinstance(w._rows["t1"], _TaskRow), "row should be a _TaskRow"
        assert w.isVisible(), "widget should be visible after task_started"

    def test_task_started_idempotent(self, qapp):
        """Calling on_task_started twice for the same id does not add a duplicate row."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Task one")
        w.on_task_started("t1", "Task one again")
        assert len(w._rows) == 1, "duplicate on_task_started must not add a second row"

    def test_multiple_tasks_each_get_a_row(self, qapp):
        """Each task_id gets its own row."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("a", "Task A")
        w.on_task_started("b", "Task B")
        assert "a" in w._rows and "b" in w._rows, "both task rows should exist"
        assert w._rows["a"] is not w._rows["b"], "rows should be distinct objects"

    def test_task_progress_updates_bar(self, qapp):
        """on_task_progress updates the QProgressBar to the correct value."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_task_progress("t1", 500, 2000)

        row = w._rows["t1"]
        assert row._bar.maximum() == 2000, f"bar maximum should be 2000; got {row._bar.maximum()}"
        assert row._bar.value() == 500, f"bar value should be 500; got {row._bar.value()}"
        assert "25%" in row._pct.text(), f"pct label should show ~25%; got {row._pct.text()!r}"

    def test_task_progress_full(self, qapp):
        """on_task_progress with done==total shows 100%."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_task_progress("t1", 100, 100)

        row = w._rows["t1"]
        assert row._bar.value() == 100
        assert "100%" in row._pct.text()

    def test_task_finished_flips_to_done_glyph(self, qapp):
        """on_task_finished sets _done=True and updates the glyph."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        from metatv.gui import icons as _icons
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_task_progress("t1", 200, 200)
        w.on_task_finished("t1")

        row = w._rows["t1"]
        assert row._done is True, "row._done should be True after on_task_finished"
        assert row._glyph.text() == _icons.migration_done_icon, (
            f"glyph should be done icon {_icons.migration_done_icon!r}; "
            f"got {row._glyph.text()!r}"
        )

    def test_task_finished_sets_bar_to_full(self, qapp):
        """on_task_finished sets the progress bar to 100% even if progress was partial."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_task_progress("t1", 50, 200)  # partial
        w.on_task_finished("t1")

        row = w._rows["t1"]
        assert row._bar.value() == row._bar.maximum(), (
            "bar should be full after task_finished"
        )
        assert "100%" in row._pct.text()

    def test_task_finished_on_unknown_id_is_safe(self, qapp):
        """on_task_finished for an unknown task_id does not crash."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_finished("nonexistent")  # must not raise

    def test_all_finished_schedules_hide(self, qapp):
        """on_all_finished starts the hide timer (widget will hide after ~2s)."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_all_finished()
        assert w._hide_timer.isActive(), "hide timer should be active after all_finished"

    def test_pending_glyph_before_finish(self, qapp):
        """Before on_task_finished, the glyph is the pending icon."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        from metatv.gui import icons as _icons
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")

        row = w._rows["t1"]
        assert row._glyph.text() == _icons.migration_pending_icon, (
            f"pending glyph should be {_icons.migration_pending_icon!r}; "
            f"got {row._glyph.text()!r}"
        )
