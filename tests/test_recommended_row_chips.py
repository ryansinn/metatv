"""Recommended rows show title · year + right-aligned language/quality CHIPS.

Regression guard for the "why is an English recommendation badged [DE]?" bug: the
row used to render ``detected_region`` (the source region, e.g. DE) jammed into the
title text. Now the title is just ``title · year`` and facets are distinct chips —
the language chip is the honest ``detected_prefix`` (EN), and the source region must
NOT appear anywhere in the row.

Calls the row builder with a stub ``self`` (it only needs ``config`` icons), so no
full section/DB construction is needed — just a QApplication (qtbot).
"""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel

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


def test_row_shows_language_prefix_and_quality_not_region(qtbot):
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(), "1998")
    texts = [lbl.text() for lbl in row.findChildren(QLabel)]
    # Title area = title · year
    assert any("Cowboy Bebop" in t and "1998" in t for t in texts), texts
    # Honest language chip (prefix) + quality chip present as their own labels
    assert "EN" in texts, texts
    assert "4K" in texts, texts
    # The source region must NOT leak into the title OR any chip.
    assert not any("DE" in t for t in texts), f"region DE leaked: {texts}"


def test_row_without_quality_has_no_quality_chip(qtbot):
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(detected_quality=""), "1998")
    texts = [lbl.text() for lbl in row.findChildren(QLabel)]
    assert "EN" in texts          # language chip still there
    assert "4K" not in texts      # no empty quality chip


def test_row_missing_prefix_shows_no_language_chip(qtbot):
    row = RecommendedSection._build_rec_row(_stub_self(), _sc(detected_prefix=""), "1998")
    texts = [lbl.text() for lbl in row.findChildren(QLabel)]
    # No language chip, and crucially still no region fallback sneaking in.
    assert not any("DE" in t for t in texts), texts
