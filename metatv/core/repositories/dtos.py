"""Plain-data DTOs returned by repository hot paths.

These frozen dataclasses carry no live SQLAlchemy session, so they are safe to
pass across the Qt thread boundary from worker threads to the main thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from metatv.core.models import MediaType

if TYPE_CHECKING:
    from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Playable DTOs — replace session.expunge() anti-pattern (B10-1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayableChannelDTO:
    """Union of all ChannelDB fields consumed by play_media, drill_into_series,
    update_details_pane_for_channel, details_pane.show_channel, and load_basic.

    Built inside a session_scope() by ChannelRepository.get_playable_dto() so
    that no ORM object crosses the session boundary.  Field names intentionally
    mirror ChannelDB so consumers need no code changes — only type-hint updates.
    """
    id: str
    source_id: str
    provider_id: str
    name: str
    stream_url: Optional[str]
    media_type: Optional[str]
    is_favorite: bool
    is_hidden: bool
    is_adult: bool
    logo_url: Optional[str]
    detected_prefix: Optional[str]
    detected_quality: Optional[str]
    detected_region: Optional[str]
    detected_title: Optional[str]
    detected_year: Optional[str]
    raw_data: Optional[dict]
    metadata_id: Optional[str]
    # Resume position — populated for VOD channels; 0 for live / unwatched
    watch_progress: int = 0      # seconds; 0 when unwatched or completed
    watch_completed: bool = False  # True → do NOT resume (user finished it)


@dataclass(frozen=True)
class PlayableEpisodeDTO:
    """Fields from EpisodeDB consumed by play_episode() and play_from_history_id().

    Built inside a session_scope() by EpisodeRepository.get_last_played_dto() so
    that no EpisodeDB object crosses the session boundary.
    """
    id: str
    title: str
    stream_url: Optional[str]
    series_id: str
    provider_id: str
    season_id: str
    episode_num: int
    season_num: int


# ---------------------------------------------------------------------------
# Channel-list DTO — central channel-list view (B10-5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChannelListDTO:
    """One row in the main channel list.

    Holds exactly the ChannelDB fields the main thread reads off the cached
    ``all_channels`` entries: the render loop in ``_on_channels_loaded`` (icon,
    prefix/region/quality/year, title, provider badge, category), the favorites
    cache update in ``_apply_favorite_toggle`` (name/category/quality), and
    ``filter_channels`` (``id``). Built inside a session_scope() by
    :meth:`from_orm`, so no ORM object crosses the worker→main-thread boundary.
    """
    id: str
    name: str
    media_type: str | None
    provider_id: str
    is_favorite: bool
    category: str | None
    quality: str | None
    detected_prefix: str | None
    detected_region: str | None
    detected_quality: str | None
    detected_year: str | None
    detected_title: str | None
    # Watch-completion fields (VOD only; both default False/0 for live channels)
    watch_completed: bool = False   # sticky "finished" flag — shown as ✓ in list
    watch_progress: int = 0         # resume position in seconds (0 when completed or unwatched)
    watch_percent: int = 0          # 0–100: % watched at last capture — drives graduated glyph (◔/◐/◕)
    # Provenance — "manual" (user played deliberately) vs "queue" (auto-advanced) vs None (unwatched)
    last_played_via: str | None = None
    # User rating — +1 liked, -1 disliked, 0 unrated.  Populated from UserRatingDB at
    # query time via a batch lookup (RatingRepository.get_all_map()); 0 means no rating.
    user_rating: int = 0
    # Graduated play-failure ledger state — "ok"|"flagged"|"degraded"|"dead".
    # Populated from StreamRetryDB at query time via a batch lookup
    # (StreamRetryRepository.get_reliability_map()), same pattern as user_rating.
    # "dead" rows never reach here (excluded at the query layer — see
    # ChannelRepository._apply_channel_filters); "degraded" drives the grayed
    # ForegroundRole in channel_list_model.py.
    reliability_state: str = "ok"
    # MetadataDB.plot text (or "" when the channel has no metadata row / no plot).
    # Populated via the outerjoin ChannelRepository.get_all() performs against
    # MetadataDB (see its _joined_plot stash) — never a per-row lookup. Powers the
    # "Comfy+" channel-list density's elided plot line (channel_list_delegate.py).
    plot: str = ""
    # MetadataDB.poster_url (or "" when absent). Populated via the SAME outerjoin
    # as plot above (see its _joined_poster_url stash) — never a per-row lookup.
    # Powers the comfy/comfy_plus channel-list thumbnail (channel_list_delegate.py).
    poster_url: str = ""
    # Cross-source identity key (ChannelDB.content_key, computed at ingestion —
    # see content_identity.content_key_for). None on pre-migration rows. Carried
    # through so the "Show N versions" context-menu action can look up siblings
    # via ChannelRepository.get_content_key_siblings without a second query.
    content_key: str | None = None
    # Collapsed-list variant-badge count — group size when this row is a
    # collapse_variants=True representative (ChannelRepository.get_all()); 1 for
    # every row when collapsing is off (the default) or the row is a singleton.
    # Populated from the ORM row's transient ``_variant_count`` (see
    # ChannelRepository._get_all_collapsed) — never re-derived at render.
    variant_count: int = 1
    # Category-marker cleanup fields — computed at ingestion (see ChannelDB.
    # detected_collection(_language|_subdub) in database.py); read directly,
    # never re-parsed from ``category``. Power the Comfy/Comfy+ row's
    # collection/secondary-language/subtitle-marker chips
    # (channel_list_delegate.py).
    detected_collection: str | None = None
    detected_collection_language: str | None = None
    detected_collection_subdub: str | None = None
    # Canonical genre (ChannelDB.detected_genre — the first raw_data["genre"]
    # segment, computed once at ingestion). Powers the comfy-row genre chip
    # (channel_list_delegate.py, #257 Part C); read directly, never re-derived.
    detected_genre: str | None = None
    # EVERY canonical genre segment (ChannelDB.detected_genres), same ingestion
    # pass as detected_genre above. The row shows up to _MAX_GENRES of them
    # (#298 — a title that is both Drama and Thriller was claiming to be only
    # Drama). A TUPLE, not the stored list: this DTO is frozen and crosses a
    # thread boundary, so it must not hand out a mutable alias of ORM state.
    detected_genres: tuple[str, ...] = ()

    @classmethod
    def from_orm(cls, ch, *, user_rating: int = 0, reliability_state: str = "ok") -> "ChannelListDTO":
        """Build a ChannelListDTO from a ChannelDB row (call inside a session).

        Args:
            ch: A live ChannelDB ORM object (must be called inside a session).
            user_rating: The user's rating for this channel (+1, -1, or 0 for unrated).
                Pass from a pre-fetched batch lookup to avoid N+1 queries.
            reliability_state: The channel's graduated play-failure ledger state
                ("ok"|"flagged"|"degraded"|"dead"). Pass from a pre-fetched batch
                lookup (StreamRetryRepository.get_reliability_map()) to avoid N+1.
        """
        return cls(
            id=ch.id,
            name=ch.name,
            media_type=ch.media_type,
            provider_id=ch.provider_id,
            is_favorite=bool(ch.is_favorite),
            category=ch.category,
            quality=ch.quality,
            detected_prefix=ch.detected_prefix,
            detected_region=ch.detected_region,
            detected_quality=ch.detected_quality,
            detected_year=ch.detected_year,
            detected_title=ch.detected_title,
            watch_completed=bool(getattr(ch, "watch_completed", False)),
            watch_progress=int(getattr(ch, "watch_progress", 0) or 0),
            watch_percent=int(getattr(ch, "watch_percent", 0) or 0),
            last_played_via=getattr(ch, "last_played_via", None),
            user_rating=user_rating,
            reliability_state=reliability_state,
            plot=getattr(ch, "_joined_plot", "") or "",
            poster_url=getattr(ch, "_joined_poster_url", "") or "",
            content_key=getattr(ch, "content_key", None),
            variant_count=int(getattr(ch, "_variant_count", 1) or 1),
            detected_collection=ch.detected_collection,
            detected_collection_language=ch.detected_collection_language,
            detected_collection_subdub=ch.detected_collection_subdub,
            detected_genre=getattr(ch, "detected_genre", None),
            detected_genres=tuple(
                g for g in (getattr(ch, "detected_genres", None) or ()) if g
            ),
        )


# ---------------------------------------------------------------------------
# Sidebar DTOs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FavoriteDTO:
    """One row in the Favorites sidebar section."""
    id: str
    name: str
    media_type: str | None
    last_played: datetime | None
    provider_id: str | None = None     # None when channel is orphaned
    available: bool = True             # False when provider is inactive/expired
    search_title: str = ""             # detected_title or name — recovery search term
    # Ingestion-computed display fields — read at render (never re-parse the name).
    detected_region: str = ""
    detected_quality: str = ""
    detected_year: str = ""
    detected_prefix: str = ""          # audio-language token — the honest chip-row language


@dataclass(frozen=True)
class HistoryDTO:
    """One row in the History sidebar section."""
    id: str
    name: str
    media_type: str | None
    episode_code: str | None     # e.g. "S01E02"; None for non-series or no episode yet
    # When it was last played — the History row's meta line renders this as "2 hours
    # ago" / "yesterday" (see metatv.gui.relative_time). Eagerly copied off the ORM row
    # inside the session like every other field here.
    last_played: datetime | None = None
    # Ingestion-computed display fields — read at render (never re-parse the name), so
    # History rows render as the same chip row as Recommended / Queue / Favorites.
    detected_title: str = ""
    detected_year: str = ""
    detected_quality: str = ""
    detected_prefix: str = ""          # audio-language token — the honest chip-row language
    # "Play Next Episode" (Wave 5) — the smart-ladder resume target (see
    # EpisodeRepository.get_resume_dto), pre-resolved in build_history_dtos via the
    # batched EpisodeRepository.get_resume_targets_for_series. next_episode_id is None
    # (has_next False) for non-series rows and for series with no resume target (no
    # episode ever played, or the series is complete).
    has_next: bool = False
    next_episode_id: str | None = None
    next_episode_code: str | None = None    # e.g. "S02E05" — the >> button's tooltip target


# ---------------------------------------------------------------------------
# Series tree DTOs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeasonDTO:
    """One season row in the series tree widget."""
    id: str
    name: str | None
    season_num: int               # SeasonDB.season_number — used for gap detection in the tree
    episode_count: int
    rating: str | None           # pre-extracted from raw_data["rating"]


@dataclass(frozen=True)
class EpisodeDTO:
    """One episode row in the series tree widget.

    Carries both display fields (for the QTreeWidget) and play-side fields
    (series_id, provider_id, season_id) so the tree never stores a live ORM
    object in UserRole data — the DTO is safe post-session.
    """
    id: str
    episode_num: int
    season_num: int
    title: str | None
    series_name: str | None
    stream_url: str | None
    duration: str | None
    is_watched: bool
    rating: float | None         # stored EpisodeDB.rating — computed at ingestion (Wave 4 — #247)
    # Play-side fields (needed by play_episode to look up parent channel + queue season)
    series_id: str = ""
    provider_id: str = ""
    season_id: str = ""
    # Watch-tracking fields — shown as ✓ (completed) or ◔/◐/◕ (graduated in-progress) in the tree
    watch_progress: int = 0      # resume position in seconds (0 = unwatched or completed)
    watch_completed: bool = False  # sticky completion flag
    watch_percent: int = 0       # 0–100: % watched at last capture — drives graduated glyph (◔/◐/◕)
    # Provenance — "manual" (user played deliberately) vs "queue" (auto-advanced) vs None (unwatched)
    last_played_via: str | None = None
    # Episode-grain favorite (Wave 2 Slice 2B) — independent of the parent series' favorite.
    is_favorite: bool = False
    # Episode-grain metadata (Wave 4 — #247) — stored EpisodeDB columns, computed at
    # ingestion; the pane reads these directly, never re-parsing raw_data at render.
    plot: str | None = None
    air_date: str | None = None  # provider's ISO date verbatim — never parsed to a date type here
    still_url: str | None = None  # episode-specific still image, distinct from cover_url


@dataclass(frozen=True)
class EpisodeFavoriteDTO:
    """One favorited-episode row in the Favorites sidebar section (Wave 2 Slice 2B).

    Episode favorites are a separate, additive sub-list under the Favorites section
    (rendered "Series — S##E##  Title"); this DTO carries just what that row and its
    play/availability logic need — no live ORM object crosses the session boundary.
    """
    id: str                              # EpisodeDB.id
    title: str | None
    series_name: str
    season_num: int
    episode_num: int
    provider_id: str | None = None       # None when orphaned
    last_played: datetime | None = None
    available: bool = True               # False when the episode's provider is hidden


# ---------------------------------------------------------------------------
# Analytics DTOs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceFingerprintDTO:
    """Per-source summary: counts, quality/region histograms, prefix coverage."""
    provider_id: str
    name: str
    live_count: int
    movie_count: int
    series_count: int
    total_count: int
    live_visible: int
    movie_visible: int
    series_visible: int
    total_visible: int
    quality_histogram: dict[str, int]      # e.g. {"HD": 100, "4K": 50, "FHD": 200}
    region_histogram: dict[str, int]       # e.g. {"EN": 500, "FR": 300}
    recognized_count: int                  # prefixes in canonical lexicon
    unrecognized_count: int                # prefixes NOT in lexicon
    recognized_pct: float                  # percentage 0-100
    adult_pct: float                       # percentage 0-100
    untagged_pct: float                    # percentage 0-100 (detected_prefix empty)
    special_view_breakdown: dict[str, int] # e.g. {"ppv": 10, "sports": 5}


@dataclass(frozen=True)
class OverlapMatrixDTO:
    """Pairwise overlap between two sources for a media type."""
    provider_a_id: str
    provider_b_id: str
    provider_a_name: str
    provider_b_name: str
    media_type: str
    shared: int                   # titles in both
    a_only: int                   # titles only in A
    b_only: int                   # titles only in B
    jaccard: float                # 0-1, shared / (a_total + b_total - shared)


@dataclass(frozen=True)
class UniqueChannelDTO:
    """Channel that exists only on this provider (not on any other)."""
    channel_id: str
    name: str
    detected_title: str | None
    detected_prefix: str | None
    detected_quality: str | None
    detected_region: str | None
    detected_year: str | None
    media_type: str
    provider_name: str


@dataclass(frozen=True)
class PrefixStatDTO:
    """Unrecognized prefix token with count and sample channel names."""
    prefix: str
    count: int
    sample_names: list[str]       # 3-5 example channel names
    is_recognized: bool           # whether it's in the canonical lexicon


# ---------------------------------------------------------------------------
# TMDb enrichment diagnostics ("Missing TMDb data" view)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TmdbFunnelDTO:
    """Enrichment funnel across visible VOD rows — decision-support for the TMDb API.

    Every count is a movie/series row on a visible, non-excluded provider, bucketed
    by how (or whether) its tmdb id was resolved.  The buckets partition the corpus:
    ``total_vod == from_list + propagated + fetched + unattempted + residual``.  The
    ``residual`` (idless AND attempted-empty) is the ONLY-TMDb-API-addressable gap.
    """
    total_vod: int
    from_list: int       # id shipped in the provider list row (Phase-1 harvest)
    propagated: int      # id adopted from a confident title sibling (free, no network)
    fetched: int         # id found via the provider detail endpoint
    unattempted: int     # idless, not yet attempted (a lazy-fetch candidate)
    residual: int        # idless AND attempted-empty ('none') — only TMDb-API can resolve

    @property
    def resolved(self) -> int:
        """Rows that now carry a tmdb id (via any provider-native method)."""
        return self.from_list + self.propagated + self.fetched

    @property
    def idless(self) -> int:
        """Rows still without a tmdb id (candidates + residual)."""
        return self.unattempted + self.residual

    @property
    def resolved_pct(self) -> float:
        return (self.resolved / self.total_vod * 100.0) if self.total_vod else 0.0

    @property
    def residual_pct(self) -> float:
        return (self.residual / self.total_vod * 100.0) if self.total_vod else 0.0


@dataclass(frozen=True)
class MissingTmdbRowDTO:
    """One idless VOD row shown in the 'Missing TMDb data' sample list."""
    channel_id: str
    name: str
    detected_title: str | None
    detected_year: str | None
    media_type: str
    tmdb_addressable: bool        # clean title (+year for movies) → likely TMDb-matchable


@dataclass(frozen=True)
class MissingTmdbSourceDTO:
    """One source's idless-VOD summary for the 'Missing TMDb data' view."""
    provider_id: str
    provider_name: str
    missing_count: int            # idless VOD rows on this source (detected_tmdb_id NULL)
    residual_count: int           # of those, attempted-empty ('none') — TMDb-API-only
    sample: list["MissingTmdbRowDTO"]


