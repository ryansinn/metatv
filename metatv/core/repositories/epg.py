"""EPG repository — queries against the epg_programmes table."""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session
from loguru import logger

from metatv.core.database import EpgProgramDB, ChannelDB
from metatv.core.epg_utils import now_utc as _now_utc, local_day_window as _local_day_window
from metatv.core.epg_utils import contiguous_guide_end as _contiguous_guide_end
from metatv.core.epg_utils import _local_tz  # re-exported so test patches still work


# Browse time-slot windows — SINGLE SOURCE OF TRUTH shared by ``get_schedule`` (the
# window math) and the Browse-tab dropdown (its labels). Each tuple is
# ``(key, label, hour_start, hour_end)`` where the hours are offsets from LOCAL
# midnight; an offset >= 24 spills into the NEXT calendar day. Late Night therefore
# spans 11 PM → 5 AM (23 → 29), Morning 5 AM → noon (5 → 12) — contiguous and
# covering the previously-missing 3–5 AM window.
SCHEDULE_TIME_SLOTS: list[tuple[str, str, int, int]] = [
    ("all",       "All Day",         0,  24),
    ("morning",   "Morning 5–12",    5,  12),
    ("afternoon", "Afternoon 12–6",  12, 18),
    ("primetime", "Prime Time 6–11", 18, 23),
    ("latenight", "Late Night 11–5", 23, 29),
]

