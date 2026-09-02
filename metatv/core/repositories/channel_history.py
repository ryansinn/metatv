"""Playback-history writes for ChannelRepository — recording and forgetting.

Split out of ``channel.py`` following the pattern its siblings already set
(``channel_stats``, ``channel_lens``, ``channel_ingestion``): a coherent
cluster that reads and writes ``last_played``/``play_count`` and nothing else.

Extracted while adding the per-group purge that History's time headings need.
``channel.py`` is the file whose 1016 -> 4129 growth is the reason the
code-health ratchet exists, so a history-purge method was not going to be the
thing that grew it again — and these four already formed a group, so this is
cohesion rather than arithmetic.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from metatv.core.database import ChannelDB


class _ChannelHistoryMixin:
    """Playback-history writes for ChannelRepository (uses self.session)."""

    def clear_history(self):
        """Clear all playback history"""
        count = self.session.query(ChannelDB).filter(
            ChannelDB.last_played.isnot(None)
        ).update({
            ChannelDB.last_played: None,
            ChannelDB.play_count: 0
        })
        self.session.commit()
        logger.info(f"Cleared history for {count} channels")
        return count
    
    def clear_history_older_than(self, days: int, *, now=None) -> int:
        """Forget playback older than ``days``, keeping everything since.

        The blunt :meth:`clear_history` is all-or-nothing, which makes tidying
        up an all-or-nothing decision too — owner: "people aren't wiping
        history daily ... maybe add a second wipe history option that wipes
        history older than a month or older than two weeks."

        Args:
            days: Age threshold. Rows last played strictly before this many
                days ago are cleared.
            now: Reference point; defaults to ``datetime.now()``. Injectable so
                a test can pin the boundary — without it the clock bug below is
                only reproducible on a machine far enough from UTC, and CI runs
                in UTC, where it hides completely.

        Returns:
            How many channels were cleared.
        """
        from datetime import datetime, timedelta

        # datetime.now(), NOT utcnow(): ``last_played`` is WRITTEN with
        # ``datetime.now()`` (local), so a UTC cutoff compared the two on
        # different clocks. Six hours adrift on the owner's machine, which made
        # "clear older than 30 days" silently clear 29.75 days — deleting more
        # history than was asked for, irreversibly.
        cutoff = (now or datetime.now()) - timedelta(days=days)
        count = self.session.query(ChannelDB).filter(
            ChannelDB.last_played.isnot(None),
            ChannelDB.last_played < cutoff,
        ).update({
            ChannelDB.last_played: None,
            ChannelDB.play_count: 0,
        }, synchronize_session=False)
        self.session.commit()
        logger.info(f"Cleared history older than {days}d for {count} channels")
        return count

    def clear_history_in_range(
        self, not_before: datetime | None, not_after: datetime | None
    ) -> tuple[int, list[tuple[str, datetime | None, int]]]:
        """Forget playback inside a half-open window — one History group's purge.

        The per-group counterpart to :meth:`clear_history_older_than`. The
        window comes from ``history_buckets.bucket_range`` — the SAME function
        that decides which heading a row is shown under, so a heading cannot
        delete rows it never listed. Local time, matching how ``last_played``
        is written.

        Before clearing, every affected row is snapshotted — plain data, not
        ORM objects, so it survives past this session — so the caller can
        offer an Undo that restores exactly what this call removed. See
        :meth:`restore_history_snapshot`.

        Args:
            not_before: Inclusive lower bound, or ``None`` for unbounded.
            not_after: Exclusive upper bound, or ``None`` for unbounded.

        Returns:
            A ``(count, snapshot)`` pair: how many channels were cleared, and
            a list of ``(channel_id, last_played, play_count)`` tuples — one
            per cleared row, captured as it stood immediately before the
            clear.
        """
        query = self.session.query(ChannelDB).filter(
            ChannelDB.last_played.isnot(None)
        )
        if not_before is not None:
            query = query.filter(ChannelDB.last_played >= not_before)
        if not_after is not None:
            query = query.filter(ChannelDB.last_played < not_after)

        snapshot = [
            (row.id, row.last_played, row.play_count) for row in query.all()
        ]

        count = query.update({
            ChannelDB.last_played: None,
            ChannelDB.play_count: 0,
        }, synchronize_session=False)
        self.session.commit()
        logger.info(
            f"Cleared history in [{not_before}, {not_after}) for {count} channels"
        )
        return count, snapshot

    def restore_history_snapshot(
        self, snapshot: list[tuple[str, datetime | None, int]]
    ) -> int:
        """Undo a group purge — restore rows nobody has touched since.

        For each ``(channel_id, last_played, play_count)`` in *snapshot*,
        restores those two fields ONLY where the row's ``last_played`` is
        currently ``NULL``. A channel the user re-played during the toast's
        lifetime already carries a newer ``last_played`` than the snapshot
        remembers; overwriting it with the snapshot would move that
        channel's history backwards, silently erasing the re-play. Such rows
        are simply skipped — Undo restores everything else.

        Args:
            snapshot: ``(channel_id, last_played, play_count)`` tuples, as
                returned by :meth:`clear_history_in_range`.

        Returns:
            How many rows were actually restored (excludes any skipped
            because they were re-played since the purge).
        """
        restored = 0
        for channel_id, last_played, play_count in snapshot:
            restored += self.session.query(ChannelDB).filter(
                ChannelDB.id == channel_id,
                ChannelDB.last_played.is_(None),
            ).update({
                ChannelDB.last_played: last_played,
                ChannelDB.play_count: play_count,
            }, synchronize_session=False)
        self.session.commit()
        logger.info(f"Restored history for {restored} channel(s) from snapshot")
        return restored

    def remove_from_history(self, channel_id: str) -> bool:
        """Remove single channel from history"""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.last_played = None
            channel.play_count = 0
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Removed {channel.name} from history")
            return True
        return False
    