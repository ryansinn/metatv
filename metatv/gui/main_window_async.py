"""_AsyncMixin — reusable async-read seam for MainWindow.

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
    """Envelope that carries a query result across the Qt thread boundary."""
    on_result: Callable[[Any], None]
    data: Any
    token: int | None
    token_ref: list[int] | None


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
    ) -> None:
        """Submit query_fn to the background executor; deliver result to on_result on the main thread.

        Args:
            query_fn: Called with a RepositoryFactory in the worker thread.
                      MUST return plain data only — no ORM objects (use DTOs).
            on_result: Called on the main thread with the plain data.
            token_ref: Optional mutable [int] counter for stale-result dropping.
                       _run_query increments it before submit; _on_query_result
                       discards results whose token no longer matches.
        """
        if token_ref is not None:
            token_ref[0] += 1
        token = token_ref[0] if token_ref is not None else None

        def _worker() -> None:
            try:
                from metatv.core.repositories import RepositoryFactory
                with self.db.session_scope() as session:
                    repos = RepositoryFactory(session)
                    data = query_fn(repos)
            except Exception:
                logger.exception("_run_query worker failed")
                return
            self._query_result.emit(
                _QueryResult(on_result=on_result, data=data, token=token, token_ref=token_ref)
            )

        self.executor.submit(_worker)

    def _on_query_result(self, result: _QueryResult) -> None:
        """Main-thread slot: drop stale results, then invoke on_result(data)."""
        if result.token_ref is not None and result.token_ref[0] != result.token:
            return
        try:
            result.on_result(result.data)
        except Exception:
            logger.exception("_run_query on_result callback raised")
