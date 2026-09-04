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
    def __init__(self, name: str, category: str = "", media_type: str = "live"):
        self.name = name
        self.category = category
        self.media_type = media_type


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


# --------------------------------------------------------------------------- #
# FloSports vertical titles (2026-09-03) — real rows from the owner's DB.
#
# Whole-token matching correctly refuses to see "football" inside
# "flofootball", so 1,370 of 1,960 FLSP rows classified as nothing and
# vanished from the Sports view. Each FloSports vertical needs its own
# compound keyword rather than relying on the base sport word to reach in.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,sport", [
    ("(FLSP 980) | flofootball: 2026 Chaffey College vs Santa Ana College "
     "(Non-Conference) (2026-09-05 21:00:10)", "american_football"),
    ("| flovolleyball: 2026 X vs Y", "volleyball"),
    ("| floswimming: 2026 X vs Y", "swimming"),
    ("| flotrack: 2026 X vs Y", "track"),
    ("(FLSP 983) | floracing: 2026 CARS Tour West at Tri_City Speedway",
     "racing"),
    ("| flograppling: 2026 X vs Y", "mma"),
])
def test_flosports_vertical_titles_classify_to_their_sport(name, sport):
    assert _parse(name)["sport_type"] == sport


def test_flo_network_wrestling_passes_the_gate_and_classifies():
    """16 "| wrestling: …" rows failed ``detect_sports_channel`` even though
    "wrestling" was already a keyword in ``parse_sports_channel`` — the gate
    and the keyword map are separate sets (see ``special_content.py``'s
    ``SPORTS_GATE_TOKENS``)."""
    from metatv.core.special_content import detect_sports_channel

    channel = _Channel(
        "(FLSP 994) | wrestling: Queen of Hearts (Mat 4)", "US| FLO NETWORK")
    assert detect_sports_channel(channel) is True
    assert parse_sports_channel(channel)["sport_type"] == "wrestling"


@pytest.mark.parametrize("name", ["Florida News 24/7", "Flower Garden 4K"])
def test_flo_prefix_additions_do_not_gate_unrelated_names(name):
    """The bare stem "flo" is deliberately never added — it would reach
    "florida" and "flower". None of the new whole-token flo-vertical/
    flosports/flo-network entries may match these either."""
    from metatv.core.special_content import detect_sports_channel

    assert detect_sports_channel(_Channel(name)) is False


# --------------------------------------------------------------------------- #
# Owner rulings, 2026-09-03: "fight" leaves the gate vocabulary entirely, and
# VOD (movie/series) can never enter the sports population — a title on
# demand is not "on now". Measured before the fix: 4,611 movies + 421 series
# sat in special_view='sports', including Netflix cartoons gated in only by
# the word "Fight" in their titles.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,media_type,category", [
    ("NF - Amend: The Fight for America", "series", "|MULTI| NETFLIX SERIES"),
    ("NF - Asterix & Obelix: The Big Fight (2025)", "series",
     "|MULTI| NETFLIX SERIES"),
])
def test_vod_fight_titles_never_gate_into_sports(name, media_type, category):
    """A real row that used to false-positive on both rulings at once: a
    Netflix VOD title containing "fight"."""
    from metatv.core.special_content import detect_sports_channel

    assert detect_sports_channel(_Channel(name, category, media_type)) is False


def test_fight_alone_no_longer_gates_a_live_channel():
    """The deliberate recall loss, pinned so the ruling cannot silently
    regress: a live channel named only "FIGHT ..." no longer auto-classifies
    as sports, because "fight" is no longer gate vocabulary at all."""
    from metatv.core.special_content import detect_sports_channel

    assert detect_sports_channel(_Channel("FIGHT NETWORK", media_type="live")) is False


def test_ufc_still_gates_a_live_channel_via_its_own_keyword():
    """"fight" left the gate, but "ufc" is untouched and still classifies —
    removing one keyword must not touch its neighbours."""
    from metatv.core.special_content import detect_sports_channel

    channel = _Channel("UFC FIGHT PASS 1", media_type="live")
    assert detect_sports_channel(channel) is True


def test_vod_never_enters_the_sports_population():
    """A live sports channel stays classified; the identical name as a movie
    is not — a series/movie cannot be "on now"."""
    from metatv.core.special_content import detect_sports_channel

    assert detect_sports_channel(_Channel("US| ESPN", media_type="live")) is True
    assert detect_sports_channel(_Channel("US| ESPN", media_type="movie")) is False
