"""Notice when the UI thread stops answering, and say what it was doing.

Why this exists
---------------
The owner reported the app hanging for five to ten seconds while scrolling a
Discover shelf into unloaded posters. The log could not help: across a
12.5-hour session the entire card/shelf/poster path emitted **13 lines**, and
during the two-minute window containing the stall it emitted none at all. The
cause turned out to be an O(N²) signal fan-out, found by reading the code.

That is the gap this closes. ``Database.session_scope`` already warns when a
COMMIT blocks the UI thread — a narrow, valuable check that fired zero times
here, because nothing was committing. This is the general form: a heartbeat on
the event loop that notices when the main thread stopped servicing it at all,
whatever the reason.

How it works
------------
A ``QTimer`` asks to be woken every :data:`_TICK_MS`. Qt can only deliver that
on the main thread, so if the wake-up is late, the main thread was busy for the
difference. No sampling, no profiler, no measurable cost when things are fine.

It reports rather than prevents. A watchdog that killed work would turn a slow
frame into a broken feature; the value is a log line naming a stall the moment
it happens, so the next report arrives with evidence instead of a description.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, QTimer
from loguru import logger

from metatv.gui import ui_phase as _phase

#: How often to ask for a wake-up. Short enough to catch a stall a person
#: notices, long enough to be free.
_TICK_MS = 250

#: Report a stall at or above this. Below ~400 ms a person reads the app as
#: responsive, and a lower bar would fill the log with ordinary frames.
_STALL_MS = 400.0

#: Never log more than one stall per this window. A pathological hang would
#: otherwise produce a line per tick and bury its own first occurrence.
_QUIET_MS = 2_000.0


class MainThreadWatchdog(QObject):
    """Logs a warning whenever the Qt event loop is starved.

    Attributes:
        max_stall_ms: Longest stall seen, for a session summary.
        stall_count: How many stalls were reported.
    """

    def __init__(self, parent: "QObject | None" = None) -> None:
        """
        Args:
            parent: Qt parent; the watchdog stops when it is destroyed.
        """
        super().__init__(parent)
        self.max_stall_ms: float = 0.0
        self.stall_count: int = 0
        self._last_tick = time.perf_counter()
        self._last_report = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    def start(self) -> None:
        """Begin watching. Safe to call twice."""
        self._last_tick = time.perf_counter()
        self._timer.start()

    def stop(self) -> None:
        """Stop watching, and summarise if anything was seen."""
        self._timer.stop()
        if self.stall_count:
            logger.info(
                "Main-thread watchdog: {} stall(s) this session, worst {:.0f}ms",
                self.stall_count, self.max_stall_ms,
            )

    def _on_tick(self) -> None:
        """Compare the wake-up we got against the one we asked for."""
        now = time.perf_counter()
        late_ms = (now - self._last_tick) * 1000.0 - _TICK_MS
        self._last_tick = now

        if late_ms < _STALL_MS:
            return

        self.stall_count += 1
        self.max_stall_ms = max(self.max_stall_ms, late_ms)

        if (now - self._last_report) * 1000.0 < _QUIET_MS:
            return
        self._last_report = now
        logger.warning(
            "UI thread unresponsive for {:.0f}ms{} (worst so far {:.0f}ms across "
            "{} stalls)",
            late_ms, _phase.describe() or " — no phase open, so whatever ran "
            "just before this line blocked the event loop",
            self.max_stall_ms, self.stall_count,
        )
