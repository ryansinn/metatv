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

The index diet (STORAGE-1a)
-----------------------------
27 of ``channels``'s indexes changed shape or disappeared (docs/REFACTOR_PLAN.md
D55/D56): three dead/redundant single-column indexes drop with no replacement
(``core.database.CHANNEL_DEAD_INDEX_NAMES``), and 24 more convert from a FULL
``index=True`` index to a PARTIAL one — a column whose real population is a
sliver of 786k rows (``last_played``: 7.4 MiB indexing 25 non-NULL rows on the
owner's library) — via ``sqlite_where`` (``core.database.CHANNEL_PARTIAL_INDEX_SPECS``,
the ``(column, where)`` pairs; both constants also drive ``Database._migrate()``'s
``DROP INDEX`` list, one source for both). Safe for `col = ?` (implies `col IS
NOT NULL`, re-verified per column with EXPLAIN QUERY PLAN — see
``tests/test_query_indexes.py`` and the PR body), not for `col IS NULL` on the
same column — checked against every real call site, in each case NULL was
already the vast majority of rows. This task builds all 24 in their new shape
via the same generic declared-index sweep described below; the only NEW code
here is the statistics-staleness fix that follows, since a reshaped index set
needs its statistics to actually catch up.

Statistics staleness (STORAGE-1a)
----------------------------------
``needs_run``'s statistics half used to ask one question — "does ``channels``
have ANY ``sqlite_stat1`` row at all" — and treated the answer as "are the
statistics GOOD". Those are different questions. The STORAGE-1 design pass
measured the owner's real library and found ``sqlite_stat1`` reporting
roughly 455-way selectivity for every low-cardinality index —
``ix_channels_is_hidden`` recorded 1,725 rows/key against a true 393,162 (2
distinct values), 227x off. Once written, that row satisfied the old
"any row exists" check forever: the unbounded, CORRECT ``ANALYZE`` this task
runs never fired again, because nothing ever asked whether the number it
already had was still true. This matters more, not less, after the
STORAGE-1a index diet lands: the planner is choosing plans over a
substantially reshaped index set (24 columns went full -> partial) using
statistics that describe the OLD shape until something re-runs ``ANALYZE``.

The fix asks the second question. ``_has_channel_stats`` now reads back the
row-count ANALYZE recorded against ``ix_channels_hidden_type_name`` — a full
(non-partial) composite that is always present and always covers every row,
so it is safe to treat as "the table's size" (a PARTIAL index would report
only the rows satisfying its own ``WHERE``, not the table — a live trap now
that 24 of them exist) — and compares it to a real ``SELECT COUNT(*)``. Past
:data:`_CHANNEL_STATS_DRIFT_TOLERANCE` (20%) the statistics are stale and
``needs_run`` returns True, which makes ``run()`` execute its always-present
trailing ``ANALYZE`` again. Two triggers end up covering this task, both
already implicit in the existing shape:

1. **After an index change.** Dropping+recreating 27 indexes (STORAGE-1a
   itself) makes ``_missing_indexes`` non-empty on the very next launch,
   which alone makes ``needs_run`` True and ``run()`` executes — ending, as
   it always has, in one unlimited ``ANALYZE``. No extra plumbing needed.
2. **Staleness drift**, the new check above — catches ordinary catalog
   growth/shrinkage between index changes, which is the gap that let the
   owner's real stats go stale forever once written.

20% is deliberately generous — a provider swap or a big prune commonly moves
the table that much, and a drift that size is exactly the case ANALYZE
exists to correct; a tighter threshold would re-run a real ``COUNT(*)`` (and
occasionally a real ``ANALYZE``) on every launch for no measurable benefit.
The ``COUNT(*)`` itself is cheap next to what it gates: SQLite answers it
from the smallest available index without touching table rows, and
``needs_run`` already runs off the main thread (see
``core/migration_manager.py``'s docstring on the probe-pass stall it fixed).
``run()``'s ``ANALYZE`` is the one real cost here — ~11s on a 1.6 GB library
per the measurement above — and it already runs where it always has: inside
``MigrationManager``'s single-worker background executor, under DB-10's
``write_gate.background_write_gate()`` (``migration_manager.py`` wraps every
task there), never on the UI thread and never inside ``Database._migrate()``.

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


#: Row-count drift, as a fraction of the table's ACTUAL size, past which
#: recorded ``sqlite_stat1`` figures are treated as stale — see "Statistics
#: staleness (STORAGE-1a)" above. 20% is deliberately generous: a routine
#: catalog refresh or a big prune commonly moves the table that much, and
#: that is exactly the case ANALYZE exists to correct, not noise to ignore.
_CHANNEL_STATS_DRIFT_TOLERANCE = 0.20

#: The index read back to learn ANALYZE's row-count estimate for ``channels``.
#: Must be a FULL (non-partial) index — a partial one's ``sqlite_stat1`` row
#: reports the rows ITS OWN ``WHERE`` matches, not the table, which would read
#: as false staleness (or false freshness) on every one of the 24 partial
#: indexes STORAGE-1a added. This composite is always declared and always
#: covers every row.
_CHANNEL_ROW_ESTIMATE_INDEX = "ix_channels_hidden_type_name"


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

    def _channel_row_estimate(self, conn: "Connection") -> "int | None":
        """The row count ANALYZE last recorded for ``channels``, or None.

        Reads ``sqlite_stat1`` for :data:`_CHANNEL_ROW_ESTIMATE_INDEX`
        specifically — a full, non-partial index — rather than "any row for
        this table", because a PARTIAL index's row carries the count of rows
        satisfying ITS OWN ``WHERE``, not the table (STORAGE-1a made this a
        live trap: 24 of ``channels``'s indexes are now partial). None means
        no ANALYZE has ever recorded this index, which ``ANALYZE`` on an
        empty table also produces — see the module docstring's "Idempotency".
        """
        stat = conn.execute(text(
            "SELECT stat FROM sqlite_stat1 WHERE tbl = 'channels' AND idx = :idx"
        ), {"idx": _CHANNEL_ROW_ESTIMATE_INDEX}).scalar()
        if not stat:
            return None
        try:
            return int(str(stat).split()[0])
        except (ValueError, IndexError):
            return None

    def _has_channel_stats(self, conn) -> bool:
        """Return True when ``channels`` has statistics that are not stale.

        "Has a statistics row" used to be the whole check, and a garbage row
        anywhere satisfied it forever — see "Statistics staleness
        (STORAGE-1a)" in the module docstring for the measured wrongness this
        replaces. Now also compares the recorded row count to a real
        ``SELECT COUNT(*)`` and treats a drift past
        :data:`_CHANNEL_STATS_DRIFT_TOLERANCE` as stale.
        """
        exists = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_stat1'"
        )).scalar()
        if not exists:
            return False
        recorded = self._channel_row_estimate(conn)
        if recorded is None:
            return False
        actual = conn.execute(text("SELECT COUNT(*) FROM channels")).scalar() or 0
        drift = abs(actual - recorded) / max(actual, 1)
        return drift <= _CHANNEL_STATS_DRIFT_TOLERANCE

    def needs_run(self, config: "Config") -> bool:
        """Return True while an index is missing or ``channels``'s statistics are stale.

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
