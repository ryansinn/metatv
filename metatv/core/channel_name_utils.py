"""Shared channel name parsing — prefix extraction, region normalization, quality/year/audio detection."""
import re
from datetime import datetime
from functools import lru_cache
from typing import NamedTuple, Optional


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

# Quality tokens that start with a digit (4K, 8K) — excluded from _SEPARATOR_RE
# because that pattern requires [A-Z] as the first character.
_DIGIT_QUALITY_PREFIX_RE = re.compile(
    r'^(4K|8K)\s*(?:[★|]|-\s+)\s*(.+)$',
    re.IGNORECASE,
)

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

# ── Suffix patterns ─────────────────────────────────────────────────────────── #

# Quality tokens at end of bare name (including codecs and source indicators)
# RAW, LIVE, CAM removed — these are ambiguous when bare (e.g., "WWE Raw" shouldn't become
# title="WWE"). They must appear bracketed [RAW] or as superscript to count as quality.
_QUALITY_SUFFIX_RE = re.compile(
    r'\s+\b(4K|8K|UHD|FHD|HDR10\+?|HDR|HEVC|H265|H264|HD|SD|HQ|LQ)\b\s*$',
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
    "MULTI AU/SUB": "Multi", "MULTI AU/AUDIO": "Multi",
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
# parentheticals like "(SPANISH ENG-SUB)" or "(ENG DUB)".  These are NOT full
# _AUDIO_NORM keys (which cover complete bracket/paren contents), but individual
# tokens within a compound qualifier.  The recognized-qualifier allowlist in
# _is_all_qualifier_tokens() checks each space/dash/slash-split leaf against this
# set alongside lang codes and quality tokens.
_SUB_DUB_TOKENS: frozenset[str] = frozenset({
    "SUB", "SUBS", "SUBBED", "SUBTITLED", "SUBTITULADO", "SUBTITLE",
    "DUB", "DUBBED", "DUBBING",
    "VOST", "VOSTFR", "VOSTA",
    "LEG", "LEGENDADO", "LEGENDADA",
    "OV", "OMU",
    "AUDIO", "DUAL",
})

# Unambiguous subtitle/dub markers.  Their PRESENCE in a trailing parenthetical is
# strong enough to treat the whole parenthetical as a qualifier annotation even when a
# co-occurring language word (KURDISH, PERSIAN, NORWEGIAN, …) is not in the recognized
# vocabulary.  DUAL / AUDIO / MULTI are DELIBERATELY EXCLUDED — they appear in real
# titles ("Dual Survival", "Multiplicity") and are ambiguous.
_UNAMBIGUOUS_SUBDUB_MARKERS: frozenset[str] = frozenset({
    "SUB", "SUBS", "SUBBED", "SUBTITLED", "SUBTITLES",
    "DUB", "DUBBED",
    "VOST", "VOSTFR",
    "LEG", "LEGENDADO", "LEGENDADOS",
    "MULTISUB", "ENGSUB",
})

# Bare audio-track annotation tokens that providers sometimes append to a title as a
# *trailing word with no bracket/paren delimiter*, e.g. "The Bridge MULTI" or
# "The Killing MULTI SUB".  Bracketed/parenthesised forms ([MULTI], (Multi-Sub)) are
# already stripped by strip_title_qualifiers; this set targets the bare-word leak.
# They denote the audio track, NOT the production, so the content-identity key
# normalisation (content_identity.py) strips a trailing run of them — but only when it
# is anchored by a MULTI/MUTI token (AUDIO_KEY_ANCHOR_TOKENS), so standalone real-word
# titles ending in "Sub"/"Audio"/"Dual" are preserved (see the DUAL/AUDIO/MULTI caveat
# above).  Single source of truth — keep in sync with the canonical _AUDIO_NORM forms;
# lowercase because the key normaliser lowercases before matching.
AUDIO_KEY_NOISE_TOKENS: frozenset[str] = frozenset({
    "multi", "muti", "sub", "audio", "au",
})

# Anchor subset of AUDIO_KEY_NOISE_TOKENS: a trailing audio-noise run is stripped from a
# content_key only when it contains one of these, so "Dual Survival" / "<title> Sub" stay
# intact while "<title> MULTI" / "<title> MULTI SUB" collapse onto the base title.
AUDIO_KEY_ANCHOR_TOKENS: frozenset[str] = frozenset({"multi", "muti"})


# ── Region/platform lookup tables ────────────────────────────────────────────── #

# Platform codes — displayed with steel blue chip instead of grey
# "A+" (Apple TV+, distinct from the "APPLE" variant above — both observed in
# real provider data) was already listed as a "surfaced by Ninja" streaming
# platform in REGION_FULL_NAMES below but missing from this set, so it fell
# through to the plain geographic-region chip instead of the platform one
# (#257 owner report). Adapting the lookup table per CLAUDE.md's "single
# source of truth" rule rather than special-casing it at a render call site.
PLATFORM_CODES: frozenset[str] = frozenset({
    "NF", "D+", "HBO", "PRIME", "TUBI", "PARAMOUNT+", "APPLE", "PEACOCK",
    "ASTRO", "F1TV", "A+",
})

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


def tag_value_for(facet: str, token: str) -> str | None:
    """Translate a *display-side* token into the value the TAG table stores.

    The two vocabularies genuinely differ, and assuming otherwise shipped a
    real bug: a row's language chip shows the CODE ``"EN"`` while the tag stores
    the resolved name ``"English"``; a quality chip shows the token ``"4K"``
    while the tag stores the GROUP ``"4K / UHD"``. Filtering on the displayed
    string therefore matched nothing and emptied the list. Region and genre
    happen to coincide, which is exactly what made the mismatch look like it
    worked.

    Reads the existing canonical tables rather than restating them —
    :data:`CODE_FACETS` (code → facet/value, the same map the decomposer tags
    from) and ``config.BASE_QUALITY_GROUPS`` (group → member tokens). The config
    import is function-local: ``config`` is imported by callers of this module,
    so a module-level import would be circular (same pattern as
    ``BASE_PREFIX_GROUPS`` above).

    Args:
        facet: Tag facet type — ``"language"``/``"quality"``/``"region"``/….
        token: The token the UI is displaying (a code, tier token, or name).

    Returns:
        The tag value to filter on, or ``None`` when *token* maps to nothing in
        that facet — callers must treat ``None`` as "don't filter" rather than
        substituting the raw token, which is what produced the empty list.
    """
    raw = (token or "").strip()
    if not raw:
        return None

    if facet == "quality":
        from metatv.core.config import BASE_QUALITY_GROUPS

        upper = raw.upper()
        if upper in BASE_QUALITY_GROUPS:
            return upper  # already a group name
        for group, members in BASE_QUALITY_GROUPS.items():
            if upper in members:
                return group
        return None

    if facet in ("language", "region", "audio"):
        for entry_facet, value, _conf in CODE_FACETS.get(raw.upper(), ()):
            if entry_facet == facet:
                return value
        # Already a resolved name (the chip showed "English", not "EN"), or a
        # code this facet does not claim.
        return raw if facet != "language" or raw.istitle() else None

    return raw


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
#
# Semantic note: values like KR/JP/CN are ISO 3166-1 *country* codes rather than
# ISO 639-1 *language* codes (ko/ja/zh). The IPTV convention conflates country and
# language (EN already serves as both in REGION_FULL_NAMES), so we follow the same
# pattern here for consistency. Tracked as semantic debt in project_filter_system.
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

# Mapping from language words found inside sub/dub annotations → canonical language name
# (the same names used in CODE_FACETS and REGION_FULL_NAMES for the `language:` facet).
# Used by extract_audio_annotation() to convert language tokens from (ENG DUB),
# (SPANISH ENG-SUB), (VOSTFR), etc. into canonical language names.
# Key = UPPERCASE token as it appears in provider names; value = canonical display name.
# SINGLE SOURCE OF TRUTH for this mapping — do NOT define parallel dicts elsewhere.
AUDIO_LANG_WORD_MAP: dict[str, str] = {
    # English variants
    "ENGLISH":       "English",
    "ENG":           "English",
    "EN":            "English",
    # Spanish / Latin
    "SPANISH":       "Spanish",
    "ESP":           "Spanish",
    "ES":            "Spanish",
    "LAT":           "Latin American Spanish",
    "LATIN":         "Latin American Spanish",
    "LATAM":         "Latin American Spanish",
    # French
    "FRENCH":        "French",
    "FRE":           "French",
    "FR":            "French",
    # German
    "GERMAN":        "German",
    "GER":           "German",
    "DE":            "German",
    # Italian
    "ITALIAN":       "Italian",
    "ITA":           "Italian",
    "IT":            "Italian",
    # Portuguese
    "PORTUGUESE":    "Portuguese",
    "POR":           "Portuguese",
    "PT":            "Portuguese",
    "PT-BR":         "Portuguese",
    "PTBR":          "Portuguese",
    # Russian
    "RUSSIAN":       "Russian",
    "RUS":           "Russian",
    "RU":            "Russian",
    # Arabic
    "ARABIC":        "Arabic",
    "ARA":           "Arabic",
    "AR":            "Arabic",
    # Japanese
    "JAPANESE":      "Japanese",
    "JAP":           "Japanese",
    "JPN":           "Japanese",
    "JP":            "Japanese",
    # Korean
    "KOREAN":        "Korean",
    "KOR":           "Korean",
    "KR":            "Korean",
    # Chinese
    "CHINESE":       "Chinese",
    "CHI":           "Chinese",
    "CHN":           "Chinese",
    "CN":            "Chinese",
    # Hindi
    "HINDI":         "Hindi",
    "HIN":           "Hindi",
    "HI":            "Hindi",
    # Turkish
    "TURKISH":       "Turkish",
    "TUR":           "Turkish",
    "TR":            "Turkish",
    # Polish
    "POLISH":        "Polish",
    "POL":           "Polish",
    "PL":            "Polish",
    # Thai
    "THAI":          "Thai",
    "THA":           "Thai",
    "TH":            "Thai",
    # Dutch
    "DUTCH":         "Dutch",
    "NL":            "Dutch",
    # Swedish
    "SWEDISH":       "Swedish",
    "SWE":           "Swedish",
    "SE":            "Swedish",
    # Norwegian
    "NORWEGIAN":     "Norwegian",
    "NOR":           "Norwegian",
    "NO":            "Norwegian",
    # Danish
    "DANISH":        "Danish",
    "DEN":           "Danish",
    "DK":            "Danish",
    # Finnish
    "FINNISH":       "Finnish",
    "FIN":           "Finnish",
    "FI":            "Finnish",
    # Romanian
    "ROMANIAN":      "Romanian",
    "ROM":           "Romanian",
    "RO":            "Romanian",
    # Hungarian
    "HUNGARIAN":     "Hungarian",
    "HUN":           "Hungarian",
    "HU":            "Hungarian",
    # Czech
    "CZECH":         "Czech",
    "CZE":           "Czech",
    "CZ":            "Czech",
    # Greek
    "GREEK":         "Greek",
    "GRE":           "Greek",
    "GR":            "Greek",
    # Kurdish
    "KURDISH":       "Kurdish",
    "KUR":           "Kurdish",
    "KU":            "Kurdish",
    # Persian / Farsi
    "PERSIAN":       "Persian",
    "FARSI":         "Persian",
    "FA":            "Persian",
    "FAS":           "Persian",
    "PER":           "Persian",
    # Ukrainian
    "UKRAINIAN":     "Ukrainian",
    "UKR":           "Ukrainian",
    "UK":            "Ukrainian",
    # Vietnamese
    "VIETNAMESE":    "Vietnamese",
    "VIE":           "Vietnamese",
    "VN":            "Vietnamese",
    # Indonesian
    "INDONESIAN":    "Indonesian",
    "IND":           "Indonesian",
    "ID":            "Indonesian",
    # Filipino / Tagalog
    "FILIPINO":      "Filipino",
    "TAGALOG":       "Filipino",
    "PH":            "Filipino",
    # Bulgarian
    "BULGARIAN":     "Bulgarian",
    "BUL":           "Bulgarian",
    "BG":            "Bulgarian",
    # Serbian / Croatian / Bosnian
    "SERBIAN":       "Serbian",
    "SRB":           "Serbian",
    "CROATIAN":      "Croatian",
    "HRV":           "Croatian",
    "BOSNIAN":       "Bosnian",
    # Slovak / Slovenian
    "SLOVAK":        "Slovak",
    "SLOVENIAN":     "Slovenian",
    # Albanian
    "ALBANIAN":      "Albanian",
    "ALB":           "Albanian",
    "AL":            "Albanian",
    # Tamil / Telugu (Indian sub-languages)
    "TAMIL":         "Tamil",
    "TAM":           "Tamil",
    "TA":            "Tamil",
    "TELUGU":        "Telugu",
    "TEL":           "Telugu",
    "TE":            "Telugu",
    # Malay
    "MALAY":         "Malay",
    "MAL":           "Malay",
    "MS":            "Malay",
    # Hebrew
    "HEBREW":        "Hebrew",
    "HEB":           "Hebrew",
    "IL":            "Hebrew",
    # VOSTFR / VOSTA special forms — these encode "French subtitles" / "original audio + FR sub"
    # Handled separately in extract_audio_annotation; listed here as fallback if seen as tokens.
    "VOSTFR":        "French",   # "Version Originale Sous-Titrée en FRançais"
    "VOSTA":         "Spanish",  # "Version Originale Sous-Titrée en espAgñol" (less common)
}


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

    for i, tok in enumerate(tokens):
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


_FULL_NAME_TO_CODE: dict[str, str] = {
    # Europe
    "ARGENTINA": "ARG", "AUSTRALIA": "AUS", "AUSTRIA": "AUT",
    "BELGIUM": "BEL", "BOLIVIA": "BOL", "BRAZIL": "BRA",
    "CANADA": "CAN", "CHILE": "CHL", "COLOMBIA": "COL",
    "CROATIA": "HRV", "DENMARK": "DEN", "ECUADOR": "ECU",
    "FINLAND": "FIN", "FRANCE": "FRA", "GERMANY": "GER",
    "GREECE": "GRE", "HUNGARY": "HUN", "IRELAND": "IRL",
    "ITALY": "ITA", "MEXICO": "MEX", "NETHERLANDS": "NED",
    "NORWAY": "NOR", "PARAGUAY": "PAR",
    "PERU": "PE",    # PE (not PER — PER is used for Persian in this codebase)
    "POLAND": "POL", "PORTUGAL": "POR", "ROMANIA": "ROU",
    "RUSSIA": "RUS", "SPAIN": "ESP", "SWEDEN": "SWE",
    "SWITZERLAND": "SUI", "TURKEY": "TUR", "UKRAINE": "UKR",
    "URUGUAY": "URY", "VENEZUELA": "VEN", "JAPAN": "JPN",
    "CHINA": "CHN", "INDIA": "IND", "PAKISTAN": "PAK",
    "ISRAEL": "ISR", "MOROCCO": "MAR", "NIGERIA": "NGA",
    "EGYPT": "EGY", "SOUTH AFRICA": "ZAF",
    # Latin America — full names seen as channel prefixes
    "DOMINICAN": "DO", "HONDURAS": "HN", "GUATEMALA": "GT",
    "CUBA": "CU",     "PANAMA": "PA",   "VENEZUELA": "VEN",
    # Africa — full names seen as channel prefixes
    "SENEGAL": "SEN",  "SOMALIA": "SOM",  "UGANDA": "UGA",
    "CAMEROON": "CM",  "GHANA": "GHA",    "KENYA": "KE",
    "ETHIOPIA": "ETH", "TOGO": "TGO",     "GABON": "GAB",
    "GAMBIA": "GM",    "TANZANIA": "TZ",  "MALI": "MLI",
    "GUINEA": "GIN",   "MOZAMBIQUE": "MZ",
}

_ALIAS_MAP: dict[str, str] = {
    "GB": "UK",
    "LATIN": "LAT", "LATAM": "LAT", "LATINAM": "LAT",
    "LATINAMERICA": "LAT", "LATIN AMERICA": "LAT",
    "ENG": "EN",   # "ENG" prefix = English, not UK
    "USA": "US",
    "BRASIL": "BRA",
    "ESPANA": "ESP",
    # Streaming platforms
    "NETFLIX": "NF",
    "DISNEY+": "D+", "DISNEY": "D+", "DPLUS": "D+", "DISNEYPLUS": "D+",
    "AMAZON": "PRIME", "AMAZONPRIME": "PRIME",
    # Language full names used as channel prefixes
    "ENGLISH": "EN",
    "HINDI": "HI",
    "TAMIL": "TA",
    "TELUGU": "TE",  "TELEGU": "TE",       # TELEGU = common provider typo
    "KANNADA": "KN",
    "MALAYALAM": "ML",
    "GUJARATI": "GU",
    "PUNJABI": "PB",   # PB (not PA): PA is Panama (Spanish); Punjabi must not collapse onto it
    "MARATHI": "MR",
    "BENGALI": "BN", "BANGALI": "BN",       # BANGALI = common provider variant
    "ODIA": "OR",
    "BHOJPURI": "BHO",
    # African alternate forms
    "ETHO": "ETH",          # Ethiopia short form seen in provider data
    "GUINEE": "GIN",        # French spelling of Guinea
    "RDOM": "DO",           # República Dominicana abbreviation
    "TCHAD": "TCD",         # Chad (French name)
    "TCH": "TCD",           # Chad short form
}

REGION_FULL_NAMES: dict[str, str] = {
    # Streaming platforms
    "NF": "Netflix", "D+": "Disney+", "HBO": "HBO Max", "PRIME": "Amazon Prime",
    "TUBI": "Tubi", "PEACOCK": "Peacock", "APPLE": "Apple TV+",
    # 2-letter ISO
    "US": "United States", "UK": "United Kingdom", "FR": "France",
    "DE": "Germany", "ES": "Spain", "IT": "Italy", "PT": "Portugal",
    "NL": "Netherlands", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    # DNK is the ISO 3166-1 alpha-3 for Denmark. "DEN" (below) is the IOC/FIFA
    # code and was the only three-letter form here, so a real provider channel
    # named "KANAL 4 [DNK] [HEVC]" matched nothing and kept the bracket glued
    # into its title (owner report).
    "DNK": "Denmark",
    "FI": "Finland", "PL": "Poland", "RO": "Romania", "HU": "Hungary",
    "CZ": "Czech Republic", "GR": "Greece", "TR": "Turkey", "RU": "Russia",
    "UA": "Ukraine", "BR": "Brazil", "MX": "Mexico", "CA": "Canada",
    "AU": "Australia", "NZ": "New Zealand", "JP": "Japan", "KR": "South Korea",
    # NB: no "AR" entry — AR is the Arabic language code (see CODE_FACETS), NOT Argentina.
    # Argentina is "ARG" (below).  Displaying AR as "Argentina" was the mislabel bug (#138).
    "CN": "China", "IN": "India", "CL": "Chile",
    "CO": "Colombia", "PE": "Peru", "VE": "Venezuela", "IR": "Iran",
    "SA": "Saudi Arabia", "AE": "UAE", "EG": "Egypt", "MA": "Morocco",
    "IL": "Israel", "ZA": "South Africa", "ZW": "Zimbabwe", "KE": "Kenya",
    "GH": "Ghana", "TZ": "Tanzania", "UG": "Uganda", "ET": "Ethiopia",
    "ZM": "Zambia", "CM": "Cameroon", "SN": "Senegal", "TN": "Tunisia",
    "DZ": "Algeria", "LY": "Libya", "CI": "Ivory Coast", "AO": "Angola",
    "MZ": "Mozambique", "NG": "Nigeria", "PK": "Pakistan",
    "TH": "Thailand", "VN": "Vietnam", "ID": "Indonesia", "PH": "Philippines",
    "AT": "Austria", "CH": "Switzerland", "IE": "Ireland", "HR": "Croatia",
    "SK": "Slovakia", "SI": "Slovenia", "BG": "Bulgaria", "RS": "Serbia",
    "BE": "Belgium", "LU": "Luxembourg",
    # 3-letter
    "ARG": "Argentina", "AUS": "Australia", "AUT": "Austria", "BEL": "Belgium",
    "BOL": "Bolivia", "BRA": "Brazil", "CAN": "Canada", "CHL": "Chile",
    "COL": "Colombia", "HRV": "Croatia", "DEN": "Denmark", "ECU": "Ecuador",
    "FIN": "Finland", "FRA": "France", "GER": "Germany", "GRE": "Greece",
    "HUN": "Hungary", "IRL": "Ireland", "ITA": "Italy", "MEX": "Mexico",
    "NED": "Netherlands", "NOR": "Norway", "PAR": "Paraguay", "PER": "Peru",
    "POL": "Poland", "POR": "Portugal", "ROU": "Romania", "RUS": "Russia",
    "ESP": "Spain", "SWE": "Sweden", "SUI": "Switzerland", "TUR": "Turkey",
    "UKR": "Ukraine", "URY": "Uruguay", "VEN": "Venezuela", "JPN": "Japan",
    "CHN": "China", "IND": "India",
    # Additional 2-letter codes not already in the ISO block above
    "GM": "Gambia", "GN": "Guinea",
    # Additional 3-letter codes for African countries
    "NGA": "Nigeria",   "GHA": "Ghana",   "SEN": "Senegal",  "UGA": "Uganda",
    "CMR": "Cameroon",  "KEN": "Kenya",   "ETH": "Ethiopia", "SOM": "Somalia",
    "TZA": "Tanzania",  "MLI": "Mali",    "GIN": "Guinea",   "GAB": "Gabon",
    "GMB": "Gambia",    "TGO": "Togo",
    # Additional LatAm 3-letter codes
    "ARG": "Argentina", "VEN": "Venezuela", "COL": "Colombia",
    "URY": "Uruguay",   "DOM": "Dominican Republic",
    # Regional groupings
    "LAT": "Latin America", "LATS": "Latin America (Spanish)",
    "EXYU": "Ex-Yugoslavia",
    "SC": "Scandinavian",  # original-audio + Scandinavian subtitles (SE/NO/DK)
    "AL": "Albania", "ALB": "Albania",
    # Language codes (used as channel prefixes on some providers)
    "EN": "English", "HI": "Hindi", "TA": "Tamil", "TE": "Telugu",
    "ML": "Malayalam", "KN": "Kannada", "BN": "Bengali", "MR": "Marathi",
    "GU": "Gujarati", "PB": "Punjabi", "PA": "Panama", "FA": "Farsi / Persian", "KU": "Kurdish",
    "OR": "Odia", "BHO": "Bhojpuri",
    # Regional streaming platforms
    "ASTRO": "Astro (Malaysia)",
    "F1TV":  "F1TV",
    # French-Canadian / Quebec
    "QFR": "Quebec French",
    # Sports leagues / brands
    "EPL": "English Premier League", "EFL": "English Football League",
    "NBA": "NBA Basketball", "NFL": "NFL Football", "MLB": "MLB Baseball",
    "NHL": "NHL Hockey", "UFC": "UFC / MMA", "WWE": "WWE Wrestling",
    "BEIN": "beIN Sports", "ESPN": "ESPN", "FOX": "Fox", "CNN": "CNN",
    "SKY": "Sky", "MBC": "MBC",
    # Streaming platforms (surfaced by Ninja, 2026-06)
    "NEXT": "Next TV", "JOYN": "Joyn", "VIX": "Vix", "CITY": "City TV",
    "PLAY+": "Play+", "A+": "Apple+", "NOWTV": "Now TV", "STH": "STH",
    # Additional regions (surfaced by Ninja, 2026-06)
    "MXC": "Mexico",  # surfaced in TREX + IPTV Ninja, measured 2,934 channels
    "ISR": "Israel",  # surfaced in TREX + IPTV Ninja, measured 588 channels
    "SOM": "Somalia",  # measured 2,812 channels
    # Content-type prefixes (Trex / provider-specific)
    "MV": "Music Videos", "SPT": "Sports",
}


def platform_display(code: str, style: str) -> str:
    """Return the viewer-facing label for a stored platform prefix *code*.

    The chokepoint that turns a stored platform code (``detected_region``
    when it's a :data:`PLATFORM_CODES` member — e.g. ``"A+"``, ``"NF"``)
    into the string shown in the channel-list platform chip, mirroring
    :func:`quality_display`'s "single chokepoint" role for the quality chip
    (#257).

    ``style`` is already resolved to ``"full"``/``"short"`` by the caller —
    this function has no notion of density. The Settings control
    ("Platform names: Auto / Full name / Short code") stores ``"auto"`` as
    its default; resolving "auto" against the CURRENT row's density (full
    name in Comfy/Comfy+, short code in Compact) is a control-layer decision
    that belongs to ``ChannelRowDelegate`` (which already tracks density),
    not this display-only helper — see
    ``ChannelRowDelegate._effective_platform_style``.

    Args:
        code: A stored platform prefix code (e.g. ``"A+"``, ``"NF"``).
        style: ``"short"`` returns *code* unchanged; anything else
            (``"full"``, or an already-resolved ``"auto"``) returns the
            friendly brand name from :data:`REGION_FULL_NAMES`, falling back
            to *code* itself when no friendly name is known.

    Returns:
        The display label. Never mutates identity — callers keep the
        original code for queries, filter keys and DB writes.
    """
    if not code:
        return code
    if style == "short":
        return code
    return REGION_FULL_NAMES.get(code.upper(), code)


# ── Confidence constants (DR-0006) ───────────────────────────────────────────── #
# Coarse, documented scale — tunable without changing the test assertions.
# "denoted"      = the facet the code explicitly means in IPTV convention (~0.9)
# "strong prior" = a real, plausible adjacent guess (~0.3)
# "weak prior"   = a real but low-probability adjacent guess (~0.15)
CONF_DENOTED: float = 0.9
CONF_STRONG_PRIOR: float = 0.3
CONF_WEAK_PRIOR: float = 0.15

# ── Name-derived cast: words that prove a trailing residual is NOT a person ──── #
# ``parse_channel_name().trailing`` captures whatever a provider appended after the
# year — "EN - Adaptation. 4K (2002) NICOLAS CAGE".  Measured over the owner's
# 414,800 VOD rows, 8,257 names carry such a residual across 917 distinct values,
# and only about half are people.  The rest are language words, formats and studio
# or collection labels: POLSKI (918), 4K (652), DOKUMENT (531), DUBBING (221),
# NAPISY (122), BG-AUDIO (54), PIXAR (52).
#
# Emitting those as ``person`` tags would not be "capture generously with low
# confidence" (DR-0006) — it would be recording something the vocabulary already
# knows to be false.  Confidence ranks a real guess; it does not launder a wrong
# one.  So a residual containing any of these is never read as a person, and the
# genuinely unclassifiable remainder becomes a LOW-confidence person tag.
NON_PERSON_RESIDUAL_WORDS: frozenset[str] = frozenset({
    # Collection / edition labels
    "COLLECTION", "COLECCION", "COLECCIÓN", "COLLECTIE", "SAGA", "TRILOGY",
    "TRILOGIA", "SERIES", "SERIE", "EDITION", "REMASTERED", "EXTENDED",
    "UNCUT", "SPECIAL", "COMPLETE", "ANTHOLOGY", "BOXSET",
    # Audio / subtitle / format words (several languages)
    "AUDIO", "DUBBING", "DUBBED", "DUB", "SUB", "SUBS", "SUBTITLED", "NAPISY",
    "LEKTOR", "MULTI", "VOSTFR", "VOSE", "LEGENDADO", "DUBLADO",
    # Genre / kind words that appear bare in this position
    "DOKUMENT", "DOKUMENTAL", "DOCUMENTARY", "ANIMACJA", "ANIMATION",
    "CARTOON", "MUSICAL", "TEATR", "THEATRE", "THEATER", "CLASSIC",
    "CLASSICS", "MOVIES", "MOVIE", "FILM", "FILMY", "KIDS", "SPORT",
    # Language words (bare, not codes — codes are caught by the classifiers)
    "POLSKI", "POLSKIE", "ENGLISH", "ESPANOL", "ESPAÑOL", "FRANCAIS",
    "FRANÇAIS", "DEUTSCH", "ITALIANO", "PORTUGUES", "PORTUGUÊS", "TURKCE",
    "TÜRKÇE", "ARABIC", "LATINO",
})

# ── AI-provenance markers (single source of truth) ───────────────────────────── #
# Some providers stamp a trailing parenthetical marker onto a channel name to flag
# how it was produced.  Two DISTINCT user-facing concepts (a user may tolerate an
# AI dub but not AI-generated content), so two distinct content_type facet values:
#
#   • "(AI Generated)"  — the CONTENT itself is AI-generated (fabricated music-video
#     "collaborations" like "[MV] Lady Gaga - Born To Win - ft. Sia & The Weeknd
#     (AI Generated)").  → value "ai_generated".
#   • "(AI)"            — an AI-generated VOICEOVER / dub, not AI content (Polish VOD
#     like "PL - Bugonia (2025) Lektor (AI)"; "Lektor" = Polish voice-over narration).
#     → value "ai_voiceover".
#
# Both are matched ONLY as a TRAILING marker (end of name, optional surrounding
# whitespace), case-insensitively.  A mid-title parenthetical or a bare "AI" without
# parens never matches — the anchoring ($) and the required parens guard against
# false positives like "AI Superstars" or "Terminator (AI Uprising)".

# Trailing "(AI Generated)" and the defensive spellings "(AI-Generated)" /
# "(A.I. Generated)".  The token right after "(" must be AI / A.I. (not e.g.
# "(Fully AI Generated)"), and "GENERATED" must be the closing word.
_AI_GENERATED_SUFFIX_RE = re.compile(
    r"\s*\(\s*A\.?\s*I\.?[\s\-]+GENERATED\s*\)\s*$",
    re.IGNORECASE,
)

# Trailing bare "(AI)" marker (AI-generated voiceover/dub).  Matches ONLY the exact
# parenthetical — "(AIR)", "(AI Uprising)", "(A.I.)" and mid-title "(AI)" do not match.
_AI_MARKER_SUFFIX_RE = re.compile(
    r"\s*\(\s*AI\s*\)\s*$",
    re.IGNORECASE,
)

# "Lektor" (Polish voice-over narration) sitting immediately before the "(AI)" marker
# is a strong denotation that the "(AI)" flags an AI dub → high confidence.
_LEKTOR_TRAILING_RE = re.compile(r"\blektor\b\s*$", re.IGNORECASE)

# Canonical content_type facet values for the two AI-provenance flavors.  Snake_case
# to match the existing content_type value family (e.g. "live_event", "ppv").
AI_GENERATED_VALUE: str = "ai_generated"
AI_VOICEOVER_VALUE: str = "ai_voiceover"


# ── content_type value → display name (single source of truth) ──────────────── #
# The ``content_type`` facet stores snake_case slugs as the queried/stored identity
# (``ppv``, ``live_event``, ``sports``, ``ai_generated``, ``ai_voiceover``).  Those
# slugs are NOT presentation-ready, so every surface that shows a content_type VALUE
# (details-pane Tags chips, the recipe/tag-cloud pantry, the Global Exclusions
# "Content Provenance" section) routes the slug through :func:`content_type_display`
# for its English label.  The slug remains the identity everywhere — display only.
#
# This is the value-display sibling of the details pane's ``_FACET_LABELS`` (which
# names the facet TYPES, e.g. ``content_type`` → "Content Type"); it lives here
# because ``channel_name_utils.py`` is the lookup-table home (CLAUDE.md) and the
# slugs originate here (``AI_GENERATED_VALUE`` / ``AI_VOICEOVER_VALUE``).
CONTENT_TYPE_DISPLAY_NAMES: dict[str, str] = {
    "ppv":            "PPV",
    "live_event":     "Live Event",
    "sports":         "Sports",
    AI_GENERATED_VALUE: "AI Generated",
    AI_VOICEOVER_VALUE: "AI Voiceover",
}


def content_type_display(value: str) -> str:
    """Return the English display name for a ``content_type`` tag *value*.

    The single chokepoint that turns a stored ``content_type`` slug into a
    human-readable label.  Known slugs map via :data:`CONTENT_TYPE_DISPLAY_NAMES`
    (``"ai_generated"`` → ``"AI Generated"``); an unknown slug degrades
    gracefully to a Title-Cased, underscore-stripped form so a future value never
    renders as a raw ``snake_case`` token even before it is added to the map.

    Args:
        value: A stored ``content_type`` tag value (e.g. ``"ai_voiceover"``).

    Returns:
        The display name (e.g. ``"AI Voiceover"``).  Never mutates identity —
        callers keep the original slug for queries/state.
    """
    known = CONTENT_TYPE_DISPLAY_NAMES.get(value)
    if known is not None:
        return known
    return value.replace("_", " ").title()


class AiProvenance(NamedTuple):
    """Result of :func:`detect_ai_provenance`.

    Attributes:
        value:        The content_type facet value — ``"ai_generated"`` (AI content)
                      or ``"ai_voiceover"`` (AI dub).
        confidence:   DR-0006 base confidence.  ``CONF_DENOTED`` for the explicit
                      ``(AI Generated)`` marker and for ``(AI)`` preceded by
                      ``Lektor``; ``CONF_STRONG_PRIOR`` for a bare ``(AI)`` with no
                      Lektor context (still the voiceover value, just ranked lower).
        cleaned_name: *name* with the recognized trailing marker removed (trailing
                      whitespace stripped).  Only the recognized marker is removed —
                      no generic paren-stripping.
    """

    value: str
    confidence: float
    cleaned_name: str


def detect_ai_provenance(name: str) -> Optional[AiProvenance]:
    """Detect a trailing AI-provenance marker on a channel name.

    Recognizes ONLY end-of-name markers (optional surrounding whitespace),
    case-insensitively.  ``(AI Generated)`` (and the defensive spellings
    ``(AI-Generated)`` / ``(A.I. Generated)``) denotes AI-generated *content*;
    a bare ``(AI)`` denotes an AI-generated *voiceover/dub*.  A mid-title
    parenthetical or a bare ``AI`` without parens never matches.

    Confidence follows DR-0006 (capture generously, label honestly): the marker
    always lands as a tag — confidence is a ranking/prune-priority signal, never a
    suppression gate.  The content marker and a Lektor-anchored ``(AI)`` are
    ``CONF_DENOTED``; a bare ``(AI)`` with no Lektor context is the same voiceover
    value at ``CONF_STRONG_PRIOR`` (the observed corpus is all Polish lektor VOD, so
    ``(AI)`` denotes an AI dub there, but a bare ``(AI)`` elsewhere is a guess).

    Args:
        name: A raw channel name or an already-parsed title.

    Returns:
        An :class:`AiProvenance` when a trailing marker is present, else ``None``.
        Pure — no DB, no Qt.
    """
    if not name:
        return None

    gm = _AI_GENERATED_SUFFIX_RE.search(name)
    if gm:
        return AiProvenance(AI_GENERATED_VALUE, CONF_DENOTED, name[: gm.start()].rstrip())

    vm = _AI_MARKER_SUFFIX_RE.search(name)
    if vm:
        cleaned = name[: vm.start()].rstrip()
        lektor = bool(_LEKTOR_TRAILING_RE.search(cleaned))
        conf = CONF_DENOTED if lektor else CONF_STRONG_PRIOR
        return AiProvenance(AI_VOICEOVER_VALUE, conf, cleaned)

    return None


# ── Content-descriptor groups (single source of truth for the `category:` facet) ── #
# These group names appear in BASE_PREFIX_GROUPS or BASE_PLATFORM_GROUPS for
# display-grouping purposes, but they are NOT locales or platforms.  They denote
# a content KIND, so their facet depends on media_type at tag time:
#   - live  channel → `category:` (a live-channel kind / programming genre)
#   - movie / series → `genre:` (a VOD content descriptor)
#
# Routing is performed by remap_content_descriptor_facets() in tag_decomposer.py,
# called from _collect_tags() in tag_backfill.py (the ONE per-channel tag builder).
#
# "Pay TV" is deliberately absent — it is a real distribution platform (channels
# from a pay-TV bundle) and correctly stays as `platform:Pay TV`.
CONTENT_DESCRIPTOR_GROUPS: frozenset[str] = frozenset({
    "Adult", "Sports", "Kids", "Music", "News", "Religious", "24/7",
})

# ── EPG "On Now" viewing content-type classifier (Slice 3C) ────────────────────── #
# A *lighter*, distinct namespace from CONTENT_DESCRIPTOR_GROUPS/CONTENT_TYPE_DISPLAY_NAMES
# above — those classify the channel CORPUS (facet tagging / dedup provenance); this
# classifies a channel for the EPG "On Now" viewing-content-type filter ("All Types ▼").
# "Movies" is deliberately new here — it has no CONTENT_DESCRIPTOR_GROUPS/prefix-group
# equivalent, so it is keyword-only (never a direct prefix-group hit).
EPG_CONTENT_TYPES: tuple[str, ...] = ("Sports", "News", "Kids", "Movies", "Music")

# Keyword tables for the keyword-scan fallback (case-insensitive substring match against
# the channel name).  "Sports" is deliberately absent — its keywords are loaded from
# special_content.py's load_sports_definitions() (bundled sports_definitions.yaml + any
# user override) via _sports_keywords_flat() below, so the sport/league keyword list has
# exactly one home instead of a second, drifting copy here.
EPG_CONTENT_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "News": (
        "news", "cnn", "bbc news", "sky news", "msnbc", "fox news", "nbc news",
        "cbs news", "abc news", "al jazeera", "euronews", "france24", "reuters",
    ),
    "Kids": (
        "kids", "cartoon", "nick", "disney", "cbeebies", "junior", "baby",
        "nickelodeon", "boomerang", "cbbc", "toon",
    ),
    "Movies": (
        "movies", "cinema", "film", "hbo", "cinemax", "starz", "showtime",
    ),
    "Music": (
        "music", "mtv", "vh1", "hits", "radio", "trace", "vevo",
    ),
}


