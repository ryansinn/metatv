"""Playback models: what a played stream contained, and how each play went.

Split out of ``database.py`` (at its size pin) when the play-outcome tables
landed, because they and ``StreamInfoDB`` answer one question from two sides —
what playing a source is actually like. ``database.py`` imports this module at
its end, which registers these tables on ``Base`` before ``create_all`` and
keeps ``from metatv.core.database import StreamInfoDB`` working; ``Base`` comes
from ``db_base`` so importing this module first is not circular.

New TABLES need no migration entry: ``create_all`` creates a missing table. A
new COLUMN on one of these does — see ``core/schema_migrations.py``.
"""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Index, Integer, String

from metatv.core.db_base import Base, JSONEncoded


class StreamInfoDB(Base):
    """What a channel's stream actually contained when it was last measured
    (PLAYED-1): resolution, fps, codecs, bitrates, audio and subtitle tracks.

    One row per channel, replaced on every measurement. ``info`` is the plain
    record ``core.stream_info.parse_mpv`` builds; ``source`` is ``"played"``
    (captured while the user watched) or ``"probe"`` (fetched on request).
    Only played channels get a row, and played channels are engaged, so a
    provider delete never orphans one (it keeps engaged channels).
    """
    __tablename__ = "stream_info"

    channel_id  = Column(String, primary_key=True)
    info        = Column(JSONEncoded, nullable=False)
    source      = Column(String, nullable=False, default="played")
    measured_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    #: The name of what was measured. Providers recycle stream ids, so when a
    #: catalog refresh finds a different name under this id the measurement is
    #: about another title and is discarded (StreamInfoRepository.invalidate_changed).
    fingerprint = Column(String)


class PlaybackEventDB(Base):
    """One play attempt's outcome (Source Analytics Q6).

    Written by ``gui/playback_start_watch.py`` — the one module that follows
    every attempt from launch to verdict — when the verdict is reached, then
    amended as the play goes on. Outcomes: ``started`` (playback advanced),
    ``never_started``, ``refused`` (connection limit — HTTP 458/509 and kin),
    ``dropped`` (advanced, then the source cut it mid-play). Kept 90 days, then
    folded into :class:`PlaybackWeeklyDB` (Q8).
    """
    __tablename__ = "playback_events"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    provider_id        = Column(String, nullable=False)
    channel_id         = Column(String, nullable=False)
    title              = Column(String, nullable=False, default="")
    started_at         = Column(DateTime, nullable=False, default=datetime.utcnow)  # UTC-naive
    outcome            = Column(String, nullable=False)
    http_code          = Column(Integer)
    time_to_picture_ms = Column(Integer)   # launch → first advancing position
    seconds_watched    = Column(Integer)

    __table_args__ = (Index("ix_playback_events_provider_time", "provider_id", "started_at"),)


class PlaybackWeeklyDB(Base):
    """Play outcomes per source per week, for events past the 90-day window (Q8)."""
    __tablename__ = "playback_weekly"

    provider_id = Column(String, primary_key=True)
    week_start  = Column(Date, primary_key=True)    # Monday, UTC
    outcome     = Column(String, primary_key=True)
    count       = Column(Integer, nullable=False, default=0)
