"""Channel prefix statistics (split from channel.py, B7-9).

Verbatim extraction of ChannelRepository.get_prefix_stats into a mixin, keeping
channel.py under the 1000-line rule. No logic changed — ChannelRepository
composes _ChannelStatsMixin.

The special-content (sports/events) query methods this mixin used to carry
(``get_sports_channels``, ``get_events_channels``, ``get_sports_taxonomy``,
``get_sports_counts``, ``get_sports_lane_counts``, and their private support —
``_special_content_query``, ``_apply_sports_facets``, ``_sports_lane_rank``,
``SPORTS_LANES``, ``PLACEHOLDER_MARKER``, ``LIVE_WINDOW``) were removed in
dead-code sweep B: the Sports and Events VIEWS that called them were retired in
#731 and nothing else ever gained a caller. See docs/REFACTOR_PLAN.md row D43.
"""
import re
from typing import Optional, List, Dict

from sqlalchemy import func, or_

from metatv.core.database import ChannelDB
from metatv.core.filter_utils import categorize_prefix, _GENRE_NORM


_GENRE_SEP_RE = re.compile(r"[,/]")


class _ChannelStatsMixin:
    """Prefix-stats for ChannelRepository (uses self.session)."""

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
        dq_counts = dict(dq_rows)

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

