"""Shared channel name parsing — prefix extraction, region normalization, quality/year/audio detection."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import NamedTuple, Optional

from metatv.core.quality_vocab import _Attributes, _AUDIO_NORM, _BRACKET_LANG_NORM, _BRACKET_QUALITY_ALIASES, _collapse_same_rank, _FPS_RE, _SOURCE_QUALITY_NORM, _SUB_DUB_TOKENS, _UNAMBIGUOUS_SUBDUB_MARKERS, AUDIO_CODEC_NORM, ENCODING_NORM, MEDIA_TYPE_TOKENS, QUALITY_TIER_RANK, QUALITY_TOKENS, RESOLUTION_TO_QUALITY, TIER_TOKENS
from metatv.core.region_codes import _ALIAS_MAP, _FULL_NAME_TO_CODE, AUDIO_LANG_WORD_MAP, normalize_region_code, PLATFORM_CODES, platform_display, REGION_FULL_NAMES
from metatv.core.content_labels import AGE_RATING_PREFIXES
from metatv.core.scene_release import _extract_scene_release, _SCENE_EDGE_RE


class ParsedChannel(NamedTuple):
    """Result of parse_channel_name().

    Attributes:
        region:     Standardized region/platform code ("ARG", "US", "NF", "D+") or "".
        bare_name:  Channel title with all suffixes/prefixes stripped.
        quality:    Quality tokens found (e.g. ["HD", "HEVC"]). First is highest tier.
        lang:       Explicit parenthetical lang/region qualifier differing from region, or "".
        year:       Year or year-range from trailing parentheses ("2020", "1993-2002"), or "".
        audio:      Audio presentation format ("Multi", "Dub", "Sub", "Dual", "Original"), or "".
        audio_langs: Languages identified as the audio track (original audio). May include
                     the original-language + any explicit audio designations.
        dub_langs:  Languages identified as a dubbed audio track (from DUB markers).
        sub_langs:  Languages identified as a subtitle track (from SUB markers).
                    "Multi" is used as a special sentinel when [Multi-Sub] is detected.
        trailing:   Text the year-strip discarded from AFTER the year, e.g.
                    "NICOLAS CAGE" in "EN - Adaptation. 4K (2002) NICOLAS CAGE".
                    Providers routinely append the lead actor there, and it used
                    to be dropped on the floor — not merely unused, but never
                    surfaced to any caller. Callers decide what it means; the
                    parser only refuses to throw it away.
        tier:       Package/tier marker ("VIP", "PPV", "GOLD"), or "". NOT quality
                    and NOT a language — before this existed, a bracketed
                    ``[VIP]`` fell through ``_classify_bracket``'s 2-3-letter
                    rule and was stored as a region.
        encoding:   Video encoding ("H.264", "H.265", "AV1"), or "". Split out of
                    ``quality`` for the reason ledger F17 gave for HDR: an
                    encoding is not a resolution tier, and letting it stand in
                    for one means an HEVC channel reports no resolution at all.
        season:     Season number as it appeared ("01", "2"), or "". Present only
                    for the SxxExx form — see :data:`_EPISODE_MARKER_RE`.
        episode:    Episode number as it appeared ("57", "004"), or "".
        audio_codec: Audio codec ("DD+ 5.1", "AAC 2.0"), or "". Distinct from
                    ``audio``, which is presentation (Multi/Dub/Sub).
        trailing_meta: ``(kind, value)`` when the text after a mid-string year was
                    RECOGNISED provider metadata rather than cast — e.g.
                    ``("collection", "Hallmark")`` for "... (2021) Hallmark".
                    ``None`` when nothing followed the year, or when the text was
                    not recognised and was therefore left inside ``bare_name``
                    (it may be a real subtitle: "FBI (2024) Reboot").
    """
    region: str
    bare_name: str
    quality: list[str]
    lang: str
    year: str
    audio: str
    audio_langs: list[str] = []
    dub_langs: list[str] = []
    sub_langs: list[str] = []
    trailing: str = ""
    trailing_meta: Optional[tuple[str, str]] = None
    tier: str = ""
    encoding: str = ""
    audio_codec: str = ""
    season: str = ""
    episode: str = ""

#: "HD/RAW" → "HD RAW". Bounded to alphanumeric-slash-alphanumeric so "AC/DC"
#: keeps its slash (it is one word) and so does a date.
_SLASH_JOINED_RE = re.compile(
    r"\b(4K|8K|UHD|FHD|HDR10\+?|HDR|HEVC|H\.?26[45]|X26[45]|HD|SD|HQ|LQ|RAW)"
    r"/(4K|8K|UHD|FHD|HDR10\+?|HDR|HEVC|H\.?26[45]|X26[45]|HD|SD|HQ|LQ|RAW)\b",
    re.IGNORECASE,
)


# ── Separator patterns ──────────────────────────────────────────────────────── #

# PREFIX ★ Name  /  PREFIX | Name  /  PREFIX - Name
# + allowed so D+ and DISNEY+ are captured.
_SEPARATOR_RE = re.compile(
    r'^([A-Z][A-Z0-9\-+]{1,11})\s*(?:[★|]|-\s+)\s*(.+)$',
    re.IGNORECASE,
)

# Names already stored with a bracket prefix: [SE] Name, [FR] Name
_BRACKET_PREFIX_RE = re.compile(
    r'^\[([A-Z][A-Z0-9\-+]{0,11})\]\s*(.+)$',
    re.IGNORECASE,
)

# Leading-pipe prefix: |WC| Title, |EN| Title (ProSat/ottcst style). The prefix is
# wrapped in pipes at the very start; the standard separator patterns require the
# prefix *before* the separator, so they miss this format entirely.
_LEADING_PIPE_PREFIX_RE = re.compile(
    r'^\|\s*([A-Z][A-Z0-9\-+]{0,11})\s*\|\s*(.+)$',
    re.IGNORECASE,
)

# Separator residue left at the start of a title after a prefix strip: some feeds
# put punctuation AFTER the closing pipe ("|MULTI|. Title" → ". Title").  Requires
# trailing whitespace so a genuine leading-punctuation title (".hack//Sign") is
# never touched.
_POST_PREFIX_RESIDUE_RE = re.compile(r'^[.\-:|,;]+\s+')

# Leading CATEGORY marker: "|EN| ANIME", "|AR-SUB| AMAZON PRIME",
# "|DE| FILME 1990-2023" — a provider ``category`` string (not the channel
# name) that duplicates language/subtitle info already carried elsewhere.
# Mirrors _LEADING_PIPE_PREFIX_RE's shape but separately captures an optional
# "-SUB"/"-DUB" compound suffix so parse_category_marker can route it
# distinctly from a plain language code. See parse_category_marker.
_CATEGORY_MARKER_RE = re.compile(
    r'^\|\s*([A-Z]{2,4})(?:-([A-Z]{2,8}))?\s*\|\s*(.*)$',
    re.IGNORECASE,
)

# The only compound suffixes a category marker recognizes — a gate against the
# shared sub/dub vocabulary (_SUB_DUB_TOKENS) rather than a parallel token
# list, restricted to the two unambiguous kinds evidenced in real category
# data (owner report: "AR-SUB" — 6,474 rows). Any other compound suffix is
# left unrecognized rather than guessed at.
_CATEGORY_MARKER_SUBDUB_KINDS: dict[str, str] = {"SUB": "sub", "DUB": "dub"}

# EPG-embedded event feed: "REGION (NETWORK [CHAN#]) | TITLE (TIMESTAMP)".
# Some providers (TREX/Ninja) encode a scheduled programme directly in the channel
# name: a known region, a broadcaster/network in parens (optionally with a feed
# number), then the programme title and an optional start timestamp. This is
# effectively EPG data inlined in the title — parse_platform_event() decomposes it.
#   "US (Peacock 01) | La Vuelta a España: Stage 11 (2025-09-03 07:20:00)"
#   "US (P+) AFC Champions League 1"   (form A: network feed, no scheduled time)
_PLATFORM_EVENT_RE = re.compile(
    r'^(?P<region>[A-Z]{2,4})\s+\(\s*'
    r'(?P<network>[A-Za-z][A-Za-z0-9+]*)'      # broadcaster/brand: ESPN+, Paramount, P+
    r'(?:\s+(?P<chan>\d+))?\s*\)\s*'           # optional feed/channel number
    r'(?P<rest>.*)$'
)
# Trailing scheduled-time stamp: "(2025-09-03 07:20:00)" at end of the title.
_EVENT_TS_RE = re.compile(
    r'\(\s*(?P<dt>\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}(?::\d{2})?)\s*\)\s*$'
)
# Providers use a far-future date (e.g. 2098-12-31) as an "always available"
# sentinel rather than a real schedule time.
_EVENT_SENTINEL_YEAR = 2090


class PlatformEvent(NamedTuple):
    """Decomposed EPG-embedded event feed (see parse_platform_event)."""
    region: str            # normalized region code (e.g. "US")
    network: str           # broadcaster/brand (e.g. "ESPN+", "Paramount")
    channel_num: str       # feed/channel number as text, or "" if absent
    title: str             # programme title with network/pipe/timestamp stripped
    start_time: Optional[datetime]  # scheduled start, or None (form-A / sentinel)
    always_available: bool # True when the timestamp was the far-future sentinel


class CategoryMarker(NamedTuple):
    """A leading ``|TOKEN|`` marker stripped from a provider category string
    (see :func:`parse_category_marker`).

    Attributes:
        code: Normalized region/language code (e.g. "EN", "AR") — always run
            through :func:`normalize_region_code`.
        kind: "language" for a plain code marker, or "sub"/"dub" for a
            compound ``CODE-SUB``/``CODE-DUB`` marker.
    """
    code: str
    kind: str


def _parse_event_ts(s: str) -> Optional[datetime]:
    """Parse the embedded timestamp ("YYYY-MM-DD HH:MM[:SS]") to a naive datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_platform_event(name: str) -> Optional[PlatformEvent]:
    """Decompose an EPG-embedded event-feed channel name.

    Grammar: ``REGION (NETWORK [CHAN#]) [|] TITLE [(TIMESTAMP)]``. Only accepted
    when REGION is a *known* region code (guards against title words like
    "FBI (2024)"). The network must start with a letter, so a bare year in the
    parens never matches. A far-future timestamp is treated as an
    "always available" sentinel (start_time=None, always_available=True).

    Returns None when the name is not this format.
    """
    if not name:
        return None
    m = _PLATFORM_EVENT_RE.match(name.strip())
    if not m:
        return None
    region = normalize_region_code(m.group("region"))
    if region not in REGION_FULL_NAMES:
        return None

    rest = m.group("rest").strip()
    if rest.startswith("|"):
        rest = rest[1:].strip()

    start_time: Optional[datetime] = None
    always = False
    tm = _EVENT_TS_RE.search(rest)
    if tm:
        rest = rest[: tm.start()].strip()
        dt = _parse_event_ts(tm.group("dt"))
        if dt and dt.year >= _EVENT_SENTINEL_YEAR:
            always = True
        else:
            start_time = dt

    return PlatformEvent(
        region=region,
        network=m.group("network"),
        channel_num=m.group("chan") or "",
        title=rest.strip(" |").strip(),
        start_time=start_time,
        always_available=always,
    )