@lru_cache(maxsize=1)
def _sports_keywords_flat() -> tuple[str, ...]:
    """Flattened sport + league keywords from special_content.py (single source of truth).

    Deferred import: ``special_content.py`` imports ``parse_platform_event`` from this
    module at module scope, so importing it back here at module level would be a
    circular import — this local import breaks the cycle by deferring it to call time.

    Cached for the process lifetime: ``load_sports_definitions()`` reads a YAML file
    from disk, and this classifier runs once per On-Now row per render — re-reading the
    file per channel would be wasteful for a table that is effectively static per
    session (a settings-UI edit to the user override file takes effect next launch).
    """
    from metatv.core.special_content import load_sports_definitions

    sport_kw, league_kw = load_sports_definitions()
    flat: list[str] = []
    for keywords in sport_kw.values():
        flat.extend(k.lower() for k in keywords)
    for keywords in league_kw.values():
        flat.extend(k.lower() for k in keywords)
    return tuple(flat)


def classify_channel_content_type(name: str, detected_prefix: Optional[str]) -> Optional[str]:
    """Classify a channel's EPG viewing content type for the On Now "All Types" filter.

    Priority (cheapest/most-confident first):
      1. ``detected_prefix`` already denotes a content-descriptor group that is also
         in :data:`EPG_CONTENT_TYPES` (e.g. a channel whose stored prefix IS "Sports" /
         "Kids" / "Music" / "News") — no keyword scan needed, no ambiguity.
      2. Keyword scan over the lowercased channel *name* — Sports keywords come from
         special_content.py's sport/league loader (:func:`_sports_keywords_flat`);
         News/Kids/Movies/Music from :data:`EPG_CONTENT_TYPE_KEYWORDS`.
      3. ``None`` — the caller displays this as "Other".

    Pure — no DB, no Qt.  ``detected_prefix`` must be the channel's already-stored
    ``detected_prefix`` field (ingestion-computed) — never re-derive it by parsing the
    name here (CLAUDE.md "channel-name fields" rule).

    Args:
        name: The channel's raw name.
        detected_prefix: The channel's stored ``detected_prefix``, or ``None``/``""``.

    Returns:
        One of :data:`EPG_CONTENT_TYPES`, or ``None`` if nothing matched.
    """
    if detected_prefix:
        prefix_titled = detected_prefix.strip().title()
        if prefix_titled in CONTENT_DESCRIPTOR_GROUPS and prefix_titled in EPG_CONTENT_TYPES:
            return prefix_titled

    name_lower = (name or "").lower()
    if not name_lower:
        return None

    if any(kw in name_lower for kw in _sports_keywords_flat()):
        return "Sports"

    for content_type, keywords in EPG_CONTENT_TYPE_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return content_type

    return None


