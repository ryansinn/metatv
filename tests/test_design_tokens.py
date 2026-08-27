"""The DTCG + Radix token layer (#295).

Owner: "let's standardize the theme palette language on something already open
and standard so we're not reinventing the wheel over and over."

Measured first, because "140 tokens is too many" turned out to be the wrong
diagnosis: the shipped set had ZERO duplicate values and ZERO single-use tokens,
and its 15 neutrals had only 2 near-identical pairs (both deliberate). It was
not padded — it was **flat**. Every value independently authored, no rule
connecting them, so a new theme meant ~140 judgement calls and no published
palette could be imported at all.

    OVERLAY_*: 39 tokens resolving to 16 base colours + hand-picked alphas
               → Radix ships alpha scales as a first-class concept
    neutrals:  luminance steps of 0/3/4/5/7/9/10/13 — hand-tuned, no rule
               → Radix's 12 steps have FIXED semantics

So: Radix scales for the ramp, DTCG (W3C) as the format, Material 3 role names
for the semantic layer. A palette now authors ~6 scale choices.

This layer is inert — it resolves tokens and nothing consumes them yet. The
bridge onto the legacy ``COLOR_*`` names is a separate slice with its own gate,
so a mis-mapped token cannot reach the app through this one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metatv.gui.tokens import radix
from metatv.gui.tokens.loader import (
    TokenResolutionError, load_tokens, palette_mode,
)

MIDNIGHT = Path(__file__).parent.parent / "metatv/gui/tokens/midnight.tokens.json"


@pytest.fixture(scope="module")
def tokens():
    return load_tokens(MIDNIGHT)


# --- the vendored data ------------------------------------------------------

def test_every_scale_has_twelve_steps():
    """Radix's contract. A short scale means a truncated vendor step."""
    scales = [n for n in dir(radix) if n.isupper() and isinstance(getattr(radix, n), tuple)]
    assert len(scales) == 60, f"expected 60 vendored scales, found {len(scales)}"
    for name in scales:
        assert len(getattr(radix, name)) == 12, f"{name} has {len(getattr(radix, name))} steps"


def test_steps_are_one_indexed_like_radix_documents_them():
    """An off-by-one here would silently shift every colour by one step."""
    assert radix.step(radix.SLATE_DARK, 1) == radix.SLATE_DARK[0]
    assert radix.step(radix.SLATE_DARK, 12) == radix.SLATE_DARK[11]
    with pytest.raises(ValueError):
        radix.step(radix.SLATE_DARK, 0)
    with pytest.raises(ValueError):
        radix.step(radix.SLATE_DARK, 13)


def test_the_dark_neutral_ramp_actually_ascends():
    """Guards the vendoring itself: dark scales run dark → light."""
    def lum(h):
        h = h.lstrip("#")
        return sum(int(h[i:i + 2], 16) for i in (0, 2, 4))
    steps = [lum(c) for c in radix.SLATE_DARK]
    assert steps == sorted(steps), "vendored dark slate is not monotonic"
    assert steps[0] < steps[-1]


# --- resolution -------------------------------------------------------------

def test_the_palette_resolves(tokens):
    assert len(tokens) >= 40
    assert tokens["surface.base"].startswith("#")
    assert tokens["on-surface.strong"].startswith("#")


def test_authoring_surface_is_scale_choices_not_values():
    """The whole point: a theme names hues, it does not pick colours.

    If literal hex starts appearing in the JSON, the flatness this replaced is
    growing back — so the count is asserted, not just discouraged.
    """
    import json
    doc = json.loads(MIDNIGHT.read_text())
    literals = [
        f"{g}.{n}"
        for g, body in doc.items()
        if not g.startswith("$") and isinstance(body, dict)
        for n, t in body.items()
        if isinstance(t, dict) and "$value" in t and not t["$value"].startswith("{")
    ]
    assert literals == [], f"palette hard-codes colours instead of referencing scales: {literals}"

    # 8 -> 16. The first number was written when a palette named a handful of
    # HUES; it now also names the SEMANTIC roles those hues serve — ok, warn,
    # err, info alongside blue, cyan, amber, red. That is the same idea one
    # level up, not the flatness this test exists to prevent: the assertion
    # above is the one that catches that, and every value in every palette is
    # still a {reference}, never a literal.
    #
    # Midnight names 14 (amber, blue, cyan, err, green, info, neutral, ok,
    # orange, primary, purple, red, teal, warn); Gruvbox names 16. A cap under
    # those would force a palette to alias a status colour onto a hue and lose
    # the ability to tune them apart, which is what the semantic names bought.
    assert len(doc["$scales"]) <= 16, (
        f"{len(doc['$scales'])} scales — a theme names hues and the roles they "
        "serve, not one entry per colour it wants"
    )


