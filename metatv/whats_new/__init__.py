"""What's New changelog — one file per entry, zero-conflict additions.

Public API (unchanged from the old ``metatv/whats_new.py``):

    WhatsNewEntry  — frozen dataclass
    WHATS_NEW      — list[WhatsNewEntry], sorted ascending by id
    latest_id()    — int, highest id or 0
    entries_since(last_seen_id) — list[WhatsNewEntry], sorted descending by id

To add a new entry:  add a new file ``metatv/whats_new/entries/NNNN_slug.py``
where NNNN is the zero-padded id (see entries/README).  Never edit this file
or any existing entry file — just add the new file.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass

from loguru import logger


@dataclass(frozen=True)
class WhatsNewEntry:
    id: int                  # monotonic; the "seen" cursor. Each new entry = previous max + 1.
    version: str             # display only, e.g. "0.1.0"
    date: str                # ISO "YYYY-MM-DD"
    title: str
    items: tuple[str, ...]   # user-facing bullet points (frozen dataclass → tuple, not list)
    test_steps: tuple[str, ...] = ()  # dev-only manual QA steps; omit when not applicable


def _load_entries() -> list[WhatsNewEntry]:
    """Discover and load all entry modules from the ``entries`` sub-package.

    Each module must expose a top-level ``ENTRY = WhatsNewEntry(...)`` attribute.
    Modules that fail to load are skipped with a warning so a broken entry file
    does not prevent the app from starting.

    Returns entries sorted ascending by id (display / cursor arithmetic uses
    this canonical ordering; the dialog caller re-sorts descending as needed).
    """
    from metatv.whats_new import entries as _entries_pkg  # noqa: PLC0415

    found: list[WhatsNewEntry] = []
    for module_info in pkgutil.iter_modules(_entries_pkg.__path__):
        if module_info.name.startswith("_"):
            continue  # skip __init__ and private helpers
        full_name = f"metatv.whats_new.entries.{module_info.name}"
        try:
            mod = importlib.import_module(full_name)
            entry = getattr(mod, "ENTRY", None)
            if not isinstance(entry, WhatsNewEntry):
                logger.warning(
                    "whats_new entry module {} has no ENTRY attribute — skipped", full_name
                )
                continue
            found.append(entry)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load whats_new entry module {} — skipped", full_name)

    return sorted(found, key=lambda e: e.id)


WHATS_NEW: list[WhatsNewEntry] = _load_entries()


def latest_id() -> int:
    """Return the highest entry id in the changelog, or 0 if empty."""
    return max((e.id for e in WHATS_NEW), default=0)


def entries_since(last_seen_id: int) -> list[WhatsNewEntry]:
    """Return entries newer than last_seen_id, newest first."""
    return sorted(
        (e for e in WHATS_NEW if e.id > last_seen_id),
        key=lambda e: e.id,
        reverse=True,
    )
