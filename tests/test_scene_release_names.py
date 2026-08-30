"""1,268 titles in the library were a torrent filename, rendered verbatim.

    Onder.Het.Maaiveld.2023.DUTCH.1080p.WEB.h264-TRIPEL
    Ceu.em.Chamas-Skyfire.2019.1080p.WEB-DL.x264.DUAL-COMANDO.TO
    3.Gun (2024) 1080p AMZN WEB-DL TR SANSURSUZ DDP5.1 H264.ENG.SUBS.XT

``_strip_attributes`` could not reach any of them. It walks backwards from the
end one token at a time and stops at the first thing it does not recognise —
and a scene name ENDS in a release-group tag ("-TURG", "XT", "COMANDO.TO") that
no vocabulary will ever contain. One unknown token at the tail hid everything
in front of it, so the parser saw a single opaque blob and stored it as the
title.

``_extract_scene_release`` is therefore a FORWARD pass: it finds where the
title STOPS rather than where the junk starts, which is the only direction that
works against an open-ended tail.

Measured across the owner's 467,373 distinct names: 484 parse differently,
481 of them a title change, and none of the 1,138 assertions in the 48 existing
test files that touch the parser changed verdict.

The two-marker gate is the load-bearing part of the design, and the tests below
that pin single-marker names are guarding against a change that would look like
an improvement:

  * "BLURAY-DE - Bonhoeffer (2024)" — BLURAY-DE is the provider's CATEGORY, and
    the prefix pass already yields "Bonhoeffer". Cutting on one marker gives
    "-DE - Bonhoeffer".
  * "UK| MORE4 HEVC HD" — cutting at HEVC would throw away the HD after it.
"""

import pytest

from metatv.core.channel_name_utils import (
    AUDIO_CODEC_NORM, _canonical_audio_codec, _extract_scene_release,
    _sub_outside_brackets, parse_channel_name,
)


# --------------------------------------------------------------------------
# Titles: the whole point
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name, title", [
    # Dot-separated — invisible to the end-anchored loop before this.
    ("Atlas.2024.1080p.WEB-DL.DUAL.5.1", "Atlas"),
    ("Beanie.2022.1080p.WEB-DL.x264.DUAL.2.0", "Beanie"),
    ("Onder.Het.Maaiveld.2023.DUTCH.1080p.WEB.h264-TRIPEL",
     "Onder Het Maaiveld 2023 DUTCH"),
    ("Ceu.em.Chamas-Skyfire.2019.1080p.WEB-DL.x264.DUAL-COMANDO.TO",
     "Ceu em Chamas-Skyfire"),
    # Space-separated, tail ends in an unknown release-group tag.
    ("3.Gun (2024) 1080p AMZN WEB-DL TR SANSURSUZ DDP5.1 H264.ENG.SUBS.XT",
     "3 Gun"),
    ("A Great Awakening (2026) 1080p WEB-DL X264 DD5.1 NL SUBS-rappie.net",
     "A Great Awakening"),
    ("2010 - A Ultima Música - BRRp 1080p H264 - Dublado",
     "2010 - A Ultima Música"),
])
def test_scene_filename_becomes_a_title(name, title):
    assert parse_channel_name(name).bare_name == title


def test_the_title_no_longer_contains_the_filename():
    """The failure as the owner would see it: the row's label WAS the file."""
    raw = "Ceu.em.Chamas-Skyfire.2019.1080p.WEB-DL.x264.DUAL-COMANDO.TO"
    title = parse_channel_name(raw).bare_name
    for junk in ("1080p", "WEB-DL", "x264", "COMANDO"):
        assert junk not in title


