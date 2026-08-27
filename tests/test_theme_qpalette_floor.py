"""Tests for the QPalette floor (What's New #253).

Owner-reported bug (screenshot evidence): the bottom nav bar / status bar
rendered pure WHITE in a dark theme, the details-pane section headers
("Overview", "Cast & Crew", "Technical Details") rendered near-black on
near-black, and the poster placeholder looked like a light-theme box.

Root cause (already diagnosed — NOT re-investigated here): those widgets are
constructed with NO stylesheet at all —

    metatv/gui/details_sections.py:1250  QLabel("<b>Overview</b>")
    metatv/gui/details_sections.py:1322  QLabel("<b>Technical Details</b>")
    metatv/gui/main_window.py:809        QStatusBar()

— so instead of picking up a MetaTV theme token, they fell back to Qt's
own DEFAULT (light) palette, because nothing had ever told the running
``QApplication`` what the active theme's colors were.
``MainWindow.refresh_theme()``'s hand-maintained sweep only re-invokes
``setStyleSheet()`` on widgets it knows about — anything with no stylesheet
at all was invisible to that enumeration by construction.

The fix (metatv/gui/theme.py): ``qt_palette()`` builds a ``QPalette`` from
the CURRENTLY ACTIVE design tokens; ``apply_theme()`` now pushes it onto the
whole ``QApplication`` (and ``metatv/__main__.py`` applies it once at cold
launch) so an unstyled widget inherits correct theme colors automatically,
live — a floor underneath the explicit-stylesheet sweep, not a replacement
for it.

Covers:
1. ``QApplication.palette()`` actually reflects each named palette's tokens
   after ``theme.apply_theme(name)`` — not Qt's compiled-in defaults. This is
   the most direct proof of the fix: pre-fix, ``apply_theme()`` never calls
   ``QApplication.setPalette()`` at all, so this fails for EVERY palette (Qt's
   stock offscreen-platform defaults — Window=#efefef, WindowText=#000000 —
   never change no matter which MetaTV theme is "active").
2. A CONTRAST assertion built from the REAL unstyled widgets named in the bug
   report (``_PlotSection``'s Overview header, ``_TechnicalSection``'s header,
   and a ``QStatusBar``), parented under a widget whose ``Window`` role is
   forced to the active theme's ``COLOR_BG_SECTION`` — standing in for the
   real dark QSS chrome those widgets actually sit inside in the app — with
   ``WindowText`` left untouched so it resolves through the exact same
   QApplication-inheritance chain the real app relies on. Reuses the
   contrast helper (``_contrast``) from ``test_palette_completeness.py``
   rather than re-implementing it.

   Pre-fix this reliably measures ~1:1 contrast — Qt's stock ``WindowText``
   (#000000, black) against the forced-dark ``COLOR_BG_SECTION`` background —
   the literal "near-black on near-black" from the bug report. Post-fix it
   measures >= 4.5:1 in every palette (the label's ``WindowText`` now comes
   from ``theme.COLOR_TEXT``/``COLOR_TEXT_HI`` via the QApplication-wide
   palette push).

Verified against the pre-fix commit (before ``qt_palette()``/the
``apply_theme()`` QApplication push existed): every test in this file fails
there — see the PR body for the exact command + output.
"""

from __future__ import annotations


import pytest
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStatusBar, QWidget

from metatv.gui import theme
from metatv.gui import theme_palettes as tp

from tests.test_palette_completeness import _contrast


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_active_theme():
    """``theme.py``'s active palette is process-global module state — same
    isolation as test_theme_palettes.py / test_theme_live_refresh.py: force
    Midnight before AND after every test in this file."""
    theme.apply_theme("Midnight")
    yield
    theme.apply_theme("Midnight")


# ---------------------------------------------------------------------------
# 1. QApplication.palette() reflects the active theme's tokens
# ---------------------------------------------------------------------------

# The exact role -> token mapping qt_palette() builds, reproduced here
# independently (not by calling theme.qt_palette() itself) so this is a
# genuine behavioral check of the LIVE QApplication palette, not a tautology.
_ROLE_TOKEN: dict[QPalette.ColorRole, str] = {
    QPalette.ColorRole.Window: "COLOR_BG_SECTION",
    QPalette.ColorRole.WindowText: "COLOR_TEXT",
    # COLOR_BG_DEEP, not COLOR_LINE (#298): Base is the background of every
    # item view and text field — the results list above all — and it was
    # reading a SEPARATOR-hairline token, which painted the channel list on a
    # mid-grey slab lighter than the app around it. A resting surface must be
    # a surface token.
    QPalette.ColorRole.Base: "COLOR_BG_DEEP",
    QPalette.ColorRole.AlternateBase: "COLOR_BG_BAR",
    QPalette.ColorRole.Text: "COLOR_TEXT",
    QPalette.ColorRole.Button: "COLOR_LINE",
    QPalette.ColorRole.ButtonText: "COLOR_TEXT",
    QPalette.ColorRole.ToolTipBase: "COLOR_BG_CARD",
    QPalette.ColorRole.ToolTipText: "COLOR_TEXT_HI",
    QPalette.ColorRole.PlaceholderText: "COLOR_DISABLED",
    QPalette.ColorRole.Highlight: "COLOR_ACCENT",
    # COLOR_ON_ACCENT, not COLOR_TEXT_HI: Highlight is a solid COLOR_ACCENT
    # fill, so its foreground is the on-accent token rather than the
    # on-background text ramp (#265). Contrast itself is asserted in
    # test_palette_completeness.py.
    QPalette.ColorRole.HighlightedText: "COLOR_ON_ACCENT",
}
_DISABLED_ROLE_TOKEN: dict[QPalette.ColorRole, str] = {
    QPalette.ColorRole.WindowText: "COLOR_DISABLED",
    QPalette.ColorRole.Text: "COLOR_DISABLED",
    QPalette.ColorRole.ButtonText: "COLOR_DISABLED",
}


