"""Per-provider connection accountant — the single arbiter of how many
simultaneous connections a provider's backend may have open at once.

This is the future single chokepoint for playback + downloads + recordings
per the Wave 5 roadmap; this slice only wires up playback (``PlayerManager``).
A future download/recording manager registers holders through the exact same
``acquire``/``release`` seam with ``kind="download"``/``kind="recording"``.

Not Qt, not DB-aware: capacity is resolved through a callable injected at
construction (``capacity_resolver: Callable[[str], int]``), so callers can
back it with ``ProviderDB.max_connections``/``config.max_player_instances``
semantics without coupling this module to SQLAlchemy or the Qt event loop.
That keeps it usable from a background thread and fully unit-testable with a
fake resolver — no real Database required.

Why "would_exceed" is rare today: MetaTV's playback layer already dedups
repeated plays of the same provider onto a single mpv window per instance key
(Split Streams keying, see ``PlayerManager._resolve_instance_key`` and
docs/CRITICAL_RULES.md#player-instance-keying) — reusing a key is idempotent
here (``acquire`` never double-counts a holder_id already registered under the
same provider). A provider's distinct holder count only grows past one when a
genuinely separate connection opens alongside an existing one — e.g.
"Play in New Window" opening a second window while the shared window is still
playing that same provider, or ``player_mode == "multiple-instances"`` where
every play spawns an independent process. Those are the only paths that can
reach the ``granted=False`` branch of :meth:`ConnectionAccountant.acquire`
today.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence

from loguru import logger


@dataclass(frozen=True)
class Holder:
    """One registered connection against a provider's capacity."""

    holder_id: str
    kind: str  # "playback" this slice; "download"/"recording" are future consumers


@dataclass(frozen=True)
class AcquireResult:
    """Outcome of an :meth:`ConnectionAccountant.acquire` or ``preview`` call."""

    granted: bool
    provider_id: str
    capacity: int              # 0 = unlimited (never exceeded)
    holders: tuple[str, ...]   # holder_ids occupying a slot at decision time
    #: Holders evicted to make room, when the caller passed ``preempt_kinds``.
    #: Empty on every grant that needed no eviction, so a caller can tell
    #: "there was room" from "I took someone's room" — which is the difference
    #: between saying nothing and telling the user their download paused.
    preempted: tuple[str, ...] = ()


