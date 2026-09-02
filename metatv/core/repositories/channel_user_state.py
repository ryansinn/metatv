"""User state on a channel: favourites, watched, hidden, suppressed, categories.

Extracted from ``channel.py`` as a mixin — the pattern ingestion, enrichment,
provider-ops, stats, history and pruning already use. ``ChannelRepository``
composes it, so no caller learns a new import and none of them changed.

**What this mixin needs from the class it is mixed into**, stated here because a
mixin's dependencies are otherwise discovered by crashing:

* ``get_by_id`` — every writer re-reads the row it is about to change.
* ``_apply_adult_filter`` — ``get_favorites`` is a LIST, and a list of the
  user's own picks still honours the adult gate.

**What this is not.** These methods write one row's user state and nothing
more. Publishing the change to the views is the GUI's job, through
``gui/channel_state_bus.publish()`` — a repository that notified anything would
be the hand-listed refresh tail that rule exists to replace. Nothing here
imports or knows about the bus.

``count_watched_matching`` deliberately stayed behind: it counts through
``_apply_channel_filters``, which makes it part of the core query surface
wearing a user-state name.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from loguru import logger
from sqlalchemy import func, or_

from metatv.core.database import ChannelDB
from metatv.core.repositories.dtos import FavoriteDTO
from metatv.core.repositories.search_ranking import channel_text_search_predicate


class ChannelUserStateMixin:
    """Per-channel user state for ``ChannelRepository`` (uses self.session)."""


    def get_favorites(self, adult_mode: str = "all",
                      force_adult_provider_ids: Optional[List[str]] = None) -> List[ChannelDB]:
        """Get all favorite channels."""
        q = self.session.query(ChannelDB).filter_by(is_favorite=True, is_hidden=False)
        q = self._apply_adult_filter(q, adult_mode, force_adult_provider_ids)
        return q.order_by(ChannelDB.name).all()

    def get_favorites_dto(
        self,
        adult_mode: str = "all",
        force_adult_provider_ids: Optional[List[str]] = None,
        hidden_provider_ids: Optional[set] = None,
    ) -> "List[FavoriteDTO]":
        """Return favorite channels as plain DTOs — thread-safe, no live session required.

        get_favorites() intentionally keeps all favorited channels regardless of
        source state (engaged-content exception — CLAUDE.md). The ``available``
        field on each DTO annotates which entries are on a currently active source
        so the sidebar can dim them without altering the list ordering.

        Args:
            hidden_provider_ids: If supplied, channels whose ``provider_id`` is in
                this set are annotated with ``available=False``.
        """
        hidden: set = hidden_provider_ids or set()
        result = []
        for ch in self.get_favorites(adult_mode=adult_mode,
                                     force_adult_provider_ids=force_adult_provider_ids):
            pid = ch.provider_id
            result.append(FavoriteDTO(
                id=ch.id,
                name=ch.name,
                media_type=ch.media_type,
                last_played=ch.last_played,
                provider_id=pid,
                available=(not hidden or pid not in hidden),
                search_title=ch.detected_title or ch.name,
                detected_region=ch.detected_region or "",
                detected_quality=ch.detected_quality or "",
                detected_year=ch.detected_year or "",
                detected_prefix=ch.detected_prefix or "",
            ))
        return result

    def clear_unavailable_favorites(self, hidden_provider_ids: set) -> int:
        """Un-favorite channels whose provider is inactive/expired.

        Sets ``is_favorite=False`` (keeps the row; doesn't delete the channel)
        for every favorited, visible channel whose provider appears in
        ``hidden_provider_ids``.

        Args:
            hidden_provider_ids: Provider IDs to treat as unavailable.

        Returns:
            Number of channels un-favorited.
        """
        from datetime import datetime as _dt
        channels = (
            self.session.query(ChannelDB)
            .filter_by(is_favorite=True, is_hidden=False)
            .filter(ChannelDB.provider_id.in_(hidden_provider_ids))
            .all()
        )
        for ch in channels:
            ch.is_favorite = False
            ch.updated_at = _dt.now()
        return len(channels)
    
    def toggle_favorite(self, channel_id: str) -> bool:
        """Toggle favorite status and return new status"""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.is_favorite = not channel.is_favorite
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Channel {channel.name} favorite status: {channel.is_favorite}")
            return channel.is_favorite
        return False

    def mark_watched(self, channel_id: str, watched: bool = True) -> bool:
        """Mark a channel (movie/series) as watched/unwatched, setting all watch fields coherently.

        ChannelDB uses ``watch_completed`` as the "finished" flag (there is no
        ``is_watched`` column on channels — that is episode-only).  The field
        semantics parallel :meth:`EpisodeRepository.mark_watched` so the two
        paths never drift:

        watched=True  → watch_completed=True,  watch_percent=100,
                         last_played_via="manual"
                         (manual mark = deliberate → renders SOLID, not muted).
        watched=False → watch_completed=False, watch_percent=0,
                         watch_progress=0  (clear resume; item is truly unwatched).

        Returns True if the channel was found and updated, False if not found.
        """
        channel = self.get_by_id(channel_id)
        if channel is None:
            return False
        if watched:
            channel.watch_completed = True
            channel.watch_percent = 100
            channel.last_played_via = "manual"
        else:
            channel.watch_completed = False
            channel.watch_percent = 0
            channel.watch_progress = 0
        channel.updated_at = datetime.now()
        self.session.commit()
        logger.info(f"Marked channel {channel.name} as {'watched' if watched else 'unwatched'}")
        return True

    def mark_watched_bulk(self, channel_ids: "List[str]", watched: bool = True) -> int:
        """Mark multiple channels as watched/unwatched atomically.

        Same field semantics as :meth:`mark_watched`. Commits once for the batch.
        Returns the number of channels actually updated.
        """
        if not channel_ids:
            return 0
        updated = 0
        for channel_id in channel_ids:
            channel = self.get_by_id(channel_id)
            if channel is None:
                continue
            if watched:
                channel.watch_completed = True
                channel.watch_percent = 100
                channel.last_played_via = "manual"
            else:
                channel.watch_completed = False
                channel.watch_percent = 0
                channel.watch_progress = 0
            channel.updated_at = datetime.now()
            updated += 1
        if updated:
            self.session.commit()
        logger.info(f"Bulk marked {updated} channel(s) as {'watched' if watched else 'unwatched'}")
        return updated

    def record_watch_progress(
        self,
        channel_id: str,
        position_s: float,
        duration_s: float,
        threshold: float = 0.9,
        played_via: str = "manual",
    ) -> bool:
        """Record VOD watch progress: resume point + completion.

        Sets ``watch_progress`` (resume seconds), ``last_played``, and
        ``last_played_via``. When ``position_s / duration_s >= threshold`` the item
        is marked ``watch_completed`` and the resume point is cleared so a finished
        movie never resurfaces in "continue watching" at 99%. On a partial watch
        (below threshold), ``watch_completed`` is explicitly cleared so that
        re-watching a previously-finished title un-completes it — this restores the
        invariant ``watch_progress > 0 ⟺ not watch_completed``. ``play_count`` is
        owned by ``mark_played`` (at play start) — this method never touches it, so
        progress capture can't double-count a play.

        Returns True if this call marked the item complete.
        """
        channel = self.get_by_id(channel_id)
        if channel is None:
            return False
        completed = bool(duration_s and duration_s > 0 and (position_s / duration_s) >= threshold)
        pct = (
            min(100, max(0, round(position_s / duration_s * 100)))
            if duration_s and duration_s > 0
            else 0
        )
        channel.last_played = datetime.now()
        channel.last_played_via = played_via
        channel.watch_percent = 100 if completed else pct
        if completed:
            channel.watch_completed = True
            channel.watch_progress = 0
        else:
            channel.watch_completed = False  # re-watching a finished title un-completes it
            channel.watch_progress = max(0, int(position_s))
        channel.updated_at = datetime.now()
        self.session.commit()
        return completed





    def set_hidden(self, channel_id: str, hidden: bool) -> None:
        """Set channel hidden status (removes from all views)."""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.is_hidden = hidden
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Channel {channel.name} hidden={hidden}")

    def set_rec_suppressed(self, channel_id: str, suppressed: bool) -> None:
        """Suppress/unsuppress channel from recommendations only."""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.is_rec_suppressed = suppressed
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Channel {channel.name} rec_suppressed={suppressed}")

    def get_rec_suppressed(self) -> List[ChannelDB]:
        """Return all channels suppressed from recommendations, ordered by name."""
        return (
            self.session.query(ChannelDB)
            .filter(ChannelDB.is_rec_suppressed == True)  # noqa: E712
            .order_by(ChannelDB.name)
            .all()
        )

    # ── User category methods ──────────────────────────────────────────────────

    def get_all_user_categories(self) -> list[dict]:
        """Return all user-defined categories with channel counts and mood.

        Returns list of dicts sorted by channel count descending:
            [{"name": str, "count": int, "mood": str | None}, ...]
        """
        rows = (
            self.session.query(
                ChannelDB.user_category,
                ChannelDB.category_mood,
                func.count().label("cnt"),
            )
            .filter(ChannelDB.user_category.isnot(None))
            .group_by(ChannelDB.user_category, ChannelDB.category_mood)
            .order_by(func.count().desc())
            .all()
        )
        seen: dict[str, dict] = {}
        for name, mood, cnt in rows:
            if name not in seen:
                seen[name] = {"name": name, "count": cnt, "mood": mood}
            else:
                seen[name]["count"] += cnt
        return sorted(seen.values(), key=lambda x: -x["count"])

    def assign_user_category(
        self,
        channel_ids: list[str],
        category: str,
        mood: str | None = None,
    ) -> int:
        """Assign user_category (and optional mood) to a list of channels.

        Returns the number of channels updated.
        """
        if not channel_ids:
            return 0
        updated = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.id.in_(channel_ids))
            .update(
                {"user_category": category, "category_mood": mood,
                 "updated_at": datetime.now()},
                synchronize_session="fetch",
            )
        )
        self.session.commit()
        logger.info(
            f"Assigned {updated} channels to user category {category!r} (mood={mood!r})"
        )
        return updated

    def remove_user_category(self, channel_ids: list[str]) -> int:
        """Clear user_category and category_mood from a list of channels."""
        if not channel_ids:
            return 0
        updated = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.id.in_(channel_ids))
            .update(
                {"user_category": None, "category_mood": None,
                 "updated_at": datetime.now()},
                synchronize_session="fetch",
            )
        )
        self.session.commit()
        return updated

    def get_by_user_category(self, category: str) -> list[ChannelDB]:
        """Return all channels assigned to a user category, sorted by name."""
        return (
            self.session.query(ChannelDB)
            .filter(ChannelDB.user_category == category)
            .order_by(ChannelDB.name)
            .all()
        )

    def get_hidden_channels(
        self,
        excluded_user_categories: set[str] | None = None,
        search_query: str | None = None,
        provider_id=None,
        excluded_provider_ids: list[str] | None = None,
    ) -> list[ChannelDB]:
        """Return is_hidden=True channels and channels in excluded user categories."""
        if excluded_user_categories:
            q = self.session.query(ChannelDB).filter(
                or_(
                    ChannelDB.is_hidden == True,  # noqa: E712
                    ChannelDB.user_category.in_(excluded_user_categories),
                )
            )
        else:
            q = self.session.query(ChannelDB).filter(ChannelDB.is_hidden == True)  # noqa: E712

        if isinstance(provider_id, list):
            if provider_id:
                q = q.filter(ChannelDB.provider_id.in_(provider_id))
        elif provider_id:
            q = q.filter(ChannelDB.provider_id == provider_id)

        if excluded_provider_ids:
            q = q.filter(~ChannelDB.provider_id.in_(excluded_provider_ids))

        if search_query:
            q = q.filter(channel_text_search_predicate(search_query))

        return q.order_by(ChannelDB.name).all()
