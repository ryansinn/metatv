"""Behavioral tests for the category→genre cross-walk (#77).

Verifies that provider_category and header compound strings now emit genre tags
for recognized canonical genres while:
- NOT destroying existing collection / region / language / platform tags (additive).
- NOT emitting genre tags for junk labels like "NETFLIX MOVIES" or "TOP IMDB".
- Using CONF_STRONG_PRIOR (not CONF_DENOTED) to rank category-derived genres below
  source-denoted raw_data["genre"] tags.
- Routing through recognized_genre() — the strict allowlist in filter_utils.

Also tests:
- filter_utils.recognized_genre() directly.
- KNOWN_GENRES is populated and consistent with _GENRE_NORM values.
- End-to-end via _collect_tags for the movie path (no raw_data["genre"]).
"""

from __future__ import annotations

import uuid
import pytest

from metatv.core.channel_name_utils import CONF_DENOTED, CONF_STRONG_PRIOR
from metatv.core.config import Config
from metatv.core.filter_utils import KNOWN_GENRES, recognized_genre
from metatv.core.migrations.tag_backfill import _collect_tags
from metatv.core.tag_decomposer import decompose


# ── Shared fixture ──────────────────────────────────────────────────────────── #

@pytest.fixture(scope="module")
def cfg():
    """A default Config() with the base prefix/quality/platform groups."""
    return Config()


# --------------------------------------------------------------------------- #
#  recognized_genre() — strict allowlist predicate                            #
# --------------------------------------------------------------------------- #

class TestRecognizedGenre:
    """filter_utils.recognized_genre() must accept known genres only."""

    def test_known_english_lowercase(self):
        """'action' (lowercase) → 'Action'."""
        assert recognized_genre("action") == "Action"

    def test_known_english_uppercase(self):
        """'ACTION' (uppercase) → 'Action'."""
        assert recognized_genre("ACTION") == "Action"

    def test_known_english_mixedcase(self):
        """'Action' (title-case) → 'Action'."""
        assert recognized_genre("Action") == "Action"

    def test_known_foreign_alias_drame(self):
        """'drame' (French for Drama) → 'Drama'."""
        assert recognized_genre("drame") == "Drama"

    def test_known_foreign_alias_drame_uppercase(self):
        """'DRAME' → 'Drama'."""
        assert recognized_genre("DRAME") == "Drama"

    def test_known_foreign_alias_komedie(self):
        """'KOMEDIE' (Polish Comedy) → 'Comedy'."""
        assert recognized_genre("KOMEDIE") == "Comedy"

    def test_known_foreign_alias_dramat(self):
        """'DRAMAT' (Polish Drama) → 'Drama'."""
        assert recognized_genre("DRAMAT") == "Drama"

    def test_known_thriller(self):
        """'thriller' → 'Thriller'."""
        assert recognized_genre("thriller") == "Thriller"

    def test_known_horror(self):
        """'horror' → 'Horror'."""
        assert recognized_genre("horror") == "Horror"

    def test_strict_rejection_netflix_movies(self):
        """'NETFLIX MOVIES' is NOT a genre → None."""
        assert recognized_genre("NETFLIX MOVIES") is None

    def test_strict_rejection_top_imdb(self):
        """'TOP IMDB' is NOT a genre → None."""
        assert recognized_genre("TOP IMDB") is None

    def test_strict_rejection_oscar_movies(self):
        """'OSCAR MOVIES' is NOT a genre → None."""
        assert recognized_genre("OSCAR MOVIES") is None

    def test_strict_rejection_empty_string(self):
        """Empty string → None."""
        assert recognized_genre("") is None

    def test_strict_rejection_whitespace(self):
        """Whitespace-only string → None."""
        assert recognized_genre("   ") is None

    def test_strict_rejection_movies_label(self):
        """'MOVIES' (common provider label, not a genre) → None."""
        assert recognized_genre("MOVIES") is None

    def test_strict_rejection_series_label(self):
        """'SERIES' is NOT a canonical genre → None."""
        assert recognized_genre("SERIES") is None


# --------------------------------------------------------------------------- #
#  KNOWN_GENRES — vocabulary integrity                                        #
# --------------------------------------------------------------------------- #