# ---------------------------------------------------------------------------
# Reconnect Engaged Content DTOs (Wave 4 — orphaned engaged-content recovery)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconnectMatchDTO:
    """The proposed live replacement for an orphaned engaged channel.

    Built by ``ChannelRepository.get_reconnect_candidates`` — the best
    same-``content_key`` channel on a NOT-hidden provider, picked by
    ``channel_name_utils.quality_tier_rank``.  Never a title-heuristic match.
    """
    channel_id: str
    name: str
    detected_title: str | None
    detected_quality: str | None
    provider_id: str
    provider_name: str


@dataclass(frozen=True)
class ReconnectCandidateDTO:
    """One orphaned *engaged* channel + its proposed live replacement (or none).

    An orphan is a channel that is engaged (favorited, played, or queued — the
    same ``ChannelRepository._engaged_channel_predicate`` gate that
    ``prune_provider_content`` uses to decide what to KEEP on a source delete)
    whose provider is hidden (inactive/expired/orphaned — see
    ``ProviderRepository.get_hidden_provider_ids``).  ``match`` is ``None``
    when the orphan has no stored ``content_key`` or no live channel shares it
    — the row is still returned (mirror-not-cage: nothing is silently
    dropped), just marked unmatched by the view.

    Built inside a session_scope() by
    :meth:`ChannelRepository.get_reconnect_candidates` — no ORM object crosses
    the session boundary.
    """
    orphan_id: str
    orphan_name: str
    detected_title: str | None
    detected_year: str | None
    media_type: str | None
    provider_id: str
    provider_name: str
    content_key: str | None
    # Engagement fields carried for display of "what will move" — mirror the
    # ChannelDB columns ChannelRepository.reconnect_engaged_content() moves.
    is_favorite: bool
    last_played: datetime | None
    play_count: int
    watch_progress: int
    watch_completed: bool
    watch_percent: int
    user_rating: int              # +1/-1/0 (UserRatingDB), 0 = unrated
    in_queue: bool                # True if any WatchQueueDB row references this channel_id
    match: "ReconnectMatchDTO | None" = None


