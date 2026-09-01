"""The 60-second watchlist check must not touch the database on the UI thread.

Owner's log, 2026-09-01, with the app simply sitting open::

    04:38:37  UI thread unresponsive for  925ms
    04:39:37  UI thread unresponsive for  831ms
    04:40:37  UI thread unresponsive for  984ms
    04:41:37  UI thread unresponsive for  937ms

A stall on the minute, every minute, for as long as the app runs — and the
watchdog cannot say what caused it, only that something did.

It was ``_check_watchlist_notifications``, wired straight to a 60s ``QTimer``
and doing all of this inline on the main thread:

* ``get_hidden_provider_ids()`` — a query
* ``query(ProviderDB).filter_by(is_active=True)`` — a query
* ``get_programs_starting_soon(...)`` — a scan of **344,468** programme rows
* ``query(ChannelDB).filter_by(id=...)`` **per match** — N+1 against 785k channels

CLAUDE.md: *"Any query scanning/aggregating large tables (channels, EPG — 240k+
rows) runs in an executor, never on the UI thread."* This one predates the rule
and does not get an exception.

The tick is now a submit; the work is on the manager's single-worker executor,
which is the same one that serialises fetch/relink writes — so it cannot race an
EPG write either.
"""
from __future__ import annotations

import ast
import pathlib


_SRC = (pathlib.Path(__file__).resolve().parent.parent
        / "metatv/core/epg_manager.py")


def _func(name: str) -> ast.FunctionDef:
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone — this guard needs rewiring")


def _calls(fn: ast.FunctionDef) -> set[str]:
    return {n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


# ── the tick itself ────────────────────────────────────────────────────────


def test_the_timer_tick_opens_no_session():
    """The main-thread half may read config and submit. Nothing else."""
    calls = _calls(_func("_check_watchlist_notifications"))
    for banned in ("session_scope", "get_session", "query",
                   "get_programs_starting_soon", "get_hidden_provider_ids"):
        assert banned not in calls, (
            f"_check_watchlist_notifications calls {banned}() on the UI thread — "
            "that is the stall-every-minute this was split to fix")


def test_the_tick_hands_the_work_to_the_executor():
    assert "submit" in _calls(_func("_check_watchlist_notifications")), (
        "the tick no longer offloads, so the work is back on the UI thread")


def test_the_worker_is_the_one_doing_the_database_work():
    """Non-degeneracy: the query must still happen SOMEWHERE."""
    calls = _calls(_func("_watchlist_notification_worker"))
    assert "get_programs_starting_soon" in calls
    assert "get_hidden_provider_ids" in calls, (
        "the hidden-provider gate went missing in the move — a notification "
        "for an expired source is the absolute gate failing where it shows")


def test_the_worker_raises_toasts_through_the_private_signal():
    """``NotificationManager.show`` builds a QTimer, so a worker may not call it.

    This is the rule the EPG manager already states for its other workers; the
    move makes it apply here, because this code is now off the main thread.
    """
    fn = _func("_watchlist_notification_worker")
    src = ast.get_source_segment(_SRC.read_text(encoding="utf-8"), fn) or ""
    assert "_notify.emit" in src, "the worker must emit, not call the manager"
    assert "self.notifications.show" not in src, (
        "the worker calls NotificationManager.show directly, which builds a "
        "QTimer off the main thread")


# ── the queue guard ────────────────────────────────────────────────────────


class _FakeExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, *a, **kw):
        self.submitted.append(fn)
        return None


def _manager(monkeypatch, *, patterns=("Doctor Who",)):
    from types import SimpleNamespace

    from metatv.core.epg_manager import EpgManager

    mgr = EpgManager.__new__(EpgManager)
    mgr._shutting_down = False
    mgr._notif_check_pending = False
    mgr._executor = _FakeExecutor()
    mgr.notifications = object()
    mgr.config = SimpleNamespace(epg_notification_minutes_before=15)
    monkeypatch.setattr("metatv.core.epg_manager.watchlist.patterns",
                        lambda _cfg: list(patterns))
    return mgr


def test_a_second_tick_does_not_stack_another_check(monkeypatch):
    """A slow guide fetch must not let the 60s timer queue eleven of these.

    Fetches run on this same single-worker executor and take 20-30s routinely
    (69.3s in #601), so without the guard a long one stacks a check per minute
    behind itself and they all run back to back when it finishes.
    """
    mgr = _manager(monkeypatch)
    mgr._check_watchlist_notifications()
    mgr._check_watchlist_notifications()
    mgr._check_watchlist_notifications()
    assert len(mgr._executor.submitted) == 1, (
        f"queued {len(mgr._executor.submitted)} checks; the pending guard is not holding")


def test_the_gate_reopens_once_the_worker_finishes(monkeypatch):
    """Non-degeneracy: a stuck flag would silence alerts for the whole session."""
    mgr = _manager(monkeypatch)
    mgr._check_watchlist_notifications()
    assert mgr._notif_check_pending is True
    mgr._notif_check_pending = False           # what the worker's finally does
    mgr._check_watchlist_notifications()
    assert len(mgr._executor.submitted) == 2


def test_a_shutdown_mid_submit_does_not_jam_the_gate(monkeypatch):
    """RuntimeError from a dead executor must clear the flag, not leave it set."""
    mgr = _manager(monkeypatch)

    def _boom(fn, *a, **kw):
        raise RuntimeError("executor shut down")

    mgr._executor.submit = _boom
    mgr._check_watchlist_notifications()
    assert mgr._notif_check_pending is False, (
        "teardown left the gate closed — alerts would stay silent if the "
        "manager outlived it")


def test_no_patterns_means_no_work_at_all(monkeypatch):
    """An empty watch list must not even reach the executor."""
    mgr = _manager(monkeypatch, patterns=())
    mgr._check_watchlist_notifications()
    assert mgr._executor.submitted == []
    assert mgr._notif_check_pending is False