# ── Restricted-content detection (owner-reported gap) ──────────────────────────── #
# The provider `is_adult` API flag is unreliable — some providers never set it even
# for content that is unambiguously marked by naming convention. This is a
# NEUTRAL/abstract internal name deliberately — "restricted" — never "adult" in code;
# user-facing surfaces keep the "Adult" label (owner steer). Do NOT rename the
# established is_adult / filter_adult_mode / build_adult_filter identifiers elsewhere;
# this is new, separately-provenanced detection that feeds the same gate.
#
# Conservative by design: a false positive here HIDES legitimate content from general
# surfaces (Discover/recommendations/browse) when adult_mode="hide", so only
# unambiguous explicit-content markers are curated in.
#
# RESTRICTED_NAME_TOKENS is scanned as whole words anywhere in the channel name.
# RESTRICTED_PREFIX_TOKENS additionally includes a bare "X" — too ambiguous to
# word-scan across a full name (would false-positive on "X Factor", "Generation X",
# "Malcolm X" style titles) but a confirmed adult marker when it IS the channel's
# entire leading prefix token (mirrors BASE_PREFIX_GROUPS["Adult"] =
# ["X", "XXX", "ADULT"] in config.py — the existing "Adult" content-descriptor group).
def is_restricted(detected_prefix: Optional[str], name: str, config=None) -> bool:
    """True when a channel is restricted, per the USER's own configuration.

    Deliberately makes no judgement of its own about what counts as restricted.
    Two signals, both user-owned:

    1. ``detected_prefix`` resolves to the user's "Adult" prefix GROUP — the same
       group shown in Global Exclusions and editable via prefix-group overrides.
       Whatever codes that group contains is what counts; this function ships no
       token list of its own. (Real libraries carry codes nobody would guess —
       one provider uses ``PORNBOX``.)
    2. ``config.restricted_keywords`` — an empty-by-default list the user fills
       in. Matched case-insensitively against the channel name. Empty means no
       name matching happens at all.

    The provider's own ``is_adult`` flag is handled separately at the query gate.

    Called at ingestion only; the result is stored on
    ``ChannelDB.detected_restricted`` and read everywhere else.
    """
    if detected_prefix:
        try:
            # base groups + the user's own overrides; falls back to the shipped
            # base map when no config is threaded (migrations without one).
            if config is not None:
                groups = config.filter_language_groups
            else:
                from metatv.core.config import BASE_PREFIX_GROUPS as groups
            adult_codes = {c.upper() for c in (groups.get("Adult") or [])}
        except Exception:
            adult_codes = set()
        if detected_prefix.strip().upper() in adult_codes:
            return True

    keywords = getattr(config, "restricted_keywords", None) or []
    if keywords and name:
        lowered = name.lower()
        return any(k.strip().lower() in lowered for k in keywords if k and k.strip())
    return False




