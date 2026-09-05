"""channel_visibility.py — the single definition of "which channels are visible".

CLAUDE.md governing principle #1 (single chokepoint / one source of truth):
before this module existed, "which channels are visible" was answered FOUR
separate times — ``ChannelRepository._apply_channel_filters``
(``core/repositories/channel.py``), a cluster of module-level
``_apply_*_filter``/``_apply_*_exclusion`` helpers in
``core/discovery_engine.py``, inline filters in
``core/preference_engine.score_candidates``, and
``TagRepository._scope_to_visible_channels`` (``core/repositories/tag.py``) —
each hand-threading its own subset of the exclusion axes, which is the
structural cause of a real bug class ("Recommendations ignores global
exclusions") and DR-0007 drift (visibility is a control-layer decision, not
an engine one, yet each engine site re-derived its own slice of it).

This module is that one definition. :class:`VisibilityScope` is a plain,
frozen bag of *already-resolved* exclusion sets/flags — it carries no
``Config`` reference and makes no policy decisions (DR-0007: the control
layer resolves what's excluded — e.g. ``ProviderRepository.
get_hidden_provider_ids()``, ``filter_utils.global_exclusion_set(config)`` —
and hands the resolved scope in). :func:`apply` threads every axis onto a
``Query(ChannelDB)`` (or an aliased equivalent via ``channel_cls``).

Migration status (tracked — do not assume this list is stale, extend it as
call sites move):

- ``ChannelRepository._apply_channel_filters`` — MIGRATED (this module's
  first, proof-of-faithfulness caller; see that method for exactly which
  lines moved).
- ``discovery_engine.py`` (``_apply_prefix_filter`` / ``_apply_provider_
  exclusion`` / ``_apply_content_type_exclusion`` / ``_apply_keyword_
  exclusion`` / ``_apply_user_category_exclusion`` / ``_apply_adult_filter``),
  ``preference_engine.score_candidates``, and ``TagRepository.
  _scope_to_visible_channels`` — MIGRATED. The one known divergence flagged
  below was reconciled onto this module's region-aware
  ``filter_utils.channel_exclusion_criterion``: ``discovery_engine.
  _apply_prefix_filter``'s old flat prefix-only ``NOT IN`` (which never
  consulted ``detected_region`` for prefix-less channels) is gone — Discover
  shelves and Recommendations (``preference_engine.score_candidates``, which
  used to call ``discovery_engine._apply_prefix_filter`` directly) now apply
  the SAME "language wins over region" predicate as the channel list /
  tag-facet counts / EPG On-Now. This was a deliberate, documented behavior
  change (see the PR that closed this migration for the full before/after) —
  a channel with no ``detected_prefix`` but an excluded ``detected_region`` is
  now ALSO hidden on those two surfaces, where it previously was not.
  ``TagRepository.get_facet_value_counts`` additionally gained the
  ``excluded_prefixes``/``excluded_categories``/``excluded_tag_content_types``
  parameters it was missing (What's New #260), closing the gap where the
  filter panel's counts disagreed with its list on those three axes.
- ``dead_signal_streak_floor`` (VE-1) — the "hide dead events" setting. Wired
  into ``ChannelRepository.get_all()`` (channel list + search),
  ``discovery_engine.py``'s card-returning shelf functions (Discover), and
  ``preference_engine.score_candidates`` (Recommendations); resolved from
  config in ``visibility_resolver.resolve_scope`` (which also reaches
  ``get_similar_channels`` and the person/genre lens for free) and at each of
  those three surfaces' own control-layer entry points. NOT wired into
  ``tag.py``'s facet-value-count / saved-recipe query family — a known gap,
  logged in docs/REFACTOR_PLAN.md rather than silently left undocumented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_

from metatv.core.database import ChannelDB
from metatv.core.filter_utils import (
    channel_exclusion_criterion,
    keyword_exclusion_criterion,
    tag_content_type_exclusion_criterion,
)


@dataclass(frozen=True)
class VisibilityScope:
    """A fully-resolved bag of channel-visibility exclusions.

    Every field defaults to a "no-op" empty value so a caller that only
    cares about a subset of axes (e.g. just ``include_hidden``) can build a
    partial scope without accidentally introducing a new exclusion. Fields
    hold already-resolved data (ids/codes/flags) — never a ``Config``
    object; resolving *what* is excluded from user settings is the control
    layer's job (DR-0007), this dataclass and :func:`apply` only encode
    *how* an already-decided exclusion is applied to a query.

    Attributes:
        excluded_provider_ids: Provider ids to drop (inactive/expired/
            orphaned sources). Pass
            ``ProviderRepository.get_hidden_provider_ids()``.
        excluded_prefixes: ``detected_prefix``/``detected_region`` codes the
            user has globally excluded (Global Exclusions category/prefix
            axis). Applied via the canonical
            ``filter_utils.channel_exclusion_criterion`` ("language wins
            over region" — see that function's docstring). Build with
            ``filter_utils.global_exclusion_set(config)``.
        excluded_categories: ``user_category`` values to drop (the
            human-assigned category axis, distinct from ``detected_prefix``).
        excluded_content_types: ``content_type`` tag values to drop (e.g.
            ``{"ai_generated"}``) via the canonical
            ``filter_utils.tag_content_type_exclusion_criterion``. Build with
            ``filter_utils.excluded_tag_content_types(config)``.
        excluded_keywords: Free-text keywords matched case-insensitively
            against ``detected_title``/``name`` via the canonical
            ``filter_utils.keyword_exclusion_criterion``. Build with
            ``filter_utils.keyword_exclusion_list(config)``.
        adult_mode: ``"all"`` (no-op) / ``"hide"`` / ``"only"``. A channel is
            "restricted" when ``is_adult`` OR ``detected_restricted`` OR its
            provider is in ``force_adult_provider_ids``.
        force_adult_provider_ids: Provider ids whose entire catalog is
            treated as restricted regardless of the per-channel flags.
        include_uncategorized: When ``excluded_prefixes`` is set, ``True``
            (default) keeps channels with no ``detected_prefix`` at all;
            ``False`` also drops them. Independent of ``excluded_prefixes``
            being empty — ``False`` alone still drops untagged channels.
        include_hidden: ``False`` (default) applies the ``is_hidden == False``
            gate; ``True`` skips it (reveal hidden channels too).
        dead_signal_streak_floor: ``None`` (default, axis off) or an int ``N``
            — exclude channels whose ``signal_dead_streak`` has reached ``N``
            (VE-1, the "hide dead events" setting). Resolved from config as
            ``config.signal_dead_streak_to_hide if config.hide_dead_events
            else None`` — see ``visibility_resolver.resolve_scope``. NULL-safe:
            a channel with no streak recorded yet is never excluded by this
            axis alone.
    """

    excluded_provider_ids: list[str] = field(default_factory=list)
    excluded_prefixes: set[str] = field(default_factory=set)
    excluded_categories: set[str] = field(default_factory=set)
    excluded_content_types: set[str] = field(default_factory=set)
    excluded_keywords: set[str] = field(default_factory=set)
    adult_mode: str = "all"
    force_adult_provider_ids: list[str] = field(default_factory=list)
    include_uncategorized: bool = True
    include_hidden: bool = False
    dead_signal_streak_floor: int | None = None


def apply(query: Any, scope: VisibilityScope, *, channel_cls: type = ChannelDB) -> Any:
    """Apply every visibility predicate in *scope* to *query*.

    Each axis is applied independently as its own ``.filter(...)`` clause
    (plain SQL ``AND``-composition) — the axes are order-independent, so
    calling this once with a fully-populated scope produces the exact same
    result set as calling it several times with disjoint partial scopes.
    A no-op default on any field means that axis contributes no filter.

    Args:
        query: A SQLAlchemy ``Query`` (or equivalent) already selecting
            *channel_cls* rows.
        scope: The resolved :class:`VisibilityScope` to apply.
        channel_cls: The ``ChannelDB`` class (or an aliased equivalent)
            carrying the columns referenced below. Defaults to ``ChannelDB``.

    Returns:
        The query with every visibility predicate in *scope* applied.
    """
    # ── Provider scoping — moved verbatim from
    # ``ChannelRepository._apply_channel_filters`` (pre-refactor: the
    # standalone ``if excluded_provider_ids: query = query.filter(~Channel
    # DB.provider_id.in_(excluded_provider_ids))`` block). ──────────────────
    if scope.excluded_provider_ids:
        query = query.filter(~channel_cls.provider_id.in_(scope.excluded_provider_ids))

    # ── Hidden gate — moved verbatim from ``_apply_channel_filters``
    # (pre-refactor: ``elif not include_hidden: query = query.filter_by(
    # is_hidden=False)``). The ``hidden_only`` branch (show ONLY hidden
    # channels) and the dead-stream-reliability gate are NOT part of this
    # scope (no field for them) and stay in ``_apply_channel_filters``. ────
    if not scope.include_hidden:
        query = query.filter(channel_cls.is_hidden == False)  # noqa: E712

    # ── Keyword axis — moved verbatim from ``_apply_channel_filters``
    # (pre-refactor: ``if excluded_keywords: query = query.filter(keyword_
    # exclusion_criterion(excluded_keywords, ChannelDB))``). Same canonical
    # helper discovery_engine._apply_keyword_exclusion and TagRepository.
    # _scope_to_visible_channels already call — single chokepoint, unchanged
    # here. ──────────────────────────────────────────────────────────────
    if scope.excluded_keywords:
        query = query.filter(keyword_exclusion_criterion(scope.excluded_keywords, channel_cls))

    # ── Prefix/region axis — NOT present in ``_apply_channel_filters``
    # pre-refactor (that method's language/region/platform prefix params are
    # an unrelated INCLUSION "identity pool" for the Browse filter panel, and
    # are left untouched). Provisioned here for the discovery_engine.py /
    # tag.py migration slice, built on the already-canonical filter_utils.
    # channel_exclusion_criterion (see module docstring for the known
    # divergence from discovery_engine._apply_prefix_filter's simpler flat
    # NOT IN). ───────────────────────────────────────────────────────────
    if scope.excluded_prefixes:
        query = query.filter(channel_exclusion_criterion(scope.excluded_prefixes, channel_cls))
    if not scope.include_uncategorized:
        query = query.filter(channel_cls.detected_prefix.isnot(None))

    # ── User-category axis — NOT present in ``_apply_channel_filters``
    # pre-refactor. Provisioned for the discovery_engine.py
    # (_apply_user_category_exclusion) / tag.py migration slice; both of
    # those sites already agree on this exact
    # ``or_(is_(None), notin_(...))`` shape, so it is reproduced faithfully
    # (not rewritten) rather than routed through a filter_utils helper
    # (none exists for this axis today). ────────────────────────────────
    if scope.excluded_categories:
        query = query.filter(
            or_(
                channel_cls.user_category.is_(None),
                channel_cls.user_category.notin_(list(scope.excluded_categories)),
            )
        )

    # ── Content-type (provenance) axis — NOT present in
    # ``_apply_channel_filters`` pre-refactor. Provisioned for the
    # discovery_engine.py / tag.py migration slice, routed through the
    # already-canonical filter_utils.tag_content_type_exclusion_criterion
    # (the same helper both of those sites already call). ───────────────
    if scope.excluded_content_types:
        query = query.filter(
            tag_content_type_exclusion_criterion(scope.excluded_content_types, channel_cls.id)
        )

    # ── Adult-content gate — moved verbatim from ``_apply_channel_filters``
    # (pre-refactor: the ``if adult_mode != "all": ...`` block, identical in
    # shape to discovery_engine._apply_adult_filter). ───────────────────
    if scope.adult_mode != "all":
        force_ids = scope.force_adult_provider_ids or []
        restricted_expr = or_(
            channel_cls.is_adult == True,  # noqa: E712
            channel_cls.detected_restricted == True,  # noqa: E712
        )
        if force_ids:
            restricted_expr = or_(restricted_expr, channel_cls.provider_id.in_(force_ids))
        if scope.adult_mode == "hide":
            query = query.filter(~restricted_expr)
        elif scope.adult_mode == "only":
            query = query.filter(restricted_expr)

    # ── Dead-signal-streak axis (VE-1) — the "hide dead events" setting; a
    # new axis, not a migrated one. The column is NOT NULL (default 0). ──────
    if scope.dead_signal_streak_floor is not None:
        query = query.filter(channel_cls.signal_dead_streak < scope.dead_signal_streak_floor)

    return query
