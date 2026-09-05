"""EPG guide download/store path — extracted from ``epg_manager.py`` (DEBT-8).

``epg_manager.py`` sat at its code-health ratchet ceiling; this module holds the
one cohesive concern that could be pulled out cleanly: resolve the fetch URL(s),
download + parse the XMLTV guide (with connection-accountant arbitration and
host cycling), and store the result. Behaviour-preserving — every method below
moved verbatim from ``EpgManager``.

``_EpgFetchMixin`` is mixed into ``EpgManager`` (``class EpgManager(_EpgFetchMixin,
QObject)``) rather than used standalone: a mixin cannot own PyQt signals, so
``refresh_started``/``refresh_finished``/``refresh_error``/``_notify``/
``_progress_update``/``_progress_done``/``_progress_error`` stay declared on
``EpgManager`` and the methods here reach them via ``self.<signal>`` exactly as
before. ``build_epg_url``/``effective_epg_url`` are public API named in
CLAUDE.md ("resolve the fetch URL via ``EpgManager.effective_epg_url(provider)``")
and STAY on ``EpgManager``; this mixin calls ``self.effective_epg_url(...)`` /
``self.build_epg_url(...)`` exactly as the pre-split code did.

Attributes/methods the host (``EpgManager``) must provide — all created in
``EpgManager.__init__`` except where noted:

- ``self.db`` — the ``Database`` instance.
- ``self._executor`` — the single-worker ``ThreadPoolExecutor``.
- ``self._active_refreshes`` — ``set[str]`` of provider IDs mid-refresh.
- ``self._accountant`` — ``ConnectionAccountant`` or ``None`` (headless/tests).
- ``self._evicted_holders`` / ``self._evicted_lock`` — EPG-2b eviction bookkeeping.
- ``self._shutting_down`` — ``bool``, flips ``True`` in ``shutdown()``.
- ``self.notifications`` — ``NotificationManager`` or ``None``.
- Signals: ``refresh_started``, ``refresh_finished``, ``refresh_error``,
  ``_progress_update``, ``_progress_done``, ``_progress_error``.
- ``self._show_notification(...)`` — thread-safe toast helper.
- ``self.effective_epg_url(...)`` / ``self.build_epg_url(...)`` — stay defined
  on ``EpgManager`` (public API); called here via ``self``.
- ``self._build_match_map(...)`` / ``self.prune_expired(...)`` — stay defined
  on ``EpgManager``; called here via ``self``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from loguru import logger

from metatv.core.database import EpgProgramDB, ProviderDB
from metatv.core.epg_utils import EPG_FILLER_THRESHOLD, now_utc
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.epg import delete_programmes_chunked
from metatv.core.repositories.provider import persist_url_stats
from metatv.core.url_cycle import UrlCycler
from metatv.core.xmltv_parser import (
    XmltvAborted,
    XmltvChannel,
    XmltvEvicted,
    XmltvProgramme,
    parse_xmltv_url,
)


def _compute_honest_guide_end(
    programmes: list[XmltvProgramme],
) -> datetime | None:
    """Return the maximum ``stop_time`` among non-filler programmes.

    A programme is "filler" when its duration exceeds ``EPG_FILLER_THRESHOLD``
    (12h) — e.g. a multi-day "Program" placeholder — which would otherwise
    inflate ``epg_data_end`` past the real schedule depth and make Browse show
    nothing while the provider appears "good through" a far-future date. Falls
    back to the filler-only max when every programme is filler, so the result
    is never ``None`` when ``programmes`` is non-empty.
    """
    real_end: datetime | None = None
    filler_end: datetime | None = None

    for prog in programmes:
        if (prog.stop_time - prog.start_time) > EPG_FILLER_THRESHOLD:
            if filler_end is None or prog.stop_time > filler_end:
                filler_end = prog.stop_time
        else:
            if real_end is None or prog.stop_time > real_end:
                real_end = prog.stop_time

    return real_end if real_end is not None else filler_end


#: Consumer kind a guide fetch registers with :class:`ConnectionAccountant`.
#: Background catch-up work: it must never outrank something the user asked for.
EPG_KIND = "monitor"

#: A guide fetch displaces nothing.
EPG_PREEMPTS: tuple[str, ...] = ()

#: Prefix of every guide-fetch accountant holder id — see ``_fetch_holder_id``.
_EPG_FETCH_HOLDER_PREFIX = "epg_fetch:"


@dataclass
class GuideFetch:
    """Result of a guide download (EPG-2b). ``partial``: playback pre-empted
    the fetch, so ``programmes`` holds only the rows fully parsed before
    eviction — never a half-read one, per xmltv_parser's "end"-event guarantee.
    """

    channels: list[XmltvChannel]
    programmes: list[XmltvProgramme]
    partial: bool = False


class _EpgFetchMixin:
    """Guide download → parse → store, mixed into ``EpgManager``. See module
    docstring for the attributes/signals the host must provide."""

    def _acquire_slot(self, provider_id: str, holder_id: str) -> bool:
        """Take a connection slot for a guide fetch; False if none is free.

        No accountant (tests/headless) means nothing to arbitrate.
        """
        if self._accountant is None:
            return True
        try:
            return self._accountant.acquire(
                provider_id, EPG_KIND, holder_id,
                preempt_kinds=EPG_PREEMPTS).granted
        except Exception:
            logger.exception("epg: connection acquire failed")
            return True

    def _release_slot(self, provider_id: str, holder_id: str) -> None:
        """Release the slot :meth:`_acquire_slot` took."""
        if self._accountant is None:
            return
        try:
            self._accountant.release(provider_id, holder_id)
        except Exception:
            logger.exception("epg: connection release failed")

    @staticmethod
    def _fetch_holder_id(provider_id: str) -> str:
        """The accountant holder id for a guide fetch — built once, so the
        acquire site and the eviction listener can't drift apart on its shape
        (mirrors ``TmdbEnrichmentManager``)."""
        return f"{_EPG_FETCH_HOLDER_PREFIX}{provider_id}"

    def _on_slot_preempted(self, provider_id: str, holder_id: str, kind: str) -> None:
        """Accountant callback (any thread, EPG-2b): note a guide fetch was evicted.

        Every listener hears every eviction, so screen on the prefix first.
        """
        if holder_id.startswith(_EPG_FETCH_HOLDER_PREFIX):
            with self._evicted_lock:
                self._evicted_holders.add(holder_id)

    def _start_refresh(self, provider_id: str, provider_name: str, force: bool) -> None:
        self._active_refreshes.add(provider_id)
        self.refresh_started.emit(provider_id)

        # Create progress notification on the main thread; pass ID to worker
        notif_id: str | None = None
        if self.notifications:
            notif_id = self.notifications.show_progress(
                title=f"EPG: {provider_name}",
                total=None,  # indeterminate — we don't know the total yet
            )
            self.notifications.update(notif_id, message="Connecting…")

        self._executor.submit(
            self._fetch_worker, provider_id, provider_name, notif_id
        )

    def _resolve_and_fetch_guide(
        self, provider_id: str, provider_name: str,
        on_parse_progress: Callable[[int], None],
    ) -> GuideFetch:
        """Resolve the fetch URL(s) for *provider_id* and return the first working guide.

        A non-empty ``epg_url_override`` is fetched once, verbatim, with no
        cycling. With no override, hosts are tried in reliability order via
        ``UrlCycler`` (CLAUDE.md: cycling has exactly one path, never a bare
        loop over ``ordered_urls()``) until one returns a parseable, non-empty
        guide; ``record_success``/``record_failure`` follow EVERY attempt,
        flushed via ``persist_url_stats`` before the next. No response-time is
        recorded — mirrors the ``fetch_channels`` latency exclusion, since a
        bulk XMLTV download would make ``median_latency_ms()`` meaningless.

        A guide that parses but is already expired is NOT a failure and does
        NOT advance to the next host — every host on a panel serves the same
        guide, so re-downloading identical stale content elsewhere would be a
        harm. Staleness is handled later, by ``needs_refresh()`` — never here.

        Returns:
            A :class:`GuideFetch` from whichever host succeeded (or was
            evicted) first.

        Raises:
            Exception: whatever the last attempt raised, or ``RuntimeError``
                if there were no hosts, or every host returned an empty guide.
        """
        with self.db.session_scope(commit=False) as session:
            provider_db = session.query(ProviderDB).filter_by(id=provider_id).first()
            if provider_db is None:
                raise RuntimeError(f"Provider {provider_id} not found")
            override = (getattr(provider_db, "epg_url_override", None) or "").strip()
            provider_model = (
                None if override
                else RepositoryFactory(session).providers.to_model(provider_db)
            )

        if override:
            try:
                channels, programmes = parse_xmltv_url(
                    override, timeout=180, on_progress=on_parse_progress,
                )
            except XmltvEvicted as e:
                return GuideFetch(e.channels, e.programmes, partial=True)
            return GuideFetch(channels, programmes)

        cycler = UrlCycler(provider_model, "fetch_epg")
        candidates = cycler.candidates()
        if not candidates:
            raise RuntimeError(f"No configured hosts for provider {provider_name!r}")

        # Hold a real slot so playback/downloads/recordings can SEE this fetch
        # and evict it (EPG-2b) — a guide is large and slow, so losing a
        # stream to it is the worst possible trade.
        _holder = self._fetch_holder_id(getattr(provider_model, "id", provider_name))
        if not self._acquire_slot(getattr(provider_model, "id", ""), _holder):
            raise RuntimeError(
                f"Provider {provider_name!r} is busy with playback — "
                f"deferring the guide fetch")

        try:
            last_error: Exception | None = None
            for base_url in candidates:
                url = self.build_epg_url(provider_model, base_url=base_url)
                if not url:
                    continue
                try:
                    channels, programmes = parse_xmltv_url(
                        url, timeout=180, on_progress=on_parse_progress,
                    )
                except XmltvAborted:
                    # Says nothing about base_url. Recording it would penalise a
                    # blameless host — and the loop would then abort identically
                    # on every remaining one, so one app close would mark them all
                    # unreliable.
                    raise
                except XmltvEvicted as e:
                    # Same reasoning as XmltvAborted just above: not a host
                    # failure, and every remaining host would evict identically.
                    return GuideFetch(e.channels, e.programmes, partial=True)
                except Exception as e:
                    logger.warning(
                        f"EPG fetch failed for {provider_name} @ {base_url}: {e}"
                    )
                    cycler.record_failure(base_url, str(e))
                    if cycler.dirty:
                        persist_url_stats(self.db, provider_model)
                    last_error = e
                    continue

                if not programmes:
                    logger.warning(
                        f"EPG fetch from {base_url} returned an empty guide (0 "
                        f"programmes) for {provider_name} — trying next host"
                    )
                    cycler.record_failure(base_url, "empty guide (0 programmes)")
                    if cycler.dirty:
                        persist_url_stats(self.db, provider_model)
                    last_error = RuntimeError(f"{base_url}: empty guide (0 programmes)")
                    continue

                # A non-empty, parseable guide — even one whose date range is
                # already in the past — is a SUCCESS for cycling purposes. See
                # docstring: re-fetching an identical stale guide from every
                # other host is a harm, not a fix.
                cycler.record_success(base_url)
                if cycler.dirty:
                    persist_url_stats(self.db, provider_model)
                self._remember_good_epg_host(provider_id, base_url)
                return GuideFetch(channels, programmes)

            raise last_error or RuntimeError(
                f"All EPG hosts failed for provider {provider_name!r}"
            )

        finally:
            self._release_slot(getattr(provider_model, "id", ""), _holder)
            with self._evicted_lock:
                self._evicted_holders.discard(_holder)

    def _remember_good_epg_host(self, provider_id: str, base_url: str) -> None:
        """Record the host that just served a guide, for the next fetch and the UI.

        Without this, ``build_epg_url``'s default (first entry in ``urls``)
        could keep naming a host that 403s while every real fetch succeeded
        elsewhere — a red 403 beside a green AUTODETECTED badge that never
        updated. Only the host is stored; credentials are re-derived on every
        build, so this cannot go stale like the cached ``epg_url`` column did.
        """
        try:
            with self.db.session_scope() as session:
                row = session.query(ProviderDB).filter_by(id=provider_id).first()
                if row is not None and getattr(
                    row, "epg_last_good_base_url", None
                ) != base_url:
                    row.epg_last_good_base_url = base_url
                    logger.info(
                        "EPG: remembering {} as the working guide host for {}",
                        base_url, row.name,
                    )
        except Exception:
            # A bookkeeping write must never fail a fetch that already
            # succeeded — the guide is parsed and about to be stored.
            logger.exception("EPG: could not record the working guide host")

    def _emit_or_abort(self, signal, *args) -> None:
        """Emit a worker progress signal, or abandon the fetch if we are gone.

        ``shutdown()`` does not wait for the worker, so Qt can delete this
        object's C++ side mid-fetch and the emit then raises RuntimeError.

        Raises:
            XmltvAborted: Shutting down or already destroyed — a distinct type
                so the fetch path can tell this from "the host failed".
        """
        if self._shutting_down:
            raise XmltvAborted("EPG manager is shutting down")
        try:
            signal.emit(*args)
        except RuntimeError as exc:      # the C++ object is already gone
            raise XmltvAborted(str(exc)) from exc

    def _fetch_worker(self, provider_id: str, provider_name: str,
                      notif_id: str | None = None) -> None:
        """Background worker: fetch and store a provider's guide.

        A thin guard around :meth:`_run_fetch`. Teardown can interrupt at any
        emit — including the first, before the download starts — so the
        handler wraps the whole body rather than one call. No error signal or
        toast on abort: both touch Qt objects already being destroyed.
        """
        try:
            self._run_fetch(provider_id, provider_name, notif_id)
        except XmltvAborted as e:
            logger.info(f"EPG refresh for {provider_name} abandoned: {e}")
            self._active_refreshes.discard(provider_id)

    def _run_fetch(self, provider_id: str, provider_name: str,
                   notif_id: str | None = None) -> None:
        """Resolve the fetch URL(s), download, parse, and store XMLTV data
        (see ``_resolve_and_fetch_guide`` for URL resolution + host cycling)."""
        fetch_holder = self._fetch_holder_id(provider_id)

        def on_parse_progress(count: int) -> None:
            """Report parse progress; aborts on teardown, evicts on preemption (EPG-2b)."""
            with self._evicted_lock:
                evicted = fetch_holder in self._evicted_holders
            if evicted:
                raise XmltvEvicted()
            self._emit_or_abort(
                self._progress_update, notif_id or "", count, -1,
                f"Parsing… {count:,} programmes",
            )

        # Phase 1: download — indeterminate (no Content-Length on most XMLTV feeds)
        self._emit_or_abort(self._progress_update,
            notif_id or "", 0, -1, "Downloading guide…"
        )

        try:
            fetch = self._resolve_and_fetch_guide(
                provider_id, provider_name,
                on_parse_progress if notif_id else None,
            )
        except XmltvAborted:
            raise      # teardown — _fetch_worker handles it, quietly
        except Exception as e:
            logger.error(f"EPG refresh failed for {provider_name}: {e}")
            self.refresh_error.emit(provider_id, str(e))
            self._emit_or_abort(self._progress_error, notif_id or "")
            self._show_notification(
                "EPG Error", f"{provider_name}: {e}",
                type_="error", auto_dismiss_ms=6000,
            )
            self._active_refreshes.discard(provider_id)
            return

        channels, programmes = fetch.channels, fetch.programmes
        session = self.db.get_session()
        try:
            total_progs = len(programmes)

            if fetch.partial:
                # EPG-2b: an evicted fetch only REPLACES the stored guide when
                # it holds more than what's already there — otherwise leave
                # the existing guide alone and let the next scheduler tick
                # (epg_last_fetched stays untouched below) retry the fetch.
                stored = session.query(EpgProgramDB).filter_by(
                    provider_id=provider_id).count()
                if total_progs <= stored:
                    logger.info(
                        f"EPG: {provider_name} partial fetch ({total_progs}) did "
                        f"not beat the stored guide ({stored}) — keeping it"
                    )
                    self._emit_or_abort(
                        self._progress_done, notif_id or "",
                        f"Guide fetch for {provider_name} paused for playback — "
                        f"kept the current guide ({stored:,} programmes); will retry",
                    )
                    return

            # Phase 2: channel matching — indeterminate (fast, no useful fraction)
            self._emit_or_abort(self._progress_update,
                notif_id or "", 0, -1,
                "Matching channels to your streams…"
            )

            # Build channel match map: epg_id → channel_db_id
            match_map = self._build_match_map(session, channels, provider_id)
            logger.info(f"EPG: matched {len(match_map)} channels for {provider_name}")
            # Denormalized display-name per epg_id, stored on each programme row so a
            # later DB-only relink can fuzzy-match (tiers 2/3) without re-downloading.
            chan_name_map = {ch.epg_id: ch.display_name for ch in channels}

            # Phase 3: clear old guide — indeterminate (one DELETE, fast)
            self._emit_or_abort(self._progress_update,
                notif_id or "", 0, -1, "Clearing old guide…"
            )
            # Chunked: this delete held the write lock 69.3s on a 3 GB database
            # and failed every concurrent writer. Commits per chunk.
            delete_programmes_chunked(
                session, EpgProgramDB.provider_id == provider_id
            )

            # Phase 4: bulk insert — now we know total, switch to determinate
            self._emit_or_abort(self._progress_update,
                notif_id or "", 0, total_progs, f"Saving {total_progs:,} programmes…"
            )

            batch: list[EpgProgramDB] = []
            min_start: datetime | None = None
            saved = 0
            _report_every = max(1, total_progs // 20)  # ~5% increments

            for prog in programmes:
                channel_db_id = match_map.get(prog.channel_id)
                row = EpgProgramDB(
                    provider_id    = provider_id,
                    channel_epg_id = prog.channel_id,
                    channel_db_id  = channel_db_id,
                    channel_name   = chan_name_map.get(prog.channel_id, ""),
                    title          = prog.title,
                    description    = prog.description,
                    start_time     = prog.start_time,
                    stop_time      = prog.stop_time,
                    is_live        = prog.is_live,
                    is_new         = prog.is_new,
                )
                batch.append(row)

                if min_start is None or prog.start_time < min_start:
                    min_start = prog.start_time

                if len(batch) >= 2000:
                    session.bulk_save_objects(batch)
                    session.commit()  # release lock between batches
                    saved += len(batch)
                    batch.clear()
                    if saved % _report_every < 2000:
                        pct = int(saved / total_progs * 100)
                        self._emit_or_abort(self._progress_update,
                            notif_id or "", saved, total_progs,
                            f"Saving… {saved:,}/{total_progs:,} ({pct}%)",
                        )

            if batch:
                session.bulk_save_objects(batch)
                session.commit()
                saved += len(batch)

            # Update provider timestamps
            now = now_utc()
            provider = session.query(ProviderDB).filter_by(id=provider_id).first()
            if provider:
                # Compute the honest guide depth — filler programmes (>12 h) are
                # excluded so multi-day placeholder slots do not inflate epg_data_end
                # and falsely indicate coverage far beyond the real schedule depth.
                honest_end = _compute_honest_guide_end(programmes)
                # EPG-2b: a partial fetch never stamps epg_last_fetched, so
                # needs_refresh() retries at the next scheduler tick instead of
                # believing this incomplete guide is the finished article.
                if not fetch.partial:
                    provider.epg_last_fetched = now
                provider.epg_data_start = min_start
                provider.epg_data_end = honest_end
                # The provider's feed can serve year-old data (e.g. ottcst returns a
                # Jan-2025 snapshot). Flag it so it's not mistaken for our bug — the
                # EPG view / provider editor surface this to the user via epg_is_stale.
                if honest_end is not None and honest_end < now:
                    logger.warning(
                        f"EPG: {provider_name} returned STALE guide data — latest "
                        f"programme ends {honest_end:%Y-%m-%d} (before now). The provider's "
                        f"XMLTV endpoint is out of date; nothing will appear in On Now."
                    )

            session.commit()

            # Age-based EPG hygiene: sweep expired programmes across ALL providers
            # now that this fetch's write lock is released. Reuses this already-open
            # session — safe under the single-worker executor invariant (no other
            # EPG write can be in flight). Catches providers that stopped refreshing
            # too, since this runs on every SUCCESSFUL fetch, not just this provider's.
            # prune_expired(session) reuses the passed-in session; the chunked
            # delete commits each chunk itself, so nothing is left uncommitted.
            self.prune_expired(session)

            count = session.query(EpgProgramDB).filter_by(provider_id=provider_id).count()
            logger.info(f"EPG: stored {count:,} programmes for {provider_name}")

            self.refresh_finished.emit(provider_id, count)
            done_msg = (
                f"{count:,} programmes loaded (partial — playback took the "
                f"connection; will complete later)" if fetch.partial
                else f"{count:,} programmes loaded"
            )
            self._emit_or_abort(self._progress_done, notif_id or "", done_msg)

        except XmltvAborted:
            session.rollback()   # no half-written guide; finally still closes
            raise
        except Exception as e:
            logger.error(f"EPG refresh failed for {provider_name}: {e}")
            session.rollback()
            self.refresh_error.emit(provider_id, str(e))
            self._emit_or_abort(self._progress_error, notif_id or "")
            self._show_notification(
                "EPG Error", f"{provider_name}: {e}",
                type_="error", auto_dismiss_ms=6000,
            )
        finally:
            session.close()
            self._active_refreshes.discard(provider_id)
