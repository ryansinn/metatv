"""Every foreground/background pair the app's stylesheets set, measured.

This is the mechanical gate that was supposed to exist and did not. The suite
that was meant to stop the UI from drifting asserted token EXISTENCE, so a role
could pair a near-white text with a near-white fill and stay green — which is
exactly what happened: the view chips shipped at 1.31:1, the details Resume
button's hover at 1.04:1, and the alert rail button at 1.13:1, all invisible,
all "covered".

What it does
------------
Walks ``theme.py``'s semantic role constants, splits each into its QSS selector
blocks, and for every block that sets BOTH a fill and a text colour computes
WCAG 2.1 contrast on the pair. Blocks that set only a text colour are SKIPPED —
measuring those needs a guess about which surface the widget sits on, and a
guess is how you get a table of confident, wrong numbers.

Two things it gets right that hand-checking kept getting wrong
--------------------------------------------------------------
1. A translucent fill is composited onto the app surface BEFORE the text is
   composited onto it. Treating ``rgba(...,0.4)`` as opaque is how a 1.1:1
   button passed every previous check.
2. ``border-color`` is not read as ``color``. Without that guard the last match
   wins and a block's BORDER is measured as its TEXT — which produced several
   convincing failures for roles that were fine.

The allowlist
-------------
:data:`KNOWN_BELOW_FLOOR` records what is still below the floor, with the
measured number and why it has not been fixed. The test fails on anything NOT
in it, and ALSO fails on an entry that now passes — so the list can only
shrink, and "fixed it" cannot be claimed without deleting a line here.

The clusters in it, and what each is waiting on
-----------------------------------------------
**COLOR_MUTED as body text (11 roles, all at 3.33:1 in Daylight).** They pair
``COLOR_MUTED`` with a transparent background. ``COLOR_MUTED`` is
``{neutral.10}``, and the palette files themselves describe step 10 as "NOT
text — a disabled control (WCAG exempts these)". So either the palette's own
claim is wrong or these eleven sites are. Deciding that changes how bright a
lot of secondary UI reads, which is a design call, not a contrast fix — it is
recorded here rather than settled by whoever noticed it.

**The lightbox / trail-map family.** These sit on the deliberately fixed-dark
"cinema" backdrop, not on the app surface this test assumes, so their numbers
here are measured against the wrong thing.

That exemption was read for a while as "these are fine, we just can't measure
them", and they were NOT fine: measured against the card they actually paint
on, Daylight's Back button was 1.06:1 (invisible), its keyboard-hint chips and
poster wells were white boxes, and its state glyphs 1.24:1.
``tests/test_cinema_surface_contrast.py`` now measures the ``LIGHTBOX_*``
half against its real surface and is the authority on those roles; six entries
left this list when that fix landed, because the correct colours pass even by
this test's wrong yardstick. The ``TRAILMAP_*`` half is still un-measured — it
mixes the dark shell with genuine app-surface regions, so it needs a per-role
answer rather than a sweep.

**Poster overlays (4).** Same problem: they paint on photographs.

**The Exclusions chip (3).** ``COLOR_EXCLUSIONS_ACTIVE`` is ``{teal.9}``, one
value shared by all three palettes, and teal.9 on a light surface is 2.46:1.
The fix is a per-palette teal — but that colour is the owner's chosen brand
mark for Exclusions, so retuning it silently is not this test's call.
"""

from __future__ import annotations

import re

import pytest
from PyQt6.QtGui import QColor

from metatv.gui import theme
from metatv.gui import theme_palettes as tp

TEXT_FLOOR = 4.5

_RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)")
# (?<![-\w]) so "border-color" is not read as "color".
_DECL = re.compile(r"(?<![-\w])(background-color|background|color)\s*:\s*([^;{}]+?)\s*(?:;|$)",
                   re.MULTILINE)


