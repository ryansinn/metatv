"""Recommended rows: title + hugging 4K chip left, year + language cluster far-right.

Regression guard for the "why is an English recommendation badged [DE]?" bug: the
row used to render ``detected_region`` (the source region, e.g. DE) jammed into the
title text. The row is: icon, a middle-eliding title, the quality (4K) chip hugging
the title TEXT, a stretch, then the right-aligned cluster (year chip, then language
chip). The language chip is the honest ``detected_prefix`` (EN), and the source
region must NOT appear.

Also guards the polish fixes (PR #344):
  * the title sizes to its content (Preferred policy, no layout stretch) so the 4K
    chip hugs the title text; its ``sizeHint`` carries a small anti-clip buffer and it
    elides in ``paintEvent`` against its FULL ``width()`` (zero contents margins), so a
    SHORT title ("1983") is NEVER clipped — only a title too long for the row elides.
    ``text()``/tooltip always stay the full string;
  * layout order is title → quality (if 4K) → [stretch] → year → language, with the
    language chip the consistent far-right element;
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
    # Chips can be QLabel (language/year) or QPushButton (quality); collect both.
    widgets = row.findChildren(QLabel) + row.findChildren(QPushButton)
    return [w.text() for w in widgets] + [w.toolTip() for w in row.findChildren(QLabel)]


def _ordered_widgets(row):
    """Widgets in the row's QHBoxLayout, in left→right order (skips spacers)."""
    layout = row.layout()
    out = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is not None:
            out.append(w)
    return out


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


def test_title_sizes_to_content_with_anti_clip_buffer(qtbot):
    # The title sizes to its content (Preferred policy, NO layout stretch) so the 4K
    # chip can hug the title TEXT — and its sizeHint carries an anti-clip buffer plus
    # zero contents margins, so a title that fits is never clipped by sub-pixel rounding.
    from PyQt6.QtWidgets import QSizePolicy
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(), "1998")
    title = row.findChild(_MiddleElideLabel)
    assert title is not None
    assert title.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Preferred
    layout = row.layout()
    idx = next(i for i in range(layout.count()) if layout.itemAt(i).widget() is title)
    assert layout.stretch(idx) == 0, "title sizes to content, not via stretch"
    fm = title.fontMetrics()
    assert title.sizeHint().width() > fm.horizontalAdvance(title.text()), "needs anti-clip buffer"
    margins = title.contentsMargins()
    assert margins.left() == 0 and margins.right() == 0


def test_short_title_not_clipped_at_its_own_hint_width(qtbot):
    # THE regression: at the width the layout grants (the label's sizeHint), a short
    # title must render in full — "1983" must NOT become "1…3".
    from PyQt6.QtCore import Qt
    label = _MiddleElideLabel("1983")
    qtbot.addWidget(label)
    label.resize(label.sizeHint())  # the width a content-sized layout grants it
    fm = label.fontMetrics()
    assert label.width() >= fm.horizontalAdvance("1983")
    assert fm.elidedText("1983", Qt.TextElideMode.ElideMiddle, label.width()) == "1983"
    label.grab()  # force a real paint; no crash, stored text stays full
    assert label.text() == "1983"
    assert label.toolTip() == "1983"


def test_short_title_not_elided_at_wide_width(qtbot):
    # Belt-and-suspenders: with room to spare, elidedText returns the FULL string.
    from PyQt6.QtCore import Qt
    label = _MiddleElideLabel("1983")
    qtbot.addWidget(label)
    fm = label.fontMetrics()
    wide = fm.horizontalAdvance("1983") + 50
    assert fm.elidedText("1983", Qt.TextElideMode.ElideMiddle, wide) == "1983"
    label.resize(wide, 20)
    label.grab()
    assert label.text() == "1983"


def test_long_title_still_elides_when_too_narrow(qtbot):
    # A genuinely-too-long title still middle-elides (visual only); the stored full text
    # is preserved for text()/tooltip.
    from PyQt6.QtCore import Qt
    long_title = "A Very Long Documentary Title That Cannot Possibly Fit"
    label = _MiddleElideLabel(long_title)
    qtbot.addWidget(label)
    label.resize(60, 20)
    label.grab()
    assert label.text() == long_title
    assert label.toolTip() == long_title
    elided = label.fontMetrics().elidedText(
        long_title, Qt.TextElideMode.ElideMiddle, label.width()
    )
    assert elided != long_title and "…" in elided  # middle-elided at this width


def test_layout_order_title_quality_stretch_year_language(qtbot):
    # 4K chip hugs the title TEXT (immediately after it, BEFORE the stretch); the year
    # and language chips are the right-aligned cluster after the stretch.
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(), "1998")
    items = _ordered_items(row)
    title_i = _widget_index(items, lambda w: isinstance(w, _MiddleElideLabel))
    quality_i = _widget_index(items, lambda w: isinstance(w, QPushButton) and w.text() == "4K")
    year_i = _widget_index(items, lambda w: isinstance(w, QLabel) and w.text() == "1998")
    lang_i = _widget_index(items, lambda w: isinstance(w, QLabel) and w.text() == "EN")
    spacer_i = _spacer_index(items)
    order = [(k, getattr(o, "text", lambda: k)()) for k, o in items]
    assert title_i < quality_i < spacer_i < year_i < lang_i, order


def test_layout_order_title_stretch_year_language_when_no_quality(qtbot):
    # Quality chip present only when set; without it: title → [stretch] → year → language.
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(detected_quality=""), "1998")
    items = _ordered_items(row)
    assert not any(k == "w" and isinstance(o, QPushButton) and o.text() == "4K" for k, o in items)
    title_i = _widget_index(items, lambda w: isinstance(w, _MiddleElideLabel))
    year_i = _widget_index(items, lambda w: isinstance(w, QLabel) and w.text() == "1998")
    lang_i = _widget_index(items, lambda w: isinstance(w, QLabel) and w.text() == "EN")
    spacer_i = _spacer_index(items)
    assert title_i < spacer_i < year_i < lang_i


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
