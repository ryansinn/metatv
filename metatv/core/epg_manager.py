"""EPG Manager — fetch, parse, store XMLTV data + notification timer.

The guide download/store path (URL resolution, host cycling, connection-slot
arbitration, download to parse to store) lives in ``epg_fetch.py``'s
``_EpgFetchMixin`` (DEBT-8) — mixed in below so ``EpgManager`` keeps its
public surface unchanged.
"""

from __future__ import annotations

import threading
import types as _types
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from loguru import logger

from metatv.core import watchlist
from metatv.core.watchlist_matching import matches_any
from metatv.core.config import Config
from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_fetch import _EpgFetchMixin
from metatv.core.epg_matching import build_match_map
from metatv.core.epg_utils import (
    epg_auto_delta,
    epg_is_stale,
    epg_interval_delta,
    local_weekday,
    now_utc,
    to_local,
)
from metatv.core.models import Provider
from metatv.core.repositories import RepositoryFactory
from metatv.core.watchlist_burst import burst_banner
from metatv.core.repositories.epg import delete_programmes_chunked
from metatv.core.repositories.provider import parse_provider_urls


# Floor for Config.epg_retention_hours — enforced in prune_expired() (not on the
# Config field itself) so a stray tiny value can never wipe data still needed for
# "on now" / near-term watchlist matches.
_MIN_EPG_RETENTION_HOURS = 6
_DEFAULT_EPG_RETENTION_HOURS = 24


