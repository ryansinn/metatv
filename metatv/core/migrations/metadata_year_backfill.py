"""Populate ``metadata.year`` for rows written before the derivation existed.

CLAUDE.md states the invariant plainly: read ``metadata.year`` everywhere,
because ``MetadataManager._derive_year()`` "populates it at write from
``release_date``, backfills pre-fix rows on read". Measured on the owner's
library:

    metadata rows with a release_date .................. 101,896
      ...of those, year populated .....................      437   (0.4%)

Both halves of the claim are true and neither reaches the column. The write
path does derive (``metadata_manager.py``'s ``_keep(metadata, "year", ...)``),
so rows written since that landed are correct — 437 of them. The read path
derives into the returned ``MetadataResult`` and never writes back, so the
STORED column stays NULL forever.

That matters because the column is read from SQL. ``content_dedup.extract_year``
asks ``meta.year`` first and otherwise parses the CHANNEL NAME for "(2004)".
Measured over the affected rows:

    fell back to parsing the channel name ..............  40,994
    got no year at all ................................  60,465
      ...of which release_date could have supplied one .  60,448   <- pure loss
    name-parsed year DISAGREES with release_date ......     622

So 60,448 titles carry a usable production date that nothing can see, and 622
have the authoritative date losing to a filename.

Fixing the producer never reaches rows already written — the same lesson as
``detected_restricted``, the tag merge and ``epg_channel_id``. One UPDATE.

Deliberately identical to ``_derive_year``
-----------------------------------------
``_derive_year`` returns ``int(release_date[:4])`` for anything parseable, with
no plausibility bound. This applies the same rule and no more, so the stored
column equals what the app would compute at read time — two slightly different
definitions of "the year" is a worse outcome than a handful of odd values.

In practice that means 18 rows are skipped (``'.'``, ``'Rambod Javan'``,
``'(1939-1946)'`` — the GLOB rejects anything not starting with four digits)
and 4 rows get Solar Hijri years (1394, 1380) that ``_derive_year`` would
produce anyway.
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

#: Rows with a derivable year and none stored.
#:
#: The GLOB is what keeps this equal to ``_derive_year``: SQLite's
#: ``CAST('abcd' AS INTEGER)`` is ``0``, not NULL, so without it the junk
#: release_dates would be written as year 0 rather than skipped.
_DERIVABLE = (
    "year IS NULL "
    "AND release_date IS NOT NULL "
    "AND substr(release_date, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'"
)


class MetadataYearBackfillTask:
    """Derive ``year`` from ``release_date`` for pre-fix metadata rows."""

    id: str = "metadata_year_backfill"
    label: str = "Recovering release years"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """True while a row still has a year to derive.

        Reads the DATA as well as the stamp, so a library that gains affected
        rows later is still repaired; the stamp stops it rescanning forever
        once there is nothing left.

        Args:
            config: The application Config.

        Returns:
            True when there is work to do.
        """
        if getattr(config, "metadata_year_backfill_version", 0) >= CURRENT_VERSION:
            return False
        try:
            with self._db.engine.connect() as conn:
                return bool(conn.execute(text(
                    f"SELECT EXISTS(SELECT 1 FROM metadata WHERE {_DERIVABLE})"
                )).scalar())
        except Exception:
            logger.exception("metadata_year_backfill: could not count; skipping")
            return False

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Derive every available year in one statement.

        Args:
            progress_cb: ``(done, total)``.
            is_cancelled: Returns True when asked to stop.
            config: Unused; accepted for the manager's keyword call.
        """
        progress_cb(0, 1)
        with self._db.session_scope() as session:
            result = session.execute(text(
                "UPDATE metadata "
                "SET year = CAST(substr(release_date, 1, 4) AS INTEGER) "
                f"WHERE {_DERIVABLE}"
            ))
            derived = result.rowcount or 0
        progress_cb(1, 1)
        logger.info(
            "metadata_year_backfill: derived {:,} release year(s) from release_date",
            derived,
        )

    def on_completed(self, config: "Config") -> None:
        """Stamp the version so this stops scanning on every launch.

        Args:
            config: Saved with the new version.
        """
        config.metadata_year_backfill_version = CURRENT_VERSION
        config.save()