# Digit-starting prefix tokens excluded from _SEPARATOR_RE ([A-Z]-only grammar): quality
# tokens 4K/8K plus the age rating "18+" — a narrow admission, not a general
# digit+punctuation widening (owner report 2026-09-03: 466 rows, empty detected_prefix).
_DIGIT_QUALITY_PREFIX_RE = re.compile(r'^(4K|8K|18\+)\s*(?:[★|]|-\s+)\s*(.+)$', re.IGNORECASE)

# Bracket-enclosed quality token at name start where the token begins with a digit.
# _BRACKET_PREFIX_RE requires [A-Z] as its first char, so [4K] and [8K] fall through
# without this. Used in step 1 of parse_channel_name to handle "[4K] [US] Title" format.
_QUALITY_DIGIT_BRACKET_RE = re.compile(
    r'^\[(4K|8K)\]\s*(.+)$',
    re.IGNORECASE,
)

# Parenthetical prefix at the very start of a name: (QFR) Title, (TUR) Title.
# Distinct from _LANG_QUALIFIER_RE which matches at the END of a name.
_PAREN_PREFIX_RE = re.compile(
    r'^\(([A-Z]{2,5})\)\s+(.+)$',
    re.IGNORECASE,
)

# Compound prefix: quality token + language/platform code, or vice versa, before a
# separator. Handles "4K-DE - Title", "SE-4K - Title", "PL 4K - Title", and the
# bracket-before-compound form "[US] 4K-DE - Title".
#
# Groups (all via named groups to avoid positional fragility):
#   bracket   optional [BRACKET] prefix (e.g. "US" from "[US]")
#   qual_a    quality from QUALITY-LANG form (e.g. "4K" in "4K-DE")
#   lang_a    lang    from QUALITY-LANG form (e.g. "DE" in "4K-DE")
#   lang_b    lang    from LANG-QUALITY form (e.g. "SE" in "SE-4K")
#   qual_b    quality from LANG-QUALITY form (e.g. "4K" in "SE-4K")
#   lang_c    lang    from LANG QUALITY form (e.g. "PL" in "PL 4K")
#   qual_c    quality from LANG QUALITY form (e.g. "4K" in "PL 4K")
#   title     remainder after the compound prefix + separator
# The optional \[ \] around each quality token sit OUTSIDE the capture group, so
# "IT-[4K] - Title" yields qual="4K" rather than "[4K]" and callers keep getting a
# clean token to normalise. Without it that shape matched nothing at all and the
# whole prefix survived into the title — the owner saw
# "IT-[4K] - Monty Python e il Sacro Graal" rendered verbatim instead of a title
# with IT and 4K lifted into chips.
_COMPOUND_PREFIX_RE = re.compile(
    r'^(?:\[(?P<bracket>[A-Z][A-Z0-9]{0,7})\]\s*)?'
    r'(?:'
    r'\[?(?P<qual_a>4K|8K|UHD|HD|FHD)\]?-(?P<lang_a>[A-Z]{2,4})'
    r'|(?P<lang_b>[A-Z]{2,4})-\[?(?P<qual_b>4K|8K|UHD|HD|FHD)\]?'
    r'|(?P<lang_c>[A-Z]{2,4})\s+\[?(?P<qual_c>4K|8K|UHD|HD|FHD)\]?'
    r')\s*(?:[★|]|-\s+)\s*(?P<title>.+)$',
    re.IGNORECASE,
)

_QUALITY_SUFFIX_RE = re.compile(
    r'\s+\b('
    r'4K|8K|UHD|FHD|HDR10\+?|HDR|HDTV|HD|SD|HQ|LQ'          # tiers
    # RAW is deliberately ABSENT: 'EN - WWE Raw (2023)' is a title, not a
    # quality, and tests/test_raw_live_cam_fix.py has guarded that since
    # regression B0. RAW is recognised only where it CANNOT be a title word —
    # as superscript decoration, bracketed, or in a slash-joined pair.
    r'|HEVC|H\.?26[45]|X26[45]|AVC|AV1|VP9|MPEG-?2'         # encodings (routed out)
    r'|\d{3,4}[pPiI]'                                       # 1080p, 3840P, 480i
    r'|\d{2,3}\s?FPS'                                       # 60fps
    r'|VIP|PPV|GOLD|ULTRA|PREMIUM'                          # tiers (routed out)
    r'|DDP?[0-9.]*|E?AC3|AAC[0-9.]*|DTS(?:-HD)?|TRUEHD|ATMOS|FLAC|OPUS'  # audio codecs
    r')\b\s*$',
    re.IGNORECASE,
)

# Audio format bracket suffix at end: [Multi-Sub], [Dub], [DUBBED], etc.
_BRACKET_SUFFIX_RE = re.compile(r'\s*\[([^\]]+)\]\s*$')

# Explicit lang/region qualifier in parens at end: (EN), (JP) — 2-3 uppercase letters only
_LANG_QUALIFIER_RE = re.compile(r'\s*\(([A-Z]{2,3})\)\s*$', re.IGNORECASE)

# Year at end: (2020), (1993-2002), (1993–2002), or provider suffix " - 2025"
_YEAR_RE = re.compile(
    r'(?:\s*\((\d{4}(?:[-–]\d{4})?)\)'   # group 1: (2025) or (1993-2002)
    r'|\s+-\s+(\d{4}))'                   # group 2: - 2025
    r'\s*$'
)

# A real 4-digit year (or year-range) in parens, anywhere in the string — NOT anchored
# to the end. Used by the mid-name year pre-cut in parse_channel_name (step 1b) to find
# a "(1996)" that has trailing text after it (cast/extra credits), e.g.
# "From Dusk Till Dawn 4K (1996) HARVEY KEITEL, TARANTINO". Restricted to 19xx/20xx so
# it never matches an arbitrary parenthetical like "(Director's Cut)" or "(Soleil Noir)".
_PAREN_YEAR_ANYWHERE_RE = re.compile(r'\((19\d{2}|20\d{2})(?:[-–](19\d{2}|20\d{2}))?\)')

# ── Trailing metadata after a mid-string "(YYYY)" ───────────────────────────── #
#
# Providers append a marker AFTER the year — "Christmas At Castle Hart (2021)
# Hallmark".  The year strip is end-anchored, so anything after it hid the year
# entirely: 2,092 rows across 478 distinct trailers parsed with year="" and kept
# "(2021) Hallmark" inside detected_title, which then keyed to the coarse
# yearless content_key AND could not match its own siblings.
#
# The year itself is never ambiguous, so it is now always extracted.  The
# trailing TEXT is only removed from the title when we can NAME what it is —
# 383 of those 478 trailers are singletons that may well be real subtitles
# ("FBI (2024) Reboot"), and silently eating them would trade one wrong title
# for another.  Recognised → routed to a facet; unrecognised → left in the
# title, year still extracted.

# Self-labelling: "- Lucky Luke Collection", "- Gullivers Collection".  Needs no
# curation at all — the provider says what it is.
_TRAILING_COLLECTION_RE = re.compile(r'^-?\s*(.+?)\s+Collection$', re.IGNORECASE)

# Studio / franchise names that appear as a bare trailing token.  Curated data
# lives here and only here (CLAUDE.md lookup-table rule).
_TRAILING_COLLECTIONS = {
    "hallmark": "Hallmark",
    "aardman": "Aardman",
    "minions": "Minions",
    "cheech and chong": "Cheech and Chong",
    "jay and silent bob": "Jay and Silent Bob",
    "ciccio e franco": "Ciccio e Franco",
}

# Dub / subtitle / audio-track markers in the provider's own language.
_TRAILING_AUDIO_TOKENS = {
    "sinhronizirano": ("dub", "Slovenian"),
    "polski": ("dub", "Polish"),
    "makedonski": ("dub", "Macedonian"),
    "dubbing": ("dub", ""),
    "dubbing kino": ("dub", ""),
    "lektor": ("dub", "Polish"),
    "lektor (ai)": ("dub", "Polish"),
    "bg.audio": ("dub", "Bulgarian"),
    "bgaudio": ("dub", "Bulgarian"),
    "napisy": ("sub", "Polish"),
    "vostfr": ("sub", "French"),
}

# "- Dubbed in Albanian" / "- Dubbed in Greek".
_TRAILING_DUBBED_IN_RE = re.compile(r'^-?\s*Dubbed\s+in\s+(.+)$', re.IGNORECASE)

# Provider genre words that trail the year.
_TRAILING_GENRE_TOKENS = {
    "dokument": "Documentary",
    "animacja": "Animation",
}


def classify_trailing_metadata(text: str) -> Optional[tuple[str, str]]:
    """Classify text found AFTER a mid-string ``(YYYY)`` marker.

    Returns a ``(kind, value)`` pair — kind is one of ``collection`` / ``dub`` /
    ``sub`` / ``genre`` / ``rating`` / ``quality`` — or ``None`` when the text is
    not recognised, in which case the caller must LEAVE IT IN THE TITLE rather
    than guess.  That conservative default is the whole point: the trailing slot
    holds real subtitles as well as provider metadata, and only the second kind
    may be moved out of the name.

    Args:
        text: Raw trailing text, e.g. ``"Hallmark"`` or ``"- Dubbed in Albanian"``.

    Returns:
        ``(kind, value)`` when recognised, else ``None``.
    """
    t = (text or "").strip()
    if not t:
        return None
    low = t.lower().lstrip("- ").strip()

    if m := _TRAILING_COLLECTION_RE.match(t):
        return ("collection", m.group(1).strip())
    if m := _TRAILING_DUBBED_IN_RE.match(t):
        return ("dub", m.group(1).strip().title())
    if low in _TRAILING_COLLECTIONS:
        return ("collection", _TRAILING_COLLECTIONS[low])
    if low in _TRAILING_AUDIO_TOKENS:
        kind, lang = _TRAILING_AUDIO_TOKENS[low]
        return (kind, lang)
    if low in _TRAILING_GENRE_TOKENS:
        return ("genre", _TRAILING_GENRE_TOKENS[low])
    if low in AGE_RATING_PREFIXES:
        return ("rating", low)
    if t.upper() in QUALITY_TOKENS:
        return ("quality", t.upper())
    return None

# ── Title-qualifier strip patterns (single-source-of-truth; also used by content_dedup) ── #

# Trailing parenthetical single-token qualifier — no internal space, letter-first.
# Strips:  (US), (VOSTFR), (HQ), (LQ), (BR), (ENG-SUB), (MULTI-DUB), (Dubbed), …
# Multi-word qualifiers like (ENG DUB) or (SPANISH ENG-SUB) are NOT matched here;
# they are handled by PAREN_MULTI_QUALIFIER_RE + _is_all_qualifier_tokens() below.
PAREN_QUALIFIER_RE = re.compile(r"\s*\(([A-Za-z][A-Za-z0-9\-/]{0,25})\)\s*$")

# Trailing parenthetical that contains an internal space — may be a multi-token
# dub/sub/lang qualifier like (ENG DUB) or (SPANISH ENG-SUB), or a real alt-title
# like (Soleil Noir) or (30 Monedas).  The strip decision is NOT made by regex
# alone — _is_all_qualifier_tokens() checks every leaf against the recognized vocab.
PAREN_MULTI_QUALIFIER_RE = re.compile(r"\s*\(([^()]+)\)\s*$")

# Trailing parenthetical digit-starting quality tokens: (4K), (8K).
# Separate from PAREN_QUALIFIER_RE because that regex requires a letter-first token.
PAREN_DIGIT_QUALITY_RE = re.compile(r"\s*\((4K|8K)\)\s*$", re.IGNORECASE)

