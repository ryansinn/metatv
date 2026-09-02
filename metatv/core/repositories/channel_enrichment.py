"""TMDb / metadata ENRICHMENT: which rows still need data, and applying it.

Extracted from ``channel.py`` as a mixin, the pattern the ingestion, stats,
history and pruning concerns already use — ``ChannelRepository`` composes it, so
no caller learns a new import and none of them changed.

**Why these members and not the plan's six.** docs/CHANNEL_REPOSITORY_SPLIT.md
names six methods for this slice. Two of them share private filters —
``_tmdb_candidate_filter`` and ``_metadata_enrichment_filter`` — with three
others the plan left behind, and a helper separated from its users is worse than
one left in place: it turns a private detail into a cross-module dependency. The
concern is "enrichment", and its members are whatever those two filters serve.
That is the plan's own rule 2 ("take the private helpers with the concern")
followed to where it actually leads.

The read/write split matters here and is easy to lose: the ``select_*`` /
``missing_*`` / ``*_funnel`` members ANSWER "what still needs enriching" and
return DTOs; ``apply_*`` are the only writers. Nothing returns an ORM object —
every one of these crosses a session boundary into
``metadata_manager`` / ``tmdb_enrichment_manager``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Set

from sqlalchemy import func, or_, update

from metatv.core.content_identity import content_key_for
from metatv.core.database import ChannelDB, MetadataDB, ProviderDB
from metatv.core.repositories.channel_ingestion import _start_year_int, _TmdbKeyProxy
from metatv.core.repositories.dtos import (
    MissingTmdbRowDTO,
    MissingTmdbSourceDTO,
    TmdbFunnelDTO,
)






# Scene-release noise tokens — their presence in a "title" means the row kept a
# release filename (e.g. "Movie.2019.1080p.WEB.x264-GROUP"), which a title search
# would NOT match cleanly.  Used only for the qualitative TMDb-addressability flag
# in the Missing-TMDb diagnostic (never for identity/collapse).
_SCENE_NOISE_TOKENS = frozenset({
    "1080p", "720p", "480p", "2160p", "4k", "x264", "x265", "h264", "h265",
    "hevc", "web", "webrip", "web-dl", "webdl", "bluray", "brrip", "bdrip",
    "hdrip", "dvdrip", "hdtv", "xvid", "aac", "ac3", "dts", "hdr", "remux",
})


def _looks_tmdb_addressable(detected_title, media_type, detected_year) -> bool:
    """Qualitative guess: could an external TMDb title search likely resolve this row?

    Decision-support only (never identity): a clean, short title — plus a year for
    movies — is plausibly matchable; a scene-release filename or an empty title is
    not.  Deliberately conservative so the "K titles the TMDb API could resolve"
    figure isn't inflated by junk rows.

    Args:
        detected_title: The stored, already-stripped title (may be None).
        media_type: ``"movie"`` / ``"series"``.
        detected_year: The stored year string (may be None).

    Returns:
        True when the row looks like a plausible title-search target.
    """
    if not detected_title:
        return False
    # Split on any non-alphanumeric run so dot-separated scene filenames
    # ("Movie.2019.1080p.WEB.x264-GRP") tokenize like space-separated ones.
    tokens = [t for t in re.split(r"[^a-z0-9]+", detected_title.lower()) if t]
    if not tokens or len(tokens) > 12:
        return False
    if any(t in _SCENE_NOISE_TOKENS for t in tokens):
        return False
    # Movies benefit from a disambiguating year; series are matchable on title alone.
    if media_type == "movie":
        return _start_year_int(detected_year) is not None
    return True


class ChannelEnrichmentMixin:
    """Enrichment reads and writes for ``ChannelRepository`` (uses self.session)."""










    # ── Provider-native tmdb enrichment (Phase 2) ─────────────────────────────

    def _tmdb_candidate_filter(self, query, excluded_provider_ids, provider_id):
        """Apply the shared idless-VOD-candidate predicate to *query*.

        A candidate is a movie/series row that is visible (``is_hidden`` False),
        belongs to a non-excluded provider, carries **no** ``detected_tmdb_id``
        (its list row shipped no id), and has **not** been attempted yet
        (``tmdb_enrich_state IS NULL``) — the persistent marker that makes the
        pass resumable and hits each row at most once.  Single definition so the
        candidate query and the has-candidates probe never drift.
        """
        query = (
            query
            .filter(ChannelDB.detected_tmdb_id.is_(None))
            .filter(ChannelDB.tmdb_enrich_state.is_(None))
            .filter(ChannelDB.media_type.in_(("movie", "series")))
            .filter(ChannelDB.is_hidden.is_(False))
        )
        if excluded_provider_ids:
            query = query.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        if provider_id is not None:
            query = query.filter(ChannelDB.provider_id == provider_id)
        return query

    def provider_ids_with_tmdb_candidates(
        self,
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> List[str]:
        """Return the distinct providers that still have idless VOD rows to attempt.

        Lets the caller split its per-session cap fairly across sources rather than
        exhausting the largest provider first (which would starve the others for
        hundreds of launches).

        Args:
            excluded_provider_ids: Hidden providers — never enriched.

        Returns:
            Distinct ``provider_id`` values with at least one candidate.
        """
        q = self._tmdb_candidate_filter(
            self.session.query(ChannelDB.provider_id).distinct(),
            excluded_provider_ids,
            provider_id=None,
        )
        return [row[0] for row in q.all()]

    def select_tmdb_enrichment_candidates(
        self,
        limit: int,
        excluded_provider_ids: Optional[Set[str]] = None,
        provider_id: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Return idless VOD rows that still need a provider-detail tmdb lookup.

        See :meth:`_tmdb_candidate_filter` for the candidate predicate.  Returns
        plain dicts (safe to cross the worker → write-session boundary — no ORM
        objects escape).

        Args:
            limit: Hard cap on rows returned.
            excluded_provider_ids: Hidden providers (inactive ∪ expired) from
                ``ProviderRepository.get_hidden_provider_ids()`` — never enriched.
            provider_id: When given, restrict to this one provider (used to draw a
                fair per-provider slice of the session cap).

        Returns:
            List of ``{"id", "provider_id", "source_id", "media_type"}`` dicts.
        """
        q = self._tmdb_candidate_filter(
            self.session.query(
                ChannelDB.id,
                ChannelDB.provider_id,
                ChannelDB.source_id,
                ChannelDB.media_type,
            ),
            excluded_provider_ids,
            provider_id,
        )
        q = q.order_by(ChannelDB.provider_id).limit(limit)

        return [
            {
                "id": cid,
                "provider_id": pid,
                "source_id": sid,
                "media_type": mt,
            }
            for (cid, pid, sid, mt) in q.all()
        ]

    def select_tmdb_candidates_by_ids(
        self,
        channel_ids,
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> List[Dict[str, str]]:
        """Narrow *channel_ids* to the rows that still need a provider-detail lookup.

        The lazy enrichment (``TmdbEnrichmentManager.enqueue``) is fed **bare ids**
        from the result surfaces (Discover / Recipe / channel list / search / details)
        — none of whose DTOs carry ``detected_tmdb_id`` / ``tmdb_enrich_state``.  This
        applies the shared candidate predicate (:meth:`_tmdb_candidate_filter`:
        idless, unattempted, visible, non-excluded VOD) to the queued ids off the UI
        thread, so a row is fetched at most once and only when it really needs it.

        Args:
            channel_ids: The ids a surface just loaded (a bounded drain batch).
            excluded_provider_ids: Hidden providers (inactive ∪ expired) from
                ``ProviderRepository.get_hidden_provider_ids()`` — never enriched.

        Returns:
            List of ``{"id", "provider_id", "source_id", "media_type"}`` dicts for the
            subset that are still candidates (plain dicts — no ORM objects escape).
        """
        ids = list(channel_ids)
        if not ids:
            return []
        q = self._tmdb_candidate_filter(
            self.session.query(
                ChannelDB.id,
                ChannelDB.provider_id,
                ChannelDB.source_id,
                ChannelDB.media_type,
            ),
            excluded_provider_ids,
            provider_id=None,
        ).filter(ChannelDB.id.in_(ids))
        return [
            {"id": cid, "provider_id": pid, "source_id": sid, "media_type": mt}
            for (cid, pid, sid, mt) in q.all()
        ]

    def tmdb_enrichment_funnel(
        self,
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> TmdbFunnelDTO:
        """Return the enrichment funnel across visible VOD rows (analytics).

        Buckets every movie/series row on a visible, non-excluded provider by how
        its tmdb id was resolved (provenance in ``tmdb_enrich_state``), so the
        "Missing TMDb data" view can present provider-native coverage vs. the
        residual gap that only the external TMDb API could close.  One GROUP BY —
        no per-row scan.

        Args:
            excluded_provider_ids: Hidden providers (inactive ∪ expired) to exclude.

        Returns:
            A :class:`TmdbFunnelDTO` (safe to cross the worker boundary).
        """
        q = (
            self.session.query(
                ChannelDB.detected_tmdb_id.isnot(None),
                ChannelDB.tmdb_enrich_state,
                func.count(),
            )
            .filter(ChannelDB.media_type.in_(("movie", "series")))
            .filter(ChannelDB.is_hidden.is_(False))
        )
        if excluded_provider_ids:
            q = q.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        q = q.group_by(
            ChannelDB.detected_tmdb_id.isnot(None), ChannelDB.tmdb_enrich_state
        )

        from_list = propagated = fetched = unattempted = residual = 0
        for has_id, state, n in q.all():
            if has_id:
                if state == "propagated":
                    propagated += n
                elif state == "fetched":
                    fetched += n
                else:
                    # 'list' / NULL / anything else with an id → harvested-from-list.
                    from_list += n
            else:
                if state == "none":
                    residual += n
                else:
                    unattempted += n  # NULL marker → still a lazy-fetch candidate

        total = from_list + propagated + fetched + unattempted + residual
        return TmdbFunnelDTO(
            total_vod=total,
            from_list=from_list,
            propagated=propagated,
            fetched=fetched,
            unattempted=unattempted,
            residual=residual,
        )

    def missing_tmdb_by_source(
        self,
        excluded_provider_ids: Optional[Set[str]] = None,
        sample_per_source: int = 8,
        max_sources: int = 50,
    ) -> List[MissingTmdbSourceDTO]:
        """Return idless-VOD counts + a sample per source for the diagnostic view.

        A row is *idless* when ``detected_tmdb_id IS NULL`` (visible VOD only); of
        those, the ``'none'``-marked subset is the residual only the TMDb API could
        resolve.  The view feeds each returned row's ``channel_id`` back through the
        enqueue chokepoint, so opening it drives enrichment (the list shrinks as ids
        land).  Returns frozen DTOs — no ORM objects escape.

        Args:
            excluded_provider_ids: Hidden providers to exclude.
            sample_per_source: Max example rows per source (for the drill-down).
            max_sources: Cap on the number of sources returned (largest gaps first).

        Returns:
            List of :class:`MissingTmdbSourceDTO`, sorted by ``missing_count`` desc.
        """
        from sqlalchemy import case

        base = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.detected_tmdb_id.is_(None))
            .filter(ChannelDB.media_type.in_(("movie", "series")))
            .filter(ChannelDB.is_hidden.is_(False))
        )
        if excluded_provider_ids:
            base = base.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))

        counts = (
            base.with_entities(
                ChannelDB.provider_id,
                func.count(),
                func.sum(case((ChannelDB.tmdb_enrich_state == "none", 1), else_=0)),
            )
            .group_by(ChannelDB.provider_id)
            .order_by(func.count().desc())
            .limit(max_sources)
            .all()
        )
        if not counts:
            return []

        # Provider names (single lookup — the DTO carries the human-readable name).
        names = {p.id: p.name for p in self.session.query(ProviderDB.id, ProviderDB.name).all()}

        out: List[MissingTmdbSourceDTO] = []
        for pid, missing_count, residual_count in counts:
            sample_rows = (
                base.with_entities(
                    ChannelDB.id,
                    ChannelDB.name,
                    ChannelDB.detected_title,
                    ChannelDB.detected_year,
                    ChannelDB.media_type,
                )
                .filter(ChannelDB.provider_id == pid)
                .order_by(ChannelDB.name)
                .limit(sample_per_source)
                .all()
            )
            sample = [
                MissingTmdbRowDTO(
                    channel_id=cid,
                    name=name,
                    detected_title=dt,
                    detected_year=dy,
                    media_type=mt,
                    tmdb_addressable=_looks_tmdb_addressable(dt, mt, dy),
                )
                for (cid, name, dt, mt, dy) in (
                    (r[0], r[1], r[2], r[4], r[3]) for r in sample_rows
                )
            ]
            out.append(
                MissingTmdbSourceDTO(
                    provider_id=pid,
                    provider_name=names.get(pid, pid),
                    missing_count=int(missing_count or 0),
                    residual_count=int(residual_count or 0),
                    sample=sample,
                )
            )
        return out

    def apply_tmdb_enrichment(
        self,
        hits: Dict[str, str],
        misses,
    ) -> int:
        """Persist a provider-native enrichment batch and report new collapses.

        For each **hit** (``channel_id → tmdb_id`` discovered via the detail
        endpoint): store ``detected_tmdb_id``, recompute ``content_key`` through
        the SAME chokepoint the migration uses
        (:func:`~metatv.core.content_identity.content_key_for`, which is
        tmdb-first, so the recomputed key is ``"tmdb:{id}|{media_type}"``), and
        mark ``tmdb_enrich_state='fetched'``.  For each **miss** (attempted but the
        detail endpoint carried no id): mark ``tmdb_enrich_state='none'`` so the
        row is never re-fetched (until a content refresh resets it) — the residual
        ``NULL id + 'none'`` is the only-TMDb-API-addressable gap the analytics
        surface reports.

        Only these three generated fields are written — user tags / ratings /
        favorites are never touched (mirror-not-cage).

        Args:
            hits: ``{channel_id: tmdb_id}`` — validated digit-string ids.
            misses: Iterable of channel ids that were attempted but yielded no id.

        Returns:
            The number of *hit* rows whose recomputed ``content_key`` now appears
            on ≥ 2 rows — i.e. rows that landed in a shared collapse group this
            batch.  A positive count is the host's cue to refresh the views.
        """
        miss_ids = list(misses)
        if miss_ids:
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id.in_(miss_ids))
                .values(tmdb_enrich_state="none")
            )

        if not hits:
            self.session.commit()
            return 0

        hit_ids = list(hits.keys())
        # media_type is needed to namespace the tmdb key (movie vs series live in
        # separate TMDb id spaces) — project just that column, no raw_data blob.
        mt_by_id = dict(
            self.session.query(ChannelDB.id, ChannelDB.media_type)
            .filter(ChannelDB.id.in_(hit_ids))
            .all()
        )

        new_keys: Dict[str, str] = {}
        for cid, tmdb in hits.items():
            media_type = mt_by_id.get(cid) or ""
            # Read a proxy through content_key_for so identity has ONE definition;
            # a valid tmdb short-circuits to "tmdb:{id}|{media_type}".
            proxy = _TmdbKeyProxy(detected_tmdb_id=tmdb, media_type=media_type, id=cid)
            key = content_key_for(proxy)
            new_keys[cid] = key
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id == cid)
                .values(
                    detected_tmdb_id=tmdb,
                    content_key=key,
                    tmdb_enrich_state="fetched",
                )
            )

        self.session.commit()

        # New collapses: of the keys we just wrote, how many enriched rows now
        # share a key with at least one other row (a real fold, not a lone id).
        distinct_keys = set(new_keys.values())
        key_counts = dict(
            self.session.query(ChannelDB.content_key, func.count())
            .filter(ChannelDB.content_key.in_(distinct_keys))
            .group_by(ChannelDB.content_key)
            .all()
        )
        return sum(1 for key in new_keys.values() if key_counts.get(key, 0) >= 2)


    def apply_metadata_harvest(self, harvest: Dict[str, dict]) -> int:
        """Fill EMPTY metadata fields for fetched titles from their detail blob.

        ``harvest`` maps ``channel_id → :data:`_HARVEST_FIELDS`` parsed from
        the channel's ``get_vod_info`` / ``get_series_info`` response (see
        :func:`metatv.metadata_providers.raw_parse.harvest_detail_metadata`).  For
        each channel that HAS a linked ``MetadataDB`` row, only fields that are
        currently empty (generated data) are filled — a populated field (a better
        provider's value, or a user edit) is never overwritten (mirror-not-cage).

        For **movie** rows it also stamps the ``genre_enrich_state`` fetch-once
        marker: ``'fetched'`` when the detail blob carried a genre, ``'none'`` when
        it did not — so the one-time genre backfill never re-fetches the same title.
        Rows that errored during fetch are simply absent from *harvest*, so they are
        left unmarked and retried on a later pass (defer-on-error).

        Args:
            harvest: ``{channel_id: {field: value}}`` — see `_HARVEST_FIELDS`.

        Returns:
            The number of metadata rows whose ``genres`` were populated this call.
        """
        # Local: an import-scope edge from the repository layer to a metadata
        # provider module would be a new cross-layer dependency at load time.
        from metatv.metadata_providers.raw_parse import HARVEST_FIELDS

        cids = list(harvest.keys())
        if not cids:
            return 0

        # channel_id → (metadata_id, media_type) for the fetched rows.
        chan_rows = (
            self.session.query(
                ChannelDB.id, ChannelDB.metadata_id, ChannelDB.media_type
            )
            .filter(ChannelDB.id.in_(cids))
            .all()
        )
        meta_id_by_cid = {cid: mid for (cid, mid, _mt) in chan_rows if mid}
        media_by_cid = {cid: mt for (cid, _mid, mt) in chan_rows}

        meta_ids = list(set(meta_id_by_cid.values()))
        meta_by_id: Dict[str, MetadataDB] = {}
        if meta_ids:
            for meta in (
                self.session.query(MetadataDB)
                .filter(MetadataDB.id.in_(meta_ids))
                .all()
            ):
                meta_by_id[meta.id] = meta

        filled = 0
        movie_fetched: List[str] = []  # got a genre → mark 'fetched'
        movie_none: List[str] = []     # attempted, no genre → mark 'none'

        for cid, h in harvest.items():
            has_genre = bool(h.get("genres"))
            if media_by_cid.get(cid) == "movie":
                (movie_fetched if has_genre else movie_none).append(cid)

            meta = meta_by_id.get(meta_id_by_cid.get(cid))
            if meta is None:
                continue  # no metadata row to fill (not a scoring candidate anyway)

            # Fill-only-empty. Artwork only became reachable when the harvest
            # started KEEPING the detail blob's image (2026-08-23): before that
            # a title whose catalog carries ``stream_icon: null`` had no route
            # back to a poster once its stored one was lost.
            for field in HARVEST_FIELDS:
                if not getattr(meta, field) and h.get(field):
                    setattr(meta, field, h[field])
                    if field == "genres":
                        filled += 1

        if movie_fetched:
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id.in_(movie_fetched))
                .values(genre_enrich_state="fetched")
            )
        if movie_none:
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id.in_(movie_none))
                .values(genre_enrich_state="none")
            )
        self.session.commit()
        return filled

    # ── Background metadata enrichment (roadmap #249) ─────────────────────────

    def _metadata_enrichment_filter(self, query, excluded_provider_ids, stale_before):
        """Apply the shared metadata-enrichment-candidate predicate to *query*.

        A candidate is a visible movie/series row with no cached metadata (no
        ``metadata_id``, or one whose ``MetadataDB.fetched_at`` is NULL) or whose
        cached metadata predates *stale_before*, that has not exhausted its retry
        budget (``metadata_enrich_state IS NULL`` — the only other value,
        ``'failed'``, permanently skips a row that kept erroring). Single
        definition shared by the candidate select and its count so they can never
        drift.  Assumes *query* already selects from ``ChannelDB``.
        """
        query = (
            query
            .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
            .filter(ChannelDB.is_hidden.is_(False))
            .filter(ChannelDB.media_type.in_(("movie", "series")))
            .filter(ChannelDB.metadata_enrich_state.is_(None))
            .filter(
                or_(
                    ChannelDB.metadata_id.is_(None),
                    MetadataDB.fetched_at.is_(None),
                    MetadataDB.fetched_at < stale_before,
                )
            )
        )
        if excluded_provider_ids:
            query = query.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        return query

    def select_metadata_enrichment_candidates(
        self,
        limit: int,
        excluded_provider_ids: Optional[Set[str]] = None,
        stale_before: Optional[datetime] = None,
    ) -> List[Dict[str, str]]:
        """Select up to *limit* channels needing metadata enrichment, engaged-first.

        Ordered in SQL: engaged channels (favorited, queued, or played — the same
        predicate :meth:`_engaged_channel_predicate` uses to protect channels on
        provider delete) sort before the remainder, so a background pass surfaces
        value the user will actually notice first instead of only after a full
        library crawl. Ties broken by ``id`` for a deterministic, resumable order.

        Args:
            limit: Max rows to return (one drain batch).
            excluded_provider_ids: Hidden providers (inactive ∪ expired) from
                ``ProviderRepository.get_hidden_provider_ids()`` — never enriched.
            stale_before: Cached metadata with ``fetched_at`` older than this
                counts as due for refresh.

        Returns:
            List of ``{"id", "name"}`` dicts, engaged rows first (plain dicts —
            no ORM objects escape the session).
        """
        from sqlalchemy import case

        q = self._metadata_enrichment_filter(
            self.session.query(ChannelDB.id, ChannelDB.name),
            excluded_provider_ids, stale_before,
        )
        engaged = self._engaged_channel_predicate()
        q = q.order_by(case((engaged, 0), else_=1), ChannelDB.id).limit(limit)
        return [{"id": cid, "name": name} for (cid, name) in q.all()]

    def count_metadata_enrichment_candidates(
        self,
        excluded_provider_ids: Optional[Set[str]] = None,
        stale_before: Optional[datetime] = None,
    ) -> int:
        """Count the full metadata-enrichment work set (same predicate as select)."""
        q = self._metadata_enrichment_filter(
            self.session.query(func.count(ChannelDB.id)),
            excluded_provider_ids, stale_before,
        )
        return q.scalar() or 0