class TestKnownGenres:
    """KNOWN_GENRES must be a consistent, non-empty vocabulary."""

    def test_known_genres_is_non_empty(self):
        """KNOWN_GENRES must have at least the core English genres."""
        assert len(KNOWN_GENRES) >= 10

    def test_known_genres_contains_core_entries(self):
        """Core canonical genres must be present."""
        for genre in ("Drama", "Comedy", "Action", "Thriller", "Horror", "Documentary"):
            assert genre in KNOWN_GENRES, f"{genre!r} not in KNOWN_GENRES"

    def test_all_recognized_genre_results_in_known_genres(self):
        """Every value produced by recognized_genre() must be in KNOWN_GENRES."""
        test_inputs = ["action", "drama", "comedy", "drame", "komedie", "dramat", "thriller"]
        for s in test_inputs:
            result = recognized_genre(s)
            if result is not None:
                assert result in KNOWN_GENRES, (
                    f"recognized_genre({s!r})={result!r} not in KNOWN_GENRES"
                )


# --------------------------------------------------------------------------- #
#  _decompose_compound / decompose("provider_category") — genre cross-walk   #
# --------------------------------------------------------------------------- #

class TestCategoryGenreCrosswalk:
    """provider_category and header feeders produce genre tags for known genres."""

    # ── Additive: genre tags are added alongside existing tags ──────────────

    def test_en_action_thriller_has_genre_action(self, cfg):
        """|EN| ACTION/THRILLER category → genre:Action is emitted."""
        tags = decompose("provider_category", "|EN| ACTION/THRILLER", config=cfg)
        assert any(t == "genre" and v == "Action" for t, v, _ in tags), (
            f"Expected genre:Action in {tags}"
        )

    def test_en_action_thriller_has_genre_thriller(self, cfg):
        """|EN| ACTION/THRILLER category → genre:Thriller is emitted."""
        tags = decompose("provider_category", "|EN| ACTION/THRILLER", config=cfg)
        assert any(t == "genre" and v == "Thriller" for t, v, _ in tags), (
            f"Expected genre:Thriller in {tags}"
        )

    def test_en_action_thriller_has_language_english(self, cfg):
        """|EN| ACTION/THRILLER → language:English is NOT lost (additive)."""
        tags = decompose("provider_category", "|EN| ACTION/THRILLER", config=cfg)
        assert any(t == "language" and v == "English" for t, v, _ in tags), (
            f"language:English must not be dropped: {tags}"
        )

    def test_en_action_thriller_has_collection(self, cfg):
        """|EN| ACTION/THRILLER → collection tag is NOT lost (additive)."""
        tags = decompose("provider_category", "|EN| ACTION/THRILLER", config=cfg)
        assert any(t == "collection" for t, _, _ in tags), (
            f"collection tag must not be dropped: {tags}"
        )

    def test_fr_drame_yields_genre_drama(self, cfg):
        """|FR| DRAME → genre:Drama (cross-language foreign alias)."""
        tags = decompose("provider_category", "|FR| DRAME", config=cfg)
        assert any(t == "genre" and v == "Drama" for t, v, _ in tags), (
            f"Expected genre:Drama in {tags}"
        )

    def test_pl_komedie_yields_genre_comedy(self, cfg):
        """|PL| KOMEDIE → genre:Comedy (Polish Comedy alias)."""
        tags = decompose("provider_category", "|PL| KOMEDIE", config=cfg)
        assert any(t == "genre" and v == "Comedy" for t, v, _ in tags), (
            f"Expected genre:Comedy in {tags}"
        )

    def test_dramat_yields_genre_drama(self, cfg):
        """Category containing DRAMAT → genre:Drama (Polish Drama alias)."""
        tags = decompose("provider_category", "EN | DRAMAT", config=cfg)
        assert any(t == "genre" and v == "Drama" for t, v, _ in tags), (
            f"Expected genre:Drama in {tags}"
        )

    def test_plain_action_yields_genre(self, cfg):
        """Plain 'ACTION' as sole category token → genre:Action."""
        tags = decompose("provider_category", "ACTION", config=cfg)
        assert any(t == "genre" and v == "Action" for t, v, _ in tags), (
            f"Expected genre:Action in {tags}"
        )

    def test_horror_yields_genre(self, cfg):
        """'HORROR' → genre:Horror."""
        tags = decompose("provider_category", "HORROR", config=cfg)
        assert any(t == "genre" and v == "Horror" for t, v, _ in tags), (
            f"Expected genre:Horror in {tags}"
        )

    # ── Strict rejection: no genre for junk labels ──────────────────────────

    def test_netflix_movies_no_genre(self, cfg):
        """'NETFLIX MOVIES' must produce NO genre tag."""
        tags = decompose("provider_category", "NETFLIX MOVIES", config=cfg)
        genre_tags = [(t, v) for t, v, _ in tags if t == "genre"]
        assert not genre_tags, (
            f"'NETFLIX MOVIES' must not emit genre tags, got: {genre_tags}"
        )

    def test_top_imdb_oscar_movies_no_genre(self, cfg):
        """'TOP IMDB/OSCAR MOVIES' must produce NO genre tag."""
        tags = decompose("provider_category", "TOP IMDB/OSCAR MOVIES", config=cfg)
        genre_tags = [(t, v) for t, v, _ in tags if t == "genre"]
        assert not genre_tags, (
            f"'TOP IMDB/OSCAR MOVIES' must not emit genre tags, got: {genre_tags}"
        )

    def test_en_netflix_movies_no_genre(self, cfg):
        """'|EN| NETFLIX MOVIES' → language:English + collection, NO genre."""
        tags = decompose("provider_category", "|EN| NETFLIX MOVIES", config=cfg)
        genre_tags = [(t, v) for t, v, _ in tags if t == "genre"]
        assert not genre_tags, (
            f"'|EN| NETFLIX MOVIES' must not emit genre tags, got: {genre_tags}"
        )
        # But language and collection must still be present.
        assert any(t == "language" and v == "English" for t, v, _ in tags)
        assert any(t == "collection" for t, _, _ in tags)

    # ── Confidence: category-derived genre uses CONF_STRONG_PRIOR ───────────

    def test_category_genre_confidence_is_strong_prior(self, cfg):
        """Genre tag from provider_category uses CONF_STRONG_PRIOR, not CONF_DENOTED."""
        tags = decompose("provider_category", "ACTION", config=cfg)
        genre_conf = next((c for t, v, c in tags if t == "genre" and v == "Action"), None)
        assert genre_conf is not None, "Expected genre:Action tag"
        assert genre_conf == CONF_STRONG_PRIOR, (
            f"Category-derived genre should have CONF_STRONG_PRIOR ({CONF_STRONG_PRIOR}), "
            f"got {genre_conf}"
        )

    def test_raw_data_genre_has_higher_confidence_than_category(self, cfg):
        """raw_data['genre'] (CONF_DENOTED) ranks above category-derived genre (CONF_STRONG_PRIOR).

        We verify this by comparing the confidence constants directly — a source-denoted
        genre field (feeder="genre") uses CONF_DENOTED while a category-inferred genre
        uses CONF_STRONG_PRIOR, so CONF_DENOTED > CONF_STRONG_PRIOR.
        """
        # genre feeder uses CONF_DENOTED
        genre_feeder_tags = decompose("genre", "Action", config=cfg)
        genre_conf = next((c for t, v, c in genre_feeder_tags if t == "genre"), None)
        assert genre_conf == CONF_DENOTED

        # category feeder uses CONF_STRONG_PRIOR for genre cross-walk
        cat_feeder_tags = decompose("provider_category", "ACTION", config=cfg)
        cat_genre_conf = next((c for t, v, c in cat_feeder_tags if t == "genre"), None)
        assert cat_genre_conf == CONF_STRONG_PRIOR

        assert CONF_DENOTED > CONF_STRONG_PRIOR, (
            "Source-denoted genre must rank above category-inferred genre"
        )

    # ── No duplicates ────────────────────────────────────────────────────────

    def test_no_duplicate_genre_tags(self, cfg):
        """No duplicate (genre, value) pairs from a single compound category."""
        tags = decompose("provider_category", "ACTION | ACTION/THRILLER", config=cfg)
        genre_pairs = [(t, v) for t, v, _ in tags if t == "genre"]
        assert len(genre_pairs) == len(set(genre_pairs)), (
            f"Duplicate genre tags found: {genre_pairs}"
        )

    # ── header feeder also produces genre cross-walk ─────────────────────────

    def test_header_feeder_also_applies(self, cfg):
        """The genre cross-walk applies to the header feeder as well."""
        tags = decompose("header", "## DRAMA ##", config=cfg)
        assert any(t == "genre" and v == "Drama" for t, v, _ in tags), (
            f"Expected genre:Drama from header feeder: {tags}"
        )


