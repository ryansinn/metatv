"""Stream retry queue repository."""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from loguru import logger

from metatv.core.database import StreamRetryDB

# Backoff delays by attempt count
_BACKOFF: list[timedelta] = [
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=12),
    timedelta(hours=48),
]
_BACKOFF_MAX = timedelta(days=7)


def _next_check_delay(attempt_count: int) -> timedelta:
    if attempt_count < len(_BACKOFF):
        return _BACKOFF[attempt_count]
    return _BACKOFF_MAX


class StreamRetryRepository:
    def __init__(self, session):
        self._session = session

    def add(self, channel_id: str, channel_name: str, stream_url: str, error: str) -> StreamRetryDB:
        existing = self._session.query(StreamRetryDB).filter_by(channel_id=channel_id).first()
        if existing:
            existing.stream_url = stream_url
            existing.last_error = error
            existing.last_checked_at = datetime.utcnow()
            existing.next_check_at = datetime.utcnow() + _next_check_delay(existing.attempt_count)
            existing.status = "pending"
            self._session.commit()
            return existing

        entry = StreamRetryDB(
            id=str(uuid4()),
            channel_id=channel_id,
            channel_name=channel_name,
            stream_url=stream_url,
            first_failed_at=datetime.utcnow(),
            last_checked_at=datetime.utcnow(),
            next_check_at=datetime.utcnow() + _BACKOFF[0],
            attempt_count=0,
            last_error=error,
            status="pending",
        )
        self._session.add(entry)
        self._session.commit()
        return entry

    def get_due(self) -> list[StreamRetryDB]:
        return (
            self._session.query(StreamRetryDB)
            .filter(StreamRetryDB.status == "pending")
            .filter(StreamRetryDB.next_check_at <= datetime.utcnow())
            .all()
        )

    def get_all_pending(self) -> list[StreamRetryDB]:
        return (
            self._session.query(StreamRetryDB)
            .filter(StreamRetryDB.status == "pending")
            .order_by(StreamRetryDB.first_failed_at)
            .all()
        )

    def mark_checked(self, entry: StreamRetryDB, ok: bool, error: str | None) -> None:
        entry.last_checked_at = datetime.utcnow()
        entry.attempt_count = (entry.attempt_count or 0) + 1
        if ok:
            entry.status = "online"
        else:
            entry.last_error = error or entry.last_error
            entry.next_check_at = datetime.utcnow() + _next_check_delay(entry.attempt_count)
        self._session.commit()

    def remove(self, entry_id: str) -> None:
        entry = self._session.query(StreamRetryDB).filter_by(id=entry_id).first()
        if entry:
            self._session.delete(entry)
            self._session.commit()

    def remove_by_channel(self, channel_id: str) -> None:
        self._session.query(StreamRetryDB).filter_by(channel_id=channel_id).delete()
        self._session.commit()

    def clear_all(self) -> None:
        self._session.query(StreamRetryDB).delete()
        self._session.commit()
