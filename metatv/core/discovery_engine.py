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
from typing import NamedTuple

from sqlalchemy import literal_column, text
from loguru import logger

from metatv.core import channel_visibility
from metatv.core.content_dedup import _PREFIX_NOISE_RE, _YEAR_EXTRACT_RE
from metatv.core.filter_utils import genres_from_raw, normalize_genre


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
    progress_fraction: float = 0.0      # 0.0 = none or completed; 0–1 = partial resume
    variant_count: int = 1              # number of same-production variants collapsed into this card (≥ 1)
    content_key: str | None = None      # stored identity key (computed at ingestion); None on pre-migration rows


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


def poster_url_from_raw(raw_data) -> str | None:
    """Resolve the poster URL a provider shipped, from its raw stream record.

    THE canonical resolver, and the only place that knows which raw keys carry a
    poster. Movies put it in ``stream_icon``; series put it in ``cover``, which
    is why reading one key covers only part of a library — measured on the
    owner's: 97.2% of movies had a stored poster and 0% of series did, because
    ingestion mapped ``stream_icon`` alone.

    Called at INGESTION (``XtreamProvider`` stores the result on
    ``ChannelDB.logo_url``) so render and query code can read the stored column
    instead of scanning ``raw_data`` JSON per row — the same compute-once rule
    ``_primary_genre`` below spells out, and for the same reason.

    Args:
        raw_data: The provider's stream record, or None.

    Returns:
        A normalised URL, or None when the provider shipped no poster.
    """
    rd = raw_data or {}
    url = (rd.get("stream_icon") or rd.get("cover") or "").strip()
    if not url:
        return None
    # Collapse double slashes in path from provider data quality issues (e.g. /movies//file.jpg).
    # Negative lookbehind preserves the :// in http:// / https://.
    return re.sub(r"(?<!:)/+", "/", url)


def channel_thumbnail(channel) -> str | None:
    """Resolve a channel's poster, preferring the value stored at ingestion.

    Reads ``logo_url`` — computed once by :func:`poster_url_from_raw` when the
    channel was ingested — and falls back to a raw_data scan only for rows that
    predate that, which the poster backfill migration clears.
    """
    stored = (getattr(channel, "logo_url", "") or "").strip()
    if stored:
        return stored
    return poster_url_from_raw(getattr(channel, "raw_data", None))


def _primary_genre(channel) -> str | None:
    """Compute the primary (first-segment) canonical genre from raw_data.

    NOTE: this is the **ingestion-time** derivation helper — it powers
    ``ChannelDB.detected_genre`` (computed once by ``update_detected_prefixes()``
    in ``core/repositories/channel.py``). Render/query code must read the
    stored ``channel.detected_genre`` field directly and never call this at
    runtime (CLAUDE.md "compute once at ingestion, read everywhere else") —
    a raw_data JSON scan per row is exactly what made Discover genre-shelf
    expand take 15-20s (#genre-perf).  Kept as a thin wrapper around the
    shared :func:`~metatv.core.filter_utils.genres_from_raw` splitter so the
    segmentation/canonicalisation logic has one definition.
    """
    genres = genres_from_raw((channel.raw_data or {}).get("genre"))
    return genres[0] if genres else None