class ConnectionAccountant:
    """Thread-safe per-provider connection arbiter.

    Pure Python — no Qt, no DB. Safe to call from any thread; a single
    ``threading.Lock`` guards the holder registry (acquire/release/reconcile
    never call each other re-entrantly, so a plain non-reentrant lock is
    sufficient — see the docstring on each method for what it does and does
    not touch while holding the lock).
    """

    #: Seconds a provider stays off-limits to BACKGROUND work after playback
    #: touches it.
    #:
    #: The accountant frees a slot the instant our HTTP call returns. The
    #: PROVIDER does not: an Xtream panel keeps counting a closed connection
    #: against ``active_cons`` until its own reaper expires the record, which
    #: is tens of seconds. So "we released it" and "you may open one" are not
    #: the same statement, and treating them as one is why playback still
    #: failed after #634.
    #:
    #: Measured on the owner's account (max_connections=1), 2026-09-01:
    #: series_monitor made six back-to-back calls to operator1.barfik.org at
    #: 03:58:06-09; plays at 03:58:12, :20 and :26 all got
    #: HTTP 500 "failed to redirect to stream origin", and the identical URL
    #: returned 206 with real Matroska bytes once the app had been shut for a
    #: few minutes. Sixty seconds covers the panels seen so far.
    PROVIDER_COOLDOWN_S: float = 60.0

    #: Kinds that are the user waiting. Never subject to the cooldown, and the
    #: only kinds that arm it.
    FOREGROUND_KINDS: frozenset[str] = frozenset({"playback", "recording"})

    #: The cooldown applies ONLY where capacity is exactly 1.
    #:
    #: That is where the provider's lag actually bites: there is no headroom,
    #: so a slot the panel has not yet reaped is a slot the user cannot have.
    #: With two or more, ordinary capacity arbitration plus the eviction
    #: listeners (#634) already cover it — and holding background work off a
    #: five-connection account for a minute after every play would starve
    #: enrichment for nothing. Unlimited (0) never cools.

    #: Seconds a freshly-registered holder is immune to a dead-holder sweep.
    #:
    #: A play registers its holder BEFORE its mpv process exists
    #: (``PlayerManager.play()`` acquires, then launches the process), so a
    #: liveness probe taken in that window would report the holder as not
    #: yet alive — and a sweep with no grace could evict a play that is a
    #: hundred milliseconds old. Ten seconds is comfortably longer than mpv's
    #: own startup. This applies to EVERY :meth:`reconcile` caller, including
    #: the explicit play()/stop() sweeps (``PlayerManager._reconcile_connections``)
    #: — a genuinely crashed mpv is now swept up to ten seconds later than
    #: before, which is fine: nothing depended on sub-second reconciliation.
    RECONCILE_GRACE_S: float = 10.0

    def __init__(self, capacity_resolver: Callable[[str], int],
                 on_preempt: "Optional[Callable[[str, str, str], None]]" = None,
                 clock: "Optional[Callable[[], float]]" = None) -> None:
        """Initialize the accountant.

        Args:
            capacity_resolver: Called with a provider_id, returns the number
                of simultaneous connections that provider allows. A return of
                ``0`` means unlimited (never exceeded). Any exception raised
                by the resolver is treated as capacity ``1`` — fail safe,
                never fail open to unlimited on a resolver error.
            on_preempt: Called with ``(provider_id, holder_id, kind)`` for each
                holder evicted by a preempting acquire. Injected the same way
                the resolver is, so this module stays free of Qt and of any
                knowledge of what a download or a recording actually IS —
                arbitration lives here, consequences live with the consumer.

                Called OUTSIDE the lock, after the registry is updated, so a
                consumer may call straight back in (to release a sibling, say)
                without deadlocking on a non-reentrant lock.
        """
        self._capacity_resolver = capacity_resolver
        #: Injected so a test can drive the cooldown without sleeping. Never
        #: read the real clock underneath a caller-supplied one — that bug has
        #: been found three times in this codebase in a single day.
        self._clock = clock or time.monotonic
        #: provider_id -> monotonic time until which background work must stay off.
        self._cooldown_until: dict[str, float] = {}
        #: EVERY consumer that can be preempted, not one.
        #:
        #: This was a single ``_on_preempt`` slot, assigned directly by
        #: ``main_window_downloads`` — so ``DownloadManager`` owned the hook
        #: outright and the two OTHER preemptible consumers (the TMDb
        #: enrichment backfill and the series-monitor poll, both registered as
        #: ``kind="monitor"``) were evicted from the registry and never told.
        #: Eviction was bookkeeping only: their in-flight HTTP calls kept the
        #: provider's connection, so mpv was refused and quit a few seconds
        #: after opening. A hand-assigned hook is an enumeration of size one.
        self._preempt_listeners: list[Callable[[str, str, str], None]] = []
        if on_preempt is not None:
            self._preempt_listeners.append(on_preempt)
        self._holders: dict[str, dict[str, str]] = {}  # provider_id -> {holder_id: kind}
        #: provider_id -> {holder_id: clock time at first registration}. Read
        #: by reconcile() to apply RECONCILE_GRACE_S; never touched by an
        #: idempotent re-acquire (only the FIRST registration counts).
        self._acquired_at: dict[str, dict[str, float]] = {}
        #: Callable returning the holder ids still alive right now, injected
        #: via set_liveness_probe(). None (the default) disables the acquire()
        #: self-heal path below entirely.
        self._liveness_probe: "Optional[Callable[[], Iterable[str]]]" = None
        #: (provider_id, holder_id) pairs currently refused and waiting —
        #: drives "say why, once": a refusal logs only the first time a pair
        #: enters this set, and the eventual grant logs once when it leaves.
        #: Cleared on grant or release.
        self._held_back: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def add_preempt_listener(self, callback: "Callable[[str, str, str], None]") -> None:
        """Register *callback* to be told when any holder is evicted.

        The one seam for learning you lost a slot. Every preemptible consumer
        registers here; each is called with ``(provider_id, holder_id, kind)``
        for EVERY eviction, so a listener must check the ids are its own
        (``DownloadManager.on_preempted`` returns early on a foreign ``kind``).

        Idempotent — registering the same bound method twice is a no-op, so a
        re-wire during a reload cannot double-notify.
        """
        with self._lock:
            if callback not in self._preempt_listeners:
                self._preempt_listeners.append(callback)

    def set_liveness_probe(self, probe: "Optional[Callable[[], Iterable[str]]]") -> None:
        """Register the callable :meth:`acquire` may poll when refused for capacity.

        *probe* returns the holder ids that are still alive right now — e.g.
        ``PlayerManager.active_keys``. A holder that is not among them AND is
        older than ``RECONCILE_GRACE_S`` is a dead playback holder still
        occupying the one slot a download/monitor/probe request needs; this
        lets ``acquire()`` sweep it and grant the request in the same call,
        instead of the request sitting refused until someone else calls
        :meth:`reconcile` (the next play/stop). Passing ``None`` (the default,
        set implicitly by never calling this) disables the self-heal path —
        a caller with nothing to probe must never be asked to guess.

        Pure plumbing, same as ``capacity_resolver``/``on_preempt``: this
        class never calls anything but what is injected here.
        """
        with self._lock:
            self._liveness_probe = probe

    # ── Read-only queries ───────────────────────────────────────────────────

    def capacity(self, provider_id: str) -> int:
        """Resolve *provider_id*'s slot count via the injected resolver.

        Returns:
            The capacity, or ``0`` for unlimited. Falls back to ``1`` if the
            resolver raises.
        """
        try:
            return int(self._capacity_resolver(provider_id))
        except Exception:
            # The resolver is caller-supplied, so this really can be anything —
            # but falling back to 1 connection silently would look like a
            # provider limit rather than a broken resolver.
            logger.warning("Capacity resolver failed for {}; assuming 1", provider_id, exc_info=True)
            return 1

    def in_use(self, provider_id: str) -> int:
        """Return the number of holders currently registered for *provider_id*."""
        with self._lock:
            return len(self._holders.get(provider_id, {}))

    def holders(self, provider_id: str) -> list[Holder]:
        """Return the current holders for *provider_id*, in registration order."""
        with self._lock:
            current = self._holders.get(provider_id, {})
            return [Holder(holder_id=hid, kind=kind) for hid, kind in current.items()]

    def preview(self, provider_id: str, holder_id: str) -> AcquireResult:
        """Read-only: report what :meth:`acquire` would return, without mutating state.

        Lets a caller (e.g. a UI layer) decide whether to warn *before*
        committing to a play — show a "connection limit reached" toast instead
        of silently failing an ``acquire()``.
        """
        with self._lock:
            current = self._holders.get(provider_id, {})
            cap = self.capacity(provider_id)
            if holder_id in current or cap <= 0 or len(current) < cap:
                return AcquireResult(True, provider_id, cap, tuple(current.keys()))
            return AcquireResult(False, provider_id, cap, tuple(current.keys()))

    # ── Mutating operations ─────────────────────────────────────────────────

    def acquire(self, provider_id: str, kind: str, holder_id: str,
                *, preempt_kinds: "Sequence[str]" = ()) -> AcquireResult:
        """Register *holder_id* as holding a connection slot for *provider_id*.

        Idempotent: re-acquiring an already-registered holder_id for the same
        provider is always granted and does not double-count — this is the
        normal case of a reused mpv window replaying into the same provider.

        Args:
            provider_id: The provider whose capacity is being consumed.
            kind: Consumer kind — ``"playback"``, ``"download"``,
                ``"recording"``. Registered through this one method whatever
                the consumer is.
            holder_id: Caller-defined identity for the connection (for
                playback, the mpv instance key).
            preempt_kinds: Kinds this caller may evict when capacity is full,
                in priority order of what it is willing to displace. Empty (the
                default) never evicts anything, so an existing caller is
                unchanged.

                **The priority axis is recoverability, not foreground.** A
                download yields because the VOD is still there in an hour; a
                scheduled recording does not, because the moment is gone. So
                playback passes ``("download",)`` and never ``("recording",)``
                — a recording makes the user choose with their eyes open
                instead of dying silently.

        Returns:
            ``AcquireResult(granted=True, ...)`` with the slot applied — with
            ``preempted`` naming anyone evicted — or
            ``AcquireResult(granted=False, ...)`` (capacity full of holders
            this caller may not evict, state unchanged).

        **Self-heal on capacity refusal.** When the slot is full even after
        preemption AND a liveness probe is registered (:meth:`set_liveness_probe`),
        this sweeps dead holders (:meth:`reconcile`) and re-tries exactly once
        before giving up — so a caller need not wait for someone else's
        play()/stop() to notice the same dead holder. A refusal from the
        cooldown branch is never retried this way: a dead holder cannot change
        the provider's own reaper lag. See ``RECONCILE_GRACE_S`` for why this
        can never evict a holder that only just registered.
        """
        result, capacity_refused = self._try_acquire(provider_id, kind, holder_id, preempt_kinds)
        if capacity_refused and self._liveness_probe is not None:
            try:
                alive = self._liveness_probe()
            except Exception:
                logger.exception("liveness probe failed while acquiring {} on {}",
                                  holder_id, provider_id)
                alive = None
            if alive is not None:
                self.reconcile(alive)
                result, _ = self._try_acquire(provider_id, kind, holder_id, preempt_kinds)
        return result

    def _try_acquire(self, provider_id: str, kind: str, holder_id: str,
                      preempt_kinds: "Sequence[str]") -> "tuple[AcquireResult, bool]":
        """One arbitration pass — the body ``acquire()`` used to run inline.

        Returns ``(result, capacity_refused)``. ``capacity_refused`` is True
        ONLY for "full even after preemption" — the one refusal a liveness
        probe sweep can change the answer to.
        """
        evicted: list[tuple[str, str]] = []
        with self._lock:
            current = self._holders.setdefault(provider_id, {})
            cap = self.capacity(provider_id)
            if holder_id in current:
                self._note_granted_locked(provider_id, holder_id, kind)
                return AcquireResult(True, provider_id, cap, tuple(current.keys())), False
            if kind in self.FOREGROUND_KINDS:
                # The user is waiting. Arm the cooldown now, not on release, so
                # a play that FAILS still keeps background work off the source
                # while the user retries — which is the loop they actually hit.
                self._cooldown_until[provider_id] = (
                    self._clock() + self.PROVIDER_COOLDOWN_S)
            elif cap == 1 and self._clock() < self._cooldown_until.get(provider_id, 0.0):
                # Free by our books, still counted by theirs. Backing off here
                # is the whole point: catch-up work has no deadline, and the
                # person staring at a black window does.
                self._note_refused_locked(
                    provider_id, holder_id, logger.debug,
                    "Connection cooldown on {}: {} ({}) held back for {:.0f}s more",
                    provider_id, holder_id, kind,
                    self._cooldown_until[provider_id] - self._clock())
                return AcquireResult(False, provider_id, cap, tuple(current.keys())), False
            if cap > 0 and len(current) >= cap:
                # Evict the LEAST recently registered preemptible holder first,
                # and only as many as are needed — a second download on the same
                # provider should not be cancelled to admit one playback.
                needed = len(current) - cap + 1
                for hid, held_kind in list(current.items()):
                    if needed <= 0:
                        break
                    if held_kind in preempt_kinds:
                        del current[hid]
                        evicted.append((hid, held_kind))
                        needed -= 1
                if needed > 0:
                    # Put back anything already taken: a partial eviction that
                    # still cannot grant would kill a download for nothing.
                    for hid, held_kind in evicted:
                        current[hid] = held_kind
                    self._note_refused_locked(
                        provider_id, holder_id, logger.info,
                        "Connection busy on {}: {} ({}) waiting — slot held by {}",
                        provider_id, holder_id, kind, tuple(current.keys()))
                    return AcquireResult(False, provider_id, cap, tuple(current.keys())), True
            current[holder_id] = kind
            self._acquired_at.setdefault(provider_id, {})[holder_id] = self._clock()
            self._note_granted_locked(provider_id, holder_id, kind)
            result = AcquireResult(
                True, provider_id, cap, tuple(current.keys()),
                preempted=tuple(hid for hid, _ in evicted),
            )

        # Outside the lock, deliberately — see __init__.
        for hid, held_kind in evicted:
            logger.info("Connection preempted on {}: {} ({}) yielded to {} ({})",
                        provider_id, hid, held_kind, holder_id, kind)
            with self._lock:
                listeners = list(self._preempt_listeners)
            for listener in listeners:
                try:
                    listener(provider_id, hid, held_kind)
                except Exception:
                    # One bad listener must not stop the others being told —
                    # a consumer left believing it still holds the slot is
                    # exactly the bug this fan-out exists to prevent.
                    logger.exception("on_preempt listener failed for {}", hid)
        return result, False

    def _note_refused_locked(self, provider_id: str, holder_id: str, log_fn,
                              template: str, *args) -> None:
        """Log *template* the first time (provider_id, holder_id) is refused.

        Must be called with ``self._lock`` already held — mutates
        ``_held_back`` directly instead of re-entering the (non-reentrant)
        lock. Repeated refusals of the same pair (a poller retrying every
        few seconds against a still-busy source) log nothing further.
        """
        key = (provider_id, holder_id)
        if key in self._held_back:
            return
        self._held_back.add(key)
        log_fn(template, *args)

    def _note_granted_locked(self, provider_id: str, holder_id: str, kind: str) -> None:
        """Log the "granted after waiting" line once, iff this pair was held back.

        Must be called with ``self._lock`` already held, same as
        :meth:`_note_refused_locked`.
        """
        key = (provider_id, holder_id)
        if key in self._held_back:
            self._held_back.discard(key)
            logger.info("Connection free on {}: {} ({}) granted after waiting",
                        provider_id, holder_id, kind)

    def note_foreground_use(self, provider_id: str) -> None:
        """Arm *provider_id*'s background cooldown without taking a slot.

        For the window BEFORE playback owns anything — the preflight probe is
        a real connection to the provider and the accountant cannot see it, so
        without this the pollers treat the source as idle for the ~1.5s the
        probe runs and take the one slot out from under it.
        """
        with self._lock:
            self._cooldown_until[provider_id] = (
                self._clock() + self.PROVIDER_COOLDOWN_S)

    def cooldown_remaining(self, provider_id: str) -> float:
        """Seconds background work must still stay off *provider_id* (0 if free)."""
        with self._lock:
            return max(0.0, self._cooldown_until.get(provider_id, 0.0) - self._clock())

    def release(self, provider_id: str, holder_id: str) -> None:
        """Release *holder_id*'s slot for *provider_id*, if held. No-op otherwise."""
        with self._lock:
            current = self._holders.get(provider_id)
            if current is not None:
                current.pop(holder_id, None)
                if not current:
                    self._holders.pop(provider_id, None)
            acquired = self._acquired_at.get(provider_id)
            if acquired is not None:
                acquired.pop(holder_id, None)
                if not acquired:
                    self._acquired_at.pop(provider_id, None)
            self._held_back.discard((provider_id, holder_id))

    def reconcile(self, alive_holder_ids: Iterable[str]) -> list[tuple[str, str]]:
        """Release every registered holder whose id is not in *alive_holder_ids*.

        **Reconcile strategy — on-query, not periodic.** ``PlayerManager``
        calls this at the top of ``play()`` and ``stop()`` with the live mpv
        instance-key set (``active_keys()``), and ``acquire()`` calls it too
        via the registered liveness probe when refused for capacity — so a
        crashed/killed mpv process never leaks its slot forever no matter
        which of those runs first. A periodic QTimer was considered and
        rejected: this object has no Qt event loop of its own (by design, to
        stay pure-Python/unit-testable), and accounting only matters at the
        moment of a new play/stop/acquire decision — a lazy sweep right
        before that decision is sufficient and simpler than wiring a
        background timer through a non-Qt class.

        A holder registered less than ``RECONCILE_GRACE_S`` ago is kept even
        if it is not in *alive_holder_ids* — see that constant's docstring for
        why a newborn holder must never be swept.

        Args:
            alive_holder_ids: The current set of holder ids that are still
                alive (e.g. ``PlayerManager.active_keys()``).

        Returns:
            ``[(provider_id, holder_id), ...]`` released, for logging.
        """
        alive = set(alive_holder_ids)
        released: list[tuple[str, str]] = []
        with self._lock:
            now = self._clock()
            for provider_id in list(self._holders.keys()):
                current = self._holders[provider_id]
                acquired = self._acquired_at.get(provider_id, {})
                for holder_id in list(current.keys()):
                    if holder_id in alive:
                        continue
                    age = now - acquired.get(holder_id, 0.0)
                    if age < self.RECONCILE_GRACE_S:
                        continue
                    current.pop(holder_id, None)
                    acquired.pop(holder_id, None)
                    self._held_back.discard((provider_id, holder_id))
                    released.append((provider_id, holder_id))
                if not current:
                    self._holders.pop(provider_id, None)
                if not acquired and provider_id in self._acquired_at:
                    self._acquired_at.pop(provider_id, None)
        return released
