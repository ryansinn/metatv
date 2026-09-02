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

The cache and its build function live in ``metatv.core.idf_corpus`` — a
standalone module, not ``preference_engine`` — because the IDF depends on
nothing in the preference engine (only ``MetadataDB``) and that file sits at
its code-health ratchet baseline. Tests of ``corpus_idf``/``build_idf``'s OWN
behaviour patch and call them in their defining module; only the one test that
proves ``compute_weights`` DELEGATES to ``corpus_idf`` patches the reference
``preference_engine`` actually resolves (its own imported name).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core import idf_corpus
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
    idf_corpus._idf_cache = None
    pe._WEIGHTS_CACHE.clear()
    yield
    idf_corpus._idf_cache = None
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
    original = idf_corpus.build_idf

    def counting(all_plots):
        calls.append(all_plots)
        return original(all_plots)

    monkeypatch.setattr(idf_corpus, "build_idf", counting)


def test_second_call_hits_the_cache(db, monkeypatch):
    _seed_plot(db, "m1", "a quiet drama about people and weather")
    _seed_plot(db, "m2", "a loud comedy about parties and friends")

    calls: list = []
    _counting_build_idf(monkeypatch, calls)

    with db.session_scope(commit=False) as s:
        first = idf_corpus.corpus_idf(s)
        second = idf_corpus.corpus_idf(s)

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
        idf_corpus.corpus_idf(s)
    assert len(calls) == 1

    # Count of non-null plots moves — enrichment just widened the corpus.
    _seed_plot(db, "m2", "a loud comedy about parties and friends")

    with db.session_scope(commit=False) as s:
        idf_corpus.corpus_idf(s)
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
        idf_corpus.corpus_idf(s)
    assert len(calls) == 1

    # Plot count is unchanged; MAX(fetched_at) moves — enrichment re-fetched
    # the same row (e.g. a corrected plot from a slower metadata provider).
    with db.session_scope() as s:
        row = s.query(MetadataDB).filter_by(id="m1").first()
        row.fetched_at = datetime(2020, 1, 1) + timedelta(days=1)

    with db.session_scope(commit=False) as s:
        idf_corpus.corpus_idf(s)
    assert len(calls) == 2, (
        "a re-fetched plot moved MAX(fetched_at) but corpus_idf served the stale IDF"
    )


def test_compute_weights_uses_the_shared_corpus(db, monkeypatch):
    _rate(db)

    # compute_weights lives in preference_engine, which no longer imports
    # build_idf at all — the IDF build is reachable only through corpus_idf.
    assert not hasattr(pe, "build_idf"), (
        "preference_engine must not import build_idf directly — the IDF "
        "layer lives in idf_corpus and is reached only through corpus_idf"
    )

    corpus_calls: list = []

    def stub_corpus_idf(session):
        corpus_calls.append(session)
        return {}

    # Patched on `pe`, not `idf_corpus`: compute_weights resolves the bare
    # name `corpus_idf` through preference_engine's own module globals (its
    # `from metatv.core.idf_corpus import corpus_idf`), so that is the
    # reference it actually sees — patching the defining module's copy would
    # not touch it, same trap as CLAUDE.md's epg_view.parse_channel_name case.
    monkeypatch.setattr(pe, "corpus_idf", stub_corpus_idf)

    with db.session_scope(commit=False) as s:
        weights = pe.compute_weights(s)

    assert weights is not None
    assert len(corpus_calls) == 1, (
        "compute_weights must get the IDF table from corpus_idf exactly once"
    )
