"""Region, country and language lookup tables and their resolvers — the single
source of truth for codes, split out of channel_name_utils (ledger F30).
"""

from __future__ import annotations

import re
from typing import Optional

from metatv.core.tag_confidence import CONF_DENOTED, CONF_STRONG_PRIOR, CONF_WEAK_PRIOR


# ── Region/platform lookup tables ────────────────────────────────────────────── #

# Platform codes — displayed with steel blue chip instead of grey. "A+" (Apple
# TV+, distinct from "APPLE" above — both observed in real provider data) was
# already in REGION_FULL_NAMES below but missing from this set, so it fell
# through to the plain geographic-region chip instead of the platform one
# (#257 owner report) — fixed in the lookup table, never at a render site.
PLATFORM_CODES: frozenset[str] = frozenset({
    "NF", "D+", "HBO", "PRIME", "TUBI", "PARAMOUNT+", "APPLE", "PEACOCK",
    "ASTRO", "F1TV", "A+",
    # Read off the provider's own categories, same pass as the region codes:
    #   OD   901  "NL| ODIDO ..."      — Odido, a Dutch telecom TV service
    #   YP   730  "ASIA | YUPP TV ..." — YuppTV, an Indian streaming platform
    # Both were rendering as geographic chips.
    "OD", "YP",
    # PORNBOX is a streaming platform, and without this it fell through to the
    # geographic chip — 30 channels in the owner's library rendered as though
    # "PORNBOX" were a country or language. Owner report. Same shape as the
    # "A+" gap recorded above: the fix is the lookup table, never a special
    # case at a render site.
    "PORNBOX",
})


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

# Mapping from language words found inside sub/dub annotations → canonical language
# name (the same names CODE_FACETS/REGION_FULL_NAMES use for the `language:` facet).
# Used by extract_audio_annotation() to convert tokens from (ENG DUB), (SPANISH
# ENG-SUB), (VOSTFR) etc. Key = UPPERCASE provider token; value = display name.
# SINGLE SOURCE OF TRUTH — do NOT define parallel dicts elsewhere.
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
    # ISO 639-2 codes mpv reports for a played stream's tracks (PLAYED-1).
    # "MAL" stays Malay above (provider usage), not ISO Malayalam.
    "BEN":           "Bengali",
    "CAT":           "Catalan",
    "CES":           "Czech",
    "DAN":           "Danish",
    "DEU":           "German",
    "DUT":           "Dutch",
    "ELL":           "Greek",
    "EST":           "Estonian",
    "FIL":           "Filipino",
    "FRA":           "French",
    "ICE":           "Icelandic",
    "ISL":           "Icelandic",
    "LAV":           "Latvian",
    "LIT":           "Lithuanian",
    "MAY":           "Malay",
    "MSA":           "Malay",
    "NLD":           "Dutch",
    "NOB":           "Norwegian",
    "PAN":           "Punjabi",
    "RON":           "Romanian",
    "RUM":           "Romanian",
    "SLK":           "Slovak",
    "SLO":           "Slovak",
    "SLV":           "Slovenian",
    "SPA":           "Spanish",
    "SQI":           "Albanian",
    "SRP":           "Serbian",
    "TGL":           "Tagalog",
    "URD":           "Urdu",
    "ZHO":           "Chinese",
}