# --------------------------------------------------------------------------
# Attributes harvested from the tail the parser could not previously reach
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name, quality, encoding, codec", [
    ("Atlas.2024.1080p.WEB-DL.DUAL.5.1", ["FHD"], "", ""),
    ("Beanie.2022.1080p.WEB-DL.x264.DUAL.2.0", ["FHD"], "H.264", ""),
    ("3.Gun (2024) 1080p AMZN WEB-DL TR SANSURSUZ DDP5.1 H264.ENG.SUBS.XT",
     ["FHD"], "H.264", "DD+ 5.1"),
    ("A Great Awakening (2026) 1080p WEB-DL X264 DD5.1 NL SUBS-rappie.net",
     ["FHD"], "H.264", "DD 5.1"),
    ("Semur 3 Kiyamet-i Cin 2022 Yerli 1080p AMZN WEB-DL x264 E-AC3 - TR.SANSURSUZ",
     ["FHD"], "H.264", "EAC3"),
    ("Konusanlar S01E57 1080p EXXEN WEB-DL [TR] AAC H264-TURG",
     ["FHD"], "H.264", "AAC"),
    ("Mahsun.J.S02E01.1080p.GAiN.WEB-DL.AAC2.0.H.264-TR.SUBS.GAIN.XT",
     ["FHD"], "H.264", "AAC 2.0"),
])
def test_attributes_are_harvested_from_the_tail(name, quality, encoding, codec):
    parsed = parse_channel_name(name)
    assert parsed.quality == quality
    assert parsed.encoding == encoding
    assert parsed.audio_codec == codec


def test_source_tags_are_not_turned_into_quality_chips():
    """WEB-DL says where a file came from, not how many pixels it has.

    It marks the cut and is then discarded. A "WEB-DL" chip beside "FHD" would
    be two chips where the user asked for one meaning.
    """
    parsed = parse_channel_name("Atlas.2024.1080p.WEB-DL.DUAL.5.1")
    assert parsed.quality == ["FHD"]
    assert "WEB-DL" not in parsed.quality and "WEBDL" not in parsed.quality


def test_release_year_survives_the_cut():
    """"Title.YYYY.1080p…" — position, not punctuation, identifies the year."""
    assert parse_channel_name("Atlas.2024.1080p.WEB-DL.x264").year == "2024"
    assert parse_channel_name("Beanie.2022.1080p.WEB-DL.x264").year == "2022"


def test_a_bare_trailing_number_is_still_not_a_year():
    """The reason step 5 demands parentheses: "Blade Runner 2049" is a title.

    Re-punctuating happens only inside the scene pass, where a bare year sits
    directly before a scene marker. A name with no scene markers must be
    untouched by any of this.
    """
    parsed = parse_channel_name("EN - Blade Runner 2049")
    assert parsed.year == ""
    assert "2049" in parsed.bare_name


# --------------------------------------------------------------------------
# The two-marker gate — every case here would BREAK on a one-marker rule
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name, title, quality, encoding", [
    # One marker (BLURAY) and it is the provider's category prefix. A cut here
    # produces "-DE - Bonhoeffer".
    ("BLURAY-DE - Bonhoeffer (2024)", "Bonhoeffer", [], ""),
    # One marker (HEVC) with a real quality token AFTER it. A cut loses the HD.
    ("UK| MORE4 HEVC HD", "MORE4", ["HD"], "H.265"),
    ("IT| 24/7 GOMORRA STAGIONE 1 FHD HEVC",
     "24/7 GOMORRA STAGIONE 1", ["FHD"], "H.265"),
])
def test_one_marker_is_not_a_scene_release(name, title, quality, encoding):
    parsed = parse_channel_name(name)
    assert parsed.bare_name == title
    assert parsed.quality == quality
    assert parsed.encoding == encoding


def test_gate_returns_none_rather_than_a_bad_split():
    """The gate is explicit so the caller falls through unchanged."""
    assert _extract_scene_release("Bonhoeffer (2024)") is None
    assert _extract_scene_release("MORE4 HEVC HD") is None
    assert _extract_scene_release("Atlas.2024.1080p.WEB-DL") is not None


@pytest.mark.parametrize("name, title", [
    ("EN - Opus (2025)", "Opus"),          # a real 2025 film; Opus is also a codec
    ("GR - Opus (2025)", "Opus"),
    ("EN - Gold (2016)", "Gold"),
    ("EN - WWE Raw (2023)", "WWE Raw"),    # regression B0
    ("EN - Atlas (2024)", "Atlas"),
])
def test_ordinary_titles_are_untouched(name, title):
    """A word that is ALSO a codec stays a title when no marker qualifies it.

    "Opus" is why the soft audio vocabulary is gated on position rather than
    trusted anywhere: it is a codec and a 2025 film, and only the surrounding
    scene markers tell the two apart.
    """
    assert parse_channel_name(name).bare_name == title


