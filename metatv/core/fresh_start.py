"""Fresh start: wipe MetaTV back to a first launch, optionally keeping sources.

Owner, 2026-10-20: a Tools option that "wipes the database and everything, so
the app starts like a fresh install", and one that keeps the sources so "the
app starts up like the sources were JUST added".

A running app holds its database open (Windows will not delete an open file),
so the wipe happens across a restart:

1. :func:`request` (UI, after confirmation) writes a marker into the config
   folder naming what to delete and, for the keep-sources mode, the sources'
   user-entered settings. The app then quits normally.
2. ``main()`` sees :func:`pending` after the event loop ends and calls
   :func:`relaunch`.
3. The new process calls :func:`perform` FIRST, before the config or the
   database is opened, and gets back the sources to re-add, which the window
   adds through the normal add path once it exists.

Deleted: the database (and its -wal/-shm), config.yaml and its backups, and
the cache folder (posters, IDF table, deep-cache scratch). Kept: logs (they
diagnose the very problem a fresh start is often for), QA notes, and anything
under the recordings/downloads folders — those are the user's files.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from metatv.core import app_paths

MARKER_NAME = "fresh_start.json"

#: The provider columns a user typed or chose. Everything else (account
#: status, URL statistics, EPG fetch state, timestamps) is regenerated, which is
#: what "as if just added" means.
SOURCE_FIELDS = ("id", "name", "type", "url", "urls", "username", "password",
                 "icon", "is_active", "force_adult", "epg_enabled",
                 "epg_url_override", "epg_refresh_interval", "refresh_schedule")


def _marker() -> Path:
    return app_paths.config_dir() / MARKER_NAME


def request(database_path: Path, sources: list[dict] | None) -> None:
    """Record a fresh start for the next launch.

    Args:
        database_path: The library file in use now (it can live outside the
            default data folder).
        sources: Source settings to re-add after the wipe (``SOURCE_FIELDS``
            per source), or None to start with no sources at all.
    """
    cfg = app_paths.config_dir()
    targets = [database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm"),
               *sorted(cfg.glob("config.yaml*")), app_paths.cache_dir()]
    marker = {"delete": [str(p) for p in targets], "sources": sources}
    cfg.mkdir(parents=True, exist_ok=True)
    _marker().write_text(json.dumps(marker, default=str), encoding="utf-8")
    logger.warning("Fresh start requested ({} source(s) kept)",
                   len(sources) if sources is not None else "no")


def cancel() -> None:
    """Withdraw a recorded fresh start (the app did not close after all)."""
    _marker().unlink(missing_ok=True)


def pending() -> bool:
    """True when a fresh start is waiting for the next launch."""
    return _marker().exists()


def _remove(path: Path) -> bool:
    """Delete a file or folder, retrying while the old process lets go of it."""
    for _ in range(20):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            return True
        except OSError:
            time.sleep(0.5)
    logger.error("Fresh start could not delete {}", path)
    return False


def perform() -> list[dict] | None:
    """Carry out a pending fresh start. Call before the config or database opens.

    Returns:
        The sources to re-add once the window exists, or None (no fresh start
        was pending, or it kept no sources).
    """
    marker = _marker()
    if not marker.exists():
        return None
    try:
        plan = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("Fresh start marker unreadable — ignored")
        marker.unlink(missing_ok=True)
        return None
    for target in plan.get("delete", []):
        _remove(Path(target))
    marker.unlink(missing_ok=True)
    logger.warning("Fresh start done")
    return plan.get("sources") or None


def relaunch_command() -> list[str]:
    """The command that starts this same MetaTV again."""
    from metatv.core.runtime_env import is_frozen

    if is_frozen():
        return [sys.executable]
    return [sys.executable, "-c", "from metatv.__main__ import main; main()"]


def relaunch() -> None:
    """Start a new MetaTV process; the caller exits right after."""
    subprocess.Popen(relaunch_command(), close_fds=True)
