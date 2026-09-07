"""Behavioral coverage for ``MainWindow.status()`` (STATUS-1's chokepoint).

A real ``QStatusBar`` on a skeleton host, driven through the real
``_StatusMixin.status`` implementation — not a copy of it (CLAUDE.md: a test
double that copies behaviour goes stale; run the real one).
"""

from __future__ import annotations

import pytest
from loguru import logger

from metatv.gui import icons as _icons
from metatv.gui.main_window_status import _StatusMixin


class _Host(_StatusMixin):
    """Plain host: the real QStatusBar plus nothing else `status()` touches."""

    def __init__(self, status_bar) -> None:
        self.status_bar = status_bar


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def host(qapp):
    from PyQt6.QtWidgets import QStatusBar

    from tests.conftest import destroy_widget

    bar = QStatusBar()
    yield _Host(bar)
    destroy_widget(bar)


def test_shows_the_text(host):
    host.status("Ready")
    assert host.status_bar.currentMessage() == "Ready"


def test_ms_zero_is_persistent(host):
    """Qt's own ``timeout=0`` semantics: no timer is armed, so the message
    outlives a wait that clears a short explicit timeout (see
    ``test_a_short_explicit_timeout_actually_clears`` below)."""
    from PyQt6.QtTest import QTest

    host.status("Loading channels…", ms=0)
    QTest.qWait(200)
    assert host.status_bar.currentMessage() == "Loading channels…"


def test_a_short_explicit_timeout_actually_clears(host):
    """Proves ``ms`` really reaches Qt's own timer (not just accepted and
    ignored): a short explicit timeout clears the message once real Qt time
    passes, driven by the real event loop rather than a mock."""
    from PyQt6.QtTest import QTest

    host.status("Copied", ms=30)
    assert host.status_bar.currentMessage() == "Copied"
    QTest.qWait(200)
    assert host.status_bar.currentMessage() == ""


def test_default_timeout_outlives_a_short_wait(host):
    """Parity default: the most common of the five ad-hoc timeouts the
    migrated call sites used before this chokepoint existed. Proven against
    the SAME real-timer mechanism as the short-timeout case above — a wait
    long enough to clear a 30ms message must not clear the 4000ms default."""
    from PyQt6.QtTest import QTest

    host.status("Hello")   # default ms=4000
    QTest.qWait(200)
    assert host.status_bar.currentMessage() == "Hello"


def test_warn_prefixes_the_glyph_and_logs_a_warning(host):
    sink: list[str] = []
    handle = logger.add(lambda msg: sink.append(msg.record["message"]), level="WARNING")
    try:
        host.status("Source unreachable", level="warn")
    finally:
        logger.remove(handle)

    shown = host.status_bar.currentMessage()
    assert shown.startswith(_icons.notification_warning_icon)
    assert "Source unreachable" in shown
    assert sink == ["Source unreachable"], "must log the UNPREFIXED text"


def test_error_prefixes_the_glyph_and_logs_an_error(host):
    sink: list[str] = []
    handle = logger.add(lambda msg: sink.append(msg.record["message"]), level="ERROR")
    try:
        host.status("Could not save your rating", level="error")
    finally:
        logger.remove(handle)

    shown = host.status_bar.currentMessage()
    assert shown.startswith(_icons.notification_error_icon)
    assert "Could not save your rating" in shown
    assert sink == ["Could not save your rating"]


def test_info_carries_no_glyph_and_does_not_log(host):
    sink: list[str] = []
    handle = logger.add(lambda msg: sink.append(msg.record["message"]), level="WARNING")
    try:
        host.status("Favorite added", level="info")
    finally:
        logger.remove(handle)

    shown = host.status_bar.currentMessage()
    assert shown == "Favorite added", "info must not gain a glyph prefix"
    assert not shown.startswith(_icons.notification_warning_icon)
    assert not shown.startswith(_icons.notification_error_icon)
    assert sink == [], "info must not reach the log via status()"


def test_warn_and_error_glyphs_are_distinct(host):
    """Colour is never the only cue — the glyph itself must differ between
    the two non-info levels, not just some shared cue plus colour."""
    assert _icons.notification_warning_icon != _icons.notification_error_icon


def test_unknown_level_raises(host):
    with pytest.raises(ValueError):
        host.status("x", level="critical")
    # Nothing shown, nothing left dangling on the real status bar.
    assert host.status_bar.currentMessage() == ""
