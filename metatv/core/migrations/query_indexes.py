"""Migration task: build every declared index (the channel list's included), then ANALYZE.

The indexes
-----------
``ChannelDB`` declares three of the ones this section is about. SQLAlchemy's
``create_all`` builds a declared index on a database that does not exist yet;
it does NOT add an index to a table that is already there, and every existing
user's library is already there — so this task creates them too, with
``checkfirst=True`` making that a no-op where they already exist. (This task
now builds every declared index on every table, not only these three — see
"Generalized to every declared index" below; this section is kept for why
these particular three are shaped the way they are.)

The channel list filters on two columns and sorts on a third::

    WHERE is_hidden = 0 AND media_type = 'movie' ORDER BY name LIMIT 50

``channels`` has 33 indexes and every one is single-column. SQLite uses one
index per table reference, so it takes ``ix_channels_is_hidden`` — which
matches 492,510 of 492,511 rows — and sorts 334,318 of them in a temp b-tree to
return fifty. 252 ms for the first page, 605 ms for a deep one.

TWO composite indexes, because the app has two shapes.
``(is_hidden, media_type, name)`` serves a single media type;
``(is_hidden, name)`` serves the default view, which passes
``media_types=['live', 'movie', 'series']`` and so constrains nothing usable.
Fixing only ``is_hidden`` in the three-column index leaves it ordered by
``(media_type, name)``, which is not ``name`` order, so one index cannot do
both.

The third index, and why
------------------------
``ix_channels_hidden_name`` also LURES the planner. Favorites asks::

    WHERE is_favorite = 1 AND is_hidden = 0 ORDER BY name

28 rows out of 492,511. Walking all of them in name order avoids a sort, and
SQLite takes that trade — 190 ms became 344 ms.

Statistics fix it only on some builds, which is why they are not the fix.
``sqlite_stat1`` records the AVERAGE rows per distinct value; ``is_favorite``
has two values, so stat1 can only say "about 246,000", and the planner's choice
is correct given what it was told. Knowing that the value ``1`` matches 28 rows
takes ``sqlite_stat4``, which exists only when SQLite was compiled with
``SQLITE_ENABLE_STAT4``. Development here runs Python 3.14, whose SQLite has
it. CI's 3.12 does not, and neither, therefore, can the packaged app be assumed
to. The first version of this change measured 0.5 ms locally and would have
shipped a 1.8x regression.

So the fix is a PARTIAL index — ``(is_hidden, name) WHERE is_favorite = 1`` —
which contains 28 rows and is chosen from its own WHERE clause, no statistics
involved. It costs 0.2 s to build and works identically on both planners.

(``ON channels (name) WHERE is_favorite = 1`` does NOT work: it offers only a
full-index SCAN, and a stat1-only planner prefers a SEARCH with an equality
over a SCAN of any size. Keeping ``is_hidden`` as the leading column is what
makes it a SEARCH.)

Then ANALYZE
------------
Statistics are still worth having, just for a different query than the one that
motivated them. ``get_by_category`` is 487 ms with the indexes and no
statistics, 126 ms with them. On its own, before any of this, ANALYZE was
measured as worth nothing at all: 221.6 ms -> 222.9 ms on the channel-list
query, byte-identical plan, because both candidate indexes matched nearly every
row and there was no better plan to choose.

``PRAGMA analysis_limit`` was tried and rejected: at 1000 it samples too
shallowly to change the plans that matter, and saves little anyway (10.0 s
against 11.5 s), because the cost is reading 33 indexes rather than counting
rows.

Measured, best of three, through the real repository on a copy of the
production database (492,511 channels). "no stat4" is the shipped planner,
simulated by dropping ``sqlite_stat4`` after ANALYZE::

    case                    before   indexes only   + ANALYZE (no stat4)
    default view (3 types)   289.9            1.2                    1.1
    one media type           244.3            1.3                    1.2
    two media types          279.5            1.2                    1.1
    get_favorites            182.7            0.5                    0.5
    get_by_category          145.9          487.4                  126.0
    get_rec_suppressed       439.5          380.8                  357.6
    get_hidden_channels        0.2            0.2                    0.2
    search("star")           340.8          487.4                  516.3

``search()`` is the one honest regression: it has no LIMIT, so it must touch
every one of its 3,282 matches, and walking an index in NAME order visits table
rows in random page order where the old plan walked roughly in rowid order and
sorted at the end. It has no callers in the application — only tests — so it is
recorded here rather than worked around.

Idempotency
-----------
``needs_run`` asks the database, not a config field: True while any index is
missing, or while ``sqlite_stat1`` holds no row for ``channels``. Both are facts
the task itself establishes, so an interrupted run simply repeats.

The ``sqlite_stat1`` half also handles the case a version counter would get
wrong. A brand-new install has all three indexes from ``create_all`` and an
EMPTY channels table; ``ANALYZE`` on an empty table writes no ``sqlite_stat1``
row at all, so the task stays pending and runs for real after the first catalog
import — which is when the statistics start to mean something.

Generalized to every declared index (DB-6)
-------------------------------------------
This task used to build only the three composite/partial indexes above, named
in a literal dict. Everything else lived a second life: a column gets
``index=True`` in the ORM, ``create_all`` builds it for anyone installing from
scratch, and reaching an EXISTING database required someone to ALSO remember to
append a ``CREATE INDEX IF NOT EXISTS`` line to the hand-written list in
``Database._migrate()``. Nobody did, reliably — ``ChannelDB`` alone declares 39
``index=True`` columns and that hand list covered about a third of them, so a
real, long-lived library was missing a double-digit number of its own declared
indexes with no error and no signal, just queries that stayed slow.

So the set this task ensures is now DERIVED, not hand-listed:
``for table in Base.metadata.sorted_tables: for index in table.indexes``
walks every ``Index`` SQLAlchemy will materialize — both the implicit
``ix_<table>_<column>`` index behind ``index=True`` and an explicit
``Index(...)`` in a model's ``__table_args__`` (the three above, and the
composite on ``content_tags`` that used to be hand-written SQL only — see
``ContentTagDB.__table_args__``). That is exactly what ``create_all`` builds
for a database that does not exist yet, so building the same set for one that
does is what makes a newly added ``index=True`` column reach every existing
user automatically, with no second edit anywhere. ``needs_run`` compares that
declared name set against ``PRAGMA index_list`` per table — missing means
pending — so a model that grows another indexed column is covered the moment
it ships, not the moment someone remembers a migration list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text

from metatv.core.database import Base

if TYPE_CHECKING:
    from sqlalchemy import Index
    from sqlalchemy.engine import Connection

    from metatv.core.config import Config
    from metatv.core.database import Database


def _all_declared_indexes() -> list[tuple[str, "Index"]]:
    """Every ``(table_name, Index)`` SQLAlchemy will materialize for the ORM.

    Covers both an ``index=True`` column's implicit index and an explicit
    ``Index(...)`` in ``__table_args__`` — see the module docstring. Sorted by
    ``(table, index name)`` so a run's progress and creation order are
    deterministic and reproducible across launches.
    """
    return sorted(
        (
            (table.name, index)
            for table in Base.metadata.sorted_tables
            for index in table.indexes
        ),
        key=lambda pair: (pair[0], pair[1].name),
    )


class QueryIndexTask:
    """Build every declared-but-missing index, then refresh query statistics."""

    id: str = "query_indexes"
    label: str = "Building channel indexes"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    # ── State ───────────────────────────────────────────────────────────────

    def _existing_index_names(self, conn: "Connection", table: str) -> set[str]:
        """Index names SQLite already has for *table* (includes autoindexes)."""
        return {row[1] for row in conn.execute(text(f"PRAGMA index_list({table})"))}

    def _missing_indexes(self, conn: "Connection") -> list[tuple[str, "Index"]]:
        """Return the declared ``(table, Index)`` pairs the database lacks.

        One ``PRAGMA index_list`` per table, cached for the call — cheap next
        to the index BUILDs this drives (~15 tables vs. up to 785k rows/index).
        """
        have_by_table: dict[str, set[str]] = {}
        missing = []
        for table, index in _all_declared_indexes():
            if table not in have_by_table:
                have_by_table[table] = self._existing_index_names(conn, table)
            if index.name not in have_by_table[table]:
                missing.append((table, index))
        return missing

    def _has_channel_stats(self, conn) -> bool:
        """Return True when ANALYZE has recorded statistics for ``channels``.

        Checks for the row, not the table: ``ANALYZE`` always creates
        ``sqlite_stat1``, but writes no row for a table that is empty.
        """
        exists = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_stat1'"
        )).scalar()
        if not exists:
            return False
        return bool(conn.execute(text(
            "SELECT 1 FROM sqlite_stat1 WHERE tbl = 'channels' LIMIT 1"
        )).scalar())

    def needs_run(self, config: "Config") -> bool:
        """Return True while an index is missing or ``channels`` has no statistics.

        Args:
            config: Unused; the database is the source of truth here.

        Returns:
            True when there is work to do.
        """
        try:
            with self._db.engine.connect() as conn:
                return bool(self._missing_indexes(conn)) or not self._has_channel_stats(conn)
        except Exception:
            logger.exception("QueryIndexTask: could not read index state; skipping")
            return False

    # ── Work ────────────────────────────────────────────────────────────────

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Create every missing declared index, then ANALYZE.

        Runs on a **worker thread** (called by ``MigrationManager``). Exceptions
        propagate so the manager leaves the task pending and it retries next
        launch.

        Args:
            progress_cb: ``(done, total)`` after each step.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for the manager's keyword call.
        """
        declared = _all_declared_indexes()
        total = len(declared) + 1  # every declared index, then the ANALYZE
        done = 0
        progress_cb(done, total)

        with self._db.engine.connect() as conn:
            missing = {
                (table, index.name) for table, index in self._missing_indexes(conn)
            }
            for table, index in declared:
                if is_cancelled():
                    logger.info("QueryIndexTask: cancelled after {} of {}", done, total)
                    return
                if (table, index.name) in missing:
                    # index.create (not hand-formatted SQL) so a partial
                    # index's sqlite_where survives — see the module docstring.
                    logger.info("QueryIndexTask: creating {}", index.name)
                    index.create(bind=conn, checkfirst=True)
                    conn.commit()
                done += 1
                progress_cb(done, total)

            if is_cancelled():
                return

            # Deliberately unbounded: see the module docstring for why
            # analysis_limit is not used. ~11 s on a 1.6 GB library, once.
            logger.info("QueryIndexTask: running ANALYZE")
            conn.execute(text("ANALYZE"))
            conn.commit()
            done += 1
            progress_cb(done, total)

        logger.info("QueryIndexTask: complete")

    def on_completed(self, config: "Config") -> None:
        """No bookkeeping to persist — ``needs_run`` reads the database itself.

        Args:
            config: Unused.
        """
        return
