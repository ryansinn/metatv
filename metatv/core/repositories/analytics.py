"""Analytics repository for source fingerprinting and overlap analysis."""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from metatv.core.database import ChannelDB, ProviderDB
from metatv.core.repositories.dtos import (
    SourceFingerprintDTO,
    OverlapMatrixDTO,
    UniqueChannelDTO,
    PrefixStatDTO,
)
from metatv.core.channel_name_utils import (
    QUALITY_TOKENS,
    REGION_FULL_NAMES,
    PLATFORM_CODES,
)


class AnalyticsRepository:
    """Compute source analytics: fingerprints, overlap, unique content, prefix stats."""

    def __init__(self, session: Session):
        self.session = session

    def source_fingerprint(self, provider_id: str) -> SourceFingerprintDTO:
        """Get a source's fingerprint: counts, quality/region histograms, prefix coverage."""
        # Build canonical lexicon set for prefix recognition check
        canonical_lexicon = (
            QUALITY_TOKENS
            | set(REGION_FULL_NAMES.keys())
            | PLATFORM_CODES
        )

        # Query counts by media type (all and visible)
        rows = self.session.query(ChannelDB).filter_by(provider_id=provider_id).all()

        live_count = sum(1 for r in rows if r.media_type == "live")
        movie_count = sum(1 for r in rows if r.media_type == "movie")
        series_count = sum(1 for r in rows if r.media_type == "series")
        total_count = len(rows)

        visible_rows = [r for r in rows if not r.is_hidden]
        live_visible = sum(1 for r in visible_rows if r.media_type == "live")
        movie_visible = sum(1 for r in visible_rows if r.media_type == "movie")
        series_visible = sum(1 for r in visible_rows if r.media_type == "series")
        total_visible = len(visible_rows)

        # Build quality histogram
        quality_histogram = {}
        for row in visible_rows:
            if row.detected_quality:
                quality_histogram[row.detected_quality] = quality_histogram.get(row.detected_quality, 0) + 1

        # Build region histogram
        region_histogram = {}
        for row in visible_rows:
            if row.detected_region:
                region_histogram[row.detected_region] = region_histogram.get(row.detected_region, 0) + 1

        # Prefix recognition coverage
        recognized_count = 0
        unrecognized_count = 0
        untagged_count = 0
        for row in visible_rows:
            if not row.detected_prefix:
                untagged_count += 1
            elif row.detected_prefix in canonical_lexicon:
                recognized_count += 1
            else:
                unrecognized_count += 1

        # Calculate percentages
        total_for_pct = total_visible if total_visible > 0 else 1  # Guard div-by-zero
        recognized_pct = (recognized_count / total_for_pct) * 100 if total_visible > 0 else 0.0
        adult_pct = (sum(1 for r in visible_rows if r.is_adult) / total_for_pct) * 100 if total_visible > 0 else 0.0
        untagged_pct = (untagged_count / total_for_pct) * 100 if total_visible > 0 else 0.0

        # Special view breakdown
        special_view_breakdown = {}
        for row in visible_rows:
            if row.special_view:
                special_view_breakdown[row.special_view] = special_view_breakdown.get(row.special_view, 0) + 1

        # Get provider name
        provider = self.session.query(ProviderDB).filter_by(id=provider_id).first()
        provider_name = provider.name if provider else provider_id

        return SourceFingerprintDTO(
            provider_id=provider_id,
            name=provider_name,
            live_count=live_count,
            movie_count=movie_count,
            series_count=series_count,
            total_count=total_count,
            live_visible=live_visible,
            movie_visible=movie_visible,
            series_visible=series_visible,
            total_visible=total_visible,
            quality_histogram=quality_histogram,
            region_histogram=region_histogram,
            recognized_count=recognized_count,
            unrecognized_count=unrecognized_count,
            recognized_pct=recognized_pct,
            adult_pct=adult_pct,
            untagged_pct=untagged_pct,
            special_view_breakdown=special_view_breakdown,
        )

    def overlap_matrix(self, provider_ids: list[str], media_type: str) -> list[OverlapMatrixDTO]:
        """Compute N×N overlap matrix (Jaccard) for given providers and media type.

        Returns one DTO per ordered pair, including identity pairs (A vs A = 100%).
        """
        result = []

        # Get provider names for display
        providers = {}
        for pid in provider_ids:
            prov = self.session.query(ProviderDB).filter_by(id=pid).first()
            providers[pid] = prov.name if prov else pid

        # For each pair (including identity)
        for a_id in provider_ids:
            for b_id in provider_ids:
                # Get A's distinct normalized titles
                a_rows = self.session.query(ChannelDB).filter(
                    and_(
                        ChannelDB.provider_id == a_id,
                        ChannelDB.media_type == media_type,
                        ChannelDB.is_hidden == False,
                    )
                ).all()
                a_titles = {
                    (r.detected_title or r.name).lower()
                    for r in a_rows
                }

                # Get B's distinct normalized titles
                b_rows = self.session.query(ChannelDB).filter(
                    and_(
                        ChannelDB.provider_id == b_id,
                        ChannelDB.media_type == media_type,
                        ChannelDB.is_hidden == False,
                    )
                ).all()
                b_titles = {
                    (r.detected_title or r.name).lower()
                    for r in b_rows
                }

                # Compute overlap metrics
                shared = len(a_titles & b_titles)
                a_only = len(a_titles - b_titles)
                b_only = len(b_titles - a_titles)
                union_size = len(a_titles | b_titles)
                jaccard = shared / union_size if union_size > 0 else 0.0

                result.append(OverlapMatrixDTO(
                    provider_a_id=a_id,
                    provider_b_id=b_id,
                    provider_a_name=providers[a_id],
                    provider_b_name=providers[b_id],
                    media_type=media_type,
                    shared=shared,
                    a_only=a_only,
                    b_only=b_only,
                    jaccard=jaccard,
                ))

        return result

    def unique_titles(self, provider_id: str, media_type: str, limit: int = 1000) -> list[UniqueChannelDTO]:
        """Get titles unique to this provider (not present on any other visible provider)."""
        # Get all distinct normalized titles from other providers
        other_rows = self.session.query(ChannelDB).filter(
            and_(
                ChannelDB.provider_id != provider_id,
                ChannelDB.media_type == media_type,
                ChannelDB.is_hidden == False,
            )
        ).all()
        other_titles = {
            (r.detected_title or r.name).lower()
            for r in other_rows
        }

        # Get this provider's rows and filter to unique
        this_rows = self.session.query(ChannelDB).filter(
            and_(
                ChannelDB.provider_id == provider_id,
                ChannelDB.media_type == media_type,
                ChannelDB.is_hidden == False,
            )
        ).all()

        result = []
        for row in this_rows:
            normalized_title = (row.detected_title or row.name).lower()
            if normalized_title not in other_titles:
                # Get provider name for display
                provider = self.session.query(ProviderDB).filter_by(id=provider_id).first()
                provider_name = provider.name if provider else provider_id

                result.append(UniqueChannelDTO(
                    channel_id=row.id,
                    name=row.name,
                    detected_title=row.detected_title,
                    detected_prefix=row.detected_prefix,
                    detected_quality=row.detected_quality,
                    detected_region=row.detected_region,
                    detected_year=row.detected_year,
                    media_type=row.media_type,
                    provider_name=provider_name,
                ))

                if len(result) >= limit:
                    break

        return result

    def unrecognized_prefixes(self, provider_id: str | None = None) -> list[PrefixStatDTO]:
        """Get unrecognized prefix tokens with counts and sample names.

        If provider_id is None, returns unrecognized prefixes across all providers.
        """
        # Build canonical lexicon
        canonical_lexicon = (
            QUALITY_TOKENS
            | set(REGION_FULL_NAMES.keys())
            | PLATFORM_CODES
        )

        # Query rows
        query = self.session.query(ChannelDB).filter(
            and_(
                ChannelDB.detected_prefix != "",
                ChannelDB.detected_prefix != None,
                ChannelDB.is_hidden == False,
            )
        )
        if provider_id:
            query = query.filter(ChannelDB.provider_id == provider_id)

        rows = query.all()

        # Count by prefix
        prefix_counts = {}
        for row in rows:
            if row.detected_prefix:
                prefix_counts[row.detected_prefix] = prefix_counts.get(row.detected_prefix, 0) + 1

        # Filter to unrecognized only
        unrecognized = {
            prefix: count
            for prefix, count in prefix_counts.items()
            if prefix not in canonical_lexicon
        }

        # Sort by count descending
        sorted_prefixes = sorted(unrecognized.items(), key=lambda x: x[1], reverse=True)

        # Build result with sample names
        result = []
        for prefix, count in sorted_prefixes:
            # Get 3-5 sample names
            sample_rows = self.session.query(ChannelDB).filter(
                and_(
                    ChannelDB.detected_prefix == prefix,
                    ChannelDB.is_hidden == False,
                )
            ).limit(5).all()
            sample_names = [r.name for r in sample_rows]

            result.append(PrefixStatDTO(
                prefix=prefix,
                count=count,
                sample_names=sample_names,
                is_recognized=False,  # We only return unrecognized ones
            ))

        return result
