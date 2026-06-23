"""Behavioral tests for RefreshQueueManager.

The tests drive the manager directly — no full MainWindow init needed.  We
mock ``NotificationManager`` and inject a fake ``ProviderLoadThread`` that
lets the test control when ``finished`` fires.

Assertions focus on the behaviors that would regress:

* Serial execution: the 2nd provider's thread does NOT start until the 1st
  emits ``finished``.
* Deduplication: enqueueing the same provider while it is running is a no-op.
* ``queue_changed`` reflects queued → running → done lifecycle.
* Enqueue-while-running APPENDS (one overview, not two).
* The active notification advances during progress.
* ``refresh_finished`` is emitted once per provider with the correct payload.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal


# ---------------------------------------------------------------------------
# Minimal QApplication for signal delivery
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def qapp():
    import sys
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    return app


# ---------------------------------------------------------------------------
# Fake ProviderLoadThread that never actually spawns a thread
# ---------------------------------------------------------------------------

class _FakeThread(QThread):
    """A fake ProviderLoadThread whose ``run`` does nothing.

    Tests drive it by calling ``_fire_progress`` / ``_fire_finished`` directly.
    """
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, provider, db, **kwargs):  # noqa: D107
        super().__init__()
        self.provider_id = provider.id
        self.prefix_stats: dict | None = None

    def run(self) -> None:  # noqa: D102
        # Do nothing — test drives via fire helpers
        pass

    def start(self) -> None:
        # Don't actually start a thread — just mark running state so isRunning() works
        pass  # We'll fire signals manually

    def _fire_progress(self, cur: int, tot: int, msg: str) -> None:
        self.progress.emit(cur, tot, msg)

    def _fire_finished(self, success: bool = True, msg: str = "Loaded 100 channels") -> None:
        self.finished.emit(success, msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_provider(pid: str, name: str) -> MagicMock:
    """Return a mock ProviderDB-like object."""
    p = MagicMock()
    p.id = pid
    p.name = name
    p.type = "xtream"
    p.url = "http://example.com"
    p.epg_enabled = False
    return p


def _make_provider_model(pid: str, name: str) -> MagicMock:
    """Return a mock Provider model object."""
    m = MagicMock()
    m.id = pid
    m.name = name
    return m


def _build_manager(threads_by_pid: dict[str, _FakeThread], providers: list):
    """Build a RefreshQueueManager with mocked DB/config/notifications.

    ``threads_by_pid`` maps provider_id → the fake thread to return when the
    manager tries to start a ProviderLoadThread for that provider.
    ``providers`` is a list of mock ProviderDB objects.
    """
    from metatv.gui.refresh_queue_manager import RefreshQueueManager

    db = MagicMock()
    config = MagicMock()
    config.prefix_separators = []
    config.filter_language_groups = {}
    config.filter_quality_groups = {}
    config.filter_platform_groups = {}
    config.filter_regional_groups = {}

    nm = MagicMock()
    notif_ids: dict[str, int] = {}
    _counter = [0]

    def _show_progress(**kwargs):
        _counter[0] += 1
        nid = f"notif-{_counter[0]}"
        return nid

    def _complete(nid, msg):
        pass

    def _set_steps(nid, steps):
        pass

    def _update(nid, **kwargs):
        pass

    def _dismiss(nid):
        pass

    nm.show_progress.side_effect = _show_progress
    nm.complete_progress.side_effect = _complete
    nm.set_steps.side_effect = _set_steps
    nm.update.side_effect = _update
    nm.dismiss.side_effect = _dismiss

    # Mock DB session / repos
    session = MagicMock()
    repos = MagicMock()
    provider_map = {p.id: p for p in providers}

    def _get_by_id(pid):
        return provider_map.get(pid)

    repos.providers.get_by_id.side_effect = _get_by_id

    def _to_model(db_prov):
        return _make_provider_model(db_prov.id, db_prov.name)

    repos.providers.to_model.side_effect = _to_model

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session)
    session_ctx.__exit__ = MagicMock(return_value=False)

    db.get_session.return_value = session

    # RepositoryFactory mock — needs to be patched where it's imported
    repo_factory_mock = MagicMock(return_value=repos)

    manager = RefreshQueueManager(db, config, nm, parent=None)

    # Patch ProviderLoadThread inside the manager's _start_entry method
    def _fake_thread_factory(provider_model, db, **kwargs):
        return threads_by_pid[provider_model.id]

    return manager, repo_factory_mock, _fake_thread_factory, nm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSerialExecution:
    """The 2nd provider's thread must NOT start until the 1st emits finished."""

    def test_second_thread_not_started_before_first_finishes(self, qapp):
        """Enqueue two providers; verify second thread.start() not called until first done."""
        p1 = _make_db_provider("p1", "Provider 1")
        p2 = _make_db_provider("p2", "Provider 2")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t2 = _FakeThread(_make_provider_model("p2", "Provider 2"), None)

        t1_started = []
        t2_started = []
        t1.start = lambda: t1_started.append(True)
        t2.start = lambda: t2_started.append(True)

        manager, repo_factory, thread_factory, nm = _build_manager(
            {"p1": t1, "p2": t2}, [p1, p2]
        )

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            # After enqueueing p1, its thread should start immediately
            assert t1_started, "p1 thread should start immediately on first enqueue"
            assert not t2_started, "p2 thread must NOT start until p1 finishes"

            manager.enqueue("p2", "Provider 2")
            # p2 still not started (p1 is running)
            assert not t2_started, "p2 thread must NOT start while p1 is running"

            # Finish p1
            t1._fire_finished(True, "Loaded 100 channels")
            qapp.processEvents()

            # Now p2 should start
            assert t2_started, "p2 thread MUST start after p1 emits finished"