def _to_card(channel, meta=None, fav_ids=None, queue_ids=None,
             watched_ids=None, liked_ids=None,
             progress_map: "dict[str, float] | None" = None) -> ContentCard:
    # Read the stored clean title (computed at ingestion by update_detected_prefixes).
    # Using detected_title is the CLAUDE.md canonical rule: "compute once at ingestion,
    # read everywhere else."  display_title() re-parses channel.name at render time
    # and misses leading-pipe prefixes like "|EN|"/"| MULTI|" (whose first char is
    # "|", not "[A-Z]"), causing dirty titles in Show-All / Discover / Recommendations.
    title = channel.detected_title or channel.name
    # Fallback to MetadataDB title when the stored title is still a non-alpha string
    # (e.g. "2013" — an edge case where the channel name is just a year).
    if meta and meta.title and not any(c.isalpha() for c in title):
        title = meta.title
    _r = _raw_rating(channel)
    already_watched = channel.id in (watched_ids or set())
    # progress_fraction: non-zero only when partially watched (not completed).
    # Completed items show the ✓ badge instead; a completed channel has watch_progress=0
    # (cleared by record_watch_progress), so we read it from the progress_map only.
    frac = (progress_map or {}).get(channel.id, 0.0) if not already_watched else 0.0
    return ContentCard(
        channel_id=channel.id,
        title=title,
        media_type=channel.media_type,
        thumbnail_url=channel_thumbnail(channel),
        rating=_r if 0 < _r < 10 else None,
        year=_raw_year(channel),
        # Ingestion-computed stored field — never re-parse raw_data at render
        # time (CLAUDE.md "compute once at ingestion, read everywhere else").
        # None on pre-backfill rows or channels with no provider genre, same
        # as the old _primary_genre(channel) behaviour for those cases.
        genre=getattr(channel, "detected_genre", None),
        is_favorite=channel.id in (fav_ids or set()),
        in_queue=channel.id in (queue_ids or set()),
        already_watched=already_watched,
        is_liked=channel.id in (liked_ids or set()),
        detected_prefix=channel.detected_prefix or None,
        progress_fraction=frac,
        content_key=getattr(channel, "content_key", None) or None,
    )


def _dedup_cards(cards: list[ContentCard]) -> list[ContentCard]:
    """Collapse cross-source duplicates on stored content_key; keep highest-rated representative.

    Grouping rules
    --------------
    - Primary key: ``card.content_key`` when set (the indexed ingestion-time identity key).
    - Fallback for un-backfilled rows (content_key is None): each card is its own group
      keyed by ``f"id:{card.channel_id}"`` — prevents all null-key cards from collapsing
      into one.

    Representative selection (deterministic tiebreakers in priority order):
    1. Higher rating wins (None treated as -1 so any real rating beats no rating).
    2. Lower channel_id string wins as a stable alphabetical tiebreaker.

    Shelf ordering is preserved: when a later card outranks the stored representative
    the value is replaced but the group's original insertion position is kept.
    ``variant_count`` on the representative is set to the size of its group.
    """
    # group_key → (slot_index, representative)
    slots: dict[str, tuple[int, ContentCard]] = {}
    groups: dict[str, list[ContentCard]] = {}
    for card in cards:
        gk = card.content_key if card.content_key else f"id:{card.channel_id}"
        if gk not in slots:
            slots[gk] = (len(slots), card)
            groups[gk] = [card]
        else:
            groups[gk].append(card)
            idx, rep = slots[gk]
            # Replace representative only when the challenger is strictly better.
            # Tiebreaker 1: higher rating (None → -1)
            # Tiebreaker 2: lower channel_id (stable alphabetical order)
            card_rating = card.rating if card.rating is not None else -1.0
            rep_rating  = rep.rating  if rep.rating  is not None else -1.0
            better = (
                card_rating > rep_rating
                or (card_rating == rep_rating and card.channel_id < rep.channel_id)
            )
            if better:
                slots[gk] = (idx, card)   # keep original slot index

    # Build result in original insertion order, updating variant_count.
    ordered = sorted(slots.values(), key=lambda t: t[0])
    result = []
    for _idx, rep in ordered:
        gk = rep.content_key if rep.content_key else f"id:{rep.channel_id}"
        rep.variant_count = len(groups[gk])
        result.append(rep)
    return result


