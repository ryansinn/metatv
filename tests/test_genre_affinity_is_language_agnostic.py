"""A genre preference is about the genre, not about which language spelled it.

Taste weights are a plain dict keyed on the genre string, so before this fix two
spellings of one genre were two unrelated preferences. The owner's library is
assembled from international providers and carries five languages of the same
handful of genres::

    Drama   70,689 mentions  <-  Drama 51,226 · دراما 8,337 · Drame 8,140 · Dramat 1,558
    Comedy  28,603 mentions  <-  Comedy 16,354 · Comédie 3,605 · كوميديا 2,779 · Komödie 2,330

743 distinct genre strings collapse to 394 canonical ones, and 66,206 of 231,814
genre mentions (28.6%) sat on a non-canonical key — each scoring a structural
0.0 against a preference learned in English.

This is the owner's reported *Drama vs DRAMA* bug one level up: the same defect
across languages instead of case.
"""

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, MetadataDB, UserRatingDB
from metatv.core.preference_engine import (
    _split_genres, compute_weights, score_candidates,
)


@pytest.fixture
def session(tmp_path: Path):
    """A real file-backed DB — compute_weights does genuine session work."""
    db = Database(f"sqlite:///{tmp_path / 'prefs.db'}")
    db.create_tables()
    with db.session_scope() as s:
        yield s


def _liked_title(session, *, genres: list[str]) -> None:
    """Store one thumbs-up on a title carrying *genres*."""
    meta = MetadataDB(id=str(uuid.uuid4()), title="Liked", genres=genres, cast=[])
    session.add(meta)
    session.flush()
    ch = ChannelDB(
        id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id="p1",
        name="Liked", media_type="movie", metadata_id=meta.id,
    )
    session.add(ch)
    session.flush()
    session.add(UserRatingDB(channel_id=ch.id, rating=1))
    session.flush()


# ── the user-visible outcome ────────────────────────────────────────────────

@pytest.mark.parametrize("liked,candidate", [
    ("Drama",   "Drame"),      # English preference, French candidate
    ("Drame",   "Drama"),      # and the reverse
    ("Drama",   "Dramat"),     # Polish
    ("Comedy",  "Komödie"),    # German
    ("Comedy",  "Comédie"),    # French
])
def test_a_liked_genre_matches_the_same_genre_in_another_language(
    session, liked: str, candidate: str
) -> None:
    """The whole point: liking one spelling must score the other.

    Runs the real weight builder, then the real read-side split, and asks the
    question the recommender asks. Pre-fix the weight sits on the liked spelling
    and the candidate is looked up under a different key, so this is 0.0.
    """
    _liked_title(session, genres=[liked])
    weights = compute_weights(session)

    candidate_genres = _split_genres([candidate])
    score = max((weights.genres.get(g, 0.0) for g in candidate_genres), default=0.0)

    assert score > 0, (
        f"a {liked!r} preference scores {candidate!r} at {score} — the engine "
        f"treats them as unrelated genres. weights={dict(weights.genres)}"
    )


def test_two_spellings_on_one_title_do_not_double_the_weight(tmp_path) -> None:
    """Collapsing must not turn one title into two votes for the same genre.

    A title tagged both *Drama* and *Drame* is one drama. Without the dedupe in
    ``_split_genres`` the canonicalisation would map both to "Drama" and add the
    weight twice, quietly making multilingual titles count double.
    """
    def weight_for(genres: list[str], name: str) -> float:
        db = Database(f"sqlite:///{tmp_path / name}")
        db.create_tables()
        with db.session_scope() as s:
            _liked_title(s, genres=genres)
            return compute_weights(s).genres.get("Drama", 0.0)

    one_spelling = weight_for(["Drama"], "one.db")
    two_spellings = weight_for(["Drama", "Drame"], "two.db")

    assert one_spelling > 0, "the single-spelling case earned no weight at all"
    assert two_spellings == one_spelling, (
        f"a title tagged both spellings earned {two_spellings} where one "
        f"spelling earns {one_spelling} — the genre is being counted twice"
    )


def test_muting_a_genre_mutes_its_other_spellings(tmp_path) -> None:
    """Muting a genre means the genre, whichever spelling the mute was stored under.

    This drives the REAL ``score_candidates`` muting path rather than
    reconstructing the comparison in the test — an earlier draft of this test
    built its own normalised set and asserted against that, which passed
    happily while production still compared raw strings. That is the same
    fixture-reimplements-the-subject defect this audit found in the credential
    guard, and it is why the mute assertion below goes through the engine.
    """
    db = Database(f"sqlite:///{tmp_path / 'mute.db'}")
    db.create_tables()
    with db.session_scope() as s:
        _liked_title(s, genres=["Drama"])

        # A candidate the user has not rated, tagged in French.
        meta = MetadataDB(id=str(uuid.uuid4()), title="Candidat",
                          genres=["Drame"], cast=[])
        s.add(meta)
        s.flush()
        s.add(ChannelDB(
            id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id="p1",
            name="Candidat", media_type="movie", metadata_id=meta.id,
        ))
        s.flush()

        weights = compute_weights(s)

        unmuted = score_candidates(s, weights, limit=10)
        # Muted by its FRENCH name. A mute stored before genres were
        # canonicalised holds whatever spelling the user was shown at the time,
        # so the muted set has to be normalised on the way in — muting by the
        # canonical name would pass even unnormalised, because the candidate
        # side is already canonical.
        muted = score_candidates(s, weights, limit=10, muted_attrs={"genres": ["Drame"]})

        assert any(c.channel_name == "Candidat" for c in unmuted), (
            "the French candidate did not score at all, so this test cannot "
            "tell whether muting worked"
        )
        assert not any(c.channel_name == "Candidat" for c in muted), (
            "muting 'Drame' left the candidate in the results — the muted set "
            "is being compared as a raw string, so a mute stored under a "
            "non-canonical spelling silently stops working"
        )


def test_an_unknown_genre_is_left_alone(session) -> None:
    """Normalisation must not invent a mapping for a genre nobody curated."""
    assert _split_genres(["Kdrama Thriller Noir"]) == ["Kdrama Thriller Noir"]
