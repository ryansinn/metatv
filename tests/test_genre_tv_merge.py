"""Behavioral tests for the TV-genre fold (#143).

Root cause: TMDB has no single "TV" genre, so providers fragment the concept
into ~15 near-duplicate labels — "TV program" (79), "TV programme" (66),
"TV Series" (42), "Television series" (26), "Program Tv" (9), the provider typo
"TV proramme" (7), plus the bare "PROGRAM"/"PROGRAMME"/"PROGRAME" forms.  Since
``normalize_genre`` passes unknown strings through unchanged, every one of these
survived as its own facet in the filter panel.

Fix: ``_GENRE_NORM`` in filter_utils.py now folds the whole family (LOWERCASED
keys) into ONE canonical "TV Show".  ``CURRENT_TAG_BACKFILL_VERSION`` was bumped
to 7 to force a re-tag of all source="generated" tags into the merged value.

These tests exercise the raw provider casing (not pre-lowercased strings) so
they prove the ``html.unescape(genre).lower()`` path in ``normalize_genre``.
"""

from __future__ import annotations

import pytest

from metatv.core.filter_utils import KNOWN_GENRES, normalize_genre
from metatv.core.migrations.tag_backfill import CURRENT_TAG_BACKFILL_VERSION


# ---------------------------------------------------------------------------
# 1. The whole fragmented family folds into "TV Show" — raw provider casing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "TV program",
    "TV programme",
    "TV Series",
    "Television series",
    "TV proramme",          # provider typo
    "TV programe",          # provider typo
    "Program Tv",
    "TV Show",
    "Tv Show",
    "TV SHOW",
    "TV series Television program",
    "PROGRAM",
    "Program",
    "programme",
    "PROGRAMME",
    "PROGRAME",             # provider typo
])
def test_tv_family_folds_to_tv_show(raw):
    """Every fragmented TV label (any provider casing) → canonical 'TV Show'."""
    assert normalize_genre(raw) == "TV Show", (
        f"normalize_genre({raw!r}) must fold to 'TV Show', "
        f"got {normalize_genre(raw)!r}"
    )


def test_tv_show_in_known_genres():
    """Adding 'TV Show' as a canonical value must extend the KNOWN_GENRES allowlist
    so the category→genre cross-walk can emit it."""
    assert "TV Show" in KNOWN_GENRES


# ---------------------------------------------------------------------------
# 2. Distinct, already-canonical genres must NOT be over-merged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Talk Show", "Talk Show"),
    ("Game Show", "Game Show"),      # #153 added "game show"→Game Show; still "Game Show"
    ("Music Show", "Music Show"),
    ("TV Movie", "TV Movie"),
    ("Show", "Show"),                # ambiguous bare "Show" — never folded
])
def test_distinct_genres_not_merged(raw, expected):
    """Genres outside the TV-program/series family must survive unchanged —
    proving the fold did not over-merge into 'TV Show'."""
    assert normalize_genre(raw) == expected, (
        f"normalize_genre({raw!r}) must stay {expected!r} (not folded into "
        f"'TV Show'), got {normalize_genre(raw)!r}"
    )


@pytest.mark.parametrize("raw,expected", [
    ("Reality Show", "Reality"),     # #153: 'Show' is noise-suffix → Reality
    ("Drama series", "Drama"),       # #153: 'series' is noise-suffix → Drama
])
def test_153_noise_suffix_folds(raw, expected):
    """#153 folds noise-suffixed variants into their base genre (this used to be
    asserted the other way in #143, before the owner-approved consolidation)."""
    assert normalize_genre(raw) == expected, (
        f"normalize_genre({raw!r}) must fold to {expected!r} (#153), "
        f"got {normalize_genre(raw)!r}"
    )


# ---------------------------------------------------------------------------
# 3. The backfill version was bumped so stored tags re-normalize
# ---------------------------------------------------------------------------

def test_backfill_version_at_least_7():
    """CURRENT_TAG_BACKFILL_VERSION must be >= 7 so existing source='generated'
    tags holding the old fragmented values are re-tagged into 'TV Show'."""
    assert CURRENT_TAG_BACKFILL_VERSION >= 7, (
        f"CURRENT_TAG_BACKFILL_VERSION is {CURRENT_TAG_BACKFILL_VERSION}, "
        "expected >= 7.  The TV-genre fold requires a re-backfill."
    )
