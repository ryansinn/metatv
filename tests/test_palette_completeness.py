"""Guard test that would have caught the wave7/theme-system Daylight/Graphite
bug: Graphite shipped 96% byte-identical to Midnight (only 6 of 152 tokens
ever touched) and Daylight shipped 80% identical with 13 of 23 background/
surface tokens still dark (including the "Global Exclusions" banner, which
rendered as a dark-olive bar on a light theme).

Covers (docs/CRITICAL_RULES.md#styles-and-theme-tokens, theme_palettes.py):

1. **Same key set** — every palette defines exactly the same token names,
   asserted both directions (no palette missing a key another defines, no
   palette carrying an extra one).
2. **Kind declaration** — ``theme_palettes.PALETTE_KIND`` names every palette
   "light" or "dark", covering exactly the palettes in ``PALETTES``.
3. **Background/surface luminance** — every ``*_BG*``/``*SURFACE*`` token
   averages > 0.65 relative luminance in a light palette, < 0.35 in a dark
   one, EXCEPT a small, individually-justified set of tokens that are
   deliberately theme-invariant BY DESIGN (see ``_STRUCTURAL_EXEMPT`` below
   for the reasoning per token) — this is the single assertion that makes a
   copy-paste-and-never-convert miss impossible to ship silently again.
4. **Distinctness** — no two palettes share more than 40% of their token
   values; the failure message reports the actual shared percentage so a
   future regression is self-explaining.
5. **Contrast** — primary body text on the primary app background is at
   least 4.5:1 in every palette.
6. **Quality-chip family stays mutually distinguishable** in every palette
   (COLOR_QUALITY_UHD/FHD/HD/RAW/LIVE) — the owner explicitly likes this hue
   system, and #3/#4 wouldn't by themselves catch two quality colours
   converging to the same (or a visually-indistinguishable) value.

Every assertion names the offending token(s) and value(s) on failure — no
bare ``assert False``.
"""

from __future__ import annotations

import re

import pytest

from metatv.gui import theme_palettes as tp

# ---------------------------------------------------------------------------
# Colour parsing / luminance / contrast helpers (relative luminance per the
# brief: 0.299R + 0.587G + 0.114B on a 0-1 scale — a documented, acceptable
# simplification of the full WCAG formula for this guard's purposes).
# ---------------------------------------------------------------------------

_NAMED = {
    "gray": (128, 128, 128),
    "lightgray": (211, 211, 211),
    "gold": (255, 215, 0),
    "white": (255, 255, 255),
}


def _parse_rgb(value: str) -> tuple[int, int, int]:
    v = value.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", v)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if v in _NAMED:
        return _NAMED[v]
    raise ValueError(f"Cannot parse colour token value: {value!r}")


def _luminance(value: str) -> float:
    r, g, b = _parse_rgb(value)
    return 0.299 * (r / 255) + 0.587 * (g / 255) + 0.114 * (b / 255)


def _contrast(value_a: str, value_b: str) -> float:
    la, lb = _luminance(value_a), _luminance(value_b)
    la, lb = max(la, lb), min(la, lb)
    return (la + 0.05) / (lb + 0.05)


# ---------------------------------------------------------------------------
# 1. Every palette defines exactly the same key set (both directions)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", list(tp.PALETTES.keys()))
def test_palette_key_set_matches_every_other_palette(palette_name):
    this_keys = set(tp.PALETTES[palette_name].keys())
    for other_name, other_palette in tp.PALETTES.items():
        if other_name == palette_name:
            continue
        other_keys = set(other_palette.keys())
        missing = other_keys - this_keys
        extra = this_keys - other_keys
        assert not missing and not extra, (
            f"{palette_name!r} vs {other_name!r} key-set mismatch — "
            f"{palette_name} is missing {sorted(missing)} and has extra "
            f"{sorted(extra)}"
        )


# ---------------------------------------------------------------------------
# 2. Kind declaration
# ---------------------------------------------------------------------------

def test_every_palette_declares_a_kind():
    assert set(tp.PALETTE_KIND.keys()) == set(tp.PALETTES.keys()), (
        f"PALETTE_KIND covers {sorted(tp.PALETTE_KIND)} but PALETTES defines "
        f"{sorted(tp.PALETTES)} — every palette must declare its kind"
    )
    bad = {name: kind for name, kind in tp.PALETTE_KIND.items() if kind not in ("light", "dark")}
    assert not bad, f"PALETTE_KIND values must be 'light' or 'dark', got: {bad}"


