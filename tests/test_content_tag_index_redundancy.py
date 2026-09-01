"""The two content_tags indexes that bought nothing.

`ix_content_tags_channel_id` is a strict left-prefix of the
`UNIQUE(channel_id, tag_id, source)` autoindex SQLite creates regardless.
`ix_content_tags_tag_id` is a strict left-prefix of
`ix_content_tags_tag_channel`. Together they cost **221 MB** on the owner's
3.1-million-row table and served no query shape the wider indexes did not.

Three independent auditors reached that separately. This pins it, because the
declaration that recreates them is one `index=True` away and nothing else would
notice for another 221 MB.

The last test is the one that matters: dropping an index is only safe if the
queries that used it still resolve to an index. It asserts the PLAN, not the
result — a query returning correct rows via a full scan passes any test that
only checks output.
"""

from __future__ import annotations

import sqlite3

import pytest

from metatv.core.database import Database

REDUNDANT = ("ix_content_tags_channel_id", "ix_content_tags_tag_id")
REQUIRED = ("ix_content_tags_tag_channel", "sqlite_autoindex_content_tags_1")


def _indexes(path) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='content_tags'")}
    finally:
        con.close()


@pytest.fixture
def fresh(tmp_path):
    """A brand-new database — a real file, never :memory: for session work."""
    path = tmp_path / "fresh.db"
    Database(f"sqlite:///{path}").create_tables()
    return path


def test_a_new_database_does_not_create_the_redundant_indexes(fresh):
    """Guards the `index=True` that would silently bring them back."""
    have = _indexes(fresh)
    assert not (have & set(REDUNDANT)), (
        f"a redundant index was recreated: {sorted(have & set(REDUNDANT))}")


def test_the_indexes_that_do_the_work_still_exist(fresh):
    """The other half of the claim. Dropping the wrong two would also pass above."""
    have = _indexes(fresh)
    for name in REQUIRED:
        assert name in have, f"{name} is missing — the drop went too far"


def test_an_existing_database_has_them_dropped(tmp_path):
    """The model change alone only helps a database created from scratch.

    The owner's database already has both, which is where the 221 MB is.
    """
    path = tmp_path / "legacy.db"
    Database(f"sqlite:///{path}").create_tables()
    con = sqlite3.connect(path)
    for name, cols in (("ix_content_tags_channel_id", "channel_id"),
                       ("ix_content_tags_tag_id", "tag_id")):
        con.execute(f"CREATE INDEX IF NOT EXISTS {name} ON content_tags ({cols})")
    con.commit()
    con.close()
    assert set(REDUNDANT) <= _indexes(path), "test setup failed to create them"

    Database(f"sqlite:///{path}").create_tables()      # re-open runs _migrate()

    remaining = _indexes(path)
    assert not (remaining & set(REDUNDANT)), (
        f"the migration left {sorted(remaining & set(REDUNDANT))} behind")
    for name in REQUIRED:
        assert name in remaining


@pytest.mark.parametrize("label,sql", [
    ("tags_for(channel)",
     "SELECT id, tag_id, source FROM content_tags WHERE channel_id = 'p_7'"),
    ("channels_for_tag",
     "SELECT channel_id FROM content_tags WHERE tag_id = 1"),
])
def test_the_real_query_shapes_still_use_an_index(fresh, label, sql):
    """Assert the PLAN, not the rows.

    A query that returns the right answer by scanning 3.1 million rows passes
    any test that only checks its output. This is the assertion that would fail
    if the drop had removed something load-bearing.
    """
    con = sqlite3.connect(fresh)
    try:
        con.execute("INSERT INTO tags (id, type, value) VALUES (1,'genre','action')")
        con.executemany(
            "INSERT INTO content_tags (channel_id, tag_id, source) VALUES (?,?,?)",
            [(f"p_{i}", 1, "generated") for i in range(500)])
        con.commit()
        plan = " ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql))
    finally:
        con.close()

    assert "USING" in plan and "INDEX" in plan, (
        f"{label} degraded to a table scan after the drop: {plan}")
