"""The watchlist pass must not land on the play the user opened the app to make.

Owner, 2026-09-01: *"why does check monitored series every 60 minutes cause there to
NEVER be a connection? maybe it should check monitored series every 24 hours, no?
60 minutes seems excessive anyway."*

It was never really "every 60 minutes". Two separate things were wrong:

* ``main_window`` fired a FULL pass at ``QTimer.singleShot(0, ...)`` — at launch,
  which is exactly when someone opens the app and presses play. Both failure logs
  show the collision: pass running 03:14:31 / play pressed 03:15:09, and pass at
  03:58:06-09 / play at 03:58:12. On a one-connection account those are the same slot.
* That call runs even when the interval is ``0``, because the interval only governs
  the RECURRING timer. Turning the setting off did not stop it, which is why it kept
  happening after the owner had already disabled it.

A pass is one ``get_series_info`` per monitored series per mirror. With 11 series x 3
mirrors at ~1-11s a call that is a ~3 minute pass. New episodes appear at most daily,
so hourly bought nothing and spent the connection twelve times more often than needed.
"""
from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_polling_is_never_a_sub_daily_cadence():
    """0 (off) or at least a day. Never hourly again.

    The default itself moved to ``0`` — see
    ``tests/test_background_polling_is_off.py``, which owns that number and the
    measurement behind it (a pass is 234 provider requests; the full source
    refresh that answers the same question is 1).

    What survives here is the CADENCE floor, which is what the owner's original
    complaint was about and what a future change could still get wrong: if
    polling is switched back on by default, it may not be hourly. This used to
    assert ``== 1440`` and so turned the deliberate move to ``0`` into a red
    gate — exactly the pin-an-exact-value trap.
    """
    from metatv.core.config import Config

    default = Config.model_fields["series_monitor_interval_minutes"].default
    assert default == 0 or default >= 1440, (
        f"default is {default} minutes — a sub-daily watchlist pass competes "
        "with playback on a one-connection account, and new episodes appear at "
        "most daily, so it buys no detection for the connection it spends")


def test_the_startup_pass_is_not_fired_at_zero_milliseconds():
    """It must be delayed, or it lands on the user's first play.

    An AST check rather than a grep: what matters is the delay ARGUMENT to the
    singleShot that schedules ``series_monitor.check_all``, whatever expression
    spells it.
    """
    src = _ROOT / "metatv/gui/main_window.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "singleShot"
                and len(node.args) == 2):
            continue
        target = node.args[1]
        # ...singleShot(delay, self.series_monitor.check_all)
        if (isinstance(target, ast.Attribute) and target.attr == "check_all"
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == "series_monitor"):
            found.append(node.args[0])

    assert found, "nothing schedules series_monitor.check_all any more"
    for delay in found:
        assert not (isinstance(delay, ast.Constant) and delay.value == 0), (
            "the watchlist pass still fires at 0ms — that is the launch moment, "
            "which is when the user presses play")


def test_the_startup_delay_is_long_enough_to_clear_the_launch_burst():
    from metatv.gui.main_window import _WATCHLIST_STARTUP_DELAY_MS

    assert _WATCHLIST_STARTUP_DELAY_MS >= 60_000, (
        "a delay under a minute still overlaps source tests, filter restore and "
        "the migration pass — the busiest part of launch")