# --------------------------------------------------------------------------
# HDTV — the single-marker case that DOES resolve, on the end-anchored path
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name, title", [
    ("NBA TV HDTV", "NBA TV"),
    ("WFOR CBS 4 HDTV", "WFOR CBS 4"),
    ("TRINITY BROADCASTING NETWORK HDTV", "TRINITY BROADCASTING NETWORK"),
])
def test_hdtv_is_a_quality_not_part_of_the_name(name, title):
    parsed = parse_channel_name(name)
    assert parsed.bare_name == title
    assert parsed.quality == ["HD"], (
        "HDTV is 720p/1080i — it belongs on the one ladder, not in a "
        "vocabulary of its own")


def test_hdtv_does_not_disturb_a_neighbouring_superscript():
    """"NBA TV HDTV ᴿᴬᵂ" — two decorations of different classes, both read."""
    parsed = parse_channel_name("NBA TV HDTV ᴿᴬᵂ")
    assert parsed.bare_name == "NBA TV"
    assert parsed.quality == ["HD", "RAW"]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, key", [
    ("DDP5.1", "DDP5.1"), ("DDP.5.1", "DDP5.1"), ("DDP 5.1", "DDP5.1"),
    ("DDP-5.1", "DDP5.1"), ("DD5.1", "DD5.1"),
    ("AAC2.0", "AAC2.0"), ("AAC 2.0", "AAC2.0"), ("AAC", "AAC"),
    ("E-AC3", "EAC3"), ("E.AC.3", "EAC3"), ("EAC3", "EAC3"),
    ("AC-3", "AC3"), ("AC3", "AC3"),
    ("DTS-HD", "DTS-HD"), ("DTS.HD", "DTS-HD"),
    ("TRUE-HD", "TRUEHD"), ("Atmos", "ATMOS"), ("Opus", "OPUS"),
])
def test_codec_spellings_fold_onto_one_key(raw, key):
    """A release group picks the separator; every spelling is the same codec."""
    assert _canonical_audio_codec(raw) == key
    assert key in AUDIO_CODEC_NORM, f"{key} folds onto no vocabulary entry"


@pytest.mark.parametrize("text, expected", [
    ("a.b (22.04.2025) c.d", "a b (22.04.2025) c d"),
    ("Atlas.2024", "Atlas 2024"),
    ("x.y [a.b] z.w", "x y [a.b] z w"),
    ("(1.2)", "(1.2)"),
    ("no brackets.here", "no brackets here"),
    ("unclosed (1.2", "unclosed (1.2"),
])
def test_bracketed_spans_keep_their_dots(text, expected):
    """An episode's air date rides in parentheses and is not a separator run."""
    import re
    assert _sub_outside_brackets(re.compile(r"[._]+"), " ", text) == expected


def test_an_air_date_survives_the_scene_pass():
    """The case the helper exists for, end to end."""
    parsed = parse_channel_name(
        "Kral Kaybederse 10 BLM (22.04.2025) 1080p Web-DL AAC H264-TURG")
    assert parsed.bare_name == "Kral Kaybederse 10 BLM (22.04.2025)"
    assert parsed.encoding == "H.264"


# --------------------------------------------------------------------------
# Drift guard
# --------------------------------------------------------------------------

def test_the_same_rank_collapse_has_exactly_one_implementation():
    """It had THREE, and only two of them were visible.

    "UHD 3840P" is one rung of the quality ladder said twice, and the loop that
    collapses it was written out inline three separate times in this module —
    once in ``_strip_attributes``, once at the end of ``parse_channel_name``,
    and once more in the scene pass. Two used ``seen_ranks`` and one used
    ``_seen_ranks``, which is why a search for the duplicate found only two of
    the three. They agreed today; nothing made them agree tomorrow.

    Guarding the IDENTIFIER rather than the behaviour, because behaviour is
    exactly what a fourth copy would also get right on the day it was written.
    """
    import re
    from pathlib import Path

    import metatv.core.channel_name_utils as mod

    source = Path(mod.__file__).read_text()
    bodies = re.findall(r"^\s*_?seen_ranks: set\[int\] = set\(\)", source, re.M)
    assert len(bodies) == 1, (
        f"{len(bodies)} same-rank collapse loops in channel_name_utils.py — "
        "call _collapse_same_rank() instead of writing a fourth")
