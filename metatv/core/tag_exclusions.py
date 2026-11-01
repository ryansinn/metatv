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
  History") and "any" hides ten times more (Horror: 5,491 titles vs 516).

``excluded_tag_content_types(config)`` is the one paused-aware builder of that
set; ``tag_content_type_exclusion_criterion`` is the SQL KEEP clause and
``excluded_channel_ids`` its materialised twin for row-by-row surfaces. Never
hand-roll a parallel tag check (single chokepoint, CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

CATEGORY_PREFIX = "category:"
GENRE_ANY_PREFIX = "genre:"
GENRE_ONLY_PREFIX = "genre-only:"

GENRE_MODE_ONLY = "only"
GENRE_MODE_ANY = "any"


@dataclass(frozen=True)
class TagExclusions:
    """The encoded slug set, split back into its axes."""

    content_types: frozenset[str] = field(default_factory=frozenset)
    categories: frozenset[str] = field(default_factory=frozenset)
    genres: frozenset[str] = field(default_factory=frozenset)
    genre_only: bool = True


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
    for s in slugs or ():
        if s.startswith(CATEGORY_PREFIX):
            categories.add(s[len(CATEGORY_PREFIX):])
        elif s.startswith(GENRE_ONLY_PREFIX):
            genres.add(s[len(GENRE_ONLY_PREFIX):])
        elif s.startswith(GENRE_ANY_PREFIX):
            genres.add(s[len(GENRE_ANY_PREFIX):])
            genre_only = False
        else:
            content_types.add(s)
    return TagExclusions(frozenset(content_types), frozenset(categories), frozenset(genres), genre_only)


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
    if not axes:
        return set()
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
    return {cid for (cid,) in q.distinct().all()}
