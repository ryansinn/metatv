"""Behavioral tests for classify_channel_content_type() (Slice 3C).

Pure function — no DB, no Qt. Covers:
- detected_prefix (title-cased) matching a CONTENT_DESCRIPTOR_GROUPS member that is
  also in the EPG_CONTENT_TYPES namespace wins immediately, no keyword scan.
- A prefix outside the namespace (e.g. "Adult") does NOT short-circuit — falls through
  to the keyword scan.
- Keyword hits per type: News / Kids / Movies / Music via EPG_CONTENT_TYPE_KEYWORDS,
  Sports via the reused special_content.py sport/league loader (single source of truth,
  not a duplicated keyword list).
- None ("Other" at the UI layer) when nothing matches.
- Case-insensitivity and empty/None-safe inputs.
"""

from __future__ import annotations

from metatv.core.channel_name_utils import (
    EPG_CONTENT_TYPES,
    classify_channel_content_type,
)


# ---------------------------------------------------------------------------
# Priority 1 — detected_prefix already denotes a content-descriptor group
# ---------------------------------------------------------------------------

def test_prefix_group_wins_without_keyword_match():
    """A 'SPORTS' prefix classifies as Sports even though the name has no sport keyword."""
    assert classify_channel_content_type("Random Channel 12", "SPORTS") == "Sports"


def test_prefix_group_is_case_insensitive():
    assert classify_channel_content_type("Some Channel", "kids") == "Kids"
    assert classify_channel_content_type("Some Channel", "News") == "News"
    assert classify_channel_content_type("Some Channel", "MUSIC") == "Music"


def test_prefix_outside_namespace_falls_through_to_keyword_scan():
    """'Adult'/'Religious'/'24/7' are CONTENT_DESCRIPTOR_GROUPS members but not in our
    namespace — they must not short-circuit; the keyword scan still runs."""
    assert classify_channel_content_type("HBO Cinemax Late Show", "ADULT") == "Movies"
    assert classify_channel_content_type("Nothing Matches Here", "RELIGIOUS") is None


# ---------------------------------------------------------------------------
# Priority 2 — keyword scan fallback
# ---------------------------------------------------------------------------

def test_news_keyword_match():
    assert classify_channel_content_type("CNN International", None) == "News"
    assert classify_channel_content_type("Sky News HD", None) == "News"
    assert classify_channel_content_type("BBC News Channel", None) == "News"


def test_kids_keyword_match():
    assert classify_channel_content_type("Disney Junior", None) == "Kids"
    assert classify_channel_content_type("Cartoon Network", None) == "Kids"
    assert classify_channel_content_type("Nickelodeon", None) == "Kids"


def test_movies_keyword_match():
    assert classify_channel_content_type("HBO Cinemax", None) == "Movies"
    assert classify_channel_content_type("Starz Cinema", None) == "Movies"


def test_music_keyword_match():
    assert classify_channel_content_type("MTV Hits", None) == "Music"
    assert classify_channel_content_type("VH1 Classic", None) == "Music"


def test_sports_keyword_reuses_special_content_loader():
    """Sports keywords come from special_content.py's sport/league tables, not a
    duplicated list in channel_name_utils.py — verify a sport-specific term (not a
    generic word like "sports") still resolves via that loader."""
    assert classify_channel_content_type("US NBA Basketball Feed", None) == "Sports"
    assert classify_channel_content_type("UK Premier League Football", None) == "Sports"


def test_keyword_scan_is_case_insensitive():
    assert classify_channel_content_type("cnn INTERNATIONAL", None) == "News"


# ---------------------------------------------------------------------------
# Priority 3 — no match
# ---------------------------------------------------------------------------

def test_no_match_returns_none():
    assert classify_channel_content_type("Local Public Access 12", None) is None


def test_empty_and_none_inputs_are_safe():
    assert classify_channel_content_type("", None) is None
    assert classify_channel_content_type(None, None) is None
    assert classify_channel_content_type("", "") is None


# ---------------------------------------------------------------------------
# Namespace sanity
# ---------------------------------------------------------------------------

def test_epg_content_types_namespace():
    assert set(EPG_CONTENT_TYPES) == {"Sports", "News", "Kids", "Movies", "Music"}


def test_every_classification_is_in_namespace():
    samples = [
        ("CNN", None), ("Disney Junior", None), ("HBO", None), ("MTV", None),
        ("NBA Basketball", None), ("Random Channel", "SPORTS"),
    ]
    for name, prefix in samples:
        result = classify_channel_content_type(name, prefix)
        assert result is None or result in EPG_CONTENT_TYPES
