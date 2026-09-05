"""Migration task: heal channels and content_tags orphaned by removed sources.

Formerly two ``PRAGMA user_version``-gated one-shot sweeps in ``database.py``
(``_prune_orphaned_channels`` / ``_prune_orphaned_content_tags``), each run at
most ONCE ever, from ``Database.create_tables()``, before startup could
proceed. SQLite foreign keys are OFF in this app, so every provider delete —
or a crash mid-delete — can leave new orphans behind, and a sweep that stamps
its version the first time it runs never looks again: the second orphan is
invisible forever.

This is the idempotent replacement. ``needs_run`` is a cheap existence probe
(no version, no pragma) — True whenever there is real work, False when there
is none — so the Migration Center re-heals orphans every time one appears
instead of once per database, and it runs off the startup path like any other
registered task.

``run()`` does what the two retired methods did, verbatim in effect and in the
same order:

1. Channels whose ``provider_id`` no longer has a row in ``providers`` are
   pruned via ``ChannelRepository.prune_provider_content`` — which preserves
   ENGAGED channels (favorited / played / queued / rated — see
   ``ChannelProviderOpsMixin._engaged_channel_predicate``, the one predicate;
   never a second one) along with their dependents (metadata, EPG, seasons,
   episodes) and already removes the doomed channels' own ``content_tags``
   rows inline.
2. Any remaining ``content_tags`` rows pointing at a channel that no longer
   exists at all — belt-and-suspenders for any channel removed by a path that
   did not go through ``prune_provider_content``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.config import Config
    from metatv.core.database import Database


def _has_orphaned_channel(session: Session) -> bool:
    """True if a non-engaged channel's provider no longer exists.

    Engaged channels (favorited/played/queued/rated) are never pruned, so an
    orphaned-but-engaged channel is not "work" — it is meant to stay forever,
    surfaced via History/Favorites/Watch Queue. Reuses the one engagement
    predicate rather than a second copy of its OR conditions.
    """
    from metatv.core.database import ChannelDB, ProviderDB
    from metatv.core.repositories.channel import ChannelRepository

    engaged = ChannelRepository(session)._engaged_channel_predicate()
    provider_ids = session.query(ProviderDB.id)
    return session.query(ChannelDB.id).filter(
        ~ChannelDB.provider_id.in_(provider_ids)
    ).filter(~engaged).limit(1).first() is not None


def _has_orphaned_content_tag(session: Session) -> bool:
    """True if a ``content_tags`` row points at a channel that no longer exists."""
    from metatv.core.database import ChannelDB, ContentTagDB

    channel_ids = session.query(ChannelDB.id)
    return session.query(ContentTagDB.channel_id).filter(
        ~ContentTagDB.channel_id.in_(channel_ids)
    ).limit(1).first() is not None


class OrphanSweepTask:
    """Prune non-engaged channels (+ dependents) and orphaned content_tags rows."""

    id: str = "orphan_sweep"
    label: str = "Cleaning up content from removed sources"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """True when an orphaned channel or content_tags row currently exists.

        Two cheap ``LIMIT 1`` existence probes — no version, no pragma. This
        is what makes the sweep idempotent instead of one-shot: it is True
        again the moment a new orphan appears, not just the first time ever.
        """
        with self._db.session_scope(commit=False) as session:
            return (
                _has_orphaned_channel(session)
                or _has_orphaned_content_tag(session)
            )

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Prune orphaned channels, then orphaned content_tags rows.

        Runs on a worker thread. Two coarse steps, checked against
        *is_cancelled* between them; either can be skipped by a cancel
        request, which simply leaves ``needs_run`` True so the sweep resumes
        on the next pass.

        Args:
            progress_cb: ``(done, total)`` — ``total`` is 2 (one per step).
            is_cancelled: True when the manager has been asked to stop.
        """
        logger.info("OrphanSweepTask: starting")

        if is_cancelled():
            logger.info("OrphanSweepTask: cancelled before starting")
            return

        from metatv.core.repositories.channel import ChannelRepository

        with self._db.session_scope(commit=False) as session:
            rows = session.execute(text(
                "SELECT DISTINCT provider_id FROM channels "
                "WHERE provider_id NOT IN (SELECT id FROM providers)"
            )).fetchall()
        orphaned_provider_ids = [r[0] for r in rows if r[0]]

        if orphaned_provider_ids:
            logger.info(
                "OrphanSweepTask: pruning orphaned channels from {} removed "
                "source(s) (preserving engaged) …",
                len(orphaned_provider_ids),
            )
            with self._db.session_scope() as session:
                counts = ChannelRepository(session).prune_provider_content(
                    orphaned_provider_ids
                )
            logger.info(
                "OrphanSweepTask: channel cleanup complete: {} channels, "
                "{} metadata, {} EPG rows, {} seasons, {} episodes removed.",
                counts["channels"], counts["metadata"],
                counts["epg_by_channel"] + counts["epg_by_provider"],
                counts["seasons"], counts["episodes"],
            )
        else:
            logger.debug("OrphanSweepTask: no orphaned provider_ids found.")

        progress_cb(1, 2)

        if is_cancelled():
            logger.info("OrphanSweepTask: cancelled after channel cleanup")
            return

        with self._db.session_scope() as session:
            result = session.execute(text(
                "DELETE FROM content_tags WHERE NOT EXISTS "
                "(SELECT 1 FROM channels WHERE channels.id = content_tags.channel_id)"
            ))
            removed = result.rowcount or 0

        if removed > 0:
            logger.info(
                "OrphanSweepTask: removed {} orphaned content_tags row(s).",
                removed,
            )
        else:
            logger.debug("OrphanSweepTask: no orphaned content_tags rows found.")

        progress_cb(2, 2)
        logger.info("OrphanSweepTask: complete")

    def on_completed(self, config: "Config") -> None:
        """No-op: idempotency comes from re-probing live state, not a saved version."""
        logger.debug("OrphanSweepTask: pass complete — nothing to persist")
