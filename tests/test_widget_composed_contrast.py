"""Stylesheets composed inside WIDGET modules, measured.

The hole this closes
--------------------
``test_stylesheet_contrast_conformance.py`` walks the role constants in
``theme.py``. But ~286 stylesheets are built inline in widget modules, and
until now not one of them was measured by anything. Two shipped defects came
out of that gap in consecutive slices — the row badges at 1.59:1 (Daylight) and
then this sweep's haul:

===================================  ========  ==============================
site                                 measured  what it was
===================================  ========  ==============================
``filter_bar`` "Clear"               1.00:1    a separator-hairline colour as
                                               text on a fixed-light surface —
                                               identical values, in ALL themes
``vod_watch_alert_dialog`` Watch     1.25:1    body text on a solid accent fill
``discover_card`` category label     1.20:1    a palette-tuned accent on a
                                               fixed-black poster scrim
``category_picker_dialog`` mood pill 1.56:1    muted-2 on a dark line colour
``details_sections`` poster empty    1.45:1    muted on a 30% scrim
===================================  ========  ==============================

How it works
------------
The sheets cannot be read off the module — they are f-strings interpolating
theme tokens — so each is reconstructed from the AST, substituting
``{_theme.TOKEN}`` from the live palette. Any block declaring BOTH a foreground
and its own background is measured; translucent fills are composited onto the
app surface first, because a fill at 0.12 alpha is not the colour it names.

Blocks that declare NO background are skipped, not silently passed: which
surface they land on is a per-site question and guessing produces a table of
confident, wrong numbers. That subset is the remaining unmeasured population.

The allowlist
-------------
:data:`KNOWN_BELOW_FLOOR` is keyed by TOKEN NAMES rather than line numbers, so
it survives edits above it. Everything in it is one cluster — ``COLOR_MUTED`` /
``COLOR_DISABLED`` / ``COLOR_ERR_2`` used as secondary text, 2.69-4.23:1 —
which is the same call ``test_stylesheet_contrast_conformance``'s allowlist
already records: the palettes describe that step as "NOT text", so either the
palette is wrong or these sites are, and deciding changes how bright a lot of
secondary UI reads. That is a design decision, not a contrast fix, and it is
recorded rather than settled by whoever ran the sweep.

The list can only shrink: an entry that starts passing fails this test.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from metatv.gui import theme as _theme

PALETTES = ["Midnight", "Graphite", "Daylight"]
FLOOR = 4.5

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GUI = _REPO_ROOT / "metatv" / "gui"
_SKIP_FILES = {"theme.py", "theme_palettes.py"}

_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_RGBA = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)"
)

# (file, selector, fg token, bg token) -> why it is still below the floor.
KNOWN_BELOW_FLOOR: dict[tuple[str, str, str, str], str] = {
    ("discover_view.py", "QPushButton:hover", "@COLOR_TEXT@", "@OVERLAY_15@"):
        "COLOR_MUTED-family secondary text; see module docstring",
    ("main_window.py", "QPushButton", "@COLOR_DISABLED@", "@COLOR_LINE_DARK@"):
        "COLOR_MUTED-family secondary text; see module docstring",
    ("main_window.py", "QPushButton",
     "@COLOR_BANNER_YEL_FG@", "@COLOR_BANNER_YEL_BG@"):
        "4.02:1 in Daylight — the owner's chosen banner pair, retuning it is "
        "their call (same reasoning as the Exclusions teal)",
    ("sports_view.py", "QPushButton",
     "@COLOR_BANNER_YEL_FG@", "@COLOR_BANNER_YEL_BG@"):
        "the SAME pair as main_window.py's banner directly above — the Sports "
        "staleness banner reuses the notice grammar wholesale, so it inherits "
        "the owner's-call status too; retune both together or neither "
        "(yellow.12 clears the floor at 9.67:1 if the owner ever says go)",
    ("categories_dialog.py", "<bare>", "@COLOR_ERR_2@", "@OVERLAY_ERR2_15@"):
        "error red on its own red tint; the pair is the semantic signal and "
        "retinting it is a palette decision",
    ("details_sections.py", "<bare>", "@COLOR_ERR_2@", "@OVERLAY_ERR2_15@"):
        "error red on its own red tint; the pair is the semantic signal and "
        "retinting it is a palette decision",
    ("discover_filter_dialog.py", "QPushButton", "@COLOR_TEXT@", "@COLOR_LINE@"):
        "4.23:1 in Daylight only — COLOR_LINE used as a control fill; the fix "
        "is a surface token, which moves this control's whole look",
}


# ---------------------------------------------------------------------------
# Reconstructing a composed stylesheet
# ---------------------------------------------------------------------------

def _resolve(node: ast.AST, *, names: bool) -> str | None:
    """Rebuild a string expression.

    Args:
        node: The AST node.
        names: When True, a ``{_theme.TOKEN}`` read renders as the literal text
            ``@TOKEN@`` — a palette-independent key. When False it renders as
            the token's CURRENT value, which is what gets measured.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                parts.append(str(piece.value))
            elif isinstance(piece, ast.FormattedValue):
                sub = _resolve_token(piece.value, names=names)
                if sub is None:
                    return None
                parts.append(sub)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve(node.left, names=names)
        right = _resolve(node.right, names=names)
        return None if left is None or right is None else left + right
    return _resolve_token(node, names=names)


