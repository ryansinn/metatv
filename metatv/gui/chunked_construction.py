"""Chunked widget construction — the ONE mechanism for building many rows
without freezing the main thread (PERF-17).

``WatchQueueSection._populate_rows`` built one chip-row widget per queue entry
synchronously, in a straight loop. On the owner's real Watch Queue — 666
entries — that froze the main thread on every data-ready; sampled 4x in one
launch, worst 3,753ms. Qt widgets are main-thread only (no executor, no
QThread can build them), so the fix is not threading, it is scheduling: build
one viewport's worth immediately, then let the event loop breathe between
batches for the rest.

``queue.py`` is the first adopter. ``filter_panel.py`` and the Discover
shelves are the next two, in their own slices — this module is meant to be
THE shared chunked-build mechanism for all three; a new caller imports
``build_chunked`` rather than hand-rolling a second ``QTimer.singleShot``
batch loop.
"""
from __future__ import annotations

from typing import Callable, Iterable, TypeVar

from PyQt6.QtCore import QObject, QTimer
from loguru import logger

T = TypeVar("T")


class ChunkHandle:
    """Live handle on one :func:`build_chunked` run.

    ``cancel()`` only ever flips a plain flag — it never touches Qt — so it is
    always safe to call: before the build starts scheduling further batches,
    after the build already finished, twice, or after the widgets it was
    building into are gone.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._done = False

    @property
    def done(self) -> bool:
        """True once every item has been built and ``on_done`` (if any) has fired.

        False after ``cancel()`` even once the last scheduled batch has been
        skipped — a cancelled run never counts as finished.
        """
        return self._done

    def cancel(self) -> None:
        """Stop any batch not yet built. Idempotent. ``on_done`` will not fire."""
        self._cancelled = True


def build_chunked(
    items: Iterable[T],
    build_one: Callable[[T], None],
    *,
    batch_size: int = 40,
    on_done: Callable[[], None] | None = None,
    parent: QObject | None = None,
) -> ChunkHandle:
    """Call ``build_one(item)`` for every item, ``batch_size`` at a time.

    The first batch runs synchronously, so the caller's viewport is already
    filled by the time this returns. Every later batch is scheduled with
    ``QTimer.singleShot(0, ...)`` so the event loop gets a turn in between —
    this is scheduling, never threading; Qt widgets stay main-thread only.

    Args:
        items: The full work list. Snapshotted into a list immediately, so a
            caller mutating its own source list afterwards cannot change what
            gets built.
        build_one: Called once per item, in order, on the main thread — free
            to build/add widgets.
        batch_size: Items per synchronous slice, including the first.
        on_done: Called exactly once, after the LAST item is built. Never
            called if the run was cancelled first.
        parent: The QObject the batches are building into, if any. Used only
            to schedule the next batch's timer AS A CHILD of it, so a
            destroyed owner takes any still-pending batch down with it — a
            second, Qt-native line of defense behind the ``cancel()`` flag
            below, which is the guard that actually decides whether a
            scheduled batch runs. Never probed directly (a test double built
            via ``Cls.__new__`` — see CLAUDE.md — raises ``RuntimeError`` on
            any Qt call, so ``parent`` is touched only lazily, the first time
            a second batch is actually needed).

    Returns:
        A :class:`ChunkHandle` — ``.cancel()`` to stop early, ``.done`` to poll.
    """
    work = list(items)
    handle = ChunkHandle()

    def schedule(callback: Callable[[], None]) -> None:
        if parent is not None:
            try:
                timer = QTimer(parent)
                timer.setSingleShot(True)
                timer.timeout.connect(callback)
                timer.start(0)
                return
            except RuntimeError:
                pass  # parent's C++ object is gone or was never initialized
        QTimer.singleShot(0, callback)

    def run_batch(start: int) -> None:
        # The liveness guard: a cancelled or superseded run must never touch
        # the section again, whether ``cancel()`` was called between batches
        # or the owner died mid-batch (caught below). This is the one line a
        # mutation check has to prove load-bearing — see the PR body.
        if handle._cancelled:
            return
        end = min(start + batch_size, len(work))
        for item in work[start:end]:
            try:
                build_one(item)
            except RuntimeError:
                # The owner's C++ object died mid-batch (e.g. app close) while
                # the Python wrapper lingered — the same trap other GUI modules
                # already guard against. Stop rather than raise into the event
                # loop; there is nothing left to build into.
                logger.debug("build_chunked: owner destroyed mid-build, stopping")
                handle._cancelled = True
                return
            if handle._cancelled:  # build_one itself triggered a cancel (re-entrant refresh)
                return
        if end >= len(work):
            handle._done = True
            if on_done is not None:
                on_done()
            return
        schedule(lambda: run_batch(end))

    run_batch(0)
    return handle
