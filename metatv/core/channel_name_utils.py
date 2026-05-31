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

# ── Suffix patterns ─────────────────────────────────────────────────────────── #

# Quality tokens at end of bare name (including codecs)
_QUALITY_SUFFIX_RE = re.compile(
    r'\s+\b(4K|8K|UHD|FHD|HDR10\+?|HDR|HEVC|H265|H264|HD|SD|HQ|LQ|RAW|LIVE)\b\s*$',
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
})

_FULL_NAME_TO_CODE: dict[str, str] = {
    "ARGENTINA": "ARG", "AUSTRALIA": "AUS", "AUSTRIA": "AUT",
    "BELGIUM": "BEL", "BOLIVIA": "BOL", "BRAZIL": "BRA",
    "CANADA": "CAN", "CHILE": "CHL", "COLOMBIA": "COL",
    "CROATIA": "HRV", "DENMARK": "DEN", "ECUADOR": "ECU",
    "FINLAND": "FIN", "FRANCE": "FRA", "GERMANY": "GER",
    "GREECE": "GRE", "HUNGARY": "HUN", "IRELAND": "IRL",
    "ITALY": "ITA", "MEXICO": "MEX", "NETHERLANDS": "NED",
    "NORWAY": "NOR", "PARAGUAY": "PAR", "PERU": "PER",
    "POLAND": "POL", "PORTUGAL": "POR", "ROMANIA": "ROU",
    "RUSSIA": "RUS", "SPAIN": "ESP", "SWEDEN": "SWE",
    "SWITZERLAND": "SUI", "TURKEY": "TUR", "UKRAINE": "UKR",
    "URUGUAY": "URY", "VENEZUELA": "VEN", "JAPAN": "JPN",
    "CHINA": "CHN", "INDIA": "IND", "PAKISTAN": "PAK",
    "ISRAEL": "ISR", "MOROCCO": "MAR", "NIGERIA": "NGA",
    "EGYPT": "EGY", "SOUTH AFRICA": "ZAF",
}

_ALIAS_MAP: dict[str, str] = {
    "GB": "UK",
    "LATIN": "LAT", "LATAM": "LAT", "LATINAM": "LAT",
    "LATINAMERICA": "LAT", "LATIN AMERICA": "LAT",
    "ENG": "UK",
    "USA": "US",
    "BRASIL": "BRA",
    "ESPANA": "ESP",
    # Streaming platforms
    "NETFLIX": "NF",
    "DISNEY+": "D+", "DISNEY": "D+", "DPLUS": "D+", "DISNEYPLUS": "D+",
    "AMAZON": "PRIME", "AMAZONPRIME": "PRIME",
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
    # Regional groupings
    "LAT": "Latin America", "LATS": "Latin America (Spanish)",
    "AL": "Albania", "ALB": "Albania",
    # Language codes (used as channel prefixes on some providers)
    "EN": "English", "HI": "Hindi", "TA": "Tamil", "TE": "Telugu",
    "ML": "Malayalam", "KN": "Kannada", "BN": "Bengali", "MR": "Marathi",
    "GU": "Gujarati", "PA": "Punjabi", "FA": "Farsi / Persian", "KU": "Kurdish",
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

    # 2. Strip quality tokens from end (first pass)
    bare, quality = _strip_quality(bare)

    # 3. Strip audio bracket suffix [Multi-Sub], [Dub], [Sub] from end
    audio = ""
    bsm = _BRACKET_SUFFIX_RE.search(bare)
    if bsm:
        content = bsm.group(1).strip().upper()
        canonical = _AUDIO_NORM.get(content)
        if canonical:
            audio = canonical
            bare = bare[: bsm.start()].strip()

    # 4. Strip explicit lang/region qualifier from end: (EN), (JP)
    lang = ""
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

    # 6. Second quality pass — catches "Name HEVC (2024)" where HEVC was before year
    bare, quality2 = _strip_quality(bare)
    quality = quality2 + quality  # prepend (quality2 came from closer to the name)

    return ParsedChannel(region, bare, quality, lang, year, audio)
