"""EPG Manager — fetch, parse, store XMLTV data + notification timer."""

from __future__ import annotations

import re
import types as _types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_utils import (
    EPG_FILLER_THRESHOLD,
    epg_auto_delta,
    epg_is_stale,
    epg_interval_delta,
    now_utc,
)
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import parse_provider_urls
from metatv.core.xmltv_parser import XmltvProgramme, normalize_channel_name, parse_xmltv_url


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
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="epg")
        self._notified_this_session: set[int] = set()  # programme IDs already toasted
        self._notification_timer: QTimer | None = None
        self._scheduler_timer: QTimer | None = None
        self._notify.connect(self._do_notify)
        self._progress_update.connect(self._do_progress_update)
        self._progress_done.connect(self._do_progress_done)
        self._progress_error.connect(self._do_progress_error)
        self._active_refreshes: set[str] = set()  # provider IDs currently refreshing
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
    def build_epg_url(provider: ProviderDB) -> str | None:
        """Construct the standard Xtream XMLTV URL from provider credentials + primary server."""
        raw_urls = parse_provider_urls(provider.urls)
        if not raw_urls:
            return None
        first = raw_urls[0]
        base = first.get("url", "").rstrip("/")
        if not base:
            return None
        username = provider.username or ""
        password = provider.password or ""
        if username and password:
            return f"{base}/xmltv.php?username={username}&password={password}"
        return f"{base}/xmltv.php"

    def _ensure_epg_url(self, provider: ProviderDB, session) -> bool:
        """Auto-populate epg_url from credentials if it is empty. Returns True if URL is set."""
        if getattr(provider, "epg_url", ""):
            return True
        url = self.build_epg_url(provider)
        if not url:
            return False
        provider.epg_url = url
        try:
            session.commit()
            logger.info(f"EPG: auto-detected URL for {provider.name}: {url}")
        except Exception:
            session.rollback()
        return True

    @staticmethod
    def effective_epg_url(provider: ProviderDB) -> str:
        """Return the URL to use for fetching: override wins over auto-built URL.

        ``epg_url_override`` (user-supplied) takes precedence; falls back to the
        auto-built ``epg_url`` populated by ``_ensure_epg_url``.
        """
        return getattr(provider, "epg_url_override", None) or getattr(provider, "epg_url", "") or ""

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
        6. ``when_stale`` → True only if guide has fully expired.
        7. ``auto`` → delta = half the guide depth, clamped to [6 h, 7 d], then same
           expiry-floor check as time-based intervals.
        8. Time interval → True if elapsed since last fetch ≥ delta **OR** guide
           has fully expired (expiry floor — time intervals must never leave an
           empty "On Now").
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
        guide_expired = epg_is_stale(data_end)  # True if data_end < now_utc()

        if effective == "every_open":
            return True

        if effective == "when_stale":
            return guide_expired

        if effective == "auto":
            # Self-tuning: half the guide depth, clamped to [6 h, 7 d].
            # Expiry floor still applies: refresh immediately when guide ran out.
            if guide_expired:
                return True
            data_start = getattr(provider, "epg_data_start", None)
            delta = epg_auto_delta(data_start, data_end)
            return now_utc() - last_fetched >= delta

        # Time-based interval
        delta = epg_interval_delta(effective)
        if delta is None:
            # Unrecognised value — treat as "every_open" (safe default)
            logger.warning(f"EPG: unknown epg_refresh_interval {effective!r} for {provider.id}; treating as every_open")
            return True

        # Expiry floor: refresh immediately if guide ran out, even within the interval
        if guide_expired:
            return True

        return now_utc() - last_fetched >= delta

    def refresh_all_if_needed(self) -> None:
        """Check every active provider and trigger a background refresh if needed.

        Providers with ``epg_enabled=False`` are skipped — the user has explicitly
        opted out of EPG fetching for those sources. NULL is treated as enabled for
        backwards compatibility with rows predating the column.

        In addition to the normal time-staleness check, this method detects the
        "unmatched guide" case: EPG rows exist but all have ``channel_db_id=NULL``
        because the fetch ran before the channel list was loaded.  For such providers
        a one-time re-fetch is triggered per session (guarded by
        ``_unmatched_refresh_attempted``) so the link is rebuilt against the now-
        loaded channel table without the user having to click Refresh manually.
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
                self._ensure_epg_url(provider, session)
                eff_url = self.effective_epg_url(provider)
                if not eff_url or provider.id in self._active_refreshes:
                    continue
                if self.needs_refresh(provider):
                    self._start_refresh(provider.id, eff_url, provider.name, force=False)
                elif (
                    provider.id not in self._unmatched_refresh_attempted
                    and (
                        epg_repo.has_unmatched_epg(provider.id)
                        or epg_repo.has_unmatched_unnamed_epg(provider.id)
                    )
                ):
                    # Guide is time-fresh but either (a) all rows are unmatched
                    # (fetch ran before channels loaded), or (b) rows are legacy and
                    # lack a stored channel_name (so the DB-only relink can't
                    # fuzzy-match them). Re-fetch once this session to rebuild the
                    # match map and populate channel_name; afterwards the cheap
                    # relink handles everything without a network fetch.
                    logger.info(
                        f"EPG: provider {provider.name!r} has unmatched/unnamed guide "
                        f"data — triggering one-time re-fetch to rebuild channel links"
                    )
                    self._unmatched_refresh_attempted.add(provider.id)
                    self._start_refresh(provider.id, eff_url, provider.name, force=False)
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
            self._ensure_epg_url(provider, session)
            eff_url = self.effective_epg_url(provider)
            if not eff_url:
                logger.warning(f"EPG: no URL available for provider {provider_id}")
                return
            self._start_refresh(provider.id, eff_url, provider.name, force=True)
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

    def _start_refresh(self, provider_id: str, epg_url: str,
                       provider_name: str, force: bool) -> None:
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
            self._fetch_worker, provider_id, epg_url, provider_name, notif_id
        )

    def _fetch_worker(self, provider_id: str, epg_url: str,
                      provider_name: str, notif_id: str | None = None) -> None:
        """Background worker: download, parse, and store XMLTV data."""
        session = self.db.get_session()
        try:
            def on_parse_progress(count: int) -> None:
                self._progress_update.emit(
                    notif_id or "", count, -1,
                    f"Parsing… {count:,} programmes",
                )

            # Phase 1: download — indeterminate (no Content-Length on most XMLTV feeds)
            self._progress_update.emit(
                notif_id or "", 0, -1, "Downloading guide…"
            )

            # Parse the XMLTV feed
            channels, programmes = parse_xmltv_url(
                epg_url, timeout=180,
                on_progress=on_parse_progress if notif_id else None,
            )
            total_progs = len(programmes)

            # Phase 2: channel matching — indeterminate (fast, no useful fraction)
            self._progress_update.emit(
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
            self._progress_update.emit(
                notif_id or "", 0, -1, "Clearing old guide…"
            )
            session.query(EpgProgramDB).filter_by(provider_id=provider_id).delete()
            session.commit()  # release write lock before inserts start

            # Phase 4: bulk insert — now we know total, switch to determinate
            self._progress_update.emit(
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
                        self._progress_update.emit(
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
            count = session.query(EpgProgramDB).filter_by(provider_id=provider_id).count()
            logger.info(f"EPG: stored {count:,} programmes for {provider_name}")

            self.refresh_finished.emit(provider_id, count)
            self._progress_done.emit(notif_id or "", f"{count:,} programmes loaded")

        except Exception as e:
            logger.error(f"EPG refresh failed for {provider_name}: {e}")
            session.rollback()
            self.refresh_error.emit(provider_id, str(e))
            self._progress_error.emit(notif_id or "")
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

        Resolution order (first match wins):
        1. Exact ``epg_channel_id`` match — highest confidence, provider-agnostic.
        2. Same-provider fuzzy name match — normalized channel name from the feed's
           own provider wins over any cross-source match.
        3. Cross-provider fuzzy name match — fills gaps when the feed's own provider
           has no matching channel (e.g. a bare XMLTV feed covering multiple sources).

        Channels belonging to hidden (inactive or expired) providers are excluded from
        the fuzzy candidate pool entirely, so guide data never attaches to a
        disabled/expired source at fetch time.
        """
        repos = RepositoryFactory(session)
        hidden_ids: set[str] = set(repos.providers.get_hidden_provider_ids())

        # ── Tier 1: exact epg_channel_id match ──────────────────────────────
        # Select only the two scalar columns needed — avoids loading raw_data
        # (potentially large JSON) for every channel in a 1M+ library.
        db_channels_with_id = session.query(
            ChannelDB.id, ChannelDB.epg_channel_id,
        ).filter(
            ChannelDB.epg_channel_id.isnot(None),
            ChannelDB.is_hidden == False,
        ).all()
        exact: dict[str, str] = {
            epg_id: cid
            for cid, epg_id in db_channels_with_id
            if epg_id
        }

        # ── Tiers 2 & 3: fuzzy name candidates, excluding hidden providers ──
        # Build two separate dicts so same-provider always beats cross-provider.
        # Last-writer-wins within each dict is fine: duplicate normalized names
        # are rare and either candidate would be acceptable.
        # yield_per streams results in fixed-size buffers to avoid materialising
        # the full channel table (240k–1M rows) into memory at once.
        all_live = session.query(
            ChannelDB.id, ChannelDB.name, ChannelDB.provider_id,
        ).filter(
            ChannelDB.media_type == "live",
            ChannelDB.is_hidden == False,
        ).yield_per(10000)

        same_provider: dict[str, str] = {}   # norm_name → channel_db_id
        cross_provider: dict[str, str] = {}  # norm_name → channel_db_id

        for cid, name, prov_id in all_live:
            if prov_id in hidden_ids:
                continue  # never attach guide data to a disabled/expired source
            norm = normalize_channel_name(name)
            if prov_id == provider_id:
                same_provider[norm] = cid
            else:
                cross_provider[norm] = cid

        result: dict[str, str] = {}
        for xch in xmltv_channels:
            if xch.epg_id in exact:
                # Tier 1 — exact epg_channel_id
                result[xch.epg_id] = exact[xch.epg_id]
            else:
                norm = normalize_channel_name(xch.display_name)
                if norm in same_provider:
                    # Tier 2 — same-provider fuzzy
                    result[xch.epg_id] = same_provider[norm]
                elif norm in cross_provider:
                    # Tier 3 — cross-provider fuzzy
                    result[xch.epg_id] = cross_provider[norm]

        matched = len(result)
        logger.info(
            f"EPG channel matching: {matched}/{len(xmltv_channels)} XMLTV channels "
            f"matched to playable streams (provider={provider_id})"
        )
        return result

    # ------------------------------------------------------------------
    # Relink — DB-only re-match (no network fetch)
    # ------------------------------------------------------------------

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
                end_str = f" · data through {end.strftime('%a %b %d %I:%M%p').replace(' 0', ' ')}"

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
            provider_ids = [p.id for p in providers if getattr(p, "epg_url", "")]

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
        self.stop_notification_timer()
        self.stop_scheduler()
        self._executor.shutdown(wait=False)
