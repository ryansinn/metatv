"""Configuration management"""

from pathlib import Path
from typing import Optional
import shutil
import tempfile
import yaml
from pydantic import BaseModel, Field
from loguru import logger


# ---------------------------------------------------------------------------
# Base lookup tables — shipped with the app, never written to config.yaml.
# Users extend these via user_prefix_overrides / user_quality_overrides /
# user_platform_overrides (prefix/code → group name).
# Providers can add per-provider overrides via provider_prefix_overrides.
# ---------------------------------------------------------------------------

BASE_PREFIX_GROUPS: dict[str, list[str]] = {
    # Content-category group (not a locale) — adult-content prefixes grouped together
    # instead of each surfacing separately under "Other". Note: bare "X" is ambiguous
    # in general but confirmed adult in this library; remove via user_prefix_overrides
    # if it ever mis-groups a non-adult "X …" channel.
    "Adult":            ["X", "XXX", "ADULT"],
    "Albanian":         ["AL", "ALB"],
    # ── Arabic locale sub-groups ──────────────────────────────────────────────
    # "Arabic" = all Arabic-speaking regions (aggregate).
    "Arabic":               ["AR", "AE", "SA", "EG", "MA", "TN", "DZ", "LB", "JO", "IQ",
                              "KW", "QA", "BH", "OM", "YE", "PS", "SY", "LY", "SD",
                              "ARA", "TAR", "OMAR",
                              "CLA"],  # CLA confirmed Arabic-language content (drama/series)
    "Arabic (Gulf)":        ["AE", "SA", "KW", "QA", "BH", "OM"],  # Gulf states
    "Arabic (Levant)":      ["LB", "SY", "JO", "PS", "IQ"],        # Levant / Mesopotamia
    "Arabic (North Africa)": ["EG", "MA", "TN", "DZ", "LY", "SD"], # North Africa / Maghreb
    # ── end Arabic ────────────────────────────────────────────────────────────
    "Armenian":         ["AM", "ARM"],
    "Azerbaijani":      ["AZ"],
    "Bulgarian":        ["BG"],
    "Chinese":          ["CN", "HK", "TW", "SG", "CHN", "TWN", "HKG"],
    "Czech":            ["CZ"],
    "Danish":           ["DK", "DNK"],
    "Dutch":            ["NL", "BE", "OD"],   # OD = Dutch provider (NPO1/2/3, Viaplay NL)
    # ── English locale sub-groups ─────────────────────────────────────────────
    # "English" = all English content (backward-compatible aggregate).
    # Sub-groups allow narrowing to a specific English-speaking region.
    "English":            ["EN", "UK", "US", "AU", "CA", "NZ", "IE", "GB", "ENG", "ENGLISH",
                           "ZA", "ZM", "ZW", "NG", "AUS", "NA"],  # BS = Serbian/Croatian (Bosnia), not English — moved out
    "English (North America)":  ["US", "CA"],           # US + Canada only
    "English (UK / Ireland)":   ["UK", "IE", "GB"],     # British & Irish
    "English (Oceania)":        ["AU", "AUS", "NZ"],    # Australian / NZ
    "English (Africa)":         ["ZA", "ZW", "ZM", "NG", "NA"],  # South/East African English
    # ── end English ───────────────────────────────────────────────────────────
    "Filipino":         ["PH"],
    "Finnish":          ["FI", "FIN"],
    # ── French locale sub-groups ──────────────────────────────────────────────
    # "French" = all French content (aggregate). Sub-groups for regional preference.
    "French":                   ["FR", "BE", "CH", "CA", "LU", "MC",
                                  "QFR", "MQ", "GP", "MG", "HT"],
    "French (Europe)":          ["FR", "BE", "CH", "LU", "MC"],  # European French
    "French (Canada)":          ["CA", "QFR"],                    # Quebec / Canadian French
    "French (Africa/Caribbean)": ["MG", "HT", "MQ", "GP", "CI", "SN", "CM"],  # Francophone Africa + Caribbean
    # ── end French ────────────────────────────────────────────────────────────
    "Georgian":         ["GE"],
    "German":           ["DE", "AT", "CH", "LI", "SW"],   # SW = Swiss channels (SWISS 1, 3+, 4+)
    "Greek":            ["GR", "CY"],
    "Hebrew":           ["IL", "ISR", "IS"],  # IS = Israeli provider prefix (YES ONE, YES 12 etc.)
    "Hungarian":        ["HU"],
    "Indian":           ["IN", "HI", "TA", "TE", "ML", "KN", "BN", "MR", "GU",
                         # NB: Punjabi = "PB" (below).  "PA" is Panama (Spanish) — NOT Punjabi.
                         "OR", "BHO",                        # Odia, Bhojpuri (normalized codes)
                         "YP",                               # YP confirmed Indian news channels (AAJTAK, Republic Bharat, India TV)
                         # Full language names & alternate abbreviations confirmed from channel data:
                         "HINDI", "IND",
                         "TEL", "TELUGU", "TELEGU",         # Telugu (TELEGU = common typo)
                         "TAM", "TAMIL",                     # Tamil
                         "KAN", "KANNADA",                   # Kannada
                         "MAL", "MALAYALAM",                 # Malayalam
                         "MARATHI",                          # Marathi
                         "PUN", "PUNJABI", "PB",             # Punjabi
                         "GUJ", "GUJARATI",                  # Gujarati
                         "BAN", "BENGALI", "BANGALI", "BENGLAI",  # Bengali (BENGLAI = typo)
                         "ODIA",                             # Odia
                         "BHOJPURI",                         # Bhojpuri
                         "ASSAM",                            # Assamese
                         "SRI",                              # Sri Lankan (Tamil/Sinhala)
                         "NP",                               # Nepali
                         # Regional sub-prefixes confirmed from channel names (South Indian content):
                         "STH", "TG", "TL", "BL", "KD"],
    "Indonesian":       ["ID"],
    "Italian":          ["IT", "CH", "SM", "VA"],
    "Japanese":         ["JP"],
    "Cambodian":        ["KH"],          # KH confirmed: Cambodia TV HD, BTV News
    "Korean":           ["KR", "KO"],   # KO confirmed as Korean (dramas: My Holo Love, etc.)
    "Kurdish":          ["KU"],
    "Latvian":          ["LV"],
    "Lithuanian":       ["LT"],
    "Malay":            ["MY"],
    "Norwegian":        ["NO", "NOR"],
    "Persian/Iranian":  ["IR", "FA", "PER", "AFG"],  # PER = Persian content; AFG = Dari/Afghan (BBC Farsi, Afghan TV)
    "Polish":           ["PL"],
    # ── Portuguese locale sub-groups ─────────────────────────────────────────
    "Portuguese":            ["PT", "BR", "BRA", "CV",
                               "ANG", "ANGOLA", "MOZ", "MOZAMBIQUE", "CABO", "CAPEVERDE",
                               "VO"],  # VO confirmed Portuguese (RTP 1/2/3 — Portuguese public broadcaster)
    "Portuguese (Portugal)": ["PT", "POR"],             # European Portuguese
    "Portuguese (Brazil)":   ["BR", "BRA"],             # Brazilian Portuguese
    "Portuguese (Africa)":   ["MZ", "MOZ", "AO", "CV", "ANGOLA", "MOZAMBIQUE", "CABO", "CAPEVERDE"],
    # ── end Portuguese ────────────────────────────────────────────────────────
    "Romanian":         ["RO"],
    "Russian":          ["RU", "BY", "KZ", "KG", "TJ", "TM", "UZ", "RUS"],
    "Serbian/Croatian": ["RS", "HR", "BA", "ME", "SI", "MK", "SR",
                         "EXYU", "EX",   # EX confirmed Ex-Yugoslav content (Croatian sinhronizirano dubs + EXYU productions)
                         "BIH", "BS", "SLO", "SLN", "MNG"],  # MNG=Montenegro (RTCG SAT confirmed)
    "Slovak":           ["SK"],
    # ── Spanish locale sub-groups ─────────────────────────────────────────────
    # "Spanish" = all Spanish-speaking regions (aggregate).
    "Spanish":          ["ES", "MX", "CO", "CL", "PE", "VE", "EC", "GT", "CU", "BO", "DO", "HN", "PY", "SV", "NI", "CR", "PA", "UY",  # AR = Arabic (Argentina is ARG); PA = Panama (kept — Spanish)
                         "ARG", "COL", "VEN", "URY", "DOM",
                         "LAT", "LATIN", "MXC",
                         "URUGUAY", "COLOMBIA", "CHILE", "CHL",
                         "PERU", "DOMINICAN", "RDOM",
                         "VENEZUELA", "VZ",
                         "HONDURAS", "GUATEMALA", "ECUADOR", "PANAMA", "CUBA",
                         "PR",
                         "VIX"],   # TelevisaUnivision streaming — Spanish-language Mexican/Latin content
    "Spanish (Spain)":  ["ES", "ESP"],                                  # Spain
    "Spanish (Mexico)": ["MX", "MEX", "MXC", "VIX"],                  # Mexico — VIX is Televisa/TelevisaUnivision
    "Spanish (South America)": ["ARG", "BO", "CL", "CHL", "CO", "COL",  # AR = Arabic — use ARG for Argentina
                                 "EC", "PE", "PY", "PAR", "UY", "URY", "VE", "VEN",
                                 "ARGENTINA", "COLOMBIA", "CHILE", "URUGUAY", "VENEZUELA", "VZ"],
    "Spanish (Central America)": ["GT", "GTM", "SV", "HN", "HND", "NI", "CR", "PA",
                                   "GUATEMALA", "HONDURAS", "PANAMA",
                                   "DO", "DOM", "CU", "CUB", "PR", "LAT", "LATIN",
                                   "DOMINICAN", "RDOM", "CUBA"],
    # ── end Spanish ───────────────────────────────────────────────────────────
    "Swahili":          ["TZ", "TZA"],   # SW reassigned to German (confirmed Swiss channels)
    "Swedish":          ["SE", "SWE"],
    "Thai":             ["TH"],
    "Turkish":          ["TR", "CY"],
    "Ukrainian":        ["UA"],
    "Urdu/Pakistani":   ["PK", "UR"],
    "Vietnamese":       ["VN"],
    "Maltese":          ["MT"],   # MT confirmed: TVM 1, TVM NEWS+
    # New groups from provider data:
    "African":          ["AF", "AFR",
                         # Normalized short codes (produced after prefix normalization):
                         "NG", "NGA",  "GH", "GHA",  "SN", "SEN",
                         "UG", "UGA",  "CM", "CMR",  "KE", "KEN",
                         "ET", "ETH",  "SO", "SOM",  "TGO",
                         "GM", "GMB",  "GA", "GAB",  "TZ", "TZA",  "MLI",
                         "GN", "GIN",  "MZ", "MOZ",
                         # Full names kept for backward compatibility:
                         "NIG", "NIGERIA", "GHANA", "SENEGAL",
                         "CAMEROON", "KENYA", "UGANDA", "MALI",
                         "CONGO", "TOG", "TOGO", "GAM", "GAMBIA", "GABON",
                         "ERI", "ERITREA", "ETHO", "ETHIOPIA", "ETR",
                         "SOMALIA", "DJIBOUTI",
                         "NAMIBIA", "TANZANIA",
                         "GUINEA", "GUINEE", "GUI",
                         "RWANDA", "ROWANDA", "RWA",
                         "BENIN", "BKF", "CAF",
                         "GENERAL"],  # GENERAL confirmed as African content (AFRICA TV1/2/3)
}