# Trailing bracket qualifier that contains an internal separator (space, slash, or dash):
# [Multi Audio/Sub], [ENG-SUB], [Multi-Sub]. The separator requirement keeps single-token
# brackets (already handled by _bracket_suffix steps) from being double-stripped.
BRACKET_QUALIFIER_RE = re.compile(r"\s*\[[^\[\]]*[\s/\-][^\[\]]*\]\s*$")

# Trailing year in parens/brackets (dedup-style, wider than _YEAR_RE):
# (2024), [2024], (2000-2005), (2024?), bare "2024", or "- 2024".
# NOTE: the bare ``\s+\d{4}$`` branch deliberately over-strips for the dedup-KEY
# normalization in content_dedup (collapsing "Blade Runner 2049" → "blade runner" is
# an accepted key compromise). It must NOT be used to clean the *display* title —
# strip_title_qualifiers uses the narrower PAREN_YEAR_SUFFIX_RE below so legitimate
# numeric titles ("Blade Runner 2049", "Space 1999", "The 4400") survive on screen.
YEAR_SUFFIX_RE = re.compile(
    r"\s*[\(\[]\d{4}(?:[-–]\d{4})?[?]?[\)\]]$"
    r"|\s+\d{4}$"
    r"|\s+-\s+\d{4}$"
)

# Display-safe trailing-year strip: ONLY parenthesized/bracketed year markers, which
# are unambiguous metadata — "(2024)", "[2024]", "(2000-2005)", "(2024?)". A bare
# trailing number (often part of the real title: 2049, 1999, 4400) is NOT stripped.
PAREN_YEAR_SUFFIX_RE = re.compile(r"\s*[\(\[]\d{4}(?:[-–]\d{4})?[?]?[\)\]]\s*$")

# Trailing quality markers used in the dedup normalization pass (global, no anchoring).
# Distinct from _QUALITY_SUFFIX_RE (which is anchored to end-of-bare-name for parsing).
QUALITY_ANYWHERE_RE = re.compile(
    r"\b(4K|8K|UHD|FHD|HD|SDR|HDR10?\+?|SD|HQ|LQ|RAW|HEVC|H\.?265)\b", re.IGNORECASE
)


def strip_title_qualifiers(bare: str) -> str:
    """Strip trailing single-token and recognized multi-token qualifier parentheticals.

    Applies a loop until stable, removing:
    - Single-token paren qualifiers with no internal space: (US), (VOSTFR), (HQ), (LQ),
      (BR), (ENG-SUB), (MULTI-DUB), (Dubbed), …
    - Multi-token parens where EVERY space/dash/slash-split leaf is a recognized lang,
      region, quality, or sub/dub marker token: (ENG DUB), (SPANISH ENG-SUB),
      (DUAL AUDIO), (MULTI SUB), (VOST FR), (LEG PT), (PT BR).
    - Digit-starting quality tokens in parens: (4K), (8K).
    - Bracket qualifiers with internal separators: [Multi Audio/Sub], [ENG-SUB].
    - Parenthesized/bracketed year markers ONLY: (2024), [2024], (2000-2005).

    Preserves multi-word alt-language titles where ANY token is unrecognized:
    (30 Monedas), (Soleil Noir), (New York), (The Beginning) all stay intact.
    Also preserves a bare trailing number that is part of the real title —
    "Blade Runner 2049", "Space 1999", "The 4400" — by stripping only
    PARENTHESIZED years, never a bare ``\\s+\\d{4}$`` (that aggressive form stays
    in content_dedup's key normalization).

    Args:
        bare: The bare channel name after prefix and quality stripping.

    Returns:
        The title with trailing qualifiers removed, whitespace-stripped.
    """
    prev = None
    while prev != bare:
        prev = bare
        bare = PAREN_YEAR_SUFFIX_RE.sub("", bare).strip()
        # Single-token paren qualifier — strip ONLY when the token is a recognized
        # qualifier (US, HQ, VOSTFR, ENG-SUB, …) or an unambiguous sub/dub marker.
        # A bare word like "(Reprise)"/"(Unplugged)"/"(Deluxe)" is a real alt-title
        # qualifier — preserve it (same vocab gate the multi-token branch uses).
        m_single = PAREN_QUALIFIER_RE.search(bare)
        if m_single and (
            _is_all_qualifier_tokens(m_single.group(1))
            or _has_unambiguous_subdub(m_single.group(1))
        ):
            bare = bare[: m_single.start()].strip()
        bare = PAREN_DIGIT_QUALITY_RE.sub("", bare).strip()
        bare = BRACKET_QUALIFIER_RE.sub("", bare).strip()
        # Multi-token parentheticals: strip when EVERY leaf token is recognized, OR
        # when the parenthetical is all-alphabetic and contains an unambiguous sub/dub
        # marker (catches language+sub qualifiers like "(JAPANESE ENG-SUB)", "(KURDISH DUB)",
        # "(NORWEGIAN SUB)" whose language word is absent from the recognized vocab).
        m = PAREN_MULTI_QUALIFIER_RE.search(bare)
        if m and (
            _is_all_qualifier_tokens(m.group(1))
            or _has_unambiguous_subdub(m.group(1))
        ):
            bare = bare[: m.start()].strip()
    return bare


def _strip_title_qualifiers_collecting(bare: str) -> tuple[str, list[str]]:
    """Like ``strip_title_qualifiers`` but also returns the inner content of each stripped qualifier.

    Used by ``parse_channel_name`` step 6c to intercept stripped sub/dub annotations
    so that ``extract_audio_annotation`` can derive language facets from them.

    Returns:
        ``(cleaned_bare, list_of_inner_contents)`` where each element in
        ``list_of_inner_contents`` is the content *inside* a stripped paren/bracket,
        suitable for passing to ``extract_audio_annotation``.
    """
    # Regex that matches and captures the inner content of a single-token paren qualifier.
    _PAREN_INNER_RE = re.compile(r"\s*\(([A-Za-z][A-Za-z0-9\-/]{0,25})\)\s*$")
    # Regex that matches and captures the inner content of a bracket qualifier.
    _BRACKET_INNER_RE = re.compile(r"\s*\[([^\[\]]*[\s/\-][^\[\]]*)\]\s*$")

    stripped_inners: list[str] = []
    prev = None
    while prev != bare:
        prev = bare
        # Year suffixes — not audio annotations; skip collecting
        bare = PAREN_YEAR_SUFFIX_RE.sub("", bare).strip()
        # Single-token paren qualifiers — strip + collect ONLY when recognized
        # (preserve real alt-titles like "(Reprise)"; mirror strip_title_qualifiers).
        m_pq = _PAREN_INNER_RE.search(bare)
        if m_pq and (
            _is_all_qualifier_tokens(m_pq.group(1))
            or _has_unambiguous_subdub(m_pq.group(1))
        ):
            stripped_inners.append(m_pq.group(1))
            bare = bare[: m_pq.start()].strip()
        # Digit quality in parens — not audio, skip
        bare = PAREN_DIGIT_QUALITY_RE.sub("", bare).strip()
        # Bracket qualifiers — collect inner content
        m_bq = _BRACKET_INNER_RE.search(bare)
        if m_bq:
            stripped_inners.append(m_bq.group(1))
        bare = BRACKET_QUALIFIER_RE.sub("", bare).strip()
        # Multi-token parentheticals
        m = PAREN_MULTI_QUALIFIER_RE.search(bare)
        if m and (
            _is_all_qualifier_tokens(m.group(1))
            or _has_unambiguous_subdub(m.group(1))
        ):
            stripped_inners.append(m.group(1))
            bare = bare[: m.start()].strip()
    return bare, stripped_inners


def extract_audio_annotation(inner: str) -> tuple[str, list[str], list[str], list[str]]:
    """Extract audio facets from a sub/dub/multi parenthetical inner string.

    Given the content *inside* a trailing parenthetical or bracket (e.g. ``"ENG DUB"``,
    ``"SPANISH ENG-SUB"``, ``"VOSTFR"``, ``"Multi-Sub"``, ``"DUAL AUDIO"``), returns
    a 4-tuple ``(form, audio_langs, dub_langs, sub_langs)`` where:

    - ``form``       — canonical presentation form: ``"Dub"``, ``"Sub"``, ``"Multi"``,
                       ``"Dual"``, ``"Original"`` (inferred), or ``""`` (unknown).
    - ``audio_langs``— languages for the audio track (the "original" audio). Empty when
                       no specific language can be determined for the audio track.
    - ``dub_langs``  — languages present as a dubbed audio track.
    - ``sub_langs``  — languages present as subtitles. ``"Multi"`` is the special
                       sentinel when a multi-subtitle annotation is detected.

    Assignment logic (in annotation order):
    - ``VOSTFR``  → form=Original, sub_langs=[French]
    - ``VOSTA``   → form=Original, sub_langs=[Spanish]
    - ``Multi-Sub``/``Multi Audio``/``MULTI`` → form=Multi, sub_langs=["Multi"]
    - ``DUAL AUDIO``/``DUAL`` → form=Dual  (no lang assignment)
    - ``LANG DUB``  → form=Dub, dub_langs=[LANG]
    - ``LANG-SUB``/``LANG SUB`` → sub_langs=[LANG]; form inferred as Original (audio not dubbed)
    - ``LANG``     → audio_langs=[LANG]  (primary/original audio language)
    - When both a LANG and a SUB/DUB marker are present in the same annotation, the
      LANG immediately adjacent to the SUB marker goes to sub_langs (or dub_langs),
      and any preceding unqualified LANG goes to audio_langs.

    Conservative: only maps tokens confidently present in AUDIO_LANG_WORD_MAP.
    Unknown language words are silently dropped — stripping still proceeds (unchanged).

    Args:
        inner: The raw content between the outer delimiters, e.g. ``"SPANISH ENG-SUB"``.

    Returns:
        ``(form, audio_langs, dub_langs, sub_langs)``
    """
    up = inner.strip().upper()

    # ── Special-case complete-match forms first ──────────────────────────────── #
    # VOSTFR: original audio + French subtitles (very common in FR provider data)
    if re.match(r'^VOSTFR$', up):
        return ("Original", [], [], ["French"])
    # VOSTA: original audio + Spanish subtitles
    if re.match(r'^VOSTA$', up):
        return ("Original", [], [], ["Spanish"])
    # VOST alone: original audio, subtitle language unspecified
    if re.match(r'^VOST$', up):
        return ("Original", [], [], [])
    # OV (Original Version), OMU (Original with German subtitles)
    if re.match(r'^OV$', up):
        return ("Original", [], [], [])
    if re.match(r'^OMU$', up):
        return ("Original", [], [], ["German"])

    # Multi forms
    multi_key = re.sub(r'[\s\-/]', '', up)  # e.g. "MULTI-SUB" → "MULTISUB"
    if multi_key in ("MULTI", "MULTISUB", "MULTIAUDIO", "MUTISUB", "MUTIAUDIO",
                     "MULTILANGUAGE", "MULTIAU", "MULTIAUDIOSUB"):
        return ("Multi", [], [], ["Multi"])
    # Multi as standalone token that may have audio in it
    if up.startswith("MULTI") and "DUB" not in up and "SUB" not in up:
        # e.g. "MULTI LANGUAGE" — cover the full multi family
        if "LANGUAGE" in up or "AUDIO" in up or up == "MULTI":
            return ("Multi", [], [], ["Multi"])

    # Dual audio
    if re.match(r'^DUAL(\s+AUDIO)?$', up) or re.match(r'^DUAL AUDIO$', up):
        return ("Dual", [], [], [])

    # Legendado / LEG — Portuguese subtitle indicator (subtitled in Portuguese)
    if re.match(r'^LEG(ENDADO?)?$', up):
        return ("Sub", [], [], ["Portuguese"])

    # Subtitulado — Spanish subtitle indicator
    if re.match(r'^SUBTITULADO$', up):
        return ("Sub", [], [], ["Spanish"])

    # ── Token-by-token parsing for compound annotations ──────────────────────── #
    # Split on whitespace, hyphen, and slash to get individual tokens.
    tokens = [t for t in re.split(r'[\s\-/]+', up) if t]

    # Identify which tokens are DUB markers and which are SUB markers.
    _DUB_MARKERS = frozenset({"DUB", "DUBBED", "DUBBING"})
    _SUB_MARKERS = frozenset({"SUB", "SUBS", "SUBBED", "SUBTITLED",
                               "SUBTITULADO", "SUBTITLE", "SUBTITLES",
                               "LEG", "LEGENDADO", "LEGENDADOS"})
    _MULTI_MARKERS = frozenset({"MULTI", "MUTI", "MULTISUB"})
    _AUDIO_NEUTRAL = frozenset({"AUDIO"})  # neutral — adjacent token determines meaning

    form: str = ""
    audio_langs: list[str] = []
    dub_langs: list[str] = []
    sub_langs: list[str] = []
    pending_lang: str | None = None  # lang token waiting for a role marker

    for _i, tok in enumerate(tokens):
        if tok in _MULTI_MARKERS:
            form = "Multi"
            if not sub_langs:
                sub_langs = ["Multi"]
            pending_lang = None
            continue

        if tok in _DUB_MARKERS:
            form = "Dub"
            if pending_lang:
                dub_langs.append(pending_lang)
                pending_lang = None
            continue

        if tok in _SUB_MARKERS:
            if not form or form == "Original":
                form = "Original"  # subs present without dub → original audio
            if pending_lang:
                sub_langs.append(pending_lang)
                pending_lang = None
            continue

        if tok in _AUDIO_NEUTRAL:
            # AUDIO alone is ambiguous (could be "DUAL AUDIO" or "MULTI AUDIO")
            # — handled by multi/dual detection above; here it means a lang context
            continue

        # Try to resolve as a language
        lang_name = AUDIO_LANG_WORD_MAP.get(tok)
        if lang_name:
            # Look ahead: if next token is a SUB/DUB marker, it goes there.
            # Otherwise it's a pending audio-track language.
            if pending_lang:
                # There was already a pending lang — flush it to audio (unqualified)
                audio_langs.append(pending_lang)
            pending_lang = lang_name
        # Non-language, non-marker tokens are silently ignored (conservative)

    # Flush any remaining pending_lang to audio (original/unqualified)
    if pending_lang:
        audio_langs.append(pending_lang)

    # Infer form when not yet set
    if not form:
        if sub_langs and not dub_langs:
            form = "Original"   # subs only → original audio inferred
        elif dub_langs:
            form = "Dub"
        # else: no form — unknown single-language annotation (just audio_langs)

    return (form, audio_langs, dub_langs, sub_langs)