def _apply_prefix_filter(query, excluded_prefixes, include_uncategorized,
                         excluded_content_types=None, excluded_keywords=None):
    """Apply global category exclusion filter to a SQLAlchemy query on ChannelDB.

    Routes through the single visibility chokepoint,
    :func:`~metatv.core.channel_visibility.apply` — the prefix axis is now the
    **canonical, region-aware** predicate (``filter_utils.channel_exclusion_
    criterion``, "language wins over region"), matching the channel list /
    tag-facet counts / EPG On-Now.  This is a deliberate behavior change from
    the pre-migration flat ``detected_prefix NOT IN (...)`` check: a channel
    with NO ``detected_prefix`` but a ``detected_region`` in *excluded_prefixes*
    is now ALSO excluded here (previously it was always shown — see PR
    description for the full rationale/impact).  Blacklist model: empty =
    hide nothing.  Untagged (no prefix, no region) channels are always shown
    unless *include_uncategorized* is False.

    Also applies the content-provenance layer (``excluded_content_types`` —
    ``content_type`` tag values to hide) and the keyword layer
    (``excluded_keywords`` — user free-text terms matched against the title) in
    the SAME chokepoint call (see :func:`_apply_content_type_exclusion` /
    :func:`_apply_keyword_exclusion` for their standalone, single-axis forms —
    ``channel_visibility.apply()``'s axes are order-independent, so combining
    them here produces the identical result set as applying each separately),
    so every shelf that scopes prefixes also drops globally-excluded AI content
    / keyword matches in one call.  All axes are paused-aware at the control
    layer (the caller passes empty sets/lists when Global Exclusions are paused).
    """
    from metatv.core.database import ChannelDB
    scope = channel_visibility.VisibilityScope(
        excluded_prefixes=set(excluded_prefixes or []),
        include_uncategorized=include_uncategorized,
        excluded_content_types=set(excluded_content_types or []),
        excluded_keywords=set(excluded_keywords or []),
        # The base query already applies its own is_hidden gate directly
        # (every shelf query filters ChannelDB.is_hidden == False) — this
        # helper only owns the prefix/content-type/keyword axes, so it must
        # not re-derive (or accidentally narrow) the hidden gate itself.
        include_hidden=True,
    )
    return channel_visibility.apply(query, scope, channel_cls=ChannelDB)


def _apply_provider_exclusion(query, excluded_provider_ids: list[str] | None):
    """Exclude channels whose provider_id is in the expired/excluded list."""
    from metatv.core.database import ChannelDB
    scope = channel_visibility.VisibilityScope(
        excluded_provider_ids=list(excluded_provider_ids or []),
        include_hidden=True,  # owned by the base query, see _apply_prefix_filter
    )
    return channel_visibility.apply(query, scope, channel_cls=ChannelDB)


def _apply_content_type_exclusion(query, excluded_content_types):
    """Exclude channels carrying a globally-excluded ``content_type`` tag.

    Discover surface of the content-provenance Global Exclusion: routes through
    the shared :func:`~metatv.core.channel_visibility.apply` chokepoint (which
    in turn applies ``filter_utils.tag_content_type_exclusion_criterion`` — a
    NOT EXISTS clause) so a shelf never surfaces content whose ``content_type``
    value (e.g. ``ai_generated``) the user has globally hidden.  No-op when
    *excluded_content_types* is empty.
    """
    from metatv.core.database import ChannelDB
    scope = channel_visibility.VisibilityScope(
        excluded_content_types=set(excluded_content_types or []),
        include_hidden=True,  # owned by the base query, see _apply_prefix_filter
    )
    return channel_visibility.apply(query, scope, channel_cls=ChannelDB)


def _apply_keyword_exclusion(query, excluded_keywords):
    """Exclude channels whose title matches a globally-excluded keyword.

    Discover surface of the keyword Global Exclusion axis (fourth axis, P1-6
    family): routes through the shared
    :func:`~metatv.core.channel_visibility.apply` chokepoint (which in turn
    applies ``filter_utils.keyword_exclusion_criterion`` — a case-insensitive
    ``ilike`` chain against ``detected_title``/``name``) so a shelf never
    surfaces content the user has told the app to hide by keyword
    ("wrestling", "telenovela", …). No-op when *excluded_keywords* is empty.
    """
    from metatv.core.database import ChannelDB
    scope = channel_visibility.VisibilityScope(
        excluded_keywords=set(excluded_keywords or []),
        include_hidden=True,  # owned by the base query, see _apply_prefix_filter
    )
    return channel_visibility.apply(query, scope, channel_cls=ChannelDB)


def _apply_user_category_exclusion(query, excluded_user_categories: list[str] | None):
    """Exclude channels whose user_category is in the global exclusion list."""
    from metatv.core.database import ChannelDB
    scope = channel_visibility.VisibilityScope(
        excluded_categories=set(excluded_user_categories or []),
        include_hidden=True,  # owned by the base query, see _apply_prefix_filter
    )
    return channel_visibility.apply(query, scope, channel_cls=ChannelDB)


