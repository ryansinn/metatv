"""Everything one 60-second tick finds arrives as ONE banner, not one each.

The owner's idle log, 2026-09-02: auto-dismiss timers firing at 00:50, 00:52,
01:13, 01:15 — **seven in the same second** — 01:20, 01:22, 01:30. Nothing was
broken. ``EpgManager`` arms a 60-second timer, asks for programmes starting
within ``epg_notification_minutes_before`` (15 by default), and emitted one
banner per match. Programmes cluster on the half hour, so all seven entered the
lead window on the same tick.

Owner: *"a burst rather than multiple notifications if they're all happening at
or around the same time."*

The tick is the unit, and that is not an approximation: after the first sweep,
each tick only picks up programmes NEWLY inside the window, so one ``pending``
list holds things starting within about the same minute. Alerts genuinely
minutes apart — the 01:20 and 01:22 in that log — still arrive separately, which
is what makes this a fix for a burst rather than a cap on the feature.
"""

from __future__ import annotations

import ast
import pathlib

# From the module that DEFINES them (CLAUDE.md): they live in watchlist_burst,
# and epg_manager merely imports the composer.
from metatv.core.watchlist_burst import (
    BURST_DISMISS_MS, BURST_NAMED_LIMIT, SINGLE_DISMISS_MS, burst_banner,
)


def _prog(title, channel="BBC One", when="in 15 min"):
    return (title, channel, when)


def test_one_programme_keeps_the_banner_it_always_had() -> None:
    """No summary is clearer than the thing itself."""
    title, message, dismiss = burst_banner([_prog("Match of the Day")])

    assert title == "Starting in 15 min: Match of the Day"
    assert message == "On BBC One"
    assert dismiss == SINGLE_DISMISS_MS


def test_seven_at_once_becomes_one_banner() -> None:
    """The owner's 01:15 case, verbatim."""
    pending = [_prog(f"Show {i}") for i in range(1, 8)]
    title, message, dismiss = burst_banner(pending)

    assert title == "7 shows starting in 15 min"
    assert message == "Show 1, Show 2, Show 3 and 4 more"
    assert dismiss == BURST_DISMISS_MS


def test_a_burst_names_what_it_can_and_counts_the_rest() -> None:
    """Names stop being scannable past a few; the number is the useful part."""
    named = burst_banner([_prog(f"S{i}") for i in range(BURST_NAMED_LIMIT)])[1]
    assert named == ", ".join(f"S{i}" for i in range(BURST_NAMED_LIMIT))
    assert "more" not in named, "nothing was left over, so say nothing about it"

    over = burst_banner([_prog(f"S{i}") for i in range(BURST_NAMED_LIMIT + 1)])[1]
    assert over.endswith(" and 1 more")


def test_two_is_already_a_burst() -> None:
    """No threshold beyond 'more than one' — two toasts at once is the bug."""
    title, message, _ = burst_banner([_prog("A"), _prog("B")])
    assert title == "2 shows starting in 15 min"
    assert message == "A, B"


def test_a_spread_of_start_times_says_no_time_rather_than_a_wrong_one() -> None:
    """The first sweep can catch a 15-minute spread; one time would be a lie.

    Every other tick agrees on the time, because everything in it entered the
    window together — so the shared clause is the normal case and this is the
    exception that must not print a confident wrong answer.
    """
    title, _message, _ = burst_banner(
        [_prog("A", when="in 2 min"), _prog("B", when="in 14 min")])

    assert title == "2 shows starting", f"picked a time it could not know: {title}"


def test_the_channel_is_dropped_from_a_burst_on_purpose() -> None:
    """Seven channels will not fit; the titles are what identify the shows."""
    _title, message, _ = burst_banner(
        [_prog("A", channel="BBC One"), _prog("B", channel="ITV2")])

    assert "BBC One" not in message and "ITV2" not in message


def test_the_dead_watchlist_signal_is_gone() -> None:
    """It was emitted once per programme and nothing ever connected to it.

    Found while removing the per-programme emit: ``watchlist_notification`` had
    no ``.connect()`` anywhere in the app or the suite. Asserted so it is not
    reintroduced by someone reading the old emit in history and assuming a
    listener exists.
    """
    from metatv.core.epg_manager import EpgManager

    assert not hasattr(EpgManager, "watchlist_notification")


# ── the worker must CALL it, and call it once ──────────────────────────────
#
# Everything above tests the composer in isolation, and that is not enough: put
# the per-programme loop back and all seven still pass, because none of them
# reach the code that decides how many banners to raise. That mutation survived
# on the first run of this file, which is the whole argument for checking.
#
# An AST guard rather than a driven worker, matching the sibling guard in
# tests/test_watchlist_notify_off_ui_thread.py: the worker wants an active
# provider with a resolvable EPG url, programme rows inside the lead window and
# matching rules before it emits anything, and no test in the suite stands that
# up. The property here is structural anyway — how many times the emit runs —
# and structure is what an AST can actually see.

_SRC = (pathlib.Path(__file__).resolve().parent.parent
        / "metatv/core/epg_manager.py")


def _func(name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(_SRC.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone — this guard needs rewiring")


def _emit_calls(fn: ast.FunctionDef) -> list[ast.Call]:
    return [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "emit"]


def test_the_worker_raises_exactly_one_banner_per_tick() -> None:
    """One emit, and it must not be inside a loop."""
    fn = _func("_watchlist_notification_worker")

    emits = _emit_calls(fn)
    assert len(emits) == 1, (
        f"{len(emits)} emit() calls in the worker — a tick raises ONE banner. "
        "Adding a second is how the burst comes back.")

    loops = [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While))]
    in_loop = {id(e) for loop in loops for e in _emit_calls(loop)}
    assert id(emits[0]) not in in_loop, (
        "the notification emit is inside a loop again — that is one banner per "
        "programme, which is the exact bug this file exists for (seven at once "
        "in the owner's 01:15 log).")


def test_the_worker_composes_through_the_shared_helper() -> None:
    """It must not hand-roll the banner text beside the tested composer."""
    called = {n.func.id for n in ast.walk(_func("_watchlist_notification_worker"))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "burst_banner" in called, (
        "the worker builds its banner some other way — then every test above "
        "is checking a function the app does not use.")
