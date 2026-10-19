"""Quality, encoding and audio vocabulary: tokens, tiers, labels, and the attribute
bag the name parser fills — split out of channel_name_utils (ledger F30).
"""

from __future__ import annotations

import re
from typing import NamedTuple


# ── Provider decoration vocabularies ────────────────────────────────────────── #
# Single source of truth for these token classes (CLAUDE.md: lookup tables live
# here and nowhere else). Measured across the owner's 785,163-name library.

#: Package/tier markers — not quality, and not a language, which is where they
#: landed: ``_classify_bracket`` read any 2-3 letter bracket as a region, so
#: ``SKY SPORTS [VIP]`` parsed to ``lang='VIP'``.
#:
#: RAW is deliberately absent — it is quality in 12,476 of 12,551 uses and is
#: handled there; one token in two facets would mean two different things.
TIER_TOKENS: frozenset[str] = frozenset({
    "VIP", "PPV", "GOLD", "ULTRA", "PREMIUM", "PLUS",
})

#: Video encodings, kept apart from ``quality``: not resolution tiers, the same
#: reasoning ledger F17 applied to HDR. 1,534 rows showed "HEVC" as their only
#: quality chip while the real resolution went unrecorded.
ENCODING_NORM: dict[str, str] = {
    "H264": "H.264", "H.264": "H.264", "X264": "H.264", "AVC": "H.264",
    "H265": "H.265", "H.265": "H.265", "X265": "H.265", "HEVC": "H.265",
    "MPEG2": "MPEG-2", "AV1": "AV1", "VP9": "VP9",
}

#: Audio CODECS — distinct from ``_AUDIO_NORM``, which records PRESENTATION
#: (Multi / Dub / Sub). A scene release carries both.
AUDIO_CODEC_NORM: dict[str, str] = {
    "DDP": "DD+", "DDP2.0": "DD+ 2.0", "DDP5.1": "DD+ 5.1", "DDP7.1": "DD+ 7.1",
    "DD": "DD", "DD2.0": "DD 2.0", "DD5.1": "DD 5.1",
    "AC3": "AC3", "EAC3": "EAC3",
    "AAC": "AAC", "AAC2.0": "AAC 2.0", "AAC5.1": "AAC 5.1",
    "DTS": "DTS", "DTS-HD": "DTS-HD", "TRUEHD": "TrueHD", "ATMOS": "Atmos",
    "FLAC": "FLAC", "OPUS": "Opus", "MP3": "MP3",
}

#: Pixel heights that mean a tier we already name. The chip shows the TIER,
#: never the pixel count, so ``QUALITY_TIER_RANK`` stays authoritative.
RESOLUTION_TO_QUALITY: dict[str, str] = {
    "4320P": "8K",
    "2160P": "4K", "3840P": "4K",
    "1440P": "FHD", "1080P": "FHD", "1080I": "FHD",
    "720P": "HD",
    "576P": "SD", "540P": "SD", "480P": "SD", "480I": "SD", "360P": "SD",
}

#: Frame-rate markers. Kept as a quality token because it is a real
#: watchability attribute the owner asked to surface as its own chip.
_FPS_RE = re.compile(r"\b(\d{2,3})\s?FPS\b", re.IGNORECASE)

# ── Suffix patterns ─────────────────────────────────────────────────────────── #

# Quality tokens at end of bare name (including codecs and source indicators)
# RAW, LIVE, CAM removed — these are ambiguous when bare (e.g., "WWE Raw" shouldn't become
# title="WWE"). They must appear bracketed [RAW] or as superscript to count as quality.
#: Broadcast/source tags that DO carry a resolution meaning, normalized onto the
#: one ladder. "WFOR CBS 4 HDTV" and "NBA TV HDTV" rendered the tag as part of
#: their title; HDTV is 720p/1080i, so it is an HD channel and says so with the
#: same chip every other HD channel uses rather than a vocabulary of one.
#: The other source tags (WEB-DL, BluRay, REMUX) say where a file came from and
#: nothing about its resolution — they mark the cut in _extract_scene_release and
#: are then discarded, never turned into a chip.
_SOURCE_QUALITY_NORM: dict[str, str] = {"HDTV": "HD"}


# ── Audio format normalization ───────────────────────────────────────────────── #

