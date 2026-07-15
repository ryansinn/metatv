"""Repository for the user's watch queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from metatv.core.database import WatchQueueDB, ChannelDB


@dataclass
class QueueEntry:
    """A single item in the watch queue, independent of ChannelDB join success."""
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
            entries.append(QueueEntry(
                queue_id=row.id,
                channel_id=row.channel_id,
                channel_name=display_name,
                media_type=display_type,
                last_played=ch.last_played if ch else None,
                channel=ch,
                provider_id=pid,
                available=available,
                search_title=search_title,
                detected_region=(ch.detected_region if ch else "") or "",
                detected_quality=(ch.detected_quality if ch else "") or "",
                detected_year=(ch.detected_year if ch else "") or "",
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
        """Append channel_id to the end of the queue. No-op if already queued."""
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
        """Remove channel_id from the queue if present."""
        row = (
            self.session.query(WatchQueueDB)
            .filter_by(channel_id=channel_id)
            .first()
        )
        if row:
            self.session.delete(row)

    def get_queued_ids(self) -> set[str]:
        """Return the set of all channel_ids currently in the queue."""
        return {row.channel_id for row in self.session.query(WatchQueueDB).all()}

    def is_queued(self, channel_id: str) -> bool:
        """Return True if channel_id is currently in the queue."""
        return (
            self.session.query(WatchQueueDB)
            .filter_by(channel_id=channel_id)
            .first()
        ) is not None

    def clear(self) -> None:
        """Remove all entries from the queue."""
        self.session.query(WatchQueueDB).delete()

    def clear_watched(self) -> int:
        """Remove entries whose channel has been played at least once. Returns count removed."""
        rows = self.session.query(WatchQueueDB).all()
        removed = 0
        for row in rows:
            ch = self.session.get(ChannelDB, row.channel_id)
            if ch and ch.last_played:
                self.session.delete(row)
                removed += 1
        return removed