# ---------------------------------------------------------------------------
# Events tab DTO
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LiveEventDTO:
    """One row in the EPG Events tab — a platform-event channel.

    Platform-event channels are regular playable live channels whose names encode
    a scheduled programme (e.g. "US (Peacock 01) | La Vuelta: Stage 11 (2025-09-03
    07:20:00)"). The provider's "always available" sentinel (far-future date ≥ 2090)
    maps to ``always_available=True`` / ``start_time=None``.

    Safe to pass across the Qt thread boundary from worker → main thread.
    """
    channel_id: str
    name: str
    detected_title: Optional[str]
    network: str
    region: str
    channel_num: str
    start_time: Optional[datetime]          # None when always_available is True
    always_available: bool                  # True for sentinel / no-schedule feeds


# ---------------------------------------------------------------------------
# Tag provenance DTO — details-pane tag display (DR-0006)
# ---------------------------------------------------------------------------

# Feeders that read directly from a provider-supplied field — these are
# "source-given" (the provider explicitly labelled the channel this way).
# All other feeders (name_parse, header, epg) are "ingestion-inferred" —
# MetaTV derived the tag from a secondary signal, not a direct assertion.
_SOURCE_GIVEN_FEEDERS: frozenset[str] = frozenset({
    "provider_category",   # ChannelDB.category — Xtream provider's own category string
    "genre",               # raw_data["genre"] — provider-supplied genre field
    "user",                # explicit user assertion (always source-given by definition)
})


