"""Play outcomes per source: recorded by the start watch, read by Source Analytics.

Rows come from ``gui/playback_start_watch.py`` (the one module that follows a
play from launch to verdict: :meth:`PlaybackEventRepository.record` at the
verdict, :meth:`~PlaybackEventRepository.update` as the play goes on); the
Sources editor's Analytics tab reads
:meth:`PlaybackEventRepository.summary`. Raw rows are kept 90 days, then folded
into weekly per-source counts (Source Analytics Q8).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median

from sqlalchemy import func
from sqlalchemy.orm import Session

from metatv.core.database import ProviderDB
from metatv.core.epg_utils import to_local
from metatv.core.playback_models import ConnectionHoldDB, PlaybackEventDB, PlaybackWeeklyDB
from metatv.core.repositories.dtos import ConnectionsDTO, PlaybackSummaryDTO

#: Outcomes a row can carry. ``refused`` = the source's connection limit.
OUTCOMES = ("started", "never_started", "refused", "dropped")

#: Raw rows older than this fold into PlaybackWeeklyDB (owner, Q8).
KEEP_DAYS = 90


def _week_start(when: datetime) -> date:
    return (when - timedelta(days=when.weekday())).date()


class PlaybackEventRepository:
    """Record and summarise play outcomes."""

    def __init__(self, session: Session):
        self.session = session

    def record(self, *, provider_id: str, channel_id: str, title: str, outcome: str,
               started_at: datetime, http_code: int | None = None,
               time_to_picture_ms: int | None = None) -> int:
        """Insert one attempt's verdict; returns its id for :meth:`finish`."""
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown play outcome {outcome!r}")
        row = PlaybackEventDB(provider_id=provider_id, channel_id=channel_id, title=title or "",
                              outcome=outcome, started_at=started_at, http_code=http_code,
                              time_to_picture_ms=time_to_picture_ms)
        self.session.add(row)
        self.session.flush()
        return row.id

    def update(self, event_id: int, *, outcome: str | None = None,
               seconds_watched: int | None = None, time_to_picture_ms: int | None = None) -> None:
        """Amend an attempt: a frozen play that then advanced becomes ``started``;
        a finished one gets how long it ran, or ``dropped`` if it was cut."""
        row = self.session.get(PlaybackEventDB, event_id)
        if row is None:
            return
        if seconds_watched is not None:
            row.seconds_watched = max(0, int(seconds_watched))
        if time_to_picture_ms is not None:
            row.time_to_picture_ms = int(time_to_picture_ms)
        if outcome is not None:
            if outcome not in OUTCOMES:
                raise ValueError(f"unknown play outcome {outcome!r}")
            row.outcome = outcome

    def summary(self, provider_id: str) -> PlaybackSummaryDTO:
        """Counts per outcome over the kept rows, the median time to picture, and
        attempts/failures per local hour of day (Q11)."""
        counts = dict(
            self.session.query(PlaybackEventDB.outcome, func.count(PlaybackEventDB.id))
            .filter(PlaybackEventDB.provider_id == provider_id)
            .group_by(PlaybackEventDB.outcome)
        )
        since = self.session.query(func.min(PlaybackEventDB.started_at)).filter(
            PlaybackEventDB.provider_id == provider_id).scalar()
        times = [t for (t,) in self.session.query(PlaybackEventDB.time_to_picture_ms).filter(
            PlaybackEventDB.provider_id == provider_id,
            PlaybackEventDB.time_to_picture_ms.isnot(None))]
        by_hour = [[0, 0] for _ in range(24)]
        for started_at, outcome in self.session.query(
                PlaybackEventDB.started_at, PlaybackEventDB.outcome).filter(
                PlaybackEventDB.provider_id == provider_id):
            cell = by_hour[to_local(started_at).hour]
            cell[0] += 1
            cell[1] += outcome != "started"
        return PlaybackSummaryDTO(
            since=since,
            started=counts.get("started", 0) + counts.get("dropped", 0),
            never_started=counts.get("never_started", 0),
            refused=counts.get("refused", 0),
            dropped=counts.get("dropped", 0),
            median_time_to_picture_ms=int(median(times)) if times else None,
            by_hour=tuple((a, f) for a, f in by_hour) if since else (),
        )

    def record_hold(self, provider_id: str, refused_at: datetime, seconds: int) -> None:
        """A connection wait resolved: the source held its connections *seconds* (Q7)."""
        self.session.add(ConnectionHoldDB(provider_id=provider_id, refused_at=refused_at,
                                          seconds=max(0, int(seconds))))

    def connections(self, provider_id: str) -> ConnectionsDTO:
        """The account's limit and use at its last check, plus the recorded waits."""
        limit, in_use = self.session.query(ProviderDB.max_connections, ProviderDB.account_active_cons
                                           ).filter(ProviderDB.id == provider_id).first() or (None, None)
        waits = sorted(s for (s,) in self.session.query(ConnectionHoldDB.seconds)
                       .filter(ConnectionHoldDB.provider_id == provider_id))
        return ConnectionsDTO(limit=limit, in_use=in_use, waits=len(waits),
                              median_seconds=int(median(waits)) if waits else None,
                              longest_seconds=waits[-1] if waits else None)

    def fold_old(self, now: datetime, keep_days: int = KEEP_DAYS) -> int:
        """Fold rows older than *keep_days* into weekly per-source counts; returns rows folded."""
        cutoff = now - timedelta(days=keep_days)
        old = self.session.query(PlaybackEventDB).filter(PlaybackEventDB.started_at < cutoff).all()
        tally: dict[tuple, int] = {}
        for row in old:
            key = (row.provider_id, _week_start(row.started_at), row.outcome)
            tally[key] = tally.get(key, 0) + 1
        for (pid, week, outcome), n in tally.items():
            weekly = self.session.get(PlaybackWeeklyDB, (pid, week, outcome))
            if weekly is None:
                self.session.add(PlaybackWeeklyDB(provider_id=pid, week_start=week,
                                                  outcome=outcome, count=n))
            else:
                weekly.count += n
        for row in old:
            self.session.delete(row)
        return len(old)

    def has_old(self, now: datetime, keep_days: int = KEEP_DAYS) -> bool:
        """Cheap probe: is there anything for :meth:`fold_old` to do?"""
        cutoff = now - timedelta(days=keep_days)
        return self.session.query(PlaybackEventDB.id).filter(
            PlaybackEventDB.started_at < cutoff).first() is not None

    def delete_for_provider(self, provider_id: str) -> None:
        """A deleted source takes its play history with it (foreign keys are off)."""
        self.session.query(PlaybackEventDB).filter_by(provider_id=provider_id).delete()
        self.session.query(PlaybackWeeklyDB).filter_by(provider_id=provider_id).delete()
        self.session.query(ConnectionHoldDB).filter_by(provider_id=provider_id).delete()
