"""Attribute weights are computed once per taste state, not once per caller.

``compute_weights`` is a full TF-IDF rebuild over every stored plot — measured
at 3.9 s on a 75,398-plot corpus — and six surfaces call it independently: the
Recommended sidebar, Discover's workers, the details pane, the trail map, the
preferences view and the discovery engine. From the owner's log, one startup ran
it six times in thirty seconds on identical inputs:

    19:39:31  IDF corpus = 75398 plots, 123920 unique terms
    19:39:40  IDF corpus = 75398 plots, 123920 unique terms
    19:39:44  IDF corpus = 75398 plots, 123920 unique terms
    ...

~23 s of CPU to produce the same answer six times, and a plausible cause of
"Couldn't load recommendations" on a slower machine where those passes overlap.

The cache is keyed on a signature of the inputs rather than timed, so a new
rating cannot be served a stale answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metatv.core import preference_engine as pe
from metatv.core.database import ChannelDB, Database, MetadataDB, UserRatingDB


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'weights.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture(autouse=True)
def _clear_cache():
    pe._WEIGHTS_CACHE.clear()
    yield
    pe._WEIGHTS_CACHE.clear()


def _rate(db, channel_id="c1", rating=1):
    with db.session_scope() as s:
        if not s.query(ChannelDB).filter_by(id=channel_id).first():
            meta_id = f"meta_{channel_id}"
            s.add(MetadataDB(id=meta_id, title="A Film", genres="Drama",
                             plot="a quiet drama about people and weather"))
            s.add(ChannelDB(id=channel_id, source_id=channel_id, provider_id="p",
                            name="A Film", media_type="movie",
                            detected_title="A Film", metadata_id=meta_id))
        s.add(UserRatingDB(channel_id=channel_id, rating=rating))


def test_a_second_call_reuses_the_first_result(db):
    """Identity, not just equality — the bug returned a fresh object each time.

    The first version of this cache stored under a variable named ``key``, which
    ``compute_weights`` already rebinds to a title key inside its loops. It
    cached under the last title string and looked up under the signature tuple,
    so every call recomputed while the cache looked populated and correct.
    """
    _rate(db)
    with db.session_scope(commit=False) as s:
        first = pe.compute_weights(s)
        second = pe.compute_weights(s)
    assert second is first, (
        "the second call rebuilt the corpus; the cache stored something the "
        "lookup cannot find"
    )


def test_only_one_entry_is_stored_for_one_taste_state(db):
    _rate(db)
    with db.session_scope(commit=False) as s:
        pe.compute_weights(s)
        pe.compute_weights(s)
        pe.compute_weights(s)
    assert len(pe._WEIGHTS_CACHE) == 1


def test_a_new_rating_invalidates(db):
    """Keyed, not timed: taste changing must be visible immediately."""
    _rate(db, "c1")
    with db.session_scope(commit=False) as s:
        before = pe.compute_weights(s)
    _rate(db, "c2")
    with db.session_scope(commit=False) as s:
        after = pe.compute_weights(s)
    assert after is not before, "a new rating was served the previous weights"


def test_the_ttl_forces_a_rebuild(db, monkeypatch):
    """The backstop for a plot corpus that grew under background enrichment."""
    _rate(db)
    with db.session_scope(commit=False) as s:
        first = pe.compute_weights(s)
        monkeypatch.setattr(pe, "WEIGHTS_TTL_S", -1.0)
        again = pe.compute_weights(s)
    assert again is not first


def test_an_empty_taste_state_is_cached_too(db):
    """A fresh install sits here while every surface asks."""
    with db.session_scope(commit=False) as s:
        first = pe.compute_weights(s)
        second = pe.compute_weights(s)
    assert second is first
    assert len(pe._WEIGHTS_CACHE) == 1


def test_the_cache_does_not_grow_without_bound(db):
    """One taste state is live at a time; old keys are dead on the next rating."""
    for i in range(12):
        _rate(db, f"c{i}")
        with db.session_scope(commit=False) as s:
            pe.compute_weights(s)
    assert len(pe._WEIGHTS_CACHE) <= 8


def test_a_signature_failure_still_returns_weights(db, monkeypatch):
    """A fingerprint we cannot take is not a reason to refuse the answer."""
    def boom(*a, **k):
        raise RuntimeError("no signature for you")
    monkeypatch.setattr(pe, "_taste_signature", boom)
    _rate(db)
    with db.session_scope(commit=False) as s:
        weights = pe.compute_weights(s)
    assert weights is not None
    assert not pe._WEIGHTS_CACHE, "nothing should be stored under a failed key"
