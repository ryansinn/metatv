"""TmdbEnrichmentManager — provider-native TMDb-id backfill for idless VOD rows.

Phase 2 of content collapsing (NO external TMDb API key).  Content-identity
Slice 3 (#317) captured the provider's *list-row* ``tmdb`` field into
``detected_tmdb_id`` at ingestion, but ~200k visible VOD rows ship a list row
with **no** id.  This manager fills those in by calling the provider's OWN detail
endpoint — ``get_vod_info`` for movies, ``get_series_info`` for series — which
carries ``info.tmdb_id`` even when the list omitted it.  A hit stores the id and
recomputes ``content_key`` through the same chokepoint the migration uses
(:func:`~metatv.core.content_identity.content_key_for`), so cross-language /
quality variants whose list row omitted the id finally collapse onto one card.

Design (matches the non-negotiables in the Phase-2 spec)
-------------------------------------------------------
* **Background + off-thread.**  A single-worker ``ThreadPoolExecutor`` (SQLite is
  a single writer) runs one enrichment *pass* per launch; the network fetches run
  inside one ``asyncio`` event loop on that worker thread.  Nothing touches Qt
  widgets — the only cross-thread hop is the ``collapses_found`` signal, which
  Qt auto-queues onto the main thread where the host refreshes the views.
* **Resumable / hit-at-most-once.**  A persistent per-row marker
  (``ChannelDB.tmdb_enrich_state``: ``NULL`` = unattempted, ``'none'`` =
  attempted-but-empty, ``'done'`` = id found) is written after every attempt, so
  an idless row is fetched at most once.  It is reset to ``NULL`` only when the
  source is content-refreshed (``ChannelRepository.reset_tmdb_enrich_state`` from
  ``provider_loader``) so genuinely new catalog data re-attempts.
* **Rate-limited + per-session cap.**  At most ``session_cap`` rows are attempted
  per launch (default 500), concurrency is capped per provider (default 4), and a
  gentle throttle spaces requests — so the ~200k backlog spreads across launches
  instead of blasting the provider at once.  A run of consecutive errors aborts
  the offending provider for the session (no retry storm; deferred to next
  launch).
* **UA required.**  All calls go through ``XtreamAPI``, which already sends the
  canonical app User-Agent (``metatv.core.http_headers.stream_user_agent``); the
  provider 403s / returns empty without it.
* **Generated-data only.**  Only ``detected_tmdb_id`` / ``content_key`` /
  ``tmdb_enrich_state`` (all generated) are written — user tags/ratings/favorites
  are never touched (mirror-not-cage).

Deferred (Phase 2b, NOT built here)
-----------------------------------
The ~69% of idless rows whose detail endpoint *also* carries no tmdb id are the
separate "TMDb-API title-search" tail.  That needs an external TMDb API key and
is intentionally out of scope for this provider-native pass.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

from metatv.core.content_identity import valid_tmdb_id

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.models import Provider


# Politeness / cap defaults (overridable via Config).  Kept conservative so a
# first launch on a fresh library never hammers the provider.
_DEFAULT_SESSION_CAP = 500      # max rows attempted per launch
_DEFAULT_CONCURRENCY = 4        # max concurrent requests per provider
_DEFAULT_THROTTLE_MS = 150      # sleep before each request
_CONSECUTIVE_ERROR_ABORT = 10   # abort a provider after this many errors in a row


def _extract_tmdb_id(data: Any) -> str | None:
    """Pull a valid TMDb id out of a ``get_vod_info`` / ``get_series_info`` response.

    Both endpoints nest the id under ``info.tmdb_id`` (some providers use the
    legacy ``info.tmdb``).  The value is validated through the shared
    :func:`~metatv.core.content_identity.valid_tmdb_id` so provider sentinels
    (``""`` / ``"0"`` / ``"null"``) are rejected exactly as at ingestion.

    Args:
        data: The parsed JSON response dict (or anything, defensively).

    Returns:
        The canonical id digit-string, or ``None`` when the response carries no
        real id.
    """
    if not isinstance(data, dict):
        return None
    info = data.get("info")
    if not isinstance(info, dict):
        return None
    return valid_tmdb_id(info.get("tmdb_id") if info.get("tmdb_id") is not None else info.get("tmdb"))


class TmdbEnrichmentManager(QObject):
    """Backfill ``detected_tmdb_id`` for idless VOD rows via provider detail endpoints.

    Signals
    -------
    collapses_found : pyqtSignal(int)
        Emitted (auto-queued onto the main thread) after a pass whose newly
        written ids produced at least one *new collapse* — i.e. an enriched row's
        recomputed ``content_key`` now matches another visible row.  The host
        connects this to ``_refresh_provider_dependent_views`` so Discover / Recipe
        / the channel list reflect the new folds without a restart.  The int is
        the number of rows that landed in a shared group this pass.
    """

    collapses_found = pyqtSignal(int)

    def __init__(
        self,
        db: "Database",
        config: "Config",
        parent=None,
    ) -> None:
        """
        Args:
            db: Database handle (worker uses ``session_scope``).
            config: Application config (toggle + politeness knobs).
            parent: Qt parent (keeps the QObject on the main thread).
        """
        super().__init__(parent)
        self.db = db
        self.config = config
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="tmdb_enrich"
        )
        self._busy = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Kick off one enrichment pass if enabled and not already running.

        Safe to call from any thread (the work runs in the executor).  Intended
        to be invoked once, throttled after startup via ``QTimer.singleShot``.
        """
        if not getattr(self.config, "tmdb_enrichment_enabled", True):
            logger.debug("tmdb_enrich: disabled by config, skipping")
            return
        if self._busy:
            logger.debug("tmdb_enrich: pass already running, skipping")
            return
        self._busy = True
        self._executor.submit(self._worker_run)

    def shutdown(self) -> None:
        """Shut down the executor without blocking the main thread.

        A pass in flight is abandoned; because markers are written only *after*
        each fetch completes, an abandoned pass simply leaves those rows
        unattempted for next launch (resumable).
        """
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Worker — runs in the executor (NO widget access)
    # ------------------------------------------------------------------

    def _worker_run(self) -> None:
        """One enrichment pass: select candidates → fetch → persist → signal."""
        try:
            collapses = self._run_pass()
            if collapses > 0:
                # Auto-queued onto the main thread (this QObject lives there).
                self.collapses_found.emit(collapses)
        except Exception:
            logger.exception("tmdb_enrich: enrichment pass failed")
        finally:
            self._busy = False

    def _run_pass(self) -> int:
        """Execute a capped pass; return the number of new collapses produced."""
        from metatv.core.repositories import RepositoryFactory

        session_cap = int(getattr(self.config, "tmdb_enrichment_session_cap", _DEFAULT_SESSION_CAP))
        concurrency = max(1, int(getattr(self.config, "tmdb_enrichment_concurrency", _DEFAULT_CONCURRENCY)))
        throttle = max(0.0, float(getattr(self.config, "tmdb_enrichment_throttle_ms", _DEFAULT_THROTTLE_MS)) / 1000.0)

        # 1. (read) select candidates scoped to visible/active providers, splitting
        #    the session cap FAIRLY across sources (so the largest provider can't
        #    starve the others for hundreds of launches), and resolve each involved
        #    provider's credentials to a domain Provider while the session is open
        #    (ORM → domain model boundary).
        with self.db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            excluded = set(repos.providers.get_hidden_provider_ids())

            provider_ids = repos.channels.provider_ids_with_tmdb_candidates(excluded)
            if not provider_ids:
                logger.debug("tmdb_enrich: no idless VOD candidates to attempt")
                return 0

            per_provider = max(1, session_cap // len(provider_ids))
            by_provider: dict[str, list[dict]] = {}
            taken = 0
            for pid in provider_ids:
                if taken >= session_cap:
                    break
                slice_limit = min(per_provider, session_cap - taken)
                rows = repos.channels.select_tmdb_enrichment_candidates(
                    limit=slice_limit,
                    provider_id=pid,
                )
                if rows:
                    by_provider[pid] = rows
                    taken += len(rows)

            candidates = [r for rows in by_provider.values() for r in rows]
            if not candidates:
                return 0

            providers: dict[str, "Provider"] = {}
            for pid in by_provider:
                pdb = repos.providers.get_by_id(pid)
                if pdb is not None:
                    providers[pid] = repos.providers.to_model(pdb)

        logger.info(
            "tmdb_enrich: attempting {} idless VOD row(s) across {} provider(s) "
            "(cap={}, concurrency={})",
            len(candidates), len(providers), session_cap, concurrency,
        )

        # 2. (network) fetch all rows for all providers inside one event loop.
        results = asyncio.run(
            self._fetch_all(by_provider, providers, concurrency, throttle)
        )

        # 3. (write) persist per provider and accumulate the collapse count.
        total_collapses = 0
        total_hits = 0
        total_miss = 0
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            for pid, (hits, misses, errors) in results.items():
                total_hits += len(hits)
                total_miss += len(misses)
                total_collapses += repos.channels.apply_tmdb_enrichment(hits, misses)
                if errors:
                    logger.info(
                        "tmdb_enrich: provider {} had {} error(s) (rows deferred to next launch)",
                        pid, errors,
                    )

        deferred = len(candidates) - total_hits - total_miss
        logger.info(
            "tmdb_enrich: pass complete — {} id(s) found, {} empty, {} deferred, "
            "{} new collapse(s)",
            total_hits, total_miss, deferred, total_collapses,
        )
        return total_collapses

    # ------------------------------------------------------------------
    # Async network phase
    # ------------------------------------------------------------------

    async def _fetch_all(
        self,
        by_provider: dict[str, list[dict]],
        providers: dict[str, "Provider"],
        concurrency: int,
        throttle: float,
    ) -> dict[str, tuple[dict[str, str], list[str], int]]:
        """Fetch every candidate row, one provider at a time (bounded concurrency).

        Providers are processed sequentially so overall concurrency never exceeds
        ``concurrency`` (politeness); within a provider, requests fan out up to
        ``concurrency`` at a time through a shared ``XtreamAPI`` session (so the
        UA-bearing connection is reused rather than re-opened per call).

        Returns:
            ``{provider_id: (hits{channel_id: tmdb_id}, misses[channel_id], errors)}``.
        """
        out: dict[str, tuple[dict[str, str], list[str], int]] = {}
        for pid, rows in by_provider.items():
            provider = providers.get(pid)
            if provider is None:
                logger.warning("tmdb_enrich: provider {} not found, deferring its rows", pid)
                out[pid] = ({}, [], len(rows))
                continue
            out[pid] = await self._fetch_provider(provider, rows, concurrency, throttle)
        return out

    async def _fetch_provider(
        self,
        provider: "Provider",
        rows: list[dict],
        concurrency: int,
        throttle: float,
    ) -> tuple[dict[str, str], list[str], int]:
        """Fetch one provider's candidate rows through a single reused session."""
        from metatv.providers.xtream import XtreamAPI

        base_urls = provider.ordered_urls() if provider.type == "xtream" else []
        if not base_urls:
            logger.warning(
                "tmdb_enrich: provider {} has no usable URL (type={}), deferring",
                provider.name, provider.type,
            )
            return ({}, [], len(rows))

        base_url = base_urls[0]
        try:
            async with XtreamAPI(base_url, provider.username, provider.password) as api:
                return await self._run_calls(api, rows, concurrency, throttle)
        except Exception:
            # Session-level failure (rare — connect happens per request): defer all.
            logger.exception("tmdb_enrich: session error for provider {}", provider.name)
            return ({}, [], len(rows))

    async def _run_calls(
        self,
        api,
        rows: list[dict],
        concurrency: int,
        throttle: float,
    ) -> tuple[dict[str, str], list[str], int]:
        """Issue the detail calls with a semaphore + throttle; classify each row.

        A per-row exception is counted (not fatal); after
        ``_CONSECUTIVE_ERROR_ABORT`` errors in a row the remaining rows are left
        unattempted (deferred) so a dead provider can't drive a retry storm.
        """
        sem = asyncio.Semaphore(concurrency)
        hits: dict[str, str] = {}
        misses: list[str] = []
        errors = 0
        consecutive = 0
        aborted = asyncio.Event()

        async def one(row: dict) -> None:
            nonlocal errors, consecutive
            if aborted.is_set():
                return
            async with sem:
                if aborted.is_set():
                    return
                if throttle:
                    await asyncio.sleep(throttle)
                cid = row["id"]
                sid = row["source_id"]
                media_type = row["media_type"]
                try:
                    if media_type == "series":
                        data = await api.get_series_info(sid)
                    else:
                        data = await api.get_vod_info(sid)
                except Exception:
                    errors += 1
                    consecutive += 1
                    if consecutive >= _CONSECUTIVE_ERROR_ABORT and not aborted.is_set():
                        aborted.set()
                        logger.warning(
                            "tmdb_enrich: aborting provider after {} consecutive errors",
                            consecutive,
                        )
                    return
                consecutive = 0
                tmdb = _extract_tmdb_id(data)
                if tmdb:
                    hits[cid] = tmdb
                else:
                    misses.append(cid)

        await asyncio.gather(*(one(r) for r in rows))
        return hits, misses, errors
