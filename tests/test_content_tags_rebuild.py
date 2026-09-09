"""DB-9: the three behaviors the design pass named as load-bearing.

``core/migrations/content_tags_rebuild.py`` replaces ``content_tags.channel_id``
(a 43-byte string) with an integer ``channel_key`` FK — a full table rebuild
(CREATE + INSERT...SELECT + DROP + RENAME), not an ``ALTER TABLE ADD COLUMN``,
run synchronously inside ``Database._migrate()``. Three things must hold for
that to be safe on a real 3M-row library:

1. The rebuild is ATOMIC — an interrupted rebuild must leave the ORIGINAL
   ``content_tags`` completely untouched and usable (never a half-migrated
   table), because a crash mid-rebuild is retried, not resumed, next launch.
2. Tag sets survive the rebuild exactly — every ``(channel, tag)`` pair
   present before must still be present after, just addressed by the new key.
3. The ``channels_assign_channel_key`` AFTER INSERT trigger must actually fire
   for every channel-insert path, or a channel silently never gets a
   ``channel_key`` and its tags can never be written (the design pass's
   Risk #1) — including the bulk-insert path a real provider refresh uses.

Real ``Database`` on a ``tmp_path`` FILE throughout — never ``:memory:``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.engine.base import Connection

from metatv.core.database import ChannelDB, Database, TagDB
from metatv.core.migrations import content_tags_rebuild as rebuild_mod


def _build_old_shaped_db(path: Path) -> Database:
    """A real DB, migrated once (so channels.channel_key + its trigger exist),
    then content_tags forced back to the pre-DB-9 shape — the state every real
    upgrading user's database is actually in."""
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    with db.engine.connect() as conn:
        conn.execute(sa.text("DROP TABLE content_tags"))
        conn.execute(sa.text(
            "CREATE TABLE content_tags ("
            "id INTEGER PRIMARY KEY, channel_id VARCHAR NOT NULL, "
            "tag_id INTEGER NOT NULL, source VARCHAR NOT NULL DEFAULT 'generated', "
            "feeders TEXT, confidence FLOAT, "
            "UNIQUE (channel_id, tag_id, source))"
        ))
        conn.execute(sa.text(
            "CREATE INDEX ix_content_tags_tag_channel ON content_tags (tag_id, channel_id)"
        ))
        conn.commit()
    return db


def _seed_channels_and_tags(db: Database, n_channels: int) -> None:
    with db.session_scope() as session:
        for i in range(n_channels):
            session.add(ChannelDB(id=f"p_{i}", source_id="s", provider_id="p",
                                  name=f"Channel {i}", media_type="movie"))
        session.add(TagDB(id=1, type="genre", value="Drama"))
        session.add(TagDB(id=2, type="genre", value="Comedy"))
    with db.engine.connect() as conn:
        rows = [
            {"cid": f"p_{i}", "tid": tid, "src": "generated",
             "feeders": '["name_parse"]' if tid == 1 else '["genre"]'}
            for i in range(n_channels) for tid in (1, 2) if (i + tid) % 2 == 0
        ]
        conn.execute(sa.text(
            "INSERT INTO content_tags (channel_id, tag_id, source, feeders) "
            "VALUES (:cid, :tid, :src, :feeders)"
        ), rows)
        conn.commit()


# ---------------------------------------------------------------------------
# 1. Atomicity
# ---------------------------------------------------------------------------

def test_an_interrupted_rebuild_leaves_the_original_table_intact(tmp_path):
    """A crash mid-transaction must not leave a half-migrated content_tags.

    Patches ``Connection.exec_driver_sql`` to fail on the ``INSERT ...
    SELECT`` step (after CREATE TABLE content_tags_new has already run inside
    the same BEGIN IMMEDIATE), simulating a real interruption. The whole
    transaction must roll back: the ORIGINAL string-``channel_id`` table must
    still exist, still hold its data, and ``content_tags_new`` must not exist.
    """
    path = tmp_path / "interrupted.db"
    db = _build_old_shaped_db(path)
    _seed_channels_and_tags(db, n_channels=5)

    real = Connection.exec_driver_sql

    def _boom(self, statement, *args, **kwargs):
        if statement.strip().startswith("INSERT INTO content_tags_new"):
            raise sa.exc.OperationalError("boom", None, RuntimeError("simulated crash"))
        return real(self, statement, *args, **kwargs)

    with patch.object(Connection, "exec_driver_sql", _boom):
        rebuild_mod.rebuild_content_tags_int_key(db.engine)  # must not raise

    with db.engine.connect() as conn:
        cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(content_tags)"))}
        tables = {r[0] for r in conn.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}
        row_count = conn.execute(sa.text("SELECT COUNT(*) FROM content_tags")).scalar()

    assert "channel_id" in cols, "the original column must still be there"
    assert "channel_key" not in cols, "a half-migrated table would carry both"
    assert "content_tags_new" not in tables, "the scratch table must not survive a rollback"
    assert row_count == 5, "the original rows must be untouched"

    # And the guard fires again next launch instead of getting stuck.
    with db.engine.connect() as conn:
        cols_again = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(content_tags)"))}
    assert "channel_id" in cols_again


