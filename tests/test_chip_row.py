"""Shared sidebar row builder (metatv/gui/chip_row.py).

``build_chip_row`` is the one canonical row used by Recommended, Watch Queue,
Favorites and History. V3 changed its shape from a single line carrying chips
(``[icon] Title [4K] … [Year] [Lang]``) to two lines of text — the title, and
underneath it the circumstantial detail. These tests pin the contract every
section relies on:

  * the title renders as the anti-clip ``MiddleElideLabel`` and is reachable
    UNAMBIGUOUSLY (``findChild`` returns the wrong label — see the test);
  * a row with no ``meta`` stays single-line;
  * a row with ``meta`` renders the second line BELOW the first and DIMMER —
    asserted on painted geometry and sampled pixels, not on the tokens the
    sheet mentions;
  * the row is mouse-transparent (the hosting item owns clicks).
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel

from metatv.gui import theme as _theme
from metatv.gui.chip_row import (
    MiddleElideLabel,
    build_chip_row,
    episode_code,
    media_icon_role,
    row_meta_label,
    row_title_label,
    sidebar_meta_line,
)

_META = "Movie · 1998 · EN"


def _row(**over):
    base = dict(title="Cowboy Bebop", meta=_META)
    base.update(over)
    return build_chip_row(**base)


def _ordered_items(row):
    """(kind, obj) per item of the row's TITLE line, in order."""
    title = row_title_label(row)
    layout = title.parentWidget().layout()
    out = []
    for i in range(layout.count()):
        it = layout.itemAt(i)
        if it.widget() is not None:
            out.append(("w", it.widget()))
        elif it.spacerItem() is not None:
            out.append(("spacer", it.spacerItem()))
    return out


def _relative_luminance(c: QColor) -> float:
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def _contrast(a: QColor, b: QColor) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ── The lookups ──────────────────────────────────────────────────────────────

def test_title_present_as_middle_elide_label(qtbot):
    row = _row()
    title = row_title_label(row)
    assert title is not None, "title renders as the anti-clip MiddleElideLabel"
    assert title.text() == "Cowboy Bebop"


def test_find_child_alone_returns_the_WRONG_label(qtbot):
    """Why ``row_title_label`` exists at all — do not "simplify" it away.

    Qt searches direct children before recursing, and on a two-line row the
    meta label is a direct child while the title is one level deeper inside the
    title line. So the obvious ``findChild(MiddleElideLabel)`` silently returns
    the META line. Seven call sites had exactly that shape when the second line
    landed, and every one of them started reading "1982 · UK" for the title.
    """
    row = _row()
    assert row.findChild(MiddleElideLabel) is row_meta_label(row)
    assert row_title_label(row) is not row_meta_label(row)
    assert row_title_label(row).text() == "Cowboy Bebop"
    assert row_meta_label(row).text() == _META


# ── One line vs two ──────────────────────────────────────────────────────────

def test_no_meta_means_no_second_line(qtbot):
    row = build_chip_row(title="Cowboy Bebop")
    assert row_meta_label(row) is None
    assert row_title_label(row) is not None


def test_meta_line_is_painted_BELOW_the_title(qtbot):
    """Geometry, not layout class: the second line must actually be under it."""
    row = _row()
    qtbot.addWidget(row)
    row.resize(260, row.sizeHint().height())
    row.show()
    qtbot.waitExposed(row)

    title, meta = row_title_label(row), row_meta_label(row)
    t = title.mapTo(row, title.rect().topLeft())
    m = meta.mapTo(row, meta.rect().topLeft())
    assert m.y() >= t.y() + title.height(), (
        f"meta line is not below the title: title y={t.y()} h={title.height()}, "
        f"meta y={m.y()} — a side-by-side layout would pass an ordering check"
    )
    assert abs(m.x() - t.x()) <= 2, "the two lines must share a left edge"


def test_two_line_row_is_taller_than_one_line(qtbot):
    one = build_chip_row(title="Cowboy Bebop").sizeHint().height()
    two = _row().sizeHint().height()
    assert two > one + 8, f"second line added no height: {one} -> {two}"


# ── The visual hierarchy ─────────────────────────────────────────────────────

@pytest.mark.parametrize("palette", ["Midnight", "Graphite", "Daylight",
                                     "Gruvbox", "Gruvbox Light"])
def test_meta_is_dimmer_than_the_title_and_both_stay_legible(qtbot, palette):
    """The hierarchy IS the design — and it must survive every palette.

    Asserted on the colour each label actually PAINTS, which is not the
    stylesheet's: ``MiddleElideLabel`` overrides ``paintEvent`` and never reads
    a sheet's ``color:``. Both lines styled from the same token rendered
    identically while the roles claimed a hierarchy that did not exist.
    """
    before = _theme.current_theme()
    try:
        _theme.apply_theme(palette)
        row = _row()
        qtbot.addWidget(row)
        title_c = row_title_label(row).pen_color()
        meta_c = row_meta_label(row).pen_color()
        card = QColor(_theme.COLOR_BG_CARD)

        assert title_c != meta_c, f"{palette}: both lines paint the same colour"
        assert _contrast(title_c, card) > _contrast(meta_c, card), (
            f"{palette}: the meta line is not quieter than the title"
        )
        assert _contrast(meta_c, card) >= 4.5, (
            f"{palette}: meta line at {_contrast(meta_c, card):.2f}:1 on the card "
            f"— quiet is not the same as unreadable"
        )
    finally:
        _theme.apply_theme(before)


