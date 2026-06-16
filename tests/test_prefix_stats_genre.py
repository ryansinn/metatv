"""Behavioral tests for the genre-counting section of get_prefix_stats().

These tests verify that the streamed column-only query (yield_per) produces
the same results as the old full-ORM .all() — threshold applied, non-Latin
dropped, normalization applied, compound strings split correctly.

Uses a file-backed Database (not :memory:) per the CLAUDE.md rule, which
catches the DetachedInstanceError class of bugs that a pooled in-memory
engine masks.
"""
import uuid

import pytest

from metatv.core.database import Base, ChannelDB, Database
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "genre_stats_test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _ch(session, name: str, media_type: str, genre: str | None, provider_id: str = "p1") -> None:
    """Insert a minimal ChannelDB row with raw_data containing the given genre string."""
    raw = {"genre": genre} if genre is not None else {"other_key": "val"}
    session.add(ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=False,
        raw_data=raw,
    ))


def _run(db: Database, **kwargs) -> dict:
    """Run get_prefix_stats with all group dicts empty (genre-only focus)."""
    with db.session_scope(commit=False) as session:
        return RepositoryFactory(session).channels.get_prefix_stats(
            language_groups={},
            quality_groups={},
            platform_groups={},
            regional_groups={},
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Core behavioral test: threshold, normalization, non-Latin drop, split
# ---------------------------------------------------------------------------

def test_genre_counts_threshold_and_normalization(db):
    """genre_counts must apply threshold, normalization, and non-Latin filtering.

    Setup:
    - "Drama" × 15  → clears cnt≥10 threshold → stays as "Drama"
    - "Drame" × 12  → normalises to "Drama" → merged (Drama total = 27)
    - "Comédie" × 8 → normalises to "Comedy" → below threshold, dropped
    - "كوميديا" × 5 → normalises to "Comedy" → merged into Comedy (total 13, but wait
      we keep Comédie+Comedy together; see below for the intent)
    - "مسرح" × 20   → no mapping, non-Latin only → must be dropped entirely

    We keep Comedy deliberately below threshold by itself to check the merge vs
    threshold interaction: "Comédie"→Comedy(8) + "كوميديا"→Comedy(5) = 13 ≥ 10 → kept.
    """
    with db.session_scope() as session:
        # Drama: 15 raw "Drama" + 12 "Drame" (normalises to Drama) = 27 Drama total
        for i in range(15):
            _ch(session, f"Drama-En-{i}", "movie", "Drama")
        for i in range(12):
            _ch(session, f"Drama-Fr-{i}", "movie", "Drame")
        # Comedy: 8 French + 5 Arabic = 13 total Comedy → ≥ 10 → kept
        for i in range(8):
            _ch(session, f"Comedy-Fr-{i}", "movie", "Comédie")
        for i in range(5):
            _ch(session, f"Comedy-Ar-{i}", "movie", "كوميديا")
        # Non-Latin unmapped: 20 rows → must be dropped
        for i in range(20):
            _ch(session, f"NonLatin-{i}", "movie", "مسرح")

    result = _run(db)
    gc = result["genre_counts"]

    assert gc.get("Drama", 0) == 27, f"Drama total wrong: {gc}"
    assert gc.get("Comedy", 0) == 13, f"Comedy total wrong: {gc}"
    assert "مسرح" not in gc, "Non-Latin unmapped genre must be dropped"


def test_genre_counts_below_threshold_dropped(db):
    """Genres that appear fewer than 10 times must not appear in genre_counts."""
    with db.session_scope() as session:
        for i in range(9):
            _ch(session, f"Sci-{i}", "movie", "Sci-Fi & Fantasy")
    result = _run(db)
    assert "Sci-Fi & Fantasy" not in result["genre_counts"]


def test_genre_counts_compound_split(db):
    """Compound genre strings like 'Drama/Comedy' split on [,/] and count each leaf."""
    with db.session_scope() as session:
        # 10 rows with compound genre → both Drama and Comedy should each get 10
        for i in range(10):
            _ch(session, f"Compound-{i}", "movie", "Drama/Comedy")
    result = _run(db)
    gc = result["genre_counts"]
    assert gc.get("Drama", 0) == 10
    assert gc.get("Comedy", 0) == 10


def test_genre_counts_comma_split(db):
    """Compound genres separated by comma also split correctly."""
    with db.session_scope() as session:
        for i in range(10):
            _ch(session, f"CommaGenre-{i}", "series", "Drama,Thriller")
    result = _run(db)
    gc = result["genre_counts"]
    assert gc.get("Drama", 0) == 10
    assert gc.get("Thriller", 0) == 10


def test_genre_counts_excludes_hidden_channels(db):
    """Hidden channels must not contribute to genre_counts."""
    with db.session_scope() as session:
        # 10 hidden rows → should not count
        for i in range(10):
            ch = ChannelDB(
                id=str(uuid.uuid4()),
                source_id=str(uuid.uuid4()),
                provider_id="p1",
                name=f"Hidden-{i}",
                media_type="movie",
                is_hidden=True,
                raw_data={"genre": "Horror"},
            )
            session.add(ch)
    result = _run(db)
    assert "Horror" not in result["genre_counts"]


def test_genre_counts_excludes_live_channels(db):
    """Only movie/series channels contribute — live channels must be ignored."""
    with db.session_scope() as session:
        for i in range(10):
            _ch(session, f"Live-{i}", "live", "Drama")
    result = _run(db)
    assert "Drama" not in result["genre_counts"]


def test_genre_counts_provider_id_filter(db):
    """provider_id arg scopes genre_counts to that provider only."""
    with db.session_scope() as session:
        # 10 rows for provider p1, 20 for p2
        for i in range(10):
            _ch(session, f"P1-{i}", "movie", "Drama", provider_id="p1")
        for i in range(20):
            _ch(session, f"P2-{i}", "movie", "Drama", provider_id="p2")

    # Without filter → Drama = 30 (≥10, present)
    result_all = _run(db)
    assert result_all["genre_counts"].get("Drama", 0) == 30

    # Scoped to p1 → Drama = 10
    result_p1 = _run(db, provider_id="p1")
    assert result_p1["genre_counts"].get("Drama", 0) == 10

    # Scoped to p2 → Drama = 20
    result_p2 = _run(db, provider_id="p2")
    assert result_p2["genre_counts"].get("Drama", 0) == 20


def test_genre_counts_arabic_with_mapping_survives(db):
    """Arabic genres WITH a _GENRE_NORM mapping must appear in genre_counts."""
    with db.session_scope() as session:
        # "دراما" maps to "Drama"
        for i in range(10):
            _ch(session, f"ArabicDrama-{i}", "movie", "دراما")
    result = _run(db)
    gc = result["genre_counts"]
    assert gc.get("Drama", 0) == 10, (
        "Arabic genre with mapping should normalise to English and pass the threshold"
    )


def test_genre_counts_channels_without_raw_data_skipped(db):
    """Channels with raw_data=None are excluded by the SQL filter — no KeyError."""
    with db.session_scope() as session:
        # One channel with null raw_data (filtered out in SQL)
        session.add(ChannelDB(
            id=str(uuid.uuid4()),
            source_id=str(uuid.uuid4()),
            provider_id="p1",
            name="NullRaw",
            media_type="movie",
            is_hidden=False,
            raw_data=None,
        ))
        # 10 normal rows to ensure at least one genre clears the threshold
        for i in range(10):
            _ch(session, f"Normal-{i}", "movie", "Comedy")
    result = _run(db)
    # Should not raise; Comedy should appear
    assert result["genre_counts"].get("Comedy", 0) == 10


# ---------------------------------------------------------------------------
# excluded_provider_ids — active-source scoping applied to all aggregations
# ---------------------------------------------------------------------------

def _ch_full(session, name: str, provider_id: str, media_type: str = "live",
             genre: str | None = None, detected_prefix: str | None = None,
             detected_quality: str | None = None) -> None:
    """Insert a ChannelDB row with all stats-relevant fields set."""
    raw = {"genre": genre} if genre else {}
    session.add(ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=False,
        raw_data=raw if raw else None,
        detected_prefix=detected_prefix,
        detected_quality=detected_quality,
    ))