def _apply_adult_filter(query, adult_mode: str, force_adult_provider_ids: list[str] | None):
    """Apply adult content filter to a SQLAlchemy query on ChannelDB.

    A channel is restricted if ``is_adult`` (provider-supplied flag) OR
    ``detected_restricted`` (ingestion-computed XXX/ADULT/X-prefix naming
    detection — catches channels the provider flag misses, owner-reported gap;
    see ``channel_name_utils.is_restricted_name``) OR its provider is force_adult.
    """
    from metatv.core.database import ChannelDB
    scope = channel_visibility.VisibilityScope(
        adult_mode=adult_mode,
        force_adult_provider_ids=list(force_adult_provider_ids or []),
        include_hidden=True,  # owned by the base query, see _apply_prefix_filter
    )
    return channel_visibility.apply(query, scope, channel_cls=ChannelDB)


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
    fav_ids:      set[str]
    queue_ids:    set[str]
    watched_ids:  set[str]          # channels where watch_completed is True
    liked_ids:    set[str]
    progress_map: dict[str, float]  # channel_id → fraction (0–1) for partial watches


def build_status_sets(session) -> StatusSets:
    """Build per-user status sets in a single pass. Call once per worker run."""
    from metatv.core.database import ChannelDB, UserRatingDB
    from metatv.core.repositories import RepositoryFactory
    repos = RepositoryFactory(session)
    # Column-only queries: only need ids, not full ORM objects (avoids loading raw_data JSON)
    fav_ids     = {cid for (cid,) in session.query(ChannelDB.id).filter(ChannelDB.is_favorite == True).all()}  # noqa: E712
    queue_ids   = repos.queue.get_queued_ids()
    # watched_ids: channels that have been fully watched (watch_completed=True).
    # This is intentionally different from "ever played" (last_played) — the Discover
    # view shows a ✓ badge only on genuinely completed titles, not merely started ones.
    watched_ids = {
        cid for (cid,) in session.query(ChannelDB.id)
        .filter(ChannelDB.watch_completed == True)  # noqa: E712
        .all()
    }
    # progress_map: partially-watched channels (watch_progress > 0, not completed).
    # Duration comes from MetadataDB.runtime (minutes→seconds) or raw_data["info"]["duration"].
    # Rows with watch_completed=True already have watch_progress cleared to 0, so they
    # never appear here.
    from metatv.core.database import MetadataDB
    partial_rows = (
        session.query(ChannelDB.id, ChannelDB.watch_progress, ChannelDB.metadata_id)
        .filter(
            ChannelDB.watch_progress > 0,
            ChannelDB.watch_completed == False,  # noqa: E712
            ChannelDB.media_type == "movie",
        )
        .all()
    )
    # Batch-fetch runtimes for partial channels that have metadata
    meta_ids = {mid for _, _, mid in partial_rows if mid}
    runtime_by_meta_id: dict[str, int] = {}
    if meta_ids:
        for row in session.query(MetadataDB.id, MetadataDB.runtime).filter(MetadataDB.id.in_(meta_ids)).all():
            if row.runtime:
                runtime_by_meta_id[row.id] = row.runtime * 60  # minutes → seconds
    progress_map: dict[str, float] = {}
    for cid, progress_s, meta_id in partial_rows:
        duration_s = runtime_by_meta_id.get(meta_id or "", 0)
        if duration_s > 0 and progress_s > 0:
            progress_map[cid] = min(1.0, progress_s / duration_s)
    liked_ids   = {r.channel_id for r in session.query(UserRatingDB).filter(UserRatingDB.rating > 0).all()}
    return StatusSets(fav_ids, queue_ids, watched_ids, liked_ids, progress_map)


# ---------------------------------------------------------------------------
# Shelf queries
# ---------------------------------------------------------------------------

