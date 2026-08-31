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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.config import Config
    from metatv.core.database import Database


#: The database the list lives in, bound once at startup by ``bind()``.
#:
#: A module-level binding rather than a parameter, because the twenty-four call
#: sites hold a ``Config`` and not all of them can reach a ``Database`` — adding
#: one to each is the plumbing this seam exists to avoid. Unbound (tests, any
#: headless path) the functions fall back to config, so nothing here can make a
#: caller fail for want of a database.
_db: "Optional[Database]" = None


def bind(db: "Optional[Database]") -> None:
    """Point the watch list at *db*, migrating the config list on first bind.

    Idempotent: binding twice does not duplicate rows, because the migration
    only writes patterns the table does not already hold.
    """
    global _db
    _db = db


def unbind() -> None:
    """Detach from the database — used by tests to force the config path."""
    global _db
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
        if _db_add(text):
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
    stored = _db_patterns() if _db is not None else _config_patterns(config)
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
    """Add *pattern* and persist. Returns True when it was actually added.

    Saves immediately: a watch rule the user typed and then lost to a crash is
    worse than the write. Blank and duplicate entries are no-ops rather than
    errors — the caller is usually a text field with an Add button.
    """
    text = (pattern or "").strip()
    if not text or contains(config, text):
        return False
    if _db is not None:
        return _db_add(text)
    config.epg_watchlist_patterns = list(patterns(config)) + [text]
    config.save()
    return True


def remove(config: "Config", pattern: str) -> bool:
    """Remove *pattern* (case-insensitively) and persist.

    Returns:
        True when something was removed. False is not an error: the row may
        already be gone from another surface showing the same list.
    """
    target = (pattern or "").strip().casefold()
    if not target:
        return False
    if _db is not None:
        return _db_remove(target)
    kept = [p for p in patterns(config) if p.casefold() != target]
    if len(kept) == len(patterns(config)):
        return False
    config.epg_watchlist_patterns = kept
    config.save()
    return True


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


def _db_add(text: str) -> bool:
    import uuid
    from metatv.core.database import AlertPatternDB
    try:
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
        return True
    except Exception:
        logger.exception("watchlist: could not add {!r}", text)
        return False


def _db_remove(target_casefold: str) -> bool:
    from metatv.core.database import AlertPatternDB
    try:
        with _db.session_scope() as session:
            rows = (session.query(AlertPatternDB)
                    .filter(AlertPatternDB.pattern_type == PATTERN_TYPE).all())
            doomed = [r for r in rows
                      if (r.pattern_value or "").casefold() == target_casefold]
            for row in doomed:
                session.delete(row)
        return bool(doomed)
    except Exception:
        logger.exception("watchlist: could not remove a pattern")
        return False
