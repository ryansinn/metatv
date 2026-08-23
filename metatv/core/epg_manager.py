"""EPG Manager — fetch, parse, store XMLTV data + notification timer."""

from __future__ import annotations

import types as _types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from loguru import logger

from metatv.core.channel_name_utils import epg_tld_compatible
from metatv.core.config import Config
from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_matching import build_match_map
from metatv.core.epg_utils import (
    EPG_FILLER_THRESHOLD,
    epg_auto_delta,
    epg_is_stale,
    epg_interval_delta,
    local_weekday,
    now_utc,
    to_local,
)
from metatv.core.models import Provider
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import parse_provider_urls, persist_url_stats
from metatv.core.url_cycle import UrlCycler
from metatv.core.xmltv_parser import (
    XmltvAborted,
    XmltvChannel,
    XmltvProgramme,
    normalize_channel_name,
    parse_xmltv_url,
)


# Matches the trailing dot-suffix of an XMLTV epg_id used as a language/region
# TLD idiom by some feeds (e.g. "UandEden.uk" -> "uk"; see also the ilike
# "%.{code}" idiom in repositories/epg.py). Only a 2-3 letter alpha suffix is
# treated as a TLD — anything else (numeric, longer) is not a TLD and the
# region gate abstains (see channel_name_utils.epg_tld_compatible).
# ``EPG_FILLER_THRESHOLD`` now lives in ``epg_utils`` (single source of truth) and is
# imported above; existing ``from metatv.core.epg_manager import EPG_FILLER_THRESHOLD``
# imports still resolve via this module's namespace. A programme longer than this is a
# multi-day placeholder slot (e.g. "Program" spanning several days on a sparse XMLTV
# feed) excluded from the real guide-depth calculation.


