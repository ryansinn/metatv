"""Special content detection and parsing for PPV, Live Events, and Sports"""

import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import yaml
from loguru import logger

from metatv.core.database import ChannelDB
from metatv.core.channel_name_utils import parse_platform_event
from metatv.core.event_datetime import parse_event_window
from metatv.core.fixture_titles import fixture_display_title, parse_fixture_opponents


# Built-in sport keyword map: canonical sport name → list of keywords to match.
# Mirrors metatv/data/sports_definitions.yaml — this is only the in-memory
# fallback used if the bundled YAML fails to read (see load_sports_definitions),
# so a keyword added to one must be added to the other.
_DEFAULT_SPORT_KEYWORDS: Dict[str, List[str]] = {
    'soccer': [
        'soccer', 'football', 'fifa', 'premier league', 'la liga',
        'bundesliga', 'serie a', 'ligue 1', 'champions league',
        'europa league', 'mls', 'liga mx', 'eredivisie', 'superliga',
        'flosoccer',
    ],
    'basketball': ['basketball', 'nba', 'wnba', 'euroleague', 'ncaa basketball'],
    'american_football': ['nfl', 'american football', 'ncaa football', 'superbowl', 'super bowl', 'flofootball'],
    'baseball': ['baseball', 'mlb', 'flobaseball'],
    'field_hockey': ['field hockey'],
    'hockey': ['ice hockey', 'hockey', 'nhl', 'stanley cup', 'flohockey'],
    'tennis': ['tennis', 'atp', 'wta', 'wimbledon', 'us open', 'roland garros', 'australian open', 'flotennis'],
    'boxing': ['boxing', 'wbc', 'wba', 'ibf', 'wbo'],
    'mma': ['ufc', 'mma', 'bellator', 'one fc', 'pfl', 'flograppling'],
    'racing': ['f1', 'formula 1', 'formula one', 'nascar', 'motogp', 'indycar', 'rally', 'floracing'],
    'cricket': ['cricket', 'ipl', 'test match', 'odi', 't20'],
    'rugby': ['rugby', 'six nations', 'super rugby', 'rugby league', 'rugby union', 'florugby'],
    'golf': ['golf', 'pga', 'masters', 'open championship', 'ryder cup'],
    'cycling': ['cycling', 'tour de france', 'vuelta', 'giro'],
    'wrestling': ['wwe', 'wrestling', 'aew', 'flowrestling'],
    'volleyball': ['volleyball', 'flovolleyball'],
    'swimming': ['swimming', 'floswimming'],
    'track': ['flotrack', 'athletics', 'track and field'],
}

# Built-in league keyword map: display name → list of keywords to match
_DEFAULT_LEAGUE_KEYWORDS: Dict[str, List[str]] = {
    'Premier League': ['premier league', 'epl'],
    'Champions League': ['champions league', 'ucl'],
    'Europa League': ['europa league', 'uel'],
    'La Liga': ['la liga'],
    'Bundesliga': ['bundesliga'],
    'Serie A': ['serie a'],
    'Ligue 1': ['ligue 1'],
    'MLS': ['mls'],
    'Liga MX': ['liga mx'],
    'NBA': ['nba'],
    'NFL': ['nfl'],
    'NHL': ['nhl'],
    'AHL': ['american hockey league', ' ahl '],
    'OHL': ['ontario hockey league', ' ohl '],
    'QMJHL': ['qmjhl', 'quebec hockey league', 'quebec junior hockey league', 'quebec major junior'],
    'WHL': ['western hockey league', ' whl '],
    'SHL': ['svensk hockey', ' shl '],
    'Hockey Ettan': ['hockey ettan'],
    'ECHL': [' echl '],
    'KHL': [' khl '],
    'Liiga': ['sm-liiga', 'liiga'],
    'DEL': [' del ', 'deutsche eishockey liga'],
    'Stanley Cup': ['stanley cup'],
    'MLB': ['mlb'],
    'UFC': ['ufc'],
    'Formula 1': ['formula 1', 'formula one', 'f1 '],
    'ATP': ['atp tour'],
    'WTA': ['wta tour'],
    'Wimbledon': ['wimbledon'],
    'US Open (Tennis)': ['us open tennis'],
    'IPL': ['ipl'],
    'Six Nations': ['six nations'],
    'Super Rugby': ['super rugby'],
    'WWE': ['wwe'],
}

