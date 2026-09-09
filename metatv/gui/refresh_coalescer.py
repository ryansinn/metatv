"""Debounce a high-frequency refresh trigger to quiet, cap, or drain.

Extracted rather than inlined in ``main_window.py`` because that file sits at
its exact ``code_health_baseline.json`` ceiling — this module is the shape the
ceiling forces, with only the import + wiring left inline there (see the
``tmdb_enrichment_manager`` construction block).

The case that brought this in (REC-LAG, owner log 2026-09-03 04:39-04:43):
``main_window.py`` wired ``TmdbEnrichmentManager.collapses_found`` DIRECTLY to
``MainWindow._refresh_provider_dependent_views`` — the full canonical refresh
cascade (Recommended weights + scoring, preferences view, Discover, filter
stats, channel list). During an active enrichment run the manager lands a
40-title batch roughly every 5 seconds, so the app ran its heaviest cascade in
a five-second loop for the whole run: 107 stalls in four minutes, worst
8,738ms. :class:`RefreshCoalescer` sits ONLY at that one connection —
``_refresh_provider_dependent_views`` itself, and every user-action refresh
site (hide/rating/manual refresh), are untouched and stay synchronous.

The case that brought in the floor (owner log 2026-09-09 17:31-17:32, "the
discover just keeps reloading and refreshing"): :meth:`RefreshCoalescer.on_settled`
fired the refresh OUTRIGHT, bypassing both timers — and ``enrichment_settled`` is
emitted at the end of EVERY drain, in the same ``finally`` block that emits the
``collapses_found`` which had just armed the quiet window. So the quiet window
never survived the statement that armed it: on_collapse set ``_pending`` and
started the 60s timer, and on_settled fired microseconds later. Measured cadence
in that log is 42s between full cascades — arithmetically impossible for a 60s
quiet timer, which is how the bypass was identified rather than guessed.
``settled`` does not mean "the user stopped browsing"; it means "this drain's
queue emptied", which during ordinary browsing happens continuously. The fast
path shadowed its own coalescer.
"""

from __future__ import annotations

from typing import Callable

from time import monotonic

from PyQt6.QtCore import QObject, QTimer


def _monotonic_ms() -> float:
    """Monotonic clock in ms — injectable on the instance so tests can drive it."""
    return monotonic() * 1000.0

#: Quiet period after the LAST collapse before refreshing. Restarted by every
#: :meth:`RefreshCoalescer.on_collapse`, so a burst collapses into one refresh
#: once it goes quiet. A module constant (not a literal in ``__init__``) so a
#: test can shrink it before constructing the coalescer.
QUIET_MS = 60_000

#: Absolute ceiling since the FIRST uncoalesced collapse of a burst. Guarantees
#: a refresh even when collapses never go quiet for the length of a long
#: enrichment run.
MAX_LATENCY_MS = 5 * 60_000

#: Minimum gap between two coalesced refreshes, for the :meth:`on_settled`
#: path only. A settle arriving at least this long after the last refresh
#: flushes immediately — the prompt end-of-burst behaviour on_settled exists
#: for. One arriving sooner waits out the remainder instead of firing, so a
#: run of back-to-back drains cannot out-pace the quiet policy the module
#: already states. Equal to :data:`QUIET_MS` deliberately: a settle-driven
#: refresh should be no more frequent than a quiet-driven one, never more.
MIN_INTERVAL_MS = QUIET_MS


class RefreshCoalescer(QObject):
    """Coalesce repeated ``on_collapse`` calls into ONE ``refresh()`` call.

    Two independent single-shot timers track one pending refresh: ``_quiet_timer``
    restarts on every :meth:`on_collapse` and fires ``QUIET_MS`` after the last
    one; ``_max_timer`` is armed once, on the first collapse of a burst, and
    fires ``MAX_LATENCY_MS`` after THAT one regardless of how many more arrive.
    Either firing — or :meth:`on_settled` — runs the refresh and resets the
    whole state machine, so the next collapse starts a fresh cycle.
    """

    def __init__(self, host: QObject, refresh: Callable[[], None]) -> None:
        """
        Args:
            host: Qt parent (also the cleanup-registry owner — see below).
            refresh: The zero-arg callable to coalesce calls to (in practice
                ``MainWindow._refresh_provider_dependent_views``).
        """
        super().__init__(host)
        self._refresh = refresh
        self._pending = False

        self._quiet_timer = QTimer(self)
        self._quiet_timer.setSingleShot(True)
        self._quiet_timer.timeout.connect(self._fire)

        self._max_timer = QTimer(self)
        self._max_timer.setSingleShot(True)
        self._max_timer.timeout.connect(self._fire)

        # Holds a settle that arrived inside the floor, so it lands the moment
        # the floor expires rather than being dropped or firing early.
        self._floor_timer = QTimer(self)
        self._floor_timer.setSingleShot(True)
        self._floor_timer.timeout.connect(self._fire)

        # Monotonic ms of the last refresh this coalescer ran; None until the
        # first, so the first settle of a session is never held back.
        self._last_fire_ms: float | None = None
        self._now_ms = _monotonic_ms

        # Same self-registering shape as deferred_config_save.save_soon: the
        # module that owns the timer registers its own cleanup, so a wiring
        # site can never forget it (CLAUDE.md: closeEvent cleanup registry).
        host._register_cleanable("enrichment_refresh_coalescer", self.stop)

    def on_collapse(self, _count: int = 0) -> None:
        """A collapse batch landed — restart the quiet window; arm the cap once.

        ``_count`` matches ``collapses_found``'s ``int`` signature but is
        unused, same as the direct-connect this replaces.
        """
        if not self._pending:
            self._pending = True
            self._max_timer.start(MAX_LATENCY_MS)
        self._quiet_timer.start(QUIET_MS)

    def on_settled(self) -> None:
        """A drain finished — flush if a refresh is pending AND the floor allows.

        ``enrichment_settled`` fires at the end of every drain, not once at the
        end of a browsing session, so an unconditional flush here made both
        timers dead code and ran the heaviest cascade in the app every ~40s
        (module docstring). A settle at least :data:`MIN_INTERVAL_MS` after the
        last refresh still flushes immediately — that is the prompt end-of-burst
        behaviour this method exists for. One arriving sooner is HELD, not
        dropped: ``_floor_timer`` lands it exactly when the floor expires, so
        the refresh is delayed, never lost.

        A settle with nothing pending (browsing that resolved nothing this
        drain) is a deliberate no-op — never a redundant refresh.
        """
        if not self._pending:
            return
        remaining = self._floor_remaining_ms()
        if remaining <= 0:
            self._fire()
        elif not self._floor_timer.isActive():
            self._floor_timer.start(int(remaining))

    def _floor_remaining_ms(self) -> float:
        """Milliseconds left before a settle-driven refresh is allowed again."""
        if self._last_fire_ms is None:
            return 0.0
        return MIN_INTERVAL_MS - (self._now_ms() - self._last_fire_ms)

    def stop(self) -> None:
        """Cleanup-registry hook: stop every timer without firing a refresh."""
        self._quiet_timer.stop()
        self._max_timer.stop()
        self._floor_timer.stop()

    def _fire(self) -> None:
        """Run the ONE coalesced refresh and reset the whole state machine."""
        self._quiet_timer.stop()
        self._max_timer.stop()
        self._floor_timer.stop()
        self._pending = False
        self._last_fire_ms = self._now_ms()
        self._refresh()
