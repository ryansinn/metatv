"""The watchlist-matching family: rule-driven EPG queries and the notification scan.

Settled in "Catch, Keep, Record" (2026-08-30) Q4 *one list, two surfaces* — a watch
rule is stored once and rendered by both the Watch Alerts sidebar and the EPG
Watchlist tab. The methods here are the read side of that rule: they promote raw
patterns to :class:`~metatv.core.watchlist_matching.WatchRule` objects via
``as_rules``, prefilter in SQL via ``sql_prefilter``, and refine in Python via
``refine`` — the same three calls both surfaces render from. ``get_programs_starting_soon``
joins the family because it feeds ``EpgManager._watchlist_notification_worker``, the
desktop-toast path for the same watch list.

Extracted out of ``core/repositories/epg.py``, which sat at its 1066-line ratchet
ceiling after WL-1 (DEBT-7, 2026-09-05). Behaviour-preserving move — every method
below is verbatim from ``EpgRepository``.
"""

from __future__ import annotations

from datetime import timedelta

from loguru import logger

from metatv.core.database import EpgProgramDB, ChannelDB
from metatv.core.epg_utils import now_utc as _now_utc
from metatv.core.watchlist_matching import as_rules, refine, sql_prefilter

#: Prefilter candidates pulled before whole-word refinement. The prefilter is
#: a superset, so the real 20-row limit is applied after matching; this bounds
#: the work between. The call site logs when it is hit — never a silent cut.
_WATCHLIST_PREFETCH = 400


