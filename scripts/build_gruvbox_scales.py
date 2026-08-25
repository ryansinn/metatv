#!/usr/bin/env python3
"""Regenerate metatv/gui/tokens/gruvbox.py from the published Gruvbox values.

Run:  venv/bin/python scripts/build_gruvbox_scales.py > metatv/gui/tokens/gruvbox.py

Kept as a script for the same reason scripts/build_font_assets.py is: the output
is derived, and a derived file nobody can regenerate is a file nobody can safely
change. The two tunables (STEP_11_L / STEP_12_L) are why — both were set by a
failing test, not by eye, and the next person to move them needs to be able to
re-run the gates against the result.
"""
from __future__ import annotations

import colorsys

# ── The published Gruvbox values ────────────────────────────────────────────
# Twelve real Gruvbox values, taking the palette's DARKER low end (dark0 and
# the "background dark" step) rather than starting at bg0_h. Gruvbox publishes
# thirteen-plus neutrals and only twelve fit; which twelve is a choice, and this
# one is forced by contrast rather than taste. Starting at bg0_h put Gruvbox's
# bg1 (#3c3836) on the row HOVER fill — nearly twice the luminance of
# Midnight's #272a2d — and purple text could not clear 4.5:1 on it. The
# alternative was lifting every accent's text step until purple cleared, which
# is what stripped the palette's colour in the first place.
NEUTRAL = ["#0d0e0f", "#1d2021", "#242424", "#282828", "#32302f", "#3c3836",
           "#504945", "#665c54", "#7c6f64", "#928374", "#bdae93", "#ebdbb2"]
ACCENTS = {
    "GRUVRED":    ("#cc241d", "#fb4934"),
    "GRUVGREEN":  ("#98971a", "#b8bb26"),
    "GRUVYELLOW": ("#d79921", "#fabd2f"),
    "GRUVBLUE":   ("#458588", "#83a598"),
    "GRUVPURPLE": ("#b16286", "#d3869b"),
    "GRUVAQUA":   ("#689d6a", "#8ec07c"),
    "GRUVORANGE": ("#d65d0e", "#fe8019"),
}
BG = "#282828"
FG1 = "#ebdbb2"

# ── Light mode ──────────────────────────────────────────────────────────────
# Gruvbox publishes a light mode, and it is not the dark ramp reversed: the
# accents have their OWN darker alternatives (#9d0006, #79740e, #076678 …),
# which exist precisely because the bright ones are unreadable on cream. So the
# light scale takes step 9 = normal and step 10 = the published *dark*
# alternative, mirroring what the dark scale does with *bright*.
NEUTRAL_LIGHT = ["#f9f5d7", "#fbf1c7", "#f2e5bc", "#ebdbb2", "#d5c4a1", "#bdae93",
                 "#a89984", "#928374", "#7c6f64", "#665c54", "#504945", "#3c3836"]
ACCENTS_LIGHT = {
    "GRUVRED":    ("#cc241d", "#9d0006"),
    "GRUVGREEN":  ("#98971a", "#79740e"),
    "GRUVYELLOW": ("#d79921", "#b57614"),
    "GRUVBLUE":   ("#458588", "#076678"),
    "GRUVPURPLE": ("#b16286", "#8f3f71"),
    "GRUVAQUA":   ("#689d6a", "#427b58"),
    "GRUVORANGE": ("#d65d0e", "#af3a03"),
}
BG_LIGHT = "#fbf1c7"
FG1_LIGHT = "#3c3836"
# Mirror of the dark rule: text steps DARKEN, and stay above (i.e. no lighter
# than) the title's luminance so the row hierarchy holds the same way.
STEP_11_L_LIGHT, STEP_12_L_LIGHT = 0.22, 0.15

# ── Tunables, both set by a failing test ────────────────────────────────────
# High enough that a low-luminance hue still clears 4.5:1 on the SELECTION
# tint. Purple is the binding case: COLOR_ROW_PLATFORM measured 3.35:1 at 0.66
# and 4.43:1 at 0.74 — both under the floor — and clears at 0.78. This is the
# LOWEST value that passes every gate, which keeps the most headroom under the
# title's luminance ceiling below.
# Close to the published *bright* rather than far above it. Gruvbox's brights
# ARE its text colours — #fb4934 is the red you read — so pushing these to 0.78
# turned them into pastels (#fd9c91) and stripped the palette's character. With
# the selection fill now properly dark, they no longer have to be pale to be
# legible on it.
STEP_11_LUM, STEP_12_LUM = 0.300, 0.420
# ...and capped below the title's own luminance, because Gruvbox's olive green
# lightens into a yellow-green that out-shouted the row title at 12.32:1.
CEILING_FRACTION = 0.92
SAT_FLOOR = 0.45


