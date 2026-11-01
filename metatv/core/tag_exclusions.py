"""Tag-valued Global Exclusions — content type, channel category and genre.

These exclusions match a channel's stored TAGS rather than columns on
``ChannelDB``, so they share one predicate shape: a membership test against
``content_tags``. They also share one wire format, so every surface that
already threads the content-type slug set (channel list, Discover,
Recommendations, tag counts, EPG On-Now, "Other Versions") picks up the new
axes with no new parameter:

* a bare value (``ai_generated``) is a ``content_type`` tag;
* ``category:Kids`` is a ``category`` tag (what a live channel IS);
* ``genre:Horror`` hides a channel carrying ANY excluded genre;
* ``genre-only:Horror`` hides a channel whose genres are ALL excluded — the
  default, because provider genre tagging is sloppy ("Drama, Religion,
  History") and "any" hides ten times more (Horror: 5,491 titles vs 516);
* ``collection:<provider_id>\t<value>`` hides one source's ``collection``
  tag (its provider category, e.g. "Au Espn Play") — keyed by source, since
  104 collection names recur on other sources that the user did not exclude;
* ``upcoming-events:<seconds>`` or ``upcoming-events:refresh`` ("Hide live
  events that start more than N in the future") hides a slot starting beyond
  the threshold — with ``refresh``, its own source's NEXT catalog refresh
  (last refresh + cycle; now + cycle when overdue; 24 hours for a manual
  source), since a game past the next refresh is re-read before it matters. Empty
  slots are stored with their far-future sentinel start, so they always are;
* ``ended-events`` ("Hide finished events") hides a fixture slot whose
  scheduled window has passed — the same window the row's "Ended" label uses
  (``event_datetime.event_is_on_now``). Names marked "END |" are the prefix
  rule's job (``filter_utils.global_exclusion_set``); a passed slot carries no
  such marker (the FLO NETWORK fixtures), so it needs this.

``excluded_tag_content_types(config)`` is the one paused-aware builder of that
set; ``tag_content_type_exclusion_criterion`` is the SQL KEEP clause and
``excluded_channel_ids`` its materialised twin for row-by-row surfaces. Never
hand-roll a parallel tag check (single chokepoint, CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:                       # pragma: no cover
    from datetime import datetime

CATEGORY_PREFIX = "category:"
COLLECTION_PREFIX = "collection:"
GENRE_ANY_PREFIX = "genre:"
GENRE_ONLY_PREFIX = "genre-only:"

ENDED_EVENTS = "ended-events"
UPCOMING_PREFIX = "upcoming-events:"

#: The threshold units the Exclusions dialog offers, in seconds. A month and a
#: year are approximate on purpose — "more than 2 months away" needs no calendar.
#: The default: each source's ``refresh_schedule`` (catalog_refresh), 24 hours
#: for a manual or on-launch source that has no cycle.
UPCOMING_REFRESH = "refresh"
UPCOMING_FALLBACK_S = 24 * 3600

UPCOMING_UNITS: dict[str, int] = {
    "minutes": 60, "hours": 3600, "days": 86400, "weeks": 7 * 86400,
    "months": 30 * 86400, "years": 365 * 86400,
}

GENRE_MODE_ONLY = "only"
GENRE_MODE_ANY = "any"


@dataclass(frozen=True)
class TagExclusions:
    """The encoded slug set, split back into its axes."""

    content_types: frozenset[str] = field(default_factory=frozenset)
    categories: frozenset[str] = field(default_factory=frozenset)
    genres: frozenset[str] = field(default_factory=frozenset)
    genre_only: bool = True
    ended_events: bool = False
    collections: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    upcoming: str | None = None   # seconds as digits, or UPCOMING_REFRESH


def collection_slug(provider_id: str, value: str) -> str:
    """Encode one excluded (source, collection) pair."""
    return f"{COLLECTION_PREFIX}{provider_id}\t{value}"


def split_tag_exclusions(slugs) -> TagExclusions:
    """Decode the wire format described in the module docstring.

    Args:
        slugs: The set built by :func:`excluded_tag_content_types`.

    Returns:
        The per-axis value sets. A set mixing both genre forms (never built by
        the builder) is treated as ``any`` — the stricter reading.
    """
    content_types, categories, genres = set(), set(), set()
    genre_only = True
    ended = False
    collections = set()
    upcoming = None
    for s in slugs or ():
        if s == ENDED_EVENTS:
            ended = True
        elif s.startswith(UPCOMING_PREFIX):
            upcoming = s[len(UPCOMING_PREFIX):]
        elif s.startswith(COLLECTION_PREFIX):
            pid, _, value = s[len(COLLECTION_PREFIX):].partition("\t")
            collections.add((pid, value))
        elif s.startswith(CATEGORY_PREFIX):
            categories.add(s[len(CATEGORY_PREFIX):])
        elif s.startswith(GENRE_ONLY_PREFIX):
            genres.add(s[len(GENRE_ONLY_PREFIX):])
        elif s.startswith(GENRE_ANY_PREFIX):
            genres.add(s[len(GENRE_ANY_PREFIX):])
            genre_only = False
        else:
            content_types.add(s)
    return TagExclusions(frozenset(content_types), frozenset(categories), frozenset(genres),
                         genre_only, ended, frozenset(collections), upcoming)


def excluded_tag_content_types(config) -> set[str]:
    """Return the user's active tag Global Exclusions in the encoded form.

    Named for its first axis (content type); it now carries all three. Empty
    when Global Exclusions are paused (``global_filter_paused``) or nothing is
    configured.

    Args:
        config: The application ``Config`` (read on the control thread; the
            engine layers receive the resolved set, never ``Config`` — DR-0007).

    Returns:
        The encoded slugs to exclude.
    """
    if getattr(config, "global_filter_paused", False):
        return set()
    out = set(getattr(config, "global_filter_excluded_tag_content_types", []) or [])
    out |= {CATEGORY_PREFIX + v for v in getattr(config, "global_filter_excluded_channel_categories", []) or []}
    mode = getattr(config, "global_filter_genre_mode", GENRE_MODE_ONLY)
    prefix = GENRE_ANY_PREFIX if mode == GENRE_MODE_ANY else GENRE_ONLY_PREFIX
    out |= {prefix + v for v in getattr(config, "global_filter_excluded_genres", []) or []}
    if not getattr(config, "show_ended_events", False):
        out.add(ENDED_EVENTS)
    out |= {collection_slug(p, v) for p, v in getattr(config, "global_filter_excluded_collections", []) or []}
    if getattr(config, "hide_upcoming_events", False):
        unit = getattr(config, "upcoming_events_unit", UPCOMING_REFRESH)
        if unit == UPCOMING_REFRESH:
            out.add(UPCOMING_PREFIX + UPCOMING_REFRESH)
        else:
            amount = max(0, int(getattr(config, "upcoming_events_amount", 24) or 0))
            out.add(f"{UPCOMING_PREFIX}{amount * UPCOMING_UNITS.get(unit, 3600)}")
    return out


def _has_tag(channel_key_col, tag_type: str, values, outside: bool = False):
    """Correlated EXISTS: the channel carries a *tag_type* tag in (or, with
    *outside*, NOT in) *values*. Generated and user tags both count."""
    from sqlalchemy import exists, select
    from sqlalchemy.orm import aliased

    from metatv.core.database import ContentTagDB, TagDB

    _ct = aliased(ContentTagDB, flat=True)
    _t = aliased(TagDB, flat=True)
    match = _t.value.notin_(list(values)) if outside else _t.value.in_(list(values))
    return exists(
        select(_ct.channel_key)
        .join(_t, _t.id == _ct.tag_id)
        .where(_ct.channel_key == channel_key_col, _t.type == tag_type, match)
        .correlate_except(_ct, _t)
    )


def _ended(channel_cls, now):
    """A fixture slot whose window is over at *now*: started, and past its own
    stop or, with none, ``DEFAULT_EVENT_DURATION`` after the start. The SQL
    twin of ``not event_is_on_now`` after the start, for stored UTC times."""
    from sqlalchemy import and_, func, or_

    from metatv.core.event_datetime import DEFAULT_EVENT_DURATION

    start, stop = channel_cls.event_start_time, channel_cls.event_stop_time
    hours = int(DEFAULT_EVENT_DURATION.total_seconds() // 3600)
    default_stop = func.datetime(start, f"+{hours} hours")
    return and_(start.isnot(None), or_(
        and_(stop.isnot(None), stop <= now),
        and_(stop.is_(None), default_stop <= func.datetime(now)),
    ))


def _upcoming(channel_cls, now, spec: str):
    """A slot starting further ahead than *spec* allows (stored UTC): a fixed
    number of seconds, or its own source's refresh cycle."""
    from datetime import timedelta

    from sqlalchemy import case, func, select

    from metatv.core.catalog_refresh import CATALOG_REFRESH_THRESHOLDS
    from metatv.core.database import ProviderDB

    if spec != UPCOMING_REFRESH:
        return channel_cls.event_start_time > now + timedelta(seconds=int(spec))
    fallback = func.datetime(now, f"+{UPCOMING_FALLBACK_S} seconds")
    cycle = case(*[(ProviderDB.refresh_schedule == k, f"+{int(td.total_seconds())} seconds")
                   for k, td in CATALOG_REFRESH_THRESHOLDS.items()], else_=None)
    next_refresh = func.datetime(ProviderDB.last_catalog_refresh_at, cycle)
    threshold = case(
        (cycle.is_(None), fallback),                              # manual / on launch
        (next_refresh > func.datetime(now), next_refresh),         # the scheduled next refresh
        else_=func.datetime(now, cycle),                           # overdue or never stamped
    )
    per_source = select(threshold).where(ProviderDB.id == channel_cls.provider_id).scalar_subquery()
    return channel_cls.event_start_time > func.coalesce(per_source, fallback)


