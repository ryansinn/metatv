"""_AsyncMixin — reusable async-read (and, since DEBT-3, async-write) seam for MainWindow.

Usage (see CLAUDE.md → "_run_query — async-read seam"):

    token_ref = [0]   # one per logical query type (prevents stale results)

    def _load_something(self):
        self._run_query(
            lambda repos: repos.channels.get_favorites_dto(),
            self._on_favorites_loaded,
            token_ref=self._my_token,
        )

    def _on_favorites_loaded(self, rows):   # called on main thread
        self._populate_list(rows)

A query_fn that WRITES (a favourite/rating/hide-from-alerts toggle) passes
``commit=True`` and returns plain data (never an ORM object) for on_result to
act on — see ``_toggle_rating`` / ``_toggle_favorite_by_id`` /
``_apply_favorite_toggle`` / ``_hide_channel_from_alerts`` in
``main_window_favorites.py``.

Requires the host class to provide:
  - self.db          (Database with session_scope())
  - self.executor    (ThreadPoolExecutor — the owner's long-lived pool)
  - self._query_result  (pyqtSignal(object) defined on the MainWindow class body)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger


@dataclass
class _QueryResult:
    """Envelope that carries a query result (or failure) across the Qt thread boundary.

    On success ``error`` is None and ``data`` holds the query result. On failure
    ``error`` holds the exception and ``data`` is None; the main-thread slot routes
    it to ``on_error`` if provided.
    """
    on_result: Callable[[Any], None]
    data: Any
    token: int | None
    token_ref: list[int] | None
    on_error: Callable[[Exception], None] | None = None
    error: Exception | None = None


class _AsyncMixin:
    """Provides _run_query / _on_query_result for MainWindow.

    Mixins define no __init__ and access host state via self.*.
    """

    def _run_query(
        self,
        query_fn: Callable,
        on_result: Callable[[Any], None],
        *,
        token_ref: list[int] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        commit: bool = False,
    ) -> None:
        """Submit query_fn to the background executor; deliver result to on_result on the main thread.

        Args:
            query_fn: Called with a RepositoryFactory in the worker thread.
                      MUST return plain data only — no ORM objects (use DTOs).
            on_result: Called on the main thread with the plain data.
            token_ref: Optional mutable [int] counter for stale-result dropping.
                       _run_query increments it before submit; _on_query_result
                       discards results whose token no longer matches.
            on_error: Optional callback invoked on the main thread if query_fn
                      raises. Receives the exception. If omitted, the failure is
                      logged only — but callers that show a loading/placeholder
                      state SHOULD pass on_error to clear it, otherwise the
                      placeholder will never be replaced.
            commit: False (default) is the historical read-only contract —
                    query_fn must not write, and the scope rolls back at exit.
                    Pass True when query_fn IS a write (DEBT-3: favourite/
                    rating/hide-from-alerts toggles) — the scope commits on
                    success, exactly like Database.session_scope()'s own
                    default, moving the write off the UI thread.
        """
        if token_ref is not None:
            token_ref[0] += 1
        token = token_ref[0] if token_ref is not None else None

        def _worker() -> None:
            try:
                from metatv.core.repositories import RepositoryFactory
                # commit=False (the default) is a read-only scope: query_fn
                # returns plain data and must not write, so we never COMMIT.
                # commit=True is for a query_fn that is itself the write.
                with self.db.session_scope(commit=commit) as session:
                    repos = RepositoryFactory(session)
                    data = query_fn(repos)
            except Exception as exc:
                logger.exception("_run_query worker failed")
                # Always marshal back to the main thread so callers can clear any
                # loading/placeholder state (stale results are still dropped there).
                self._query_result.emit(_QueryResult(
                    on_result=on_result, data=None, token=token,
                    token_ref=token_ref, on_error=on_error, error=exc,
                ))
                return
            self._query_result.emit(
                _QueryResult(on_result=on_result, data=data, token=token, token_ref=token_ref)
            )

        self.executor.submit(_worker)

    def _on_query_result(self, result: _QueryResult) -> None:
        """Main-thread slot: drop stale results, then dispatch success or failure."""
        if result.token_ref is not None and result.token_ref[0] != result.token:
            return
        if result.error is not None:
            if result.on_error is None:
                return   # already logged in the worker; nothing more to deliver
            try:
                result.on_error(result.error)
            except Exception:
                logger.exception("_run_query on_error callback raised")
            return
        try:
            result.on_result(result.data)
        except Exception:
            logger.exception("_run_query on_result callback raised")
