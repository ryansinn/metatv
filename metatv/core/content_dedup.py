"""Cross-source content deduplication for the recommendation engine.

Heuristic title normalization groups the same show from different providers
into a single recommendation entry, preventing the same production from
appearing multiple times under slightly different names ("EN * The Punisher",
"EN| The Punisher", "Punisher 4K", etc.).

Architecture note
-----------------
This is explicitly a **temporary heuristic**. The correct long-term fix is
canonical external IDs: once TMDb/OMDb is wired up, ``imdb_id`` / ``tmdb_id``
on MetadataDB become the dedup key, and poster-URL path matching provides a
secondary signal. The ``build_dedup_key()`` return value is the single place
in ``score_candidates()`` that needs updating when that happens.

To remove this module entirely: delete this file and revert the ~12 lines in
``preference_engine.score_candidates()`` that import and call
``build_dedup_key()`` and ``build_engaged_normalized()``. Config fields
(``rec_dedupe_overrides``) and UI elements (variant_count badge, context menu
action, exclusions panel section) are permanent and should be kept.
"""

from __future__ import annotations

import re

from loguru import logger

from metatv.core.channel_name_utils import (
    PAREN_QUALIFIER_RE as _PAREN_QUALIFIER_RE,
    BRACKET_QUALIFIER_RE as _BRACKET_QUALIFIER_RE,
    YEAR_SUFFIX_RE as _YEAR_SUFFIX_RE,
    QUALITY_ANYWHERE_RE as _QUALITY_SUFFIX_RE,
)


# ---------------------------------------------------------------------------
# Compiled regex constants
# ---------------------------------------------------------------------------

_PREFIX_NOISE_RE = re.compile(
    r"^(?:(?:[A-Z][A-Z0-9\-+]{1,11}(?:/[A-Z]{2,5})?)\s*[|:*\-–—●•★◉\xb7]\s*)+"
)
"""Strip provider prefix noise like 'EN|', 'EN * ', 'UK/US: ', '4K●', 'D+●'."""

_BRACKET_PREFIX_RE = re.compile(r"^\[[A-Z][A-Z0-9\-+]{0,11}\]\s*")
"""Strip bracket-format prefixes: [SE], [EN], [NF], [D+]. Applied repeatedly for doubles like '[SE] [SE]'."""

_YEAR_EXTRACT_RE = re.compile(r"\b(19[5-9]\d|20[0-2]\d)\b")
"""Extract a plausible production year (1950–2029) from a channel name."""


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def normalize_title(name: str, prefix: str | None = None) -> str:
    """Strip provider prefix noise and normalize for cross-source dedup.

    Handles: "EN * Show", "EN| Show", "EN: Show", "EN - Show",
    "Show (2024)", "Show 4K", "UK/US| Show".

    Returns a lowercase, whitespace-collapsed title. An empty string means
    the entire name was noise; callers should fall back to ``channel.id`` as
    a unique key so the channel still gets scored independently.
    """
    # Strip leading/trailing whitespace first — some providers insert a leading
    # space before the channel name which defeats prefix-stripping regexes.
    name = name.strip()

    # 1. Strip the stored detected_prefix + its trailing delimiter
    if prefix:
        from metatv.core.prefix_detector import strip_prefix
        name = strip_prefix(name, prefix)

    # 2. Regex-strip remaining prefix patterns (catches formats detect_prefix misses)
    name = _PREFIX_NOISE_RE.sub("", name)
    # Also strip bracket-format prefixes: [SE], [EN], [NF], [SE] [SE] (doubled)
    while _BRACKET_PREFIX_RE.match(name):
        name = _BRACKET_PREFIX_RE.sub("", name, count=1)

    # 3. Alternately strip trailing qualifiers until stable:
    #    year markers, paren qualifiers, and bracket qualifiers.
    #    "Show (2024) (ENG-SUB)": pass1 strips (ENG-SUB)→"Show (2024)", pass2 strips year→"Show".
    #    "Show [Multi Audio/Sub]": pass1 strips bracket→"Show".
    prev = None
    while prev != name:
        prev = name
        name = _YEAR_SUFFIX_RE.sub("", name)
        name = _PAREN_QUALIFIER_RE.sub("", name)
        name = _BRACKET_QUALIFIER_RE.sub("", name)

    # 4. Strip quality markers (4K, HD, HQ, LQ, etc.)
    name = _QUALITY_SUFFIX_RE.sub("", name)

    # 5. Lowercase, collapse whitespace, drop non-word characters
    name = re.sub(r"[^\w\s]", " ", name.lower())
    return " ".join(name.split()).strip()


def extract_year(name: str, meta) -> int | None:
    """Best-effort production year: MetadataDB.year first, then channel name.

    Args:
        name: Raw channel name (may contain year like "Show (2004)").
        meta: MetadataDB instance or None.

    Returns:
        Integer year, or None when no reliable year is available.
    """
    if meta and meta.year:
        return int(meta.year)
    m = _YEAR_EXTRACT_RE.search(name)
    return int(m.group(1)) if m else None


