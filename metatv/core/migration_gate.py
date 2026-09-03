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
"""
from __future__ import annotations

import threading

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
