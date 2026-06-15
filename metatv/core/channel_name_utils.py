"""Shared channel name parsing — prefix extraction, region normalization, quality/year/audio detection."""
import re
from datetime import datetime
from typing import NamedTuple, Optional


class ParsedChannel(NamedTuple):
    """Result of parse_channel_name().

    Attributes:
        region:    Standardized region/platform code ("ARG", "US", "NF", "D+") or "".
        bare_name: Channel title with all suffixes/prefixes stripped.
        quality:   Quality tokens found (e.g. ["HD", "HEVC"]). First is highest tier.
        lang:      Explicit parenthetical lang/region qualifier differing from region, or "".
        year:      Year or year-range from trailing parentheses ("2020", "1993-2002"), or "".
        audio:     Audio presentation format ("Multi", "Dub", "Sub"), or "".
    """
    region: str
    bare_name: str
    quality: list[str]
    lang: str
    year: str
    audio: str


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
_COMPOUND_PREFIX_RE = re.compile(
    r'^(?:\[(?P<bracket>[A-Z][A-Z0-9]{0,7})\]\s*)?'
    r'(?:'
    r'(?P<qual_a>4K|8K|UHD|HD|FHD)-(?P<lang_a>[A-Z]{2,4})'
    r'|(?P<lang_b>[A-Z]{2,4})-(?P<qual_b>4K|8K|UHD|HD|FHD)'
    r'|(?P<lang_c>[A-Z]{2,4})\s+(?P<qual_c>4K|8K|UHD|HD|FHD)'
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
    # Dub variants (27+9+3+1)
    "DUB": "Dub", "DUBBED": "Dub", "DUBBED VERSION": "Dub",
    # Sub variants (92+38+2)
    "SUB": "Sub", "SUBTITLED": "Sub", "SUBTITULADO": "Sub",
    "SUBTITLE": "Sub",
}


# ── Region/platform lookup tables ────────────────────────────────────────────── #

# Platform codes — displayed with steel blue chip instead of grey
PLATFORM_CODES: frozenset[str] = frozenset({
    "NF", "D+", "HBO", "PRIME", "TUBI", "PARAMOUNT+", "APPLE", "PEACOCK",
    "ASTRO", "F1TV",
})

# Quality tokens that can appear as a detected_prefix (e.g. "HD - Movie" → prefix "HD").
# Used to populate detected_quality when the prefix itself is a quality marker.
QUALITY_TOKENS: frozenset[str] = frozenset({
    "4K", "8K", "UHD", "FHD", "HDR10+", "HDR", "HEVC", "H265", "H264",
    "HD", "SD", "HQ", "LQ", "RAW", "CAM",
})

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
    "PUNJABI": "PA",
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
    "FI": "Finland", "PL": "Poland", "RO": "Romania", "HU": "Hungary",
    "CZ": "Czech Republic", "GR": "Greece", "TR": "Turkey", "RU": "Russia",
    "UA": "Ukraine", "BR": "Brazil", "MX": "Mexico", "CA": "Canada",
    "AU": "Australia", "NZ": "New Zealand", "JP": "Japan", "KR": "South Korea",
    "CN": "China", "IN": "India", "AR": "Argentina", "CL": "Chile",
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
    "GU": "Gujarati", "PA": "Punjabi", "FA": "Farsi / Persian", "KU": "Kurdish",
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
    "PLAY+": "Play+", "A+": "A+", "NOWTV": "Now TV", "STH": "STH",
    # Additional regions (surfaced by Ninja, 2026-06)
    "MXC": "Mexico",  # surfaced in TREX + IPTV Ninja, measured 2,934 channels
    "ISR": "Israel",  # surfaced in TREX + IPTV Ninja, measured 588 channels
    "SOM": "Somalia",  # measured 2,812 channels
    # Content-type prefixes (Trex / provider-specific)
    "MV": "Music Videos", "SPT": "Sports",
}


def normalize_region_code(raw: str) -> str:
    """Normalize a raw prefix token to a canonical short display code."""
    upper = raw.strip().upper()
    if upper in _FULL_NAME_TO_CODE:
        return _FULL_NAME_TO_CODE[upper]
    if upper in _ALIAS_MAP:
        return _ALIAS_MAP[upper]
    return upper


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


def parse_channel_name(name: str) -> ParsedChannel:
    """Parse a raw channel name into structured components.

    Stripping order:
      1. Prefix (region/platform) from start
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

    bare = name.strip()
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

    # 2. Strip quality tokens from end (first pass)
    bare, quality = _strip_quality(bare)

    # 3. Strip audio bracket suffix [Multi-Sub], [Dub], [Sub] from end.
    # Also strips content-origin brackets like [UK], [US] (2-3 alpha letters,
    # not a quality token) — these are captured as lang in step 4.
    # Also strips quality-token brackets like [4K], [UHD], [HD].
    audio = ""
    # _bracket_origin already initialized above; suffix bracket overrides compound bracket
    bsm = _BRACKET_SUFFIX_RE.search(bare)
    if bsm:
        content = bsm.group(1).strip().upper()
        bc = _classify_bracket(content)
        if bc.kind == "audio":
            audio = bc.value
            bare = bare[: bsm.start()].strip()
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
        candidate = normalize_region_code(lm.group(1))
        if candidate != region:
            lang = candidate
        bare = bare[: lm.start()].strip()

    # 5. Strip year from end
    year = ""
    ym = _YEAR_RE.search(bare)
    if ym:
        year = ym.group(1) or ym.group(2)  # group 1 = paren form, group 2 = dash form
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
        # audio in step 6a is unusual and not expected; unknown stays in bare

    # 6b. Second quality pass — catches "Name HEVC (2024)" where HEVC was before year
    bare, quality2 = _strip_quality(bare)
    quality = quality2 + quality  # prepend (quality2 came from closer to the name)

    # 7. Append prefix quality (standalone "4K - Movie" or compound "4K-DE") at lowest
    # priority so name-suffix quality (step 2/6b) — which describes the actual encode —
    # wins when both are present (e.g. "[US] 4K-DE - Movie UHD" → quality[0] = "UHD").
    if _prefix_quality and _prefix_quality not in quality:
        quality = quality + [_prefix_quality]

    return ParsedChannel(region, bare, quality, lang, year, audio)
