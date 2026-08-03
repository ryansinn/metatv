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
"""
from concurrent.futures import ThreadPoolExecutor

from loguru import logger


class BackgroundRefreshMixin:
    """Provides refresh()/_bg_refresh()/_on_data_ready(); mix in before CollapsibleSection.

    ``show_load_error`` comes from ``CollapsibleSection`` via the MRO.
    """

    def _init_background_refresh(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._data_ready.connect(self._on_data_ready)

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
        """
        lst = self._refresh_list()
        self._pending_scroll = self._scroll_offset(lst)
        lst.clear()
        self.show_loading(lst, self._loading_message())
        self._executor.submit(self._bg_refresh)

    @staticmethod
    def _scroll_offset(lst) -> int:
        """Current vertical scroll offset, or 0 when the widget has no bar yet."""
        bar = lst.verticalScrollBar() if hasattr(lst, "verticalScrollBar") else None
        return bar.value() if bar is not None else 0

    def _restore_scroll(self, lst) -> None:
        """Put the list back where the user had it, clamped to the new content.

        Clamping matters: the refresh may have returned FEWER rows (the item was
        removed from the queue), so the old offset can exceed the new maximum.
        Qt clamps on assignment, but doing it explicitly keeps the intent
        obvious and the value inspectable in tests.
        """
        offset = self.__dict__.pop("_pending_scroll", 0)
        if not offset:
            return
        bar = lst.verticalScrollBar() if hasattr(lst, "verticalScrollBar") else None
        if bar is None:
            return
        bar.setValue(min(offset, bar.maximum()))

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
            self.__dict__.pop("_pending_scroll", None)
            return
        self._populate_rows(rows)
        self._restore_scroll(lst)