# ── Dual-facet code table (DR-0006) ─────────────────────────────────────────── #
# Maps a normalized IPTV prefix code → one or more (facet_type, value, confidence)
# entries.  Rules (see DR-0006 and CLAUDE.md "Tags/facets" rule):
#
#   • The "denoted" facet (what the code *means* in IPTV convention) → CONF_DENOTED.
#   • A real adjacent guess (a candidate the code *might also* indicate) → CONF_STRONG_PRIOR
#     or CONF_WEAK_PRIOR depending on how likely the guess actually is.
#   • A candidate must genuinely exist.  ``EN`` has no place called "EN", so only one
#     entry (language).  ``FR`` can plausibly mean both French (language) and France (region).
#   • ``LAT`` is a DISTINCT value ("Latin American Spanish"), never merged with generic
#     "Spanish" — dialect granularity the user separates (DR-0006 explicitly states this).
#   • ``AR`` = IPTV-convention Arabic language code, NOT Argentina.
#     Argentina is ``ARG`` / ``AR`` the ISO-3166-1 country code.  In IPTV prefix
#     convention the two-letter ``AR`` overwhelmingly means Arabic; the decomposer
#     must consult this table before falling through to REGION_FULL_NAMES.
#
# This dict is the SINGLE SOURCE OF TRUTH for dual/prior/ambiguous codes.
# Do NOT hardcode dual-facet logic in tag_decomposer.py — read from here.
CODE_FACETS: dict[str, list[tuple[str, str, float]]] = {
    # ── Language-first codes with a plausible region prior ─────────────────── #
    # EN: language code only — there is no place called "EN", so NO region guess.
    "EN":  [("language", "English",               CONF_DENOTED)],

    # FR: primarily French (language); France is a real prior but many FR channels
    # are Canadian/diaspora, so the region guess is low-confidence.
    "FR":  [("language", "French",                CONF_DENOTED),
            ("region",   "FR",                    CONF_STRONG_PRIOR)],

    # DE: primarily German (language); Germany is a real prior.
    "DE":  [("language", "German",                CONF_DENOTED),
            ("region",   "DE",                    CONF_STRONG_PRIOR)],

    # ES: primarily Spanish (language); Spain is very low-confidence
    # (Latin America dwarfs Spain in IPTV traffic).
    "ES":  [("language", "Spanish",               CONF_DENOTED),
            ("region",   "ES",                    CONF_WEAK_PRIOR)],

    # IT: primarily Italian (language); Italy is a real prior.
    "IT":  [("language", "Italian",               CONF_DENOTED),
            ("region",   "IT",                    CONF_STRONG_PRIOR)],

    # PT: primarily Portuguese (language); Portugal is a real prior (Brazil also uses PT).
    "PT":  [("language", "Portuguese",            CONF_DENOTED),
            ("region",   "PT",                    CONF_STRONG_PRIOR)],

    # NL: primarily Dutch (language); Netherlands is a real prior.
    "NL":  [("language", "Dutch",                 CONF_DENOTED),
            ("region",   "NL",                    CONF_STRONG_PRIOR)],

    # PL: primarily Polish (language); Poland is a real prior.
    "PL":  [("language", "Polish",                CONF_DENOTED),
            ("region",   "PL",                    CONF_STRONG_PRIOR)],

    # SE: primarily Swedish (language); Sweden is a real prior.
    "SE":  [("language", "Swedish",               CONF_DENOTED),
            ("region",   "SE",                    CONF_STRONG_PRIOR)],

    # NO: primarily Norwegian (language); Norway is a real prior.
    "NO":  [("language", "Norwegian",             CONF_DENOTED),
            ("region",   "NO",                    CONF_STRONG_PRIOR)],

    # DK: primarily Danish (language); Denmark is a real prior.
    "DK":  [("language", "Danish",                CONF_DENOTED),
            ("region",   "DK",                    CONF_STRONG_PRIOR)],

    # FI: primarily Finnish (language); Finland is a real prior.
    "FI":  [("language", "Finnish",               CONF_DENOTED),
            ("region",   "FI",                    CONF_STRONG_PRIOR)],

    # ── Region-first codes with a plausible language prior ─────────────────── #
    # US: primarily United States (region); English is a real but lower prior
    # (Telemundo, Univision and other Spanish-language US channels are common).
    "US":  [("region",   "US",                    CONF_DENOTED),
            ("language", "English",               CONF_STRONG_PRIOR)],

    # UK: primarily United Kingdom (region); English is a real prior.
    "UK":  [("region",   "UK",                    CONF_DENOTED),
            ("language", "English",               CONF_STRONG_PRIOR)],

    # ── Special/distinct values ─────────────────────────────────────────────── #
    # LAT: Latin American Spanish — a DISTINCT value, never merged into "Spanish".
    # No single region is meaningful (spans many countries), so no region guess.
    "LAT": [("language", "Latin American Spanish", CONF_DENOTED)],

    # AR: IPTV convention = Arabic language.  NOT Argentina (which is ARG or the
    # ISO-3166-1 country code AR — kept in REGION_FULL_NAMES for legacy compat).
    # CODE_FACETS takes priority: the decomposer checks here before REGION_FULL_NAMES.
    "AR":  [("language", "Arabic",                CONF_DENOTED)],
}


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