def test_a_retry_after_the_interruption_succeeds(tmp_path):
    """The self-healing half of atomicity: next launch's retry finishes the job."""
    path = tmp_path / "retry.db"
    db = _build_old_shaped_db(path)
    _seed_channels_and_tags(db, n_channels=5)

    real = Connection.exec_driver_sql
    calls = {"n": 0}

    def _boom_once(self, statement, *args, **kwargs):
        if statement.strip().startswith("INSERT INTO content_tags_new") and calls["n"] == 0:
            calls["n"] += 1
            raise sa.exc.OperationalError("boom", None, RuntimeError("simulated crash"))
        return real(self, statement, *args, **kwargs)

    with patch.object(Connection, "exec_driver_sql", _boom_once):
        rebuild_mod.rebuild_content_tags_int_key(db.engine)  # fails, rolls back

    rebuild_mod.rebuild_content_tags_int_key(db.engine)  # the retry: no patch, must succeed

    with db.engine.connect() as conn:
        cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(content_tags)"))}
    assert cols == {"channel_key", "tag_id", "source", "feeders"}


# ---------------------------------------------------------------------------
# 2. Tag-set fidelity
# ---------------------------------------------------------------------------

def test_tag_sets_are_identical_before_and_after(tmp_path):
    """Every (channel, tag) pair present before the rebuild is present after —
    addressed by channel_key instead of channel_id, nothing gained or lost."""
    path = tmp_path / "fidelity.db"
    db = _build_old_shaped_db(path)
    _seed_channels_and_tags(db, n_channels=12)

    with db.engine.connect() as conn:
        before = {
            (cid, tid) for cid, tid in conn.execute(
                sa.text("SELECT channel_id, tag_id FROM content_tags")
            )
        }
    assert before, "test setup produced no rows to migrate"

    Database(f"sqlite:///{path}").create_tables()  # the real upgrade path

    with db.engine.connect() as conn:
        after = {
            (cid, tid) for cid, tid in conn.execute(sa.text(
                "SELECT c.id, ct.tag_id FROM content_tags ct "
                "JOIN channels c ON c.channel_key = ct.channel_key"
            ))
        }

    assert after == before, (
        f"tag set changed across the rebuild: lost={before - after} "
        f"gained={after - before}"
    )


def test_feeders_survive_the_rebuild_too(tmp_path):
    """Not just the (channel, tag) pair — the feeders list riding on it."""
    path = tmp_path / "feeders.db"
    db = _build_old_shaped_db(path)
    _seed_channels_and_tags(db, n_channels=4)

    with db.engine.connect() as conn:
        before_feeders = sorted(
            (cid, tid, feeders) for cid, tid, feeders in conn.execute(
                sa.text("SELECT channel_id, tag_id, feeders FROM content_tags")
            )
        )

    Database(f"sqlite:///{path}").create_tables()

    with db.engine.connect() as conn:
        after_feeders = sorted(
            (c_id, tid, feeders) for c_id, tid, feeders in conn.execute(sa.text(
                "SELECT c.id, ct.tag_id, ct.feeders FROM content_tags ct "
                "JOIN channels c ON c.channel_key = ct.channel_key"
            ))
        )

    assert after_feeders == before_feeders


# ---------------------------------------------------------------------------
# 3. The channel_key trigger — silent tag loss prevention
# ---------------------------------------------------------------------------

def test_a_single_orm_insert_gets_a_channel_key(tmp_path):
    """The base case: session.add(ChannelDB(...)) must populate channel_key."""
    db = Database(f"sqlite:///{tmp_path / 'single.db'}")
    db.create_tables()
    with db.session_scope() as session:
        session.add(ChannelDB(id="p_1", source_id="s", provider_id="p",
                              name="Test", media_type="movie"))
    with db.session_scope(commit=False) as session:
        channel = session.query(ChannelDB).filter_by(id="p_1").one()
        assert channel.channel_key is not None


def test_a_bulk_insert_gives_every_channel_a_distinct_key(tmp_path):
    """The path a real provider refresh actually uses: many rows in one flush.

    The trigger recomputes MAX(channel_key)+1 per row, so this is the case
    that would silently collide or leave NULLs if it only worked for a single
    row at a time.
    """
    db = Database(f"sqlite:///{tmp_path / 'bulk.db'}")
    db.create_tables()
    with db.session_scope() as session:
        for i in range(50):
            session.add(ChannelDB(id=f"p_{i}", source_id="s", provider_id="p",
                                  name=f"Channel {i}", media_type="movie"))
    with db.session_scope(commit=False) as session:
        keys = [c.channel_key for c in session.query(ChannelDB).all()]
    assert all(k is not None for k in keys), "at least one channel got no channel_key"
    assert len(set(keys)) == len(keys), f"channel_key collided: {keys}"


def test_a_channel_inserted_after_the_rebuild_can_still_be_tagged(tmp_path):
    """End to end: the exact silent-loss scenario the trigger exists to close.

    Without the trigger (or with one that only ran on a fresh install), a
    channel added on an UPGRADED database would get a NULL channel_key and
    every attempt to tag it would fail the NOT NULL FK — silently, since
    ``set_content_tags`` treats "no channel_key" as "channel not found yet"
    and simply skips (see ``TagRepository._channel_key``).
    """
    path = tmp_path / "post_upgrade.db"
    db = _build_old_shaped_db(path)
    _seed_channels_and_tags(db, n_channels=2)

    db2 = Database(f"sqlite:///{path}")  # the upgrade path
    db2.create_tables()

    with db2.session_scope() as session:
        session.add(ChannelDB(id="new_channel", source_id="s", provider_id="p",
                              name="New", media_type="movie"))

    from metatv.core.repositories.tag import TagRepository, _clear_tag_cache
    _clear_tag_cache()
    with db2.session_scope() as session:
        TagRepository(session).set_content_tags(
            "new_channel", [("genre", "Drama", "name_parse")], source="generated")

    with db2.session_scope(commit=False) as session:
        tags = TagRepository(session).tags_for("new_channel")
    assert tags == [("genre", "Drama")], (
        "a channel added after the upgrade could not be tagged — the "
        "channel_key trigger did not fire for it"
    )