# Context-scoped keyword precedence: mirrors metatv/data/sports_definitions.yaml's
# sport_keyword_overrides section — this is only the in-memory fallback used if
# the bundled YAML fails to read, so a change to one must change the other. Each
# entry is checked BEFORE the global sport_kw first-match loop in
# parse_sports_channel: a keyword can mean different sports in different
# category contexts (same specific-beats-global precedence as the region rule).
_DEFAULT_SPORT_KEYWORD_OVERRIDES: List[Dict[str, str]] = [
    {'category_token': 'flo', 'keyword': 'football', 'sport': 'american_football'},
]

_VS_PATTERN = re.compile(r'\s+(?:vs\.?|v\.?)\s+', re.IGNORECASE)
_TRAILING_JUNK = re.compile(r'[\[\(].*$')  # Strip trailing "[EVENT]", "(HD)", etc.

# Bundled definitions file — shipped with the app, checked into git.
_BUNDLED_DEFINITIONS = Path(__file__).parent.parent / 'data' / 'sports_definitions.yaml'


#: (path, mtime_ns) -> (sport_keywords, league_keywords, sport_keyword_overrides).
#: Not lru_cache: the key has to include the file's mtime, and ``config`` is not
#: hashable.
_DEFINITIONS_CACHE: "dict[tuple[str, int | None], Tuple[Dict, Dict, List[Dict[str, str]]]]" = {}

_STAMP_TTL_S = 1.0
#: A hot backfill calls load_sports_definitions once per row; re-statting the
#: override file per row is 785k syscalls per pass. Within this TTL the last
#: (path, mtime) key is reused unchecked — a Settings edit still lands within
#: a second, which no caller can observe.
_last_stamp_check: dict = {"path": None, "at": 0.0, "key": None}


def get_user_definitions_path(config=None) -> Path:
    """Return path to the user's personal definitions override file.

    This file is created ONLY by the settings UI when the user explicitly
    customises definitions. It should never be auto-created by the code.
    """
    if config is not None:
        return Path(config.config_dir) / 'sports_definitions.yaml'
    return Path.home() / '.config' / 'metatv' / 'sports_definitions.yaml'