def is_event_placeholder(name: str) -> bool:
    """Return True when *name* is a PPV/event placeholder row (no actual stream).

    Providers pad their PPV slot bundles with placeholder entries when no event is
    scheduled for a slot.  These rows are NOT playable streams and must be excluded
    from all content surfaces.

    Detection rule: the name contains the literal substring ``NO EVENT STREAMING``
    (case-insensitive).  This substring is the canonical "empty slot" marker used by
    every provider that injects these rows (e.g.
    ``- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 [DE| DYN PPV EXCLUSIVE]``).
    The substring is specific enough to avoid false positives on real channels — a
    legitimate channel named "… NO EVENT STREAMING …" does not exist in practice, and
    even if it did, the provider should rename it.
    """
    if not name:
        return False
    return "NO EVENT STREAMING" in name.upper()


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


def normalize_region_code(raw: str) -> str:
    """Normalize a raw prefix token to a canonical short display code."""
    upper = raw.strip().upper()
    if upper in _FULL_NAME_TO_CODE:
        return _FULL_NAME_TO_CODE[upper]
    if upper in _ALIAS_MAP:
        return _ALIAS_MAP[upper]
    return upper


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


# Bare "multiple audio/subtitle tracks available" indicator tokens.  Distinct
# from _SUB_DUB_TOKENS (the SUB/DUB *role* family) because these denote "more
# than one track", not a specific sub/dub role; MUTI is the common
# missing-L typo, MULTISUB the compound form.  A dedicated collection-noise
# constant (rather than extending _SUB_DUB_TOKENS or reusing the *function*-
# local ``_MULTI_MARKERS`` inside extract_audio_annotation) so this stays
# scoped to collection-string cleanup and never silently reshapes the
# (deliberately conservative — see the DUAL/AUDIO/MULTI caveat near
# _UNAMBIGUOUS_SUBDUB_MARKERS) title-parenthetical qualifier logic.
_MULTI_TRACK_TOKENS: frozenset[str] = frozenset({"MULTI", "MUTI", "MULTISUB"})