def next_refresh_times(session, now) -> list[tuple[str, datetime]]:
    """``(source name, next scheduled refresh)`` for each active source with a
    cycle — the Python twin of the ``refresh`` threshold above, for display."""

    from metatv.core.catalog_refresh import CATALOG_REFRESH_THRESHOLDS
    from metatv.core.database import ProviderDB

    out = []
    for name, schedule, last in session.query(
            ProviderDB.name, ProviderDB.refresh_schedule, ProviderDB.last_catalog_refresh_at
    ).filter(ProviderDB.is_active.is_(True)).all():
        cycle = CATALOG_REFRESH_THRESHOLDS.get(schedule or "")
        if cycle is None:
            continue
        nxt = last + cycle if last is not None and last + cycle > now else now + cycle
        out.append((name, nxt))
    return sorted(out, key=lambda r: r[1])


def _has_upcoming_event(channel_key_col, now, spec: str):
    from sqlalchemy import exists, select
    from sqlalchemy.orm import aliased

    from metatv.core.database import ChannelDB

    _c = aliased(ChannelDB, flat=True)
    return exists(select(_c.channel_key).where(_c.channel_key == channel_key_col, _upcoming(_c, now, spec))
                  .correlate_except(_c))


def _has_ended_event(channel_key_col, now):
    from sqlalchemy import exists, select
    from sqlalchemy.orm import aliased

    from metatv.core.database import ChannelDB

    _c = aliased(ChannelDB, flat=True)
    return exists(select(_c.channel_key).where(_c.channel_key == channel_key_col, _ended(_c, now))
                  .correlate_except(_c))


