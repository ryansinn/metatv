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
recently-added columns to simulate an older one**, runs the migration, and then
issues a real ORM query. If a future column is added to a model and not to the
migration list, this goes red with the same error the owner saw.
"""

from __future__ import annotations

import re
from pathlib import Path

import sqlalchemy as sa

from metatv.core import database
from metatv.core.database import Base, ChannelDB, Database


def _orm_columns(model) -> list[str]:
    return [c.name for c in model.__table__.columns]


def _table_columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


#: The ``channels`` columns that were in the ORIGINAL ``CREATE TABLE``.
#:
#: These need no ALTER entry: any database old enough to lack them never
#: existed. FROZEN — the correct response to this list being wrong is almost
#: always to add your column to ``_migrate()``, not to add it here. Editing it
#: says "this shipped in the very first schema", which for anything written
#: after 2026 is false.
ORIGINAL_CHANNELS_COLUMNS = frozenset({
    "added_at", "category", "category_id", "cover_url", "detected_prefix",
    "epg_channel_id", "event_metadata", "event_start_time", "id", "is_favorite",
    "is_hidden", "language", "last_played", "league_name", "logo_url",
    "media_type", "metadata_id", "name", "play_count", "provider_id", "quality",
    "raw_data", "source_id", "special_view", "sport_type", "stream_url",
    "team_name", "updated_at",
})


def _migrated_channels_columns() -> set[str]:
    """The ``channels`` columns ``Database._migrate()`` knows how to add.

    Read out of the source rather than by running the migration, so the failure
    names the missing ENTRY — which is what the fix is — instead of a symptom
    several layers downstream.
    """
    src = Path(database.__file__).read_text(encoding="utf-8")
    block = src[src.index("migrations = ["):src.index("for table, col, col_type in migrations")]
    return set(re.findall(r'\(\s*"channels",\s*"(\w+)"', block))


def test_every_added_column_has_an_alter_table_entry():
    """The invariant, stated where it can be checked cheaply.

    A column is either in the original schema or in the migration list. Anything
    else means existing databases never gain it, and every ORM query against
    that table raises ``no such column`` — which is exactly what the owner saw,
    twice in one day, from #617 and #648.
    """
    known = ORIGINAL_CHANNELS_COLUMNS | _migrated_channels_columns()
    orphaned = [c.name for c in ChannelDB.__table__.columns if c.name not in known]

    assert not orphaned, (
        f"{orphaned} exist on ChannelDB but have no ALTER TABLE entry in "
        "Database._migrate(). create_all() only creates missing TABLES, so an "
        "existing database never gains them and every query naming one fails "
        "with 'no such column'. Add them to the migrations list."
    )


def test_the_original_column_list_has_not_drifted():
    """Non-degeneracy: the frozen list must still describe real columns.

    A stale name here silently shrinks what the test above checks — it would
    keep passing while quietly excusing a column that no longer exists, and the
    next real omission could hide behind it.
    """
    orm = {c.name for c in ChannelDB.__table__.columns}
    stale = sorted(ORIGINAL_CHANNELS_COLUMNS - orm)
    assert not stale, f"listed as original but no longer on the model: {stale}"


def test_a_real_query_runs_after_the_upgrade(tmp_path):
    """End to end, through the ORM — the shape the owner actually hit.

    The column check above is the precise diagnosis; this is the symptom. A
    query naming every column is what broke, so the guard issues one.
    """
    db = Database(f"sqlite:///{tmp_path / 'up.db'}")
    db.create_tables()
    with db.engine.connect() as conn:
        for col in ("last_seen_at", "signal_verdict", "signal_checked_at"):
            try:
                conn.execute(sa.text(f"ALTER TABLE channels DROP COLUMN {col}"))
                conn.commit()
            except Exception:
                conn.rollback()

    Database(f"sqlite:///{tmp_path / 'up.db'}").create_tables()

    with db.session_scope(commit=False) as session:
        session.query(ChannelDB).filter(ChannelDB.is_favorite == True).all()  # noqa: E712


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
