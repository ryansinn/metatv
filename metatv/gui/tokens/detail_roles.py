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
    muted     = _("COLOR_MUTED")
    text_hi   = _("COLOR_TEXT_HI")
    accent    = _("COLOR_ACCENT_BLUE")
    radius_sm = _("RADIUS_SM")
    radius_md = _("RADIUS_MD")
    line      = _("COLOR_LINE")
    font_md   = _("FONT_MD")
    font_sm   = _("FONT_SM")
    font_xs   = _("FONT_XS")
    ok        = _("COLOR_OK")

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
        # ── Sidebar rows (V3) ────────────────────────────────────────────
        # These two roles carry SIZE and background only. Both labels are
        # MiddleElideLabel, which paints itself and never consults a stylesheet
        # `color:` — the pen comes from its `color_token` argument
        # (COLOR_TEXT_HI for the title, COLOR_TEXT for the meta line). A `color:`
        # here would look like the source of truth and be silently ignored.
        "SIDEBAR_ROW_TITLE": (
            f"font-size: {font_md}; background: transparent;"
        ),
        # The second line: episode, how long left, when you watched it. One step
        # quieter than the title so a glance reads titles and a second look reads
        # state.
        "SIDEBAR_ROW_META": (
            f"font-size: {font_sm}; background: transparent;"
        ),
        # The compact row's right-edge tail — History's terse age ("2h", "3d"),
        # an EPG row's "329m left". COLOR_TEXT rather than a grey: the pre-token
        # greys clear no app surface at 4.5:1, and the smaller size is what makes
        # this subordinate, not a dimmer colour.
        # "+12 eps", "1 new" — the count on a row that has news. The OK colour
        # as TEXT, never as a fill, and always beside the ring: the ring says
        # THAT there is news, this says how much.
        "SIDEBAR_ROW_NEWS": (
            f"color: {ok}; font-size: {font_xs}; font-weight: bold;"
            f" background: transparent;"
        ),
        "SIDEBAR_ROW_TAIL": (
            f"color: {text}; font-size: {font_xs}; background: transparent;"
        ),
        # The section card. Object-name scoped so it lands on the section frame
        # and not on every descendant QFrame inside it.
        "SIDEBAR_SECTION_CARD": (
            f"QFrame#sidebarSection {{ background: {bg_card};"
            f" border: 1px solid {line};"
            f" border-radius: {radius_md}; }}"
        ),
        "DETAIL_SECTION_SUMMARY": (
            f"color: {text}; font-size: {font_sm}; background: transparent;"
        ),
    }
