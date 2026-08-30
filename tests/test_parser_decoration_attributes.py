"""Attributes the provider sends, that used to live in the title.

Measured on the owner's 785,163-name library before this change:

* **15,676** channels carried superscript decoration inside ``detected_title``
  — ``ESPN NEWS ᴴᴰ ⁶⁰ᶠᵖˢ`` — and **3,405** of those had NO quality recorded at
  all, while the plain ``HD`` on an identical channel from another source was
  captured correctly. Cleaning one side is what made them diverge.
* ``SKY SPORTS [VIP]`` parsed to **lang='VIP'**, because ``_classify_bracket``
  treated any two-or-three-letter bracket as a region code.
* ``ESPN HD/RAW`` read neither token; ``RELAX 3840P`` read neither.

After: 17,883 titles change (16,686 of them shorter) and 14,597 channels gain a
quality they always had in their name.
"""

from __future__ import annotations

import pytest

from metatv.core.channel_name_utils import (
    ENCODING_NORM, RESOLUTION_TO_QUALITY, TIER_TOKENS, parse_channel_name,
)


# --------------------------------------------------------------------------- #
# Superscript decoration
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("sup,plain", [
    ("ᴴᴰ", "HD"), ("ᵁᴴᴰ", "UHD"), ("⁴ᴷ", "4K"),
    ("ᶠʰᵈ", "FHD"), ("ˢᴰ", "SD"),
])
def test_a_decorated_quality_is_captured_like_its_plain_twin(sup, plain):
    decorated = parse_channel_name(f"US| ESPN {sup}")
    ordinary = parse_channel_name(f"US| ESPN {plain}")
    assert decorated.bare_name == ordinary.bare_name == "ESPN"
    assert decorated.quality == ordinary.quality
    assert decorated.quality, "the decorated form recorded no quality at all"


def test_an_accented_title_is_not_decomposed(qapp=None):
    """The reason folding is per-character and not a blanket NFKD.

    ``unicodedata.normalize("NFKD", …)`` over the whole string would also split
    ``Á`` into ``A`` + a combining accent and quietly rewrite every accented
    title in the library. A superscript decomposes to something wholly
    alphanumeric; an accented letter decomposes to a letter plus a mark.
    """
    assert parse_channel_name("|ES| Alita: Ángel de combate").bare_name == \
        "Alita: Ángel de combate"
    assert parse_channel_name("|FR| Amélie").bare_name == "Amélie"


def test_a_decoration_the_quality_vocabulary_does_not_know_still_leaves_the_title():
    """``ᴿᴬᵂ`` is the most common decoration in the library (12,162 channels)."""
    parsed = parse_channel_name("PRIME| TLC ᴿᴬᵂ")
    assert parsed.bare_name == "TLC"
    assert "RAW" in parsed.quality


# --------------------------------------------------------------------------- #
# The bracket-as-language bug
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tier", sorted(TIER_TOKENS))
def test_a_tier_bracket_is_not_a_language(tier):
    parsed = parse_channel_name(f"US| SKY SPORTS [{tier}]")
    assert parsed.tier == tier
    assert parsed.lang == "", f"[{tier}] was stored as lang={parsed.lang!r}"
    assert parsed.bare_name == "SKY SPORTS"


def test_a_real_language_bracket_still_reads_as_one():
    """The fix must not make every bracket a tier."""
    parsed = parse_channel_name("EN - Frauds (2025) (GB)")
    assert parsed.lang == "UK"
    assert parsed.tier == ""


def test_a_tier_word_at_the_end_is_captured_too():
    parsed = parse_channel_name("US| SKY SPORTS VIP")
    assert parsed.tier == "VIP"
    assert parsed.bare_name == "SKY SPORTS"


# --------------------------------------------------------------------------- #
# Resolution folds into the one ladder
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("pixels,tier", sorted(RESOLUTION_TO_QUALITY.items()))
def test_a_pixel_height_becomes_its_tier(pixels, tier):
    """The chip shows the tier, never the pixel count — one ladder stays
    authoritative (``QUALITY_TIER_RANK``)."""
    parsed = parse_channel_name(f"US| RELAX {pixels}")
    assert parsed.quality == [tier], f"{pixels} -> {parsed.quality}"
    assert parsed.bare_name == "RELAX"


def test_one_tier_stated_twice_yields_one_chip():
    """"UHD 3840P" is the same rung said two ways; two chips would mean one
    thing. Non-tier tokens share the unranked default and must NOT collapse."""
    assert parse_channel_name("4K| RELAX ᵁᴴᴰ 3840P").quality == ["UHD"]
    both = parse_channel_name("US| ESPN HD 60fps HDR").quality
    assert "HD" in both and "60fps" in both and "HDR" in both


# --------------------------------------------------------------------------- #
# Slash-joined, encoding, audio codec
# --------------------------------------------------------------------------- #

def test_slash_joined_attributes_are_read_as_two():
    parsed = parse_channel_name("US| ESPN HD/RAW")
    assert parsed.bare_name == "ESPN"
    assert parsed.quality == ["HD", "RAW"]


def test_a_slash_inside_a_real_name_is_left_alone():
    """The split is bounded to two known attribute tokens, so a title keeps its
    slash — otherwise "AC/DC" becomes "AC DC"."""
    assert "/" in parse_channel_name("US| AC/DC Channel").bare_name


@pytest.mark.parametrize("token,canonical", sorted(ENCODING_NORM.items()))
def test_an_encoding_is_not_a_quality(token, canonical):
    """Ledger F17's argument for HDR: an encoding is not a resolution tier, and
    letting it stand in for one meant 1,534 rows whose only quality chip said
    "HEVC" while the real resolution went unrecorded."""
    parsed = parse_channel_name(f"US| ESPN {token}")
    assert parsed.encoding == canonical
    assert parsed.quality == [], f"{token} leaked into quality: {parsed.quality}"


def test_an_encoding_in_brackets_routes_the_same_way():
    """HEVC is in BOTH vocabularies, so whichever is consulted first wins —
    the bracket path had to be reordered as well as the suffix path."""
    assert parse_channel_name("US| ESPN [HEVC]").encoding == "H.265"
    assert parse_channel_name("US| ESPN HEVC").encoding == "H.265"


def test_an_audio_codec_is_its_own_field():
    """Distinct from ``audio``, which is presentation (Multi / Dub / Sub)."""
    parsed = parse_channel_name("EN - Show [DDP5.1]")
    assert parsed.audio_codec == "DD+ 5.1"
    assert parsed.audio == ""


def test_fps_is_kept_as_its_own_chip():
    parsed = parse_channel_name("US| ESPN NEWS ᴴᴰ ⁶⁰ᶠᵖˢ")
    assert parsed.bare_name == "ESPN NEWS"
    assert parsed.quality == ["HD", "60fps"]


# --------------------------------------------------------------------------- #
# Nothing is destroyed
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", [
    "US| ESPN", "EN - Cleopatra (1963)", "|NL| ESPN 4 HD",
    "US| LIVENOW FROM FOX", "PRIME| TLC ᴿᴬᵂ", "US| SKY SPORTS [VIP]",
])
def test_a_name_never_normalizes_to_nothing(name):
    assert parse_channel_name(name).bare_name.strip(), f"{name!r} lost its title"


def test_the_year_and_region_paths_are_untouched():
    parsed = parse_channel_name("EN - Cleopatra (1963)")
    assert (parsed.bare_name, parsed.year, parsed.region) == ("Cleopatra", "1963", "EN")
