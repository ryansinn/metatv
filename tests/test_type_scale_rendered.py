"""The V3 type scale, measured as Qt actually renders it.

The palette test next door asserts the TOKEN values. That is necessary and not
sufficient: a token is a string until Qt lays it out, and "13px" only becomes
hierarchy once you know what it paints. `font-size` also does not map 1:1 onto
rendered height — 9px and 10px both land inside a 1px band — so a scale that
looks generous in the token table can still render as one undifferentiated
size. These measure the painted result: the rendered height of real polished
widgets carrying the real role tokens.

Proven to fail against the pre-V3 ramp (9/10/11/12/13/14/18/20): the
view-title-to-body ratio was 19/15 = 1.27x, and body text rendered 15px tall.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel

from metatv.gui import theme

SAMPLE = "Breaking Bad"


def _rendered(qtbot, token: str) -> tuple[int, int]:
    """Height and width the label ACTUALLY paints at, in device pixels.

    Goes through a real polished QLabel rather than QFont(size) because that is
    the path the app uses: every one of these tokens reaches a widget as a QSS
    `font-size`, and Qt resolves QSS to an effective font only on polish.
    """
    label = QLabel(SAMPLE)
    qtbot.addWidget(label)
    label.setStyleSheet(f"font-size: {token};")
    label.ensurePolished()
    metrics = label.fontMetrics()
    return metrics.height(), metrics.horizontalAdvance(SAMPLE)


def test_body_text_clears_the_legibility_floor(qtbot):
    """Body carries the app; it rendered 15px tall before V3.

    A floor, not an equality — a later scale is free to grow it.

    16, not 17. The same token paints 18px on Linux and 16px on macOS: font
    rasterisation is a PLATFORM property, and a floor set from one machine's
    numbers is an assertion about that machine. 17 failed every macOS CI run
    while the scale was perfectly correct there. 16 still catches the
    regression this was written for — the pre-V3 ramp rendered body at 15.
    """
    height, _ = _rendered(qtbot, theme.FONT_MD)
    assert height >= 16, (
        f"body text renders {height}px tall; the pre-V3 ramp rendered 15px "
        "and this is the guard against falling back to it"
    )


@pytest.mark.parametrize(
    "role, floor, label",
    [
        ("FONT_2XL", 1.40, "view title"),
        ("FONT_XL", 1.25, "section heading"),
        ("FONT_LG", 1.10, "row title"),
    ],
)
def test_the_hierarchy_is_visible_at_render_size(qtbot, role, floor, label):
    """Each level must out-render body text by a perceptible ratio.

    Ratios, not pixel deltas: +3px on 15px body reads as a step, the same +3px
    on a 38px display face does not. Pre-V3 the view title managed only 1.27x
    over body, which is why weight — not size — was carrying the hierarchy.
    """
    body, _ = _rendered(qtbot, theme.FONT_MD)
    got, _ = _rendered(qtbot, getattr(theme, role))
    ratio = got / body
    assert ratio >= floor, (
        f"{label} renders {got}px against {body}px body — {ratio:.2f}x, "
        f"under the {floor}x that makes a level read as a level"
    )


def test_every_ramp_step_renders_larger_than_the_one_below(qtbot):
    """No step may collapse into its neighbour once painted.

    Two distinct token values can still render at the same height (9px and 10px
    both paint a 13-14px line), which is the failure this catches and the token
    test structurally cannot.
    """
    ramp = ["FONT_XS", "FONT_SM", "FONT_MD", "FONT_LG", "FONT_XL", "FONT_2XL",
            "FONT_3XL", "FONT_4XL"]
    heights = [_rendered(qtbot, getattr(theme, r))[0] for r in ramp]

    collapsed = [
        f"{lo}->{hi} both render {a}px"
        for lo, hi, a, b in zip(ramp, ramp[1:], heights, heights[1:])
        if b <= a
    ]
    assert not collapsed, "; ".join(collapsed)


def test_the_ramp_spans_a_real_range_when_painted(qtbot):
    """End to end the scale must cover enough ground to be a scale.

    Pre-V3 the eight body steps painted 13px..27px. The span is what lets a
    display size feel like a display size next to a caption.
    """
    small, _ = _rendered(qtbot, theme.FONT_XS)
    large, _ = _rendered(qtbot, theme.FONT_4XL)
    assert large - small >= 20, (
        f"the painted ramp spans only {large - small}px ({small}..{large})"
    )
    assert large / small >= 2.2, (
        f"the painted ramp covers only {large / small:.2f}x end to end"
    )
