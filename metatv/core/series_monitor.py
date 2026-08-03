"""SeriesMonitorManager — detect new episodes for monitored series.

Workers run in a ``ThreadPoolExecutor(max_workers=1)`` to stay within the
SQLite-lock limit.  All config writes and ``NotificationManager`` calls happen
on the Qt main thread via private signals (same pattern as ``EpgManager``).

A monitored series can be mirrored across MULTIPLE listings (the same show
carried by two+ sources — or by two+ listings on ONE source — under the same
``content_key``).  Detection is per-MIRROR: each entry stores a
``baselines: {"provider_id|source_id": episode_count}`` dict instead of one
scalar count, and a new episode landing on ANY mirror triggers the alert — not
just the listing the user happened to click "Alert me" from.

The key is (provider, source), not provider alone. ``content_key`` is a
deliberately generous identity, so one provider routinely carries several
listings that collapse to the same key; under a provider-only key those
overwrote a single slot and were each compared against the same stale ``prev``,
manufacturing "+N episodes" alerts that grew every launch until the clamp
pinned them to the provider's TOTAL episode count. See :func:`mirror_key`.
"""

from __future__ import annotations

import asyncio
import threading
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


#: Separator joining a mirror's provider id and source id into one baseline key.
#: Provider ids are UUIDs and source ids are numeric, so a pipe can never occur
#: inside either half — which is what makes :func:`is_mirror_key` reliable.
_MIRROR_SEP = "|"


def mirror_key(provider_id: str, source_id) -> str:
    """Return the ``baselines`` key identifying ONE mirror of a series.

    Keyed by (provider, source) rather than by provider alone: a single provider
    can carry several listings that share a ``content_key``, and with a
    provider-only key each of those overwrote the same slot while every one of
    them was compared against the same stale ``prev``. That produced fabricated
    "+N episodes" alerts that grew on every launch (owner report 2026-08-02:
    "Rick And Morty +132 eps", which was the provider's TOTAL episode count, not
    new episodes).
    """
    return f"{provider_id}{_MIRROR_SEP}{source_id}"


def is_mirror_key(key: str) -> bool:
    """True if *key* is the (provider, source) form rather than a bare provider id."""
    return _MIRROR_SEP in key


def provider_of(key: str) -> str:
    """Return the provider id half of a baseline key (works on both shapes)."""
    return key.split(_MIRROR_SEP, 1)[0]


def normalize_monitored_entry(entry: dict) -> dict:
    """Return *entry* with a per-MIRROR ``baselines`` dict.

    Handles both historical shapes. Pure and side-effect-free — the caller
    decides whether/how to persist the result. This is the single chokepoint
    both ``Config.get_monitored_series`` (real config, migrate-on-read +
    write-back) and the worker below (defensive tolerance for entries handed to
    it directly, e.g. test doubles that stub ``Config`` without running the
    config-level migration) call.

    Two migrations, oldest first:

    1. Scalar ``baseline_episode_count`` → a dict.
    2. Provider-keyed ``{provider_id: count}`` → mirror-keyed
       ``{"provider|source": count}``. Only the PRIMARY provider's baseline
       survives, because it is the only one whose ``source_id`` the entry
       records; a non-primary provider's count cannot be attributed to a
       specific listing, and keeping it under a guessed key would preserve the
       very confusion this migration exists to remove. Dropped baselines are
       re-established silently on the next check (the ``prev is None`` path
       never alerts), so the cost is one quiet cycle, not a false alert.

    ``unseen_new`` is also reset to 0 whenever a provider-keyed baseline is
    migrated: those counts were produced by the collision and are *proven*
    corrupt, not merely implausible, so they are discarded rather than clamped
    (same reasoning as ``zero_out_inflated_unseen_new`` vs.
    ``clamp_unseen_new_to_baseline_total``).

    Args:
        entry: A raw monitored-series config dict.

    Returns:
        ``entry`` unchanged (same object) when it already carries mirror-keyed
        baselines; otherwise a NEW dict.
    """
    baselines = entry.get("baselines")
    provider_id = entry.get("provider_id")
    source_id = entry.get("source_id")

    if not isinstance(baselines, dict):
        migrated = dict(entry)
        legacy = entry.get("baseline_episode_count")
        if provider_id and source_id is not None and legacy is not None:
            migrated["baselines"] = {mirror_key(provider_id, source_id): legacy}
        else:
            migrated["baselines"] = {}
        return migrated

    if not baselines or all(is_mirror_key(k) for k in baselines):
        return entry

    # Provider-keyed (or mixed) — rebuild, keeping only what can be attributed.
    migrated = dict(entry)
    rebuilt = {k: v for k, v in baselines.items() if is_mirror_key(k)}
    if provider_id and source_id is not None and provider_id in baselines:
        rebuilt[mirror_key(provider_id, source_id)] = baselines[provider_id]
    dropped = [k for k in baselines if not is_mirror_key(k) and k != provider_id]
    if dropped:
        logger.info(
            f"series_monitor: {entry.get('title', 'series')} — dropping "
            f"{len(dropped)} provider-keyed baseline(s) that cannot be tied to "
            f"a specific listing; they re-establish silently on the next check"
        )
    migrated["baselines"] = rebuilt
    if entry.get("unseen_new"):
        logger.info(
            f"series_monitor: {entry.get('title', 'series')} — resetting "
            f"unseen_new={entry.get('unseen_new')} (produced by the "
            f"provider-keyed baseline collision, proven corrupt)"
        )
    migrated["unseen_new"] = 0
    migrated["growth_providers"] = []
    return migrated


