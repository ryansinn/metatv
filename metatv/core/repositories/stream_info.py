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

    def upsert(self, channel_id: str, info: dict, source: str = "played") -> None:
        """Replace the channel's record with a fresh measurement."""
        row = self.session.get(StreamInfoDB, channel_id)
        if row is None:
            row = StreamInfoDB(channel_id=channel_id)
            self.session.add(row)
        row.info = info
        row.source = source
        row.measured_at = datetime.utcnow()
