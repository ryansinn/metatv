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
    muted      = _("COLOR_MUTED")
    warn       = _("COLOR_WARN")
    accent     = _("COLOR_ACCENT_BLUE")
    radius_sm  = _("RADIUS_SM")
    font_md    = _("FONT_MD")
    font_sm    = _("FONT_SM")
    font_xs    = _("FONT_XS")
    lang_fill  = _("OVERLAY_BLUE_10")
    # The one sidebar-chip geometry. Every chip role below interpolates it,
    # so a padding change is one edit and cannot land on two of three.
    chip_geom  = (
        f"border-radius: {radius_sm}; padding: 0px 5px;"
        f" font-size: {font_xs};"
    )

    return {
        # ── Sidebar group headings ───────────────────────────────────────
        # The label is the CONSTANT (it always says SERIES); the count is the
        # VARIABLE. So the count carries the emphasis — row-title size, bold,
        # on the bright ramp — while the label stays muted and small-caps and
        # does not compete with the rows it governs.
        #
        # No hue on the count: green already means "new" here (the +N badge)
        # and blue already means "interactive", so a coloured count would claim
        # a meaning it does not have. Size and value do the work instead.
        "SIDEBAR_GROUP_HEADING": (
            # COLOR_TEXT, not COLOR_MUTED. Muted measured 4.15:1 here and fails
            # the 4.5 text floor in four of six palettes — a heading is TEXT,
            # and "quiet" cannot be bought with contrast a reader needs. It
            # stays secondary the way it should: small-caps, letter-spaced and
            # a size down from the rows, against a count that is brighter and
            # larger still.
            # font-weight lives in the SHEET, not only in the QFont: the
            # heading is bold and DETAIL_SECTION_SUMMARY is not, so
            # stating it here is both true and what keeps two roles that
            # differ from resolving byte-identical.
            f"color: {text}; font-size: {font_sm}; font-weight: bold;"
            f" background: transparent;"
        ),
        "SIDEBAR_GROUP_HEADING_COUNT": (
            f"color: {text_hi}; font-size: {font_md}; font-weight: bold;"
            f" background: transparent;"
        ),
        # ── Sidebar row chips ────────────────────────────────────────────
        # Their own family, NOT the channel list's YEAR_CHIP/LANG_CHIP —
        # those are sized for a 40px list row (YEAR_CHIP is 15px type, LARGER
        # than the 13px title beside it) and they inflated a compact sidebar
        # row to 27px, which is most of the density the compact shape exists
        # to buy. Owner: "it's not a library book, it's an indicator."
        #
        # All three share ONE geometry string and are all QPushButton-scoped,
        # so there is exactly one padding to maintain. That is not tidiness:
        # the year/language chips WERE QLabels with the same declared padding
        # and still looked looser, because a QLabel's border wraps the font's
        # whole line box (ascent + descent + leading) while a QPushButton's
        # hugs content + padding. Same number, different box model, and the
        # quality chip was the only one that looked right. Owner: "seems crazy
        # to manage two different paddings this way."
        **{
            role: f"QPushButton {{ {fill} {chip_geom} }}"
            for role, fill in (
                ("SIDEBAR_CHIP_YEAR",
                 f"color: {text}; border: 1px solid {border}; background: transparent;"),
                # A TRANSPARENT border, not `none`: the border is part of the
                # box, so a chip without one is 2px shorter than its neighbours
                # and the row's chips stop lining up. Keeps the fill-only look
                # with identical metrics.
                ("SIDEBAR_CHIP_LANG",
                 f"color: {accent}; background: {lang_fill};"
                 f" border: 1px solid transparent;"),
                # The only chip in the family that is a CONTROL. Accent on an
                # accent hairline: blue already means interactive everywhere
                # else in this app, and an outline rather than a fill keeps it
                # quieter than the "+N" pill, which is news and outranks it.
                # In the family so it inherits the one geometry — a control
                # that sits in a row of chips has to BE chip-shaped.
                ("SIDEBAR_CHIP_ACTION",
                 f"color: {accent}; background: transparent;"
                 f" border: 1px solid {accent};"),
            )
        },
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
