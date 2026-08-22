"""Facet lenses: "everything matching this person / this genre", one definition.

A *lens* is the metadata-adjacency query behind a cast-name or genre click —
deliberately distinct from ``get_similar_channels``'s crude title-token
adjacency (DR-0003): same anchor, different neighbours, and the contrast is the
point.

Why this is a module and not more methods on ``ChannelRepository``
------------------------------------------------------------------
Two callers need the SAME answer or the feature lies to the user: the lightbox
lens (which pages the set inside the overlay) and the channel-list context chip
(where "See all in Search" lands). Keeping the predicates here — as plain
functions over a query — means neither can grow a private rule. It also keeps
them out of ``channel.py``, which is 4k lines of recorded debt the code-health
ratchet exists to stop growing.

Everything here is pure: functions take a query or rows and return a query or
rows. No session state, no Config held anywhere (the control layer resolves
exclusions and passes them in, same as ``VisibilityScope``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Set

from loguru import logger
from sqlalchemy import or_

from metatv.core.filter_utils import normalize_genre
from metatv.core.database import ChannelDB, MetadataDB

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

# Max rows a lens scans before collapsing (mirrors the Similar query's guard):
# one click must never become an unbounded table scan.
LENS_CANDIDATE_SCAN = 200

# Strict-genre only ever means movies/series — a live channel's provider genre
# is a bouquet label, not a production genre.
GENRE_MEDIA_TYPES = ["movie", "series"]


def metadata_person_exists(pattern: str):
    """Correlated EXISTS: the channel's ``MetadataDB`` row names this person.

    The chokepoint for "does this channel's *enriched* metadata mention this
    person" — shared by the free-text search predicate, the channel-list
    person filter and the lightbox lens. The details pane displays
    ``MetadataDB.cast``/``director``, so any filter over "who's in this" must
    match what is displayed, not the raw provider blob.

    ``MetadataDB.cast`` is a ``JSONEncoded`` (Text-backed) column holding
    ``[{"name": …, "character": …}]``; a substring ILIKE against the serialized
    JSON is enough for a name lookup. Both columns are wrapped in
    ``type_coerce(..., Text)`` first — without it SQLAlchemy runs the
    ``JSONEncoded`` bind-processor on the *pattern* too (JSON-encoding it into a
    quoted literal), which silently never matches.

    Args:
        pattern: A SQL LIKE/ILIKE pattern, e.g. ``f"%{name}%"``.
    """
    from sqlalchemy import (
        Text as _Text, exists as _exists, select as _sa_select,
        type_coerce as _type_coerce,
    )

    # correlate(ChannelDB) is REQUIRED: get_all() outerjoins MetadataDB (for the
    # list DTO's plot/poster columns), so without an explicit correlation
    # SQLAlchemy auto-correlates MetadataDB out of this subquery too and raises
    # "returned no FROM clauses due to auto-correlation".
    return _exists(
        _sa_select(MetadataDB.id)
        .where(
            MetadataDB.id == ChannelDB.metadata_id,
            or_(
                MetadataDB.director.ilike(pattern),
                _type_coerce(MetadataDB.cast, _Text).ilike(pattern),
            ),
        )
        .correlate(ChannelDB)
    )


def person_predicate(name: str):
    """Single definition of "this channel is associated with this person".

    Four sources, OR-ed, in order of trustworthiness:

    - the enriched ``MetadataDB`` cast/director (what the UI displays);
    - the channel NAME itself, **live included** — providers ship whole curated
      actor categories ("24/7 TOM HANKS", "BS| NICOLAS CAGE COLLECTION") and the
      parser folds a trailing performer into ``detected_title``, so the person
      is visibly on the row; hiding those is censorial (mirror-not-cage);
    - the raw provider ``cast`` / ``director`` blobs, for the ~99.8% of rows
      that were never enriched.

    Args:
        name: Raw person name; wildcards are added here.
    """
    from sqlalchemy import text as _text

    pattern = f"%{name}%"
    return or_(
        metadata_person_exists(pattern),
        ChannelDB.name.ilike(pattern),
        _text(
            "json_extract(raw_data, '$.cast') LIKE :_person_cast"
        ).bindparams(_person_cast=pattern),
        _text(
            "json_extract(raw_data, '$.director') LIKE :_person_dir"
        ).bindparams(_person_dir=pattern),
    )


def genre_predicate(genre: str):
    """Single definition of "this channel carries this genre".

    Matches the ingested ``detected_genres`` JSON array on the CANONICAL genre
    (so a French "Drame" click answers with the rows stored as "Drama"), falling
    back to a substring match on the raw provider genre for rows written before
    that field existed. Pair it with a ``media_type`` restriction to
    :data:`GENRE_MEDIA_TYPES`.

    Args:
        genre: Genre as displayed; canonicalised here.
    """
    from sqlalchemy import text as _text

    canon = normalize_genre(genre)
    return or_(
        _text(
            "EXISTS (SELECT 1 FROM json_each(channels.detected_genres) AS dg_je "
            "WHERE dg_je.value = :_strict_genre_exact)"
        ).bindparams(_strict_genre_exact=canon),
        _text(
            "json_extract(raw_data, '$.genre') LIKE :_strict_genre"
        ).bindparams(_strict_genre=f"%{genre}%"),
    )


def apply_global_exclusions(query, config):
    """AND the user's Global Exclusions onto a channel query.

    The SOFT (user-curated) axis — the category blacklist plus the explicit
    "Block [PREFIX]" codes — and the sibling of the absolute
    ``excluded_provider_ids`` gate. Shared by every in-overlay adjacency surface
    so a globally excluded language cannot leak into one of them while the
    others honour it; that drift is what made Recommendations show excluded
    content.

    The excluded SET comes from the shared ``filter_utils`` resolvers (single
    source of truth for the data); the SQL comes from the canonical
    ``discovery_engine._apply_prefix_filter``. ``config=None`` or a paused
    Global Filter applies nothing.
    """
    if config is None or getattr(config, "global_filter_paused", False):
        return query
    from metatv.core.discovery_engine import _apply_prefix_filter
    from metatv.core.filter_utils import (
        get_active_category_filter, get_excluded_prefixes,
    )

    cat_excluded, include_uncategorized = get_active_category_filter(config)
    excluded_prefixes = set(cat_excluded or []) | get_excluded_prefixes(config)
    return _apply_prefix_filter(
        query, list(excluded_prefixes) or None, include_uncategorized
    )


def collapse_best_variant(rows, config=None, limit=None) -> "List[ChannelDB]":
    """Collapse same-production variants, keeping the best copy of each.

    The read-time half of the content-identity rule: group on the STORED
    ``content_key`` (so localized/translated/"MULTI" copies collapse exactly as
    they do on Discover and in Other Versions), falling back to the normalized
    title only for rows written before the backfill. Within a group the winner
    is whichever the user's own version preferences score highest; without a
    *config* the first row encountered wins.

    Args:
        rows: Candidate ``ChannelDB`` rows, in preference order.
        config: Optional ``Config`` scoring the per-group winner.
        limit: Max groups to return (None = all).

    Returns:
        One row per content group, in first-seen group order.
    """
    from metatv.core.content_dedup import normalize_title
    from metatv.core.preference_engine import version_score

    best: "dict[str, tuple[ChannelDB, int]]" = {}
    for ch in rows:
        group_key = ch.content_key or normalize_title(ch.name, ch.detected_prefix)
        score = version_score(ch, config) if config is not None else 0
        existing = best.get(group_key)
        if existing is None or score > existing[1]:
            best[group_key] = (ch, score)
    out = [ch for ch, _ in best.values()]
    return out[:limit] if limit else out


def lens_channels(
    session: "Session",
    lens: str,
    value: str,
    excluded_provider_ids: "Optional[Set[str] | List[str]]" = None,
    limit: int = 24,
    config=None,
) -> "List[ChannelDB]":
    """Every visible title matching a facet, collapsed to one row per title.

    Resolves the SAME set the channel-list context chip would, because both
    route through :func:`person_predicate` / :func:`genre_predicate` — so the
    lightbox lens and "See all in Search" can never disagree.

    Visibility — every gate the other adjacency surfaces apply:

    - ``is_hidden == False`` (per-channel hide);
    - ``provider_id NOT IN excluded_provider_ids`` — the absolute DR-0007 gate
      (inactive ∪ expired ∪ orphaned), supplied by the caller from
      ``ProviderRepository.get_hidden_provider_ids()``;
    - the user's Global Exclusions, via :func:`apply_global_exclusions`.

    Args:
        session: Caller's open session; the rows are ORM objects, so consume
            them inside it and map to DTOs before crossing a thread.
        lens: ``"person"`` (cast or director) or ``"genre"``.
        value: The clicked name / genre, as displayed.
        excluded_provider_ids: Hidden provider ids to exclude.
        limit: Max collapsed titles to return.
        config: Optional ``Config`` — supplies the Global Exclusions and scores
            the per-title variant winner.

    Returns:
        Collapsed ``ChannelDB`` rows; ``[]`` for an unknown lens or empty value.
    """
    value = (value or "").strip()
    if not value:
        return []

    query = session.query(ChannelDB).filter(
        ChannelDB.is_hidden == False,  # noqa: E712 — per-channel hide gate
    )
    if lens == "person":
        query = query.filter(person_predicate(value))
    elif lens == "genre":
        query = query.filter(
            ChannelDB.media_type.in_(GENRE_MEDIA_TYPES),
            genre_predicate(value),
        )
    else:
        logger.warning("lens_channels: unknown lens '{}'", lens)
        return []

    excluded = list(excluded_provider_ids or [])
    if excluded:
        query = query.filter(~ChannelDB.provider_id.in_(excluded))
    query = apply_global_exclusions(query, config)

    # Ordering by name keeps the bounded scan window deterministic rather than
    # whatever order the planner happens to return.
    candidates = query.order_by(ChannelDB.name).limit(LENS_CANDIDATE_SCAN).all()
    return collapse_best_variant(candidates, config=config, limit=limit)
