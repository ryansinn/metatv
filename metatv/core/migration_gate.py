"""Migration-in-progress gate — a read-only signal for deferring contending work.

Sibling of ``TmdbEnrichmentManager._defer_for_migration`` (`core/tmdb_enrichment_manager.py`),
which polls ``MigrationManager.is_running`` to yield its own bulk writes while a migration
pass holds the DB — the same SQLite single-writer contention that produced the 2026-08-01
crash chain. That manager already had the right pattern; this module gives it to readers
too, not just writers.

On the owner's 2026-09-03 launch log, a ``prefix_rescan`` v6 pass held the DB for **three
minutes**. Sidebar sections kept submitting their own background reads into that contention:
Recommended took ~30s to show anything, every other section sat empty with no explanation,
and the contention slowed the migration pass itself. ``BackgroundRefreshMixin.refresh()``
(`gui/sidebar/background_refresh.py`) checks ``is_running()`` before submitting its query and
renders a waiting state instead — see that module for the read side.

Pure ``threading``, no Qt — importable from ``core`` (``MigrationManager``, which owns the
set/clear calls) and ``gui`` (sidebar sections, which only ever read it) alike, per CLAUDE.md
"core holds no Qt".

:func:`wait_until_idle` is the WRITER-side sibling of :func:`is_running`: a bounded polling
wait, not a one-shot check. ``TmdbEnrichmentManager._defer_for_migration`` and
``MetadataEnrichmentQueue._defer_for_migration`` each hand-rolled the identical loop before
this existed — same SQLite single-writer reasoning, differing only in their own
``migration_manager``/poll+ceiling constants/``should_stop`` source. Deliberately takes the
CALLER's injected ``migration_manager`` (whose ``.is_running`` a test double drives) rather
than reading the module-level gate above — that keeps existing behaviour, including the
existing test doubles, unchanged.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

_running = threading.Event()


def is_running() -> bool:
    """True while a ``MigrationManager`` pass is actively executing.

    Read-only, best-effort — same soft-check contract as
    ``MigrationManager.is_running`` itself: a missed transition by a beat or
    two is harmless, since every caller of this gate already retries.
    """
    return _running.is_set()


def _set_running(running: bool) -> None:
    """Set or clear the gate. Called only by ``MigrationManager`` — never by a reader.

    Thread-safe via ``threading.Event``; safe to call from the migration
    worker thread while the Qt main thread calls ``is_running()``.
    """
    if running:
        _running.set()
    else:
        _running.clear()


def wait_until_idle(
    migration_manager: "Optional[object]",
    *,
    max_wait_s: float,
    poll_s: float,
    should_stop: "Callable[[], bool]",
) -> bool:
    """Best-effort: block while *migration_manager* reports a pass running.

    Called at the top of a bulk-write batch method, before its read query even
    runs, so a migrator-crowded batch never wastes a network round trip only
    to then wait to persist it — the same reasoning ``TmdbEnrichmentManager``
    and ``MetadataEnrichmentQueue`` each wrote out in full before this existed.

    Args:
        migration_manager: Anything exposing an ``is_running`` bool property
            (typically a ``MigrationManager``), or ``None`` — meaning nothing
            to defer to, so this returns immediately.
        max_wait_s: Ceiling on total time spent waiting. A stuck or
            misreporting migration manager must not wedge the caller forever;
            this is a courtesy, not a guarantee the migration actually
            finished.
        poll_s: Gap between ``is_running`` checks.
        should_stop: Polled alongside ``is_running`` — e.g. the caller's own
            shutdown flag — so a caller already tearing down breaks the wait
            immediately instead of riding it out.

    Returns:
        True if this waited at all (``migration_manager`` was busy for at
        least one poll), so a caller can log accordingly; False when there
        was nothing to defer to or the pass was already idle.
    """
    if migration_manager is None:
        return False
    waited = 0.0
    while (
        not should_stop()
        and migration_manager.is_running
        and waited < max_wait_s
    ):
        time.sleep(poll_s)
        waited += poll_s
    return waited > 0
