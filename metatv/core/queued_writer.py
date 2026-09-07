"""One background writer thread, queued and boundedly flushable.

``core/profile_store.py`` and ``core/watchlist.py`` each grew their own copy of
this: a ``ThreadPoolExecutor(max_workers=1)`` created lazily, a list of
in-flight ``Future``s, a ``flush(timeout)`` that waits on them and logs what
did not land, and a ``shutdown(timeout)`` that flushes then tears the pool
down. Both exist for the same real incident, not a hypothetical one — SQLite
has one writer and a 30s ``busy_timeout``, and a click handler that wrote
inline blocked the UI thread for the full timeout while a migration or bulk
pass held the lock (profile_store's module docstring: a 29.8s watchlist
DELETE stall; watchlist's own docstring: two removed alert rules on
2026-09-01 that silently failed to leave the list because the old
``_db_remove`` logged and returned ``False``). ``max_workers=1`` is not a
resource choice in either caller — it serialises a module's writes against
each other so two saves of the same key, or an add followed by a remove of
the same pattern, cannot land out of order.

This module is that mechanism, pulled out once. What is deliberately NOT
here: replaying pending writes over a read (``watchlist._apply_pending``) and
an error-handler callback (``watchlist.set_write_error_handler``) are real
policy differences — watchlist needs both because a caller can read between a
queued write and a landed one, profile_store is write-only after startup and
needs neither. Each module keeps that bookkeeping itself and composes a
:class:`SingleWriter` underneath it for the pool/queue/flush/shutdown part
that was byte-for-byte identical.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Callable, Optional

from loguru import logger


class SingleWriter:
    """A lazily-created single-worker thread pool with a flushable queue.

    Not thread-unsafe by construction: ``submit`` may be called from any
    thread, and the internal pending-future bookkeeping is guarded by its own
    lock — the same shape both ``profile_store`` and ``watchlist`` hand-rolled.
    """

    def __init__(self, *, thread_name_prefix: str, label: str,
                 default_timeout: float = 5.0) -> None:
        """Configure the writer. Creates nothing yet — the pool starts on first :meth:`submit`.

        Args:
            thread_name_prefix: Passed straight to ``ThreadPoolExecutor``, so
                the one worker thread is identifiable in a thread dump.
            label: Prefixes every log line this writer emits (e.g.
                ``"profile"``/``"watchlist"``), matching what each caller
                logged before the pool/queue mechanics moved here.
            default_timeout: Seconds :meth:`flush`/:meth:`shutdown` wait when
                the caller does not pass its own — both existing callers used
                5.0, well under SQLite's 30s ``busy_timeout``: blocking app
                shutdown for the full timeout to persist one write is the
                freeze this exists to avoid, relocated to the quit button.
        """
        self._thread_name_prefix = thread_name_prefix
        self._label = label
        self._default_timeout = default_timeout
        self._pool: "Optional[ThreadPoolExecutor]" = None
        self._pending: list[Future] = []
        self._lock = threading.Lock()

    def _ensure_pool(self) -> ThreadPoolExecutor:
        """The single writer thread, created on first use."""
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=self._thread_name_prefix)
        return self._pool

    def submit(self, fn: "Callable[..., None]", *args, **kwargs) -> Future:
        """Queue *fn* on the writer thread and return its ``Future``.

        Tracked internally for :meth:`flush`/:meth:`shutdown`; the caller is
        free to track the same ``Future`` (or wrap it, as
        ``watchlist._PendingWrite`` does) for its own bookkeeping — the two
        lists just happen to stay in step, they are not the same list.
        """
        future = self._ensure_pool().submit(fn, *args, **kwargs)
        with self._lock:
            self._pending.append(future)
        future.add_done_callback(self._forget)
        return future

    def _forget(self, future: Future) -> None:
        with self._lock:
            try:
                self._pending.remove(future)
            except ValueError:                    # already drained by flush()
                pass

    def flush(self, timeout: "Optional[float]" = None) -> bool:
        """Wait for queued writes to land.

        Returns:
            True when the queue drained inside *timeout*.
        """
        wait_s = self._default_timeout if timeout is None else timeout
        with self._lock:
            futures = list(self._pending)
        if not futures:
            return True
        _done, not_done = wait(futures, timeout=wait_s)
        if not_done:
            logger.warning("{}: {} write(s) still queued after {}s",
                           self._label, len(not_done), wait_s)
        return not not_done

    def shutdown(self, timeout: "Optional[float]" = None) -> None:
        """Drain queued writes, bounded, and stop the writer thread.

        Whether the pool is waited on is decided by whether the flush
        succeeded — an unconditional ``shutdown(wait=True)`` would hold the
        app open for however long a stuck write takes. Once the queue is
        empty, waiting costs nothing and leaves no stray thread. The pool is
        recreated lazily on the next :meth:`submit`, same as before.
        """
        drained = self.flush(timeout)
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=drained)
