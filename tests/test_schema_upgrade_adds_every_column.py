"""Every ORM column must exist after upgrading an OLDER database.

This is the defect this file exists for, and it shipped TWICE in one day:

    sqlite3.OperationalError: no such column: channels.last_seen_at

``create_tables()`` calls ``Base.metadata.create_all()``, which creates missing
TABLES and never adds a column to a table that already exists. A new column
therefore needs an explicit entry in ``Database._migrate()``'s ALTER TABLE list,
and #617 (``signal_verdict``/``signal_dead_streak``/``signal_checked_at``) and
#648 (``last_seen_at``) both shipped without one.

**Why the whole suite stayed green through both.** Every test builds its
database from scratch, where ``create_all`` emits the current schema and the
column exists by construction. The upgrade path — the only path a real user
takes — was never executed. A fresh-database test cannot fail this way no matter
how many of them there are, which is why adding more of those was never going to
catch it.

So this test does the one thing those cannot: it builds a database, **drops the
migrated columns to simulate an older one**, runs the migration, and then issues
a real ORM query. If a future column is added to a model and not to the
migration list, this goes red with the same error the owner saw.

**Widened from one table to every table (SCHEMA-1).** Until then this file
checked ``channels`` alone — the table the two known incidents happened to hit —
so a column added to any of the other sixteen was unguarded by construction.
Widening it turned up **twelve** columns in exactly the #617/#648 state: present
on the model, absent from ``_migrate()``, and absent from the commit that
CREATED their table, so an existing database never gains them.
``providers.max_connections`` (which had a dead, unimportable
``002_add_max_connections.py`` standing in for the entry it never got), five on
``metadata`` (``cast``/``crew``/``trailer_url``/``content_rating``/
``release_date``) and six on ``channels`` (``special_view``/
``event_start_time``/``sport_type``/``league_name``/``team_name``/
``event_metadata`` — all six had been grandfathered into the old frozen list as
"original", which they were not). All twelve are in ``_migrate()`` now.

That is also why ``ORIGINAL_COLUMNS`` below is worth trusting: each table's
frozen set was checked against the columns declared in the revision of
``database.py`` that first named its ``__tablename__``, and after the twelve
entries above they agree exactly. "Any database old enough to lack these never
existed" is now a verified statement rather than an assumption.

**Widened again, from presence to presence-AND-TYPE (GUARD-6).** Everything
above proves a column EXISTS after the upgrade; nothing proves it has the
right TYPE. `create_all()` creating a table from scratch and `_migrate()`
adding one column with `ALTER TABLE ... ADD COLUMN` can only ever agree with
the ORM or be caught by the presence check above — but a table REBUILD (DROP
+ recreate under the same name with a different declared type) is invisible
to a presence-only check: the column is there, under the right name, with the
wrong type. No rebuild exists in this codebase yet, but one is queued and
already designed to do exactly this — **DB-9's `content_tags` integer FK**
rebuilds the table, and its own design pass flagged that it would ship
carrying this exact gap. This extension lands ahead of it on purpose.

`test_upgraded_schema_matches_orm_column_types` (below) reflects the live,
upgraded schema with SQLAlchemy's own `sa.inspect(engine).get_columns(table)`
— never a hand-listed expectation, so a changed type is checked declaratively
against the ORM model the same way the presence check above is — and compares
each column's SQLite column AFFINITY (`INTEGER`/`TEXT`/`REAL`/`NUMERIC`/
`BLOB` — the actual 5-class system SQLite itself resolves a declared type
NAME into, per sqlite.org/datatype3.html: INTEGER if it contains "INT", TEXT
if it contains "CHAR"/"CLOB"/"TEXT", BLOB if it contains "BLOB" or is empty,
REAL if it contains "REAL"/"FLOA"/"DOUB", NUMERIC otherwise) against the
ORM's declared type, compiled through the same dialect and classified by the
same rule. **This is the honest granularity, arrived at empirically, not
assumed:** the first version of this compared SQLAlchemy's own reflected TYPE
CLASS name (`VARCHAR` vs `TEXT`, `BOOLEAN` vs `INTEGER`) and false-failed on
ten real, correct tables — `_migrate()`'s ALTER TABLE list writes bare `TEXT`
for columns the ORM declares `String`/VARCHAR (SQLite has no separate VARCHAR
storage; TEXT and VARCHAR are the SAME affinity) and bare `INTEGER DEFAULT
0/1` for columns the ORM declares `Boolean` (SQLite has no boolean storage
class at all — sqlite.org: "Boolean values are stored as integers 0 and 1").
Both are correct, established, working SQLite convention, not a defect, so
comparing anything finer than affinity — exact SQLAlchemy type class,
`VARCHAR(50)` vs `VARCHAR(255)`, signed-ness — asserts a distinction SQLite
itself does not keep, and would have taught this guard to cry wolf on the
schema as it exists today. The one deliberate widening beyond SQLite's literal
5-rule text: "BOOLEAN" folds into the INTEGER bucket rather than NUMERIC, for
the reason above. **What this deliberately does not cover:** nullable/
default/PRIMARY KEY/index differences between the ORM and the live schema —
SQLite's own `ALTER TABLE ADD COLUMN` cannot express `NOT NULL` without a
default in the first place, so a constraint check would manufacture failures
out of a real SQLite limitation rather than a bug — and extra live columns
not present on the ORM (a column a rebuild forgot to keep, rather than one
that changed shape); presence in that direction is a different failure mode
this file does not claim to guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sqlalchemy as sa

from metatv.core import database
from metatv.core.database import Base, ChannelDB, Database

#: table name -> ORM class, derived from the mappers so it cannot drift.
MODELS = {mapper.class_.__tablename__: mapper.class_ for mapper in Base.registry.mappers}


def _table_columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


#: The columns each table was CREATED with, per table.
#:
#: These need no ALTER entry: any database old enough to lack them never
#: existed. FROZEN, and written out literally rather than computed — a set
#: derived at test time from "the ORM minus the migration list" would absorb
#: every future omission silently, which is the failure this whole file exists
#: to prevent. The correct response to this dict being wrong is almost always
#: to add your column to ``_migrate()``, not to add it here. Editing it says
#: "this shipped in the very first CREATE TABLE", which for anything written
#: after 2026-05 is false.
ORIGINAL_COLUMNS: dict[str, frozenset[str]] = {
    "alert_matches": frozenset({
        "alert_pattern_id", "channel_id", "created_at", "id",
        "is_dismissed", "is_viewed", "matched_at",
    }),
    "alert_patterns": frozenset({
        "applies_to", "created_at", "description", "id", "is_enabled",
        "last_checked", "name", "pattern_type", "pattern_value",
        "updated_at",
    }),
    "channels": frozenset({
        "added_at", "category", "category_id", "cover_url",
        "detected_prefix", "epg_channel_id", "id", "is_favorite",
        "is_hidden", "language", "last_played", "logo_url", "media_type",
        "metadata_id", "name", "play_count", "provider_id", "quality",
        "raw_data", "source_id", "stream_url", "updated_at",
    }),
    "content_tags": frozenset({
        "channel_id", "confidence", "feeders", "id", "source", "tag_id",
    }),
    "downloads": frozenset({
        "channel_id", "channel_name", "created_at", "dest_path",
        "downloaded_bytes", "error", "id", "paused_by_playback", "position",
        "provider_id", "source_url", "state", "total_bytes", "updated_at",
    }),
    "epg_programmes": frozenset({
        "channel_db_id", "channel_epg_id", "description", "id", "is_live",
        "is_new", "provider_id", "start_time", "stop_time", "title",
    }),
    "episodes": frozenset({
        "added_at", "container_extension", "cover_url", "duration",
        "episode_id", "episode_num", "id", "is_watched", "last_played",
        "play_count", "provider_id", "raw_data", "season_id", "season_num",
        "series_id", "series_name", "stream_url", "title", "updated_at",
    }),
    "filters": frozenset({
        "created_at", "description", "id", "is_enabled", "is_global",
        "name", "order", "provider_id", "rules", "updated_at",
    }),
    "metadata": frozenset({
        "actors", "backdrop_url", "director", "fetched_at", "genres", "id",
        "imdb_id", "media_type", "plot", "poster_url", "rating",
        "rating_count", "runtime", "source", "tagline", "title", "tmdb_id",
        "year",
    }),
    "profile": frozenset({
        "key", "updated_at", "value",
    }),
    "providers": frozenset({
        "added_at", "id", "is_active", "last_error", "last_refresh",
        "last_sync", "name", "password", "refresh_schedule",
        "total_categories", "total_channels", "type", "updated_at", "url",
        "urls", "username",
    }),
    "recordings": frozenset({
        "channel_id", "channel_name", "created_at", "dest_path", "error",
        "extend_seconds", "id", "pad_end_seconds", "pad_start_seconds",
        "preempt_playback", "programme_end", "programme_start",
        "programme_title", "provider_id", "recorded_bytes", "source_url",
        "state", "updated_at",
    }),
    "seasons": frozenset({
        "cover_url", "created_at", "episode_count", "id", "name",
        "provider_id", "raw_data", "season_number", "series_id",
        "series_name", "updated_at",
    }),
    "stream_retry": frozenset({
        "attempt_count", "channel_id", "channel_name", "first_failed_at",
        "id", "last_checked_at", "last_error", "next_check_at", "status",
        "stream_url",
    }),
    "tags": frozenset({
        "id", "type", "value",
    }),
    "user_ratings": frozenset({
        "channel_id", "rated_at", "rating",
    }),
    "watch_queue": frozenset({
        "added_at", "channel_id", "id", "position",
    }),
}

#: One entry per ALTER TABLE line: ``(table, column, column_type)``.
_MIGRATION_ENTRY_RE = re.compile(r'\(\s*"(\w+)",\s*"(\w+)",\s*"([^"]+)"\s*\)')


def _migration_entries() -> list[tuple[str, str, str]]:
    """Every ``(table, column, type)`` triple ``Database._migrate()`` applies.

    Read out of the source rather than by running the migration, so a failure
    names the missing ENTRY — which is what the fix is — instead of a symptom
    several layers downstream.
    """
    src = Path(database.__file__).read_text(encoding="utf-8")
    block = src[src.index("migrations = ["):src.index("for table, col, col_type in migrations")]
    return _MIGRATION_ENTRY_RE.findall(block)


def _migrated_columns() -> dict[str, set[str]]:
    """``table -> {column, ...}`` that ``Database._migrate()`` knows how to add."""
    out: dict[str, set[str]] = {}
    for table, col, _type in _migration_entries():
        out.setdefault(table, set()).add(col)
    return out


ORM_TABLES = sorted(Base.metadata.tables)


@pytest.mark.parametrize("table", ORM_TABLES)
def test_every_added_column_has_an_alter_table_entry(table):
    """The invariant, stated where it can be checked cheaply — for EVERY table.

    A column is either in the original schema or in the migration list. Anything
    else means existing databases never gain it, and every ORM query against
    that table raises ``no such column`` — which is exactly what the owner saw,
    twice in one day, from #617 and #648.
    """
    known = ORIGINAL_COLUMNS.get(table, frozenset()) | _migrated_columns().get(table, set())
    orphaned = sorted(c.name for c in Base.metadata.tables[table].columns
                      if c.name not in known)

    assert not orphaned, (
        f"{table}.{orphaned} exist on the model but have no ALTER TABLE entry "
        "in Database._migrate(). create_all() only creates missing TABLES, so "
        "an existing database never gains them and every query naming one "
        f'fails with "no such column". Add ("{table}", "<col>", "<TYPE>") to '
        "the migrations list."
    )


@pytest.mark.parametrize("table", ORM_TABLES)
def test_the_original_column_list_has_not_drifted(table):
    """Non-degeneracy: every frozen name must still describe a real column.

    A stale name here silently shrinks what the test above checks — it would
    keep passing while quietly excusing a column that no longer exists, and the
    next real omission could hide behind it.
    """
    orm = {c.name for c in Base.metadata.tables[table].columns}
    stale = sorted(ORIGINAL_COLUMNS.get(table, frozenset()) - orm)
    assert not stale, f"{table}: listed as original but no longer on the model: {stale}"


def test_every_orm_table_is_frozen():
    """A NEW table must be added to ``ORIGINAL_COLUMNS`` deliberately.

    Without this, ``ORIGINAL_COLUMNS.get(table, frozenset())`` above would treat
    an unlisted table as "nothing is original" — which happens to be strict, so
    it fails loudly — but the reverse mistake (a name here that is no table at
    all) would silently guard nothing. Both directions are asserted so the dict
    and the ORM stay in step.
    """
    orm = set(Base.metadata.tables)
    assert set(ORIGINAL_COLUMNS) == orm, (
        f"tables on the ORM but not frozen: {sorted(orm - set(ORIGINAL_COLUMNS))}; "
        f"frozen but not on the ORM: {sorted(set(ORIGINAL_COLUMNS) - orm)}"
    )


def test_no_column_is_both_original_and_migrated():
    """The two sets must be disjoint, or the freeze is claiming something false.

    A name in both says "this shipped in the first CREATE TABLE" *and* "existing
    databases need it added" — one of those is wrong, and the pair would make
    the orphan check above pass for the wrong reason.
    """
    migrated = _migrated_columns()
    overlap = {t: sorted(ORIGINAL_COLUMNS[t] & migrated.get(t, set()))
               for t in ORIGINAL_COLUMNS
               if ORIGINAL_COLUMNS[t] & migrated.get(t, set())}
    assert not overlap, f"listed as original AND migrated: {overlap}"


def test_every_migration_entry_names_a_real_column():
    """A typo in the list is otherwise invisible.

    ``_migrate()`` swallows ``OperationalError`` (that is how "duplicate column
    name" is made idempotent), so an entry naming a table or column that does
    not exist fails silently forever — and, worse, satisfies the orphan check
    for the column it was *meant* to name only if it is spelled right.
    """
    unknown = []
    for table, col, _type in _migration_entries():
        orm_table = Base.metadata.tables.get(table)
        if orm_table is None or col not in orm_table.columns:
            unknown.append(f"{table}.{col}")
    assert not unknown, f"migration entries naming nothing on the ORM: {unknown}"


def test_every_migration_entry_is_executable_sql(tmp_path):
    """Each entry's ``ALTER TABLE`` must actually parse and run.

    The same swallowed ``OperationalError`` hides a malformed type as
    thoroughly as a missing entry: the column is simply never added, and the
    "no such column" crash lands on the user instead. Every entry is executed
    here against a throwaway table, where nothing is swallowed.
    """
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'probe.db'}")
    entries = _migration_entries()
    assert entries, "parsed no migration entries — the regex has drifted"
    with engine.connect() as conn:
        for table, col, col_type in entries:
            conn.execute(sa.text("DROP TABLE IF EXISTS probe"))
            conn.execute(sa.text("CREATE TABLE probe (placeholder INTEGER)"))
            conn.execute(sa.text(f"ALTER TABLE probe ADD COLUMN {col} {col_type}"))
            assert col in {r[1] for r in conn.execute(sa.text("PRAGMA table_info(probe)"))}, (
                f'("{table}", "{col}", "{col_type}") ran without error but added '
                "no column"
            )
        conn.execute(sa.text("DROP TABLE IF EXISTS probe"))
        conn.commit()


def _drop_indexes_covering(conn, table: str, col: str) -> None:
    """Drop every explicitly-declared index that names *col*.

    **This is the whole reason the old version of this file proved nothing.** It
    tried to drop ``last_seen_at``/``signal_verdict``/``signal_checked_at`` inside
    a bare ``try/except`` — and SQLite refuses ``DROP COLUMN`` on an indexed
    column, so all three refusals were swallowed and the "older database" it
    then upgraded was simply the current schema. All three carry ``index=True``,
    which ``create_all`` honours, so the test could never have failed: it would
    have passed just as well against an EMPTY migrations list.

    ``origin`` distinguishes a ``CREATE INDEX`` (``"c"``) from the autoindexes
    SQLite makes for UNIQUE/PRIMARY KEY (``"u"``/``"pk"``), which cannot be
    dropped — and neither can the column under them, which is why the caller
    still checks what actually came off.
    """
    for row in list(conn.execute(sa.text(f"PRAGMA index_list({table})"))):
        name, origin = row[1], row[3]
        if origin != "c":
            continue
        covered = {r[2] for r in conn.execute(sa.text(f"PRAGMA index_info({name})"))}
        if col in covered:
            conn.execute(sa.text(f'DROP INDEX IF EXISTS "{name}"'))


def _simulate_older_database(db: Database, table: str, columns: set[str]) -> set[str]:
    """Drop what ``_migrate()`` adds, so *table* looks like an older schema.

    Returns:
        The columns actually dropped — never assume it is all of them, and never
        proceed on an empty set.
    """
    dropped = set()
    for col in sorted(columns):
        with db.engine.connect() as conn:
            try:
                _drop_indexes_covering(conn, table, col)
                conn.execute(sa.text(f'ALTER TABLE {table} DROP COLUMN "{col}"'))
                conn.commit()
                dropped.add(col)
            except Exception:
                conn.rollback()
    return dropped


@pytest.mark.parametrize("table", sorted(_migrated_columns()))
def test_a_real_query_runs_after_the_upgrade(tmp_path, table):
    """End to end, through the ORM — the shape the owner actually hit.

    The column check above is the precise diagnosis; this is the symptom. A
    query naming every column is what broke, so the guard issues one — for
    every table ``_migrate()`` touches, not just ``channels``.
    """
    url = f"sqlite:///{tmp_path / f'up_{table}.db'}"
    db = Database(url)
    db.create_tables()

    migrated = _migrated_columns()[table]
    dropped = _simulate_older_database(db, table, migrated)
    assert dropped, (
        f"could not drop any of {table}'s {len(migrated)} migrated columns, so "
        "this never simulated an older database — the test would pass on a "
        "completely empty migrations list"
    )

    Database(url).create_tables()  # the upgrade path

    present = _table_columns(db.engine, table)
    missing = sorted(c.name for c in Base.metadata.tables[table].columns
                     if c.name not in present)
    assert not missing, (
        f"{table}: {missing} were dropped and the upgrade did not put them back"
    )

    with db.session_scope(commit=False) as session:
        session.query(MODELS[table]).all()


def test_the_channels_upgrade_survives_a_filtered_query(tmp_path):
    """The original incident's exact shape, kept as its own named case.

    ``no such column: channels.last_seen_at`` came out of a real filtered query
    on the owner's library, not a bare SELECT — so one stays here naming a
    column and a predicate.
    """
    url = f"sqlite:///{tmp_path / 'up.db'}"
    db = Database(url)
    db.create_tables()
    dropped = _simulate_older_database(
        db, "channels", {"last_seen_at", "signal_verdict", "signal_checked_at"})
    assert dropped == {"last_seen_at", "signal_verdict", "signal_checked_at"}

    Database(url).create_tables()

    with db.session_scope(commit=False) as session:
        session.query(ChannelDB).filter(
            ChannelDB.is_favorite == True,  # noqa: E712
            ChannelDB.last_seen_at.is_(None),
        ).all()


def test_every_table_the_orm_declares_actually_exists(tmp_path):
    """The sibling failure: a NEW table is created by create_all, so it is safe —
    but only while it is genuinely new. Asserted so the assumption is checked."""
    db = Database(f"sqlite:///{tmp_path / 'tables.db'}")
    db.create_tables()
    with db.engine.connect() as conn:
        present = {r[0] for r in conn.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}
    missing = [t for t in Base.metadata.tables if t not in present]
    assert not missing, f"declared but never created: {missing}"


def test_database_py_declares_no_index_by_hand():
    """DB-6's index sibling: one source of truth, same spirit as the ALTER
    TABLE guard above.

    Indexes are no longer hand-listed in ``Database._migrate()`` — the full
    set is derived from ``Base.metadata`` by
    ``QueryIndexTask`` (``metatv/core/migrations/query_indexes.py``), which is
    what makes a newly ``index=True``'d column reach an existing library
    automatically. A ``CREATE INDEX`` literal reappearing here would mean a
    second, hand-maintained mechanism has grown back beside the generated one
    — exactly the kind of enumeration this project keeps finding drifts.

    Dropping an index is policy, not a declaration (``ix_content_tags_*``
    stays hand-written on purpose), so this guards ``CREATE INDEX`` only.
    """
    src = Path(database.__file__).read_text(encoding="utf-8")
    assert "CREATE INDEX" not in src, (
        "found a hand-written CREATE INDEX in database.py — indexes are "
        "declared on the ORM model and built by QueryIndexTask, never by a "
        "literal SQL string here."
    )


# ---------------------------------------------------------------------------
# GUARD-6: column TYPE, not just presence — the table-rebuild blind spot.
# ---------------------------------------------------------------------------

def _sqlite_affinity(type_repr: str) -> str:
    """SQLite's own column-affinity bucket for a declared/reflected type NAME.

    Implements the rules at sqlite.org/datatype3.html, checked in the order
    SQLite specifies: INTEGER if the name contains "INT"; TEXT if it contains
    "CHAR"/"CLOB"/"TEXT" (this is what makes VARCHAR and TEXT the SAME
    affinity — SQLite has no separate VARCHAR storage class); BLOB if it
    contains "BLOB" or is empty; REAL if it contains "REAL"/"FLOA"/"DOUB";
    NUMERIC otherwise.

    One deliberate widening past the literal SQLite text (see module
    docstring for why): "BOOLEAN" is folded into the INTEGER bucket rather
    than left in NUMERIC, since SQLite stores every boolean as the integer 0
    or 1 and this codebase's own migrations already declare boolean columns
    as literal ``INTEGER DEFAULT 0/1``.
    """
    name = type_repr.upper()
    if "INT" in name or "BOOL" in name:
        return "INTEGER"
    if "CHAR" in name or "CLOB" in name or "TEXT" in name:
        return "TEXT"
    if "BLOB" in name or not name:
        return "BLOB"
    if "REAL" in name or "FLOA" in name or "DOUB" in name:
        return "REAL"
    return "NUMERIC"


def _orm_column_type_classes(dialect, table: str) -> dict[str, str]:
    """``{column_name: affinity}`` as the ORM model declares it, compiled
    through *dialect* — so a custom type (e.g. ``JSONEncoded``, whose ``impl``
    is ``Text``) resolves to the DDL it actually emits, not its Python class
    name."""
    return {
        col.name: _sqlite_affinity(str(col.type.compile(dialect=dialect)))
        for col in Base.metadata.tables[table].columns
    }


def _reflected_column_type_classes(engine, table: str) -> dict[str, str]:
    """``{column_name: affinity}`` as SQLAlchemy's own reflection reads off
    the LIVE table — ``sa.inspect(engine).get_columns(...)``, never a
    hand-listed expectation, so this stays declarative the same way the
    presence check above does."""
    return {
        c["name"]: _sqlite_affinity(type(c["type"]).__name__)
        for c in sa.inspect(engine).get_columns(table)
    }


@pytest.mark.parametrize("table", ORM_TABLES)
def test_upgraded_schema_matches_orm_column_types(tmp_path, table):
    """After the real upgrade path, the live schema must match ``Base.metadata``
    on BOTH column presence and SQLite column AFFINITY — not presence alone.

    Presence alone is what ``test_a_real_query_runs_after_the_upgrade`` and
    ``test_every_added_column_has_an_alter_table_entry`` already prove; both are
    blind to a column that exists under the right name with the WRONG type,
    which only a table REBUILD can produce (an ``ALTER TABLE ADD COLUMN`` can't
    misdeclare an existing column's type — it can only add a new one). Runs for
    every ORM table, not only the ones ``_migrate()`` touches, so a table with
    zero migrated columns is still checked against a fresh ``create_all()`` —
    the same round-trip DB-9's rebuilt ``content_tags`` would go through.
    """
    url = f"sqlite:///{tmp_path / f'typecheck_{table}.db'}"
    db = Database(url)
    db.create_tables()

    migrated = _migrated_columns().get(table, set())
    if migrated:
        dropped = _simulate_older_database(db, table, migrated)
        assert dropped, (
            f"could not drop any of {table}'s {len(migrated)} migrated columns, "
            "so this never simulated an older database"
        )
        Database(url).create_tables()  # the upgrade path

    engine = db.engine
    orm_types = _orm_column_type_classes(engine.dialect, table)
    live_types = _reflected_column_type_classes(engine, table)

    missing = sorted(set(orm_types) - set(live_types))
    assert not missing, (
        f"{table}: {missing} present on the model but absent from the live "
        "table after the upgrade path"
    )

    mismatched = sorted(
        (name, orm_types[name], live_types[name])
        for name in orm_types
        if live_types[name] != orm_types[name]
    )
    assert not mismatched, (
        f"{table}: column affinity disagrees between the ORM model and the "
        f"live upgraded schema, as (name, orm_affinity, live_affinity): "
        f"{mismatched}. A column existing under the right name is not enough "
        "— this is exactly what a table REBUILD (DROP + recreate with a "
        "different declared type) breaks and a presence-only check cannot see."
    )


def test_type_class_helper_is_censusing_every_table():
    """A runner that ran nothing exits 0: if ``ORM_TABLES`` or the type-class
    helpers silently produced empty dicts for every table, the parametrized
    test above would pass vacuously. Pin that today's schema gives every
    table at least one column, so a real regression in the helpers themselves
    cannot hide behind zero collected assertions."""
    assert ORM_TABLES, "censused zero tables — Base.metadata.tables is empty"
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    empty_tables = [
        t for t in ORM_TABLES
        if not _orm_column_type_classes(engine.dialect, t)
        or not _reflected_column_type_classes(engine, t)
    ]
    assert not empty_tables, (
        f"these tables censused zero columns on either side: {empty_tables} "
        "— the type-class helpers broke, not the schema"
    )


def test_type_mismatch_detection_fires_on_a_db9_shaped_rebuild(tmp_path):
    """Proof this guard actually distinguishes match from mismatch.

    No table rebuild exists yet in this codebase to exercise (that is the
    whole point — this lands ahead of DB-9), so this produces the shape by
    hand: drop and recreate ``episodes`` with ``series_id`` as ``INTEGER``
    instead of the ORM's declared ``VARCHAR`` (TEXT affinity) — the exact
    kind of change a DROP + recreate rebuild can make and an
    ``ALTER TABLE ADD COLUMN`` cannot. Asserts the SAME comparison
    ``test_upgraded_schema_matches_orm_column_types`` uses catches it, so
    that test is not merely passing because nothing it checks can ever fail.
    """
    url = f"sqlite:///{tmp_path / 'db9_shaped_rebuild.db'}"
    db = Database(url)
    db.create_tables()
    engine = db.engine
    with engine.connect() as conn:
        conn.execute(sa.text("DROP TABLE episodes"))
        conn.execute(sa.text(
            "CREATE TABLE episodes (id VARCHAR PRIMARY KEY, series_id INTEGER)"
        ))
        conn.commit()

    orm_types = _orm_column_type_classes(engine.dialect, "episodes")
    live_types = _reflected_column_type_classes(engine, "episodes")

    assert orm_types["series_id"] == "TEXT", (
        "sanity: the ORM must still declare series_id as a TEXT-affinity "
        "type (VARCHAR), or this proof is not testing what it claims to"
    )
    assert live_types["series_id"] == "INTEGER", (
        "sanity: the rebuild above must actually have landed as INTEGER"
    )
    assert live_types["series_id"] != orm_types["series_id"], (
        "the comparison must flag episodes.series_id after a rebuild changed "
        f"its affinity to INTEGER (ORM still declares {orm_types['series_id']!r}) "
        "— if this passes, the guard test above would too, on a real bug"
    )


def test_type_classes_agree_on_a_column_untouched_by_the_rebuild(tmp_path):
    """The mismatch proof above must not be a blanket failure — a column the
    rebuild left alone (``id``) must still compare equal, or the detector is
    just reporting every column as mismatched regardless of content."""
    url = f"sqlite:///{tmp_path / 'db9_shaped_rebuild_control.db'}"
    db = Database(url)
    db.create_tables()
    engine = db.engine
    with engine.connect() as conn:
        conn.execute(sa.text("DROP TABLE episodes"))
        conn.execute(sa.text(
            "CREATE TABLE episodes (id VARCHAR PRIMARY KEY, series_id INTEGER)"
        ))
        conn.commit()

    orm_types = _orm_column_type_classes(engine.dialect, "episodes")
    live_types = _reflected_column_type_classes(engine, "episodes")
    assert live_types["id"] == orm_types["id"] == "TEXT"
