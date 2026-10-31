"""Fold play outcomes older than 90 days into weekly counts (Source Analytics Q8).

Idempotent, like ``orphan_sweep``: ``needs_run`` probes live state (is any row
past the window?), so the fold happens whenever there is something to fold and
never needs a saved version.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable

from loguru import logger

from metatv.core.repositories.playback_events import PlaybackEventRepository

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database


class PlaybackEventsFoldTask:
    """Fold old ``playback_events`` rows into ``playback_weekly``."""

    id: str = "playback_events_fold"
    label: str = "Summarising old playback history"

    def __init__(self, db: "Database") -> None:
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        with self._db.session_scope(commit=False) as session:
            return PlaybackEventRepository(session).has_old(datetime.utcnow())

    def run(self, progress_cb: Callable[[int, int], None], is_cancelled: Callable[[], bool]) -> None:
        if is_cancelled():
            return
        with self._db.session_scope() as session:
            folded = PlaybackEventRepository(session).fold_old(datetime.utcnow())
        logger.info("PlaybackEventsFoldTask: folded {} play(s) into weekly counts", folded)
        progress_cb(1, 1)

    def on_completed(self, config: "Config") -> None:
        """No-op: idempotency comes from re-probing live state."""