# --------------------------------------------------------------------------- #
#  End-to-end via _collect_tags — the movie path (no raw_data["genre"])       #
# --------------------------------------------------------------------------- #

class TestMoviePathEndToEnd:
    """Verify the movie genre path: category→genre cross-walk for movie-shaped inputs.

    Before #77, a movie channel with raw_data={} (no genre field) produced ZERO
    genre tags.  After this change, a movie with category='|EN| ACTION/THRILLER'
    should produce genre:Action and genre:Thriller via the provider_category feeder.
    """

    def test_movie_shape_no_raw_genre_gets_genre_from_category(self, cfg):
        """Movie-shaped channel (raw_data={}, no genre field) gains genre from category."""
        tags = _collect_tags(
            config=cfg,
            category="|EN| ACTION/THRILLER",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data={},  # no genre field — movie path
        )
        type_value_feeder = [(t, v, f) for t, v, f in tags]
        # Should now include genre:Action and genre:Thriller from provider_category
        assert any(t == "genre" and v == "Action" for t, v, f in type_value_feeder), (
            f"Expected genre:Action for movie path, got: {type_value_feeder}"
        )
        assert any(t == "genre" and v == "Thriller" for t, v, f in type_value_feeder), (
            f"Expected genre:Thriller for movie path, got: {type_value_feeder}"
        )
        # Feeder must be 'provider_category'
        genre_feeders = {f for t, v, f in type_value_feeder if t == "genre"}
        assert "provider_category" in genre_feeders, (
            f"Genre tags must carry provider_category feeder, got feeders: {genre_feeders}"
        )

    def test_movie_shape_none_raw_data_gets_genre_from_category(self, cfg):
        """Movie-shaped channel (raw_data=None) also gains genre from category."""
        tags = _collect_tags(
            config=cfg,
            category="FR | DRAME",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,  # None — old-style movie path
        )
        assert any(t == "genre" and v == "Drama" for t, v, f in tags), (
            f"Expected genre:Drama for FR | DRAME movie path, got: {tags}"
        )

    def test_platform_only_category_no_genre(self, cfg):
        """A platform-only category like 'NETFLIX | HD' produces NO genre tag."""
        tags = _collect_tags(
            config=cfg,
            category="NETFLIX | HD",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
        )
        genre_tags = [(t, v) for t, v, f in tags if t == "genre"]
        assert not genre_tags, (
            f"Platform-only category 'NETFLIX | HD' must not produce genre tags, got: {genre_tags}"
        )

    def test_raw_data_genre_and_category_genre_both_present(self, cfg):
        """When both raw_data genre and category genre exist, both are captured.

        The tag repository will merge them as feeders; here we verify _collect_tags
        captures both the 'genre' feeder (from raw_data) and the 'provider_category'
        feeder (from the category cross-walk) for the same (genre, Action) pair.
        """
        tags = _collect_tags(
            config=cfg,
            category="|EN| ACTION/THRILLER",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data={"genre": "Action"},  # both paths for Action
        )
        # Should have two entries for (genre, Action) — one per feeder
        action_feeders = {f for t, v, f in tags if t == "genre" and v == "Action"}
        assert "genre" in action_feeders, "genre feeder must appear from raw_data"
        assert "provider_category" in action_feeders, (
            "provider_category feeder must appear from category cross-walk"
        )

    def test_series_category_genre_also_works(self, cfg):
        """The cross-walk also covers series (not just movies)."""
        tags = _collect_tags(
            config=cfg,
            category="|FR| DRAME",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data={"genre": "Drama"},  # series: has raw_data genre
        )
        # Both feeders should corroborate genre:Drama
        drama_feeders = {f for t, v, f in tags if t == "genre" and v == "Drama"}
        assert "genre" in drama_feeders
        assert "provider_category" in drama_feeders