# key → (hour_start, hour_end) for the real slots ("all" is excluded so it falls
# back to the full-day window in ``get_schedule``).
SCHEDULE_SLOT_RANGES: dict[str, tuple[int, int]] = {
    key: (h_start, h_end)
    for key, _label, h_start, h_end in SCHEDULE_TIME_SLOTS
    if key != "all"
}


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
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
    ) -> list[EpgProgramDB]:
        """All programmes on a given calendar date.

        Args:
            target_date: The date to fetch.
            provider_ids: Providers to include.
            search_query: Optional keyword filter on title + description.
            hide_filler: Skip filler titles.
            filler_patterns: Title substrings considered filler.
            time_slot: "all" | "morning" | "afternoon" | "primetime" | "latenight"
            excluded_channel_provider_ids: When truthy, programmes whose matched
                ChannelDB row belongs to one of these provider IDs are excluded —
                the channel-side scoping complement to the feed-side ``provider_ids``
                filter (mirrors ``get_current_programs``). Pass
                ``ProviderRepository.get_hidden_provider_ids()`` so Browse honours
                the global Exclusions / inactive-source scoping.

        Returns:
            Programmes ordered by start_time.
        """
        # Convert the LOCAL calendar date chosen by the user into a UTC-naive window.
        # target_date is a local date; EPG rows are stored as UTC-naive datetimes.
        day_start, day_end = _local_day_window(target_date, tz=_local_tz())

        # Resolve the query window. A specific time slot REPLACES the day window with
        # its own [slot_start, slot_end) bounds (hour offsets from local midnight,
        # i.e. day_start). Late Night ends at hour 29 (= 5 AM the NEXT calendar day),
        # so the slot window must extend past day_end — applying the day cap here is
        # the bug that clipped Late Night to 11 PM–midnight and made it look empty
        # (and made date changes appear to "not reload" while on that slot).
        slot_ranges = SCHEDULE_SLOT_RANGES
        if time_slot in slot_ranges:
            h_start, h_end = slot_ranges[time_slot]
            window_start = day_start + timedelta(hours=h_start)
            window_end   = day_start + timedelta(hours=h_end)
        else:
            window_start, window_end = day_start, day_end

        query = self.session.query(EpgProgramDB).filter(
            EpgProgramDB.provider_id.in_(provider_ids),
            EpgProgramDB.start_time >= window_start,
            EpgProgramDB.start_time <  window_end,
            EpgProgramDB.channel_db_id.isnot(None),  # playable channels only
        )

        if excluded_channel_provider_ids:
            query = (
                query
                .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
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

    def get_schedule_forward(
        self,
        provider_ids: list[str],
        anchor: datetime | None = None,
        search_query: str = "",
        hide_filler: bool = True,
        filler_patterns: list[str] | None = None,
        lang_code: str = "",
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
        after: tuple[datetime, int] | None = None,
        limit: int = 200,
        max_age: timedelta | None = None,
        _now: datetime | None = None,
    ) -> list[EpgProgramDB]:
        """Forward-looking, chronological, keyset-paginated schedule.

        The Browse-tab successor to :meth:`get_schedule`'s calendar-day ×
        bounded-time-slot model. Returns programmes whose ``start_time`` is at or
        after the *effective anchor* — ``max(now, anchor)`` so the PAST is never
        shown — ordered ascending by ``(start_time, id)`` and capped at ``limit``.

        Pagination is keyset (cursor): pass the last ``(start_time, id)`` from the
        previous page as ``after`` to fetch the next page. Keyset (vs OFFSET) keeps
        each page O(log n) on the 100k+/day ``epg_programmes`` table.

        Scoping/filter parity with :meth:`get_schedule` — ``provider_ids``,
        ``excluded_channel_provider_ids`` (channel-side hidden-provider scoping),
        ``search_query``, ``hide_filler``/``filler_patterns``, ``lang_code``, and
        ``channel_db_id IS NOT NULL`` (playable channels only).

        Args:
            provider_ids: Feed-provider IDs whose XMLTV supplies the programmes.
            anchor: Requested start instant (UTC-naive). Floored to ``now`` so a
                past anchor never surfaces already-aired programmes. ``None`` = now.
            search_query: Optional keyword filter on title + description.
            hide_filler: Skip filler titles.
            filler_patterns: Title substrings considered filler.
            lang_code: Restrict to channels whose epg id ends ``.<lang_code>``.
            excluded_channel_provider_ids: Channel-side scoping — drop programmes
                whose matched ChannelDB row belongs to a hidden provider (mirrors
                :meth:`get_schedule`; pass ``get_hidden_provider_ids()``).
            after: Keyset cursor — the ``(start_time, id)`` of the last row from
                the previous page. ``None`` starts at the first page.
            limit: Max rows returned (one page).
            max_age: Left-bound guard ``start_time >= now - max_age``. In Phase-1
                forward-only browsing this is dominated by the ``>= now`` floor, so
                it is effectively inert; it is wired so the Phase-2 timeline
                scrubber can reuse this method with a real left bound.
            _now: Reference "now" (UTC-naive); defaults to :func:`now_utc`.

        Returns:
            Up to ``limit`` programmes ordered ascending by ``(start_time, id)``.
        """
        now = _now or _now_utc()
        # Never the past: a requested anchor only moves the window FORWARD.
        effective_anchor = anchor if (anchor is not None and anchor > now) else now

        query = self.session.query(EpgProgramDB).filter(
            EpgProgramDB.provider_id.in_(provider_ids),
            EpgProgramDB.start_time >= effective_anchor,
            EpgProgramDB.channel_db_id.isnot(None),  # playable channels only
        )

        # Max-age floor (Phase-2 left bound). Dominated by the >= effective_anchor
        # filter in Phase-1 forward mode, but wired so it is honoured everywhere.
        if max_age is not None:
            query = query.filter(EpgProgramDB.start_time >= now - max_age)

        if excluded_channel_provider_ids:
            query = (
                query
                .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
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

        if after is not None:
            from sqlalchemy import and_, or_
            after_start, after_id = after
            # Keyset: rows strictly after (start_time, id) in the sort order.
            query = query.filter(
                or_(
                    EpgProgramDB.start_time > after_start,
                    and_(
                        EpgProgramDB.start_time == after_start,
                        EpgProgramDB.id > after_id,
                    ),
                )
            )

        return (
            query
            .order_by(EpgProgramDB.start_time, EpgProgramDB.id)
            .limit(limit)
            .all()
        )

    def get_contiguous_guide_end(
        self,
        provider_ids: list[str],
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
        _now: datetime | None = None,
    ) -> datetime | None:
        """Last guide time the selected sources cover *contiguously* from now.

        Unlike ``ProviderDB.epg_data_end`` (the max stop_time anywhere — which a
        single deep channel inflates), this walks the actual matched programmes for
        the scoped sources and stops at the first coverage hole. So when a feed is
        missing tonight's late-night block, the Browse empty-state honestly reports
        coverage ending at the hole instead of claiming it "reaches tomorrow".

        Filler (multi-day placeholder) programmes are excluded so they can't bridge
        a real gap. Time math is delegated to ``epg_utils.contiguous_guide_end``.

        Args:
            provider_ids: Feed-provider IDs whose XMLTV supplies the programmes.
            excluded_channel_provider_ids: Channel-side scoping — drop programmes
                whose matched ChannelDB row belongs to a hidden provider (mirrors
                ``get_schedule`` so coverage matches what Browse actually lists).
            _now: Reference "now" (UTC-naive); defaults to ``now_utc``.

        Returns:
            The last contiguous stop_time (UTC-naive), or ``None`` when the scoped
            sources have no matched programme ending after now.
        """
        now = _now or _now_utc()
        query = self.session.query(
            EpgProgramDB.start_time, EpgProgramDB.stop_time
        ).filter(
            EpgProgramDB.provider_id.in_(provider_ids),
            EpgProgramDB.channel_db_id.isnot(None),
            EpgProgramDB.stop_time > now,
        )
        if excluded_channel_provider_ids:
            query = (
                query
                .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
            )
        spans = [(row.start_time, row.stop_time) for row in query.all()]
        return _contiguous_guide_end(spans, _now=now)

    def search_programs(
        self,
        query_str: str,
        provider_ids: list[str],
        hours_ahead: int = 168,
        lang_code: str = "",
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
    ) -> list[EpgProgramDB]:
        """Full-text search on title + description for upcoming programmes.

        Args:
            excluded_channel_provider_ids: When truthy, programmes whose matched
                ChannelDB row belongs to one of these provider IDs are excluded
                (Browse exclusion scoping — mirrors ``get_schedule``). Requires a
                matched channel, so unmatched rows are dropped only when this is set.
        """
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
        if excluded_channel_provider_ids:
            query = (
                query
                .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
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

    def has_unmatched_unnamed_epg(self, provider_id: str) -> bool:
        """Return True iff the provider has rows that are BOTH unmatched and unnamed.

        These are *legacy* rows (``channel_db_id`` NULL **and** ``channel_name``
        empty) — stored before per-programme display-name persistence — which the
        DB-only relink cannot fix: tier-1 needs an ``epg_channel_id`` match and
        tiers 2/3 need the display name, which isn't stored. One re-fetch
        repopulates ``channel_name`` and rebuilds the links; afterwards this
        returns False and the cheap relink handles everything. A row that is
        already matched (channel_db_id set) does NOT need re-fetching, so matched
        providers never trigger here even if their legacy rows lack a name.
        """
        from sqlalchemy import or_
        row = (
            self.session.query(EpgProgramDB.id)
            .filter(
                EpgProgramDB.provider_id == provider_id,
                EpgProgramDB.channel_db_id.is_(None),
                or_(
                    EpgProgramDB.channel_name == "",
                    EpgProgramDB.channel_name.is_(None),
                ),
            )
            .first()
        )
        return row is not None

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
