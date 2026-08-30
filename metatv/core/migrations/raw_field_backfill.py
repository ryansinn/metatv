"""Migration task: fill ``MetadataDB`` columns the provider's own payload already carries.

Two fields have now been missed the same way, so this is a table rather than a
field:

``runtime``
    Populated on **0 of 652,216 rows**. Providers send it — ``info.duration`` on
    movies, ``episode_run_time`` at the TOP level on series — and
    ``metadata_from_raw`` read only the first. 48,322 series resolve a real
    value; a further 79,230 send ``"0"``, which is mapped to None rather than a
    literal zero, since a stored 0 renders as "0 min".

``trailer_url``
    Populated on 46,148 rows out of the **114,308** whose payload carries one.
    Same shape of miss: the code read the nested ``info.youtube_trailer`` and
    Xtream VOD rows put it at the top level under ``trailer``. Nothing rendered
    it either, until the Trailer button.

Fixed forward in ``metadata_from_raw``, which covers everything ingested from
here on. This is the one-time pass for rows that already exist, because cached
metadata is not re-derived on read.

Adding a third field is one row in ``FIELDS`` and a ``CURRENT_VERSION`` bump —
not a 22nd migration module and a 22nd hand-written registration in
``main_window.py`` (ledger F29).

Idempotency
-----------
``needs_run`` compares ``config.raw_field_backfill_version`` with
``CURRENT_VERSION``. The version is bumped only on full completion, so a crash
or a cancel leaves it unbumped and the task restarts from scratch next launch;
already-committed batches are durable (#364 crash-retry semantics).

Only rows where the column ``IS NULL`` are considered, and only those whose
payload actually implies a value are written — so a re-run after adding a field
costs one scan and rewrites nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from metatv.metadata_providers.provider_metadata import (
    runtime_from_raw, trailer_from_raw,
)

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.config import Config
    from metatv.core.database import Database

#: Bump when a row is added to FIELDS below, so the new column is filled on
#: libraries that already ran an earlier version.
#:   1 — runtime
#:   2 — trailer_url
CURRENT_VERSION = 2

#: Rows per commit. Matches the other backfills — large enough that the commit
#: overhead disappears, small enough that a cancel loses little work.
_BATCH = 2000

#: ``MetadataDB`` column -> the resolver that reads it out of a channel's
#: ``raw_data``. Each resolver is the SAME function ingestion calls, so a field
#: cannot drift between the two paths.
FIELDS: "dict[str, object]" = {
    "runtime": runtime_from_raw,
    "trailer_url": trailer_from_raw,
}


class RawFieldBackfillTask:
    """Populate ``MetadataDB`` columns from each channel's stored ``raw_data``."""

    id: str = "raw_field_backfill"
    label: str = "Reading details the provider already sent"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """True when the backfill has not completed for this version."""
        return getattr(config, "raw_field_backfill_version", 0) < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Fill each FIELDS column for the metadata rows that have none.

        Runs on a worker thread. One pass per field, each filtered on that
        column ``IS NULL``, so adding a field costs one extra scan and rewrites
        nothing already filled.

        Exceptions propagate: the manager leaves the version unbumped on a
        crash, which is what makes the retry correct (#364).

        Args:
            progress_cb: ``(done, total)`` after each batch commit, summed
                across every field's pass.
            is_cancelled: True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat.
        """
        from metatv.core.database import ChannelDB, MetadataDB

        logger.info("RawFieldBackfillTask: starting (version={})", CURRENT_VERSION)

        counts = {}
        with self._db.session_scope(commit=False) as session:
            for column in FIELDS:
                counts[column] = (
                    session.query(ChannelDB.id)
                    .join(MetadataDB, MetadataDB.id == ChannelDB.metadata_id)
                    .filter(getattr(MetadataDB, column).is_(None),
                            ChannelDB.raw_data.isnot(None))
                    .count()
                )
        total = sum(counts.values())
        logger.info("RawFieldBackfillTask: {:,} candidate rows across {}",
                    total, ", ".join(f"{c} ({n:,})" for c, n in counts.items()))

        done = 0
        for column, resolve in FIELDS.items():
            written = 0
            # Keyset pagination, NOT offset. The filter is ``<column> IS NULL``
            # and the loop's own writes remove rows from that set, so an OFFSET
            # would step past exactly as many rows as the previous batch wrote.
            # Paging on the last channel id seen is immune to the set shrinking
            # underneath it and rides the primary-key index.
            last_id = ""
            while True:
                if is_cancelled():
                    logger.info("RawFieldBackfillTask: cancelled at {:,}/{:,}",
                                done, total)
                    return
                with self._db.session_scope() as session:
                    batch = (
                        session.query(ChannelDB.id, ChannelDB.raw_data, MetadataDB)
                        .join(MetadataDB, MetadataDB.id == ChannelDB.metadata_id)
                        .filter(getattr(MetadataDB, column).is_(None),
                                ChannelDB.raw_data.isnot(None),
                                ChannelDB.id > last_id)
                        .order_by(ChannelDB.id)
                        .limit(_BATCH)
                        .all()
                    )
                    if not batch:
                        break
                    for _channel_id, raw, meta in batch:
                        done += 1
                        value = resolve(raw)
                        if value:
                            setattr(meta, column, value)
                            written += 1
                    last_id = batch[-1][0]
                progress_cb(min(done, total), total)
            logger.info("RawFieldBackfillTask: {} — {:,} written", column, written)

        progress_cb(total, total)
        logger.info("RawFieldBackfillTask: complete — {:,} rows scanned", done)

    def on_completed(self, config: "Config") -> None:
        """Record the version so this does not run again."""
        config.raw_field_backfill_version = CURRENT_VERSION
        config.save()
