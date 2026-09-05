"""Migration task: fill provider-payload-derived columns already ingested elsewhere.

Started as ``MetadataDB``-only; generalized (DB-4) to also target ``ChannelDB``
columns, since the same "the payload had it, nothing read it" shape recurred
there. Four fields, two target tables:

``runtime`` (MetadataDB)
    Populated on **0 of 652,216 rows**. Providers send it — ``info.duration`` on
    movies, ``episode_run_time`` at the TOP level on series — and
    ``metadata_from_raw`` read only the first. 48,322 series resolve a real
    value; a further 79,230 send ``"0"``, which is mapped to None rather than a
    literal zero, since a stored 0 renders as "0 min".

``trailer_url`` (MetadataDB)
    Populated on 46,148 rows out of the **114,308** whose payload carries one.
    Same shape of miss: the code read the nested ``info.youtube_trailer`` and
    Xtream VOD rows put it at the top level under ``trailer``. Nothing rendered
    it either, until the Trailer button.

``detected_rating`` / ``detected_added`` (ChannelDB)
    The Discover "Top Rated"/"Recently Added" shelves sorted/filtered on
    ``json_extract(channels.raw_data, '$.rating'/'$.added')`` at query time —
    1.1-1.9s per shelf over 785k rows. Now stored + indexed at ingestion
    (``providers/xtream.py``); this backfills the rows that predate that.

Fixed forward at ingestion, which covers everything ingested from here on.
This is the one-time pass for rows that already exist, because cached data is
not re-derived on read.

Adding a field is one row in ``FIELDS`` and (when it targets a NEW table) a
``CURRENT_VERSION`` bump — not a 22nd migration module and a 22nd hand-written
registration in ``main_window.py`` (ledger F29). A ``FIELDS`` row names its
target table: ``"MetadataDB"`` rows join on ``metadata_id`` (the row being
mutated is the metadata row); ``"ChannelDB"`` rows need no join — the row being
mutated IS the channel that carries the ``raw_data``.

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

from metatv.core.content_identity import added_from_raw, rating_from_raw
from metatv.metadata_providers.provider_metadata import (
    runtime_from_raw, trailer_from_raw,
)

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.config import Config
    from metatv.core.database import Database

#: Bump when a FIELDS row targets a table/column no earlier version filled, so
#: libraries that already ran an earlier version still backfill it. Two rows
#: can ship under the same bump when they land together (rating + added, both
#: new in this version) — the invariant is "every column has SOME version that
#: covers it", not one version number per field.
#:   1 — runtime
#:   2 — trailer_url
#:   3 — detected_rating, detected_added
CURRENT_VERSION = 3

#: Rows per commit. Matches the other backfills — large enough that the commit
#: overhead disappears, small enough that a cancel loses little work.
_BATCH = 2000


def _detected_rating_from_raw(raw_data) -> "float | None":
    """Adapt :func:`~metatv.core.content_identity.rating_from_raw` (a scalar
    resolver, called at ingestion as ``rating_from_raw(raw_data.get("rating"))``)
    to this task's blob-shaped ``resolve(raw_data)`` calling convention — the
    same shape ``runtime_from_raw``/``trailer_from_raw`` already use.
    """
    return rating_from_raw(raw_data.get("rating")) if isinstance(raw_data, dict) else None


def _detected_added_from_raw(raw_data) -> "int | None":
    """Sibling of :func:`_detected_rating_from_raw`, for ``detected_added``."""
    return added_from_raw(raw_data.get("added")) if isinstance(raw_data, dict) else None


#: column -> (target table name, resolver). The resolver is the SAME function
#: ingestion calls (directly for MetadataDB fields; wrapped for the ChannelDB
#: ones, which take a scalar at ingestion — see the two functions above), so a
#: field cannot drift between the two paths.
FIELDS: "dict[str, tuple[str, object]]" = {
    "runtime": ("MetadataDB", runtime_from_raw),
    "trailer_url": ("MetadataDB", trailer_from_raw),
    "detected_rating": ("ChannelDB", _detected_rating_from_raw),
    "detected_added": ("ChannelDB", _detected_added_from_raw),
}


class RawFieldBackfillTask:
    """Populate ``MetadataDB``/``ChannelDB`` columns from stored ``raw_data``."""

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
        logger.info("RawFieldBackfillTask: starting (version={})", CURRENT_VERSION)

        counts = {}
        with self._db.session_scope(commit=False) as session:
            for column, (target, _resolve) in FIELDS.items():
                counts[column] = self._count_candidates(session, target, column)
        total = sum(counts.values())
        logger.info("RawFieldBackfillTask: {:,} candidate rows across {}",
                    total, ", ".join(f"{c} ({n:,})" for c, n in counts.items()))

        done = 0
        for column, (target, resolve) in FIELDS.items():
            written = 0
            # Keyset pagination, NOT offset. The filter is ``<column> IS NULL``
            # and the loop's own writes remove rows from that set, so an OFFSET
            # would step past exactly as many rows as the previous batch wrote.
            # Paging on the last row id seen is immune to the set shrinking
            # underneath it and rides the primary-key index.
            last_id = ""
            while True:
                if is_cancelled():
                    logger.info("RawFieldBackfillTask: cancelled at {:,}/{:,}",
                                done, total)
                    return
                with self._db.session_scope() as session:
                    batch = self._load_batch(session, target, column, last_id)
                    if not batch:
                        break
                    for _row_id, raw, mutable in batch:
                        done += 1
                        value = resolve(raw)
                        if value is not None:
                            setattr(mutable, column, value)
                            written += 1
                    last_id = batch[-1][0]
                progress_cb(min(done, total), total)
            logger.info("RawFieldBackfillTask: {} — {:,} written", column, written)

        progress_cb(total, total)
        logger.info("RawFieldBackfillTask: complete — {:,} rows scanned", done)

    @staticmethod
    def _count_candidates(session, target: str, column: str) -> int:
        """Count rows where *column* (on *target*) is still NULL but fillable."""
        from metatv.core.database import ChannelDB, MetadataDB

        if target == "MetadataDB":
            return (
                session.query(ChannelDB.id)
                .join(MetadataDB, MetadataDB.id == ChannelDB.metadata_id)
                .filter(getattr(MetadataDB, column).is_(None),
                        ChannelDB.raw_data.isnot(None))
                .count()
            )
        return (
            session.query(ChannelDB.id)
            .filter(getattr(ChannelDB, column).is_(None),
                    ChannelDB.raw_data.isnot(None))
            .count()
        )

    @staticmethod
    def _load_batch(session, target: str, column: str, last_id: str):
        """Return ``[(id, raw_data, mutable_row), ...]`` for one page.

        ``MetadataDB`` targets join on ``metadata_id`` — the row being mutated
        is the ``MetadataDB`` row. ``ChannelDB`` targets need no join — the row
        being mutated IS the channel that carries the ``raw_data``.
        """
        from metatv.core.database import ChannelDB, MetadataDB

        if target == "MetadataDB":
            return (
                session.query(ChannelDB.id, ChannelDB.raw_data, MetadataDB)
                .join(MetadataDB, MetadataDB.id == ChannelDB.metadata_id)
                .filter(getattr(MetadataDB, column).is_(None),
                        ChannelDB.raw_data.isnot(None),
                        ChannelDB.id > last_id)
                .order_by(ChannelDB.id)
                .limit(_BATCH)
                .all()
            )
        channels = (
            session.query(ChannelDB)
            .filter(getattr(ChannelDB, column).is_(None),
                    ChannelDB.raw_data.isnot(None),
                    ChannelDB.id > last_id)
            .order_by(ChannelDB.id)
            .limit(_BATCH)
            .all()
        )
        return [(c.id, c.raw_data, c) for c in channels]

    def on_completed(self, config: "Config") -> None:
        """Record the version so this does not run again."""
        config.raw_field_backfill_version = CURRENT_VERSION
        config.save()