def _load_definitions_file(path: Path) -> Tuple[Dict, Dict, List[Dict[str, str]]]:
    """Read a definitions YAML and return (sport_keywords, league_keywords, sport_keyword_overrides)."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return (
        data.get('sport_keywords') or {},
        data.get('league_keywords') or {},
        data.get('sport_keyword_overrides') or [],
    )


def _load_definitions_cached(config=None) -> Tuple[Dict, Dict, List[Dict[str, str]]]:
    """Load sport keywords, league keywords, and sport keyword overrides.

    Always reads from the bundled ``metatv/data/sports_definitions.yaml`` as the
    base. If the user has a personal override file at
    ``~/.config/metatv/sports_definitions.yaml`` (written by the settings UI),
    those entries are merged on top — new sports/leagues/overrides are added,
    existing keyword lists are extended.

    The user override file is never auto-created by this function.

    Args:
        config: Application Config object (optional). Used only to locate the
                user's config directory.

    Returns:
        Tuple of (sport_keywords, league_keywords, sport_keyword_overrides).
    """
    # Cached on the override file's identity + mtime, so a Settings edit still
    # takes effect on the next call while a re-read costs nothing.
    #
    # This is called ONCE PER CHANNEL by parse_sports_channel, and reading and
    # parsing the bundled YAML takes **4.34 ms**. That was the entire cost of
    # parse_sports_channel — measured, 4.34 ms of 4.34 ms. On the owner's
    # library it made the classification pass 736 rows/s, so re-classifying
    # 785,163 rows took 18 minutes, and ProviderLoader's own categorize step
    # was paying the same toll on every refresh.
    #
    # Someone already knew: channel_name_utils._sports_keywords_flat() carries
    # an lru_cache and a comment saying load_sports_definitions() reads a YAML
    # file. The cache went on the call site that was noticed rather than on the
    # function, so the hot caller kept paying.
    user_path = get_user_definitions_path(config)
    now = time.monotonic()
    if (_last_stamp_check["path"] == str(user_path)
            and (now - _last_stamp_check["at"]) < _STAMP_TTL_S):
        cache_key = _last_stamp_check["key"]
    else:
        try:
            stamp = user_path.stat().st_mtime_ns
        except OSError:
            stamp = None                      # no override file — a valid state
        cache_key = (str(user_path), stamp)
        _last_stamp_check.update(path=str(user_path), at=now, key=cache_key)
    cached = _DEFINITIONS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Load bundled defaults
    try:
        sport_kw, league_kw, overrides = _load_definitions_file(_BUNDLED_DEFINITIONS)
    except Exception as e:
        logger.warning(f"Failed to read bundled sports definitions: {e} — using in-memory defaults")
        sport_kw = {k: list(v) for k, v in _DEFAULT_SPORT_KEYWORDS.items()}
        league_kw = {k: list(v) for k, v in _DEFAULT_LEAGUE_KEYWORDS.items()}
        overrides = [dict(entry) for entry in _DEFAULT_SPORT_KEYWORD_OVERRIDES]

    # Merge user overrides if the settings UI has created them. The stamp in
    # the cache key already answers "does the override file exist" — a
    # separate exists() would be a second stat() per cache miss, the very
    # syscall this TTL exists to avoid.
    if cache_key[1] is not None:
        try:
            user_sports, user_leagues, user_overrides = _load_definitions_file(user_path)
            for sport, keywords in user_sports.items():
                existing = set(sport_kw.get(sport, []))
                sport_kw.setdefault(sport, []).extend(k for k in keywords if k not in existing)
            for league, keywords in user_leagues.items():
                existing = set(league_kw.get(league, []))
                league_kw.setdefault(league, []).extend(k for k in keywords if k not in existing)
            # Appended after the bundled ones — same "first match wins" order
            # as the keyword lists above, so a bundled override still takes
            # precedence unless the user's own entry is genuinely new.
            overrides = overrides + list(user_overrides)
            logger.debug(f"Merged user sports definitions from {user_path}")
        except Exception as e:
            logger.warning(f"Failed to read user sports definitions ({user_path}): {e}")

    # Callers only READ these (parse_sports_channel iterates them), so one
    # shared object per key is correct. Anything that needs to mutate must copy.
    _DEFINITIONS_CACHE[cache_key] = (sport_kw, league_kw, overrides)
    return sport_kw, league_kw, overrides


def load_sports_definitions(config=None) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Load sport and league keyword maps.

    See :func:`_load_definitions_cached` for the caching/merge behavior this
    wraps. Sibling :func:`load_sport_keyword_overrides` reads the third element
    of the same cached load.

    Args:
        config: Application Config object (optional). Used only to locate the
                user's config directory.

    Returns:
        Tuple of (sport_keywords, league_keywords) dicts.
    """
    sport_kw, league_kw, _overrides = _load_definitions_cached(config)
    return sport_kw, league_kw


def load_sport_keyword_overrides(config=None) -> List[Dict[str, str]]:
    """Load context-scoped sport keyword overrides (see the YAML's
    ``sport_keyword_overrides`` section and ``_DEFAULT_SPORT_KEYWORD_OVERRIDES``).

    Each entry is ``{'category_token': ..., 'keyword': ..., 'sport': ...}`` and
    is checked by :func:`parse_sports_channel` before the generic sport
    first-match loop — see that function's docstring.

    Args:
        config: Application Config object (optional). Used only to locate the
                user's config directory.

    Returns:
        List of override dicts, bundled entries first, user entries appended.
    """
    _sport_kw, _league_kw, overrides = _load_definitions_cached(config)
    return overrides


@lru_cache(maxsize=4096)
def _keyword_pattern(keyword: str) -> "re.Pattern[str]":
    """A whole-token matcher for one sport/league keyword.

    ``if keyword in name`` is what this replaces, and the failures it produced
    were not subtle — measured across the 35,181 channels tagged as sports,
    **2,089 league assignments** came from a keyword appearing inside an
    unrelated word::

        'US| FANDUEL TV'           -> Europa League   FAND-UEL
        'CITY| ABC WBAY GREENBAY'  -> NBA             GREE-NBA-Y
        '4k| TF1 HDR/UHD/4K'       -> Formula 1       T-F1
        '4K - Conflict (2024)'     -> NFL             co-NFL-ict

    Lookarounds on alphanumerics rather than ``\b``: several keywords end in a
    digit (``f1``, ``av1``) where ``\b`` sits in the wrong place, and several
    are phrases with internal spaces.

    Keywords are stripped before compiling. Some are written with padding —
    ``' ahl '``, ``' ohl '``, ``' whl '`` — which was a hand-rolled attempt at
    exactly this boundary, and it is why the AHL never matched: the channels are
    named ``AHL-TEAM|…`` and a leading space cannot match a hyphen. Stripping
    them and doing the boundary properly fixes those without a data edit.
    """
    token = re.escape(keyword.strip().lower())
    return re.compile(rf"(?<![a-z0-9]){token}(?![a-z0-9])")


