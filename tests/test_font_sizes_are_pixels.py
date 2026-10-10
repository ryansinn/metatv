"""Text sizes come from the theme, in pixels — never the OS's point size.

macOS renders 1pt as 1 logical px (the system default is 13pt); Linux desktops
use 96 DPI (10-11pt ≈ 13-15px). A widget sized in points, or one that inherited
the OS default, therefore came out a different size from the px-token styled
text — differently on each platform. The app font is now the type scale's base
in px (``fonts.apply_ui_font`` + ``theme``'s font floor) and a Settings text
size multiplies every FONT_* token.

These run on CI's macOS runner too, which is the point: a platform drift shows
up as a red check rather than a user report.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_PT_IN_SHEET = re.compile(r"font-size\s*:\s*[0-9.]+\s*pt\b")


def _python_files():
    return [p for p in (ROOT / "metatv").rglob("*.py") if "__pycache__" not in p.parts]


def test_no_point_sizes_anywhere():
    """No setPointSize/setPointSizeF call and no ``font-size: Npt`` in any sheet."""
    offenders = []
    for path in _python_files():
        src = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("setPointSize", "setPointSizeF")):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.func.attr}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and _PT_IN_SHEET.search(node.value):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} pt in a sheet")
    assert not offenders, (
        "Font sizes are px tokens from the theme (FONT_*), never points — a point "
        "size renders differently per OS:\n  " + "\n  ".join(offenders))


@pytest.fixture
def scaled_theme(qapp):
    from metatv.gui import theme
    yield theme
    theme.set_text_scale(1.0)


def _px(token: str) -> int:
    return int(str(token)[:-2])


def test_an_unstyled_widget_matches_the_type_scale(qapp, scaled_theme, owned_widgets):
    """Rendered size: a label with NO stylesheet takes the app font, which must
    be FONT_MD in px — the same size a FONT_MD-styled label renders at."""
    from PyQt6.QtWidgets import QLabel

    from metatv.gui import fonts
    theme = scaled_theme
    fonts.apply_ui_font(qapp)
    theme.apply_theme(theme.current_theme())

    plain = owned_widgets.own(QLabel("plain"))
    styled = owned_widgets.own(QLabel("styled"))
    theme.style_fn(styled, lambda: f"font-size: {theme.FONT_MD};")
    styled.ensurePolished()
    plain.ensurePolished()

    assert plain.font().pixelSize() == _px(theme.FONT_MD), (
        "an unstyled widget must sit at the type scale's base size in px, not "
        "the OS point size")
    assert plain.font().pixelSize() == styled.font().pixelSize()


def test_text_size_moves_styled_and_unstyled_together(qapp, scaled_theme, owned_widgets):
    from PyQt6.QtWidgets import QLabel

    theme = scaled_theme
    base = _px(theme.FONT_MD)
    assert theme.set_text_scale(1.25) is True
    assert _px(theme.FONT_MD) == round(base * 1.25)
    plain = owned_widgets.own(QLabel("plain"))
    plain.ensurePolished()
    assert plain.font().pixelSize() == _px(theme.FONT_MD), (
        "the font floor must follow the text-size setting")
    assert theme.set_text_scale(1.25) is False, "same scale twice is a no-op"
