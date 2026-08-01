"""Recommendation-scoring rebalance (0.16.0).

Three defects the rebalance fixes, each with a test that executes the changed path:

1. Volume bias — raw-SUM scoring let richer-metadata titles (more cast, longer plots)
   out-score thinner ones by sheer volume. `_matched_mean` scores each field by the
   average strength of its matches instead. See ``test_matched_mean_*``.

2. Single-performer domination — one liked title's whole cast used to gain weight. An
   actor now needs to appear across >=ACTOR_MIN_SUPPORT liked/favorited titles before it
   counts. See ``test_actor_needs_two_titles_to_count``.

3. Movie/series starvation — with more movies (and, post-#348, richer movie metadata)
   the capped Recommended list filled entirely with movies. ``balance_media_types``
   round-robins the two types. See ``test_balance_*``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from metatv.core.database import ChannelDB, MetadataDB, UserRatingDB


# --------------------------------------------------------------------------- #
# Helpers (file-backed DB per the tests rule — never :memory:)
# --------------------------------------------------------------------------- #

def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _channel(session, name, *, media_type="movie", metadata_id=None,
             last_played=None, provider_id="p1") -> ChannelDB:
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        metadata_id=metadata_id,
        last_played=last_played,
    )
    session.add(ch)
    session.flush()
    return ch


def _metadata(session, title, *, genres=None, cast=None, director=None,
              plot=None, year=None) -> MetadataDB:
    meta = MetadataDB(
        id=str(uuid.uuid4()),
        title=title,
        genres=genres or [],
        cast=cast or [],
        director=director,
        plot=plot,
        year=year,
    )
    session.add(meta)
    session.flush()
    return meta


def _rate(session, channel_id, rating):
    session.add(UserRatingDB(channel_id=channel_id, rating=rating))
    session.flush()


def _sc(score, media_type):
    """Minimal stand-in for ScoredChannel — the interleaver reads only these two."""
    return SimpleNamespace(score=score, media_type=media_type)


def _scp(score, people):
    """Stand-in for the people-diversity re-rank (reads .score + .score_people)."""
    return SimpleNamespace(score=score, media_type="movie", score_people=tuple(people))


# --------------------------------------------------------------------------- #
# 1. _matched_mean — averages matches, ignores neutral, honors negatives
# --------------------------------------------------------------------------- #

def test_matched_mean_averages_and_ignores_neutral():
    from metatv.core.preference_engine import _matched_mean
    assert _matched_mean([]) == 0.0
    assert _matched_mean([0.0, 0.0]) == 0.0
    # Neutral (0) entries don't dilute — a lone strong match keeps its strength.
    assert _matched_mean([4.0, 0.0, 0.0]) == 4.0
    # Multiple matches average (not sum) → volume can't inflate the field.
    assert _matched_mean([4.0, 2.0]) == 3.0
    # A matched dislike (negative) still pulls the field down.
    assert _matched_mean([4.0, -2.0]) == 1.0


def test_matched_mean_kills_volume_inflation():
    """Ten weak matches must not out-score one strong match (the old SUM bug)."""
    from metatv.core.preference_engine import _matched_mean
    many_weak = _matched_mean([0.5] * 10)   # would SUM to 5.0
    one_strong = _matched_mean([3.0])
    assert one_strong > many_weak


# --------------------------------------------------------------------------- #
# 2. Actor corroboration gate — >=2 titles before a performer counts
# --------------------------------------------------------------------------- #

def test_actor_needs_two_titles_to_count(tmp_path):
    from metatv.core.preference_engine import compute_weights, ACTOR_MIN_SUPPORT
    assert ACTOR_MIN_SUPPORT == 2

    db = _make_db(tmp_path / "actors.db")
    session = db.get_session()
    try:
        # "Repeated Star" appears in two liked titles; the others in one each.
        m1 = _metadata(session, "Liked A", genres=["Action"],
                       cast=[{"name": "Repeated Star"}, {"name": "One Off A"}])
        m2 = _metadata(session, "Liked B", genres=["Action"],
                       cast=[{"name": "Repeated Star"}, {"name": "One Off B"}])
        c1 = _channel(session, "EN - Liked A", metadata_id=m1.id)
        c2 = _channel(session, "EN - Liked B", metadata_id=m2.id)
        _rate(session, c1.id, 1)
        _rate(session, c2.id, 1)
        session.commit()

        weights = compute_weights(session)
        assert "Repeated Star" in weights.actors      # support == 2 → counts
        assert weights.actors["Repeated Star"] > 0
        assert "One Off A" not in weights.actors       # support == 1 → pruned
        assert "One Off B" not in weights.actors
    finally:
        session.close()
        db.close()


# --------------------------------------------------------------------------- #
# 3. _interleave_media_types — round-robin, leads with the stronger type
# --------------------------------------------------------------------------- #

def test_interleave_leads_with_stronger_and_alternates():
    from metatv.core.preference_engine import _interleave_media_types
    movies = [_sc(10, "movie"), _sc(8, "movie"), _sc(6, "movie")]
    series = [_sc(9, "series"), _sc(5, "series")]
    out = _interleave_media_types(movies + series, slots=4)
    assert [s.media_type for s in out] == ["movie", "series", "movie", "series"]
    assert [s.score for s in out] == [10, 9, 8, 5]


def test_interleave_fills_from_other_type_when_one_exhausts():
    from metatv.core.preference_engine import _interleave_media_types
    movies = [_sc(10, "movie"), _sc(8, "movie"), _sc(6, "movie")]
    series = [_sc(9, "series"), _sc(5, "series")]
    out = _interleave_media_types(movies + series, slots=10)
    # series (2) exhaust first; the last slot falls back to the remaining movie.
    assert [s.media_type for s in out] == ["movie", "series", "movie", "series", "movie"]


def test_interleave_single_type_returns_top_slots_unchanged():
    from metatv.core.preference_engine import _interleave_media_types
    movies = [_sc(10, "movie"), _sc(8, "movie"), _sc(6, "movie")]
    out = _interleave_media_types(movies, slots=2)
    assert [s.score for s in out] == [10, 8]


# --------------------------------------------------------------------------- #
# 4. _diversify_people — within-generation performer spreading
# --------------------------------------------------------------------------- #

def test_diversify_people_pushes_repeat_performer_down():
    from metatv.core.preference_engine import _diversify_people
    a = _scp(10, ["Star"])    # top match
    b = _scp(9,  ["Star"])    # second, shares Star → should be decayed
    c = _scp(8,  [])          # no liked people → never decayed
    d = _scp(7,  ["Other"])
    out = _diversify_people([a, b, c, d])
    assert out[0] is a                       # strongest still leads
    assert out.index(c) < out.index(b)       # neutral item leapfrogs the 2nd Star
    assert out.index(d) < out.index(b)       # so does the different-person item
    assert out[-1] is b                      # the repeat performer sinks to last


def test_diversify_people_leaves_distinct_people_alone():
    from metatv.core.preference_engine import _diversify_people
    a = _scp(10, ["Star"])
    b = _scp(9,  ["Other"])   # different person → no decay → keeps rank
    out = _diversify_people([a, b])
    assert [s.score for s in out] == [10, 9]


# --------------------------------------------------------------------------- #
# 5. score_candidates end-to-end — the movie/series starvation fix
# --------------------------------------------------------------------------- #

def _build_movie_heavy_fixture(session):
    """Liked signal gives Action + a corroborated actor 'Star'. Movie candidates
    match genre+actor (higher score); series candidates match genre only (lower).
    With more movies than series, the raw ranking is movie-dominated."""
    # Two liked movies so 'Star' clears the actor support gate.
    for tag in ("A", "B"):
        m = _metadata(session, f"Liked {tag}", genres=["Action"],
                      cast=[{"name": "Star"}])
        ch = _channel(session, f"EN - Liked {tag}", metadata_id=m.id,
                      last_played=datetime(2024, 1, 1))   # watched → not a candidate
        _rate(session, ch.id, 1)

    movie_ids, series_ids = [], []
    for i in range(6):
        m = _metadata(session, f"Cand Movie {i}", genres=["Action"],
                      cast=[{"name": "Star"}])            # genre + actor match
        movie_ids.append(_channel(session, f"EN - Cand Movie {i}",
                                   metadata_id=m.id).id)
    for i in range(3):
        m = _metadata(session, f"Cand Series {i}", genres=["Action"])  # genre only
        series_ids.append(_channel(session, f"EN - Cand Series {i}",
                                    media_type="series", metadata_id=m.id).id)
    session.commit()
    return set(movie_ids), set(series_ids)


def test_balance_off_yields_movies_only(tmp_path):
    """Default (no balancing): the small top-N fills entirely with the higher-
    scoring, more-numerous movies — reproducing the reported starvation."""
    from metatv.core.preference_engine import compute_weights, score_candidates

    db = _make_db(tmp_path / "unbalanced.db")
    session = db.get_session()
    try:
        movie_ids, series_ids = _build_movie_heavy_fixture(session)
        weights = compute_weights(session)
        recs = score_candidates(session, weights, limit=4)
        types = {r.channel_id: r.media_type for r in recs}
        assert len(recs) == 4
        assert all(t == "movie" for t in types.values())
        assert not (set(types) & series_ids)
    finally:
        session.close()
        db.close()


def test_balance_on_yields_mix(tmp_path):
    """balance_media_types=True: the same capped list now carries BOTH types."""
    from metatv.core.preference_engine import compute_weights, score_candidates

    db = _make_db(tmp_path / "balanced.db")
    session = db.get_session()
    try:
        movie_ids, series_ids = _build_movie_heavy_fixture(session)
        weights = compute_weights(session)
        recs = score_candidates(session, weights, limit=4, balance_media_types=True)
        got = [r.media_type for r in recs]
        assert "movie" in got and "series" in got, got
        # Round-robin over an even cap → an even split.
        assert got.count("movie") == 2 and got.count("series") == 2
        # Movies still lead (their match is stronger).
        assert recs[0].media_type == "movie"
    finally:
        session.close()
        db.close()


def _build_actor_repeat_fixture(session):
    """Two candidate movies share liked actor 'Star' (higher base score); two match
    genre only (lower). Diversity should let a genre-only movie leapfrog the 2nd Star."""
    for tag in ("A", "B"):   # 'Star' clears the support gate across two liked titles
        m = _metadata(session, f"Liked {tag}", genres=["Action"], cast=[{"name": "Star"}])
        ch = _channel(session, f"EN - Liked {tag}", metadata_id=m.id,
                      last_played=datetime(2024, 1, 1))
        _rate(session, ch.id, 1)
    for i in range(2):
        m = _metadata(session, f"Star Movie {i}", genres=["Action"], cast=[{"name": "Star"}])
        _channel(session, f"EN - Star Movie {i}", metadata_id=m.id)
    for i in range(2):
        m = _metadata(session, f"Plain Movie {i}", genres=["Action"])   # genre only
        _channel(session, f"EN - Plain Movie {i}", metadata_id=m.id)
    session.commit()


def test_diversify_off_stacks_same_actor(tmp_path):
    """Default: both higher-scoring same-actor movies stack at the top."""
    from metatv.core.preference_engine import compute_weights, score_candidates

    db = _make_db(tmp_path / "div_off.db")
    session = db.get_session()
    try:
        _build_actor_repeat_fixture(session)
        weights = compute_weights(session)
        recs = score_candidates(session, weights, limit=4)
        assert recs[0].score_people == ("Star",)
        assert recs[1].score_people == ("Star",)   # 2nd slot is the repeat performer
    finally:
        session.close()
        db.close()


def test_diversify_on_surfaces_other_content(tmp_path):
    """diversify_people=True: a genre-only movie leapfrogs the second Star movie."""
    from metatv.core.preference_engine import compute_weights, score_candidates

    db = _make_db(tmp_path / "div_on.db")
    session = db.get_session()
    try:
        _build_actor_repeat_fixture(session)
        weights = compute_weights(session)
        recs = score_candidates(session, weights, limit=4, diversify_people=True)
        assert recs[0].score_people == ("Star",)   # strongest match still leads
        assert recs[1].score_people == ()           # a non-Star movie surfaces next
    finally:
        session.close()
        db.close()
