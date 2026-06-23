"""Tests for _GENRE_NORM: non-English genre strings → canonical English labels.

The normalize_genre() function and _GENRE_NORM dict live in
metatv/core/filter_utils.py (single source of truth). They are applied when
building filter-panel genre counts (get_prefix_stats) and when a genre chip is
clicked in the details pane.

Design note: _GENRE_NORM is the single canonical record of foreign-language genre
mappings. The i18n layer (future) translates the other direction: English canonical →
display language. This test suite enforces that every known non-English genre variant
maps to the correct English canonical form.
"""

import pytest
from metatv.core.filter_utils import normalize_genre


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
    ("Kriminal",        "Crime"),
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
    ("دراما",               "Drama"),
    ("ﺩﺭاﻣﺎ",               "Drama"),       # presentation-form variant
    ("كوميديا",             "Comedy"),
    ("ﻛﻮﻣﻴﺪﻱ",             "Comedy"),      # presentation-form variant
    ("وثائقي",              "Documentary"),
    ("جريمة",               "Crime"),
    ("رعب",                 "Horror"),
    ("إثارة",               "Thriller"),
    ("رومانسي",             "Romance"),
    ("رياضة",               "Sport"),
    # Extended Arabic (high-count live values)
    ("حركة ومغامرة",        "Action & Adventure"),
    ("غموض",                "Mystery"),
    ("خيال علمي وفانتازيا", "Sci-Fi & Fantasy"),
    ("رسوم متحركة",         "Animation"),
    ("عائلي",               "Family"),
    ("حرب وسياسة",          "War & Politics"),
    ("واقع",                "Reality"),
    ("غربي",                "Western"),
    ("كوميدي",              "Comedy"),
    ("ﺗﺸﻮﻳﻖ ﻭﺇﺛﺎﺭﺓ",        "Thriller"),
])
def test_arabic_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Arabic genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Polish ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Kryminał",            "Crime"),
    ("Komedia",             "Comedy"),
    ("Akcja i Przygoda",    "Action & Adventure"),
    ("Animacja",            "Animation"),
    ("Tajemnica",           "Mystery"),
    ("Dokumentalny",        "Documentary"),
    ("Familijny",           "Family"),
])
def test_polish_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Polish genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Swedish / Scandinavian ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Komedi",              "Comedy"),
    ("Sci-Fi & Fantasi",    "Sci-Fi & Fantasy"),
    ("Mystik",              "Mystery"),
    ("Dokumentarfilm",      "Documentary"),
    ("Äventyr",             "Adventure"),
    ("Action & Äventyr",    "Action & Adventure"),
    ("Animerat",            "Animation"),
    ("Verklighet",          "Reality"),
    ("Brott",               "Crime"),
    ("Barn",                "Kids"),
    ("Familj",              "Family"),
    ("Mysterium",           "Mystery"),
    ("Krig & Politik",      "War & Politics"),
    ("Kriminalitet",        "Crime"),
    ("Västern",             "Western"),
])
def test_scandinavian_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Scandinavian genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Dutch ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Mysterie",            "Mystery"),
    ("Familie",             "Family"),
    ("Animatie",            "Animation"),
])
def test_dutch_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Dutch genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Slovak / Czech ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Kriminálny",          "Crime"),
    ("Mysteriózny",         "Mystery"),
    ("Akčný a Dobrodružný", "Action & Adventure"),
    ("Vojnový a Politický", "War & Politics"),
    ("Dráma",               "Drama"),
    ("Komédia",             "Comedy"),
])
def test_slovak_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Slovak genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Croatian / Bosnian / Serbian (Latin) ──────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Komedija",            "Comedy"),
    ("Akcija i avantura",   "Action & Adventure"),
    ("Rat i politika",      "War & Politics"),
    ("Misterija",           "Mystery"),
])
def test_croatian_serbian_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Croatian/Serbian genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Portuguese ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Mistério",            "Mystery"),
    ("Comédia",             "Comedy"),
    ("Animação",            "Animation"),
])
def test_portuguese_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Portuguese genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Greek ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Δράμα",               "Drama"),
    ("Μυστηρίου",           "Mystery"),
    ("Κωμωδία",             "Comedy"),
    ("Κινούμενα Σχέδια",    "Animation"),
    ("Ντοκυμαντέρ",         "Documentary"),
    ("Οικογενειακή",        "Family"),
    ("Αστυνομική",          "Crime"),
])
def test_greek_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Greek genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Russian / Cyrillic ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("драма",               "Drama"),
    ("комедия",             "Comedy"),
    ("детектив",            "Crime"),
    ("криминал",            "Crime"),
    ("Боевик и Приключения","Action & Adventure"),
    ("НФ и Фэнтези",        "Sci-Fi & Fantasy"),
    ("семейный",            "Family"),
])
def test_russian_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Russian genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Hebrew ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("דרמה",                "Drama"),
    ("קומדיה",              "Comedy"),
    ("מדע בדיוני ופנטזיה",  "Sci-Fi & Fantasy"),
    ("מסתורין",             "Mystery"),
    ("פשע",                 "Crime"),
    ("ילדים",               "Kids"),
    ("אקשן והרפתקאות",      "Action & Adventure"),
    ("משפחה",               "Family"),
])
def test_hebrew_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Hebrew genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Turkish ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Aksiyon & Macera",    "Action & Adventure"),
    ("Bilim Kurgu & Fantazi","Sci-Fi & Fantasy"),
    ("Suç",                 "Crime"),
    ("Gizem",               "Mystery"),
    ("Aile",                "Family"),
    ("Savaş & Politik",     "War & Politics"),
])
def test_turkish_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Turkish genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


