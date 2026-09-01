"""Single-flight guard for whole-library repository sweeps.

A whole-library pass is triggered by more than one caller, and those callers
are not independent: ``TmdbEnrichmentManager._propagate_after_drain`` fires when
the enrich queue empties, ``_ProviderMixin._on_all_refreshes_finished`` fires
when a refresh completes, and one refresh satisfies both at the same moment.

Owner log 2026-08-31 caught the tmdb sibling sweep running CONCURRENTLY on two
pools (``tmdb_enrich_0`` and ``ThreadPoolExecutor-7_1``), each holding SQLite's
single write lock against the other. Both exhausted their lock retries and
aborted, the bulk catalogue INSERT of the refresh that triggered them failed
the same way (the source reported ``success=False``), and the survivor kept the
app's close open for 40 seconds.

Standing down costs nothing: the pass already in flight scans the whole
library, so it covers the rows of the caller that yielded.

Lives in its own module rather than inside the repository mixin because the
racing callers each build their own ``RepositoryFactory`` on their own session
— an instance attribute could never see the other one, so the lock has to be
module scope, and a cross-cutting concurrency guard is not ingestion logic.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

from loguru import logger

#: One lock per sweep name, created on first use.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    """Return the process-wide lock for the sweep called *name*."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(name, threading.Lock())


@contextmanager
def single_flight(name: str):
    """Run the body only if no other pass of *name* is already running.

    Non-blocking by design: a second caller stands down immediately rather than
    queueing behind a multi-minute pass whose work would be redundant anyway.

    Args:
        name: Sweep identifier, used for the lock and the log line.

    Yields:
        True if the caller holds the sweep and should do the work, False if
        another pass is already in flight and this one should stand down.
    """
    lock = _lock_for(name)
    if not lock.acquire(blocking=False):
        logger.info(
            "{}: a whole-library pass is already running; standing down "
            "(it covers these rows too)", name)
        yield False
        return
    try:
        yield True
    finally:
        lock.release()


def is_running(name: str) -> bool:
    """Return True if a pass of *name* is currently in flight (tests)."""
    return _lock_for(name).locked()