def _inflated_unseen(entry: dict) -> tuple[int, int] | None:
    """Return ``(unseen_new, sane_max)`` if *entry*'s ``unseen_new`` exceeds its
    summed per-provider baselines, else ``None`` (nothing to correct: no usable
    baseline data, ``unseen_new`` absent/non-positive, or already sane).

    Shared by ``zero_out_inflated_unseen_new`` and
    ``clamp_unseen_new_to_baseline_total`` — the single place that decides
    WHETHER an entry is inflated; the two callers differ only in HOW they
    correct it (reset to 0 vs. clamp to the sum).
    """
    baselines = entry.get("baselines")
    if not isinstance(baselines, dict) or not baselines:
        return None
    unseen = entry.get("unseen_new")
    if not isinstance(unseen, int) or unseen <= 0:
        return None
    sane_max = sum(v for v in baselines.values() if isinstance(v, int))
    if unseen <= sane_max:
        return None
    return unseen, sane_max


def zero_out_inflated_unseen_new(entry: dict) -> dict:
    """One-time repair: reset a PROVEN-CORRUPT ``unseen_new`` to 0.

    Repairs config state left over from the #259 baseline-accounting bug: a
    flaky provider fetch that returned an empty/malformed ``episodes``
    payload was stored as a baseline of ``0``, so the next successful check
    read the delta as the ENTIRE catalogue and ``unseen_new`` accumulated
    without bound across launches (one observed real-config case reached 320
    for a 132-episode show). A count found ``unseen_new > sum(baselines)`` is
    PROVEN corrupt (the owner's confirmation: none of the excess was real new
    episodes) and carries no recoverable signal — there's no way to tell
    which, if any, of the recorded "unseen" episodes were genuine, so 0 is
    the honest value, not a clamped guess. Because the baselines themselves
    are correct once this bug is fixed, any genuinely new episode is
    detected fresh on the very next check — nothing is lost going forward.

    This is THE ONE-TIME REPAIR ONLY — called from
    ``Config.get_monitored_series``, the existing migrate-on-read
    chokepoint. The ONGOING guard applied to every fresh write is the
    different, deliberately more conservative
    ``clamp_unseen_new_to_baseline_total`` (a fresh write isn't proven
    corrupt, just implausible, so it's clamped rather than discarded).

    Pure and side-effect-free — the caller decides whether/how to persist
    the result. Idempotent: once ``unseen_new`` is 0 (or otherwise within
    the sane range, or there's no baseline data to check it against), a
    second call is a no-op and returns ``entry`` UNCHANGED (same object).

    Args:
        entry: A monitored-series config dict. Expected to already carry a
            ``baselines`` dict — call ``normalize_monitored_entry`` first for
            legacy entries.

    Returns:
        ``entry`` unchanged (same object) if ``unseen_new`` is already sane,
        absent, or there's no usable baseline data to validate against;
        otherwise a NEW dict with ``unseen_new`` reset to ``0``.
    """
    check = _inflated_unseen(entry)
    if check is None:
        return entry
    unseen, sane_max = check
    title = entry.get("display_title") or entry.get("title", "Unknown series")
    logger.warning(
        f"series_monitor: resetting corrupt unseen_new for {title} from "
        f"{unseen} to 0 (exceeded summed baselines, sum={sane_max})"
    )
    migrated = dict(entry)
    migrated["unseen_new"] = 0
    return migrated


