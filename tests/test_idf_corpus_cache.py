"""The plot-corpus IDF table is built once and shared, not rebuilt per caller.

``compute_weights`` used to fetch every ``MetadataDB.plot`` (132,273 rows) and
rebuild the IDF table (129,556 terms) on EVERY call — and several consumers
(Discover's workers, the details pane, the preferences view, the discovery
engine, the trail map) call it independently, so one settings change built it
twice within two seconds in the owner's own logs.

The IDF depends only on the METADATA CORPUS — never on ratings, favorites, or
scoring settings — so ``corpus_idf`` caches it under a cheap stamp
(``(count of non-null plots, MAX(fetched_at))``) that only moves when
enrichment actually changes the corpus. This is a separate, lower layer than
the taste-keyed ``_WEIGHTS_CACHE`` in ``test_preference_weights_cache.py``:
different scoring dials produce different taste signatures (and so different
cache entries there), but they should all share ONE IDF build here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core import preference_engine as pe
from metatv.core.database import ChannelDB, Database, MetadataDB, UserRatingDB


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'idf_corpus.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """Module-level caches must not leak state between tests (repo rule)."""
    pe._idf_cache = None
    pe._WEIGHTS_CACHE.clear()
    yield
    pe._idf_cache = None
    pe._WEIGHTS_CACHE.clear()


def _seed_plot(db, meta_id: str, plot: str, fetched_at: datetime | None = None) -> None:
    with db.session_scope() as s:
        kwargs = {} if fetched_at is None else {"fetched_at": fetched_at}
        s.add(MetadataDB(id=meta_id, title=meta_id, plot=plot, **kwargs))


def _rate(db, channel_id: str = "c1", rating: int = 1) -> None:
    """Minimal signal so ``compute_weights`` runs past its empty-taste early exit."""
    with db.session_scope() as s:
        if not s.query(ChannelDB).filter_by(id=channel_id).first():
            meta_id = f"meta_{channel_id}"
            s.add(MetadataDB(id=meta_id, title="A Film", genres="Drama",
                             plot="a quiet drama about people and weather"))
            s.add(ChannelDB(id=channel_id, source_id=channel_id, provider_id="p",
                            name="A Film", media_type="movie",
                            detected_title="A Film", metadata_id=meta_id))
        s.add(UserRatingDB(channel_id=channel_id, rating=rating))


def _counting_build_idf(monkeypatch, calls: list) -> None:
    original = pe.build_idf

    def counting(all_plots):
        calls.append(all_plots)
        return original(all_plots)

    monkeypatch.setattr(pe, "build_idf", counting)


def test_second_call_hits_the_cache(db, monkeypatch):
    _seed_plot(db, "m1", "a quiet drama about people and weather")
    _seed_plot(db, "m2", "a loud comedy about parties and friends")

    calls: list = []
    _counting_build_idf(monkeypatch, calls)

    with db.session_scope(commit=False) as s:
        first = pe.corpus_idf(s)
        second = pe.corpus_idf(s)

    assert len(calls) == 1, (
        f"expected one build shared across two calls, got {len(calls)} — the "
        f"second call rebuilt instead of hitting the cache"
    )
    assert first == second


def test_new_plot_invalidates(db, monkeypatch):
    _seed_plot(db, "m1", "a quiet drama about people and weather")

    calls: list = []
    _counting_build_idf(monkeypatch, calls)

    with db.session_scope(commit=False) as s:
        pe.corpus_idf(s)
    assert len(calls) == 1

    # Count of non-null plots moves — enrichment just widened the corpus.
    _seed_plot(db, "m2", "a loud comedy about parties and friends")

    with db.session_scope(commit=False) as s:
        pe.corpus_idf(s)
    assert len(calls) == 2, (
        "a new plot changed the corpus count but corpus_idf served the stale IDF"
    )


def test_refetched_plot_invalidates(db, monkeypatch):
    _seed_plot(
        db, "m1", "a quiet drama about people and weather",
        fetched_at=datetime(2020, 1, 1),
    )

    calls: list = []
    _counting_build_idf(monkeypatch, calls)

    with db.session_scope(commit=False) as s:
        pe.corpus_idf(s)
    assert len(calls) == 1

    # Plot count is unchanged; MAX(fetched_at) moves — enrichment re-fetched
    # the same row (e.g. a corrected plot from a slower metadata provider).
    with db.session_scope() as s:
        row = s.query(MetadataDB).filter_by(id="m1").first()
        row.fetched_at = datetime(2020, 1, 1) + timedelta(days=1)

    with db.session_scope(commit=False) as s:
        pe.corpus_idf(s)
    assert len(calls) == 2, (
        "a re-fetched plot moved MAX(fetched_at) but corpus_idf served the stale IDF"
    )


def test_compute_weights_uses_the_shared_corpus(db, monkeypatch):
    _rate(db)

    build_calls: list = []
    monkeypatch.setattr(
        pe, "build_idf", lambda all_plots: (build_calls.append(all_plots), {})[1]
    )

    corpus_calls: list = []

    def stub_corpus_idf(session):
        corpus_calls.append(session)
        return {}

    monkeypatch.setattr(pe, "corpus_idf", stub_corpus_idf)

    with db.session_scope(commit=False) as s:
        weights = pe.compute_weights(s)

    assert weights is not None
    assert len(corpus_calls) == 1, (
        "compute_weights must get the IDF table from corpus_idf exactly once"
    )
    assert build_calls == [], (
        "compute_weights called build_idf directly — the old inline plot query "
        "is still there instead of routing through corpus_idf"
    )