# All known variants → canonical form. Keys are uppercased for matching.
_AUDIO_NORM: dict[str, str] = {
    # Multi variants (548+178+58+44+37+32+17+15+5+3 + typos = 1,000+)
    "MULTI": "Multi",
    "MULTI-SUB": "Multi", "MULTI-AUDIO": "Multi",
    "MULTI SUB": "Multi", "MULTI AUDIO": "Multi",
    "MULTI AUDIO/SUB": "Multi", "MULTI AU/SUB": "Multi",
    "MULTI AU/AUDIO": "Multi", "MULTI AUDO": "Multi",
    "MULTI AUDO/ SUB": "Multi", "MULTI AUDO/SUB": "Multi",
    "MULTIAUDIO": "Multi", "MULTI AUDIO SUB": "Multi",
    "MULTI LANGUAGE": "Multi", "MULTILANGUAGE": "Multi",
    "MULTI-AUDIO/SUB": "Multi",
    # "MUTI" — common typo for "Multi" (missing L); fold into the same group
    "MUTI": "Multi",
    "MUTI-SUB": "Multi", "MUTI-AUDIO": "Multi",
    "MUTI SUB": "Multi", "MUTI AUDIO": "Multi",
    "MUTI AUDIO/SUB": "Multi", "MUTIAUDIO": "Multi",
    # Dub variants (27+9+3+1)
    "DUB": "Dub", "DUBBED": "Dub", "DUBBED VERSION": "Dub",
    # Sub variants (92+38+2)
    "SUB": "Sub", "SUBTITLED": "Sub", "SUBTITULADO": "Sub",
    "SUBTITLE": "Sub",
}

# Bare subtitle/dub markers that appear as *leaf tokens* inside multi-word
# parentheticals like "(SPANISH ENG-SUB)" or "(ENG DUB)" — NOT full _AUDIO_NORM
# keys (which cover complete bracket/paren contents), but individual tokens
# within a compound qualifier. _is_all_qualifier_tokens()'s allowlist checks each
# space/dash/slash-split leaf against this set alongside lang codes and quality.
_SUB_DUB_TOKENS: frozenset[str] = frozenset({
    "SUB", "SUBS", "SUBBED", "SUBTITLED", "SUBTITULADO", "SUBTITLE",
    "DUB", "DUBBED", "DUBBING",
    "VOST", "VOSTFR", "VOSTA",
    "LEG", "LEGENDADO", "LEGENDADA",
    "OV", "OMU",
    "AUDIO", "DUAL",
})

# Unambiguous subtitle/dub markers. Their PRESENCE in a trailing parenthetical is
# strong enough to treat the whole parenthetical as a qualifier annotation even
# when a co-occurring language word (KURDISH, PERSIAN, NORWEGIAN, …) isn't in the
# recognized vocabulary. DUAL/AUDIO/MULTI are DELIBERATELY EXCLUDED — they appear
# in real titles ("Dual Survival", "Multiplicity") and are ambiguous.
_UNAMBIGUOUS_SUBDUB_MARKERS: frozenset[str] = frozenset({
    "SUB", "SUBS", "SUBBED", "SUBTITLED", "SUBTITLES",
    "DUB", "DUBBED",
    "VOST", "VOSTFR",
    "LEG", "LEGENDADO", "LEGENDADOS",
    "MULTISUB", "ENGSUB",
})

# Bare audio-track annotation tokens providers sometimes append as a *trailing
# word with no bracket/paren delimiter* ("The Bridge MULTI", "The Killing MULTI
# SUB") — bracketed forms ([MULTI], (Multi-Sub)) are already stripped by
# strip_title_qualifiers; this set targets the bare-word leak. They denote the
# audio track, NOT the production, so content_identity.py's key normalisation
# strips a trailing run of them, but only when anchored by a MULTI/MUTI token
# (AUDIO_KEY_ANCHOR_TOKENS) so real titles ending "Sub"/"Audio"/"Dual" survive
# (DUAL/AUDIO/MULTI caveat above). Single source of truth — keep in sync with
# the canonical _AUDIO_NORM forms; lowercase since the key normaliser lowercases
# before matching.
AUDIO_KEY_NOISE_TOKENS: frozenset[str] = frozenset({
    "multi", "muti", "sub", "audio", "au",
})

# Anchor subset of AUDIO_KEY_NOISE_TOKENS: a trailing audio-noise run is stripped from a
# content_key only when it contains one of these, so "Dual Survival" / "<title> Sub" stay
# intact while "<title> MULTI" / "<title> MULTI SUB" collapse onto the base title.
AUDIO_KEY_ANCHOR_TOKENS: frozenset[str] = frozenset({"multi", "muti"})