def clamp_unseen_new_to_baseline_total(entry: dict) -> dict:
    """Ongoing guard: clamp (never zero) an implausible ``unseen_new`` on a
    FRESH write down to the summed per-provider baselines.

    Applied to every write in ``SeriesMonitorManager._on_new_episodes`` as a
    belt-and-braces bound — the value here is not proven corrupt (unlike the
    one-time repair's starting state), just implausible, so the conservative
    move is to cap it at the total episode count currently believed across
    every provider baseline rather than discard it outright. This is what
    stops a FUTURE accounting bug from reproducing an absurd number.

    This is THE ONGOING GUARD ONLY. The different, one-time repair for
    entries already PROVEN corrupt by the #259 bug is
    ``zero_out_inflated_unseen_new`` (resets to 0, not the sum) — see its
    docstring for why the two calls make different corrections.

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
    check = _inflated_unseen(entry)
    if check is None:
        return entry
    unseen, sane_max = check
    title = entry.get("display_title") or entry.get("title", "Unknown series")
    logger.warning(
        f"series_monitor: clamping unseen_new for {title} from {unseen} to "
        f"{sane_max} (exceeds summed baselines {entry.get('baselines')})"
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
        # Set by shutdown(). ThreadPoolExecutor.shutdown(wait=False) stops NEW
        # work but cannot interrupt the batch already running, so without this
        # the in-flight worker kept issuing live HTTP fetches for every
        # remaining series after Database.close() had run — ending in
        # "cannot schedule new futures after interpreter shutdown" and a
        # WARNING per series on every app exit.
        self._stopping = threading.Event()
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
        """Shut down the timer and executor without blocking the main thread.

        Sets the stop flag FIRST: ``shutdown(wait=False)`` prevents new
        submissions but leaves the running batch untouched, and that batch
        outlives ``Database.close()``. The worker polls the flag between
        entries so it unwinds instead of fetching on into teardown.
        """
        self._stopping.set()
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
        # Dedupe on the full (provider, source) pair. content_key is a
        # deliberately generous identity, so a single provider can contribute
        # several distinct listings here — that is legitimate (each is a real
        # separate listing with its own episode count) and each now gets its own
        # baseline slot. What must not happen is the SAME pair being checked
        # twice in one pass, which would fetch twice and compare the second
        # result against a baseline the first just wrote.
        seen = {(primary_provider_id, str(primary_source_id))}
        for sib in repos.channels.get_content_key_siblings(
            primary_channel.content_key, cid, excluded_provider_ids=hidden,
        ):
            if not (
                sib.get("media_type") == "series"
                and sib.get("source_id")
                and sib.get("provider_id")
            ):
                continue
            pair = (sib["provider_id"], str(sib["source_id"]))
            if pair in seen:
                continue
            seen.add(pair)
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
            if self._stopping.is_set():
                logger.debug(
                    "series_monitor: stop requested — abandoning the rest of "
                    "this batch"
                )
                return
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
            grown: dict[str, int] = {}        # mirror key -> delta
            grown_names: dict[str, str] = {}  # mirror key -> provider display name

            for provider_id, source_id in mirrors:
                mkey = mirror_key(provider_id, source_id)
                # Each mirror is a separate live fetch, so a multi-mirror entry
                # can span the whole teardown window on its own — poll here too,
                # not just per entry.
                if self._stopping.is_set():
                    return
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
                    prev = baselines.get(mkey)

                    if prev is None:
                        # Baseline not yet established for THIS provider — establish
                        # it now without notifying, so we never alert on a mirror's
                        # entire back-catalog the first time it's seen.
                        logger.info(
                            f"series_monitor: establishing baseline for {title} on "
                            f"{provider.name} = {current_count}"
                        )
                        new_baselines[mkey] = current_count
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
                    new_baselines[mkey] = current_count

                    if delta > 0:
                        logger.info(
                            f"series_monitor: {title} grew by {delta} episode(s) on "
                            f"{provider.name} ({prev} → {current_count})"
                        )
                        grown[mkey] = delta
                        grown_names[mkey] = provider.name
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
                # dict.fromkeys: several mirrors on ONE provider can grow in the
                # same pass now that each has its own baseline, and the display
                # list must not repeat that provider's name once per listing.
                # Preserves first-seen order.
                "grown_provider_names": list(dict.fromkeys(
                    grown_names[k] for k in grown
                )),
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
            # Ongoing belt-and-braces guard: unseen_new can never legitimately
            # exceed the total episode count currently believed across every
            # provider baseline. This value is NOT proven corrupt (unlike the
            # one-time config migration's starting state) -- just implausible
            # -- so it's CLAMPED to the sum, never zeroed. See
            # clamp_unseen_new_to_baseline_total's docstring for the
            # distinction from zero_out_inflated_unseen_new (the migration).
            clamped = clamp_unseen_new_to_baseline_total({
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
