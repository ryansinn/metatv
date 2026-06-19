"""EPG repository — queries against the epg_programmes table."""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session
from loguru import logger

from metatv.core.database import EpgProgramDB, ChannelDB
from metatv.core.epg_utils import now_utc as _now_utc, local_day_window as _local_day_window
from metatv.core.epg_utils import _local_tz  # re-exported so test patches still work


class EpgRepository:
    """Repository for EPG programme data access."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Current & upcoming
    # ------------------------------------------------------------------

    def get_current_programs(
        self,
        provider_ids: list[str],
        hide_filler: bool = True,
        filler_patterns: list[str] | None = None,
        dismissed_channel_ids: set[str] | None = None,
        lang_code: str = "",
        hidden_titles: list[str] | None = None,
        hidden_channel_ids: list[str] | None = None,
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
    ) -> list[EpgProgramDB]:
        """Programmes airing right now across the given providers.

        Only returns entries that have a matched channel (channel_db_id IS NOT NULL)
        so callers know they are playable.

        Args:
            provider_ids: Feed-provider IDs whose XMLTV supplies the programmes.
            excluded_channel_provider_ids: When truthy, programmes whose matched
                ChannelDB row belongs to one of these provider IDs are excluded.
                This is the channel-side scoping complement to the feed-side
                ``provider_ids`` filter — it prevents disabled-source channels
                from appearing when another source's EPG feed happens to match
                them cross-provider.  ``None`` / empty preserves existing behaviour.
        """
        now = _now_utc()
        query = self.session.query(EpgProgramDB).filter(
            EpgProgramDB.provider_id.in_(provider_ids),
            EpgProgramDB.start_time <= now,
            EpgProgramDB.stop_time  >  now,
            EpgProgramDB.channel_db_id.isnot(None),
        )

        if excluded_channel_provider_ids:
            query = (
                query
                .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
            )

        if hide_filler and filler_patterns:
            for pattern in filler_patterns:
                query = query.filter(~EpgProgramDB.title.ilike(f"%{pattern}%"))

        if dismissed_channel_ids:
            query = query.filter(
                ~EpgProgramDB.channel_db_id.in_(dismissed_channel_ids)
            )

        if lang_code:
            query = query.filter(EpgProgramDB.channel_epg_id.ilike(f"%.{lang_code}"))

        if hidden_titles:
            query = query.filter(~EpgProgramDB.title.in_(hidden_titles))

        if hidden_channel_ids:
            query = query.filter(~EpgProgramDB.channel_db_id.in_(hidden_channel_ids))

        return query.order_by(EpgProgramDB.start_time).all()

    def get_upcoming_for_watchlist(
        self,
        patterns: list[str],
        hours_ahead: int = 48,
        provider_ids: list[str] | None = None,
        lang_code: str = "",
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
    ) -> dict[str, list[EpgProgramDB]]:
        """Upcoming programmes matching each watchlist pattern.

        Args:
            patterns: List of keyword patterns to match against title.
            hours_ahead: How many hours into the future to look.
            provider_ids: Optional feed-provider filter.
            excluded_channel_provider_ids: When truthy, excludes programmes
                whose matched ChannelDB row belongs to one of these provider IDs.

        Returns:
            Dict mapping each pattern to a list of upcoming EpgProgramDB rows,
            ordered by start_time.
        """
        now = _now_utc()
        cutoff = now + timedelta(hours=hours_ahead)
        result: dict[str, list[EpgProgramDB]] = {}

        for pattern in patterns:
            query = self.session.query(EpgProgramDB).filter(
                EpgProgramDB.title.ilike(f"%{pattern}%"),
                EpgProgramDB.start_time >= now,
                EpgProgramDB.start_time <= cutoff,
                EpgProgramDB.channel_db_id.isnot(None),
            )
            if provider_ids:
                query = query.filter(EpgProgramDB.provider_id.in_(provider_ids))
            if excluded_channel_provider_ids:
                query = (
                    query
                    .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                    .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
                )
            if lang_code:
                query = query.filter(EpgProgramDB.channel_epg_id.ilike(f"%.{lang_code}"))
            result[pattern] = query.order_by(EpgProgramDB.start_time).limit(20).all()

        return result

    def get_live_for_watchlist(
        self,
        patterns: list[str],
        provider_ids: list[str] | None = None,
        lang_code: str = "",
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
    ) -> dict[str, list[EpgProgramDB]]:
        """Programmes matching watchlist patterns that are airing RIGHT NOW."""
        now = _now_utc()
        result: dict[str, list[EpgProgramDB]] = {}

        for pattern in patterns:
            query = self.session.query(EpgProgramDB).filter(
                EpgProgramDB.title.ilike(f"%{pattern}%"),
                EpgProgramDB.start_time <= now,
                EpgProgramDB.stop_time  >  now,
                EpgProgramDB.channel_db_id.isnot(None),
            )
            if provider_ids:
                query = query.filter(EpgProgramDB.provider_id.in_(provider_ids))
            if excluded_channel_provider_ids:
                query = (
                    query
                    .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                    .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
                )
            if lang_code:
                query = query.filter(EpgProgramDB.channel_epg_id.ilike(f"%.{lang_code}"))
            result[pattern] = query.all()

        return result

    # ------------------------------------------------------------------
    # Browse / schedule
    # ------------------------------------------------------------------

    def get_schedule(
        self,
        target_date: date,
        provider_ids: list[str],
        search_query: str = "",
        hide_filler: bool = True,
        filler_patterns: list[str] | None = None,
        time_slot: str = "all",
        lang_code: str = "",
    ) -> list[EpgProgramDB]:
        """All programmes on a given calendar date.

        Args:
            target_date: The date to fetch.
            provider_ids: Providers to include.
            search_query: Optional keyword filter on title + description.
            hide_filler: Skip filler titles.
            filler_patterns: Title substrings considered filler.
            time_slot: "all" | "morning" | "afternoon" | "primetime" | "latenight"

        Returns:
            Programmes ordered by start_time.
        """
        # Convert the LOCAL calendar date chosen by the user into a UTC-naive window.
        # target_date is a local date; EPG rows are stored as UTC-naive datetimes.
        day_start, day_end = _local_day_window(target_date, tz=_local_tz())

        query = self.session.query(EpgProgramDB).filter(
            EpgProgramDB.provider_id.in_(provider_ids),
            EpgProgramDB.start_time >= day_start,
            EpgProgramDB.start_time <  day_end,
            EpgProgramDB.channel_db_id.isnot(None),  # playable channels only
        )

        # Time slot filter. day_start is anchored to local-midnight-in-UTC (see above),
        # so these hour offsets yield exact local-time windows.
        slot_ranges = {
            "morning":   (6,  12),
            "afternoon": (12, 18),
            "primetime": (18, 23),
            "latenight": (23, 27),  # wraps into next day
        }
        if time_slot in slot_ranges:
            h_start, h_end = slot_ranges[time_slot]
            slot_start = day_start + timedelta(hours=h_start)
            slot_end   = day_start + timedelta(hours=h_end)
            query = query.filter(
                EpgProgramDB.start_time >= slot_start,
                EpgProgramDB.start_time <  slot_end,
            )

        if search_query:
            like = f"%{search_query}%"
            query = query.filter(
                EpgProgramDB.title.ilike(like) | EpgProgramDB.description.ilike(like)
            )

        if hide_filler and filler_patterns:
            for pattern in filler_patterns:
                query = query.filter(~EpgProgramDB.title.ilike(f"%{pattern}%"))

        if lang_code:
            query = query.filter(EpgProgramDB.channel_epg_id.ilike(f"%.{lang_code}"))

        return query.order_by(EpgProgramDB.start_time).all()

    def search_programs(
        self,
        query_str: str,
        provider_ids: list[str],
        hours_ahead: int = 168,
        lang_code: str = "",
    ) -> list[EpgProgramDB]:
        """Full-text search on title + description for upcoming programmes."""
        now = _now_utc()
        cutoff = now + timedelta(hours=hours_ahead)
        like = f"%{query_str}%"
        query = (
            self.session.query(EpgProgramDB)
            .filter(
                EpgProgramDB.provider_id.in_(provider_ids),
                EpgProgramDB.start_time >= now,
                EpgProgramDB.start_time <= cutoff,
                EpgProgramDB.title.ilike(like) | EpgProgramDB.description.ilike(like),
            )
        )
        if lang_code:
            query = query.filter(EpgProgramDB.channel_epg_id.ilike(f"%.{lang_code}"))
        return query.order_by(EpgProgramDB.start_time).limit(200).all()

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def get_recommendations(
        self,
        patterns: list[str],
        dismissed_ids: set[str],
        provider_ids: list[str],
        limit: int = 10,
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
    ) -> list[tuple[str, str, int]]:
        """Channels with the most upcoming programmes matching watchlist patterns.

        Excludes channels already in dismissed_ids and channels with no
        channel_db_id (unplayable).

        Args:
            excluded_channel_provider_ids: When truthy, excludes programmes
                whose matched ChannelDB row belongs to one of these provider IDs.

        Returns:
            List of (channel_db_id, channel_name, match_count) sorted by
            match_count descending.
        """
        if not patterns:
            return []

        now = _now_utc()
        cutoff = now + timedelta(hours=168)

        from sqlalchemy import or_
        pattern_conditions = [
            EpgProgramDB.title.ilike(f"%{p}%") for p in patterns
        ]

        query = (
            self.session.query(
                EpgProgramDB.channel_db_id,
                func.count(EpgProgramDB.id).label("cnt"),
            )
            .filter(
                EpgProgramDB.provider_id.in_(provider_ids),
                EpgProgramDB.channel_db_id.isnot(None),
                EpgProgramDB.start_time >= now,
                EpgProgramDB.start_time <= cutoff,
                or_(*pattern_conditions),
            )
        )

        if excluded_channel_provider_ids:
            query = (
                query
                .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
            )

        rows = (
            query
            .group_by(EpgProgramDB.channel_db_id)
            .order_by(func.count(EpgProgramDB.id).desc())
            .limit(limit * 3)  # oversample to allow dismissed filtering
            .all()
        )

        results: list[tuple[str, str, int]] = []
        seen_ids: set[str] = set(dismissed_ids)

        for channel_db_id, cnt in rows:
            if channel_db_id in seen_ids:
                continue
            seen_ids.add(channel_db_id)

            # Look up channel name
            channel = self.session.query(ChannelDB).filter_by(id=channel_db_id).first()
            name = channel.name if channel else channel_db_id
            results.append((channel_db_id, name, cnt))

            if len(results) >= limit:
                break

        return results

    def get_matching_programs(
        self,
        channel_db_id: str,
        patterns: list[str],
        provider_ids: list[str],
        limit: int = 10,
    ) -> list[tuple[str, datetime]]:
        """Upcoming programmes on a specific channel whose titles match any watchlist pattern.

        Mirrors ``get_recommendations``'s time window (now → +168 h) and provider filter.
        Returns plain ``(title, start_time)`` tuples so callers are safe after the session
        closes — never ORM objects.

        Args:
            channel_db_id: The channel whose schedule to search.
            patterns: Watchlist keyword patterns; at least one must match ``title ILIKE``.
            provider_ids: EPG-active provider IDs to restrict the search to.
            limit: Maximum number of rows returned.

        Returns:
            List of ``(title, start_time)`` tuples ordered by ``start_time`` ascending.
        """
        if not patterns or not provider_ids:
            return []

        from sqlalchemy import or_
        now = _now_utc()
        cutoff = now + timedelta(hours=168)

        pattern_conditions = [
            EpgProgramDB.title.ilike(f"%{p}%") for p in patterns
        ]

        rows = (
            self.session.query(EpgProgramDB.title, EpgProgramDB.start_time)
            .filter(
                EpgProgramDB.provider_id.in_(provider_ids),
                EpgProgramDB.channel_db_id == channel_db_id,
                EpgProgramDB.start_time >= now,
                EpgProgramDB.start_time <= cutoff,
                or_(*pattern_conditions),
            )
            .order_by(EpgProgramDB.start_time)
            .limit(limit)
            .all()
        )

        # Return plain tuples — never expose ORM objects across the session boundary.
        return [(title, start_time) for title, start_time in rows]

    # ------------------------------------------------------------------
    # Per-channel schedule (for details pane agenda)
    # ------------------------------------------------------------------

    def get_now_for_channel(self, channel_db_id: str) -> EpgProgramDB | None:
        """Return the programme currently airing on a specific channel, or None."""
        now = _now_utc()
        return (
            self.session.query(EpgProgramDB)
            .filter(
                EpgProgramDB.channel_db_id == channel_db_id,
                EpgProgramDB.start_time <= now,
                EpgProgramDB.stop_time > now,
            )
            .order_by(EpgProgramDB.start_time.desc())  # most recently started wins if overlap
            .first()
        )

    def get_schedule_for_channel(
        self,
        channel_db_id: str,
        from_time: datetime | None = None,
        hours_ahead: int = 8,
    ) -> list[EpgProgramDB]:
        """Return upcoming programmes on a specific channel ordered by start_time."""
        start = from_time if from_time is not None else _now_utc()
        cutoff = start + timedelta(hours=hours_ahead)
        return (
            self.session.query(EpgProgramDB)
            .filter(
                EpgProgramDB.channel_db_id == channel_db_id,
                EpgProgramDB.stop_time > start,
                EpgProgramDB.start_time < cutoff,
            )
            .order_by(EpgProgramDB.start_time)
            .limit(12)
            .all()
        )

    # ------------------------------------------------------------------
    # Meta / maintenance
    # ------------------------------------------------------------------

    def get_data_end(self, provider_id: str) -> datetime | None:
        """Return the latest stop_time stored for this provider."""
        row = (
            self.session.query(func.max(EpgProgramDB.stop_time))
            .filter_by(provider_id=provider_id)
            .scalar()
        )
        return row

    def count_programs(self, provider_id: str) -> int:
        """Total programme rows for a provider."""
        return (
            self.session.query(EpgProgramDB)
            .filter_by(provider_id=provider_id)
            .count()
        )

    def count_by_providers(self, provider_ids: list[str]) -> int:
        """Total programme rows across multiple providers."""
        if not provider_ids:
            return 0
        return (
            self.session.query(EpgProgramDB)
            .filter(EpgProgramDB.provider_id.in_(provider_ids))
            .count()
        )

    def clear_provider_data(self, provider_id: str) -> int:
        """Delete all EPG rows for a provider. Returns deleted count."""
        count = (
            self.session.query(EpgProgramDB)
            .filter_by(provider_id=provider_id)
            .delete()
        )
        self.session.commit()
        logger.info(f"EPG: cleared {count} rows for provider {provider_id}")
        return count

    def get_programs_starting_soon(
        self,
        within_minutes: int,
        provider_ids: list[str],
    ) -> list[EpgProgramDB]:
        """Programmes starting within the next N minutes (for notifications)."""
        now = _now_utc()
        cutoff = now + timedelta(minutes=within_minutes)
        return (
            self.session.query(EpgProgramDB)
            .filter(
                EpgProgramDB.provider_id.in_(provider_ids),
                EpgProgramDB.start_time > now,
                EpgProgramDB.start_time <= cutoff,
                EpgProgramDB.channel_db_id.isnot(None),
            )
            .all()
        )

    def has_unmatched_epg(self, provider_id: str) -> bool:
        """Return True iff the provider has EPG rows but none are matched to a channel.

        Uses two cheap existence checks on indexed columns — no full-row loading.

        "Unmatched" means the guide was fetched (rows exist) but ``_build_match_map``
        produced no links (all ``channel_db_id`` values are NULL). This happens when
        the fetch ran before the channel list was loaded.  A provider with *no rows at
        all* returns False — that is a "never fetched" state, not an unmatched state;
        ``needs_refresh`` / the never-fetched branch already handles it.
        """
        # Any row at all?
        has_any = (
            self.session.query(EpgProgramDB.id)
            .filter(EpgProgramDB.provider_id == provider_id)
            .first()
        )
        if not has_any:
            return False  # no rows → not an unmatched guide
        # Any matched row?
        has_matched = (
            self.session.query(EpgProgramDB.id)
            .filter(
                EpgProgramDB.provider_id == provider_id,
                EpgProgramDB.channel_db_id.isnot(None),
            )
            .first()
        )
        return has_matched is None  # rows exist but none are matched

    def get_channel_name_for_epg_id(self, channel_epg_id: str) -> str | None:
        """Resolve an epg_channel_id to a human-readable channel name."""
        prog = (
            self.session.query(EpgProgramDB)
            .filter_by(channel_epg_id=channel_epg_id)
            .first()
        )
        if prog and prog.channel_db_id:
            ch = self.session.query(ChannelDB).filter_by(id=prog.channel_db_id).first()
            if ch:
                return ch.name
        return None