# Leading pipe-delimited marker that _CATEGORY_MARKER_RE didn't recognize
# because its code exceeds that regex's 2-4 char code slot (e.g. "MULTI" is
# 5 chars) — parse_category_marker() leaves it in place unrecognized.
# strip_collection_noise_tokens() below re-examines exactly this shape and
# removes it when every token inside is noise.
_LEADING_BRACKET_RE = re.compile(r'^\|\s*([^|]+?)\s*\|\s*')

# Combined vocabulary for strip_collection_noise_tokens(): a token counts as
# collection noise when it duplicates the quality chip (QUALITY_TOKENS), the
# subtitle-marker chip's sub/dub family (_SUB_DUB_TOKENS), a multi-track
# marker (_MULTI_TRACK_TOKENS), or the media-type icon (MEDIA_TYPE_TOKENS).
_COLLECTION_NOISE_TOKENS: frozenset[str] = (
    QUALITY_TOKENS | _SUB_DUB_TOKENS | _MULTI_TRACK_TOKENS | MEDIA_TYPE_TOKENS
)

# Restricted vocabulary for the TRAILING-token pass in
# strip_collection_noise_tokens() — deliberately excludes MEDIA_TYPE_TOKENS.
# Measured against the owner's real 486,588-row library: the whole-span gate
# above only fully/partially cleans ~5.2% of noisy rows because real feeds
# routinely tack a single quality/sub-dub/multi word onto an otherwise-real
# name ("HINDI SUBS", "FILMOVI 4K UHD") rather than making the WHOLE string
# noise. Those trailing words are safe to peel one at a time regardless of
# what remains. Media-type words are NOT safe to peel this way — "TAMIL
# MOVIES" / "NORDIC FILMS" are legitimate collection names where the media
# word IS part of the name, and a media word can lead too ("MOVIES
# 2018-2021"), so MEDIA_TYPE_TOKENS never participates in the trailing pass
# (only the whole-span gate above, where "every token is noise" already
# proves the media word isn't naming anything real).
_TRAILING_NOISE_TOKENS: frozenset[str] = (
    QUALITY_TOKENS | _SUB_DUB_TOKENS | _MULTI_TRACK_TOKENS
)

