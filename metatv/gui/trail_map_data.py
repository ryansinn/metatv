"""Worker-side data layer for the Explore trail-map (no Qt imports).

The trail-map view is a *dumb* Qt overlay: every DB read happens off the UI thread
and returns the frozen :class:`TrailRowDTO` (ORM objects never cross the thread
boundary — ORM-to-DTO rule).  This module owns that shaping so it is unit-testable
against a real ``Database`` without a running ``QApplication``.

Data-source-agnostic by design (the reuse the feature is built for): the view calls
a *seed loader* for column 0 and :func:`load_similar_rows` for each drilled column.
Every Explore entry point swaps only the seed loader — the lightbox nav-stack
(:func:`load_seed_rows`), Watch History (:func:`load_history_seed_rows`), Favorites /
Watch Queue (:func:`load_engaged_seed_rows`) and Recommended (plain seed rows).  The
row DTO already carries the optional ``watch_count`` / ``last_watched`` fields the
engaged-record modes add.

Scoping (DR-0007): the *seed* trail is a record of engaged content, so it is shown
as-walked (exempt) — History, Favorites and the Watch Queue are all record views.
Recommended is forward-looking, so its seed goes through the preference engine WITH
the ``excluded_provider_ids`` gate.  The *similar* columns are forward-looking
discovery too, so they go through the ``get_similar_channels`` chokepoint with the
caller's ``excluded_provider_ids`` gate (inactive ∪ expired ∪ orphaned).
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


def _fmt_last_watched(dt) -> str | None:
    """Format a ``last_played`` timestamp as a short, friendly "when" string.

    ``last_played`` is written via ``datetime.now()`` (local, naive) — it is NOT an
    EPG start/stop time, so the epg_utils timezone chokepoint does not apply here and
    plain local arithmetic is correct.  Returns ``None`` for a missing timestamp.
    """
    if not dt:
        return None
    from datetime import datetime

    now = datetime.now()
    secs = max(0.0, (now - dt).total_seconds())
    if secs < 3600:
        mins = int(secs // 60)
        return "just now" if mins < 1 else f"{mins}m ago"
    days = (now.date() - dt.date()).days
    if days <= 0:
        return f"{int(secs // 3600)}h ago"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days}d ago"
    month = dt.strftime("%b")
    if dt.year == now.year:
        return f"{month} {dt.day}"
    return f"{month} {dt.day}, {dt.year}"


def _row_from_channel(
    session, ch, queue_ids: set, ratings_map: dict, *, history_extras: bool = False
) -> TrailRowDTO:
    """Map one ``ChannelDB`` row → ``TrailRowDTO`` (called inside the read session).

    Reads the ★rating + poster from the channel's already-linked metadata row and
    resolves the poster zero-network from the channel's own provider data first
    (``channel_thumbnail`` — the resolver Discover cards use), so building a column
    never fires a per-row network fetch.  Engagement state comes from the two maps
    the caller reads once (queue ids + ratings), never a per-row query.

    ``history_extras`` populates the Watch-History-mode fields (``watch_count`` =
    ``play_count``, ``last_watched`` formatted from ``last_played``) so the shared row
    + detail renderers show "watched N× · <when>".  The watch-state fields
    (progress/completed) that drive the badges and the Play/Resume label are always
    set, so history rows surface the correct watch badge + Play affordance regardless.
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
        watch_count=(int(ch.play_count or 0) if history_extras else None),
        last_watched=(_fmt_last_watched(ch.last_played) if history_extras else None),
    )


def _engagement_maps(session):
    """Read the queued-id set and the rating map ONCE (perf: not per-row)."""
    from metatv.core.database import UserRatingDB
    from metatv.core.repositories import RepositoryFactory

    repos = RepositoryFactory(session)
    queue_ids = set(repos.queue.get_queued_ids())
    ratings_map = {r.channel_id: r.rating for r in session.query(UserRatingDB).all()}
    return queue_ids, ratings_map


