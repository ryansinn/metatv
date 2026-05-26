"""Background manager for checking failed streams on a backoff schedule."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable

from loguru import logger
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from metatv.core.repositories.stream_retry import StreamRetryRepository

if TYPE_CHECKING:
    from metatv.core.database import Database


class StreamRetryManager(QObject):
    """Periodically re-validates streams that previously failed.

    Emits ``stream_online`` when a stream comes back, and ``retry_list_changed``
    whenever the pending list changes so the sidebar can refresh.
    """

    stream_online      = pyqtSignal(str, str)   # channel_id, channel_name
    retry_list_changed = pyqtSignal()

    # Poll interval — only fires when there's at least one pending entry due
    _POLL_MS = 2 * 60 * 1000  # 2 minutes

    def __init__(
        self,
        db: "Database",
        validate_fn: Callable[[str], tuple[bool, str | None]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._validate_fn = validate_fn
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stream_retry")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_due)
        self._busy = False

    def start(self) -> None:
        self._timer.start(self._POLL_MS)
        logger.debug("StreamRetryManager started")

    def stop(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def add_failure(self, channel_id: str, channel_name: str, stream_url: str, error: str) -> None:
        """Record a stream failure (called on main thread after preflight fails)."""
        session = self._db.get_session()
        try:
            repo = StreamRetryRepository(session)
            repo.add(channel_id, channel_name, stream_url, error)
        finally:
            session.close()
        self.retry_list_changed.emit()

    def remove(self, entry_id: str) -> None:
        session = self._db.get_session()
        try:
            repo = StreamRetryRepository(session)
            repo.remove(entry_id)
        finally:
            session.close()
        self.retry_list_changed.emit()

    def remove_by_channel(self, channel_id: str) -> None:
        session = self._db.get_session()
        try:
            repo = StreamRetryRepository(session)
            repo.remove_by_channel(channel_id)
        finally:
            session.close()
        self.retry_list_changed.emit()

    def clear_all(self) -> None:
        session = self._db.get_session()
        try:
            repo = StreamRetryRepository(session)
            repo.clear_all()
        finally:
            session.close()
        self.retry_list_changed.emit()

    def get_all_pending(self) -> list:
        session = self._db.get_session()
        try:
            repo = StreamRetryRepository(session)
            return repo.get_all_pending()
        finally:
            session.close()

    def check_all_now(self) -> None:
        """Force-check all pending entries regardless of schedule (e.g. after source refresh)."""
        if not self._busy:
            self._executor.submit(self._run_checks, force_all=True)

    # ------------------------------------------------------------------ #
    # Background checking                                                  #
    # ------------------------------------------------------------------ #

    def _check_due(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._executor.submit(self._run_checks, force_all=False)

    def _run_checks(self, force_all: bool) -> None:
        try:
            session = self._db.get_session()
            try:
                repo = StreamRetryRepository(session)
                entries = repo.get_all_pending() if force_all else repo.get_due()
                if not entries:
                    return

                changed = False
                for entry in entries:
                    try:
                        ok, err = self._validate_fn(entry.stream_url)
                        repo.mark_checked(entry, ok, err)
                        changed = True
                        if ok:
                            logger.info(f"StreamRetry: {entry.channel_name} is back online")
                            self.stream_online.emit(entry.channel_id, entry.channel_name)
                    except Exception as exc:
                        logger.warning(f"StreamRetry check error for {entry.channel_name}: {exc}")
                        repo.mark_checked(entry, False, str(exc))
                        changed = True

                if changed:
                    self.retry_list_changed.emit()
            finally:
                session.close()
        finally:
            self._busy = False
