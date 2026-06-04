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
from typing import NamedTuple

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
    url = (rd.get("stream_icon") or rd.get("cover") or "").strip()
    if not url:
        return None
    # Collapse double slashes in path from provider data quality issues (e.g. /movies//file.jpg).
    # Negative lookbehind preserves the :// in http:// / https://.
    return re.sub(r"(?<!:)/+", "/", url)


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


def _apply_prefix_filter(query, excluded_prefixes, include_uncategorized):
    """Apply global category exclusion filter to a SQLAlchemy query on ChannelDB.

    Blacklist model: excluded_prefixes = prefixes to HIDE. Empty = hide nothing.
    NULL (no detected_prefix) is always shown unless include_uncategorized=False.
    """
    from metatv.core.database import ChannelDB
    from sqlalchemy import or_
    if excluded_prefixes:
        if include_uncategorized:
            # Exclude listed prefixes; NULL (untagged) is always visible
            query = query.filter(
                or_(
                    ChannelDB.detected_prefix.notin_(excluded_prefixes),
                    ChannelDB.detected_prefix.is_(None),
                )
            )
        else:
            # Exclude listed prefixes AND untagged channels (notin_ drops NULL too)
            query = query.filter(ChannelDB.detected_prefix.notin_(excluded_prefixes))
    elif not include_uncategorized:
        query = query.filter(ChannelDB.detected_prefix.isnot(None))
    return query


def _apply_user_category_exclusion(query, excluded_user_categories: list[str] | None):
    """Exclude channels whose user_category is in the global exclusion list."""
    from metatv.core.database import ChannelDB
    from sqlalchemy import or_
    if excluded_user_categories:
        query = query.filter(
            or_(
                ChannelDB.user_category.notin_(excluded_user_categories),
                ChannelDB.user_category.is_(None),
            )
        )
    return query


def _apply_adult_filter(query, adult_mode: str, force_adult_provider_ids: list[str] | None):
    """Apply adult content filter to a SQLAlchemy query on ChannelDB."""
    if adult_mode == "all":
        return query
    from metatv.core.database import ChannelDB
    from sqlalchemy import or_
    force_ids = force_adult_provider_ids or []
    if force_ids:
        is_adult_expr = or_(ChannelDB.is_adult == True, ChannelDB.provider_id.in_(force_ids))  # noqa: E712
    else:
        is_adult_expr = (ChannelDB.is_adult == True)  # noqa: E712
    if adult_mode == "hide":
        return query.filter(~is_adult_expr)
    if adult_mode == "only":
        return query.filter(is_adult_expr)
    return query


def build_adult_filter(session, config) -> tuple[str, list[str]]:
    """Return (adult_mode, force_adult_provider_ids) from config + DB.

    Call once per worker run and pass results into all discovery functions.
    """
    from metatv.core.database import ProviderDB
    adult_mode = getattr(config, "filter_adult_mode", "hide")
    force_ids = [p.id for p in session.query(ProviderDB).all() if getattr(p, "force_adult", False)]
    return adult_mode, force_ids


# ---------------------------------------------------------------------------
# Status sets
# ---------------------------------------------------------------------------

class StatusSets(NamedTuple):
    fav_ids:     set[str]
    queue_ids:   set[str]
    watched_ids: set[str]
    liked_ids:   set[str]


def build_status_sets(session) -> StatusSets:
    """Build per-user status sets in a single pass. Call once per worker run."""
    from metatv.core.database import ChannelDB, UserRatingDB
    from metatv.core.repositories import RepositoryFactory
    repos = RepositoryFactory(session)
    fav_ids     = {ch.id for ch in session.query(ChannelDB).filter(ChannelDB.is_favorite == True).all()}  # noqa: E712
    queue_ids   = repos.queue.get_queued_ids()
    watched_ids = {ch.id for ch in session.query(ChannelDB).filter(ChannelDB.last_played.isnot(None)).all()}
    liked_ids   = {r.channel_id for r in session.query(UserRatingDB).filter(UserRatingDB.rating > 0).all()}
    return StatusSets(fav_ids, queue_ids, watched_ids, liked_ids)


# ---------------------------------------------------------------------------
# Shelf queries
# ---------------------------------------------------------------------------

