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


LONG = "Monty Python's The Meaning of Life"
SHORT = "Fury"


def _title_section(qapp, text: str = LONG, lines: int = 3):
    """Build the section sized so *text* wraps to about *lines* lines.

    The width is derived from the FONT's own measurement of *text* rather than
    hardcoded. A fixed 320px assumed the platform font this was written on:
    the same string rendered narrower on the macOS CI runner, fitted on one
    line, and the wrap assertions failed there while passing locally — which
    blocked two rolling releases from ever reaching the tester. Anything
    font-metric-dependent has to be expressed relative to the metrics.
    """
    from metatv.core.config import Config
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(Config())
    section.show()
    QApplication.processEvents()

    advance = section.title_label.fontMetrics().horizontalAdvance(text)
    section.resize(max(80, advance // lines), 400)
    section.title_label.setText(text)
    QApplication.processEvents()
    return section


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

    # Font-independent: the SAME label, measured at a width a third of the
    # text's own single-line advance, must need more height than at a width
    # comfortably wider than it. No ratio against a line height, which varies
    # by platform font.
    advance = label.fontMetrics().horizontalAdvance(LONG)
    wrapped = label.heightForWidth(max(80, advance // 3))
    unwrapped = label.heightForWidth(advance + 40)

    assert wrapped > unwrapped, (
        f"the label reports the same height ({wrapped}px) whether or not it "
        f"has room for one line — it is not wrapping, so the clipping test "
        f"above cannot fail"
    )


def test_a_short_title_is_not_given_extra_height(qapp):
    """No over-correction — a one-line title must stay one line tall.

    Measured at a width that comfortably fits the text (derived from the font,
    not assumed), so this asserts "does not wrap when it has room" rather than
    "is under N pixels".
    """
    section = _title_section(qapp, SHORT, lines=1)
    label = section.title_label

    roomy = label.fontMetrics().horizontalAdvance(SHORT) + 40
    one_line = label.fontMetrics().height()

    assert label.heightForWidth(roomy) <= one_line * 1.6


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