# ISO 639-1 codes (TMDb's ``original_language``) → the same language names
# AUDIO_LANG_WORD_MAP uses. Kept apart from that map on purpose: it feeds
# provider-token parsing, where bare two-letter words like IS/HE would misfire.
# A stream track's region subtag ("es-MX", "pt-BR") → the dialect name the
# language facet already uses. Spain's Spanish (es-ES, castellano) is plain
# "Spanish"; Latin American Spanish is its own value. Unlisted pairs fall back
# to the base language.
LANGUAGE_REGION_VARIANTS: dict[tuple[str, str], str] = {
    ("es", "MX"): "Spanish (Mexico)",
    ("es", "419"): "Latin American Spanish",
    ("es", "AR"): "Latin American Spanish",
    ("es", "BO"): "Latin American Spanish",
    ("es", "CL"): "Latin American Spanish",
    ("es", "CO"): "Latin American Spanish",
    ("es", "CR"): "Latin American Spanish",
    ("es", "CU"): "Latin American Spanish",
    ("es", "DO"): "Latin American Spanish",
    ("es", "EC"): "Latin American Spanish",
    ("es", "GT"): "Latin American Spanish",
    ("es", "HN"): "Latin American Spanish",
    ("es", "NI"): "Latin American Spanish",
    ("es", "PA"): "Latin American Spanish",
    ("es", "PE"): "Latin American Spanish",
    ("es", "PR"): "Latin American Spanish",
    ("es", "PY"): "Latin American Spanish",
    ("es", "SV"): "Latin American Spanish",
    ("es", "US"): "Latin American Spanish",
    ("es", "UY"): "Latin American Spanish",
    ("es", "VE"): "Latin American Spanish",
    ("pt", "BR"): "Portuguese (Brazil)",
    ("pt", "PT"): "Portuguese (Portugal)",
}

