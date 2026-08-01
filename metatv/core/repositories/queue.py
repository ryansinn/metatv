"""Repository for the user's watch queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from metatv.core.database import WatchQueueDB, ChannelDB, EpisodeDB


@dataclass
class QueueEntry:
    """A single item in the watch queue, independent of ChannelDB join success.

    Channel-grain (default): ``episode_id`` is None; ``channel_id``/``channel_name``
    identify the queued movie/live/series channel itself.

    Episode-grain (Wave 2 Slice 2B): ``episode_id`` is set; ``channel_id``/
    ``channel_name``/``channel``/``provider_id``/``available`` all still describe
    the PARENT SERIES (availability/orphan-recovery joins are unchanged for either
    grain — see WatchQueueRepository.get_all), while ``season_num``/``episode_num``/
    ``episode_title`` identify the specific queued episode.
    """
    queue_id:     int
    channel_id:   str
    channel_name: str
    media_type:   str
    last_played:  datetime | None   # eagerly extracted before session close
    channel:      ChannelDB | None  # None when orphaned (channel no longer in DB)
    provider_id:  str | None = None   # None when orphaned
    available:    bool = True         # False when provider is inactive/expired or orphaned
    search_title: str = ""            # detected_title or name — recovery search term
    # Ingestion-computed display fields — read at render (never re-parse the name).
    detected_region:  str = ""
    detected_quality: str = ""
    detected_year:    str = ""
    detected_prefix:  str = ""        # audio-language token — the honest chip-row language
    # Episode-grain fields (Wave 2 Slice 2B) — None on channel-grain entries.
    episode_id:    str | None = None
    season_num:    int | None = None
    episode_num:   int | None = None
    episode_title: str | None = None

    @property
    def is_episode(self) -> bool:
        """True when this entry queues a single EPISODE rather than a whole channel."""
        return self.episode_id is not None


class WatchQueueRepository:
    """CRUD for WatchQueueDB — ordered list of channels to watch soon."""

    def __init__(self, session: Session):
        self.session = session

    def get_all(
        self,
        hidden_provider_ids: set[str] | None = None,
    ) -> list[QueueEntry]:
        """Return queue entries in position order.

        Each entry carries a live ChannelDB reference if the channel still exists.
        Orphaned entries (channel deleted or ID changed) are kept and logged so
        the user never loses visibility into what they queued.

        Args:
            hidden_provider_ids: If supplied, entries whose channel belongs to one
                of these providers are annotated with ``available=False``.  Orphaned
                entries (no matching ChannelDB row) are always unavailable.
        """
        rows = (
            self.session.query(WatchQueueDB)
            .order_by(WatchQueueDB.position)
            .all()
        )
        hidden: set[str] = hidden_provider_ids or set()
        entries: list[QueueEntry] = []
        for row in rows:
            ch = self.session.get(ChannelDB, row.channel_id)
            if not ch and row.source_id:
                # Fallback: channel was refreshed with a new primary key but same
                # provider-native stream ID — try to relocate it.
                ch = (
                    self.session.query(ChannelDB)
                    .filter_by(source_id=row.source_id)
                    .first()
                )
            if not ch:
                logger.warning(
                    f"Watch queue entry orphaned: channel_id={row.channel_id!r} "
                    f"name={row.channel_name!r} — displaying stored name"
                )
            # Prefer stored name (orphan-safe), fall back to live channel name,
            # then generic "Unknown" as last resort.
            display_name = (
                row.channel_name
                or (ch.name if ch else "")
                or "Unknown"
            )
            display_type = row.media_type or (ch.media_type if ch else "") or ""
            # Compute availability and recovery title inside the session.
            pid = ch.provider_id if ch else None
            available = (
                ch is not None and (not hidden or pid not in hidden)
            )
            search_title = (ch.detected_title if ch else "") or display_name
            # Episode-grain rows (Slice 2B): sort by the EPISODE's own last_played,
            # not the series' — the series may have been engaged via a different
            # episode. season_num/episode_num/episode_title are denormalized on the
            # row itself (orphan-safe), so no EpisodeDB join is needed for those.
            if row.episode_id:
                ep = self.session.get(EpisodeDB, row.episode_id)
                entry_last_played = ep.last_played if ep else None
            else:
                entry_last_played = ch.last_played if ch else None
            entries.append(QueueEntry(
                queue_id=row.id,
                channel_id=row.channel_id,
                channel_name=display_name,
                media_type=display_type,
                last_played=entry_last_played,
                channel=ch,
                provider_id=pid,
                available=available,
                search_title=search_title,
                detected_region=(ch.detected_region if ch else "") or "",
                detected_quality=(ch.detected_quality if ch else "") or "",
                detected_year=(ch.detected_year if ch else "") or "",
                detected_prefix=(ch.detected_prefix if ch else "") or "",
                episode_id=row.episode_id,
                season_num=row.season_num,
                episode_num=row.episode_num,
                episode_title=row.episode_title,
            ))
        return entries

    def clear_unavailable(self, hidden_provider_ids: set[str]) -> int:
        """Delete queue rows whose channel's provider is hidden (inactive/expired)
        or whose channel no longer exists (orphaned).

        Args:
            hidden_provider_ids: Provider IDs to treat as unavailable.

        Returns:
            Number of rows removed.
        """
        rows = (
            self.session.query(WatchQueueDB)
            .order_by(WatchQueueDB.position)
            .all()
        )
        removed = 0
        for row in rows:
            ch = self.session.get(ChannelDB, row.channel_id)
            if not ch and row.source_id:
                ch = (
                    self.session.query(ChannelDB)
                    .filter_by(source_id=row.source_id)
                    .first()
                )
            # Remove orphaned entries or entries on a hidden provider.
            if ch is None or ch.provider_id in hidden_provider_ids:
                self.session.delete(row)
                removed += 1
        return removed

    def add(self, channel_id: str, channel_name: str = "", media_type: str = "", source_id: str = "") -> None:
        """Append channel_id to the end of the queue. No-op if already queued.

        Channel-grain only (``episode_id IS NULL``) — see :meth:`add_episode` for
        queuing a single episode. Scoping this way means queuing episodes of a
        series never makes the series ROOT itself read as "in queue" (and vice
        versa); they are independent entries.
        """
        if self.is_queued(channel_id):
            return
        # Assign a position strictly greater than any existing row so a prior
        # non-tail remove() (which does not reindex) can never leave two rows
        # sharing a position and making order_by(position) unstable.
        max_pos = self.session.query(func.max(WatchQueueDB.position)).scalar()
        self.session.add(WatchQueueDB(
            channel_id=channel_id,
            channel_name=channel_name,
            media_type=media_type,
            source_id=source_id,
            position=(max_pos + 1) if max_pos is not None else 0,
        ))

    def remove(self, channel_id: str) -> None:
        """Remove the channel-grain queue row for channel_id, if present.

        Scoped to ``episode_id IS NULL`` — never deletes an episode-grain row
        that happens to share this channel_id as its parent series.
        """
        row = (
            self.session.query(WatchQueueDB)
            .filter_by(channel_id=channel_id, episode_id=None)
            .first()
        )
        if row:
            self.session.delete(row)

    def get_queued_ids(self) -> set[str]:
        """Return the set of channel_ids with a CHANNEL-grain queue entry.

        Scoped to ``episode_id IS NULL`` — a series with only episodes queued is
        not included (its root channel isn't itself in the queue).
        """
        return {
            row.channel_id
            for row in self.session.query(WatchQueueDB).filter_by(episode_id=None).all()
        }

    def is_queued(self, channel_id: str) -> bool:
        """Return True if channel_id has a CHANNEL-grain queue entry (episode_id IS NULL)."""
        return (
            self.session.query(WatchQueueDB)
            .filter_by(channel_id=channel_id, episode_id=None)
            .first()
        ) is not None

    # --- Episode-grain (Wave 2 Slice 2B) ------------------------------------

    def add_episode(
        self,
        episode_id: str,
        channel_id: str,
        channel_name: str = "",
        season_num: int = 0,
        episode_num: int = 0,
        episode_title: str = "",
        source_id: str = "",
    ) -> None:
        """Append a single EPISODE to the end of the queue. No-op if already queued.

        Args:
            episode_id: EpisodeDB.id of the episode to queue.
            channel_id: ChannelDB.id of the PARENT SERIES (used for provider/
                availability joins — see WatchQueueRepository.get_all).
            channel_name: The series' display name, denormalized (orphan-safe).
            season_num, episode_num, episode_title: Denormalized episode identity —
                survive an orphaned EpisodeDB row, same rationale as channel_name.
            source_id: The series' provider-native stream id (orphan fallback lookup).
        """
        if self.is_episode_queued(episode_id):
            return
        max_pos = self.session.query(func.max(WatchQueueDB.position)).scalar()
        self.session.add(WatchQueueDB(
            channel_id=channel_id,
            channel_name=channel_name,
            media_type="series",
            source_id=source_id,
            episode_id=episode_id,
            season_num=season_num,
            episode_num=episode_num,
            episode_title=episode_title,
            position=(max_pos + 1) if max_pos is not None else 0,
        ))

    def remove_episode(self, episode_id: str) -> None:
        """Remove the queue row for a single episode, if present."""
        row = (
            self.session.query(WatchQueueDB)
            .filter_by(episode_id=episode_id)
            .first()
        )
        if row:
            self.session.delete(row)

    def is_episode_queued(self, episode_id: str) -> bool:
        """Return True if this episode has its own queue entry."""
        return (
            self.session.query(WatchQueueDB)
            .filter_by(episode_id=episode_id)
            .first()
        ) is not None

    def clear(self) -> None:
        """Remove all entries from the queue (both grains)."""
        self.session.query(WatchQueueDB).delete()

    def clear_watched(self) -> int:
        """Remove entries whose content has been played at least once.

        Episode-grain rows check the EPISODE's own last_played (not the series');
        channel-grain rows check the channel's. Returns count removed.
        """
        rows = self.session.query(WatchQueueDB).all()
        removed = 0
        for row in rows:
            if row.episode_id:
                ep = self.session.get(EpisodeDB, row.episode_id)
                if ep and ep.last_played:
                    self.session.delete(row)
                    removed += 1
                continue
            ch = self.session.get(ChannelDB, row.channel_id)
            if ch and ch.last_played:
                self.session.delete(row)
                removed += 1
        return removed
