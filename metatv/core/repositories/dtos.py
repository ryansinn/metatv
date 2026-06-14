"""Plain-data DTOs returned by repository hot paths.

These frozen dataclasses carry no live SQLAlchemy session, so they are safe to
pass across the Qt thread boundary from worker threads to the main thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from metatv.core.models import MediaType

if TYPE_CHECKING:
    from metatv.core.repositories import RepositoryFactory


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
    episode_count: int
    rating: str | None           # pre-extracted from raw_data["rating"]


@dataclass(frozen=True)
class EpisodeDTO:
    """One episode row in the series tree widget."""
    id: str
    episode_num: int
    season_num: int
    title: str | None
    series_name: str | None
    stream_url: str | None
    duration: str | None
    is_watched: bool
    rating: str | None           # pre-extracted from raw_data["info"]["rating"]


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
