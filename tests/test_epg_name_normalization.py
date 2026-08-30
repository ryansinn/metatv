"""Two sources describing the same channel must produce the same key.

`normalize_channel_name` is what makes a guide entry and a channel row equal.
Measured on the owner's library it matched **2 of 17,951** ProSat channels
against a 260,275-programme guide, so scheduled recording did not work on the
source he actually watches live TV on. It missed on three counts at once:

    'OD| ESPN 4 ᴴᴰ'   (guide)    ->  'od| espn 4 ᴴᴰ'
    '|NL| ESPN 4 HD'  (channel)  ->  '|nl| espn 4'

the prefix survived (the separator class was `[★◉•·]` and never included `|`),
the superscript quality was invisible to an ASCII vocabulary, and it was a
second name vocabulary competing with the `parse_channel_name` that already
runs at ingestion.

After: 2,744 ProSat and 7,320 TREX channels match and pass the region gate.
"""

from __future__ import annotations

import pytest

from metatv.core.xmltv_parser import normalize_channel_name as norm


# --------------------------------------------------------------------------- #
# The pairs from the owner's own data.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("guide,channel", [
    ("OD| ESPN 4 ᴴᴰ",              "|NL| ESPN 4 HD"),
    ("US| HISTORY HD",             "|US| History"),
    ("LAT| ESPN DEPORTES HD",      "|LAT| ESPN Deportes"),
    ("PRIME| TLC ᴿᴬᵂ",             "|UK| TLC"),
    ("VO| BABY TV ᴴᴰ",             "|DE| Baby TV"),
    ("4K| SKY SPORT 4K [LIVE-EVENT]", "|UK| Sky Sport 4K"),
])
def test_the_two_sides_agree(guide, channel):
    assert norm(guide) == norm(channel), (
        f"{guide!r} -> {norm(guide)!r} but {channel!r} -> {norm(channel)!r}"
    )


def test_a_pipe_prefix_is_stripped_from_both_shapes():
    """`OD|` and `|NL|` are the same idea with different punctuation.

    The old separator class was `[★◉•·]`. Neither shape contains any of those,
    so the prefix stayed in the key and two sources could never be equal.
    """
    assert norm("OD| ESPN") == "espn"
    assert norm("|NL| ESPN") == "espn"
    assert norm("US ★ ESPN") == "espn"     # the shape that DID work still does


@pytest.mark.parametrize("sup,plain", [
    ("ᴴᴰ", "HD"), ("ᵁᴴᴰ", "UHD"), ("⁴ᴷ", "4K"), ("ᶠʰᵈ", "FHD"),
    ("ˢᴰ", "SD"), ("ʰᵉᵛᶜ", "HEVC"),
])
def test_a_decorated_quality_matches_its_plain_twin(sup, plain):
    """The plain form WAS already stripped, so cleaning one side made the two
    diverge — the decoration was worse than merely being kept."""
    assert norm(f"US| ESPN {sup}") == norm(f"US| ESPN {plain}") == "espn"


@pytest.mark.parametrize("sup", ["ᴿᴬᵂ", "ⱽᴵᴾ", "ᵁᴸᵀᴿᴬ", "ᴳᴼᴸᴰ", "ᴾᴾⱽ", "⁶⁰ᶠᵖˢ", "³⁸⁴⁰ᴾ"])
def test_a_decoration_the_parser_does_not_know_is_still_dropped(sup):
    """Folding alone was not enough, which is why runs are dropped whole.

    Only six of the library's 26 superscript tokens are quality the parser
    knows. The rest are tier and format markers — and `ᴿᴬᵂ` is the most common
    token of all (6,305 channels), so folding it to the word "raw" would leave
    'TLC ᴿᴬᵂ' and 'TLC' still unequal. This test failed until runs were dropped
    rather than folded.
    """
    assert norm(f"US| TLC {sup}") == "tlc"


@pytest.mark.parametrize("word", ["GOLD", "SUPER", "ULTRA", "RAW"])
def test_the_same_token_as_a_plain_WORD_survives(word):
    """Why this is scoped to superscript and not to a token list.

    "GOLD" and "SUPER" are real channel names. A list of noise words would
    strip them; decoration is unambiguous.
    """
    assert word.lower() in norm(f"US| {word}")


def test_a_bracket_tag_does_not_shield_the_quality_behind_it():
    """Brackets are removed BEFORE parsing, not after.

    A trailing "[LIVE-EVENT]" sits between the parser and the quality token it
    strips from the end, so "SKY SPORT 4K [LIVE-EVENT]" kept its 4K while the
    plainer "Sky Sport 4K" lost it — the two then differed *because* one carried
    a tag. Caught by the owner's own data, not by reasoning.
    """
    assert norm("4K| SKY SPORT 4K [LIVE-EVENT]") == norm("|UK| Sky Sport 4K")


def test_a_bare_live_is_part_of_the_name_and_survives():
    """Only BRACKETED tags go. "LIVENOW FROM FOX" is a channel, not a tag.

    Owner flagged that the decorations carry quality "but also has LIVE" —
    which is true, and is exactly why the rule is bracket-scoped rather than
    word-scoped. Stripping the word would leave "NOW FROM FOX".
    """
    assert norm("US| LIVENOW FROM FOX") == "livenow from fox"
    assert "live" in norm("|US| LiveNOW from FOX")


def test_region_is_not_part_of_the_key():
    """Deliberate: region is carried separately and enforced by the gate.

    `epg_tld_compatible` is what stops a UK channel adopting an Italian guide —
    measured, it rejects 429 of 3,173 ProSat name-matches, and those rejections
    are correct (UK vs it, DE vs ca). Keeping region in the KEY as well would
    mean the same channel from two sources never compares equal in the first
    place, which is the bug this fixes.
    """
    assert norm("US| ESPN") == norm("LAT| ESPN") == "espn"


def test_nothing_useful_is_normalized_away():
    """A name that is only a prefix and a tag must not become empty and
    silently match every other empty one."""
    for name in ("US| ESPN", "ESPN", "|NL| ESPN 4 HD"):
        assert norm(name), f"{name!r} normalized to nothing"


def test_it_is_stable_and_idempotent():
    once = norm("OD| ESPN 4 ᴴᴰ")
    assert norm(once) == once