# Pre-built recognized-token set for _is_all_qualifier_tokens() — covers all
# vocabulary that can legitimately appear as individual leaf tokens inside a
# multi-word trailing parenthetical qualifier.  Built once at import time.
#
# Includes: uppercase lang full-names, bracket-lang keys, region codes in
# REGION_FULL_NAMES, quality tokens, and bare sub/dub markers.
# A leaf is recognized when its uppercased/stripped form is in this set.
_RECOGNIZED_QUALIFIER_TOKENS: frozenset[str] = (
    frozenset(_BRACKET_LANG_NORM.keys())                  # SPANISH, FRENCH, HINDI …
    | frozenset(k.upper() for k in _FULL_NAME_TO_CODE)   # ARGENTINA, BRAZIL …
    | frozenset(k.upper() for k in _ALIAS_MAP)            # ENG, USA, LATIN …
    | frozenset(REGION_FULL_NAMES.keys())                  # US, UK, FR, ARG, LAT …
    | QUALITY_TOKENS                                        # 4K, 8K, HD, HEVC …
    | _SUB_DUB_TOKENS                                      # SUB, DUB, VOSTFR, LEG …
    # Bare audio-language words (KURDISH, NORWEGIAN, JAPANESE …) — a single-token
    # language parenthetical "(KURDISH)" is a strippable qualifier (and an audio-lang
    # facet feeder), not an alt-title like "(Reprise)". Single-word keys only.
    | frozenset(k.upper() for k in AUDIO_LANG_WORD_MAP if " " not in k and "-" not in k and "/" not in k)
    # Single-word _AUDIO_NORM keys (e.g. MULTI, MUTI) — multi-word keys like
    # "MULTI SUB" are compound phrases; their individual words are already covered
    # by _SUB_DUB_TOKENS, but "MULTI"/"MUTI" alone need explicit inclusion.
    | frozenset(k for k in _AUDIO_NORM if " " not in k and "-" not in k and "/" not in k)
)


def _is_all_qualifier_tokens(inner: str) -> bool:
    """Return True when every leaf token in *inner* is a recognized qualifier token.

    Used to decide whether a space-containing trailing parenthetical is a
    strippable dub/sub/lang qualifier or a real alt-title to preserve.

    Algorithm:
    1. Split *inner* on whitespace, hyphens, and slashes into leaf tokens.
    2. Discard empty strings (consecutive separators).
    3. Return True only when the content is non-empty AND every leaf token,
       uppercased, appears in the pre-built ``_RECOGNIZED_QUALIFIER_TOKENS`` set.

    Examples that return True (all leaves recognized):
        "ENG DUB"         → {"ENG", "DUB"}   — both recognized
        "SPANISH ENG-SUB" → {"SPANISH", "ENG", "SUB"} — all recognized
        "DUAL AUDIO"      → {"DUAL", "AUDIO"} — both recognized
        "VOST FR"         → {"VOST", "FR"}    — both recognized
        "PT BR"           → {"PT", "BR"}      — both recognized (lang + region)

    Examples that return False (an unrecognized leaf → preserve as alt-title):
        "Soleil Noir"     → {"SOLEIL", "NOIR"} — neither recognized
        "30 Monedas"      → {"30", "MONEDAS"}  — neither recognized
        "New York"        → {"NEW", "YORK"}    — neither recognized
        "The Beginning"   → {"THE", "BEGINNING"} — neither recognized

    Args:
        inner: The text content between the outer parentheses (not including them).

    Returns:
        True when the parenthetical is a strippable qualifier; False to preserve.
    """
    leaves = [t for t in re.split(r"[\s\-/]+", inner.strip()) if t]
    if not leaves:
        return False
    return all(leaf.upper() in _RECOGNIZED_QUALIFIER_TOKENS for leaf in leaves)


def _has_unambiguous_subdub(inner: str) -> bool:
    """True when *inner* is an all-alphabetic token run containing an unambiguous sub/dub marker.

    Anchored on an unambiguous marker (SUB/DUB/VOST/LEG family), this strips
    language+sub qualifiers whose language word is not in the recognized vocab
    (e.g. "JAPANESE ENG-SUB", "KURDISH SUB", "PERSIAN DUB") while the all-alpha
    guard prevents matching real titles that merely end in a parenthetical
    containing a digit (e.g. "Episode 5 SUB" is left intact because "5" is
    not alphabetic).

    Args:
        inner: The text content between the outer parentheses (not including them).

    Returns:
        True when the parenthetical is a strippable sub/dub annotation; False to preserve.
    """
    leaves = [p for p in re.split(r"[\s\-/]+", inner.strip()) if p]
    if not leaves:
        return False
    if not all(leaf.isalpha() for leaf in leaves):
        return False
    return any(leaf.upper() in _UNAMBIGUOUS_SUBDUB_MARKERS for leaf in leaves)


def is_category_header(name: str) -> bool:
    """Return True when *name* is a provider category-header/separator row.

    Category headers are label rows injected by some providers to group channels
    in the source playlist (e.g. ``##### BEIN SPORTS #####``,
    ``###### RELAX 4K ######``, ``##### BE SPORTS HD ##### · HD``). They are NOT
    playable streams and must be excluded from all content surfaces.

    Detection rule: the name starts with 2 or more ``#`` characters (after
    stripping leading whitespace). A single leading ``#`` (``#1 News``) and an
    interior ``#`` (``CH#5``) are NOT headers and must not match.
    """
    stripped = name.lstrip() if name else ""
    return len(stripped) >= 2 and stripped[0] == "#" and stripped[1] == "#"


def parse_category_marker(category: str) -> tuple[str, Optional[CategoryMarker]]:
    """Strip a leading ``|TOKEN|`` marker from a provider category string.

    Real provider category strings carry a leading pipe-delimited marker that
    duplicates channel-name language/subtitle information, e.g.
    ``"|EN| ANIME"``, ``"|AR-SUB| AMAZON PRIME"``, ``"|DE| FILME 1990-2023"``.
    This strips the marker and classifies it — a plain code is a
    :class:`CategoryMarker` with ``kind="language"``; a ``CODE-SUB``/
    ``CODE-DUB`` compound is ``kind="sub"``/``"dub"`` — reusing
    :func:`normalize_region_code` and the shared sub/dub vocabulary
    (:data:`_SUB_DUB_TOKENS` via :data:`_CATEGORY_MARKER_SUBDUB_KINDS`) rather
    than inventing parallel data. An unrecognized compound suffix (anything
    but SUB/DUB) is left alone — the whole string is returned unchanged with
    no marker, per the "don't guess beyond it" rule.

    Args:
        category: The raw provider ``category`` string (may be ``None``/empty).

    Returns:
        ``(clean_category, marker)`` — ``clean_category`` has the marker
        removed and whitespace collapsed (or is the original text,
        whitespace-collapsed, when no marker is recognized); ``marker`` is
        ``None`` when no leading marker was recognized.
    """
    if not category:
        return category or "", None
    collapsed = " ".join(category.split())
    m = _CATEGORY_MARKER_RE.match(collapsed)
    if not m:
        return collapsed, None
    code_raw, suffix_raw, rest = m.group(1), m.group(2), m.group(3)
    clean = " ".join(rest.split())
    if suffix_raw:
        suffix_upper = suffix_raw.upper()
        kind = (
            _CATEGORY_MARKER_SUBDUB_KINDS.get(suffix_upper)
            if suffix_upper in _SUB_DUB_TOKENS else None
        )
        if kind is None:
            # Unrecognized compound (not SUB/DUB) — don't guess, leave as-is.
            return collapsed, None
        return clean, CategoryMarker(code=normalize_region_code(code_raw), kind=kind)
    return clean, CategoryMarker(code=normalize_region_code(code_raw), kind="language")


# Bare "multiple audio/subtitle tracks available" indicator tokens — distinct
# from _SUB_DUB_TOKENS (a specific sub/dub *role*) because these denote "more
# than one track"; MUTI is the common missing-L typo, MULTISUB the compound
# form. Own constant (not folded into _SUB_DUB_TOKENS or the *function*-local
# ``_MULTI_MARKERS`` in extract_audio_annotation) so it stays scoped to
# collection-string cleanup and never reshapes the (deliberately conservative
# — see the DUAL/AUDIO/MULTI caveat near _UNAMBIGUOUS_SUBDUB_MARKERS)
# title-parenthetical qualifier logic.
_MULTI_TRACK_TOKENS: frozenset[str] = frozenset({"MULTI", "MUTI", "MULTISUB"})