class EpgWatchlistMixin:
    """Watch-rule-driven programme queries, mixed into :class:`EpgRepository`.

    Expects ``self.session`` (a SQLAlchemy ``Session``), provided by the host class.
    """

    def _scope_watchlist_query(
        self,
        query,
        provider_ids: list[str] | None,
        lang_code: str,
        excluded_channel_provider_ids: set[str] | list[str] | None,
    ):
        """Apply the feed / hidden-source / language filters to a programme query.

        The exclusion join is pasted TWELVE times in this file. Only the two
        watchlist queries are migrated here (WL-1's scope); the other ten are
        in docs/REFACTOR_PLAN.md and must be checked for policy differences
        before adoption. New query methods call this instead of pasting.
        """
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
        return query

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

        for rule in as_rules(patterns):
            query = self.session.query(EpgProgramDB).filter(
                sql_prefilter(rule, EpgProgramDB.title, EpgProgramDB.description),
                EpgProgramDB.start_time >= now,
                EpgProgramDB.start_time <= cutoff,
                EpgProgramDB.channel_db_id.isnot(None),
            )
            query = self._scope_watchlist_query(
                query, provider_ids, lang_code, excluded_channel_provider_ids)
            # The 20 is applied AFTER refinement, never in SQL: the prefilter
            # is a superset, so a LIMIT here can spend the whole allowance on
            # rows the rule rejects and drop a real match off a full-looking list.
            rows = (query.order_by(EpgProgramDB.start_time)
                    .limit(_WATCHLIST_PREFETCH).all())
            if len(rows) == _WATCHLIST_PREFETCH:
                logger.debug("watchlist upcoming: prefetch cap hit for {!r}",
                             rule.key)
            result[rule.key] = refine(rows, rule, limit=20)

        return result

    def count_for_watchlist(
        self,
        patterns,
        hours_ahead: int = 168,
        provider_ids: list[str] | None = None,
        lang_code: str = "",
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
    ) -> "dict[str, tuple[int, int, bool, int]]":
        """Per rule: ``(matched, suppressed, capped, description_gain)``.

        Feeds the rule row's summary line — the control that makes an exclude
        list trustworthy. ``suppressed`` re-runs the SAME rule with its excludes
        dropped, ``description_gain`` with ``search_description`` forced on (0
        once it already is), so neither can disagree with the matcher; ``capped``
        means the prefilter ceiling hit and the numbers are floors — say so.
        """
        from dataclasses import replace

        now = _now_utc()
        cutoff = now + timedelta(hours=hours_ahead)
        out: dict[str, tuple[int, int, bool, int]] = {}

        def _rows_for(candidate) -> list:
            query = self._scope_watchlist_query(
                self.session.query(EpgProgramDB).filter(
                    sql_prefilter(candidate, EpgProgramDB.title, EpgProgramDB.description),
                    EpgProgramDB.start_time >= now, EpgProgramDB.start_time <= cutoff,
                    EpgProgramDB.channel_db_id.isnot(None)),
                provider_ids, lang_code, excluded_channel_provider_ids)
            return query.limit(_WATCHLIST_PREFETCH).all()

        for rule in as_rules(patterns):
            rows = _rows_for(rule)
            capped = len(rows) == _WATCHLIST_PREFETCH
            matched = len(refine(rows, rule))
            without = len(refine(rows, replace(rule, exclude=())))
            gain = 0  # Description widens the prefilter itself: a second query
            if not rule.search_description:
                desc = replace(rule, search_description=True)
                gain = max(0, len(refine(_rows_for(desc), desc)) - matched)
            out[rule.key] = (matched, max(0, without - matched), capped, gain)
            if capped:
                logger.debug("watchlist counts: prefilter cap hit for {!r}", rule.key)
        return out

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

        for rule in as_rules(patterns):
            query = self.session.query(EpgProgramDB).filter(
                sql_prefilter(rule, EpgProgramDB.title, EpgProgramDB.description),
                EpgProgramDB.start_time <= now,
                EpgProgramDB.stop_time  >  now,
                EpgProgramDB.channel_db_id.isnot(None),
            )
            query = self._scope_watchlist_query(
                query, provider_ids, lang_code, excluded_channel_provider_ids)
            # No LIMIT by design (tests/test_epg_watchlist_ranking.py).
            result[rule.key] = refine(query.all(), rule)

        return result

    def get_programs_starting_soon(
        self,
        within_minutes: int,
        provider_ids: list[str],
        excluded_channel_provider_ids: set[str] | list[str] | None = None,
    ) -> list[EpgProgramDB]:
        """Programmes starting within the next N minutes (for notifications).

        TWO independent scoping axes, and this is the function that only had
        one. ``provider_ids`` scopes the FEED — whose XMLTV supplied the
        programme. ``excluded_channel_provider_ids`` scopes the CHANNEL the
        programme was matched to, which can belong to a different provider
        entirely: ``epg_matching.build_match_map`` keeps a separate
        ``cross_provider`` candidate dict on purpose, so cross-provider matching
        is a working feature rather than an edge case.

        Without the second axis a programme from an ACTIVE feed, matched to a
        channel on a DISABLED source, passes the filter and fires a desktop
        toast for something the user cannot watch. On the owner's library that
        was 418 rows across 6 channels, 18 of them still in the future.

        ``has_future_programmes`` below already had this parameter and its
        docstring already called itself this function's sibling "with the same
        matched-channel and scoping rules" — a symmetry that did not exist until
        now. #536 fixed the feed axis at three call sites and left the channel
        axis to whoever rediscovered it; the sidebar did, the notification path
        did not.

        Args:
            within_minutes: How far ahead to look.
            provider_ids: Feed-provider IDs whose XMLTV supplies the programmes.
            excluded_channel_provider_ids: Channel-side scoping — drop
                programmes whose matched ChannelDB row belongs to a hidden
                provider.

        Returns:
            The in-scope programmes starting inside the window.
        """
        now = _now_utc()
        cutoff = now + timedelta(minutes=within_minutes)
        query = self.session.query(EpgProgramDB).filter(
            EpgProgramDB.provider_id.in_(provider_ids),
            EpgProgramDB.start_time > now,
            EpgProgramDB.start_time <= cutoff,
            EpgProgramDB.channel_db_id.isnot(None),
        )
        if excluded_channel_provider_ids:
            query = (
                query
                .join(ChannelDB, EpgProgramDB.channel_db_id == ChannelDB.id)
                .filter(ChannelDB.provider_id.notin_(excluded_channel_provider_ids))
            )
        return query.all()