# Matches the last whitespace/hyphen/slash-delimited leaf of a string, plus
# any separator run immediately before it — group 1 is the leaf itself;
# slicing the source string at m.start() drops that leaf (and its leading
# separator) while leaving every character before it untouched, so a kept
# prefix is never reformatted/rejoined.
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


def _strip_quality(bare: str) -> tuple[str, list[str]]:
    """Strip all trailing quality tokens from bare, returning (bare, tokens)."""
    tokens: list[str] = []
    while True:
        qm = _QUALITY_SUFFIX_RE.search(bare)
        if not qm:
            break
        tokens.insert(0, qm.group(1).upper())
        bare = bare[: qm.start()].strip()
    return bare, tokens


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
    if (q := _BRACKET_QUALITY_ALIASES.get(content)):
        return _BracketClass("quality", q)
    if content in QUALITY_TOKENS:
        return _BracketClass("quality", content)
    if (code := _BRACKET_LANG_NORM.get(content)):
        return _BracketClass("origin", code)
    if content in PLATFORM_CODES:
        return _BracketClass("origin", content)
    if len(content) in (2, 3) and content.isalpha() and content not in QUALITY_TOKENS:
        return _BracketClass("origin", normalize_region_code(content))
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

    trailing = ""

    # 1b. Pre-cut: relocate a real 4-digit year in parens that has trailing FREE-TEXT
    # junk after it (cast/extra credits, not a recognized qualifier) so the existing
    # end-anchored steps below (quality/audio/lang/year) can extract it normally.
    # E.g. "Title 4K (1996) HARVEY KEITEL, ..." → "Title 4K (1996)" — the "(1996)"
    # itself is kept so step 5's _YEAR_RE still finds it at the end.  Only real
    # (19xx)/(20xx) years trigger this — never an arbitrary parenthetical like
    # "(Director's Cut)" or "(Soleil Noir)", and never a bare trailing number that's
    # part of the title ("Blade Runner 2049") since this only matches parenthesized
    # years.  When there are multiple parenthesized years, the LAST one is the cut
    # point.  A year already at the end (nothing trailing) is left alone.  Two
    # guards keep this from misfiring on legitimate titles:
    #   - Skip when the trailing text is itself a parenthetical/bracket qualifier
    #     ("Hanna (2019) (US)", "Title (2022) (ENG DUB)") — those are already
    #     handled correctly by the later end-anchored steps (lang/bracket/
    #     multi-qualifier), which don't care what precedes them.
    #   - Skip when the trailing text isn't ALL-CAPS. Provider cast/extra blobs are
    #     conventionally uppercase ("HARVEY KEITEL, TARANTINO", "BROADWAY MUSICAL");
    #     mixed/title-case trailing text ("FBI (2024) Reboot") is a real subtitle
    #     that's part of the title, not metadata junk, and must be left intact.
    _year_matches = list(_PAREN_YEAR_ANYWHERE_RE.finditer(bare))
    if _year_matches:
        _last_year_match = _year_matches[-1]
        _trailing = bare[_last_year_match.end():].strip()
        _trailing_is_upper_junk = (
            any(ch.isupper() for ch in _trailing)
            and not any(ch.islower() for ch in _trailing)
        )
        if (
            _trailing
            and not _trailing.startswith(("(", "["))
            and _trailing_is_upper_junk
        ):
            # Keep it. This span is already known to be provider-appended
            # extra credits ("HARVEY KEITEL, TARANTINO", "NICOLAS CAGE") —
            # the guards above established that. Discarding it meant no
            # caller could see the actor the provider had helpfully named,
            # even on titles with no metadata at all.
            trailing = _trailing
            bare = bare[: _last_year_match.end()]

    # 2. Strip quality tokens from end (first pass)
    bare, quality = _strip_quality(bare)

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
        # "unknown": bracket stays in bare name

    # 4. Strip explicit lang/region qualifier from end: (EN), (JP)
    # Parenthetical form overrides bracket form if both are present.
    lang = _bracket_origin
    lm = _LANG_QUALIFIER_RE.search(bare)
    if lm:
        token = lm.group(1).strip().upper()
        if token in QUALITY_TOKENS:
            # Quality token in parenthetical form: "(SD)", "(UHD)", "(FHD)", "(HQ)".
            # Guard exactly as the bracket path (_classify_bracket) does — a quality
            # marker must never be misclassified as a lang/region qualifier and then
            # stored as detected_region (which also silently dropped the quality).
            quality.append(token)
            bare = bare[: lm.start()].strip()
        else:
            candidate = normalize_region_code(lm.group(1))
            if candidate != region:
                lang = candidate
            bare = bare[: lm.start()].strip()

    # 5. Strip year from end
    year = ""
    ym = _YEAR_RE.search(bare)
    if ym:
        year = ym.group(1) or ym.group(2)  # group 1 = paren form, group 2 = dash form
        # Anything still after the year here (step 1b usually took it already).
        trailing = trailing or bare[ym.end():].strip()
        bare = bare[: ym.start()].strip()

    # 6a. Second bracket pass — catches brackets that were hidden by the year token in
    #     step 5 ("[4K] (2025)") or by a second bracket in step 3 ("[FRENCH] [4k]").
    #     Uses the same _classify_bracket() classifier as step 3.
    #     Step 4 (lang assignment) already ran, so "origin" results set lang= directly.
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
        # audio in step 6a is unusual and not expected; unknown stays in bare

    # 6b. Second quality pass — catches "Name HEVC (2024)" where HEVC was before year
    bare, quality2 = _strip_quality(bare)
    quality = quality2 + quality  # prepend (quality2 came from closer to the name)

    # 6c. Trailing-qualifier strip loop — catches single-token parenthetical/bracket
    #     qualifiers that earlier steps leave behind when there is no year to anchor the
    #     strip.  Examples: "Name (US) (4K)", "Name (VOSTFR)", "Name (HQ)".
    #     Multi-word alt-titles ("Name (30 Monedas)", "Name (Soleil Noir)") are preserved
    #     because PAREN_QUALIFIER_RE requires no internal space inside the parens.
    #     Already-committed field assignments (lang, year, audio, quality) are NOT
    #     re-derived here — this pass only cleans the displayed title.
    #     Audio annotation: we also intercept stripped qualifiers to extract audio facets.
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

    # 7. Append prefix quality (standalone "4K - Movie" or compound "4K-DE") at lowest
    # priority so name-suffix quality (step 2/6b) — which describes the actual encode —
    # wins when both are present (e.g. "[US] 4K-DE - Movie UHD" → quality[0] = "UHD").
    if _prefix_quality and _prefix_quality not in quality:
        quality = quality + [_prefix_quality]

    return ParsedChannel(region, bare, quality, lang, year, audio,
                         _audio_langs, _dub_langs, _sub_langs, trailing)


