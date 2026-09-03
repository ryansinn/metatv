"""Shared off-thread refresh skeleton for sidebar sections (B8-5).

Unifies the executor + signal + try/except/emit-None + clear/dispatch that
Favorites/History/Queue each hand-rolled — the duplication the `_run_query` seam
couldn't reach from standalone `QWidget`s. A section opts in by:

  * declaring ``_data_ready = pyqtSignal(object)``  (``list`` on success, ``None`` on
    load failure),
  * calling ``self._init_background_refresh()`` in ``__init__`` (creates the owned
    executor and connects the signal),
  * implementing ``_refresh_list()`` (the QListWidget to clear/populate),
    ``_load_rows()`` (returns plain data; runs on the worker — no widget access),
    ``_load_error_message()``, and ``_populate_rows(rows)`` (main thread).

Invariants preserved (CLAUDE.md): ``max_workers=1`` (SQLite-lock rule + last-write-wins
on rapid refresh), the ``_executor`` attribute name (``MainWindow.setup_ui``'s closeEvent
cleanup keys on ``hasattr(section, "_executor")``), and the ``None`` → ``show_load_error``
visible-failure row.

``RecommendedSection`` deliberately does NOT use this: its ``None`` means a *valid empty
state* ("rate to get recommendations"), not a failure, and it emits a
``(recs, year_by_id)`` tuple — different semantics, so folding it would change behavior.
Anything that exception must ALSO get belongs one level down, on
``CollapsibleSection`` — which is where the scroll-preservation helpers this module
calls now live (they were here, and the exception silently missed out on them).

``refresh()`` also defers to a running migration pass (MIG-1): on the owner's 2026-09-03
launch log a 3-minute ``prefix_rescan`` v6 pass left Recommended taking ~30s to show
anything and every other section sitting empty with no explanation, while the sections'
own reads contended for the same SQLite writer turn the migration needed. Rather than
submit into that contention, ``refresh()`` checks ``migration_gate.is_running()`` first —
same sibling pattern as ``TmdbEnrichmentManager._defer_for_migration`` on the write side —
renders a waiting row, and retries itself once, 3s later.
"""
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QTimer

from loguru import logger

from metatv.core import migration_gate

#: Text shown instead of the loading row while a migration pass holds the DB.
_WAITING_FOR_MIGRATION_MESSAGE = "Waiting for the library update…"

#: How long to wait before a deferred refresh() retries itself.
_MIGRATION_RETRY_MS = 3000