# Leading pipe-delimited marker _CATEGORY_MARKER_RE didn't recognize because
# its code exceeds that regex's 2-4 char slot (e.g. "MULTI" is 5 chars);
# strip_collection_noise_tokens() below re-examines this shape and removes it
# when every token inside is noise.
_LEADING_BRACKET_RE = re.compile(r'^\|\s*([^|]+?)\s*\|\s*')

# Collection-noise vocabulary: a token duplicating the quality chip
# (QUALITY_TOKENS), sub/dub chip (_SUB_DUB_TOKENS), multi-track marker
# (_MULTI_TRACK_TOKENS), or media-type icon (MEDIA_TYPE_TOKENS).
_COLLECTION_NOISE_TOKENS: frozenset[str] = (
    QUALITY_TOKENS | _SUB_DUB_TOKENS | _MULTI_TRACK_TOKENS | MEDIA_TYPE_TOKENS
)

# TRAILING-token pass vocabulary — deliberately excludes MEDIA_TYPE_TOKENS.
# Measured against the owner's real 486,588-row library: the whole-span gate
# above only cleans ~5.2% of noisy rows, since real feeds usually tack ONE
# quality/sub-dub/multi word onto an otherwise-real name ("HINDI SUBS",
# "FILMOVI 4K UHD") rather than making the whole string noise — safe to peel
# one at a time. Media words are NOT safe to peel this way ("TAMIL MOVIES" /
# "NORDIC FILMS" are legitimate names; a media word can also LEAD, "MOVIES
# 2018-2021"), so MEDIA_TYPE_TOKENS only participates in the whole-span gate,
# where "every token is noise" already proves the media word names nothing.
_TRAILING_NOISE_TOKENS: frozenset[str] = (
    QUALITY_TOKENS | _SUB_DUB_TOKENS | _MULTI_TRACK_TOKENS
)

# Matches the string's last whitespace/hyphen/slash-delimited leaf plus any
# separator run before it — group 1 is the leaf; slicing at m.start() drops
# leaf+separator while leaving the kept prefix untouched/unreformatted.
_TRAILING_TOKEN_RE = re.compile(r'[\s\-/]*([^\s\-/]+)\s*$')


def _is_collection_noise_token(token: str) -> bool:
    """Return True when *token* (any case) is in :data:`_COLLECTION_NOISE_TOKENS`."""
    return token.upper() in _COLLECTION_NOISE_TOKENS


def _is_trailing_noise_token(token: str) -> bool:
    """Return True when *token* (any case) is in :data:`_TRAILING_NOISE_TOKENS`."""
    return token.upper() in _TRAILING_NOISE_TOKENS


def strip_collection_noise_tokens(collection: str | None) -> str | None:
    """Strip provider-category tokens already conveyed elsewhere on the row.

    ``detected_collection`` (the comfy-row line-2 chip) is derived from the
    provider's raw category string via :func:`parse_category_marker`. Real
    feeds routinely repeat information the row already shows via its own
    dedicated chips/icon — a quality tier duplicating the quality chip
    (``detected_quality``), a media-type word duplicating the media-type
    icon, or a multi-track/sub-dub marker duplicating the subtitle-marker
    chip (``detected_collection_subdub``). This strips that noise so the
    chip only carries what actually names the collection/provider bundle
    (e.g. ``"|MULTI| APPLE+ KIDS"`` -> ``"APPLE+ KIDS"``).

    Mirrors :func:`_is_all_qualifier_tokens`'s established "strip only when
    the WHOLE span is noise" idiom for its first two passes — never remove a
    single noise word out of otherwise-meaningful running text that way,
    since that risks mangling a real collection name that merely *contains*
    a noise-vocabulary word (e.g. ``"SERIES MANIA"`` must survive intact:
    "MANIA" alone is not the collection's name, "SERIES MANIA" together is).
    Three passes:

    1. **Leading bracket marker** — a leading ``|TOKEN|`` (or multi-word
       ``|TOKEN TOKEN|``) group left behind by :func:`parse_category_marker`
       because its code was too long for that regex's 2-4 char code slot
       (e.g. ``"|MULTI|"`` — 5 chars) is stripped whenever every token
       inside the brackets is noise. Repeats for consecutive leading
       brackets.
    2. **Free-text body, whole-span** — the remaining text is cleared to
       ``""`` only when EVERY token in it is noise (e.g. ``"MULTISUB SERIES
       4K"`` — all three tokens are noise, so the whole chip disappears). A
       single non-noise token anywhere in the body means this pass leaves
       it untouched.
    3. **Free-text body, trailing run** — when pass 2 didn't clear
       everything, peel a *trailing* run of quality/sub-dub/multi-track
       tokens one at a time (looping — ``"FILMOVI 4K UHD"`` -> ``"FILMOVI"``)
       from :data:`_TRAILING_NOISE_TOKENS`. Deliberately excludes
       :data:`MEDIA_TYPE_TOKENS`: measured against the owner's real
       library, real collection names routinely lead OR end with a bare
       media word that is part of the name — ``"TAMIL MOVIES"``, ``"NORDIC
       FILMS"``, ``"MOVIES 2018-2021"`` — so a media word never gets peeled
       here (only pass 2's whole-span check can remove one, and only when
       every other token is *also* noise). Never peels past the last
       remaining token — pass 2 already guarantees at least one non-noise
       (full-vocabulary) token survives by the time this pass runs, so a
       single noise token alone always resolves via pass 2's ``""``, never
       via this pass leaving it behind.

    Token matching is whole-token only (never a substring) — the body is
    split on whitespace/hyphen/slash and each leaf is compared by exact
    (case-insensitive) set membership, so ``"4K"`` never damages a
    collection legitimately named ``"24K"`` and ``"SERIES"`` never touches
    ``"SERIES MANIA"``.

    Args:
        collection: The raw ``detected_collection`` candidate (already run
            through :func:`parse_category_marker`), or ``None``/``""``.

    Returns:
        The cleaned string; ``None``/``""`` input is returned unchanged;
        stripping every token in pass 2 yields ``""`` (the caller normalizes
        that to ``None`` so no empty chip renders — never re-run at paint
        time); pass 3 always leaves at least one token.
    """
    if not collection:
        return collection

    working = collection
    while True:
        m = _LEADING_BRACKET_RE.match(working)
        if not m:
            break
        leaves = [t for t in re.split(r"[\s\-/]+", m.group(1).strip()) if t]
        if not leaves or not all(_is_collection_noise_token(t) for t in leaves):
            break
        working = working[m.end():].strip()

    body_tokens = [t for t in re.split(r"[\s\-/]+", working.strip()) if t]
    if body_tokens and all(_is_collection_noise_token(t) for t in body_tokens):
        return ""

    # Pass 3: peel a trailing run of quality/sub-dub/multi tokens — never
    # media-type (see docstring) — one leaf at a time, never past the last
    # remaining token.
    while True:
        leaves = [t for t in re.split(r"[\s\-/]+", working.strip()) if t]
        if len(leaves) <= 1 or not _is_trailing_noise_token(leaves[-1]):
            break
        m = _TRAILING_TOKEN_RE.search(working)
        working = working[: m.start()].rstrip()

    return working


def collection_display(collection: str | None, platform_code: str | None = None) -> str | None:
    """Render-layer transform for the channel-list collection chip (#257).

    CHANNEL LIST ONLY — never touches the stored ``detected_collection``,
    which :func:`strip_collection_noise_tokens` already cleaned at
    ingestion and which Discover ALSO reads verbatim (the owner explicitly
    wants Discover to keep a trailing "SERIES"/"MOVIES" — it's meaningful
    context there). This is a second, purely cosmetic pass applied only at
    paint time in the list row, where that same word duplicates the row's
    own media-type icon.

    Two independent cleanups, applied in order:

    1. **Trailing media-type token** — a single trailing whole-token
       ``MEDIA_TYPE_TOKENS`` word (``"SERIES"``, ``"MOVIES"``, …) is peeled
       off, e.g. ``"APPLE+ SERIES"`` -> ``"APPLE+"``. Whole-token only (never
       a substring), so ``"SERIES MANIA"``'s trailing token is ``"MANIA"``
       — not a match — and the name survives intact.
    2. **Leading platform-duplicate token** — when *platform_code* is given
       (this row's OWN platform chip value, e.g. ``"A+"``), a leading run
       that spells out the same platform is stripped, matched
       case-insensitively against either the raw code or its
       :func:`platform_display` full name: ``"APPLE+ KIDS"`` with
       ``platform_code="A+"`` -> ``"KIDS"`` (``"APPLE+"`` ==
       ``platform_display("A+", "full").upper()``). A collection with no
       leading platform-code match is returned whole — ``"HINDU SUBS"``
       stays whole when *platform_code* is ``None``/doesn't match.

    Combining both passes can legitimately clear the chip entirely — e.g.
    ``"APPLE+ SERIES"`` with ``platform_code="A+"`` becomes ``""`` (pass 1
    strips "SERIES" to "APPLE+", pass 2 strips "APPLE+" to "") because
    every token was already shown elsewhere on the row (the platform chip
    + the media-type icon) — the intended "kill the triple redundancy"
    outcome, not a bug.

    Args:
        collection: The stored ``detected_collection`` value (already
            ingestion-cleaned by :func:`strip_collection_noise_tokens`), or
            ``None``/``""``.
        platform_code: This row's own platform prefix code (only pass this
            when it's a recognized :data:`PLATFORM_CODES` member — i.e. the
            SAME value driving the row's platform chip), or ``None``/``""``
            to skip the platform-dedup pass entirely.

    Returns:
        The channel-list-only display string (``""`` when both passes fully
        consume it — the caller renders no chip). ``None``/``""`` input is
        returned unchanged. Never mutates the stored value.
    """
    if not collection:
        return collection

    working = collection

    # Pass 1: trailing media-type token, whole-word only.
    leaves = [t for t in re.split(r"[\s\-/]+", working.strip()) if t]
    if leaves and leaves[-1].upper() in MEDIA_TYPE_TOKENS:
        m = _TRAILING_TOKEN_RE.search(working)
        if m:
            working = working[: m.start()].rstrip()

    # Pass 2: leading platform-duplicate token run.
    if platform_code and working:
        full_name = platform_display(platform_code, "full")
        candidates = {c.upper() for c in (platform_code, full_name) if c}
        upper_working = working.upper()
        for candidate in sorted(candidates, key=len, reverse=True):
            if upper_working == candidate:
                working = ""
                break
            if upper_working.startswith(candidate + " "):
                working = working[len(candidate):].strip()
                break

    return working


#: Episode markers inside a VOD title — only the forms the data supports.
#: ``S01E57``/``S2 E4``/``S01.E05``: 960 rows, 48 shows filed as movies, no film.
#: ``1x05`` was measured and rejected: its 14 matches were all films ("10x10
#: (2018)", "12x12"); "Season N Episode N" matched nothing.
_EPISODE_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9])S(\d{1,2})[ ._-]?E(\d{1,3})(?![0-9])", re.IGNORECASE)
#: Turkish "N. Bölüm" (episode N): 4,634 movie rows, 305 shows (F32). What follows
#: is decoration ("@showtv", "Full Bölüm", "(FİNAL)"); the show is what precedes.
_BOLUM_MARKER_RE = re.compile(r"(?<![\w])(\d{1,4})\s*\.?\s*B[öo]l[üu]m\b", re.IGNORECASE)


