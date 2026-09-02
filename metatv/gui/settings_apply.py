"""Applying Settings: run each handler once, and reload the list once.

Clicking OK froze the UI for **27 seconds** (measured 2026-09-02: the watchdog
reported 27,050 ms and subtracting it lands exactly on "Settings saved"). Eleven
handlers fire on ``settings_applied``, synchronously, on the main thread — and
two of them independently call ``load_channels()``, so one OK re-ran the whole
785,551-row filter TWICE whether or not anything relevant had changed.

Three things live here, and they are one concern — what OK costs:

1. **One list reload.** Handlers ask via :func:`request_channel_reload`; while a
   settings pass is running the request is recorded and satisfied once, at the
   end. Outside a pass the call is immediate, so the handlers behave identically
   when they run for any other reason.
2. **Per-handler timing**, at DEBUG. The worklog's own rule for this family is
   *instrument, do not infer* — the watchdog can only say "something blocked",
   never which of eleven things. Now one OK produces the attribution.
3. **One handler cannot take out the rest.** They were eleven separate Qt
   connections, so a raise in one left the others to run; as a single slot they
   would not, which would be a regression. Each is isolated and logged.

**The list is still THE list.** It used to be eleven ``connect`` lines with a
comment warning that a hand-written tail had once repeated three of five and
silently dropped the rest. This is the same single enumeration, moved to where
it can be ordered, timed and guarded — ``test_settings_apply`` asserts every
name resolves on ``MainWindow``, which the connect lines only checked by
crashing at startup.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

#: Every ``settings_applied`` handler, IN ORDER. Order is behaviour: the theme
#: is re-applied before the split toggle re-reads it, and the adult-mode change
#: writes into the filter bar before anything reloads from it.
HANDLERS: tuple[str, ...] = (
    "_apply_sidebar_visibility",
    "_refresh_recommendation_views",
    "_apply_channel_list_density",
    "_apply_sidebar_row_density",
    "refresh_theme",
    "_apply_collapse_variants_setting",
    # Settings → Content is the ONLY reachable adult-mode control, so its change
    # has to reach both the filter bar's (hidden) combo and the list.
    "_apply_adult_mode_setting",
    # alerts_show_idle_items changes WHICH rows the section lists, so it has to
    # re-render; the existing alert-visibility chokepoint already does it.
    "_refresh_vod_alerts_section",
    # series_monitor_interval_minutes only takes effect when the timer is
    # re-armed; start_scheduler() re-reads config and is safe to re-call.
    "_restart_series_monitor_scheduler",
    # Applies the menu-bar setting AND re-ticks the Tools entry, so the two
    # surfaces cannot disagree after an OK.
    "_apply_menu_bar_setting",
    "_sync_split_toggle",
)

_ACTIVE = "_settings_apply_active"
_WANTED = "_settings_reload_wanted"

#: A handler slower than this is worth a line in the log on its own.
SLOW_HANDLER_MS = 250


def request_channel_reload(host: Any) -> bool:
    """Ask for the channel list to be reloaded. Returns True if it happened now.

    Inside a settings pass the request is recorded and satisfied once at the
    end; outside one it is immediate. Handlers therefore need no idea which
    context they are in, which is the point — two of them are also reachable
    from ordinary UI actions.
    """
    if host.__dict__.get(_ACTIVE):
        host.__dict__[_WANTED] = True
        return False
    host.load_channels()
    return True


def run(host: Any) -> dict[str, float]:
    """Run every handler in :data:`HANDLERS` once, then reload the list once.

    Args:
        host: The MainWindow.

    Returns:
        ``{handler name: milliseconds}`` — returned rather than only logged so a
        test can assert the whole list actually ran.
    """
    host.__dict__[_ACTIVE] = True
    host.__dict__[_WANTED] = False
    timings: dict[str, float] = {}
    started = time.monotonic()
    try:
        for name in HANDLERS:
            handler = getattr(host, name, None)
            if handler is None:
                # Not fatal: a partially-built host in a test, or a handler
                # renamed without updating the list. Loud, and the rest run.
                logger.warning("settings apply: no handler named {}", name)
                continue
            at = time.monotonic()
            try:
                handler()
            except Exception:
                logger.exception("settings apply: {} failed", name)
            timings[name] = (time.monotonic() - at) * 1000
            if timings[name] >= SLOW_HANDLER_MS:
                logger.debug("settings apply: {} took {:.0f}ms",
                             name, timings[name])
    finally:
        host.__dict__[_ACTIVE] = False

    if host.__dict__.get(_WANTED):
        at = time.monotonic()
        try:
            host.load_channels()
        except Exception:
            logger.exception("settings apply: the coalesced reload failed")
        timings["load_channels"] = (time.monotonic() - at) * 1000
    host.__dict__[_WANTED] = False

    logger.debug("settings apply: {:.0f}ms total — {}",
                 (time.monotonic() - started) * 1000,
                 ", ".join(f"{n} {ms:.0f}ms" for n, ms in
                           sorted(timings.items(), key=lambda kv: -kv[1])[:4]))
    return timings
