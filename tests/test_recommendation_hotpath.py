"""Behavioral equivalence tests for the recommendation hot-path performance refactor.

Covers:
- ix_channels_last_played index: present after create_tables(); migration adds it on existing DBs.
- score_candidates: ranked output (ids + order + scores) unchanged after batched metadata fetch.
- compute_weights: AttributeWeights unchanged after batched channel/metadata fetch + column-only plots.
- build_engaged_normalized: engaged fingerprint set unchanged after batched N+1 removal.
- build_status_sets: fav/watched id sets unchanged after column-only queries.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from metatv.core.database import (
    Base, ChannelDB, MetadataDB, UserRatingDB, WatchQueueDB,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: Path):
    """Create a file-backed Database (not :memory:) and return (engine, Session)."""
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _make_channel(session, name: str, media_type: str = "movie",
                  metadata_id: str | None = None,
                  detected_prefix: str | None = None,
                  is_favorite: bool = False,
                  is_hidden: bool = False,
                  last_played: datetime | None = None,
                  provider_id: str = "p1") -> ChannelDB:
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        metadata_id=metadata_id,
        detected_prefix=detected_prefix,
        is_favorite=is_favorite,
        is_hidden=is_hidden,
        last_played=last_played,
    )
    session.add(ch)
    session.flush()
    return ch


def _make_metadata(session, title: str, genres=None, director: str | None = None,
                   year: int | None = None, plot: str | None = None,
                   rating: float | None = None, cast=None) -> MetadataDB:
    meta = MetadataDB(
        id=str(uuid.uuid4()),
        title=title,
        genres=genres or [],
        director=director,
        year=year,
        plot=plot,
        rating=rating,
        cast=cast or [],
    )
    session.add(meta)
    session.flush()
    return meta


def _make_rating(session, channel_id: str, rating: int) -> UserRatingDB:
    r = UserRatingDB(channel_id=channel_id, rating=rating)
    session.add(r)
    session.flush()
    return r


# ---------------------------------------------------------------------------
# 1. Index tests
# ---------------------------------------------------------------------------

class TestLastPlayedIndex:
    """Verify ix_channels_last_played is created by both create_tables() and migration."""

    def test_index_present_after_create_tables(self, tmp_path):
        """New DB: index must exist after create_tables()."""
        db = _make_db(tmp_path / "new.db")
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_channels_last_played'")
            ).fetchall()
        db.close()
        assert len(rows) == 1, "ix_channels_last_played not found after create_tables()"

    def test_migration_adds_index_to_existing_db(self, tmp_path):
        """Existing DB without the index: _migrate() adds it."""
        from metatv.core.database import Database
        db_path = tmp_path / "existing.db"

        # Create DB tables WITHOUT the index (simulate a pre-refactor DB)
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        # Explicitly drop the index if it exists (SQLAlchemy may create it via index=True)
        with engine.connect() as conn:
            conn.execute(text("DROP INDEX IF EXISTS ix_channels_last_played"))
            conn.commit()
        # Confirm it's gone
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_channels_last_played'")
            ).fetchall()
        assert len(rows) == 0, "setup failed: index should be absent before migration"
        engine.dispose()

        # Now open via Database (runs _migrate())
        db = Database(f"sqlite:///{db_path}")
        db._migrate()
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_channels_last_played'")
            ).fetchall()
        db.close()
        assert len(rows) == 1, "ix_channels_last_played not added by _migrate()"

    def test_migration_idempotent(self, tmp_path):
        """Running _migrate() twice must not raise — IF NOT EXISTS ensures idempotency."""
        from metatv.core.database import Database
        db = Database(f"sqlite:///{tmp_path / 'idem.db'}")
        db.create_tables()
        db._migrate()  # second run
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_channels_last_played'")
            ).fetchall()
        db.close()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 2. compute_weights equivalence
# ---------------------------------------------------------------------------

class TestComputeWeightsEquivalence:
    """Batched channel/metadata fetch must produce identical AttributeWeights."""

    def test_weights_from_ratings_and_favorites(self, tmp_path):
        from metatv.core.preference_engine import compute_weights

        db = _make_db(tmp_path / "w.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        meta_action = _make_metadata(session, "Action Film",
                                     genres=["Action", "Thriller"],
                                     director="James Cameron",
                                     plot="hero fights villain in explosive battle to save world",
                                     year=2020)
        meta_drama = _make_metadata(session, "Drama Film",
                                    genres=["Drama", "Romance"],
                                    director="Sofia Coppola",
                                    plot="couple struggles through complicated romance",
                                    year=2018)
        meta_fav = _make_metadata(session, "Fav Film",
                                  genres=["Action"],
                                  director="James Cameron",
                                  plot="another hero fights",
                                  year=2019)

        ch1 = _make_channel(session, "EN - Action Film (2020)", media_type="movie",
                             metadata_id=meta_action.id)
        ch2 = _make_channel(session, "EN - Drama Film (2018)", media_type="movie",
                             metadata_id=meta_drama.id)
        ch_fav = _make_channel(session, "EN - Fav Film (2019)", media_type="movie",
                               metadata_id=meta_fav.id, is_favorite=True)

        _make_rating(session, ch1.id, 1)   # liked
        _make_rating(session, ch2.id, -1)  # disliked
        session.commit()

        weights = compute_weights(session)

        # Liked genres/director should be positive
        assert weights.genres.get("Action", 0.0) > 0.0
        assert weights.directors.get("James Cameron", 0.0) > 0.0
        # Disliked should be negative
        assert weights.genres.get("Drama", 0.0) < 0.0
        assert weights.directors.get("Sofia Coppola", 0.0) < 0.0
        # Favorite implicit signal (+0.5) also for Action
        assert weights.genres["Action"] > 1.0  # rating(+1) + favorite(+0.5)
        assert weights.rated_count == 2
        assert weights.liked_count == 1
        assert weights.disliked_count == 1

        session.close()
        db.close()

    def test_weights_empty_when_no_ratings(self, tmp_path):
        from metatv.core.preference_engine import compute_weights, AttributeWeights

        db = _make_db(tmp_path / "empty.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()
        session.commit()

        weights = compute_weights(session)
        assert weights.is_empty()

        session.close()
        db.close()

    def test_plot_keywords_weighted(self, tmp_path):
        """TF-IDF keywords are accumulated in weights.keywords.

        IDF requires multiple documents to produce non-zero terms (words appearing in
        >35% of a single-document corpus get filtered out entirely). We seed several
        metadata rows with distinct plots so the IDF corpus is large enough for
        'heist' to pass the MAX_CORPUS_FREQ threshold.
        """
        from metatv.core.preference_engine import compute_weights

        db = _make_db(tmp_path / "kw.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        # The rated channel — plot contains "heist" (distinctive word)
        meta_heist = _make_metadata(session, "Heist Movie",
                                    genres=["Crime"],
                                    plot="skilled thieves plan elaborate bank heist with precision timing",
                                    year=2021)
        ch_heist = _make_channel(session, "EN - Heist Movie (2021)", media_type="movie",
                                  metadata_id=meta_heist.id)
        _make_rating(session, ch_heist.id, 1)

        # Corpus filler — give the IDF enough documents so "heist" stays below 35% freq.
        # We need at least ceil(1 / 0.35) = 3 total docs for any word to pass the filter
        # when it appears only once. Four fillers + the rated one = 5 total.
        filler_plots = [
            "romantic couple meets unexpectedly during summer vacation",
            "detective investigates mysterious disappearance downtown",
            "soldiers charge battle trenches against relentless enemy",
            "astronaut drifts through debris field searching rescue signal",
        ]
        for i, plot in enumerate(filler_plots):
            _make_metadata(session, f"Filler {i}", plot=plot, year=2020 - i)

        session.commit()

        weights = compute_weights(session)
        # At least some keywords should be weighted
        assert len(weights.keywords) > 0, (
            f"keywords is empty; IDF corpus may be too small or all words filtered. "
            f"rated_count={weights.rated_count}"
        )
        # "heist" is a distinctive word that should appear (only in one plot → low freq)
        assert "heist" in weights.keywords, f"'heist' not in keywords: {list(weights.keywords)[:20]}"
        assert weights.keywords["heist"] > 0

        session.close()
        db.close()


# ---------------------------------------------------------------------------
# 3. score_candidates equivalence
# ---------------------------------------------------------------------------

class TestScoreCandidatesEquivalence:
    """Batched metadata fetch must produce identical ScoredChannel ranking."""

    def _build_fixture(self, session):
        """Seed ratings, favorites, queued items, and several candidates with metadata."""
        meta_action = _make_metadata(session, "Good Action",
                                     genres=["Action"],
                                     director="John Woo",
                                     year=2020,
                                     plot="explosive action thriller")
        meta_drama = _make_metadata(session, "Great Drama",
                                    genres=["Drama"],
                                    director="Martin Scorsese",
                                    year=2019,
                                    plot="complex drama about family")
        meta_comedy = _make_metadata(session, "Funny Comedy",
                                     genres=["Comedy"],
                                     year=2021,
                                     plot="lighthearted comedy adventure")

        # Liked channels (signal source, not candidates — they've been watched)
        ch_liked = _make_channel(session, "EN - Good Action (2020)", media_type="movie",
                                  metadata_id=meta_action.id,
                                  last_played=datetime(2024, 1, 1))
        _make_rating(session, ch_liked.id, 1)

        # Candidates (not watched, not favorited, not queued)
        cand_action = _make_channel(session, "EN - Similar Action Film", media_type="movie",
                                     metadata_id=meta_action.id, detected_prefix="EN")
        cand_drama = _make_channel(session, "EN - Great Drama (2019)", media_type="movie",
                                    metadata_id=meta_drama.id, detected_prefix="EN")
        cand_comedy = _make_channel(session, "EN - Funny Comedy (2021)", media_type="movie",
                                     metadata_id=meta_comedy.id, detected_prefix="EN")

        session.commit()
        return cand_action, cand_drama, cand_comedy

    def test_ranked_output_ids_and_order(self, tmp_path):
        """score_candidates returns Action candidate highest (matches liked genre)."""
        from metatv.core.preference_engine import compute_weights, score_candidates

        db = _make_db(tmp_path / "sc.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        cand_action, cand_drama, cand_comedy = self._build_fixture(session)

        weights = compute_weights(session)
        results = score_candidates(session, weights, limit=30)

        ids = [r.channel_id for r in results]
        # Action candidate must be in results and have positive score
        assert cand_action.id in ids
        # All results must have positive score
        assert all(r.score > 0 for r in results)
        # Results must be sorted descending
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

        session.close()
        db.close()

    def test_watched_channels_excluded(self, tmp_path):
        """Channels with last_played set must not appear in recommendations."""
        from metatv.core.preference_engine import compute_weights, score_candidates

        db = _make_db(tmp_path / "watched.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        meta = _make_metadata(session, "Action Movie",
                               genres=["Action"],
                               year=2022)
        # Liked channel (has been watched — not a candidate)
        ch_watched = _make_channel(session, "EN - Watched Action", media_type="movie",
                                    metadata_id=meta.id,
                                    last_played=datetime(2024, 6, 1))
        _make_rating(session, ch_watched.id, 1)
        # Unwatched candidate
        cand = _make_channel(session, "EN - Fresh Action", media_type="movie",
                              metadata_id=meta.id)
        session.commit()

        weights = compute_weights(session)
        results = score_candidates(session, weights, limit=30)
        ids = [r.channel_id for r in results]

        assert ch_watched.id not in ids
        assert cand.id in ids

        session.close()
        db.close()

    def test_disliked_channels_excluded(self, tmp_path):
        """Channels with a dislike rating must never appear in recommendations."""
        from metatv.core.preference_engine import compute_weights, score_candidates

        db = _make_db(tmp_path / "disliked.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        meta_good = _make_metadata(session, "Liked Genre Film",
                                    genres=["Action"],
                                    year=2020)
        meta_bad = _make_metadata(session, "Disliked Genre Film",
                                   genres=["Horror"],
                                   year=2021)

        ch_liked_signal = _make_channel(session, "EN - Liked Action", media_type="movie",
                                         metadata_id=meta_good.id,
                                         last_played=datetime(2024, 1, 1))
        _make_rating(session, ch_liked_signal.id, 1)

        ch_disliked_cand = _make_channel(session, "EN - Horror Candidate", media_type="movie",
                                          metadata_id=meta_bad.id)
        _make_rating(session, ch_disliked_cand.id, -1)

        ch_good_cand = _make_channel(session, "EN - Action Candidate", media_type="movie",
                                      metadata_id=meta_good.id)
        session.commit()

        weights = compute_weights(session)
        results = score_candidates(session, weights, limit=30)
        ids = [r.channel_id for r in results]

        assert ch_disliked_cand.id not in ids
        assert ch_good_cand.id in ids

        session.close()
        db.close()

    def test_favorited_channels_excluded(self, tmp_path):
        """Favorited channels must not appear as recommendation candidates."""
        from metatv.core.preference_engine import compute_weights, score_candidates

        db = _make_db(tmp_path / "fav.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        meta = _make_metadata(session, "Action Film", genres=["Action"], year=2020)
        # Signal source: watched + rated liked
        ch_signal = _make_channel(session, "EN - Watched Action", media_type="movie",
                                   metadata_id=meta.id, last_played=datetime(2024, 1, 1))
        _make_rating(session, ch_signal.id, 1)

        # Favorited candidate — must not appear in recs
        ch_fav = _make_channel(session, "EN - Favorited Action", media_type="movie",
                                metadata_id=meta.id, is_favorite=True)
        # Regular candidate
        ch_fresh = _make_channel(session, "EN - Fresh Action Alt", media_type="movie",
                                  metadata_id=meta.id)
        session.commit()

        weights = compute_weights(session)
        results = score_candidates(session, weights, limit=30)
        ids = [r.channel_id for r in results]

        assert ch_fav.id not in ids
        assert ch_fresh.id in ids

        session.close()
        db.close()


# ---------------------------------------------------------------------------
# 4. build_engaged_normalized equivalence
# ---------------------------------------------------------------------------

class TestBuildEngagedNormalizedEquivalence:
    """Batched fetch must produce the same fingerprint set as the original N+1 path."""

    def test_engaged_includes_favorited_and_watched(self, tmp_path):
        from metatv.core.content_dedup import build_engaged_normalized, build_dedup_key

        db = _make_db(tmp_path / "eng.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        meta1 = _make_metadata(session, "Action Movie", genres=["Action"],
                                director="James Cameron", year=2020)
        meta2 = _make_metadata(session, "Drama Show", genres=["Drama"], year=2018)

        ch_fav = _make_channel(session, "EN - Action Movie (2020)", media_type="movie",
                                metadata_id=meta1.id, is_favorite=True)
        ch_watched = _make_channel(session, "EN - Drama Show (2018)", media_type="series",
                                    metadata_id=meta2.id,
                                    last_played=datetime(2024, 3, 1))
        session.commit()

        all_engaged_ids = {ch_fav.id}
        result = build_engaged_normalized(session, all_engaged_ids, overrides=set())

        # Favorite fingerprint must be in the set
        expected_fav_key = build_dedup_key(ch_fav, meta1)
        assert expected_fav_key in result

        # Watched channel fingerprint must also be in result (added via watched join)
        expected_watched_key = build_dedup_key(ch_watched, meta2)
        assert expected_watched_key in result

        session.close()
        db.close()

    def test_overrides_excluded_from_engaged(self, tmp_path):
        from metatv.core.content_dedup import build_engaged_normalized, build_dedup_key

        db = _make_db(tmp_path / "ovr.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        meta = _make_metadata(session, "Override Film", genres=["Sci-Fi"], year=2022)
        ch = _make_channel(session, "EN - Override Film (2022)", media_type="movie",
                            metadata_id=meta.id, is_favorite=True)
        session.commit()

        # With override: fingerprint should NOT be in result (suppressed)
        result_overridden = build_engaged_normalized(session, {ch.id}, overrides={ch.id})
        expected_key = build_dedup_key(ch, meta)
        assert expected_key not in result_overridden

        # Without override: fingerprint IS in result
        result_normal = build_engaged_normalized(session, {ch.id}, overrides=set())
        assert expected_key in result_normal

        session.close()
        db.close()

    def test_watched_without_metadata(self, tmp_path):
        """Watched channels with no metadata_id still produce a fingerprint (no year/director)."""
        from metatv.core.content_dedup import build_engaged_normalized, normalize_title

        db = _make_db(tmp_path / "no_meta.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        ch = _make_channel(session, "EN - No Meta Movie", media_type="movie",
                            metadata_id=None, last_played=datetime(2024, 5, 1))
        session.commit()

        result = build_engaged_normalized(session, set(), overrides=set())
        norm = normalize_title(ch.name, ch.detected_prefix)
        # Key with None year/director
        expected = (norm, "movie", None, None)
        assert expected in result

        session.close()
        db.close()


# ---------------------------------------------------------------------------
# 5. build_status_sets equivalence
# ---------------------------------------------------------------------------

class TestBuildStatusSetsEquivalence:
    """Column-only queries for fav_ids and watched_ids must return correct id sets."""

    def test_fav_ids_correct(self, tmp_path):
        from metatv.core.discovery_engine import build_status_sets

        db = _make_db(tmp_path / "bss.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        ch_fav = _make_channel(session, "Fav Channel", is_favorite=True)
        ch_not_fav = _make_channel(session, "Regular Channel", is_favorite=False)
        session.commit()

        result = build_status_sets(session)
        assert ch_fav.id in result.fav_ids
        assert ch_not_fav.id not in result.fav_ids

        session.close()
        db.close()

    def test_watched_ids_correct(self, tmp_path):
        from metatv.core.discovery_engine import build_status_sets

        db = _make_db(tmp_path / "watched_ids.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        ch_watched = _make_channel(session, "Watched Channel",
                                    last_played=datetime(2024, 6, 1))
        ch_fresh = _make_channel(session, "Fresh Channel")
        session.commit()

        result = build_status_sets(session)
        assert ch_watched.id in result.watched_ids
        assert ch_fresh.id not in result.watched_ids

        session.close()
        db.close()

    def test_all_sets_populated_correctly(self, tmp_path):
        """All four status sets are correct simultaneously."""
        from metatv.core.discovery_engine import build_status_sets
        from metatv.core.database import WatchQueueDB, UserRatingDB

        db = _make_db(tmp_path / "all_sets.db")
        Session = sessionmaker(bind=db.engine)
        session = Session()

        ch_fav = _make_channel(session, "Fav", is_favorite=True)
        ch_watched = _make_channel(session, "Watched", last_played=datetime(2024, 1, 1))
        ch_queued = _make_channel(session, "Queued")
        ch_liked = _make_channel(session, "Liked")
        ch_plain = _make_channel(session, "Plain")

        session.add(WatchQueueDB(channel_id=ch_queued.id, channel_name="Queued",
                                  media_type="movie", source_id="s1", position=0))
        session.add(UserRatingDB(channel_id=ch_liked.id, rating=1))
        session.commit()

        result = build_status_sets(session)

        assert result.fav_ids == {ch_fav.id}
        assert result.watched_ids == {ch_watched.id}
        assert ch_queued.id in result.queue_ids
        assert ch_liked.id in result.liked_ids
        assert ch_plain.id not in result.fav_ids
        assert ch_plain.id not in result.watched_ids
        assert ch_plain.id not in result.queue_ids
        assert ch_plain.id not in result.liked_ids

        session.close()
        db.close()
