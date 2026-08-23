"""The corner-radius scale, and the Qt rule that makes it dangerous to guess.

Measured, not recalled (Qt 6.11 / PyQt6 6.11.1)::

    Qt honours a border-radius only while it is <= HALF the box's height.
    One pixel over, it does not clamp — it silently renders a SQUARE.

That is the whole reason this file exists. The failure has no stylesheet
signature: ``border-radius: 12px`` on a 20px chip looks like a rounder chip in
the source and renders as a rectangle on screen. A sweep that "tidies" 165
literals onto four steps is exactly the change most likely to introduce it, so
the sweep ships with a test that renders.

It also records why a PILL is not on the scale: a pill is half the control's
height, so it depends on the control and cannot be a constant. The two web
idioms for one — ``border-radius: 999px`` and ``50%`` — both render a hard
rectangle in Qt, which the first test below pins down so nobody tries again.
"""

from __future__ import annotations

import re

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QWidget

from metatv.gui import theme as _theme

_RADIUS = re.compile(r"border-radius:\s*(\d+)px\s*(?=[;}])")


def _renders_rounded(qapp, radius_css: str, height: int, width: int = 80) -> bool:
    """Paint a solid box and report whether its top-left corner is actually cut.

    White on black, so "was the corner painted" is a single pixel comparison
    rather than a judgement call.
    """
    host = QWidget()
    host.setStyleSheet("background:#000000;")
    box = QLabel("", host)
    box.setStyleSheet(f"background:#ffffff; border-radius:{radius_css};")
    box.setFixedSize(width, height)
    box.move(0, 0)
    host.setFixedSize(width, height)
    host.show()
    qapp.processEvents()
    image = host.grab().toImage()
    return QColor(image.pixel(0, 0)).name() != "#ffffff"


# ---------------------------------------------------------------------------
# 1. The engine rule itself.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("height", [16, 20, 24, 28, 40])
def test_qt_squares_a_box_whose_radius_exceeds_half_its_height(qapp, height):
    """The cutoff is exactly ``height / 2``, and going over does NOT clamp.

    Pinned per height so a future Qt that starts clamping is caught as a
    behaviour change rather than silently making the guards below pointless.
    """
    half = height // 2
    assert _renders_rounded(qapp, f"{half}px", height), (
        f"a radius of exactly half ({half}px of {height}px) should still round"
    )
    assert not _renders_rounded(qapp, f"{half + 1}px", height), (
        f"{half + 1}px on a {height}px box rounded — Qt has started clamping, "
        f"and the radius scale's safety rule needs revisiting"
    )


@pytest.mark.parametrize("idiom", ["999px", "9999px", "50%"])
def test_the_web_pill_idioms_render_a_rectangle(qapp, idiom):
    """``border-radius: 999px`` and ``50%`` are how a pill is written on the
    web. Both give a hard rectangle here — so a ``RADIUS_PILL`` token would
    have squared every chip it touched."""
    assert not _renders_rounded(qapp, idiom, 20), (
        f"{idiom} rounded — a pill token may now be possible, which would be "
        f"worth having"
    )


# ---------------------------------------------------------------------------
# 2. The scale.
# ---------------------------------------------------------------------------

SCALE = {
    "RADIUS_NONE": 0,
    "RADIUS_SM": 4,
    "RADIUS_MD": 8,
    "RADIUS_LG": 12,
}


def test_the_scale_is_four_steps_and_each_is_a_distinct_size():
    """Four steps, and no two closer than 4px — the problem being fixed is 15
    values of which 3px and 4px (108 of 165 sites between them) were visually
    identical at every size this interface uses."""
    values = [_theme.radius_px(getattr(_theme, name)) for name in SCALE]
    assert values == sorted(values)
    steps = [b - a for a, b in zip(values, values[1:])]
    assert all(step >= 4 for step in steps), f"steps too close to tell apart: {steps}"


@pytest.mark.parametrize("name,expected", sorted(SCALE.items()))
def test_each_token_reads_as_px_and_as_an_int(name, expected):
    """A stylesheet wants ``"8px"``; a QPainter wants ``8``. One definition."""
    token = getattr(_theme, name)
    assert token.endswith("px")
    assert _theme.radius_px(token) == expected


@pytest.mark.parametrize("name", sorted(SCALE))
def test_every_step_actually_rounds_at_its_documented_floor(qapp, name):
    """Each step declares a minimum control height it is safe on. Assert the
    box really rounds there — the arithmetic and the renderer agreeing is the
    only thing that makes the docstring's advice trustworthy."""
    value = _theme.radius_px(getattr(_theme, name))
    if value == 0:
        pytest.skip("a square is a square at every height")
    floor = value * 2
    assert _renders_rounded(qapp, f"{value}px", floor), (
        f"{name} ({value}px) does not round on its documented {floor}px floor"
    )


# ---------------------------------------------------------------------------
# 3. No role constant has silently squared.
# ---------------------------------------------------------------------------

def _role_sheets() -> list[tuple[str, str, int]]:
    """``(name, sheet, radius)`` for every theme role carrying a single radius."""
    out = []
    for name in dir(_theme):
        if name.startswith("_") or not name.isupper():
            continue
        sheet = getattr(_theme, name)
        if not isinstance(sheet, str) or "border-radius" not in sheet:
            continue
        match = _RADIUS.search(sheet)
        if match:
            out.append((name, sheet, int(match.group(1))))
    return out


def test_there_are_role_constants_to_check():
    """A guard whose population silently became empty guards nothing."""
    assert len(_role_sheets()) >= 40


def test_widget_module_literals_are_a_known_remainder():
    """The sweep covered ``theme.py``'s role constants — the canonical layer —
    and deliberately stopped there.

    Widget modules still hold raw radius literals. Threading token reads into
    them was tried and reverted: it turns a pure-literal inline sheet into a
    theme-reading one, which the style-registry drift guard correctly flags
    (a composed sheet renders once and goes stale on a theme switch) and which
    pushes the shrink-only COMPOSED_BUDGET the wrong way. Those sites want
    ``theme.style_fn`` or promotion to a shared role FIRST; the radius is the
    least interesting thing about them.

    This asserts the remainder only SHRINKS, so the debt cannot quietly grow
    back while it waits.
    """
    import pathlib
    import re as _re

    literals = 0
    for path in pathlib.Path("metatv").rglob("*.py"):
        if path.name in ("theme.py", "scales.py"):
            continue
        literals += len(_re.findall(r"border-radius:\s*\d+px", path.read_text()))
    assert literals <= 92, (
        f"{literals} raw radius literals in widget modules — this number may "
        f"only go down; use theme.style_fn or a shared role constant"
    )


@pytest.mark.parametrize("name,radius", [(n, r) for n, _s, r in _role_sheets()])
def test_no_role_radius_exceeds_the_scale_or_its_own_pill_budget(name, radius):
    """Every radius is either ON the scale, or is a documented pill-scale value
    left alone by the sweep.

    The sweep deliberately stopped at 8px: from 9px up, several of these are
    pill-intent (radius == half the control's height) and moving them onto a
    fixed step would square them. This test is what stops someone finishing the
    job mechanically.
    """
    on_scale = radius in set(SCALE.values())
    pill_scale = radius >= 9
    assert on_scale or pill_scale, (
        f"{name} uses {radius}px — not a scale step ({sorted(SCALE.values())}) "
        f"and not in the pill range this sweep left alone"
    )
