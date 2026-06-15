"""EPG Manager — fetch, parse, store XMLTV data + notification timer."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_utils import epg_is_stale, epg_interval_delta, now_utc
from metatv.core.repositories.provider import parse_provider_urls
from metatv.core.xmltv_parser import XmltvProgramme, normalize_channel_name, parse_xmltv_url


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

    def __init__(self, db: Database, config: Config, notifications=None, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.notifications = notifications  # NotificationManager or None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="epg")
        self._notified_this_session: set[int] = set()  # programme IDs already toasted
        self._notification_timer: QTimer | None = None
        self._notify.connect(self._do_notify)
        self._progress_update.connect(self._do_progress_update)
        self._progress_done.connect(self._do_progress_done)
        self._progress_error.connect(self._do_progress_error)
        self._active_refreshes: set[str] = set()  # provider IDs currently refreshing

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
        7. Time interval → True if elapsed since last fetch ≥ delta **OR** guide
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
            effective = getattr(self.config, "epg_default_refresh_interval", "3d") or "3d"
        else:
            effective = per_source

        data_end = getattr(provider, "epg_data_end", None)
        guide_expired = epg_is_stale(data_end)  # True if data_end < now_utc()

        if effective == "every_open":
            return True

        if effective == "when_stale":
            return guide_expired

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
        """
        if not self.config.epg_auto_refresh:
            return

        session = self.db.get_session()
        try:
            providers = session.query(ProviderDB).filter_by(is_active=True).all()
            for provider in providers:
                if not getattr(provider, "epg_enabled", True):
                    continue  # user disabled EPG for this provider
                self._ensure_epg_url(provider, session)
                eff_url = self.effective_epg_url(provider)
                if eff_url and provider.id not in self._active_refreshes and self.needs_refresh(provider):
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

            # Parse the XMLTV feed
            channels, programmes = parse_xmltv_url(
                epg_url, timeout=180,
                on_progress=on_parse_progress if notif_id else None,
            )
            total_progs = len(programmes)
            self._progress_update.emit(
                notif_id or "", 0, total_progs,
                f"Matching {total_progs:,} programmes to channels…"
            )

            # Build channel match map: epg_id → channel_db_id
            match_map = self._build_match_map(session, channels)
            logger.info(f"EPG: matched {len(match_map)} channels for {provider_name}")

            # Clear existing data — commit delete immediately so the write lock is released
            # before the bulk insert begins.  Each insert batch is also committed
            # separately so concurrent writers (provider loader, second EPG feed) can
            # interleave rather than waiting 30-40 s for one giant transaction.
            self._progress_update.emit(
                notif_id or "", 0, total_progs, f"Saving {total_progs:,} programmes…"
            )
            session.query(EpgProgramDB).filter_by(provider_id=provider_id).delete()
            session.commit()  # release write lock before inserts start

            batch: list[EpgProgramDB] = []
            max_stop: datetime | None = None
            min_start: datetime | None = None
            saved = 0
            _report_every = max(1, total_progs // 20)  # ~5% increments

            for prog in programmes:
                channel_db_id = match_map.get(prog.channel_id)
                row = EpgProgramDB(
                    provider_id    = provider_id,
                    channel_epg_id = prog.channel_id,
                    channel_db_id  = channel_db_id,
                    title          = prog.title,
                    description    = prog.description,
                    start_time     = prog.start_time,
                    stop_time      = prog.stop_time,
                    is_live        = prog.is_live,
                    is_new         = prog.is_new,
                )
                batch.append(row)

                if max_stop is None or prog.stop_time > max_stop:
                    max_stop = prog.stop_time
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
                provider.epg_last_fetched = now
                provider.epg_data_start = min_start
                provider.epg_data_end = max_stop
                # The provider's feed can serve year-old data (e.g. ottcst returns a
                # Jan-2025 snapshot). Flag it so it's not mistaken for our bug — the
                # EPG view / provider editor surface this to the user via epg_is_stale.
                if max_stop is not None and max_stop < now:
                    logger.warning(
                        f"EPG: {provider_name} returned STALE guide data — latest "
                        f"programme ends {max_stop:%Y-%m-%d} (before now). The provider's "
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

    def _build_match_map(self, session, xmltv_channels) -> dict[str, str]:
        """Build xmltv_epg_id → channel_db_id lookup.

        Primary match: ChannelDB.epg_channel_id == xmltv channel.epg_id (exact)
        Fallback: normalized display-name comparison against ALL live channels
        """
        # Exact match: channels with a populated epg_channel_id
        db_channels_with_id = session.query(ChannelDB).filter(
            ChannelDB.epg_channel_id.isnot(None),
            ChannelDB.is_hidden == False,
        ).all()
        exact: dict[str, str] = {
            ch.epg_channel_id: ch.id
            for ch in db_channels_with_id
            if ch.epg_channel_id
        }

        # Fuzzy fallback: normalize all live channel names
        all_live = session.query(ChannelDB).filter(
            ChannelDB.media_type == "live",
            ChannelDB.is_hidden == False,
        ).all()
        name_to_id: dict[str, str] = {
            normalize_channel_name(ch.name): ch.id
            for ch in all_live
        }

        result: dict[str, str] = {}
        for xch in xmltv_channels:
            if xch.epg_id in exact:
                result[xch.epg_id] = exact[xch.epg_id]
            else:
                norm = normalize_channel_name(xch.display_name)
                if norm in name_to_id:
                    result[xch.epg_id] = name_to_id[norm]

        matched = sum(1 for v in result.values() if v)
        logger.info(f"EPG channel matching: {matched}/{len(xmltv_channels)} XMLTV channels matched to playable streams")
        return result

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
        self._executor.shutdown(wait=False)