@dataclass(frozen=True)
class ChannelTagDTO:
    """One tag on a channel, with provenance + confidence for display.

    Built inside a session_scope() by TagRepository.get_channel_tags_dto() so
    that no ORM object crosses the session boundary.

    Provenance classification:
    - ``source_given=True``: the provider explicitly supplied this tag value
      (feeder is ``provider_category``, ``genre``, or ``user``).
    - ``source_given=False``: MetaTV derived the tag by inference from a
      secondary signal (``name_parse``, ``header``, or ``epg``).

    Confidence is the v1 formula from tag.py (``min(1.0, feeders/3)``).
    DR-0006: confidence is ranking + prune-priority only — never hidden.
    """
    facet_type: str               # "region", "language", "genre", "platform", etc.
    value: str                    # canonical tag value, e.g. "US", "Drama", "Netflix"
    source_given: bool            # True = provider asserted; False = MetaTV inferred
    confidence: float             # [0.0, 1.0] — low = ranked last, never suppressed
    feeders: tuple[str, ...]      # contributing feeder names (for tooltip)


# ---------------------------------------------------------------------------
# Recipe builder DTOs — tag-cloud + pantry sidebar (task #56, slice 1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FacetSummaryDTO:
    """One row in the Recipe builder's left "Pantry" sidebar.

    Reports the number of *distinct tag values* carried by channels on active
    sources for a single facet type (e.g. Genre → 512 distinct genres).
    Built inside a session_scope() by TagRepository.get_facet_summary() so
    that no ORM object crosses the session boundary.
    """
    facet_type: str       # e.g. "genre", "language", "region", "platform", "quality", "decade", "collection"
    distinct_values: int  # number of unique tag values in active-source channels for this facet


