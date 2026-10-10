"""Semantic roles for the details pane's grouped "Also available" grid.

Same arrangement as ``chip_roles.py``: a role group is a pure function of the
tokens, so it composes here and ``theme`` merges it into its own globals at
import and on every palette switch. ``theme.py`` is on a shrink-only ratchet
and does not need to hold every stylesheet in the app to own the tokens they
are built from.
"""

from __future__ import annotations

from typing import Mapping


def chip_geometry(font_md: str, radius_sm: str) -> str:
    """The metrics every outlined details-pane chip shares.

    Border WIDTH and COLOUR vary per chip (selected/dashed/hover state), so
    only the part that never varies lives here: radius, padding, font size.
    Composed into ``DETAIL_REGION_CHIP`` below AND into
    ``metatv.gui.detail_chips.chip_sheet`` — the pane's one outlined-chip
    builder — so a padding or radius change moves both instead of drifting
    into two near-identical literals the way the region grid and the
    chip toolkit were about to.

    Args:
        font_md: The resolved ``FONT_MD`` token value.
        radius_sm: The resolved ``RADIUS_SM`` token value.

    Returns:
        The shared declaration fragment (no enclosing braces, no border or
        colour) — splice it between those in the caller's own sheet.
    """
    return f"border-radius: {radius_sm}; padding: 2px 8px; font-size: {font_md};"


def build(t: Mapping[str, object]) -> dict[str, str]:
    """Compose the details-pane region roles from the bound token values."""
    def _(name: str) -> str:
        return str(t[name])

    bg_card   = _("COLOR_BG_CARD")
    bg_deep   = _("COLOR_BG_DEEP")
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
    geometry  = chip_geometry(font_md, radius_sm)

    return {
        # A region chip is a COUNT, and counts read as a grid — so every chip is
        # the same quiet shape and only the number varies. The old per-version
        # chips carried a source glyph, a resolved region name and a quality
        # tier each, which is why sixty-five of them were unreadable.
        "DETAIL_REGION_CHIP": (
            f"QPushButton {{ background: {bg_card}; color: {text_hi};"
            f" border: 1px solid {border}; {geometry} text-align: left; }}"
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
        # ── DETAILS-3a: chip toolkit + fact-provenance groups ────────────
        # Key-column labels reuse DETAIL_SECTION_SUMMARY (identical sheet — a
        # twin role here is what test_theme_role_duplication refuses).
        # A provenance band heading ("SEEN IN THE FILE", "FROM TMDB"…) —
        # small-caps-by-convention (the caller upper-cases the text), letter-
        # spaced so it reads as a section label rather than another fact.
        "DETAIL_GROUP_HEADING": (
            f"color: {text}; font-size: {font_xs}; font-weight: bold;"
            f" letter-spacing: 1px;"
        ),
        # The short "why" beside a guessed (inference) fact — "from the
        # name", "from region Sweden (SE)". Quiet TEXT at the small size, the
        # same weight as a Facts key, never facet-tinted: a guess reads at
        # the body ramp and carries its reason instead of a colour claim.
        # The thin left rule the "Details for <copy>" rows hang from (option D).
        "DETAIL_FACTS_RULE": f"#detailsRule {{ border-left: 2px solid {border}; }}",
        # A Similar row's confirmed state mark (watched ✓); the plain marks use TEXT_MD.
        "DETAIL_STATE_MARK_OK": f"font-size: {font_md}; color: {ok};",
        # Liked / disliked marks on a Similar row (shape + colour, never colour alone).
        "DETAIL_STATE_MARK_LIKED": f"font-size: {font_md}; color: {accent};",
        "DETAIL_STATE_MARK_DISLIKED": f"font-size: {font_md}; color: {_('COLOR_ACCENT_ORANGE')};",
        # The details pane's title and its adult badge.
        "DETAIL_TITLE": f"font-size: {_('FONT_4XL')}; font-weight: bold;",
        "DETAIL_ADULT_BADGE": (
            f"color: {_('COLOR_ERR_2')}; font-size: {font_md}; font-weight: 600;"
            f" background: {_('OVERLAY_ERR2_15')}; border-radius: 3px; padding: 1px 5px;"
        ),
        # A Similar row's title button (its eliding label uses SIDEBAR_ROW_TITLE).
        "DETAIL_ROW_TITLE_BTN": f"QPushButton {{ font-size: {font_md}; border: none; }}",
        "DETAIL_FACT_REASON": (
            f"color: {text}; font-size: {font_xs};"
        ),
    }
