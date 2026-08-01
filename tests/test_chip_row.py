"""Shared sidebar chip-row builder (metatv/gui/chip_row.py).

``build_chip_row`` is the one canonical row used by Recommended, Watch Queue,
Favorites and History: ``[icon] Title [4K] … [Year] [Lang]``.  These tests pin
the contract every section relies on:

  * the title renders (as the anti-clip ``MiddleElideLabel``);
  * the language chip is the honest ``prefix`` (never a region), and only when set;
  * the quality and year chips appear only when their value is non-empty;
  * layout order is title → quality → [stretch] → year → language, with the
    language chip the consistent far-right element;
  * the row is mouse-transparent (the hosting item owns clicks).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.gui import theme as _theme
from metatv.gui.chip_row import MiddleElideLabel, build_chip_row


def _row(**over):
    base = dict(
        media_icon="📺", title="Cowboy Bebop", year="1998", quality="4K", prefix="EN",
    )
    base.update(over)
    return build_chip_row(**base)


def _texts(row):
    widgets = row.findChildren(QLabel) + row.findChildren(QPushButton)
    return [w.text() for w in widgets]


def _ordered_items(row):
    """(kind, obj) per layout item in order — kind is 'w' (widget) or 'spacer'."""
    layout = row.layout()
    out = []
    for i in range(layout.count()):
        it = layout.itemAt(i)
        if it.widget() is not None:
            out.append(("w", it.widget()))
        elif it.spacerItem() is not None:
            out.append(("spacer", it.spacerItem()))
    return out


def _widget_index(items, pred):
    return next(i for i, (k, obj) in enumerate(items) if k == "w" and pred(obj))


def _spacer_index(items):
    return next(i for i, (k, _obj) in enumerate(items) if k == "spacer")


def test_title_present_as_middle_elide_label(qtbot):
    row = _row()
    title = row.findChild(MiddleElideLabel)
    assert title is not None, "title renders as the anti-clip MiddleElideLabel"
    assert title.text() == "Cowboy Bebop"


def test_language_chip_from_prefix_not_region(qtbot):
    # The language chip is the honest prefix (EN); nothing renders a region token.
    row = _row(prefix="EN")
    assert "EN" in _texts(row)
    lang_chips = [
        w for w in row.findChildren(QLabel)
        if w.text() == "EN" and w.styleSheet() == _theme.LANG_CHIP
    ]
    assert lang_chips, "language renders as its own LANG_CHIP-styled chip"


def test_no_language_chip_when_prefix_empty(qtbot):
    row = _row(prefix="")
    assert not any(
        w.styleSheet() == _theme.LANG_CHIP for w in row.findChildren(QLabel)
    ), "no LANG_CHIP when prefix is empty"


def test_quality_chip_is_a_button_only_when_set(qtbot):
    # QUALITY_CHIP is QPushButton-scoped — the quality chip must be a QPushButton.
    row = _row(quality="4K")
    assert any(b.text() == "4K" for b in row.findChildren(QPushButton))
    # ...and absent entirely when quality is empty.
    bare = _row(quality="")
    assert not any(b.text() == "4K" for b in bare.findChildren(QPushButton))


def test_year_chip_only_when_set(qtbot):
    row = _row(year="1998")
    year_chips = [
        w for w in row.findChildren(QLabel)
        if w.text() == "1998" and w.styleSheet() == _theme.YEAR_CHIP
    ]
    assert year_chips, "year renders as its own YEAR_CHIP-styled chip"
    bare = _row(year="")
    assert not any(w.styleSheet() == _theme.YEAR_CHIP for w in bare.findChildren(QLabel))


def test_layout_order_title_quality_stretch_year_language(qtbot):
    row = _row()
    items = _ordered_items(row)
    title_i = _widget_index(items, lambda w: isinstance(w, MiddleElideLabel))
    quality_i = _widget_index(items, lambda w: isinstance(w, QPushButton) and w.text() == "4K")
    year_i = _widget_index(items, lambda w: isinstance(w, QLabel) and w.text() == "1998")
    lang_i = _widget_index(items, lambda w: isinstance(w, QLabel) and w.text() == "EN")
    spacer_i = _spacer_index(items)
    assert title_i < quality_i < spacer_i < year_i < lang_i


def test_language_chip_is_the_far_right_element(qtbot):
    # Even without a year, the language chip is the last widget in the row.
    row = _row(year="")
    items = _ordered_items(row)
    widget_items = [obj for k, obj in items if k == "w"]
    last = widget_items[-1]
    assert isinstance(last, QLabel) and last.text() == "EN"


def test_row_is_mouse_transparent(qtbot):
    row = _row()
    assert row.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_liked_prefixes_the_icon_with_the_like_glyph(qtbot):
    from metatv.gui import icons as _icons
    liked_row = _row(liked=True, media_icon="🎬")
    qtbot.addWidget(liked_row)
    # The first widget is the icon label; the like glyph precedes the media icon.
    liked_icon = _ordered_items(liked_row)[0][1]
    assert _icons.like_icon in liked_icon.text()

    plain_row = build_chip_row(media_icon="🎬", title="x")
    qtbot.addWidget(plain_row)
    plain_icon = _ordered_items(plain_row)[0][1]
    assert _icons.like_icon not in plain_icon.text(), "no like glyph when liked is False"