def test_meta_label_actually_paints_its_token(qtbot):
    """Sampled pixels: the painted text really is the meta colour.

    A ``color_token`` that is stored and never used would pass every check
    above; this one grabs the label and looks for its ink.
    """
    row = _row()
    qtbot.addWidget(row)
    row.resize(260, row.sizeHint().height())
    row.show()
    qtbot.waitExposed(row)

    meta = row_meta_label(row)
    img = meta.grab().toImage()
    want = meta.pen_color()
    hits = sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if _contrast(img.pixelColor(x, y), want) < 1.35
    )
    assert hits > 5, "the meta line drew no ink in its own colour"


# ── Composition helpers ──────────────────────────────────────────────────────

def test_meta_line_drops_missing_parts_without_dangling_separators():
    assert sidebar_meta_line("Movie", "1985", "EN") == "Movie · 1985 · EN"
    assert sidebar_meta_line("", "1985", None) == "1985"
    assert sidebar_meta_line(None, "", None) == ""
    assert sidebar_meta_line("3 days ago") == "3 days ago"


def test_media_icon_role_is_a_glyph_role_not_a_word():
    """This used to assert the WORD ("Movie"). The owner: "the whole point of
    the movie, series, live icons reduce the need for all this busy and
    repetitive text. So rather than using the words, use the icons.""""
    assert media_icon_role("movie") == "movie"
    assert media_icon_role("series") == "series"
    assert media_icon_role("live") == "live"
    assert media_icon_role("") == ""
    assert media_icon_role(None) == ""
    assert media_icon_role("nonsense") == ""


def test_episode_code_needs_both_halves():
    assert episode_code(5, 3) == "S05E03"
    assert episode_code(18, 1) == "S18E01"
    assert episode_code(5, None) == ""
    assert episode_code(None, 3) == ""


# ── Unchanged contracts ──────────────────────────────────────────────────────

def test_row_is_mouse_transparent(qtbot):
    assert _row().testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_a_trailing_button_keeps_the_row_hit_testable(qtbot):
    from PyQt6.QtWidgets import QPushButton
    btn = QPushButton(">>")
    row = _row(trailing_button=btn)
    qtbot.addWidget(row)
    assert not row.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), (
        "a transparent ANCESTOR hides the button's whole subtree from hit-testing"
    )
    assert btn in [w for k, w in _ordered_items(row) if k == "w"], (
        "the trailing button belongs on the TITLE line, not the meta line"
    )


def test_liked_shows_the_like_glyph_before_the_title(qtbot):
    from metatv.gui import icons as _icons
    liked = _row(liked=True)
    qtbot.addWidget(liked)
    first = _ordered_items(liked)[0][1]
    assert isinstance(first, QLabel) and _icons.like_icon in first.text()

    plain = _row()
    qtbot.addWidget(plain)
    assert not any(
        isinstance(w, QLabel) and _icons.like_icon in w.text()
        for k, w in _ordered_items(plain)
    ), "no like glyph when liked is False"


def test_new_badge_renders_the_word_new(qtbot):
    row = _row(new_badge=True)
    qtbot.addWidget(row)
    assert any(
        isinstance(w, QLabel) and w.text() == "NEW"
        for k, w in _ordered_items(row)
    ), "the word NEW is the cue, never colour alone"
    assert not any(
        isinstance(w, QLabel) and w.text() == "NEW"
        for k, w in _ordered_items(_row())
    )


# ── Drift guard ──────────────────────────────────────────────────────────────

def test_nothing_looks_up_a_row_label_with_a_bare_findChild():
    """``findChild(MiddleElideLabel)`` returns the WRONG label on a two-line row.

    An AST walk, not a regex: the call can be written on the row, on a widget
    fetched from a list, or through an alias import (``_MiddleElideLabel``), and
    a line-based grep knows only one of those shapes. Seven call sites had this
    exact bug the moment the second line landed, and every one of them failed
    silently — reading "1982 · UK" where it meant "Blade Runner" — rather than
    raising. Use ``row_title_label`` / ``row_meta_label``.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in list(root.glob("metatv/**/*.py")) + list(root.glob("tests/**/*.py")):
        if path.name == "test_chip_row.py":
            continue  # this file asserts the broken behaviour on purpose
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "findChild"):
                continue
            # A call that also passes an object NAME is unambiguous — that is
            # exactly what row_title_label/row_meta_label do. Only the one-arg
            # "give me any MiddleElideLabel" form is the bug.
            if len(node.args) + len(node.keywords) > 1:
                continue
            named = {
                a.id for a in ast.walk(node) if isinstance(a, ast.Name)
            } | {
                a.attr for a in ast.walk(node) if isinstance(a, ast.Attribute)
            }
            if named & {"MiddleElideLabel", "_MiddleElideLabel"}:
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")

    assert not offenders, (
        "bare findChild(MiddleElideLabel) returns the META label on a two-line "
        "row — use row_title_label()/row_meta_label(): " + ", ".join(offenders)
    )
