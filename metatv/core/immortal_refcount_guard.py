"""Keep ``None``/``True``/``False`` immortal while PyQt6 counts references on them.

Why this exists
---------------
On 2026-09-29 the app aborted after days of uptime with every thread raising
``TypeError: __init__() should return None, not 'NoneType'`` — the downloads
and recordings schedulers, the Downloads refresh, and loguru reporting those
errors. The core dump showed ``None``'s refcount word at ``ob_refcnt=6928,
ob_overflow=1``: it had stopped being immortal.

Python 3.14 starts an immortal object's refcount at ``3 << 30`` and treats it
as immortal while the low 32 bits read negative as ``int32``, leaving a margin
of ``2**30`` either way (cpython#158401). PyQt6's ``*.abi3.so`` modules are
built against pre-3.12 limited-API headers, where ``Py_INCREF`` is an inline
``ob_refcnt++`` — so every PyQt6 call that returns ``None`` adds one that the
interpreter never takes back (1,000,000 ``setObjectName()`` calls → exactly
+1,000,000). After ~1.07 billion such calls the low word wraps, ``None`` turns
mortal, and the interpreter's own "is this None?" checks start failing.

What it does
------------
:meth:`ImmortalRefcountGuard.check` reads each object's low refcount word and,
once it has drifted a quarter of the margin from where it started, writes the
starting value back and logs the drift rate. It must run on a thread holding
the GIL (the main-thread QTimer that calls it does): every inline increment in
an extension happens under the GIL too, so the store cannot interleave with one.

The real fix is upstream (PyQt6 calling ``Py_IncRef`` instead of incrementing
inline); this guard only makes the leak harmless until then.
"""

from __future__ import annotations

import ctypes
import sys
import sysconfig
import time
from typing import Callable

from loguru import logger

#: Python 3.14's starting refcount for an immortal object (low 32 bits).
IMMORTAL_INITIAL = 3 << 30

#: Reset once the low word has moved this far from where it started — a
#: quarter of the ``2**30`` margin, so the guard acts long before the wrap.
DRIFT_LIMIT = 1 << 28

#: How often the owner should call :meth:`ImmortalRefcountGuard.check`. The
#: fastest drift ever measured here would need hours to use up DRIFT_LIMIT.
CHECK_INTERVAL_MS = 60_000

_GUARDED: tuple[tuple[str, object], ...] = (
    ("None", None),
    ("True", True),
    ("False", False),
)


def _is_immortal(low: int) -> bool:
    """True when a low refcount word reads negative as int32 (3.14's test)."""
    return low >= 1 << 31


def _layout_supported() -> bool:
    """The guard's assumptions: 3.14+, 64-bit, little-endian, GIL build."""
    return (
        sys.version_info >= (3, 14)
        and sys.maxsize > 2**32
        and sys.byteorder == "little"
        and not sysconfig.get_config_var("Py_GIL_DISABLED")
    )


class ImmortalRefcountGuard:
    """Resets the refcount of ``None``/``True``/``False`` before it can wrap.

    Attributes:
        resets: How many resets were made this session, per object name.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """
        Args:
            clock: Seconds source for the drift-rate log line.
        """
        self._clock = clock
        self.resets: dict[str, int] = {}
        self._since: dict[str, float] = {}
        self._words: dict[str, ctypes.c_uint32] = {}
        if not _layout_supported():
            logger.debug("Immortal refcount guard: not needed on this interpreter")
            return
        now = clock()
        for name, obj in _GUARDED:
            word = ctypes.c_uint32.from_address(id(obj))
            if not _is_immortal(word.value):
                # Either the layout is not what we think, or the object is
                # already mortal — writing to it would be a guess either way.
                logger.warning(
                    "Immortal refcount guard: {} reads {:#x}, not immortal — not guarding it",
                    name, word.value,
                )
                continue
            self._words[name] = word
            self._since[name] = now

    @property
    def active(self) -> bool:
        """True when at least one object is being guarded."""
        return bool(self._words)

    def check(self) -> None:
        """Reset any guarded refcount that has drifted past :data:`DRIFT_LIMIT`.

        Call on a thread holding the GIL; cheap enough for a 60-second timer.
        """
        for name, word in self._words.items():
            low = word.value
            drift = low - IMMORTAL_INITIAL
            if abs(drift) < DRIFT_LIMIT:
                continue
            now = self._clock()
            hours = max(now - self._since[name], 1e-9) / 3600.0
            word.value = IMMORTAL_INITIAL
            self._since[name] = now
            self.resets[name] = self.resets.get(name, 0) + 1
            logger.info(
                "Immortal refcount guard: reset {} after a drift of {:+,} "
                "({:+,.0f}/hour; the wrap is at ±{:,})",
                name, drift, drift / hours, 1 << 30,
            )
