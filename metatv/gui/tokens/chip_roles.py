"""Semantic roles for the active-filter chip line.

Roles live here rather than in ``theme.py`` for the same reason the radius and
spacing scales do: that file is over 2000 lines on a shrink-only ratchet, and a
role group is a *pure function of the tokens* — give it the token values and it
returns the stylesheet strings. Nothing about it needs to be inside the module
that happens to hold the tokens.

``theme`` merges the result into its own globals, once at import and again on
every palette switch, so ``theme.FILTER_CHIP`` resolves exactly like a role
declared inline and ``theme.style(w, "FILTER_CHIP")`` finds it.

Text colours come from the two sanctioned text roles only. ``COLOR_MUTED`` and
its siblings are pre-token greys named by appearance and clear 4.5:1 against no
app surface in any palette — they are for borders and fills, never type.
"""

from __future__ import annotations

from typing import Mapping


def build(t: Mapping[str, object]) -> dict[str, str]:
    """Compose the chip roles from the currently-bound token values.

    Args:
        t: A mapping of token name to value — in practice ``theme``'s globals.

    Returns:
        ``{role name: stylesheet string}``, ready to merge into ``theme``.
    """
    def _(name: str) -> str:
        return str(t[name])

    bg_bar     = _("COLOR_BG_BAR")
    bg_card    = _("COLOR_BG_CARD")
    line       = _("COLOR_LINE")
    border     = _("COLOR_BORDER")
    text_hi    = _("COLOR_TEXT_HI")
    text       = _("COLOR_TEXT")
    warn       = _("COLOR_WARN")
    accent     = _("COLOR_ACCENT_BLUE")
    radius_sm  = _("RADIUS_SM")
    font_md    = _("FONT_MD")

    return {
        # The strip itself. Sits on its own ground so the chips have something
        # to be distinct FROM.
        "FILTER_CHIP_BAR": (
            f"QWidget#filterChipBar {{ background: {bg_bar};"
            f" border-bottom: 1px solid {line}; }}"
        ),
        # A chip is a statement of fact about the result list, not a control to
        # hunt for, so it is quiet: surface-tinted, thin-bordered, normal
        # weight. The orange CONTEXT_FILTER_CHIP is deliberately louder — that
        # one marks a temporary, unusual state you need to notice and escape.
        "FILTER_CHIP": (
            f"QWidget {{ background: {bg_card};"
            f" border: 1px solid {border};"
            f" border-radius: {radius_sm}; }}"
        ),
        "FILTER_CHIP_LABEL": (
            f"color: {text_hi}; font-size: {font_md};"
            f" background: transparent; border: none;"
        ),
        # The × is a target, not decoration: readable at rest, and on hover it
        # takes the warning colour so it is unmistakably "this removes
        # something".
        "FILTER_CHIP_CLOSE": (
            f"QPushButton {{ color: {text}; font-size: {font_md};"
            f" background: transparent; border: none; padding: 0; }}"
            f"QPushButton:hover {{ color: {warn}; }}"
        ),
        # "+ Add filter" — the door back to the full panel. A dashed border
        # reads as "space for more", the standard add-affordance idiom, and
        # separates it from the solid chips beside it without a second colour.
        "FILTER_CHIP_ADD": (
            f"QPushButton {{ color: {accent}; font-size: {font_md};"
            f" background: transparent; border: 1px dashed {border};"
            f" border-radius: {radius_sm}; padding: 2px 8px; }}"
            f"QPushButton:hover {{ color: {text_hi};"
            f" border-color: {accent}; }}"
        ),
        "FILTER_CHIP_CLEAR": (
            f"QPushButton {{ color: {text}; font-size: {font_md};"
            f" background: transparent; border: none; padding: 2px 6px; }}"
            f"QPushButton:hover {{ color: {warn}; }}"
        ),
        # Overflow marker — chip-shaped, so the line keeps one rhythm, but
        # unfilled, because it names chips rather than being one.
        "FILTER_CHIP_OVERFLOW": (
            f"QPushButton {{ color: {text}; font-size: {font_md};"
            f" background: transparent; border: 1px solid {border};"
            f" border-radius: {radius_sm}; padding: 2px 8px; }}"
            f"QPushButton:hover {{ color: {text_hi};"
            f" border-color: {accent}; }}"
        ),
        # The empty state. Not a chip: there is nothing to remove.
        "FILTER_CHIP_EMPTY": (
            f"color: {text}; font-size: {font_md};"
            f" background: transparent; border: none;"
        ),
    }