# ---------------------------------------------------------------------------
# 3. Background/surface luminance per declared kind
# ---------------------------------------------------------------------------

# Tokens that are deliberately theme-invariant (same literal value in every
# palette, light or dark) despite matching the *_BG*/*SURFACE* name pattern —
# each one individually justified by a real call-site dependency, not just
# "we forgot to convert it":
#
#   COLOR_BG_DEEP, COLOR_LIGHTBOX_BG, COLOR_LIGHTBOX_HEADER
#       The Similar-Titles lightbox / Explore trail-map "cinema" backdrop —
#       always dark, in every palette, by design (theme_palettes.py module
#       docstring). COLOR_BG_DEEP additionally does double duty as a fixed
#       DARK TEXT colour on chips that always have a bright/coloured fill
#       (theme.py QUEUE_MATCHED_NEW_TAG, TRAILMAP_HERE_TAG) — lightening it
#       for a light palette would make that badge text illegible.
#
#   COLOR_SURFACE_LIGHT, COLOR_SURFACE_LIGHT_2, COLOR_SURFACE_LIGHT_3
#       A fixed-light "highlight chip" surface family (filter_bar.py /
#       sports_filter_bar.py) — always light, in every palette, by design;
#       the inverse case of the lightbox family above.
#
#   COLOR_MOOD_LIKE_BG, COLOR_MOOD_CURIOUS_BG, COLOR_MOOD_NOTFORME_BG,
#   COLOR_MOOD_DISLIKE_BG, COLOR_MOOD_TRASH_BG, COLOR_MOOD_WATCH_BG,
#   COLOR_MOOD_EXPLORE_BG
#       Self-contained FILLED badge chips (category_picker_dialog.py's mood
#       bar + quick-pick chips) — each pairs its own saturated fill with
#       either a dedicated per-palette foreground already tuned for THAT
#       exact fill (LIKE/CURIOUS/NOTFORME/EXPLORE have their own _FG token)
#       or a themed/brand foreground that already adapts correctly (DISLIKE
#       pairs with the themed COLOR_TEXT_HI, which goes dark in a light
#       palette automatically; TRASH/WATCH pair with the theme-invariant
#       brand accents COLOR_RED_BRIGHT/COLOR_ACCENT_BLUE_2). Like a coloured
#       status pill in most design systems, these are meant to stay
#       recognisable regardless of the app shell's overall darkness, not
#       track it — confirmed empirically: even MIDNIGHT (the blessed,
#       "pixel-identical to today" baseline) fails a blanket <0.35 rule on
#       these four medium-bright fills, so the rule is provably too strict
#       for this family rather than these values being a bug.
_STRUCTURAL_EXEMPT: frozenset[str] = frozenset({
    "COLOR_BG_DEEP", "COLOR_LIGHTBOX_BG", "COLOR_LIGHTBOX_HEADER",
    "COLOR_SURFACE_LIGHT", "COLOR_SURFACE_LIGHT_2", "COLOR_SURFACE_LIGHT_3",
    "COLOR_MOOD_LIKE_BG", "COLOR_MOOD_CURIOUS_BG", "COLOR_MOOD_NOTFORME_BG",
    "COLOR_MOOD_DISLIKE_BG", "COLOR_MOOD_TRASH_BG", "COLOR_MOOD_WATCH_BG",
    "COLOR_MOOD_EXPLORE_BG",
})


def _bg_surface_tokens(palette: dict) -> dict[str, str]:
    return {
        k: v for k, v in palette.items()
        if isinstance(v, str) and ("_BG" in k or "SURFACE" in k) and k not in _STRUCTURAL_EXEMPT
    }


@pytest.mark.parametrize("palette_name", list(tp.PALETTES.keys()))
def test_background_surface_tokens_match_declared_kind(palette_name):
    palette = tp.PALETTES[palette_name]
    kind = tp.PALETTE_KIND[palette_name]
    tokens = _bg_surface_tokens(palette)
    assert tokens, f"no *_BG*/*SURFACE* tokens found in {palette_name} — pattern regressed"

    if kind == "light":
        offenders = {k: v for k, v in tokens.items() if _luminance(v) <= 0.65}
        assert not offenders, (
            f"{palette_name} is declared 'light' but these background/surface "
            f"tokens are too dark (luminance <= 0.65): "
            + ", ".join(f"{k}={v} (lum={_luminance(v):.3f})" for k, v in sorted(offenders.items()))
        )
    else:
        offenders = {k: v for k, v in tokens.items() if _luminance(v) >= 0.35}
        assert not offenders, (
            f"{palette_name} is declared 'dark' but these background/surface "
            f"tokens are too light (luminance >= 0.35): "
            + ", ".join(f"{k}={v} (lum={_luminance(v):.3f})" for k, v in sorted(offenders.items()))
        )


