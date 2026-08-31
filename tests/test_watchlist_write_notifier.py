"""A watch-list write that fails has to reach the user, on the main thread.

``core/watchlist.py`` moved its writes to a worker so a click cannot block the
UI for the 30 s SQLite ``busy_timeout``. That change is only half a fix on its
own: the old code logged the failure and returned ``False``, so the user
pressed Remove, the rule stayed, and nothing said why. These tests pin the
other half — the failure becomes a visible error — and the constraint that
makes it safe: ``NotificationManager`` builds a ``QTimer``, so it must only
ever be touched from the main thread, while ``watchlist`` calls its handler
from the writer.
"""

from __future__ import annotations

import threading

import pytest

from metatv.core import watchlist
from metatv.core.notifications import NotificationManager, NotificationType
from metatv.gui.watchlist_write_notifier import (
    WatchlistWriteNotifier, install_watchlist_writes,
)


@pytest.fixture(autouse=True)
def _clean_handler():
    """Leave no module-level handler behind for the next test."""
    yield
    watchlist.set_write_error_handler(None)
    watchlist.unbind()


def _drain(qapp, notifications, tries: int = 200):
    """Spin the event loop until the queued signal has been delivered."""
    for _ in range(tries):
        if notifications.notifications:
            return
        qapp.processEvents()


def test_a_failed_write_becomes_an_error_notification(qapp):
    """The user pressed Remove and it did not save. Say so."""
    notifications = NotificationManager()
    notifier = WatchlistWriteNotifier(notifications)
    assert notifier is not None   # parentless QObject: the name is what keeps it alive

    watchlist._write_error_handler(
        "remove", "NRL", "(sqlite3.OperationalError) database is locked")
    _drain(qapp, notifications)

    assert len(notifications.notifications) == 1, "the failure never reached the user"
    shown = notifications.notifications[0]
    assert shown.type is NotificationType.ERROR
    assert "NRL" in shown.title, shown.title
    assert "remove" in shown.title.lower(), shown.title
    assert "database is locked" in shown.message, shown.message


def test_the_add_and_remove_wordings_differ(qapp):
    """Two operations, two sentences — "could not add" is not "could not remove"."""
    notifications = NotificationManager()
    notifier = WatchlistWriteNotifier(notifications)
    assert notifier is not None   # parentless QObject: the name is what keeps it alive

    watchlist._write_error_handler("add", "Cricket", "disk I/O error")
    _drain(qapp, notifications)
    assert "add" in notifications.notifications[0].title.lower()
    assert "Cricket" in notifications.notifications[0].title


def test_the_notification_is_built_on_the_main_thread(qapp):
    """``NotificationManager.show`` makes a QTimer; a worker must not call it.

    The handler ``watchlist`` invokes runs on the writer thread, so the
    marshalling step is the whole point of this class — this drives it from a
    real background thread and checks where the work landed.
    """
    notifications = NotificationManager()
    notifier = WatchlistWriteNotifier(notifications)
    assert notifier is not None   # parentless QObject: the name is what keeps it alive
    seen: list[str] = []
    notifications.add_listener(
        lambda _visible: seen.append(threading.current_thread().name))

    worker = threading.Thread(
        target=watchlist._write_error_handler,
        args=("remove", "Mexico", "database is locked"))
    worker.start()
    worker.join(timeout=5)
    _drain(qapp, notifications)

    assert seen, "the notification never fired"
    assert seen[0] == threading.main_thread().name, (
        f"the NotificationManager was touched from {seen[0]}")


def test_a_headless_host_logs_instead_of_crashing(qapp):
    """No NotificationManager is a valid state; a failed write must not raise."""
    notifier = WatchlistWriteNotifier(None)
    assert notifier is not None   # parentless QObject: the name is what keeps it alive
    watchlist._write_error_handler("add", "NRL", "database is locked")
    qapp.processEvents()


def test_install_binds_the_store_and_registers_the_drain(qapp, tmp_path):
    """One call wires all three, because all three have to happen together.

    Binding is what routes writes through the queue, the notifier is what makes
    a failed one visible, and the cleanup registration is what stops
    ``closeEvent`` closing the database out from under a queued write.
    """
    from PyQt6.QtCore import QObject

    from metatv.core.database import Database

    class _Window(QObject):
        """A QObject, because the real host is one and becomes the Qt parent."""

        def __init__(self, database):
            super().__init__()
            self.db = database
            self.notification_manager = NotificationManager()
            self.cleanables: list[tuple[str, object]] = []

        def _register_cleanable(self, name, fn):
            self.cleanables.append((name, fn))

    database = Database(f"sqlite:///{tmp_path / 'wl.db'}")
    database.create_tables()
    window = _Window(database)

    notifier = install_watchlist_writes(window)

    assert isinstance(notifier, WatchlistWriteNotifier)
    assert watchlist._db is database, "the store was not bound"
    assert watchlist._write_error_handler is not None, "failures would be silent"
    assert [name for name, _ in window.cleanables] == ["watchlist"]
    assert window.cleanables[0][1] is watchlist.shutdown, (
        "queued writes would outlive the database connection")


def test_the_window_wires_it_at_construction():
    """An installer nobody calls is the same as no fix at all."""
    from pathlib import Path

    import metatv.gui.main_window as mw

    source = Path(mw.__file__).read_text()
    assert "install_watchlist_writes(self)" in source
