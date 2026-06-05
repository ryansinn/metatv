"""Shared channel name parsing — prefix extraction, region normalization, quality/year/audio detection."""
import re
from typing import NamedTuple


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

# Quality tokens that start with a digit (4K, 8K) — excluded from _SEPARATOR_RE
# because that pattern requires [A-Z] as the first character.
_DIGIT_QUALITY_PREFIX_RE = re.compile(
    r'^(4K|8K)\s*(?:[★|]|-\s+)\s*(.+)$',
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
_QUALITY_SUFFIX_RE = re.compile(
    r'\s+\b(4K|8K|UHD|FHD|HDR10\+?|HDR|HEVC|H265|H264|HD|SD|HQ|LQ|RAW|LIVE|CAM)\b\s*$',
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

# Full language names in bracket suffixes → 2-letter codes → stored as detected_region.
# Covers dubbed/localized audio tracks: "EN ★ Movie [SPANISH]" → detected_region = "ES".
# Keys are uppercased; values are the canonical ISO-639-1 / REGION_FULL_NAMES code.
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
    # Sports leagues / brands
    "EPL": "English Premier League", "EFL": "English Football League",
    "NBA": "NBA Basketball", "NFL": "NFL Football", "MLB": "MLB Baseball",
    "NHL": "NHL Hockey", "UFC": "UFC / MMA", "WWE": "WWE Wrestling",
    "BEIN": "beIN Sports", "ESPN": "ESPN", "FOX": "Fox", "CNN": "CNN",
    "SKY": "Sky", "MBC": "MBC",
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

    # 1. Extract prefix
    m = _SEPARATOR_RE.match(bare)
    if m:
        region = normalize_region_code(m.group(1))
        bare = m.group(2).strip()
    else:
        bm = _BRACKET_PREFIX_RE.match(bare)
        if bm:
            region = normalize_region_code(bm.group(1))
            bare = bm.group(2).strip()
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
    _bracket_origin = ""  # e.g. "UK" from [UK] suffix
    bsm = _BRACKET_SUFFIX_RE.search(bare)
    if bsm:
        content = bsm.group(1).strip().upper()
        canonical = _AUDIO_NORM.get(content)
        if canonical:
            audio = canonical
            bare = bare[: bsm.start()].strip()
        elif (q_alias := _BRACKET_QUALITY_ALIASES.get(content)):
            # Compound quality bracket like [SD/CAM], [CAM-VERSION] — normalize to
            # canonical token. Must come before the QUALITY_TOKENS check so that
            # aliases that ARE in QUALITY_TOKENS (e.g. plain "CAM") also land here.
            quality.insert(0, q_alias)
            bare = bare[: bsm.start()].strip()
        elif content in QUALITY_TOKENS:
            # Quality-token bracket like [4K], [UHD], [HD] — treat same as bare suffix.
            # isalpha() fails for "4K" so this must come before the origin-bracket check.
            quality.insert(0, content)
            bare = bare[: bsm.start()].strip()
        elif (lang_code := _BRACKET_LANG_NORM.get(content)):
            # Full language name like [SPANISH], [HINDI] → 2-letter code in detected_region.
            _bracket_origin = lang_code
            bare = bare[: bsm.start()].strip()
        elif content in PLATFORM_CODES:
            # Platform bracket like [ASTRO], [F1TV] — longer than 3 chars or has digits,
            # so the isalpha()+len check below wouldn't catch them.
            _bracket_origin = content
            bare = bare[: bsm.start()].strip()
        elif (len(content) in (2, 3) and content.isalpha()
              and content not in QUALITY_TOKENS):
            # Content-origin bracket like [UK], [US], [DE] — same semantics as (UK)
            _bracket_origin = normalize_region_code(content)
            bare = bare[: bsm.start()].strip()
        # else: unrecognised bracket stays in bare name

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

    # 6a. Second bracket-quality pass — catches "[4K] (2025)" where year follows the
    #     quality bracket, so step 3's _BRACKET_SUFFIX_RE didn't see it at the end.
    bsm2 = _BRACKET_SUFFIX_RE.search(bare)
    if bsm2:
        content2 = bsm2.group(1).strip().upper()
        if (q_alias2 := _BRACKET_QUALITY_ALIASES.get(content2)):
            quality.insert(0, q_alias2)
            bare = bare[: bsm2.start()].strip()
        elif content2 in QUALITY_TOKENS:
            quality.insert(0, content2)
            bare = bare[: bsm2.start()].strip()
        elif (lang_code2 := _BRACKET_LANG_NORM.get(content2)):
            # Step 4 already ran so update lang directly (not just _bracket_origin)
            _bracket_origin = lang_code2
            lang = lang_code2
            bare = bare[: bsm2.start()].strip()
        elif content2 in PLATFORM_CODES:
            _bracket_origin = content2
            lang = content2
            bare = bare[: bsm2.start()].strip()

    # 6b. Second quality pass — catches "Name HEVC (2024)" where HEVC was before year
    bare, quality2 = _strip_quality(bare)
    quality = quality2 + quality  # prepend (quality2 came from closer to the name)

    # 7. Prepend digit-starting quality prefix (e.g. "4K") at highest priority
    if _prefix_quality:
        quality = [_prefix_quality] + quality

    return ParsedChannel(region, bare, quality, lang, year, audio)