@dataclass(frozen=True)
class TagCountDTO:
    """One entry in the Recipe builder's weighted tag-cloud widget.

    Carries a single tag value and the number of active-source channels
    carrying it, for one facet type.  Sorted by channel_count DESC so the
    cloud can size type by weight.  Built inside a session_scope() by
    TagRepository.get_tag_counts_for_facet() — no ORM objects cross the
    session boundary.
    """
    value: str            # canonical tag value, e.g. "Drama", "English", "Netflix"
    channel_count: int    # number of active-source channels carrying this tag value


@dataclass(frozen=True)
class TagSearchResultDTO:
    """One cross-facet match in the Recipe builder's Pantry search.

    Unlike :class:`TagCountDTO` (which carries values for one already-selected
    facet), this DTO also carries the ``facet_type`` the value belongs to —
    because the Pantry search scans tag values across ALL facets at once and the
    center cloud now mixes facets (each tag colored by its facet).  Built inside
    a session_scope() by TagRepository.search_tag_values_across_facets() — no
    ORM objects cross the session boundary.
    """
    facet_type: str       # the namespace this value belongs to, e.g. "genre", "collection"
    value: str            # canonical tag value, e.g. "Comedy", "Dark Comedy"
    channel_count: int    # number of active-source channels carrying this tag value