# Quality tokens that can appear as a detected_prefix (e.g. "HD - Movie" → prefix "HD").
# Used to populate detected_quality when the prefix itself is a quality marker.
QUALITY_TOKENS: frozenset[str] = frozenset({
    "4K", "8K", "UHD", "FHD", "HDR10+", "HDR", "HEVC", "H265", "H264",
    "HD", "SD", "HQ", "LQ", "RAW", "CAM",
})

# Bare media-type indicator words that duplicate the comfy row's media-type icon
# (LIVE/MOVIE/SERIES — metatv.core.models.MediaType) when they appear standalone
# in a provider category string feeding detected_collection (e.g. "MULTISUB
# SERIES 4K" on a row whose icon already reads "series"). Whole-token match
# only — see strip_collection_noise_tokens()'s "whole span must be noise"
# gate, which is what keeps a real collection name like "SERIES MANIA" intact
# even though "SERIES" alone is in this set. Deliberately excludes the bare
# word "TV" (too common inside real channel/network brand names, e.g. "KIDS
# TV", mirroring the same caution the DUAL/AUDIO/MULTI exclusion below takes
# for real titles).
MEDIA_TYPE_TOKENS: frozenset[str] = frozenset({
    "MOVIE", "MOVIES", "FILM", "FILMS",
    "SERIES", "SERIE", "TVSHOW", "TVSHOWS", "SHOW", "SHOWS",
    "LIVE", "VOD",
})

# ── quality token → viewer-facing label + explanation (single source of truth) ─ #
# Not every QUALITY_TOKEN a provider stamps on a name is a picture-quality TIER.
# ``HEVC`` / ``H265`` / ``H264`` are *codecs* and ``RAW`` is a *bitrate/processing*
# descriptor — a viewer reading them in the On Now Quality column or a filter chip
# has no way to rank them against 4K/HD/SD.  These two maps translate the stored
# token for DISPLAY ONLY: the DB value, the filter key, and every query keep the
# original token as identity (exactly like CONTENT_TYPE_DISPLAY_NAMES below).
#
# Only tokens that actually mislead get an entry — a plain resolution tier (4K, HD,
# SD…) is already self-explanatory and falls through to its uppercased self.
QUALITY_DISPLAY_NAMES: dict[str, str] = {
    # RAW is the one token whose label is genuinely wrong to a viewer: it reads as
    # "unfinished/bad" when it means an untranscoded high-bitrate feed.
    "RAW": "Uncompressed",
    # The codec tokens keep their short form (they ARE the recognizable name) and
    # carry their explanation in the tooltip instead — see QUALITY_TOOLTIPS.
}

QUALITY_TOOLTIPS: dict[str, str] = {
    "RAW":  "Uncompressed — an untranscoded, high-bitrate source feed (not a resolution tier)",
    "HEVC": "HEVC (H.265) — an efficient video codec, not a picture-quality tier",
    "H265": "H.265 / HEVC — an efficient video codec, not a picture-quality tier",
    "H264": "H.264 / AVC — a video codec, not a picture-quality tier",
}

# ── quality token → sortable tier rank (single source of truth) ────────────────
# Higher is better picture quality: 8K > 4K/UHD > FHD > HD > (codec/other) > SD > LQ.
# Only true resolution TIERS are ranked; codec tokens (HEVC/H265/H264) and
# bitrate/processing descriptors (RAW, HQ, CAM) are not comparable to a resolution
# tier, so they fall back to _QUALITY_TIER_RANK_DEFAULT (between SD and HD) rather
# than a made-up position. Used to rank channels within a match group (e.g. the EPG
# watchlist) so the best surviving stream leads before a display cap trims the rest
# — never a parallel/local tier dict elsewhere (Lookup tables single-source-of-truth
# rule, CLAUDE.md).
QUALITY_TIER_RANK: dict[str, int] = {
    "8K": 6,
    "4K": 5,
    "UHD": 5,
    "FHD": 4,
    "HD": 3,
    "SD": 1,
    "LQ": 0,
}
_QUALITY_TIER_RANK_DEFAULT = 2  # unranked tokens (HEVC, RAW, HQ, CAM, unknown…)


def quality_tier_rank(token: str | None) -> int:
    """Return a sortable tier rank for a stored ``detected_quality`` token.

    Args:
        token: A stored ``ChannelDB.detected_quality`` token (may be ``None``/empty).

    Returns:
        An integer rank, higher = better picture quality. Unknown or missing
        tokens fall back to :data:`_QUALITY_TIER_RANK_DEFAULT`.
    """
    if not token:
        return _QUALITY_TIER_RANK_DEFAULT
    return QUALITY_TIER_RANK.get(token.strip().upper(), _QUALITY_TIER_RANK_DEFAULT)


