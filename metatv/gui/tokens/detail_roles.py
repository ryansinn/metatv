"""Semantic roles for the details pane's grouped "Also available" grid.

Same arrangement as ``chip_roles.py``: a role group is a pure function of the
tokens, so it composes here and ``theme`` merges it into its own globals at
import and on every palette switch. ``theme.py`` is on a shrink-only ratchet
and does not need to hold every stylesheet in the app to own the tokens they
are built from.
"""

from __future__ import annotations

from typing import Mapping


def build(t: Mapping[str, object]) -> dict[str, str]:
    """Compose the details-pane region roles from the bound token values."""
    def _(name: str) -> str:
        return str(t[name])

    bg_card   = _("COLOR_BG_CARD")
    border    = _("COLOR_BORDER")
    text_hi   = _("COLOR_TEXT_HI")
    text      = _("COLOR_TEXT")
    accent    = _("COLOR_ACCENT_BLUE")
    radius_sm = _("RADIUS_SM")
    font_md   = _("FONT_MD")
    font_sm   = _("FONT_SM")

    return {
        # A region chip is a COUNT, and counts read as a grid — so every chip is
        # the same quiet shape and only the number varies. The old per-version
        # chips carried a source glyph, a resolved region name and a quality
        # tier each, which is why sixty-five of them were unreadable.
        "DETAIL_REGION_CHIP": (
            f"QPushButton {{ background: {bg_card}; color: {text_hi};"
            f" border: 1px solid {border}; border-radius: {radius_sm};"
            f" font-size: {font_md}; padding: 2px 8px; text-align: left; }}"
            f"QPushButton:hover {{ border-color: {accent}; }}"
        ),
        # "+ 7 more" and "‹ All regions" — navigation, not data, so they read as
        # links rather than as another chip in the grid.
        "DETAIL_REGION_LINK": (
            f"QPushButton {{ background: transparent; color: {accent};"
            f" border: none; font-size: {font_md}; padding: 2px 6px; }}"
            f"QPushButton:hover {{ color: {text_hi}; }}"
        ),
        # "65 versions · 19 regions", right of the section heading.
        "DETAIL_REGION_SUMMARY": (
            f"color: {text}; font-size: {font_sm};"
        ),
        # ── Section headers ──────────────────────────────────────────────
        # The chevron is a target, so it is legible at rest rather than
        # revealing itself on hover: unlike a Play button on one row of
        # eighteen, there are six of these and each one is the only way into
        # its section.
        "DETAIL_SECTION_CHEVRON": (
            f"QPushButton {{ color: {text}; background: transparent;"
            f" border: none; padding: 0; }}"
            f"QPushButton:hover {{ color: {text_hi}; }}"
        ),
        # A button, not a label: the WORDS toggle too, not just the 20px
        # chevron. Styled to read as a heading — the affordance is the cursor
        # and the hover, not a button frame.
        "DETAIL_SECTION_TITLE": (
            f"QPushButton {{ color: {text_hi}; font-size: {font_md};"
            f" font-weight: bold; background: transparent; border: none;"
            f" padding: 0; text-align: left; }}"
            f"QPushButton:hover {{ color: {accent}; }}"
        ),
        "DETAIL_SECTION_SUMMARY": (
            f"color: {text}; font-size: {font_sm}; background: transparent;"
        ),
    }
