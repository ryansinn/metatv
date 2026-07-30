"""TmdbEnrichmentManager — lazy, on-demand provider-native TMDb-id backfill.

Phase 2 of content collapsing (NO external TMDb API key).  Content-identity
Slice 3 (#317) captured the provider's *list-row* ``tmdb`` field into
``detected_tmdb_id`` at ingestion, but many visible VOD rows ship a list row with
**no** id.  This manager fills those in by calling the provider's OWN detail
endpoint — ``get_vod_info`` for movies, ``get_series_info`` for series — which
carries ``info.tmdb_id`` even when the list omitted it.  A hit stores the id and
recomputes ``content_key`` through the same chokepoint the migration uses
(:func:`~metatv.core.content_identity.content_key_for`), so cross-language /
quality variants whose list row omitted the id finally collapse onto one card.

Lazy / on-demand (the reshape — supersedes the startup bulk sweep)
------------------------------------------------------------------
There is **no launch sweep and no per-session cap**.  Instead the manager exposes
:meth:`enqueue` — result surfaces (Discover shelves, Recipe "Matching Content",
the channel list, search, details "Other Versions") feed it the **bare channel
ids they just loaded**; the worker narrows those to real candidates off-thread
(:meth:`ChannelRepository.select_tmdb_candidates_by_ids`) and fetches only what
the user is actually looking at.  "Visible" = the loaded page/batch — there is no
scroll-viewport tracking (kept deliberately simple).

Design (non-negotiables preserved from Phase 2)
-----------------------------------------------
* **Background + off-thread.**  A single-worker ``ThreadPoolExecutor`` (SQLite is
  a single writer) drains the queue in throttled batches; network fetches run
  inside one ``asyncio`` loop per batch on that worker thread.  Nothing touches Qt
  widgets — the only cross-thread hops are the ``collapses_found`` and
  ``enrichment_progress`` signals, which Qt auto-queues onto the main thread.  The
  worker **never** calls ``NotificationManager`` directly (it makes a main-thread
  ``QTimer``) — it emits a signal a main-thread slot renders.
* **Fetch-at-most-once.**  Every attempt writes the persistent per-row marker
  ``ChannelDB.tmdb_enrich_state`` (``'fetched'`` on a hit, ``'none'`` on empty);
  a marked or id-bearing row is filtered out of every future enqueue.  In-session
  a ``_seen`` set drops re-enqueues cheaply before they ever hit the DB.
* **Rate-limited.**  Per-provider concurrency cap (default 4) + a gentle
  per-request throttle; a run of consecutive errors aborts that provider for the
  batch (no retry storm).
* **UA required.**  All calls go through ``XtreamAPI``, which already sends the
  canonical app User-Agent; the provider 403s / returns empty without it.
* **Generated-data only.**  Only ``detected_tmdb_id`` / ``content_key`` /
  ``tmdb_enrich_state`` (all generated) are written — user data is untouched.

Deferred (Phase 2b, NOT built here)
-----------------------------------
Rows whose detail endpoint *also* carries no id (marker ``'none'``) are the
separate "TMDb-API title-search" tail — the only-TMDb-API-addressable residual the
"Missing TMDb data" analytics surface reports.  It needs an external key and is
intentionally out of scope for this provider-native pass.
"""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

from metatv.core.content_identity import valid_tmdb_id

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.models import Provider