def get_recently_added(session, limit: int = 30, fav_ids=None, queue_ids=None,
                       watched_ids=None, liked_ids=None,
                       excluded_prefixes=None, include_uncategorized: bool = True,
                       adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.added') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_top_rated(session, media_type: str = "movie", limit: int = 30,
                  min_rating: float = 5.0, fav_ids=None, queue_ids=None,
                  watched_ids=None, liked_ids=None,
                  excluded_prefixes=None, include_uncategorized: bool = True,
                  adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_by_genre(session, genre: str, limit: int = 30, fav_ids=None,
                 queue_ids=None, watched_ids=None, liked_ids=None,
                 excluded_prefixes=None, include_uncategorized: bool = True,
                 adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_by_decade(session, decade: int, limit: int = 30, fav_ids=None,
                  queue_ids=None, watched_ids=None, liked_ids=None,
                  excluded_prefixes=None, include_uncategorized: bool = True,
                  adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
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
                       excluded_prefixes=None, include_uncategorized: bool = True,
                       adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
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
        q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
        q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
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
                         excluded_prefixes=excluded_prefixes,
                         include_uncategorized=include_uncategorized,
                         adult_mode=adult_mode,
                         force_adult_provider_ids=force_adult_provider_ids)
    logger.debug(f"Featured actor: {actor!r} ({len(cards)} cards)")
    return (actor, cards)


def get_by_actor(session, actor: str, limit: int = 30, fav_ids=None,
                 queue_ids=None, watched_ids=None, liked_ids=None,
                 excluded_prefixes=None, include_uncategorized: bool = True,
                 adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_all_genres(session, min_count: int = 10,
                   excluded_prefixes=None, include_uncategorized: bool = True,
                   adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    counter: Counter = Counter()
    for ch in q.all():
        genre_str = (ch.raw_data or {}).get("genre") or ""
        for g in _GENRE_SEP_RE.split(genre_str):
            g = g.strip()
            if g:
                counter[g] += 1
    return [g for g, cnt in counter.most_common() if cnt >= min_count]


def get_all_decades(session,
                    excluded_prefixes=None, include_uncategorized: bool = True,
                    adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
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
                                excluded_prefixes=None,
                                include_uncategorized: bool = True,
                                ) -> list[str]:
    """Sort genres so those with more liked content appear first."""
    if not liked_ids:
        return genres
    from metatv.core.database import ChannelDB
    genre_score: dict[str, int] = {g: 0 for g in genres}
    q = session.query(ChannelDB).filter(ChannelDB.id.in_(liked_ids))
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    for ch in q.all():
        genre_str = (ch.raw_data or {}).get("genre") or ""
        for g in _GENRE_SEP_RE.split(genre_str):
            g = g.strip()
            if g in genre_score:
                genre_score[g] += 1
    return sorted(genres, key=lambda g: genre_score[g], reverse=True)


# ---------------------------------------------------------------------------
# User-category shelves
# ---------------------------------------------------------------------------

def get_all_user_categories(session, excluded_user_categories: list[str] | None = None,
                             ) -> list[dict]:
    """Return all user-defined categories with channel counts, sorted by count descending.

    Excludes categories that are in the global exclusion list.
    Returns [{"name": str, "count": int, "mood": str | None}, ...]
    """
    from metatv.core.database import ChannelDB
    from sqlalchemy import func
    rows = (
        session.query(
            ChannelDB.user_category,
            ChannelDB.category_mood,
            func.count().label("cnt"),
        )
        .filter(ChannelDB.user_category.isnot(None))
        .group_by(ChannelDB.user_category, ChannelDB.category_mood)
        .all()
    )
    seen: dict[str, dict] = {}
    excl = set(excluded_user_categories or [])
    for name, mood, cnt in rows:
        if name in excl:
            continue
        if name not in seen:
            seen[name] = {"name": name, "count": cnt, "mood": mood}
        else:
            seen[name]["count"] += cnt
    return sorted(seen.values(), key=lambda x: -x["count"])


def get_by_user_category(session, category: str, limit: int = 30,
                          fav_ids=None, queue_ids=None, watched_ids=None, liked_ids=None,
                          excluded_prefixes=None, include_uncategorized: bool = True,
                          adult_mode: str = "all",
                          force_adult_provider_ids: list[str] | None = None,
                          ) -> list[ContentCard]:
    """Return ContentCards for all channels in a user-defined category."""
    from metatv.core.database import ChannelDB, MetadataDB
    q = (
        session.query(ChannelDB, MetadataDB)
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.user_category == category,
            ChannelDB.is_hidden == False,  # noqa: E712
        )
    )
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    rows = q.order_by(ChannelDB.name).limit(limit).all()
    return [
        _to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids)
        for ch, meta in rows
    ]
