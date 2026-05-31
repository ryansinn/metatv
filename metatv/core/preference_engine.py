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


def compute_weights(session) -> AttributeWeights:
    """Load all ratings, join to MetadataDB, and accumulate attribute weights.

    Level 1 — genre, director, cast (structured fields).
    Level 2 — TF-IDF weighted keywords from plot text.
    """
    from metatv.core.database import UserRatingDB, ChannelDB, MetadataDB

    ratings = session.query(UserRatingDB).all()

    # Include favorites as implicit +0.5 signals (they shaped the user's taste
    # even if never explicitly rated).
    rated_channel_ids = {r.channel_id for r in ratings}
    favorites = [
        ch for ch in session.query(ChannelDB)
        .filter(ChannelDB.is_favorite == True, ChannelDB.metadata_id.isnot(None)).all()  # noqa: E712
        if ch.id not in rated_channel_ids
    ]

    if not ratings and not favorites:
        return AttributeWeights()

    weights = AttributeWeights(
        rated_count=len(ratings),
        liked_count=sum(1 for r in ratings if r.rating > 0),
        disliked_count=sum(1 for r in ratings if r.rating < 0),
    )

    all_plots = [m.plot for m in session.query(MetadataDB).all() if m.plot]
    idf = build_idf(all_plots)
    logger.debug(f"Preference engine: IDF corpus = {len(all_plots)} plots, {len(idf)} unique terms")

    # Build a combined signal list: (channel, sig) pairs
    signal_pairs: list[tuple] = []
    for r in ratings:
        ch = session.get(ChannelDB, r.channel_id)
        if ch:
            signal_pairs.append((ch, float(r.rating)))
    for ch in favorites:
        signal_pairs.append((ch, 0.5))  # implicit moderate positive signal

    for channel, sig in signal_pairs:
        if not channel or not channel.metadata_id:
            continue
        meta = session.get(MetadataDB, channel.metadata_id)
        if not meta:
            continue

        # Level 1 — structured attributes
        for genre in _split_genres(_loads(meta.genres) or []):
            weights.genres[genre] = weights.genres.get(genre, 0.0) + sig

        for director in _split_directors(meta.director) if meta.director else []:
            weights.directors[director] = (
                weights.directors.get(director, 0.0) + sig * 1.5
            )

        for person in (_loads(meta.cast) or [])[:10]:
            name = person.get("name") if isinstance(person, dict) else None
            if name:
                weights.actors[name] = weights.actors.get(name, 0.0) + sig * 0.5

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

    return weights


def score_candidates(session, weights: AttributeWeights, limit: int = 30,
                     muted_attrs: dict | None = None,
                     dedupe_overrides: set[str] | None = None,
                     included_prefixes: list[str] | None = None,
                     include_uncategorized: bool = True,
                     version_scorer=None) -> list[ScoredChannel]:
    """Score movies/series by user preference weights.

    Exclusion rules:
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
    from metatv.core.content_dedup import build_dedup_key, build_engaged_normalized

    if weights.is_empty():
        return []

    disliked_ids: set[str] = {
        r.channel_id for r in session.query(UserRatingDB)
        .filter(UserRatingDB.rating < 0).all()
    }
    # Explicitly liked items (sort newer first)
    liked_map: dict[str, datetime] = {
        r.channel_id: r.rated_at for r in session.query(UserRatingDB)
        .filter(UserRatingDB.rating > 0).all()
    }
    # Favorited items are excluded from the recommendations list — the user already
    # has them; surfacing them again would be redundant.
    favorite_ids: set[str] = {
        ch.id for ch in session.query(ChannelDB)
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

    from metatv.core.discovery_engine import _apply_prefix_filter
    candidates_q = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.is_rec_suppressed == False,  # noqa: E712
            ChannelDB.metadata_id.isnot(None),
        )
    )
    candidates_q = _apply_prefix_filter(candidates_q, included_prefixes, include_uncategorized)
    candidates = candidates_q.all()

    best_per_title: dict[tuple, ScoredChannel] = {}
    variant_counts: dict[tuple, int] = {}
    vscore_by_id: dict[str, int] = {}   # channel_id → version_score for tiebreaking
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
        meta = session.get(MetadataDB, channel.metadata_id)
        if not meta:
            continue

        dedup_key = build_dedup_key(channel, meta)
        if channel.id not in _overrides and dedup_key in engaged_normalized:
            continue

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

        genre_score   = sum(weights.genres.get(g, 0.0) for g in genres if g not in muted_genres)
        dir_score     = sum(weights.directors.get(d, 0.0) for d in _split_directors(meta.director)
                            if d not in muted_dirs) if meta.director else 0.0
        actor_score   = sum(
            weights.actors.get(p.get("name", ""), 0.0)
            for p in cast[:5]
            if isinstance(p, dict) and p.get("name", "") not in muted_actors
        )
        keyword_score = sum(weights.keywords.get(k, 0.0) for k in kws if k not in muted_kws) * 0.4

        total = genre_score + dir_score + actor_score + keyword_score
        if total <= 0:
            continue

        shown = getattr(channel, 'rec_shown_count', 0) or 0
        if shown > 0:
            total *= max(0.4, 1.0 - shown * 0.04)  # -4% per impression, floor at 40%

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
        )
        if version_scorer is not None:
            vscore_by_id[channel.id] = version_scorer(channel)

        variant_counts[dedup_key] = variant_counts.get(dedup_key, 0) + 1
        existing = best_per_title.get(dedup_key)
        if existing is None:
            best_per_title[dedup_key] = sc
        elif version_scorer is not None:
            # Preferred version wins; break ties with preference score.
            new_vs = vscore_by_id.get(channel.id, 0)
            old_vs = vscore_by_id.get(existing.channel_id, 0)
            if new_vs > old_vs or (new_vs == old_vs and total > existing.score):
                best_per_title[dedup_key] = sc
        elif total > existing.score:
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
    liked_cap = min(3, len(liked_results))
    merged = liked_results[:liked_cap] + fresh_results[:limit - liked_cap]
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
