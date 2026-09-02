"""The UI thread says so when it stops answering.

The owner reported five-to-ten-second hangs while scrolling. The log could not
help: across a 12.5-hour session the whole card/shelf/poster path emitted 13
lines, and during the two-minute window containing a stall it emitted none. The
cause was found by reading code, not logs.

``Database.session_scope`` already warns when a COMMIT blocks the UI thread —
narrow, useful, and it fired zero times here because nothing was committing.
This is the general form: a heartbeat that notices the event loop being starved
whatever the cause.
"""

import time

from PyQt6.QtCore import QTimer

from metatv.gui.main_thread_watchdog import _STALL_MS, MainThreadWatchdog


def test_a_real_stall_is_detected(qapp) -> None:
    """Block the main thread and confirm the watchdog notices."""
    watchdog = MainThreadWatchdog()
    watchdog.start()

    def block_then_quit():
        time.sleep((_STALL_MS + 500) / 1000.0)
        QTimer.singleShot(400, qapp.quit)

    QTimer.singleShot(200, block_then_quit)
    qapp.exec()
    watchdog.stop()

    assert watchdog.stall_count >= 1, "a deliberate main-thread block went unnoticed"
    assert watchdog.max_stall_ms >= _STALL_MS


def test_an_idle_event_loop_reports_nothing(qapp) -> None:
    """The property that makes it safe to leave on.

    A watchdog that cried wolf on ordinary frames would be turned off, and then
    it would not be there for the stall that matters.
    """
    watchdog = MainThreadWatchdog()
    watchdog.start()
    QTimer.singleShot(900, qapp.quit)
    qapp.exec()
    watchdog.stop()

    assert watchdog.stall_count == 0, (
        f"reported {watchdog.stall_count} stall(s) on an idle loop"
    )


def test_it_reports_to_the_log(qapp) -> None:
    """The log line is the entire deliverable — a counter nobody reads is not."""
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lines.append, level="WARNING", format="{message}")
    try:
        watchdog = MainThreadWatchdog()
        watchdog.start()

        def block_then_quit():
            time.sleep((_STALL_MS + 500) / 1000.0)
            QTimer.singleShot(400, qapp.quit)

        QTimer.singleShot(200, block_then_quit)
        qapp.exec()
        watchdog.stop()
    finally:
        logger.remove(sink)

    assert any("UI thread unresponsive" in line for line in lines), (
        f"the stall was counted but never logged: {lines}"
    )


def test_a_long_hang_does_not_flood_the_log(qapp) -> None:
    """One pathological stall must not bury its own first occurrence."""
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lines.append, level="WARNING", format="{message}")
    try:
        watchdog = MainThreadWatchdog()
        watchdog.start()
        for _ in range(3):
            time.sleep((_STALL_MS + 200) / 1000.0)
            qapp.processEvents()
        watchdog.stop()
    finally:
        logger.remove(sink)

    stall_lines = [line for line in lines if "UI thread unresponsive" in line]
    assert len(stall_lines) <= 2, f"three back-to-back stalls logged {len(stall_lines)} lines"


def test_the_watchdog_is_registered_for_cleanup() -> None:
    """It owns a QTimer, so it stops with the window (CLAUDE.md cleanup registry)."""
    import ast
    import inspect

    from metatv.gui import main_window

    tree = ast.parse(inspect.getsource(main_window))
    registered = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "_register_cleanable"
        and node.args and isinstance(node.args[0], ast.Constant)
    }
    assert "main_thread_watchdog" in registered


def test_sampler_captures_the_blocking_stack(qapp) -> None:
    """A stale heartbeat, sampled synchronously, names the calling frame.

    No Qt timer needed — ``_sampler_iteration`` is the unit under test, called
    directly the way the real sampler thread would call it mid-stall.
    """
    watchdog = MainThreadWatchdog()
    watchdog._heartbeat = time.perf_counter() - 1.0

    watchdog._sampler_iteration()

    capture = watchdog._stall_capture
    assert isinstance(capture, str)
    assert "sampled during stall" in capture
    # threading.main_thread() IS the pytest thread here, so the synchronous
    # call above shows up in the captured main-thread stack.
    assert "test_sampler_captures_the_blocking_stack" in capture


def test_fresh_heartbeat_clears_the_capture(qapp) -> None:
    """Once the heartbeat catches up, a stale capture must not linger."""
    watchdog = MainThreadWatchdog()
    watchdog._heartbeat = time.perf_counter() - 1.0
    watchdog._sampler_iteration()
    assert watchdog._stall_capture is not None

    watchdog._heartbeat = time.perf_counter()
    watchdog._sampler_iteration()

    assert watchdog._stall_capture is None


def test_one_capture_per_stall(qapp, monkeypatch) -> None:
    """A single stall gets exactly one capture, however many times we poll."""
    import metatv.gui.main_thread_watchdog as watchdog_module

    calls = {"n": 0}
    real_current_frames = watchdog_module.sys._current_frames

    def counting_current_frames():
        calls["n"] += 1
        return real_current_frames()

    monkeypatch.setattr(watchdog_module.sys, "_current_frames", counting_current_frames)

    watchdog = MainThreadWatchdog()
    watchdog._heartbeat = time.perf_counter() - 1.0

    watchdog._sampler_iteration()
    watchdog._sampler_iteration()

    assert calls["n"] == 1


def test_report_includes_and_clears_capture(qapp) -> None:
    """A queued capture rides along in the stall's log line, then is gone."""
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lines.append, level="WARNING", format="{message}")
    try:
        watchdog = MainThreadWatchdog()
        watchdog._stall_capture = "sampled during stall, heartbeat age 999ms\nthread MainThread:\n  metatv/gui/main_window.py:1 in bogus_marker_frame"
        # Force a stall report without waiting on a real clock: back-date the
        # last tick so _on_tick computes a stall on the very next call.
        watchdog._last_tick = time.perf_counter() - (_STALL_MS + 500) / 1000.0

        watchdog._on_tick()
    finally:
        logger.remove(sink)

    stall_lines = [line for line in lines if "UI thread unresponsive" in line]
    assert stall_lines, f"no stall was reported: {lines}"
    assert any("bogus_marker_frame" in line for line in lines)
    assert watchdog._stall_capture is None