BASE_QUALITY_GROUPS: dict[str, list[str]] = {
    "RAW":             ["RAW"],          # Uncompressed/minimally processed — highest tier, often 4K+
    "4K / UHD":        ["4K", "UHD", "8K", "2160P", "PL4K"],
    "HD":              ["HD", "FHD", "1080P", "720P", "HDR", "HDR10", "HDR10+"],
    "HQ":              ["HQ"],
    "SD":              ["SD", "480P", "360P"],
    "LQ":              ["LQ", "LD"],
    "CAM / Pre-release": ["CAM", "HDTS", "CAMRIP", "TSCAM"],
}

BASE_PLATFORM_GROUPS: dict[str, list[str]] = {
    # ── Individual streaming brands (each selectable independently) ────────────
    # EAR: Arabic-subtitled foreign content library — foreign films/series (English,
    # French, Brazilian etc.) with Arabic subtitles added. NOT Arabic-language content.
    # Value target: Arabic-speaking audience. Also appears in Multi/Subtitle group.
    "EAR":           ["EAR"],
    "Netflix":       ["NF", "NETFLIX"],
    "Amazon Prime":  ["PRIME", "AMAZON"],
    "Disney+":       ["D+", "DISNEY+", "DISNEY"],
    "VIX":           ["VIX"],           # TelevisaUnivision streaming — predominantly Mexican/Latin content
    "Joyn":          ["JOYN"],          # German streaming (ARD/3sat confirmed)
    "Tubi":          ["TUBI"],
    "WOW":           ["WOW"],           # German Sky streaming (Sky Cinema confirmed)
    "GOLD":          ["GOLD"],          # BBC Nordic DK etc. confirmed
    "VIP":           ["VIP"],           # French 4K tier (TF1 4K, M6 4K, France 2 4K confirmed)
    "Shahid":        ["SHAHID"],        # Arabic/Middle East streaming confirmed
    # Less common full-name variants (low channel counts, catch-all):
    "Apple TV+":     ["A+", "APPLE", "APPLETV"],  # A+ confirmed Apple TV+ content
    "SC":            ["SC"],    # SC — mixed multi-language VOD library (English/Turkish/Indian; origin TBD)
    "Other Streaming": ["HBO", "HULU", "PEACOCK", "PARAMOUNT", "PARAMOUNT+",
                        "PLAY", "PLAY+"],  # PLAY/PLAY+ = Belgian streaming (PLAY ACTIE, PLAY CRIME etc.)
    # ── Broadcast / Pay TV ────────────────────────────────────────────────────
    "Sports":     ["ESPN", "DAZN", "PPV", "NBA", "NFL", "MLB", "NHL", "UFC", "WWE", "BEIN", "SKY SPORTS",
                   "SPT", "SPORT", "SPORTS",         # generic sports prefixes
                   "SP",                              # SP confirmed: beIN Sports 1/2/3
                   "UEFA", "F1",                      # competitions
                   "EPL", "EFL", "SPFL",              # UK football leagues
                   "MLS", "LIGA", "CAF",              # other leagues
                   "WC", "CHAMP", "L1", "L2", "L21", "FL",  # cups/leagues
                   "LIVE", "NEXT", "ENDED",           # live/upcoming/ended PPV event status tokens
                   "DIRTVISION",                      # motorsports streaming
                   "TRILLERTV"],                      # combat sports/entertainment
    "Pay TV":     ["DSTV",    # MultiChoice/DStv Sub-Saharan Africa (confirmed: SABC, eNCA, Cape Town TV, SuperSport, MOJALOVE — South African satellite pay-TV platform)
                   "OSN",     # OSN Middle East (confirmed: Movies Premier, Hollywood)
                   "SKY",     # Sky UK/DE/IT (confirmed pay TV provider)
                   "STC",     # Saudi Telecom Company TV (confirmed: STC TV Sports)
                   "MYHD",    # MyHD pay TV
                   "GOBX",    # GOtv Box
                   "DIGI"],   # Digi (Romanian/Hungarian telecom TV)
    "News":       ["CNN", "BBC", "FOX", "NBC", "CBS", "ABC", "MSNBC", "SKY NEWS", "AL JAZEERA", "FRANCE24"],
    "Kids":       ["KIDS", "CARTOON", "DISNEY JUNIOR", "NICK", "NICKELODEON", "PBS KIDS",
                   "ENF"],  # ENF confirmed kids/children (Baby TV, Disney Channel, Disney Junior — French "enfants")
    "Music":      ["MU", "MUSIC"],  # MU = music channels (4 MUSIC, BOX HITS confirmed); MUSIC = Trace Africa etc.
    "Religious":  ["RELIGIOUS", "QURAN"],  # RELIGIOUS confirmed (Aastha TV etc.); QURAN = Arabic religious
    "24/7":       ["24/7"],   # 24/7 loop channels (classic TV reruns confirmed)
}

