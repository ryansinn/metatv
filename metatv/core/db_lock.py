"""One retry policy for a transient SQLite lock, for every writer that needs it.

SQLite has a single writer. ``busy_timeout=30000`` (set on every connection in
:mod:`metatv.core.database`) absorbs ordinary contention by WAITING, and for
most of the app that is enough. Two shapes get past it:

* a transaction that READS and then writes. SQLite cannot upgrade a read
  transaction once another connection has committed underneath it, so it
  returns ``SQLITE_BUSY`` **immediately** — ``busy_timeout`` does not apply to
  that case at all. Retrying the whole transaction is the documented remedy,
  and it is safe precisely because nothing was committed.
* a genuinely long write. A bulk pass can hold the lock past thirty seconds, at
  which point the waiter gives up and raises.

``ChannelRepository._retry_on_lock`` was written for the second shape on
2026-08-01 and lives on the repository because it needs ``self.session`` to
roll back. The watch-list writer is the first caller that has neither a
repository nor a shared session — it opens its own ``session_scope()`` per
write — so rather than a second copy trimmed to fit, the policy moves here and
both call it. (CLAUDE.md: "Need a variant → extend the shared core (one helper
both call), don't copy-and-trim.")

What paid for it: on 2026-09-01 the owner deleted two watch-list rules while an
EPG pass held the writer. Both DELETEs raised ``database is locked`` from the
``watchlist-write`` thread and both rules stayed in the list, each with a toast
saying it could not be removed. The write was already off the UI thread, so it
could have afforded to wait and simply never did.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from loguru import logger
from sqlalchemy.exc import OperationalError

T = TypeVar("T")

#: How many times a locked write is re-attempted before the error reaches the
#: caller. Three, matching what the bulk writers have used since 2026-08-01.
LOCK_RETRY_ATTEMPTS = 3

#: Seconds between attempts. Long enough that a short bulk commit finishes in
#: the gap, short enough that a queued user edit is not left hanging: with the
#: default attempts this bounds the added wait at ~4s on top of whatever each
#: attempt itself spends waiting on ``busy_timeout``.
LOCK_RETRY_DELAY_S = 2.0


def is_lock_error(exc: BaseException) -> bool:
    """Whether *exc* is SQLite's "database is locked", and not another failure.

    Substring rather than an error code: SQLAlchemy wraps the DBAPI error and
    the code is not preserved on the wrapper, while the message is stable
    across both ``sqlite3.OperationalError`` and its SQLAlchemy wrapper.

    Defined once here so no caller re-invents the test — the one place a typo
    turns "retry a lock" into "retry everything, including a genuine bug".
    """
    return isinstance(exc, OperationalError) and "locked" in str(exc).lower()


def retry_on_lock(
    label: str,
    call: Callable[[], T],
    *,
    before_retry: Callable[[], None] | None = None,
    attempts: int = LOCK_RETRY_ATTEMPTS,
    delay_s: float = LOCK_RETRY_DELAY_S,
) -> T:
    """Run *call*, retrying it whole while SQLite reports the database locked.

    ``call`` must be safe to re-run from scratch. That is not a restriction in
    practice: an attempt that raised a lock error committed nothing, so a retry
    re-runs against exactly the state the first attempt saw.

    Any other exception propagates on the first attempt, and so does a lock
    error on the last one — only contention is retried, never a bug.

    Args:
        label: Short phase name, used in log messages only.
        call: Zero-argument callable to invoke and, on a lock, re-invoke.
        before_retry: Called after a lock error, before sleeping — the seam a
            caller with a long-lived session uses to roll it back. Callers that
            open a fresh session per attempt (``session_scope``) need nothing
            here, because the context manager has already rolled back.
        attempts: Total attempts, including the first.
        delay_s: Seconds to sleep between attempts.

    Returns:
        Whatever ``call`` returned on the attempt that succeeded.

    Raises:
        Whatever ``call`` raised, once retries are exhausted or the error was
        not a lock.
    """
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except OperationalError as exc:
            if not is_lock_error(exc):
                raise
            if before_retry is not None:
                before_retry()
            if attempt == attempts:
                logger.error(
                    "{}: still locked after {} attempt(s), giving up",
                    label, attempts,
                )
                raise
            logger.warning(
                "{}: locked (attempt {}/{}); retrying in {}s",
                label, attempt, attempts, delay_s,
            )
            time.sleep(delay_s)
    raise AssertionError("unreachable")  # pragma: no cover