def director_key(meta) -> str | None:
    """Normalized first-director last name for dedup fingerprint.

    Returns None when the director is unknown — unknown-director channels
    fall into the same bucket and may incorrectly group different productions,
    but there is no better signal without the data.
    """
    if not meta or not meta.director:
        return None
    # Split on comma, slash, or ampersand (same logic as _split_directors)
    parts = [p.strip() for p in re.split(r"[,/&]", meta.director) if p.strip()]
    if not parts:
        return None
    return parts[0].split()[-1].lower()   # last name of primary director


def build_dedup_key(channel, meta) -> tuple:
    """Content fingerprint for grouping same-production channels.

    Key: ``(norm_title, media_type, year, director)``.

    Two channels share a key when they have the same normalized title,
    media type, production year, and primary director. Language variants
    (EN/FR/DE) of the same production all share a key; the highest-scoring
    copy wins.

    Reboots with the same title but a different year or director get
    different keys and appear as separate recommendations.

    Director is excluded for series because TV shows have many episode
    directors and metadata providers attribute the series to different
    people (creator, showrunner, first-episode director, etc.), producing
    false splits for the same show. For movies, director is reliable.

    Falls back to ``(channel.id, '', None, None)`` when normalization
    produces nothing, so the channel still participates in scoring.
    """
    norm = normalize_title(channel.name, getattr(channel, "detected_prefix", None))
    if not norm:
        return (channel.id, "", None, None)
    media_type = channel.media_type or ""
    dir_k = director_key(meta) if media_type != "series" else None
    return (
        norm,
        media_type,
        extract_year(channel.name, meta),
        dir_k,
    )


def build_engaged_normalized(
    session,
    all_engaged_ids: set[str],
    overrides: set[str],
) -> set[tuple]:
    """Build the set of content fingerprints for already-engaged content.

    Covers rated (liked/disliked), favorited, queued, and already-watched
    channels. When a recommendation candidate matches one of these
    fingerprints, it is suppressed — the user has already engaged with this
    production (possibly from a different source).

    Channels in ``overrides`` are excluded from the engaged set so their
    counterparts are not suppressed by the fingerprint match.
    """
    from metatv.core.database import ChannelDB, MetadataDB

    engaged: set[tuple] = set()

    # Explicitly engaged channels (rated, favorited, queued)
    # Batch-fetch all engaged channels in one IN query instead of per-id session.get()
    engaged_ids_list = list(all_engaged_ids - overrides)
    engaged_channel_map: dict[str, ChannelDB] = {}
    if engaged_ids_list:
        for ch in session.query(ChannelDB).filter(ChannelDB.id.in_(engaged_ids_list)).all():
            engaged_channel_map[ch.id] = ch

    # Batch-fetch metadata for engaged channels that have metadata_id
    engaged_meta_ids = [ch.metadata_id for ch in engaged_channel_map.values() if ch.metadata_id]
    engaged_meta_map: dict[str, MetadataDB] = {}
    if engaged_meta_ids:
        for meta in session.query(MetadataDB).filter(MetadataDB.id.in_(engaged_meta_ids)).all():
            engaged_meta_map[meta.id] = meta

    for ch in engaged_channel_map.values():
        norm = normalize_title(ch.name, getattr(ch, "detected_prefix", None))
        if not norm:
            continue
        meta = engaged_meta_map.get(ch.metadata_id) if ch.metadata_id else None
        engaged.add((
            norm,
            ch.media_type or "",
            extract_year(ch.name, meta),
            director_key(meta),
        ))

    # Watched channels — column-only query to avoid loading raw_data JSON.
    # Columns needed: id, name, detected_prefix, media_type, metadata_id (channel);
    # director, year (metadata via outerjoin on nullable metadata_id).
    for (ch_id, ch_name, ch_prefix, ch_media_type, ch_meta_id,
         meta_director, meta_year) in (
        session.query(
            ChannelDB.id,
            ChannelDB.name,
            ChannelDB.detected_prefix,
            ChannelDB.media_type,
            ChannelDB.metadata_id,
            MetadataDB.director,
            MetadataDB.year,
        )
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.last_played.isnot(None),
            ChannelDB.media_type.in_(["movie", "series"]),
        )
        .all()
    ):
        if ch_id in overrides:
            continue
        norm = normalize_title(ch_name, ch_prefix)
        if norm:
            # Build a lightweight proxy for extract_year / director_key helpers
            # which only read .year and .director from the MetadataDB side.
            class _MetaProxy:
                __slots__ = ("year", "director")
                def __init__(self, y, d):
                    self.year = y
                    self.director = d
            meta_proxy = _MetaProxy(meta_year, meta_director) if (meta_director is not None or meta_year is not None) else None
            engaged.add((
                norm,
                ch_media_type or "",
                extract_year(ch_name, meta_proxy),
                director_key(meta_proxy),
            ))

    logger.debug(f"Content dedup: {len(engaged)} engaged content fingerprints")
    return engaged
