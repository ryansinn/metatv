"""Migration task: fill ``MetadataDB.runtime`` from the provider's own payload.

Providers send ``episode_run_time`` on 53.7% of series — a minutes string at the
TOP level of ``raw_data``, where movies carry ``info.duration``. Nothing read
it: ``MetadataDB.runtime`` was populated on **0 of 652,216 rows**, so the one
surface that renders a runtime (the trail-map detail strip, which shows it only
when present) never had one to show.

``provider_metadata.metadata_from_raw`` now reads the field, which fixes every
row ingested from here on. This task is the one-time pass for rows that already
exist — without it the fix would only reach content the owner happens to
re-refresh, and cached metadata is not re-derived on read.

Measured on the owner's library: **48,322** series resolve a real runtime.
A further 79,230 send ``"0"``, which the parser deliberately maps to ``None``
rather than a literal zero — a stored 0 renders as "0 min", which is worse than
showing nothing.

Idempotency
-----------
``needs_run`` compares ``config.runtime_backfill_version`` with
``CURRENT_VERSION``. The version is bumped only on full completion, so a crash
or a cancel leaves it unbumped and the task restarts from scratch next launch;
already-committed batches are durable (#364 crash-retry semantics).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from metatv.metadata_providers.provider_metadata import runtime_from_raw

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.config import Config
    from metatv.core.database import Database

CURRENT_VERSION = 1

#: Rows per commit. Matches the other backfills — large enough that the commit
#: overhead disappears, small enough that a cancel loses little work.
_BATCH = 2000


class RuntimeBackfillTask:
    """Populate ``MetadataDB.runtime`` from each channel's stored ``raw_data``."""

    id: str = "runtime_backfill"
    label: str = "Reading episode runtimes"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """True when the backfill has not completed for this version."""
        return getattr(config, "runtime_backfill_version", 0) < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Fill runtime for metadata rows that have none.

        Runs on a worker thread. Only rows where ``runtime IS NULL`` are
        considered, and only those whose channel payload actually implies one
        are written — so a second run is cheap and a provider that sends
        nothing is not rewritten every launch.

        Exceptions propagate: the manager leaves the version unbumped on a
        crash, which is what makes the retry correct (#364).

        Args:
            progress_cb: ``(done, total)`` after each batch commit.
            is_cancelled: True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat.
        """
        from metatv.core.database import ChannelDB, MetadataDB

        logger.info("RuntimeBackfillTask: starting (version={})", CURRENT_VERSION)
        done = written = 0

        with self._db.session_scope(commit=False) as session:
            total = (
                session.query(ChannelDB.id)
                .join(MetadataDB, MetadataDB.id == ChannelDB.metadata_id)
                .filter(MetadataDB.runtime.is_(None),
                        ChannelDB.raw_data.isnot(None))
                .count()
            )
        logger.info("RuntimeBackfillTask: {:,} candidate rows", total)

        # Keyset pagination, NOT offset. The filter is ``runtime IS NULL`` and
        # the loop's own writes remove rows from that set, so an OFFSET would
        # step past exactly as many rows as the previous batch wrote. Paging on
        # the last channel id seen is immune to the set shrinking underneath it
        # and rides the primary-key index.
        last_id = ""
        while True:
            if is_cancelled():
                logger.info("RuntimeBackfillTask: cancelled at {:,}/{:,}", done, total)
                return
            with self._db.session_scope() as session:
                batch = (
                    session.query(ChannelDB.id, ChannelDB.raw_data, MetadataDB)
                    .join(MetadataDB, MetadataDB.id == ChannelDB.metadata_id)
                    .filter(MetadataDB.runtime.is_(None),
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
                    minutes = runtime_from_raw(raw)
                    if minutes:
                        meta.runtime = minutes
                        written += 1
                last_id = batch[-1][0]
            progress_cb(min(done, total), total)

        progress_cb(total, total)
        logger.info(
            "RuntimeBackfillTask: complete — {:,} scanned, {:,} runtimes written",
            done, written,
        )

    def on_completed(self, config: "Config") -> None:
        """Record the version so this does not run again."""
        config.runtime_backfill_version = CURRENT_VERSION
        config.save()
