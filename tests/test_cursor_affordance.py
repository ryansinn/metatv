"""Behavioral tests for the app-wide pointing-hand cursor affordance.

The affordance is a single application-level event filter
(:mod:`metatv.gui.cursor_affordance`) that, on a widget's ``Enter`` event, gives
clickable controls ``Qt.CursorShape.PointingHandCursor``. These tests construct
the filter and synthesize ``Enter`` events on sample widgets, then assert the
resulting ``widget.cursor().shape()`` — exercising the real decision path rather
than its shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QPushButton,
    QRadioButton,
)

from metatv.gui.cursor_affordance import (
    CLICKABLE_PROPERTY,
    PointingHandFilter,
    set_clickable,
)


@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


def _send_enter(filt: PointingHandFilter, widget) -> bool:
    """Run *widget* through the filter's Enter handling; return its result."""
    event = QEvent(QEvent.Type.Enter)
    return filt.eventFilter(widget, event)


def test_enter_sets_hand_on_enabled_button(qapp):
    """An enabled push-button (chips/rail buttons are QPushButtons) gets the hand."""
    filt = PointingHandFilter()
    btn = QPushButton("Play")
    assert btn.cursor().shape() != Qt.CursorShape.PointingHandCursor

    consumed = _send_enter(filt, btn)

    assert btn.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert consumed is False, "filter must never swallow the Enter event"


def test_enter_does_not_set_hand_on_checkbox(qapp):
    """A QCheckBox keeps the normal cursor — its box is the affordance."""
    filt = PointingHandFilter()
    box = QCheckBox("Enabled")

    _send_enter(filt, box)

    assert box.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_enter_does_not_set_hand_on_radio(qapp):
    """A QRadioButton keeps the normal cursor — its circle is the affordance."""
    filt = PointingHandFilter()
    radio = QRadioButton("Option")

    _send_enter(filt, radio)

    assert radio.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_enter_does_not_set_hand_on_disabled_button(qapp):
    """A disabled button offers nothing to click — no hand."""
    filt = PointingHandFilter()
    btn = QPushButton("Unavailable")
    btn.setEnabled(False)

    _send_enter(filt, btn)

    assert btn.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_disabling_after_hover_clears_the_hand(qapp):
    """A button hovered while enabled, then disabled, drops the hand on re-hover."""
    filt = PointingHandFilter()
    btn = QPushButton("Toggle")

    _send_enter(filt, btn)
    assert btn.cursor().shape() == Qt.CursorShape.PointingHandCursor

    btn.setEnabled(False)
    _send_enter(filt, btn)
    assert btn.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_custom_label_opts_in_via_property(qapp):
    """A non-button widget opts in with the ``clickable=True`` dynamic property."""
    filt = PointingHandFilter()
    label = QLabel("Genre: Drama")
    label.setProperty(CLICKABLE_PROPERTY, True)

    _send_enter(filt, label)

    assert label.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_plain_label_without_property_gets_nothing(qapp):
    """A plain (non-opted-in) label is not treated as clickable."""
    filt = PointingHandFilter()
    label = QLabel("Just text")

    _send_enter(filt, label)

    assert label.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_non_enter_event_is_ignored(qapp):
    """Events other than Enter never touch the cursor."""
    filt = PointingHandFilter()
    btn = QPushButton("Play")

    consumed = filt.eventFilter(btn, QEvent(QEvent.Type.Leave))

    assert btn.cursor().shape() != Qt.CursorShape.PointingHandCursor
    assert consumed is False


# ---------------------------------------------------------------------------
# set_clickable() — the helper hand-rolled clickable widgets call instead of a
# direct setCursor(Qt.CursorShape.PointingHandCursor) literal.
# ---------------------------------------------------------------------------

def test_set_clickable_sets_property_and_cursor_immediately(qapp):
    """set_clickable(widget) sets the opt-in property AND applies the hand right away.

    Unlike the filter (which only reacts to a hover Enter event), callers of
    set_clickable need the cursor to update immediately — e.g. a poster that
    becomes clickable the instant its image loads, while already hovered.
    """
    label = QLabel("Genre: Drama")

    set_clickable(label)

    assert label.property(CLICKABLE_PROPERTY) is True
    assert label.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_set_clickable_false_clears_property_and_cursor(qapp):
    """set_clickable(widget, False) reverses a prior opt-in (e.g. poster cleared)."""
    label = QLabel("Poster")
    set_clickable(label, True)
    assert label.cursor().shape() == Qt.CursorShape.PointingHandCursor

    set_clickable(label, False)

    assert label.property(CLICKABLE_PROPERTY) is False
    assert label.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_set_clickable_respects_disabled_widget(qapp):
    """A disabled widget never gets the hand, even when marked clickable=True."""
    label = QLabel("Disabled clickable")
    label.setEnabled(False)

    set_clickable(label, True)

    assert label.cursor().shape() != Qt.CursorShape.PointingHandCursor


