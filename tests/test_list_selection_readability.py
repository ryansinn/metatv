"""Selected-row text stays readable on the tinted selection, in every palette.

The bug (owner screenshot, Gruvbox, 2026-09-03)
------------------------------------------------
``theme.apply_list_selection(view)`` appends ``LIST_SELECTION_QSS``: a
translucent ``OVERLAY_SELECTION`` tint + a 2px accent bar, deliberately with
NO ``color:`` rule (so per-item colours survive). With no ``color:`` in the
QSS, Qt still paints selected text with the palette's ``HighlightedText`` —
which ``qt_palette()`` sets to ``COLOR_ON_ACCENT``, correct for a SOLID accent
fill, wrong for a translucent tint. In Gruvbox the accent is pale (#83a598),
so ``COLOR_ON_ACCENT`` is near-black (#0d0e0f): near-black text over a 14.5%
tint on a near-black background measures ~1.22:1 (see
``test_old_on_accent_pairing_fails_in_gruvbox`` below, which is the pre-fix
proof). Second symptom: the tree's branch/indent strip, not covered by
``::item``, painted the raw OPAQUE ``Highlight`` fill instead of the tint.

The fix (``metatv/gui/theme.py``, one chokepoint: ``apply_list_selection``)
pins the view's own QPalette — ``HighlightedText`` -> ``COLOR_TEXT_HI`` (the
surface's own bright-text ramp; a translucent tint OF the surface takes its
foreground from the surface, never ``on_fill``/``ON_ACCENT`` — the documented
exception in docs/CRITICAL_RULES.md) and ``Highlight`` -> ``OVERLAY_SELECTION``
(so the branch/indent strip paints the tint too) — and re-registers through
``style_fn`` so a later ``apply_theme`` re-applies both.

Test 1 was run against the tree BEFORE this fix (theme.py's edit temporarily
reverted) and was RED: every palette but Graphite failed the palette-role
assertions (Graphite's ``COLOR_ON_ACCENT`` happens to equal its
``COLOR_TEXT_HI``, both ``#eeeeee`` — coincidence, not correctness). Restoring
the fix turns it GREEN. See the PR body for the exact before/after numbers.
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QTreeWidget

from metatv.gui import theme as _theme
from metatv.gui import theme_palettes as tp
from tests.test_widget_composed_contrast import _composite, _contrast, _rgba

FLOOR = 4.5


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_theme():
    original = _theme.current_theme()
    yield
    _theme.apply_theme(original)


@pytest.mark.parametrize("palette_name", list(tp.PALETTES.keys()))
def test_view_palette_pins_text_hi_and_overlay_selection(qapp, palette_name):
    """The two roles apply_list_selection() must pin, in every palette."""
    _theme.apply_theme(palette_name)
    view = QTreeWidget()

    _theme.apply_list_selection(view)

    pal = view.palette()
    got_text = pal.color(QPalette.ColorRole.HighlightedText).name()
    want_text = _rgba(_theme.COLOR_TEXT_HI)
    assert got_text == "#" + "".join(f"{int(c):02x}" for c in want_text[:3]), (
        f"{palette_name}: HighlightedText is {got_text}, expected COLOR_TEXT_HI "
        f"{_theme.COLOR_TEXT_HI} — selected text will use the on-accent ramp "
        f"instead of the surface's own bright-text ramp"
    )
    got_hl = pal.color(QPalette.ColorRole.Highlight)
    want_hl = _rgba(_theme.OVERLAY_SELECTION)
    assert (got_hl.red(), got_hl.green(), got_hl.blue(), round(got_hl.alphaF(), 3)) == (
        int(want_hl[0]), int(want_hl[1]), int(want_hl[2]), round(want_hl[3], 3)
    ), (
        f"{palette_name}: Highlight is {got_hl.name()} alpha={got_hl.alphaF():.3f}, "
        f"expected OVERLAY_SELECTION {_theme.OVERLAY_SELECTION} — the branch/"
        f"indent strip will paint the opaque solid fill instead of the tint"
    )


@pytest.mark.parametrize("palette_name", list(tp.PALETTES.keys()))
def test_text_hi_on_composited_tint_clears_floor(qapp, palette_name):
    """Rendered-appearance half: composite the tint over the real resting
    surface (COLOR_BG_DEEP — the Base role qt_palette() gives every item
    view; there is no separate "COLOR_BG" token in this codebase) and
    measure contrast the same way test_widget_composed_contrast.py does.
    """
    _theme.apply_theme(palette_name)
    surface = _rgba(_theme.COLOR_BG_DEEP)
    composited = _composite(_rgba(_theme.OVERLAY_SELECTION), surface)

    ratio = _contrast(_rgba(_theme.COLOR_TEXT_HI), composited)

    assert ratio >= FLOOR, (
        f"{palette_name}: COLOR_TEXT_HI on the composited selection tint is "
        f"only {ratio:.2f}:1, below the {FLOOR}:1 floor"
    )


def test_old_on_accent_pairing_fails_in_gruvbox(qapp):
    """Pre-fix-behaviour proof: COLOR_ON_ACCENT (what HighlightedText used to
    resolve to, via qt_palette()'s app-wide QPalette, before this fix pinned
    the view's own palette instead) is why the bug shipped. This documents
    the failure so a revert to ON_ACCENT is caught here, not just visually.
    """
    _theme.apply_theme("Gruvbox")
    surface = _rgba(_theme.COLOR_BG_DEEP)
    composited = _composite(_rgba(_theme.OVERLAY_SELECTION), surface)

    old_ratio = _contrast(_rgba(_theme.COLOR_ON_ACCENT), composited)

    assert old_ratio < FLOOR, (
        f"expected the OLD COLOR_ON_ACCENT pairing to fail in Gruvbox (it "
        f"measured ~1.22:1 on the owner's screenshot); got {old_ratio:.2f}:1 "
        f"— if this now passes, the diagnosis needs re-checking"
    )


def test_theme_switch_repalettes_and_does_not_stack_the_rule(qapp):
    """Apply in palette A, switch to B: the view follows, and the appended
    selection QSS is never duplicated across the switch.
    """
    _theme.apply_theme("Midnight")
    view = QTreeWidget()
    _theme.apply_list_selection(view)

    _theme.apply_theme("Daylight")

    pal = view.palette()
    got_text = pal.color(QPalette.ColorRole.HighlightedText).name()
    want_text = _rgba(_theme.COLOR_TEXT_HI)
    assert got_text == "#" + "".join(f"{int(c):02x}" for c in want_text[:3]), (
        "the view kept Midnight's HighlightedText after switching to Daylight"
    )
    sheet = view.styleSheet()
    assert sheet.count("QAbstractItemView::item:selected") == 1, (
        f"selection rule appears {sheet.count('QAbstractItemView::item:selected')} "
        f"times after a theme switch — it must not stack:\n{sheet}"
    )
