"""Which streaming platforms earn their own Discover shelf, and which version leads.

Discover already rolls the catalogue up by genre, decade, actor, collection and
the user's own categories.  The one axis it never rolled up is the platform the
title came from — the tag ``platform:Netflix`` that ``tag_decomposer`` writes at
ingestion from the provider's name prefix.  A shelf per platform is that rollup.

Two decisions are encoded here rather than at the call site, because both are
answers a query would otherwise re-invent per surface:

**Which platforms qualify** (:func:`platform_shelf_values`) — a platform earns a
shelf once at least ``min_titles`` *distinct titles* carry its tag, counted the
way every other collapse surface counts (``COALESCE(content_key, 'id:' || id)``,
CLAUDE.md's content-identity rule), among VOD rows visible under the caller's
:class:`~metatv.core.channel_visibility.VisibilityScope`.  Distinct TITLES, not
rows: a library holding one film in six qualities is not six titles, and a
row-count threshold would let a handful of much-duplicated films open a shelf.

**Which version represents a title** (:func:`representative_version`) — the seam
VP-1 (Version Preferences, unbuilt) will fill.  It is deliberately a seam and
not a TODO comment: the platform shelf collapses versions today, so there is
exactly one place the choice has to be made, and it is this one.

Live channels are never in scope.  Discover is the VOD surface (owner, PLAT-1
Q2) — a platform shelf mixing tonight's football feed into a Netflix film list
answers a different question, and the Live surface that answers it is LIVE-1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from metatv.core.channel_visibility import VisibilityScope
    from metatv.core.discovery_engine import ContentCard

#: The tag namespace a platform shelf is keyed on.  A shelf key is
#: ``platform:<value>`` — the tag VALUE, so a decomposer rename moves the shelf
#: instead of orphaning it.
PLATFORM_FACET: str = "platform"

#: The only media types a platform shelf may contain (PLAT-1 Q2 — Discover is
#: VOD).  Shared by the threshold count and the card fetch so the number on the
#: threshold and the rows on the shelf are drawn from the same population.
PLATFORM_SHELF_MEDIA_TYPES: tuple[str, ...] = ("movie", "series")


def platform_shelf_values(
    session,
    *,
    min_titles: int,
    excluded_values: Iterable[str] = (),
    scope: "VisibilityScope",
) -> list[tuple[str, int]]:
    """Platform tag values carrying at least *min_titles* distinct visible titles.

    ONE aggregate query, never a count per platform: the library this was built
    against holds 786k channel rows and 1.2M tag rows, so a per-value loop is a
    per-value table scan on the Discover load path.

    Args:
        session: Open DB session.
        min_titles: Distinct-title floor a platform must clear to earn a shelf
            (``Config.discover_platform_shelf_min_titles``, default 50).
        excluded_values: Platform values that never get a shelf whatever their
            count — pass
            ``channel_name_utils.PLATFORM_SHELF_EXCLUDED_VALUES``.  Curated data
            lives there; this parameter exists so the engine holds no policy
            (DR-0007), not so a caller can invent a second list.
        scope: A fully-resolved :class:`VisibilityScope` — hidden providers,
            Global Exclusions, the adult gate and the VE-1 dead-signal floor.
            Build it with ``visibility_resolver.resolve_scope``.

    Returns:
        ``[(platform_value, distinct_title_count), …]``, highest count first,
        with ties broken alphabetically so the shelf order is stable between
        loads.  Empty when nothing clears the floor.
    """
    from sqlalchemy import func as _func

    from metatv.core import channel_visibility
    from metatv.core.database import ChannelDB, ContentTagDB, TagDB

    # The same group key every collapse surface uses (CLAUDE.md content
    # identity): the stored content_key, with each un-keyed row its own
    # singleton group so a NULL key never merges the whole library into one.
    group_key = _func.coalesce(
        ChannelDB.content_key, _func.concat("id:", ChannelDB.id)
    )
    titles = _func.count(_func.distinct(group_key))

    query = (
        session.query(TagDB.value, titles.label("titles"))
        .select_from(ContentTagDB)
        .join(TagDB, TagDB.id == ContentTagDB.tag_id)
        .join(ChannelDB, ChannelDB.id == ContentTagDB.channel_id)
        .filter(
            TagDB.type == PLATFORM_FACET,
            ChannelDB.media_type.in_(list(PLATFORM_SHELF_MEDIA_TYPES)),
            ChannelDB.name.notlike("##%"),  # provider category headers
        )
    )
    excluded = list(excluded_values)
    if excluded:
        query = query.filter(TagDB.value.notin_(excluded))
    # The single visibility chokepoint — never a hand-threaded exclusion axis,
    # so a platform shelf can never advertise content the channel list hides.
    query = channel_visibility.apply(query, scope, channel_cls=ChannelDB)

    rows = (
        query.group_by(TagDB.value)
        .having(titles >= int(min_titles))
        .all()
    )
    return sorted(
        ((value, int(count)) for value, count in rows),
        key=lambda vc: (-vc[1], vc[0]),
    )


def representative_version(cards: "Sequence[ContentCard]") -> "list[ContentCard]":
    """The VP-1 seam: order each ``content_key`` group so its best version leads.

    Returns *cards* unchanged today — the ORDER IS the contract, because the
    caller hands the result to ``discovery_engine._dedup_cards``, which keeps
    the FIRST card it sees for a group as that group's representative.  So when
    Version Preferences (VP-1) ships, reordering here is the whole change: a
    stable sort that floats the preferred language/region version of each
    ``content_key`` to the front of its group, falling back to any non-excluded
    version, and the card the user sees follows.

    This exists as a function rather than a comment because "which version
    represents a collapsed title" has to have exactly one home; a TODO beside
    the ``_dedup_cards`` call would be a second one the day another shelf
    collapses versions.

    Args:
        cards: Cards for one shelf, in query order, before dedup.

    Returns:
        The same cards, in the order ``_dedup_cards`` should read them.
    """
    return list(cards)