def get_recently_added(session, limit: int = 30, fav_ids=None, queue_ids=None,
                       watched_ids=None, liked_ids=None, progress_map=None,
                       excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                       adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                       excluded_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.added') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids, progress_map)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_top_rated(session, media_type: str = "movie", limit: int = 30,
                  min_rating: float = 5.0, fav_ids=None, queue_ids=None,
                  watched_ids=None, liked_ids=None, progress_map=None,
                  excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                  adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                  excluded_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids, progress_map)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_by_genre(session, genre: str, limit: int = 30, fav_ids=None,
                 queue_ids=None, watched_ids=None, liked_ids=None, progress_map=None,
                 excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                 adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                 excluded_provider_ids: list[str] | None = None,
                 ) -> list[ContentCard]:
    """Content matching a genre, sorted by rating.

    *genre* is the **canonical** label (from ``get_all_genres``).  Matches the
    ingestion-computed ``ChannelDB.detected_genres`` list (see
    ``update_detected_prefixes()`` in ``core/repositories/channel.py``) — every
    raw-alias/HTML-escape/segment-boundary complexity that used to live here
    (D5 / DR-0005, bugs A + B) was resolved once at ingestion into that stored,
    already-canonicalised list, so a "Drama" shelf still pulls in rows whose
    raw provider genre was "Drame" / "Dramma" / "دراما", and a multi-genre row
    like "Action & Adventure / Sci-Fi" still appears on both the Action &
    Adventure and Science Fiction shelves — without re-parsing raw_data.

    Perf (#genre-perf): the old implementation ran a ~200-condition
    ``json_extract(raw_data, '$.genre') LIKE …`` OR-chain against the full
    ``raw_data`` blob for every movie/series row (240k+), taking 15-20s per
    shelf expand.  This reads the small pre-extracted ``detected_genres``
    column instead — no raw_data touch, no per-row alias fan-out.
    """
    from metatv.core.database import ChannelDB, MetadataDB
    _target = normalize_genre(genre)
    _genre_match = text(
        "EXISTS (SELECT 1 FROM json_each(channels.detected_genres) AS dg_je "
        "WHERE dg_je.value = :genre_target)"
    ).bindparams(genre_target=_target)
    q = (
        session.query(ChannelDB, MetadataDB)
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
            ChannelDB.detected_genres.isnot(None),
            _genre_match,
        )
    )
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids, progress_map)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_by_decade(session, decade: int, limit: int = 30, fav_ids=None,
                  queue_ids=None, watched_ids=None, liked_ids=None, progress_map=None,
                  excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                  adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                  excluded_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    results: list[ContentCard] = []
    for ch, meta in q.all():
        yr = _raw_year(ch)
        if yr and start <= yr <= end:
            results.append(_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids, progress_map))
    results.sort(key=lambda c: c.rating or 0, reverse=True)
    results = _dedup_cards(results)
    return results[:limit]


def get_featured_actor(session, weights=None, fav_ids=None, queue_ids=None,
                       watched_ids=None, liked_ids=None, progress_map=None,
                       excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                       adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                       excluded_provider_ids: list[str] | None = None,
                       ) -> tuple[str, list[ContentCard]]:
    """Return (actor_name, cards) for a Featured Actor shelf."""
    from metatv.core.database import ChannelDB

    actor: str | None = None

    if weights and weights.actors:
        positive = {k: v for k, v in weights.actors.items() if v > 0}
        if positive:
            actor = max(positive, key=lambda k: positive[k])

    if not actor:
        # Perf: select only the cast string via json_extract() in SQL so we
        # don't materialise full ORM objects with the entire raw_data blob.
        _cast_col = literal_column("json_extract(channels.raw_data, '$.cast')").label("cast")
        q = (
            session.query(_cast_col)
            .select_from(ChannelDB)
            .filter(
                ChannelDB.media_type == "series",
                ChannelDB.is_hidden == False,  # noqa: E712
                ChannelDB.raw_data.isnot(None),
                text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) >= 7.5"),
                text("json_extract(channels.raw_data, '$.cast') IS NOT NULL"),
                text("json_extract(channels.raw_data, '$.cast') != ''"),
            )
        )
        q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
        q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
        q = _apply_provider_exclusion(q, excluded_provider_ids)
        counter: Counter = Counter()
        for (cast_str,) in q.yield_per(5000):
            for name in [n.strip() for n in (cast_str or "").split(",") if n.strip()]:
                counter[name] += 1
        if counter:
            actor = counter.most_common(1)[0][0]

    if not actor:
        return ("", [])

    cards = get_by_actor(session, actor, limit=30,
                         fav_ids=fav_ids, queue_ids=queue_ids,
                         watched_ids=watched_ids, liked_ids=liked_ids,
                         progress_map=progress_map,
                         excluded_prefixes=excluded_prefixes,
                         include_uncategorized=include_uncategorized,
                         excluded_content_types=excluded_content_types,
                         excluded_keywords=excluded_keywords,
                         adult_mode=adult_mode,
                         force_adult_provider_ids=force_adult_provider_ids,
                         excluded_provider_ids=excluded_provider_ids)
    logger.debug(f"Featured actor: {actor!r} ({len(cards)} cards)")
    return (actor, cards)


