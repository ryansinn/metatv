"""Stream retry queue repository."""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4


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


# Graduated play-failure ledger thresholds (roadmap S3) — play_fail_count is the
# count of USER-INITIATED play failures (distinct from attempt_count, the
# background checker's own re-probe counter). 1st failure → "flagged" (also the
# point a row first enters the retry checker); 3rd+ → "degraded" (rendered
# grayed-but-clickable in the channel list); 6th+ → "dead" (excluded from
# forward-looking list queries — see ChannelRepository._apply_channel_filters).
_DEGRADED_AT = 3
_DEAD_AT = 6


def _reliability_state_for(play_fail_count: int) -> str:
    """Map a play_fail_count to its graduated reliability_state."""
    if play_fail_count >= _DEAD_AT:
        return "dead"
    if play_fail_count >= _DEGRADED_AT:
        return "degraded"
    if play_fail_count >= 1:
        return "flagged"
    return "ok"


class StreamRetryRepository:
    def __init__(self, session):
        self._session = session

    def add(self, channel_id: str, channel_name: str, stream_url: str, error: str) -> StreamRetryDB:
        """Record a play failure — upserts the retry row AND graduates the ledger.

        Called for every user-initiated play failure (advisory HTTP codes
        included, per the roadmap S3 revisit of the prior advisory exclusion).
        """
        existing = self._session.query(StreamRetryDB).filter_by(channel_id=channel_id).first()
        if existing:
            existing.stream_url = stream_url
            existing.last_error = error
            existing.last_checked_at = datetime.utcnow()
            existing.next_check_at = datetime.utcnow() + _next_check_delay(existing.attempt_count)
            existing.status = "pending"
            existing.play_fail_count = (existing.play_fail_count or 0) + 1
            existing.last_play_error = error
            existing.reliability_state = _reliability_state_for(existing.play_fail_count)
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
            play_fail_count=1,
            last_play_error=error,
            reliability_state=_reliability_state_for(1),
        )
        self._session.add(entry)
        self._session.commit()
        return entry

    def get_reliability_map(self) -> dict[str, str]:
        """Return ``{channel_id: reliability_state}`` for every non-"ok" row.

        Batch lookup for the channel-list DTO build (mirrors
        ``RatingRepository.get_all_map()``) — one query instead of N+1.
        """
        rows = (
            self._session.query(StreamRetryDB.channel_id, StreamRetryDB.reliability_state)
            .filter(StreamRetryDB.reliability_state != "ok")
            .all()
        )
        return dict(rows)

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

    def get_all_display(self) -> list[StreamRetryDB]:
        """Return pending + online rows for sidebar display.

        Unlike :meth:`get_all_pending`, this INCLUDES rows the checker just
        marked ``status == "online"`` — the recovered entry stays visible
        (green icon, "Back online!" tooltip) until the user removes it via
        the existing remove/clear paths. The checker itself must keep using
        ``get_all_pending`` (it must never re-probe an already-online row).
        """
        return (
            self._session.query(StreamRetryDB)
            .filter(StreamRetryDB.status.in_(("pending", "online")))
            .order_by(StreamRetryDB.first_failed_at)
            .all()
        )

    def mark_checked(self, entry: StreamRetryDB, ok: bool, error: str | None) -> None:
        entry.last_checked_at = datetime.utcnow()
        entry.attempt_count = (entry.attempt_count or 0) + 1
        if ok:
            entry.status = "online"
            # Ledger reset: a background-checker SUCCESS clears the graduated
            # failure state entirely, regardless of how far it had graduated.
            entry.play_fail_count = 0
            entry.reliability_state = "ok"
            entry.last_play_error = None
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