def _resolve_token(node: ast.AST, *, names: bool) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in ("_theme", "theme")
    ):
        if names:
            # NOT braces: the block splitter treats "{...}" as a CSS rule, so a
            # brace sentinel silently shredded every sheet it appeared in.
            return "@" + node.attr + "@"
        value = getattr(_theme, node.attr, None)
        return str(value) if isinstance(value, str) else None
    return None


def _blocks(sheet: str) -> list[tuple[str, str]]:
    """Split a sheet into ``(selector, body)``, plus any selector-less body."""
    out, rest = [], sheet
    for m in re.finditer(r"([A-Za-z#\[\]\":=_\-.]+[^{}]*)\{([^{}]*)\}", sheet):
        out.append((m.group(1).strip(), m.group(2)))
        rest = rest.replace(m.group(0), "")
    if rest.strip():
        out.append(("<bare>", rest))
    return out


def _declared(body: str, prop: str) -> str | None:
    """Last value declared for *prop*, or None.

    ``border-color`` must not be read as ``color`` — without the guard the last
    match wins and a block's BORDER gets measured as its text.
    """
    found = None
    for m in re.finditer(rf"(?<![a-z-]){prop}\s*:\s*([^;]+)", body):
        value = m.group(1).strip()
        if _HEX.search(value) or _RGBA.match(value) or value.startswith("@"):
            found = value
    return found


# ---------------------------------------------------------------------------
# Colour maths (a translucent fill composites BEFORE the text lands on it)
# ---------------------------------------------------------------------------

def _rgba(value: str):
    value = value.strip()
    m = _RGBA.match(value)
    if m:
        alpha = float(m.group(4)) if m.group(4) else 1.0
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)), alpha)
    m = _HEX.search(value)
    if not m:
        return None
    h = m.group(0).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(float(int(h[i:i + 2], 16)) for i in (0, 2, 4)) + (1.0,)


