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

That tells us a stall happened, not what caused it — the main-thread tick only
runs again once the stall is already over, so it can only report on the wreck,
never see the crash. A background **sampler thread** closes that gap: it wakes
every 100 ms, watches the same heartbeat, and — while the stall is still in
progress — snapshots every thread's Python stack via ``sys._current_frames()``.
The next tick then has an actual stack trace to log, not a guess. Running the
sampler on its own thread also catches a stall the tick-based check alone
cannot tell apart from a real block: a CPU-bound pure-Python worker starves the
GIL and delays the timer callback exactly like main-thread work would. Because
the interpreter still yields the GIL to other threads at its normal switch
interval (~5 ms), the sampler thread gets scheduled mid-stall regardless of
which thread is actually hogging the CPU, and the capture names it.

It reports rather than prevents. A watchdog that killed work would turn a slow
frame into a broken feature; the value is a log line naming a stall the moment
it happens, so the next report arrives with evidence instead of a description.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback

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

#: How often the sampler thread wakes to check the heartbeat. This IS its
#: sleep — it waits on an Event with this timeout, never ``time.sleep``, so
#: :meth:`MainThreadWatchdog.stop` can wake it immediately.
_SAMPLER_POLL_S = 0.1

#: How many trailing frames to keep for a non-main thread's stack. The main
#: thread's stack is kept in full; a background thread only matters when our
#: own code shows up in it, and the last few frames are enough to see that.
_OTHER_THREAD_FRAMES = 6


def _repo_relative(filename: str) -> str:
    """Trim a stack-frame path down to the ``metatv/...`` tail when present."""
    idx = filename.find("metatv")
    return filename[idx:] if idx != -1 else filename


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
        # Written from the main thread (start/_on_tick) and read from the
        # sampler thread; float assignment is atomic under the GIL, so no
        # lock is needed for this diagnostics-only value.
        self._heartbeat: float = time.perf_counter()
        # Written from the sampler thread, read+cleared from the main thread
        # in _on_tick; str/None assignment is likewise atomic under the GIL.
        self._stall_capture: "str | None" = None
        self._sampler_stop = threading.Event()
        self._sampler_thread: "threading.Thread | None" = None
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    def start(self) -> None:
        """Begin watching. Safe to call twice."""
        self._last_tick = time.perf_counter()
        self._heartbeat = self._last_tick
        self._timer.start()
        if self._sampler_thread is None or not self._sampler_thread.is_alive():
            self._sampler_stop.clear()
            self._sampler_thread = threading.Thread(
                target=self._sampler_loop, name="watchdog-sampler", daemon=True,
            )
            self._sampler_thread.start()

    def stop(self) -> None:
        """Stop watching, and summarise if anything was seen.

        Safe to call without a prior :meth:`start`.
        """
        self._timer.stop()
        self._sampler_stop.set()
        if self._sampler_thread is not None:
            self._sampler_thread.join(timeout=1.0)
            self._sampler_thread = None
        if self.stall_count:
            logger.info(
                "Main-thread watchdog: {} stall(s) this session, worst {:.0f}ms",
                self.stall_count, self.max_stall_ms,
            )

    def _sampler_loop(self) -> None:
        """Poll the heartbeat and capture stacks while a stall is in progress."""
        while not self._sampler_stop.wait(_SAMPLER_POLL_S):
            self._sampler_iteration()

    def _sampler_iteration(self) -> None:
        """One poll: reset on a fresh heartbeat, capture once per stall.

        Factored out of :meth:`_sampler_loop` so a test can drive it
        synchronously instead of racing a real background thread.
        """
        age = time.perf_counter() - self._heartbeat
        if age < _TICK_MS / 1000.0:
            self._stall_capture = None
            return
        if age >= _STALL_MS / 1000.0 and self._stall_capture is None:
            self._stall_capture = self._capture_stacks(age)

    def _capture_stacks(self, age: float) -> str:
        """Snapshot every thread's Python stack, main thread in full.

        A non-main thread is included only when our own code appears
        somewhere in it — that is the GIL-hog signature — and then only its
        last :data:`_OTHER_THREAD_FRAMES` frames.
        """
        frames = sys._current_frames()
        main_ident = threading.main_thread().ident
        sampler_ident = self._sampler_thread.ident if self._sampler_thread else None
        names = {t.ident: t.name for t in threading.enumerate()}

        lines = [f"sampled during stall, heartbeat age {age * 1000:.0f}ms"]

        main_frame = frames.get(main_ident)
        if main_frame is not None:
            lines.append(f"thread {names.get(main_ident, 'MainThread')}:")
            for entry in traceback.extract_stack(main_frame):
                lines.append(
                    f"  {_repo_relative(entry.filename)}:{entry.lineno} "
                    f"in {entry.name}"
                )

        for ident, frame in frames.items():
            if ident == main_ident or ident == sampler_ident:
                continue
            stack = traceback.extract_stack(frame)
            if not any("metatv" in entry.filename for entry in stack):
                continue
            lines.append(f"thread {names.get(ident, f'thread-{ident}')}:")
            for entry in stack[-_OTHER_THREAD_FRAMES:]:
                lines.append(
                    f"  {_repo_relative(entry.filename)}:{entry.lineno} "
                    f"in {entry.name}"
                )

        return "\n".join(lines)

    def _on_tick(self) -> None:
        """Compare the wake-up we got against the one we asked for."""
        self._heartbeat = time.perf_counter()
        now = self._heartbeat
        late_ms = (now - self._last_tick) * 1000.0 - _TICK_MS
        self._last_tick = now

        if late_ms < _STALL_MS:
            return

        self.stall_count += 1
        self.max_stall_ms = max(self.max_stall_ms, late_ms)

        # Take the capture (if any) whether or not this report is about to be
        # rate-limited away — a suppressed report must not leave a stale
        # capture sitting around to attach itself to a later, unrelated stall.
        capture, self._stall_capture = self._stall_capture, None

        if (now - self._last_report) * 1000.0 < _QUIET_MS:
            return
        self._last_report = now

        if capture:
            detail = _phase.describe() or (
                " — no phase open; the sampled stacks below name what ran"
            )
        else:
            detail = _phase.describe() or (
                " — no phase open, and no stack sample was captured for "
                "this stall"
            )
        suffix = f"\n{capture}" if capture else ""
        logger.warning(
            "UI thread unresponsive for {:.0f}ms{} (worst so far {:.0f}ms across "
            "{} stalls){}",
            late_ms, detail, self.max_stall_ms, self.stall_count, suffix,
        )
