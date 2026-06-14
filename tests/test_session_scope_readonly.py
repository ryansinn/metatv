"""B8-3: session_scope(commit=False) is a read-only scope — no COMMIT, writes discarded.

The async-read seam (_run_query) wraps every query_fn in session_scope. With the default
commit-on-success that meant a pure read still issued a COMMIT. session_scope now takes
commit=False (used by the seam) which never commits and rolls back at exit, so an accidental
write in a read path does not persist.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event

from metatv.core.database import Database, ChannelDB


@pytest.fixture()
def db(tmp_path):
    # File-backed (not :memory:, whose pooled connections each get an empty DB).
    d = Database(f"sqlite:///{tmp_path}/t.db")
    d.create_tables()
    yield d
    d.close()


def _commit_counter(db):
    counts = {"commit": 0, "rollback": 0}

    @event.listens_for(db.engine, "commit")
    def _on_commit(conn):
        counts["commit"] += 1

    @event.listens_for(db.engine, "rollback")
    def _on_rollback(conn):
        counts["rollback"] += 1

    return counts


def test_commit_false_does_not_commit_a_read(db):
    counts = _commit_counter(db)
    with db.session_scope(commit=False) as s:
        s.query(ChannelDB).all()   # a read begins a transaction
    assert counts["commit"] == 0   # but commit=False never COMMITs


def test_commit_true_still_commits(db):
    """Baseline: the default path is unchanged — a successful scope still COMMITs."""
    counts = _commit_counter(db)
    with db.session_scope() as s:
        s.add(ChannelDB(id="a", source_id="a", provider_id="p", name="real", media_type="live"))
    assert counts["commit"] == 1


def test_commit_false_rolls_back_accidental_write(db):
    with db.session_scope(commit=False) as s:
        s.add(ChannelDB(id="ghost", source_id="g", provider_id="p", name="ghost", media_type="live"))
    # The write must not have persisted.
    with db.session_scope() as s:
        assert s.query(ChannelDB).filter_by(id="ghost").first() is None