def _hx(c):
    return tuple(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))


def _st(r, g, b):
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp(a, b, t):
    A, B = _hx(a), _hx(b)
    return _st(*(round(A[i] + (B[i] - A[i]) * t) for i in range(3)))


def _lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _hx(c)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


CEIL = _lum(FG1) * CEILING_FRACTION
# Light mode's floor is the mirror image: an accent used as text must be at
# least as dark as the title, or it out-shouts it from the other direction.
FLOOR_LIGHT = _lum(FG1_LIGHT) / CEILING_FRACTION


def _darken(c, target_l):
    """Light-mode twin of :func:`_lighten` — same saturation floor, opposite end."""
    r, g, b = (v / 255 for v in _hx(c))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    s = max(s, SAT_FLOOR)
    out = c
    while target_l < 0.95:
        rr, gg, bb = colorsys.hls_to_rgb(h, target_l, s)
        out = _st(round(rr * 255), round(gg * 255), round(bb * 255))
        if _lum(out) >= FLOOR_LIGHT:
            break
        target_l += 0.02
    return out


def _lighten(c, target_l):
    r, g, b = (v / 255 for v in _hx(c))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    s = max(s, SAT_FLOOR)
    out = c
    while target_l > 0.05:
        rr, gg, bb = colorsys.hls_to_rgb(h, target_l, s)
        out = _st(round(rr * 255), round(gg * 255), round(bb * 255))
        if _lum(out) <= CEIL:
            break
        target_l -= 0.02
    return out


# Dark-mode lightness ramp for steps 1-8, mirroring what Radix actually does.
# NOT a lerp from the grey ground toward the colour: that produces muddy
# mid-tones (gruvblue step 5 came out #364f4d) and, worse, it made
# COLOR_ROW_SELECTED_FILL a washed #324849 where Midnight's is a deep #003362.
# A pale selection fill then forced every accent's TEXT step to be lightened
# until it cleared 4.5:1 on it — and lightening a saturated hue desaturates it,
# which is how a Gruvbox palette ended up beige with a little forest green.
# Darkening in HLS keeps the hue saturated while it gets dark, exactly like
# Radix's own #0d2847 / #003362.
# Targets are LUMINANCE, not HLS lightness, and that distinction is the whole
# fix. At equal lightness a teal is far more luminous than a navy — green
# carries 0.72 of the luminance formula against blue's 0.07 — so a lightness
# ramp made gruvblue's step 4 (#194143, the row SELECTION fill) measure like a
# mid-tone while Midnight's #003362 measures genuinely dark. Purple text then
# could not clear 4.5:1 on it. Solving for luminance makes every hue land at
# the same visual depth. The ramp starts just above the app ground (#282828,
# luminance 0.021) and climbs geometrically.
# Measured off Radix's OWN dark scales — the median luminance of blue, red,
# green, amber and purple at each of steps 1-8. Matching the ladder the rest of
# the app was designed against beats inventing one: it is what makes
# COLOR_ROW_SELECTED_FILL land at the same visual depth as Midnight's #003362,
# which is what lets the accents stay saturated instead of being lightened
# until they clear contrast on a fill that was too pale.
DARK_STEP_LUM = (0.0067, 0.0095, 0.0177, 0.0269, 0.0374, 0.0562, 0.0917, 0.1508)


def _at_least_luminance(c, floor_lum):
    """*c* unchanged when it already measures at or above *floor_lum*."""
    if _lum(c) >= floor_lum:
        return c
    return _at_luminance(c, floor_lum)


def _at_luminance(c, target_lum):
    """The hue, kept saturated, adjusted until it measures *target_lum*."""
    r, g, b = (v / 255 for v in _hx(c))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    s = max(s, SAT_FLOOR)
    lo, hi = 0.0, 1.0
    out = c
    for _ in range(40):                      # bisect on lightness
        mid = (lo + hi) / 2
        rr, gg, bb = colorsys.hls_to_rgb(h, mid, s)
        out = _st(round(rr * 255), round(gg * 255), round(bb * 255))
        if _lum(out) < target_lum:
            lo = mid
        else:
            hi = mid
    return out