def _matches_keyword(keywords: "list[str]", *haystacks: str) -> bool:
    """Whether any keyword appears as a whole token in any haystack."""
    return any(
        _keyword_pattern(kw).search(hay)
        for kw in keywords
        if kw and kw.strip()
        for hay in haystacks
    )


@lru_cache(maxsize=256)
def _stem_pattern(stem: str) -> "re.Pattern[str]":
    """A word-START matcher for one descriptive sport word.

    Whole-token matching is right for an acronym and WRONG for a stem, and the
    difference is not stylistic. ``sport`` under a whole-token rule matches
    "SPORT TV" and misses "SPORTSNET 360", "SPECTRUM SPORTS 1" and "CBS SPORTS
    NETWORK" — measured, that single keyword took **11,451 real sports channels
    out of the sports view**, which is a far bigger error than the false
    positives whole-token matching was introduced to remove.

    So the guard is only on the LEFT edge: "firefighter" does not contain the
    word ``fight``, but "fighting" does.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(stem.strip().lower())}")


def _matches_stem(stems: "tuple[str, ...]", *haystacks: str) -> bool:
    """Whether any stem starts a word in any haystack."""
    return any(
        _stem_pattern(stem).search(hay)
        for stem in stems
        if stem and stem.strip()
        for hay in haystacks
    )


def parse_sports_channel(channel: ChannelDB, config=None) -> Dict[str, Any]:
    """Extract sport_type, league_name, and team_name from a sports channel.

    Channels that do not match any keyword are assigned sport_type='unknown'
    so they remain visible in the Sports view rather than being silently excluded.

    Args:
        channel: The channel to parse.
        config: Optional Config for user-customized keyword maps.

    Returns:
        Dict with keys: sport_type (str), league_name (str|None), team_name (str|None).
    """
    result: Dict[str, Any] = {
        'sport_type': 'unknown',
        'league_name': None,
        'team_name': None,
    }

    sport_kw, league_kw = load_sports_definitions(config)
    overrides = load_sport_keyword_overrides(config)

    name = channel.name or ''
    category = (channel.category or '').lstrip('#').strip()
    name_lower = name.lower()
    category_lower = category.lower()

    # --- Sport detection (first match wins) ---
    # Context-scoped overrides are checked FIRST: a keyword can mean different
    # sports in different category contexts (same specific-beats-global
    # precedence as the region rule). A match here skips the generic loop
    # entirely — league detection and everything after runs unchanged.
    sport_matched = False
    for entry in overrides:
        if (_matches_keyword([entry.get('category_token', '')], category_lower)
                and _matches_keyword([entry.get('keyword', '')], name_lower)):
            result['sport_type'] = entry['sport']
            sport_matched = True
            break

    if not sport_matched:
        for sport, keywords in sport_kw.items():
            if _matches_keyword(keywords, name_lower, category_lower):
                result['sport_type'] = sport
                break

    # --- League detection ---
    for league_name, keywords in league_kw.items():
        if _matches_keyword(keywords, name_lower, category_lower):
            result['league_name'] = league_name
            break

    # --- Team extraction via "vs" / "v" pattern ---
    # Split on " | " (with surrounding spaces) to get pipe-delimited segments,
    # then scan from the end for a segment containing a "vs" matchup. This
    # correctly handles names like "EN | NHL | Panthers vs Bruins" where
    # the matchup is always in the last meaningful segment.
    segments = [s.strip() for s in name.split(' | ')]
    for segment in reversed(segments):
        vs_match = _VS_PATTERN.search(segment)
        if vs_match:
            left = segment[:vs_match.start()].strip()
            right = segment[vs_match.end():].strip()
            # Strip trailing tags like "[EVENT]", "(HD)"
            right = _TRAILING_JUNK.sub('', right).strip()
            if left and right:
                result['team_name'] = f"{left} vs {right}"
            break

    return result


def detect_ppv_channel(channel: ChannelDB) -> bool:
    """Detect if channel is a PPV event
    
    PPV Pattern: Contains date/time in channel name + "PPV" keyword
    Example: "End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | 8K EXCLUSIVE | US: SOCCER PPV 1"
    """
    name = channel.name.lower()
    
    # Must have "ppv" keyword
    if 'ppv' not in name:
        return False
    
    # Must have date pattern (DD-MM-YYYY or MM-DD-YYYY)
    date_pattern = r'\d{2}-\d{2}-\d{4}'
    if not re.search(date_pattern, channel.name):
        return False
    
    # Filter out organizational headers (no stream_url)
    if not channel.stream_url:
        return False
    
    return True


def detect_live_event_channel(channel: ChannelDB) -> bool:
    """Detect if channel is a live event
    
    Live Event Pattern: [EVENT] or [LIVE-EVENT] tag in channel name
    Example: "4K| SKY SPORTS UHD [EVENT]"
    """
    name = channel.name.lower()
    
    # Check for event tags
    if '[event]' in name or '[live-event]' in name:
        return True
    
    return False


def detect_platform_event_channel(channel: ChannelDB) -> bool:
    """Detect an EPG-embedded event feed: "US (Peacock 01) | Title (timestamp)".

    These encode a scheduled programme (or an always-available network feed) in the
    channel name. Only the *scheduled* form (a real timestamp or the always-available
    sentinel) is a live event; the plain network form ("US (P+) Title", no time) is a
    regular channel and falls through to the keyword-based detectors.
    """
    pe = parse_platform_event(channel.name or "")
    return bool(pe and (pe.start_time is not None or pe.always_available))


#: Keywords matched at the START of a word. Each one is here because the data
#: says prefix matching adds real sports channels and adds almost nothing else —
#: measured across the owner's 467,373 distinct names, counting exactly what the
#: prefix rule catches that a whole-token rule misses:
#:
#:   sport    2,545 rows  SPORTS(2300) SPORTSNET(113) SPORTOWE SPORTING SPORT1
#:   moto       270 rows  MOTOR(66) MOTOGP(64) MOTORVISION(32) MOTORSPORT(8)
#:   formula     73 rows  FORMULA1(71) FORMULA2
#:   f1          35 rows  F1TV — and the left guard still blocks TF1
#:   rugby       27 rows  RUGBYPASS(26) RUGBYSTAR
#:   espn        10 rows  ESPN2 ESPNU ESPN3 ESPN8 ESPNEWS
#:   tsn          5 rows  TSN1..TSN5
#:
#: The only false catch in all of that is MOTOWN (7 rows), which lands in the
#: sports view with no sport and no league. That is the trade, stated.
SPORTS_GATE_STEMS: tuple[str, ...] = (
    'sport', 'moto', 'formula', 'f1', 'rugby', 'espn', 'tsn',
)

#: Keywords matched as WHOLE tokens, because prefix matching demonstrably pulls
#: in the wrong thing:
#:
#:   bein      "BEING MARY JANE", "Being Flynn"      137 wrong rows
#:   fight     "Freedom Fighters"                    300 wrong rows
#:   football  "FOOTBALLERS WIVES"
#:   cricket   "The Crickets Dance", "THE CRICKETER"
#:   hockey    "HOCKEYVADERS"        baseball  "The Baseballs" (a band)
#:
#: and the acronyms, which hide inside unrelated words — nba in GREENBAY, nfl in
#: Conflict. For soccer/boxing/basketball the two rules matched identically on
#: real data, so they sit here with the rest of the vocabulary.
#: FloSports verticals (2026-09-03). ``detect_sports_channel`` and
#: ``parse_sports_channel`` are two separate sets over two separate vocabularies
#: — see the module note above the gate — and "wrestling" was in the keyword
#: map (``_DEFAULT_SPORT_KEYWORDS``/``sports_definitions.yaml``) all along but
#: never in the gate, so 16 "| wrestling: …" rows never reached the sports view
#: to be labelled. "flosports"/"flo network" name the network itself — all FLO
#: content is sports, whatever vertical it carries. Each flo-vertical compound
#: is a whole token, same as the acronyms above: it never appears inside another
#: word (unlike the bare stem "flo", which would reach "florida"/"flower" and is
#: deliberately not added here).
SPORTS_GATE_TOKENS: tuple[str, ...] = (
    'nba', 'nfl', 'nhl', 'mlb', 'ufc',
    'bein', 'sky sports', 'fox sports', 'nbc sports',
    'football', 'soccer', 'boxing', 'kickboxing', 'basketball', 'baseball',
    'cricket', 'tennis', 'hockey', 'racing', 'fight',
    'premier league', 'champions league', 'la liga', 'bundesliga',
    'flosports', 'flo network', 'wrestling', 'volleyball', 'swimming',
    'flotrack', 'flofootball', 'flowrestling', 'flohockey', 'floracing',
    'flograppling', 'flobaseball', 'florugby', 'flosoccer', 'flotennis',
    'flovolleyball', 'floswimming',
)


def detect_sports_channel(channel: ChannelDB) -> bool:
    """Detect if channel is a sports channel
    
    Sports Pattern: Contains sports keywords in name or category
    """
    name = channel.name.lower()
    category = (channel.category or "").lstrip('#').strip().lower()

    return (_matches_stem(SPORTS_GATE_STEMS, name, category)
            or _matches_keyword(list(SPORTS_GATE_TOKENS), name, category))


def parse_ppv_event(channel: ChannelDB) -> Dict[str, Any]:
    """Parse PPV event details from channel name
    
    Example: "End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | 8K EXCLUSIVE | US: SOCCER PPV 1"
    
    Returns:
        dict with keys: event_name, start_time, quality, sport_type, stream_number
    """
    result = {
        'event_name': None,
        'start_time': None,
        'quality': None,
        'sport_type': None,
        'stream_number': None,
        'stop_time': None,
    }
    
    parts = channel.name.split('|')
    
    # Extract event name (usually second part after status)
    if len(parts) >= 2:
        event_name = parts[1].strip()
        if event_name and event_name.lower() not in ['all', 'end', 'live']:
            result['event_name'] = event_name
    
    # Extract date and time — one chokepoint, all three provider date forms.
    # This used to be a local DD-MM-YYYY regex plus `re.search(r'(\d{2}):(\d{2})')`,
    # which (a) knew one of the three shapes, covering 654 of 1,358 dated rows,
    # (b) ignored the timezone named in the string, and (c) took the FIRST HH:MM
    # anywhere in the name — including one inside the event title.
    _window = parse_event_window(channel.name)
    result['start_time'] = _window.start
    # The provider's own end, present only on the slot form. Carried alongside
    # the start so "still on" is a fact rather than an assumed duration.
    result['stop_time'] = _window.stop
    
    # Extract quality markers
    name_upper = channel.name.upper()
    if '8K' in name_upper:
        result['quality'] = '8K'
    elif '4K' in name_upper or 'UHD' in name_upper:
        result['quality'] = '4K'
    elif 'FHD' in name_upper or '1080' in name_upper:
        result['quality'] = 'FHD'
    elif 'HD' in name_upper or '720' in name_upper:
        result['quality'] = 'HD'
    
    # Extract sport type from channel name
    name_lower = channel.name.lower()
    # (stems matched at a word start, tokens matched whole) — the same split
    # detect_sports_channel uses, for the same reason: 'football' must reach
    # FOOTBALLERS while 'nfl' must not reach CONFLICT.
    sport_keywords = {
        'soccer':     (('soccer', 'football'), ('fifa',)),
        'basketball': (('basketball',), ('nba',)),
        'football':   (('american football',), ('nfl',)),
        'boxing':     (('boxing', 'fight'), ()),
        'mma':        (('bellator',), ('ufc', 'mma')),
        'racing':     (('formula', 'racing', 'nascar'), ('f1',)),
        'hockey':     (('hockey',), ('nhl',)),
        'baseball':   (('baseball',), ('mlb',)),
    }

    for sport, (stems, tokens) in sport_keywords.items():
        if (_matches_stem(stems, name_lower)
                or _matches_keyword(list(tokens), name_lower)):
            result['sport_type'] = sport
            break
    
    # Extract stream number (e.g., "PPV 1", "PPV 2")
    stream_match = re.search(r'PPV\s+(\d+)', channel.name, re.IGNORECASE)
    if stream_match:
        result['stream_number'] = int(stream_match.group(1))
    
    return result


def detect_and_categorize_channel(channel: ChannelDB) -> Optional[str]:
    """Detect and categorize channel into special views

    Priority:
        1. PPV (has date/time + PPV keyword)
        2. Live Event ([EVENT] tag, or EPG-embedded "REGION (NETWORK) | Title (time)")
        3. Sports (has sports keywords)

    Returns:
        'ppv', 'live_event', 'sports', or None
    """
    # TREX-style organizational headers start with '#' — not actual channels
    if channel.name and channel.name.startswith('#'):
        return None

    # Priority 1: PPV
    if detect_ppv_channel(channel):
        return 'ppv'

    # Priority 2: Live Events — [EVENT] tag or EPG-embedded scheduled programme
    if detect_live_event_channel(channel) or detect_platform_event_channel(channel):
        return 'live_event'
    
    # Priority 3: Sports
    if detect_sports_channel(channel):
        return 'sports'
    
    return None


def _apply_fixture_title(channel: ChannelDB) -> None:
    """Store a fixture's matchup title (SPORT-8), never blanking an existing one.

    ``fixture_display_title()`` is the ONE chokepoint (``fixture_titles.py``)
    for turning a fixture's raw provider slot string into what the Sports
    list should show. None means "no derivable matchup" — the row's own
    ``detected_title``, usually set by the DIFFERENT ``update_detected_prefixes``
    chokepoint, is left exactly as it is. Shared by the ``ppv`` and ``sports``
    branches below so the rule lives in one place, not two.
    """
    title = fixture_display_title(channel.name or "")
    if title:
        channel.detected_title = title


def update_channel_special_content(channel: ChannelDB, config=None) -> bool:
    """Update channel with special content categorization.

    Args:
        channel: Channel to categorize and enrich.
        config: Optional Config for user-customized keyword maps.

    Returns:
        True if channel was categorized, False otherwise.
    """
    special_view = detect_and_categorize_channel(channel)

    if not special_view:
        return False

    channel.special_view = special_view

    if special_view == 'ppv':
        ppv_data = parse_ppv_event(channel)
        channel.event_start_time = ppv_data['start_time']
        channel.event_stop_time = ppv_data['stop_time']
        channel.sport_type = ppv_data['sport_type']
        # PPV fixtures (the day-name matchup form) carry opponents same as
        # the sports branch below — same chokepoint (SPORT-4).
        channel.event_team_a, channel.event_team_b = parse_fixture_opponents(channel.name or "")
        _apply_fixture_title(channel)

        metadata = ppv_data.copy()
        for _key in ('start_time', 'stop_time'):
            if metadata.get(_key):
                metadata[_key] = metadata[_key].isoformat()
        channel.event_metadata = metadata

    elif special_view == 'live_event':
        # EPG-embedded event feeds carry a network/time in the name; enrich from them.
        pe = parse_platform_event(channel.name or "")
        if pe is not None:
            channel.event_start_time = pe.start_time
            # This grammar names a start and nothing else; "still on" falls back
            # to DEFAULT_EVENT_DURATION. Assigned rather than left alone so a row
            # that changes shape cannot keep a stop from its previous form.
            channel.event_stop_time = None

            metadata: Dict[str, Any] = {
                'event_name': pe.title or None,
                'network': pe.network,            # browseable broadcaster/brand
                'channel_num': pe.channel_num or None,
                'region': pe.region,
                'availability': 'always' if pe.always_available else 'scheduled',
            }
            if pe.start_time:
                metadata['start_time'] = pe.start_time.isoformat()
            channel.event_metadata = metadata

            # These are sports events — enrich sport/league/team for the sports facets.
            sports_data = parse_sports_channel(channel, config)
            channel.sport_type = sports_data['sport_type']
            channel.league_name = sports_data['league_name']
            channel.team_name = sports_data['team_name']

    elif special_view == 'sports':
        sports_data = parse_sports_channel(channel, config)
        channel.sport_type = sports_data['sport_type']
        channel.league_name = sports_data['league_name']
        channel.team_name = sports_data['team_name']
        # A dated fixture can classify as 'sports' rather than 'ppv' — 927 of them
        # do — and this branch extracted no time at all, so the schedule column and
        # the Q19 staleness cross-check had nothing to read. Same chokepoint as the
        # ppv branch; None for the 24/7 racks, which is correct rather than a miss.
        _window = parse_event_window(channel.name or "")
        channel.event_start_time = _window.start
        channel.event_stop_time = _window.stop
        # Fixture opponents (SPORT-4) — same chokepoint as the ppv branch;
        # None for the 24/7 racks and racing "at venue" listings, which is
        # correct rather than a miss.
        channel.event_team_a, channel.event_team_b = parse_fixture_opponents(channel.name or "")
        _apply_fixture_title(channel)

    return True
