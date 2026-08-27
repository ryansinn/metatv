"""Migration task: store the poster the provider already shipped.

``ChannelDB.logo_url`` is written at ingestion from the provider's raw stream
record. It was read from ``stream_icon`` alone — which is where MOVIES put the
poster. Series put it in ``cover``, so measured on the owner's library:

    movie   334,451   logo_url stored  325,209  (97.2%)
    series   82,525   logo_url stored        0  ( 0.0%)

``XtreamAPI.convert_to_channel`` now goes through
:func:`~metatv.core.discovery_engine.poster_url_from_raw`, which knows both
keys — but that only helps rows written AFTER it, and a full catalog refresh is
minutes to hours per source. Every one of those 82,525 rows already carries its
poster in the stored ``raw_data``, so this reads it from there and needs no
network at all.

Idempotency
-----------
``needs_run`` counts rows with an empty ``logo_url`` whose ``raw_data`` mentions
a poster key. That reaches zero when the work is done and stays there, so an
interrupted run simply resumes — no version counter to get out of step with the
data it describes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

_BATCH = 2_000

# Tests the VALUE, not just the key. Two thirds of the rows that merely CONTAIN
# "stream_icon" hold it empty (`"stream_icon": ""` — 4,027 of the first 6,000 on
# the owner's library), and those can never be fixed. A key-only filter counts
# them as pending forever, so needs_run stays True and the task re-runs every
# launch doing six seconds of work it cannot complete.
#
# json_extract is guarded by json_valid: a row whose raw_data is not JSON would
# otherwise abort the statement. Measured on the owner's library, this filter
# returns 82,426 — exactly the number the backfill can actually fix.
_CANDIDATES = (
    "SELECT id, raw_data FROM channels "
    "WHERE (logo_url IS NULL OR logo_url = '') "
    "AND raw_data IS NOT NULL AND json_valid(raw_data) "
    "AND COALESCE("
    "  NULLIF(TRIM(COALESCE(json_extract(raw_data, '$.stream_icon'), '')), ''),"
    "  NULLIF(TRIM(COALESCE(json_extract(raw_data, '$.cover'), '')), '')"
    ") IS NOT NULL"
)

# Paged by a keyset cursor on the primary key rather than a plain LIMIT. Even
# with the value-aware filter above, a row the SQL thinks is fixable can still
# resolve to None in Python (poster_url_from_raw owns the final say), and such a
# row stays a candidate no matter how often it is examined — a cursor-less LIMIT
# would hand back the same rows forever.
_PAGE = _CANDIDATES + " AND id > :after ORDER BY id LIMIT :n"


class PosterBackfillTask:
    """Fill in ``logo_url`` from stored ``raw_data`` for rows ingested without one."""

    id: str = "poster_backfill"
    label: str = "Restoring poster images"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def _pending(self) -> int:
        with self._db.engine.connect() as conn:
            return conn.execute(text(
                f"SELECT count(*) FROM ({_CANDIDATES})"
            )).scalar() or 0

    def needs_run(self, config: "Config") -> bool:
        """Return True while any row still has a findable poster and no ``logo_url``.

        Args:
            config: Unused; the data is the source of truth.

        Returns:
            True when there is work to do.
        """
        try:
            return self._pending() > 0
        except Exception:
            logger.exception("PosterBackfillTask: could not count pending rows; skipping")
            return False

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Resolve and store each missing poster, in committed batches.

        Runs on a **worker thread** (called by ``MigrationManager``).

        Args:
            progress_cb: ``(done, total)`` after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for the manager's keyword call.
        """
        from metatv.core.discovery_engine import poster_url_from_raw

        total = self._pending()
        if not total:
            return
        logger.info("PosterBackfillTask: {:,} channels have a poster to restore", total)

        done = 0
        filled = 0
        after = ""
        progress_cb(0, total)
        while not is_cancelled():
            with self._db.session_scope() as session:
                rows = session.execute(text(_PAGE), {"after": after, "n": _BATCH}).all()
                if not rows:
                    break
                updates = [
                    {"cid": cid, "url": url}
                    for cid, raw in rows
                    if (url := poster_url_from_raw(_as_mapping(raw)))
                ]
                if updates:
                    session.execute(
                        text("UPDATE channels SET logo_url = :url WHERE id = :cid"), updates
                    )
                    filled += len(updates)
                # Advance past everything examined, updated or not — a barren
                # batch is normal, not a reason to stop.
                after = rows[-1][0]
                done += len(rows)
            progress_cb(min(done, total), total)

        logger.info(
            "PosterBackfillTask: complete — {:,} posters restored from {:,} rows examined",
            filled, done,
        )

    def on_completed(self, config: "Config") -> None:
        """No bookkeeping — ``needs_run`` reads the data itself.

        Args:
            config: Unused.
        """
        return


def _as_mapping(raw):
    """Return ``raw_data`` as a dict whether it arrived decoded or as JSON text.

    The JSONEncoded column decodes through the ORM, but this task reads via raw
    SQL for speed, so it can see the stored string.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        import json
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}
