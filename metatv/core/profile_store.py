"""Where the user's own state lives, once the database is available.

``config.yaml`` was doing three jobs wearing one coat. Measured on the owner's
file: 1,849 of 2,252 lines — 82% — are not settings at all but **user state**,
things they selected and watermarks recording what they have already been
shown. The genuine preferences are 403 lines across 257 keys. A checkbox
rewrote all of it, because you cannot write one key to a photograph.

This module is the persister for that 82%. It is not a second source of truth:
:class:`~metatv.core.config.Config` remains the in-memory holder and every one
of the ~46 call sites still reads ``config.<field>``. Only where the bytes land
changes.

Why the reads do not move
-------------------------
There is exactly one ``Config.load()`` in the app and the GUI never re-reads the
file. The live state has always been in memory; the YAML was only ever written.
So "where should this live" is purely a persistence question, and answering it
at the persistence layer leaves every consumer untouched. Same call the QA
sidecar made, and for the same reason.

Writes never run on the calling thread
--------------------------------------
The hard-won half. ``config.save()`` has 130 call sites and most of them are
click handlers. SQLite has one writer and a 30 s ``busy_timeout``, and this
project has already watched that go wrong: while a migration held the write
lock, ``watchlist``'s UI-thread DELETE blocked for 29.8 s and froze the app. So
writes here are queued to a single-worker pool exactly as ``core/watchlist.py``
does it, and :func:`record` returns at once.

What this store does NOT need, and watchlist does
-------------------------------------------------
Watchlist replays a ``_pending`` list over its rows so a read cannot see the gap
between a queued write and a landed one. There is no such gap here, because
**reads never come to this module at all** — they read the in-memory ``Config``,
which was updated before ``save()`` was ever called. That makes this store
write-only after startup, and it is the one place its shape is simpler than the
seam it is modelled on.

Migration is attach-time, per key, and verified
-----------------------------------------------
:func:`attach` is the whole migration. For each profile field: if the store has
a row, the store wins and the value is loaded into the config; if it does not,
the current (YAML-loaded) value is written, **read back, and compared** — and
only a key that survives that round trip is reported as owned. A key that fails
stays in ``config.yaml`` and is logged. Nothing is pruned on a promise.

That per-key granularity is the point. One field that will not round-trip must
not hold up the other thirty-three, and it must not take the user's data with
it.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.database import Database

#: The database the profile lives in, bound once at startup by :func:`bind`.
#:
#: Module-level rather than injected, matching ``core/watchlist.py``: the thing
#: that persists (``Config.save``) holds no ``Database`` and giving it one would
#: be the plumbing this seam exists to avoid. Unbound — every test that does not
#: ask for it, and any headless path — the store is simply inert and ``Config``
#: keeps writing YAML exactly as before. That fallback is not a degraded mode;
#: it is the behaviour this replaces, still there.
_db: "Optional[Database]" = None

#: Keys this store has proven it owns: written, read back, and compared. Only
#: these are excluded from ``config.yaml``. Empty until :func:`attach` runs, so
#: a crash before that point leaves the YAML authoritative.
_owned: set[str] = set()

#: How long :func:`flush` waits. Deliberately well under the 30 s
#: ``busy_timeout``: blocking app shutdown for 30 s to persist a checkbox is the
#: freeze this module exists to remove, relocated to the quit button. A write
#: that misses the window is logged.
_FLUSH_TIMEOUT = 5.0

_writer: "Optional[ThreadPoolExecutor]" = None
_pending: list[Future] = []
_lock = threading.Lock()


def bind(db: "Optional[Database]") -> None:
    """Point the profile store at *db*. Drains writes owed to the previous one."""
    global _db
    flush()
    _db = db


def unbind() -> None:
    """Detach from the database and forget what was owned.

    Clearing ``_owned`` is the load-bearing half: a key is only kept out of
    ``config.yaml`` because a database was proven to hold it, so losing the
    database must put it straight back in the file. Tests use this to force the
    YAML path, and it is also what makes the store safe to rebind.
    """
    global _db
    shutdown()
    _db = None
    _owned.clear()


def is_bound() -> bool:
    """True when a database is available to persist to."""
    return _db is not None


def owned_keys() -> frozenset[str]:
    """The keys this store has verifiably taken over from ``config.yaml``."""
    return frozenset(_owned)


def flush(timeout: float = _FLUSH_TIMEOUT) -> bool:
    """Wait for queued writes to reach the database.

    Returns:
        True when the queue drained inside *timeout*.
    """
    with _lock:
        futures = [f for f in _pending if f is not None]
    if not futures:
        return True
    _done, not_done = wait(futures, timeout=timeout)
    if not_done:
        logger.warning("profile: {} write(s) still queued after {}s",
                       len(not_done), timeout)
    return not not_done


def shutdown(timeout: float = _FLUSH_TIMEOUT) -> None:
    """Drain queued writes, bounded, and stop the writer thread.

    Registered on ``MainWindow``'s cleanup registry so it runs before
    ``closeEvent`` closes the database underneath a queued write.

    Whether the pool is waited on is decided by whether the flush succeeded —
    an unconditional ``shutdown(wait=True)`` would hold the app open for however
    long a stuck write takes. Once the queue is empty, waiting costs nothing and
    leaves no stray thread.
    """
    global _writer
    drained = flush(timeout)
    pool, _writer = _writer, None
    if pool is not None:
        pool.shutdown(wait=drained)


def _ensure_writer() -> ThreadPoolExecutor:
    """The single writer thread, created on first use.

    ``max_workers=1`` is not a resource decision. It serialises this store's
    writes against each other, so two saves of the same key cannot land in the
    wrong order, and it keeps the subsystem from contending with itself for
    SQLite's one write lock — the same rule ``EpgManager`` follows for fetches.
    """
    global _writer
    if _writer is None:
        _writer = ThreadPoolExecutor(max_workers=1,
                                     thread_name_prefix="profile-store")
    return _writer


def read_all() -> dict[str, Any]:
    """Every stored key. ``{}`` when unbound or unreadable.

    A missing key and a key stored as ``None`` are different answers, and this
    returns both faithfully — ``None`` is a real value for the filter sentinels.
    """
    if _db is None:
        return {}
    from metatv.core.database import ProfileDB

    try:
        with _db.session_scope(commit=False) as session:
            return {row.key: row.value for row in session.query(ProfileDB).all()}
    except Exception:
        logger.exception("profile: could not read the stored profile")
        return {}


def _write_now(values: dict[str, Any]) -> None:
    """UPSERT *values*. Runs on the writer thread (or the caller's, in attach)."""
    if _db is None or not values:
        return
    from metatv.core.database import ProfileDB

    with _db.session_scope() as session:
        for key, value in values.items():
            row = session.get(ProfileDB, key)
            if row is None:
                session.add(ProfileDB(key=key, value=value))
            else:
                row.value = value


def record(values: dict[str, Any]) -> None:
    """Queue *values* to be persisted. Returns immediately.

    Args:
        values: Only the keys that actually changed. ``Config.save`` does that
            comparison; sending everything would turn each checkbox back into a
            full rewrite, which is the cost this store exists to remove.
    """
    if _db is None or not values:
        return
    payload = dict(values)                    # detached from the caller's dict

    def _task() -> None:
        try:
            _write_now(payload)
        except Exception:
            # Logged, never raised: a failed profile write must not take down a
            # background thread, and the value is still correct in memory and
            # will be retried by the next save that touches the key.
            logger.exception("profile: could not persist {}", sorted(payload))

    future = _ensure_writer().submit(_task)
    with _lock:
        _pending.append(future)
    future.add_done_callback(_forget)


def _forget(future: Future) -> None:
    with _lock:
        try:
            _pending.remove(future)
        except ValueError:                    # already drained by flush()
            pass


def attach(config, field_names) -> frozenset[str]:
    """Load the stored profile into *config*, migrating any key not yet held.

    This is the whole migration, and it is idempotent: run it on a fresh
    database and every key is seeded from the YAML; run it again and every key
    is already there and the stored value simply wins.

    Synchronous on purpose. It happens once, at startup, before any window is on
    screen, and everything after it depends on knowing which keys are owned — a
    queued answer would mean the first ``save()`` racing the migration for the
    right to write ``config.yaml``.

    Args:
        config: The freshly loaded ``Config``. Mutated in place.
        field_names: The profile field names, derived by ``Config`` from its own
            field declarations — never a list maintained here, which would go
            stale the first time someone adds a field without reading this.

    Returns:
        The keys now owned by the store. Only these leave ``config.yaml``.
    """
    _owned.clear()
    if _db is None:
        return frozenset()

    stored = read_all()
    loaded, migrated, refused = [], [], []

    for key in sorted(field_names):
        if key in stored:
            setattr(config, key, stored[key])
            _owned.add(key)
            loaded.append(key)
            continue

        value = getattr(config, key)
        try:
            _write_now({key: value})
        except Exception:
            logger.exception("profile: could not migrate {!r} to the database", key)
            refused.append(key)
            continue

        # Read back and COMPARE before claiming the key. The prune that follows
        # is irreversible with one generation of .bak behind it, so "it worked"
        # has to be something observed, not assumed. A type that does not
        # survive a JSON round trip (a tuple arriving back as a list, a dict with
        # non-string keys) is caught here rather than by the user noticing their
        # selections have quietly changed shape.
        back = read_all().get(key, _MISSING)
        if back is _MISSING or back != value:
            logger.error(
                "profile: {!r} did not survive the round trip ({!r} -> {!r}); "
                "leaving it in config.yaml", key, value, back)
            refused.append(key)
            continue

        _owned.add(key)
        migrated.append(key)

    if migrated:
        logger.info("profile: migrated {} key(s) from config.yaml to the database",
                    len(migrated))
    if loaded:
        logger.debug("profile: loaded {} stored key(s)", len(loaded))
    if refused:
        logger.warning("profile: {} key(s) stayed in config.yaml: {}",
                       len(refused), ", ".join(refused))
    return frozenset(_owned)


class _Missing:
    """Distinguishes "no row" from a row whose value is ``None``."""

    def __repr__(self) -> str:                       # pragma: no cover - debug aid
        return "<no row>"


_MISSING = _Missing()
