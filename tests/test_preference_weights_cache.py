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


# ---------------------------------------------------------------------------
# WHICH inputs the signature covers.
#
# Everything above tests the cache MECHANISM — that it stores, reuses, expires
# and survives a failed signature. None of it tested WHAT the key is taken over,
# which is where the real bug lived: the signature covered an input
# ``compute_weights`` does not read and missed one it does, so it was wrong in
# both directions at once and the mechanism tests all stayed green.
# ---------------------------------------------------------------------------


def _play(db, channel_id="c1"):
    """Stamp last_played, exactly as marking a channel played does."""
    from datetime import datetime, timedelta
    with db.session_scope() as s:
        ch = s.query(ChannelDB).filter_by(id=channel_id).first()
        ch.last_played = datetime.now() + timedelta(seconds=1)


def _favorite(db, channel_id="c1", value=True):
    with db.session_scope() as s:
        ch = s.query(ChannelDB).filter_by(id=channel_id).first()
        ch.is_favorite = value


def test_playing_something_does_not_invalidate(db):
    """The reported hang: play anything, and the next selection rebuilt the corpus.

    ``compute_weights`` never reads ``last_played`` — its implicit signal is
    ``is_favorite``. Keying on watch history therefore threw the answer away on
    every play and made the NEXT channel selection pay a full TF-IDF rebuild on
    the UI thread: measured at **2,118 ms** against the owner's 121,667-plot
    library, and named by the main-thread watchdog as a 5,087 ms stall.

    Asserts object identity: an equal-but-rebuilt result is exactly the bug.
    """
    _rate(db)
    with db.session_scope(commit=False) as s:
        before = pe.compute_weights(s)
    _play(db)
    with db.session_scope(commit=False) as s:
        after = pe.compute_weights(s)
    assert after is before, (
        "playing a channel threw away the cached weights — but the weights do "
        "not depend on watch history, so the rebuild produced the same answer "
        "at a cost of ~2 s on the UI thread"
    )


def test_favoriting_something_does_invalidate(db):
    """The other half: favorites ARE read, and were absent from the signature.

    Favorites enter as the implicit +0.5 signal, so a new favorite genuinely
    changes the weights — and used to be invisible to the cache until the
    ten-minute TTL expired.
    """
    _rate(db)
    with db.session_scope(commit=False) as s:
        before = pe.compute_weights(s)
    _favorite(db, "c1")
    with db.session_scope(commit=False) as s:
        after = pe.compute_weights(s)
    assert after is not before, (
        "favoriting a title was served the previous weights — is_favorite is an "
        "input to compute_weights and must be part of its cache key"
    )


def test_unfavoriting_also_invalidates(db):
    """The set shrinking is as much a change as it growing."""
    _rate(db)
    _favorite(db, "c1", True)
    with db.session_scope(commit=False) as s:
        before = pe.compute_weights(s)
    _favorite(db, "c1", False)
    with db.session_scope(commit=False) as s:
        after = pe.compute_weights(s)
    assert after is not before


def test_the_signature_is_cheap_enough_to_ask_every_time(db):
    """The cache only pays off if asking costs far less than answering.

    Not a wall-clock threshold (which would be flaky on a loaded CI box) — it
    asserts the SHAPE that makes it cheap: two aggregate queries, no per-row
    work, and nothing touching the plot corpus the rebuild exists to avoid.
    """
    _rate(db)
    statements = []
    with db.session_scope(commit=False) as s:
        original = s.execute

        def _recording(stmt, *a, **k):
            statements.append(str(stmt))
            return original(stmt, *a, **k)

        s.execute = _recording
        pe._taste_signature(s, pe.DEFAULT_REC_SETTINGS)

    assert len(statements) == 2, (
        f"signature took {len(statements)} queries; it runs on every call to "
        f"every one of six surfaces"
    )
    joined = " ".join(statements).lower()
    assert "count(*)" in joined
    assert "plot" not in joined, (
        "the signature touched the plot corpus — that is the expensive thing "
        "it exists to avoid"
    )
    assert "last_played" not in joined, (
        "watch history is back in the signature; compute_weights does not read "
        "it, so this reintroduces a rebuild on every play"
    )