def _collection_match(tag_cls, channel_cls, pairs):
    from sqlalchemy import and_, or_
    return and_(tag_cls.type == "collection",
                or_(*[and_(channel_cls.provider_id == p, tag_cls.value == v) for p, v in pairs]))


def _has_collection(channel_key_col, pairs):
    """Correlated EXISTS: the channel carries an excluded collection on its own source."""
    from sqlalchemy import exists, select
    from sqlalchemy.orm import aliased

    from metatv.core.database import ChannelDB, ContentTagDB, TagDB

    _ct, _t, _c = (aliased(m, flat=True) for m in (ContentTagDB, TagDB, ChannelDB))
    return exists(
        select(_ct.channel_key)
        .join(_t, _t.id == _ct.tag_id)
        .join(_c, _c.channel_key == _ct.channel_key)
        .where(_ct.channel_key == channel_key_col, _collection_match(_t, _c, pairs))
        .correlate_except(_ct, _t, _c)
    )


def tag_exclusion_hit(excluded_slugs, channel_key_col):
    """The clause that is TRUE for an excluded channel (``None`` when nothing is excluded)."""
    from sqlalchemy import and_, or_

    ex = split_tag_exclusions(excluded_slugs)
    hits = []
    if ex.content_types:
        hits.append(_has_tag(channel_key_col, "content_type", ex.content_types))
    if ex.categories:
        hits.append(_has_tag(channel_key_col, "category", ex.categories))
    if ex.genres:
        hit = _has_tag(channel_key_col, "genre", ex.genres)
        if ex.genre_only:
            hit = and_(hit, ~_has_tag(channel_key_col, "genre", ex.genres, outside=True))
        hits.append(hit)
    if ex.ended_events:
        from metatv.core.epg_utils import now_utc
        hits.append(_has_ended_event(channel_key_col, now_utc()))
    if ex.collections:
        hits.append(_has_collection(channel_key_col, ex.collections))
    if ex.upcoming is not None:
        from metatv.core.epg_utils import now_utc
        hits.append(_has_upcoming_event(channel_key_col, now_utc(), ex.upcoming))
    return or_(*hits) if hits else None


