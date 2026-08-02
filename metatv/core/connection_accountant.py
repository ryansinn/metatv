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
from typing import Callable, Iterable


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


class ConnectionAccountant:
    """Thread-safe per-provider connection arbiter.

    Pure Python — no Qt, no DB. Safe to call from any thread; a single
    ``threading.Lock`` guards the holder registry (acquire/release/reconcile
    never call each other re-entrantly, so a plain non-reentrant lock is
    sufficient — see the docstring on each method for what it does and does
    not touch while holding the lock).
    """

    def __init__(self, capacity_resolver: Callable[[str], int]) -> None:
        """Initialize the accountant.

        Args:
            capacity_resolver: Called with a provider_id, returns the number
                of simultaneous connections that provider allows. A return of
                ``0`` means unlimited (never exceeded). Any exception raised
                by the resolver is treated as capacity ``1`` — fail safe,
                never fail open to unlimited on a resolver error.
        """
        self._capacity_resolver = capacity_resolver
        self._holders: dict[str, dict[str, str]] = {}  # provider_id -> {holder_id: kind}
        self._lock = threading.Lock()

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

    def acquire(self, provider_id: str, kind: str, holder_id: str) -> AcquireResult:
        """Register *holder_id* as holding a connection slot for *provider_id*.

        Idempotent: re-acquiring an already-registered holder_id for the same
        provider is always granted and does not double-count — this is the
        normal case of a reused mpv window replaying into the same provider.

        Args:
            provider_id: The provider whose capacity is being consumed.
            kind: Consumer kind — ``"playback"`` this slice; future consumers
                (downloads, recordings) register their own kind through this
                same method.
            holder_id: Caller-defined identity for the connection (for
                playback, the mpv instance key).

        Returns:
            ``AcquireResult(granted=True, ...)`` with the slot applied, or
            ``AcquireResult(granted=False, ...)`` (capacity already full —
            state unchanged) listing the current holders.
        """
        with self._lock:
            current = self._holders.setdefault(provider_id, {})
            if holder_id in current:
                return AcquireResult(True, provider_id, self.capacity(provider_id), tuple(current.keys()))
            cap = self.capacity(provider_id)
            if cap > 0 and len(current) >= cap:
                return AcquireResult(False, provider_id, cap, tuple(current.keys()))
            current[holder_id] = kind
            return AcquireResult(True, provider_id, cap, tuple(current.keys()))

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
