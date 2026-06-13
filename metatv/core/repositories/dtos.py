"""Plain-data DTOs returned by repository hot paths.

These frozen dataclasses carry no live SQLAlchemy session, so they are safe to
pass across the Qt thread boundary from worker threads to the main thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

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
    from metatv.core.models import MediaType

    channels = repos.channels.get_recent_history(limit=limit, adult_mode=adult_mode)
    result: list[HistoryDTO] = []
    for ch in channels:
        episode_code: str | None = None
        if ch.media_type == MediaType.SERIES:
            last_ep = repos.episodes.get_last_played(
                series_id=ch.source_id,
                provider_id=ch.provider_id,
            )
            if last_ep:
                episode_code = f"S{last_ep.season_num:02d}E{last_ep.episode_num:02d}"
        result.append(HistoryDTO(
            id=ch.id,
            name=ch.name,
            media_type=ch.media_type,
            episode_code=episode_code,
        ))
    return result
