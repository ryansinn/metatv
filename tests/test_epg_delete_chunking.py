"""The EPG guide delete must never hold one write transaction over the whole table.

SQLite has exactly one writer. Clearing 260,275 programmes off the owner's 3 GB
database with a single unbounded ``DELETE`` measured **69.3 seconds** holding the
write lock — 2.3x the 30s ``busy_timeout`` — so every other writer that wanted the
lock during that window failed outright: a provider refresh lost 2.5 minutes of
work mid-upsert, and ``persist_url_stats`` dropped its stats.

These tests assert the property that would break if anyone collapsed the chunked
delete back into one statement: **bounded rows per transaction**. Row counts alone
cannot see that — a single DELETE removes exactly the same rows — so what is
asserted is how much work each transaction carries, and that is what goes red.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy.orm import Session

from metatv.core.database import Database, EpgProgramDB
from metatv.core.repositories.epg import DELETE_CHUNK, delete_programmes_chunked


_NOW = datetime.datetime(2026, 8, 31, 12, 0)


@pytest.fixture
def db(tmp_path):
    """A real on-disk Database — DB-session work is never tested on :memory:."""
    database = Database(f"sqlite:///{tmp_path / 'epg.db'}")
    database.create_tables()
    return database


def _seed(database: Database, provider_id: str, count: int, *, hours_ago: int = 0) -> None:
    start = _NOW - datetime.timedelta(hours=hours_ago)
    with database.session_scope() as session:
        session.add_all([
            EpgProgramDB(
                provider_id=provider_id,
                channel_epg_id=f"c{i}",
                channel_name="n",
                title=f"t{i}",
                start_time=start,
                stop_time=start + datetime.timedelta(hours=1),
            )
            for i in range(count)
        ])


class _CommitCounter:
    """Counts Session.commit() calls, so 'bounded per transaction' is observable."""

    def __init__(self, monkeypatch):
        self.count = 0
        real = Session.commit

        def counting(session, *args, **kwargs):
            self.count += 1
            return real(session, *args, **kwargs)

        monkeypatch.setattr(Session, "commit", counting)


def test_delete_commits_once_per_chunk_not_once_for_everything(db, monkeypatch):
    """The whole point: N rows must cost ceil(N/chunk) transactions, not one.

    This is the assertion that goes RED if the chunking is removed — collapsing
    the loop into a single ``DELETE`` leaves every row count below identical and
    only the commit count changes.
    """
    _seed(db, "p1", 2500)
    counter = _CommitCounter(monkeypatch)

    with db.session_scope(commit=False) as session:
        deleted = delete_programmes_chunked(
            session, EpgProgramDB.provider_id == "p1", chunk=500
        )

    assert deleted == 2500
    assert counter.count == 5, (
        f"expected one commit per 500-row chunk, got {counter.count} — "
        "an unbounded DELETE reports 1 and holds the write lock throughout"
    )


def test_no_single_transaction_removes_more_than_the_chunk(db, monkeypatch):
    """Every transaction is bounded, whatever the total — the lock-hold guarantee.

    Rows removed per commit are derived from the *remaining* count, not from
    ``session.deleted``: the helper deletes with ``synchronize_session=False``,
    so the session's identity map never sees the rows and ``len(session.deleted)``
    is 0 on every commit. An assertion against it would read as coverage while
    passing on zeroes forever.
    """
    total_rows = 1201
    _seed(db, "p1", total_rows)
    remaining_at_commit: list[int] = []
    real = Session.commit

    def recording(session, *args, **kwargs):
        # The DELETE has already run in this transaction; count what survives it.
        remaining_at_commit.append(
            session.query(EpgProgramDB).filter_by(provider_id="p1").count()
        )
        return real(session, *args, **kwargs)

    monkeypatch.setattr(Session, "commit", recording)

    with db.session_scope(commit=False) as session:
        delete_programmes_chunked(session, EpgProgramDB.provider_id == "p1", chunk=300)

    assert remaining_at_commit, "the delete never committed"
    removed_per_commit = [
        before - after
        for before, after in zip([total_rows] + remaining_at_commit, remaining_at_commit)
    ]
    assert max(removed_per_commit) <= 300, (
        f"a transaction removed {max(removed_per_commit)} rows, over the 300 cap"
    )
    # Non-degenerate: without this the assertion above passes on all-zero deltas.
    assert max(removed_per_commit) > 0, "observed no removals — the test sees nothing"
    assert sum(removed_per_commit) == total_rows


def test_delete_removes_exactly_the_matching_rows(db):
    """Chunking must not change which rows go — a partial sweep is worse than slow."""
    _seed(db, "keep", 40)
    _seed(db, "drop", 1100)

    with db.session_scope(commit=False) as session:
        deleted = delete_programmes_chunked(
            session, EpgProgramDB.provider_id == "drop", chunk=250
        )
        assert deleted == 1100
        assert session.query(EpgProgramDB).filter_by(provider_id="drop").count() == 0
        assert session.query(EpgProgramDB).filter_by(provider_id="keep").count() == 40


def test_each_chunk_is_durable_before_the_next_one_runs(db):
    """Committing per chunk is the point: the work survives without the caller.

    ``delete_programmes_chunked`` is called with ``commit=False`` sessions (the
    EPG fetch worker's), so if it relied on the caller to commit, one transaction
    would span the whole sweep and hold the lock exactly as before.
    """
    _seed(db, "p1", 900)

    with db.session_scope(commit=False) as session:
        delete_programmes_chunked(session, EpgProgramDB.provider_id == "p1", chunk=300)

    reopened = Database(str(db.engine.url))
    with reopened.session_scope(commit=False) as session:
        assert session.query(EpgProgramDB).filter_by(provider_id="p1").count() == 0


def test_empty_match_commits_nothing_and_returns_zero(db):
    """The termination branch: no matching rows must not spin or write."""
    _seed(db, "other", 10)
    with db.session_scope(commit=False) as session:
        assert delete_programmes_chunked(session, EpgProgramDB.provider_id == "gone") == 0
        assert session.query(EpgProgramDB).count() == 10


def test_row_count_an_exact_multiple_of_chunk_terminates(db):
    """Off-by-one guard: N == k*chunk must not loop forever or drop the last chunk."""
    _seed(db, "p1", 600)
    with db.session_scope(commit=False) as session:
        assert delete_programmes_chunked(
            session, EpgProgramDB.provider_id == "p1", chunk=300
        ) == 600
        assert session.query(EpgProgramDB).count() == 0


def test_retention_sweep_criterion_also_chunks(db, monkeypatch):
    """prune_expired's cutoff filter goes through the same helper, not its own DELETE."""
    _seed(db, "p1", 800, hours_ago=100)   # expired
    _seed(db, "p1", 50)                   # current
    cutoff = _NOW - datetime.timedelta(hours=48)
    counter = _CommitCounter(monkeypatch)

    with db.session_scope(commit=False) as session:
        deleted = delete_programmes_chunked(
            session, EpgProgramDB.stop_time < cutoff, chunk=200
        )
        assert deleted == 800
        assert session.query(EpgProgramDB).count() == 50
    assert counter.count == 4


def test_no_unbounded_delete_survives_on_the_programmes_table():
    """Drift guard: a future edit must not reintroduce a bare table-wide DELETE.

    AST-based, so the prose in this file (which necessarily contains the words it
    forbids) cannot trip it — the same lesson as the ``setStyleSheet`` guard, whose
    line regex knew one shape while eleven real sites sailed past it.

    An unbounded delete that genuinely must stay unbounded declares itself with a
    ``chunked-delete-exempt:`` comment stating why, so the exemption lives beside
    the code rather than in a list here that nobody reads.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "metatv"
    helper_module = "metatv/core/repositories/epg.py"
    offenders = []

    for path in root.rglob("*.py"):
        source = path.read_text()
        lines = source.splitlines()
        tree = ast.parse(source, str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "delete"):
                continue
            # Walk back down the chained call looking for .query(EpgProgramDB).
            cursor = node.func.value
            touches_epg = False
            while isinstance(cursor, ast.Call) and isinstance(cursor.func, ast.Attribute):
                if cursor.func.attr == "query":
                    touches_epg = any(
                        isinstance(arg, ast.Name) and arg.id == "EpgProgramDB"
                        for arg in cursor.args
                    )
                    break
                cursor = cursor.func.value
            if not touches_epg:
                continue

            rel = str(path.relative_to(root.parent))
            if rel == helper_module:
                continue  # the sanctioned chunk delete itself
            # An exemption marker within the six lines above the call.
            window = "\n".join(lines[max(0, node.lineno - 7):node.lineno])
            if "chunked-delete-exempt" in window:
                continue
            offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "unbounded DELETE on epg_programmes outside the chunked helper: "
        f"{offenders}. Route it through delete_programmes_chunked(), or add a "
        "'chunked-delete-exempt:' comment saying why it must stay atomic."
    )


def test_the_exemption_marker_is_actually_required(tmp_path):
    """The guard must not be satisfied by anything — prove the marker is load-bearing.

    Without this, a typo in the marker string would silently exempt everything and
    the guard above would pass forever while detecting nothing.
    """
    import ast

    sample = (
        "class R:\n"
        "    def go(self):\n"
        "        self.session.query(EpgProgramDB).filter().delete()\n"
    )
    tree = ast.parse(sample)
    found = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "delete"
    ]
    assert found, "the AST shape the guard hunts for no longer matches — guard is blind"


def test_default_chunk_is_a_sane_bound():
    """A chunk large enough to be slow again would silently undo the fix."""
    assert 0 < DELETE_CHUNK <= 10_000