#: (role, selector) -> why it is still below the floor.
#:
#: Every entry is a decision, not an oversight. Delete a line when you fix it —
#: the test fails if an allowlisted pair starts passing.
KNOWN_BELOW_FLOOR: dict[tuple[str, str], str] = {
    ("DISCOVER_REC_PILL_BTN", "QPushButton"):
        "3.19 worst palette",
    ("EXCL_CHIP_ACTIVE", "QPushButton"):
        "2.46 — needs a per-palette Exclusions teal; that colour is the owner's brand mark",
    ("EXCL_CHIP_ACTIVE", "QPushButton:hover"):
        "2.70 — needs a per-palette Exclusions teal; that colour is the owner's brand mark",
    ("EXCL_CHIP_ACTIVE", "QPushButton:pressed"):
        "2.70 — needs a per-palette Exclusions teal; that colour is the owner's brand mark",
    ("LANG_CHIP", "<bare>"):
        "3.77 worst palette",
    ("LIGHTBOX_BACK_BTN", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("LIGHTBOX_LENS_LINK", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("LIGHTBOX_NOTICE_TEXT", "<bare>"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("LIGHTBOX_BREADCRUMB_CRUMB", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("LIGHTBOX_CLOSE_BTN", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("LIGHTBOX_FOOTER_HINT", "<bare>"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("LIGHTBOX_GENRE_CHIP", "<bare>"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("LIGHTBOX_VERSION_BADGE", "<bare>"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("LIGHTBOX_VERSION_ROW", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("NAV_TOGGLE_BTN", "QPushButton:checked:hover"):
        "2.97 worst palette",
    ("POSTER_UNWATCHED_BADGE", "QPushButton"):
        "paints over POSTER ART, not an app surface — this number is not what is seen",
    ("POSTER_UNWATCHED_BADGE", "QPushButton:hover"):
        "paints over POSTER ART, not an app surface — this number is not what is seen",
    ("POSTER_WATCHED_BADGE", "QPushButton"):
        "paints over POSTER ART, not an app surface — this number is not what is seen",
    ("QA_ATTACHMENT_CHIP", "QPushButton:hover"):
        "3.01 worst palette",
    ("QA_ATTACH_BTN", "QPushButton:hover"):
        "4.28 worst palette",
    ("QA_FAIL_BTN", "QPushButton:hover"):
        "3.01 worst palette",
    ("QA_FAIL_BTN_ACTIVE", "QPushButton"):
        "3.01 worst palette",
    ("RATING_BTN", "QPushButton:hover"):
        "4.28 worst palette",
    ("RECIPE_BAR_SAVE_BTN", "QPushButton"):
        "1.39 worst palette",
    ("RECIPE_BAR_SAVE_BTN", "QPushButton:hover"):
        "1.10 worst palette",
    ("RECIPE_SAVE_BTN", "QPushButton"):
        "3.15 worst palette",
    ("RECIPE_SAVE_BTN", "QPushButton:disabled"):
        "disabled control — WCAG exempts these by definition",
    ("SAVE_BTN", "QPushButton"):
        "3.15 worst palette",
    ("SAVE_BTN", "QPushButton:disabled"):
        "disabled control — WCAG exempts these by definition",
    ("TRAILMAP_LINK_BTN", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("TRAILMAP_CLOSE_BTN", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("TRAILMAP_DETAIL_LINK_BTN", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("TRAILMAP_FAV_STAR", "QPushButton"):
        "sits on the fixed-dark cinema backdrop, not the app surface — wrong-surface measurement",
    ("VARIANT_BADGE", "<bare>"):
        "1.44 worst palette",
}


def _parse(value) -> tuple[float, float, float, float] | None:
    text = str(value).strip()
    match = _RGBA.match(text)
    if match:
        return (float(match.group(1)), float(match.group(2)), float(match.group(3)),
                float(match.group(4)) if match.group(4) else 1.0)
    color = QColor(text)
    if not color.isValid():
        return None
    return (color.red(), color.green(), color.blue(), color.alphaF())


def _over(fg, bg):
    return tuple(fg[i] * fg[3] + bg[i] * (1 - fg[3]) for i in range(3)) + (1.0,)


def _luminance(c) -> float:
    def channel(x: float) -> float:
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2])


def _contrast(fg, bg) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _blocks(qss: str):
    """(selector, declarations) for each brace block, plus any bare ones."""
    out = []
    bare = re.sub(r"[^{}]*\{[^}]*\}", "", qss)
    if bare.strip():
        out.append(("<bare>", {m.group(1): m.group(2) for m in _DECL.finditer(bare)}))
    for match in re.finditer(r"([^{}]*)\{([^}]*)\}", qss):
        out.append((match.group(1).strip() or "<bare>",
                    {d.group(1): d.group(2) for d in _DECL.finditer(match.group(2))}))
    return out


def measure(palette_name: str) -> dict[tuple[str, str], float]:
    """{(role, selector): ratio} for every self-contained pair below the floor."""
    theme.apply_theme(palette_name)
    app_bg = _parse(str(theme.COLOR_BG_SECTION))
    failures: dict[tuple[str, str], float] = {}
    for attr in sorted(n for n in dir(theme) if n.isupper()):
        qss = getattr(theme, attr)
        if not isinstance(qss, str) or "color" not in qss.lower():
            continue
        for selector, decls in _blocks(qss):
            fg_raw, bg_raw = decls.get("color"), (
                decls.get("background-color") or decls.get("background")
            )
            if not fg_raw or not bg_raw:
                continue          # needs a guess about the surface — skip it
            fg, bg = _parse(fg_raw), _parse(bg_raw)
            if fg is None or bg is None:
                continue
            bg = _over(bg, app_bg)          # a translucent fill is not its own colour
            ratio = _contrast(_over(fg, bg), bg)
            if ratio < TEXT_FLOOR:
                key = (attr, selector)
                failures[key] = min(ratio, failures.get(key, 99.0))
    return failures


@pytest.mark.parametrize("palette_name", list(tp.PALETTES))
def test_no_unlisted_stylesheet_pair_is_below_the_text_floor(qapp, palette_name):
    """The gate. A new role that pairs two colours nobody can read fails here."""
    failures = measure(palette_name)
    unlisted = {k: v for k, v in failures.items() if k not in KNOWN_BELOW_FLOOR}
    assert not unlisted, (
        f"{palette_name}: {len(unlisted)} stylesheet pair(s) below {TEXT_FLOOR}:1 "
        f"and not in KNOWN_BELOW_FLOOR — fix them, or add an entry saying why:\n"
        + "\n".join(f"  {role}  {sel}  {ratio:.2f}:1"
                    for (role, sel), ratio in sorted(unlisted.items(), key=lambda kv: kv[1]))
    )


def test_the_allowlist_only_shrinks(qapp):
    """An allowlisted pair that now passes EVERYWHERE must be deleted.

    Without this the list becomes a place where fixed things go to be forgotten,
    and it stops describing the app. It is also the only thing that makes
    "I fixed it" checkable: you cannot claim a fix without removing a line.
    """
    still_failing: set[tuple[str, str]] = set()
    for palette_name in tp.PALETTES:
        still_failing |= set(measure(palette_name))
    stale = sorted(set(KNOWN_BELOW_FLOOR) - still_failing)
    assert not stale, (
        "these are allowlisted but now pass in every palette — delete them from "
        f"KNOWN_BELOW_FLOOR:\n" + "\n".join(f"  {role}  {sel}" for role, sel in stale)
    )


@pytest.mark.parametrize("palette_name", list(tp.PALETTES))
def test_the_details_rail_and_primary_actions_are_readable(qapp, palette_name):
    """The specific roles the owner looks at most, pinned by name so a
    regression here is reported as itself rather than as a count.

    Every one of these was measurably broken (#298): the Resume button's hover
    at 1.04:1, the alert rail button at 1.13:1 resting, PANEL_BTN at 2.70:1 in
    all three palettes.
    """
    failures = measure(palette_name)
    watched = {"DETAIL_RAIL_BTN", "DETAIL_RAIL_BTN_ALERT", "DETAIL_RAIL_BTN_FAV",
               "DETAIL_RESUME_BTN", "DETAIL_PLAY_BTN", "DETAIL_QUEUE_BTN",
               "PANEL_BTN", "CLOSE_BTN", "FILTER_ONLY_BTN"}
    hit = {k: v for k, v in failures.items() if k[0] in watched}
    assert not hit, (
        f"{palette_name}: " + ", ".join(f"{r}/{s} {v:.2f}:1" for (r, s), v in hit.items())
    )
