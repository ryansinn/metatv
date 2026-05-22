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
    channel_id:       str
    channel_name:     str
    media_type:       str
    score:            float
    matching_genres:  list[str]
    matching_keywords: list[str]
    director:         str | None
    poster_url:       str | None
    reason:           str  # e.g. "Action, Nolan, +heist"


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
    if not ratings:
        return AttributeWeights()

    weights = AttributeWeights(
        rated_count=len(ratings),
        liked_count=sum(1 for r in ratings if r.rating > 0),
        disliked_count=sum(1 for r in ratings if r.rating < 0),
    )

    all_plots = [m.plot for m in session.query(MetadataDB).all() if m.plot]
    idf = build_idf(all_plots)
    logger.debug(f"Preference engine: IDF corpus = {len(all_plots)} plots, {len(idf)} unique terms")

    for r in ratings:
        channel = session.get(ChannelDB, r.channel_id)
        if not channel or not channel.metadata_id:
            continue
        meta = session.get(MetadataDB, channel.metadata_id)
        if not meta:
            continue

        sig = float(r.rating)  # +1.0 or -1.0

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


def score_candidates(session, weights: AttributeWeights, limit: int = 30) -> list[ScoredChannel]:
    """Score all unrated movies/series by user preference weights.

    Returns a ranked list of recommendations, highest score first.
    Channels without MetadataDB or with score <= 0 are excluded.
    """
    from metatv.core.database import ChannelDB, MetadataDB, UserRatingDB

    if weights.is_empty():
        return []

    rated_ids = {r.channel_id for r in session.query(UserRatingDB).all()}

    candidates = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.metadata_id.isnot(None),
        )
        .all()
    )

    scored: list[ScoredChannel] = []
    for channel in candidates:
        if channel.id in rated_ids:
            continue
        meta = session.get(MetadataDB, channel.metadata_id)
        if not meta:
            continue

        genres = _split_genres(_loads(meta.genres) or [])
        cast   = _loads(meta.cast)   or []
        kws    = extract_keywords(meta.plot) if meta.plot else []

        genre_score   = sum(weights.genres.get(g, 0.0) for g in genres)
        dir_score     = sum(weights.directors.get(d, 0.0) for d in _split_directors(meta.director)) if meta.director else 0.0
        actor_score   = sum(
            weights.actors.get(p.get("name", ""), 0.0)
            for p in cast[:5]
            if isinstance(p, dict)
        )
        keyword_score = sum(weights.keywords.get(k, 0.0) for k in kws) * 0.4

        total = genre_score + dir_score + actor_score + keyword_score
        if total <= 0:
            continue

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

        scored.append(ScoredChannel(
            channel_id=channel.id,
            channel_name=channel.name,
            media_type=channel.media_type,
            score=total,
            matching_genres=match_genres,
            matching_keywords=match_kws,
            director=meta.director,
            poster_url=meta.poster_url,
            reason=", ".join(parts) or "Attribute match",
        ))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit]


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
