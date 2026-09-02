"""The one place that answers "what is on the watch list".

Twenty-four sites across nine modules read ``config.epg_watchlist_patterns``
directly, each re-deciding the same small questions: is ``None`` the same as
empty (some wrote ``or []``, some did not), does matching lowercase (three did,
six did not), does adding de-duplicate (four checked, one did not). That is the
shape a chokepoint exists to end — and it is also what makes the storage
question tractable, because the *store* is one line behind this seam rather
than twenty-four call sites.

Module-level functions taking a ``Config`` rather than an injected object:
every one of those nine modules already holds ``self.config``, so this needs no
plumbing to adopt. When the backing store moves to the database, only the
bodies here change.

**A rule is one stored list rendered on two surfaces** — Watch Alerts and the
EPG watchlist — never two lists (settled design, ROADMAP). This module is that
list.

Writes never run on the calling thread
--------------------------------------
Six click handlers across four modules call :func:`add` and :func:`remove` —
the EPG watch-list panel, the details pane's watch toggle, the agenda widget
and the main window. Every one of them ran a DELETE or an INSERT **on the UI
thread**, and SQLite has one writer with a 30 s ``busy_timeout``: while the
``sports_reclassify`` migration held the lock, ``_db_remove`` blocked for the
full timeout and the whole app froze. The owner's watchdog logged the stalls at
29.8 s, 29.9 s and 31.6 s, and then the click did nothing at all, because the
old ``_db_remove`` logged the failure and returned ``False`` — the user pressed
Remove and the rule stayed.

So the write is queued to a single-worker pool and the call returns at once.
The three things that makes work:

* ``max_workers=1`` — watch-list writes serialise against each other, so an add
  followed by a remove of the same pattern cannot land in the wrong order, and
  the subsystem never contends with itself (the same rule ``EpgManager`` follows
  for its fetches).
* A queued write sits in ``_pending`` until the database confirms it, and every
  read replays ``_pending`` over the stored rows. The answer :func:`add`,
  :func:`remove` and :func:`contains` give is therefore the same before and
  after the write lands — a caller cannot see the gap.
* When a write FAILS, the entry leaves ``_pending`` (so the next read shows the
  truth, not the optimistic guess) and the handler installed by
  :func:`set_write_error_handler` is called with the real cause. The GUI's
  handler — ``gui/watchlist_write_notifier.py`` — turns that into an error
  toast. Silence is what this replaces.

``core/`` has no UI dependency, so the handler is a plain callable and it is
invoked **on the writer thread**: a Qt handler must marshal to the main thread
itself, which is exactly what the notifier's private signal does.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

from loguru import logger

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.config import Config
    from metatv.core.watchlist_matching import WatchRule
    from metatv.core.database import Database


#: The database the list lives in, bound once at startup by ``bind()``.
#:
#: A module-level binding rather than a parameter, because the twenty-four call
#: sites hold a ``Config`` and not all of them can reach a ``Database`` — adding
#: one to each is the plumbing this seam exists to avoid. Unbound (tests, any
#: headless path) the functions fall back to config, so nothing here can make a
#: caller fail for want of a database.
_db: "Optional[Database]" = None

_OP_ADD = "add"
_OP_REMOVE = "remove"

#: How long :func:`flush` waits for queued writes. Generous against the 30 s
#: ``busy_timeout`` would mean a 30 s app close, and a watch rule is not worth
#: that; a lost write is logged and surfaced like any other failure.
_FLUSH_TIMEOUT = 5.0


@dataclass(eq=False)
class _PendingWrite:
    """One queued mutation. ``eq=False`` so removal from ``_pending`` is by
    identity — two adds of the same text are two entries, not one."""

    op: str
    text: str
    future: "Optional[Future]" = field(default=None)


_writer: "Optional[ThreadPoolExecutor]" = None
_pending: list[_PendingWrite] = []
_lock = threading.Lock()
_write_error_handler: "Optional[Callable[[str, str, str], None]]" = None


def set_write_error_handler(
    handler: "Optional[Callable[[str, str, str], None]]",
) -> None:
    """Install the callback invoked when a queued write fails.

    Args:
        handler: Called as ``handler(op, pattern, message)`` where ``op`` is
            ``"add"`` or ``"remove"``. **Called on the writer thread** — a Qt
            handler must marshal to the main thread itself. ``None`` clears it.
    """
    global _write_error_handler
    _write_error_handler = handler


def flush(timeout: float = _FLUSH_TIMEOUT) -> bool:
    """Wait for queued writes to reach the database.

    Args:
        timeout: Seconds to wait.

    Returns:
        True when the queue drained inside *timeout*.
    """
    with _lock:
        futures = [w.future for w in _pending if w.future is not None]
    if not futures:
        return True
    _done, not_done = wait(futures, timeout=timeout)
    if not_done:
        logger.warning("watchlist: {} write(s) still queued after {}s",
                       len(not_done), timeout)
    return not not_done


def shutdown(timeout: float = _FLUSH_TIMEOUT) -> None:
    """Drain queued writes, bounded, and stop the writer thread.

    Registered on ``MainWindow``'s cleanup registry, so it runs before
    ``closeEvent`` closes the database underneath a queued write.

    Whether the pool is waited on is decided by whether the flush succeeded.
    An unconditional ``shutdown(wait=True)`` blocks until the worker returns
    however long that takes, so a write stuck on the 30 s ``busy_timeout``
    would hold the app open for the full 30 s — the freeze this module exists
    to remove, moved to the quit button. Once the queue IS empty the worker has
    nothing left to do, so waiting costs nothing and leaves no stray thread.
    """
    global _writer
    drained = flush(timeout)
    pool, _writer = _writer, None
    if pool is not None:
        pool.shutdown(wait=drained)


def bind(db: "Optional[Database]") -> None:
    """Point the watch list at *db*, migrating the config list on first bind.

    Idempotent: binding twice does not duplicate rows, because the migration
    only writes patterns the table does not already hold. Any write still
    queued against the PREVIOUS database is drained first — it belongs to that
    one.
    """
    global _db
    flush()
    _db = db


def unbind() -> None:
    """Detach from the database — used by tests to force the config path."""
    global _db
    shutdown()
    _db = None


def migrate_from_config(config: "Config") -> int:
    """Copy any config-only patterns into the database. Returns how many moved.

    **The config list is left in place, deliberately.** These are the owner's
    real alerts; a migration that deletes its own source has no way back if the
    destination turns out wrong, and the YAML doubles as the plain-text export
    the roadmap wants anyway. Nothing reads it once the database is bound, so
    it cannot drift into a second source of truth.
    """
    if _db is None:
        return 0
    stored = _config_patterns(config)
    if not stored:
        return 0
    existing = {p.casefold() for p in _db_patterns()}
    added = 0
    for text in stored:
        if text.casefold() in existing:
            continue
        # Synchronous on purpose: this runs once at startup, before any window
        # is on screen, and the count it returns has to be true. A failure here
        # must not stop the app launching.
        try:
            _db_add(text)
        except Exception:
            logger.exception("watchlist: could not migrate {!r} to the database", text)
            continue
        added += 1
    if added:
        logger.info("watchlist: migrated {} pattern(s) from config to the database", added)
    return added


#: ``AlertPatternDB.pattern_type`` for a watch-list keyword. The table also
#: serves the Watch Alerts surface, and the settled design is ONE list on two
#: surfaces — so this discriminates rows by kind, not by which view wrote them.
PATTERN_TYPE = "keyword"


def patterns(config: "Config") -> tuple[str, ...]:
    """Every watch pattern, in the user's own order.

    Order is the user's, not sorted: they add rules in the order they think of
    them and the list is short enough to scan.

    Returns:
        A tuple, so a caller cannot mutate the stored list by accident — which
        is exactly how ``config.epg_watchlist_patterns.append(...)`` used to
        write through to config without saving it.
    """
    stored = (_apply_pending(_db_patterns()) if _db is not None
              else _config_patterns(config))
    seen: set[str] = set()
    out: list[str] = []
    for raw in stored:
        text = (raw or "").strip() if isinstance(raw, str) else ""
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return tuple(out)


def rules(config: "Config") -> "tuple[WatchRule, ...]":
    """Every watch pattern as a matchable rule, in the user's own order.

    The rule is what both surfaces are supposed to share (Q4: "one list, two
    surfaces"), so this — not :func:`patterns` — is what a matching caller
    wants. :func:`patterns` stays for display and for the write paths.

    Built on top of :func:`patterns` rather than beside it, so ordering,
    blank-stripping, casefolded de-duplication and the pending-write overlay
    keep exactly one definition; this only attaches the stored per-rule flags.

    A term with no stored row — one still queued for insert, or a config-only
    fallback list — gets the settled default: whole-word, no excludes.
    """
    from metatv.core.watchlist_matching import WatchRule

    flags = _db_rule_flags() if _db is not None else {}
    out: list[WatchRule] = []
    for term in patterns(config):
        whole_word, exclude = flags.get(term.casefold(), (True, ()))
        out.append(WatchRule(term=term, whole_word=whole_word, exclude=exclude))
    return tuple(out)


def _db_rule_flags() -> "dict[str, tuple[bool, tuple[str, ...]]]":
    """casefolded term -> (whole_word, exclude terms), for rules stored in the DB.

    ``whole_word`` reads NULL as True: a row inserted by an older build has no
    opinion, and the settled default is the one to apply. The migration stamps
    those rows to 1 anyway — this is the belt to its braces, and it is what
    makes the reader safe to run against a database mid-upgrade.

    Errors return an EMPTY map rather than raising, matching ``_db_patterns``:
    a flag read that fails should fall back to the default behaviour, not take
    down the EPG view that asked for it.
    """
    from metatv.core.database import AlertPatternDB
    try:
        with _db.session_scope(commit=False) as session:
            rows = (session.query(AlertPatternDB.pattern_value,
                                  AlertPatternDB.whole_word,
                                  AlertPatternDB.exclude_terms)
                    .filter(AlertPatternDB.pattern_type == PATTERN_TYPE)
                    .all())
        out: dict[str, tuple[bool, tuple[str, ...]]] = {}
        for value, whole_word, excludes in rows:
            if not value:
                continue
            terms = tuple(str(x).strip() for x in (excludes or []) if str(x).strip())
            out[value.casefold()] = (True if whole_word is None else bool(whole_word),
                                     terms)
        return out
    except Exception:
        logger.exception("watchlist: could not read rule flags from the database")
        return {}


def lowered(config: "Config") -> tuple[str, ...]:
    """The patterns, casefolded, for matching.

    ``casefold`` rather than ``lower``: matching is what this is for, and the
    watch list holds names like "Guten Morgen Österreich".
    """
    return tuple(p.casefold() for p in patterns(config))


def count(config: "Config") -> int:
    """How many patterns are watched — for a count badge or an empty state."""
    return len(patterns(config))


def contains(config: "Config", pattern: str) -> bool:
    """Whether *pattern* is already watched, compared case-insensitively.

    The direct-config sites used ``pattern not in config.epg_watchlist_patterns``,
    which is case-SENSITIVE — so "NRL" and "nrl" were two rules that matched the
    same programmes.
    """
    return (pattern or "").strip().casefold() in {p.casefold() for p in patterns(config)}


def add(config: "Config", pattern: str) -> bool:
    """Add *pattern*. Returns True when it was accepted.

    On the database store the row is written by the writer thread and this
    returns as soon as the change is queued — see the module note. Every read
    replays the queue, so the pattern is on the list the instant this returns.

    Blank and duplicate entries are no-ops rather than errors — the caller is
    usually a text field with an Add button.
    """
    text = (pattern or "").strip()
    if not text or contains(config, text):
        return False
    if _db is not None:
        return _queue(_OP_ADD, text)
    config.epg_watchlist_patterns = list(patterns(config)) + [text]
    config.save()
    return True


def remove(config: "Config", pattern: str) -> bool:
    """Remove *pattern* (case-insensitively). Returns True when it was accepted.

    Queued rather than written inline on the database store, for the reason in
    the module note: this is called straight from a button handler, and the
    DELETE it used to run there blocked the UI thread for the full 30 s
    ``busy_timeout`` whenever a bulk pass held the write lock.

    Returns:
        True when something was removed. False is not an error: the row may
        already be gone from another surface showing the same list.
    """
    text = (pattern or "").strip()
    target = text.casefold()
    if not target:
        return False
    if _db is not None:
        if target not in {p.casefold() for p in patterns(config)}:
            return False
        return _queue(_OP_REMOVE, text)
    kept = [p for p in patterns(config) if p.casefold() != target]
    if len(kept) == len(patterns(config)):
        return False
    config.epg_watchlist_patterns = kept
    config.save()
    return True


# ── the write queue ──────────────────────────────────────────────────────────

def _apply_pending(stored: list) -> list:
    """Replay queued writes over *stored* so a read never shows a stale answer.

    Args:
        stored: The rows the database currently holds.

    Returns:
        What the list looks like once every queued write has landed.
    """
    with _lock:
        queued = list(_pending)
    if not queued:
        return stored
    out = list(stored)
    for write in queued:
        key = (write.text or "").casefold()
        matches = [s for s in out if isinstance(s, str) and s.casefold() == key]
        if write.op == _OP_REMOVE:
            out = [s for s in out if s not in matches]
        elif not matches:
            out.append(write.text)
    return out


def _queue(op: str, text: str) -> bool:
    """Hand one mutation to the writer thread. Returns True when it was queued."""
    write = _PendingWrite(op=op, text=text)
    with _lock:
        _pending.append(write)
        try:
            write.future = _writer_pool().submit(_run_write, write)
        except Exception:
            _pending.remove(write)
            logger.exception("watchlist: could not queue {} of {!r}", op, text)
            return False
    return True


def _writer_pool() -> ThreadPoolExecutor:
    """The single writer thread, created on first use."""
    global _writer
    if _writer is None:
        _writer = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="watchlist-write")
    return _writer


def _run_write(write: _PendingWrite) -> None:
    """Writer thread: apply one queued mutation, then report or forget it."""
    message = ""
    try:
        if write.op == _OP_ADD:
            _db_add(write.text)
        else:
            _db_remove(write.text.casefold())
    except Exception as exc:
        logger.exception("watchlist: could not {} {!r}", write.op, write.text)
        message = str(exc).split("\n", 1)[0].strip() or exc.__class__.__name__
    finally:
        # Dropped whether it succeeded or failed: on failure the next read must
        # show what the database actually holds, not the optimistic guess.
        with _lock:
            if write in _pending:
                _pending.remove(write)
    if message and _write_error_handler is not None:
        try:
            _write_error_handler(write.op, write.text, message)
        except Exception:
            logger.exception("watchlist: the write-error handler raised")


# ── the two backing stores ───────────────────────────────────────────────────

def _config_patterns(config: "Config") -> list:
    """The raw config list — the store before the move, and still the backup."""
    return list(getattr(config, "epg_watchlist_patterns", None) or [])


def _db_patterns() -> list:
    """Every stored pattern, oldest first, so the user's order survives.

    A database error falls back to an EMPTY list rather than raising: a watch
    list that fails to load should show as empty and recover on the next read,
    not take down the EPG view that asked for it.
    """
    from metatv.core.database import AlertPatternDB
    try:
        with _db.session_scope(commit=False) as session:
            rows = (session.query(AlertPatternDB.pattern_value)
                    .filter(AlertPatternDB.pattern_type == PATTERN_TYPE)
                    .order_by(AlertPatternDB.created_at, AlertPatternDB.id)
                    .all())
        return [r[0] for r in rows if r[0]]
    except Exception:
        logger.exception("watchlist: could not read patterns from the database")
        return []


def _db_add(text: str) -> None:
    """Insert one pattern. RAISES on failure — see the note on ``_db_remove``."""
    import uuid
    from metatv.core.database import AlertPatternDB
    with _db.session_scope() as session:
        session.add(AlertPatternDB(
            id=str(uuid.uuid4()),
            name=text,
            pattern_type=PATTERN_TYPE,
            pattern_value=text,
            # Defaults chosen to preserve what the config list MEANT: every
            # stored string matched anything, anywhere, always on.
            applies_to="all",
            is_enabled=True,
        ))


def _db_remove(target_casefold: str) -> None:
    """Delete every row matching *target_casefold*. RAISES on failure.

    Both writers raise rather than returning a bool, deliberately. They used to
    log-and-return ``False``, which is how a failed removal became a click that
    silently did nothing: the caller could not tell "there was nothing to
    remove" from "the database is locked". Their one caller now is
    :func:`_run_write`, which turns the exception into the error the user sees.
    """
    from metatv.core.database import AlertPatternDB
    with _db.session_scope() as session:
        rows = (session.query(AlertPatternDB)
                .filter(AlertPatternDB.pattern_type == PATTERN_TYPE).all())
        for row in rows:
            if (row.pattern_value or "").casefold() == target_casefold:
                session.delete(row)
