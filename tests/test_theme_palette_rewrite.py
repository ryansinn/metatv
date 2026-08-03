"""Composed stylesheets must switch theme too (#284).

``theme.style()``/``style_fn()`` fixed the widgets that opted in, but ~370 call
sites still build a stylesheet with an f-string and hand it straight to
``setStyleSheet``.  Qt caches the RENDERED string, so every one of those keeps
painting the previous palette after a switch — the owner's report that list
backgrounds stayed dark under light chrome.

Converting them individually is ~300 edits spread over every screen, each an
opportunity for a late-binding closure bug, and it would only cover the sites
that existed on the day it was done.  So instead ``apply_theme`` computes what
each colour VALUE became and rewrites those substrings wherever they survive: a
sheet built from ``COLOR_BG`` literally contains ``COLOR_BG``'s old value, no
matter which expression produced it.

The interesting tests here are the ones about what it must NOT rewrite.  A blind
find-and-replace over every widget's stylesheet is exactly the kind of fix that
looks complete and quietly corrupts the things that were pinned on purpose.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from metatv.gui import theme as _theme


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_theme():
    original = _theme.current_theme()
    yield
    _theme.apply_theme(original)


class TestComposedSheetsSwitch:

    def test_an_fstring_stylesheet_follows_the_theme(self, qapp):
        """The bug, stated plainly: this widget never opted in to anything."""
        _theme.apply_theme("Midnight")
        w = QLabel()
        w.setStyleSheet(f"background: {_theme.COLOR_BG_CARD}; color: {_theme.COLOR_TEXT};")
        midnight = w.styleSheet()

        _theme.apply_theme("Daylight")

        assert w.styleSheet() != midnight, (
            "a composed stylesheet kept the Midnight colours under the Daylight "
            "palette — this is the reported defect"
        )
        assert _theme.COLOR_BG_CARD in w.styleSheet()
        assert _theme.COLOR_TEXT in w.styleSheet()

    def test_it_survives_a_round_trip(self, qapp):
        _theme.apply_theme("Midnight")
        w = QLabel()
        w.setStyleSheet(f"background: {_theme.COLOR_BG_CARD};")
        original = w.styleSheet()

        _theme.apply_theme("Daylight")
        _theme.apply_theme("Midnight")

        assert w.styleSheet() == original, "not reversible — colours drifted"

    def test_a_multi_token_sheet_updates_every_colour(self, qapp):
        _theme.apply_theme("Midnight")
        w = QLabel()
        w.setStyleSheet(
            f"QLabel {{ background: {_theme.COLOR_BG_CARD}; color: {_theme.COLOR_TEXT_HI}; "
            f"border: 1px solid {_theme.COLOR_BORDER}; }}"
        )

        _theme.apply_theme("Daylight")
        sheet = w.styleSheet()

        for token in ("COLOR_BG_CARD", "COLOR_TEXT_HI", "COLOR_BORDER"):
            assert getattr(_theme, token) in sheet, f"{token} was left stale"

    def test_structural_values_are_untouched(self, qapp):
        """Only colours move. Padding and radii are layout, not palette."""
        _theme.apply_theme("Midnight")
        w = QLabel()
        w.setStyleSheet(f"padding: 6px 12px; border-radius: 4px; color: {_theme.COLOR_TEXT};")

        _theme.apply_theme("Daylight")

        assert "padding: 6px 12px" in w.styleSheet()
        assert "border-radius: 4px" in w.styleSheet()


class TestWhatItRefusesToRewrite:
    """The guards. Without these, a global search-and-replace silently corrupts."""

    def test_an_ambiguous_value_is_skipped_not_guessed(self):
        """Two tokens sharing an old value that diverge have no single answer."""
        mapping = _theme._build_palette_rewrite_map(
            before={"COLOR_A": "#111111", "COLOR_B": "#111111"},
            after={"COLOR_A": "#222222", "COLOR_B": "#333333"},
        )
        assert "#111111" not in mapping, (
            "guessed between two different new values for one old value"
        )

    def test_a_theme_invariant_value_is_never_rewritten(self):
        """Mood chips, COLOR_QUALITY_*, and the lightbox family are pinned on
        purpose — they sit over photographic posters. If a variable token
        happened to share their value, rewriting it would re-theme the thing
        that was deliberately held fixed."""
        mapping = _theme._build_palette_rewrite_map(
            before={"COLOR_BG": "#0a0a0a", "COLOR_LIGHTBOX_BG": "#0a0a0a"},
            after={"COLOR_BG": "#ffffff", "COLOR_LIGHTBOX_BG": "#0a0a0a"},
        )
        assert "#0a0a0a" not in mapping, (
            "would have re-themed an invariant token that shares this value"
        )

    def test_an_unchanged_value_produces_no_entry(self):
        mapping = _theme._build_palette_rewrite_map(
            before={"COLOR_A": "#123456"}, after={"COLOR_A": "#123456"},
        )
        assert mapping == {}

    def test_a_short_hex_does_not_match_inside_a_longer_one(self, qapp):
        """#fff must not rewrite the first half of #ffffff."""
        _theme.apply_theme("Midnight")
        w = QLabel()
        w.setStyleSheet("color: #ffffff; background: #fff;")

        _theme._rewrite_stale_palette_values({"#fff": "#000"})

        assert "#ffffff" in w.styleSheet(), "clobbered a longer hex value"
        assert "background: #000" in w.styleSheet()

    def test_the_longest_value_wins(self, qapp):
        """An rgba() containing a hex substring must be replaced as a whole."""
        _theme.apply_theme("Midnight")
        w = QLabel()
        w.setStyleSheet("background: rgba(10, 10, 10, 0.5);")

        _theme._rewrite_stale_palette_values({
            "rgba(10, 10, 10, 0.5)": "rgba(255, 255, 255, 0.5)",
            "10, 10": "99, 99",
        })

        assert w.styleSheet() == "background: rgba(255, 255, 255, 0.5);"


class TestItDoesNotBreakTheSweep:

    def test_a_widget_with_no_stylesheet_is_skipped(self, qapp):
        _theme.apply_theme("Midnight")
        plain = QLabel()
        assert plain.styleSheet() == ""

        _theme.apply_theme("Daylight")

        assert plain.styleSheet() == ""

    def test_a_dead_widget_does_not_stop_the_pass(self, qapp):
        from PyQt6 import sip

        _theme.apply_theme("Midnight")
        doomed = QLabel()
        doomed.setStyleSheet(f"color: {_theme.COLOR_TEXT};")
        survivor = QLabel()
        survivor.setStyleSheet(f"color: {_theme.COLOR_TEXT};")
        sip.delete(doomed)

        _theme.apply_theme("Daylight")

        assert _theme.COLOR_TEXT in survivor.styleSheet(), (
            "a deleted sibling stopped the rewrite before reaching this widget"
        )

    def test_an_empty_map_is_a_no_op(self, qapp):
        w = QLabel()
        w.setStyleSheet("color: #abcdef;")
        assert _theme._rewrite_stale_palette_values({}) == 0
        assert w.styleSheet() == "color: #abcdef;"
