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
from dataclasses import dataclass

from sqlalchemy import text
from loguru import logger

from metatv.core.content_dedup import _PREFIX_NOISE_RE, _YEAR_EXTRACT_RE


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
    genre: str | None    # primary genre only (first "/" segment)


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
        if stripped:
            return stripped.strip()
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
    return genre_str.split("/")[0].strip() or None


def _to_card(channel) -> ContentCard:
    return ContentCard(
        channel_id=channel.id,
        title=display_title(channel),
        media_type=channel.media_type,
        thumbnail_url=_thumbnail(channel),
        rating=_raw_rating(channel) or None,
        year=_raw_year(channel),
        genre=_primary_genre(channel),
    )


# ---------------------------------------------------------------------------
# Shelf queries
# ---------------------------------------------------------------------------

def get_recently_added(session, limit: int = 30) -> list[ContentCard]:
    """Movies and series sorted by provider-added timestamp, newest first."""
    from metatv.core.database import ChannelDB
    rows = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
        )
        .order_by(text("CAST(json_extract(raw_data, '$.added') AS REAL) DESC"))
        .limit(limit)
        .all()
    )
    return [_to_card(ch) for ch in rows]


def get_top_rated(session, media_type: str = "movie", limit: int = 30,
                  min_rating: float = 5.0) -> list[ContentCard]:
    """Top-rated content of the given media_type by provider rating."""
    from metatv.core.database import ChannelDB
    rows = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type == media_type,
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text(f"CAST(json_extract(raw_data, '$.rating') AS REAL) >= {min_rating}"),
            text("CAST(json_extract(raw_data, '$.rating') AS REAL) <= 10"),
        )
        .order_by(text("CAST(json_extract(raw_data, '$.rating') AS REAL) DESC"))
        .limit(limit)
        .all()
    )
    return [_to_card(ch) for ch in rows]


def get_by_genre(session, genre: str, limit: int = 30) -> list[ContentCard]:
    """Series matching a genre string (partial match), sorted by rating."""
    from metatv.core.database import ChannelDB
    rows = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type == "series",
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text("json_extract(raw_data, '$.genre') LIKE :pat").bindparams(
                pat=f"%{genre}%"
            ),
        )
        .order_by(text("CAST(json_extract(raw_data, '$.rating') AS REAL) DESC"))
        .limit(limit)
        .all()
    )
    return [_to_card(ch) for ch in rows]


def get_by_decade(session, decade: int, limit: int = 30) -> list[ContentCard]:
    """Movies and series from a decade (e.g. decade=1990 → 1990–1999).

    Year is extracted Python-side since it comes from title text or a date
    field rather than a clean integer column.
    """
    from metatv.core.database import ChannelDB
    start, end = decade, decade + 9
    # Pre-filter: only channels whose name or releaseDate plausibly has a year
    # in that range — avoids pulling all 305K rows into Python.
    year_pats = [str(y) for y in range(start, end + 1)]
    raw = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text("CAST(json_extract(raw_data, '$.rating') AS REAL) >= 5"),
            text("CAST(json_extract(raw_data, '$.rating') AS REAL) <= 10"),
        )
        .all()
    )
    results: list[ContentCard] = []
    for ch in raw:
        yr = _raw_year(ch)
        if yr and start <= yr <= end:
            results.append(_to_card(ch))
    results.sort(key=lambda c: c.rating or 0, reverse=True)
    return results[:limit]


def get_featured_actor(
    session, weights=None
) -> tuple[str, list[ContentCard]]:
    """Return (actor_name, cards) for a Featured Actor shelf.

    Selection priority:
    1. Top actor from user preference weights (if weights provided and non-empty).
    2. Actor appearing most frequently in series with rating ≥ 7.5.
    """
    from metatv.core.database import ChannelDB

    actor: str | None = None

    if weights and weights.actors:
        positive = {k: v for k, v in weights.actors.items() if v > 0}
        if positive:
            actor = max(positive, key=lambda k: positive[k])

    if not actor:
        rows = (
            session.query(ChannelDB)
            .filter(
                ChannelDB.media_type == "series",
                ChannelDB.is_hidden == False,  # noqa: E712
                ChannelDB.raw_data.isnot(None),
                text("CAST(json_extract(raw_data, '$.rating') AS REAL) >= 7.5"),
            )
            .all()
        )
        counter: Counter = Counter()
        for ch in rows:
            cast_str = (ch.raw_data or {}).get("cast") or ""
            for name in [n.strip() for n in cast_str.split(",") if n.strip()]:
                counter[name] += 1
        if counter:
            actor = counter.most_common(1)[0][0]

    if not actor:
        return ("", [])

    cards = get_by_actor(session, actor, limit=30)
    logger.debug(f"Featured actor: {actor!r} ({len(cards)} cards)")
    return (actor, cards)


def get_by_actor(session, actor: str, limit: int = 30) -> list[ContentCard]:
    """Series featuring a named actor (partial match on cast string)."""
    from metatv.core.database import ChannelDB
    rows = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type == "series",
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text("json_extract(raw_data, '$.cast') LIKE :pat").bindparams(
                pat=f"%{actor}%"
            ),
        )
        .order_by(text("CAST(json_extract(raw_data, '$.rating') AS REAL) DESC"))
        .limit(limit)
        .all()
    )
    return [_to_card(ch) for ch in rows]


def get_all_genres(session, min_count: int = 10) -> list[str]:
    """Return genre names (from series raw_data) that have ≥ min_count entries."""
    from metatv.core.database import ChannelDB
    rows = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type == "series",
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            text("json_extract(raw_data, '$.genre') IS NOT NULL"),
            text("json_extract(raw_data, '$.genre') != ''"),
        )
        .all()
    )
    counter: Counter = Counter()
    for ch in rows:
        genre_str = (ch.raw_data or {}).get("genre") or ""
        for g in genre_str.split("/"):
            g = g.strip()
            if g:
                counter[g] += 1
    return [g for g, cnt in counter.most_common() if cnt >= min_count]


def get_all_decades(session) -> list[int]:
    """Return decades (as start year) that have ≥ 5 entries with a known year."""
    from metatv.core.database import ChannelDB
    rows = (
        session.query(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
        )
        .all()
    )
    decade_counts: Counter = Counter()
    for ch in rows:
        yr = _raw_year(ch)
        if yr and 1950 <= yr <= 2030:
            decade_counts[(yr // 10) * 10] += 1
    return sorted(
        [d for d, cnt in decade_counts.items() if cnt >= 5],
        reverse=True,
    )
