"""DB-10 — bounds concurrent BACKGROUND write transactions against SQLite's
single write lock.

SQLite has exactly one write lock for the whole database (see
``Database.__init__``'s ``busy_timeout=30000`` pragma). A second concurrent
background writer cannot make progress anyway — it can only burn
``busy_timeout`` holding a connection open while it waits its turn. Capping
in-flight BACKGROUND writers at :data:`MAX_CONCURRENT_BACKGROUND_WRITERS`
converts that contention into an orderly queue instead of a retry storm: the
write gateway itself stays rejected (project decision — see the DB-10
worklog entry), this is the narrower fix for the same symptom, a slow
provider stacking several background writers against one lock at once.

Reached only through :meth:`Database.session_scope`'s ``background=True``
kwarg, or a direct ``with background_write_gate():`` wrap around a legacy
``get_session()``/``try``/``finally`` block that has not been migrated to
``session_scope`` (CLAUDE.md: migrating that pattern is its own concern, out
of scope here — DB-10 only gates the write paths that already exist). Never
call this for a UI-triggered write (a favourite toggle, a rating, anything on
the ``_run_query(commit=True)`` path) — those stay latency-sensitive and
ungated by design.

Cap is 1, not configurable
---------------------------
A second concurrent background writer cannot acquire SQLite's single write
lock anyway, so raising this only trades an orderly queue for the exact
contention it exists to avoid. A plain module constant, not a ``Config``
field — add a knob only if a caller is found that genuinely needs 2+, and
say why; none does today.

Timeout, not an unbounded wait
-------------------------------
A gate that can block forever is worse than the contention it replaces —
``Database.close()``'s own ``_CLOSE_BUSY_TIMEOUT_MS`` comment records what one
indefinite 30s wait already cost the owner (a Ctrl+C during shutdown).
:data:`GATE_TIMEOUT_S` is half of the connection's own ``busy_timeout``
(30000ms): a caller that times out here still has the OTHER half of that
budget left to actually acquire SQLite's lock once it proceeds, so the
combined worst case (gate wait + SQLite wait) stays inside the failure mode
that already existed pre-DB-10 rather than stacking a second full timeout on
top of it. On timeout this logs once and PROCEEDS WITHOUT the gate — never
silently skips the write, and never blocks indefinitely. SQLite's own
``busy_timeout`` remains the final correctness backstop either way.

Reentrant per thread
---------------------
A background writer that already holds the gate on its own thread (a write
nested inside another write's own call chain — e.g. a migration task,
already gated at ``MigrationManager``'s dispatch chokepoint, that calls
``MetadataManager._persist_metadata_cache``, itself gated) must not block on
itself. A depth counter keyed by thread ident decides that, never the
semaphore, so nesting can never deadlock a writer against its own call stack.

Main thread always passes straight through
--------------------------------------------
Every real background writer in this codebase already runs on its own
dedicated worker thread (a manager's single-worker ``ThreadPoolExecutor``, or
a plain ``threading.Thread`` run loop) — nothing this module considers
"background" ever executes on the Qt main thread. Several write helpers are
nonetheless SHARED between a manager's background loop and a direct
UI-triggered call on the main thread (e.g. ``DownloadManager._set_state``,
used by both the transfer loop and ``pause()``/``resume()``/``cancel()``).
Rather than fork every such helper into a gated and an ungated copy, the gate
itself never blocks the main thread — blocking the UI thread on this gate
would recreate exactly the freeze DB-10 exists to prevent, not something it
should ever cause.

Not the ConnectionAccountant
------------------------------
``ConnectionAccountant`` (``core/connection_accountant.py``) arbitrates a
DIFFERENT resource — a provider's own stream-connection slots — through its
own plain ``threading.Lock``, entirely in memory, no SQLite involved. The two
can never deadlock against each other: the accountant's lock is acquired and
released within a single one of its own methods and never held across a call
back into caller code (``_try_acquire`` calls preempt listeners "outside the
lock, deliberately" — see its own docstring), so nothing holding the
accountant's lock ever blocks waiting on this gate. Symmetrically, every
caller that holds THIS gate and also touches the accountant (e.g.
``DownloadManager._transfer`` acquires a connection slot, then later opens a
gated ``session_scope`` to flush progress; ``RecordingManager._record`` the
same) only ever makes fast, non-blocking, in-memory accountant calls
(``acquire``/``release``/``holders``/``in_use``) while holding this gate —
never the reverse (waiting ON the accountant while blocking others out of
this gate). No cycle is possible because neither primitive ever WAITS while
holding the other.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from loguru import logger

#: SQLite has exactly one write lock for the whole database — see module
#: docstring "Cap is 1, not configurable".
MAX_CONCURRENT_BACKGROUND_WRITERS = 1

#: Ceiling on how long a background writer waits for the gate before giving
#: up and proceeding anyway — see module docstring "Timeout, not an
#: unbounded wait". Half of the connection's own busy_timeout (30000ms,
#: Database.__init__).
GATE_TIMEOUT_S = 15.0

_gate = threading.Semaphore(MAX_CONCURRENT_BACKGROUND_WRITERS)

#: Reentrant hold tracking, keyed by thread ident. Guarded by its own lock —
#: deliberately separate from ``_gate`` itself, so checking "do I already
#: hold it" never needs the semaphore.
_holder_lock = threading.Lock()
_holder_depth: "dict[int, int]" = {}


@contextmanager
def background_write_gate() -> "Iterator[None]":
    """Serialize BACKGROUND write transactions to at most one in flight.

    See module docstring for the full contract (cap, timeout, reentrancy,
    main-thread bypass). Never call directly from application code that isn't
    itself a background-writer chokepoint — go through
    ``Database.session_scope(commit=True, background=True)`` wherever that
    pattern fits, and reserve a direct ``with background_write_gate():`` wrap
    for a legacy ``get_session()`` block (see ``EpgManager._run_fetch``/
    ``_relink_worker``, ``MigrationManager._run_all``).
    """
    if threading.current_thread() is threading.main_thread():
        # Never a background writer by construction — see module docstring
        # "Main thread always passes straight through".
        yield
        return

    ident = threading.get_ident()
    with _holder_lock:
        depth = _holder_depth.get(ident, 0)
        if depth:
            _holder_depth[ident] = depth + 1
            reentrant = True
        else:
            reentrant = False

    if reentrant:
        try:
            yield
        finally:
            with _holder_lock:
                remaining = _holder_depth.get(ident, 1) - 1
                if remaining <= 0:
                    _holder_depth.pop(ident, None)
                else:
                    _holder_depth[ident] = remaining
        return

    acquired = _gate.acquire(timeout=GATE_TIMEOUT_S)
    if acquired:
        with _holder_lock:
            _holder_depth[ident] = 1
    else:
        logger.warning(
            "write_gate: {} waited {:.0f}s for the background-write gate "
            "and gave up — proceeding without it. Another background writer "
            "is slow, not necessarily stuck; SQLite's own busy_timeout is "
            "the final backstop.",
            threading.current_thread().name, GATE_TIMEOUT_S,
        )
    try:
        yield
    finally:
        if acquired:
            with _holder_lock:
                _holder_depth.pop(ident, None)
            _gate.release()
