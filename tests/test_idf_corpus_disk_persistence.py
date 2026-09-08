"""``corpus_idf`` persists the built IDF table to disk (IDF-1).

``test_idf_corpus_cache.py`` covers the pure in-memory cache, which only helps
calls *within* one launch. The owner's app freezes repeatedly at startup
because every cold launch rebuilds the IDF table over 132,840 plots — a
CPU-bound Python task that collapses the main thread under GIL contention
while the sidebar builds rows (measured worst case: a 16.5s watchdog stall).
The disk cache below (``~/.cache/metatv/idf_corpus.json``, behind the same
``(count, MAX(fetched_at))`` stamp) is what lets a *second* launch — a fresh
process, empty in-memory cache — skip that rebuild entirely.

These tests pin ``Path.home()`` to the test's own ``tmp_path`` (on top of the
autouse ``_isolate_user_config`` fixture in ``tests/conftest.py``, which
already keeps it off the real user directory) so the exact write location can
be asserted, per CLAUDE.md's rule to use ``Path.home()`` — never
``expanduser()``, which reads ``HOME`` directly and would bypass that guard.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func

from metatv.core import idf_corpus
from metatv.core.database import MetadataDB


@pytest.fixture(autouse=True)
def _reset_idf_cache():
    """Module-level in-memory cache must not leak state between tests (repo rule)."""
    idf_corpus._idf_cache = None
    yield
    idf_corpus._idf_cache = None


@pytest.fixture(autouse=True)
def _pin_home(monkeypatch, tmp_path):
    """Pin ``Path.home()`` to this test's own ``tmp_path``.

    The conftest ``_isolate_user_config`` fixture already redirects
    ``Path.home()`` away from the real user directory (to its own throwaway
    fake home); this additionally pins it to THIS test's ``tmp_path`` so
    tests can assert exactly where the disk cache file lands.
    """
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))


def _seed_plot(db, meta_id: str, plot: str, fetched_at: datetime | None = None) -> None:
    with db.session_scope() as s:
        kwargs = {} if fetched_at is None else {"fetched_at": fetched_at}
        s.add(MetadataDB(id=meta_id, title=meta_id, plot=plot, **kwargs))


def _cache_path() -> Path:
    return idf_corpus._disk_cache_path()


def _live_stamp(db):
    with db.session_scope(commit=False) as s:
        return (
            s.query(func.count(MetadataDB.plot), func.max(MetadataDB.fetched_at))
            .filter(MetadataDB.plot.isnot(None))
            .one()
        )


def test_first_build_writes_the_cache_file_with_matching_stamp(db):
    _seed_plot(db, "m1", "a quiet drama about people and weather")
    _seed_plot(db, "m2", "a loud comedy about parties and friends")

    with db.session_scope(commit=False) as s:
        idf = idf_corpus.corpus_idf(s)

    cache_path = _cache_path()
    assert cache_path.exists(), "corpus_idf must write the disk cache on a fresh build"

    data = json.loads(cache_path.read_text())
    assert data["idf"] == idf
    assert data["stamp"] == idf_corpus._serializable_stamp(_live_stamp(db))


def test_second_launch_hits_disk_cache_without_rebuilding(db, monkeypatch):
    """Prove the disk path is actually taken, not just a warm in-memory hit.

    Clearing ``_idf_cache`` simulates a fresh process. ``build_idf`` is
    monkeypatched to raise, so if ``corpus_idf`` fell through to a rebuild
    instead of reading the file, this test would fail loudly rather than
    silently passing on a lucky cache hit.
    """
    _seed_plot(db, "m1", "a quiet drama about people and weather")
    _seed_plot(db, "m2", "a loud comedy about parties and friends")

    with db.session_scope(commit=False) as s:
        first = idf_corpus.corpus_idf(s)

    idf_corpus._idf_cache = None

    def _boom(all_plots):
        raise AssertionError("build_idf must not run on a disk-cache hit")

    monkeypatch.setattr(idf_corpus, "build_idf", _boom)

    with db.session_scope(commit=False) as s:
        second = idf_corpus.corpus_idf(s)

    assert second == first


def test_moved_corpus_rebuilds_and_rewrites_the_file(db):
    # Three plots with disjoint content words: below the 3-doc threshold every
    # word's corpus frequency (1/n) exceeds MAX_CORPUS_FREQ (0.35) and gets
    # filtered out entirely, so build_idf would trivially return {} for both
    # "first" and "second" — a false pass. Three-plus plots keep the table
    # non-empty so a real content change is observable.
    _seed_plot(db, "m1", "an astronaut wanders across lonely craters searching for answers")
    _seed_plot(db, "m2", "a detective chases thieves through silent alleyways at night")
    _seed_plot(db, "m3", "a scientist studies fossils buried beneath frozen tundra")

    with db.session_scope(commit=False) as s:
        first = idf_corpus.corpus_idf(s)
    assert first, "test setup must produce a non-empty IDF table"

    cache_path = _cache_path()
    first_written = cache_path.read_text()

    idf_corpus._idf_cache = None
    # Count of non-null plots moves — enrichment just widened the corpus.
    _seed_plot(db, "m4", "an inventor builds engines inside secret workshops")

    with db.session_scope(commit=False) as s:
        second = idf_corpus.corpus_idf(s)

    assert second != first, "a wider corpus must produce a different IDF table"
    second_written = cache_path.read_text()
    assert second_written != first_written, (
        "corpus_idf must rewrite the disk cache once the corpus has moved"
    )
    assert json.loads(second_written)["idf"] == second
    assert json.loads(second_written)["stamp"] == idf_corpus._serializable_stamp(
        _live_stamp(db)
    )


def test_corrupt_cache_file_falls_back_to_a_correct_rebuild(db):
    _seed_plot(db, "m1", "a quiet drama about people and weather")
    _seed_plot(db, "m2", "a loud comedy about parties and friends")

    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{not json")

    with db.session_scope(commit=False) as s:
        idf = idf_corpus.corpus_idf(s)

    with db.session_scope(commit=False) as s:
        all_plots = [
            row[0] for row in
            s.query(MetadataDB.plot).filter(MetadataDB.plot.isnot(None)).all()
        ]
    assert idf == idf_corpus.build_idf(all_plots), (
        "a corrupt cache file must still yield a correct rebuilt table"
    )

    # The bad file must have been overwritten with a valid one.
    data = json.loads(cache_path.read_text())
    assert data["idf"] == idf


def test_cache_file_lands_only_inside_the_patched_home(db, tmp_path):
    _seed_plot(db, "m1", "a quiet drama about people and weather")

    with db.session_scope(commit=False) as s:
        idf_corpus.corpus_idf(s)

    cache_path = _cache_path()
    assert cache_path == tmp_path / ".cache" / "metatv" / "idf_corpus.json"
    assert cache_path.is_relative_to(tmp_path), (
        f"expected the IDF cache under the patched home {tmp_path}, got {cache_path}"
    )

    # No leftover .tmp sibling (os.replace must have consumed it), and no
    # IDF-cache file written anywhere else under the patched home.
    idf_related = {p for p in tmp_path.rglob("idf_corpus*") if p.is_file()}
    assert idf_related == {cache_path}, (
        f"expected only {cache_path} among IDF-cache files, found {idf_related}"
    )
