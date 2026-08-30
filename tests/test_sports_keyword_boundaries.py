"""A sport keyword must match a whole token, not a substring.

``parse_sports_channel`` classified with ``if keyword in name``. Across the
35,181 channels tagged as sports that produced **2,089 league assignments** from
a keyword buried inside an unrelated word:

    'US| FANDUEL TV'           -> Europa League   FAND-UEL
    'CITY| ABC WBAY GREENBAY'  -> NBA             GREE-NBA-Y
    '4k| TF1 HDR/UHD/4K'       -> Formula 1       T-F1
    '4K - Conflict (2024)'     -> NFL             co-NFL-ict

Wiring the (already written, entirely unreferenced) Sports view over this would
have shipped a view where NBA lists Green Bay local stations.

After: 2,089 false league tags removed, 273 real ones gained, and AHL — already
in the definitions and never matching — resolves.
"""

from __future__ import annotations

import pytest

from metatv.core.special_content import parse_sports_channel


class _Channel:
    def __init__(self, name: str, category: str = ""):
        self.name = name
        self.category = category


def _parse(name: str, category: str = ""):
    return parse_sports_channel(_Channel(name, category))


# --------------------------------------------------------------------------- #
# The false positives, each named for the word that caused it.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,buried", [
    ("US| FANDUEL TV",          "uel inside FANDUEL"),
    ("CITY| ABC WBAY GREENBAY", "nba inside GREENBAY"),
    ("4k| TF1 HDR/UHD/4K",      "f1 inside TF1"),
    ("4K - Conflict (2024)",    "nfl inside Conflict"),
    ("AR| AL MAJD RAWDA",       "raw inside RAWDA"),
])
def test_a_keyword_buried_in_a_word_does_not_classify(name, buried):
    result = _parse(name)
    assert result["league_name"] is None, (
        f"{name!r} was assigned {result['league_name']!r} — {buried}"
    )


# --------------------------------------------------------------------------- #
# …without breaking the true positives.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,sport,league", [
    ("NHL| CALGARY FLAMES",     "hockey",     "NHL"),
    ("US| NBA LEAGUE PASS",     "basketball", "NBA"),
    ("4K| SKY SPORTS F1 UHD",   "racing",     "Formula 1"),
    ("UK| PREMIER LEAGUE TV",   "soccer",     "Premier League"),
    ("US| UFC FIGHT PASS",      "mma",        "UFC"),
])
def test_a_real_keyword_still_classifies(name, sport, league):
    result = _parse(name)
    assert result["sport_type"] == sport
    assert result["league_name"] == league


def test_the_ahl_finally_matches():
    """Already in the definitions, never matching.

    The keyword is written ``' ahl '`` — padded with spaces, which was a
    hand-rolled attempt at exactly the boundary this module now does properly.
    The channels are named ``AHL-TEAM|…``, and a leading space cannot match a
    hyphen, so all 64 came back ``unknown``. Stripping the padding and using a
    real boundary fixes it with no change to the definitions.
    """
    result = _parse("AHL-TEAM| ABBOTSFORD CANUCKS [ABB]")
    assert result["league_name"] == "AHL"


def test_a_keyword_may_be_bounded_by_punctuation_not_only_space():
    """``AHL-TEAM``, ``NHL|``, ``(NBA)`` — the boundary is "not alphanumeric",
    which is why lookarounds are used rather than ``\\b``: several keywords end
    in a digit, where ``\\b`` sits in the wrong place."""
    for name in ("AHL-TEAM| X", "AHL|X", "X (AHL)", "X [AHL]", "X.AHL.Y"):
        assert _parse(name)["league_name"] == "AHL", name


def test_a_digit_ending_keyword_is_bounded_correctly():
    """``f1`` must match "SPORTS F1" and not "TF1"."""
    assert _parse("UK| SKY SPORTS F1")["league_name"] == "Formula 1"
    assert _parse("FR| TF1")["league_name"] is None


def test_the_category_is_searched_too():
    """Classification reads name AND category — the fix must not drop one."""
    assert _parse("Some Channel", "|US| NBA")["league_name"] == "NBA"


def test_an_unclassified_channel_stays_visible():
    """``sport_type='unknown'`` is deliberate — the Sports view keeps them
    rather than silently excluding what it could not label."""
    assert _parse("US| RANDOM CHANNEL")["sport_type"] == "unknown"
