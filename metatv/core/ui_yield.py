"""Let the UI thread run during long background Python loops.

PyQt widget code releases and re-acquires the GIL around every C++ call; a
CPU-bound background thread holding the GIL makes each re-acquire wait a full
switch interval, so the UI collapses far worse than a fair share (measured
~125x on widget building — see the "PyQt GIL convoy" note). A background loop
over tens of thousands of rows calls :func:`yield_to_ui` per item: every
*every* items it sleeps a millisecond, handing the GIL to the UI thread. On
the main thread it does nothing.
"""
from __future__ import annotations

import threading
import time


def yield_to_ui(index: int, every: int = 1000) -> None:
    """Briefly give up the GIL every *every* iterations, off the main thread only."""
    if index and index % every == 0 and threading.current_thread() is not threading.main_thread():
        time.sleep(0.001)
