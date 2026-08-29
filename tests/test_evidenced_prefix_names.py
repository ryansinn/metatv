"""Prefix codes get a name only when the provider's own data says what they mean.

293 of 421 distinct prefixes in the owner's library resolved to no name at all
— roughly **111,000 channels** rendering with a blank geographic chip, `AR`
alone accounting for 68,593.

None of these were guessed from an ISO table. Every one was read off the
**provider's own category label**, which spells the code out:

    AR    "|AR| أفلام أجنبية" + an "|AR-SUB|" variant   -> Arabic, not Argentina
    EX    "|EXYU| STRANI FILMOVI"                       -> Ex-Yugoslavia
    AF    "|AF| AFRICAN MOVIES"                         -> Africa, not Afrikaans
    IS    "IS| HEBREW SDAROT"                           -> Israel

That is a better source than ISO, because the provider chose the code. `AR` is
the case that proves it: ISO alpha-2 says Argentina, and the content is beIN
Sport with Arabic-script categories.

Two codes are deliberately left unnamed, and the tests below pin that too — an
unnamed code is honest, a wrongly-named one is not.
"""

from __future__ import annotations

import pytest

from metatv.core.channel_name_utils import PLATFORM_CODES, REGION_FULL_NAMES


@pytest.mark.parametrize("code,name", [
    ("AR", "Arabic"), ("EX", "Ex-Yugoslavia"), ("TM", "Tamil"),
    ("TG", "Telugu"), ("TL", "Telugu"), ("AF", "Africa"),
    ("SW", "Sweden"), ("UR", "Urdu"), ("SCAN", "Scandinavia"),
    ("KD", "Kannada"), ("IS", "Israel"),
])
def test_an_evidenced_code_has_its_name(code, name):
    assert REGION_FULL_NAMES.get(code) == name


def test_ar_is_arabic_not_argentina():
    """The case that shows why the provider's data beats an ISO lookup.

    ISO 3166 alpha-2 "AR" is Argentina. The 68,593 channels carrying it are
    beIN Sport with categories in Arabic script and an "|AR-SUB|" (Arabic
    subtitles) variant. An ISO-driven table would have mislabelled all of them.
    """
    assert REGION_FULL_NAMES["AR"] == "Arabic"
    assert REGION_FULL_NAMES["AR"] != "Argentina"


@pytest.mark.parametrize("code,name", [("OD", "Odido"), ("YP", "YuppTV")])
def test_a_platform_code_is_named_and_marked_as_a_platform(code, name):
    """These were rendering as geographic chips; they are services."""
    assert REGION_FULL_NAMES.get(code) == name
    assert code in PLATFORM_CODES


@pytest.mark.parametrize("code,why", [
    ("SO", "means South-Indian-dubbed AND Somali in the same library"),
    ("MULTI", "is a multi-audio marker, not a place"),
])
def test_a_genuinely_ambiguous_code_stays_unnamed(code, why):
    """An unnamed code is honest; a wrongly-named one is not.

    `SO` carries "|IN| SOUTH HINDI DUBBED" (1,344) and "|AF| SO FANPROJ" (158,
    a Somali brand) in one library — a single label would be wrong for one of
    them. `MULTI` is "|MULTI| NETFLIX": a multi-audio marker that needs its own
    concept rather than a country name.
    """
    assert code not in REGION_FULL_NAMES, f"{code} was named, but it {why}"


def test_the_new_codes_did_not_displace_an_existing_one():
    """Adding to a lookup table must not silently rebind a code."""
    for code, expected in [("SE", "Sweden"), ("EN", "English"), ("US", None)]:
        if expected is not None:
            assert REGION_FULL_NAMES.get(code) == expected, (
                f"{code} changed meaning while new codes were added"
            )
    assert "US" in REGION_FULL_NAMES


def test_every_named_code_has_a_nonempty_name():
    bad = [k for k, v in REGION_FULL_NAMES.items() if not (v or "").strip()]
    assert not bad, f"codes mapped to an empty name: {bad}"
