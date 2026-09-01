"""Configuration management"""

from pathlib import Path
from typing import Optional
import shutil
import tempfile
import yaml
from pydantic import BaseModel, Field, PrivateAttr
from loguru import logger

from metatv.core import profile_store

#: Filename for the dev-QA sidecar. Its contents are every ``Config`` field
#: whose name starts with ``qa_`` — DERIVED from the prefix, never a list
#: someone maintains, so a tenth qa_ field lands here without anyone
#: remembering this exists.
#:
#: Why it is not in config.yaml: it is 38% of the owner's file (1,797 of 4,768
#: lines) and it is not configuration at all. It is the QA record of how PRs
#: and commits land — the technical companion to What's New — and it grows
#: without bound by design. Keeping it in config.yaml meant every one of the
#: 130 ``config.save()`` call sites rewrote all of it.
QA_STATE_FILENAME = "qa_state.yaml"


def _qa_defaults(model_cls) -> dict:
    """The value each ``qa_`` field has when nobody has touched it.

    Needed because "is there any QA state" is NOT ``any(values)``: two of the
    fields are collapse flags that default to ``True``, so an untouched config
    looks non-empty and every ordinary user would get a sidecar they will
    never use. Comparing against the declared defaults is the precise question.
    """
    out = {}
    for name in _qa_field_names(model_cls):
        field = model_cls.model_fields[name]
        out[name] = (field.default_factory() if field.default_factory is not None
                     else field.default)
    return out


#: Marks a field as PROFILE state — the user's own selections and watermarks,
#: persisted by ``core/profile_store.py`` into the database rather than into
#: ``config.yaml``.
#:
#: Declared ON THE FIELD, not in a list at the bottom of this module, and that
#: is the whole reason it is a marker rather than a tuple of names. This
#: codebase's recurring failure is the enumeration nobody remembers to update —
#: the ``refresh_theme()`` sweep, the hand-listed test config stubs,
#: ``_SETTINGS_APPLIED_HOOKS``. A field that is added without a decision about
#: where it persists gets the default (``config.yaml``), which is the safe
#: answer; a field that IS user state says so where it is declared, next to its
#: docstring, where the person adding it is already looking.
#:
#: Greppable both ways: ``grep json_schema_extra=PROFILE`` lists the profile,
#: and a field's own line tells you where it goes.
PROFILE = {"store": "profile"}


def _profile_field_names(model_cls) -> "set[str]":
    """Every field marked :data:`PROFILE` on *model_cls*.

    Derived from the model, exactly as ``_qa_field_names`` is derived from the
    ``qa_`` prefix. ``profile_store.attach`` takes this rather than owning a
    list, so the store cannot disagree with the declarations.
    """
    out = set()
    for name, field in model_cls.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get("store") == "profile":
            out.add(name)
    return out


def _qa_field_names(model_cls) -> "set[str]":
    """Every ``qa_``-prefixed field name on *model_cls*.

    Derived rather than enumerated, for the reason this codebase keeps
    relearning: a hand-kept list is only right until the next field is added
    by someone who does not know the list exists.
    """
    return {name for name in model_cls.model_fields if name.startswith("qa_")}


#: PyYAML's C emitter when the platform has libyaml, else the pure-Python one.
#:
#: Measured on the owner's 130 KB config: 69.5 ms pure Python, 12.2 ms with
#: libyaml — and ``yaml.dump`` was 69 of the 75 ms a save costs, so this IS the
#: cost of saving. The startup log showed 13 saves in 57 seconds, 1.8 s of
#: blocking work on the UI thread.
#:
#: The two emitters differ only in where they wrap long lines; the parsed
#: result is identical, verified against every key in that config. Falls back
#: silently because libyaml is optional and macOS CI may not have it.
_YamlDumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)

