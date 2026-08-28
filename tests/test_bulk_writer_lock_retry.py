"""Every bulk write path retries a transient SQLite lock.

On 2026-08-01 the tmdb-sibling propagation crashed on ``database is locked``
because only the per-batch commit had retry coverage. ``_retry_on_lock`` was
added and three phases were wired through it — and then two more bulk writers,
``backfill_tmdb_ids`` and ``backfill_content_keys``, were written without it.
Three siblings got the guard and two did not, which is the enumeration failure
CLAUDE.md names: nobody remembered to add the new ones.

So the check is DERIVED from the AST rather than a hand-listed set of method
names. A new bulk writer fails this test unless it is protected or explicitly
recorded as exempt with a reason.

WAL and ``busy_timeout=30000`` already absorb ordinary contention; what these
retries cover is a long bulk transaction competing with the UI, which is
exactly the shape that crashed.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from metatv.core.repositories import channel_ingestion

# A bulk writer that deliberately does NOT retry must be listed here WITH the
# reason. Empty on purpose — if you are adding to it, say why in the comment.
EXEMPT: dict[str, str] = {}


def _module_ast() -> ast.Module:
    return ast.parse(Path(inspect.getfile(channel_ingestion)).read_text(encoding="utf-8"))


def _committing_methods(cls: ast.ClassDef) -> set[str]:
    """Methods of *cls* that call ``.commit()`` anywhere in their body."""
    out = set()
    for m in cls.body:
        if isinstance(m, ast.FunctionDef) and any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr == "commit" for c in ast.walk(m)
        ):
            out.add(m.name)
    return out


def _commits_inside_a_loop(fn: ast.FunctionDef, committing: set[str]) -> bool:
    """True when *fn* writes repeatedly — directly, or via a committing helper.

    The indirection matters. Moving a commit into a per-batch helper called from
    the loop is exactly the refactor this file's subject went through, and a
    guard that only saw DIRECT commits would score the result as "not a bulk
    writer" and pass while the retry was gone. Proven by mutation: bypassing
    the retry has to turn this red, not just the by-name test.
    """
    for node in ast.walk(fn):
        if not isinstance(node, (ast.For, ast.While)):
            continue
        for inner in ast.walk(node):
            if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)):
                continue
            if inner.func.attr == "commit":
                return True
            if (isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "self"
                    and inner.func.attr in committing):
                return True
    return False


def _retry_protected_names(cls: ast.ClassDef) -> set[str]:
    """Method names passed as the callable to ``self._retry_on_lock(...)``."""
    names: set[str] = set()
    for node in ast.walk(cls):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_retry_on_lock"):
            for arg in node.args:
                if isinstance(arg, ast.Attribute):
                    names.add(arg.attr)
    return names


def _ingestion_class() -> ast.ClassDef:
    return next(n for n in ast.walk(_module_ast())
                if isinstance(n, ast.ClassDef) and n.name == "ChannelIngestionMixin")


def test_every_bulk_writer_is_lock_protected():
    """A method that commits inside a loop must retry, or be a retried batch."""
    cls = _ingestion_class()
    protected = _retry_protected_names(cls)
    committing = _committing_methods(cls)
    unprotected = []
    for m in cls.body:
        if not isinstance(m, ast.FunctionDef) or not _commits_inside_a_loop(m, committing):
            continue
        calls = {c.func.attr for c in ast.walk(m)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        if m.name in protected or "_retry_on_lock" in calls or m.name in EXEMPT:
            continue
        unprotected.append(m.name)
    assert not unprotected, (
        "bulk write path(s) with no lock retry: "
        f"{unprotected} — wrap the batch via self._retry_on_lock(...), or add "
        "an entry to EXEMPT with the reason"
    )


def test_the_two_backfills_are_reached_through_the_retry():
    """Named explicitly: these are the two that were missing it."""
    protected = _retry_protected_names(_ingestion_class())
    for batch in ("_process_tmdb_backfill_batch", "_process_content_key_backfill_batch"):
        assert batch in protected, f"{batch} is no longer retried"


def test_a_batch_is_retried_as_a_unit_not_just_its_commit():
    """Retrying only ``commit()`` would flush nothing after a rollback.

    A failed commit's rollback expires the session's in-memory changes, so the
    batch must be recomputed from a fresh query. Each retried batch method
    therefore has to own its own SELECT, not just the write.
    """
    cls = _ingestion_class()
    for name in ("_process_tmdb_backfill_batch", "_process_content_key_backfill_batch"):
        fn = next(m for m in cls.body
                  if isinstance(m, ast.FunctionDef) and m.name == name)
        calls = {c.func.attr for c in ast.walk(fn)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        assert "query" in calls, f"{name} must re-query, not just re-commit"
        assert "commit" in calls, f"{name} must own its commit"


@pytest.mark.parametrize("name", ["backfill_tmdb_ids", "backfill_content_keys"])
def test_the_public_pass_still_returns_a_total(db, name):
    """Behaviour is unchanged: the pass still counts every row it wrote."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as s:
        for i in range(3):
            s.add(ChannelDB(id=f"c{i}", source_id=str(i), provider_id="p",
                            name=f"EN - Film {i} (201{i})", media_type="movie",
                            raw_data={"tmdb": str(700 + i)}))
    with db.session_scope() as s:
        repo = RepositoryFactory(s).channels
        kwargs = {"recompute_all": True} if name == "backfill_content_keys" else {}
        assert getattr(repo, name)(**kwargs) == 3


@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'lock.db'}")
    d.create_tables()
    yield d
    d.close()
