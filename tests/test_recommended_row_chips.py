"""Recommended rows: a clean title over "Series · 1998 · EN · 4K".

Regression guard for the "why is an English recommendation badged [DE]?" bug: the
row used to render ``detected_region`` (the source region, e.g. DE) jammed into the
title text. The facts a row shows are the honest ones — ``detected_prefix`` (EN) for
language, the year, the quality — and the source region must NOT appear anywhere.

V3 moved those facts out of right-aligned chips and into the meta line under the
title. The chip-ORDER tests that pinned the old arrangement went with it; the two
things they were protecting did not, and are asserted here still:

  * the source region never renders;
  * the title sizes to its content (Preferred policy, no layout stretch); its
    ``sizeHint`` carries a small anti-clip buffer and it elides in ``paintEvent``
    against its FULL ``width()`` (zero contents margins), so a SHORT title ("1983")
    is NEVER clipped — only a title too long for the row elides, and ``text()``
    /tooltip always stay the full string.

Calls the row builder with a stub ``self``, so no full section/DB construction is
needed — just a QApplication (qtbot).
"""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel, QPushButton, QSizePolicy

from metatv.gui.chip_row import (
    DENSITY_COMPACT, row_meta_label, row_title_label,
)
from metatv.gui.sidebar.recommended import RecommendedSection, _MiddleElideLabel


def _stub_self():
    """A stand-in for the section, carrying what _build_rec_row reads.

    ``_row_density`` included: rows now render compact or comfortable from the
    viewer's preference, and the section resolves it. A double that omits it
    fails with AttributeError the moment a row is built.
    """
    from tests.conftest import sidebar_config
    return SimpleNamespace(
        config=sidebar_config(),
        _row_density=lambda: DENSITY_COMPACT,
    )


def _sc(**over):
    base = {
        "media_type": "series", "already_liked": False,
        "detected_title": "Cowboy Bebop", "detected_year": "1998",
        "detected_prefix": "EN", "detected_region": "DE", "detected_quality": "4K",
        "channel_name": "EN - Cowboy Bebop (1998)",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _row(**over):
    return RecommendedSection._build_rec_row(_stub_self(), _sc(**over), "1998")


def _row_texts(row):
    widgets = row.findChildren(QLabel) + row.findChildren(QPushButton)
    return [w.text() for w in widgets] + [w.toolTip() for w in row.findChildren(QLabel)]


def _facts(row):
    """The facts the row shows, in order — chips at compact, meta at comfy.

    Recommended renders COMPACT by default (the owner's pick), so these read
    the chips. What they guard is unchanged: the honest ``detected_prefix``
    appears and the source ``detected_region`` never does.
    """
    from PyQt6.QtWidgets import QPushButton
    meta = row_meta_label(row)
    if meta is not None:
        return [p.strip() for p in meta.text().split("·")]
    return [b.text() for b in row.findChildren(QPushButton) if b.text()]


# ── The honest facts, and the one that must never appear ─────────────────────

def test_row_shows_the_honest_facts_and_never_the_region(qtbot):
    row = _row()
    texts = _row_texts(row)
    assert row_title_label(row).text() == "Cowboy Bebop", texts
    assert _facts(row) == ["4K", "1998", "EN"], texts
    assert not any("DE" in t for t in texts), f"region DE leaked: {texts}"


def test_the_media_type_is_an_icon_and_never_a_word(qtbot):
    """It was briefly the WORD, which is the repetition the icon exists to kill."""
    from PyQt6.QtWidgets import QLabel
    for media_type in ("movie", "series"):
        row = _row(media_type=media_type)
        qtbot.addWidget(row)
        painted = [
            w for w in row.findChildren(QLabel)
            if w.pixmap() is not None and not w.pixmap().isNull()
        ]
        assert painted, f"{media_type}: no type icon painted"
        joined = " ".join(_row_texts(row))
        for word in ("Movie", "Series", "Live"):
            assert word not in joined, f"{media_type}: row spells out {word!r}"


def test_missing_facts_draw_no_chip_at_all(qtbot):
    assert _facts(_row(detected_quality="")) == ["1998", "EN"]
    assert _facts(_row(detected_prefix="")) == ["4K", "1998"]
    assert _facts(_row(detected_quality="", detected_prefix="")) == ["1998"]


def test_row_missing_prefix_shows_no_language_and_no_region(qtbot):
    row = _row(detected_prefix="")
    assert "EN" not in _facts(row)
    assert not any("DE" in t for t in _row_texts(row))


def test_the_compact_row_IS_its_chips(qtbot):
    """This test used to assert the opposite, and was right at the time.

    #457 removed the chips entirely; the owner asked for them back — "I do like
    the previous design with the colored chips and single line" — so compact is
    the default and the chips are how it says anything. Inverted rather than
    deleted, because "no chips" was a real decision for exactly one release and
    the reversal should be visible in the history.
    """
    from PyQt6.QtWidgets import QPushButton
    row = _row()
    qtbot.addWidget(row)
    chips = [b.text() for b in row.findChildren(QPushButton) if b.text()]
    assert chips == ["4K", "1998", "EN"], chips


# ── The title label's anti-clip contract (unchanged by V3) ───────────────────

def test_title_sizes_to_content_with_anti_clip_buffer(qtbot):
    # The title sizes to its content (Preferred policy, NO layout stretch), and its
    # sizeHint carries an anti-clip buffer plus zero contents margins, so a title
    # that fits is never clipped by sub-pixel rounding.
    row = _row()
    title = row_title_label(row)
    assert title is not None
    assert title.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Preferred
    layout = title.parentWidget().layout()
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


def test_the_meta_line_never_widens_the_row(qtbot):
    from metatv.gui.chip_row import DENSITY_COMFORTABLE
    """A long meta line elides; it does not push the section wider than its titles.

    The title is what the section is FOR — "Series · 1998 · EN · 4K" must never be
    the thing that decides how much horizontal space History demands.
    """
    stub = _stub_self()
    stub._row_density = lambda: DENSITY_COMFORTABLE
    short = RecommendedSection._build_rec_row(stub, _sc(detected_prefix=""), "1998")
    long_meta = RecommendedSection._build_rec_row(stub, _sc(), "1998")
    assert row_meta_label(long_meta).sizePolicy().horizontalPolicy() == (
        QSizePolicy.Policy.Ignored
    )
    assert long_meta.minimumSizeHint().width() <= max(
        short.minimumSizeHint().width(),
        row_title_label(long_meta).minimumSizeHint().width() + 40,
    ), "the meta line is dictating the row's minimum width"