class BackgroundRefreshMixin:
    """Provides refresh()/_bg_refresh()/_on_data_ready(); mix in before CollapsibleSection.

    ``show_load_error`` comes from ``CollapsibleSection`` via the MRO.
    """

    def _init_background_refresh(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._data_ready.connect(self._on_data_ready)
        #: The single pending migration-retry timer, or None. Tracked so a
        #: second refresh() call while still waiting arms no second timer.
        self._migration_retry_timer: QTimer | None = None

    def shutdown(self) -> None:
        """Stop this section's worker pool.

        Defined on the MIXIN, so every section that composes it is covered at
        once. Six sections do (`favorites`, `history`, `queue`, `alerts`,
        `recommended`, and the base) and NONE of them could stop the pool
        ``_init_background_refresh`` hands them — six threads that outlived the
        window, found by deriving the owners rather than listing them.

        Putting it here rather than in each section is the point: a seventh
        section gets a working shutdown for free, which is exactly how the six
        came to be missing one.

        Safe before ``_init_background_refresh`` (a section torn down mid-build
        never made a pool) and safe twice.

        Also cancels a pending migration-retry timer (see ``refresh()``) — a
        section torn down while waiting out a migration pass must not fire a
        retry against a widget that no longer exists.
        """
        self._cancel_migration_retry()
        executor = self.__dict__.get("_executor")
        if executor is None:
            return
        executor.shutdown(wait=False, cancel_futures=True)

    def _cancel_migration_retry(self) -> None:
        """Stop and drop the pending migration-retry timer, if one is armed."""
        timer = self.__dict__.get("_migration_retry_timer")
        if timer is None:
            return
        timer.stop()
        self._migration_retry_timer = None

    def _loading_message(self) -> str:
        """Text for the transient loading placeholder. Sections MAY override."""
        return "Loading…"

    def refresh(self) -> None:
        """Kick off an off-thread load; clears the list and shows a loading row.

        The placeholder occupies the load window so the section never shows its
        stale empty/zero state while the background read runs. ``_on_data_ready``
        clears the list before rendering, which replaces the placeholder.

        The scroll offset is captured here, BEFORE the clear that destroys it,
        and restored once the new rows are in. A section refresh is usually the
        side effect of a single action — marking one item watched, queueing one
        title — and losing your place in a long list every time you act on one
        row makes the list unusable for exactly the bulk triage it exists for
        (owner report, repeatedly).

        ``_capture_scroll``/``_restore_scroll`` come from ``CollapsibleSection``
        so the sections that do NOT compose this mixin share the one definition.

        Defers instead of submitting while ``migration_gate.is_running()`` — see
        ``_defer_for_migration_wait`` and the module docstring (MIG-1).
        """
        if migration_gate.is_running():
            self._defer_for_migration_wait()
            return
        lst = self._refresh_list()
        self._capture_scroll(lst)
        lst.clear()
        self.show_loading(lst, self._loading_message())
        self._executor.submit(self._bg_refresh)

    def _defer_for_migration_wait(self) -> None:
        """Render a waiting row and arm a single retry instead of contending.

        A section's background read is small next to a migration pass's bulk
        batched commits, but both want the same SQLite writer turn — submitting
        anyway is how Recommended took ~30s and every other section sat empty
        with no explanation on the owner's 2026-09-03 launch log (a 3-minute
        ``prefix_rescan`` v6 pass). Skip the read, tell the user why nothing has
        loaded, and retry once the gate clears.

        The retry timer must not stack: a second ``refresh()`` call while
        already waiting (e.g. a provider mutation firing the canonical refresh
        mid-wait) finds ``_migration_retry_timer`` already armed and no-ops —
        one pending retry is enough, since the retry itself calls ``refresh()``
        again and will pick up whatever prompted the second call.
        """
        lst = self._refresh_list()
        self.show_loading(lst, _WAITING_FOR_MIGRATION_MESSAGE)
        if self.__dict__.get("_migration_retry_timer") is not None:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_migration_retry)
        timer.start(_MIGRATION_RETRY_MS)
        self._migration_retry_timer = timer

    def _on_migration_retry(self) -> None:
        """Fired 3s after a deferred refresh(); the gate may or may not be clear yet."""
        self._migration_retry_timer = None
        self.refresh()

    def _bg_refresh(self) -> None:
        """Worker thread — NO widget access. Loads rows, emits them (or None on failure)."""
        try:
            rows = self._load_rows()
        except Exception:
            logger.exception("{} background refresh error", type(self).__name__)
            self._data_ready.emit(None)
            return
        self._data_ready.emit(rows)

    def _on_data_ready(self, rows) -> None:
        """Main thread: clear, then render rows or a visible failure row."""
        lst = self._refresh_list()
        lst.clear()
        if rows is None:
            self.show_load_error(lst, self._load_error_message())
            # Drop the saved offset: an error row is a different, much shorter
            # list, and scrolling it to a stale position would hide the message.
            self._drop_captured_scroll()
            return
        self._populate_rows(rows)
        self._restore_scroll(lst)
        # Fit the rows to the section's height and re-read its header. Deferred
        # so the list has actually laid out — measuring its viewport in the same
        # tick as the populate reads a stale height, which silently produces a
        # budget for the size the section had BEFORE the rows arrived.
        QTimer.singleShot(0, self.reapply_row_budget)