def tag_content_type_exclusion_criterion(excluded_slugs, channel_key_col):
    """Return the SQLAlchemy KEEP criterion for the tag Global Exclusions.

    Keeps exactly the channels no tag axis excludes, as correlated
    ``NOT EXISTS`` clauses — no id-set is materialised, so pagination and row
    counts stay in SQL over 1M+ ``content_tags`` rows.

    Args:
        excluded_slugs: Built by :func:`excluded_tag_content_types`. Empty → a
            tautology.
        channel_key_col: The outer query's ``channel_key`` column to correlate on.

    Returns:
        A boolean clause for ``.filter(...)``.
    """
    from sqlalchemy import true

    hit = tag_exclusion_hit(excluded_slugs, channel_key_col)
    return true() if hit is None else ~hit


def excluded_channel_ids(session, excluded_slugs) -> set[str]:
    """The materialised twin: ids of every channel the tag axes exclude.

    For the row-by-row surfaces (channel list Python pass, EPG On-Now, details
    "Other Versions") that hold rows/DTOs carrying no tags. Same clause as the
    SQL form, evaluated once.

    Args:
        session: An open SQLAlchemy session.
        excluded_slugs: Built by :func:`excluded_tag_content_types`.

    Returns:
        Channel id strings; empty when nothing is excluded.
    """
    from sqlalchemy import and_, or_

    from metatv.core.database import ChannelDB, ContentTagDB, TagDB

    ex = split_tag_exclusions(excluded_slugs)
    axes = [(t, v) for t, v in (("content_type", ex.content_types), ("category", ex.categories),
                                ("genre", ex.genres)) if v]
    out: set[str] = set()
    if ex.ended_events:
        from metatv.core.epg_utils import now_utc
        out = {cid for (cid,) in session.query(ChannelDB.id).filter(_ended(ChannelDB, now_utc())).all()}
    if ex.upcoming is not None:
        from metatv.core.epg_utils import now_utc
        out |= {cid for (cid,) in session.query(ChannelDB.id)
                .filter(_upcoming(ChannelDB, now_utc(), ex.upcoming)).all()}
    if ex.collections:
        out |= {cid for (cid,) in session.query(ChannelDB.id)
                .join(ContentTagDB, ContentTagDB.channel_key == ChannelDB.channel_key)
                .join(TagDB, TagDB.id == ContentTagDB.tag_id)
                .filter(_collection_match(TagDB, ChannelDB, ex.collections)).distinct().all()}
    if not axes:
        return out
    # Driven from the tag index (only matching rows are touched), never a scan of
    # every channel evaluating EXISTS.
    match = or_(*[and_(TagDB.type == t, TagDB.value.in_(list(v))) for t, v in axes])
    q = (session.query(ChannelDB.id)
         .join(ContentTagDB, ContentTagDB.channel_key == ChannelDB.channel_key)
         .join(TagDB, TagDB.id == ContentTagDB.tag_id)
         .filter(match))
    if ex.genres and ex.genre_only:
        q = q.filter(or_(TagDB.type != "genre",
                         ~_has_tag(ChannelDB.channel_key, "genre", ex.genres, outside=True)))
    return out | {cid for (cid,) in q.distinct().all()}
