"""Preference engine — attribute-weighted scoring from user ratings.

Level 1: structured attributes (genre, director, cast) from MetadataDB.
Level 2: TF-IDF plot keywords extracted from MetadataDB.plot.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from loguru import logger

from metatv.core.media_mix import (
    MEDIA_MIX_AUTOMATIC, mix_media_types, resolve_media_share,
)


STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "can", "her",
    "his", "its", "their", "who", "what", "when", "where", "how", "why",
    "he", "she", "it", "they", "we", "you", "this", "that", "these",
    "those", "which", "all", "not", "no", "also", "into", "after", "before",
    "between", "while", "about", "out", "up", "only", "own", "over",
    "then", "so", "than", "too", "very", "just", "there", "through",
    "during", "each", "more", "both", "back", "other", "off", "such",
    "new", "first", "old", "high", "even", "life", "young", "two", "one",
    "same", "another", "most", "some", "any", "find", "make", "take",
    "come", "get", "give", "know", "look", "see", "tell", "film", "movie",
    "show", "series", "story", "world", "man", "woman", "men", "soon",
    "begins", "finds", "sets", "goes", "tries", "help", "try", "upon",
    "when", "your", "they", "them", "that", "have", "been", "were", "will",
    "their", "from", "with", "this", "that", "what", "into", "when",
    "after", "while", "about", "which", "over", "each", "must", "three",
    "four", "five", "time", "good", "long", "part", "well", "away",
    "only", "also", "back", "then", "want", "used", "goes", "once",
    "real", "keep", "face", "left", "side", "much", "hard", "days",
    "full", "home", "last", "next", "year", "play", "live", "turn",
    "move", "hand", "work", "down", "away", "again", "being", "still",
    "choice", "together",
    "everything", "something", "anything", "nothing", "someone", "anyone",
    "everyone", "nobody", "somebody", "noone", "none", "nowhere",
    "wherever", "whenever", "whatever",
    "however", "although", "because", "though", "since", "until", "unless",
    "place", "people", "things", "thing", "ways", "kind", "sort", "type",
    "every", "never", "always", "often", "later", "early", "maybe", "perhaps",
    "around", "against", "within", "without", "across", "along", "behind",
    "beneath", "beyond", "inside", "outside", "under", "above", "below",
    # Plot-pacing adverbs
    "abruptly", "suddenly", "eventually", "quickly", "slowly",
    # Plot-arc verbs — describe story structure, not preference
    "discover", "reveal", "escape", "return", "realize",
    "struggle", "decide", "learn", "begin", "attempt",
    # Generic social/group nouns
    "population", "community", "society", "crowd",
    "family", "party", "member", "leader", "fellow",
    # Vague adjectives that appear across all genres
    "wealthy", "dangerous", "mysterious", "powerful", "ancient",
    "deadly", "unlikely", "hidden", "unknown", "legendary",
    "famous", "local", "former",
    # Broad nouns — too generic to carry preference signal
    "world", "drama", "system", "force", "power",
    "journey", "quest", "mission", "battle",
})

MAX_CORPUS_FREQ: float = 0.35  # drop words appearing in >35% of all plots

# A single performer/director appearing in one liked title is noise, not taste:
# an actor must show up across at least this many rated/favorited items before it
# carries any weight, so the recommendations never become "all about" one face.
ACTOR_MIN_SUPPORT: int = 2
# Per-item actor contribution — deliberately small ("just an indication"): genre and
# director are the load-bearing signals; a matched cast member only nudges.
ACTOR_WEIGHT: float = 0.35

# Within-a-single-generation diversity: once a recommendation with a given liked
# performer/director is placed, the NEXT candidate sharing that person is knocked down
# by this factor per prior appearance, so items *without* that person get room to
# surface. It is NOT a stored weight — it only shapes THIS list; engaging with the
# surfaced item (queue / like / dislike) removes it, so the next refresh rotates other
# same-person content back in.
PEOPLE_DIVERSITY_DECAY: float = 0.5
# Only the top slice by score is greedily re-ranked for people-diversity (the tail
# never surfaces) — bounds the O(n²) pass on large libraries.
_DIVERSITY_HEAD: int = 120

# Per-field multipliers applied when a signal is accumulated (genre/director/actor)
# or when a candidate's field is scored (keyword). Genre is the reference unit at
# 1.0; a director match is worth more than a genre match, a cast match much less.
GENRE_WEIGHT: float = 1.0
DIRECTOR_WEIGHT: float = 1.5
KEYWORD_WEIGHT: float = 0.4

# Impression decay — every time an item is shown, its score is knocked down by
# this fraction, never below IMPRESSION_DECAY_FLOOR of the original.
IMPRESSION_DECAY: float = 0.04
IMPRESSION_DECAY_FLOOR: float = 0.4

# How many already-liked items may occupy the capped list; the rest of the slots
# go to fresh discoveries.
LIKED_CAP: int = 3


@dataclass(frozen=True)
class RecScoringSettings:
    """User-tunable dials for the recommendation scorer.

    Every field defaults to the module constant it steers, so the bare
    ``RecScoringSettings()`` reproduces the shipped behavior exactly — the panel
    is for steering, not required setup. Frozen and passed by parameter: there is
    no global mutable scoring state.

    Attributes:
        genre_weight: Multiplier on genre affinity accumulated from a signal.
        director_weight: Multiplier on director affinity.
        actor_weight: Multiplier on cast affinity ("just an indication").
        keyword_weight: Multiplier on the plot-keyword field when scoring.
        actor_min_support: How many rated/favorited titles a performer must appear
            in before carrying any weight (corroboration gate).
        people_diversity_decay: Per prior appearance knock-down applied by the
            within-generation people-diversity re-rank (1.0 = no spreading).
        impression_decay: Score reduction per recorded impression.
        liked_cap: Maximum already-liked items in the returned list.
        media_mix: ``None`` (rank order stands — the bare-engine default), the
            string ``"automatic"`` (√-damped share of the user's engagement), or
            an explicit movie share in 0.0–1.0.
    """

    genre_weight:           float = GENRE_WEIGHT
    director_weight:        float = DIRECTOR_WEIGHT
    actor_weight:           float = ACTOR_WEIGHT
    keyword_weight:         float = KEYWORD_WEIGHT
    actor_min_support:      int   = ACTOR_MIN_SUPPORT
    people_diversity_decay: float = PEOPLE_DIVERSITY_DECAY
    impression_decay:       float = IMPRESSION_DECAY
    liked_cap:              int   = LIKED_CAP
    media_mix: str | float | None = None

    @classmethod
    def from_config(cls, config) -> "RecScoringSettings":
        """Build settings from the user's config, falling back to the defaults.

        Every ``rec_*`` config field is ``None`` until the user actually moves a
        dial, so an untouched config yields the shipped defaults and a later
        change to a default flows through automatically. The one inversion is the
        media mix: ``rec_media_mix = None`` means **Automatic** (the app default),
        while a float is the user's explicit movie share.
        """
        defaults = cls()

        def _dial(name: str, default):
            value = getattr(config, name, None)
            return default if value is None else value

        raw_mix = getattr(config, "rec_media_mix", None)
        return cls(
            genre_weight=float(_dial("rec_weight_genre", defaults.genre_weight)),
            director_weight=float(_dial("rec_weight_director", defaults.director_weight)),
            actor_weight=float(_dial("rec_weight_actor", defaults.actor_weight)),
            keyword_weight=float(_dial("rec_weight_keyword", defaults.keyword_weight)),
            actor_min_support=int(_dial("rec_actor_min_support", defaults.actor_min_support)),
            people_diversity_decay=float(
                _dial("rec_people_diversity_decay", defaults.people_diversity_decay)
            ),
            impression_decay=float(_dial("rec_impression_decay", defaults.impression_decay)),
            liked_cap=int(_dial("rec_liked_cap", defaults.liked_cap)),
            media_mix=MEDIA_MIX_AUTOMATIC if raw_mix is None else float(raw_mix),
        )


# The shipped dials — used whenever a caller passes no settings.
DEFAULT_REC_SETTINGS: RecScoringSettings = RecScoringSettings()


@dataclass
class AttributeWeights:
    """Accumulated preference signal from rated content."""
    genres:    dict[str, float] = field(default_factory=dict)
    directors: dict[str, float] = field(default_factory=dict)
    actors:    dict[str, float] = field(default_factory=dict)
    keywords:  dict[str, float] = field(default_factory=dict)
    rated_count:    int = 0
    liked_count:    int = 0
    disliked_count: int = 0

    def is_empty(self) -> bool:
        return self.rated_count == 0

    def top(self, attr: str, n: int = 10) -> list[tuple[str, float]]:
        """Return top-n entries by absolute weight for the named attribute dict."""
        d: dict[str, float] = getattr(self, attr, {})
        return sorted(d.items(), key=lambda kv: abs(kv[1]), reverse=True)[:n]


@dataclass
class ScoredChannel:
    """A candidate recommendation with its computed match score."""
    channel_id:        str
    channel_name:      str
    media_type:        str
    score:             float
    matching_genres:   list[str]
    matching_keywords: list[str]
    director:          str | None
    poster_url:        str | None
    reason:            str          # e.g. "Action, Nolan, +heist"
    already_liked:     bool = False  # user has given this a thumbs-up
    metadata_rating:   float | None = None  # TMDb/OMDb score (0–10)
    rec_shown_count:   int = 0       # total impression count (for tooltip + decay)
    variant_count:     int = 0       # how many source/language copies collapsed into this entry
    # Ingestion-computed display fields — read at render (never re-parse the name).
    detected_title:    str = ""
    detected_region:   str = ""
    detected_quality:  str = ""
    detected_year:     str = ""
    detected_prefix:   str = ""  # honest audio-language token (e.g. "EN") — NOT the region
    # Liked people (matched actors + director) driving this item's score — read by the
    # within-generation people-diversity re-rank so the same face doesn't fill the list.
    score_people:      tuple[str, ...] = ()


def version_score(channel, config) -> int:
    """Score a channel against the user's version preferences (prefix/provider/quality).

    Higher score = better match. Used to pick the preferred variant when multiple
    language/region copies of the same production are candidates.
    """
    score = 0
    if config.preferred_version_prefixes and channel.detected_prefix:
        try:
            idx = config.preferred_version_prefixes.index(channel.detected_prefix)
            score += max(0, 10 - idx)
        except ValueError:
            pass
    if config.preferred_version_provider_ids and channel.provider_id in config.preferred_version_provider_ids:
        try:
            idx = config.preferred_version_provider_ids.index(channel.provider_id)
            score += max(0, 5 - idx)
        except ValueError:
            pass
    if config.preferred_version_quality:
        if config.preferred_version_quality.upper() in channel.name.upper():
            score += 5
    return score


def extract_keywords(plot: str) -> list[str]:
    """Return content words from a plot string (lowercased, stop-word filtered)."""
    words = re.findall(r"\b[a-z]{4,}\b", plot.lower())
    return [w for w in words if w not in STOP_WORDS]


def build_idf(all_plots: list[str]) -> dict[str, float]:
    """Build IDF table from a corpus of plot strings.

    Words appearing in more than MAX_CORPUS_FREQ of documents are excluded —
    they carry no discriminating power.
    """
    n = len(all_plots)
    if n == 0:
        return {}
    doc_freq: Counter = Counter()
    for plot in all_plots:
        doc_freq.update(set(extract_keywords(plot)))
    return {
        word: math.log(n / freq)
        for word, freq in doc_freq.items()
        if (freq / n) <= MAX_CORPUS_FREQ
    }


def _title_key(channel) -> str:
    """Collapse key for one channel's title identity (CLAUDE.md 'Content identity').

    Mirrors the canonical ``COALESCE(content_key, 'id:' || id)`` grouping used by
    Browse/Discover/Other-Versions: variants that share a stored ``content_key``
    are one title; a row without one stands alone.
    """
    ck = getattr(channel, "content_key", None) or None
    return ck if ck else f"id:{channel.id}"


def compute_weights(session, settings: RecScoringSettings | None = None) -> AttributeWeights:
    """Load all ratings, join to MetadataDB, and accumulate attribute weights.

    Level 1 — genre, director, cast (structured fields).
    Level 2 — TF-IDF weighted keywords from plot text.

    Args:
        session: Open SQLAlchemy session.
        settings: User-tuned scoring dials (attribute weights + the actor
            corroboration gate); ``None`` uses the shipped defaults.
    """
    from metatv.core.database import UserRatingDB, ChannelDB, MetadataDB

    dials = settings or DEFAULT_REC_SETTINGS

    ratings = session.query(UserRatingDB).all()

    # Include favorites as implicit +0.5 signals (they shaped the user's taste
    # even if never explicitly rated).
    rated_channel_ids = {r.channel_id for r in ratings}
    # Batch-fetch rated channels in one IN query instead of per-row session.get()
    rated_ids_list = list(rated_channel_ids)
    rated_channel_map: dict[str, ChannelDB] = {}
    if rated_ids_list:
        for ch in session.query(ChannelDB).filter(ChannelDB.id.in_(rated_ids_list)).all():
            rated_channel_map[ch.id] = ch

    favorites = [
        ch for ch in session.query(ChannelDB)
        .filter(ChannelDB.is_favorite == True, ChannelDB.metadata_id.isnot(None)).all()  # noqa: E712
        if ch.id not in rated_channel_ids
    ]

    if not ratings and not favorites:
        return AttributeWeights()

    # Collapse to one signal per TITLE (CLAUDE.md "Content identity" — group on the
    # stored content_key, computed at ingestion, never re-keyed here). Rating or
    # favoriting the same film in three language variants is one act of taste, not
    # three: letting every variant through used to triple the genre weight and
    # triple-fire the actor-corroboration counter. Precedence within a title group:
    # an explicit rating always beats an implicit favorite (0.5); among explicit
    # ratings the most recently rated one wins (tie-break on channel.id); among
    # favorites-only groups the lowest channel.id wins (same determinism goal).
    from datetime import datetime

    _title_signals: dict[str, tuple] = {}  # title_key -> (channel, sig, rated_at, is_explicit)
    for r in ratings:
        ch = rated_channel_map.get(r.channel_id)
        if not ch:
            continue
        key = _title_key(ch)
        existing = _title_signals.get(key)
        if existing is None:
            _title_signals[key] = (ch, float(r.rating), r.rated_at, True)
            continue
        cur = (r.rated_at or datetime.min, ch.id)
        prev = (existing[2] or datetime.min, existing[0].id)
        if cur > prev:
            _title_signals[key] = (ch, float(r.rating), r.rated_at, True)
    for ch in favorites:
        key = _title_key(ch)
        existing = _title_signals.get(key)
        if existing is None:
            _title_signals[key] = (ch, 0.5, None, False)
        elif not existing[3] and ch.id < existing[0].id:
            _title_signals[key] = (ch, 0.5, None, False)
        # else: an explicit rating already claims this title — it always wins.

    signal_pairs: list[tuple] = [
        (ch, sig) for ch, sig, _rated_at, _explicit in _title_signals.values()
    ]
    # Counts describe TITLES the user judged, not provider rows — derived from the
    # collapsed explicit-rating entries only (favorites never count as "rated").
    _explicit_signals = [v for v in _title_signals.values() if v[3]]

    weights = AttributeWeights(
        rated_count=len(_explicit_signals),
        liked_count=sum(1 for _, sig, _, _ in _explicit_signals if sig > 0),
        disliked_count=sum(1 for _, sig, _, _ in _explicit_signals if sig < 0),
    )
    # How many distinct rated/favorited items each actor appears in — used to prune
    # single-appearance performers below (corroboration gate).
    actor_support: Counter = Counter()

    # Column-only fetch for plots — avoids loading full ORM rows for ~1,300 metadata rows
    all_plots = [
        row[0] for row in
        session.query(MetadataDB.plot).filter(MetadataDB.plot.isnot(None)).all()
    ]
    idf = build_idf(all_plots)
    logger.debug(f"Preference engine: IDF corpus = {len(all_plots)} plots, {len(idf)} unique terms")

    # Batch-fetch all needed MetadataDB rows in one IN query instead of per-channel session.get()
    all_metadata_ids = [ch.metadata_id for ch, _ in signal_pairs if ch and ch.metadata_id]
    meta_map: dict[str, MetadataDB] = {}
    if all_metadata_ids:
        for meta in session.query(MetadataDB).filter(MetadataDB.id.in_(all_metadata_ids)).all():
            meta_map[meta.id] = meta

    for channel, sig in signal_pairs:
        if not channel or not channel.metadata_id:
            continue
        meta = meta_map.get(channel.metadata_id)
        if not meta:
            continue

        # Level 1 — structured attributes
        for genre in _split_genres(_loads(meta.genres) or []):
            weights.genres[genre] = weights.genres.get(genre, 0.0) + sig * dials.genre_weight

        for director in _split_directors(meta.director) if meta.director else []:
            weights.directors[director] = (
                weights.directors.get(director, 0.0) + sig * dials.director_weight
            )

        for person in (_loads(meta.cast) or [])[:10]:
            name = person.get("name") if isinstance(person, dict) else None
            if name:
                weights.actors[name] = weights.actors.get(name, 0.0) + sig * dials.actor_weight
                actor_support[name] += 1

        # Level 2 — TF-IDF plot keywords
        if meta.plot:
            kws = extract_keywords(meta.plot)
            kw_counts = Counter(kws)
            total = len(kws) or 1
            for word, cnt in kw_counts.items():
                if word in idf:
                    tf = cnt / total
                    weights.keywords[word] = (
                        weights.keywords.get(word, 0.0) + sig * tf * idf[word]
                    )

    # Corroboration gate: drop performers seen in only a single rated/favorited item.
    # One film's worth of cast is noise; taste in an actor shows up across titles.
    weights.actors = {
        name: w for name, w in weights.actors.items()
        if actor_support[name] >= dials.actor_min_support
    }

    return weights


def score_candidates(session, weights: AttributeWeights, limit: int = 30,
                     muted_attrs: dict | None = None,
                     dedupe_overrides: set[str] | None = None,
                     excluded_prefixes: list[str] | None = None,
                     include_uncategorized: bool = True,
                     excluded_keywords: list[str] | None = None,
                     excluded_provider_ids: list[str] | None = None,
                     version_scorer=None,
                     balance_media_types: bool = False,
                     diversify_people: bool = False,
                     media_mix: str | float | None = None,
                     settings: RecScoringSettings | None = None) -> list[ScoredChannel]:
    """Score movies/series by user preference weights.

    Movie/series mix (``media_mix``, or ``settings.media_mix`` when the parameter
    is omitted): ``None`` leaves the raw ranking alone, ``"automatic"`` derives a
    √-damped share from the user's engagement, and a float is an explicit movie
    share. It supersedes the legacy fixed 50/50 ``balance_media_types`` flag,
    which still works when no mix is given.

    Exclusion rules (applied via the single ``channel_visibility.apply()``
    chokepoint — see ``metatv/core/channel_visibility.py``):
    - From an inactive/expired source (excluded_provider_ids) → excluded
    - Matches a Global Exclusions prefix/category (excluded_prefixes) — the
      canonical, region-aware predicate: a candidate WITH a detected_prefix is
      judged on the prefix alone, one with NO prefix falls back to its
      detected_region ("language wins over region") — or keyword
      (excluded_keywords, case-insensitive substring on the title) → excluded
    - Disliked (rating < 0) → always excluded
    - Hidden (is_hidden) → excluded
    - Rec-suppressed (is_rec_suppressed) → excluded
    - Already watched (last_played set) → excluded; recommendation served its purpose
    - Currently in Watch Queue → excluded; user already queued it
    - Currently in Favorites → excluded (capped at 5 liked-but-unwatched slots)
    - Same production from another source (norm_title + media_type + year + director match)
      → excluded unless channel.id is in dedupe_overrides
    - Duplicate source/language variants → only highest-scoring copy surfaced

    Returns a ranked list, highest score first.
    """
    from datetime import datetime
    from metatv.core.database import ChannelDB, MetadataDB, UserRatingDB, WatchQueueDB
    from metatv.core.content_dedup import (
        build_dedup_key, build_engaged_normalized, is_content_key_dedup,
    )

    if weights.is_empty():
        return []

    dials = settings or DEFAULT_REC_SETTINGS

    disliked_ids: set[str] = {
        r.channel_id for r in session.query(UserRatingDB)
        .filter(UserRatingDB.rating < 0).all()
    }
    # A dislike is a judgment about the TITLE, not about the one provider row the
    # user happened to be looking at. Widen to every sibling sharing a stored
    # content_key so the app stops re-offering the same film from another source.
    if disliked_ids:
        _disliked_cks = {
            ck for (ck,) in session.query(ChannelDB.content_key)
            .filter(ChannelDB.id.in_(list(disliked_ids)), ChannelDB.content_key.isnot(None)).all()
        }
        if _disliked_cks:
            disliked_ids |= {
                cid for (cid,) in session.query(ChannelDB.id)
                .filter(ChannelDB.content_key.in_(list(_disliked_cks))).all()
            }
    # Explicitly liked items (sort newer first)
    liked_map: dict[str, datetime] = {
        r.channel_id: r.rated_at for r in session.query(UserRatingDB)
        .filter(UserRatingDB.rating > 0).all()
    }
    # Favorited items are excluded from the recommendations list — the user already
    # has them; surfacing them again would be redundant.
    # Column-only query: only need ids, not full ORM objects
    favorite_ids: set[str] = {
        cid for (cid,) in session.query(ChannelDB.id)
        .filter(ChannelDB.is_favorite == True).all()  # noqa: E712
    }
    queued_ids: set[str] = {
        row.channel_id for row in session.query(WatchQueueDB).all()
    }

    _overrides = dedupe_overrides or set()
    all_engaged_ids = disliked_ids | favorite_ids | queued_ids | set(liked_map.keys())
    engaged_normalized = build_engaged_normalized(session, all_engaged_ids, _overrides)

    # For series, director is excluded from the dedup key (see content_dedup.py), so
    # year is the only differentiator.  We build two sets to handle both null-year
    # directions without suppressing genuine reboots (where both sides have a year):
    #
    #   engaged_series_with_year  → (norm, "series") for engaged entries that DO have
    #     a year.  Suppresses null-year candidates: "EAR ★ Rick and Morty" (year=None)
    #     when "EN - Rick And Morty (2013)" (year=2013) is queued.
    #
    #   engaged_series_null_year  → (norm, "series") for engaged entries that have NO
    #     year.  Suppresses year-bearing candidates: "EN - BoJack Horseman (2014)"
    #     (year=2014) when "EN ★ BoJack Horseman" (year=None) is favorited.
    #
    # Only one side needs year=None to trigger — if both sides have a year and they
    # differ, neither set matches and the exact-key check handles them as separate
    # productions (reboots).
    engaged_series_with_year: set[tuple] = {
        (k[0], k[1]) for k in engaged_normalized if k[1] == "series" and k[2] is not None
    }
    engaged_series_null_year: set[tuple] = {
        (k[0], k[1]) for k in engaged_normalized if k[1] == "series" and k[2] is None
    }

    from metatv.core import channel_visibility
    candidates_q = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_rec_suppressed == False,  # noqa: E712
            ChannelDB.metadata_id.isnot(None),
        )
    )
    # Single visibility chokepoint (metatv.core.channel_visibility.apply) —
    # owns is_hidden, provider scoping, and the prefix/keyword Global-Exclusion
    # axes in one call.  The prefix axis is now the canonical, region-aware
    # predicate (filter_utils.channel_exclusion_criterion, "language wins over
    # region") instead of the old flat detected_prefix NOT IN check that used
    # to live in discovery_engine._apply_prefix_filter — this is the fix for
    # "Recommendations ignores global exclusions": a candidate with no
    # detected_prefix but an excluded detected_region is now ALSO dropped here,
    # matching the channel list / tag-facet counts / EPG On-Now (see PR
    # description for the full rationale/impact).
    candidates_q = channel_visibility.apply(
        candidates_q,
        channel_visibility.VisibilityScope(
            excluded_provider_ids=list(excluded_provider_ids or []),
            excluded_prefixes=set(excluded_prefixes or []),
            include_uncategorized=include_uncategorized,
            excluded_keywords=set(excluded_keywords or []),
        ),
        channel_cls=ChannelDB,
    )
    candidates = candidates_q.all()

    # Batch-fetch all MetadataDB rows needed for the candidates loop in one IN query.
    # The candidate filter guarantees metadata_id IS NOT NULL, so every candidate needs it.
    candidate_metadata_ids = [ch.metadata_id for ch in candidates if ch.metadata_id]
    candidate_meta_map: dict[str, MetadataDB] = {}
    if candidate_metadata_ids:
        for meta in session.query(MetadataDB).filter(
            MetadataDB.id.in_(candidate_metadata_ids)
        ).all():
            candidate_meta_map[meta.id] = meta

    # Implicit prefix preference: count how often the user has positively engaged with
    # each prefix (favorites, queued, liked, and watched).  Used as a tiebreaker when
    # no explicit preferred_version_prefixes config entry matches — so that the
    # recommended version is in the language/source the user actually watches.
    # Column-only queries: only need detected_prefix, not full ORM objects.
    _implicit_prefix: Counter = Counter()
    _pos_ids = (favorite_ids | queued_ids | set(liked_map.keys())) - disliked_ids
    if _pos_ids:
        for (prefix,) in session.query(ChannelDB.detected_prefix).filter(
            ChannelDB.id.in_(list(_pos_ids)),
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.detected_prefix.isnot(None),
        ).all():
            _implicit_prefix[prefix] += 1
    for (prefix,) in session.query(ChannelDB.detected_prefix).filter(
        ChannelDB.last_played.isnot(None),
        ChannelDB.media_type.in_(["movie", "series"]),
        ChannelDB.detected_prefix.isnot(None),
    ).all():
        _implicit_prefix[prefix] += 2  # played = 2× engagement weight
    _max_impl = max(_implicit_prefix.values(), default=1)

    best_per_title: dict[tuple, ScoredChannel] = {}
    variant_counts: dict[tuple, int] = {}
    # (channel_id) → (explicit_vscore, implicit_vscore) for version tiebreaking.
    # Tuple comparison is lexicographic: explicit config always dominates; implicit
    # engagement frequency breaks ties when explicit scores are equal.
    vscore_by_id: dict[str, tuple[int, float]] = {}
    # (norm, mt) → first year-bearing dedup_key seen; used for null-year absorption
    # within the recommendation list so the same show doesn't appear twice.
    null_year_map: dict[tuple, tuple] = {}

    for channel in candidates:
        if channel.id in disliked_ids:
            continue
        if channel.id in favorite_ids:  # already in favorites — no need to surface again
            continue
        if channel.id in queued_ids:   # already in watch queue — user knows about it
            continue
        if channel.last_played:  # already watched — recommendation done
            continue
        meta = candidate_meta_map.get(channel.metadata_id)
        if not meta:
            continue

        dedup_key = build_dedup_key(channel, meta)
        if channel.id not in _overrides and dedup_key in engaged_normalized:
            continue

        # The year/series fingerprint reconciliation below exists only to absorb the
        # noisy-year problem in the runtime fingerprint. The stored content_key already
        # collapses year/audio variants at ingestion, so for content_key keys we group
        # on the key as-is and skip the (year-positional) fingerprint logic entirely.
        ck_key = is_content_key_dedup(dedup_key)
        if not ck_key:
            # Bidirectional null-year suppression for series.
            # Applied only when one side has year=None; both-year mismatches are reboots.
            norm_mt = (dedup_key[0], dedup_key[1])
            if channel.id not in _overrides and channel.media_type == "series":
                if dedup_key[2] is None and norm_mt in engaged_series_with_year:
                    continue  # null-year candidate, year-bearing engaged variant
                if dedup_key[2] is not None and norm_mt in engaged_series_null_year:
                    continue  # year-bearing candidate, null-year engaged variant

            # Null-year absorption within the recommendation list:
            # If a year-bearing entry for this (norm, mt) already exists, absorb this
            # null-year variant into it so the same show doesn't appear twice.
            if dedup_key[2] is None:
                canonical = null_year_map.get(norm_mt)
                if canonical is not None:
                    dedup_key = canonical   # merge into the year-bearing entry
            else:
                existing = null_year_map.get(norm_mt)
                if existing is None:
                    null_year_map[norm_mt] = dedup_key
                elif existing[2] is None:
                    # Upgrade the null-year key to this year-bearing key
                    if existing in best_per_title:
                        best_per_title[dedup_key] = best_per_title.pop(existing)
                        variant_counts[dedup_key] = variant_counts.pop(existing, 0)
                    null_year_map[norm_mt] = dedup_key

        genres = _split_genres(_loads(meta.genres) or [])
        cast   = _loads(meta.cast)   or []
        kws    = extract_keywords(meta.plot) if meta.plot else []

        _muted       = muted_attrs or {}
        muted_genres = set(_muted.get("genres",    []))
        muted_dirs   = set(_muted.get("directors", []))
        muted_actors = set(_muted.get("actors",    []))
        muted_kws    = set(_muted.get("keywords",  []))

        # Per-field MEAN (not sum): a candidate's score in each field is the average
        # strength of the affinities it actually has there, so a big cast or a long,
        # keyword-dense plot can't inflate a field by sheer volume — which is exactly
        # what let richer-metadata movies out-score thinner-metadata series. Fields
        # still ADD across each other, so matching on genre+director+cast beats
        # matching on genre alone (real corroboration), but no single field runs away.
        genre_score   = _matched_mean(weights.genres.get(g, 0.0) for g in genres if g not in muted_genres)
        dir_score     = _matched_mean(weights.directors.get(d, 0.0) for d in _split_directors(meta.director)
                                      if d not in muted_dirs) if meta.director else 0.0
        actor_score   = _matched_mean(
            weights.actors.get(p.get("name", ""), 0.0)
            for p in cast[:5]
            if isinstance(p, dict) and p.get("name", "") not in muted_actors
        )
        keyword_score = _matched_mean(
            weights.keywords.get(k, 0.0) for k in kws if k not in muted_kws
        ) * dials.keyword_weight

        total = genre_score + dir_score + actor_score + keyword_score
        if total <= 0:
            continue

        shown = getattr(channel, 'rec_shown_count', 0) or 0
        if shown > 0:
            # Default: -4% per impression, floor at 40% of the original score.
            total *= max(IMPRESSION_DECAY_FLOOR, 1.0 - shown * dials.impression_decay)

        match_genres = [g for g in genres if weights.genres.get(g, 0.0) > 0]
        match_kws = sorted(
            (k for k in set(kws) if weights.keywords.get(k, 0.0) > 0.5),
            key=lambda k: weights.keywords[k],
            reverse=True,
        )[:4]

        parts: list[str] = match_genres[:2]
        matched_dirs = [d for d in _split_directors(meta.director) if weights.directors.get(d, 0.0) > 0] if meta.director else []
        if matched_dirs:
            parts.append(matched_dirs[0].split()[-1])
        if match_kws:
            parts.append("+" + ", ".join(match_kws[:2]))

        # Liked people actually driving this score (positive-weight actors + directors)
        # — the set the within-generation diversity re-rank spreads out. Pure-genre
        # matches carry no people, so they surface freely.
        matched_actors = [
            p.get("name", "") for p in cast[:5]
            if isinstance(p, dict) and weights.actors.get(p.get("name", ""), 0.0) > 0
        ]
        score_people = tuple(matched_actors + matched_dirs)

        sc = ScoredChannel(
            channel_id=channel.id,
            channel_name=channel.name,
            media_type=channel.media_type,
            score=total,
            matching_genres=match_genres,
            matching_keywords=match_kws,
            director=meta.director,
            poster_url=meta.poster_url,
            reason=", ".join(parts) or "Attribute match",
            already_liked=channel.id in liked_map,
            metadata_rating=meta.rating,
            rec_shown_count=getattr(channel, 'rec_shown_count', 0) or 0,
            detected_title=channel.detected_title or channel.name,
            detected_region=channel.detected_region or "",
            detected_quality=channel.detected_quality or "",
            detected_year=channel.detected_year or "",
            detected_prefix=channel.detected_prefix or "",
            score_people=score_people,
        )
        explicit_vs = version_scorer(channel) if version_scorer is not None else 0
        impl_vs = _implicit_prefix.get(channel.detected_prefix or "", 0) / _max_impl
        vscore_by_id[channel.id] = (explicit_vs, impl_vs)

        variant_counts[dedup_key] = variant_counts.get(dedup_key, 0) + 1
        existing = best_per_title.get(dedup_key)
        if existing is None:
            best_per_title[dedup_key] = sc
        else:
            # Version preference wins first (explicit config, then implicit engagement
            # frequency); content score breaks remaining ties.
            new_vs = vscore_by_id.get(channel.id, (0, 0.0))
            old_vs = vscore_by_id.get(existing.channel_id, (0, 0.0))
            if new_vs > old_vs or (new_vs == old_vs and total > existing.score):
                best_per_title[dedup_key] = sc

    for key, sc in best_per_title.items():
        sc.variant_count = variant_counts.get(key, 1)

    scored = list(best_per_title.values())
    scored.sort(key=lambda s: s.score, reverse=True)

    # Cap already-liked items at 5 slots (newest-liked first) so they don't crowd
    # out new discoveries. Remaining slots go to fresh (unrated) content.
    liked_results = sorted(
        [sc for sc in scored if sc.already_liked],
        key=lambda sc: liked_map.get(sc.channel_id, datetime.min),
        reverse=True,
    )
    fresh_results = [sc for sc in scored if not sc.already_liked]
    liked_cap = min(dials.liked_cap, len(liked_results))
    fresh_slots = max(0, limit - liked_cap)
    # 1) Spread repeated performers/directors across this generation so one liked face
    #    can't fill the list (re-rank preserves per-type order for the interleave below).
    if diversify_people:
        fresh_results = _diversify_people(fresh_results, decay=dials.people_diversity_decay)
    # 2) Guarantee a movie/series mix even when one type dominates the raw ranking
    #    (more titles, or richer metadata). Discovery slots only — explicit likes above
    #    are the user's own picks and stay as-is.
    mix_spec = media_mix if media_mix is not None else dials.media_mix
    movie_share = resolve_media_share(session, mix_spec)
    if movie_share is not None:
        fresh_selected = mix_media_types(fresh_results, fresh_slots, movie_share)
    elif balance_media_types:
        fresh_selected = _interleave_media_types(fresh_results, fresh_slots)
    else:
        fresh_selected = fresh_results[:fresh_slots]
    merged = liked_results[:liked_cap] + fresh_selected
    return merged[:limit]


def record_impressions(session, channel_ids: list[str], cooldown_minutes: int = 60) -> None:
    """Increment rec_shown_count for each channel, deduplicated within a cooldown window.

    Channels already recorded within cooldown_minutes are skipped — prevents a single
    browsing session from inflating counts on every list refresh.
    """
    from datetime import datetime, timedelta
    from metatv.core.database import ChannelDB

    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=cooldown_minutes)
    for cid in channel_ids:
        ch = session.get(ChannelDB, cid)
        if ch and (ch.rec_last_shown is None or ch.rec_last_shown < cutoff):
            ch.rec_shown_count = (ch.rec_shown_count or 0) + 1
            ch.rec_last_shown = now
    session.commit()


def _matched_mean(values) -> float:
    """Mean of the non-neutral (matched) contributions in one attribute field.

    Averaging the *strength* of the affinities an item actually has — rather than
    summing them — stops a big cast list or a long, keyword-dense plot from
    inflating a field by sheer volume. Neutral (0) entries are ignored so they
    don't dilute the average; a matched dislike (negative weight) still pulls the
    field down. Returns 0.0 when nothing matches.
    """
    matched = [v for v in values if v != 0.0]
    return sum(matched) / len(matched) if matched else 0.0


def _diversify_people(scored: list[ScoredChannel],
                      decay: float = PEOPLE_DIVERSITY_DECAY) -> list[ScoredChannel]:
    """Greedily re-rank so the same liked performer/director doesn't fill the list.

    Walks the score-ordered candidates picking, at each step, the highest *effective*
    score — the base score decayed by ``decay`` (default ``PEOPLE_DIVERSITY_DECAY``)
    for each already-placed item that shares one of this candidate's liked people. A
    pure-genre match (no liked people) is never decayed, so it can leapfrog a third
    same-actor title. Only the top ``_DIVERSITY_HEAD`` by score are re-ranked (the
    tail never surfaces); the tail is appended in score order. Input must already be
    sorted by score, descending.
    """
    if len(scored) <= 1:
        return list(scored)
    remaining = list(scored[:_DIVERSITY_HEAD])
    tail = scored[_DIVERSITY_HEAD:]
    out: list[ScoredChannel] = []
    seen: Counter = Counter()
    while remaining:
        best_idx, best_eff = 0, None
        for idx, cand in enumerate(remaining):
            eff = cand.score
            overlap = sum(seen[p] for p in cand.score_people)
            if overlap:
                eff *= decay ** overlap
            if best_eff is None or eff > best_eff:
                best_idx, best_eff = idx, eff
        chosen = remaining.pop(best_idx)
        out.append(chosen)
        for p in chosen.score_people:
            seen[p] += 1
    return out + tail


def _interleave_media_types(scored: list[ScoredChannel], slots: int) -> list[ScoredChannel]:
    """Strict 50/50 round-robin — the legacy ``balance_media_types`` behavior.

    Superseded by ``media_mix`` (see ``metatv.core.media_mix.mix_media_types``),
    which both call sites now use: a fixed half-and-half split ignores that most
    users lean one way. Kept for callers that explicitly ask for an even list.

    Each type keeps its own score order; the type with the stronger top match
    leads. When one type is exhausted the remainder fills from the other. This is
    what keeps the sidebar from filling entirely with movies just because there
    are more of them (or their metadata is richer, inflating raw scores). If only
    one type is present there is nothing to balance — the top ``slots`` are
    returned unchanged.
    """
    if slots <= 0:
        return []
    movies = [s for s in scored if s.media_type == "movie"]
    series = [s for s in scored if s.media_type == "series"]
    if not movies or not series:
        return scored[:slots]
    take_movie = movies[0].score >= series[0].score
    out: list[ScoredChannel] = []
    i = j = 0
    while len(out) < slots and (i < len(movies) or j < len(series)):
        if take_movie and i < len(movies):
            out.append(movies[i]); i += 1
        elif not take_movie and j < len(series):
            out.append(series[j]); j += 1
        elif i < len(movies):
            out.append(movies[i]); i += 1
        else:
            out.append(series[j]); j += 1
        take_movie = not take_movie
    return out


def _split_names(value: str) -> list[str]:
    """Split a comma, slash, or ampersand-delimited string into individual names."""
    return [v.strip() for v in re.split(r"[,/&]", value) if v.strip()]


def _split_directors(director: str) -> list[str]:
    return _split_names(director)


def _split_genres(genre_value) -> list[str]:
    """Split genres — handles both list-of-strings and slash/comma-delimited strings."""
    if isinstance(genre_value, list):
        result = []
        for g in genre_value:
            result.extend(_split_names(g) if isinstance(g, str) else [])
        return result
    if isinstance(genre_value, str):
        return _split_names(genre_value)
    return []


def _loads(value) -> list | None:
    """Safely deserialize a JSON string or return the value if already a list."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None