# Politeness defaults (overridable via Config).
_DEFAULT_CONCURRENCY = 4        # max concurrent requests per provider
_DEFAULT_THROTTLE_MS = 150      # sleep before each request
_CONSECUTIVE_ERROR_ABORT = 10   # abort a provider after this many errors in a row
_DRAIN_BATCH = 40               # candidates resolved + fetched per drain iteration


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
    """Lazily backfill ``detected_tmdb_id`` for idless VOD rows the user is viewing.

    Signals
    -------
    collapses_found : pyqtSignal(int)
        Emitted (auto-queued onto the main thread) after a drain batch whose newly
        written ids produced at least one *new collapse* — an enriched row's
        recomputed ``content_key`` now matches another visible row.  The host
        connects this to ``_refresh_provider_dependent_views`` so the views
        re-collapse (a gentle settle) without a restart.
    enrichment_progress : pyqtSignal(str, str, int)
        ``(provider_id, provider_name, in_flight_count)``.  A main-thread slot
        renders ONE coalesced "Updating N titles from {name}…" toast per source:
        ``count > 0`` shows/updates it, ``count == 0`` clears it.  This also
        explains the re-collapse reflow.  Emitted only from the main-thread-owned
        QObject (never a direct NotificationManager call from the worker).
    """

    collapses_found = pyqtSignal(int)
    enrichment_progress = pyqtSignal(str, str, int)

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
            parent: Qt parent (keeps the QObject on the main thread so its signals
                auto-queue back onto it).
        """
        super().__init__(parent)
        self.db = db
        self.config = config
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="tmdb_enrich"
        )
        self._lock = threading.Lock()
        # Insertion-ordered dedup set of channel ids awaiting a fetch.
        self._queue: "OrderedDict[str, None]" = OrderedDict()
        # Ids ever enqueued this session — drops re-enqueues (and non-candidates)
        # cheaply so a surface re-render doesn't re-hit the DB for the same rows.
        self._seen: set[str] = set()
        # Live in-flight counts + names per provider, for the coalesced toast.
        self._inflight: dict[str, int] = {}
        self._provider_names: dict[str, str] = {}
        self._busy = False
        self._shutdown = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, channel_ids) -> None:
        """Queue channel ids a result surface just loaded for lazy enrichment.

        Safe to call from the main thread (the fetch runs in the executor).  Ids
        already seen this session, or that turn out not to be candidates, are
        dropped; the actual idless/unattempted filtering happens off-thread in the
        worker.  Kicks the drain worker when it is idle.

        Args:
            channel_ids: An iterable of channel ids (the loaded page/batch).
        """
        if self._shutdown or not channel_ids:
            return
        if not getattr(self.config, "tmdb_enrichment_enabled", True):
            return
        with self._lock:
            if self._shutdown:
                return
            added = False
            for cid in channel_ids:
                if cid and cid not in self._seen:
                    self._seen.add(cid)
                    self._queue[cid] = None
                    added = True
            if not added or self._busy:
                return
            self._busy = True
        self._executor.submit(self._worker_drain)

    def shutdown(self) -> None:
        """Shut down the executor without blocking the main thread.

        A drain in flight is abandoned; because markers are written only *after*
        each fetch completes, an abandoned batch leaves those rows unattempted for
        a future enqueue / next launch (resumable).
        """
        with self._lock:
            self._shutdown = True
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Worker — runs in the single-worker executor (NO widget access)
    # ------------------------------------------------------------------

    def _worker_drain(self) -> None:
        """Drain the queue in throttled batches until it is empty.

        The single-worker executor serialises drains, so ``_inflight`` is never
        touched by two drains at once.  ``_busy`` is cleared atomically with the
        empty-queue check (same lock acquisition) so an ``enqueue`` racing the end
        of a drain always re-kicks — no lost wakeup.
        """
        try:
            while True:
                with self._lock:
                    if self._shutdown or not self._queue:
                        self._busy = False
                        break
                    batch_ids = list(islice(self._queue.keys(), _DRAIN_BATCH))
                    for cid in batch_ids:
                        del self._queue[cid]
                try:
                    self._process_batch(batch_ids)
                except Exception:
                    logger.exception("tmdb_enrich: drain batch failed")
        finally:
            # Clear every source's toast now the drain is done (queue drained).
            self._clear_all_inflight()

    def _process_batch(self, batch_ids: list[str]) -> None:
        """Resolve → fetch → persist one drain batch; signal progress + collapses."""
        from metatv.core.repositories import RepositoryFactory

        concurrency = max(1, int(getattr(self.config, "tmdb_enrichment_concurrency", _DEFAULT_CONCURRENCY)))
        throttle = max(0.0, float(getattr(self.config, "tmdb_enrichment_throttle_ms", _DEFAULT_THROTTLE_MS)) / 1000.0)

        # 1. (read) narrow the queued ids to real candidates, group by provider,
        #    and resolve each provider's credentials to a domain model while the
        #    session is open (ORM → domain boundary).
        with self.db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            excluded = set(repos.providers.get_hidden_provider_ids())
            rows = repos.channels.select_tmdb_candidates_by_ids(batch_ids, excluded)
            if not rows:
                return

            by_provider: dict[str, list[dict]] = {}
            for r in rows:
                by_provider.setdefault(r["provider_id"], []).append(r)

            providers: dict[str, "Provider"] = {}
            names: dict[str, str] = {}
            for pid in list(by_provider):
                pdb = repos.providers.get_by_id(pid)
                if pdb is None:
                    del by_provider[pid]
                    continue
                providers[pid] = repos.providers.to_model(pdb)
                names[pid] = pdb.name

        if not by_provider:
            return

        # 2. (notify) publish the live per-source count → main-thread toast.
        self._begin_inflight(by_provider, names)

        # 3. (network + write) one provider at a time.
        total_collapses = 0
        for pid, prows in by_provider.items():
            hits, misses, errors = asyncio.run(
                self._fetch_provider(providers[pid], prows, concurrency, throttle)
            )
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                total_collapses += repos.channels.apply_tmdb_enrichment(hits, misses)
            if errors:
                logger.info(
                    "tmdb_enrich: provider {} had {} error(s) this batch", pid, errors
                )
            logger.debug(
                "tmdb_enrich: {} — {} hit(s), {} empty of {} attempted",
                names.get(pid, pid), len(hits), len(misses), len(prows),
            )

        # 4. (settle) one refresh per batch drives the re-collapse (the toast
        #    explains the reflow); emitted only when a real fold happened.
        if total_collapses > 0:
            self.collapses_found.emit(total_collapses)

    # ------------------------------------------------------------------
    # In-flight accounting for the coalesced per-source toast
    # ------------------------------------------------------------------

    def _begin_inflight(self, by_provider: dict[str, list[dict]], names: dict[str, str]) -> None:
        """Record + emit each provider's current in-flight count for this batch."""
        with self._lock:
            for pid, prows in by_provider.items():
                self._inflight[pid] = len(prows)
                self._provider_names[pid] = names.get(pid, pid)
        for pid, prows in by_provider.items():
            self.enrichment_progress.emit(pid, names.get(pid, pid), len(prows))

    def _clear_all_inflight(self) -> None:
        """Emit a zero count for every source with an open toast (drain finished)."""
        with self._lock:
            pids = list(self._inflight.keys())
            names = dict(self._provider_names)
            self._inflight.clear()
            self._provider_names.clear()
            shutting = self._shutdown
        if shutting:
            return
        for pid in pids:
            self.enrichment_progress.emit(pid, names.get(pid, pid), 0)

    # ------------------------------------------------------------------
    # Async network phase (reused from the Phase-2 base)
    # ------------------------------------------------------------------

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