# ── EPG TLD compatibility (region-gated fuzzy matching, Wave 3 Slice 3B) ─────── #
# Maps a normalized region/prefix code (as stored in ChannelDB.detected_prefix /
# .detected_region — see normalize_region_code above) to the set of EPG-feed
# TLDs (the lowercase suffix of an XMLTV epg_id, e.g. "UandEden.uk" -> "uk")
# that are plausible broadcast pairings for that region. Consulted ONLY by
# EpgManager._build_match_map's tiers 2/3 (same-/cross-provider fuzzy name
# matching, core/epg_manager.py) to reject cross-region false positives — e.g.
# an EN-prefixed channel fuzzy-matching a Spanish (.es) guide feed. Tier-1
# exact epg_channel_id matches are never gated.
#
# A code absent from this map, or an EPG feed with no parseable TLD, means the
# gate ABSTAINS — the match proceeds exactly as it did before this feature
# existed. This is deliberately partial: only common broadcast-language
# groupings are covered; an unrecognized region/prefix never blocks a match.
_EPG_TLD_EN = frozenset({"uk", "us", "ca", "ie", "au", "nz"})
_EPG_TLD_ES = frozenset({"es", "mx", "ar", "cl", "co"})
_EPG_TLD_DE = frozenset({"de", "at", "ch"})
_EPG_TLD_FR = frozenset({"fr", "be", "ca", "ch"})
_EPG_TLD_IT = frozenset({"it"})
_EPG_TLD_NL = frozenset({"nl", "be"})

REGION_TLD_COMPATIBILITY: dict[str, frozenset[str]] = {
    # English-language broadcast regions (2- and 3-letter forms + the "EN"
    # language-code prefix some providers use)
    "US": _EPG_TLD_EN, "UK": _EPG_TLD_EN, "GB": _EPG_TLD_EN, "CA": _EPG_TLD_EN,
    "IE": _EPG_TLD_EN, "AU": _EPG_TLD_EN, "NZ": _EPG_TLD_EN, "EN": _EPG_TLD_EN,
    "AUS": _EPG_TLD_EN, "IRL": _EPG_TLD_EN, "CAN": _EPG_TLD_EN,
    # Spanish-language broadcast regions
    "ES": _EPG_TLD_ES, "ESP": _EPG_TLD_ES, "MX": _EPG_TLD_ES, "MEX": _EPG_TLD_ES,
    "ARG": _EPG_TLD_ES, "CL": _EPG_TLD_ES, "CHL": _EPG_TLD_ES,
    "CO": _EPG_TLD_ES, "COL": _EPG_TLD_ES,
    # German-language broadcast regions (Switzerland is multilingual — also
    # compatible with the French/Italian TLD groups)
    "DE": _EPG_TLD_DE, "GER": _EPG_TLD_DE, "AT": _EPG_TLD_DE, "AUT": _EPG_TLD_DE,
    "CH": _EPG_TLD_DE | _EPG_TLD_FR | _EPG_TLD_IT,
    "SUI": _EPG_TLD_DE | _EPG_TLD_FR | _EPG_TLD_IT,
    # French-language broadcast regions (Belgium is multilingual — also
    # compatible with the Dutch TLD group)
    "FR": _EPG_TLD_FR, "FRA": _EPG_TLD_FR,
    "BE": _EPG_TLD_FR | _EPG_TLD_NL, "BEL": _EPG_TLD_FR | _EPG_TLD_NL,
    # Italian
    "IT": _EPG_TLD_IT, "ITA": _EPG_TLD_IT,
    # Dutch
    "NL": _EPG_TLD_NL, "NED": _EPG_TLD_NL,
}


def epg_tld_compatible(codes: "list[str | None] | tuple[str | None, ...]", epg_tld: str | None) -> bool:
    """Region-gate for EPG fuzzy matching (tiers 2/3 only — see epg_manager.py).

    Given a channel's detected region/prefix code(s) and an EPG feed's TLD
    (parsed from the trailing dot-suffix of its ``epg_id``), decide whether a
    fuzzy name match between them is a plausible broadcast pairing.

    Args:
        codes: The channel's ``detected_prefix`` / ``detected_region`` values
            (order doesn't matter; ``None``/empty entries are ignored).
        epg_tld: The EPG feed's parsed TLD (lowercase, no dot), or ``None``
            when the feed's epg_id had no parseable suffix.

    Returns:
        ``True`` whenever the gate can't make a confident call — no TLD, or
        neither code is in :data:`REGION_TLD_COMPATIBILITY` — so an
        unrecognized combination never blocks a match that would have
        succeeded before this feature existed (abstain). ``False`` only when
        at least one code IS mapped and the TLD is known but not in ANY
        mapped code's compatible set — an actual region mismatch.
    """
    if not epg_tld:
        return True  # abstain — no TLD to gate on
    known_sets = [
        REGION_TLD_COMPATIBILITY[c.strip().upper()]
        for c in codes
        if c and c.strip().upper() in REGION_TLD_COMPATIBILITY
    ]
    if not known_sets:
        return True  # abstain — neither code is in the compatibility map
    return any(epg_tld in s for s in known_sets)