#: Likewise for reading.
_YamlLoader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


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
    # PORNBOX added on an owner report: 30 channels, 2 flagged. is_restricted's
    # own docstring already cited it — "real libraries carry codes nobody would
    # guess — one provider uses PORNBOX" — so the code knew about it and the
    # table did not. Unambiguous, which is the bar here: a false positive HIDES
    # legitimate content when adult_mode="hide". Users can still override.
    "Adult":            ["X", "XXX", "ADULT", "PORNBOX"],
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

    #: The exact payload of the last successful write, or None before one.
    #:
    #: ``save()`` compares against this and does nothing when they match.
    #: The numbers are why: on the owner's 129 KB / 299-key config, one save
    #: is ~83 ms and ``yaml.dump`` is 85-95% of it, while ``model_dump()``
    #: costs ~1 ms. So the check is a hundredth of the thing it avoids.
    #:
    #: Why comparing a ``model_dump()`` is the right check, and a
    #: ``__setattr__`` dirty flag is not: twenty-six sites mutate a config
    #: container IN PLACE — ``config.x.append(...)``, ``config.x[k] = v`` —
    #: rather than reassigning the field, so a flag hung off attribute
    #: assignment would never fire for them and would silently drop the
    #: user's edit. A dump reflects the real state whichever way it was made.
    #:
    #: Keeping the dump itself as the snapshot is safe because ``model_dump()``
    #: returns FRESH containers rather than the live ones. If that stopped
    #: being true the snapshot would alias live state, every comparison would
    #: be a list against itself, and EVERY save would be skipped — so it is
    #: pinned by ``test_model_dump_does_not_alias_live_containers`` rather
    #: than assumed.
    _last_written: dict = PrivateAttr(default_factory=dict)
    
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
    # Graduated play-failure ledger (roadmap S3): on a source refresh, re-probe
    # that source's flagged/degraded/dead retry-checker rows immediately
    # (instead of waiting for the next backoff-scheduled check) and restore
    # any that come back online to reliability_state="ok". Configurable in
    # Settings → Playback.
    recheck_failed_on_refresh: bool = True
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
    global_filter_excluded_categories: list = Field(default_factory=list, json_schema_extra=PROFILE)
    global_filter_include_uncategorized: bool = Field(default=True, json_schema_extra=PROFILE)  # True = show content with no detected_prefix
    global_filter_icon: str = Field(default="fa5s.filter", json_schema_extra=PROFILE)  # qtawesome key — resolved via icon_utils.resolve_icon()
    # Per-prefix blocklist — individual prefixes always hidden everywhere.
    # Written by the "Block [PREFIX]" quick action in the Other Versions panel.
    global_filter_excluded_prefixes: list = Field(default_factory=list, json_schema_extra=PROFILE)
    # Legacy field — was a whitelist; migrated to excluded_categories on first save.
    global_filter_included_categories: list = Field(default_factory=list, json_schema_extra=PROFILE)

    # Prefix detection settings
    prefix_bracket_enabled: bool = True  # extract [XX] bracket format
    # Bump CURRENT_PREFIX_SCAN_VERSION in metatv/core/migrations/prefix_rescan.py
    # to trigger a one-time background re-scan for all users on next launch.
    prefix_detector_version: int = 0
    # Whether to show content whose prefix code didn't match any named language group.
    # True = include "Other" content; False = hide it. Controlled by the filter dialog.
    global_filter_include_other_prefixes: bool = Field(default=True, json_schema_extra=PROFILE)
    # When True, all global filter settings are preserved but not applied anywhere.
    # Lets the user temporarily see unfiltered content without losing their configuration.
    global_filter_paused: bool = Field(default=False, json_schema_extra=PROFILE)

    # Discover view zone persistence
    # shelf keys: "recently_added", "top_movies", "top_series", "genre:Drama", "decade:1990", etc.
    discover_pinned_shelves: list = Field(default_factory=list)
    discover_expanded_shelves: list = Field(default_factory=list)
    #: Kept as a FIELD but no longer written to: collapsed is the default
    #: zone, so storing it recorded the answer the code would reach anyway.
    #: On the owner's config that was 818 entries — 17% of the whole file —
    #: growing by one per shelf ever rendered. See _retire_collapsed_shelves.
    discover_collapsed_shelves: list = Field(default_factory=list)
    #: True once the first-launch zone defaults have been applied.
    #:
    #: This exists BECAUSE collapsed stopped being stored. "First launch" used
    #: to mean "all four zone lists are empty", and a user who had only ever
    #: collapsed things would suddenly match that — so every start would look
    #: like their first and re-expand the default shelves. Inferring a
    #: first run from an absence of data breaks the moment having no data is
    #: legitimate; an explicit marker cannot.
    discover_zones_seeded: bool = False
    discover_hidden_shelves: list = Field(default_factory=list)
    discover_shelf_order: list = Field(default_factory=list)  # manual order within expanded zone
    discover_more_expanded: bool = False   # "More Categories" accordion — collapsed by default
    discover_collapse_to_top: bool = True  # re-collapsed shelves jump to top of collapsed zone
    discover_zoom: float = 1.0             # content card zoom factor (0.6–1.8); persisted

    # Watch Queue view state — is the find-in-queue box revealed? Off by default:
    # a permanently-visible filter costs a row of the sidebar's scarcest resource
    # for a control most sessions never touch, so the 🔍 header button reveals it.
    # The TEXT is deliberately not persisted (see WatchQueueSection) — only whether
    # the box is on screen.
    queue_filter_visible: bool = False

    # Recommended view state
    preferences_attributes_expanded: bool = False  # collapsed by default
    # Its two siblings, which used to save nothing and so forgot on restart.
    preferences_exclusions_expanded: bool = False
    preferences_version_prefs_expanded: bool = False
    muted_attributes: dict = Field(default_factory=lambda: {
        "genres": [], "directors": [], "actors": [], "keywords": []
    }, json_schema_extra=PROFILE)
    rec_dedupe_overrides: list = Field(default_factory=list)
    # channel_ids that bypass title-based dedup ("not the same show" user override)

    # Recommendation steering — every dial is None until the user moves it, so an
    # untouched config uses (and keeps tracking) the shipped defaults in
    # preference_engine.RecScoringSettings.  Resolved in one place:
    # RecScoringSettings.from_config().
    #
    # Movie/series mix — the ONE key behind both the dashboard slider and the
    # settings panel.  None = Automatic (√-damped share of your engagement);
    # a float is an explicit movie share (0.0 = all series … 1.0 = all movies).
    rec_media_mix: float | None = None
    rec_weight_genre: float | None = None            # genre affinity multiplier
    rec_weight_director: float | None = None         # director affinity multiplier
    rec_weight_actor: float | None = None            # cast affinity multiplier
    rec_weight_keyword: float | None = None          # plot-keyword field multiplier
    rec_actor_min_support: int | None = None         # titles a performer must appear in
    rec_people_diversity_decay: float | None = None  # 1.0 = no people spreading
    rec_impression_decay: float | None = None        # score drop per impression
    rec_liked_cap: int | None = None                 # already-liked slots in the list


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
    # "sources" retired from this list (Wave 6, #<pending>) — Sources moved out of
    # the sidebar section stack into the always-visible status strip + Sources
    # manager view (see gui/sidebar/sources_strip.py, gui/sources_manager_view.py).
    # Existing configs are migrated by _inject_new_sections().
    sidebar_sections: list = Field(default_factory=lambda: ["alerts", "downloads", "recordings", "recommended", "queue", "favorites", "history"])
    sidebar_visible_sections: list = Field(default_factory=lambda: ["alerts", "downloads", "recordings", "recommended", "queue", "favorites", "history"])
    sidebar_section_states: dict = Field(default_factory=dict)  # Collapsed state and heights per section
    sidebar_width: int = 340  # Width of sidebar in pixels
    window_geometry: str = ""  # Base64-encoded QByteArray from saveGeometry()
    sidebar_section_sizes: list = Field(default_factory=list)  # Heights of sidebar sections in pixels

    # Settings dialog — three-panel layout (left-nav section list, right help
    # panel).  settings_dialog_section is the index of the last-selected
    # left-nav row; width/height are the dialog's last size.  All three are UI
    # state (persist on close regardless of OK/Cancel), never a setting value.
    settings_dialog_section: int = 0
    settings_dialog_width: int = 900
    settings_dialog_height: int = 600

    # Sources manager — provider editor detail pane's Summary/Connection/Settings
    # tabs (see gui/provider_editor.py). UI state (persists on change, restores on
    # init), never a setting value — same convention as settings_dialog_section.
    provider_editor_selected_tab: int = 0

    # Recipe view legacy splitter geometry (pre-redesign two-column layout).
    # Retained so older config.yaml files still load cleanly; the current
    # masonry redesign no longer reads or writes them.
    recipe_main_splitter_sizes: list = Field(default_factory=list)
    recipe_col1_splitter_sizes: list = Field(default_factory=list)
    recipe_content_splitter_sizes: list = Field(default_factory=list)
    recipe_col1_collapsed: bool = False
    recipe_more_facets_expanded: bool = False

    # Saved recipes — the user's personal facet "recipes" (Saved tab).  Each entry
    # is ``{"name": str, "includes": {facet: [values]}, "excludes": {facet: [values]}}``.
    # Persisted so a saved recipe survives restarts and reloads back into the builder.
    saved_recipes: list = Field(default_factory=list, json_schema_extra=PROFILE)

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
    # Deep-cache ("Buffer without limit", VOD-only, ephemeral): per-play mode that
    # relaunches mpv with --stream-record into a scratch dir so the buffer can grow
    # past mpv's in-memory/disk cache. See MPVPlayer's "deep" buffer profile and
    # _compose_deep_cache_args(). Str (not Path) + tilde literal, expanded at the
    # consumer — same pattern as image_cache_dir below.
    deep_cache_dir: str = "~/.cache/metatv/deepcache"  # scratch dir for deep-cache .ts recordings
    #: Where saved VOD downloads land. Persistent, unlike deep_cache_dir.
    download_dir: str = "~/Videos/MetaTV"
    #: Global stop — no download runs at all while this is set.
    downloads_paused: bool = False
    #: SIGNED offsets on a recording's guide window, in seconds. Negative
    #: starts (or ends) earlier, positive later — "record extra" is only half
    #: of it: skipping a pregame hour is -3600 on the start, as legitimate as
    #: +900 on the end. Defaults are 2 minutes early and 15 minutes late,
    #: because sport overruns, always.
    #: Stored per recording, never folded into the window: a running recording
    #: can be extended, so the stop time has to stay computable.
    recording_pad_start_seconds: int = -120
    recording_pad_end_seconds: int = 900
    #: Fallback window for "record what's on" when the channel has no EPG.
    #: A third of this catalogue has no guide data, and a recording that
    #: silently does not happen is worse than one the user can see and cancel.
    recording_default_minutes: int = 120
    deep_cache_max_gb: int = 20  # soft cap; oldest files purged before it's exceeded
    network_timeout: int = 30  # seconds
    reconnect_attempts: int = 3
    # ── URL ranking tunables (Provider.ordered_urls(), core/models.py) ───────
    # A provider's alternate host URLs are ranked on recency-weighted health +
    # latency, not a lifetime success/failure ratio (a chronically slow-but-
    # working host could sit at the top forever otherwise). These three knobs
    # are the ONLY place these numbers live — never hardcode them elsewhere.
    url_health_decay: float = 0.85  # EWMA decay per recent_attempts step, newest-first (0-1)
    url_cooldown_minutes: int = 10  # demote a URL whose most-recent attempt failed within this window
    url_recent_attempts_kept: int = 20  # cap on ProviderURL.recent_attempts persisted per URL
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

    # ── Update checker (in-app GitHub Releases check) ────────────────────────
    # When True, bundled (.app) builds check GitHub Releases for a newer version
    # on startup and offer an assisted download.  Source runs are never
    # auto-checked (only the manual "Check for updates" action).  Toggle lives in
    # Settings → Interface → Updates.
    update_check_enabled: bool = True
    # ISO-8601 UTC timestamp of the last automatic check.  Throttles automatic
    # checks to at most once / 24 h; "" = never checked.
    update_last_checked: str = ""
    # A version the user chose to "Skip this version"; the auto banner stays
    # suppressed while the latest release equals this value.
    update_skip_version: str = ""

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

    # Words/phrases the USER considers restricted, matched case-insensitively
    # against channel names at ingestion. Intentionally EMPTY by default — the
    # app ships no opinion about which words mean restricted content, because a
    # guess hides real titles (this library contains "Appropriate Adult" and
    # "xXx", both legitimate). Restricted-by-prefix uses the "Adult" prefix
    # group instead, which the user can edit.
    restricted_keywords: list = Field(default_factory=list)
    provider_prefix_overrides: dict = Field(default_factory=dict)
    user_quality_overrides: dict = Field(default_factory=dict)
    user_platform_overrides: dict = Field(default_factory=dict)
    # Extra separator strings the user has added beyond the built-in set.
    user_extra_separators: list = Field(default_factory=list)
    # None = never configured (restore → leave section at all-checked default).
    # []   = explicitly none (restore → uncheck all — "Only" action can produce this).
    # [items] = restore exactly those items.
    # Legacy [] loaded from pre-sentinel configs is migrated to None in model_post_init.
    filter_included_languages: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_included_regions: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_included_qualities: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_included_platforms: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_included_categories: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_included_genres: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_included_subtitles: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_included_dubs: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_included_formats: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    # Opt-out "known values" tracking — one per dynamic facet, mirroring the
    # filter_included_* fields above.  This is what lets the app distinguish a
    # NEW/unseen facet value from one the user deliberately deselected (see
    # docs/FILTERING_DESIGN.md — the opt-out model).
    #   None    = the opt-out feature has never established a baseline for this
    #             facet → the first update_data() call INCLUDES every present value
    #             (un-hides everything) and records the baseline here.
    #   [items] = the accumulated set of facet values already surfaced to the user.
    #             A value present in the data but NOT in this set is NEW → included
    #             by default and offered for opt-out via the new-values popup.
    filter_known_languages: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_known_regions: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_known_qualities: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_known_platforms: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_known_categories: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_known_genres: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_known_subtitles: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_known_dubs: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    filter_known_formats: Optional[list] = Field(default=None, json_schema_extra=PROFILE)
    # Schema version for the filter_included_* None-sentinel.  0 (or absent) = a
    # pre-sentinel config whose [] means "never configured" → migrate [] to None
    # ONCE in model_post_init.  >=1 = written by the sentinel-aware save, where []
    # means an explicit none-selection and must be preserved across reloads.
    #: True once ``profile_store.attach`` has verifiably taken keys over. A
    #: SETTING, so it stays in config.yaml on purpose — seeing it True beside an
    #: empty profile table is how a lost database is told apart from a user who
    #: has simply never migrated. See ``core/profile_store.py``.
    profile_store_populated: bool = False
    filter_config_version: int = 0
    filter_section_states: dict = Field(default_factory=dict)      # {section_key: is_expanded}
    filter_panel_width: int = 220                                   # Persisted splitter width
    # "chips" = a one-line active-filter bar, panel opened on demand (default,
    # the column costs ~250px whether or not it is filtering); "panel" = the
    # always-present Includes column. docs/V3_INTERFACE_SPEC.md Q3.
    filter_ui_mode: str = "chips"
    # Hide the menu bar until Alt is pressed. OFF by default and IGNORED on
    # macOS, where the menu bar is the system bar and there is nothing in the
    # window to hide. Note what it costs: the header surfaces only Tools, so
    # Layout, Style, Buffer, View, File and Help all go behind the Alt press.
    menu_bar_auto_hide: bool = False
    filter_include_untagged: bool = True   # Show channels with no detected_prefix
    filter_untagged_selected: list = Field(
        default_factory=lambda: ["no_prefix", "no_quality"])        # legacy "Unknown" section (retired #299)
    # Facets whose per-section "Untagged" footer row the user has switched OFF.
    # Stores the EXCEPTIONS, not the inclusions: absent means "shown", so the
    # default is inclusive and any facet added later starts inclusive too
    # (#299 — a filter must not hide what its facet cannot describe).
    filter_facets_hiding_untagged: list = Field(default_factory=list)
    filter_adult_mode: str = "hide"        # "all", "hide", or "only"
    filter_hide_watched: bool = False      # When True, exclude watch_completed channels
    show_excluded_count: bool = True
    search_includes_filtered: bool = True
    # Channel-list "Group by type" view toggle (opt-in; flat list is the default).
    group_by_type: bool = False
    # media_types whose grouped section is collapsed (header only). Persisted so
    # collapse state survives restarts.
    group_collapsed_types: list = Field(default_factory=list)
    # Channel-list row density (Settings → Interface → Channel List): "compact"
    # (one line), "comfy" (two lines, default), or "comfy_plus" (comfy plus a
    # middle plot line — collapses to comfy's two lines when a row has no
    # plot). One global key — not per-view.
    channel_list_density: str = "comfy"

    # Sidebar row density (Settings → Interface → Sidebar rows): "compact" (one
    # line — icon, title, chips) or "comfortable" (two lines, the second a quiet
    # meta line). Compact is the default because the sidebar's scarcest resource
    # is vertical space: ~20px against ~37px is roughly twice the entries in the
    # same allocation. See metatv.gui.chip_row.
    sidebar_row_density: str = "compact"
    #: Trade SIDEBAR scrollbars for "Show N more" rows. Off by default: every
    #: entry is present and the section scrolls, like any other list. On: the
    #: section shows what fits and ends with a row that makes it taller — for
    #: pointing devices that cannot scroll. One switch for BOTH halves, because
    #: a truncated list with neither a scrollbar nor a row is just misleading.
    #: Sidebar-only; the main results list always has its scrollbar.
    sidebar_show_more_row: bool = False

    #: Show Watch Alerts entries that have nothing new. Off by default: the
    #: sidebar section is a NOTICEBOARD, so it lists what has arrived, and a
    #: standing watchlist of things that have not shown up yet is a different
    #: question — answered in Manage Watch Alerts and, for EPG keywords, in the
    #: EPG view's Watch tab. On: every rule and monitored series is listed
    #: whether or not it is firing, which is the old behaviour.
    #: Applies to Movies and Series only. EPG already lists what is on now or
    #: coming up, which is inherently the active set, and Stream Monitoring
    #: lists streams being retried right now.
    alerts_show_idle_items: bool = False
    # Show poster thumbnails at the left of comfy/comfy_plus channel-list rows
    # (never compact). Lazy, viewport-only: only rows currently on screen ever
    # request a download (see channel_list_thumbnails.py). Default on.
    channel_list_thumbnails: bool = True
    # Platform chip name style (Settings → Interface → Channel List →
    # "Platform names", #257): "auto" (default) resolves per row density —
    # full brand name (e.g. "Apple+") in comfy/comfy_plus, short code (e.g.
    # "A+") in compact; "full"/"short" pin one style regardless of density.
    # See channel_list_delegate.ChannelRowDelegate._effective_platform_style.
    platform_name_style: str = "auto"
    # Active colour palette (Settings → Interface → Appearance). Must be a key
    # in metatv.gui.theme_palettes.PALETTES ("Midnight"/"Graphite"/"Daylight");
    # an unknown/stale name (e.g. a palette removed in a later release) is
    # ignored by theme.apply_theme(), which just leaves the current one active.
    theme_name: str = "Midnight"
    # Collapse quality/language/source variants of the same production
    # (content_key group) into one row with a "×N" variant badge (Settings →
    # Interface → Channel List). Opt-in — OFF by default because it changes
    # what rows the user sees. See ChannelRepository.get_all(collapse_variants=).
    collapse_variants_in_list: bool = False

    # Metadata provider settings
    metadata_enabled: bool = True  # Enable metadata fetching
    metadata_cache_ttl_days: int = 30  # Fresh content cache lifetime
    metadata_old_content_ttl_days: int = 90  # Old content (>2 years) cache lifetime
    metadata_auto_fetch: bool = True  # Automatically fetch on channel selection
    metadata_background_refresh: bool = False  # Background refresh of stale metadata (Phase 3)
    
    # Metadata provider configuration
    metadata_provider_priority: list = Field(default_factory=lambda: ["provider", "tmdb", "omdb"])  # Provider priority order
    # Allow-list consulted by MetadataProviderRegistry.get_enabled() (wave4/external-metadata-providers).
    # Defaults to every shipped provider — TMDb/OMDb are still independently gated by their
    # own is_enabled() (empty API key), so listing them here is a no-op until a key is set.
    # NOTE: this default only helps a NEW config — an install upgrading from before
    # tmdb/omdb existed has this already persisted as ["provider"] in config.yaml, which
    # pydantic loads verbatim (the Field default never applies once a key is on disk).
    # See metadata_enabled_providers_version / _migrate_metadata_enabled_providers() below
    # for the one-time backfill that closes that gap for existing installs.
    metadata_enabled_providers: list = Field(default_factory=lambda: ["provider", "tmdb", "omdb"])  # Which providers are enabled
    # Schema version for metadata_enabled_providers (wave4/external-metadata-providers
    # follow-up — owner-reported: a real config.yaml persisted from before TMDb/OMDb
    # existed had metadata_enabled_providers: [provider], so pasting a TMDb API key into
    # Settings was a silent no-op — MetadataProviderRegistry.get_enabled() dropped "tmdb"
    # before is_enabled() was ever consulted). 0 (or absent) = not yet migrated;
    # _migrate_metadata_enabled_providers() (model_post_init) merges "tmdb"/"omdb" into
    # the persisted list ONCE and bumps this to 1. This list has no Settings UI, so a
    # config missing a shipped name only ever means "predates that provider" — there is
    # no user intent to preserve. Version-gated (not a plain membership check re-run
    # every load) so that if this list ever grows an editing UI, a user's later,
    # deliberate removal of a provider is never silently undone by this migration
    # running again.
    metadata_enabled_providers_version: int = 0
    
    # Provider-specific API keys and settings
    metadata_tmdb_api_key: str = ""  # TMDb API key
    metadata_tmdb_language: str = "en-US"  # TMDb language
    metadata_tmdb_include_adult: bool = False  # Include adult content
    
    metadata_omdb_api_key: str = ""  # OMDb API key
    
    # Image caching settings
    image_cache_enabled: bool = True  # Enable image caching
    image_cache_dir: str = "~/.cache/metatv/images"  # Image cache directory
    image_cache_max_size_mb: int = 500  # Maximum cache size in MB

    # Provider-native TMDb enrichment (Phase 2 — tmdb_enrichment_manager.py).
    # Backfills detected_tmdb_id for idless VOD rows by calling the provider's own
    # detail endpoint, so cross-language/quality variants finally collapse.  No
    # external API key.  Politeness knobs spread the ~200k backlog across launches.
    tmdb_enrichment_enabled: bool = True        # Master toggle for the background pass
    tmdb_enrichment_session_cap: int = 500      # Max idless rows attempted per launch
    tmdb_enrichment_concurrency: int = 4        # Max concurrent detail requests per provider
    tmdb_enrichment_throttle_ms: int = 150      # Gentle delay before each request

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
    global_filter_excluded_content_types: list = Field(default_factory=list, json_schema_extra=PROFILE)
    global_filter_included_content_types: list = Field(default_factory=list, json_schema_extra=PROFILE)  # legacy
    # Individually excluded source_category labels from the "Other" section of the
    # Content Types expander — raw labels (e.g. "QURAN CHANNEL - NOREEN SADIQ") rather
    # than named groups. Applied in addition to global_filter_excluded_content_types.
    global_filter_excluded_source_categories: list = Field(default_factory=list, json_schema_extra=PROFILE)

    # Content-provenance exclusions — ``content_type`` TAG values to hide (slugs,
    # e.g. ["ai_generated", "ai_voiceover"]). Empty = hide nothing. Distinct from the
    # source-category groups above: those key off the provider's category header
    # (source_category), while these match a channel's stored ``content_type`` tag
    # (a NOT-EXISTS over content_tags). Driven by the "Content Provenance" section of
    # the Exclusions dialog. Opt-out: a new content_type value is visible until
    # explicitly excluded.
    global_filter_excluded_tag_content_types: list = Field(default_factory=list, json_schema_extra=PROFILE)

    # User-defined categories that are globally excluded (added via "Add to Global Exclusions"
    # in the CategoryPickerDialog when creating or editing a user category).
    # Channels with user_category matching any of these names are hidden everywhere.
    global_filter_excluded_user_categories: list = Field(default_factory=list, json_schema_extra=PROFILE)

    # User-defined keyword exclusions — free-text words/phrases (e.g. "wrestling",
    # "telenovela") matched case-insensitively as a SUBSTRING against a channel's
    # detected_title (falling back to name) at QUERY time, everywhere Global
    # Exclusions apply (channel list, Discover, Recommendations). Empty by
    # default — the app ships no opinion about what to hide.
    #
    # Distinct from ``restricted_keywords`` above: that list feeds
    # ``channel_name_utils.is_restricted()`` and is baked into
    # ``ChannelDB.detected_restricted`` at INGESTION (a one-time compute that
    # gates the adult_mode filter). This list has no ingestion step and no
    # stored field — it's read live by ``filter_utils.keyword_exclusion_list``/
    # ``keyword_exclusion_criterion`` on every query, so editing it takes
    # effect immediately on the next load, and it hides content from general
    # browsing regardless of adult_mode.
    global_excluded_keywords: list = Field(default_factory=list)

    # Sports / Events view filter state persistence
    # Keyword definitions (sport_keywords, league_keywords) live in:
    #   ~/.config/metatv/sports_definitions.yaml
    # That file is created on first run and is freely editable.
    sports_filter_state: dict = Field(default_factory=dict)
    events_filter_state: dict = Field(default_factory=dict)
    #: Active Sports lane — see sports_view.LANE_LABELS.
    sports_lane: str = "upcoming"
    #: Events time rendering: "elapsed" (default) | "countdowns" | "off".
    #: Seconds were rejected as "busy and obnoxious"; see events_view._TICK_MS.
    events_live_timing: str = "elapsed"

    # EPG settings
    epg_default_refresh_interval: str = "auto"  # Global default interval; sources inherit this when per-source = "default"
    epg_watchlist_patterns: list = Field(default_factory=list)
    epg_watchlist_quiet_collapsed: bool = True  # collapse "nothing on now" section by default
    # Watch Alerts -> EPG: whether the "Upcoming" sub-group (programmes that are
    # not on yet) is folded to its heading. Expanded by default so nothing
    # changes for anyone who has not asked for it; collapsing is the point —
    # the upcoming block is usually the long one, and folding it leaves the
    # alerts and what is on NOW visible in a much shorter section. Owner: "the
    # upcoming shows take over the entire array and maybe I don't care what's
    # on next."
    alerts_epg_upcoming_collapsed: bool = False
    # e.g. ["NHL", "Jeopardy!", "MasterChef Canada"]
    epg_watchlist_channels: list = Field(default_factory=list)
    # channel_db_ids pinned to watchlist (MY CHANNELS section)
    epg_dismissed_channels: dict = Field(default_factory=dict)
    # {channel_db_id: iso_timestamp_dismissed_until}
    epg_notification_minutes_before: int = 15
    epg_auto_refresh: bool = True
    epg_refresh_interval_hours: int = 24
    # Age-based EPG hygiene: how long (hours) an EXPIRED programme (stop_time in the
    # past) is kept before EpgManager.prune_expired() sweeps it, run after every
    # successful fetch. Floor of 6h is enforced in prune_expired(), not here, so a
    # stray small value can never wipe data still needed for "on now".
    epg_retention_hours: int = 24
    epg_hide_filler: bool = True
    epg_filler_patterns: list = Field(default_factory=lambda: [
        "No Game Today", "No Event Today", "Off Air",
        "Sign Off", "No Programme", "TBA",
    ])
    epg_hidden_titles: list = Field(default_factory=list)
    epg_hidden_channels: list = Field(default_factory=list)
    epg_hidden_prefixes: list = Field(default_factory=list)
    # channel_db_ids whose EPG link has been manually cleared (🧹 "Clear EPG
    # link" — channel menu + details-pane rail). EpgManager._build_match_map
    # excludes these from ALL matching tiers (1/2/3) so a persistent bad
    # guide-data link doesn't get silently re-attached the next time relink_all()
    # runs — which happens on every EPG view activation (docs/CRITICAL_RULES.md
    # #epg-manager-internals). Removing a channel_db_id ("Re-link EPG data")
    # lets the next relink pass re-match it.
    epg_link_blocklist: list = Field(default_factory=list)
    # detected_prefix values that never enter fuzzy matching tiers 2/3 (tier-1
    # exact epg_channel_id matches are unaffected). These denote show-loop /
    # rotation feeds ("24/7 Movies", generic filler channels) whose names are
    # too generic for fuzzy name matching to be trustworthy. Case-insensitive.
    epg_fuzzy_prefix_blocklist: list = Field(
        default_factory=lambda: ["EAR", "24/7", "24-7"]
    )
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

    # Internal migration version for the tmdb-id backfill (content-identity Slice 3).
    # Bump CURRENT_VERSION in metatv/core/migrations/tmdb_id_backfill.py to trigger a
    # one-time pass that reads raw_data["tmdb"] into detected_tmdb_id.  MUST run before
    # the content_key backfill (registration order in gui/main_window.py) so the
    # content_key recompute can key on the tmdb id.
    tmdb_id_backfill_version: int = 0

    # Internal migration version for the tmdb title-sibling propagation (Phase-2 reshape).
    # Bump CURRENT_VERSION in metatv/core/migrations/tmdb_sibling_propagation.py to trigger
    # a one-time pass where idless VOD rows adopt a confident same-title sibling's
    # detected_tmdb_id.  MUST run after the tmdb-id + content_key backfills (registration
    # order in gui/main_window.py) so id-bearing siblings exist to adopt from.
    tmdb_sibling_propagation_version: int = 0

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

    # Internal migration version for the detected_genre(s) backfill (#genre-perf).
    # Bump CURRENT_VERSION in metatv/core/migrations/detected_genre_backfill.py to
    # trigger a one-time pass populating ChannelDB.detected_genre/detected_genres
    # (stored canonical genre(s), computed at ingestion) for pre-existing rows —
    # what lets Discover's genre shelves read a small indexed/stored field instead
    # of alias-matching against raw_data on every shelf expand.
    # One-time cleanup of detected_region values inherited from an unrelated
    # content_key sibling (see migrations/bad_region_cleanup.py). Only ever
    # CLEARS a contradicting region — an empty region is honest, a guessed one
    # is how the mislabels happened.
    bad_region_cleanup_version: int = 0
    genre_backfill_version: int = 0

    # Internal migration version for the detected_restricted backfill (owner-reported
    # gap — restricted-content name/prefix detection, e.g. XXX/ADULT/X-prefix, that the
    # provider's is_adult flag misses).  Bump CURRENT_VERSION in
    # metatv/core/migrations/restricted_backfill.py to trigger a one-time pass
    # populating ChannelDB.detected_restricted (computed at ingestion via
    # channel_name_utils.is_restricted_prefix()) for pre-existing rows.
    restricted_backfill_version: int = 0
    #: Version of the case-variant tag merge that has been applied.
    tag_case_merge_version: int = 0
    #: Version of the epg_channel_id recovery that has been applied.
    epg_channel_id_backfill_version: int = 0
    #: Version of the metadata.year derivation that has been applied.
    metadata_year_backfill_version: int = 0
    # ── Signal checking ─────────────────────────────────────────────────
    # How a stream is judged dead air rather than a picture. Exposed because
    # the right answer is provider-dependent: a channel that runs a 4-second
    # bumper between segments needs a different black threshold than one that
    # cuts straight to programme.
    #: Seconds of stream sampled per check. The wall-clock cost is dominated by
    #: connect + buffer, so a longer sample is cheaper than it looks — but every
    #: second is a second holding the provider's only connection.
    signal_sample_seconds: int = 4
    #: Fraction of the sample that must be black before the verdict is "black".
    #: 0.5 means "more than half". A bumper or a fade is black for a moment;
    #: half the sample is not a bumper.
    signal_black_fraction: float = 0.5
    #: How dark counts as black, as a fraction of full scale.
    signal_black_pixel_threshold: float = 0.10
    #: Seconds of motionless picture before it is called a frozen slate.
    signal_freeze_seconds: int = 2
    #: Hide events whose last check found no picture. Off by default: seeing
    #: the scale of the problem is the point until the check has earned trust.
    hide_dead_events: bool = False
    #: Consecutive dead checks before an event is treated as dead for hiding.
    #: One bad check is a bad moment; three across different sittings is a fact.
    signal_dead_streak_to_hide: int = 2

    #: Version of the raw_data -> MetadataDB field backfill that has been
    #: applied (see migrations/raw_field_backfill.FIELDS). Supersedes the
    #: runtime-only version this generalised.
    raw_field_backfill_version: int = 0
    #: Version of the sports/PPV/event classifier the stored rows were
    #: labelled by. Bump CURRENT_VERSION in migrations/sports_reclassify.py
    #: whenever special_content.py's classification changes.
    sports_reclassify_version: int = 0

    # Internal migration version for the category-marker backfill (owner-reported
    # gap — provider category strings carrying a leading "|EN| ANIME"-style marker
    # that duplicates channel-name language info). Bump CURRENT_VERSION in
    # metatv/core/migrations/category_marker_backfill.py to trigger a one-time pass
    # populating ChannelDB.detected_collection(_language|_subdub) for pre-existing
    # rows (new channels get them at ingestion).
    category_marker_backfill_version: int = 0

    # Internal migration version for the episode metadata backfill (Wave 4 — #247).
    # Bump CURRENT_VERSION in metatv/core/migrations/episode_metadata_backfill.py to
    # trigger a one-time pass populating EpisodeDB.plot/air_date/rating/still_url from
    # each row's already-stored raw_data blob (new episodes get these at ingestion).
    episode_metadata_backfill_version: int = 0
    # Internal migration version for the collection-token-cleanup backfill
    # (owner-reported gap — detected_collection repeating tokens the row
    # already shows via its own quality chip / media-type icon / subtitle-
    # marker chip, e.g. "MULTISUB SERIES 4K"). Bump CURRENT_VERSION in
    # metatv/core/migrations/collection_token_cleanup_backfill.py to trigger
    # a one-time pass re-deriving ChannelDB.detected_collection for
    # pre-existing rows (new channels get it at ingestion).
    collection_token_cleanup_backfill_version: int = 0

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
    #   {"series_channel_id": str,   # ChannelDB.id of the PRIMARY (add-time) channel
    #    "source_id": str,           # PRIMARY provider's xtream series id
    #    "provider_id": str,         # PRIMARY provider — kept for back-compat +
    #                                # get_monitored_for_provider() filtering
    #    "title": str,
    #    "baselines": dict[str, int],  # {"provider_id|source_id": episode_count}
    #                                   # — one entry per MIRROR (listing)
    #                                   # currently carrying this series: the
    #                                   # primary plus any content_key siblings
    #                                   # discovered at check time, INCLUDING
    #                                   # several on the same provider (that is
    #                                   # normal — content_key is a generous
    #                                   # identity).  Keyed by the pair, not by
    #                                   # provider alone: a provider-only key let
    #                                   # same-provider listings overwrite one
    #                                   # slot and manufacture false "+N eps"
    #                                   # alerts.  A mirror absent from this dict
    #                                   # has no baseline yet (established
    #                                   # silently on its first check — never
    #                                   # alerts on the whole back-catalog).
    #                                   # Build keys via series_monitor.mirror_key.
    #    "unseen_new": int,          # new episodes since last cleared (summed
    #                                 # across every provider that grew)
    #    "growth_providers": list[str],  # display names credited for the most
    #                                     # recent unseen growth (toast + row
    #                                     # tooltip attribution); cleared
    #                                     # alongside unseen_new
    #    "last_checked": str | None} # ISO timestamp
    # Legacy shape (pre-per-provider-baselines upgrade): a scalar
    # "baseline_episode_count" instead of "baselines" — tolerated on read,
    # migrated to the per-provider shape (and the migrated list written back)
    # by get_monitored_series().  See series_monitor.normalize_monitored_entry().
    monitored_series: list = Field(default_factory=list, json_schema_extra=PROFILE)

    # Series monitor — recurring background recheck interval, in minutes.
    # SeriesMonitorManager.start_scheduler() reads this to arm a QTimer that
    # re-runs check_all() while the app stays open (in addition to the startup
    # check and the post-provider-refresh check_provider() call).  0 = off.
    #
    # A day, not an hour. A pass is one get_series_info per monitored series per
    # mirror, and on a one-connection account every one of those calls is the slot
    # the user plays through — 11 series x 3 mirrors at ~1-11s a call is a ~3
    # minute pass. New episodes appear at most daily, so hourly bought nothing and
    # spent the connection twelve times more often than it needed to.
    series_monitor_interval_minutes: int = 1440

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
    vod_watch_alerts: list = Field(default_factory=list, json_schema_extra=PROFILE)

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
        """Return a copy of the monitored series list.

        Migrates any legacy entry (scalar ``baseline_episode_count``, from
        before the per-provider baselines upgrade) to the per-provider
        ``baselines`` shape, AND resets any ``unseen_new`` left inflated by
        the #259 baseline-accounting bug (a flaky provider fetch recorded a
        baseline of 0, so the next successful check counted the whole
        catalogue as "new" every pass) to 0 — a count found exceeding its
        summed baselines is PROVEN corrupt (no way to tell which, if any, of
        the recorded episodes were genuine new ones), so 0 is the honest
        value, not a clamped guess; genuinely new episodes are detected fresh
        on the very next check regardless.  Both steps run on first read,
        writing the migrated list back, and are one-time, idempotent upgrades
        (see ``series_monitor.normalize_monitored_entry`` and
        ``series_monitor.zero_out_inflated_unseen_new`` — NOT the different,
        ongoing ``clamp_unseen_new_to_baseline_total`` guard applied to fresh
        writes in ``SeriesMonitorManager._on_new_episodes``).  Entries
        already sane pass through unchanged.  This never touches favorites,
        ratings, history, or watch progress, and never removes an entry — it
        only ever corrects the derived ``unseen_new``/``baselines`` fields on
        this list.
        """
        from metatv.core.series_monitor import (
            normalize_monitored_entry,
            zero_out_inflated_unseen_new,
        )

        changed = False
        migrated = []
        for e in self.monitored_series:
            m = normalize_monitored_entry(e)
            c = zero_out_inflated_unseen_new(m)
            if c is not e:
                changed = True
            migrated.append(c)
        if changed:
            self.monitored_series = migrated
            self.save()
        return list(self.monitored_series)

    def get_monitored_for_provider(self, provider_id: str) -> list:
        """Return monitored series entries that involve the given provider.

        Matches the entry's PRIMARY provider (the source the user clicked
        "Alert me" from) OR any provider already recorded in its per-provider
        ``baselines`` dict — so a call after THAT mirror's refresh also finds
        entries discovered as siblings by a prior full ``check_all()`` pass.
        """
        from metatv.core.series_monitor import provider_of

        # provider_of, not a bare `in`: baseline keys are "provider|source"
        # (one slot per mirror), so a plain membership test never matches.
        return [
            e for e in self.get_monitored_series()
            if e.get("provider_id") == provider_id
            or any(
                provider_of(k) == provider_id
                for k in (e.get("baselines") or {})
            )
        ]

    def update_monitored_series(
        self, series_channel_id: str, *, save: bool = True, **fields
    ) -> None:
        """Update fields on an existing monitored series entry, in place.

        Args:
            series_channel_id: Entry to update.
            save: Write the file now. Pass ``False`` when several updates are
                coming in a row and the caller will call :meth:`save` once
                itself. The entry is updated IN MEMORY either way, immediately —
                only the file write is deferred. That distinction matters: the
                Watch Alerts badges read ``unseen_new`` straight back, so
                deferring the in-memory update would make new-episode counts lag
                a whole pass, while deferring the SAVE costs nothing visible.
            **fields: Fields to merge onto the entry.
        """
        updated = []
        for e in self.monitored_series:
            if e.get("series_channel_id") == series_channel_id:
                merged = dict(e)
                merged.update(fields)
                updated.append(merged)
            else:
                updated.append(e)
        self.monitored_series = updated
        if save:
            self.save()

    def update_monitored_series_many(self, updates: dict) -> None:
        """Apply field updates to many entries and save **once**.

        :meth:`update_monitored_series` saves on every call, which is right for
        a single user action and ruinous in a loop. Each save copies the config
        to ``.bak``, runs a full Pydantic ``model_dump()`` and re-serialises the
        whole file — and this config is not small (owner's, 2026-08-31: 4,854
        lines / 132 KB, three quarters of it QA results, derived filter caches
        and an ever-growing collapsed-shelf list).

        Two paths were paying that per iteration, BOTH on the main thread:

        * ``SeriesMonitorManager._on_new_episodes`` — a queued-signal slot fired
          once per checked series. Not a loop, so a time-based debounce cannot
          coalesce it: the signals arrive seconds apart across a pass. It writes
          in memory immediately and lets the pass boundary do the one save.
        * ``MainWindow._apply`` (the ``_run_query`` callback that backfills
          region/language) — once per row, where the cost
          is not merely contention but a direct freeze.

        Args:
            updates: ``{series_channel_id: {field: value, ...}}``. Ids not
                present in ``monitored_series`` are ignored, matching
                :meth:`update_monitored_series`'s behaviour for an unknown id.
        """
        if not updates:
            return
        changed = False
        merged_list = []
        for e in self.monitored_series:
            fields = updates.get(e.get("series_channel_id"))
            if fields:
                merged = dict(e)
                merged.update(fields)
                merged_list.append(merged)
                changed = True
            else:
                merged_list.append(e)
        if not changed:
            return
        self.monitored_series = merged_list
        self.save()

    def clear_unseen(self, series_channel_id: str) -> None:
        """Reset unseen_new to 0 (and its provider attribution) for the given series.

        Called both by the explicit "Mark seen" action and by drilling into the
        series' season/episode tree (opening it is itself an acknowledgment).
        """
        self.update_monitored_series(series_channel_id, unseen_new=0, growth_providers=[])

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

    def _migrate_metadata_enabled_providers(self) -> None:
        """Merge newly-shipped provider names into ``metadata_enabled_providers`` — ONCE.

        ``metadata_enabled_providers`` has no Settings UI (nothing ever writes it), so
        a persisted value missing a shipped provider name only ever means "this config
        predates that provider" — there is no user intent to preserve. Without this, an
        existing install's persisted ``["provider"]`` value silently excludes "tmdb"/
        "omdb" from ``MetadataProviderRegistry.get_enabled()`` forever: pasting a TMDb
        API key into Settings becomes a silent no-op with nothing to diagnose from
        (owner-reported against a real ``config.yaml``, wave4/external-metadata-providers).

        Version-gated (``metadata_enabled_providers_version``) rather than a plain
        membership check re-run on every load, so that if this list ever grows an
        editing UI, a user's later, deliberate removal of a provider is never silently
        undone by this migration running again on a subsequent launch. Idempotent:
        a no-op once the version is already >= 1.
        """
        if self.metadata_enabled_providers_version >= 1:
            return
        for name in ("tmdb", "omdb"):
            if name not in self.metadata_enabled_providers:
                self.metadata_enabled_providers.append(name)
        self.metadata_enabled_providers_version = 1

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

    def _retire_collapsed_shelves(self) -> None:
        """Drop the stored collapsed zone, once, preserving what it implied.

        ``discover_collapsed_shelves`` recorded the DEFAULT zone — the value
        ``determine_zone`` falls through to — so every entry was the answer the
        code would give with no entry at all. On the owner's config that was
        818 of 4,768 lines.

        The one thing it did carry is that the user had been here before, which
        ``_is_first_launch`` read as "not all four lists are empty". That
        meaning is transferred to ``discover_zones_seeded`` first, then the list
        is cleared. Order matters: clearing first would erase the evidence this
        migration needs.
        """
        if self.discover_zones_seeded:
            return
        has_zone_state = any((self.discover_pinned_shelves,
                              self.discover_expanded_shelves,
                              self.discover_collapsed_shelves,
                              self.discover_hidden_shelves))
        changed = False
        if has_zone_state:
            self.discover_zones_seeded = True
            changed = True
        if self.discover_collapsed_shelves:
            logger.info(
                "Discover: dropping {} stored collapsed shelves — collapsed is "
                "the default zone, so they recorded nothing",
                len(self.discover_collapsed_shelves))
            self.discover_collapsed_shelves = []
            changed = True
        if changed:
            self.save()

    @classmethod
    def _merge_qa_sidecar(cls, config_dir: Path, data: dict) -> dict:
        """Overlay ``qa_state.yaml`` onto freshly-loaded config data.

        Reads both, so a config.yaml written before the split still works —
        its inline ``qa_*`` keys load exactly as before, and the next save
        moves them to the sidecar and drops them from config.yaml. Nothing has
        to be migrated by hand and nothing is lost if the sidecar is missing.

        The sidecar WINS where both have a key, because it is the file being
        written now. The only way config.yaml still holds a qa_ key is that it
        predates the split, which makes it the older copy by definition.

        A broken sidecar is logged and ignored rather than raised: the QA
        checklist is a dev tool, and losing a tick list must never stop the
        app loading someone's actual settings.
        """
        qa_file = config_dir / QA_STATE_FILENAME
        if not qa_file.exists():
            return data
        try:
            with open(qa_file) as f:
                qa = yaml.load(f, Loader=_YamlLoader) or {}
        except Exception as e:
            logger.warning(f"Could not read {qa_file}: {e}")
            return data
        if not isinstance(qa, dict):
            logger.warning(f"{qa_file} is not a mapping; ignoring it")
            return data
        merged = dict(data)
        merged.update({k: v for k, v in qa.items() if k.startswith("qa_")})
        return merged

    def _inject_new_sections(self) -> None:
        """Insert newly added sidebar sections into existing configs that predate them."""
        changed = False
        # "downloads"/"recordings" (Catch, Keep, Record slice 4): the engines
        # shipped in #612 with no surface at all, so an existing config has no
        # entry for either and would never show them.
        new_sections = ["queue", "recommended", "downloads", "recordings"]
        for sid in new_sections:
            if sid not in self.sidebar_sections:
                idx = self.sidebar_sections.index("alerts") + 1 if "alerts" in self.sidebar_sections else 0
                self.sidebar_sections.insert(idx, sid)
                changed = True
            if sid not in self.sidebar_visible_sections:
                idx = self.sidebar_visible_sections.index("alerts") + 1 if "alerts" in self.sidebar_visible_sections else 0
                self.sidebar_visible_sections.insert(idx, sid)
                changed = True
        # Retire orphaned sections whose UI no longer exists in the sidebar section
        # stack — strip any stale saved reference so the create loop never tries to
        # build a section that no longer exists:
        #   "new_episodes" — folded into the always-visible Watch Alerts section.
        #   "sources"      — moved out of the sidebar entirely (Wave 6) into the
        #                    status strip + Sources manager view.
        _retired_sections = {"new_episodes", "sources"}
        for _attr in ("sidebar_sections", "sidebar_visible_sections"):
            _lst = getattr(self, _attr)
            _filtered = [s for s in _lst if s not in _retired_sections]
            if _filtered != _lst:
                setattr(self, _attr, _filtered)
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
        self._apply_value_migrations()

    def _apply_value_migrations(self) -> None:
        """Field migrations that must run over the values, wherever they came from.

        Separated from ``model_post_init`` because these two touch PROFILE
        fields, which no longer arrive only from YAML: once
        ``profile_store.attach`` loads a stored value over the top, a migration
        that ran only at construction would never see it. So attach calls this
        again.

        Both are gated on emptiness and are idempotent — that is the property
        that lets them run twice, and it is what this split relies on.

        Not moved here: the ``filter_config_version < 1`` migration in
        ``model_post_init``, which also touches profile fields. It is gated on a
        version marker that is set to 1 by the first save any config has ever
        done, so it is already a no-op for everyone whose data can reach the
        store — a pre-sentinel ``[]`` is migrated to ``None`` before it is ever
        written there. Its marker stays in ``config.yaml`` on purpose: a
        migration's own bookkeeping belongs with the code that decides whether
        to run it, not inside the data it rewrites.
        """
        # Seed per-match "viewed" state on pre-feature VOD watch-alert rules so the
        # alert-visibility green only lights up for matches found AFTER the upgrade.
        self._migrate_vod_alert_viewed()
        # Merge newly-shipped provider names (tmdb/omdb) into a persisted
        # metadata_enabled_providers that predates them — see the field's docstring.
        self._migrate_metadata_enabled_providers()

    def attach_profile_store(self, db) -> frozenset[str]:
        """Bind the profile store to *db* and migrate this config into it.

        The one call that moves the user's selections and watermarks out of
        ``config.yaml``. Runs at startup, right after the database is created and
        before any view reads a filter — synchronously, because everything after
        it depends on knowing which keys the store owns.

        Args:
            db: The open :class:`~metatv.core.database.Database`.

        Returns:
            The keys now persisted in the database rather than in the YAML.
        """
        profile_store.bind(db)
        owned = profile_store.attach(self, _profile_field_names(type(self)))
        # A stored value has just landed on top of what YAML supplied, so the
        # value migrations have to see it. Idempotent by construction.
        self._apply_value_migrations()
        # Prime the write-comparison with what the STORE holds, so the first save
        # after startup does not re-write 34 rows that are already correct.
        #
        # Deliberately the store's contents and not the model's: if a migration
        # above just changed a value, the model and the database now disagree,
        # and that disagreement is precisely what has to be written. Priming
        # from the model would record the change as already saved and lose it.
        stored = profile_store.read_all()
        self._last_written["_profile"] = {k: stored[k] for k in owned if k in stored}
        return owned

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
                    data = yaml.load(f, Loader=_YamlLoader) or {}

                # Check if config is empty/corrupt (missing database_url indicates corruption)
                if not data or not data.get("database_url"):
                    logger.warning("Config file is empty or missing database_url")
                    # Try to restore from backup
                    if backup_file.exists():
                        logger.warning("Attempting to restore from backup")
                        try:
                            with open(backup_file) as f:
                                data = yaml.load(f, Loader=_YamlLoader) or {}
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
                    data = cls._merge_qa_sidecar(config_dir, data)
                    config = cls(**data)
                    config._inject_new_sections()
                    config._retire_collapsed_shelves()
                    config._rewrite_if_stale(data, config_file)
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                # Try backup on parse error
                if backup_file.exists():
                    logger.warning("Config parse error, attempting backup restore")
                    try:
                        with open(backup_file) as f:
                            data = yaml.load(f, Loader=_YamlLoader) or {}
                        if data:
                            data = cls._merge_qa_sidecar(config_dir, data)
                            config = cls(**data)
                            config._inject_new_sections()
                            config._retire_collapsed_shelves()
                            recovered_from_backup = True
                    except Exception as e2:
                        logger.error(f"Backup restore also failed: {e2}")

        # Create default config if load failed
        if not config:
            logger.info("Creating fresh default config")
            config = cls()
            # No prior config to honor (fresh install, or an unrecoverable one): start
            # the What's New cursor at the newest entry so first launch does NOT replay
            # the entire historical changelog (160+ entries). Existing users with a
            # valid config keep whatever cursor they had saved.
            from metatv.whats_new import latest_id
            config.last_seen_whats_new_id = latest_id()
            # Note: Don't save fresh config to backup yet — only save after successful load
            # The first save() will create the backup

        return config, recovered_from_backup
    
    def _rewrite_if_stale(self, data: dict, config_file: "Path") -> bool:
        """Rewrite the file when it predates the current schema.

        pydantic already fills a missing key with its declared default, so an
        older file LOADS correctly — but it stays old on disk, and every launch
        re-derives the same defaults from a file that never learns them. Worse,
        the gap is invisible: nothing reading ``config.yaml`` can tell which
        settings are chosen and which are simply absent.

        So the file is read, normalised by the model, and written back in the
        current format the first time a key is missing. After that it is a full,
        honest record of every setting the app has — which is what makes plain
        ``config.field`` access correct everywhere else, instead of a
        ``getattr(config, field, default)`` at each call site defending against
        a file that could have healed itself once.

        Only when something is actually missing: rewriting on every launch would
        churn the file and rotate the backup for nothing.

        Args:
            data: The raw mapping read from disk, before model validation.
            config_file: Where it came from, for the log line.

        Returns:
            True when the file was rewritten.
        """
        # PROFILE fields are absent on purpose — CFG-5 moved 34 of them to the
        # `profile` table and prunes them from the YAML once a verified read-back
        # says the database holds them. Counting those as "missing" would make
        # this rewrite them back into config.yaml on every single launch, quietly
        # undoing the prune. Absence stopped meaning staleness the moment some
        # settings legitimately live somewhere else.
        #
        # The DECLARED set, not `profile_store.owned_keys()`: this runs inside
        # load(), and the store is not bound until MainWindow has a database, so
        # owned_keys() is empty here and would exclude nothing.
        #
        # The qa_ fields are the same story and were found the same way — by
        # running this against a real migrated config rather than reasoning
        # about it. #643 moved them to qa_state.yaml, so all nine are absent
        # from config.yaml by design and this rewrote the file on EVERY launch
        # to put them back. Two subtractions, one rule: a field that lives
        # somewhere else is not a field that is missing.
        missing = sorted(set(type(self).model_fields)
                         - set(data)
                         - _profile_field_names(type(self))
                         - _qa_field_names(type(self)))
        if not missing:
            return False
        logger.info(
            "Config at {} predates this version — {} setting(s) were absent "
            "and have been written with their defaults: {}",
            config_file, len(missing),
            ", ".join(missing[:8]) + ("…" if len(missing) > 8 else ""),
        )
        try:
            self.save()
        except Exception as exc:      # noqa: BLE001 - never block startup on this
            # A config that loaded fine must still start the app. The rewrite is
            # housekeeping, not a precondition.
            logger.warning("Could not rewrite the config file: {}", exc)
            return False
        return True

    def save(self, *, force: bool = False):
        """Save configuration to file using atomic writes (temp file → replace).

        Does nothing when the content is byte-identical to the last write — see
        the comparison below for why that is worth checking.

        Creates config.yaml.bak backup of the current valid config before overwriting.
        Uses atomic writes to prevent truncation on crash/interrupt.

        Args:
            force: Write even when unchanged. For a caller that needs the file
                on disk to be provably current; not an opt-out.
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

        # Convert to dict, handling Path objects
        data = self.model_dump()
        for key, value in data.items():
            if isinstance(value, Path):
                data[key] = str(value)

        # Nothing changed since the last write? Then do not do the expensive
        # part. Measured on the owner's config (129 KB, 299 keys): a save is
        # ~83 ms and yaml.dump is 85-95% of that, while the model_dump above
        # costs ~1 ms. There are 130 call sites and none of them checks, so
        # every "on change" handler that fires without a change — a splitter
        # nudged back to the same size, a section toggled twice — paid the
        # full 83 ms on the UI thread.
        #
        # Compared AFTER the database_url default above, so first-run does
        # write. `force` exists for a caller that must be certain the file on
        # disk is current (a shutdown path), not as a way to opt out.
        # `config_file.exists()` is part of the condition, not an afterthought:
        # if the file is deleted out from under us, the in-memory snapshot still
        # matches and we would skip forever, leaving the user with no config on
        # disk and no way to notice. Existence is the other half of "already
        # written".
        # Split into the two files. QA state is 38% of the owner's config and
        # is not configuration — it is the dev record of how PRs land — so it
        # lives in its own sidecar and, crucially, a QA write no longer
        # rewrites config.yaml at all.
        qa_names = _qa_field_names(type(self))
        qa_data = {k: v for k, v in data.items() if k in qa_names}
        qa_file = self.config_dir / QA_STATE_FILENAME

        # The profile slice — the user's own selections and watermarks — goes to
        # the database, one row per key, and leaves config.yaml entirely. On the
        # owner's file that is 1,849 of 2,252 lines: 82% of what a checkbox was
        # rewriting.
        #
        # `owned_keys()` is empty until `profile_store.attach()` has written each
        # key, read it back and compared it, so this is not a promise that the
        # data moved — it is the store reporting what it has verified it holds.
        # Before attach (including `__main__`'s save immediately after load, and
        # every test that never binds a database) the set is empty and every key
        # goes to YAML exactly as before. There is no window in which a field is
        # missing from both.
        owned = profile_store.owned_keys()
        profile_data = {k: v for k, v in data.items() if k in owned}
        main_data = {k: v for k, v in data.items()
                     if k not in qa_names and k not in owned}

        # Only the keys that CHANGED. Sending the whole slice would make every
        # save a 34-row write and reinstate, in the database, exactly the
        # rewrite-everything cost this replaces.
        last_profile = self._last_written.get("_profile", {})
        changed_profile = {k: v for k, v in profile_data.items()
                           if k not in last_profile or last_profile[k] != v}

        # Each file is compared and written INDEPENDENTLY. That is the whole
        # point: ticking a QA step must not touch config.yaml, and changing a
        # setting must not rewrite the QA record.
        wrote = False
        if force or self._last_written.get("_main") != main_data or not config_file.exists():
            if config_file.exists() and config_file.stat().st_size > 0:
                try:
                    shutil.copy2(config_file, backup_file)
                    logger.debug(f"Backed up config to {backup_file}")
                except Exception as e:
                    logger.warning(f"Failed to create backup: {e}")
            self._atomic_write(config_file, main_data)
            logger.info(f"Saved config to {config_file}")
            wrote = True

        # The sidecar is written only when there IS QA state, so a normal user
        # who never runs METATV_DEV never grows the file at all. Compared
        # against the declared defaults rather than truthiness — two of these
        # fields are collapse flags that default to True.
        if qa_data and qa_data != _qa_defaults(type(self)):
            if force or self._last_written.get("_qa") != qa_data or not qa_file.exists():
                self._atomic_write(qa_file, qa_data)
                logger.debug(f"Saved QA state to {qa_file}")
                wrote = True

        # Queued, never written on this thread. `save()` is called from 130
        # sites and most are click handlers; SQLite has one writer and a 30 s
        # busy_timeout, and this project has already watched a UI-thread write
        # block for 29.8 s behind a migration and freeze the app (core/watchlist.py
        # carries the scar). `record` returns at once.
        if changed_profile:
            profile_store.record(changed_profile)
            wrote = True

        if not wrote:
            logger.debug("Config unchanged since last write; skipping save")
            return

        # `data` is already detached from the model — model_dump() builds fresh
        # containers rather than handing back the live lists — so no further
        # copying is needed. That detachment is the load-bearing property, and
        # test_model_dump_does_not_alias_live_containers pins it.
        # `profile_data`, not `changed_profile`: this records the state now on
        # disk, so the next save can tell what moved. Storing only the delta
        # would make every key look changed on the save after the one that
        # wrote it.
        self._last_written = {"_main": main_data, "_qa": qa_data,
                              "_profile": profile_data}

    def _atomic_write(self, target: Path, payload: dict) -> None:
        """Write *payload* to *target* via a temp file and an atomic replace.

        Extracted so config.yaml and the QA sidecar cannot drift on how they
        are written — the temp-then-replace is what stops a crash mid-write
        leaving a truncated file, and that mattering for one of them means it
        matters for both.
        """
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.config_dir, delete=False, suffix=".yaml"
            ) as tmp:
                tmp_path = Path(tmp.name)
                yaml.dump(payload, tmp, Dumper=_YamlDumper, default_flow_style=False)
            tmp_path.replace(target)
        except Exception as e:
            logger.error(f"Failed to write {target}: {e}")
            try:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
            except OSError:
                pass  # best-effort cleanup of a temp file we are already abandoning
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