def _extract_episode_marker(bare: str) -> "tuple[str, str, str]":
    """Pull an ``SxxExx`` marker out of a title.

    A provider that files 414 episodes of one show as 414 separate movies gives
    the owner 414 rows where there should be one card. The marker is what makes
    them look distinct: strip it and ``content_key`` — computed from
    ``detected_title`` — collapses them the way it already collapses every other
    cross-source duplicate.

    The numbers are kept as strings exactly as written, not ``int``: "01" and
    "1" are the same episode but a provider is consistent within a show, and a
    string preserves the zero-padding a display might want. Callers that need to
    sort should ``int()`` at that point.

    Args:
        bare: A channel name with its provider prefix already removed.

    Returns:
        ``(title, season, episode)``; season and episode are "" when there is
        no marker, and *title* is then returned unchanged.

    Examples:
        >>> _extract_episode_marker("Konusanlar S01E57")
        ('Konusanlar', '01', '57')
        >>> _extract_episode_marker("10x10")
        ('10x10', '', '')
    """
    match = _EPISODE_MARKER_RE.search(bare)
    if not match:
        if (bolum := _BOLUM_MARKER_RE.search(bare)) and bare[: bolum.start()].strip():
            return bare[: bolum.start()].strip(" _-|"), "", bolum.group(1)
        return bare, "", ""
    title = bare[: match.start()] + " " + _BOLUM_MARKER_RE.sub(" ", bare[match.end():], count=1)  # "S02E04 76. Bolum"
    title = re.sub(r"\s{2,}", " ", title)
    return _SCENE_EDGE_RE.sub("", title), match.group(1), match.group(2)
_LEADING_QUALIFIERS_RE = re.compile(r"^((?:\s*[\(\[][^\)\]]*[\)\]])+)\s*(.*)$")  # "(US) X"

def _strip_attributes(bare: str) -> tuple[str, _Attributes]:
    """Pull every trailing decoration off a name, each into its own class.

    One loop rather than four passes, because these arrive interleaved —
    ``ESPN NEWS HD 60fps``, ``... 1080p WEB-DL DDP5.1 H.264`` — and a pass that
    only knows one class stops at the first token it does not recognise, which
    is why ``UHD`` survived in ``RELAX ᵁᴴᴰ 3840P``: the loop hit ``3840P``,
    did not know it, and gave up with the UHD still attached.

    Classification, in order:

    * a pixel height becomes its TIER (``3840P`` → ``4K``) so one ladder stays
      authoritative and the chip never shows a pixel count;
    * an encoding goes to ``encoding``, not ``quality`` — ledger F17's argument
      for HDR applies exactly: it is not a resolution tier, and letting it stand
      in for one means an HEVC channel reports no resolution at all;
    * a tier marker goes to ``tier``, which is the field that did not exist when
      ``[VIP]`` started being stored as a language;
    * an audio codec goes to ``audio_codec``, distinct from ``audio``
      (presentation: Multi/Dub/Sub).

    Duplicates collapse and the first of each class wins, so
    ``HD/RAW`` yields ``["HD", "RAW"]`` once each.
    """
    quality: list[str] = []
    tier = encoding = audio_codec = ""
    while True:
        qm = _QUALITY_SUFFIX_RE.search(bare)
        if not qm:
            break
        token = qm.group(1).upper().replace(" ", "")
        bare = bare[: qm.start()].strip()

        if token in RESOLUTION_TO_QUALITY:
            token = RESOLUTION_TO_QUALITY[token]
        elif token in _SOURCE_QUALITY_NORM:
            token = _SOURCE_QUALITY_NORM[token]
        if token in ENCODING_NORM:
            encoding = encoding or ENCODING_NORM[token]
            continue
        if token in TIER_TOKENS:
            tier = tier or token
            continue
        if token in AUDIO_CODEC_NORM:
            audio_codec = audio_codec or AUDIO_CODEC_NORM[token]
            continue
        if _FPS_RE.fullmatch(token):
            token = token.upper().replace("FPS", "fps")
        if token not in quality:
            quality.insert(0, token)

    return bare, _Attributes(_collapse_same_rank(quality), tier, encoding, audio_codec)


# Bracket classification result — kind drives which field the value lands in.
# "audio"   → ParsedChannel.audio  (format: "Multi", "Dub", "Sub")
# "quality" → ParsedChannel.quality list
# "origin"  → _bracket_origin → ParsedChannel.lang → detected_region
# "unknown" → left in bare title (no field to store it in yet)
class _BracketClass:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value


def _classify_bracket(content: str) -> _BracketClass:
    """Classify an uppercased bracket-suffix token into its semantic category.

    Called by both the step-3 and step-6a bracket passes in parse_channel_name()
    so the two parallel passes share one definition and can't silently diverge.
    """
    if (canon := _AUDIO_NORM.get(content)):
        return _BracketClass("audio", canon)
    # BEFORE the quality tests: HEVC/H264/H265 appear in QUALITY_TOKENS too, so
    # whichever vocabulary is consulted first decides the field. They are
    # encodings, not resolution tiers (ledger F17's argument for HDR).
    if content in ENCODING_NORM:
        return _BracketClass("encoding", ENCODING_NORM[content])
    if (codec := AUDIO_CODEC_NORM.get(content.replace(" ", ""))):
        return _BracketClass("audio_codec", codec)
    if content in TIER_TOKENS:
        return _BracketClass("tier", content)
    if (res := RESOLUTION_TO_QUALITY.get(content)):
        return _BracketClass("quality", res)
    if (q := _BRACKET_QUALITY_ALIASES.get(content)):
        return _BracketClass("quality", q)
    if content in QUALITY_TOKENS:
        return _BracketClass("quality", content)
    if (code := _BRACKET_LANG_NORM.get(content)):
        return _BracketClass("origin", code)
    if content in PLATFORM_CODES:
        return _BracketClass("origin", content)
    # 2-3 letters are a region only if the table knows them: ANY such token used
    # to be one — [VIP], "(BK)", "(DOC)", "[TOR]" (ledger F4: 113 codes, 1,446 rows).
    code = normalize_region_code(content) if len(content) in (2, 3) and content.isalpha() else ""
    if code in REGION_FULL_NAMES and content not in QUALITY_TOKENS:
        return _BracketClass("origin", code)
    return _BracketClass("unknown", content)


# ── Control-character mojibake cleanup (single source of truth) ──────────────── #
# Some provider feeds ship names with stray C0/C1 control characters — most often a
# raw C1 byte (U+0080–U+009F) left behind by a latin-1/UTF-8 mishandling of an
# accented letter (e.g. "|ES| Alita: <U+0081>ngel de combate", where the U+0081
# corrupts "Á").  The glyph renders as a box/blank AND leaks into the title-fallback
# content_key (``_normalize_for_key`` turns it into a stray space), so two would-be
# variants split.  We strip these non-printing controls at the single name-parsing
# chokepoint (``parse_channel_name``) so every derived ``detected_*`` field — and the
# ``content_key`` computed from ``detected_title`` — stores clean.  Legitimate letters
# are never touched (only true control codepoints match); we do NOT guess-repair the
# corrupted letter, we only remove the non-printing artifact.
#
# Range: C0 controls (U+0000–U+001F) + DEL (U+007F) + C1 controls (U+0080–U+009F).
# Normal spaces (U+0020) are outside the range and preserved; any whitespace run the
# removal exposes is collapsed so no double-space survives.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean_control_chars(name: str) -> str:
    """Strip non-printing C0/C1 control characters (mojibake artifacts) from a name.

    Removes control codepoints in the ranges U+0000–U+001F, U+007F, and
    U+0080–U+009F (the C1 block that carries raw-byte mojibake like a stray
    U+0081), then collapses any whitespace run the removal exposes and trims.
    Ordinary printable characters — including accented letters and legitimate
    punctuation — are left untouched; this is a lossless removal of the
    non-printing artifact only, never a heuristic character substitution.

    Single source of truth for control-char cleanup: called at the top of
    :func:`parse_channel_name` so every ``detected_*`` field (and the
    ``content_key`` derived from ``detected_title``) is computed from clean text.

    Args:
        name: The raw provider channel name (may be ``None`` / empty).

    Returns:
        The name with control characters removed and whitespace normalised.
        Returns the input unchanged when it is falsy.
    """
    if not name:
        return name
    cleaned = _CONTROL_CHAR_RE.sub("", name)
    # Collapse any whitespace run the removal exposed (and trim ends).
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _is_superscript_char(ch: str) -> bool:
    """True for a superscript/modifier form of an ordinary letter or digit.

    What keeps decoration apart from accents: a superscript decomposes to
    something wholly alphanumeric (``ᴴ`` → ``H``); an accented letter decomposes
    to a letter plus a non-alphanumeric mark (``Á`` → ``A`` + U+0301). A blanket
    NFKD cannot tell them apart and would rewrite every accented title.
    """
    if ch.isascii():
        return False
    decomposed = unicodedata.normalize("NFKD", ch)
    return (
        decomposed != ch
        and decomposed.strip() != ""
        and all(c.isalnum() for c in decomposed)
    )


def _classify_decoration(token: str) -> tuple[str, str]:
    """Classify one already-folded decoration token into ``(kind, value)``.

    Kinds: ``quality`` / ``tier`` / ``encoding`` / ``audio_codec`` / ``""``.
    """
    upper = token.upper().replace(" ", "")
    if upper in RESOLUTION_TO_QUALITY:
        return "quality", RESOLUTION_TO_QUALITY[upper]
    if upper in ENCODING_NORM:
        return "encoding", ENCODING_NORM[upper]
    if upper in AUDIO_CODEC_NORM:
        return "audio_codec", AUDIO_CODEC_NORM[upper]
    if upper in TIER_TOKENS:
        return "tier", upper
    if _FPS_RE.fullmatch(upper):
        return "quality", upper.replace("FPS", "fps")
    if upper in QUALITY_TOKENS or upper == "RAW":
        return "quality", upper
    return "", token


def _extract_superscript_attributes(name: str) -> tuple[str, _Attributes]:
    """Pull whole superscript tokens out of a name and classify them.

    15,676 channels carry one, and 3,405 of those had NO quality recorded while
    the plain ``HD`` on the same channel elsewhere was captured. Reading them
    HERE rather than folding them into the name is what lets ``RAW`` be a
    quality when it is decoration and a title word when it is not
    (``WWE Raw`` — tests/test_raw_live_cam_fix.py).

    Whole tokens only, so a name merely CONTAINING a decorated character keeps it.
    """
    if name.isascii():
        return name, _Attributes([], "", "", "")
    kept: list[str] = []
    quality: list[str] = []
    tier = encoding = audio_codec = ""
    for token in name.split():
        if not token or not all(_is_superscript_char(c) for c in token):
            kept.append(token)
            continue
        folded = unicodedata.normalize("NFKD", token)
        kind, value = _classify_decoration(folded)
        if kind == "quality":
            if value not in quality:
                quality.append(value)
        elif kind == "tier":
            tier = tier or value
        elif kind == "encoding":
            encoding = encoding or value
        elif kind == "audio_codec":
            audio_codec = audio_codec or value
        # An unrecognised decoration is dropped rather than kept: it is
        # decoration either way, and leaving it in the title is what put
        # 'ESPN NEWS ᴴᴰ ⁶⁰ᶠᵖˢ' and 'ESPN NEWS' into two content keys.
    cleaned = " ".join(kept) if kept else name
    return cleaned, _Attributes(quality, tier, encoding, audio_codec)


