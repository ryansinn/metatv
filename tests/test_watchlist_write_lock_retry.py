"""A watch-list write survives a transient SQLite lock instead of being lost.

Owner's log, 2026-09-01, twice in thirty seconds while an EPG pass held the
writer::

    ERROR watchlist:_run_write:512 - watchlist: could not remove 'ATP/WTA Cincinnati'
    sqlite3.OperationalError: database is locked
    [SQL: DELETE FROM alert_patterns WHERE alert_patterns.id = ?]

Both rules stayed in the list, each with a toast saying it could not be
removed. The write already runs on the ``watchlist-write`` thread, so waiting
costs the user nothing — it simply never waited.

``busy_timeout=30000`` is not the answer on its own and that is the part worth
recording: ``_db_remove`` READS the row and then deletes it, and SQLite cannot
upgrade a read transaction once another connection has committed underneath
it. It returns ``SQLITE_BUSY`` immediately in that case, with the busy timeout
not applying at all. Retrying the whole transaction is the remedy, and it is
safe because a failed attempt committed nothing.

The retry itself is ``metatv.core.db_lock.retry_on_lock``, shared with the bulk
writers rather than copied — so the first two tests here drive
``watchlist._run_write`` end to end, and the last pins the sharing so a future
change cannot quietly re-grow a second policy.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from metatv.core import watchlist
from metatv.core.config import Config
from metatv.core.database import AlertPatternDB, Database


@pytest.fixture
def config(tmp_path):
    return Config(config_dir=tmp_path)


@pytest.fixture(autouse=True)
def _unbound():
    watchlist.unbind()
    yield
    watchlist.unbind()


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """The delay is real in production and pointless in a test."""
    monkeypatch.setattr(watchlist, "_LOCK_RETRY_DELAY_S", 0.001)


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'wl.db'}")
    database.create_tables()
    return database


def _locked() -> OperationalError:
    return OperationalError("DELETE FROM alert_patterns", {},
                            Exception("database is locked"))


def _run(op="remove", text="ATP/WTA Cincinnati"):
    """Drive the real writer-thread entry point for one queued mutation."""
    errors = []
    watchlist.set_write_error_handler(
        lambda op_, text_, message: errors.append((op_, text_, message)))
    try:
        watchlist._run_write(watchlist._PendingWrite(op=op, text=text))
    finally:
        watchlist.set_write_error_handler(None)
    return errors


def test_a_write_that_hits_the_lock_once_still_lands(monkeypatch):
    """The owner's case: the second attempt gets the writer and the rule goes."""
    attempts = []

    def flaky(write):
        attempts.append(write.op)
        if len(attempts) == 1:
            raise _locked()

    monkeypatch.setattr(watchlist, "_apply_write", flaky)
    errors = _run()

    assert len(attempts) == 2, "a locked write was not retried"
    assert errors == [], f"the user was told about a write that succeeded: {errors}"


def test_a_lock_that_never_clears_is_still_reported(monkeypatch):
    """Retrying may not become silently swallowing."""
    attempts = []

    def always_locked(write):
        attempts.append(write.op)
        raise _locked()

    monkeypatch.setattr(watchlist, "_apply_write", always_locked)
    errors = _run()

    assert len(attempts) > 1, "it gave up without retrying at all"
    assert len(errors) == 1
    op, text, message = errors[0]
    assert (op, text) == ("remove", "ATP/WTA Cincinnati")
    assert "locked" in message.lower()


def test_a_real_failure_is_not_retried(monkeypatch):
    """Only contention retries. A bug must surface on the first attempt."""
    attempts = []

    def broken(write):
        attempts.append(write.op)
        raise OperationalError("DELETE", {}, Exception("no such table: alert_patterns"))

    monkeypatch.setattr(watchlist, "_apply_write", broken)
    errors = _run()

    assert len(attempts) == 1, "a genuine error was retried as if it were a lock"
    assert len(errors) == 1 and "no such table" in errors[0][2]


def test_the_dispatch_still_reaches_every_store_operation(config, db):
    """The extraction of ``_apply_write`` must not have dropped a branch.

    A real ``Database`` on a real file, not ``:memory:`` — CLAUDE.md, and the
    reason applies here: the operations under test are session-scoped writes.
    Add, update and remove are each driven through the queue and then read
    back, so a mis-wired branch fails rather than passing on a mock.
    """
    watchlist.bind(db)

    assert watchlist.add(config, "Mexico") is True
    watchlist.flush()
    assert watchlist.patterns(config) == ("Mexico",)

    watchlist.update(config, "Mexico", exclude=["news"])
    watchlist.flush()
    with db.session_scope(commit=False) as session:
        row = session.query(AlertPatternDB).one()
        assert row.exclude_terms == ["news"]

    assert watchlist.remove(config, "Mexico") is True
    watchlist.flush()
    assert watchlist.patterns(config) == ()


def test_the_retry_policy_is_shared_not_copied():
    """One policy, two callers — the chokepoint rule, in executable form.

    ``ChannelRepository._retry_on_lock`` was the only retry loop in the
    codebase and it needs ``self.session``; the watch-list writer opens its own
    session per write. The temptation was a second loop trimmed to fit. This
    fails if either caller stops routing through the shared helper, or if a
    third ``except OperationalError`` retry loop appears anywhere in core.
    """
    import ast
    import pathlib

    from metatv.core import db_lock

    root = pathlib.Path(db_lock.__file__).resolve().parent

    def calls_shared(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return any(isinstance(n, ast.Name) and n.id == "retry_on_lock"
                   for n in ast.walk(tree))

    assert calls_shared(root / "watchlist.py")
    assert calls_shared(root / "repositories" / "channel.py")

    # No hand-rolled sleep-and-retry-on-lock loop outside db_lock.py.
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "db_lock.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            handled = ast.unparse(node.type) if node.type else ""
            if "OperationalError" not in handled:
                continue
            body = ast.unparse(node)
            if "sleep" in body:
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == [], (
        f"a second lock-retry loop has grown outside db_lock.py: {offenders}")
