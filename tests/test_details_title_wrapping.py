"""A long details-pane title must not be clipped (#283).

Owner, on "Monty Python's The Meaning of Life": "this title is totally crushed
in the layout" — the title wrapped to three lines but only ~two lines' worth of
height was allocated, so the first and last lines were cut off.

The title label carries a horizontal size policy of ``Ignored`` on purpose: its
sizeHint would otherwise widen the whole details column, a trap that has
recurred about five times (docs/DETAILS_PANE_DESIGN.md). But an ignored width
also leaves Qt with no width to wrap against when computing height, so the
allocated height was for fewer lines than actually render.

``setHeightForWidth(True)`` makes the layout ask the label how tall it needs to
be at the width it is actually given — keeping the ignored width AND getting a
correct height.

Asserts RENDERED geometry (CLAUDE.md: UI slices assert appearance), not that a
flag is set: a policy that is configured but not consulted still clips.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _title_section(qapp):
    from metatv.core.config import Config
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(Config())
    section.resize(320, 400)          # narrow enough to force wrapping
    section.show()
    QApplication.processEvents()
    return section


LONG = "Monty Python's The Meaning of Life"
SHORT = "Fury"


def test_height_for_width_is_enabled(qapp):
    """The mechanism — without it Qt cannot compute a wrapped height at all."""
    section = _title_section(qapp)
    assert section.title_label.sizePolicy().hasHeightForWidth()


def test_a_wrapping_title_gets_room_for_every_line(qapp):
    """The owner's case, measured.

    Compares the height the label needs at its actual width against the height
    it is given. Short of that, a clipped title still "passes" any check that
    only looks at the text.
    """
    section = _title_section(qapp)
    label = section.title_label
    label.setText(LONG)
    QApplication.processEvents()

    width = label.width()
    needed = label.heightForWidth(width)

    assert needed > 0, "heightForWidth returned nothing — wrapping not computed"
    assert label.height() >= needed, (
        f"title is {label.height()}px tall but needs {needed}px at {width}px "
        f"wide — the top and bottom lines are cut off"
    )


def test_it_actually_wraps_to_more_than_one_line(qapp):
    """Guard the guard: if the fixture is too wide to wrap, the test above
    proves nothing."""
    section = _title_section(qapp)
    label = section.title_label
    label.setText(LONG)
    QApplication.processEvents()

    one_line = label.fontMetrics().height()
    assert label.heightForWidth(label.width()) > one_line * 1.5, (
        "the fixture is not narrow enough to force wrapping, so the clipping "
        "test cannot fail"
    )


def test_a_short_title_is_not_given_extra_height(qapp):
    """No over-correction — a one-line title must stay one line tall."""
    section = _title_section(qapp)
    label = section.title_label
    label.setText(SHORT)
    QApplication.processEvents()

    one_line = label.fontMetrics().height()
    assert label.heightForWidth(label.width()) <= one_line * 1.6


def test_the_column_is_not_widened_by_a_long_title(qapp):
    """The trap this policy exists to avoid, kept closed.

    An Ignored horizontal policy means the label never reports a width hint —
    fixing the height must not accidentally reintroduce one.
    """
    from PyQt6.QtWidgets import QSizePolicy

    section = _title_section(qapp)
    assert (
        section.title_label.sizePolicy().horizontalPolicy()
        == QSizePolicy.Policy.Ignored
    ), "the title would widen the whole details column again"
