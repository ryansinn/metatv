"""Provider lifecycle: deleting a source, and reconnecting what you engaged with.

Extracted from ``channel.py`` as a mixin — the pattern ingestion, enrichment,
stats, history and pruning already use. ``ChannelRepository`` composes it, so no
caller learns a new import and none of them changed.

docs/CHANNEL_REPOSITORY_SPLIT.md calls this "the one carrying the most live
risk", and isolating it so it can be read on its own is the point. Two rules
live here and neither is obvious from the code that uses them:

* **Stream ids are REUSED.** A channel's id is ``provider_id + "_" + stream_id``,
  so a new account on the same provider row recycles ids: the upsert replaces
  the name while ``is_favorite`` and the queue entry survive, and the flag now
  points at a different title. ``get_reconnect_candidates`` /
  ``reconnect_engaged_content`` are how a user gets their engagement back onto
  the right row.
* **Engagement is what must not be lost.** ``_engaged_channel_predicate`` is the
  one definition of "the user did something with this" — favourite, queued,
  rated, played. Widening it is how a delete starts eating history.

``prune_provider_content`` is deliberately NOT here: it moved to
``channel_pruning.py`` earlier, and it carries its own rule (foreign keys are
OFF, so every child table is pruned by hand — ``content_tags`` once leaked
1.24M rows).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set

from loguru import logger
from sqlalchemy import or_

from metatv.core.channel_name_utils import quality_tier_rank
from metatv.core.database import ChannelDB, ProviderDB, UserRatingDB, WatchQueueDB
from metatv.core.repositories.dtos import ReconnectCandidateDTO, ReconnectMatchDTO


class ChannelProviderOpsMixin:
    """Source deletion and engagement reconnection (uses self.session)."""

    
    def delete_by_provider(self, provider_id: str) -> int:
        """Delete all channels for a provider"""
        count = self.session.query(ChannelDB).filter_by(
            provider_id=provider_id
        ).delete()
        self.session.commit()
        logger.info(f"Deleted {count} channels for provider {provider_id}")
        return count

    def _engaged_channel_predicate(self):
        """Return the SQL predicate for an *engaged* channel (kept on provider delete).

        A channel is engaged — and therefore preserved even when its provider is
        removed — when it is favorited, has been played (``last_played`` set or
        ``play_count > 0``), or is currently queued.  This is the single
        "flag engaged-unavailable, don't delete" gate reused by every doomed-set
        delete below so the exclusion can never drift between statements.
        """
        return or_(
            ChannelDB.is_favorite == True,           # noqa: E712
            ChannelDB.last_played.isnot(None),
            ChannelDB.play_count > 0,
            ChannelDB.id.in_(self.session.query(WatchQueueDB.channel_id)),
        )

    def get_reconnect_candidates(
        self,
        hidden_provider_ids: Optional[Set[str]] = None,
    ) -> List["ReconnectCandidateDTO"]:
        """Return orphaned *engaged* channels + their proposed live replacement.

        An orphan is an engaged channel (:meth:`_engaged_channel_predicate` —
        favorited, played, or queued; the same gate ``prune_provider_content``
        uses to decide what a source delete KEEPS) whose provider is hidden
        (inactive/expired/orphaned — see
        ``ProviderRepository.get_hidden_provider_ids``).

        For each orphan the proposed match is the best-quality live channel
        (not on a hidden provider, not itself hidden) sharing the SAME stored
        ``content_key`` — ranked via
        ``channel_name_utils.quality_tier_rank(detected_quality)``, the single
        quality-tier ranking (never a second one).  A NULL ``content_key`` or
        no live sibling yields ``match=None`` — the row is still returned so
        the view can list it plainly as unmatched (mirror-not-cage). Never
        matches across different ``content_key``s and never falls back to a
        title heuristic — ``content_key`` is the one identity field.

        Batched (no N+1): one query for the orphans, one for every live
        candidate sharing any orphan's content_key, one for ratings, one for
        queue membership, one for provider names.

        Args:
            hidden_provider_ids: Hidden provider ids (inactive ∪ expired ∪
                orphaned) — see ``ProviderRepository.get_hidden_provider_ids``.
                An empty/None set returns ``[]`` immediately (nothing can be
                orphaned when nothing is hidden).

        Returns:
            List of :class:`ReconnectCandidateDTO`, ordered by orphan name.
        """
        hidden = set(hidden_provider_ids or ())
        if not hidden:
            return []

        engaged = self._engaged_channel_predicate()
        orphans = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.provider_id.in_(hidden))
            .filter(engaged)
            .order_by(ChannelDB.name)
            .all()
        )
        if not orphans:
            return []

        orphan_ids = {o.id for o in orphans}
        provider_names = {
            p.id: p.name for p in self.session.query(ProviderDB.id, ProviderDB.name).all()
        }

        # Batch-fetch every live (non-hidden-provider, non-hidden-flag) channel
        # sharing a content_key with ANY orphan — one query, never N+1.
        keys = {o.content_key for o in orphans if o.content_key}
        candidates_by_key: Dict[str, List[ChannelDB]] = {}
        if keys:
            live_rows = (
                self.session.query(ChannelDB)
                .filter(ChannelDB.content_key.in_(keys))
                .filter(~ChannelDB.provider_id.in_(hidden))
                .filter(ChannelDB.is_hidden.is_(False))
                .all()
            )
            for row in live_rows:
                candidates_by_key.setdefault(row.content_key, []).append(row)

        rating_map = {
            r.channel_id: r.rating
            for r in (
                self.session.query(UserRatingDB)
                .filter(UserRatingDB.channel_id.in_(orphan_ids))
                .all()
            )
        }
        queued_ids = {
            row[0]
            for row in (
                self.session.query(WatchQueueDB.channel_id)
                .filter(WatchQueueDB.channel_id.in_(orphan_ids))
                .distinct()
                .all()
            )
        }

        result: List[ReconnectCandidateDTO] = []
        for orphan in orphans:
            match_dto: Optional[ReconnectMatchDTO] = None
            if orphan.content_key:
                live_candidates = [
                    c for c in candidates_by_key.get(orphan.content_key, ())
                    if c.id != orphan.id
                ]
                if live_candidates:
                    # Best quality tier wins; tie-break on id for determinism.
                    best = max(
                        live_candidates,
                        key=lambda c: (quality_tier_rank(c.detected_quality), c.id),
                    )
                    match_dto = ReconnectMatchDTO(
                        channel_id=best.id,
                        name=best.name,
                        detected_title=best.detected_title,
                        detected_quality=best.detected_quality,
                        provider_id=best.provider_id,
                        provider_name=provider_names.get(best.provider_id, best.provider_id),
                    )
            result.append(ReconnectCandidateDTO(
                orphan_id=orphan.id,
                orphan_name=orphan.name,
                detected_title=orphan.detected_title,
                detected_year=orphan.detected_year,
                media_type=orphan.media_type,
                provider_id=orphan.provider_id,
                provider_name=provider_names.get(orphan.provider_id, "Removed source"),
                content_key=orphan.content_key,
                is_favorite=bool(orphan.is_favorite),
                last_played=orphan.last_played,
                play_count=int(orphan.play_count or 0),
                watch_progress=int(orphan.watch_progress or 0),
                watch_completed=bool(orphan.watch_completed),
                watch_percent=int(orphan.watch_percent or 0),
                user_rating=rating_map.get(orphan.id, 0),
                in_queue=orphan.id in queued_ids,
                match=match_dto,
            ))
        return result

    def reconnect_engaged_content(self, orphan_id: str, live_channel_id: str) -> None:
        """Merge engagement from an orphaned channel onto its live replacement.

        The live channel may already carry its OWN independent engagement (the
        user sampled both copies before the orphan's source went away) — this
        is a MERGE that can only ever INCREASE engagement, never move it
        backwards, so a reconnect can never erase engagement the live channel
        already has (user ratings/favorites/history are sacrosanct):

        - ``is_favorite``: ``live.is_favorite OR orphan.is_favorite``.
        - ``play_count``: **summed** — both were real plays of the same content.
        - ``last_played`` (+ its paired ``last_played_via``): the LATER of the
          two, taken together as one pair (None always loses to a real
          timestamp).
        - Resume position — ``watch_progress``/``watch_percent``/
          ``watch_completed`` are ONE atomic group, never mixed field-by-field
          across the two rows (pairing one row's seconds with the other's
          percent would corrupt the resume point). If either row is
          ``watch_completed``, the result is completed (using that row's own
          group). Otherwise the WHOLE group is taken from whichever row has
          the higher ``watch_percent``.
        - Rating (``UserRatingDB``, 1:1 keyed by ``channel_id``): an explicit
          rating already on the live channel is NEVER overwritten by an
          implicit reconnect — the orphan's rating only moves over when the
          live channel has none.

        The orphan's own fields are cleared afterwards (favorites/history are
        never left double-booked). Caller MUST invoke this inside
        ``Database.session_scope()`` so the whole merge commits or rolls back
        as ONE transaction — a half-moved engagement is worse than none
        (CLAUDE.md).

        Refuses to move across ``content_key``s (including when either side
        has no stored key) — ``content_key`` is the one identity field, never
        a title heuristic; this is a defense-in-depth check even though
        :meth:`get_reconnect_candidates` never proposes a mismatched pair.

        Watch-queue membership: every ``WatchQueueDB`` row referencing
        ``orphan_id`` (both channel-grain and episode-grain — an episode-grain
        row still carries the parent series' ``channel_id``) is re-pointed at
        ``live_channel_id``. A channel-grain row (``episode_id IS NULL``) is
        dropped instead of moved when the live channel already has one — so
        reconnecting never duplicates a queue row.

        Args:
            orphan_id: ``ChannelDB.id`` of the orphaned engaged channel.
            live_channel_id: ``ChannelDB.id`` of the live replacement.

        Raises:
            ValueError: orphan/live channel not found, the same row, or a
                ``content_key`` mismatch.
        """
        if orphan_id == live_channel_id:
            raise ValueError("Reconnect refused: orphan and live channel are the same row")

        orphan = self.session.get(ChannelDB, orphan_id)
        live = self.session.get(ChannelDB, live_channel_id)
        if orphan is None:
            raise ValueError(f"Reconnect failed: orphan channel not found ({orphan_id!r})")
        if live is None:
            raise ValueError(f"Reconnect failed: live channel not found ({live_channel_id!r})")
        if not orphan.content_key or orphan.content_key != live.content_key:
            raise ValueError(
                "Reconnect refused: content_key mismatch "
                f"(orphan={orphan.content_key!r}, live={live.content_key!r})"
            )

        now = datetime.now()

        # Snapshot every relevant scalar BEFORE any mutation — the merge below
        # reads both sides together, so nothing may be overwritten mid-read.
        live_snap = {
            "is_favorite": bool(live.is_favorite),
            "last_played": live.last_played,
            "last_played_via": live.last_played_via,
            "play_count": int(live.play_count or 0),
            "watch_progress": int(live.watch_progress or 0),
            "watch_percent": int(live.watch_percent or 0),
            "watch_completed": bool(live.watch_completed),
        }
        orphan_snap = {
            "is_favorite": bool(orphan.is_favorite),
            "last_played": orphan.last_played,
            "last_played_via": orphan.last_played_via,
            "play_count": int(orphan.play_count or 0),
            "watch_progress": int(orphan.watch_progress or 0),
            "watch_percent": int(orphan.watch_percent or 0),
            "watch_completed": bool(orphan.watch_completed),
        }

        merged_is_favorite = live_snap["is_favorite"] or orphan_snap["is_favorite"]
        merged_play_count = live_snap["play_count"] + orphan_snap["play_count"]

        # last_played + last_played_via move together — None loses to any real
        # timestamp; a tie (or both None) keeps the live channel's own pair.
        if orphan_snap["last_played"] and (
            not live_snap["last_played"] or orphan_snap["last_played"] > live_snap["last_played"]
        ):
            merged_last_played = orphan_snap["last_played"]
            merged_last_played_via = orphan_snap["last_played_via"]
        else:
            merged_last_played = live_snap["last_played"]
            merged_last_played_via = live_snap["last_played_via"]

        # Resume-position group — never split across rows (see docstring).
        if live_snap["watch_completed"] or orphan_snap["watch_completed"]:
            completed_source = max(
                (s for s in (live_snap, orphan_snap) if s["watch_completed"]),
                key=lambda s: s["watch_percent"],
            )
            merged_watch_progress = completed_source["watch_progress"]
            merged_watch_percent = completed_source["watch_percent"]
            merged_watch_completed = True
        else:
            resume_source = (
                live_snap if live_snap["watch_percent"] >= orphan_snap["watch_percent"]
                else orphan_snap
            )
            merged_watch_progress = resume_source["watch_progress"]
            merged_watch_percent = resume_source["watch_percent"]
            merged_watch_completed = False

        live.is_favorite = merged_is_favorite
        live.play_count = merged_play_count
        live.last_played = merged_last_played
        live.last_played_via = merged_last_played_via
        live.watch_progress = merged_watch_progress
        live.watch_percent = merged_watch_percent
        live.watch_completed = merged_watch_completed
        live.updated_at = now

        orphan.is_favorite = False
        orphan.last_played = None
        orphan.play_count = 0
        orphan.watch_progress = 0
        orphan.watch_completed = False
        orphan.watch_percent = 0
        orphan.last_played_via = None
        orphan.updated_at = now

        # Rating — UserRatingDB is 1:1 keyed by channel_id (the PK). An
        # explicit rating already on the live channel is kept as-is; the
        # orphan's rating only moves over when the live channel has none.
        orphan_rating_row = self.session.get(UserRatingDB, orphan_id)
        if orphan_rating_row is not None:
            live_rating_row = self.session.get(UserRatingDB, live_channel_id)
            if live_rating_row is None:
                self.session.merge(UserRatingDB(
                    channel_id=live_channel_id,
                    rating=orphan_rating_row.rating,
                    rated_at=orphan_rating_row.rated_at,
                ))
            self.session.delete(orphan_rating_row)

        # Watch-queue membership — re-point every row referencing the orphan.
        queue_rows = (
            self.session.query(WatchQueueDB)
            .filter(WatchQueueDB.channel_id == orphan_id)
            .all()
        )
        if queue_rows:
            live_has_channel_grain = (
                self.session.query(WatchQueueDB)
                .filter_by(channel_id=live_channel_id, episode_id=None)
                .first() is not None
            )
            for row in queue_rows:
                if row.episode_id is None and live_has_channel_grain:
                    # Live channel already has a channel-grain entry — drop the
                    # orphan's redundant one rather than duplicating it.
                    self.session.delete(row)
                    continue
                row.channel_id = live_channel_id
                row.channel_name = live.name
                row.media_type = live.media_type or row.media_type
                row.source_id = live.source_id
                if row.episode_id is None:
                    live_has_channel_grain = True

        self.session.flush()
        logger.info(f"Reconnected engaged content: {orphan_id!r} -> {live_channel_id!r}")