def test_alpha_steps_become_qt_safe_rgba(tokens):
    """Qt reads 8-digit hex as #AARRGGBB; Radix emits #RRGGBBAA.

    Passing those through would paint an 8%-alpha scrim as a near-opaque
    blue-grey — no error, just the wrong colour, inherited from the vendored
    data. This is the conversion that stops it.
    """
    scrim = tokens["scrim.subtle"]
    assert scrim.startswith("rgba("), f"alpha token left as {scrim!r}"
    alpha = float(scrim.rstrip(")").split(",")[-1])
    assert 0.0 < alpha < 0.2, f"subtle scrim resolved to alpha {alpha}"


def test_an_unknown_scale_raises_rather_than_falling_back(tmp_path):
    """A half-loaded theme is worse than one that refuses to load.

    A fallback colour would surface as an unreadable widget far from the cause.
    """
    bad = tmp_path / "bad.tokens.json"
    bad.write_text(
        '{"$mode":"dark","$scales":{},"surface":{"base":{"$value":"{nosuchhue.2}"}}}'
    )
    with pytest.raises(TokenResolutionError):
        load_tokens(bad)


def test_mode_must_be_dark_or_light(tmp_path):
    bad = tmp_path / "bad.tokens.json"
    bad.write_text('{"$mode":"twilight","surface":{"base":{"$value":"{slate.2}"}}}')
    with pytest.raises(TokenResolutionError):
        load_tokens(bad)


def test_midnight_is_a_dark_palette():
    assert palette_mode(MIDNIGHT) == "dark"


# --- what the tokens have to be good for ------------------------------------

def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexstr: str) -> float:
    h = hexstr.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


TEXT_ROLES = [
    "on-surface.strong", "on-surface.default", "meta.year", "meta.collection",
    "facet.language", "facet.region", "facet.genre", "facet.platform",
    "quality.4k", "quality.uhd", "primary.text", "state.ok", "state.warn",
    "state.err",
]


@pytest.mark.parametrize("role", TEXT_ROLES)
def test_text_roles_clear_the_text_floor(tokens, role):
    """4.5:1 against the surface they are read on.

    This is the failure the whole remake started from: the details rail sat at
    1.97:1 and the poster placeholder at 2.10:1, both roughly HALF the floor for
    UI chrome, because their greys were rgba() washes rather than palette
    values. Per-role floors, because a border is not text — outline.* is
    deliberately not in this list.
    """
    ratio = _contrast(tokens[role], tokens["surface.base"])
    assert ratio >= 4.5, f"{role} is {ratio:.2f}:1 on surface.base"


def test_no_two_facets_share_a_hue(tokens):
    """The mockup review caught language and platform reading as the same thing.

    Hue IS the encoding for a facet, so two facets sharing one is a false
    statement about the data.
    """
    facets = {
        k: v for k, v in tokens.items()
        if k.startswith("facet.") and not k.endswith("-fill")
    }
    seen: dict[str, str] = {}
    for name, value in facets.items():
        assert value not in seen, f"{name} and {seen[value]} are both {value}"
        seen[value] = name


def test_the_surface_ramp_ascends_and_stays_tight(tokens):
    """Dark UIs fail when their greys spread too far: the eye reads distance as
    hierarchy, implying one the content does not have."""
    ramp = [
        tokens["surface.dim"], tokens["surface.base"],
        tokens["surface.container"], tokens["surface.container-high"],
        tokens["surface.container-max"],
    ]
    lums = [_lum(c) for c in ramp]
    assert lums == sorted(lums), "surface ramp is not monotonic"
    assert _contrast(ramp[0], ramp[-1]) < 2.0, "surface ramp is too wide"


def test_a_solid_primary_fill_has_a_legible_foreground(tokens):
    """COLOR_ON_ACCENT's rule, carried over: a token drawn ON a fill needs its
    own on-fill token, never the on-background text ramp."""
    assert _contrast(tokens["primary.on"], tokens["primary.default"]) >= 4.5