@pytest.mark.parametrize("palette_name", list(tp.PALETTES.keys()))
class TestQApplicationPaletteMatchesActiveTheme:
    def test_active_roles_match_tokens(self, qapp, palette_name):
        theme.apply_theme(palette_name)
        app_palette = QApplication.instance().palette()
        expected = tp.PALETTES[palette_name]

        offenders = []
        for role, token_name in _ROLE_TOKEN.items():
            actual = app_palette.color(role).name()
            want = QColor(expected[token_name]).name()
            if actual != want:
                offenders.append(f"{role}: got {actual}, expected {token_name}={want}")
        assert not offenders, f"{palette_name}: " + "; ".join(offenders)

    def test_disabled_roles_match_tokens(self, qapp, palette_name):
        theme.apply_theme(palette_name)
        app_palette = QApplication.instance().palette()
        expected = tp.PALETTES[palette_name]

        offenders = []
        for role, token_name in _DISABLED_ROLE_TOKEN.items():
            actual = app_palette.color(QPalette.ColorGroup.Disabled, role).name()
            want = QColor(expected[token_name]).name()
            if actual != want:
                offenders.append(f"{role}: got {actual}, expected {token_name}={want}")
        assert not offenders, f"{palette_name} (Disabled group): " + "; ".join(offenders)


# ---------------------------------------------------------------------------
# 2. Contrast — the real unstyled widgets from the bug report
# ---------------------------------------------------------------------------

def _themed_dark_parent(bg_value: str) -> QWidget:
    """A parent widget with ONLY its ``Window`` role explicitly forced to
    *bg_value* — everything else (``WindowText``, etc.) resolves through the
    live ``QApplication`` default, exactly mirroring how the real app's dark
    QSS containers establish a background around a widget that carries no
    stylesheet of its own. The qt_palette floor is what makes that
    resolution land on the right color; this helper isolates it.
    """
    parent = QWidget()
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(bg_value))
    parent.setPalette(pal)
    return parent


@pytest.mark.parametrize("palette_name", list(tp.PALETTES.keys()))
class TestUnstyledWidgetContrastAgainstThemedBackground:
    """The real bug: details_sections.py's Overview/Technical Details QLabels
    and main_window.py's QStatusBar carry no ``setStyleSheet()`` call at all,
    so their foreground used to come from Qt's compiled-in default
    (near-black) regardless of theme, while the real chrome around them is
    themed dark. This reproduces that exact pairing using the REAL widget
    classes, not a stand-in.
    """

    def test_details_section_header_contrast(self, qapp, palette_name):
        """The details-section headers, measured where their colour now comes from.

        This replaces two tests that reached for the unstyled
        ``<b>Overview</b>`` and ``<b>Technical Details</b>`` QLabels and read
        their inherited palette. Those labels are gone: all six details
        sections share one ``CollapsibleHeader`` whose title is a QPushButton
        with an explicit colour from ``DETAIL_SECTION_TITLE``.

        So the risk moved. It is no longer "inherits Qt's compiled-in
        near-black" — the QPalette floor those tests were written for still
        covers that class, on the widgets that still have no stylesheet. It is
        now "the token chosen for the role is unreadable on the surface it
        paints on", which is what this measures. And it covers all six headers
        at once rather than two, because there is one role behind them.
        """
        import re

        theme.apply_theme(palette_name)
        bg_value = theme.COLOR_BG_SECTION

        match = re.search(r"color:\s*(#[0-9a-fA-F]{3,8})", theme.DETAIL_SECTION_TITLE)
        assert match, "DETAIL_SECTION_TITLE sets no explicit colour"
        fg = match.group(1)

        ratio = _contrast(fg, bg_value)
        assert ratio >= 4.5, (
            f"{palette_name}: details section header foreground {fg} on "
            f"background {bg_value} contrast is {ratio:.2f}:1, below the "
            f"4.5:1 minimum"
        )

    def test_details_section_summary_contrast(self, qapp, palette_name):
        """The right-aligned count is text too, and quieter by design."""
        import re

        theme.apply_theme(palette_name)
        bg_value = theme.COLOR_BG_SECTION

        match = re.search(r"color:\s*(#[0-9a-fA-F]{3,8})", theme.DETAIL_SECTION_SUMMARY)
        assert match, "DETAIL_SECTION_SUMMARY sets no explicit colour"
        ratio = _contrast(match.group(1), bg_value)
        assert ratio >= 4.5, (
            f"{palette_name}: section summary {match.group(1)} on {bg_value} "
            f"is {ratio:.2f}:1, below 4.5:1"
        )

    def test_status_bar_contrast(self, qapp, palette_name):
        theme.apply_theme(palette_name)
        bg_value = theme.COLOR_BG_SECTION
        parent = _themed_dark_parent(bg_value)

        status_bar = QStatusBar(parent)
        status_bar.showMessage("Ready")

        fg = status_bar.palette().color(QPalette.ColorRole.WindowText).name()
        ratio = _contrast(fg, bg_value)
        assert ratio >= 4.5, (
            f"{palette_name}: QStatusBar foreground {fg} on background "
            f"{bg_value} contrast is {ratio:.2f}:1, below the 4.5:1 minimum"
        )