def test_excluded_provider_ids_scopes_all_aggregations(tmp_path):
    """excluded_provider_ids must exclude inactive-provider channels from every
    sub-count: total_channels, prefix_counts, quality_groups, and genre_counts.

    This is the regression guard for the bug where filter-panel counts reflected
    the full library while the channel list was scoped to active sources only.

    Two providers: provider A (active) and provider B (inactive/hidden).
    With no exclusion → counts span both.
    With excluded_provider_ids={"prov-b"} → only prov-a data survives.
    """
    path = tmp_path / "excl_prov_test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()

    try:
        with database.session_scope() as session:
            # Provider A: 5 live channels with EN prefix, 3 movies with Drama genre, HD quality
            for i in range(5):
                _ch_full(session, f"A-Live-{i}", "prov-a",
                         detected_prefix="EN", detected_quality=None)
            for i in range(3):
                _ch_full(session, f"A-Movie-{i}", "prov-a", media_type="movie",
                         genre="Drama", detected_prefix="EN", detected_quality="HD")

            # Provider B: 10 live channels with FR prefix, 15 movies with Comedy genre, SD quality
            for i in range(10):
                _ch_full(session, f"B-Live-{i}", "prov-b",
                         detected_prefix="FR", detected_quality=None)
            for i in range(15):
                _ch_full(session, f"B-Movie-{i}", "prov-b", media_type="movie",
                         genre="Comedy", detected_prefix="FR", detected_quality="SD")

        lang_groups = {"English": ["EN"], "French": ["FR"]}
        qual_groups = {"HD": ["HD", "FHD"], "SD": ["SD"]}

        def _run_stats(excl=None):
            with database.session_scope(commit=False) as session:
                return RepositoryFactory(session).channels.get_prefix_stats(
                    language_groups=lang_groups,
                    quality_groups=qual_groups,
                    platform_groups={},
                    regional_groups={},
                    excluded_provider_ids=excl,
                )

        # Without exclusion — all 33 channels visible
        stats_all = _run_stats()
        assert stats_all["total_channels"] == 33
        assert stats_all["prefix_counts"].get("EN", 0) == 8   # 5 live + 3 movie
        assert stats_all["prefix_counts"].get("FR", 0) == 25  # 10 live + 15 movie
        assert stats_all["quality_groups"].get("HD", 0) == 3
        assert stats_all["quality_groups"].get("SD", 0) == 15
        # Comedy = 15 ≥ 10 threshold; Drama = 3 < 10, so absent
        assert stats_all["genre_counts"].get("Comedy", 0) == 15
        assert "Drama" not in stats_all["genre_counts"]

        # With provider B excluded — only prov-a's 8 channels survive
        stats_a = _run_stats(excl={"prov-b"})
        assert stats_a["total_channels"] == 8, (
            f"Expected 8 (prov-a only), got {stats_a['total_channels']}"
        )
        assert stats_a["prefix_counts"].get("EN", 0) == 8
        assert "FR" not in stats_a["prefix_counts"], (
            "FR prefix (prov-b) must vanish when prov-b is excluded"
        )
        assert stats_a["quality_groups"].get("HD", 0) == 3
        assert stats_a["quality_groups"].get("SD", 0) == 0, (
            "SD quality (prov-b) must vanish when prov-b is excluded"
        )
        # Comedy (prov-b) drops out; Drama (prov-a) is only 3, still below threshold
        assert "Comedy" not in stats_a["genre_counts"], (
            "Comedy genre (prov-b only) must vanish when prov-b is excluded"
        )
        assert "Drama" not in stats_a["genre_counts"], (
            "Drama (prov-a, count=3) remains below the 10-count threshold"
        )
        # Language group for English should count only prov-a channels
        assert stats_a["language_groups"].get("English", 0) == 8
        assert "French" not in stats_a["language_groups"]

    finally:
        database.engine.dispose()
