"""The details header: a title with room to be a title.

The title row was ``[title ···] [prefix chip] [quality chip] [year]``. The title
is the only child of that row that can shrink, so every badge took its width
first and the title wrapped around whatever was left — the owner's report was a
long title "scrunched due to the badges/chips".

These assert RENDERED GEOMETRY. "The chips are no longer children of the title
row" is satisfied by a layout that still leaves the title 40px wide.

DETAILS-3b removed the prefix/quality chips from this section entirely (quality
now lives on the "Available in" copy chips, a parallel slice) — the tests that
asserted their geometry went with them; the title/byline geometry tests below
are unaffected since nothing shares either row.
"""

from __future__ import annotations

import pytest

from metatv.gui.details_title import _MetadataSection


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


