"""Turns a failed watch-list write into something the user can see.

``core/watchlist.py`` queues its writes to a single worker thread so a click on
Remove cannot block the UI for the 30 s SQLite ``busy_timeout`` (see that
module's note). The other half of that change is this one: when the write
fails, the user must be told, because the old behaviour — log it and return
``False`` — is a Remove button that does nothing at all.

``core/`` holds no Qt dependency, so ``watchlist`` calls a plain callable and
does it **on the writer thread**. This class is the marshalling step: the
handler it installs is a private signal's ``emit``, which Qt delivers to the
main thread's event loop, and only the main-thread slot touches the
NotificationManager (which builds a ``QTimer`` and must not be called from a
worker — the same rule ``EpgManager`` follows for its own notifications).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

from metatv.core import watchlist
from metatv.core.notifications import condense_error

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.notifications import NotificationManager

#: op -> the sentence the user reads. Not f-strings at the call site: there are
#: exactly two operations and both need the same shape.
_HEADLINES = {
    "add": "Could not add {pattern!r} to your watch list",
    "remove": "Could not remove {pattern!r} from your watch list",
}


class WatchlistWriteNotifier(QObject):
    """Reports failed watch-list writes as an error notification.

    Constructing one installs it as ``watchlist``'s write-error handler, so it
    covers every call site of ``watchlist.add`` / ``watchlist.remove`` at once
    — the EPG panel, the details pane, the agenda widget and the main window —
    rather than each of them growing its own failure branch.
    """

    #: Private: writer thread -> main thread. (op, pattern, message)
    _write_failed = pyqtSignal(str, str, str)

    def __init__(
        self,
        notifications: "Optional[NotificationManager]",
        parent: "Optional[QObject]" = None,
    ) -> None:
        """
        Args:
            notifications: The window's NotificationManager. ``None`` leaves the
                failure logged only, which is what a headless host gets.
            parent: Qt parent — keeps this object on the main thread, so the
                signal connection below is a QUEUED one when the writer thread
                emits it.
        """
        super().__init__(parent)
        self._notifications = notifications
        self._write_failed.connect(self._on_write_failed)
        watchlist.set_write_error_handler(self._write_failed.emit)

    def _on_write_failed(self, op: str, pattern: str, message: str) -> None:
        """Main thread: show the failure.

        Args:
            op: ``"add"`` or ``"remove"``.
            pattern: The watch pattern the user acted on.
            message: The cause, straight from the database layer.
        """
        headline = _HEADLINES.get(op, "A watch-list change could not be saved")
        title = headline.format(pattern=pattern)
        logger.warning("watchlist: {} — {}", title, message)
        if self._notifications is None:
            return
        self._notifications.show(
            title=title,
            message=f"{condense_error(message)}. The list still shows what is saved.",
            type="error",
            auto_dismiss_ms=8000,
        )


def install_watchlist_writes(window) -> WatchlistWriteNotifier:
    """Wire the watch list into *window*: store, failure toast, and drain.

    One call rather than three lines in ``MainWindow.__init__``, because the
    three belong together — binding the store is what makes writes go through
    the queue, the notifier is what makes a failed one visible, and the cleanup
    registration is what stops ``closeEvent`` closing the database out from
    under a write that is still queued.

    Args:
        window: The MainWindow. Read for ``db`` and ``notification_manager``;
            used as the notifier's Qt parent and cleanup registrar.

    Returns:
        The notifier, so the caller can keep it alive.
    """
    watchlist.bind(window.db)
    notifier = WatchlistWriteNotifier(window.notification_manager, window)
    window._register_cleanable("watchlist", watchlist.shutdown)
    return notifier