def _hydrate_seed_rows(
    session, ids: list[str], *, history_extras: bool = False
) -> list[TrailRowDTO]:
    """Hydrate *ids* → ``TrailRowDTO`` in the given order (the one seed-row core).

    Every seed loader in this module funnels through here — one ordered read + the
    two engagement maps, then per-row mapping.  ``history_extras`` turns on the
    engaged-record fields (``watch_count`` / ``last_watched``).  Missing ids are
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
            out.append(
                _row_from_channel(
                    session, ch, queue_ids, ratings_map, history_extras=history_extras
                )
            )
    return out


def load_seed_rows(session, ids: list[str]) -> list[TrailRowDTO]:
    """Hydrate the seed (column 0) rows for *ids*, preserving order.

    The lightbox's walked trail (and the Recommended Explore seed, whose titles are
    forward-looking so the "watched N×" extras would always be empty).  Not
    provider-scoped here: the caller decides what belongs in column 0 — the
    Recommended id loader applies its own ``excluded_provider_ids`` gate.
    """
    return _hydrate_seed_rows(session, ids)


def load_engaged_seed_rows(session, ids: list[str] | None = None) -> list[TrailRowDTO]:
    """Hydrate an ENGAGED-record seed (Favorites / Watch Queue) with the watch extras.

    Same core as :func:`load_seed_rows` plus ``watch_count`` / ``last_watched``, so a
    favorited or queued title shows "watched N× · <when>" exactly as a history stop
    does.  As record views these are NOT provider-scoped (DR-0007 exemption): a
    favorite on a since-inactive source is still a favorite.
    """
    return _hydrate_seed_rows(session, ids or [], history_extras=True)


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


# Explore seed size (History / Favorites / Watch Queue).  The trail column scrolls,
# so this is a generous cap, not a page — it bounds the one ordered read each view
# issues.  ``HISTORY_SEED_LIMIT`` is the original name, kept as the alias.
EXPLORE_SEED_LIMIT = 200
HISTORY_SEED_LIMIT = EXPLORE_SEED_LIMIT


def load_history_ids(
    session, limit: int = HISTORY_SEED_LIMIT, adult_mode: str = "all"
) -> list[str]:
    """Return recently-played channel ids, most-recent first.

    The single ordering chokepoint is ``ChannelRepository.get_recent_history`` (the
    same query the History sidebar uses); this just projects it to ids so the Full
    History view can seed the trail-map with the *actual* engaged ids (dedup stays
    correct).  As a RECORD view, history is NOT provider-scoped — a stop whose source
    later went inactive is still part of the record (DR-0007 record-view exemption).
    """
    from metatv.core.repositories import RepositoryFactory

    repos = RepositoryFactory(session)
    return [
        ch.id
        for ch in repos.channels.get_recent_history(limit=limit, adult_mode=adult_mode)
    ]


def load_history_seed_rows(
    session, ids: list[str] | None = None, *, limit: int = HISTORY_SEED_LIMIT
) -> list[TrailRowDTO]:
    """Hydrate the Watch-History seed (column 0) as ``TrailRowDTO``s.

    The Full History view's history-backed seed loader (the data-source-agnostic
    reuse the trail-map was built for).  Rows carry the history extras
    (``watch_count`` / ``last_watched``) plus the always-set watch state, so the
    shared row renderer shows the watch badges and the detail strip's Play/Resume
    label works.

    When *ids* is given the rows are hydrated in that order (the view passes the ids
    it seeded ``open`` with, so ordering + path-dedup line up).  When *ids* is None
    the loader resolves the recent-history order itself via
    :func:`load_history_ids` — the convenience shape used directly + in tests.

    As a RECORD view this is NOT provider-scoped: a played title on a since-inactive
    source still appears (DR-0007 record-view exemption).  Missing ids are dropped.
    """
    if ids is None:
        ids = load_history_ids(session, limit=limit)
    return load_engaged_seed_rows(session, ids)


def load_favorite_ids(
    session, limit: int = EXPLORE_SEED_LIMIT, adult_mode: str = "all"
) -> list[str]:
    """Return favorited channel ids in the SAME order the Favorites rail shows them.

    One ordering source of truth with the sidebar section: the shared
    ``ChannelRepository.get_favorites_dto`` read, split into "Continue Watching"
    (``last_played`` desc) then "Never Watched" (by name) exactly as
    ``FavoritesSection._populate_rows`` does — so Explore's column 0 reads as the
    rail, made walkable.

    Favorites is a RECORD view (DR-0007 exemption): entries on inactive/expired
    sources are NOT dropped, they are simply annotated unavailable by the repository.
    """
    from metatv.core.repositories import RepositoryFactory

    repos = RepositoryFactory(session)
    dtos = repos.channels.get_favorites_dto(adult_mode=adult_mode)
    watched = sorted(
        [d for d in dtos if d.last_played], key=lambda d: d.last_played, reverse=True
    )
    never = sorted([d for d in dtos if not d.last_played], key=lambda d: d.name)
    return [d.id for d in (*watched, *never)][:limit]


def load_queue_ids(session, limit: int = EXPLORE_SEED_LIMIT) -> list[str]:
    """Return queued channel ids in the user's own queue order (``position``).

    Reads the single ``WatchQueueRepository.get_all`` chokepoint the sidebar uses, so
    Explore's column 0 is the queue as the user ordered it.  Orphaned entries (no
    surviving ``ChannelDB`` row) carry an id that hydration then drops — the trail-map
    can only walk titles that still exist in the corpus.

    The Watch Queue is a RECORD view (DR-0007 exemption): entries on inactive/expired
    sources stay in the seed.
    """
    from metatv.core.repositories import RepositoryFactory

    repos = RepositoryFactory(session)
    return [e.channel_id for e in repos.queue.get_all() if e.channel_id][:limit]


# Recommended Explore seed size.  Matches the sidebar rail's own ``limit=20`` so the
# Explore column shows the SAME set the rail does (not a deeper, divergent list).
RECOMMENDED_SEED_LIMIT = 20


def load_recommended_ids(
    session, config, limit: int = RECOMMENDED_SEED_LIMIT
) -> list[str]:
    """Return the current recommendations, in engine order — the rail's own call.

    Runs the SAME ``preference_engine`` scoring the Recommended sidebar section runs
    (``balance_media_types=True, diversify_people=True``, the same muted-attribute /
    dedupe-override / category-filter / hidden-provider inputs), so "Explore →" opens
    exactly what the rail is showing rather than a second, differently-tuned list.

    Unlike the rail this does NOT call ``record_impressions``: the rail already
    counted these titles as shown, and re-counting on every Explore open would decay
    them twice for one viewing.

    Recommendations are forward-looking (not a record view), so the hidden-provider
    gate applies — content on an inactive/expired source is never seeded.

    Returns an empty list when the user has no taste weights yet.
    """
    from metatv.core.filter_utils import get_active_category_filter
    from metatv.core.preference_engine import (
        compute_weights, score_candidates, version_score,
    )
    from metatv.core.repositories import RepositoryFactory

    weights = compute_weights(session)
    if weights.is_empty():
        return []
    excluded_prefixes, include_uncategorized = get_active_category_filter(config)
    hidden = RepositoryFactory(session).providers.get_hidden_provider_ids()
    recs = score_candidates(
        session, weights, limit=limit,
        muted_attrs=getattr(config, "muted_attributes", None),
        dedupe_overrides=set(getattr(config, "rec_dedupe_overrides", []) or []),
        excluded_prefixes=excluded_prefixes,
        include_uncategorized=include_uncategorized,
        excluded_provider_ids=hidden or None,
        version_scorer=lambda ch: version_score(ch, config),
        balance_media_types=True,
        diversify_people=True,
    )
    return [sc.channel_id for sc in recs]


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