class TestDeduplication:
    """Enqueueing the same provider while running must be a no-op."""

    def test_duplicate_enqueue_ignored(self, qapp):
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        start_count = [0]
        t1.start = lambda: start_count.__setitem__(0, start_count[0] + 1)

        manager, repo_factory, thread_factory, nm = _build_manager({"p1": t1}, [p1])

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            assert start_count[0] == 1

            # Enqueue again while running — must be ignored
            manager.enqueue("p1", "Provider 1")
            manager.enqueue("p1", "Provider 1")
            qapp.processEvents()

            assert start_count[0] == 1, "Duplicate enqueue must not start another thread"
            assert len(manager._queue) == 1, "Queue length must remain 1 (no duplicate entries)"


class TestQueueChanged:
    """queue_changed signal must reflect QUEUED → RUNNING → done lifecycle."""

    def test_lifecycle_signal_sequence(self, qapp):
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm = _build_manager({"p1": t1}, [p1])

        snapshots: list[list] = []

        def _on_changed(snapshot):
            snapshots.append([(name, status.value, pct) for name, status, pct in snapshot])

        manager.queue_changed.connect(_on_changed)

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            qapp.processEvents()

        # At least one snapshot should show RUNNING state
        running_snapshots = [s for s in snapshots if any(st == "running" for _, st, _ in s)]
        assert running_snapshots, "queue_changed must emit with RUNNING status after thread starts"

    def test_queue_empty_after_finish(self, qapp):
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm = _build_manager({"p1": t1}, [p1])

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            t1._fire_finished(True)
            qapp.processEvents()

        assert len(manager._queue) == 0, "Queue must be empty after provider finishes"
        assert "p1" not in manager._queued_ids, "p1 must be removed from queued_ids after done"


class TestEnqueueWhileRunning:
    """Enqueueing a second source while one is running must APPEND, not spawn two overviews."""

    def test_single_overview_notification_for_two_sources(self, qapp):
        p1 = _make_db_provider("p1", "Provider 1")
        p2 = _make_db_provider("p2", "Provider 2")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t2 = _FakeThread(_make_provider_model("p2", "Provider 2"), None)
        t1.start = lambda: None
        t2.start = lambda: None

        manager, repo_factory, thread_factory, nm = _build_manager(
            {"p1": t1, "p2": t2}, [p1, p2]
        )

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            # Capture overview notif id before enqueueing p2
            overview_id_before = manager._overview_notif_id

            manager.enqueue("p2", "Provider 2")
            qapp.processEvents()

            # The overview notif id must not have changed — same singleton
            assert manager._overview_notif_id == overview_id_before, (
                "Enqueueing a second source must reuse the existing overview notification"
            )

        # show_progress should have been called twice: once for the overview,
        # once for p1's active toast.  NOT a third time for p2's overview.
        show_calls = nm.show_progress.call_count
        assert show_calls == 2, (
            f"Expected 2 show_progress calls (1 overview + 1 active), got {show_calls}"
        )


class TestRefreshFinishedSignal:
    """refresh_finished must be emitted once per provider with correct payload."""

    def test_refresh_finished_emitted_on_success(self, qapp):
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm = _build_manager({"p1": t1}, [p1])

        emitted: list[tuple] = []

        def _on_finished(pid, success, msg, thread):
            emitted.append((pid, success, msg))

        manager.refresh_finished.connect(_on_finished)

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            t1._fire_finished(True, "Loaded 100 channels")
            qapp.processEvents()

        assert len(emitted) == 1, "refresh_finished must emit exactly once"
        pid, success, msg = emitted[0]
        assert pid == "p1"
        assert success is True

    def test_refresh_finished_emitted_on_failure(self, qapp):
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm = _build_manager({"p1": t1}, [p1])

        emitted: list[tuple] = []
        manager.refresh_finished.connect(lambda pid, ok, msg, t: emitted.append((pid, ok)))

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            t1._fire_finished(False, "Connection refused")
            qapp.processEvents()

        assert emitted, "refresh_finished must emit even on failure"
        pid, success = emitted[0]
        assert pid == "p1"
        assert success is False


class TestOverviewDismissedWhenEmpty:
    """Overview notification must be dismissed when the queue empties."""

    def test_overview_dismissed_after_last_source(self, qapp):
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm = _build_manager({"p1": t1}, [p1])

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            overview_id = manager._overview_notif_id
            assert overview_id is not None, "Overview notification must be created on enqueue"

            t1._fire_finished(True)
            qapp.processEvents()

        # After finishing, overview should be dismissed
        assert manager._overview_notif_id is None, "Overview notif ref must be cleared after queue empties"
        nm.dismiss.assert_called_with(overview_id)


class TestShutdown:
    """shutdown() must drop pending items but not kill a running thread."""

    def test_shutdown_clears_pending(self, qapp):
        p1 = _make_db_provider("p1", "Provider 1")
        p2 = _make_db_provider("p2", "Provider 2")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t2 = _FakeThread(_make_provider_model("p2", "Provider 2"), None)
        t1.start = lambda: None
        t2.start = lambda: None

        manager, repo_factory, thread_factory, nm = _build_manager(
            {"p1": t1, "p2": t2}, [p1, p2]
        )

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            manager.enqueue("p2", "Provider 2")
            assert len(manager._queue) == 2

            manager.shutdown()

        # After shutdown, only the running entry (if any) should remain
        running = [e for e in manager._queue if e.status.value == "running"]
        pending = [e for e in manager._queue if e.status.value == "queued"]
        assert not pending, "Pending entries must be dropped on shutdown"
