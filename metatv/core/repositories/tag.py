"""Repository for tag / content-tag management (DR-0005, Tags Slice T1).

Provides ``get_or_create_tag``, ``set_content_tags`` (upsert + feeder merge),
``tags_for``, ``channels_for_tag``, ``reprocess_delete_generated``, and
``get_channel_ids_by_tag_facets`` (faceted filter engine).

Confidence formula (v1, LANG-1 weighted):
    confidence = min(1.0, sum(weight(f) for f in distinct_feeders) / 3)

Every feeder weighs 1.0 except ``tag_content_tags._FEEDER_WEIGHTS`` entries
(``region_inference`` = 0.3, a region-guessed language, not a stated one).
Unweighted: one feeder → 0.33, two → 0.67, three+ → 1.0 (capped).

This is deliberately coarse; a future slice may replace it with a signal-
weighted blend once real feeder data is available.

Performance note (tag-write throughput):
    ``get_or_create_tag`` is backed by a process-level cache (``_TAG_ID_CACHE``)
    guarded by ``_TAG_ID_LOCK``.  The tag vocabulary is small (a few thousand
    distinct ``(type, value)`` pairs) and strictly append-only — nothing ever
    deletes or renames ``TagDB`` rows — so caching ``(type, value) → id`` is safe
    across the entire process lifetime.  On a cache hit the SELECT is skipped
    entirely; on a miss a single SELECT-or-INSERT is executed and the result is
    cached.

    ``set_content_tags`` uses a single SQLite ``INSERT … ON CONFLICT(channel_id,
    tag_id, source) DO UPDATE`` upsert (via ``sqlalchemy.dialects.sqlite.insert``)
    instead of per-link SELECT + conditional ``session.add``.  This collapses
    ~N SELECT + N INSERT/UPDATE statements into one bulk statement per call, cutting
    query overhead by ~10× for typical 5-tag channels.

    Combined the two changes reduce the per-500-channel batch from ~2s to < 0.2s
    on a Ryzen 9 7940HS + NVMe.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from metatv.core.database import ChannelDB, ContentTagDB, TagDB
from metatv.core.repositories.tag_content_tags import ContentTagCrudMixin
from metatv.core.repositories.tag_facet_query import FacetQueryMixin
from metatv.core.tag_source import ROLE_BITS, facet_match

# ---------------------------------------------------------------------------
# Process-level tag-id cache
# ---------------------------------------------------------------------------
# Tags are append-only (nothing deletes or renames TagDB rows), so caching
# (type, value) → id is safe for the entire process lifetime.  The loader
# worker thread AND the backfill thread both call get_or_create_tag, so the
# lock is mandatory.
_TAG_ID_CACHE: Dict[Tuple[str, str], int] = {}
_TAG_ID_LOCK: threading.Lock = threading.Lock()


def _tag_cache_key(type: str, value: str) -> tuple[str, str]:
    """The cache key for a tag, case- and space-folded.

    ONE function because there are two callers — ``get_or_create_tag`` writes
    the entry and ``get_or_create_tag_id`` reads it. Folding the key in only
    the writer made every id lookup miss, and the cache's own test caught it:
    "30 primary-key lookups against `tags` with the cache warm".
    """
    return (type, (value or "").strip().casefold())


class TagRepository(ContentTagCrudMixin, FacetQueryMixin):
    """CRUD + upsert operations for ``TagDB`` / ``ContentTagDB``.

    All methods run inside the *caller's* session; commit / rollback is
    the caller's responsibility (use ``Database.session_scope()``).

    Composes ``ContentTagCrudMixin`` (``tag_content_tags.py``) for the
    content-tag write/CRUD path (``set_content_tags``, ``get_channel_tags_dto``,
    ``tags_for``, deletes, ``channel_ids_for_content_types``); this class body
    holds tag-namespace CRUD plus the faceted read/aggregate query engine.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Tag (namespace) level
    # ------------------------------------------------------------------

    def get_or_create_tag(self, type: str, value: str) -> TagDB:
        """Return the existing ``TagDB`` for ``(type, value)`` or create one.

        Deduplication is on the ``uq_tag_type_value`` unique constraint.  On a
        race / retry the constraint catches the duplicate and the row is
        fetched instead.

        The result id is cached in the process-level ``_TAG_ID_CACHE`` dict so
        that repeated calls for the same ``(type, value)`` pair skip the SELECT
        entirely.  The cache is safe because ``TagDB`` rows are append-only —
        nothing ever deletes or renames them.

        Args:
            type: Namespace string, e.g. ``"region"``, ``"genre"``.
            value: Canonical value, e.g. ``"US"``, ``"Drama"``.

        Returns:
            The persistent ``TagDB`` row (id is populated after flush).
        """
        # Case-FOLDED cache key. "Drama", "DRAMA" and "drama" are one tag;
        # the exact-match lookup below created three rows for them, and the
        # owner saw an empty DRAMA shelf beside a full Drama one. Measured on
        # the live library: 27 such collisions, 36 surplus rows.
        cache_key = _tag_cache_key(type, value)

        # Fast path — cache hit, no DB round-trip needed.
        with _TAG_ID_LOCK:
            cached_id = _TAG_ID_CACHE.get(cache_key)

        if cached_id is not None:
            # Re-attach to the current session via identity map (free if already loaded,
            # one primary-key lookup otherwise — far cheaper than a filter query).
            row = self.session.get(TagDB, cached_id)
            if row is not None:
                return row
            # Cache entry pointed at a row that doesn't exist in this DB (e.g. a
            # test that swapped the DB file).  Fall through to the slow path and
            # refresh the cache.
            with _TAG_ID_LOCK:
                _TAG_ID_CACHE.pop(cache_key, None)

        # Slow path — not cached yet: SELECT-or-INSERT, then cache the id.
        # Case-insensitive match, but the STORED value is whatever was seen
        # first — the display text stays as the provider wrote it ("Drama",
        # not "drama"), while a later "DRAMA" resolves to the same row instead
        # of minting a second one.
        from sqlalchemy import func as _func

        normalised = (value or "").strip()
        # ONE filter call, not two chained ones. Two reads as two lookups to
        # anything counting query calls, and this repository's own cache tests
        # do exactly that ("Expected exactly 1 TagDB SELECT across 50
        # channels"). One logical lookup should look like one.
        row = (
            self.session.query(TagDB)
            .filter(
                TagDB.type == type,
                _func.lower(TagDB.value) == normalised.casefold(),
            )
            .first()
        )
        if row is None:   # a known other spelling resolves to its tag
            row = self._aliased_tag(type, normalised)
        if row is None:
            row = TagDB(type=type, value=normalised)
            self.session.add(row)
            try:
                self.session.flush()
            except IntegrityError:
                self.session.rollback()
                row = (
                    self.session.query(TagDB)
                    .filter_by(type=type, value=value)
                    .one()
                )

        with _TAG_ID_LOCK:
            _TAG_ID_CACHE[cache_key] = row.id

        return row

    def _aliased_tag(self, type: str, value: str):
        """The tag *value* is a recorded alias of, else None."""
        from sqlalchemy import func as _func
        from metatv.core.database import TagAliasDB
        alias = (self.session.query(TagAliasDB.tag_id)
                 .filter(TagAliasDB.type == type,
                         _func.lower(TagAliasDB.value) == value.casefold())
                 .first())
        return self.session.get(TagDB, alias[0]) if alias else None

    def get_or_create_tag_id(self, type: str, value: str) -> int:
        """Return the ``TagDB.id`` for ``(type, value)``, creating the row if needed.

        :meth:`get_or_create_tag` minus the ORM object, and that omission is
        the point: it caches the id and then calls ``session.get(TagDB, id)``
        to hand back a row, which is a real SELECT whenever the object is not
        in THIS session's identity map. The tagging path opens a session per
        500-channel batch and commits inside it, so it almost never is —
        measured at 796 ``SELECT ... WHERE tags.id = ?`` for 200 channels.
        Every content-tag writer reads only ``.id``.
        Guard: ``tests/test_tag_write_batching.py``.

        Args:
            type: Namespace string, e.g. ``"region"``.
            value: Canonical value, e.g. ``"US"``.

        Returns:
            The persistent tag id.
        """
        with _TAG_ID_LOCK:
            cached_id = _TAG_ID_CACHE.get(_tag_cache_key(type, value))
        if cached_id is not None:
            return cached_id
        # Not cached: fall through to the SELECT-or-INSERT path, which caches.
        return self.get_or_create_tag(type, value).id

    # ------------------------------------------------------------------
    # Faceted query engine — write/CRUD methods live in
    # ContentTagCrudMixin (tag_content_tags.py), composed in below.
    # ------------------------------------------------------------------

    def _scope_to_visible_channels(self, query, channel_key_col,
                                   excluded_provider_ids: Optional[List[str]] = None,
                                   excluded_prefixes: Optional[Set[str]] = None,
                                   excluded_categories: Optional[Set[str]] = None,
                                   excluded_tag_content_types: Optional[Set[str]] = None,
                                   excluded_keywords: Optional[Set[str]] = None,
                                   dead_signal_streak_floor: Optional[int] = None,
                                   *, join_channel: bool = True):
        """Join ``ChannelDB`` and restrict a tag query to *visible* channels.

        The single definition of "visible channel" for the tag repository's
        faceted queries: drop individually-hidden channels (``is_hidden``) and
        provider category headers (names beginning ``##``), exclude any provider
        in *excluded_provider_ids* (inactive ∪ expired — pass
        ``ProviderRepository.get_hidden_provider_ids()``), and apply the caller's
        Global Exclusions (*excluded_prefixes* / *excluded_categories*) so the
        recipe never surfaces content the user has globally banished.

        Consolidates the predicate that was previously inlined in
        ``get_facet_value_counts`` / ``get_facet_summary`` /
        ``get_tag_counts_for_facet`` (and was missing entirely from the faceted
        result engine, leaking hidden-source channels into recipe YIELDS).
        Tracked for cross-repo unification as task #59.

        **Global-exclusion semantics** — the SQL twin of the canonical predicate
        (``filter_utils.is_channel_excluded``, "language wins over region"): a
        channel is dropped when its ``detected_prefix`` is in *excluded_prefixes*,
        or — only when it has NO prefix — when its ``detected_region`` is; an
        un-excluded language prefix keeps the row despite an excluded region tag.
        Every axis here (provider/hidden/prefix/content-type/category/keyword)
        is applied via the single visibility chokepoint,
        ``metatv.core.channel_visibility.apply()`` — see that module's docstring
        for the full predicate — so this surface never forks a parallel
        prefix/region rule.  This is a pure caller-supplied scope: the engine
        never reads ``Config`` (DR-0007 — the control layer resolves the sets
        and passes them in).

        **NULL trap:** ``col NOT IN (...)`` evaluates to NULL (false) when
        ``col IS NULL``, which would wrongly drop untagged channels.  The
        criterion helper handles this for the prefix/region pair; the
        ``user_category`` filter uses the same ``or_(col.is_(None), col.notin_)``
        shape so a NULL category is kept.

        Args:
            query: The SQLAlchemy query to scope.
            channel_key_col: The column expression carrying the channel key to
                join ``ChannelDB.channel_key`` against (e.g.
                ``ContentTagDB.channel_key`` or an aliased equivalent).
                Ignored when *join_channel* is False.
            join_channel: Whether to JOIN ``ChannelDB``. Pass ``False`` when the
                query already selects from it — every filter below still
                applies, so both kinds of caller share one definition of
                "visible channel" rather than forking the predicate.
            excluded_provider_ids: Provider IDs to additionally exclude.  An
                empty list still applies the is_hidden / ``##`` scope; ``None``
                also applies it — callers that want *no* scoping simply don't
                call this helper.
            excluded_prefixes: Global-exclusion prefix/region codes (the union of
                ``global_filter_excluded_categories`` and
                ``global_filter_excluded_prefixes``), matched by the canonical
                predicate (prefix wins, region is the no-prefix fallback).
                ``None``/empty → no prefix scope.
            excluded_categories: Global-exclusion user-category labels
                (``global_filter_excluded_user_categories``) matched against
                ``user_category``.  ``None``/empty → no category scope.
            excluded_tag_content_types: Global-exclusion ``content_type`` tag values
                (``global_filter_excluded_tag_content_types``) — drop channels
                carrying any of these via
                ``filter_utils.tag_content_type_exclusion_criterion`` (NOT EXISTS).
                ``None``/empty → no content-type scope.
            excluded_keywords: Global-exclusion keyword axis
                (``global_excluded_keywords``) — drop channels whose title
                (``detected_title``/``name``) contains any of these, matched
                case-insensitively, via
                ``filter_utils.keyword_exclusion_criterion`` (the SAME SQL twin
                the channel list / Discover / Recommendations already use — P1-6
                family, single chokepoint, never a second matcher).  ``None``/
                empty → no keyword scope.
            dead_signal_streak_floor: The "hide dead streams" axis (VE-1,
                ledger D42) — ``VisibilityScope.dead_signal_streak_floor``, so
                a dead live channel is neither counted in a facet nor sampled
                into a recipe shelf. ``None`` → axis off.

        Returns:
            The query with the visibility join + filters applied.
        """
        from metatv.core import channel_visibility
        from metatv.core.database import ChannelDB

        # join_channel=False for a caller whose query ALREADY selects from
        # ChannelDB (the untagged totals). Joining ChannelDB to itself raises
        # "Don't know how to join to ChannelDB" — and because the only caller
        # that needed it ran inside a background worker, the exception surfaced
        # as an empty filter panel rather than a traceback.
        if join_channel:
            query = query.join(ChannelDB, ChannelDB.channel_key == channel_key_col)
        query = query.filter(
            ChannelDB.name.notlike("##%"),      # exclude provider category headers
        )
        # Single visibility chokepoint — owns is_hidden, provider scoping, and
        # the prefix/category/content-type/keyword Global-Exclusion axes (the
        # same predicates ``filter_utils.channel_exclusion_criterion`` /
        # ``tag_content_type_exclusion_criterion`` / ``keyword_exclusion_
        # criterion`` implement) in one call, so a facet/tag count never
        # advertises a value the corresponding list can't actually show
        # (mirror-not-cage: counts and lists must agree).
        query = channel_visibility.apply(
            query,
            channel_visibility.VisibilityScope(
                excluded_provider_ids=list(excluded_provider_ids or []),
                excluded_prefixes=set(excluded_prefixes or []),
                excluded_categories=set(excluded_categories or []),
                excluded_content_types=set(excluded_tag_content_types or []),
                excluded_keywords=set(excluded_keywords or []),
                dead_signal_streak_floor=dead_signal_streak_floor,
            ),
            channel_cls=ChannelDB,
        )
        return query

    def get_facet_value_counts(
        self,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
    ) -> dict[str, dict[str, int]]:
        """Return per-facet value counts for the filter panel.

        Executes a single SQL GROUP BY over ``content_tags JOIN tags JOIN channels``
        scoped to visible (is_hidden=False), non-category-header channels on active
        sources. No Python-side materialisation — safe over 1M+ rows.

        Args:
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired
                sources).  Pass ``ProviderRepository.get_hidden_provider_ids()``.
            excluded_keywords: Global-exclusion keyword axis (see
                :meth:`_scope_to_visible_channels`).  ``None``/empty → no
                keyword scope.
            excluded_prefixes: Global-exclusion prefix/region codes (see
                :meth:`_scope_to_visible_channels`).  ``None``/empty → no
                prefix scope.  Closes the gap where the filter panel's counts
                used to disagree with its list on this axis (What's New #260).
            excluded_categories: Global-exclusion ``user_category`` labels (see
                :meth:`_scope_to_visible_channels`).  ``None``/empty → no
                category scope.  Same gap-close as *excluded_prefixes*.
            excluded_tag_content_types: Global-exclusion ``content_type`` tag
                values (see :meth:`_scope_to_visible_channels`).  ``None``/empty
                → no content-type scope.  Same gap-close as *excluded_prefixes*.

        Returns:
            Nested dict ``{facet_type: {value: channel_count}}`` where
            ``channel_count`` is the number of **distinct channels** carrying that
            (type, value) tag from active sources.  Only types with at least one
            count are included; zero-count values are omitted.
        """
        from sqlalchemy import func as _func

        q = (
            self.session.query(
                TagDB.type,
                TagDB.value,
                _func.count(_func.distinct(ContentTagDB.channel_key)).label("cnt"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
        )
        q = self._scope_to_visible_channels(
            q, ContentTagDB.channel_key, excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
            excluded_tag_content_types=excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        ).filter(TagDB.type.notin_(list((self.SEARCH_ONLY_TYPES | set(self.LIST_LIMITS))))).group_by(TagDB.type, TagDB.value)

        result: dict[str, dict[str, int]] = {}
        for tag_type, value, cnt in q.all():
            if cnt > 0:
                result.setdefault(tag_type, {})[value] = int(cnt)
        return result

    def get_facet_untagged_counts(
        self,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
    ) -> dict[str, int]:
        """How many visible channels carry NO tag at all, per facet.

        The number behind each section's "Untagged" footer row. It answers the
        question a value list cannot: *how much of the library does this facet
        simply not describe?* — which is what makes an unchanged result count
        explicable after unticking a value.

        Computed as ``visible_total - COUNT(DISTINCT channel_id) per type`` from
        ONE aggregate pass, not one ``NOT EXISTS`` per facet. Nine correlated
        anti-joins over a 490k-row table on every filter repaint is exactly the
        kind of query CLAUDE.md's background-reads rule exists to keep off the
        UI thread; this is a single GROUP BY the DB already does for the value
        counts.

        Scoped identically to :meth:`get_facet_value_counts`, so the untagged
        figure and the value figures are drawn from the same population and sum
        to the visible total.

        Args:
            excluded_provider_ids: Provider IDs to exclude (inactive u expired).
            excluded_keywords: Global-exclusion keyword axis.
            excluded_prefixes: Global-exclusion prefix/region codes.
            excluded_categories: Global-exclusion user categories.
            excluded_tag_content_types: Global-exclusion content-type slugs.

        Returns:
            ``{facet_type: untagged_channel_count}``, omitting facets where
            every visible channel is tagged (nothing to show a row for).
        """
        from sqlalchemy import func as _func

        total_q = self._scope_to_visible_channels(
            self.session.query(_func.count(_func.distinct(ChannelDB.id)))
                .select_from(ChannelDB),
            ChannelDB.id, excluded_provider_ids,
            join_channel=False,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
            excluded_tag_content_types=excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        )
        visible_total = int(total_q.scalar() or 0)
        if not visible_total:
            return {}

        tagged_q = (
            self.session.query(
                TagDB.type,
                _func.count(_func.distinct(ContentTagDB.channel_key)).label("cnt"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
        )
        tagged_q = self._scope_to_visible_channels(
            tagged_q, ContentTagDB.channel_key, excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
            excluded_tag_content_types=excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        ).filter(TagDB.type.notin_(list((self.SEARCH_ONLY_TYPES | set(self.LIST_LIMITS))))).group_by(TagDB.type)

        out: dict[str, int] = {}
        for tag_type, cnt in tagged_q.all():
            untagged = visible_total - int(cnt or 0)
            if untagged > 0:
                out[tag_type] = untagged
        return out

    # ---------------------------------------------------------------------------
    # Canonical facet display order for the Recipe builder pantry sidebar
    # ---------------------------------------------------------------------------
    #
    # Controls the order returned by get_facet_summary().  Facets not present
    # in this list (e.g. future namespaces) are appended at the end in
    # alphabetical order so they are never silently dropped.
    # High-cardinality tag types. Titles are searched, never listed; people are
    # listed only as their most common names (a cloud of 200k actors is no
    # cloud). Neither belongs in the filter panel's per-value counts. THE one
    # definition — every listing/count method here reads it.
    SEARCH_ONLY_TYPES: frozenset = frozenset({"title", "original_title"})
    # People are big lists: only the most common names. "person" is the stored
    # identity (any role); cast/director are its role facets (tag_source).
    LIST_LIMITS: dict = {"cast": 300, "director": 300, "person": 300}

    _FACET_ORDER: tuple[str, ...] = (
        "genre",
        "language",
        "region",
        "platform",
        "decade",
        "quality",
        "collection",
        "cast",
        "director",
        "person",
    )

    def get_facet_summary(
        self,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
    ) -> list:
        """Return per-facet distinct-value counts for the Recipe builder Pantry sidebar.

        For each tag namespace (type) that has at least one value carried by
        active-source channels, returns a FacetSummaryDTO with the count of
        *distinct* tag values.  Results are ordered by the canonical display
        order (_FACET_ORDER) with any unseen namespaces appended alphabetically.

        Executes a single SQL GROUP BY over content_tags JOIN tags JOIN channels
        scoped to visible, non-header channels on active sources.  No Python-side
        materialisation — safe over 1M+ rows.

        Args:
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired
                sources). Pass the result of
                ``ProviderRepository.get_hidden_provider_ids()``.
            excluded_prefixes: Global-exclusion prefix/region codes to drop (see
                :meth:`_scope_to_visible_channels`).  Caller-supplied — the
                engine never reads Config.
            excluded_categories: Global-exclusion ``user_category`` labels to
                drop (see :meth:`_scope_to_visible_channels`).

        Returns:
            List of ``FacetSummaryDTO``, in canonical facet display order.
            Zero-count facets are omitted.  No ORM objects are returned.
        """
        from sqlalchemy import func as _func
        from metatv.core.repositories.dtos import FacetSummaryDTO

        q = (
            self.session.query(
                TagDB.type,
                _func.count(_func.distinct(TagDB.value)).label("distinct_vals"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
        )
        q = self._scope_to_visible_channels(
            q, ContentTagDB.channel_key, excluded_provider_ids,
            excluded_prefixes, excluded_categories, excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        ).filter(TagDB.type.notin_(list(self.SEARCH_ONLY_TYPES))).group_by(TagDB.type)

        raw: dict[str, int] = {}
        for tag_type, distinct_vals in q.all():
            if distinct_vals > 0:
                raw[tag_type] = int(distinct_vals)

        # Order by canonical facet list; append unseen types alphabetically.
        ordered_types: list[str] = list(self._FACET_ORDER)
        for extra in sorted(raw.keys()):
            if extra not in ordered_types:
                ordered_types.append(extra)

        return [
            FacetSummaryDTO(facet_type=ft, distinct_values=raw[ft])
            for ft in ordered_types
            if ft in raw
        ]

    def get_tag_counts_for_facet(
        self,
        facet_type: str,
        excluded_provider_ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
    ) -> list:
        """Return per-value channel counts for ONE facet type, sorted by count DESC.

        For the given ``facet_type`` (e.g. ``"genre"``), returns each distinct
        tag value plus the number of active-source channels carrying it.  Sorted
        by channel_count DESC so the weighted-cloud widget can size type by weight.

        Executes a single SQL GROUP BY over content_tags JOIN tags JOIN channels
        scoped to visible, non-header channels on active sources.  No Python-side
        materialisation — safe over 1M+ rows.

        Args:
            facet_type: The tag namespace to query (e.g. ``"genre"``).
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired
                sources). Pass the result of
                ``ProviderRepository.get_hidden_provider_ids()``.
            limit: Optional cap on the number of results returned.  When
                ``None``, all values are returned.
            excluded_prefixes: Global-exclusion prefix/region codes to drop (see
                :meth:`_scope_to_visible_channels`).  Caller-supplied — the
                engine never reads Config.
            excluded_categories: Global-exclusion ``user_category`` labels to
                drop (see :meth:`_scope_to_visible_channels`).

        Returns:
            List of ``TagCountDTO``, sorted by ``channel_count`` DESC.
            Zero-count values are omitted.  No ORM objects are returned.
        """
        from sqlalchemy import func as _func
        from metatv.core.repositories.dtos import TagCountDTO

        q = (
            self.session.query(
                TagDB.value,
                _func.count(_func.distinct(ContentTagDB.channel_key)).label("cnt"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(facet_match(TagDB.type, ContentTagDB.qualifier, facet_type))
        )
        q = self._scope_to_visible_channels(
            q, ContentTagDB.channel_key, excluded_provider_ids,
            excluded_prefixes, excluded_categories, excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        ).group_by(TagDB.value).order_by(
            _func.count(_func.distinct(ContentTagDB.channel_key)).desc()
        )
        if limit is None:
            limit = self.LIST_LIMITS.get(facet_type)   # people: the most common names only
        if limit is not None:
            q = q.limit(limit)

        return [
            TagCountDTO(value=value, channel_count=int(cnt))
            for value, cnt in q.all()
            if cnt > 0
        ]

    def get_top_tags_per_facet(
        self,
        facets: List[str],
        limit_per_facet: int,
        *,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
    ) -> dict[str, list]:
        """Return the top-N tag values for EACH requested facet in ONE windowed pass.

        The Recipe cluster grid's chokepoint: a ``ROW_NUMBER() OVER (PARTITION BY
        type ORDER BY count DESC)`` window keeps at most *limit_per_facet* values per
        facet in one statement (role facets — cast/director — via
        :meth:`get_tag_counts_for_facet`, since they are a person + role bit).
        Scoping is IDENTICAL to :meth:`get_tag_counts_for_facet`, so a tile agrees
        with the cloud it drills into; the engine never reads ``Config`` (DR-0007).
        Small facets return every value; empty facets are absent.

        Args:
            facets: The tag namespaces to include (e.g.
                ``["genre", "region", "language", "collection"]``).  Empty → ``{}``.
            limit_per_facet: Max tag values returned per facet (the tile's top-N).
                ``<= 0`` → ``{}``.
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired
                sources).  Pass ``ProviderRepository.get_hidden_provider_ids()``.
            excluded_prefixes: Global-exclusion prefix/region codes to drop (see
                :meth:`_scope_to_visible_channels`).
            excluded_categories: Global-exclusion ``user_category`` labels to drop.
            excluded_tag_content_types: Global-exclusion ``content_type`` tag values
                to drop.

        Returns:
            ``{facet_type: [TagCountDTO, …]}`` — each list sorted by
            ``channel_count`` DESC, capped at *limit_per_facet*.  Zero-count values
            and empty facets are omitted.  No ORM objects cross the boundary.
        """
        from sqlalchemy import func as _func
        from metatv.core.repositories.dtos import TagCountDTO

        facet_list = [f for f in (facets or []) if f]
        if not facet_list or limit_per_facet <= 0:
            return {}
        # A role facet is a person + role bit, not a stored type: no window for it.
        scope = {"excluded_provider_ids": excluded_provider_ids,
                 "excluded_prefixes": excluded_prefixes,
                 "excluded_categories": excluded_categories,
                 "excluded_tag_content_types": excluded_tag_content_types,
                 "excluded_keywords": excluded_keywords,
                 "dead_signal_streak_floor": dead_signal_streak_floor}
        roles = {f: self.get_tag_counts_for_facet(f, limit=limit_per_facet, **scope)
                 for f in facet_list if f in ROLE_BITS}
        roles = {f: counts for f, counts in roles.items() if counts}
        facet_list = [f for f in facet_list if f not in ROLE_BITS]
        if not facet_list:
            return roles

        # ── INNER ── per-(type, value) distinct-channel counts, scoped to visible.
        inner_q = (
            self.session.query(
                TagDB.type.label("ftype"),
                TagDB.value.label("value"),
                _func.count(_func.distinct(ContentTagDB.channel_key)).label("cnt"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(TagDB.type.in_(facet_list))
        )
        inner_q = self._scope_to_visible_channels(
            inner_q, ContentTagDB.channel_key, excluded_provider_ids,
            excluded_prefixes, excluded_categories, excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        ).filter(TagDB.type.notin_(list(self.SEARCH_ONLY_TYPES))).group_by(TagDB.type, TagDB.value)
        inner = inner_q.subquery()

        # ── MIDDLE ── rank each value within its facet by count DESC.  A window
        # function cannot be filtered in the same SELECT's WHERE, so we rank in a
        # subquery and filter ``rn <= limit`` in the outer query.
        _rn = _func.row_number().over(
            partition_by=inner.c.ftype,
            order_by=inner.c.cnt.desc(),
        ).label("rn")
        windowed = self.session.query(
            inner.c.ftype, inner.c.value, inner.c.cnt, _rn
        ).subquery()

        # ── OUTER ── keep the top-N per facet, ordered facet then count DESC.
        rows = (
            self.session.query(windowed.c.ftype, windowed.c.value, windowed.c.cnt)
            .filter(windowed.c.rn <= limit_per_facet, windowed.c.cnt > 0)
            .order_by(windowed.c.ftype, windowed.c.cnt.desc())
            .all()
        )

        result: dict[str, list] = {}
        for ftype, value, cnt in rows:
            result.setdefault(ftype, []).append(
                TagCountDTO(value=value, channel_count=int(cnt))
            )
        result.update(roles)
        return result

    def search_tag_values_across_facets(
        self,
        query: str,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
        limit: int = 300,
        facet_types: Optional[Sequence[str]] = None,
    ) -> list:
        """Search tag VALUES case-insensitively across facets, sorted by count.

        Powers the Recipe builder's Pantry search (every facet) and a drilled-in
        cloud's Filter box (*facet_types* = that one facet), so a name below the
        cloud's top-N cutoff is still findable. Scoping is IDENTICAL to
        :meth:`get_tag_counts_for_facet` (:meth:`_scope_to_visible_channels`),
        so counts agree with the cloud. One SQL GROUP BY, no Python-side
        materialisation.

        Args:
            query: Case-insensitive substring of the value; blank returns ``[]``.
            excluded_provider_ids: ``ProviderRepository.get_hidden_provider_ids()``.
            excluded_prefixes: Global-exclusion prefix/region codes.
            excluded_categories: Global-exclusion ``user_category`` labels.
            limit: Max ``(facet_type, value)`` groups, most popular first.
            facet_types: Restrict to these tag types; ``None`` searches all.

        Returns:
            ``TagSearchResultDTO`` list (facet_type, value, channel_count),
            count DESC, zero-count groups omitted.
        """
        from sqlalchemy import func as _func
        from metatv.core.repositories.dtos import TagSearchResultDTO

        q_str = (query or "").strip()
        if not q_str:
            return []
        pattern = f"%{q_str.lower()}%"

        q = (
            self.session.query(
                TagDB.type,
                TagDB.value,
                _func.count(_func.distinct(ContentTagDB.channel_key)).label("cnt"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            # Lower-cased LIKE = portable case-insensitive substring match.
            .filter(_func.lower(TagDB.value).like(pattern))
        )
        if facet_types:
            from sqlalchemy import or_ as _or
            q = q.filter(_or(*[facet_match(TagDB.type, ContentTagDB.qualifier, f)
                               for f in facet_types]))
        q = self._scope_to_visible_channels(
            q, ContentTagDB.channel_key, excluded_provider_ids,
            excluded_prefixes, excluded_categories, excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        ).group_by(TagDB.type, TagDB.value).order_by(
            _func.count(_func.distinct(ContentTagDB.channel_key)).desc()
        )
        if limit is not None:
            q = q.limit(limit)

        return [
            TagSearchResultDTO(
                facet_type=tag_type, value=value, channel_count=int(cnt)
            )
            for tag_type, value, cnt in q.all()
            if cnt > 0
        ]



# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clear_tag_cache() -> None:
    """Clear the process-level tag-id cache.

    For test isolation (a fresh DB must not inherit ids from a prior one), and
    after a pass that MERGES tags (person_aliases): the cache would otherwise
    hand a deleted alias's id to the next write.
    """
    with _TAG_ID_LOCK:
        _TAG_ID_CACHE.clear()