def get_by_actor(session, actor: str, limit: int = 30, fav_ids=None,
                 queue_ids=None, watched_ids=None, liked_ids=None, progress_map=None,
                 excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                 adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                 excluded_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids, progress_map)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]


def get_all_genres(session, min_count: int = 10,
                   excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                   adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                   excluded_provider_ids: list[str] | None = None,
                   ) -> list[str]:
    """Return individual genre names that have ≥ min_count entries.

    Reads the ingestion-computed ``ChannelDB.detected_genres`` list (already
    split on ``/``/``,`` and canonicalised — cross-language aliases like
    Drame/Dramma/دراما already collapsed into "Drama", D5 / DR-0005) instead of
    parsing ``raw_data`` at query time. Only counts genres from channels that
    pass the global category filter.

    Perf (#genre-perf): selects only the small ``detected_genres`` column —
    no ``raw_data`` touch, no full ORM objects, no per-row string splitting —
    then streams with ``yield_per``.
    """
    from metatv.core.database import ChannelDB
    q = (
        session.query(ChannelDB.detected_genres)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.detected_genres.isnot(None),
        )
    )
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    counter: Counter = Counter()
    for (genres,) in q.yield_per(5000):
        for g in (genres or ()):
            counter[g] += 1
    return [g for g, cnt in counter.most_common() if cnt >= min_count]


def get_all_decades(session,
                    excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                    adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                    excluded_provider_ids: list[str] | None = None,
                    ) -> list[int]:
    """Return decades (as start year) that have ≥ 5 entries with a known year.

    Perf: selects only releaseDate/release_date (JSON) + name in SQL, avoiding
    full ORM object materialisation.  Year derivation runs in Python on those
    three small strings rather than on the whole raw_data blob.
    """
    from metatv.core.database import ChannelDB
    _rd_col   = literal_column("json_extract(channels.raw_data, '$.releaseDate')").label("release_date")
    _rd2_col  = literal_column("json_extract(channels.raw_data, '$.release_date')").label("release_date2")
    _name_col = ChannelDB.name.label("name")
    q = (
        session.query(_rd_col, _rd2_col, _name_col)
        .select_from(ChannelDB)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.raw_data.isnot(None),
        )
    )
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    decade_counts: Counter = Counter()
    for (rd, rd2, name) in q.yield_per(5000):
        yr: int | None = None
        for val in (rd, rd2):
            if val:
                m = re.match(r"(\d{4})", str(val))
                if m:
                    yr = int(m.group(1))
                    break
        if yr is None and name:
            m = _YEAR_EXTRACT_RE.search(name)
            if m:
                yr = int(m.group(1))
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
                                excluded_content_types=None,
                                excluded_keywords=None,
                                ) -> list[str]:
    """Sort genres so those with more liked content appear first.

    Reads the ingestion-computed ``detected_genres`` list — bounded by
    ``liked_ids`` (typically small) so this was never the perf hotspot, but
    reading the stored field keeps every genre read on one chokepoint.
    """
    if not liked_ids:
        return genres
    from metatv.core.database import ChannelDB
    genre_score: dict[str, int] = dict.fromkeys(genres, 0)
    q = (
        session.query(ChannelDB.detected_genres)
        .filter(ChannelDB.id.in_(liked_ids))
    )
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    for (dg,) in q.yield_per(5000):
        for g in (dg or ()):
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
                          progress_map=None,
                          excluded_prefixes=None, include_uncategorized: bool = True,
                       excluded_content_types=None,
                       excluded_keywords=None,
                          adult_mode: str = "all",
                          force_adult_provider_ids: list[str] | None = None,
                          excluded_provider_ids: list[str] | None = None,
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
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    rows = q.order_by(ChannelDB.name).limit(limit).all()
    return [
        _to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids, progress_map)
        for ch, meta in rows
    ]


# ---------------------------------------------------------------------------
# Collection shelves — provider-category "Collections" (What's New #256)
# ---------------------------------------------------------------------------

