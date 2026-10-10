"""Stored stream measurements, one row per channel (PLAYED-1)."""
from __future__ import annotations

from datetime import datetime

from metatv.core.database import ChannelDB, StreamInfoDB
from metatv.core.stream_info import audio_contradicts_prefix, summarize


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

    def prefix_exempt_ids(self, excluded_prefixes) -> set[str]:
        """Channels a Global Exclusion would hide by prefix, but whose measured
        audio proves they are not in the language that prefix denotes (an
        excluded |SE| copy measured as English). A verified fact outranks the
        prefix guess, so the exclusion predicates keep these."""
        if not excluded_prefixes:
            return set()
        rows = (
            self.session.query(StreamInfoDB.channel_id, StreamInfoDB.info, ChannelDB.detected_prefix)
            .join(ChannelDB, ChannelDB.id == StreamInfoDB.channel_id)
            .filter(ChannelDB.detected_prefix.in_(list(excluded_prefixes)))
            .all()
        )
        return {
            cid for cid, info, prefix in rows
            if audio_contradicts_prefix(
                (summarize({"info": info}) or {}).get("audio", ()), prefix)
        }

    def upsert(self, channel_id: str, info: dict, source: str = "played") -> None:
        """Replace the channel's record with a fresh measurement."""
        row = self.session.get(StreamInfoDB, channel_id)
        if row is None:
            row = StreamInfoDB(channel_id=channel_id)
            self.session.add(row)
        row.info = info
        row.source = source
        row.measured_at = datetime.utcnow()
        # Searchable: a language heard in the stream becomes a language tag.
        # Episodes have no channel row to tag (their ids miss the channel join).
        from metatv.core.repositories.tag import TagRepository
        tags = TagRepository(self.session)
        tags.apply_measured_tags(channel_id, info)
        # An episode has no channel row to tag; its languages roll up to the
        # series COPY that holds it (same source, same series id) — never to a
        # sibling variant, whose episodes are a different file.
        series_id = self._series_copy_of_episode(channel_id)
        if series_id:
            tags.apply_measured_tags(series_id, info)

    def _series_copy_of_episode(self, episode_id: str) -> "str | None":
        """The ``ChannelDB.id`` of the series copy an episode belongs to, or None."""
        from metatv.core.database import EpisodeDB
        ep = self.session.get(EpisodeDB, episode_id)
        if ep is None:
            return None
        row = (self.session.query(ChannelDB.id)
               .filter(ChannelDB.source_id == ep.series_id,
                       ChannelDB.provider_id == ep.provider_id,
                       ChannelDB.media_type == "series")
               .first())
        return row[0] if row else None
