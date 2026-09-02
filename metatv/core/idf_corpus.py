"""Shared plot-corpus IDF table — built once, cached behind a cheap stamp.

The IDF (inverse document frequency) is a property of the METADATA CORPUS
alone: it is derived purely from ``MetadataDB.plot`` text and does not depend
on ratings, favorites, or scoring settings. Every recommendation-scoring
consumer needs the same table (``preference_engine.compute_weights``, and
through it Discover's workers, the details pane, the preferences view, the
discovery engine, and the trail map), so it is built once here and shared
rather than rebuilt per caller — measured at seconds per build over a
130,000+ plot corpus, and one settings change was building it twice within
two seconds.

``corpus_idf`` caches the result behind a stamp — ``(count of non-null
plots, MAX(fetched_at))`` — that changes exactly when enrichment adds or
re-fetches metadata, the only way the corpus can move. A marginally stale IDF
is statistically harmless (it weights terms, it never gates content), which
is why this cheap stamp beats exact per-row invalidation.

This lives in its own module — not in ``preference_engine.py`` — because it
depends on nothing in the preference engine (only ``MetadataDB``), and that
file is already at its code-health ratchet baseline.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter

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
    "your", "them", "three",
    "four", "five", "time", "good", "long", "part", "well", "away",
    "want", "used", "once",
    "real", "keep", "face", "left", "side", "much", "hard", "days",
    "full", "home", "last", "next", "year", "play", "live", "turn",
    "move", "hand", "work", "down", "again", "still",
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
    "drama", "system", "force", "power",
    "journey", "quest", "mission", "battle",
})

MAX_CORPUS_FREQ: float = 0.35  # drop words appearing in >35% of all plots


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


_idf_cache_lock = threading.Lock()
_idf_cache: "tuple[tuple[int, object], dict[str, float]] | None" = None


def corpus_idf(session) -> dict[str, float]:
    """Return the shared plot-corpus IDF table, rebuilt only when the corpus moved.

    The IDF depends only on the METADATA CORPUS — not ratings, favorites, or
    scoring settings — so rebuilding it per ``compute_weights`` call buys
    nothing: Discover's workers, the details pane, preferences view, discovery
    engine and trail map each call it independently, and one settings change
    was measured building it twice within two seconds. The stamp —
    ``(count of non-null plots, MAX(fetched_at))`` — changes exactly when
    enrichment adds or re-fetches metadata, the only way the corpus moves; a
    stale IDF is harmless (it weights terms, never gates content), so a cheap
    stamp beats exact per-row invalidation.
    """
    from sqlalchemy import func
    from metatv.core.database import MetadataDB

    stamp = (
        session.query(func.count(MetadataDB.plot), func.max(MetadataDB.fetched_at))
        .filter(MetadataDB.plot.isnot(None))
        .one()
    )

    global _idf_cache
    # Held across the whole build (not just the compare): two consumers racing
    # in from different threads must produce one build and one wait-then-hit,
    # never two overlapping rebuilds of the same 129k-term table.
    with _idf_cache_lock:
        if _idf_cache is not None and _idf_cache[0] == stamp:
            logger.debug(f"IDF corpus cache hit ({len(_idf_cache[1])} terms)")
            return _idf_cache[1]
        all_plots = [
            row[0] for row in
            session.query(MetadataDB.plot).filter(MetadataDB.plot.isnot(None)).all()
        ]
        idf = build_idf(all_plots)
        _idf_cache = (stamp, idf)
        logger.debug(
            f"Preference engine: IDF corpus = {len(all_plots)} plots, "
            f"{len(idf)} unique terms (rebuilt)"
        )
        return idf
