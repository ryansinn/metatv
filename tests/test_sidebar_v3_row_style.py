"""The V3 sidebar: two-line rows, section cards, small-caps group headings.

#329 and #447 shipped the sidebar's ALLOCATION — no nested scrollbars, content
aware minimums, the news boost, `+N more`. What they did not touch is what the
render actually looks like, and the owner's note was direct: a complete
implementation of the new side panel style is still owed.

This covers the style half:

* rows are TWO lines — the identifying title on top, the circumstantial detail
  (year, language, episode) underneath in a quieter colour, so a glance reads
  titles and a second look reads state;
* each section is a rounded CARD with a gap to its neighbour, rather than a run
  of flat rows distinguished only by a tinted header strip;
* sub-group headings are small-caps and muted — a divider, not another title
  competing with the rows it separates.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel

from metatv.gui import theme as _theme
from metatv.gui import theme_palettes as tp
from metatv.gui.chip_row import build_chip_row, sidebar_meta_line


# ── The meta line ────────────────────────────────────────────────────────────

def test_the_meta_line_drops_missing_parts_without_a_dangling_separator():
    """The whole reason it is a function and not four f-strings."""
    assert sidebar_meta_line("1984", "EN") == "1984 · EN"
    assert sidebar_meta_line(None, "EN") == "EN"
    assert sidebar_meta_line("1984", "") == "1984"
    assert sidebar_meta_line("", None) == ""


def test_every_sidebar_section_composes_its_meta_line_through_the_builder():
    """Four sections, one separator convention — or they drift."""
    import pathlib

    for name in ("history", "queue", "favorites", "recommended"):
        src = pathlib.Path(f"metatv/gui/sidebar/{name}.py").read_text()
        assert "sidebar_meta_line(" in src, (
            f"{name}.py builds a row without the shared meta-line builder"
        )


# ── The row ──────────────────────────────────────────────────────────────────

def test_a_row_with_a_meta_line_is_two_lines_tall(qapp):
    one = build_chip_row(media_icon="🎬", title="Silicon Valley")
    two = build_chip_row(media_icon="🎬", title="Silicon Valley", meta="2014 · EN")
    assert two.sizeHint().height() > one.sizeHint().height(), (
        "the meta line did not add a second line"
    )


def test_a_row_without_a_meta_line_is_unchanged(qapp):
    """Callers with nothing to say on a second line must not grow one."""
    row = build_chip_row(media_icon="🎬", title="Plain", year="1984", prefix="EN")
    texts = {w.text() for w in row.findChildren(QLabel)}
    assert "1984" in texts and "EN" in texts, "the legacy chip row lost its chips"


def test_the_meta_text_is_actually_rendered(qapp):
    """Not just accepted as a parameter."""
    row = build_chip_row(media_icon="🎬", title="Silicon Valley", meta="2014 · EN")
    assert any(w.text() == "2014 · EN" for w in row.findChildren(QLabel))


def test_the_meta_line_sits_UNDER_the_title_not_beside_it(qapp):
    """Rendered geometry. "There is a meta label" is not "it is a second line"."""
    row = build_chip_row(media_icon="🎬", title="Silicon Valley", meta="2014 · EN")
    row.resize(300, row.sizeHint().height())
    row.show()
    qapp.processEvents()

    title = next(w for w in row.findChildren(QLabel) if w.text() == "Silicon Valley")
    meta = next(w for w in row.findChildren(QLabel) if w.text() == "2014 · EN")
    t = title.mapTo(row, title.rect().bottomLeft()).y()
    m = meta.mapTo(row, meta.rect().topLeft()).y()
    assert m >= t - 2, (
        f"the meta line starts at y={m} while the title runs to y={t} — they are "
        f"side by side, not stacked"
    )


def test_the_meta_line_is_quieter_than_the_title_but_still_legible(qapp):
    """Both halves. Quiet enough to subordinate, legible enough to read."""
    def lum(v):
        h = v.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))

        def ch(x):
            x /= 255
            return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)

    def contrast(a, b):
        lo, hi = sorted((lum(a), lum(b)))
        return (hi + 0.05) / (lo + 0.05)

    import re

    for name in tp.PALETTES:
        _theme.apply_theme(name)
        surface = _theme.COLOR_BG_CARD
        # Read the colour off the ROLE, not off the palette token I expect it to
        # use. Measuring COLOR_TEXT directly proves nothing about what
        # SIDEBAR_ROW_META actually paints — a mutation swapping the role to
        # COLOR_TEXT_HI passed this test until it read the role instead.
        found = re.search(r"color:\s*(#[0-9a-fA-F]{3,8})", _theme.SIDEBAR_ROW_META)
        assert found, "SIDEBAR_ROW_META sets no explicit colour"
        meta = contrast(found.group(1), surface)
        title = contrast(_theme.COLOR_TEXT_HI, surface)
        assert meta >= 4.5, f"{name}: the meta line is {meta:.2f}:1 on the card"
        assert meta < title, (
            f"{name}: the meta line ({meta:.2f}:1) is as loud as the title "
            f"({title:.2f}:1) — it is meant to subordinate"
        )


# ── The section card ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("palette_name", list(tp.PALETTES))
def test_the_section_card_stands_off_its_surroundings(qapp, palette_name):
    """A card that matches the ground behind it is not a card."""
    _theme.apply_theme(palette_name)
    assert "sidebarSection" in _theme.SIDEBAR_SECTION_CARD, (
        "the card style is not object-name scoped — it will paint every QFrame "
        "inside the section too"
    )
    assert _theme.COLOR_BG_CARD in _theme.SIDEBAR_SECTION_CARD
    assert "border-radius" in _theme.SIDEBAR_SECTION_CARD


def test_the_section_is_actually_wearing_the_card(qapp, tmp_path):
    """Wired, not merely defined — the failure mode that shipped twice."""
    from metatv.core.config import Config
    from metatv.gui.sidebar.base import CollapsibleSection

    section = CollapsibleSection("History", "H", Config(config_dir=tmp_path))
    assert section.objectName() == "sidebarSection"
    assert "sidebarSection" in section.styleSheet()
