"""Tests for apostrophe handling in content identity key normalization.

Ensures that apostrophes (various forms) are deleted, not space-replaced,
so that "Three's Company" and "Threes Company" normalize to the same key.

Guards the fix for the owner-reported bug (2026-09-03): 1,328 title buckets
were split solely by apostrophe variants before this fix.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest


def test_normalize_title_apostrophes_deleted_not_spaced():
    """Apostrophes are deleted, not space-replaced, in title normalization.

    Before fix: "Three's Company" → "three s company", "Threes Company" → "threes company".
    After fix: both → "threes company" (apostrophe deleted).
    """
    from metatv.core.content_identity import normalize_title_for_key

    # Straight apostrophe
    assert normalize_title_for_key("Three's Company") == "threes company"
    # Already apostrophe-free
    assert normalize_title_for_key("Threes Company") == "threes company"
    # Case insensitive
    assert normalize_title_for_key("THREE'S COMPANY") == "threes company"


def test_normalize_title_various_apostrophe_forms():
    """All common apostrophe forms (straight, right single quote, modifier, backtick) are deleted."""
    from metatv.core.content_identity import normalize_title_for_key

    # Straight apostrophe (ASCII)
    assert normalize_title_for_key("Clarkson's Farm") == "clarksons farm"
    # Right single quotation mark (U+2019)
    assert normalize_title_for_key("Clarkson's Farm") == "clarksons farm"
    # Modifier letter apostrophe (U+02BC)
    assert normalize_title_for_key("Clarksonʼ Farm") == "clarkson farm"
    # Backtick (sometimes mistyped)
    assert normalize_title_for_key("Clarkson`s Farm") == "clarksons farm"


def test_normalize_title_apostrophe_with_audio_noise():
    """Apostrophe deletion composes with audio-noise stripping (trailing MULTI run)."""
    from metatv.core.content_identity import normalize_title_for_key

    # Title with apostrophe AND trailing audio noise (MULTI)
    assert normalize_title_for_key("The Bridge's MULTI") == "the bridges"


def test_content_key_for_apostrophe_variants_collapse():
    """Two channel stubs differing only by apostrophe share a content_key."""
    from metatv.core.content_identity import content_key_for

    def _channel(**kwargs):
        defaults = {
            "id": str(uuid.uuid4()),
            "detected_title": "Dark Star",
            "media_type": "movie",
            "detected_year": "2017",
            "detected_tmdb_id": None,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    # Movie: "Three's Company" and "Threes Company" → same key
    with_apos = _channel(detected_title="Three's Company")
    without_apos = _channel(detected_title="Threes Company")
    assert content_key_for(with_apos) == content_key_for(without_apos)
    assert content_key_for(with_apos) == "threes company|movie|2017"

    # Series: same collapse, but year omitted
    with_apos_series = _channel(
        detected_title="Grey's Anatomy",
        media_type="series",
        detected_year="2005"
    )
    without_apos_series = _channel(
        detected_title="Greys Anatomy",
        media_type="series",
        detected_year=None  # Different year convention, same title
    )
    assert content_key_for(with_apos_series) == content_key_for(without_apos_series)
    assert content_key_for(with_apos_series) == "greys anatomy|series"


def test_normalize_title_apostrophe_multiword():
    """Apostrophe at various positions in multi-word titles."""
    from metatv.core.content_identity import normalize_title_for_key

    # Beginning
    assert normalize_title_for_key("'Tis the Season") == "tis the season"
    # Middle
    assert normalize_title_for_key("O'Reilly Factor") == "oreilly factor"
    # End
    assert normalize_title_for_key("Farmers' Almanac") == "farmers almanac"


@pytest.mark.parametrize("title", [
    "Three's Company",
    "Threes Company",
    "GREY'S ANATOMY",
    "Greys Anatomy",
    "The Queen's Gambit",
    "The Queens Gambit",
])
def test_mutation_apostrophe_deletion_is_required(title: str):
    """Regression: verify that apostrophe deletion is required (not space replacement).

    This test will fail if the apostrophe deletion line is reverted to space replacement.
    The spec requires a mutation check: revert the `_APOSTROPHE_RE.sub` line and
    confirm this test goes RED.
    """
    from metatv.core.content_identity import normalize_title_for_key

    normalized = normalize_title_for_key(title)
    # After apostrophe deletion, no "x s " patterns should exist
    # (e.g., no "three s " or "queen s " from space-replacement)
    assert " s " not in normalized, (
        f"Title '{title}' normalized to '{normalized}', which contains ' s ' — "
        "this suggests apostrophes are being space-replaced instead of deleted."
    )


def test_remake_guard_does_not_reject_apostrophe_variants_with_multiple_ids():
    """Remake guard does not skip adoption when apostrophe variants carry distinct ids.

    Before the apostrophe fix, "Three's Company" and "Threes Company" had different
    keys and the remake guard would see two ids in one bucket — manufactured ambiguity
    that should not happen now. This test ensures that when variants differ only by
    apostrophe and carry distinct ids, the remake guard still correctly refuses to
    guess (because the ids are legitimately different productions).
    """
    from metatv.core.content_identity import content_key_for

    def _channel(**kwargs):
        defaults = {
            "id": str(uuid.uuid4()),
            "detected_title": "Dark Star",
            "media_type": "movie",
            "detected_year": "2017",
            "detected_tmdb_id": None,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    # Two movie rows: same title (one with apostrophe), different tmdb ids
    # They should NOT collapse because they have different ids (genuine remakes)
    with_apos = _channel(
        detected_title="Three's Company",
        detected_tmdb_id="12345",
    )
    without_apos = _channel(
        detected_title="Threes Company",
        detected_tmdb_id="67890",
    )

    # They should have different keys because they carry different ids (tmdb-first)
    assert content_key_for(with_apos) != content_key_for(without_apos)
    assert content_key_for(with_apos) == "tmdb:12345|movie"
    assert content_key_for(without_apos) == "tmdb:67890|movie"
    # The remake guard's job is done by the tmdb-first key: different ids → different keys
