"""A programme on several sources: open it, or just play it.

Three owner reports, one cause. Expansion was wired to ``play_clicked``, which
only fires on the 18px marker slot AND only when the row counts as playable —
so an expandable row had to claim it was playable to open at all:

* "clicking the show title for an epg item that has multiple channels playing
  it, does not expand the row. only clicking on the expand collapse carot
  expands"
* "the carot turns into a play icon ... but it shouldn't because it is
  expanding or collapsing the options, not playing"
* "carot and play buttons look way too similar"

The row now has TWO leading columns. A source-stack marker hangs in the left
margin at exactly ``_CHILD_INDENT`` wide, which pushes the play slot into the
same column as its children's — so the play affordances form one continuous
line down the group and the parent's title shares its left edge with its
sources'. Clicking anywhere that is not the play button opens the row.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QEnterEvent, QMouseEvent

from metatv.core.config import Config
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.sidebar.alerts_rows import (
    ROW_PAD_Y, SLOT_W, _AlertRow, _CHILD_INDENT,
)

NOW = datetime(2026, 8, 26, 12, 0, 0)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _parent(qapp, tmp_path, *, live=True, expanded=False):
    row = _AlertRow("Two and a Half Men", "8m left", Config(config_dir=tmp_path),
                    when=NOW + timedelta(minutes=8), live=live,
                    started_at=NOW - timedelta(minutes=22) if live else None,
                    chip_time=True, expandable=True, expanded=expanded)
    row.setFixedWidth(290)
    row.show()
    qapp.processEvents()
    _unhover(row)
    return row


def _child(qapp, tmp_path):
    row = _AlertRow("DTOUR [CA]", "8m left", Config(config_dir=tmp_path),
                    when=NOW + timedelta(minutes=8), live=True,
                    started_at=NOW - timedelta(minutes=22), indent=_CHILD_INDENT)
    row.setFixedWidth(290)
    row.show()
    qapp.processEvents()
    _unhover(row)
    return row


def _unhover(row):
    """Clear the synthetic hover the offscreen platform delivers.

    It parks the cursor at (0,0), so ``show()`` sends an enter event to
    whatever lands there — which silently makes every row look hovered.
    """
    row.leaveEvent(QEvent(QEvent.Type.Leave))


def _hover(row):
    pos = QPointF(4, 4)
    row.enterEvent(QEnterEvent(pos, pos, pos))


def _click(row, x):
    pos = QPointF(x, row.height() // 2)
    row.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def _signals(row):
    got = {"expand": 0, "play": 0, "row": 0}
    row.expand_clicked.connect(lambda: got.__setitem__("expand", got["expand"] + 1))
    row.play_clicked.connect(lambda: got.__setitem__("play", got["play"] + 1))
    row.row_clicked.connect(lambda: got.__setitem__("row", got["row"] + 1))
    return got


class TestTheWholeRowOpensIt:
    """The reported bug: only an 18px strip responded."""

    @pytest.mark.parametrize("x,where", [(150, "the title"), (5, "the marker"),
                                         (270, "the empty space")])
    def test_clicking_anywhere_expands(self, qapp, tmp_path, x, where):
        row = _parent(qapp, tmp_path)
        got = _signals(row)
        _click(row, x)
        assert got["expand"] == 1, f"clicking {where} did not open the row"
        assert got["play"] == 0, f"clicking {where} tried to PLAY"
        row.deleteLater()

    def test_a_plain_row_still_selects_rather_than_expanding(self, qapp, tmp_path):
        """Only an expandable row redirects its body click."""
        row = _child(qapp, tmp_path)
        got = _signals(row)
        _click(row, 150)
        assert got["row"] == 1 and got["expand"] == 0
        row.deleteLater()


class TestTheMarkerIsNotAPlayButton:
    """Two columns, so the disclosure control never becomes a triangle."""

    def test_the_marker_is_the_source_stack_not_a_chevron(self, qapp, tmp_path):
        """A chevron at 14px is very nearly a play triangle, which is the
        collision the owner reported. The app-wide expand/collapse chevrons
        keep their own keys and are not used here."""
        row = _parent(qapp, tmp_path)
        assert row._marker is not None
        assert _icons.vector_key("sources_closed") != _icons.vector_key("collapse")
        assert _icons.vector_key("sources_open") != _icons.vector_key("expand")
        row.deleteLater()

    def test_the_marker_changes_between_open_and_closed(self, qapp, tmp_path):
        """Shape, not colour alone — the two states must be told apart with the
        hue ignored."""
        shut = _parent(qapp, tmp_path, expanded=False)
        open_ = _parent(qapp, tmp_path, expanded=True)
        a = shut._marker.pixmap().toImage()
        b = open_._marker.pixmap().toImage()
        assert not a.isNull() and not b.isNull()
        assert a != b, "the marker looks identical open and closed"
        for r in (shut, open_):
            r.deleteLater()

    def test_an_unhovered_expandable_row_shows_no_play_glyph(self, qapp, tmp_path):
        row = _parent(qapp, tmp_path)
        assert row._slot.pixmap().isNull(), (
            "the play slot is painted with no pointer on the row"
        )
        row.deleteLater()

    def test_hovering_puts_play_in_the_slot_and_leaves_the_marker_alone(
            self, qapp, tmp_path):
        row = _parent(qapp, tmp_path)
        before = row._marker.pixmap().toImage()
        _hover(row)
        assert not row._slot.pixmap().isNull(), "no play affordance on hover"
        assert row._marker.pixmap().toImage() == before, (
            "hovering changed the disclosure marker — it is not a play control"
        )
        row.deleteLater()

    def test_hovering_then_clicking_the_slot_plays(self, qapp, tmp_path):
        row = _parent(qapp, tmp_path)
        got = _signals(row)
        _hover(row)
        _click(row, row._slot_rect().left() + SLOT_W // 2)
        assert got["play"] == 1 and got["expand"] == 0
        row.deleteLater()

    def test_an_upcoming_programme_offers_no_play(self, qapp, tmp_path):
        """No time machine — an upcoming row's only action is to open."""
        row = _parent(qapp, tmp_path, live=False)
        got = _signals(row)
        _hover(row)
        assert row._slot.pixmap().isNull()
        _click(row, row._slot_rect().left() + SLOT_W // 2)
        assert got["play"] == 0 and got["expand"] == 1
        row.deleteLater()


class TestOneContinuousPlayColumn:
    """Rendered geometry — the point of the two-column leading area."""

    def test_parent_and_child_play_slots_share_a_column(self, qapp, tmp_path):
        parent, child = _parent(qapp, tmp_path), _child(qapp, tmp_path)
        assert parent._slot_rect().left() == child._slot_rect().left(), (
            f"parent slot at {parent._slot_rect().left()}, child at "
            f"{child._slot_rect().left()} — the play affordances do not line up"
        )
        for r in (parent, child):
            r.deleteLater()

    def test_the_marker_hangs_left_of_that_column(self, qapp, tmp_path):
        row = _parent(qapp, tmp_path)
        marker_x = row._marker.mapTo(row, QPoint(0, 0)).x()
        assert marker_x < row._slot_rect().left()
        assert row._marker.width() == _CHILD_INDENT, (
            "the marker must be exactly one child-indent wide, or the play "
            "slot lands in a different column from the children's"
        )
        row.deleteLater()

    def test_parent_and_child_titles_share_a_left_edge(self, qapp, tmp_path):
        from metatv.gui.chip_row import row_title_label

        parent, child = _parent(qapp, tmp_path), _child(qapp, tmp_path)
        px = row_title_label(parent).mapTo(parent, QPoint(0, 0)).x()
        cx = row_title_label(child).mapTo(child, QPoint(0, 0)).x()
        assert px == cx, f"parent title at {px}, child at {cx}"
        for r in (parent, child):
            r.deleteLater()


class TestTheRowsAreNoLongerPaddedLikeAWastedLine:
    """Owner: "the space between each item is a wasted row ... spacing between
    rows should be cut in half"."""

    def test_padding_is_halved_but_the_line_box_still_fits(self, qapp, tmp_path):
        from PyQt6.QtWidgets import QLabel

        line = QLabel().fontMetrics().height()
        row = _child(qapp, tmp_path)
        padding = row.minimumHeight() - line
        # Floor AND the property that would break: never shorter than the font's
        # full line box (that is what a clipped descender is), and not padded
        # back out to the old 12px.
        assert row.minimumHeight() >= line, "a descender would be clipped"
        assert 0 < padding <= 8, f"{padding}px of padding — the halving was lost"
        assert 2 * ROW_PAD_Y <= 6
        row.deleteLater()

    def test_a_group_heading_leads_in_without_a_blank_line(self, qapp, tmp_path):
        from metatv.gui.sidebar.base import GroupHeading

        heading = GroupHeading("SERIES", 7)
        label = heading.label.sizeHint().height()
        chrome = heading.sizeHint().height() - label
        assert chrome > 0, "a heading needs SOME lead-in to separate groups"
        assert chrome <= 8, (
            f"{chrome}px of chrome around a {label}px label reads as a blank row"
        )
        heading.deleteLater()
