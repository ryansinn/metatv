"""Recommended rows: title (+ year) left, right-aligned language/quality CHIPS.

Regression guard for the "why is an English recommendation badged [DE]?" bug: the
row used to render ``detected_region`` (the source region, e.g. DE) jammed into the
title text. Now the row is: icon, a middle-eliding title, the year hugging it, then
right-aligned chips — the language chip is the honest ``detected_prefix`` (EN), the
quality chip reuses the QUALITY_CHIP badge, and the source region must NOT appear.

Calls the row builder with a stub ``self`` (it only needs ``config`` icons), so no
full section/DB construction is needed — just a QApplication (qtbot).
"""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.gui.sidebar.recommended import RecommendedSection


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