# ---------------------------------------------------------------------------
# Real app primitives — proving the migration off hand-rolled setCursor() calls
# actually wired each primitive through set_clickable() / the filter.
# ---------------------------------------------------------------------------

def test_details_clickable_label_gets_hand_cursor(qapp):
    """details_sections._ClickableLabel (copy-channel-id-on-click) opts in via set_clickable."""
    from metatv.gui.details_sections import _ClickableLabel

    label = _ClickableLabel()

    assert label.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_discover_card_gets_hand_cursor(qapp):
    """_ContentCard (Discover poster card) has no shared clickable base class —
    it calls set_clickable() directly at its own construction site, the
    accepted one-off exception to routing through a shared base.
    """
    from unittest.mock import MagicMock
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtGui import QPixmap
    from metatv.core.discovery_engine import ContentCard
    from metatv.gui.discover_card import _ContentCard

    class _FakeImageCache(QObject):
        image_loaded = pyqtSignal(str, QPixmap)
        image_failed = pyqtSignal(str, str)

        def get_image_async(self, url, provider_urls=None):
            pass

    config = MagicMock()
    config.movie_icon = "M"
    config.series_icon = "S"
    config.rating_star_icon = "*"
    config.like_icon = "+"
    config.favorite_icon = "F"
    config.queue_icon = "Q"
    config.watched_icon = "W"
    config.discover_zoom = 1.0

    card_data = ContentCard(
        channel_id="ch-001", title="Test Movie", media_type="movie",
        thumbnail_url=None, rating=None, year=2023, genre="Action",
    )
    card = _ContentCard(card_data, _FakeImageCache(), config)

    assert card.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_real_app_checkbox_subclass_excluded(qapp):
    """A real app QCheckBox subclass (filter panel's tri-state box) never gets the hand.

    Exercises the exclusion through an actual app widget, not just a bare
    QCheckBox, since a QCheckBox subclass could in principle re-opt-in.
    """
    from metatv.gui.filter_group_row import _TriCheckbox

    box = _TriCheckbox()
    filt = PointingHandFilter()

    _send_enter(filt, box)

    assert box.cursor().shape() != Qt.CursorShape.PointingHandCursor


# ---------------------------------------------------------------------------
# Drift guard — PointingHandCursor must never be hand-rolled outside this module
# ---------------------------------------------------------------------------
#
# #271 built the chokepoint but explicitly deferred sweeping existing call
# sites; nothing then stopped LATER PRs (#277, #293, #297) from adding new
# hand-rolled setCursor(Qt.CursorShape.PointingHandCursor) calls that bypass
# it entirely (a disabled widget with a hand-rolled call never clears the
# cursor — the app-level filter's disabled-widget handling never runs for
# it). This test closes that hole for good: any future occurrence of the
# literal anywhere under metatv/ outside cursor_affordance.py itself fails
# the suite immediately, pointing at set_clickable().

_REPO_ROOT = Path(__file__).resolve().parents[1]
_METATV_ROOT = _REPO_ROOT / "metatv"
_CHOKEPOINT_REL = "metatv/gui/cursor_affordance.py"


def test_pointing_hand_cursor_only_in_chokepoint() -> None:
    """``PointingHandCursor`` must appear nowhere under metatv/ except the chokepoint.

    A hand-rolled ``widget.setCursor(Qt.CursorShape.PointingHandCursor)`` bypasses
    the app-level ``PointingHandFilter`` entirely — it never gets the disabled-
    widget handling, and doesn't need to exist at all for a plain
    ``QAbstractButton`` (those qualify automatically). If this test fires:
    remove the direct ``setCursor`` call, and if the widget is not a button, call
    ``cursor_affordance.set_clickable(widget)`` instead.
    """
    violations: list[tuple[str, int, str]] = []
    for path in _METATV_ROOT.rglob("*.py"):
        rel = str(path.relative_to(_REPO_ROOT))
        if rel == _CHOKEPOINT_REL:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if "PointingHandCursor" in line:
                violations.append((rel, lineno, line.strip()))

    if not violations:
        return

    report = "\n".join(
        f"  {rel}:{lineno}  →  {snippet}" for rel, lineno, snippet in violations
    )
    pytest.fail(
        f"Found {len(violations)} hand-rolled PointingHandCursor reference(s) "
        "outside metatv/gui/cursor_affordance.py. Remove the direct setCursor() "
        "call — buttons qualify automatically; non-button widgets must call "
        f"cursor_affordance.set_clickable(widget) instead:\n{report}"
    )