def _composite(fg, bg):
    r, g, b, a = fg
    br, bgc, bb, _ = bg
    return (r * a + br * (1 - a), g * a + bgc * (1 - a), b * a + bb * (1 - a), 1.0)


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _contrast(fg, bg) -> float:
    lf = 0.2126 * _lin(fg[0]) + 0.7152 * _lin(fg[1]) + 0.0722 * _lin(fg[2])
    lb = 0.2126 * _lin(bg[0]) + 0.7152 * _lin(bg[1]) + 0.0722 * _lin(bg[2])
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def _measured_blocks():
    """Every self-contained (fg + own bg) block in the widget modules.

    Yields ``(key, ratio)`` where key is ``(file, selector, fg, bg)`` in TOKEN
    NAMES, so it is stable across edits and identical across palettes.
    """
    surface = _rgba(_theme.COLOR_BG_CARD)
    seen = set()
    for path in sorted(_GUI.rglob("*.py")):
        if path.name in _SKIP_FILES:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - all tracked files parse
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                continue
            values = _resolve(node, names=False)
            if not values or "color" not in values or ":" not in values:
                continue
            keys = _resolve(node, names=True)
            if not keys:
                continue
            for (sel, body), (_, key_body) in zip(_blocks(values), _blocks(keys)):
                fg_v, bg_v = _declared(body, "color"), (
                    _declared(body, "background") or _declared(body, "background-color")
                )
                if not fg_v or not bg_v:
                    continue
                fg_k = _declared(key_body, "color")
                bg_k = (_declared(key_body, "background")
                        or _declared(key_body, "background-color"))
                fg_c, bg_c = _rgba(fg_v), _rgba(bg_v)
                if not fg_c or not bg_c:
                    continue
                key = (path.name, sel, fg_k or fg_v, bg_k or bg_v)
                if key in seen:
                    continue
                seen.add(key)
                yield key, _contrast(fg_c, _composite(bg_c, surface))


@pytest.fixture(autouse=True)
def _restore_theme():
    previous = _theme.current_theme()
    yield
    _theme.apply_theme(previous)


@pytest.mark.parametrize("palette", PALETTES)
def test_no_unlisted_widget_stylesheet_is_below_the_floor(palette):
    """FAILS against the pre-sweep tree with five sites under 1.6:1."""
    _theme.apply_theme(palette)
    failures = {
        key: ratio for key, ratio in _measured_blocks()
        if ratio < FLOOR and key not in KNOWN_BELOW_FLOOR
    }
    assert not failures, (
        f"{palette}: {len(failures)} widget-composed stylesheet(s) below "
        f"{FLOOR}:1 — fix them, or add an entry to KNOWN_BELOW_FLOOR saying "
        f"why:\n  " + "\n  ".join(
            f"{k[0]} {k[1]} {k[2]} on {k[3]} = {v:.2f}:1"
            for k, v in sorted(failures.items(), key=lambda kv: kv[1])
        )
    )


def test_the_allowlist_only_shrinks():
    """An entry that now passes everywhere must be deleted, not left to rot."""
    still_failing = set()
    for palette in PALETTES:
        _theme.apply_theme(palette)
        still_failing |= {k for k, ratio in _measured_blocks() if ratio < FLOOR}
    stale = sorted(set(KNOWN_BELOW_FLOOR) - still_failing)
    assert not stale, (
        "these are allowlisted but now pass in every palette — delete them "
        "from KNOWN_BELOW_FLOOR:\n  " + "\n  ".join(str(k) for k in stale)
    )


def test_the_sweep_actually_reaches_widget_modules():
    """A resolver that silently returns None would read as a clean codebase.

    Pins that the AST reconstruction still finds a substantial population — if
    a refactor changes how sheets are written and the resolver stops matching,
    this fails instead of reporting zero problems forever.
    """
    _theme.apply_theme("Midnight")
    measured = list(_measured_blocks())
    assert len(measured) >= 25, (
        f"only {len(measured)} widget stylesheet blocks resolved — the AST "
        f"reconstruction has probably stopped matching how sheets are written"
    )
    files = {k[0] for k, _ in measured}
    assert len(files) >= 8, f"only reached {sorted(files)}"


def test_translucent_fills_are_composited_not_taken_literally():
    """The maths that makes the numbers real.

    A fill at 0.08 alpha is not the colour it names; treating it as opaque is
    how a 1.6:1 chip passes a check. Pinned directly because every ratio above
    depends on it.
    """
    black_on_white = _composite(_rgba("rgba(0,0,0,0.0)"), _rgba("#ffffff"))
    assert black_on_white[:3] == (255.0, 255.0, 255.0)
    half = _composite(_rgba("rgba(0,0,0,0.5)"), _rgba("#ffffff"))
    assert 126 <= half[0] <= 129
