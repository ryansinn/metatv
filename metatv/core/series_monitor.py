"""SeriesMonitorManager — detect new episodes for monitored series.

Workers run in a ``ThreadPoolExecutor(max_workers=1)`` to stay within the
SQLite-lock limit.  All config writes and ``NotificationManager`` calls happen
on the Qt main thread via private signals (same pattern as ``EpgManager``).

A monitored series can be mirrored across MULTIPLE providers (the same show
carried by two+ sources under the same ``content_key``).  Detection is
per-provider: each entry stores a ``baselines: {provider_id: episode_count}``
dict instead of one scalar count, and a new episode landing on ANY provider
that carries the series triggers the alert — not just the source the user
happened to click "Alert me" from.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
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


def _has_usable_episodes(episodes_data) -> bool:
    """Return True if *episodes_data* is a real (possibly-zero-count) payload.

    False for a missing/``None`` field, a non-dict/non-list value, or an empty
    top-level container — all of which mean the fetch failed or returned a
    malformed response, NOT that the series legitimately has zero episodes.
    ``_count_episodes`` can't tell these apart (both resolve to ``0``), so
    callers that are about to WRITE a baseline from a live fetch must check
    this first — a bare ``0`` from a flaky provider must never be recorded as
    the new baseline (root cause of #259: a flaky fetch stored baseline 0,
    then the next successful check reported the entire catalogue as "new").
    """
    if isinstance(episodes_data, dict):
        return bool(episodes_data)
    if isinstance(episodes_data, list):
        return bool(episodes_data)
    return False


def normalize_monitored_entry(entry: dict) -> dict:
    """Return *entry* with a per-provider ``baselines`` dict.

    Migrates the legacy single-provider shape (a scalar
    ``baseline_episode_count``) into ``baselines: {provider_id: count}``. Pure
    and side-effect-free — the caller decides whether/how to persist the
    result.  This is the single chokepoint both ``Config.get_monitored_series``
    (real config, migrate-on-read + write-back) and the worker below (defensive
    tolerance for entries handed to it directly, e.g. test doubles that stub
    ``Config`` without running the config-level migration) call.

    Args:
        entry: A raw monitored-series config dict.

    Returns:
        ``entry`` unchanged (same object) if it already carries a ``baselines``
        dict; otherwise a NEW dict with ``baselines`` populated from the legacy
        field (``{}`` when no legacy baseline was ever established).
    """
    if isinstance(entry.get("baselines"), dict):
        return entry
    migrated = dict(entry)
    provider_id = entry.get("provider_id")
    legacy = entry.get("baseline_episode_count")
    if provider_id and legacy is not None:
        migrated["baselines"] = {provider_id: legacy}
    else:
        migrated["baselines"] = {}
    return migrated


def clamp_inflated_unseen_new(entry: dict) -> dict:
    """Return *entry* with ``unseen_new`` clamped to the summed per-provider baselines.

    Repairs config state left over from the #259 baseline-accounting bug: a
    flaky provider fetch that returned an empty/malformed ``episodes``
    payload was stored as a baseline of ``0``, so the next successful check
    read the delta as the ENTIRE catalogue and ``unseen_new`` accumulated
    without bound across launches (one observed real-config case reached
    320 for a 132-episode show). ``unseen_new`` can never legitimately
    exceed the total episode count currently believed across every provider
    baseline, so any value above that sum is clamped down to the sum itself
    — this is both the one-time repair for already-inflated entries (called
    from ``Config.get_monitored_series``, the existing migrate-on-read
    chokepoint) AND the ongoing belt-and-braces guard applied to every fresh
    write (called from ``SeriesMonitorManager._on_new_episodes``), so a
    future accounting bug can't reproduce an absurd number either.

    Pure and side-effect-free — the caller decides whether/how to persist
    the result. Idempotent: once ``unseen_new`` is within the sane range (or
    there's no baseline data to check it against), a second call is a no-op
    and returns ``entry`` UNCHANGED (same object).

    Args:
        entry: A monitored-series config dict. Expected to already carry a
            ``baselines`` dict — call ``normalize_monitored_entry`` first for
            legacy entries.

    Returns:
        ``entry`` unchanged (same object) if ``unseen_new`` is already sane,
        absent, or there's no usable baseline data to validate against;
        otherwise a NEW dict with ``unseen_new`` clamped to
        ``sum(baselines.values())``.
    """
    baselines = entry.get("baselines")
    if not isinstance(baselines, dict) or not baselines:
        return entry
    unseen = entry.get("unseen_new")
    if not isinstance(unseen, int) or unseen <= 0:
        return entry
    sane_max = sum(v for v in baselines.values() if isinstance(v, int))
    if unseen <= sane_max:
        return entry
    logger.warning(
        f"series_monitor: clamping inflated unseen_new for "
        f"{entry.get('display_title') or entry.get('title', 'Unknown series')} "
        f"from {unseen} to {sane_max} (exceeds summed baselines {baselines})"
    )
    migrated = dict(entry)
    migrated["unseen_new"] = sane_max
    return migrated


class SeriesMonitorManager(QObject):
    """Checks monitored series for new episodes and fires notifications.

    Signals
    -------
    new_episodes_found : pyqtSignal(str, int)
        Emitted on the main thread when new episodes are confirmed.
        Args: (series_channel_id, total_unseen_count)

    checking_started / checking_finished : pyqtSignal()
        Public busy-state signals bracketing a check pass (startup, recurring
        timer, or post-provider-refresh) — views use these to show a subtle
        "checking…" hint.  Bracket a BATCH count, not a single call, so an
        overlapping ``check_provider`` + timer tick still resolves to a single
        busy→idle transition.

    _notify_new : private pyqtSignal(str, int, str, object)
        Internal signal that marshals a "new episodes" event from the worker
        thread to the main thread.
        Args: (series_channel_id, delta, title, payload) where payload is
        ``{"baselines": {provider_id: count}, "grown_provider_names": [str]}``.

    _check_batch_done : private pyqtSignal()
        Marshals "one submitted batch finished" from the worker thread to the
        main thread so the busy counter is only ever touched on the main thread.
    """

    # Public signals — views connect to these to refresh their display
    new_episodes_found = pyqtSignal(str, int)  # series_channel_id, total_unseen
    checking_started = pyqtSignal()
    checking_finished = pyqtSignal()

    # Private signals — marshal worker→main thread (NOT called from UI)
    _notify_new = pyqtSignal(str, int, str, object)  # cid, delta, title, payload
    _check_batch_done = pyqtSignal()

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
        self._pending_batches = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_all)
        # Wire private signals to main-thread slots
        self._notify_new.connect(self._on_new_episodes)
        self._check_batch_done.connect(self._on_check_batch_done)

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
        self._submit_check(entries)

    def check_all(self) -> None:
        """Check every monitored series across all providers.

        Called once on app startup (``QTimer.singleShot``), again after every
        recurring-timer tick (see ``start_scheduler``), and is the batch
        ``check_provider`` submits a subset of.
        """
        entries = self.config.get_monitored_series()
        if not entries:
            return
        self._submit_check(entries)

    def set_baseline(self, series_channel_id: str) -> None:
        """Compute the current episode count and store it as the baseline.

        Reads from the DB first (fast path).  If the series has no stored
        episodes yet, falls back to a live ``fetch_series_info`` call.
        Called when the user first starts monitoring a series.  Only sets the
        baseline for the entry's PRIMARY provider — any other provider mirror
        gets baselined silently on its first ``check_all``/timer pass.
        """
        self._executor.submit(self._worker_set_baseline, series_channel_id)

    def start_scheduler(self) -> None:
        """Arm the recurring recheck timer per ``config.series_monitor_interval_minutes``.

        0 (or a falsy/missing config value) disables the recurring recheck —
        the startup check and post-refresh ``check_provider`` calls still run.
        Safe to call repeatedly (e.g. after a settings change): stops any
        existing timer first and re-reads the current config value.
        """
        self._timer.stop()
        minutes = getattr(self.config, "series_monitor_interval_minutes", 60) or 0
        if minutes <= 0:
            logger.info("series_monitor: recurring recheck disabled (interval=0)")
            return
        self._timer.start(int(minutes) * 60 * 1000)
        logger.info(f"series_monitor: recurring recheck every {minutes} min")

    def stop_scheduler(self) -> None:
        """Stop the recurring recheck timer."""
        self._timer.stop()

    def shutdown(self) -> None:
        """Shut down the timer and executor without blocking the main thread."""
        self._timer.stop()
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Busy-state bookkeeping (checking_started / checking_finished)
    # ------------------------------------------------------------------

    def _submit_check(self, entries: list[dict]) -> None:
        """Submit *entries* to the executor, bracketing with checking_started/finished."""
        self._pending_batches += 1
        if self._pending_batches == 1:
            self.checking_started.emit()
        self._executor.submit(self._run_batch, entries)

    def _run_batch(self, entries: list[dict]) -> None:
        """Executor entry point: run the real worker, then signal completion."""
        try:
            self._worker_check_entries(entries)
        finally:
            self._check_batch_done.emit()

    def _on_check_batch_done(self) -> None:
        """Main-thread slot: decrement the busy counter, emit checking_finished at 0."""
        self._pending_batches = max(0, self._pending_batches - 1)
        if self._pending_batches == 0:
            self.checking_finished.emit()

    # ------------------------------------------------------------------
    # Worker — runs in executor (NO widget/config access)
    # ------------------------------------------------------------------

    def _resolve_mirrors(self, session, cid: str, primary_provider_id: str,
                          primary_source_id: str) -> list[tuple[str, str]]:
        """Return every (provider_id, source_id) currently carrying this series.

        Starts from the entry's primary provider, then adds any content_key
        siblings on OTHER (non-hidden) providers — the same series mirrored
        across sources.  Runs inside the caller's session (read-only).
        """
        from metatv.core.repositories import RepositoryFactory

        mirrors: list[tuple[str, str]] = [(primary_provider_id, primary_source_id)]
        repos = RepositoryFactory(session)
        primary_channel = repos.channels.get_by_id(cid)
        if not primary_channel or not primary_channel.content_key:
            return mirrors
        hidden = repos.providers.get_hidden_provider_ids()
        for sib in repos.channels.get_content_key_siblings(
            primary_channel.content_key, cid, excluded_provider_ids=hidden,
        ):
            if (
                sib.get("media_type") == "series"
                and sib.get("source_id")
                and sib.get("provider_id")
                and sib.get("provider_id") != primary_provider_id
            ):
                mirrors.append((sib["provider_id"], sib["source_id"]))
        return mirrors

    def _worker_check_entries(self, entries: list[dict]) -> None:
        """Check each monitored entry across every provider that carries it.

        Emits ``_notify_new`` once per entry with the summed delta across all
        providers that grew, plus the updated per-provider ``baselines`` and the
        display names of the provider(s) that grew (for toast/tooltip
        attribution).
        """
        from metatv.core.repositories import RepositoryFactory
        from metatv.providers.factory import get_provider

        for raw_entry in entries:
            entry = normalize_monitored_entry(raw_entry)
            cid = entry.get("series_channel_id")
            primary_provider_id = entry.get("provider_id")
            primary_source_id = entry.get("source_id")
            title = entry.get("display_title") or entry.get("title", "Unknown series")
            baselines: dict = dict(entry.get("baselines") or {})

            if not (cid and primary_provider_id and primary_source_id):
                logger.warning(
                    f"series_monitor: skipping entry with missing fields: {entry}"
                )
                continue

            try:
                with self.db.session_scope(commit=False) as session:
                    mirrors = self._resolve_mirrors(
                        session, cid, primary_provider_id, primary_source_id
                    )
            except Exception:
                logger.exception(f"series_monitor: error resolving mirrors for {title}")
                mirrors = [(primary_provider_id, primary_source_id)]

            new_baselines = dict(baselines)
            grown: dict[str, int] = {}        # provider_id -> delta
            grown_names: dict[str, str] = {}  # provider_id -> display name

            for provider_id, source_id in mirrors:
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
                            f"series_monitor: unexpected response for {title} on "
                            f"{provider_id}: {type(data)}"
                        )
                        continue

                    episodes_field = data.get("episodes")
                    if not _has_usable_episodes(episodes_field):
                        # Missing/malformed/empty episodes payload — a provider
                        # hiccup, not proof the series lost every episode. Skip
                        # the baseline write for THIS provider entirely (new_
                        # baselines already carries whatever value it had before
                        # this pass, since it started as a copy of `baselines`)
                        # rather than silently recording a 0 that the next
                        # successful check would read as "everything is new".
                        logger.warning(
                            f"series_monitor: no usable episodes payload for "
                            f"{title} on {provider.name} — skipping baseline "
                            f"update this pass"
                        )
                        continue

                    current_count = _count_episodes(episodes_field)
                    prev = baselines.get(provider_id)

                    if prev is None:
                        # Baseline not yet established for THIS provider — establish
                        # it now without notifying, so we never alert on a mirror's
                        # entire back-catalog the first time it's seen.
                        logger.info(
                            f"series_monitor: establishing baseline for {title} on "
                            f"{provider.name} = {current_count}"
                        )
                        new_baselines[provider_id] = current_count
                        continue

                    if current_count < prev:
                        # A drop means a provider hiccup, not deleted episodes —
                        # never lower a stored baseline. new_baselines already
                        # holds `prev` (it started as a copy of `baselines`), so
                        # just leave it alone and treat this pass as unchanged.
                        logger.warning(
                            f"series_monitor: {title} on {provider.name} reported "
                            f"fewer episodes than the stored baseline "
                            f"({current_count} < {prev}) — keeping the higher "
                            f"baseline"
                        )
                        continue

                    delta = current_count - prev
                    new_baselines[provider_id] = current_count

                    if delta > 0:
                        logger.info(
                            f"series_monitor: {title} grew by {delta} episode(s) on "
                            f"{provider.name} ({prev} → {current_count})"
                        )
                        grown[provider_id] = delta
                        grown_names[provider_id] = provider.name
                    else:
                        logger.debug(
                            f"series_monitor: {title} unchanged on {provider.name} "
                            f"({current_count} episodes)"
                        )

                except Exception:
                    logger.exception(
                        f"series_monitor: error checking {title} on {provider_id} "
                        f"({source_id})"
                    )

            total_delta = sum(grown.values())
            payload = {
                "baselines": new_baselines,
                "grown_provider_names": [grown_names[pid] for pid in grown],
            }
            self._notify_new.emit(cid, total_delta, title, payload)

    def _worker_set_baseline(self, series_channel_id: str) -> None:
        """Compute and persist the current baseline for a series' PRIMARY provider."""
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

        def _emit_baseline(count: int) -> None:
            self._notify_new.emit(
                series_channel_id, 0, title,
                {"baselines": {provider_id: count}, "grown_provider_names": []},
            )

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
                _emit_baseline(episode_count)
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

            episodes_field = data.get("episodes")
            if not _has_usable_episodes(episodes_field):
                logger.warning(
                    f"series_monitor: no usable episodes payload for baseline "
                    f"of {title} — not establishing a baseline from this fetch"
                )
                return

            episode_count = _count_episodes(episodes_field)
            logger.info(
                f"series_monitor: baseline for {title} = {episode_count} (from API)"
            )
            _emit_baseline(episode_count)

        except Exception:
            logger.exception(
                f"series_monitor: error setting baseline for {title}"
            )

    # ------------------------------------------------------------------
    # Main-thread slot
    # ------------------------------------------------------------------

    def _on_new_episodes(
        self, series_channel_id: str, delta: int, title: str, payload: dict
    ) -> None:
        """Main-thread handler: update config and fire notification.

        ``payload`` is ``{"baselines": {provider_id: count}, "grown_provider_names":
        [str]}`` — the FULL per-provider baseline snapshot from this check (merged
        over any baseline for a provider not covered by this check, so a provider
        that dropped out never silently loses its recorded baseline) plus the
        display names of the provider(s) that grew, for toast/tooltip attribution.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = payload or {}
        checked_baselines = payload.get("baselines") or {}
        grown_names = payload.get("grown_provider_names") or []

        existing_unseen = 0
        existing_baselines: dict = {}
        for e in self.config.get_monitored_series():
            if e.get("series_channel_id") == series_channel_id:
                existing_unseen = e.get("unseen_new", 0)
                existing_baselines = dict(e.get("baselines") or {})
                break
        merged_baselines = {**existing_baselines, **checked_baselines}

        if delta > 0:
            # Belt-and-braces guard: unseen_new can never legitimately exceed
            # the total episode count currently believed across every
            # provider baseline. Reuses the same clamp the one-time config
            # migration applies (clamp_inflated_unseen_new), so a future
            # accounting bug can't reproduce an absurd number either.
            clamped = clamp_inflated_unseen_new({
                "baselines": merged_baselines,
                "unseen_new": existing_unseen + delta,
            })
            total_unseen = clamped["unseen_new"]

            self.config.update_monitored_series(
                series_channel_id,
                baselines=merged_baselines,
                unseen_new=total_unseen,
                growth_providers=grown_names,
                last_checked=now_iso,
            )

            if self.notifications:
                ep_word = "episode" if delta == 1 else "episodes"
                provider_suffix = f" on {', '.join(grown_names)}" if grown_names else ""
                self.notifications.show(
                    title=title,
                    message=f"{delta} new {ep_word} available{provider_suffix}",
                    type="info",
                    auto_dismiss_ms=6000,
                )

            self.new_episodes_found.emit(series_channel_id, total_unseen)
        else:
            # delta == 0: just update baselines and last_checked (baselines may
            # include a freshly-established provider whose stored value was 0).
            self.config.update_monitored_series(
                series_channel_id,
                baselines=merged_baselines,
                last_checked=now_iso,
            )
