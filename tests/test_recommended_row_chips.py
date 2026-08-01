"""Recommended rows: title left, year+quality left-cluster, language chip far-right.

Regression guard for the "why is an English recommendation badged [DE]?" bug: the
row used to render ``detected_region`` (the source region, e.g. DE) jammed into the
title text. The row is: icon, a middle-eliding title, then the LEFT cluster (year
chip + quality chip), a stretch, then the language chip pushed to the far right —
the language chip is the honest ``detected_prefix`` (EN), and the source region must
NOT appear.

Also guards three polish fixes (PR #344):
  * the title middle-elides in ``paintEvent`` against the CURRENT width, so a SHORT
    title ("1983") is never chopped — ``text()``/tooltip always stay the full string;
  * the quality chip sits BEFORE (left of) the language chip in layout order, so the
    language chip is the consistent far-right element;
  * the year renders as its own ``YEAR_CHIP``-styled chip.

Calls the row builder with a stub ``self`` (it only needs ``config`` icons), so no
full section/DB construction is needed — just a QApplication (qtbot).
"""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.gui import theme as _theme
from metatv.gui.sidebar.recommended import RecommendedSection, _MiddleElideLabel


def _stub_self():
    return SimpleNamespace(
        config=SimpleNamespace(movie_icon="🎬", series_icon="📺", like_icon="👍")
    )


def _sc(**over):
    base = dict(
        media_type="series", already_liked=False,
        detected_title="Cowboy Bebop", detected_year="1998",
        detected_prefix="EN", detected_region="DE", detected_quality="4K",
        channel_name="EN - Cowboy Bebop (1998)",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _row_texts(row):
    # Chips can be QLabel (language) or QPushButton (quality); collect both.
    widgets = row.findChildren(QLabel) + row.findChildren(QPushButton)
    return [w.text() for w in widgets] + [w.toolTip() for w in row.findChildren(QLabel)]


def _ordered_widgets(row):
    """Widgets in the row's QHBoxLayout, in left→right order."""
    layout = row.layout()
    out = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is not None:
            out.append(w)
    return out


def test_row_shows_language_and_quality_chips_not_region(qtbot):
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(), "1998")
    texts = _row_texts(row)
    assert any("Cowboy Bebop" in t for t in texts), texts   # title present (label/tooltip)
    assert "1998" in texts, texts                            # year is its own label
    assert "EN" in texts, texts                              # honest language chip (prefix)
    assert "4K" in texts, texts                              # quality chip renders (QUALITY_CHIP button)
    assert not any("DE" in t for t in texts), f"region DE leaked: {texts}"


def test_quality_chip_is_a_button_so_the_badge_style_renders(qtbot):
    # QUALITY_CHIP is QPushButton-scoped; the quality chip must be a QPushButton or
    # the '4K' badge silently renders as plain text.
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(), "1998")
    assert any(b.text() == "4K" for b in row.findChildren(QPushButton)), "4K must be a chip button"


def test_row_without_quality_has_no_quality_chip(qtbot):
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(detected_quality=""), "1998")
    assert not any(b.text() == "4K" for b in row.findChildren(QPushButton))
    assert "EN" in _row_texts(row)  # language chip still there


def test_row_missing_prefix_shows_no_language_chip_and_no_region(qtbot):
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(detected_prefix=""), "1998")
    assert not any("DE" in t for t in _row_texts(row))


def test_short_title_is_preserved_full_not_chopped(qtbot):
    # The title middle-elides in paintEvent against the CURRENT width (not by mutating
    # the stored text in resizeEvent), so a SHORT title that easily fits is never
    # chopped ("1983" used to render as "1…3"). text()/tooltip stay the full string
    # regardless of paint width — force paints at wide + narrow widths to prove it.
    label = _MiddleElideLabel("1983")
    qtbot.addWidget(label)
    label.resize(400, 20)
    label.grab()          # force a paintEvent at a comfortable width
    label.resize(24, 20)  # a width where the old resize-elide chopped short titles
    label.grab()          # force a paintEvent at a cramped width
    assert label.text() == "1983"     # stored text never mutated by paint
    assert label.toolTip() == "1983"

    # And a genuinely-too-long title still middle-elides (visual only); the stored
    # full text is preserved for text()/tooltip.
    long_title = "A Very Long Documentary Title That Cannot Possibly Fit"
    long_label = _MiddleElideLabel(long_title)
    qtbot.addWidget(long_label)
    long_label.resize(60, 20)
    long_label.grab()
    assert long_label.text() == long_title
    elided = long_label.fontMetrics().elidedText(
        long_title, _theme_elide_middle(), long_label.contentsRect().width()
    )
    assert elided != long_title and "…" in elided  # middle-elided at this width


def test_quality_chip_is_left_of_language_chip(qtbot):
    # Every row has a language chip, so it must be the consistent far-right element;
    # the quality chip lives in the LEFT cluster, before it.
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(), "1998")
    widgets = _ordered_widgets(row)
    quality_idx = next(
        i for i, w in enumerate(widgets)
        if isinstance(w, QPushButton) and w.text() == "4K"
    )
    lang_idx = next(
        i for i, w in enumerate(widgets)
        if isinstance(w, QLabel) and w.text() == "EN"
    )
    assert quality_idx < lang_idx, [type(w).__name__ + ":" + w.text() for w in widgets]


def test_year_renders_as_year_chip_and_no_region(qtbot):
    # The year is a bordered chip (its own YEAR_CHIP-styled QLabel), not plain text —
    # and the source region must not leak anywhere.
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(), "1998")
    year_chips = [
        w for w in row.findChildren(QLabel)
        if w.text() == "1998" and w.styleSheet() == _theme.YEAR_CHIP
    ]
    assert year_chips, "year must render as its own YEAR_CHIP-styled chip"
    assert not any("DE" in t for t in _row_texts(row))


def _theme_elide_middle():
    from PyQt6.QtCore import Qt
    return Qt.TextElideMode.ElideMiddle