# ---------------------------------------------------------------------------
# 4. Distinctness — no two palettes share more than 40% of their values
# ---------------------------------------------------------------------------

def _shared_fraction(a: dict, b: dict) -> tuple[float, list[str]]:
    keys = sorted(set(a.keys()) & set(b.keys()))
    same = [k for k in keys if a[k] == b[k]]
    return (len(same) / len(keys) if keys else 0.0), same


@pytest.mark.parametrize(
    "name_a,name_b",
    [
        (a, b)
        for i, a in enumerate(tp.PALETTES)
        for b in list(tp.PALETTES)[i + 1:]
    ],
)
def test_palettes_are_mutually_distinct(name_a, name_b):
    frac, same = _shared_fraction(tp.PALETTES[name_a], tp.PALETTES[name_b])
    pct = frac * 100
    assert frac <= 0.40, (
        f"{name_a!r} and {name_b!r} share {pct:.1f}% of their token values "
        f"(limit 40%) — {len(same)} identical tokens, including: "
        + ", ".join(same[:15]) + (" ..." if len(same) > 15 else "")
    )


# ---------------------------------------------------------------------------
# 5. Contrast — primary text on primary background
# ---------------------------------------------------------------------------

# COLOR_TEXT is the standard body-text token; COLOR_BG_SECTION is the base
# app surface (sidebar/channel-list section background) — the most
# representative "primary text on primary background" pair in the app.
_PRIMARY_TEXT_TOKEN = "COLOR_TEXT"
_PRIMARY_BG_TOKEN = "COLOR_BG_SECTION"


@pytest.mark.parametrize("palette_name", list(tp.PALETTES.keys()))
def test_primary_text_contrast_at_least_4_5(palette_name):
    palette = tp.PALETTES[palette_name]
    text_val = palette[_PRIMARY_TEXT_TOKEN]
    bg_val = palette[_PRIMARY_BG_TOKEN]
    ratio = _contrast(text_val, bg_val)
    assert ratio >= 4.5, (
        f"{palette_name}: {_PRIMARY_TEXT_TOKEN}={text_val} on "
        f"{_PRIMARY_BG_TOKEN}={bg_val} has contrast {ratio:.2f}:1, "
        f"below the 4.5:1 minimum"
    )


# ---------------------------------------------------------------------------
# 6. Quality-chip family stays mutually distinguishable in every palette
# ---------------------------------------------------------------------------

_QUALITY_TOKENS = (
    "COLOR_QUALITY_UHD", "COLOR_QUALITY_FHD", "COLOR_QUALITY_HD",
    "COLOR_QUALITY_RAW", "COLOR_QUALITY_LIVE",
)


@pytest.mark.parametrize("palette_name", list(tp.PALETTES.keys()))
def test_quality_chip_family_mutually_distinguishable(palette_name):
    """4K/FHD/HD/RAW/LIVE badges must never converge to the same (or a
    perceptually indistinguishable) colour — the owner explicitly likes this
    hue system, so a threshold check alone (which a generated value could
    pass while still collapsing two hues together) isn't enough here.
    """
    palette = tp.PALETTES[palette_name]
    values = {name: palette[name] for name in _QUALITY_TOKENS}

    # No two tokens may share a literal value.
    seen: dict[str, str] = {}
    dupes = []
    for name, val in values.items():
        if val in seen:
            dupes.append(f"{name}={val} same as {seen[val]}")
        seen[val] = name
    assert not dupes, f"{palette_name}: quality chip colours collided: {dupes}"

    # No two tokens may be so close in relative luminance AND hue that they'd
    # read as the same colour at a glance — guard against a "technically
    # different, visually identical" generated value.
    import colorsys
    hsl = {}
    for name, val in values.items():
        r, g, b = _parse_rgb(val)
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        hsl[name] = (h, s, l)

    names = list(values)
    close_pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ha, sa, la = hsl[a]
            hb, sb, lb = hsl[b]
            hue_dist = min(abs(ha - hb), 1 - abs(ha - hb))  # circular hue distance
            if hue_dist < 0.04 and abs(la - lb) < 0.08:
                close_pairs.append(f"{a}={values[a]} vs {b}={values[b]}")
    assert not close_pairs, (
        f"{palette_name}: these quality chip pairs are too close in hue/"
        f"lightness to stay mutually distinguishable: {close_pairs}"
    )
