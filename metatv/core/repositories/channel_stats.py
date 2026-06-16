"""Channel statistics + special-content queries (split from channel.py, B7-9).

Verbatim extraction of ChannelRepository.get_prefix_stats and the sports/events
query methods into a mixin, keeping channel.py under the 1000-line rule. No logic
changed — ChannelRepository composes _ChannelStatsMixin.
"""
import re
from collections import Counter
from typing import Optional, List, Dict

from sqlalchemy import func, or_

from metatv.core.database import ChannelDB
from metatv.core.filter_utils import categorize_prefix, _GENRE_NORM


_GENRE_SEP_RE = re.compile(r"[,/]")


class _ChannelStatsMixin:
    """Prefix-stats + sports/events queries for ChannelRepository (uses self.session)."""

    def get_prefix_stats(self,
                        provider_id: Optional[str] = None,
                        language_groups: Optional[Dict[str, List[str]]] = None,
                        quality_groups: Optional[Dict[str, List[str]]] = None,
                        platform_groups: Optional[Dict[str, List[str]]] = None,
                        regional_groups: Optional[Dict[str, List[str]]] = None,
                        excluded_user_categories: Optional[set] = None,
                        excluded_provider_ids: Optional[List[str]] = None) -> Dict:
        """Get statistics about detected prefixes.

        Args:
            provider_id: Only analyze channels for this provider.
            language_groups: Language group mappings from config.
            quality_groups: Quality group mappings from config.
            platform_groups: Platform group mappings from config.
            regional_groups: Regional group mappings from config.
            excluded_user_categories: User-category values to exclude.
            excluded_provider_ids: Provider IDs to exclude (inactive + expired
                sources). When supplied, every aggregation is scoped to active
                sources only so counts agree with the channel list.

        Returns:
            Dict with statistics about prefix distribution.
        """
        language_groups = language_groups or {}
        quality_groups = quality_groups or {}
        platform_groups = platform_groups or {}
        regional_groups = regional_groups or {}
        # Normalise once; None / empty → no exclusion (preserves current behaviour).
        _excl_prov = list(excluded_provider_ids) if excluded_provider_ids else None

        def _apply_provider_exclusion(q):
            """Return q with the provider exclusion filter applied (if any)."""
            if _excl_prov:
                q = q.filter(ChannelDB.provider_id.notin_(_excl_prov))
            return q

        query = self.session.query(ChannelDB)
        if provider_id:
            query = query.filter_by(provider_id=provider_id)
        query = query.filter_by(is_hidden=False)
        query = _apply_provider_exclusion(query)
        if excluded_user_categories:
            # Must explicitly allow NULL user_category — SQL NOT IN excludes NULLs
            query = query.filter(
                or_(ChannelDB.user_category.is_(None),
                    ~ChannelDB.user_category.in_(excluded_user_categories))
            )

        # Get unique prefixes with counts
        prefix_query = self.session.query(
            ChannelDB.detected_prefix,
            func.count(ChannelDB.id)
        ).filter_by(is_hidden=False)
        prefix_query = _apply_provider_exclusion(prefix_query)
        if excluded_user_categories:
            prefix_query = prefix_query.filter(
                or_(ChannelDB.user_category.is_(None),
                    ~ChannelDB.user_category.in_(excluded_user_categories))
            )

        if provider_id:
            prefix_query = prefix_query.filter_by(provider_id=provider_id)

        prefix_query = prefix_query.group_by(ChannelDB.detected_prefix)

        prefix_counts = {}
        all_prefixes = set()
        no_prefix_count = 0

        for prefix, count in prefix_query.all():
            if prefix:
                prefix_counts[prefix] = count
                all_prefixes.add(prefix)
            else:
                no_prefix_count = count

        # Quality counts — use detected_quality directly (matches what the SQL filter uses).
        # Channels like "NF - Movie 4K" have detected_prefix=NF but detected_quality=4K;
        # counting by prefix alone would miss them and produce wildly wrong counts.
        quality_counts: dict[str, int] = {}
        dq_rows = (
            self.session.query(ChannelDB.detected_quality, func.count(ChannelDB.id))
            .filter(ChannelDB.is_hidden == False,  # noqa: E712
                    ChannelDB.detected_quality.isnot(None))
        )
        if provider_id:
            dq_rows = dq_rows.filter(ChannelDB.provider_id == provider_id)
        dq_rows = _apply_provider_exclusion(dq_rows)
        dq_rows = dq_rows.group_by(ChannelDB.detected_quality).all()
        dq_counts = {dq: cnt for dq, cnt in dq_rows}

        for group_name, tokens in quality_groups.items():
            total = sum(dq_counts.get(t.upper(), 0) for t in tokens)
            if total:
                quality_counts[group_name] = total

        # Categorize prefixes into language / platform groups
        language_counts = {}
        platform_counts = {}
        unmapped_prefixes = set()

        # Build reverse lookup: prefix → set of regional group names
        region_prefix_to_groups: Dict[str, List[str]] = {}
        for group_name, prefixes in regional_groups.items():
            for p in prefixes:
                region_prefix_to_groups.setdefault(p.upper(), []).append(group_name)

        region_counts: Dict[str, int] = {}

        for prefix in all_prefixes:
            categories = categorize_prefix(prefix, language_groups, quality_groups, platform_groups)
            count = prefix_counts[prefix]

            # A prefix that is itself a quality token (e.g. "4K - Movie") is already
            # counted via detected_quality above — don't double-count under language.
            if categories['quality']:
                continue

            in_region = prefix.upper() in region_prefix_to_groups
            if not (categories['language'] or categories['platform'] or in_region):
                unmapped_prefixes.add(prefix)

            if categories['language']:
                lang = categories['language']
                language_counts[lang] = language_counts.get(lang, 0) + count

            if categories['platform']:
                plat = categories['platform']
                platform_counts[plat] = platform_counts.get(plat, 0) + count

            # A prefix can belong to multiple regional groups (e.g. MX = both
            # "North America" and "Latin America" and "Central America")
            for rg in region_prefix_to_groups.get(prefix.upper(), []):
                region_counts[rg] = region_counts.get(rg, 0) + count

        # Unmapped prefixes surface as "Other" in the Language dropdown.
        # The individual prefix codes are also returned so the filter can pass them
        # to get_all() when the user selects "Other".
        unmapped_list = sorted(unmapped_prefixes)
        other_count = sum(prefix_counts[p] for p in unmapped_list)
        if unmapped_list:
            language_counts["Other"] = other_count

        total_channels = query.count()

        no_quality_query = self.session.query(func.count(ChannelDB.id)).filter(
            ChannelDB.is_hidden == False,  # noqa: E712
            ChannelDB.detected_quality.is_(None),
        )
        if provider_id:
            no_quality_query = no_quality_query.filter(
                ChannelDB.provider_id == provider_id)
        no_quality_query = _apply_provider_exclusion(no_quality_query)
        if excluded_user_categories:
            no_quality_query = no_quality_query.filter(
                or_(ChannelDB.user_category.is_(None),
                    ~ChannelDB.user_category.in_(excluded_user_categories)))
        no_quality_count = no_quality_query.scalar() or 0

        # Genre counts — split compound strings, normalise multilingual variants to English,
        # then count. Genres that contain no Latin letters (e.g. Arabic/CJK script) and
        # have no mapping are dropped so they can't force the panel wider with RTL text.
        from collections import Counter as _Counter
        genre_counter: _Counter = _Counter()
        _has_latin = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
        genre_q = (
            self.session.query(ChannelDB.raw_data)
            .filter(
                ChannelDB.media_type.in_(["movie", "series"]),
                ChannelDB.is_hidden == False,  # noqa: E712
                ChannelDB.raw_data.isnot(None),
            )
        )
        if provider_id:
            genre_q = genre_q.filter(ChannelDB.provider_id == provider_id)
        genre_q = _apply_provider_exclusion(genre_q)
        if excluded_user_categories:
            genre_q = genre_q.filter(
                or_(ChannelDB.user_category.is_(None),
                    ~ChannelDB.user_category.in_(excluded_user_categories))
            )
        for (raw_data,) in genre_q.yield_per(2000):
            genre_str = (raw_data or {}).get("genre") or ""
            for g in _GENRE_SEP_RE.split(genre_str):
                g = g.strip()
                if not g:
                    continue
                canonical = _GENRE_NORM.get(g.lower(), g)
                # Skip genres with no Latin letters and no mapping (Arabic/CJK script etc.)
                if canonical == g and not _has_latin.search(g):
                    continue
                genre_counter[canonical] += 1
        genre_counts = {g: cnt for g, cnt in genre_counter.most_common() if cnt >= 10}

        return {
            'all_prefixes': list(all_prefixes),
            'prefix_counts': prefix_counts,
            'language_groups': language_counts,
            'quality_groups': quality_counts,
            'platform_groups': platform_counts,
            'region_groups': region_counts,
            'unmapped_prefixes': unmapped_list,
            'total_channels': total_channels,
            'channels_with_prefix': total_channels - no_prefix_count,
            'channels_without_prefix': no_prefix_count,
            'channels_without_quality': no_quality_count,
            'genre_counts': genre_counts,
        }

    # -------------------------------------------------------------------------
    # Special content queries
    # -------------------------------------------------------------------------

    def get_sports_channels(
        self,
        sport_types: Optional[List[str]] = None,
        league_names: Optional[List[str]] = None,
    ) -> List[ChannelDB]:
        """Get sports channels with optional cascade filters.

        Empty or None filter lists mean "no filter — include all".
        The special value ``'unknown'`` in sport_types also matches channels
        whose sport_type is NULL, ensuring unclassified channels stay visible.

        Args:
            sport_types: Canonical sport names to include (e.g. ['hockey', 'soccer']).
            league_names: League display names to include (e.g. ['NHL', 'Premier League']).

        Returns:
            Channels ordered by sport_type, league_name, name.
        """
        query = self.session.query(ChannelDB).filter(
            ChannelDB.special_view == 'sports',
            ChannelDB.is_hidden == False,
            ChannelDB.stream_url.isnot(None),
            ~ChannelDB.name.like('#%'),
        )

        if sport_types:
            lower_types = [s.lower() for s in sport_types]
            if 'unknown' in lower_types:
                query = query.filter(
                    (ChannelDB.sport_type.in_(sport_types)) |
                    (ChannelDB.sport_type.is_(None))
                )
            else:
                query = query.filter(ChannelDB.sport_type.in_(sport_types))

        if league_names:
            query = query.filter(ChannelDB.league_name.in_(league_names))

        return query.order_by(
            ChannelDB.sport_type, ChannelDB.league_name, ChannelDB.name
        ).all()

    def get_events_channels(self) -> List[ChannelDB]:
        """Get all live event channels (special_view == 'live_event').

        Returns:
            Channels ordered by name.
        """
        return self.session.query(ChannelDB).filter(
            ChannelDB.special_view == 'live_event',
            ChannelDB.is_hidden == False,
            ChannelDB.stream_url.isnot(None),
            ~ChannelDB.name.like('#%'),
        ).order_by(ChannelDB.name).all()

    def get_sports_taxonomy(self) -> Dict[str, Dict[str, List[str]]]:
        """Build the sport → league → team hierarchy for cascade filter dropdowns.

        Channels without a sport_type are placed under the key ``'unknown'``.
        Channels with a sport_type but no league_name appear in that sport's dict
        but have no league sub-key (so the League dropdown shows only sports that
        actually have league data).

        Returns:
            Nested dict: ``{sport: {league: [team, ...]}}`` — leagues and teams
            are sorted alphabetically.
        """
        rows = self.session.query(
            ChannelDB.sport_type,
            ChannelDB.league_name,
            ChannelDB.team_name,
        ).filter(
            ChannelDB.special_view == 'sports',
            ChannelDB.is_hidden == False,
            ChannelDB.stream_url.isnot(None),
            ~ChannelDB.name.like('#%'),
        ).distinct().all()

        taxonomy: Dict[str, Dict[str, set]] = {}
        for sport, league, team in rows:
            sport_key = sport if sport else 'unknown'
            taxonomy.setdefault(sport_key, {})
            if league:
                taxonomy[sport_key].setdefault(league, set())
                if team:
                    taxonomy[sport_key][league].add(team)

        return {
            sport: {league: sorted(teams) for league, teams in sorted(leagues.items())}
            for sport, leagues in sorted(taxonomy.items())
        }

    def get_sports_counts(self) -> Dict[str, int]:
        """Return channel counts grouped by sport_type, for dropdown badges.

        Returns:
            Dict mapping sport display name (or 'unknown') to channel count.
        """
        rows = self.session.query(
            ChannelDB.sport_type,
            func.count(ChannelDB.id),
        ).filter(
            ChannelDB.special_view == 'sports',
            ChannelDB.is_hidden == False,
            ChannelDB.stream_url.isnot(None),
            ~ChannelDB.name.like('#%'),
        ).group_by(ChannelDB.sport_type).all()

        return {(sport if sport else 'unknown'): count for sport, count in rows}