def _compute_honest_guide_end(
    programmes: list[XmltvProgramme],
) -> datetime | None:
    """Return the maximum ``stop_time`` among non-filler programmes.

    A programme is "filler" when its duration exceeds ``EPG_FILLER_THRESHOLD``
    (12 hours).  Filler entries (e.g. a multi-day "Program" slot) inflate
    ``epg_data_end`` and falsely indicate coverage well beyond the real
    schedule depth, causing the Browse UI to show nothing while the provider
    appears "good through" a far-future date.

    Falls back to the maximum stop among filler-only entries when every
    programme in the feed is filler (pathological feed), so ``epg_data_end``
    is never ``None`` when programmes exist.

    Args:
        programmes: Parsed XMLTV programme objects (``XmltvProgramme``).

    Returns:
        The latest honest guide-end datetime, or ``None`` if ``programmes``
        is empty.
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


# Floor for Config.epg_retention_hours — enforced in prune_expired() (not on the
# Config field itself) so a stray tiny value can never wipe data still needed for
# "on now" / near-term watchlist matches.
_MIN_EPG_RETENTION_HOURS = 6
_DEFAULT_EPG_RETENTION_HOURS = 24


class EpgManager(QObject):
    """Manages EPG data lifecycle: fetching, parsing, storing, and notifications.

    All network/DB work runs in a ThreadPoolExecutor. Signals are emitted on
    the Qt main thread for safe UI updates.
    """

    refresh_started  = pyqtSignal(str)        # provider_id
    refresh_finished = pyqtSignal(str, int)   # provider_id, programme_count
    refresh_error    = pyqtSignal(str, str)   # provider_id, error_message
    watchlist_notification = pyqtSignal(str, str, str)  # title, channel_name, time_str
    # Internal signals marshal notification calls from worker threads to main thread
    _notify          = pyqtSignal(str, str, str, int)  # title, message, type, auto_dismiss_ms
    _progress_update = pyqtSignal(str, int, int, str)   # notif_id, current, total (-1=indeterminate), message
    _progress_done   = pyqtSignal(str, str)             # notif_id, final_message
    _progress_error  = pyqtSignal(str)                  # notif_id — dismiss on error

    # Periodic scheduler interval — poke needs_refresh every hour.  The per-provider
    # throttle inside needs_refresh does the real gating; this is just the clock tick.
    _SCHEDULER_INTERVAL_MS = 60 * 60 * 1_000  # 1 hour

    def __init__(self, db: Database, config: Config, notifications=None, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.notifications = notifications  # NotificationManager or None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="epg")
        self._notified_this_session: set[int] = set()  # programme IDs already toasted
        self._notification_timer: QTimer | None = None
        self._scheduler_timer: QTimer | None = None
        self._notify.connect(self._do_notify)
        self._progress_update.connect(self._do_progress_update)
        self._progress_done.connect(self._do_progress_done)
        self._progress_error.connect(self._do_progress_error)
        self._active_refreshes: set[str] = set()  # provider IDs currently refreshing
        # Plain Python attribute on purpose: still readable after Qt has
        # deleted this object's C++ side, which is the worker's exact case.
        self._shutting_down = False
        self._unmatched_refresh_attempted: set[str] = set()  # per-session unmatched-relink guard

    def _do_notify(self, title: str, message: str, type_: str, auto_dismiss_ms: int) -> None:
        if self.notifications:
            self.notifications.show(
                title=title, message=message,
                type=type_, auto_dismiss_ms=auto_dismiss_ms,
            )

    def _do_progress_update(self, notif_id: str, current: int, total: int, message: str) -> None:
        if self.notifications and notif_id:
            kwargs: dict = {"progress_current": current, "message": message}
            if total > 0:
                kwargs["progress_total"] = total
                kwargs["progress"] = current / total
            self.notifications.update(notif_id, **kwargs)

    def _do_progress_done(self, notif_id: str, message: str) -> None:
        if self.notifications and notif_id:
            self.notifications.complete_progress(notif_id, message)

    def _do_progress_error(self, notif_id: str) -> None:
        if self.notifications and notif_id:
            self.notifications.dismiss(notif_id)

    def _show_notification(self, title: str, message: str,
                           type_: str = "info", auto_dismiss_ms: int = 4000) -> None:
        """Thread-safe helper: emit signal so notification runs on main thread."""
        self._notify.emit(title, message, type_, auto_dismiss_ms)

    # ------------------------------------------------------------------
    # Refresh control
    # ------------------------------------------------------------------

    @staticmethod
    def build_epg_url(provider: ProviderDB | Provider, base_url: str | None = None) -> str | None:
        """Construct the standard Xtream XMLTV URL from provider credentials + a host.

        Args:
            provider: Provider row/model supplying ``username``/``password`` — a
                ``ProviderDB`` row or the in-memory ``Provider`` domain model both
                expose the same attributes.
            base_url: The host to build the URL against. Defaults to ``None``,
                which reproduces the original behaviour — the first entry in the
                provider's ``urls`` JSON list. That default only works against a
                ``ProviderDB`` row, whose ``urls`` column carries the raw list;
                pass an explicit *base_url* (e.g. one candidate from
                ``UrlCycler.candidates()``) when cycling through multiple hosts or
                working from the in-memory ``Provider`` model.

        Returns:
            The constructed XMLTV URL, or ``None`` if no host is available.
        """
        if base_url is None:
            raw_urls = parse_provider_urls(provider.urls)
            if not raw_urls:
                return None
            base_url = raw_urls[0].get("url", "")
        base = base_url.rstrip("/") if base_url else ""
        if not base:
            return None
        username = provider.username or ""
        password = provider.password or ""
        if username and password:
            return f"{base}/xmltv.php?username={username}&password={password}"
        return f"{base}/xmltv.php"

    @staticmethod
    def effective_epg_url(provider: ProviderDB) -> str:
        """Return the URL to fetch: a user override wins, else derive from live credentials.

        Deliberately NOT read from the stored ``epg_url`` column. That column was a
        cached derivation of *mutable* inputs (username/password/host) with no
        invalidation, so a re-subscription on the same provider row left it holding
        the previous account's credentials forever — the owner's guide silently died
        for 11 days behind a green "AUTODETECTED" badge. Deriving here means a
        credential change is picked up on the very next fetch, with nothing to
        invalidate.
        """
        override = (getattr(provider, "epg_url_override", None) or "").strip()
        if override:
            return override
        return EpgManager.build_epg_url(provider) or ""

    def needs_refresh(self, provider: ProviderDB) -> bool:
        """Return True if this provider's EPG data should be re-fetched.

        Resolution order:
        1. No effective URL → False.
        2. ``epg_enabled`` is False → False.
        3. Never fetched (``epg_last_fetched`` is None) → True.
        4. Resolve effective interval = per-source ``epg_refresh_interval`` unless
           it is ``"default"`` / blank, in which case use the global config default
           (``config.epg_default_refresh_interval``).
        5. ``every_open`` → True.
        6. ``when_stale`` → True when the guide has fully expired, EXCEPT for a
           feed that is stale at source (see below), which is throttled to the
           auto delta so it doesn't re-fetch every launch.
        7. ``auto`` → delta = half the guide depth, clamped to [6 h, 7 d], then same
           expiry-floor check as time-based intervals.
        8. Time interval → True if elapsed since last fetch ≥ delta **OR** the
           expiry floor fires (guide ran out — time intervals must never leave an
           empty "On Now").

        Expiry floor & stale-at-source: the floor forces an immediate re-fetch when
        the guide has run out, but is SUPPRESSED when the guide was already expired
        at fetch time (``epg_data_end < epg_last_fetched``) — a feed lagging real
        time re-serves the same stale guide, so the floor would re-fetch on every
        launch forever. Such feeds fall back to the interval throttle. (Sibling of
        the TREX unmatched-guide convergence fix, #285.)
        """
        if not self.effective_epg_url(provider):
            return False

        if not getattr(provider, "epg_enabled", True):
            return False

        last_fetched = getattr(provider, "epg_last_fetched", None)
        if last_fetched is None:
            return True  # never fetched

        # Resolve effective interval
        per_source = getattr(provider, "epg_refresh_interval", None) or "default"
        if per_source == "default":
            effective = getattr(self.config, "epg_default_refresh_interval", "auto") or "auto"
        else:
            effective = per_source

        data_end = getattr(provider, "epg_data_end", None)
        data_start = getattr(provider, "epg_data_start", None)
        guide_expired = epg_is_stale(data_end)  # True if data_end < now_utc()

        # A guide that was ALREADY expired when we last fetched it (data_end <
        # last_fetched) means the FEED itself lags real time — it serves programme
        # data ending in the past. Re-fetching pulls the same stale guide, so
        # honouring the "expiry floor" (refresh-now-because-the-guide-ran-out) would
        # re-fetch on EVERY launch and never converge. That is the BiggyJuke loop —
        # a sibling of the TREX unmatched-guide loop fixed in #285. When the feed is
        # stale at source we suppress the expiry floor and let the normal interval
        # throttle govern, so a genuinely-recovering feed is still re-checked
        # periodically (every auto delta, min 6 h) rather than hammered every launch.
        # A guide that was valid at fetch time but has since run out (data_end >=
        # last_fetched) is the legitimate case the floor exists for — it stays.
        guide_stale_at_source = data_end is not None and data_end < last_fetched
        expiry_floor = guide_expired and not guide_stale_at_source

        if effective == "every_open":
            return True

        if effective == "when_stale":
            # Refresh when the guide runs out — but a stale-at-source feed is
            # *permanently* stale, so throttle it to the auto delta instead of
            # re-fetching on every launch.
            if guide_stale_at_source:
                return now_utc() - last_fetched >= epg_auto_delta(data_start, data_end)
            return guide_expired

        if effective == "auto":
            # Self-tuning: half the guide depth, clamped to [6 h, 7 d].
            # Expiry floor refreshes immediately when the guide ran out (unless the
            # feed is stale at source — see above, where the throttle governs).
            if expiry_floor:
                return True
            delta = epg_auto_delta(data_start, data_end)
            return now_utc() - last_fetched >= delta

        # Time-based interval
        delta = epg_interval_delta(effective)
        if delta is None:
            # Unrecognised value — treat as "every_open" (safe default)
            logger.warning(f"EPG: unknown epg_refresh_interval {effective!r} for {provider.id}; treating as every_open")
            return True

        # Expiry floor: refresh immediately if the guide ran out mid-interval
        # (unless the feed is stale at source — the interval throttle governs there).
        if expiry_floor:
            return True

        return now_utc() - last_fetched >= delta

    def refresh_all_if_needed(self) -> None:
        """Check every active provider and trigger a background refresh if needed.

        Providers with ``epg_enabled=False`` are skipped — the user has explicitly
        opted out of EPG fetching for those sources. NULL is treated as enabled for
        backwards compatibility with rows predating the column.

        In addition to the normal time-staleness check, this method detects the
        "unnamed legacy guide" case: EPG rows exist but are unmatched
        (``channel_db_id=NULL``) AND lack a stored ``channel_name``, so the cheap
        DB-only relink can't fuzzy-match them.  A one-time re-fetch is triggered to
        populate names, guarded by TWO layers:

        - ``_unmatched_refresh_attempted`` — in-memory, per-session dedupe.
        - ``ProviderDB.epg_unnamed_refetch_attempted`` — **persistent** cross-launch
          marker (reset only when the source is content-refreshed).

        The persistent marker is what stops the every-launch loop: a feed that
        genuinely serves nameless programme rows (channel ids with no ``<channel>``
        display-name, e.g. TREX) keeps ``has_unmatched_unnamed_epg`` True forever, so
        the in-memory guard alone re-fetched the full guide on EVERY launch (it resets
        each start).  Once the marker is set, this branch never fires again for that
        provider; the guide still refreshes on the normal ``needs_refresh`` interval.
        A content refresh clears the marker so a genuinely-improved feed re-attempts
        the names re-fetch exactly once.  (Sibling of the #285 fix, which converged the
        unmatched-but-NAMED case but not the nameless-forever case.)
        """
        if not self.config.epg_auto_refresh:
            return

        session = self.db.get_session()
        try:
            from metatv.core.repositories.epg import EpgRepository
            epg_repo = EpgRepository(session)
            providers = session.query(ProviderDB).filter_by(is_active=True).all()
            for provider in providers:
                if not getattr(provider, "epg_enabled", True):
                    continue  # user disabled EPG for this provider
                eff_url = self.effective_epg_url(provider)
                if not eff_url or provider.id in self._active_refreshes:
                    continue
                if self.needs_refresh(provider):
                    self._start_refresh(provider.id, provider.name, force=False)
                elif (
                    provider.id not in self._unmatched_refresh_attempted
                    and not getattr(provider, "epg_unnamed_refetch_attempted", False)
                    and epg_repo.has_unmatched_unnamed_epg(provider.id)
                ):
                    # Guide is time-fresh but has LEGACY rows that are unmatched AND
                    # lack a stored channel_name, so the DB-only relink can't fuzzy-match
                    # them. Re-fetch ONCE to populate channel_name; the cheap relink then
                    # handles everything without a further network fetch.
                    #
                    # We deliberately do NOT re-fetch the merely "unmatched but named"
                    # case (``has_unmatched_epg``): ``relink_all()`` already re-matches
                    # named rows DB-only on every activation, so a network re-fetch adds
                    # nothing.  For a provider whose guide can never match its channels
                    # (a source serving placeholder/foreign EPG, e.g. TREX) those rows
                    # stay permanently unmatched AND unnamed — a channel id with no
                    # ``<channel>`` display-name in the feed is written with an empty
                    # ``channel_name`` and no re-fetch can ever fill it — so
                    # ``has_unmatched_unnamed_epg`` never goes False.  With ONLY the
                    # in-memory guard (resets each launch) this branch re-fetched the
                    # full guide on EVERY launch, ignoring the refresh interval.  The
                    # persistent ``epg_unnamed_refetch_attempted`` marker (set + committed
                    # below) is what stops the cross-launch loop; the guide still
                    # refreshes on the normal ``needs_refresh`` interval.  A content
                    # refresh clears the marker so a genuinely-improved feed re-attempts
                    # exactly once.
                    logger.info(
                        f"EPG: provider {provider.name!r} has unnamed (legacy) guide "
                        f"data — triggering one-time re-fetch to populate channel names"
                    )
                    self._unmatched_refresh_attempted.add(provider.id)
                    provider.epg_unnamed_refetch_attempted = True
                    session.commit()  # persist so the next launch does NOT re-fetch again
                    self._start_refresh(provider.id, provider.name, force=False)
        finally:
            session.close()

    def force_refresh_provider(self, provider_id: str) -> None:
        """Unconditionally refresh one provider's EPG data.

        Uses ``effective_epg_url`` (override takes precedence over auto-built URL).
        """
        if provider_id in self._active_refreshes:
            logger.info(f"EPG refresh already running for {provider_id}")
            return

        session = self.db.get_session()
        try:
            provider = session.query(ProviderDB).filter_by(id=provider_id).first()
            if not provider:
                logger.warning(f"EPG: provider {provider_id} not found")
                return
            eff_url = self.effective_epg_url(provider)
            if not eff_url:
                logger.warning(f"EPG: no URL available for provider {provider_id}")
                return
            self._start_refresh(provider.id, provider.name, force=True)
        finally:
            session.close()

    def purge_provider_epg(self, provider_id: str, session=None) -> int:
        """Delete all EPG programmes for *provider_id* and clear its EPG timestamps.

        Called when the user disables EPG for a provider so the UI immediately
        reflects the change (no stale programmes in On Now / Watchlist / Browse).
        Also nulls ``epg_last_fetched``, ``epg_data_start``, and ``epg_data_end``
        so the editor's EPG status line shows "Not configured / off".

        Args:
            provider_id: The provider whose EPG data should be removed.
            session: An open SQLAlchemy session to reuse (e.g. inside ``_save``).
                     If None, a new session is opened and closed by this method.

        Returns:
            Number of ``EpgProgramDB`` rows deleted.
        """
        own_session = session is None
        if own_session:
            session = self.db.get_session()
        try:
            deleted = (
                session.query(EpgProgramDB)
                .filter_by(provider_id=provider_id)
                .delete()
            )
            provider = session.query(ProviderDB).filter_by(id=provider_id).first()
            if provider:
                provider.epg_last_fetched = None
                provider.epg_data_start = None
                provider.epg_data_end = None
            if own_session:
                session.commit()
            logger.info(
                f"EPG: purged {deleted} programmes for provider {provider_id} "
                f"(EPG disabled by user)"
            )
            return deleted
        except Exception:
            if own_session:
                session.rollback()
            raise
        finally:
            if own_session:
                session.close()

    def prune_expired(self, session=None) -> int:
        """Delete ``EpgProgramDB`` rows across ALL providers whose ``stop_time`` has
        aged past the retention window.

        Runs after every successful fetch (see ``_fetch_worker``, right after the
        provider-timestamp commit) so age-based hygiene sweeps the WHOLE table, not
        just the provider that just refreshed — a source that has stopped refreshing
        still gets its stale rows cleared out whenever ANY other provider fetches.
        Without this, ``epg_programmes`` only ever grows (each fetch replaces one
        provider's rows but never reclaims programmes that simply expired).

        Retention is ``Config.epg_retention_hours`` (default 24h), floored at
        ``_MIN_EPG_RETENTION_HOURS`` (6h) so a stray small value can never prune
        programmes still relevant to "on now" / near-term watchlist matches.

        Args:
            session: An open SQLAlchemy session to reuse (e.g. the one
                ``_fetch_worker`` already holds — the single-worker executor
                invariant, CLAUDE.md#epg-manager-internals, guarantees no other EPG
                write is in flight to race this delete). If ``None``, a new session
                is opened and closed by this method.

        Returns:
            Number of ``EpgProgramDB`` rows deleted.
        """
        own_session = session is None
        if own_session:
            session = self.db.get_session()
        try:
            configured = getattr(self.config, "epg_retention_hours", _DEFAULT_EPG_RETENTION_HOURS)
            hours = max(_MIN_EPG_RETENTION_HOURS, configured or _DEFAULT_EPG_RETENTION_HOURS)
            cutoff = now_utc() - timedelta(hours=hours)
            deleted = (
                session.query(EpgProgramDB)
                .filter(EpgProgramDB.stop_time < cutoff)
                .delete()
            )
            if own_session:
                session.commit()
            if deleted:
                logger.info(
                    f"EPG: pruned {deleted:,} expired programmes "
                    f"(older than {hours}h retention, cutoff {cutoff:%Y-%m-%d %H:%M} UTC)"
                )
            return deleted
        except Exception:
            if own_session:
                session.rollback()
            raise
        finally:
            if own_session:
                session.close()

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
    ) -> tuple[list[XmltvChannel], list[XmltvProgramme]]:
        """Resolve the fetch URL(s) for *provider_id* and return the first working guide.

        A non-empty ``epg_url_override`` is fetched once, verbatim, with no
        cycling — it is an explicit instruction to use exactly one URL, and
        trying other hosts against a hand-written URL would be wrong. With no
        override, the provider's hosts are tried in reliability order via
        ``UrlCycler`` (CLAUDE.md: URL cycling has exactly one path, never a
        bare loop over ``ordered_urls()``) until a host returns a parseable,
        non-empty guide. ``record_success``/``record_failure`` follow EVERY
        attempt and are flushed with ``persist_url_stats`` before the next
        attempt starts, so a dead host stops ranking first — cycling without
        recording is the bug that already shipped once (CLAUDE.md). No
        response-time is recorded: mirrors the ``fetch_channels`` latency
        exclusion, since a full XMLTV download is the same bulk-download shape,
        not a comparably-sized request, and mixing it into
        ``median_latency_ms()`` would make the median meaningless.

        A guide that parses but is already expired (its date range is in the
        past) is NOT a failure and does NOT advance to the next host — every
        host on a panel serves the same guide, and an XMLTV payload is a bulk
        download (hundreds of thousands of programmes), so re-downloading it
        from every other host to receive identical stale content would be a
        serious harm, not a fix. Staleness is handled later, by
        ``needs_refresh()``'s interval throttle — never here.

        Returns:
            ``(channels, programmes)`` from whichever host succeeded first.

        Raises:
            Exception: whatever the last attempt raised, or a ``RuntimeError``
                if there were no hosts to try or every host returned an empty
                guide.
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
            return parse_xmltv_url(
                override, timeout=180, on_progress=on_parse_progress,
            )

        cycler = UrlCycler(provider_model, "fetch_epg")
        candidates = cycler.candidates()
        if not candidates:
            raise RuntimeError(f"No configured hosts for provider {provider_name!r}")

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
            return channels, programmes

        raise last_error or RuntimeError(
            f"All EPG hosts failed for provider {provider_name!r}"
        )

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
        def on_parse_progress(count: int) -> None:
            """Report parse progress; aborts the parse once we are torn down."""
            self._emit_or_abort(
                self._progress_update, notif_id or "", count, -1,
                f"Parsing… {count:,} programmes",
            )

        # Phase 1: download — indeterminate (no Content-Length on most XMLTV feeds)
        self._emit_or_abort(self._progress_update, 
            notif_id or "", 0, -1, "Downloading guide…"
        )

        try:
            channels, programmes = self._resolve_and_fetch_guide(
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

        session = self.db.get_session()
        try:
            total_progs = len(programmes)

            # Phase 2: channel matching — indeterminate (fast, no useful fraction)
            self._emit_or_abort(self._progress_update, 
                notif_id or "", 0, -1,
                f"Matching channels to your streams…"
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
            session.query(EpgProgramDB).filter_by(provider_id=provider_id).delete()
            session.commit()  # release write lock before inserts start

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
            # prune_expired(session) reuses the passed-in session and does NOT commit
            # for us (own_session=False) — commit explicitly or the delete rolls back
            # on session.close() below.
            self.prune_expired(session)
            session.commit()

            count = session.query(EpgProgramDB).filter_by(provider_id=provider_id).count()
            logger.info(f"EPG: stored {count:,} programmes for {provider_name}")

            self.refresh_finished.emit(provider_id, count)
            self._emit_or_abort(self._progress_done, notif_id or "", f"{count:,} programmes loaded")

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

    def _build_match_map(
        self, session, xmltv_channels, provider_id: str
    ) -> dict[str, str]:
        """Build xmltv_epg_id → channel_db_id lookup.

        Delegates to :func:`metatv.core.epg_matching.build_match_map`; see that
        module for the tier/blocklist/region rules.
        """
        return build_match_map(session, xmltv_channels, provider_id, self.config)

    def _relink_provider(self, session, provider_id: str) -> int:
        """Re-run channel matching for existing EPG rows without re-downloading.

        Reads the distinct ``channel_epg_id`` values already stored in
        ``EpgProgramDB``, passes them to ``_build_match_map`` as lightweight
        pseudo-channel objects (so tiers 1 and 2/3 both run), then bulk-updates
        only the rows whose ``channel_db_id`` changed.

        Args:
            session: An open SQLAlchemy session (caller manages lifecycle).
            provider_id: Provider whose EPG rows should be re-linked.

        Returns:
            Total number of ``EpgProgramDB`` rows updated.
        """
        # Collect distinct (channel_epg_id, channel_name) pairs from stored rows.
        pairs = (
            session.query(EpgProgramDB.channel_epg_id, EpgProgramDB.channel_name)
            .filter(EpgProgramDB.provider_id == provider_id)
            .distinct()
            .all()
        )
        if not pairs:
            return 0

        # Build fake channel objects so _build_match_map can run all three tiers:
        # tier 1 keys off epg_id; tiers 2/3 fuzzy-match the display_name. Use the
        # stored channel_name as the display_name, falling back to the epg_id for
        # legacy rows stored before display-name persistence (tier-1 still works).
        fake_channels = [
            _types.SimpleNamespace(epg_id=eid, display_name=(name or eid))
            for eid, name in pairs
        ]

        match_map = self._build_match_map(session, fake_channels, provider_id)

        from sqlalchemy import or_

        total_updated = 0
        for epg_id, channel_db_id in match_map.items():
            # Update rows where channel_db_id IS NULL (unmatched) OR differs
            # from the newly resolved id.  A plain `!= channel_db_id` generates
            # `col != :val` which is never True for NULL rows in SQL.
            updated = (
                session.query(EpgProgramDB)
                .filter(
                    EpgProgramDB.provider_id == provider_id,
                    EpgProgramDB.channel_epg_id == epg_id,
                    or_(
                        EpgProgramDB.channel_db_id.is_(None),
                        EpgProgramDB.channel_db_id != channel_db_id,
                    ),
                )
                .update(
                    {"channel_db_id": channel_db_id},
                    synchronize_session=False,
                )
            )
            total_updated += updated

        return total_updated

    def _relink_worker(self) -> None:
        """Background worker: re-link EPG rows for all active, EPG-enabled providers."""
        session = self.db.get_session()
        try:
            providers = (
                session.query(ProviderDB)
                .filter_by(is_active=True)
                .all()
            )
            grand_total = 0
            changed_provider_ids: list[str] = []
            for provider in providers:
                if not getattr(provider, "epg_enabled", True):
                    continue
                if provider.id in self._active_refreshes:
                    logger.debug(
                        f"EPG relink: skipping {provider.name!r} — fetch in progress"
                    )
                    continue
                self._active_refreshes.add(provider.id)
                try:
                    relinked = self._relink_provider(session, provider.id)
                    if relinked:
                        session.commit()
                        grand_total += relinked
                        changed_provider_ids.append(provider.id)
                        logger.debug(
                            f"EPG relink: {relinked} rows updated for {provider.name!r}"
                        )
                except Exception as exc:
                    session.rollback()
                    logger.warning(f"EPG relink failed for {provider.id}: {exc}")
                finally:
                    self._active_refreshes.discard(provider.id)

            if grand_total:
                logger.info(
                    f"EPG relink complete: {grand_total} rows updated across "
                    f"{len(changed_provider_ids)} provider(s)"
                )
                # Notify views so they repopulate — reuse refresh_finished so the
                # already-wired handlers (_refresh_watch_alerts + _on_epg_refreshed)
                # reload On Now / Watchlist without any new signal plumbing.
                for pid in changed_provider_ids:
                    count = (
                        session.query(EpgProgramDB)
                        .filter_by(provider_id=pid)
                        .count()
                    )
                    self.refresh_finished.emit(pid, count)
            else:
                logger.debug("EPG relink: no rows needed updating")
        except Exception as exc:
            logger.error(f"EPG relink worker error: {exc}")
        finally:
            session.close()

    def relink_all(self) -> None:
        """Re-run channel matching for all providers using existing EPG rows.

        Unlike ``refresh_all_if_needed``, this is a DB-only operation — no network
        fetch. It fixes the **partial-match** case where some channels were linked
        at fetch time but others (e.g. those whose channel list was not yet loaded,
        or whose name match changed) were left with ``channel_db_id=NULL``.

        Runs in the manager's existing single-worker executor so it never races
        with a live fetch for the same SQLite file.  Emits ``refresh_finished``
        for each provider where rows changed so the EPG view and sidebar Watch
        Alerts reload automatically.
        """
        self._executor.submit(self._relink_worker)

    # ------------------------------------------------------------------
    # Clear EPG link (persistent block) — inverse of relink
    # ------------------------------------------------------------------

    def clear_channel_epg_link(self, channel_id: str) -> None:
        """Unlink *channel_id*'s EPG guide data and block it from re-matching.

        Persists the block first (``config.epg_link_blocklist`` — consulted by
        ``_build_match_map`` so a later ``relink_all()`` — which runs on every EPG
        view activation — can never silently re-attach guide data), then nulls the
        channel's ``epg_channel_id`` and any already-linked ``EpgProgramDB`` rows
        on the manager's single-worker executor (same one-write-at-a-time rule as
        fetch/relink, so it never races a concurrent EPG write).

        Args:
            channel_id: The ``ChannelDB.id`` to unlink and block.
        """
        blocklist = list(self.config.epg_link_blocklist or [])
        if channel_id not in blocklist:
            blocklist.append(channel_id)
            self.config.epg_link_blocklist = blocklist
            self.config.save()
        self._executor.submit(self._clear_channel_epg_link_worker, channel_id)

    def _clear_channel_epg_link_worker(self, channel_id: str) -> None:
        """Background worker: null the channel's EPG link + linked programme rows."""
        provider_id: str | None = None
        updated = 0
        try:
            with self.db.session_scope() as session:
                channel = session.query(ChannelDB).filter_by(id=channel_id).first()
                if channel is not None:
                    provider_id = channel.provider_id
                    channel.epg_channel_id = None
                updated = (
                    session.query(EpgProgramDB)
                    .filter(EpgProgramDB.channel_db_id == channel_id)
                    .update({"channel_db_id": None}, synchronize_session=False)
                )
            logger.info(
                f"EPG link cleared for channel {channel_id} "
                f"({updated} programme row(s) unlinked, provider={provider_id})"
            )
        except Exception as exc:
            logger.warning(f"Clear EPG link failed for channel {channel_id}: {exc}")
            return
        if provider_id:
            # Reuse refresh_finished — the already-wired handlers
            # (_refresh_watch_alerts + _on_epg_refreshed + sidebar Sources)
            # reload On Now / Browse / Watch Alerts without new signal plumbing.
            self.refresh_finished.emit(provider_id, updated)

    def relink_channel_epg(self, channel_id: str) -> None:
        """Re-allow EPG matching for a previously-blocked channel (inverse of clear).

        Removes *channel_id* from ``config.epg_link_blocklist`` and kicks off a
        full ``relink_all()`` pass so the channel is re-matched immediately
        rather than waiting for the next EPG view activation.

        Args:
            channel_id: The ``ChannelDB.id`` to re-allow.
        """
        blocklist = list(self.config.epg_link_blocklist or [])
        if channel_id in blocklist:
            blocklist.remove(channel_id)
            self.config.epg_link_blocklist = blocklist
            self.config.save()
        self.relink_all()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status_text(self, provider_id: str) -> str:
        """Human-readable EPG status for a provider."""
        session = self.db.get_session()
        try:
            provider = session.query(ProviderDB).filter_by(id=provider_id).first()
            if not provider:
                return "No EPG data"

            last = getattr(provider, "epg_last_fetched", None)
            end  = getattr(provider, "epg_data_end", None)

            if last is None:
                return "No EPG data — click ⟳ to fetch"

            now = now_utc()
            age = now - last
            if age.total_seconds() < 3600:
                age_str = f"{int(age.total_seconds() / 60)}m ago"
            elif age.total_seconds() < 86400:
                age_str = f"{int(age.total_seconds() / 3600)}h ago"
            else:
                age_str = f"{age.days}d ago"

            end_str = ""
            if end:
                # epg_data_end is UTC-naive — convert to local before display
                # (per the EPG timezone rule) so the day/time isn't off by the
                # local offset (or a whole day near midnight).
                local_end = f"{local_weekday(end)} {to_local(end).strftime('%b %d %I:%M%p')}"
                end_str = f" · data through {local_end.replace(' 0', ' ')}"

            return f"Updated {age_str}{end_str}"
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Notification timer
    # ------------------------------------------------------------------

    def start_scheduler(self) -> None:
        """Start the periodic refresh scheduler (1-hour tick).

        The scheduler calls ``refresh_all_if_needed()`` on every tick.  The
        per-provider ``needs_refresh`` throttle does all the real gating — this
        timer is just the clock that makes sure we check while the app is running.

        Safe to call multiple times: subsequent calls are no-ops.
        """
        if self._scheduler_timer is not None:
            return
        self._scheduler_timer = QTimer(self)
        self._scheduler_timer.setInterval(self._SCHEDULER_INTERVAL_MS)
        self._scheduler_timer.timeout.connect(self.refresh_all_if_needed)
        self._scheduler_timer.start()
        logger.info("EPG periodic refresh scheduler started (1-hour tick)")

    def stop_scheduler(self) -> None:
        """Stop the periodic refresh scheduler."""
        if self._scheduler_timer:
            self._scheduler_timer.stop()
            self._scheduler_timer = None

    def start_notification_timer(self) -> None:
        """Start a 60-second repeating timer to check for watchlist shows starting soon."""
        if self._notification_timer is not None:
            return
        self._notification_timer = QTimer(self)
        self._notification_timer.setInterval(60_000)
        self._notification_timer.timeout.connect(self._check_watchlist_notifications)
        self._notification_timer.start()
        logger.info("EPG notification timer started")

    def stop_notification_timer(self) -> None:
        if self._notification_timer:
            self._notification_timer.stop()
            self._notification_timer = None

    def _check_watchlist_notifications(self) -> None:
        """Called every 60s. Toast for any watchlist show starting soon."""
        patterns = self.config.epg_watchlist_patterns
        if not patterns or not self.notifications:
            return

        minutes = self.config.epg_notification_minutes_before
        session = self.db.get_session()
        try:
            from metatv.core.repositories.epg import EpgRepository
            repo = EpgRepository(session)
            providers = session.query(ProviderDB).filter_by(is_active=True).all()
            provider_ids = [p.id for p in providers if self.effective_epg_url(p)]

            if not provider_ids:
                return

            upcoming = repo.get_programs_starting_soon(minutes, provider_ids)
            for prog in upcoming:
                if prog.id in self._notified_this_session:
                    continue
                # Check if title matches any watchlist pattern
                title_lower = prog.title.lower()
                matched = any(pat.lower() in title_lower for pat in patterns)
                if not matched:
                    continue

                self._notified_this_session.add(prog.id)

                # Resolve channel name
                channel = None
                if prog.channel_db_id:
                    channel = session.query(ChannelDB).filter_by(id=prog.channel_db_id).first()
                channel_name = channel.name if channel else prog.channel_epg_id

                # Minutes until start
                now = now_utc()
                mins_away = max(0, int((prog.start_time - now).total_seconds() / 60))
                time_str = f"in {mins_away} min" if mins_away > 0 else "now"

                if self.notifications:
                    self.notifications.show(
                        title=f"Starting {time_str}: {prog.title}",
                        message=f"On {channel_name}",
                        type="info",
                        auto_dismiss_ms=10_000,
                    )
                self.watchlist_notification.emit(prog.title, channel_name, time_str)

        except Exception as e:
            logger.error(f"EPG notification check error: {e}")
        finally:
            session.close()

    def shutdown(self) -> None:
        """Clean up resources on app exit."""
        # FIRST: the executor is torn down without waiting, so an in-flight
        # parse needs to notice it should stop rather than crash on a dead
        # QObject.
        self._shutting_down = True
        self.stop_notification_timer()
        self.stop_scheduler()
        self._executor.shutdown(wait=False)
