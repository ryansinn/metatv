"""A burst of config changes must cost ONE disk write, not one each.

``Config.save()`` serialises 299 keys and copies the whole 129 KB file to .bak
first — 14 ms idle, 55-93 ms in the owner's running app. Fine once; ruinous on
a repeat.

``_on_search_text_changed`` is explicitly debounced, with the comment *"debounce
to avoid per-keystroke DB queries"* — and it called ``_save_search_state()``
BEFORE starting that timer. So the DB query was protected and the disk write was
not, which is the cheaper of the two things guarded and the more expensive one
left open. Measured on the owner's log 2026-09-02: six full writes in thirteen
seconds from nothing but typing.

The value still updates immediately; only the write is deferred. And a pending
write flushes on shutdown, so deferring costs nothing on the path that matters.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest

from metatv.gui import deferred_config_save as defer


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _host(qapp):
    """A real QObject host — QTimer needs a QObject parent, and the module's
    contract is "anything with .config and ._register_cleanable"."""
    from PyQt6.QtCore import QObject

    host = QObject()
    host.config = MagicMock()
    host._register_cleanable = MagicMock()
    return host


# ── the burst ────────────────────────────────────────────────────────────────

def test_asking_does_not_write(qapp):
    """The whole point: the expensive part waits."""
    host = _host(qapp)
    defer.save_soon(host)
    host.config.save.assert_not_called()


def test_a_burst_of_asks_produces_exactly_one_write(qapp):
    """Ten keystrokes, one write. Driven through the module's own slot rather
    than a real event loop so the count is exact rather than timing-dependent."""
    host = _host(qapp)
    for _ in range(10):
        defer.save_soon(host)
    host.config.save.assert_not_called()
    defer._write(host)
    assert host.config.save.call_count == 1


def test_every_ask_restarts_the_countdown(qapp):
    """Restarting is what collapses a burst.

    A timer merely left running fires mid-burst and writes twice for one typed
    word. Asserted by counting ``start()`` calls rather than by watching
    ``remainingTime()`` against the wall clock: the clock version passed on its
    own and failed inside a 922-test run, which is a flaky gate rather than a
    guard, and a flaky guard gets deleted the second time it cries wolf.
    """
    host = _host(qapp)
    defer.save_soon(host)
    timer = host.__dict__[defer._TIMER_ATTR]
    assert timer.isSingleShot(), "a repeating timer would write forever"

    starts = []
    real_start = timer.start
    timer.start = lambda *a: (starts.append(1), real_start(*a))[1]

    for _ in range(4):
        defer.save_soon(host)
    assert len(starts) == 4, (
        f"{len(starts)} of 4 asks restarted the countdown — one that does not "
        "restart lets the write land mid-burst instead of after it")


# ── the flush, which is why deferring is safe ────────────────────────────────

def test_flush_writes_a_pending_save(qapp):
    host = _host(qapp)
    defer.save_soon(host)
    assert defer.flush(host) is True
    host.config.save.assert_called_once()
    assert not host.__dict__[defer._TIMER_ATTR].isActive(), "timer left armed"


def test_flush_with_nothing_pending_writes_nothing(qapp):
    """Shutdown must not force a redundant 129 KB write on every close."""
    host = _host(qapp)
    assert defer.flush(host) is False
    host.config.save.assert_not_called()


def test_flush_after_a_write_does_not_write_again(qapp):
    host = _host(qapp)
    defer.save_soon(host)
    defer._write(host)
    assert defer.flush(host) is False
    assert host.config.save.call_count == 1


def test_the_flush_is_registered_for_shutdown_exactly_once(qapp):
    """Registered when the timer is created, not per call — the registry takes
    one entry per name and re-registering would be silent churn."""
    host = _host(qapp)
    for _ in range(5):
        defer.save_soon(host)
    assert host._register_cleanable.call_count == 1
    name, callback = host._register_cleanable.call_args[0]
    assert name == "deferred_config_save"

    callback()                        # what closeEvent will call
    host.config.save.assert_called_once()


def test_a_failing_save_does_not_propagate(qapp):
    """A config that cannot be written must not take down the shutdown path."""
    host = _host(qapp)
    host.config.save.side_effect = OSError("disk full")
    defer.save_soon(host)
    assert defer.flush(host) is False


# ── the wiring ───────────────────────────────────────────────────────────────

SRC = (pathlib.Path(__file__).resolve().parent.parent
       / "metatv" / "gui" / "main_window_channels.py").read_text()


def test_the_search_state_no_longer_writes_synchronously():
    """The line this exists to remove.

    ``_save_search_state`` ran a full config write inline, and one of its seven
    callers is the per-keystroke handler.
    """
    body = SRC[SRC.index("def _save_search_state"):]
    body = body[:body.index("\n    def ", 1)]
    assert "self.config.save()" not in body, (
        "_save_search_state writes synchronously again — that is one full "
        "129 KB write per keystroke")
    assert "_cfgsave.save_soon(self)" in body


def test_the_state_itself_is_still_updated_immediately():
    """Only the WRITE is deferred. Anything reading config in memory — the
    restore path included — must see the change at once."""
    body = SRC[SRC.index("def _save_search_state"):]
    body = body[:body.index("\n    def ", 1)]
    assert "self.config.last_search_state = state" in body
    assert (body.index("self.config.last_search_state = state")
            < body.index("_cfgsave.save_soon(self)"))