BASE_REGIONAL_GROUPS: dict[str, list[str]] = {
    # ── Americas ──────────────────────────────────────────────────────────────
    "North America": [
        "US", "CA",
        "MX", "MEX",    # Mexico: geographically North America, culturally LatAm
    ],
    "Caribbean": [
        "CU", "CUB",    # Cuba
        "DO", "DOM",    # Dominican Republic
        "JM",           # Jamaica
        "HT",           # Haiti
        "TT",           # Trinidad & Tobago
        "BB",           # Barbados
        "PR",           # Puerto Rico
        "LC", "GD", "VC", "AG", "DM", "KN",  # Lesser Antilles
        "CAR",          # CAR confirmed Caribbean aggregator (T&T radio, Caribbean TV)
    ],
    "Central America": [
        "MX", "MEX",    # Mexico (also in North America)
        "GT", "GTM",    # Guatemala
        "SV",           # El Salvador
        "HN", "HND",    # Honduras
        "NI",           # Nicaragua
        "CR",           # Costa Rica
        "PA",           # Panama (Spanish) — Punjabi is now "PB"
    ],
    "South America": [
        "ARG",          # Argentina (AR = Arabic, not Argentina)
        "BO",           # Bolivia
        "BR", "BRA",    # Brazil
        "CL", "CHL",    # Chile
        "CO", "COL",    # Colombia
        "EC", "ECU",    # Ecuador
        "PY", "PAR",    # Paraguay
        "PE",           # Peru
        "UY", "URY",    # Uruguay
        "VE", "VEN",    # Venezuela
        "GY",           # Guyana
        "SR",           # Suriname
    ],
    "Latin America": [
        # Aggregate: South America + Central America + Caribbean (excl. Brazil for language purity)
        # Use this when you want all Spanish/Portuguese-speaking Americas at once.
        "ARG", "BO", "BR", "BRA", "CL", "CHL", "CO", "COL",   # AR = Arabic — use ARG for Argentina
        "EC", "ECU", "PY", "PAR", "PE", "UY", "URY", "VE", "VEN",
        "MX", "MEX", "GT", "GTM", "SV", "HN", "HND", "NI", "CR",
        "PA",   # Panama
        "CU", "CUB", "DO", "DOM", "PR",
        "LAT", "LATIN", "VIX",  # regional/streaming codes
    ],

    # ── Europe ────────────────────────────────────────────────────────────────
    "Western Europe": [
        "UK", "EN",     # United Kingdom / English
        "IE", "IRL",    # Ireland
        "FR", "FRA",    # France
        "DE", "GER",    # Germany
        "AT", "AUT",    # Austria
        "CH", "SUI",    # Switzerland
        "NL", "NED",    # Netherlands
        "BE", "BEL",    # Belgium
        "LU",           # Luxembourg
        "ES", "ESP",    # Spain
        "PT", "POR",    # Portugal
        "IT", "ITA",    # Italy
        "SM", "VA",     # San Marino, Vatican
        "MC",           # Monaco
        "DK", "DNK",    # Denmark
        "SE", "SWE",    # Sweden
        "NO", "NOR",    # Norway
        "FI", "FIN",    # Finland
        "IS",           # Iceland
        "MT",           # Malta
    ],
    "Eastern Europe": [
        "PL", "POL",    # Poland
        "CZ",           # Czech Republic
        "SK",           # Slovakia
        "HU", "HUN",    # Hungary
        "RO", "ROU",    # Romania
        "BG",           # Bulgaria
        "HR", "HRV",    # Croatia
        "RS",           # Serbia
        "SI",           # Slovenia
        "BA",           # Bosnia
        "ME",           # Montenegro
        "MK",           # North Macedonia
        "AL", "ALB",    # Albania
        "GR", "GRE",    # Greece
        "CY",           # Cyprus
        "RU", "RUS",    # Russia
        "UA", "UKR",    # Ukraine
        "BY",           # Belarus
        "MD",           # Moldova
        "EE",           # Estonia
        "LV",           # Latvia
        "LT",           # Lithuania
        "EXYU",         # Ex-Yugoslavia aggregate
    ],
    "Europe": [
        # Full Europe aggregate (Western + Eastern — use when language doesn't matter)
        "UK", "EN", "IE", "IRL", "FR", "FRA", "DE", "GER", "AT", "AUT",
        "CH", "SUI", "NL", "NED", "BE", "BEL", "LU", "ES", "ESP",
        "PT", "POR", "IT", "ITA", "SM", "VA", "MC", "DK", "DNK",
        "SE", "SWE", "NO", "NOR", "FI", "FIN", "IS", "MT",
        "PL", "POL", "CZ", "SK", "HU", "HUN", "RO", "ROU", "BG",
        "HR", "HRV", "RS", "SI", "BA", "ME", "MK", "AL", "ALB",
        "GR", "GRE", "CY", "RU", "RUS", "UA", "UKR", "BY", "MD",
        "EE", "LV", "LT", "EXYU",
        "TR", "TUR",    # Turkey (geographically spans Europe/Asia)
    ],

    # ── Africa ────────────────────────────────────────────────────────────────
    "North Africa": [
        "EG", "EGY",    # Egypt
        "MA", "MAR",    # Morocco
        "TN",           # Tunisia
        "DZ",           # Algeria
        "LY",           # Libya
        "SD",           # Sudan
    ],
    "Sub-Saharan Africa": [
        "NG", "NGA",    # Nigeria
        "GH", "GHA",    # Ghana
        "SN", "SEN",    # Senegal
        "UG", "UGA",    # Uganda
        "CM", "CMR",    # Cameroon
        "KE", "KEN",    # Kenya
        "ET", "ETH",    # Ethiopia
        "SO", "SOM",    # Somalia
        "TGO",          # Togo (TG reserved for South Indian sub-prefix)
        "GA", "GAB",    # Gabon
        "GM", "GMB",    # Gambia
        "TZ", "TZA",    # Tanzania
        "MLI",          # Mali
        "GN", "GIN",    # Guinea
        "MZ", "MOZ",    # Mozambique
        "ZA", "ZAF",    # South Africa
        "ZW",           # Zimbabwe
        "ZM",           # Zambia
        "AO",           # Angola
        "CI",           # Ivory Coast
        "NA",           # Namibia
        "BW",           # Botswana
        "RW", "RWA",    # Rwanda
        "BJ",           # Benin
        "AF", "AFR",    # Africa generic prefixes
        "DSTV",         # DStv (major African pay TV)
        "GENERAL",      # confirmed African content (AFRICA TV1/2/3)
        "TD", "TCD",    # Chad (TCHAD in French — normalized to TCD)
    ],
    "Africa": [
        # Aggregate: North + Sub-Saharan
        "EG", "EGY", "MA", "MAR", "TN", "DZ", "LY", "SD",
        "NG", "NGA", "GH", "GHA", "SN", "SEN", "UG", "UGA",
        "CM", "CMR", "KE", "KEN", "ET", "ETH", "SO", "SOM",
        "TGO", "GA", "GAB", "GM", "GMB", "TZ", "TZA", "MLI",
        "GN", "GIN", "MZ", "MOZ", "ZA", "ZAF", "ZW", "ZM",
        "AO", "CI", "NA", "BW", "RW", "RWA", "BJ",
        "AF", "AFR", "DSTV", "GENERAL",
        "TD", "TCD",    # Chad
    ],

    # ── Middle East ───────────────────────────────────────────────────────────
    "Middle East": [
        "AE",           # UAE
        "SA",           # Saudi Arabia
        "IQ",           # Iraq
        "SY",           # Syria
        "JO",           # Jordan
        "KW",           # Kuwait
        "QA",           # Qatar
        "BH",           # Bahrain
        "OM",           # Oman
        "YE",           # Yemen
        "PS",           # Palestine
        "LB",           # Lebanon
        "IR",           # Iran
        "IL", "ISR",    # Israel
        # North Africa often grouped with Middle East:
        "EG", "EGY", "MA", "MAR", "TN", "DZ", "LY",
        # Arabic language codes (common Middle East prefixes):
        "AR", "ARA",
        # Streaming services targeting the region:
        "SHAHID", "OSN",
    ],

    # ── Asia ──────────────────────────────────────────────────────────────────
    "East Asia": [
        "JP", "JPN",    # Japan
        "KR", "KO",     # South Korea
        "CN", "CHN",    # China
        "TW", "TWN",    # Taiwan
        "HK", "HKG",    # Hong Kong
        "MO",           # Macau
    ],
    "Southeast Asia": [
        "TH",           # Thailand
        "VN",           # Vietnam
        "ID",           # Indonesia
        "PH",           # Philippines
        "MY",           # Malaysia
        "SG",           # Singapore
        "MM",           # Myanmar
        "KH",           # Cambodia
        "LA",           # Laos
        "BN",           # Brunei (also = Bengali prefix — conflict, use carefully)
    ],
    "South Asia": [
        "IN", "IND",    # India
        "PK", "PAK",    # Pakistan
        "BD",           # Bangladesh
        "LK", "SRI",    # Sri Lanka
        "NP",           # Nepal
        "BT",           # Bhutan
        "MV",           # Maldives
        "AF", "AFG",    # Afghanistan
        # Indian language codes (South Asia lingua franca group):
        "HI", "TA", "TE", "ML", "KN", "BN", "MR", "GU", "PB",   # PB = Punjabi (PA = Panama, not South Asia)
        "OR", "BHO", "IND",
        # Abbreviated forms:
        "TEL", "TAM", "KAN", "MAL", "GUJ", "PUN",
    ],
    "Central Asia": [
        "KZ",           # Kazakhstan
        "KG",           # Kyrgyzstan
        "UZ",           # Uzbekistan
        "TJ",           # Tajikistan
        "TM",           # Turkmenistan
        "MN",           # Mongolia
    ],
    "Asia": [
        # Full Asia aggregate
        "AS",                           # Broad Asian content (Korean, Japanese, Chinese, South Asian, SE Asian)
        "JP", "JPN", "KR", "KO", "CN", "CHN", "TW", "TWN", "HK", "HKG", "MO",
        "TH", "VN", "ID", "PH", "MY", "SG", "MM", "KH", "LA",
        "IN", "IND", "PK", "PAK", "BD", "LK", "SRI", "NP", "BT", "AF", "AFG",
        "KZ", "KG", "UZ", "TJ", "TM", "MN",
        "HI", "TA", "TE", "ML", "KN", "MR", "GU",
    ],

    # ── Oceania ───────────────────────────────────────────────────────────────
    "Oceania": [
        "AU", "AUS",    # Australia
        "NZ",           # New Zealand
        "FJ",           # Fiji
        "PG",           # Papua New Guinea
        "SB",           # Solomon Islands
        "VU",           # Vanuatu
        "TO",           # Tonga
        "WS",           # Samoa
    ],
}

BASE_PREFIX_SEPARATORS: list[str] = [" ★ ", "★", " | ", "| ", "|", ": ", ":", " - "]


def _apply_overrides(
    base: dict[str, list[str]],
    overrides: dict[str, str],  # {code: group_name}
) -> dict[str, list[str]]:
    """Return a copy of base with per-code group assignments overridden."""
    result: dict[str, list[str]] = {k: list(v) for k, v in base.items()}
    for code, group_name in overrides.items():
        # Remove from any existing group
        for codes in result.values():
            if code in codes:
                codes.remove(code)
        # Add to target group (create group if new)
        result.setdefault(group_name, []).append(code)
    # Drop any groups left empty after override removal
    return {k: v for k, v in result.items() if v}