def accent_scale(normal, bright):
    lo = [_at_luminance(normal, t) for t in DARK_STEP_LUM]
    # A FLOOR, not a target. A single lightness target forces the worst-case
    # hue's requirement onto every hue: purple needs lifting to clear 4.5:1 on
    # the selection fill, and applying the same lift to red turned #fb4934 into
    # #fc7869. Lifting only what falls short leaves the brights that already
    # clear it exactly as Gruvbox published them.
    return lo + [normal, bright,
                 _at_least_luminance(bright, STEP_11_LUM),
                 _at_least_luminance(bright, STEP_12_LUM)]


def accent_scale_light(normal, dark):
    # Far gentler than the dark ramp's. On a cream ground these steps are
    # BACKGROUNDS and borders, and Radix light scales keep 1-5 as very pale
    # tints; the dark ramp's t-values put step 4 at #ebc97c, dark enough that
    # the light-kind surface guard rejected it outright.
    lo = [_lerp(BG_LIGHT, normal, t) for t in
          (0.03, 0.07, 0.12, 0.18, 0.26, 0.40, 0.58, 0.78)]
    return lo + [normal, dark,
                 _darken(dark, STEP_11_L_LIGHT), _darken(dark, STEP_12_L_LIGHT)]


def alpha_scale(solid):
    r, g, b = _hx(solid)
    return [f"#{r:02x}{g:02x}{b:02x}{a:02x}" for a in
            (0x00, 0x09, 0x14, 0x1d, 0x25, 0x30, 0x40, 0x5d, 0x6d, 0x7b, 0xb5, 0xef)]


def _emit(name, vals):
    print(f"{name}: tuple[str, ...] = (")
    for i in range(0, 12, 4):
        print("    " + ", ".join(f'"{v}"' for v in vals[i:i + 4]) + ",")
    print(")\n")


def main():
    print(DOC)
    print("from __future__ import annotations")
    print()
    _emit("GRUVNEUTRAL_DARK", NEUTRAL)
    _emit("GRUVNEUTRAL_A_DARK", alpha_scale(FG1))
    for name, (normal, bright) in ACCENTS.items():
        _emit(f"{name}_DARK", accent_scale(normal, bright))
        _emit(f"{name}_A_DARK", alpha_scale(bright))

    _emit("GRUVNEUTRAL_LIGHT", NEUTRAL_LIGHT)
    _emit("GRUVNEUTRAL_A_LIGHT", alpha_scale(FG1_LIGHT))
    for name, (normal, dark) in ACCENTS_LIGHT.items():
        _emit(f"{name}_LIGHT", accent_scale_light(normal, dark))
        _emit(f"{name}_A_LIGHT", alpha_scale(dark))


DOC = '''"""Gruvbox scales, in the same 12-step shape the Radix ones use.

GENERATED by scripts/build_gruvbox_scales.py — regenerate rather than hand-edit.

Gruvbox is a published palette, not a generated scale system: it defines a
neutral ramp (bg0_h -> fg1) and exactly TWO steps per accent, normal and bright.
This module maps those onto Radix's twelve steps so the existing token layer
resolves a Gruvbox palette exactly like any other — every role name, legacy_map
entry and OVERLAY_* alpha keeps working untouched.

Published values are used verbatim wherever they land:

* NEUTRAL is twelve real Gruvbox values. No interpolation at all.
* Accent step 9 is the published *normal* and step 10 the published *bright* —
  precisely the two Radix steps that mean solid fill and solid hover, which is
  what those two Gruvbox values are for.

Steps 1-8 and 11-12 are derived, because Gruvbox does not publish them. Three
things shape the derivation and every one was set by a failing test:

* 11-12 LIGHTEN the bright step in HLS with a saturation floor, rather than
  interpolating toward the cream foreground. Lerping washed the hue out —
  yellow.11 and orange.11 landed on the same pale sand and the quality chips
  stopped being tellable apart.
* Lightening is CAPPED below the title's own luminance. Gruvbox's olive green
  lightens into a yellow-green so luminous it out-shouted the row title
  (12.32:1 against the title's 11.95:1), inverting the row hierarchy.
* ...but the target is high enough that a low-luminance hue still clears AA on
  the SELECTION tint, where purple sat at 3.35:1 when the target was lower.
  The two constraints pull opposite ways, which is why they are stated as
  numbers in the generator rather than tuned by eye.

Its own module because radix.py is vendored and says DO NOT hand-edit.
"""'''


if __name__ == "__main__":
    main()
