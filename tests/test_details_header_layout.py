"""The details header: a title with room to be a title.

The title row was ``[title ···] [prefix chip] [quality chip] [year]``. The title
is the only child of that row that can shrink, so every badge took its width
first and the title wrapped around whatever was left — the owner's report was a
long title "scrunched due to the badges/chips".

These assert RENDERED GEOMETRY. "The chips are no longer children of the title
row" is satisfied by a layout that still leaves the title 40px wide.
"""

from __future__ import annotations

import pytest

from metatv.gui.details_sections import _MetadataSection


class _Ch:
    raw_data = None
    category = None
    is_favorite = False
    provider_id = "p1"
    id = "p1_1"

    def __init__(self, title, year="2024", prefix="EN", quality="4k", kind="movie"):
        self.name = title
        self.detected_title = title
        self.detected_year = year
        self.detected_prefix = prefix
        self.detected_quality = quality
        self.media_type = kind


@pytest.fixture
def section(qapp, tmp_path):
    from metatv.core.config import Config

    sec = _MetadataSection(Config(config_dir=tmp_path))
    sec.resize(460, 300)
    sec.show()
    qapp.processEvents()
    return sec


LONG = "Monty Python's The Meaning of Life"


def test_the_title_gets_the_whole_row(section, qapp):
    """The defect, measured.

    With the badges back on this row the title was allocated what they left
    over. Now nothing shares the row, so it gets essentially all of it.
    """
    section.load_basic(_Ch(LONG))
    qapp.processEvents()

    title = section.title_label
    row = title.parent()
    assert title.width() >= row.width() - 2, (
        f"the title is {title.width()}px inside a {row.width()}px row — "
        f"something is still sharing it"
    )


def test_the_badges_are_not_in_the_title_row(section, qapp):
    section.load_basic(_Ch(LONG))
    qapp.processEvents()
    row = section.title_label.parent()
    for chip in (section._prefix_chip, section._quality_chip):
        assert chip.parent() is not row, f"{chip.text()!r} is still in the title row"


def test_a_long_title_takes_fewer_lines_than_the_badges_forced(section, qapp):
    """The user-visible symptom: line count.

    At 460px this title needs two lines. Sharing the row with a resolved
    prefix chip ("English (EN)") and a quality chip took enough width to push
    it past that.
    """
    section.load_basic(_Ch(LONG))
    qapp.processEvents()

    title = section.title_label
    line_h = title.fontMetrics().lineSpacing()
    lines = round(title.height() / line_h)
    assert lines <= 2, f"the title still wraps to {lines} lines at {title.width()}px"


def test_the_byline_says_kind_and_year(section, qapp):
    section.load_basic(_Ch("Kraven The Hunter"))
    qapp.processEvents()
    assert section._byline_lbl.text() == "Movie · 2024"
    assert not section._byline_lbl.isHidden()


def test_the_byline_sits_directly_under_the_title(section, qapp):
    """Rendered position — it is one block, not two things that happen to exist."""
    section.load_basic(_Ch("Kraven The Hunter"))
    qapp.processEvents()

    title = section.title_label
    byline = section._byline_lbl
    title_bottom = title.mapTo(section, title.rect().bottomLeft()).y()
    byline_top = byline.mapTo(section, byline.rect().topLeft()).y()

    assert byline_top >= title_bottom - 2, "the byline overlaps the title"
    assert byline_top - title_bottom < title.fontMetrics().lineSpacing(), (
        "the byline is more than a line away from the title — not one block"
    )


def test_the_badges_still_render_somewhere(section, qapp):
    """Moved, not deleted. Quality and region are real information."""
    section.load_basic(_Ch("Kraven The Hunter"))
    qapp.processEvents()
    assert section._prefix_chip.text() == "English (EN)"
    assert section._quality_chip.text() == "4K"
    assert not section._prefix_chip.isHidden()
    assert not section._quality_chip.isHidden()


def test_the_badge_row_never_floors_the_pane_wider_than_it_is(section, qapp):
    """The width trap, which a plain QHBoxLayout on this row would reintroduce.

    A QHBoxLayout's minimum width is the SUM of its children, so a long region
    name plus a quality plus "Source: …" would push the whole details column
    past its viewport — the failure docs/DETAILS_PANE_DESIGN.md records
    recurring about five times. A flow layout's minimum is its widest single
    child.
    """
    section.load_basic(_Ch(LONG, prefix="LAT", quality="uhd"))
    qapp.processEvents()
    layout = section._badge_row_w.layout()
    widths = [layout.itemAt(i).widget().sizeHint().width()
              for i in range(layout.count())]
    minimum = section._badge_row_w.minimumSizeHint().width()

    assert minimum < sum(widths), (
        f"the badge row's minimum ({minimum}px) is the SUM of its children "
        f"({sum(widths)}px) — it will floor the details pane wider than its "
        f"viewport. This row must stay a flow layout."
    )
    # Margins and spacing put it a little over the widest child; what matters
    # is that it tracks the widest rather than the total.
    assert minimum <= max(widths) + 32, (
        f"minimum {minimum}px is well past the widest child {max(widths)}px"
    )
