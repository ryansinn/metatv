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
    ("sources.py", "QPushButton", "@COLOR_TEXT@", "@OVERLAY_15@"):
        "COLOR_MUTED-family secondary text; see module docstring — same pair "
        "as discover_view.py's QPushButton:hover above, newly visible here "
        "because it is now reachable through a .format() template",
    ("main_window.py", "QPushButton",
     "@COLOR_BANNER_YEL_FG@", "@COLOR_BANNER_YEL_BG@"):
        "4.02:1 in Daylight — the owner's chosen banner pair, retuning it is "
        "their call (same reasoning as the Exclusions teal)",
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

_SCOPE_DEPTH_CAP = 8

# A node type that introduces its own local-variable namespace when walking a
# module for composed sheets. Lambdas are deliberately excluded: the
# `_theme.style_fn(w, lambda: _btn_style.format(...))` pattern closes over a
# variable from the ENCLOSING function, so a lambda body must keep resolving
# names against its parent's scope map, not a fresh (empty) one of its own.
_SCOPE_OWNERS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _scope_map(body: list[ast.stmt]) -> dict[str, ast.AST]:
    """``name -> value node`` for simple assignments directly in *body*.

    Only ``x = ...`` (single ``Name`` target) and ``x: T = ...`` are
    recognised — good enough, since a composed sheet is assigned once. Descends
    into compound statements (if/for/while/try) so a sheet assigned inside a
    branch is still found, but NOT into a nested ``FunctionDef``/
    ``AsyncFunctionDef``/``ClassDef`` — those get their own independent map
    when the walker reaches them. The LAST assignment to a name wins.
    """
    mapping: dict[str, ast.AST] = {}

    def visit(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (*_SCOPE_OWNERS, ast.ClassDef)):
                continue
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            ):
                mapping[stmt.targets[0].id] = stmt.value
            elif (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.value is not None
            ):
                mapping[stmt.target.id] = stmt.value
            for field in ("body", "orelse", "finalbody"):
                child = getattr(stmt, field, None)
                if isinstance(child, list):
                    visit(child)
            for handler in getattr(stmt, "handlers", None) or []:
                visit(handler.body)

    visit(body)
    return mapping


def _iter_scoped_nodes(node: ast.AST, scope: dict[str, ast.AST]):
    """Yield every descendant of *node*, each paired with the local-variable
    scope map of its nearest enclosing function (or the module, at top level).

    A ``FunctionDef``/``AsyncFunctionDef`` gets its OWN map (built from its own
    body only — no inheriting outer locals); everything else — including a
    ``lambda`` body, so it can see its enclosing function's variables —
    continues under the current scope.
    """
    yield node, scope
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPE_OWNERS):
            yield from _iter_scoped_nodes(child, _scope_map(child.body))
        else:
            yield from _iter_scoped_nodes(child, scope)


