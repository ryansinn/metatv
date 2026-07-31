"""Worker-side data layer for the Explore trail-map (no Qt imports).

The trail-map view is a *dumb* Qt overlay: every DB read happens off the UI thread
and returns the frozen :class:`TrailRowDTO` (ORM objects never cross the thread
boundary — ORM-to-DTO rule).  This module owns that shaping so it is unit-testable
against a real ``Database`` without a running ``QApplication``.

Data-source-agnostic by design (the reuse the feature is built for): the view calls
:func:`load_seed_rows` for column 0 (the walked trail — the lightbox nav-stack today,
a Watch-History list tomorrow) and :func:`load_similar_rows` for each drilled column.
A future History view swaps only the seed loader; the row DTO already carries the
optional ``watch_count`` / ``last_watched`` fields that mode adds.

Scoping (DR-0007): the *seed* trail is a record of engaged content, so it is shown
as-walked (exempt).  The *similar* columns are forward-looking discovery, so they go
through the ``get_similar_channels`` chokepoint with the caller's
``excluded_provider_ids`` gate (inactive ∪ expired ∪ orphaned).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrailRowDTO:
    """Everything a trail-map row (and the detail strip's non-metadata fields) needs.

    Built inside the worker's ``session_scope`` and returned across the thread
    boundary in place of the ORM row.  ``dedup_key`` is the content identity used to
    keep a title from reappearing anywhere on the active path (no loops): the stored
    ``content_key`` when present, else the normalized title.
    """
    id: str
    title: str
    year: str | None
    poster_url: str | None
    media_type: str
    provider_id: str | None
    lang: str
    rating: float | None            # metadata ★ score (stored MetadataDB row)
    user_rating: int                # -1 / 0 / +1
    in_queue: bool
    is_favorite: bool
    is_suppressed: bool
    watch_progress: int             # resume position, seconds
    watch_completed: bool
    watch_percent: int
    dedup_key: str
    # Watch-History-mode extras — None/0 for the lightbox trail; a future History
    # seed loader populates them (rows then show "N× · last watched …").
    watch_count: int | None = None
    last_watched: str | None = None

    def as_badge_item(self) -> dict:
        """Return the dict the shared badge renderer (``sim_badges``) consumes."""
        return {
            "lang": self.lang,
            "rating": self.rating,
            "year": self.year,
            "user_rating": self.user_rating,
            "in_queue": self.in_queue,
            "is_favorite": self.is_favorite,
            "watched": self.watch_completed,
        }


def _dedup_key_for(ch) -> str:
    """Content identity for path de-dup: stored content_key, else normalized title."""
    if getattr(ch, "content_key", None):
        return ch.content_key
    from metatv.core.content_dedup import normalize_title
    return normalize_title(ch.name, ch.detected_prefix) or (ch.id or "")


def _row_from_channel(session, ch, queue_ids: set, ratings_map: dict) -> TrailRowDTO:
    """Map one ``ChannelDB`` row → ``TrailRowDTO`` (called inside the read session).

    Reads the ★rating + poster from the channel's already-linked metadata row and
    resolves the poster zero-network from the channel's own provider data first
    (``channel_thumbnail`` — the resolver Discover cards use), so building a column
    never fires a per-row network fetch.  Engagement state comes from the two maps
    the caller reads once (queue ids + ratings), never a per-row query.
    """
    from metatv.core.database import MetadataDB
    from metatv.core.discovery_engine import channel_thumbnail

    c_meta = session.get(MetadataDB, ch.metadata_id) if ch.metadata_id else None
    return TrailRowDTO(
        id=ch.id,
        title=ch.detected_title or ch.name,
        year=(c_meta.year if c_meta else None) or ch.detected_year,
        poster_url=channel_thumbnail(ch) or (c_meta.poster_url if c_meta else None),
        media_type=ch.media_type or "",
        provider_id=ch.provider_id,
        lang=(ch.detected_region or "").strip(),
        rating=(c_meta.rating if c_meta else None),
        user_rating=int(ratings_map.get(ch.id, 0) or 0),
        in_queue=ch.id in queue_ids,
        is_favorite=bool(ch.is_favorite),
        is_suppressed=bool(ch.is_rec_suppressed),
        watch_progress=int(ch.watch_progress or 0),
        watch_completed=bool(ch.watch_completed),
        watch_percent=int(ch.watch_percent or 0),
        dedup_key=_dedup_key_for(ch),
    )


def _engagement_maps(session):
    """Read the queued-id set and the rating map ONCE (perf: not per-row)."""
    from metatv.core.database import UserRatingDB
    from metatv.core.repositories import RepositoryFactory

    repos = RepositoryFactory(session)
    queue_ids = set(repos.queue.get_queued_ids())
    ratings_map = {r.channel_id: r.rating for r in session.query(UserRatingDB).all()}
    return queue_ids, ratings_map


def load_seed_rows(session, ids: list[str]) -> list[TrailRowDTO]:
    """Hydrate the seed (column 0) rows for *ids*, preserving order.

    The seed trail is engaged content (walked stops / history), so it is NOT
    provider-scoped — a stop whose source later went inactive is still part of the
    record and stays visible (DR-0007 record-view exemption).  Missing ids are
    silently dropped.
    """
    from metatv.core.database import ChannelDB

    if not ids:
        return []
    queue_ids, ratings_map = _engagement_maps(session)
    rows = session.query(ChannelDB).filter(ChannelDB.id.in_(ids)).all()
    by_id = {ch.id: ch for ch in rows}
    out: list[TrailRowDTO] = []
    for cid in ids:
        ch = by_id.get(cid)
        if ch is not None:
            out.append(_row_from_channel(session, ch, queue_ids, ratings_map))
    return out


def load_similar_rows(
    session,
    parent_id: str,
    *,
    excluded_provider_ids: set | None = None,
    config=None,
    limit: int = 20,
) -> list[TrailRowDTO]:
    """Similar titles for *parent_id* via the scoped ``get_similar_channels`` chokepoint.

    De-dup against the active path is applied by the CALLER at render time (it knows
    the current lineage); this returns the raw scoped neighbours so the view can
    cache them once per parent regardless of which path reaches that parent.
    """
    from metatv.core.repositories import RepositoryFactory

    repos = RepositoryFactory(session)
    queue_ids, ratings_map = _engagement_maps(session)
    neighbours = repos.channels.get_similar_channels(
        parent_id,
        excluded_provider_ids=excluded_provider_ids,
        limit=limit,
        config=config,
    )
    return [_row_from_channel(session, ch, queue_ids, ratings_map) for ch in neighbours]


def metadata_to_detail(meta) -> dict:
    """Map a ``MetadataResult`` (or ``None``) → the detail-strip's on-demand fields.

    Only the "rich" fields the strip shows *only-if-available* (good-on-raw-data):
    overview/cast/director/runtime + a ★rating fallback + genres.  Everything else
    the strip needs (title/year/watch state/favorite) comes from the cached
    ``TrailRowDTO``, so this never has to be complete.
    """
    if not meta:
        return {}
    raw_genres = getattr(meta, "genres", None)
    if isinstance(raw_genres, list):
        genres = [str(g).strip() for g in raw_genres if str(g).strip()]
    elif isinstance(raw_genres, str):
        genres = [g.strip() for g in raw_genres.split(",") if g.strip()]
    else:
        genres = []
    cast_names = [
        (p.get("name") or "")
        for p in (getattr(meta, "cast", None) or [])[:5]
        if isinstance(p, dict)
    ]
    return {
        "plot": getattr(meta, "plot", None) or "",
        "cast": ", ".join(n for n in cast_names if n),
        "director": (getattr(meta, "director", None) or "").strip(),
        "runtime": getattr(meta, "runtime", None),
        "rating": getattr(meta, "rating", None),
        "genres": genres,
    }
