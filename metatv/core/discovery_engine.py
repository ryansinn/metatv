"""Discovery engine — shelf data queries for the Discover view.

Builds ContentCard lists for horizontal shelves (Recently Added, Top Rated,
Genre, Decade, Featured Actor) using data already in the source's raw_data
field — no TMDb API key required.

All DB-side sorting uses SQLite's json_extract() via SQLAlchemy text() to
avoid pulling 300K+ rows into Python for sorting.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import text
from loguru import logger

from metatv.core.content_dedup import _PREFIX_NOISE_RE, _YEAR_EXTRACT_RE


# Splits comma- or slash-delimited genre strings into individual genres.
_GENRE_SEP_RE = re.compile(r"[/,]")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ContentCard:
    """A single content item for display in a discovery shelf or browse grid."""
    channel_id: str
    title: str           # prefix-stripped, year retained
    media_type: str      # "movie" | "series"
    thumbnail_url: str | None
    rating: float | None
    year: int | None
    genre: str | None    # primary genre only (first segment)
    is_favorite: bool = False
    in_queue: bool = False
    already_watched: bool = False
    is_liked: bool = False
    detected_prefix: str | None = None  # provider category label (e.g. "DE", "KU")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def display_title(channel) -> str:
    """Strip provider prefix from channel.name, keeping year and subtitle.

    Unlike normalize_title(), this preserves original casing and year markers
    so the result is suitable for display (not dedup keying).
    """
    name = channel.name
    prefix = getattr(channel, "detected_prefix", None)
    if prefix:
        stripped = re.sub(
            rf"^{re.escape(prefix)}\s*[|:*\-–—●•★◉\xb7\s]\s*",
            "", name, flags=re.IGNORECASE,
        )
        if stripped and stripped != name:
            return stripped.strip()
    # Fall through to regex-based prefix stripping (handles formats that
    # detected_prefix misses, or where the prefix itself contains the separator)
    return _PREFIX_NOISE_RE.sub("", name).strip()


def _raw_rating(channel) -> float:
    """Parse provider rating from raw_data, returning 0.0 on failure."""
    try:
        return float((channel.raw_data or {}).get("rating") or 0)
    except (ValueError, TypeError):
        return 0.0


def _raw_year(channel) -> int | None:
    """Best-effort year: raw_data releaseDate → title regex."""
    rd = channel.raw_data or {}
    for key in ("releaseDate", "release_date"):
        val = rd.get(key)
        if val:
            m = re.match(r"(\d{4})", str(val))
            if m:
                return int(m.group(1))
    m = _YEAR_EXTRACT_RE.search(channel.name)
    return int(m.group(1)) if m else None


def _thumbnail(channel) -> str | None:
    rd = channel.raw_data or {}
    url = rd.get("stream_icon") or rd.get("cover") or ""
    return url.strip() or None


def _primary_genre(channel) -> str | None:
    rd = channel.raw_data or {}
    genre_str = (rd.get("genre") or "").strip()
    if not genre_str:
        return None
    # Take first segment from either delimiter
    for seg in _GENRE_SEP_RE.split(genre_str):
        seg = seg.strip()
        if seg:
            return seg
    return None


def _to_card(channel, meta=None, fav_ids=None, queue_ids=None,
             watched_ids=None, liked_ids=None) -> ContentCard:
    title = display_title(channel)
    # Fallback to MetadataDB title when display_title yields a non-alpha string (e.g. "2013")
    if meta and meta.title and not any(c.isalpha() for c in title):
        title = meta.title
    _r = _raw_rating(channel)
    return ContentCard(
        channel_id=channel.id,
        title=title,
        media_type=channel.media_type,
        thumbnail_url=_thumbnail(channel),
        rating=_r if 0 < _r < 10 else None,
        year=_raw_year(channel),
        genre=_primary_genre(channel),
        is_favorite=channel.id in (fav_ids or set()),
        in_queue=channel.id in (queue_ids or set()),
        already_watched=channel.id in (watched_ids or set()),
        is_liked=channel.id in (liked_ids or set()),
        detected_prefix=channel.detected_prefix or None,
    )


def _dedup_cards(cards: list[ContentCard]) -> list[ContentCard]:
    """Remove source/language duplicates — same title+year, keep highest-rated."""
    from metatv.core.content_dedup import normalize_title
    seen: dict[tuple, ContentCard] = {}
    for card in cards:
        key = (normalize_title(card.title), card.year)
        existing = seen.get(key)
        if existing is None or (card.rating or 0) > (existing.rating or 0):
            seen[key] = card
    return list(seen.values())


def _apply_prefix_filter(query, included_prefixes, include_uncategorized):
    """Apply global category filter to a SQLAlchemy query on ChannelDB."""
    from metatv.core.database import ChannelDB
    from sqlalchemy import or_
    if included_prefixes:
        cond = ChannelDB.detected_prefix.in_(included_prefixes)
        if include_uncategorized:
            cond = or_(cond, ChannelDB.detected_prefix.is_(None))
        return query.filter(cond)
    elif not include_uncategorized:
        return query.filter(ChannelDB.detected_prefix.isnot(None))
    return query


# ---------------------------------------------------------------------------
# Shelf queries
# ---------------------------------------------------------------------------

def get_recently_added(session, limit: int = 30, fav_ids=None, queue_ids=None,
                       watched_ids=None, liked_ids=None,
                       included_prefixes=None, include_uncategorized: bool = True,
                       ) -> list[ContentCard]:
    """Movies and series sorted by provider-added timestamp, newest first."""
    from metatv.core.database import ChannelDB, MetadataDB
    q = (
        session.query(ChannelDB, MetadataDB)
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
        )
    )
    q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.added') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_top_rated(session, media_type: str = "movie", limit: int = 30,
                  min_rating: float = 5.0, fav_ids=None, queue_ids=None,
                  watched_ids=None, liked_ids=None,
                  included_prefixes=None, include_uncategorized: bool = True,
                  ) -> list[ContentCard]:
    """Top-rated content of the given media_type by provider rating."""
    from metatv.core.database import ChannelDB, MetadataDB
    q = (
        session.query(ChannelDB, MetadataDB)
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.media_type == media_type,
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text(f"CAST(json_extract(channels.raw_data, '$.rating') AS REAL) >= {min_rating}"),
            text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) < 10"),
        )
    )
    q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_by_genre(session, genre: str, limit: int = 30, fav_ids=None,
                 queue_ids=None, watched_ids=None, liked_ids=None,
                 included_prefixes=None, include_uncategorized: bool = True,
                 ) -> list[ContentCard]:
    """Content matching a genre string (partial match), sorted by rating."""
    from metatv.core.database import ChannelDB, MetadataDB
    q = (
        session.query(ChannelDB, MetadataDB)
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text("json_extract(channels.raw_data, '$.genre') LIKE :pat").bindparams(
                pat=f"%{genre}%"
            ),
        )
    )
    q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_by_decade(session, decade: int, limit: int = 30, fav_ids=None,
                  queue_ids=None, watched_ids=None, liked_ids=None,
                  included_prefixes=None, include_uncategorized: bool = True,
                  ) -> list[ContentCard]:
    """Movies and series from a decade (e.g. decade=1990 → 1990–1999)."""
    from metatv.core.database import ChannelDB, MetadataDB
    start, end = decade, decade + 9
    q = (
        session.query(ChannelDB, MetadataDB)
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) >= 5"),
            text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) < 10"),
        )
    )
    q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
    results: list[ContentCard] = []
    for ch, meta in q.all():
        yr = _raw_year(ch)
        if yr and start <= yr <= end:
            results.append(_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids))
    results.sort(key=lambda c: c.rating or 0, reverse=True)
    results = _dedup_cards(results)
    return results[:limit]


def get_featured_actor(session, weights=None, fav_ids=None, queue_ids=None,
                       watched_ids=None, liked_ids=None,
                       included_prefixes=None, include_uncategorized: bool = True,
                       ) -> tuple[str, list[ContentCard]]:
    """Return (actor_name, cards) for a Featured Actor shelf."""
    from metatv.core.database import ChannelDB

    actor: str | None = None

    if weights and weights.actors:
        positive = {k: v for k, v in weights.actors.items() if v > 0}
        if positive:
            actor = max(positive, key=lambda k: positive[k])

    if not actor:
        q = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.media_type == "series",
                ChannelDB.is_hidden == False,  # noqa: E712
                ChannelDB.raw_data.isnot(None),
                text("CAST(json_extract(raw_data, '$.rating') AS REAL) >= 7.5"),
            )
        )
        q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
        counter: Counter = Counter()
        for ch in q.all():
            cast_str = (ch.raw_data or {}).get("cast") or ""
            for name in [n.strip() for n in cast_str.split(",") if n.strip()]:
                counter[name] += 1
        if counter:
            actor = counter.most_common(1)[0][0]

    if not actor:
        return ("", [])

    cards = get_by_actor(session, actor, limit=30,
                         fav_ids=fav_ids, queue_ids=queue_ids,
                         watched_ids=watched_ids, liked_ids=liked_ids,
                         included_prefixes=included_prefixes,
                         include_uncategorized=include_uncategorized)
    logger.debug(f"Featured actor: {actor!r} ({len(cards)} cards)")
    return (actor, cards)


def get_by_actor(session, actor: str, limit: int = 30, fav_ids=None,
                 queue_ids=None, watched_ids=None, liked_ids=None,
                 included_prefixes=None, include_uncategorized: bool = True,
                 ) -> list[ContentCard]:
    """Series featuring a named actor (partial match on cast string)."""
    from metatv.core.database import ChannelDB, MetadataDB
    q = (
        session.query(ChannelDB, MetadataDB)
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.media_type == "series",
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text("json_extract(channels.raw_data, '$.cast') LIKE :pat").bindparams(
                pat=f"%{actor}%"
            ),
        )
    )
    q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_all_genres(session, min_count: int = 10,
                   included_prefixes=None, include_uncategorized: bool = True,
                   ) -> list[str]:
    """Return individual genre names that have ≥ min_count entries.

    Genre strings from raw_data are split on both '/' and ',' so compound
    strings like 'Action & Adventure / Drama' or 'Animation, Mystery' yield
    individual genre counts rather than counting the compound string as-is.
    Only counts genres from channels that pass the global category filter.
    """
    from metatv.core.database import ChannelDB
    q = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text("json_extract(raw_data, '$.genre') IS NOT NULL"),
            text("json_extract(raw_data, '$.genre') != ''"),
        )
    )
    q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
    counter: Counter = Counter()
    for ch in q.all():
        genre_str = (ch.raw_data or {}).get("genre") or ""
        for g in _GENRE_SEP_RE.split(genre_str):
            g = g.strip()
            if g:
                counter[g] += 1
    return [g for g, cnt in counter.most_common() if cnt >= min_count]


def get_all_decades(session,
                    included_prefixes=None, include_uncategorized: bool = True,
                    ) -> list[int]:
    """Return decades (as start year) that have ≥ 5 entries with a known year."""
    from metatv.core.database import ChannelDB
    q = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
        )
    )
    q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
    decade_counts: Counter = Counter()
    for ch in q.all():
        yr = _raw_year(ch)
        if yr and 1950 <= yr <= 2030:
            decade_counts[(yr // 10) * 10] += 1
    return sorted(
        [d for d, cnt in decade_counts.items() if cnt >= 5],
        reverse=True,
    )


def _rank_genres_by_preference(genres: list[str], liked_ids: set,
                                session,
                                included_prefixes=None,
                                include_uncategorized: bool = True,
                                ) -> list[str]:
    """Sort genres so those with more liked content appear first."""
    if not liked_ids:
        return genres
    from metatv.core.database import ChannelDB
    genre_score: dict[str, int] = {g: 0 for g in genres}
    q = session.query(ChannelDB).filter(ChannelDB.id.in_(liked_ids))
    q = _apply_prefix_filter(q, included_prefixes, include_uncategorized)
    for ch in q.all():
        genre_str = (ch.raw_data or {}).get("genre") or ""
        for g in _GENRE_SEP_RE.split(genre_str):
            g = g.strip()
            if g in genre_score:
                genre_score[g] += 1
    return sorted(genres, key=lambda g: genre_score[g], reverse=True)