class EpgManager(_EpgFetchMixin, QObject):
    """Manages EPG data lifecycle: fetching, parsing, storing, and notifications.

    All network/DB work runs in a ThreadPoolExecutor. Signals are emitted on
    the Qt main thread for safe UI updates.
    """

    refresh_started  = pyqtSignal(str)        # provider_id
    refresh_finished = pyqtSignal(str, int)   # provider_id, programme_count
    refresh_error    = pyqtSignal(str, str)   # provider_id, error_message
    # Internal signals marshal notification calls from worker threads to main thread
    _notify          = pyqtSignal(str, str, str, int)  # title, message, type, auto_dismiss_ms
    _progress_update = pyqtSignal(str, int, int, str)   # notif_id, current, total (-1=indeterminate), message
    _progress_done   = pyqtSignal(str, str)             # notif_id, final_message
    _progress_error  = pyqtSignal(str)                  # notif_id — dismiss on error

    # Periodic scheduler interval — poke needs_refresh every hour.  The per-provider
    # throttle inside needs_refresh does the real gating; this is just the clock tick.
    _SCHEDULER_INTERVAL_MS = 60 * 60 * 1_000  # 1 hour

    def __init__(self, db: Database, config: Config, notifications=None, parent=None,
                 connection_accountant=None) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.notifications = notifications  # NotificationManager or None
        #: ``player_manager``'s ConnectionAccountant, or None (tests/headless).
        #: A guide fetch is a full XMLTV download from the SAME host the user
        #: plays from, and most accounts allow ONE connection — so an
        #: unenrolled fetch silently takes the connection playback needs. This
        #: is the third consumer in that state (#622 series_monitor, #632 tmdb
        #: backfill). metadata_manager is deliberately NOT enrolled — it only
        #: reaches api.themoviedb.org / www.omdbapi.com, never the provider.
        self._accountant = connection_accountant
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="epg")
        self._notified_this_session: set[int] = set()  # programme IDs already toasted
        #: True while a watchlist check is queued or running on the executor.
        #: Without it a slow guide fetch (20-30s routinely, 69.3s in #601)
        #: would let the 60s timer stack one check behind another.
        self._notif_check_pending = False
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
        #: Guide-fetch holder ids the accountant has evicted (EPG-2b), so the
        #: in-flight parse can notice and stop. Set from ANY thread by
        #: ``_on_slot_preempted``, guarded by ``_evicted_lock``.
        self._evicted_holders: set[str] = set()
        self._evicted_lock = threading.Lock()
        # Registered LAST: the listener reads _evicted_holders/_evicted_lock,
        # so wiring it earlier repeats the v0.14.1 init-order-callback bug.
        if self._accountant is not None:
            self._accountant.add_preempt_listener(self._on_slot_preempted)

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
            configured = [u.get("url", "") for u in raw_urls]
            # Prefer the host that last served a parseable guide. Falling back
            # to configured[0] means the FIRST host positionally, which has
            # nothing to do with whether it serves EPG: a panel commonly has 20
            # hosts where only some answer xmltv.php, so the displayed URL (and
            # the one `effective_epg_url` gates on) could 403 forever while the
            # fetch quietly succeeded against a different host every time. It is
            # only honoured while still configured, so removing a host drops it.
            remembered = (getattr(provider, "epg_last_good_base_url", None) or "").strip()
            if remembered and any(
                remembered.rstrip("/") == (c or "").rstrip("/") for c in configured
            ):
                base_url = remembered
            else:
                base_url = configured[0] if configured else ""
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

        Expiry floor & stale-at-source: the floor forces an immediate re-fetch
        when the guide has run out, but is SUPPRESSED when the guide was
        already expired at fetch time (``epg_data_end < epg_last_fetched``) —
        a feed lagging real time re-serves the same stale guide, so the floor
        would re-fetch on every launch forever (sibling of the TREX
        unmatched-guide convergence fix, #285). Such feeds fall back to the
        interval throttle instead.
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

        # Stale-at-source (the BiggyJuke loop, sibling of #285's TREX fix) —
        # see docstring. Suppressing the floor here is what stops it re-fetching
        # every launch; the normal interval throttle still governs below.
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
        "unnamed legacy guide" case: rows unmatched (``channel_db_id=NULL``)
        AND lacking a stored ``channel_name``, so the cheap DB-only relink
        can't fuzzy-match them. A one-time re-fetch populates names, guarded
        by TWO layers: ``_unmatched_refresh_attempted`` (in-memory,
        per-session) and ``ProviderDB.epg_unnamed_refetch_attempted``
        (**persistent**, cleared only on content refresh).

        The persistent marker is what stops the every-launch loop: a feed
        genuinely serving nameless rows (e.g. TREX) keeps
        ``has_unmatched_unnamed_epg`` True forever, so the in-memory guard
        alone would re-fetch on EVERY launch. Sibling of the #285 fix, which
        converged the unmatched-but-NAMED case but not this nameless-forever one.
        """
        if not self.config.epg_auto_refresh:
            return

        session = self.db.get_session()
        try:
            from metatv.core.repositories.epg import EpgRepository
            epg_repo = EpgRepository(session)
            # is_active alone is not the gate: an EXPIRED subscription stays
            # active until removed, and fetching its guide cycles every host
            # for a 451 apiece (TREX did exactly that for an evening).
            # get_hidden_provider_ids is the canonical inactive ∪ expired set.
            hidden = set(RepositoryFactory(session).providers.get_hidden_provider_ids())
            providers = session.query(ProviderDB).filter_by(is_active=True).all()
            for provider in providers:
                if provider.id in hidden:
                    continue  # expired / hidden — nothing it returns is usable
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
                    # Guide is time-fresh but has LEGACY rows unmatched AND
                    # nameless — re-fetch ONCE to populate channel_name; the
                    # cheap relink then handles the rest with no more network
                    # calls. NOT the merely "unmatched but named" case
                    # (``has_unmatched_epg``): ``relink_all()`` already
                    # re-matches those DB-only. See docstring for why the
                    # persistent marker (set below) is what stops this from
                    # looping every launch.
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
            deleted = delete_programmes_chunked(
                session, EpgProgramDB.provider_id == provider_id
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
            deleted = delete_programmes_chunked(
                session, EpgProgramDB.stop_time < cutoff
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

        # Fake channel objects so _build_match_map runs all three tiers (tier 1
        # keys off epg_id; 2/3 fuzzy-match display_name); fall back to epg_id
        # for legacy rows stored before display-name persistence.
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
            # Same gate as the fetch scan above, and for the same reason: an
            # EXPIRED subscription stays is_active until removed — #536 fixed
            # the fetch loop and left this one + the watchlist check behind,
            # applied at one call site instead of the three sharing the mistake.
            hidden = set(RepositoryFactory(session).providers.get_hidden_provider_ids())
            providers = [
                p for p in session.query(ProviderDB).filter_by(is_active=True).all()
                if p.id not in hidden
            ]
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
                # Reuse refresh_finished so the already-wired handlers reload
                # On Now / Watchlist without any new signal plumbing.
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

        A DB-only operation, unlike ``refresh_all_if_needed`` — fixes the
        **partial-match** case where some channels linked at fetch time but
        others (channel list not yet loaded, or a name match changed) were
        left ``channel_db_id=NULL``. Runs on the single-worker executor so it
        never races a live fetch; emits ``refresh_finished`` per changed
        provider so the EPG view / sidebar Watch Alerts reload automatically.
        """
        self._executor.submit(self._relink_worker)

    # ------------------------------------------------------------------
    # Clear EPG link (persistent block) — inverse of relink
    # ------------------------------------------------------------------

    def clear_channel_epg_link(self, channel_id: str) -> None:
        """Unlink *channel_id*'s EPG guide data and block it from re-matching.

        Persists the block first (``config.epg_link_blocklist``, consulted by
        ``_build_match_map`` so a later ``relink_all()`` can never silently
        re-attach it), then nulls the channel's ``epg_channel_id`` and any
        linked ``EpgProgramDB`` rows on the single-worker executor (same
        one-write-at-a-time rule as fetch/relink).
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
        """Timer tick. Does no database work here — see the worker below.

        This used to run the whole check (a 344,468-row programme scan, then
        an N+1 channel lookup against 785k channels) ON THE UI THREAD every 60
        seconds — the owner's log showed a ~900ms stall every minute the app
        was open. CLAUDE.md bars an EPG-sized query from the UI thread; this
        predates the rule and does not get an exception.
        """
        if self._shutting_down or self._notif_check_pending:
            return
        # Cheap, main-thread-safe reads: config only, no database.
        if not watchlist.patterns(self.config) or not self.notifications:
            return
        self._notif_check_pending = True
        try:
            self._executor.submit(self._watchlist_notification_worker)
        except RuntimeError:
            # Executor gone (teardown). Not an error, and it must not leave the
            # flag set — a shutdown that jammed the gate would silence alerts
            # for the rest of the session if the manager outlived it.
            self._notif_check_pending = False

    def _watchlist_notification_worker(self) -> None:
        """Off-thread half of the 60s watchlist check.

        Runs on the manager's single-worker executor, so it can never race an
        EPG write — a long guide fetch just delays it, made safe by the
        queueing guard above (else an 11-minute fetch stacks eleven checks).
        Notifications go through the private ``_notify`` signal, never
        ``self.notifications`` directly (``.show`` builds a QTimer, main-thread only).
        """
        try:
            minutes = self.config.epg_notification_minutes_before
            rules = watchlist.rules(self.config)
            with self.db.session_scope(commit=False) as session:
                from metatv.core.repositories.epg import EpgRepository
                repo = EpgRepository(session)
                # Hidden sources must not raise watch alerts — a notification
                # for a programme on an expired source is the "disabled/expired
                # is an absolute gate" rule failing in the most visible way.
                hidden = set(RepositoryFactory(session).providers.get_hidden_provider_ids())
                providers = [
                    p for p in session.query(ProviderDB).filter_by(is_active=True).all()
                    if p.id not in hidden
                ]
                provider_ids = [p.id for p in providers if self.effective_epg_url(p)]
                if not provider_ids:
                    return

                # `hidden` on BOTH axes (feed list above, matched CHANNEL here,
                # deliberately different sets) — doing only the first once let
                # 18 future programmes on 6 channels raise a toast.
                upcoming = repo.get_programs_starting_soon(
                    minutes, provider_ids, excluded_channel_provider_ids=hidden)

                pending = []
                for prog in upcoming:
                    if prog.id in self._notified_this_session:
                        continue
                    # The only match test — shares the matcher with the
                    # watchlist queries so a toast can't announce what the list
                    # never shows.
                    if not matches_any(prog.title, rules,
                                       prog.description, prog.is_live):
                        continue
                    self._notified_this_session.add(prog.id)

                    channel = None
                    if prog.channel_db_id:
                        channel = session.query(ChannelDB).filter_by(
                            id=prog.channel_db_id).first()
                    channel_name = channel.name if channel else prog.channel_epg_id

                    mins_away = max(
                        0, int((prog.start_time - now_utc()).total_seconds() / 60))
                    time_str = f"in {mins_away} min" if mins_away > 0 else "now"
                    # Plain strings by this point, so nothing detached
                    # crosses the session boundary when emitted below.
                    pending.append((prog.title, channel_name, time_str))

            if not self._shutting_down and pending:
                title, message, dismiss_ms = burst_banner(pending)
                self._notify.emit(title, message, "info", dismiss_ms)
        except Exception as e:
            logger.error(f"EPG notification check error: {e}")
        finally:
            self._notif_check_pending = False

    def shutdown(self) -> None:
        """Clean up resources on app exit."""
        # FIRST: the executor is torn down without waiting, so an in-flight
        # parse needs to notice it should stop rather than crash on a dead
        # QObject.
        self._shutting_down = True
        self.stop_notification_timer()
        self.stop_scheduler()
        self._executor.shutdown(wait=False)
