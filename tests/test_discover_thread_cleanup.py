"""Discover view must stop BOTH loader threads on deactivate — the exit-crash fix.

Regression guard for `QThread: Destroyed while thread is still running` (core
dump on close): `on_deactivate` used to stop only `_thread` and not
`_see_all_thread`, and it called `quit()`/`wait()` without first cancelling the
worker — but the worker's `run()` monopolizes the thread's event loop, so
`quit()` never landed and `wait(2000)` timed out, leaving the thread running
when it got destroyed.

The fix: a cooperative `cancel()` flag on both workers (so `run()` bails between
shelf queries and returns, letting `quit()` take effect) and `on_deactivate`
stopping both threads.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _running_thread() -> MagicMock:
    t = MagicMock()
    t.isRunning.return_value = True
    t.wait.return_value = True      # stops cleanly within the timeout
    return t


def test_on_deactivate_stops_both_threads_and_cancels_workers():
    """Both the shelf loader and the see-all loader must be cancelled + stopped."""
    from metatv.gui.discover_view import DiscoverView

    view = DiscoverView.__new__(DiscoverView)
    view._worker = MagicMock()
    view._see_all_worker = MagicMock()
    view._thread = _running_thread()
    view._see_all_thread = _running_thread()

    view.on_deactivate()

    # Workers cancelled FIRST (so quit() can actually land).
    view._worker.cancel.assert_called_once()
    view._see_all_worker.cancel.assert_called_once()
    # Both threads quit + waited.
    view._thread.quit.assert_called_once()
    view._thread.wait.assert_called_once()
    view._see_all_thread.quit.assert_called_once()
    view._see_all_thread.wait.assert_called_once()


def test_on_deactivate_is_safe_before_any_load():
    """Never-activated view (no _worker, threads None) must not raise."""
    from metatv.gui.discover_view import DiscoverView

    view = DiscoverView.__new__(DiscoverView)
    view._thread = None
    view._see_all_thread = None
    # In production, on_deactivate's getattr(self, "_worker", None) yields None on a
    # properly-initialized QObject before any load; set None to exercise that path.
    view._worker = None
    view._see_all_worker = None
    view.on_deactivate()  # must not raise (both _stop_loader calls are no-ops)


def test_see_all_worker_suppresses_ready_emit_when_cancelled(tmp_path, qapp):
    """A cancelled see-all worker must NOT emit ready into a torn-down view."""
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.gui.discover_workers import _SeeAllWorker

    db = Database(f"sqlite:///{tmp_path / 't.db'}")
    db.create_tables()
    cfg = Config()

    # Cancelled → no emit.
    w = _SeeAllWorker(db, cfg, "recently_added")
    w.cancel()
    assert w._cancelled is True
    got: list = []
    w.ready.connect(lambda *a: got.append(a))
    w.run()
    assert got == [], "cancelled worker must not emit ready"

    # Not cancelled → emits (even an empty card list) — proves the guard, not empty-DB.
    w2 = _SeeAllWorker(db, cfg, "recently_added")
    got2: list = []
    w2.ready.connect(lambda *a: got2.append(a))
    w2.run()
    assert len(got2) == 1, "non-cancelled worker must emit ready"

    db.close()


def test_loader_worker_emits_finished_even_when_cancelled(tmp_path, qapp):
    """The finished signal must fire on a cancel-return so thread.quit() lands."""
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.gui.discover_workers import _LoaderWorker

    db = Database(f"sqlite:///{tmp_path / 't.db'}")
    db.create_tables()

    w = _LoaderWorker(db, Config())
    w.cancel()
    finished: list = []
    shelves: list = []
    w.finished.connect(lambda: finished.append(True))
    w.shelfReady.connect(lambda d: shelves.append(d))

    w.run()

    assert finished == [True], "finished must fire even when cancelled (so quit() lands)"
    assert shelves == [], "cancelled loader must emit no shelves"

    db.close()
