"""Recover ``epg_channel_id`` from ``raw_data`` for rows written without it.

The Xtream provider has always parsed this field (``xtream.py:357``); the bulk
insert's column list dropped it. Measured on the owner's library before the
fix:

    channels                                        785,163
      with a stored epg_channel_id                        0
    live channels whose raw_data DOES carry one      20,506

EPG tier-1 matching — the path the code describes as "highest confidence" —
reads this column, so it has never fired on any install.

Fixing the write path is not enough. The value is already sitting in every
affected row's ``raw_data`` blob, so this recovers it in place rather than
making the user re-ingest their whole catalogue to get EPG working. That is the
same lesson as ``detected_restricted`` and the tag merge: a column computed at
ingestion needs a backfill, because fixing the producer never reaches the rows
already written.

One UPDATE over the rows that have a value to recover. Re-running is a no-op:
the WHERE clause excludes rows that already carry one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

#: Bumped when this should sweep again.
CURRENT_VERSION: int = 1

#: Rows that carry a usable id in raw_data and have none stored.
_RECOVERABLE = (
    "raw_data IS NOT NULL AND json_valid(raw_data) "
    "AND TRIM(COALESCE(json_extract(raw_data, '$.epg_channel_id'), '')) != '' "
    "AND TRIM(COALESCE(epg_channel_id, '')) = ''"
)


class EpgChannelIdBackfillTask:
    """Copy the provider's EPG id out of raw_data into its own column."""

    id: str = "epg_channel_id_backfill"
    label: str = "Recovering EPG channel ids"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """True while a row still has an id to recover.

        Reads the DATA rather than only a stamp, so a library that gains
        affected rows later is still repaired — but the version stamp below
        stops it rescanning forever once there is nothing left.

        Args:
            config: The application Config.

        Returns:
            True when there is work to do.
        """
        if getattr(config, "epg_channel_id_backfill_version", 0) >= CURRENT_VERSION:
            return False
        try:
            with self._db.engine.connect() as conn:
                return bool(conn.execute(text(
                    f"SELECT EXISTS(SELECT 1 FROM channels WHERE {_RECOVERABLE})"
                )).scalar())
        except Exception:
            logger.exception("epg_channel_id_backfill: could not count; skipping")
            return False

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Recover every available id in one statement.

        Args:
            progress_cb: ``(done, total)``.
            is_cancelled: Returns True when asked to stop.
            config: Unused; accepted for the manager's keyword call.
        """
        progress_cb(0, 1)
        with self._db.session_scope() as session:
            result = session.execute(text(
                "UPDATE channels "
                "SET epg_channel_id = TRIM(json_extract(raw_data, '$.epg_channel_id')) "
                f"WHERE {_RECOVERABLE}"
            ))
            recovered = result.rowcount or 0
        progress_cb(1, 1)
        logger.info(
            "epg_channel_id_backfill: recovered {:,} EPG channel id(s) from raw_data",
            recovered,
        )

    def on_completed(self, config: "Config") -> None:
        """Stamp the version so this stops scanning on every launch.

        Args:
            config: Saved with the new version.
        """
        config.epg_channel_id_backfill_version = CURRENT_VERSION
        config.save()