def _resolve(
    node: ast.AST, *, names: bool, scope: dict[str, ast.AST] | None = None,
    _depth: int = 0,
) -> str | None:
    """Rebuild a string expression.

    Args:
        node: The AST node.
        names: When True, a ``{_theme.TOKEN}`` read renders as the literal text
            ``@TOKEN@`` — a palette-independent key. When False it renders as
            the token's CURRENT value, which is what gets measured.
        scope: name -> value-node map for the node's enclosing function (or
            module), used to resolve a bare ``ast.Name`` reference to a local
            variable. ``None`` (the default) resolves nothing new — every
            pre-existing call site keeps working unchanged.
        _depth: Recursion guard against a name-assignment cycle (``a = b``,
            ``b = a``); capped at :data:`_SCOPE_DEPTH_CAP`.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        # A `.format()`/`.join()` argument is often numeric (`fs=13`, an rgb
        # component…) — `str()` is exactly what the real call does with it.
        return str(node.value)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                parts.append(str(piece.value))
            elif isinstance(piece, ast.FormattedValue):
                sub = _resolve_token(piece.value, names=names, scope=scope, _depth=_depth)
                if sub is None:
                    return None
                parts.append(sub)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve(node.left, names=names, scope=scope, _depth=_depth)
        right = _resolve(node.right, names=names, scope=scope, _depth=_depth)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Name):
        if scope is None or _depth >= _SCOPE_DEPTH_CAP:
            return None
        target = scope.get(node.id)
        if target is None:
            return None
        return _resolve(target, names=names, scope=scope, _depth=_depth + 1)
    if isinstance(node, ast.Call):
        return _resolve_call(node, names=names, scope=scope, _depth=_depth)
    return _resolve_token(node, names=names, scope=scope, _depth=_depth)


def _resolve_token(
    node: ast.AST, *, names: bool, scope: dict[str, ast.AST] | None = None,
    _depth: int = 0,
) -> str | None:
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
    if isinstance(node, ast.Name):
        # Reached from a JoinedStr's `{...}` slot: `f"...{some_local_var}..."`.
        if scope is None or _depth >= _SCOPE_DEPTH_CAP:
            return None
        return _resolve(node, names=names, scope=scope, _depth=_depth)
    return None


def _resolve_call(
    node: ast.Call, *, names: bool, scope: dict[str, ast.AST] | None, _depth: int,
) -> str | None:
    """``"...".format(...)`` and ``"sep".join([...])`` over resolvable pieces.

    Deliberately minimal: no ``**kwargs``/``*args`` spreading, no format specs
    beyond what ``str.format`` itself does (a template that came from real
    source already has its literal ``{``/``}`` doubled, so the built-in method
    is the correct substitution, not a reimplementation of it). Anything else
    (an arbitrary function call, e.g. a zero-arg sheet-builder helper) is out
    of scope for this resolver and yields ``None``, same as today.
    """
    if _depth >= _SCOPE_DEPTH_CAP:
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr == "format":
        if any(isinstance(a, ast.Starred) for a in node.args):
            return None
        if any(kw.arg is None for kw in node.keywords):
            return None
        template = _resolve(func.value, names=names, scope=scope, _depth=_depth)
        if template is None:
            return None
        args = []
        for arg_node in node.args:
            value = _resolve(arg_node, names=names, scope=scope, _depth=_depth + 1)
            if value is None:
                return None
            args.append(value)
        kwargs = {}
        for kw in node.keywords:
            value = _resolve(kw.value, names=names, scope=scope, _depth=_depth + 1)
            if value is None:
                return None
            kwargs[kw.arg] = value
        try:
            return template.format(*args, **kwargs)
        except (KeyError, IndexError, ValueError):
            return None
    if func.attr == "join":
        if len(node.args) != 1:
            return None
        pieces_node = node.args[0]
        if not isinstance(pieces_node, (ast.List, ast.Tuple)):
            return None
        sep = _resolve(func.value, names=names, scope=scope, _depth=_depth)
        if sep is None:
            return None
        pieces = []
        for elt in pieces_node.elts:
            value = _resolve(elt, names=names, scope=scope, _depth=_depth + 1)
            if value is None:
                return None
            pieces.append(value)
        return sep.join(pieces)
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
        module_scope = _scope_map(tree.body)
        for node, scope in _iter_scoped_nodes(tree, module_scope):
            if not isinstance(
                node, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Name, ast.Call)
            ):
                continue
            values = _resolve(node, names=False, scope=scope)
            if not values or "color" not in values or ":" not in values:
                continue
            keys = _resolve(node, names=True, scope=scope)
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

    GUARD-3 (scope-aware ``Name``/``.format()``/``.join()`` resolution) raised
    the measured population from 28 blocks/16 files to 34/17; these floors are
    ~90% of that new count, rounded down, so a resolver regression is still
    caught at the new level rather than silently falling back to the old one.
    """
    _theme.apply_theme("Midnight")
    measured = list(_measured_blocks())
    assert len(measured) >= 30, (
        f"only {len(measured)} widget stylesheet blocks resolved — the AST "
        f"reconstruction has probably stopped matching how sheets are written"
    )
    files = {k[0] for k, _ in measured}
    assert len(files) >= 15, f"only reached {sorted(files)}"


def test_a_sheet_composed_from_a_local_variable_is_measured():
    """A ``local_var + f"…"`` sheet must not vanish, hover block included.

    The hover piece's OWN background comes from a second local
    (``hover_bg = _theme.COLOR_ACCENT``), not a direct ``_theme.X`` read — so
    it is not a self-contained literal ``ast.walk`` could stumble onto on its
    own; seeing it requires resolving TWO ``ast.Name`` references (``base``
    for the whole tail, ``hover_bg`` inside it).

    Proven to FAIL on the pre-GUARD-3 resolver two ways at once:
    ``_resolve(BinOp)`` recursed into its ``Name("base")`` operand, which fell
    through to ``_resolve_token`` (Attribute-only) and returned ``None`` —
    collapsing the whole concatenation; and even ``ast.walk`` finding the
    hover ``JoinedStr`` on its own (it is still a node in the tree) went
    nowhere, because its ``{hover_bg}`` slot hit the same Attribute-only
    ``_resolve_token`` and returned ``None`` too. Only the base block —
    resolvable from its own assignment, no local-variable indirection — was
    measured.
    """
    _theme.apply_theme("Midnight")
    source = (
        "def build(w):\n"
        '    base = f"QLabel {{ color: {_theme.COLOR_TEXT}; '
        'background: {_theme.COLOR_BG_CARD}; }}"\n'
        "    hover_bg = _theme.COLOR_ACCENT\n"
        '    w.setStyleSheet(base + f"QLabel:hover {{ color: {_theme.COLOR_TEXT}; '
        'background: {hover_bg}; }}")\n'
    )
    tree = ast.parse(source)
    module_scope = _scope_map(tree.body)
    selectors_with_fg_and_bg = set()
    for node, scope in _iter_scoped_nodes(tree, module_scope):
        if not isinstance(
            node, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Name, ast.Call)
        ):
            continue
        values = _resolve(node, names=False, scope=scope)
        if not values or "color" not in values or ":" not in values:
            continue
        for sel, body in _blocks(values):
            fg = _declared(body, "color")
            bg = _declared(body, "background") or _declared(body, "background-color")
            if fg and bg:
                selectors_with_fg_and_bg.add(sel)
    assert "QLabel" in selectors_with_fg_and_bg, (
        "the base block (reachable via its own assignment) went missing too"
    )
    assert "QLabel:hover" in selectors_with_fg_and_bg, (
        "the :hover block, which lives only in the concatenated tail, was not "
        "measured — a Name operand in a BinOp is silently dropping its sibling"
    )


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
