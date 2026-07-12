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

    @classmethod
    def from_orm(cls, ch, *, user_rating: int = 0) -> "ChannelListDTO":
        """Build a ChannelListDTO from a ChannelDB row (call inside a session).

        Args:
            ch: A live ChannelDB ORM object (must be called inside a session).
            user_rating: The user's rating for this channel (+1, -1, or 0 for unrated).
                Pass from a pre-fetched batch lookup to avoid N+1 queries.
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


@dataclass(frozen=True)
class HistoryDTO:
    """One row in the History sidebar section."""
    id: str
    name: str
    media_type: str | None
    episode_code: str | None     # e.g. "S01E02"; None for non-series or no episode yet


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
    rating: str | None           # pre-extracted from raw_data["info"]["rating"]
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
    result: list[HistoryDTO] = []
    for ch in channels:
        episode_code: str | None = None
        if ch.media_type == MediaType.SERIES:
            episode_code = code_map.get((ch.source_id, ch.provider_id))
        result.append(HistoryDTO(
            id=ch.id,
            name=ch.name,
            media_type=ch.media_type,
            episode_code=episode_code,
        ))
    return result
