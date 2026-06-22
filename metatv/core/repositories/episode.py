"""Episode repository for data access"""

from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

from metatv.core.database import EpisodeDB
from metatv.core.repositories.dtos import EpisodeDTO


class EpisodeRepository:
    """Repository for episode data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, episode_id: str) -> Optional[EpisodeDB]:
        """Get episode by ID"""
        return self.session.query(EpisodeDB).filter_by(id=episode_id).first()
    
    def get_by_series(self, series_id: str, provider_id: str) -> List[EpisodeDB]:
        """Get all episodes for a series"""
        return self.session.query(EpisodeDB).filter_by(
            series_id=series_id,
            provider_id=provider_id
        ).order_by(
            EpisodeDB.season_num,
            EpisodeDB.episode_num
        ).all()
    
    def get_by_season(self, season_id: str) -> List[EpisodeDB]:
        """Get all episodes for a season"""
        return self.session.query(EpisodeDB).filter_by(
            season_id=season_id
        ).order_by(EpisodeDB.episode_num).all()

    def get_episodes_dto_by_season(self, season_id: str) -> "List[EpisodeDTO]":
        """Return episodes as plain DTOs — thread-safe, no live session required."""
        episodes = self.get_by_season(season_id=season_id)
        result: list[EpisodeDTO] = []
        for ep in episodes:
            rating: str | None = None
            if ep.raw_data and isinstance(ep.raw_data, dict):
                info = ep.raw_data.get("info", {})
                if isinstance(info, dict):
                    rating = info.get("rating") or None
            result.append(EpisodeDTO(
                id=ep.id,
                episode_num=ep.episode_num,
                season_num=ep.season_num,
                title=ep.title,
                series_name=ep.series_name,
                stream_url=ep.stream_url,
                duration=ep.duration,
                is_watched=ep.is_watched,
                rating=rating,
                series_id=ep.series_id,
                provider_id=ep.provider_id,
                season_id=ep.season_id,
                watch_progress=int(getattr(ep, "watch_progress", 0) or 0),
                watch_completed=bool(getattr(ep, "watch_completed", False)),
                watch_percent=int(getattr(ep, "watch_percent", 0) or 0),
            ))
        return result
    
    def get_last_played(self, series_id: str, provider_id: str) -> Optional[EpisodeDB]:
        """Get last played episode for a series"""
        return self.session.query(EpisodeDB).filter(
            EpisodeDB.series_id == series_id,
            EpisodeDB.provider_id == provider_id,
            EpisodeDB.last_played.isnot(None)
        ).order_by(EpisodeDB.last_played.desc()).first()

    def get_last_played_dto(self, series_id: str, provider_id: str) -> "Optional[PlayableEpisodeDTO]":
        """Return a PlayableEpisodeDTO for the last played episode, or None.

        Must be called inside a session_scope().  No ORM object escapes — the
        returned frozen dataclass is safe to use after the session closes.
        """
        from metatv.core.repositories.dtos import PlayableEpisodeDTO
        ep = self.get_last_played(series_id=series_id, provider_id=provider_id)
        if ep is None:
            return None
        return PlayableEpisodeDTO(
            id=ep.id,
            title=ep.title,
            stream_url=ep.stream_url,
            series_id=ep.series_id,
            provider_id=ep.provider_id,
            season_id=ep.season_id,
            episode_num=ep.episode_num,
            season_num=ep.season_num,
        )

    def get_last_played_codes_for_series(
        self, keys: "List[tuple[str, str]]"
    ) -> "Dict[tuple[str, str], str]":
        """Batch the per-series last-played lookup into ONE query.

        For each ``(series_id, provider_id)`` key, returns the ``S..E..`` code of its
        most recently played episode. Replaces an N+1 of ``get_last_played`` calls (one
        per history row). History can span providers, so the key is the pair, not just
        the series id. Ordering desc + first-seen-per-key reproduces ``get_last_played``'s
        single-row semantics exactly.
        """
        if not keys:
            return {}
        wanted = set(keys)
        series_ids = {k[0] for k in keys}
        provider_ids = {k[1] for k in keys}
        rows = self.session.query(EpisodeDB).filter(
            EpisodeDB.series_id.in_(series_ids),
            EpisodeDB.provider_id.in_(provider_ids),
            EpisodeDB.last_played.isnot(None),
        ).order_by(EpisodeDB.last_played.desc()).all()
        out: Dict[tuple[str, str], str] = {}
        for ep in rows:
            key = (ep.series_id, ep.provider_id)
            if key in wanted and key not in out:
                out[key] = f"S{ep.season_num:02d}E{ep.episode_num:02d}"
        return out
    
    def mark_played(self, episode_id: str):
        """Mark episode as played"""
        episode = self.get_by_id(episode_id)
        if episode:
            episode.last_played = datetime.now()
            episode.play_count = (episode.play_count or 0) + 1
            episode.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Marked episode as played: {episode.title}")
    
    def mark_watched(self, episode_id: str, watched: bool = True) -> bool:
        """Mark episode as watched/unwatched, setting all watch fields coherently.

        watched=True  → is_watched=True,  watch_completed=True,  watch_percent=100,
                         watch_progress unchanged (resume point left as-is).
        watched=False → is_watched=False, watch_completed=False, watch_percent=0,
                         watch_progress=0  (clear resume point — item is truly unwatched).

        Returns True if the episode was found and updated, False if not found.
        """
        episode = self.get_by_id(episode_id)
        if episode is None:
            return False
        if watched:
            episode.is_watched = True
            episode.watch_completed = True
            episode.watch_percent = 100
        else:
            episode.is_watched = False
            episode.watch_completed = False
            episode.watch_percent = 0
            episode.watch_progress = 0
        episode.updated_at = datetime.now()
        self.session.commit()
        logger.info(f"Marked episode {episode.title} as {'watched' if watched else 'unwatched'}")
        return True

    def mark_watched_bulk(self, episode_ids: "List[str]", watched: bool = True) -> int:
        """Mark multiple episodes as watched/unwatched atomically.

        Sets all watch fields coherently (same semantics as :meth:`mark_watched`).
        Commits once for the whole batch.

        Returns the number of episodes actually updated.
        """
        if not episode_ids:
            return 0
        updated = 0
        for episode_id in episode_ids:
            episode = self.get_by_id(episode_id)
            if episode is None:
                continue
            if watched:
                episode.is_watched = True
                episode.watch_completed = True
                episode.watch_percent = 100
            else:
                episode.is_watched = False
                episode.watch_completed = False
                episode.watch_percent = 0
                episode.watch_progress = 0
            episode.updated_at = datetime.now()
            updated += 1
        if updated:
            self.session.commit()
        logger.info(f"Bulk marked {updated} episode(s) as {'watched' if watched else 'unwatched'}")
        return updated

    def get_watch_state_by_season(self, season_id: str) -> "tuple[int, int]":
        """Return (total_episodes, completed_episodes) for a season.

        Used to derive the season-level watched indicator without adding a
        SeasonDB column — the indicator is computed from its episodes.
        """
        episodes = self.get_by_season(season_id=season_id)
        total = len(episodes)
        completed = sum(1 for ep in episodes if ep.watch_completed)
        return total, completed
    
    def update_progress(self, episode_id: str, progress_seconds: int):
        """Update watch progress"""
        episode = self.get_by_id(episode_id)
        if episode:
            episode.watch_progress = progress_seconds
            episode.updated_at = datetime.now()
            self.session.commit()

    def record_watch_progress(
        self,
        episode_id: str,
        position_s: float,
        duration_s: float,
        threshold: float = 0.9,
        played_via: str = "manual",
    ) -> bool:
        """Record episode watch progress: resume point + sticky completion.

        Mirror of :meth:`ChannelRepository.record_watch_progress` for episodes:
        sets ``watch_progress`` (resume seconds), ``last_played``, and
        ``last_played_via``; at ``>= threshold`` marks ``is_watched`` (sticky) and
        clears the resume point. ``play_count`` is owned by ``mark_played``.

        Returns True if this call marked the episode watched.
        """
        episode = self.get_by_id(episode_id)
        if episode is None:
            return False
        completed = bool(duration_s and duration_s > 0 and (position_s / duration_s) >= threshold)
        pct = (
            min(100, max(0, round(position_s / duration_s * 100)))
            if duration_s and duration_s > 0
            else 0
        )
        episode.last_played = datetime.now()
        episode.last_played_via = played_via
        episode.watch_percent = 100 if completed else pct
        if completed:
            episode.is_watched = True
            episode.watch_completed = True
            episode.watch_progress = 0
        else:
            episode.watch_progress = max(0, int(position_s))
        episode.updated_at = datetime.now()
        self.session.commit()
        return completed

    def bulk_create_or_update(self, episodes: List[EpisodeDB]):
        """Bulk create or update episodes"""
        for episode in episodes:
            existing = self.get_by_id(episode.id)
            if existing:
                # Update existing, preserve playback tracking
                existing.title = episode.title
                existing.duration = episode.duration
                existing.container_extension = episode.container_extension
                existing.stream_url = episode.stream_url
                existing.cover_url = episode.cover_url
                existing.raw_data = episode.raw_data
                existing.updated_at = datetime.now()
            else:
                # Create new
                self.session.add(episode)
        
        self.session.commit()
        logger.info(f"Bulk created/updated {len(episodes)} episodes")
    
    def delete_by_series(self, series_id: str, provider_id: str) -> int:
        """Delete all episodes for a series"""
        count = self.session.query(EpisodeDB).filter_by(
            series_id=series_id,
            provider_id=provider_id
        ).delete()
        self.session.commit()
        logger.info(f"Deleted {count} episodes for series {series_id}")
        return count
