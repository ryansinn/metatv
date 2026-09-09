"""The channel list's composite indexes, and the ANALYZE that makes them safe.

Every assertion here reads a QUERY PLAN rather than a stopwatch. The plan is
the mechanism — which index SQLite chose and whether it had to sort — and it is
identical on both CI runners, where a millisecond figure would not be.

The plan the app must NOT get is spelled out in
``test_analyze_stops_the_planner_choosing_the_wrong_index_for_favorites``:
adding an index can make a query slower, and this one did, by 1.8x, until the
ANALYZE landed with it.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text

from metatv.core.database import Base, ChannelDB, Database
from metatv.core.migrations.query_indexes import QueryIndexTask, _all_declared_indexes

# The three shapes the channel list actually issues.
Q_TYPED = (
    "SELECT id FROM channels WHERE is_hidden = 0 AND media_type = 'movie' "
    "ORDER BY name LIMIT 50"
)
Q_UNTYPED = "SELECT id FROM channels WHERE is_hidden = 0 ORDER BY name LIMIT 50"
Q_FAVORITES = (
    "SELECT id FROM channels WHERE is_favorite = 1 AND is_hidden = 0 ORDER BY name"
)


def _plan(db: Database, sql: str) -> str:
    """Return the query plan for *sql* as one line."""
    with db.engine.connect() as conn:
        rows = conn.execute(text("EXPLAIN QUERY PLAN " + sql))
        return " | ".join(str(r[-1]) for r in rows)


def _run(task: QueryIndexTask) -> list[tuple[int, int]]:
    """Run the task, returning what it reported to progress_cb."""
    seen: list[tuple[int, int]] = []
    task.run(lambda done, total: seen.append((done, total)), lambda: False)
    return seen


@pytest.fixture
def db(tmp_path):
    """A real on-disk database with enough rows to plan against.

    On disk, not ``:memory:`` — this task's whole subject is what SQLite writes
    into ``sqlite_master`` and ``sqlite_stat1``.

    3,000 channels, half movies and half live, three of them favorites. The
    planner's choice does not depend on the count while there are no
    statistics, so this reproduces the production behaviour at a size a test
    can afford.
    """
    database = Database(f"sqlite:///{tmp_path}/t.db")
    database.create_tables()
    with database.session_scope() as session:
        for i in range(3000):
            session.add(ChannelDB(
                id=f"c{i}",
                source_id=str(i),
                provider_id="p",
                name=f"Name {i:05d}",
                media_type="movie" if i % 2 else "live",
                is_hidden=False,
                is_favorite=(i < 3),
            ))
    return database


def test_the_typed_channel_list_uses_the_three_column_index(db):
    """The hot query filters on two columns and sorts on a third; one index does all of it."""
    _run(QueryIndexTask(db))
    plan = _plan(db, Q_TYPED)

    assert "ix_channels_hidden_type_name" in plan, plan
    assert "is_hidden=?" in plan and "media_type=?" in plan, (
        f"the index was chosen but only partly used: {plan}"
    )
    assert "TEMP B-TREE" not in plan, (
        f"still sorting; the index is not supplying `name` order: {plan}"
    )


def test_the_untyped_channel_list_gets_its_own_index(db):
    """(is_hidden, media_type, name) cannot order a query that fixes only is_hidden.

    Fixing is_hidden leaves that index ordered by (media_type, name), which is
    not `name` order — so the untyped view needs (is_hidden, name) beside it.
    This is the assertion that fails if someone decides one index is enough.
    """
    _run(QueryIndexTask(db))
    plan = _plan(db, Q_UNTYPED)

    assert "ix_channels_hidden_name" in plan, plan
    assert "TEMP B-TREE" not in plan, (
        f"still sorting the whole table to return fifty rows: {plan}"
    )


def test_the_partial_index_keeps_favorites_off_the_full_walk(db):
    """Adding (is_hidden, name) made Favorites 1.8x SLOWER; a partial index undoes it.

    Favorites matches 28 rows of 492,511, and ``ix_channels_hidden_name`` lets
    SQLite skip the sort by walking every row in name order instead. Measured
    on the owner's library: 190 ms -> 344 ms.

    Statistics are NOT the fix, which is the whole point of this test.
    ``sqlite_stat1`` records average rows per distinct value, and
    ``is_favorite`` has two values, so stat1 can only say "about half the
    table". Learning that the value 1 matches 28 rows needs ``sqlite_stat4``,
    which exists only where SQLite was built with SQLITE_ENABLE_STAT4 — true of
    the Python 3.14 used for development, false on CI's 3.12. The first version
    of this change asserted the post-ANALYZE plan and passed locally while
    failing on both runners.

    ``ix_channels_favorite_hidden_name`` is chosen from its own WHERE clause,
    so this assertion holds on either build.

    STORAGE-1a (D58) reopened this exact trap from the other side: a
    standalone ``ix_channels_is_favorite`` partial index — gated by the SAME
    ``is_favorite = 1`` predicate — gave the planner a second candidate, and
    CI's non-STAT4 planner chose IT over this composite, losing the free
    ordering and adding ``USE TEMP B-TREE FOR ORDER BY``. Fixed by never
    creating that standalone index at all (see channel_index_policy.py's
    ``CHANNEL_DEAD_INDEX_NAMES``) rather than by hoping the planner keeps
    picking the composite — asserted here directly so the fix cannot regress
    silently.
    """
    _run(QueryIndexTask(db))

    plan = _plan(db, Q_FAVORITES)
    assert "ix_channels_favorite_hidden_name" in plan, (
        f"Favorites is not using the partial index: {plan}"
    )
    assert "ix_channels_hidden_name (" not in plan, (
        f"Favorites fell back to the full name-ordered walk: {plan}"
    )
    assert "USE TEMP B-TREE" not in plan, f"Favorites is sorting again: {plan}"
    with db.engine.connect() as conn:
        names = _index_names(conn, "channels")
    assert "ix_channels_is_favorite" not in names, (
        "a standalone is_favorite index exists again and can lure the "
        "planner away from the composite (D58)"
    )


def test_the_partial_index_does_not_need_statistics(db):
    """The plan must be right from the index alone, before ANALYZE has run.

    This is the assertion that would have caught the STAT4 mistake: it holds
    with no statistics in the database at all, which is the weakest planner any
    user can have.
    """
    with db.engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS sqlite_stat4"))
        conn.execute(text("DROP TABLE IF EXISTS sqlite_stat1"))
        conn.commit()

    plan = _plan(db, Q_FAVORITES)
    assert "ix_channels_favorite_hidden_name" in plan, (
        f"partial index not chosen without statistics: {plan}"
    )


def test_needs_run_stays_true_until_channels_have_statistics(db):
    """A version counter would get this wrong; asking the database does not.

    A new install has both indexes from ``create_all`` and an EMPTY channels
    table. ANALYZE on an empty table writes no ``sqlite_stat1`` row, so the
    task must stay pending and run for real after the first catalog import.
    """
    task = QueryIndexTask(db)

    with db.engine.connect() as conn:
        have = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='channels'"
        ))}
    assert {"ix_channels_hidden_type_name", "ix_channels_hidden_name",
            "ix_channels_favorite_hidden_name"} <= have, (
        "create_all did not build the composite indexes; __table_args__ is wrong"
    )

    assert task.needs_run(None) is True, "indexes present but no statistics — still pending"

    _run(task)
    assert task.needs_run(None) is False


def test_running_twice_is_a_no_op_and_reports_every_step(db):
    """Interrupting the task must be safe, so re-running it must be too.

    ``total`` is derived (every declared index + the ANALYZE), not a literal
    4 — the whole point of DB-6 is that this count grows on its own as the
    model gains indexed columns, with nothing here to keep in sync.
    """
    task = QueryIndexTask(db)
    total = len(_all_declared_indexes()) + 1

    first = _run(task)
    assert first[0] == (0, total) and first[-1] == (total, total), first

    second = _run(task)
    assert second[-1] == (total, total), second
    assert task.needs_run(None) is False


def test_cancelling_leaves_the_task_pending(db):
    """A cancelled run must not look finished, or the statistics never land."""
    task = QueryIndexTask(db)
    task.run(lambda done, total: None, lambda: True)

    assert task.needs_run(None) is True


def _channel_stat(database: Database) -> str | None:
    """The recorded row estimate for the three-column index, or None."""
    with database.engine.connect() as conn:
        return conn.execute(text(
            "SELECT stat FROM sqlite_stat1 "
            "WHERE tbl = 'channels' AND idx = 'ix_channels_hidden_type_name'"
        )).scalar()


def test_closing_refreshes_statistics_that_the_catalog_has_outgrown(tmp_path):
    """QueryIndexTask writes statistics once; a refresh can add six figures of rows.

    ``PRAGMA optimize`` on close re-ANALYZEs only what has drifted, so the
    numbers the planner reads keep up with the library. Without it, the
    statistics describe whatever the catalog looked like the day the migration
    ran, and every index choice after that is made from a stale picture.
    """
    def _add(database, lo, hi):
        with database.session_scope() as session:
            for i in range(lo, hi):
                session.add(ChannelDB(
                    id=f"c{i}", source_id=str(i), provider_id="p",
                    name=f"N{i:06d}", media_type="movie", is_hidden=False,
                ))

    database = Database(f"sqlite:///{tmp_path}/t.db")
    database.create_tables()
    _add(database, 0, 300)
    _run(QueryIndexTask(database))
    assert _channel_stat(database).startswith("300 "), _channel_stat(database)

    _add(database, 300, 30000)
    assert _channel_stat(database).startswith("300 "), (
        "statistics should still be stale before close"
    )

    database.close()

    reopened = Database(f"sqlite:///{tmp_path}/t.db")
    try:
        stat = _channel_stat(reopened)
        assert stat is not None and stat.startswith("30000 "), (
            f"close() did not refresh statistics; still {stat!r}"
        )
    finally:
        reopened.engine.dispose()


def _index_names(conn, table: str) -> set[str]:
    """Every index SQLite has for *table*, autoindexes included."""
    return {row[1] for row in conn.execute(text(f"PRAGMA index_list({table})"))}


def test_every_declared_index_exists_after_the_upgrade(tmp_path):
    """DB-6: a library that predates every declared index must end up with all of them.

    Builds the schema, then drops every non-autoindex index on every table —
    simulating a long-lived library that only ever got what a hand-maintained
    migration list remembered to create. Must FAIL on the pre-fix tree: the old
    ``QueryIndexTask`` only knew about the three composite/partial indexes on
    ``channels``, so 85 of the 88 indexes ``Base.metadata`` declares (across
    every table, not just ``channels``) were left behind.
    """
    database = Database(f"sqlite:///{tmp_path}/legacy.db")
    database.create_tables()

    declared = _all_declared_indexes()
    with database.engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            for name in _index_names(conn, table.name):
                if not name.startswith("sqlite_autoindex_"):
                    conn.execute(text(f"DROP INDEX {name}"))
        conn.commit()

        have_before = {
            table.name: _index_names(conn, table.name) for table in Base.metadata.sorted_tables
        }
    assert not any(index.name in have_before[table] for table, index in declared), (
        "test setup failed to drop every declared index"
    )

    _run(QueryIndexTask(database))

    with database.engine.connect() as conn:
        have_after = {
            table.name: _index_names(conn, table.name)
            for table in Base.metadata.sorted_tables
        }
    missing = [
        f"{table}.{index.name}"
        for table, index in declared
        if index.name not in have_after[table]
    ]
    assert not missing, (
        f"{len(missing)} declared index(es) missing after the upgrade: {missing}"
    )


def test_the_index_task_is_idempotent(tmp_path):
    """A second run against an already-complete database creates nothing."""
    database = Database(f"sqlite:///{tmp_path}/idem.db")
    database.create_tables()
    _run(QueryIndexTask(database))

    with database.engine.connect() as conn:
        before = {
            table.name: _index_names(conn, table.name)
            for table in Base.metadata.sorted_tables
        }

    second = _run(QueryIndexTask(database))
    total = len(_all_declared_indexes()) + 1
    assert second[-1] == (total, total), second

    with database.engine.connect() as conn:
        after = {
            table.name: _index_names(conn, table.name)
            for table in Base.metadata.sorted_tables
        }
    assert before == after, "the idempotent second run changed the index set"


# ---------------------------------------------------------------------------
# STORAGE-1a — the index diet: three free drops, 24 full->partial conversions,
# and the ANALYZE staleness fix. Ships through the same DB-6 machinery these
# tests already exercise: Database._migrate()'s DROP INDEX list removes the
# old-shape index by name, QueryIndexTask's declared-index sweep rebuilds the
# ones still declared (now in their partial shape) and leaves the rest gone.
# ---------------------------------------------------------------------------


def _index_sql(conn, name: str) -> str | None:
    """The exact ``CREATE INDEX`` text SQLite has stored for *name*, or None."""
    return conn.execute(text(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"
    ), {"name": name}).scalar()


def test_the_four_free_drops_are_removed_and_never_rebuilt(tmp_path):
    """A legacy library carries the undeclared duplicate + three redundant indexes.

    ``idx_channels_detected_prefix`` (an orphan, declared nowhere in the ORM),
    ``ix_channels_is_hidden`` (a left-prefix of ``ix_channels_hidden_name``),
    ``ix_channels_language`` (a dead column) and ``ix_channels_is_favorite``
    (D58 — subsumed by ``ix_channels_favorite_hidden_name``, which is gated by
    the identical ``is_favorite = 1`` predicate; found when CI's non-STAT4
    planner chose the standalone index over the composite for the channel
    list's own Favorites query and paid for it with an unnecessary sort) must
    all be gone after the migration, and — because none of the four carries
    ``index=True`` any more — QueryIndexTask's declared-index sweep must not
    recreate them.
    """
    database = Database(f"sqlite:///{tmp_path}/legacy_drops.db")
    database.create_tables()  # builds the current (post-diet) declared shape

    # Simulate the pre-STORAGE-1a state: these four existed on disk even
    # though only three of the names were ever ORM-declared.
    with database.engine.connect() as conn:
        conn.execute(text(
            "CREATE INDEX idx_channels_detected_prefix ON channels (detected_prefix)"
        ))
        conn.execute(text("CREATE INDEX ix_channels_is_hidden ON channels (is_hidden)"))
        conn.execute(text("CREATE INDEX ix_channels_language ON channels (language)"))
        conn.execute(text("CREATE INDEX ix_channels_is_favorite ON channels (is_favorite)"))
        conn.commit()

    database._migrate()
    _run(QueryIndexTask(database))

    with database.engine.connect() as conn:
        names = _index_names(conn, "channels")
    for dropped in (
        "idx_channels_detected_prefix", "ix_channels_is_hidden",
        "ix_channels_language", "ix_channels_is_favorite",
    ):
        assert dropped not in names, f"{dropped} was rebuilt — index=True must be gone"


def test_a_legacy_full_index_is_dropped_and_rebuilt_partial(tmp_path):
    """The core DB-6 trap: a dropped index must not keep ``index=True``.

    Simulates a pre-STORAGE-1a library where ``ix_channels_last_played`` is a
    FULL index (no WHERE clause). ``_migrate()`` must drop it by name so
    QueryIndexTask's sweep — which only fills in a MISSING declared index —
    rebuilds it in the declared PARTIAL shape rather than finding the name
    already present and leaving the old full shape in place.
    """
    database = Database(f"sqlite:///{tmp_path}/legacy_partial.db")
    # create_tables() itself already runs _migrate(), whose DROP INDEX list
    # removes ix_channels_last_played right after create_all() builds it — so
    # by the time this returns, the name is free to recreate in the OLD shape
    # below (exactly what a real pre-STORAGE-1a-upgrade launch does: drop,
    # then QueryIndexTask fills the gap back in on the declared shape).
    database.create_tables()

    # Simulate a pre-STORAGE-1a library: the index exists in its OLD, FULL
    # shape (no WHERE clause) under the declared name.
    with database.engine.connect() as conn:
        conn.execute(text(
            "CREATE INDEX ix_channels_last_played ON channels (last_played)"
        ))
        conn.commit()
        legacy_sql = _index_sql(conn, "ix_channels_last_played")
    assert legacy_sql is not None and "WHERE" not in legacy_sql.upper(), (
        "test setup failed to build a legacy FULL index"
    )

    database._migrate()
    _run(QueryIndexTask(database))

    with database.engine.connect() as conn:
        rebuilt_sql = _index_sql(conn, "ix_channels_last_played")
    assert rebuilt_sql is not None, "the index must be rebuilt, not left dropped"
    assert "WHERE" in rebuilt_sql.upper() and "IS NOT NULL" in rebuilt_sql.upper(), (
        f"rebuilt index is not partial: {rebuilt_sql}"
    )


#: The three busiest conversions named in the STORAGE-1 design pass, re-
#: verified here rather than trusted: a ``col = ?`` equality lookup must
#: still choose the PARTIAL ``col IS NOT NULL`` index, because SQLite's
#: partial-index analysis recognises that the equality implies the WHERE.
_PARTIAL_EQUALITY_COLUMNS = ("last_played", "tmdb_enrich_state", "detected_genre")


def test_partial_indexes_still_serve_an_equality_lookup_on_their_own_column(tmp_path):
    """Re-verifies STORAGE-1's own safety claim on real data, not by citation.

    A ``WHERE col IS NOT NULL`` partial index still serves ``WHERE col = ?``
    — checked here (plan AND result rows) for the three busiest conversions,
    matching the design pass's own probe methodology (EXPLAIN QUERY PLAN,
    identical result set) rather than re-citing its numbers.
    """
    database = Database(f"sqlite:///{tmp_path}/partial_eq.db")
    database.create_tables()
    with database.session_scope() as session:
        for i in range(600):
            session.add(ChannelDB(
                id=f"c{i}", source_id=str(i), provider_id="p",
                name=f"N{i:04d}", media_type="movie", is_hidden=False,
                last_played=(datetime(2024, 1, 1) if i % 25 == 0 else None),
                tmdb_enrich_state=("fetched" if i % 17 == 0 else None),
                detected_genre=("Drama" if i % 11 == 0 else None),
            ))
    _run(QueryIndexTask(database))

    with database.engine.connect() as conn:
        last_played_literal = conn.execute(
            text("SELECT last_played FROM channels WHERE id = 'c0'")
        ).scalar()

    probes = {
        "last_played": f"SELECT id FROM channels WHERE last_played = '{last_played_literal}'",
        "tmdb_enrich_state": "SELECT id FROM channels WHERE tmdb_enrich_state = 'fetched'",
        "detected_genre": "SELECT id FROM channels WHERE detected_genre = 'Drama'",
    }
    for col in _PARTIAL_EQUALITY_COLUMNS:
        sql = probes[col]
        plan = _plan(database, sql)
        assert f"ix_channels_{col}" in plan, f"{col}: partial index not chosen: {plan}"
        with database.engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        assert rows, f"{col}: probe query returned no rows — fixture/probe mismatch"


def test_needs_run_goes_true_again_when_the_catalog_drifts_past_recorded_stats(db):
    """The bug STORAGE-1a fixes: "a stat1 row exists" != "the stats are still true".

    Before this fix, ``needs_run()`` went permanently False the moment
    ANALYZE wrote ONE row for ``channels`` — however wrong — because the old
    check only asked whether a row existed at all (measured on the owner's
    real library: ``ix_channels_is_hidden`` recorded 1,725 rows/key against a
    true 393,162, and had clearly been sitting that wrong for a long time).
    Growing the catalog well past what was recorded, with no re-ANALYZE
    between, must make ``needs_run()`` True again.
    """
    task = QueryIndexTask(db)
    _run(task)
    assert task.needs_run(None) is False

    # 3,000 -> 33,000 rows with no re-ANALYZE: a 10x drift past what was
    # recorded, simulating a catalog that grew between launches.
    with db.session_scope() as session:
        for i in range(3000, 33000):
            session.add(ChannelDB(
                id=f"c{i}", source_id=str(i), provider_id="p",
                name=f"Name {i:05d}", media_type="movie", is_hidden=False,
            ))

    assert task.needs_run(None) is True, (
        "statistics drifted 10x past what ANALYZE recorded and needs_run stayed False"
    )


def test_needs_run_stays_false_for_ordinary_catalog_growth(db):
    """The staleness check must not make every launch re-ANALYZE.

    A drift comfortably inside ``_CHANNEL_STATS_DRIFT_TOLERANCE`` (20%) must
    leave ``needs_run`` False — the fix targets a catalog that has genuinely
    outgrown its statistics, not ordinary noise between launches.
    """
    task = QueryIndexTask(db)
    _run(task)
    assert task.needs_run(None) is False

    with db.session_scope() as session:
        for i in range(3000, 3150):  # +5%, well inside tolerance
            session.add(ChannelDB(
                id=f"c{i}", source_id=str(i), provider_id="p",
                name=f"Name {i:05d}", media_type="movie", is_hidden=False,
            ))

    assert task.needs_run(None) is False, (
        "a 5% catalog change re-triggered ANALYZE — the tolerance is too tight"
    )
