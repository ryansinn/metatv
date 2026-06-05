"""Tests for _GENRE_NORM: non-English genre strings → canonical English labels.

The normalize_genre() function and _GENRE_NORM dict live in
metatv/core/repositories/channel.py. They are applied when building filter-panel
genre counts (get_prefix_stats) and when a genre chip is clicked in the details pane.

Design note: _GENRE_NORM is the single canonical record of foreign-language genre
mappings. The i18n layer (future) translates the other direction: English canonical →
display language. This test suite enforces that every known non-English genre variant
maps to the correct English canonical form.
"""

import pytest
from metatv.core.repositories.channel import normalize_genre


# ── French ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Drame",           "Drama"),
    ("drame",           "Drama"),
    ("Comédie",         "Comedy"),
    ("comédie",         "Comedy"),
    ("Documentaire",    "Documentary"),
    ("Mystère",         "Mystery"),
    ("mystère",         "Mystery"),
    ("Horreur",         "Horror"),
])
def test_french_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"{raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── German ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Komödie",         "Comedy"),
    ("Dokumentär",      "Documentary"),
    ("Dokumentar",      "Documentary"),
])
def test_german_genres(raw, expected):
    assert normalize_genre(raw) == expected


# ── Spanish / Italian ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Documental",      "Documentary"),
    ("Comedia",         "Comedy"),
    ("Dramma",          "Drama"),
    ("Commedia",        "Comedy"),
    ("Animación",       "Animation"),
    ("Animazione",      "Animation"),
])
def test_spanish_italian_genres(raw, expected):
    assert normalize_genre(raw) == expected


# ── Arabic script ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("دراما",           "Drama"),
    ("ﺩﺭاﻣﺎ",           "Drama"),     # presentation-form variant
    ("كوميديا",         "Comedy"),
    ("ﻛﻮﻣﻴﺪﻱ",         "Comedy"),    # presentation-form variant
    ("وثائقي",          "Documentary"),
    ("جريمة",           "Crime"),
    ("رعب",             "Horror"),
    ("إثارة",           "Thriller"),
    ("رومانسي",         "Romance"),
    ("رياضة",           "Sport"),
])
def test_arabic_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Arabic genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Pass-through for already-English and unknown ──────────────────────────────

def test_english_passthrough():
    """Known English genres should pass through unchanged."""
    for g in ("Drama", "Comedy", "Documentary", "Crime", "Horror", "Sport"):
        assert normalize_genre(g) == g


def test_unknown_genre_passthrough():
    """Unknown genres are returned as-is (no silent data loss)."""
    assert normalize_genre("SomeFutureGenre") == "SomeFutureGenre"


# ── Compound genres split by caller, each part normalized ────────────────────

def test_normalize_is_applied_per_leaf():
    """normalize_genre() is called on individual leaves after splitting on ,/
    This test confirms the function handles each leaf correctly in isolation."""
    assert normalize_genre("Drame") == "Drama"
    assert normalize_genre("Crime") == "Crime"   # English passes through
    assert normalize_genre("دراما") == "Drama"
    assert normalize_genre("جريمة") == "Crime"