ISO_639_1_LANGUAGE_NAMES: dict[str, str] = {
    "ar": "Arabic",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "ca": "Catalan",
    "cn": "Chinese",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ku": "Kurdish",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "ml": "Malayalam",
    "ms": "Malay",
    "nb": "Norwegian",
    "nl": "Dutch",
    "no": "Norwegian",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sq": "Albanian",
    "sr": "Serbian",
    "sv": "Swedish",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tl": "Tagalog",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "zh": "Chinese",
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
    "CUBA": "CU",     "PANAMA": "PA",
    # Africa — full names seen as channel prefixes
    "SENEGAL": "SEN",  "SOMALIA": "SOM",  "UGANDA": "UGA",
    "CAMEROON": "CM",  "GHANA": "GHA",    "KENYA": "KE",
    "ETHIOPIA": "ETH", "TOGO": "TGO",     "GABON": "GAB",
    "GAMBIA": "GM",    "TANZANIA": "TZ",  "MALI": "MLI",
    "GUINEA": "GIN",   "MOZAMBIQUE": "MZ",
    # Seen leading provider group labels ("KUWAIT +6H", "ESTONIA PPV"); ISO
    # codes, matching REGION_FULL_NAMES and the Global Exclusions lists.
    "UNITED STATES": "US", "UNITED KINGDOM": "UK", "NEW ZEALAND": "NZ",
    "KUWAIT": "KW", "QATAR": "QA", "SAUDI ARABIA": "SA", "BAHRAIN": "BH",
    "IRAQ": "IQ", "JORDAN": "JO", "LEBANON": "LB", "SYRIA": "SY", "YEMEN": "YE",
    "PALESTINE": "PS", "SUDAN": "SD", "ALGERIA": "DZ", "TUNISIA": "TN",
    "LIBYA": "LY", "UNITED ARAB EMIRATES": "AE", "IRAN": "IR",
    "ESTONIA": "EE", "LATVIA": "LV", "LITHUANIA": "LT", "BELARUS": "BY",
    "KAZAKHSTAN": "KZ", "UZBEKISTAN": "UZ", "ARMENIA": "AM", "AZERBAIJAN": "AZ",
    "GEORGIA": "GE", "CYPRUS": "CY", "MALTA": "MT", "BULGARIA": "BG",
    "SERBIA": "RS", "SLOVENIA": "SI", "BOSNIA": "BA", "MONTENEGRO": "ME",
    "ALBANIA": "AL", "NORTH MACEDONIA": "MK", "CZECH REPUBLIC": "CZ",
    "SLOVAKIA": "SK", "HONG KONG": "HK", "TAIWAN": "TW", "SINGAPORE": "SG",
    "MALAYSIA": "MY", "THAILAND": "TH", "VIETNAM": "VN", "PHILIPPINES": "PH",
    "INDONESIA": "ID", "SOUTH KOREA": "KR", "KOREA": "KR", "CAMBODIA": "KH",
    "NEPAL": "NP", "BANGLADESH": "BD", "SRI LANKA": "LK", "HAITI": "HT",
    "MADAGASCAR": "MG", "CAPE VERDE": "CV",
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
    # Indian-language prefixes as TREX spells them (2026-10-31): "|KA| Chef
    # Chidambara", "IN-KA - …" are Kannada; "|PJ| Ardaas", "IN-PU - Duja Rabb"
    # are Punjabi. (KA is Georgian in ISO 639-1; no source here uses it so.)
    "KA": "KN", "PJ": "PB", "PU": "PB",
    "QC": "QFR",   # Quebec ("QC - Karl Tremblay - Hommage Centre Bell") — Quebec French
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
    # ── Codes evidenced from the owner's library, 2026-08-29 ──────────────── #
    # 293/421 distinct prefixes had no name (~111,000 blank chips); each code
    # below was read off the PROVIDER'S OWN category label (a better source
    # than an ISO table — the provider chose the code), with its measured
    # count: AR 68,593 ("|AR| أفلام أجنبية" + "|AR-SUB|" — LANGUAGE, not
    # Argentina/ARG), EX 14,798 (ex-Yugoslavia, "|EXYU| …"), TM 7,036 / TG
    # 4,388 / TL 4,293 (Tamil/Telugu, "|IN| … MOVIES"), AF 3,719 (Africa, not
    # Afrikaans), SW 3,183 (93% Sweden "|SW|"/"EU| SVERIGE" vs 7% Swiss "CH|
    # SWITZERLAND" provider inconsistency — labelled Sweden, a known
    # imperfection), UR 1,894 (Urdu), SCAN 1,260, KD 969 (Kannada), IS 844
    # (Israel). DELIBERATELY NOT ADDED (evidence genuinely split): SO 1,688
    # ("South Hindi Dubbed" 1,344 vs a Somali brand 158) and MULTI 5,284
    # (a multi-audio marker, not a country — needs its own concept).
    "AR": "Arabic", "EX": "Ex-Yugoslavia", "TM": "Tamil", "TG": "Telugu",
    "TL": "Telugu", "AF": "Africa", "SW": "Sweden", "UR": "Urdu",
    "SCAN": "Scandinavia", "KD": "Kannada", "IS": "Israel",
    # Streaming platforms
    "NF": "Netflix", "D+": "Disney+", "HBO": "HBO Max", "PRIME": "Amazon Prime",
    "TUBI": "Tubi", "PEACOCK": "Peacock", "APPLE": "Apple TV+",
    "OD": "Odido", "YP": "YuppTV",
    # 2-letter ISO
    "US": "United States", "UK": "United Kingdom", "FR": "France",
    "DE": "Germany", "ES": "Spain", "IT": "Italy", "PT": "Portugal",
    "NL": "Netherlands", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    # DNK = ISO 3166-1 alpha-3 for Denmark ("DEN" below is IOC/FIFA); missing
    # it left "KANAL 4 [DNK] [HEVC]" with the bracket glued to the title.
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
    "CMR": "Cameroon",  "KEN": "Kenya",   "ETH": "Ethiopia",
    "SOM": "Somalia",   # measured 2,812 channels
    "TZA": "Tanzania",  "MLI": "Mali",    "GIN": "Guinea",   "GAB": "Gabon",
    "GMB": "Gambia",    "TGO": "Togo",
    # Additional LatAm 3-letter codes
    "DOM": "Dominican Republic",
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
    # AHL: "AHL-TEAM| TORONTO MARLIES [TOR]" (owner, 2026-10-31)
    "NHL": "NHL Hockey", "AHL": "AHL Hockey", "UFC": "UFC / MMA", "WWE": "WWE Wrestling",
    "BEIN": "beIN Sports", "ESPN": "ESPN", "FOX": "Fox", "CNN": "CNN",
    "SKY": "Sky", "MBC": "MBC",
    # Streaming platforms (surfaced by Ninja, 2026-06)
    "NEXT": "Next TV", "JOYN": "Joyn", "VIX": "Vix", "CITY": "City TV",
    "PLAY+": "Play+", "A+": "Apple+", "NOWTV": "Now TV", "STH": "STH",
    # Additional regions (surfaced by Ninja, 2026-06)
    "MXC": "Mexico",  # surfaced in TREX + IPTV Ninja, measured 2,934 channels
    "ISR": "Israel",  # surfaced in TREX + IPTV Ninja, measured 588 channels
    # Content-type prefixes (Trex / provider-specific)
    "MV": "Music Videos", "SPT": "Sports",
    # ISO codes that had no display name (they rendered as bare codes).
    "KW": "Kuwait", "QA": "Qatar", "IQ": "Iraq", "JO": "Jordan", "LB": "Lebanon",
    "PS": "Palestine", "SD": "Sudan", "SY": "Syria", "YE": "Yemen", "BH": "Bahrain",
    "AZ": "Azerbaijan", "KH": "Cambodia", "HK": "Hong Kong", "SG": "Singapore",
    "TW": "Taiwan", "HT": "Haiti", "MG": "Madagascar", "GE": "Georgia",
    "CY": "Cyprus", "NP": "Nepal", "LV": "Latvia", "LT": "Lithuania",
    "MY": "Malaysia", "MT": "Malta", "CV": "Cape Verde", "BY": "Belarus",
    "KZ": "Kazakhstan", "UZ": "Uzbekistan", "BA": "Bosnia and Herzegovina",
    "ME": "Montenegro", "MK": "North Macedonia", "AM": "Armenia",
    "BD": "Bangladesh", "LK": "Sri Lanka", "EE": "Estonia",

    # ── Named 2026-10-20: codes the language groups list with no name ───── #
    "BO": "Bolivia",
    "CR": "Costa Rica",
    "CU": "Cuba",
    "CUB": "Cuba",
    "CUBA": "Cuba",
    "DO": "Dominican Republic",
    "DOMINICAN": "Dominican Republic",
    "EC": "Ecuador",
    "GT": "Guatemala",
    "GTM": "Guatemala",
    "GUATEMALA": "Guatemala",
    "HN": "Honduras",
    "HND": "Honduras",
    "HONDURAS": "Honduras",
    "NI": "Nicaragua",
    "PY": "Paraguay",
    "SV": "El Salvador",
    "UY": "Uruguay",
    "VZ": "Venezuela",
    "PR": "Puerto Rico",
    "OM": "Oman",
    "ARM": "Armenia",
    "TWN": "Taiwan",
    "HKG": "Hong Kong",
    "NA": "Namibia",
    "NAMIBIA": "Namibia",
    "MC": "Monaco",
    "MQ": "Martinique",
    "GP": "Guadeloupe",
    "LI": "Liechtenstein",
    "SM": "San Marino",
    "VA": "Vatican City",
    "AFG": "Afghanistan",
    "ANG": "Angola",
    "ANGOLA": "Angola",
    "MOZ": "Mozambique",
    "CABO": "Cape Verde",
    "CAPEVERDE": "Cape Verde",
    "KG": "Kyrgyzstan",
    "TJ": "Tajikistan",
    "BIH": "Bosnia and Herzegovina",
    "SLO": "Slovenia",
    "GA": "Gabon",
    "CONGO": "Congo",
    "TOG": "Togo",
    "GAM": "Gambia",
    "ERI": "Eritrea",
    "ERITREA": "Eritrea",
    "ETR": "Eritrea",
    "DJIBOUTI": "Djibouti",
    "GUI": "Guinea",
    "RWANDA": "Rwanda",
    "ROWANDA": "Rwanda",
    "RWA": "Rwanda",
    "BENIN": "Benin",
    "BKF": "Burkina Faso",
    "CAF": "Central African Republic",
    "SRI": "Sri Lanka",
    "TEL": "Telugu",
    "TAM": "Tamil",
    "KAN": "Kannada",
    "MAL": "Malayalam",
    "PUN": "Punjabi",
    "GUJ": "Gujarati",
    "BAN": "Bengali",
    "BENGLAI": "Bengali",
    "ASSAM": "Assamese",
    "ARA": "Arabic",
    "KO": "Korean",
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

#: Codes that name a LANGUAGE, never a place (owner, 2026-10-20: "Hindi isn't
#: a region, it's a language"). The language itself comes from the language
#: groups (config.BASE_PREFIX_GROUPS: HI -> "Indian", UR -> "Urdu/Pakistani");
#: this list only stops the decomposer ALSO tagging the code as a region.
LANGUAGE_ONLY_CODES: frozenset[str] = frozenset({
    "HI", "TA", "TE", "TG", "TL", "ML", "KN", "KD", "MR", "PB", "GU", "BHO", "OR",
    "BN", "UR", "KU",
    "TEL", "TAM", "KAN", "MAL", "PUN", "GUJ", "BAN", "BENGLAI", "ASSAM", "ARA", "KO",
})


def code_family(codes) -> set[str]:
    """Every code naming the SAME place/language as any of *codes*.

    A country has several codes in the wild — Denmark is DK, DNK and DEN,
    Sweden SE, SW and SWE — and an exclusion written as one must hide the
    others. Family = codes sharing one REGION_FULL_NAMES name; an unnamed
    code is its own family.
    """
    out = {str(c).upper() for c in codes if c}
    names = {REGION_FULL_NAMES[c] for c in out if c in REGION_FULL_NAMES}
    if names:
        out |= {c for c, n in REGION_FULL_NAMES.items() if n in names}
    return out


def normalize_region_code(raw: str) -> str:
    """Normalize a raw prefix token to a canonical short display code."""
    upper = raw.strip().upper()
    if upper in _FULL_NAME_TO_CODE:
        return _FULL_NAME_TO_CODE[upper]
    if upper in _ALIAS_MAP:
        return _ALIAS_MAP[upper]
    return upper


_LEADING_COUNTRY_RE = re.compile(
    r"^(" + "|".join(sorted(map(re.escape, _FULL_NAME_TO_CODE), key=len, reverse=True))
    + r")\b\s*(.*)$", re.IGNORECASE)


def leading_country(label: str) -> tuple[str, str] | None:
    """``(code, rest)`` when *label* STARTS with a country name — "SWEDEN SOCCER
    PPV" → ``("SWE", "SOCCER PPV")`` — via the same table
    :func:`normalize_region_code` reads; None otherwise. Leading only, so a
    country word inside a title is never read as a region."""
    m = _LEADING_COUNTRY_RE.match((label or "").strip())
    return (_FULL_NAME_TO_CODE[m.group(1).upper()], m.group(2).strip()) if m else None


def split_category_prefix(category: str) -> tuple[Optional[str], Optional[str]]:
    """Split a provider ``category`` string's leading region-code token.

    A distinct provider convention from :func:`parse_category_marker`'s
    ``"|XX| REST"`` (LEADING pipe, e.g. ``"|EN| ANIME"``): this shape has NO
    leading pipe — ``"AR| BEIN SPORTS NX"``, ``"US| FLO NETWORK"`` — the code
    sits at the very start, followed by one pipe. ``update_detected_prefixes()``
    uses this as the category-fallback source for a channel whose NAME yields
    no prefix/region of its own (fill-empty-only: the name-derived value
    always wins — #582).

    The leading token only becomes ``code`` when it is a KNOWN region code —
    validated by :func:`normalize_region_code` + membership in
    :data:`REGION_FULL_NAMES` — so a quality/format token before a pipe
    (``"4K| UHD Channels"``, ``"RAW| Feed"``) is never mistaken for a region;
    it falls through to ``(None, rest)`` instead.

    Args:
        category: The raw provider ``category`` string (may be ``None``/empty).

    Returns:
        ``(code, rest)`` — ``code`` is the normalized region code, or
        ``None`` when there is no pipe or the leading token isn't a known
        region; ``rest`` is the trimmed remainder after ``"CODE|"`` (or the
        whole collapsed string when there was no pipe), or ``None`` when
        nothing is left.
    """
    if not category:
        return None, None
    collapsed = " ".join(category.split())
    if not collapsed:
        return None, None
    if "|" not in collapsed:
        return None, collapsed
    code_raw, _, rest_raw = collapsed.partition("|")
    code_raw = code_raw.strip()
    rest = rest_raw.strip() or None
    if not code_raw or " " in code_raw:
        return None, rest if rest is not None else collapsed
    code = normalize_region_code(code_raw)
    if code in REGION_FULL_NAMES:
        return code, rest
    return None, rest
