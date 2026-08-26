"""The V3 sidebar SECTION style: cards, small-caps group headings, row budget.

#329 and #447 shipped the sidebar's ALLOCATION — no nested scrollbars, content
aware minimums, the news boost, ``+N more``. What they did not touch is what the
render actually looks like, and the owner's note was direct: a complete
implementation of the new side panel style is still owed.

The ROW half of that style (two lines, the quiet second line, the meta-line
composition) is pinned in ``tests/test_chip_row.py``, next to the builder it
describes. This file covers the section around the rows:

* each section is a rounded CARD that stands off the ground behind it, rather
  than a run of flat rows distinguished only by a tinted header strip;
* sub-group headings are small-caps and muted — a divider, not another title
  competing with the rows it separates — from ONE styler, in every section;
* the taller two-line row is accounted for by the allocation maths, and a
  section never renders "+N more" over nothing.
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem

from metatv.gui import theme as _theme
from metatv.gui import theme_palettes as tp
from metatv.gui.chip_row import build_chip_row


def _lum(c: QColor) -> float:
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def _contrast(a: QColor, b: QColor) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ── The section card ─────────────────────────────────────────────────────────

@pytest.fixture()
def section(qapp, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.sidebar.base import CollapsibleSection
    sec = CollapsibleSection("History", "H", Config(config_dir=tmp_path))
    sec.resize(260, 200)
    sec.show()
    qapp.processEvents()
    yield sec
    sec.hide()


@pytest.mark.parametrize("palette_name", list(tp.PALETTES))
def test_the_section_PAINTS_a_card_distinct_from_the_sidebar_ground(
    qapp, tmp_path, palette_name
):
    """Sampled pixels, not the tokens the sheet mentions.

    A style constant can name COLOR_BG_CARD and still paint nothing — the frame
    needs WA_StyledBackground and an object-name-scoped rule to land on the
    frame rather than every QFrame inside it. Grabbing the widget is the only
    check that covers all three at once.
    """
    from metatv.core.config import Config
    from metatv.gui.sidebar.base import CollapsibleSection

    before = _theme.current_theme()
    try:
        _theme.apply_theme(palette_name)
        sec = CollapsibleSection("History", "H", Config(config_dir=tmp_path))
        sec.resize(260, 200)
        sec.show()
        qapp.processEvents()

        img = sec.grab().toImage()
        # A point inside the card body, clear of the header strip and the border.
        painted = img.pixelColor(img.width() // 2, img.height() - 8)
        card = QColor(_theme.COLOR_BG_CARD)
        ground = QColor(_theme.COLOR_BG_DEEP)

        # It paints the CARD token — not merely "something other than the ground",
        # which an unstyled frame falling through to the QPalette also satisfies.
        assert painted == card, (
            f"{palette_name}: the section body painted {painted.name()}, not the "
            f"card token {card.name()}"
        )
        assert _contrast(card, ground) >= 1.05, (
            f"{palette_name}: card {card.name()} vs sidebar ground {ground.name()} "
            f"is {_contrast(card, ground):.3f}:1 — indistinguishable, so a card "
            f"boundary is invisible in this palette"
        )
        sec.hide()
    finally:
        _theme.apply_theme(before)


def test_the_card_is_scoped_to_the_section_frame_only(section):
    """Wired, not merely defined — the failure mode that shipped twice.

    Object-name scoping matters for more than tidiness: an unscoped
    ``background`` on a widget with children cascades onto every QFrame inside
    the section.
    """
    assert section.objectName() == "sidebarSection"
    assert "QFrame#sidebarSection" in section.styleSheet()


def test_cards_are_separated_by_a_gap(qapp, tmp_path):
    """Cards that touch read as one long panel with lines drawn on it."""
    from unittest.mock import MagicMock, patch
    from metatv.core.config import Config
    import metatv.gui.main_window as mw

    with patch.object(mw, "QSplitter") as fake_splitter:
        fake_splitter.return_value = MagicMock()
        host = mw.MainWindow.__new__(mw.MainWindow)
        host.config = Config(config_dir=tmp_path)
        try:
            mw.MainWindow.create_sidebar(host)
        except Exception:
            pass  # only the handle width is under test; the rest needs a real window
        calls = fake_splitter.return_value.setHandleWidth.call_args_list

    assert calls, "the sidebar splitter never set a handle width — cards will touch"
    assert calls[0].args[0] >= 4, (
        f"the gap between section cards is {calls[0].args[0]}px — not a separation"
    )


# ── Group headings ───────────────────────────────────────────────────────────

def test_the_group_heading_styler_renders_caps_without_changing_the_text(qapp):
    """Capitalisation is a FONT property here, deliberately.

    Uppercasing the string would change ``item.text()``, and the Watch Queue's
    headings carry live filter counts ("Never Watched (2 of 3)") that the
    section and its tests read back. A purely visual choice must stay purely
    visual.
    """
    from metatv.gui.sidebar.base import style_group_heading

    item = QListWidgetItem("Never Watched (2 of 3)")
    style_group_heading(item)

    assert item.text() == "Never Watched (2 of 3)", "the styler rewrote the text"
    assert item.font().capitalization() == QFont.Capitalization.AllUppercase
    assert item.foreground().color() == QColor(_theme.COLOR_MUTED)
    assert item.font().pixelSize() == int(_theme.FONT_SM.replace("px", "")), (
        "a group heading must be smaller than the titles it separates"
    )


def test_the_styler_handles_a_tree_item_too(qapp):
    """Watch Alerts is a QTreeWidget; its setters take a column."""
    from metatv.gui.sidebar.base import style_group_heading

    tree = QTreeWidget()
    item = QTreeWidgetItem(["EPG"])
    tree.addTopLevelItem(item)
    style_group_heading(item, column=0)

    assert item.font(0).capitalization() == QFont.Capitalization.AllUppercase
    assert item.foreground(0).color() == QColor(_theme.COLOR_MUTED)


@pytest.mark.parametrize("module", ["queue", "favorites", "alerts"])
def test_every_section_with_group_headings_uses_the_one_styler(module):
    """Three sections had each grown their own copy of the same wrong lines.

    Asserted on the source because the alternative — constructing all three
    sections against a DB — tests the sections, not the thing that drifted.
    """
    import pathlib

    src = pathlib.Path(f"metatv/gui/sidebar/{module}.py").read_text()
    # Either shared styler: style_group_heading() paints an ITEM, GroupHeading
    # is the WIDGET that replaced it where a heading needs two tones (a muted
    # label beside a bright count), which an item cannot express.
    assert ("style_group_heading(" in src) or ("GroupHeading(" in src), (
        f"{module}.py styles a group heading by hand"
    )
    assert "setBold(True)" not in src, (
        f"{module}.py still hand-rolls a heading font — that is the drift"
    )


# ── The taller row, and the allocation that has to know about it ─────────────

def test_content_row_height_matches_a_real_two_line_row(qapp):
    """The constant is a stated fact about a widget — keep them together.

    ``min_expanded_height()`` multiplies this by MIN_ROWS, so a stale value
    silently under- or over-allocates every section.
    """
    from metatv.gui.sidebar.base import CollapsibleSection

    from metatv.gui.chip_row import DENSITY_COMFORTABLE
    real = build_chip_row(
        title="Star Trek: Deep Space Nine", meta="S03E11 · 1993 · EN",
        density=DENSITY_COMFORTABLE,
    ).sizeHint().height()
    assert CollapsibleSection.CONTENT_ROW_H >= real, (
        f"CONTENT_ROW_H is {CollapsibleSection.CONTENT_ROW_H} but a real row is "
        f"{real}px — sections will allocate too little"
    )
    assert CollapsibleSection.CONTENT_ROW_H <= real + 6, (
        f"CONTENT_ROW_H is {CollapsibleSection.CONTENT_ROW_H} against a real "
        f"{real}px row — sections will hoard height they never use"
    )


def test_min_expanded_height_is_derived_from_the_content_row(qapp, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.sidebar.base import CollapsibleSection

    sec = CollapsibleSection("History", "H", Config(config_dir=tmp_path))
    assert sec.min_expanded_height() >= (
        sec.HEADER_H + sec.MIN_ROWS * sec.CONTENT_ROW_H
    ), "a section's floor no longer fits MIN_ROWS of the row it actually renders"


def test_a_section_never_shows_a_more_marker_over_an_empty_list(qapp, tmp_path):
    """"+ 6 more →" with nothing above it reads as a broken section, not a full one.

    Reachable whenever ONE row does not leave room for the tail as well — which
    the two-line row, at nearly twice the height it replaced, made ordinary.
    """
    from metatv.core.config import Config
    from metatv.gui.sidebar.base import CollapsibleSection
    from metatv.gui.sidebar.row_budget import _MORE_ROLE, _MORE_ROW

    sec = CollapsibleSection("History", "H", Config(config_dir=tmp_path))
    lst = QListWidget()
    for i in range(6):
        item = QListWidgetItem()
        row = build_chip_row(title=f"Title {i}", meta="Movie · 1999 · EN")
        item.setSizeHint(row.sizeHint())
        lst.addItem(item)
        lst.setItemWidget(item, row)
    # A viewport with room for exactly one row and nothing more.
    lst.resize(260, sec.CONTENT_ROW_H + 4)
    lst.show()
    qapp.processEvents()

    sec.apply_row_budget(lst, on_more=lambda: None)

    visible = [
        lst.item(i) for i in range(lst.count())
        if not lst.item(i).isHidden() and lst.item(i).data(_MORE_ROLE) != _MORE_ROW
    ]
    assert visible, (
        "the section hid every content row and kept only the '+N more' marker"
    )
    lst.hide()
