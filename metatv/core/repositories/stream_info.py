"""Stored stream measurements, one row per channel (PLAYED-1)."""
from __future__ import annotations

from datetime import datetime

from metatv.core.database import StreamInfoDB


class StreamInfoRepository:
    """Read and replace a channel's stored stream record."""

    def __init__(self, session):
        self.session = session

    def get(self, channel_id: str) -> dict | None:
        """``{"info", "source", "measured_at"}`` as plain data, or None."""
        row = self.session.get(StreamInfoDB, channel_id)
        if row is None:
            return None
        return {"info": row.info, "source": row.source, "measured_at": row.measured_at}

    def get_many(self, channel_ids: list[str]) -> dict[str, dict]:
        """``{channel_id: record}`` for every channel that has one, in one query."""
        if not channel_ids:
            return {}
        rows = self.session.query(StreamInfoDB).filter(StreamInfoDB.channel_id.in_(channel_ids)).all()
        return {r.channel_id: {"info": r.info, "source": r.source, "measured_at": r.measured_at}
                for r in rows}

    def upsert(self, channel_id: str, info: dict, source: str = "played") -> None:
        """Replace the channel's record with a fresh measurement."""
        row = self.session.get(StreamInfoDB, channel_id)
        if row is None:
            row = StreamInfoDB(channel_id=channel_id)
            self.session.add(row)
        row.info = info
        row.source = source
        row.measured_at = datetime.utcnow()
