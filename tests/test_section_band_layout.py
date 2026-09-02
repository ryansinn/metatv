"""The section band, measured against the settled design.

Every assertion here is a thing the FIRST attempt got wrong. It was built from
the sidebar's ``GroupHeading`` grammar instead of the artifact (Finding Tron,
Concept E), and three of the differences are not arbitrary:

* the label is **bright** and the count is **muted** — the opposite of the
  sidebar, because here the label names the field that matched, which is the
  whole explanation of why a row is on screen;
* a **hairline rule** runs from the label across to the count, and its absence
  is what left the band looking empty across the width. Owner: *"why is there
  so much empty space on the right side of the search results area now."*;
* the **caret is at the far right**, after the control — it was deleted.

Geometry, not tokens-exist: CLAUDE.md is explicit that "order ≠ position" and
that a UI slice asserts rendered appearance.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QFont

from metatv.gui import channel_list_section_band as band


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def wide(qapp):
    """A realistic band: 900px, the width a search list actually gets."""
    return QRect(0, 0, 900, band.band_height(QFont()))


def _lay(rect, *, has_toggle=True, count=462, label="TITLES"):
    return band.layout(rect, label=label, count=count,
                       has_toggle=has_toggle, base_font=QFont())


def test_the_parts_run_left_to_right_in_the_designed_order(wide):
    """Label · rule · count · All|Word · caret."""
    b = _lay(wide)
    xs = [("label", b.label.left()), ("rule", b.rule.left()),
          ("count", b.count.left()), ("all", b.all_seg.left()),
          ("word", b.word_seg.left()), ("caret", b.caret.left())]
    assert xs == sorted(xs, key=lambda kv: kv[1]), xs


def test_the_rule_actually_spans_the_gap(wide):
    """The fix for the empty space — flex:1, so it takes whatever is left."""
    b = _lay(wide)
    assert not b.rule.isNull(), "no rule at all — the band reads as empty"
    assert b.rule.height() == 1, "a hairline, not a bar"
    assert b.rule.width() > wide.width() // 2, (
        f"the rule is {b.rule.width()}px of {wide.width()} — it is meant to "
        "carry the eye from the label to the count, not to be a dash")
    # It touches neither neighbour: a rule running into the count reads as an
    # underline on the number.
    assert b.rule.left() > b.label.right()
    assert b.rule.right() < b.count.left()


def test_everything_after_the_rule_is_pinned_to_the_right_edge(wide):
    """Right-to-left placement is what makes the rule elastic."""
    b = _lay(wide)
    assert wide.right() - b.caret.right() == band.PAD_H
    narrow = _lay(QRect(0, 0, 500, wide.height()))
    assert narrow.caret.right() == 500 - 1 - band.PAD_H
    # The rule absorbs the difference; nothing else moves relative to the right.
    assert b.rule.width() - narrow.rule.width() == 400


def test_a_section_without_a_toggle_leaves_no_gap_where_it_was(wide):
    """Movies/Series/Live get no control, and the rule grows into the space."""
    with_toggle = _lay(wide, has_toggle=True)
    without = _lay(wide, has_toggle=False)

    assert without.all_seg.isNull() and without.word_seg.isNull()
    assert without.rule.width() > with_toggle.rule.width(), (
        "the rule must reclaim the control's space, not leave a hole")
    assert without.caret.right() == with_toggle.caret.right()


def test_the_two_halves_are_adjacent_and_equal_height(wide):
    """One pill with a divide, not two buttons."""
    b = _lay(wide)
    assert b.all_seg.right() == b.word_seg.left(), "a gap between the halves"
    assert b.all_seg.height() == b.word_seg.height()
    assert b.all_seg.center().y() == b.word_seg.center().y() == b.caret.center().y()


def test_a_longer_count_does_not_push_anything_off_the_edge(wide):
    """785,551 is a real number this list shows."""
    b = _lay(wide, count=785551)
    assert b.count.left() > b.label.right(), "the count collided with the label"
    assert b.caret.right() < wide.right()
    assert not b.rule.isNull()


def test_a_narrow_band_drops_the_rule_rather_than_inverting_it(qapp):
    """Better no rule than a negative-width one painted over the label."""
    b = _lay(QRect(0, 0, 150, band.band_height(QFont())))
    assert b.rule.isNull() or b.rule.width() >= 0