# ---------------------------------------------------------------------------
# Cross-repo builder (requires an open session — call inside session_scope())
# ---------------------------------------------------------------------------

def build_history_dtos(
    repos: "RepositoryFactory",
    limit: int = 30,
    adult_mode: str = "all",
) -> list[HistoryDTO]:
    """Build HistoryDTOs with last-played episode code pre-populated for series.

    Must be called inside a session_scope() — performs multiple queries.
    """
    channels = repos.channels.get_recent_history(limit=limit, adult_mode=adult_mode)
    # Batch the series last-played lookup into one query (was N+1 — one query per row).
    series_keys = [
        (ch.source_id, ch.provider_id)
        for ch in channels
        if ch.media_type == MediaType.SERIES
    ]
    code_map = repos.episodes.get_last_played_codes_for_series(series_keys)
    # Batch the "Play Next Episode" resume-target lookup alongside it (Wave 5) — same
    # keys, sibling helper (see EpisodeRepository.get_resume_targets_for_series).
    resume_map = repos.episodes.get_resume_targets_for_series(series_keys)
    result: list[HistoryDTO] = []
    for ch in channels:
        episode_code: str | None = None
        next_episode_id: str | None = None
        next_episode_code: str | None = None
        if ch.media_type == MediaType.SERIES:
            key = (ch.source_id, ch.provider_id)
            episode_code = code_map.get(key)
            resume = resume_map.get(key)
            if resume is not None:
                next_episode_id = resume.id
                next_episode_code = f"S{resume.season_num:02d}E{resume.episode_num:02d}"
        result.append(HistoryDTO(
            id=ch.id,
            name=ch.name,
            media_type=ch.media_type,
            episode_code=episode_code,
            last_played=ch.last_played,
            # Stored ingestion fields off the ChannelDB row (mapped inside the session)
            # so the sidebar renders the shared chip row without re-parsing the name.
            detected_title=ch.detected_title or "",
            detected_year=ch.detected_year or "",
            detected_quality=ch.detected_quality or "",
            detected_prefix=ch.detected_prefix or "",
            has_next=next_episode_id is not None,
            next_episode_id=next_episode_id,
            next_episode_code=next_episode_code,
        ))
    return result