# ── Romanian ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Dramă",               "Drama"),
    ("Acţiune & Aventuri",  "Action & Adventure"),
    ("Animaţie",            "Animation"),
    ("Crimă",               "Crime"),
])
def test_romanian_genres(raw, expected):
    assert normalize_genre(raw) == expected, f"Romanian genre {raw!r} → {normalize_genre(raw)!r}, want {expected!r}"


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


# ── Cross-language equivalence — key requirement ──────────────────────────────

def test_cross_language_equivalence():
    """Foreign-language variants must resolve to the SAME canonical as their English counterpart.

    This is the core invariant: filtering 'Crime' should also catch content
    tagged as 'Kryminał' (Polish) or 'غموض' (Arabic Mystery ... wait, that's Mystery).
    Spot-check the most important high-count mappings.
    """
    # Crime in three languages → same canonical
    assert normalize_genre("Kryminał") == normalize_genre("Crime")
    assert normalize_genre("Kriminalitet") == normalize_genre("Crime")
    assert normalize_genre("جريمة") == normalize_genre("Crime")

    # Mystery in three languages → same canonical
    assert normalize_genre("غموض") == normalize_genre("Mystery")
    assert normalize_genre("Mysterie") == normalize_genre("Mystery")
    assert normalize_genre("Tajemnica") == normalize_genre("Mystery")

    # Animation in three languages → same canonical
    assert normalize_genre("Animacja") == normalize_genre("Animation")
    assert normalize_genre("رسوم متحركة") == normalize_genre("Animation")
    assert normalize_genre("Animatie") == normalize_genre("Animation")

    # Action & Adventure compound in three languages → same canonical
    assert normalize_genre("حركة ومغامرة") == normalize_genre("Action & Adventure")
    assert normalize_genre("Akcja i Przygoda") == normalize_genre("Action & Adventure")
    assert normalize_genre("Aksiyon & Macera") == normalize_genre("Action & Adventure")


# ── Backfill version test ──────────────────────────────────────────────────────

def test_tag_backfill_version_bumped():
    """CURRENT_TAG_BACKFILL_VERSION must be >= 2 (bumped for cross-language genre expansion)."""
    from metatv.core.migrations.tag_backfill import CURRENT_TAG_BACKFILL_VERSION
    assert CURRENT_TAG_BACKFILL_VERSION >= 2, (
        f"Expected CURRENT_TAG_BACKFILL_VERSION >= 2, got {CURRENT_TAG_BACKFILL_VERSION}. "
        "Bump it when extending _GENRE_NORM so existing installs re-backfill."
    )
