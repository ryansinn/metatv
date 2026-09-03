"""Write the config once a burst of changes settles, not once per change.

``Config.save()` serialises 299 keys to YAML and copies the whole file to
``.bak`` first — 14 ms on an idle machine, 55-93 ms in the owner's running app,
against a 129 KB file. That is fine for a single deliberate action and ruinous
for anything that fires repeatedly.

The case that brought this in: ``_on_search_text_changed`` is explicitly
debounced — *"debounce to avoid per-keystroke DB queries"* — but it called
``_save_search_state()`` BEFORE starting that timer, so the DB query was
protected and the disk write was not. Measured on the owner's log 2026-09-02:
six full writes in thirteen seconds, from nothing but typing in the search box.
The debounce guarded the cheaper of the two things.

**The value still updates immediately.** Only the WRITE is deferred, so
anything reading ``config`` in memory sees the change at once and only the disk
lags — which is the whole point, since the disk is the only expensive part.

A pending write is flushed on shutdown through the cleanup registry, so
deferring costs nothing on the path that matters: closing the app persists the
same state it would have persisted before.

**Adoption beyond MainWindow.** Child views and sidebar sections have no
``_register_cleanable`` — that registry lives on MainWindow — so for them the
``try/except`` below is routine, not exceptional. They are still safe: on
close, MainWindow's own shutdown path runs a final ``config.save()``, and
``Config.save()`` writes whatever is in memory at that moment — the very
value ``save_soon`` already applied synchronously — so a pending write left
un-flushed by a child host is simply picked up by the app-wide final save.
The cleanup-registry flush is an optimisation (writes sooner, for hosts that
have it), never the correctness backstop.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from PyQt6.QtCore import QTimer

#: How long a burst has to be quiet before the write happens.
#:
#: Longer than the 200 ms search debounce on purpose — the point is to write
#: once for a typed word, not once per settled keystroke — and short enough that
#: a user who types and immediately kills the process loses at most this much.
#: Every ordinary exit flushes.
DEFAULT_DELAY_MS = 1500

_TIMER_ATTR = "_deferred_config_timer"
_PENDING_ATTR = "_deferred_config_pending"


def save_soon(host: Any, *, delay_ms: int = DEFAULT_DELAY_MS) -> None:
    """Ask for ``host.config`` to be written once the burst settles.

    Calling this N times in quick succession produces ONE write.

    Args:
        host: The GUI object owning the config — MainWindow, a dialog, a
            content view, or a sidebar section — as ``config`` or ``_config``.
        delay_ms: Quiet period before writing.
    """
    timer = host.__dict__.get(_TIMER_ATTR)
    if timer is None:
        # Unparented deliberately. ``QTimer(host)`` needs a real QObject, and
        # half the hosts that reach here are duck-typed doubles — one went red
        # with "argument 1 has unexpected type". The host's own __dict__ holds
        # the only reference, so it still dies with the host.
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: _write(host))
        host.__dict__[_TIMER_ATTR] = timer
        # Flush on shutdown, so a deferred write is never a lost one. Registered
        # with the timer's creation rather than on every call — the registry
        # takes one entry per name and re-registering would be silent churn.
        try:
            host._register_cleanable("deferred_config_save", lambda: flush(host))
        except Exception:                                # pragma: no cover
            # Routine for a child view/section — see the module docstring:
            # MainWindow's final config.save() on close covers them.
            logger.debug(f"{type(host).__name__} has no cleanup registry; "
                         "relying on MainWindow's final save to flush")
    host.__dict__[_PENDING_ATTR] = True
    timer.setInterval(delay_ms)
    timer.start()          # restarting is what collapses the burst into one


def flush(host: Any) -> bool:
    """Write now if a save is pending. Returns whether it wrote.

    Called on shutdown, and safe to call at any time — with nothing pending it
    does nothing rather than forcing a redundant 129 KB write.
    """
    if not host.__dict__.get(_PENDING_ATTR):
        return False
    timer = host.__dict__.get(_TIMER_ATTR)
    if timer is not None:
        timer.stop()
    return _write(host)


def _write(host: Any) -> bool:
    """The one place the deferred write actually happens."""
    host.__dict__[_PENDING_ATTR] = False
    try:
        # Most hosts (MainWindow-family) expose ``config``; dialogs, mixins
        # and views more often keep it private as ``_config``. Try both
        # rather than forcing every adopter to expose a public alias.
        config = getattr(host, "config", None)
        if config is None:
            config = host._config
        config.save()
        return True
    except Exception:                                    # pragma: no cover
        logger.exception("deferred config save failed")
        return False