# A collection with only one member is noise, not a shelf — floor below which
# get_all_collections() drops it. Named constant per CLAUDE.md ("no magic
# numbers"), not inlined at each call site.
MIN_COLLECTION_SHELF_MEMBERS = 2


def get_all_collections(session, min_count: int = MIN_COLLECTION_SHELF_MEMBERS,
                        excluded_prefixes=None, include_uncategorized: bool = True,
                        excluded_content_types=None,
                        excluded_keywords=None,
                        adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                        excluded_provider_ids: list[str] | None = None,
                        ) -> list[str]:
    """Return ``detected_collection`` names with >= min_count member channels.

    Mirrors ``get_all_genres``'s shape and scoping parameters, but reads the
    ingestion-computed ``ChannelDB.detected_collection`` column — a single
    clean category label (e.g. "Apple+ Kids", "Hindu Subs") with its leading
    bracket marker and any redundant quality/media-type/multi-sub tokens
    already stripped by ``update_detected_prefixes()``
    (``core/repositories/channel.py``, #252). Never re-parses ``channel.name``
    or ``channel.category`` at query time (CLAUDE.md "compute once at
    ingestion, read everywhere else").

    Applies the same global-exclusion / adult / provider-scoping chokepoints
    as every other shelf query — a hidden-provider channel must never be
    counted toward a collection's member total (CLAUDE.md "disabled/expired
    sources are an absolute gate").

    Ordered deterministically — member count descending, then name ascending
    — so repeated Discover loads never reshuffle equal-count shelves (unlike
    ``Counter.most_common()``'s unspecified tie order).
    """
    from metatv.core.database import ChannelDB
    q = (
        session.query(ChannelDB.detected_collection)
        .filter(
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.detected_collection.isnot(None),
        )
    )
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    counter: Counter = Counter()
    for (collection,) in q.yield_per(5000):
        counter[collection] += 1
    eligible = [(name, cnt) for name, cnt in counter.items() if cnt >= min_count]
    eligible.sort(key=lambda t: (-t[1], t[0]))
    return [name for name, _cnt in eligible]


def get_by_collection(session, collection: str, limit: int = 30, fav_ids=None,
                      queue_ids=None, watched_ids=None, liked_ids=None, progress_map=None,
                      excluded_prefixes=None, include_uncategorized: bool = True,
                      excluded_content_types=None,
                      excluded_keywords=None,
                      adult_mode: str = "all", force_adult_provider_ids: list[str] | None = None,
                      excluded_provider_ids: list[str] | None = None,
                      ) -> list[ContentCard]:
    """Content whose ingestion-computed collection label matches *collection*.

    *collection* is the exact string returned by ``get_all_collections`` — the
    stored ``ChannelDB.detected_collection`` value. Matched by plain equality
    against that stored column, never a re-parse of ``channel.category`` or
    ``channel.name`` (CLAUDE.md "compute once at ingestion, read everywhere
    else"; contrast with ``get_by_genre``'s ``json_each`` membership match,
    which exists only because ``detected_genres`` is a multi-value list —
    ``detected_collection`` is a single string, so equality is the correct
    match, not a different shape).

    Same scoping chokepoints as every other shelf query (prefix/content-type/
    keyword exclusion, adult filter, hidden-provider exclusion) and the same
    cross-source ``content_key`` dedup as the genre/decade/actor shelves.
    """
    from metatv.core.database import ChannelDB, MetadataDB
    q = (
        session.query(ChannelDB, MetadataDB)
        .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.detected_collection == collection,
            ChannelDB.is_hidden == False,  # noqa: E712
        )
    )
    q = _apply_prefix_filter(q, excluded_prefixes, include_uncategorized, excluded_content_types, excluded_keywords)
    q = _apply_adult_filter(q, adult_mode, force_adult_provider_ids)
    q = _apply_provider_exclusion(q, excluded_provider_ids)
    rows = q.order_by(
        text("CAST(json_extract(channels.raw_data, '$.rating') AS REAL) DESC")
    ).limit(limit * 5).all()
    cards = [_to_card(ch, meta, fav_ids, queue_ids, watched_ids, liked_ids, progress_map)
             for ch, meta in rows]
    return _dedup_cards(cards)[:limit]