def _extract_slash_pair_attributes(name: str) -> tuple[str, _Attributes]:
    """Read ``HD/RAW`` as two attributes and remove it from the name.

    A slash pair of two known attribute tokens is unambiguous, which is what
    makes ``RAW`` readable here while a bare trailing ``RAW`` stays a title
    word. Bounded to a known-token/known-token shape, so ``AC/DC`` keeps its
    slash and so does a date.
    """
    quality: list[str] = []
    tier = encoding = audio_codec = ""

    def _take(match: "re.Match[str]") -> str:
        nonlocal tier, encoding, audio_codec
        for raw_token in (match.group(1), match.group(2)):
            kind, value = _classify_decoration(raw_token)
            if kind == "quality":
                if value not in quality:
                    quality.append(value)
            elif kind == "tier":
                tier = tier or value
            elif kind == "encoding":
                encoding = encoding or value
            elif kind == "audio_codec":
                audio_codec = audio_codec or value
        return " "

    cleaned = _SLASH_JOINED_RE.sub(_take, name)
    return " ".join(cleaned.split()), _Attributes(quality, tier, encoding, audio_codec)


def parse_channel_name(name: str) -> ParsedChannel:
    """Parse a raw channel name into structured components.

    Stripping order:
      1. Prefix (region/platform) from start
      1b. Pre-cut a mid-name "(YYYY)" that has trailing text after it (e.g. cast/extra
          credits) so it lands at the end for step 5 to extract
      2. Quality tokens from end (loop)
      3. Audio bracket suffix [Multi-Sub], [Dub], [Sub] from end
      4. Lang qualifier (XX) from end
      5. Year (NNNN) or range (NNNN-NNNN) from end
      6. Quality tokens from end again (catches HEVC hiding before year)

    Examples:
        "AR - Bob Marley: One Love HEVC (2024)"  → region=AR, bare="Bob Marley: One Love", quality=["HEVC"], year="2024"
        "NF - Star Wars: Andor [Multi-Sub]"      → region=NF, bare="Star Wars: Andor", audio="Multi"
        "D+ - Clone Wars (2008)"                 → region=D+, bare="Clone Wars", year="2008"
        "EN ★ AYAKA [Dub]"                       → region=EN, bare="AYAKA", audio="Dub"
        "X-Files (1993-2002)"                    → region="", bare="X-Files", year="1993-2002"
    """
    if not name:
        return ParsedChannel("", "", [], "", "", "")

    # Strip control-character mojibake (stray C1 bytes like U+0081 from a latin-1/
    # UTF-8 mishandling of accented letters) at the single name-parsing chokepoint so
    # every derived detected_* field — and the content_key built from detected_title —
    # is computed from clean text and never carries the non-printing artifact.
    bare = clean_control_chars(name)
    # Decoration first, and as its OWN class rather than folded into the plain
    # vocabulary. Folding was the first attempt and it regressed a decision this
    # codebase had already made correctly: 'EN - WWE Raw (2023)' is a title, and
    # bare RAW must not be stripped (test_raw_live_cam_fix.py, regression B0).
    # Folding 'ᴿᴬᵂ' to 'RAW' made the two indistinguishable, so the fix for one
    # broke the other. A SUPERSCRIPT token cannot be part of a title, which is
    # what makes it safe to read here and unsafe to read after folding.
    bare, _sup_attrs = _extract_superscript_attributes(bare)
    # Same argument for a slash-joined pair: "HD/RAW" is unambiguously two
    # attributes, so RAW is readable there even though a bare trailing RAW is not.
    bare, _slash_attrs = _extract_slash_pair_attributes(bare)
    if not bare:
        return ParsedChannel("", "", [], "", "", "")
    region = ""
    _prefix_quality: str = ""  # set when a digit-starting quality token is the prefix
    _bracket_origin: str = ""  # secondary lang/region from bracket or suffix

    # 0. Pre-extraction prefix forms the standard separator patterns miss because the
    # prefix is not immediately followed by a separator. When one matches, the prefix
    # is consumed here and step 1 is skipped so it can't be clobbered.
    _prefix_consumed = False

    # 0a. Leading-pipe prefix: |WC| Title — strip the pipe-wrapped token to region.
    lpm = _LEADING_PIPE_PREFIX_RE.match(bare)
    if lpm:
        region = normalize_region_code(lpm.group(1).upper())
        bare = lpm.group(2).strip()
        # Some feeds put a separator AFTER the closing pipe ("|MULTI|. Title"),
        # which survives the prefix strip as a leading ". " on the title.  Only a
        # punctuation run FOLLOWED BY whitespace is residue — a bare leading dot
        # can be a real title (".hack//Sign").
        bare = _POST_PREFIX_RESIDUE_RE.sub("", bare)
        _prefix_consumed = True

    # 0b. EPG-embedded event feed: "US (Peacock 01) | Title (timestamp)" — set the
    # region and strip the network/pipe/timestamp to a clean title. The event fields
    # (start time, network) are captured separately by special_content.parse.
    if not _prefix_consumed:
        pe = parse_platform_event(bare)
        if pe:
            region = pe.region
            if pe.title:
                bare = pe.title
            _prefix_consumed = True

    # 1. Extract prefix — try compound first (catches "4K-SC", "SE-4K"), then standard.
    # Skip when a pre-extraction form (step 0) already set the region.
    cm = None if _prefix_consumed else _COMPOUND_PREFIX_RE.match(bare)
    if _prefix_consumed:
        pass  # prefix already extracted in step 0
    elif cm:
        compound_lang = (
            cm.group("lang_a") or cm.group("lang_b") or cm.group("lang_c") or ""
        ).upper()
        compound_q = (
            cm.group("qual_a") or cm.group("qual_b") or cm.group("qual_c") or ""
        ).upper()
        bracket = cm.group("bracket")
        if compound_lang and compound_lang not in QUALITY_TOKENS:
            region = normalize_region_code(compound_lang)
            if compound_q:
                _prefix_quality = compound_q  # appended to quality[] in step 7 (lower priority than suffix)
            if bracket:
                # bracket from "[US] 4K-DE - Title" becomes secondary lang (step 4)
                _bracket_origin = normalize_region_code(bracket)
            bare = cm.group("title").strip()
    else:
        m = _SEPARATOR_RE.match(bare)
        if m:
            region = normalize_region_code(m.group(1))
            bare = m.group(2).strip()
        else:
            # [4K]/[8K] bracket at start — digit-first so _BRACKET_PREFIX_RE won't match.
            # Handles "[4K] [US] Title" and "[4K] Title" provider formats.
            qd = _QUALITY_DIGIT_BRACKET_RE.match(bare)
            if qd:
                _prefix_quality = qd.group(1).upper()
                bare = qd.group(2).strip()
                # Check for a following region bracket: [4K] [US] Title → region="US"
                bm2 = _BRACKET_PREFIX_RE.match(bare)
                if bm2:
                    region = normalize_region_code(bm2.group(1))
                    bare = bm2.group(2).strip()
            else:
                bm = _BRACKET_PREFIX_RE.match(bare)
                if bm:
                    code = bm.group(1).upper()
                    if code in QUALITY_TOKENS:
                        # Quality token in letter-bracket form: [HD], [UHD], [FHD] at start.
                        _prefix_quality = code
                        bare = bm.group(2).strip()
                        # Check for a following region bracket: [UHD] [SC] Title → region="SC"
                        bm2 = _BRACKET_PREFIX_RE.match(bare)
                        if bm2 and bm2.group(1).upper() not in QUALITY_TOKENS:
                            region = normalize_region_code(bm2.group(1))
                            bare = bm2.group(2).strip()
                    else:
                        region = normalize_region_code(code)
                        bare = bm.group(2).strip()
                else:
                    pm = _PAREN_PREFIX_RE.match(bare)
                    if pm:
                        region = normalize_region_code(pm.group(1))
                        bare = pm.group(2).strip()
                    else:
                        # Digit-starting quality token prefix (e.g. "4K - Title", "8K ★ Title").
                        # These are quality markers, not region codes — go in quality[], not region.
                        dq = _DIGIT_QUALITY_PREFIX_RE.match(bare)
                        if dq:
                            _prefix_quality = dq.group(1).upper()
                            bare = dq.group(2).strip()

    # 1a. Scene-release filename ("Atlas.2024.1080p.WEB-DL.x264.DDP5.1").
    # Runs here — after the prefix pass, before every end-anchored pass — for
    # two reasons. The prefix pass must go first or "BLURAY-DE - Bonhoeffer
    # (2024)" loses its title to its own category label. And the end-anchored
    # passes must come after, because this pass turns "Atlas.2024" into
    # "Atlas 2024" and it is step 5's year strip, not this one, that knows what
    # a trailing year means.
    _scene = _extract_scene_release(bare)
    if _scene is not None:
        bare, _scene_attrs = _scene
    else:
        _scene_attrs = None

    # 1a-ii. Episode marker. AFTER the scene cut, because "Konusanlar S01E57
    # 1080p EXXEN WEB-DL AAC H264-TURG" only exposes its marker once the tail
    # is gone, and BEFORE the year strip, because removing "S01E57" can leave a
    # trailing year the end-anchored pass should then see.
    bare, _season, _episode = _extract_episode_marker(bare)

    trailing = ""

    # 1b. Pre-cut free text after the LAST real "(19xx)"/"(20xx)" year so the
    # end-anchored steps below can extract it: "Title 4K (1996) HARVEY KEITEL, ..."
    # → "Title 4K (1996)", year kept for step 5. Never an arbitrary parenthetical
    # ("(Director's Cut)") or a bare number in the title ("Blade Runner 2049").
    #   - Qualifier tails ("Hanna (2019) (US)") are left to the later steps,
    #     unless an all-caps credit follows them (handled first, below).
    #   - Only ALL-CAPS text is a provider credit ("HARVEY KEITEL", "BROADWAY
    #     MUSICAL"); mixed case ("FBI (2024) Reboot") is a real subtitle.
    trailing_meta: Optional[tuple[str, str]] = None
    _early_year = ""
    _year_matches = list(_PAREN_YEAR_ANYWHERE_RE.finditer(bare))
    if _year_matches:
        _last_year_match = _year_matches[-1]
        _trailing = bare[_last_year_match.end():].strip()
        _trailing_is_upper_junk = (
            any(ch.isupper() for ch in _trailing)
            and not any(ch.islower() for ch in _trailing)
        )
        # "(2012) (US) CHARLIE SHEEN": an all-caps tail AFTER qualifiers is cut
        # like one after the year; the year is stashed as the branch below does.
        # Recognised metadata first ("… ARABIAN 1001 NIGHTS COLLECTION"), then credit.
        _q = _LEADING_QUALIFIERS_RE.match(_trailing)
        if _q and _q.group(2).isupper():
            _tail, _g1, _g2 = _q.group(2).strip(), *_last_year_match.group(1, 2)
            bare = f"{bare[: _last_year_match.end()]} {_q.group(1).strip()}"
            _early_year = f"{_g1}-{_g2}" if _g2 else _g1
            if (_meta := classify_trailing_metadata(_tail)) is not None:
                trailing_meta = _meta
            else:
                trailing = _tail
        elif _trailing and not _trailing.startswith(("(", "[")):
            if (_meta := classify_trailing_metadata(_trailing)) is not None:
                # Recognised provider metadata ("Hallmark", "sinhronizirano",
                # "- Lucky Luke Collection") — checked BEFORE the all-caps credit
                # test, which used to swallow "… COLLECTION" tails.  Route it to a
                # facet and truncate, so the year reaches the end-anchored strip.
                trailing_meta = _meta
                bare = bare[: _last_year_match.end()]
            elif _trailing_is_upper_junk:
                # A provider-appended credit ("HARVEY KEITEL, TARANTINO"): kept
                # as trailing so callers can see the actor it names.
                trailing = _trailing
                bare = bare[: _last_year_match.end()]
            else:
                # Not recognised: maybe a real subtitle ("FBI (2024) Reboot"), so it
                # stays — but lift the unambiguous year out of its way.
                _g1, _g2 = _last_year_match.group(1), _last_year_match.group(2)
                _early_year = f"{_g1}-{_g2}" if _g2 else _g1
                bare = (
                    bare[: _last_year_match.start()].strip() + " " + _trailing
                ).strip()
        elif _trailing:
            # W-1: trailing IS a parenthetical/bracket — often handled by a
            # later end-anchored step ("(US)"), but not an UNRECOGNISED one
            # ("(PORTUGUESE ENG-SUB)", "(MULTI FHD HEVC)"), which no later step
            # relocates, so step 5's search finds nothing. Stash a fallback
            # only; bare is untouched, so an already-handled trailer is unaffected.
            _g1, _g2 = _last_year_match.group(1), _last_year_match.group(2)
            _early_year = f"{_g1}-{_g2}" if _g2 else _g1

    # 2. Strip quality tokens from end (first pass)
    bare, _attrs = _strip_attributes(bare)
    quality = _attrs.quality
    tier, encoding, audio_codec = _attrs.tier, _attrs.encoding, _attrs.audio_codec
    if _scene_attrs is not None:
        # Step 1a already read the tail this name will never reach. Its findings
        # go FIRST: a resolution stated in the filename is more specific than
        # anything the surviving head can offer, and only one of the two can win.
        quality = _scene_attrs.quality + [
            q for q in quality if q not in _scene_attrs.quality
        ]
        encoding = encoding or _scene_attrs.encoding
        audio_codec = audio_codec or _scene_attrs.audio_codec

    # 3. Strip audio bracket suffix [Multi-Sub], [Dub], [Sub] from end.
    # Also strips content-origin brackets like [UK], [US] (2-3 alpha letters,
    # not a quality token) — these are captured as lang in step 4.
    # Also strips quality-token brackets like [4K], [UHD], [HD].
    audio = ""
    _audio_langs: list[str] = []
    _dub_langs: list[str] = []
    _sub_langs: list[str] = []
    # _bracket_origin already initialized above; suffix bracket overrides compound bracket
    bsm = _BRACKET_SUFFIX_RE.search(bare)
    if bsm:
        content = bsm.group(1).strip().upper()
        bc = _classify_bracket(content)
        if bc.kind == "audio":
            audio = bc.value
            bare = bare[: bsm.start()].strip()
            # Extract audio facets from the bracket content (e.g. [Multi-Sub], [Dub])
            _af, _al, _dl, _sl = extract_audio_annotation(bsm.group(1).strip())
            if not _audio_langs:
                _audio_langs = _al
            _dub_langs = list(dict.fromkeys(_dub_langs + _dl))
            _sub_langs = list(dict.fromkeys(_sub_langs + _sl))
        elif bc.kind == "quality":
            quality.insert(0, bc.value)
            bare = bare[: bsm.start()].strip()
        elif bc.kind == "origin":
            _bracket_origin = bc.value
            bare = bare[: bsm.start()].strip()
        elif bc.kind == "tier":
            tier = tier or bc.value
            bare = bare[: bsm.start()].strip()
        elif bc.kind == "encoding":
            encoding = encoding or bc.value
            bare = bare[: bsm.start()].strip()
        elif bc.kind == "audio_codec":
            audio_codec = audio_codec or bc.value
            bare = bare[: bsm.start()].strip()
        # "unknown": bracket stays in bare name. A kind added to
        # _classify_bracket but not handled here lands in "unknown" and the
        # bracket silently survives into the title — which is how [VIP] was
        # both misfiled AND still visible.

    # 4. Strip explicit lang/region qualifier from end: (EN), (JP)
    # Parenthetical form overrides bracket form if both are present.
    lang = _bracket_origin
    lm = _LANG_QUALIFIER_RE.search(bare)
    if lm:
        token = lm.group(1).strip().upper()
        # The square brackets' classifier: "(SUB)"/"(DUB)" were stored as regions (F4).
        pc = _classify_bracket(token)
        if pc.kind == "quality":
            quality.append(pc.value)
            bare = bare[: lm.start()].strip()
        elif pc.kind == "audio":
            audio = audio or pc.value
            bare = bare[: lm.start()].strip()
        elif pc.kind == "origin":
            if pc.value != region:
                lang = pc.value
            bare = bare[: lm.start()].strip()   # an unknown code stays in the name

    # 5. Strip year from end
    year = ""
    ym = _YEAR_RE.search(bare)
    if ym:
        year = ym.group(1) or ym.group(2)  # group 1 = paren form, group 2 = dash form
        # Anything still after the year here (step 1b usually took it already).
        trailing = trailing or bare[ym.end():].strip()
        bare = bare[: ym.start()].strip()
    elif _early_year:
        # A mid-string year whose trailing text was deliberately left in the
        # name (unrecognised).  The year still belongs in its own field.
        year = _early_year

    # 6a. Second bracket pass (same classifier as step 3) for brackets the year or a second bracket hid.
    bsm2 = _BRACKET_SUFFIX_RE.search(bare)
    if bsm2:
        content2 = bsm2.group(1).strip().upper()
        bc2 = _classify_bracket(content2)
        if bc2.kind == "quality":
            quality.insert(0, bc2.value)
            bare = bare[: bsm2.start()].strip()
        elif bc2.kind == "origin":
            _bracket_origin = bc2.value
            lang = bc2.value   # step 4 already ran; update lang directly
            bare = bare[: bsm2.start()].strip()
        elif bc2.kind == "audio" and not audio:
            # Capture audio annotation from second bracket pass too
            audio = bc2.value
            bare = bare[: bsm2.start()].strip()
            _af2, _al2, _dl2, _sl2 = extract_audio_annotation(bsm2.group(1).strip())
            if not _audio_langs:
                _audio_langs = _al2
            _dub_langs = list(dict.fromkeys(_dub_langs + _dl2))
            _sub_langs = list(dict.fromkeys(_sub_langs + _sl2))

    # 6b. Second quality pass — catches "Name HEVC (2024)" where HEVC was before year
    bare, _attrs2 = _strip_attributes(bare)
    quality2 = _attrs2.quality
    tier = tier or _attrs2.tier
    encoding = encoding or _attrs2.encoding
    audio_codec = audio_codec or _attrs2.audio_codec
    quality = quality2 + quality  # prepend (quality2 came from closer to the name)

    # 6c. Strip leftover single-token qualifiers ("Name (US) (4K)", "Name (VOSTFR)");
    #     multi-word alt-titles ("Name (Soleil Noir)") stay. Cleans the title only —
    #     committed fields are not re-derived — but audio facets are read off them.
    bare, _stripped_inners = _strip_title_qualifiers_collecting(bare)
    for _inner in _stripped_inners:
        _inner_up = _inner.strip().upper()
        _inner_tokens = re.split(r'[\s\-/]+', _inner_up)
        # Audio/sub/dub annotation markers (explicit role markers)
        _AUDIO_MARKERS = frozenset({
            "DUB", "DUBBED", "SUB", "SUBS", "SUBBED", "SUBTITLED",
            "VOSTFR", "VOSTA", "VOST", "LEG", "LEGENDADO", "MULTI",
            "MUTI", "DUAL", "OV", "OMU",
        })
        has_audio_marker = any(tok in _AUDIO_MARKERS for tok in _inner_tokens)
        is_known_audio_form = _inner_up in _AUDIO_NORM

        if has_audio_marker or is_known_audio_form:
            # Compound annotation — extract form + role assignments
            _af, _al, _dl, _sl = extract_audio_annotation(_inner)
            if _af and not audio:
                audio = _af
            elif _af == "Multi" and audio != "Multi":
                audio = "Multi"
            _audio_langs = list(dict.fromkeys(_audio_langs + _al))
            _dub_langs = list(dict.fromkeys(_dub_langs + _dl))
            _sub_langs = list(dict.fromkeys(_sub_langs + _sl))
        else:
            # Single-language token (e.g. "(KURDISH)", "(JAPANESE)") — language only,
            # no role assignment; add to audio_langs as original/unqualified audio.
            single_tok = _inner_tokens[0] if len(_inner_tokens) == 1 else None
            if single_tok:
                lang_name = AUDIO_LANG_WORD_MAP.get(single_tok)
                if lang_name and lang_name not in _audio_langs:
                    _audio_langs.append(lang_name)

    # 6d. Quality exposed by 6c ("Title 4K (2025) (MULTI SUB)"). Quality only: a tier
    # word here is a title word ("One Piece Film Gold", "STC PPV"), so that pass is dropped.
    _bare3, _attrs3 = _strip_attributes(bare)
    if _attrs3.quality and not _attrs3.tier:
        bare, quality = _bare3, _attrs3.quality + quality
        encoding, audio_codec = encoding or _attrs3.encoding, audio_codec or _attrs3.audio_codec

    # 7. Append prefix quality (standalone "4K - Movie" or compound "4K-DE") at lowest
    # priority so name-suffix quality (step 2/6b) — which describes the actual encode —
    # wins when both are present (e.g. "[US] 4K-DE - Movie UHD" → quality[0] = "UHD").
    _is_rating = _prefix_quality in AGE_RATING_PREFIXES
    region = normalize_region_code(_prefix_quality) if _is_rating else region
    if _prefix_quality and not _is_rating and _prefix_quality not in quality:
        # Same-rank guard as _strip_attributes: a "4K|" prefix on a name whose
        # suffix already said UHD is one tier stated twice, and would render as
        # two chips meaning one thing.
        _prefix_rank = QUALITY_TIER_RANK.get(_prefix_quality)
        _have_rank = {QUALITY_TIER_RANK.get(q) for q in quality}
        if _prefix_rank is None or _prefix_rank not in _have_rank:
            quality = quality + [_prefix_quality]

    # 8. Merge what the decoration passes pulled off before parsing began. They
    # run FIRST (a superscript cannot be part of a title, so it is safe to read
    # there and unsafe to read after folding) but merge LAST, so a quality
    # stated plainly in the name still leads the list.
    # A quality the tail named ("London Calling (2025) 4K") ranks last of all.
    _tail_attrs = (_strip_attributes(f"x {trailing_meta[1]}")[1]   # stripper needs a word before
                   if trailing_meta and trailing_meta[0] == "quality" else _Attributes([], "", "", ""))
    for _extra in (_sup_attrs, _slash_attrs, _tail_attrs):
        for _q in _extra.quality:
            if _q not in quality:
                quality.append(_q)
        tier = tier or _extra.tier
        encoding = encoding or _extra.encoding
        audio_codec = audio_codec or _extra.audio_codec

    # "UHD" from a suffix and "4K" from a decoration are one rung said twice.
    quality = _collapse_same_rank(quality)

    return ParsedChannel(region, bare, quality, lang, year, audio,
                         _audio_langs, _dub_langs, _sub_langs, trailing,
                         trailing_meta, tier, encoding, audio_codec,
                         _season, _episode)
