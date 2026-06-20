"""SeriesMonitorManager — detect new episodes for monitored series.

Workers run in a ``ThreadPoolExecutor(max_workers=1)`` to stay within the
SQLite-lock limit.  All config writes and ``NotificationManager`` calls happen
on the Qt main thread via private signals (same pattern as ``EpgManager``).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.notifications import NotificationManager


def _count_episodes(episodes_data) -> int:
    """Count total episodes from the raw episodes field returned by fetch_series_info.

    ``episodes_data`` is either a dict keyed by season-number string (each value
    is a list of episode dicts) or, in rare cases, a plain list.
    """
    if isinstance(episodes_data, dict):
        return sum(
            len(v) for v in episodes_data.values() if isinstance(v, list)
        )
    if isinstance(episodes_data, list):
        return len(episodes_data)
    return 0


class SeriesMonitorManager(QObject):
    """Checks monitored series for new episodes and fires notifications.

    Signals
    -------
    new_episodes_found : pyqtSignal(str, int)
        Emitted on the main thread when new episodes are confirmed.
        Args: (series_channel_id, total_unseen_count)

    _notify_new : private pyqtSignal(str, int, str, int)
        Internal signal that marshals a "new episodes" event from the worker
        thread to the main thread.
        Args: (series_channel_id, delta, title, new_total_count)
    """

    # Public signal — views connect to this to refresh their display
    new_episodes_found = pyqtSignal(str, int)  # series_channel_id, total_unseen

    # Private signal — marshals worker→main thread (NOT called from UI)
    _notify_new = pyqtSignal(str, int, str, int)  # cid, delta, title, new_total

    def __init__(
        self,
        db: "Database",
        config: "Config",
        notifications: "NotificationManager | None" = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.notifications = notifications
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="series_monitor"
        )
        # Wire private signal to main-thread slot
        self._notify_new.connect(self._on_new_episodes)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_provider(self, provider_id: str) -> None:
        """Submit a worker that checks all monitored series for *provider_id*.

        Safe to call from any thread; the actual work runs in the executor.
        """
        entries = self.config.get_monitored_for_provider(provider_id)
        if not entries:
            return
        self._executor.submit(self._worker_check_entries, entries)

    def check_all(self) -> None:
        """Check every monitored series across all providers.

        Intended to be called once on app startup (via ``QTimer.singleShot``).
        """
        entries = self.config.get_monitored_series()
        if not entries:
            return
        self._executor.submit(self._worker_check_entries, entries)

    def set_baseline(self, series_channel_id: str) -> None:
        """Compute the current episode count and store it as the baseline.

        Reads from the DB first (fast path).  If the series has no stored
        episodes yet, falls back to a live ``fetch_series_info`` call.
        Called when the user first starts monitoring a series.
        """
        self._executor.submit(self._worker_set_baseline, series_channel_id)

    def shutdown(self) -> None:
        """Shut down the executor without blocking the main thread."""
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Worker — runs in executor (NO widget/config access)
    # ------------------------------------------------------------------

    def _worker_check_entries(self, entries: list[dict]) -> None:
        """Check each monitored entry; emit _notify_new for each that has grown."""
        from metatv.core.repositories import RepositoryFactory
        from metatv.providers.factory import get_provider

        for entry in entries:
            cid = entry.get("series_channel_id")
            source_id = entry.get("source_id")
            provider_id = entry.get("provider_id")
            title = entry.get("title", "Unknown series")
            baseline = entry.get("baseline_episode_count")

            if not (cid and source_id and provider_id):
                logger.warning(
                    f"series_monitor: skipping entry with missing fields: {entry}"
                )
                continue

            try:
                with self.db.session_scope(commit=False) as session:
                    repos = RepositoryFactory(session)
                    provider_db = repos.providers.get_by_id(provider_id)
                    if not provider_db:
                        logger.warning(
                            f"series_monitor: provider {provider_id} not found, "
                            f"skipping {title}"
                        )
                        continue
                    provider = repos.providers.to_model(provider_db)

                plugin = get_provider(provider.type)
                if not plugin:
                    logger.warning(
                        f"series_monitor: no plugin for provider type "
                        f"{provider.type}, skipping {title}"
                    )
                    continue

                data = asyncio.run(plugin.fetch_series_info(provider, source_id))
                if not isinstance(data, dict):
                    logger.warning(
                        f"series_monitor: unexpected response for {title}: {type(data)}"
                    )
                    continue

                episodes_data = data.get("episodes", {})
                current_count = _count_episodes(episodes_data)

                if baseline is None:
                    # Baseline not yet established (set_baseline failed, or hasn't
                    # landed yet) — establish it now WITHOUT notifying, so we never
                    # alert on the entire back-catalog. The delta=0 slot persists it.
                    logger.info(
                        f"series_monitor: establishing baseline for {title} "
                        f"= {current_count}"
                    )
                    self._notify_new.emit(cid, 0, title, current_count)
                    continue

                delta = current_count - baseline

                if delta > 0:
                    logger.info(
                        f"series_monitor: {title} grew by {delta} episode(s) "
                        f"({baseline} → {current_count})"
                    )
                    # Marshal to main thread — pass new_total so slot can update baseline
                    self._notify_new.emit(cid, delta, title, current_count)
                else:
                    logger.debug(
                        f"series_monitor: {title} unchanged ({current_count} episodes)"
                    )
                    # Still update last_checked timestamp (use a signal + update via slot
                    # would be overkill; this is fire-and-forget so we emit with delta=0
                    # and handle in _on_new_episodes with a guard).
                    # Actually: emit with delta=0 triggers no notification but updates
                    # last_checked.  Use a dedicated signal path.
                    self._notify_new.emit(cid, 0, title, current_count)

            except Exception:
                logger.exception(
                    f"series_monitor: error checking {title} ({source_id})"
                )

    def _worker_set_baseline(self, series_channel_id: str) -> None:
        """Compute and persist the current baseline for a series."""
        from metatv.core.database import EpisodeDB, SeasonDB
        from metatv.core.repositories import RepositoryFactory
        from metatv.providers.factory import get_provider

        entry = next(
            (e for e in self.config.get_monitored_series()
             if e.get("series_channel_id") == series_channel_id),
            None,
        )
        if not entry:
            logger.warning(
                f"series_monitor: set_baseline called for unmonitored id "
                f"{series_channel_id}"
            )
            return

        source_id = entry.get("source_id")
        provider_id = entry.get("provider_id")
        title = entry.get("title", "Unknown")

        try:
            # Fast path: count from the DB (seasons → episodes already stored)
            with self.db.session_scope(commit=False) as session:
                season_rows = (
                    session.query(SeasonDB)
                    .filter(SeasonDB.series_id == series_channel_id)
                    .all()
                )
                season_ids = [s.id for s in season_rows]
                episode_count = 0
                if season_ids:
                    episode_count = (
                        session.query(EpisodeDB)
                        .filter(EpisodeDB.season_id.in_(season_ids))
                        .count()
                    )

            if episode_count > 0:
                logger.info(
                    f"series_monitor: baseline for {title} = {episode_count} (from DB)"
                )
                self._notify_new.emit(series_channel_id, 0, title, episode_count)
                return

            # Slow path: no stored episodes yet — fetch live
            with self.db.session_scope(commit=False) as session:
                repos = RepositoryFactory(session)
                provider_db = repos.providers.get_by_id(provider_id)
                if not provider_db:
                    logger.warning(
                        f"series_monitor: provider {provider_id} not found for "
                        f"baseline of {title}"
                    )
                    return
                provider = repos.providers.to_model(provider_db)

            plugin = get_provider(provider.type)
            if not plugin:
                logger.warning(
                    f"series_monitor: no plugin for {provider.type}, "
                    f"cannot set baseline for {title}"
                )
                return

            data = asyncio.run(plugin.fetch_series_info(provider, source_id))
            if not isinstance(data, dict):
                logger.warning(
                    f"series_monitor: unexpected response for baseline of {title}"
                )
                return

            episode_count = _count_episodes(data.get("episodes", {}))
            logger.info(
                f"series_monitor: baseline for {title} = {episode_count} (from API)"
            )
            # delta=0 → no notification; just update the stored baseline
            self._notify_new.emit(series_channel_id, 0, title, episode_count)

        except Exception:
            logger.exception(
                f"series_monitor: error setting baseline for {title}"
            )

    # ------------------------------------------------------------------
    # Main-thread slot
    # ------------------------------------------------------------------

    def _on_new_episodes(
        self, series_channel_id: str, delta: int, title: str, new_total: int
    ) -> None:
        """Main-thread handler: update config and fire notification."""
        now_iso = datetime.now(timezone.utc).isoformat()

        if delta > 0:
            # Accumulate unseen count
            existing_unseen = 0
            for e in self.config.get_monitored_series():
                if e.get("series_channel_id") == series_channel_id:
                    existing_unseen = e.get("unseen_new", 0)
                    break

            self.config.update_monitored_series(
                series_channel_id,
                baseline_episode_count=new_total,
                unseen_new=existing_unseen + delta,
                last_checked=now_iso,
            )

            if self.notifications:
                ep_word = "episode" if delta == 1 else "episodes"
                self.notifications.show(
                    title=title,
                    message=f"{delta} new {ep_word} available",
                    type="info",
                    auto_dismiss_ms=6000,
                )

            total_unseen = existing_unseen + delta
            self.new_episodes_found.emit(series_channel_id, total_unseen)
        else:
            # delta == 0: just update baseline and last_checked (baseline may have
            # come from a set_baseline call where the stored value was 0).
            self.config.update_monitored_series(
                series_channel_id,
                baseline_episode_count=new_total,
                last_checked=now_iso,
            )
