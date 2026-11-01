"""Content labels: content types, AI provenance, restricted-content detection,
descriptor groups and the word lists that classify a name's residue — split
out of channel_name_utils (ledger F30).
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

from metatv.core.tag_confidence import CONF_DENOTED, CONF_STRONG_PRIOR

# Age-rating prefix tokens — a viewing restriction, and NEVER a locale claim, so a row
# carrying one may not inherit a sibling's region (channel_ingestion). One definition,
# read by classify_trailing_metadata, step 7 of parse_channel_name, and by ingestion.
AGE_RATING_PREFIXES: frozenset[str] = frozenset({"18+", "16+", "12+"})

#: Name prefixes a provider puts on an event that has already finished
#: ("End | Pacers vs. Bucks", "ENDED | AZTEC VS. GALLUP"). The listing stays up
#: after the game; Settings → "Show finished events" decides whether it shows.
ENDED_EVENT_PREFIXES: frozenset[str] = frozenset({"END", "ENDED"})

#: Every event-status prefix: on now, coming up, finished. LIVE and NEXT stay
#: visible; only the finished ones are hidden (ENDED_EVENT_PREFIXES above).
EVENT_STATUS_PREFIXES: frozenset[str] = frozenset({"LIVE", "NEXT"}) | ENDED_EVENT_PREFIXES

#: Prefixes that only say "this is a live channel" ("TV| A3 NEW YORK 02 WCBS
#: CBS" — 550 US local stations on TREX). A content type, not a locale.
LIVE_TV_PREFIXES: frozenset[str] = frozenset({"TV"})



#: Spelled-out league names prefixing a dash-matchup fixture's team A — "MAJOR
#: LEAGUE BASEBALL DIAMONDBACKS - PHILLIES" names DIAMONDBACKS/PHILLIES, not
#: "MAJOR LEAGUE BASEBALL DIAMONDBACKS" (SPORT-4, core/fixture_titles.py). Only
#: MLB is corpus-measured (2026-09-02); the rest mirror abbreviations already
#: known above/in special_content.py's league_keywords, for parity — ambiguous
#: prefixes are left alone rather than guessed (bias to recall).
FIXTURE_LEAGUE_NAME_PREFIXES: tuple[str, ...] = (
    "MAJOR LEAGUE BASEBALL", "NATIONAL BASKETBALL ASSOCIATION",
    "NATIONAL FOOTBALL LEAGUE", "NATIONAL HOCKEY LEAGUE",
    "ENGLISH PREMIER LEAGUE",
)

# ── Name-derived cast: words that prove a trailing residual is NOT a person ──── #
# ``parse_channel_name().trailing`` captures whatever a provider appended after the
# year — "EN - Adaptation. 4K (2002) NICOLAS CAGE". Measured over the owner's
# 414,800 VOD rows, 8,257 names carry such a residual across 917 distinct values
# and only about half are people — the rest are language/format/studio/collection
# labels (POLSKI 918, 4K 652, DOKUMENT 531, DUBBING 221, NAPISY 122, BG-AUDIO 54,
# PIXAR 52). Emitting those as ``person`` tags would not be "capture generously
# with low confidence" (DR-0006) — confidence ranks a real guess, it does not
# launder one the vocabulary already knows is wrong — so a residual containing
# any of these is never read as a person; the genuinely unclassifiable remainder
# becomes a LOW-confidence person tag.
# Billing qualifiers a provider tacks onto a credited name ("CILLIAN MURPHY
# UNCREDITED"): stripped from the END of the name, never part of the person.
CREDIT_QUALIFIER_WORDS: frozenset[str] = frozenset({"UNCREDITED", "CAMEO", "VOICE"})

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
# Some providers stamp a trailing parenthetical marker to flag how a channel was
# produced. Two DISTINCT user-facing concepts (a user may tolerate an AI dub but
# not AI-generated content), so two content_type facet values: "(AI Generated)"
# — the CONTENT itself is AI-generated (fabricated "[MV] Lady Gaga - Born To Win
# - ft. Sia & The Weeknd (AI Generated)") → "ai_generated"; "(AI)" — an
# AI-generated VOICEOVER/dub, not AI content ("PL - Bugonia (2025) Lektor (AI)",
# "Lektor" = Polish voice-over) → "ai_voiceover". Both match ONLY as a TRAILING
# marker (end of name, optional whitespace), case-insensitively — a mid-title
# parenthetical or bare "AI" without parens never matches, so "AI Superstars" /
# "Terminator (AI Uprising)" are never false positives.

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
# (``ppv``, ``live_event``, ``sports``, ``ai_generated``, ``ai_voiceover``) — NOT
# presentation-ready, so every surface showing a content_type VALUE (details-pane
# Tags chips, the recipe/tag-cloud pantry, Global Exclusions' "Content Provenance"
# section) routes it through :func:`content_type_display` for its English label;
# the slug stays the identity everywhere else. Value-display sibling of the
# details pane's ``_FACET_LABELS`` (names the facet TYPES, e.g. ``content_type``
# → "Content Type"); lives here per CLAUDE.md's lookup-table-home rule, beside the
# slugs' origin (``AI_GENERATED_VALUE`` / ``AI_VOICEOVER_VALUE``).
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
# display-grouping purposes, but they are NOT locales or platforms — they denote a
# content KIND, so their facet depends on media_type at tag time: live channel →
# `category:` (a live-channel kind/programming genre); movie/series → `genre:` (a
# VOD content descriptor). Routed by remap_content_descriptor_facets() in
# tag_decomposer.py, called from tag_backfill.py's _collect_tags() (the ONE
# per-channel tag builder). "Pay TV" is deliberately absent — it is a real
# distribution platform and correctly stays `platform:Pay TV`.
CONTENT_DESCRIPTOR_GROUPS: frozenset[str] = frozenset({
    "Adult", "Sports", "Kids", "Music", "News", "Religious", "24/7",
})

# ── Platform values that never get their own Discover shelf (PLAT-1) ─────────── #
# A `platform:` tag value here is skipped by platform_shelves.platform_shelf_values()
# however many titles carry it.  Curated data lives here, never a parallel set in
# the shelf module — a decomposer rename must move BOTH the shelf and this gate.
PLATFORM_SHELF_EXCLUDED_VALUES: frozenset[str] = frozenset({
    # Catch-all bucket for HBO/Hulu/Peacock/Paramount/PLAY — one shelf mixing five
    # brands is not "a platform"; splitting it needs more parsing (a separate project).
    "Other Streaming",
    # The other catch-all: DStv/OSN/Sky/STC/MyHD/GOtv/Digi are unrelated regional
    # pay-TV operators, not one streaming service a viewer would browse.
    "Pay TV",
    # Subtitle library mis-bucketed as a platform: mixed multi-language VOD.
    "SC",
    # Subtitle library mis-bucketed as a platform: Arabic-subtitled foreign films.
    "EAR",
})

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
# NOTE: this block used to describe RESTRICTED_NAME_TOKENS and
# RESTRICTED_PREFIX_TOKENS. NEITHER EXISTS. The function below matches on two
# things only: the user's "Adult" prefix GROUP (BASE_PREFIX_GROUPS["Adult"] plus
# their overrides) and config.restricted_keywords, which is empty by default.
# The stale text cost real time — it reads as though a shipped word-scan catches
# "XXX" anywhere in a name, and nothing does.
#
# Prefix-scoped matching is the DESIGN, not an omission, and the owner put the
# case better than the old comment did: a title containing "XXX" is not adult
# content. There is a whole `xXx` action franchise, and `A's to XXX` is a
# documentary ABOUT the industry rather than an example of it. A whole-name scan
# would hide both. The same applies to a bare "X" — "X Factor", "Generation X",
# "Malcolm X".
#
# That is why the only name-based signal is config.restricted_keywords, which
# ships EMPTY: the user decides, because only the user knows what they meant.
#: Provider COLLECTION labels that denote adult content on their own.
#:
#: Matched EXACTLY (case- and spacing-normalised), never as a substring. That is
#: deliberate and it is the same lesson as the title case above: "Young Adult"
#: is a legitimate genre, and a substring match on "ADULT" would hide it. Exact
#: match trades recall for precision, which is the right direction when the cost
#: of a false positive is hiding content the user wanted.
#:
#: A collection is a far better signal than a prefix code, because it does not
#: require anyone to have guessed the code. On the owner's library "FOR ADULTS"
#: holds 212 channels of which 184 were ALREADY flagged by prefix — the other 28
#: were the PORNBOX ones nobody had curated in yet. The collection knew.
ADULT_COLLECTION_LABELS: frozenset[str] = frozenset({
    "FOR ADULTS",
})


def _normalise_collection(value: Optional[str]) -> str:
    """Upper-case and collapse whitespace, for exact collection matching."""
    return " ".join((value or "").split()).upper()


def is_restricted(detected_prefix: Optional[str], name: str, config=None,
                  collection: Optional[str] = None) -> bool:
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
        except (AttributeError, TypeError, KeyError):
            adult_codes = set()  # silent: no Adult group configured — nothing to match
        if detected_prefix.strip().upper() in adult_codes:
            return True

    # A curated COLLECTION label. Checked after the prefix and before the
    # user's keywords, because it needs nobody to have guessed a provider's
    # code: "FOR ADULTS" carried 28 channels whose PORNBOX prefix was not in
    # any table. Exact match only — see ADULT_COLLECTION_LABELS.
    if collection and _normalise_collection(collection) in ADULT_COLLECTION_LABELS:
        return True

    keywords = getattr(config, "restricted_keywords", None) or []
    if keywords and name:
        lowered = name.lower()
        return any(k.strip().lower() in lowered for k in keywords if k and k.strip())
    return False


#: Words in a provider label that denote a CONTENT TYPE, not a collection —
#: "SWEDEN SOCCER PPV" is pay-per-view whatever else it is.
CONTENT_TYPE_WORDS: dict[str, str] = {"PAY PER VIEW": "ppv", "PPV": "ppv"}