def quality_display(token: str) -> str:
    """Return the viewer-facing label for a stored quality *token*.

    The single chokepoint that turns a stored ``detected_quality`` token — or a
    filter GROUP name, which shares the namespace (``"RAW"``, ``"4K / UHD"``) —
    into the string shown in a chip, column or list row.  Known misleading tokens
    map via :data:`QUALITY_DISPLAY_NAMES` (``"RAW"`` → ``"Uncompressed"``).

    An unknown value is returned **unchanged apart from stripping** — deliberately
    NOT uppercased, so a mixed-case group name (``"CAM / Pre-release"``) survives
    intact.  A caller that wants the uppercased tier convention (the badge chips)
    uppercases before calling.

    Args:
        token: A stored quality token or filter group name (e.g. ``"HEVC"``).

    Returns:
        The display label.  Never mutates identity — callers keep the original
        token for queries, filter keys and DB writes.
    """
    raw = (token or "").strip()
    known = QUALITY_DISPLAY_NAMES.get(raw.upper())
    return known if known is not None else raw


def quality_tooltip(token: str) -> str:
    """Return the hover explanation for a stored quality *token*.

    Pairs with :func:`quality_display`: a codec/bitrate descriptor gets a sentence
    saying what it actually means (and that it is *not* a quality tier), while a
    plain tier falls back to the generic ``"4K quality"`` phrasing.

    Args:
        token: A stored quality token (e.g. ``"HEVC"``).

    Returns:
        Tooltip text; never empty for a non-empty token.
    """
    upper = (token or "").strip().upper()
    if not upper:
        return ""
    known = QUALITY_TOOLTIPS.get(upper)
    if known is not None:
        return known
    return f"{upper} quality"


# Bracket content that isn't a bare QUALITY_TOKEN but maps to one — typically
# compound cam-rip variants. Keys are uppercased bracket contents.
_BRACKET_QUALITY_ALIASES: dict[str, str] = {
    "CAM":          "CAM",
    "SD/CAM":       "CAM",
    "CAM-VERSION":  "CAM",
    "CAM-VERSON":   "CAM",   # typo seen in provider data
    "VERSION CAM":  "CAM",
    "CAM VERSION":  "CAM",
    "V.CAM":        "CAM",
}

# Full language names in bracket suffixes → codes stored as detected_region.
# Covers dubbed/localized audio tracks: "EN ★ Movie [SPANISH]" → detected_region = "ES".
# Semantic note: KR/JP/CN are ISO 3166-1 *country* codes, not ISO 639-1 *language*
# codes (ko/ja/zh) — the IPTV convention conflates the two (EN already serves as
# both in REGION_FULL_NAMES), so this follows suit for consistency. Tracked as
# semantic debt in project_filter_system.
_BRACKET_LANG_NORM: dict[str, str] = {
    "SPANISH":    "ES",
    "FRENCH":     "FR",
    "HINDI":      "HI",
    "KOREAN":     "KR",
    "TURKISH":    "TR",
    "ARABIC":     "AR",
    "GERMAN":     "DE",
    "ITALIAN":    "IT",
    "PORTUGUESE": "PT",
    "RUSSIAN":    "RU",
    "JAPANESE":   "JP",
    "CHINESE":    "CN",
    "THAI":       "TH",
    "POLISH":     "PL",
}


class _Attributes(NamedTuple):
    """What a trailing-token sweep pulled off a name."""

    quality: list[str]
    tier: str
    encoding: str
    audio_codec: str


def _collapse_same_rank(quality: list[str]) -> list[str]:
    """Drop quality tokens that repeat a rung of the ladder already taken.

    "UHD 3840P" resolves to UHD and 4K — the same rung said twice, which would
    render as two chips meaning one thing. The first token of a rank wins.
    Unranked tokens (RAW, 60fps, HDR, HEVC) all share the default rank and are
    NOT collapsed into each other: they are different facts, not competing
    resolutions.

    Args:
        quality: Tokens in the order they should be preferred.

    Returns:
        The same list with same-rank repeats removed.
    """
    deduped: list[str] = []
    seen_ranks: set[int] = set()
    for token in quality:
        rank = QUALITY_TIER_RANK.get(token)
        if rank is None:
            deduped.append(token)
            continue
        if rank in seen_ranks:
            continue
        seen_ranks.add(rank)
        deduped.append(token)
    return deduped
