"""Name what the main thread was doing when it stopped answering.

``MainThreadWatchdog`` can prove a stall happened and nothing more. Its own
message says so — *"whatever ran just before this line blocked the event
loop"* — and that is the whole difficulty with every PERF item in this project:
the watchdog reports AFTER the block has cleared, so every attribution so far
has been read off gaps between unrelated log lines and then argued about.

A phase is a named span of main-thread work. Entering one records its name;
the watchdog reports the name of whatever was open when it fired. That turns
"something blocked for 2,730 ms" into "``filter-panel.update_data`` blocked for
2,730 ms", which is the difference between a hypothesis and a measurement.

**It measures; it does not fix.** Deliberately — the owner asked for the
understanding first and the fix left alone, and the last hypothesis to be
argued instead of measured was wrong: ``set_flat_items`` building one widget
per filter value was the leading suspect for a 1,349 ms stall, and building all
148 of the owner's values costs **35 ms** (0.24 ms per row, measured
2026-09-02). Virtualizing the filter panel would have been a large change
buying 2.6% of that stall.

Nesting is allowed and the INNERMOST open phase is reported, because that is
the most specific true answer. Nothing here touches Qt, so it costs one
``perf_counter`` call and a list append per span.
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from loguru import logger

#: A phase slower than this is logged when it closes, whether or not the
#: watchdog noticed. The watchdog only reports stalls over its own threshold
#: and then goes quiet for a while, so a merely-slow phase would otherwise
#: leave no trace at all.
SLOW_PHASE_MS = 200

#: (name, started_at) for every phase currently open, outermost first.
_open: list[tuple[str, float]] = []


@contextmanager
def phase(name: str) -> Iterator[None]:
    """Mark a span of main-thread work as *name*.

    Args:
        name: A stable identifier — ``"filter-panel.update_data"``, not a
            sentence. It goes in log lines that get grepped.

    Yields:
        None. The phase closes on exit, including on an exception: a phase left
        open by a raise would be blamed for everything that followed it, which
        is worse than no attribution at all.
    """
    started = time.perf_counter()
    _open.append((name, started))
    try:
        yield
    finally:
        if _open and _open[-1][0] == name:
            _open.pop()
        else:                                    # pragma: no cover
            # Interleaved rather than nested — not something the with-statement
            # can produce, but a future decorator or manual push could.
            for i in range(len(_open) - 1, -1, -1):
                if _open[i][0] == name:
                    del _open[i]
                    break
        elapsed = (time.perf_counter() - started) * 1000
        if elapsed >= SLOW_PHASE_MS:
            logger.debug("phase {} took {:.0f}ms", name, elapsed)


def timed(name: str):
    """Decorator form of :func:`phase`, for a whole method.

    The common case — most phases ARE one method, and a decorator says so at
    the definition instead of indenting its whole body.

    Args:
        name: The phase identifier; see :func:`phase`.
    """
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with phase(name):
                return fn(*args, **kwargs)
        return wrapper
    return decorate


def current() -> Optional[str]:
    """The innermost phase currently open, or None.

    The innermost because it is the most specific TRUE answer: an outer
    ``startup`` tells you nothing a timestamp did not.
    """
    return _open[-1][0] if _open else None


def describe() -> str:
    """What the watchdog appends to a stall report.

    Returns the open phase and how long it has been running — the second half
    matters, because a phase that has been open 3 ms when a 2,000 ms stall is
    reported is a bystander, not the cause.
    """
    if not _open:
        return ""
    name, started = _open[-1]
    return f" during {name} (open {(time.perf_counter() - started) * 1000:.0f}ms)"


def reset() -> None:
    """Drop every open phase. For tests, and for a clean slate after a crash."""
    _open.clear()
