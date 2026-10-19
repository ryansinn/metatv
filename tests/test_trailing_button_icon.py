"""set_button_icon(trailing=True) paints the icon AFTER the words.

Rendered pixels, not a flag: the icon is painted pure red and the test finds
where the red lands. Without ``trailing`` Qt puts it on the leading edge, so
this fails if the option stops working.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("qtawesome")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _red_columns(btn) -> list[int]:
    img = btn.grab().toImage()
    cols = []
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            if c.red() > 200 and c.green() < 60 and c.blue() < 60:
                cols.append(x)
                break
    return cols


@pytest.mark.parametrize("trailing", [True, False])
def test_icon_side_follows_the_trailing_flag(qapp, owned_widgets, trailing):
    from PyQt6.QtWidgets import QPushButton

    from metatv.gui import icon_utils

    btn = owned_widgets.own(QPushButton("Category (2/5)"))
    btn.resize(220, 32)
    icon_utils.set_button_icon(btn, "dropdown_caret", color="#ff0000", trailing=trailing)
    cols = _red_columns(btn)
    assert cols, "the icon was not painted at all"
    centre = btn.width() / 2
    if trailing:
        assert min(cols) > centre, f"trailing icon drawn at x={min(cols)}, left of centre"
    else:
        assert max(cols) < centre, f"leading icon drawn at x={max(cols)}, right of centre"
    # The words are unchanged by the flip.
    assert btn.text() == "Category (2/5)"
