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
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, QTimer

#: Quiet period after the LAST collapse before refreshing. Restarted by every
#: :meth:`RefreshCoalescer.on_collapse`, so a burst collapses into one refresh
#: once it goes quiet. A module constant (not a literal in ``__init__``) so a
#: test can shrink it before constructing the coalescer.
QUIET_MS = 60_000

#: Absolute ceiling since the FIRST uncoalesced collapse of a burst. Guarantees
#: a refresh even when collapses never go quiet for the length of a long
#: enrichment run.
MAX_LATENCY_MS = 5 * 60_000


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
        """Enrichment queue drained — flush now if a refresh is pending.

        A settle with nothing pending (browsing that resolved nothing this
        drain) is a deliberate no-op — never a redundant refresh.
        """
        if self._pending:
            self._fire()

    def stop(self) -> None:
        """Cleanup-registry hook: stop both timers without firing a refresh."""
        self._quiet_timer.stop()
        self._max_timer.stop()

    def _fire(self) -> None:
        """Run the ONE coalesced refresh and reset the whole state machine."""
        self._quiet_timer.stop()
        self._max_timer.stop()
        self._pending = False
        self._refresh()
