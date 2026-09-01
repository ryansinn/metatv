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

    def __init__(self, capacity_resolver: Callable[[str], int],
                 on_preempt: "Optional[Callable[[str, str, str], None]]" = None) -> None:
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
        """
        evicted: list[tuple[str, str]] = []
        with self._lock:
            current = self._holders.setdefault(provider_id, {})
            cap = self.capacity(provider_id)
            if holder_id in current:
                return AcquireResult(True, provider_id, cap, tuple(current.keys()))
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
                    return AcquireResult(False, provider_id, cap, tuple(current.keys()))
            current[holder_id] = kind
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
        return result

    def release(self, provider_id: str, holder_id: str) -> None:
        """Release *holder_id*'s slot for *provider_id*, if held. No-op otherwise."""
        with self._lock:
            current = self._holders.get(provider_id)
            if current is not None:
                current.pop(holder_id, None)
                if not current:
                    self._holders.pop(provider_id, None)

    def reconcile(self, alive_holder_ids: Iterable[str]) -> list[tuple[str, str]]:
        """Release every registered holder whose id is not in *alive_holder_ids*.

        **Reconcile strategy — on-query, not periodic.** ``PlayerManager``
        calls this at the top of ``play()`` and ``stop()`` with the live mpv
        instance-key set (``active_keys()``), so a crashed/killed mpv process
        never leaks its slot forever — nothing else observes process death.
        A periodic QTimer was considered and rejected: this object has no Qt
        event loop of its own (by design, to stay pure-Python/unit-testable),
        and accounting only matters at the moment of a new play/stop decision
        — a lazy sweep right before that decision is sufficient and simpler
        than wiring a background timer through a non-Qt class.

        Args:
            alive_holder_ids: The current set of holder ids that are still
                alive (e.g. ``PlayerManager.active_keys()``).

        Returns:
            ``[(provider_id, holder_id), ...]`` released, for logging.
        """
        alive = set(alive_holder_ids)
        released: list[tuple[str, str]] = []
        with self._lock:
            for provider_id in list(self._holders.keys()):
                current = self._holders[provider_id]
                for holder_id in list(current.keys()):
                    if holder_id not in alive:
                        current.pop(holder_id, None)
                        released.append((provider_id, holder_id))
                if not current:
                    self._holders.pop(provider_id, None)
        return released