class Config(BaseModel):
    """Application configuration"""
    
    # Paths
    config_dir: Path = Field(default_factory=lambda: Path.home() / ".config" / "metatv")
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".local" / "share" / "metatv")
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "metatv")
    
    # Database
    database_url: str = Field(default="")
    
    # UI Settings
    notification_position: str = "bottom-right"
    max_stacked_notifications: int = 3
    
    # UI Icons/Indicators
    favorite_icon: str = "★"  # Filled star - is favorited
    unfavorite_icon: str = "☆"  # Outline star - not favorited
    live_icon: str = "📡"  # Live broadcast indicator
    movie_icon: str = "🎬"  # Movie indicator
    series_icon: str = "📺"  # TV series indicator
    season_icon: str = "📁"  # Season folder indicator
    episode_icon: str = "▶"  # Episode indicator
    unknown_icon: str = "❓"  # Unknown media type
    
    # UI Control Icons
    expand_icon: str = ">"  # Collapsed state (accordion/tree)
    collapse_icon: str = "⌄"  # Expanded state (accordion/tree)
    play_icon: str = "▶"  # Play button/indicator
    loading_icon: str = "⟳"  # Loading/buffering indicator
    close_icon: str = "×"  # Close/dismiss button
    delete_icon: str = "🗑"  # Delete/clear button
    refresh_icon: str = "⟳"  # Refresh button
    settings_icon: str = "⚙"  # Settings button
    search_icon: str = "🔍"  # Search indicator
    filter_icon: str = "⚡"  # Filter/preset indicator
    history_icon: str = "🕒"            # History indicator
    provider_icon: str = "📡"          # Provider / source section
    watch_alerts_icon: str = "⚠"      # Alerts section
    stream_retry_pending_icon: str = "🔴"  # Stream retry — awaiting re-check
    stream_retry_online_icon:  str = "🟢"  # Stream retry — back online
    info_icon: str = "ℹ"
    watchlist_icon: str = "⏰"         # Watchlist tab
    live_indicator_icon: str = "🟢"    # On Now / live indicator
    calendar_icon: str = "📅"          # Browse / calendar tab
    discover_icon: str = "✨"          # Discover tab
    move_up_icon: str = "▲"            # Move item up in list
    move_down_icon: str = "▼"          # Move item down in list
    visibility_toggle_icon: str = "👁" # Show/hide password toggle
    watched_icon: str = "✓"            # Watched / completed indicator
    rating_star_icon: str = "★"        # Star used in content rating display
    like_icon: str = "👍"              # Like / positive rating
    dislike_icon: str = "👎"           # Dislike / negative rating
    not_interested_icon: str = "🙅"    # Not Interested — suppress from recommendations only
    curious_icon: str = "❓"           # Curious / exploring — mild positive, gather discovery data
    hide_icon: str = "🚫"              # Hide channel from all views
    preferences_icon: str = "🎯"       # Preferences / Recommended dashboard
    preferred_version_icon: str = "🎯" # Best-match version indicator (distinct semantic from favorites ★)
    queue_icon: str = "📋"             # Watch Queue section / action
    pin_icon: str = "📌"               # Pin shelf to top in Discover
    manage_icon: str = "⚙"            # Manage / settings button
    watchlist_on_icon: str = "🔔"      # EPG watchlist — alert active
    watchlist_off_icon: str = "🔕"     # EPG watchlist — alert inactive
    prev_icon: str = "◀"              # Previous (lightbox / pagination)
    next_icon: str = "▶"              # Next (lightbox / pagination)
    list_view_icon: str = "☰"         # Toggle to list view
    grid_view_icon: str = "⊞"         # Toggle to grid view

    # Global Exclusions — opt-out blacklist (applies to discovery + recommendations everywhere)
    # Prefix codes to HIDE. Empty list = hide nothing (show all). Opt-out model: new prefixes
    # are always visible until the user explicitly excludes them.
    global_filter_excluded_categories: list = Field(default_factory=list)
    global_filter_include_uncategorized: bool = True  # True = show content with no detected_prefix
    global_filter_icon: str = "fa5s.filter"  # qtawesome key — resolved via icon_utils.resolve_icon()
    # Per-prefix blocklist — individual prefixes always hidden everywhere.
    # Written by the "Block [PREFIX]" quick action in the Other Versions panel.
    global_filter_excluded_prefixes: list = Field(default_factory=list)
    # Legacy field — was a whitelist; migrated to excluded_categories on first save.
    global_filter_included_categories: list = Field(default_factory=list)

    # Prefix detection settings
    prefix_bracket_enabled: bool = True  # extract [XX] bracket format
    # Bump CURRENT_PREFIX_SCAN_VERSION in metatv/core/migrations/prefix_rescan.py
    # to trigger a one-time background re-scan for all users on next launch.
    prefix_detector_version: int = 0
    # Whether to show content whose prefix code didn't match any named language group.
    # True = include "Other" content; False = hide it. Controlled by the filter dialog.
    global_filter_include_other_prefixes: bool = True
    # When True, all global filter settings are preserved but not applied anywhere.
    # Lets the user temporarily see unfiltered content without losing their configuration.
    global_filter_paused: bool = False

    # Discover view zone persistence
    # shelf keys: "recently_added", "top_movies", "top_series", "genre:Drama", "decade:1990", etc.
    discover_pinned_shelves: list = Field(default_factory=list)
    discover_expanded_shelves: list = Field(default_factory=list)
    discover_collapsed_shelves: list = Field(default_factory=list)
    discover_hidden_shelves: list = Field(default_factory=list)
    discover_shelf_order: list = Field(default_factory=list)  # manual order within expanded zone
    discover_more_expanded: bool = False   # "More Categories" accordion — collapsed by default
    discover_collapse_to_top: bool = True  # re-collapsed shelves jump to top of collapsed zone
    discover_zoom: float = 1.0             # content card zoom factor (0.6–1.8); persisted

    # Recommended view state
    preferences_attributes_expanded: bool = False  # collapsed by default
    muted_attributes: dict = Field(default_factory=lambda: {
        "genres": [], "directors": [], "actors": [], "keywords": []
    })
    rec_dedupe_overrides: list = Field(default_factory=list)
    # channel_ids that bypass title-based dedup ("not the same show" user override)
    
    # Notification Icons
    notification_progress_icon: str = "⟳"  # Progress notification
    notification_success_icon: str = "✓"  # Success notification
    notification_error_icon: str = "✗"  # Error notification
    notification_warning_icon: str = "⚠"  # Warning notification
    notification_info_icon: str = ""   # Info notification (no icon by default)
    
    # Theme & Appearance (for future theming system)
    theme: str = "auto"  # "light", "dark", "auto" (follows system)
    accent_color: str = "#4488ff"  # Primary accent color
    use_system_colors: bool = True  # Follow system color scheme
    font_family: str = ""  # Empty = system default
    font_size: int = 0  # 0 = system default
    
    # Sidebar Configuration
    sidebar_sections: list = Field(default_factory=lambda: ["alerts", "recommended", "queue", "favorites", "history", "sources"])
    sidebar_visible_sections: list = Field(default_factory=lambda: ["alerts", "recommended", "queue", "favorites", "history", "sources"])
    sidebar_section_states: dict = Field(default_factory=dict)  # Collapsed state and heights per section
    sidebar_width: int = 340  # Width of sidebar in pixels
    window_geometry: str = ""  # Base64-encoded QByteArray from saveGeometry()
    sidebar_section_sizes: list = Field(default_factory=list)  # Heights of sidebar sections in pixels
    
    # Performance
    chunk_size: int = 1000  # Channels to process at once
    concurrent_requests: int = 5
    
    # External players
    preferred_player: str = "mpv"
    player_mode: str = "single-instance"  # "single-instance" or "multiple-instances"
    close_player_when_finished: bool = True  # Close player when stream finishes (mpv --keep-open=no)
    max_player_instances: int = 1  # Max player instances (0 = use provider's max_connections, -1 = unlimited)
    split_streams_by_source: bool = False  # one mpv window per source (keyed by provider_id) when True
    player_args: dict = Field(default_factory=dict)
    
    # MPV-specific settings
    mpv_socket_path: str = "/tmp/mpv-metatv-socket"
    mpv_extra_args: list = Field(default_factory=list)  # Additional args like ["--cache=yes", "--demuxer-max-bytes=50M"]
    
    # VLC-specific settings
    vlc_extra_args: list = Field(default_factory=list)  # Additional args like ["--network-caching=3000"]
    
    # Playback settings
    default_cache_size: str = "auto"  # "auto" or size like "50M", "100M"
    buffer_profile: str = "modest"  # "reconnect_only" | "modest" | "large" | "open_ended" — default buffer when default_cache_size is "auto"
    prebuffer_before_play: bool = False  # pause at startup until the cache pre-fills (mpv --cache-pause-initial)
    prebuffer_wait_secs: int = 10        # seconds of cache to buffer before unpausing (--cache-pause-wait)
    mpv_args_override_all: bool = False  # when True, _compose_extra_args returns ONLY mpv_extra_args (skips UA/reconnect/buffer/prebuffer)
    network_timeout: int = 30  # seconds
    reconnect_attempts: int = 3
    autoplay_season_episodes: bool = True  # Auto-queue subsequent episodes when playing from season
    # After a queued auto-advance run ends, ask "Still here? Did you watch them all?"
    # so the user can promote queue-watched episodes to fully-engaged (solid icon, advance resume anchor).
    # Configurable in Settings → Playback.
    prompt_after_autoplay: bool = True
    # Watch-completion: fraction of a VOD item's duration that counts as "completed"
    # (e.g. 0.9 = 90%). Configurable in Settings → Playback.
    watch_complete_threshold: float = 0.9
    # Watch-partial: lower bound fraction before a progress glyph (◔/◐/◕) appears.
    # Below this percent the item is treated as untouched (no progress glyph shown).
    # Configurable in Settings → Playback next to "Mark as watched at".
    watch_partial_threshold: float = 0.10
    # Default action for a bare double-click on a VOD item with saved progress.
    # "resume"    → resume from saved position (default; matches the #146 behaviour).
    # "beginning" → always start from 0.
    # The details-pane Play button always starts from 0 and Resume always resumes
    # (both decoupled from this).  Per-play "Resume from M:SS" / "Play from Beginning"
    # context actions also override.
    # Configurable in Settings → Interaction → "Default double-click action".
    playback_resume_mode: str = "resume"

    # Action performed by a middle-click on a channel row. Maps to a key in the
    # gui.middle_click_actions registry (single source of truth for label + play
    # path); unknown values fall back to the default. Decoupled from the
    # double-click default above.
    # Configurable in Settings → Interaction → "Middle-click action".
    middle_click_action: str = "playback_position"

    # Stream diagnostics settings (headless engine; see core/stream_diagnostics.py)
    diagnostics_baseline_url: str = "https://speed.cloudflare.com/__down?bytes=25000000"  # Neutral-host speed sample
    diagnostics_sample_seconds: int = 8  # How long to sample provider throughput
    
    # Filtering settings
    filters_enabled: bool = True
    filter_section_visible: bool = True  # Whether filter section is expanded/collapsed
    filter_default_mode: str = "include_all"  # "include_all" or "exclude_all"
    filter_media_types: list = Field(default_factory=lambda: ["live", "movies", "series"])  # Which media types to show
    filter_enabled_media_types: list = Field(default_factory=lambda: ["live", "movie", "series"])  # User's current selection
    # User-level overrides for the base lookup tables.
    # Structure: {code: group_name} — assigns a specific prefix/code to a group,
    # overriding (or extending) the base. Provider-level overrides are keyed by
    # provider UUID: {provider_uuid: {code: group_name}}.
    user_prefix_overrides: dict = Field(default_factory=dict)
    provider_prefix_overrides: dict = Field(default_factory=dict)
    user_quality_overrides: dict = Field(default_factory=dict)
    user_platform_overrides: dict = Field(default_factory=dict)
    # Extra separator strings the user has added beyond the built-in set.
    user_extra_separators: list = Field(default_factory=list)
    # None = never configured (restore → leave section at all-checked default).
    # []   = explicitly none (restore → uncheck all — "Only" action can produce this).
    # [items] = restore exactly those items.
    # Legacy [] loaded from pre-sentinel configs is migrated to None in model_post_init.
    filter_included_languages: Optional[list] = None
    filter_included_regions: Optional[list] = None
    filter_included_qualities: Optional[list] = None
    filter_included_platforms: Optional[list] = None
    filter_included_categories: Optional[list] = None
    filter_included_genres: Optional[list] = None
    filter_included_subtitles: Optional[list] = None
    filter_included_dubs: Optional[list] = None
    filter_included_formats: Optional[list] = None
    # Schema version for the filter_included_* None-sentinel.  0 (or absent) = a
    # pre-sentinel config whose [] means "never configured" → migrate [] to None
    # ONCE in model_post_init.  >=1 = written by the sentinel-aware save, where []
    # means an explicit none-selection and must be preserved across reloads.
    filter_config_version: int = 0
    filter_section_states: dict = Field(default_factory=dict)      # {section_key: is_expanded}
    filter_panel_width: int = 220                                   # Persisted splitter width
    filter_include_untagged: bool = True   # Show channels with no detected_prefix
    filter_untagged_selected: list = Field(
        default_factory=lambda: ["no_prefix", "no_quality"])        # Untagged/Unknown section state
    filter_adult_mode: str = "hide"        # "all", "hide", or "only"
    filter_hide_watched: bool = False      # When True, exclude watch_completed channels
    show_excluded_count: bool = True
    search_includes_filtered: bool = True
    # Channel-list "Group by type" view toggle (opt-in; flat list is the default).
    group_by_type: bool = False
    # media_types whose grouped section is collapsed (header only). Persisted so
    # collapse state survives restarts.
    group_collapsed_types: list = Field(default_factory=list)
    
    # Metadata provider settings
    metadata_enabled: bool = True  # Enable metadata fetching
    metadata_cache_ttl_days: int = 30  # Fresh content cache lifetime
    metadata_old_content_ttl_days: int = 90  # Old content (>2 years) cache lifetime
    metadata_auto_fetch: bool = True  # Automatically fetch on channel selection
    metadata_background_refresh: bool = False  # Background refresh of stale metadata (Phase 3)
    
    # Metadata provider configuration
    metadata_provider_priority: list = Field(default_factory=lambda: ["provider", "tmdb", "omdb"])  # Provider priority order
    metadata_enabled_providers: list = Field(default_factory=lambda: ["provider"])  # Which providers are enabled
    
    # Provider-specific API keys and settings
    metadata_tmdb_api_key: str = ""  # TMDb API key
    metadata_tmdb_language: str = "en-US"  # TMDb language
    metadata_tmdb_include_adult: bool = False  # Include adult content
    
    metadata_omdb_api_key: str = ""  # OMDb API key
    
    # Image caching settings
    image_cache_enabled: bool = True  # Enable image caching
    image_cache_dir: str = "~/.cache/metatv/images"  # Image cache directory
    image_cache_max_size_mb: int = 500  # Maximum cache size in MB
    
    # Content category groups — maps raw source_category labels (from ## headers ##) to
    # normalized display names used in the Global Filter and Discovery shelves.
    # Keys are the normalized type name shown in the UI; values are lists of raw labels
    # exactly as they appear in the provider's ## header ## strings (case-insensitive match).
    content_category_groups: dict = Field(default_factory=lambda: {
        "Sports":        ["SPORTS NETWORK", "SOCCER PPV", "NBA LIVE EVENTS", "NBA TEAMS",
                          "NBA LEAGUE REPLAY", "NHL LIVE EVENTS", "NHL TEAMS", "NFL LIVE EVENTS",
                          "NFL LEAGUE REPLAY", "USA NCAA LIVE", "DAZN PPV US", "FIFA+ PPV",
                          "NBA PASS PPV", "BALLY NETWORK", "B1G+ PPV"],
        "Entertainment": ["ENTERTAINMENT", "SPECTRUM NETWORK", "BEIN CINEMA"],
        "News":          ["NEWS NETWORK"],
        "Kids":          ["KIDS NETWORK"],
        "Movies":        ["MOVIES NETWORK", "PRIME", "TUBI", "PARAMOUNT+ PPV"],
        "Religious":     ["BIBLICAL/RELIGIOUS"],
        "Relaxation":    ["RELAX", "RELAX 4K", "RELAX UHD"],
    })
    # Content type exclusions — empty = hide nothing. Legacy included list kept for migration.
    global_filter_excluded_content_types: list = Field(default_factory=list)
    global_filter_included_content_types: list = Field(default_factory=list)  # legacy
    # Individually excluded source_category labels from the "Other" section of the
    # Content Types expander — raw labels (e.g. "QURAN CHANNEL - NOREEN SADIQ") rather
    # than named groups. Applied in addition to global_filter_excluded_content_types.
    global_filter_excluded_source_categories: list = Field(default_factory=list)

    # User-defined categories that are globally excluded (added via "Add to Global Exclusions"
    # in the CategoryPickerDialog when creating or editing a user category).
    # Channels with user_category matching any of these names are hidden everywhere.
    global_filter_excluded_user_categories: list = Field(default_factory=list)

    # Sports / Events view filter state persistence
    # Keyword definitions (sport_keywords, league_keywords) live in:
    #   ~/.config/metatv/sports_definitions.yaml
    # That file is created on first run and is freely editable.
    sports_filter_state: dict = Field(default_factory=dict)
    events_filter_state: dict = Field(default_factory=dict)

    # EPG settings
    epg_default_refresh_interval: str = "auto"  # Global default interval; sources inherit this when per-source = "default"
    epg_watchlist_patterns: list = Field(default_factory=list)
    epg_watchlist_quiet_collapsed: bool = True  # collapse "nothing on now" section by default
    # e.g. ["NHL", "Jeopardy!", "MasterChef Canada"]
    epg_watchlist_channels: list = Field(default_factory=list)
    # channel_db_ids pinned to watchlist (MY CHANNELS section)
    epg_dismissed_channels: dict = Field(default_factory=dict)
    # {channel_db_id: iso_timestamp_dismissed_until}
    epg_notification_minutes_before: int = 15
    epg_auto_refresh: bool = True
    epg_refresh_interval_hours: int = 24
    epg_hide_filler: bool = True
    epg_filler_patterns: list = Field(default_factory=lambda: [
        "No Game Today", "No Event Today", "Off Air",
        "Sign Off", "No Programme", "TBA",
    ])
    epg_hidden_titles: list = Field(default_factory=list)
    epg_hidden_channels: list = Field(default_factory=list)
    epg_hidden_prefixes: list = Field(default_factory=list)
    epg_category_overrides: dict = Field(default_factory=dict)  # channel_db_id → category code
    epg_filter_state: dict = Field(default_factory=dict)
    epg_events_view_mode: str = "timeline"   # "timeline" | "network" — Events tab sub-view toggle
    epg_events_network_filter: str = "All"   # network combo selection in Events tab
    # Browse-tab "Allow browsing back" window (hours). The Browse timeline's default
    # left edge is the oldest CURRENTLY-AIRING show's start (so you see the beginning
    # of everything on now). This setting extends the scrubber's left edge FURTHER
    # into the past, letting you browse back that many hours. 0 (default) = no extra
    # back-browse beyond the oldest currently-airing show.
    epg_browse_hide_older_than_hours: int = 0
    # Phase-2 timeline scrubber snap granularity (minutes). Dragging the handle snaps
    # to this increment; the slider's integer steps are one increment each. One of
    # epg_utils.EPG_SCRUBBER_INCREMENTS (15 / 30 / 60).
    epg_scrubber_increment_minutes: int = 30

    # Details pane UI settings
    details_pane_visible: bool = False  # Show/hide details pane
    details_pane_width: int = 452  # Width of details pane in pixels (default tuned so a
    # portrait 2:3 poster fills the card without pillarbox padding — see
    # docs/DETAILS_PANE_DESIGN.md → "Poster sizing")
    details_pane_collapsed_sections: list = Field(default_factory=list)  # Which sections are collapsed

    # Version preference settings (used in "Other Versions" section of details pane)
    preferred_version_prefixes: list = Field(default_factory=list)
    # Ordered prefix codes, e.g. ["EN", "US"] — first match wins (+10 per rank position)
    preferred_version_quality: str = ""
    # Quality marker to prefer, e.g. "1080p", "4K", "HD" — matched against channel name
    preferred_version_provider_ids: list = Field(default_factory=list)
    # Ordered provider UUIDs — prefer content from this provider (+5 per rank position)

    # User-defined human-readable names for prefix codes (e.g. {"KU": "Kurdish", "EAR": "Arabic Subtitled"})
    # Checked first in _resolve_category_name(), before the built-in lookup tables.
    category_name_overrides: dict = Field(default_factory=dict)

    # Internal migration version for detected_prefix / detected_quality re-parsing.
    # Incremented when the parsing logic changes so the app can auto-rescan on startup.
    prefix_parse_version: int = 0

    # Internal migration version for the stale-metadata backfill.
    # Bump CURRENT_METADATA_RESCAN_VERSION in metatv/core/migrations/metadata_rescan.py
    # to trigger a one-time background re-derivation of stale metadata links.
    metadata_rescan_version: int = 0

    # Internal migration version for the tag backfill (T3, DR-0005).
    # Bump CURRENT_TAG_BACKFILL_VERSION in metatv/core/migrations/tag_backfill.py
    # to trigger a one-time re-derivation of all content_tags from the decomposer.
    tag_backfill_version: int = 0

    # Internal migration version for the content_key backfill (content-identity Slice 1).
    # Bump CURRENT_VERSION in metatv/core/migrations/content_key_backfill.py
    # to trigger a one-time re-derivation of all content_key values from stored detected_* fields.
    content_key_backfill_version: int = 0

    # Internal migration version for the detected_title re-parse (#78).
    # Bump CURRENT_VERSION in metatv/core/migrations/detected_title_reparse.py
    # to trigger a one-time full re-run of update_detected_prefixes() that strips trailing
    # quality/region/subtitle qualifiers from detected_title and recomputes content_key.
    detected_reparse_version: int = 0

    # Internal migration version for the category-facet re-facet.
    # Bump CURRENT_VERSION in metatv/core/migrations/category_facet_refacet.py to trigger
    # a one-time pass that moves content-descriptor group tags (Sports/Adult/Kids/Music/
    # News/Religious/24-7) from language:/platform: to category: (live) or genre: (VOD).
    category_facet_version: int = 0

    # What's New dialog — cursor tracking which entries the user has seen.
    # 0 = never seen any entry (shows all on first launch after this feature ships).
    last_seen_whats_new_id: int = 0

    # Dev-only QA checklist — gated by METATV_DEV env var; ignored in normal use.
    # qa_checked_steps: LEGACY — maps str(entry_id) → list of checked step indices.
    #   Kept for back-compat read of old configs only; migrated into qa_step_results
    #   on first load and never written again.
    # qa_step_results: consolidated tri-state per-step record (the new source of truth).
    #   Shape: str(entry_id) → { str(step_idx): record }, where record is a plain dict:
    #     {"state": "pass" | "fail",
    #      "sha":   "<short HEAD sha at mark time>",
    #      "ts":    "<ISO-8601 timestamp>",
    #      "note":  "<text, fail only>",
    #      "attachments": ["<abs path>", ...],  # screenshots, fail only
    #      "log":   "<abs path to log snapshot>"}  # fail only
    #   A step absent from the dict (or with no record) is untested.
    # qa_verified_id: purge cursor — entries with id <= this value are hidden.
    # qa_archived_ids: per-entry archive — entry ids individually tucked away after
    #   all their steps pass, without waiting for every entry to be done.
    qa_checked_steps: dict = Field(default_factory=dict)
    qa_step_results: dict = Field(default_factory=dict)
    qa_verified_id: int = 0
    qa_archived_ids: list = Field(default_factory=list)
    # qa_archived_collapsed: persist the Archived section collapse state.
    #   True (default) = hidden; False = expanded.
    qa_archived_collapsed: bool = True
    # qa_flagged_items: open-ended tester-flagged observations, persisted across sessions.
    #   Each item is a plain dict:
    #     {"id": str,           # uuid4 string — stable identity across edits
    #      "created": str,      # ISO-8601 timestamp (UTC)
    #      "build_sha": str,    # repo HEAD short sha at creation time
    #      "title": str,        # one-line description
    #      "note": str,         # free-text notes (may be multi-line)
    #      "attachments": [...], # list of abs paths to saved screenshots
    #      "status": str}        # "open" | "triaged"
    qa_flagged_items: list = Field(default_factory=list)
    # qa_flagged_collapsed: persist the Flagged Items section collapse state.
    #   False (default) = expanded.
    qa_flagged_collapsed: bool = False
    # qa_resolved_collapsed: persist the "Resolved" flagged sub-section collapse state.
    #   True (default) = hidden.  Addressed flagged items (claimed by a later PR's
    #   addresses=("flagged:<id>") declaration) auto-file into this collapsed group so
    #   the active Flagged list shows only items still needing work — no manual triage.
    qa_resolved_collapsed: bool = True
    # qa_addressed: manually-marked "addressed by PR" state for failed steps / flagged items.
    #   Written by the tester when a later PR fixes a known failure but no forward addresses=
    #   declaration exists on that entry.  Key format:
    #     "e{entry_id}_s{step_idx}" for a failed step
    #     "flagged:{item_id}"       for a tester-flagged item
    #   Value shape: {"pr": int|None, "entry_id": int|None, "ts": "<ISO timestamp>",
    #                 "manual": true}
    #   The step's qa_step_results state remains "fail" — this is not an auto-pass.
    qa_addressed: dict = Field(default_factory=dict)

    # Source refresh behaviour
    # When False (default), "Refresh All" skips sources the user has toggled OFF
    # (is_active=False) — everywhere else an inactive source is treated as hidden
    # (get_hidden_provider_ids scopes it out of Browse/Discover/Recipe/EPG), so
    # Refresh All spending connection budget on it was the surprising exception.
    # Set to True to also refresh disabled sources (keeps their cache warm for
    # when re-enabled).  Per-source refresh (the individual source refresh button)
    # is never affected by this setting — that's always a deliberate user action.
    refresh_all_includes_inactive: bool = False

    # Series monitor — user-opted series tracked for new episode arrivals.
    # Each entry is a plain dict:
    #   {"series_channel_id": str,   # ChannelDB.id of the series
    #    "source_id": str,           # xtream series id, for fetch_series_info
    #    "provider_id": str,
    #    "title": str,
    #    "baseline_episode_count": int | None,  # None = baseline not yet established
    #    "unseen_new": int,          # new episodes since last cleared
    #    "last_checked": str | None} # ISO timestamp
    monitored_series: list = Field(default_factory=list)

    # Search state persistence — "Remember last search" feature.
    # When remember_search is True, last_search_state is written on every search
    # change and restored on startup / when returning to the channel-list view.
    # Keys: query (str), provider_id (str|None), hidden_mode (bool),
    #       genre_filter (str|None), person_filter (str|None).
    remember_search: bool = True
    last_search_state: dict = Field(default_factory=dict)

    # VOD Watch Alerts — keyword/title rules that fire when matching content appears.
    # Each entry is a plain dict:
    #   {"text": str,              # keyword / title to watch for
    #    "match_type": str,        # "movie" | "series" | "any"
    #    "created": str,           # ISO timestamp (used as stable id)
    #    "alerted_ids": list[str], # channel_db_ids already alerted (dedup / toast-once)
    #    "viewed_ids": list[str]}  # SUBSET of alerted_ids the user has acknowledged.
    # The per-match "viewed" flag is the single source of truth for the alert-
    # visibility green across every surface: a channel is an UNVIEWED match iff it is
    # in some rule's alerted_ids and NOT in that rule's viewed_ids.  Clearing it
    # (per-item or bulk) turns the green off everywhere.  See
    # ``_migrate_vod_alert_viewed`` for the one-time pre-feature seed.
    vod_watch_alerts: list = Field(default_factory=list)

    def add_monitored_series(self, entry: dict) -> None:
        """Add a series to the monitor list (no-op if already present)."""
        cid = entry.get("series_channel_id")
        if not cid:
            return
        if not self.is_series_monitored(cid):
            self.monitored_series = list(self.monitored_series) + [entry]
            self.save()

    def remove_monitored_series(self, series_channel_id: str) -> None:
        """Remove a series from the monitor list."""
        self.monitored_series = [
            e for e in self.monitored_series
            if e.get("series_channel_id") != series_channel_id
        ]
        self.save()

    def is_series_monitored(self, series_channel_id: str) -> bool:
        """Return True if the given series_channel_id is in the monitor list."""
        return any(
            e.get("series_channel_id") == series_channel_id
            for e in self.monitored_series
        )

    def get_monitored_series(self) -> list:
        """Return a copy of the monitored series list."""
        return list(self.monitored_series)

    def get_monitored_for_provider(self, provider_id: str) -> list:
        """Return monitored series entries belonging to the given provider."""
        return [
            e for e in self.monitored_series
            if e.get("provider_id") == provider_id
        ]

    def update_monitored_series(self, series_channel_id: str, **fields) -> None:
        """Update fields on an existing monitored series entry (in-place, then save)."""
        updated = []
        for e in self.monitored_series:
            if e.get("series_channel_id") == series_channel_id:
                merged = dict(e)
                merged.update(fields)
                updated.append(merged)
            else:
                updated.append(e)
        self.monitored_series = updated
        self.save()

    def clear_unseen(self, series_channel_id: str) -> None:
        """Reset unseen_new to 0 for the given series."""
        self.update_monitored_series(series_channel_id, unseen_new=0)

    # ── VOD Watch Alert helpers ───────────────────────────────────────────────

    def get_vod_watch_alerts(self) -> list:
        """Return a copy of the VOD watch-alert rule list."""
        return list(self.vod_watch_alerts)

    def add_vod_watch_alert(self, rule: dict) -> None:
        """Add a watch-for rule (no-op if a rule with the same created id already exists)."""
        rule_id = rule.get("created", "")
        if rule_id and any(r.get("created") == rule_id for r in self.vod_watch_alerts):
            return
        # Carry both tracking keys from creation so a freshly-added rule is never
        # mistaken for a pre-feature rule by ``_migrate_vod_alert_viewed`` (which
        # seeds only rules that LACK ``viewed_ids``).  New matches recorded later
        # land in ``alerted_ids`` only → they read as unviewed (green).
        rule = dict(rule)
        rule.setdefault("alerted_ids", [])
        rule.setdefault("viewed_ids", [])
        self.vod_watch_alerts = list(self.vod_watch_alerts) + [rule]
        self.save()

    def remove_vod_watch_alert(self, rule_created: str) -> None:
        """Remove the rule with the given ``created`` timestamp id."""
        self.vod_watch_alerts = [
            r for r in self.vod_watch_alerts
            if r.get("created") != rule_created
        ]
        self.save()

    def record_vod_alert_match(self, rule_created: str, channel_id: str) -> None:
        """Append *channel_id* to the rule's ``alerted_ids`` list and save."""
        updated = []
        for r in self.vod_watch_alerts:
            if r.get("created") == rule_created:
                merged = dict(r)
                ids = list(merged.get("alerted_ids") or [])
                if channel_id not in ids:
                    ids.append(channel_id)
                merged["alerted_ids"] = ids
                updated.append(merged)
            else:
                updated.append(r)
        self.vod_watch_alerts = updated
        self.save()

    def get_vod_alert_matches(self, rule_created: str) -> list[str]:
        """Return the list of alerted channel ids for a given rule."""
        for r in self.vod_watch_alerts:
            if r.get("created") == rule_created:
                return list(r.get("alerted_ids") or [])
        return []

    # ── Per-match "viewed" state — single source of truth for the alert green ──
    # A channel is an UNVIEWED match iff it is in some rule's ``alerted_ids`` and not
    # in that rule's ``viewed_ids``.  Every alert-visibility surface (sidebar badge,
    # details Alert button, channel-list rows, Watch Queue line) reads this, so
    # clearing a match turns the green off everywhere at once.

    def get_unviewed_vod_match_ids(self) -> set[str]:
        """Return the set of channel ids that are matched but not yet viewed.

        Computed across every rule: ``⋃ alerted_ids − ⋃ viewed_ids``.
        """
        alerted: set[str] = set()
        viewed: set[str] = set()
        for r in self.vod_watch_alerts:
            alerted.update(r.get("alerted_ids") or [])
            viewed.update(r.get("viewed_ids") or [])
        return alerted - viewed

    def get_unviewed_vod_match_count(self) -> int:
        """Number of distinct unviewed matched channels across all rules."""
        return len(self.get_unviewed_vod_match_ids())

    def is_vod_match_unviewed(self, channel_id: str) -> bool:
        """True when *channel_id* is a matched-but-not-yet-viewed alert channel."""
        return channel_id in self.get_unviewed_vod_match_ids()

    def get_rules_with_new_matches_count(self) -> int:
        """Number of watch-for RULES that currently have >=1 unviewed match.

        Distinct from :meth:`get_unviewed_vod_match_count` (which counts matched
        *items*): this counts firing *alerts* for the header glance, so a single
        rule with 73 new items still reads as one firing alert.
        """
        return sum(
            1 for r in self.vod_watch_alerts
            if self.get_vod_rule_unviewed_count(r.get("created", "")) > 0
        )

    def get_vod_rule_unviewed_count(self, rule_created: str) -> int:
        """Number of unviewed matches for a single rule (sidebar per-rule badge)."""
        for r in self.vod_watch_alerts:
            if r.get("created") == rule_created:
                alerted = set(r.get("alerted_ids") or [])
                viewed = set(r.get("viewed_ids") or [])
                return len(alerted - viewed)
        return 0

    def mark_vod_alert_match_viewed(self, channel_id: str) -> bool:
        """Mark a single matched channel as viewed across every rule.

        Args:
            channel_id: The matched ChannelDB id to acknowledge.

        Returns:
            True if any rule changed (and the config was saved), else False.
        """
        changed = False
        updated = []
        for r in self.vod_watch_alerts:
            alerted = r.get("alerted_ids") or []
            viewed = list(r.get("viewed_ids") or [])
            if channel_id in alerted and channel_id not in viewed:
                merged = dict(r)
                viewed.append(channel_id)
                merged["viewed_ids"] = viewed
                updated.append(merged)
                changed = True
            else:
                updated.append(r)
        if changed:
            self.vod_watch_alerts = updated
            self.save()
        return changed

    def mark_all_vod_alerts_viewed(self) -> int:
        """Mark every matched channel as viewed (bulk "Clear Alerts").

        Returns:
            The count of distinct channels that were unviewed before the call
            (i.e. how many alerts the bulk-clear acknowledged).
        """
        before = self.get_unviewed_vod_match_count()
        if before == 0:
            return 0
        updated = []
        for r in self.vod_watch_alerts:
            merged = dict(r)
            # viewed = every alerted id (preserve order, dedup).
            merged["viewed_ids"] = list(dict.fromkeys(merged.get("alerted_ids") or []))
            updated.append(merged)
        self.vod_watch_alerts = updated
        self.save()
        return before

    def mark_vod_rule_viewed(self, rule_created: str) -> int:
        """Acknowledge every match for a single rule (per-rule "Clear this alert").

        Sets the matching rule's ``viewed_ids`` to all of its ``alerted_ids``
        (order-preserving dedup) and saves; other rules are left untouched.

        Args:
            rule_created: The ``created`` id of the rule to acknowledge.

        Returns:
            The number of channels that were unviewed for this rule before the
            call (how many alerts this clear acknowledged); 0 when the rule is
            unknown or already fully viewed (no save in that case).
        """
        cleared = self.get_vod_rule_unviewed_count(rule_created)
        if cleared == 0:
            return 0
        updated = []
        for r in self.vod_watch_alerts:
            if r.get("created") == rule_created:
                merged = dict(r)
                # viewed = every alerted id (preserve order, dedup).
                merged["viewed_ids"] = list(dict.fromkeys(merged.get("alerted_ids") or []))
                updated.append(merged)
            else:
                updated.append(r)
        self.vod_watch_alerts = updated
        self.save()
        return cleared

    def _migrate_vod_alert_viewed(self) -> None:
        """One-time per-rule seed: pre-feature rules treat existing matches as viewed.

        A rule that LACKS the ``viewed_ids`` key predates the alert-visibility
        feature; its ``alerted_ids`` were already toasted, so seed
        ``viewed_ids = alerted_ids`` to avoid a flood of green on first upgrade.
        Only matches recorded AFTER the upgrade (which append to ``alerted_ids``
        only) then light up.  Idempotent — once the key exists the rule is skipped.
        """
        changed = False
        updated = []
        for r in self.vod_watch_alerts:
            if "viewed_ids" not in r:
                merged = dict(r)
                merged["viewed_ids"] = list(merged.get("alerted_ids") or [])
                updated.append(merged)
                changed = True
            else:
                updated.append(r)
        if changed:
            self.vod_watch_alerts = updated

    # ── Computed views of the base lookup tables ─────────────────────────────
    # These are NOT stored in config.yaml — they're computed from the base
    # constants + user/provider overrides at access time.

    @property
    def filter_language_groups(self) -> dict[str, list[str]]:
        """Effective prefix→group mapping: base + user overrides."""
        return _apply_overrides(BASE_PREFIX_GROUPS, self.user_prefix_overrides)

    @property
    def filter_quality_groups(self) -> dict[str, list[str]]:
        """Effective quality-code→group mapping: base + user overrides."""
        return _apply_overrides(BASE_QUALITY_GROUPS, self.user_quality_overrides)

    @property
    def filter_platform_groups(self) -> dict[str, list[str]]:
        """Effective platform-code→group mapping: base + user overrides."""
        return _apply_overrides(BASE_PLATFORM_GROUPS, self.user_platform_overrides)

    @property
    def filter_regional_groups(self) -> dict[str, list[str]]:
        """Geographic regional groups — continent/area aggregations of prefix codes.

        Orthogonal to filter_language_groups: the same prefix code may appear in
        both (e.g. FR is in 'French' language group AND 'Europe' regional group).
        Use Language to filter by what you hear; use Region to filter by where it's from.
        """
        return BASE_REGIONAL_GROUPS

    @property
    def prefix_separators(self) -> list[str]:
        """Effective separator list: base + any user additions."""
        extra = [s for s in self.user_extra_separators if s not in BASE_PREFIX_SEPARATORS]
        return BASE_PREFIX_SEPARATORS + extra

    def _inject_new_sections(self) -> None:
        """Insert newly added sidebar sections into existing configs that predate them."""
        changed = False
        new_sections = ["queue", "recommended"]
        for sid in new_sections:
            if sid not in self.sidebar_sections:
                idx = self.sidebar_sections.index("alerts") + 1 if "alerts" in self.sidebar_sections else 0
                self.sidebar_sections.insert(idx, sid)
                changed = True
            if sid not in self.sidebar_visible_sections:
                idx = self.sidebar_visible_sections.index("alerts") + 1 if "alerts" in self.sidebar_visible_sections else 0
                self.sidebar_visible_sections.insert(idx, sid)
                changed = True
        if changed:
            self.save()

    def model_post_init(self, __context):
        """Initialize database_url if not set, and migrate legacy filter_included_* fields."""
        if not self.database_url:
            db_path = self.data_dir / "metatv.db"
            self.database_url = f"sqlite:///{db_path}"
        # Migrate legacy filter_included_* empty-list values to None — ONE TIME ONLY.
        # Before the None-sentinel was introduced, [] meant "never configured" (the
        # restore path treated [] as all-selected).  A pre-sentinel config has
        # filter_config_version 0 (or the field absent); treat its [] as None
        # (never configured) so existing users see the default all-selected restore.
        # AFTER the sentinel-aware save runs (version bumped to 1 and persisted), []
        # means an *explicit* none-selection and MUST be preserved — so the migration
        # must never run again, or it would silently undo "Only"/none-selected state.
        if self.filter_config_version < 1:
            if self.filter_included_languages == []:
                self.filter_included_languages = None
            if self.filter_included_regions == []:
                self.filter_included_regions = None
            if self.filter_included_qualities == []:
                self.filter_included_qualities = None
            if self.filter_included_platforms == []:
                self.filter_included_platforms = None
            if self.filter_included_categories == []:
                self.filter_included_categories = None
            if self.filter_included_genres == []:
                self.filter_included_genres = None
            if self.filter_included_subtitles == []:
                self.filter_included_subtitles = None
            if self.filter_included_dubs == []:
                self.filter_included_dubs = None
            if self.filter_included_formats == []:
                self.filter_included_formats = None
            self.filter_config_version = 1
        # Migrate legacy dev-QA qa_checked_steps → qa_step_results (tri-state).
        # Old shape: {str(entry_id): [checked_idx, ...]}.  Every previously-checked
        # step becomes a "pass" record.  Only runs when the new field is still empty
        # so a real config is never clobbered; the old field is left intact for
        # back-compat but never written again.
        self._migrate_qa_step_results()
        # Seed per-match "viewed" state on pre-feature VOD watch-alert rules so the
        # alert-visibility green only lights up for matches found AFTER the upgrade.
        self._migrate_vod_alert_viewed()

    def _migrate_qa_step_results(self) -> None:
        """Backfill ``qa_step_results`` from the legacy ``qa_checked_steps`` list shape.

        Idempotent: a no-op once ``qa_step_results`` is populated.  Each previously
        checked step index becomes a ``{"state": "pass", "sha": "", "ts": ""}`` record.
        Tolerates both the historical list form (``{eid: [idx, ...]}``) and a
        dict-of-bools form (``{eid: {idx: bool}}``) in case an old variant exists.
        """
        if self.qa_step_results or not self.qa_checked_steps:
            return
        migrated: dict = {}
        for entry_id, checked in self.qa_checked_steps.items():
            indices: list[int] = []
            if isinstance(checked, dict):
                indices = [int(idx) for idx, on in checked.items() if on]
            elif isinstance(checked, (list, tuple, set)):
                indices = [int(idx) for idx in checked]
            if not indices:
                continue
            migrated[str(entry_id)] = {
                str(idx): {"state": "pass", "sha": "", "ts": ""}
                for idx in indices
            }
        if migrated:
            self.qa_step_results = migrated

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def load(cls) -> tuple["Config", bool]:
        """Load configuration from file or create default.

        Returns:
            (config, recovered_from_backup) - recovered_from_backup is True if config was empty/corrupt
            and was restored from .bak file.
        """
        config_dir = Path.home() / ".config" / "metatv"
        config_file = config_dir / "config.yaml"
        backup_file = config_dir / "config.yaml.bak"

        config = None
        recovered_from_backup = False
        data = {}

        if config_file.exists():
            try:
                with open(config_file) as f:
                    data = yaml.safe_load(f) or {}

                # Check if config is empty/corrupt (missing database_url indicates corruption)
                if not data or not data.get("database_url"):
                    logger.warning("Config file is empty or missing database_url")
                    # Try to restore from backup
                    if backup_file.exists():
                        logger.warning("Attempting to restore from backup")
                        try:
                            with open(backup_file) as f:
                                data = yaml.safe_load(f) or {}
                            if data:
                                recovered_from_backup = True
                                logger.info("Successfully restored config from backup")
                            else:
                                logger.error("Backup file is also empty")
                                data = {}
                        except Exception as e:
                            logger.error(f"Failed to load backup: {e}")
                            data = {}
                    else:
                        logger.warning("No backup available, creating fresh config")
                        data = {}
                else:
                    logger.info(f"Loaded config from {config_file}")

                if data:
                    config = cls(**data)
                    config._inject_new_sections()
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                # Try backup on parse error
                if backup_file.exists():
                    logger.warning("Config parse error, attempting backup restore")
                    try:
                        with open(backup_file) as f:
                            data = yaml.safe_load(f) or {}
                        if data:
                            config = cls(**data)
                            config._inject_new_sections()
                            recovered_from_backup = True
                    except Exception as e2:
                        logger.error(f"Backup restore also failed: {e2}")

        # Create default config if load failed
        if not config:
            logger.info("Creating fresh default config")
            config = cls()
            # Note: Don't save fresh config to backup yet — only save after successful load
            # The first save() will create the backup

        return config, recovered_from_backup
    
    def save(self):
        """Save configuration to file using atomic writes (temp file → replace).

        Creates config.yaml.bak backup of the current valid config before overwriting.
        Uses atomic writes to prevent truncation on crash/interrupt.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Set database URL if not set
        if not self.database_url:
            db_path = self.data_dir / "metatv.db"
            self.database_url = f"sqlite:///{db_path}"

        config_file = self.config_dir / "config.yaml"
        backup_file = self.config_dir / "config.yaml.bak"

        # Back up current config if it exists and is valid
        if config_file.exists() and config_file.stat().st_size > 0:
            try:
                shutil.copy2(config_file, backup_file)
                logger.debug(f"Backed up config to {backup_file}")
            except Exception as e:
                logger.warning(f"Failed to create backup: {e}")

        # Convert to dict, handling Path objects
        data = self.model_dump()
        for key, value in data.items():
            if isinstance(value, Path):
                data[key] = str(value)

        # Write to temp file first, then atomically replace
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.config_dir,
                delete=False,
                suffix='.yaml'
            ) as tmp:
                tmp_path = Path(tmp.name)
                yaml.dump(data, tmp, default_flow_style=False)

            # Atomically replace original file
            tmp_path.replace(config_file)
            logger.info(f"Saved config to {config_file}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            # Clean up temp file if it exists
            try:
                tmp_path.unlink(missing_ok=True)
            except:
                pass
            raise


# ---------------------------------------------------------------------------
# Dev-mode gate
# ---------------------------------------------------------------------------

import os as _os  # noqa: E402 — placed after class to avoid polluting module namespace


def dev_mode_enabled() -> bool:
    """Return True when the METATV_DEV environment variable is set to a truthy value.

    Falsey values (absent, empty string, "0", "false", "False", "no") all return
    False.  Any other non-empty string (e.g. "1", "true", "yes") returns True.

    This is the single gate for every dev-only feature (Testing Checklist window,
    menu item, auto-show on startup).  When False, no dev UI is constructed and
    normal users are completely unaffected.

    Returns:
        bool: True when dev mode is active.
    """
    val = _os.environ.get("METATV_DEV", "").strip().lower()
    return val not in ("", "0", "false", "no")
