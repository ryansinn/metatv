"""Regression guard: no hand-typed glyphs in ``metatv/gui/**/*.py``.

``icons.py`` is the single source of truth for every icon/emoji/symbol the app
shows (CLAUDE.md, "Icons — always from ``metatv/gui/icons.py``"), and that rule
had no mechanical check. So two close glyphs shipped side by side —
``main_window.py`` built its context-filter dismiss button as
``QPushButton("✕")`` (U+2715) while ``icons.close_icon`` is ``"×"`` (U+00D7),
and every other close in the app used the second one. Nothing could see that,
because nothing was looking.

Three shapes, all AST-based (a glyph in a comment or a docstring — including
this one — is fine, and the guard must not be defeatable by rewrapping a line):

(a) a button constructed with a bare glyph literal — ``QPushButton("✕")``;
(b) ``.setText(<bare glyph literal>)`` on a name constructed as a button in
    the same module — the "toggle badge" shape, which is also the one the
    factory replaces with ``icon_utils.set_button_icon(btn, role)``;
(c) any string literal, anywhere in a widget's visible label, that is a
    hand-typed copy of a glyph ``icons.py`` already names. This is the
    "second close glyph" case: the literal and the constant drift apart and
    nobody can tell which is canonical.

Scope of (c) — why not every literal equal to an icon value
-----------------------------------------------------------
Some ``icons.py`` values are ordinary typography that widget code legitimately
types inline: ``·`` (``playback_neutral_icon``, also the meta separator in
forty-odd labels), ``—`` (``mood_none_icon``, also an em dash and an
empty-value placeholder), ``•``, and ``×`` (also multiplication, as in
"played 3×"). Sweeping those produced 130 hits, essentially all of them
correct prose — an allowlist that size is not a guard, it is a second copy of
the codebase. So (c) matches only PICTOGRAPHIC glyphs (Unicode category
``So``/``Sk``: ✓ ✗ ● ▼ 📌 …), which have no reading as text. The bare-glyph
shapes (a) and (b) still catch ``✕``, ``…`` and friends in a button label
whatever their Unicode category, which is where a stray glyph actually hurts.

The allowlist ``tests/stray_glyph_literals_allowlist.json`` is SHRINK-ONLY:
``_ALLOWLIST_CEILING`` is the number of entries allowed, and it is 0. Adding
an entry means raising that number in this file — a visible decision in the
diff, not a quiet append.
"""

from __future__ import annotations

import ast
import json
import re
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GUI = _REPO_ROOT / "metatv" / "gui"
_ICONS = _GUI / "icons.py"
_ALLOWLIST_PATH = Path(__file__).resolve().parent / "stray_glyph_literals_allowlist.json"

#: Entries allowed in the allowlist. Shrink-only: raising it is a reviewed edit.
_ALLOWLIST_CEILING = 0

_BUTTON_TYPES = {"QPushButton", "QToolButton"}

#: Calls whose string arguments end up on screen as a widget's own label.
_LABEL_METHODS = {
    "setText", "setPlaceholderText", "setTitle", "setWindowTitle",
    "addItem", "insertItem", "addTab", "append",
}

#: Unicode categories that are pictographs rather than typography. See the
#: module docstring for why ``Po``/``Pd``/``Sm`` are deliberately excluded.
_PICTOGRAPH_CATEGORIES = {"So", "Sk"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _defined_glyphs() -> dict[str, str]:
    """Every module-level ``<name>_icon = "<glyph>"`` in ``icons.py``.

    Read from the AST rather than by importing, so the guard has no Qt or
    import-order dependency and cannot be affected by a runtime theme.
    """
    tree = ast.parse(_ICONS.read_text())
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        value = node.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.endswith("_icon") and value.value:
                out.setdefault(value.value, target.id)
    return out


def _is_bare_glyph(text: str) -> bool:
    """A short symbol with no words in it — the whole label is the picture."""
    stripped = text.strip()
    return bool(stripped) and len(stripped) <= 3 and not re.search(r"[A-Za-z0-9]", stripped)


def _is_pictographic(glyph: str) -> bool:
    """True for ✓ ● ▼ 📌 …; False for · — • × and other typography."""
    return bool(glyph) and all(
        unicodedata.category(ch) in _PICTOGRAPH_CATEGORIES
        or ord(ch) > 0x1F000  # emoji planes: category So already, but be explicit
        for ch in glyph
        if ch not in "️︎"  # variation selectors carry no category meaning
    )


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _button_names(tree: ast.AST) -> set[str]:
    """Names/attributes assigned a ``QPushButton``/``QToolButton`` construction."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in _BUTTON_TYPES
        ):
            continue
        name = _target_name(node.targets[0])
        if name:
            names.add(name)
    return names


def _label_constants(call: ast.Call) -> list[ast.Constant]:
    """String constants this call puts on screen as a widget label.

    Covers both a widget constructor's arguments and the ``setText``-family
    methods, and looks INSIDE f-strings — ``QPushButton(f"{prefix} ×")`` hides
    its glyph from a plain-constant scan.
    """
    func = call.func
    is_label_call = (
        (isinstance(func, ast.Name) and func.id.startswith("Q"))
        or (isinstance(func, ast.Attribute) and func.attr in _LABEL_METHODS)
    )
    if not is_label_call:
        return []
    out: list[ast.Constant] = []
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg)
        elif isinstance(arg, ast.JoinedStr):
            out.extend(
                piece for piece in arg.values
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
            )
    return out


def _gui_modules() -> list[Path]:
    return [p for p in sorted(_GUI.rglob("*.py")) if p != _ICONS]


def _load_allowlist() -> dict[str, str]:
    if not _ALLOWLIST_PATH.exists():
        return {}
    data = json.loads(_ALLOWLIST_PATH.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def scan(root: Path | None = None) -> dict[str, list[str]]:
    """Every stray-glyph violation under *root*, grouped by rule.

    Exposed as a function (rather than inlined into the tests) so the same
    scan can be pointed at a pre-fix checkout to prove the guard fails there.
    """
    gui = (root / "metatv" / "gui") if root else _GUI
    icons_path = gui / "icons.py"
    tree = ast.parse(icons_path.read_text())
    glyphs: dict[str, str] = {}
    for node in tree.body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign)
            else node.targets if isinstance(node, ast.Assign) else []
        )
        value = getattr(node, "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
            for target in targets:
                if isinstance(target, ast.Name) and target.id.endswith("_icon"):
                    glyphs.setdefault(value.value, target.id)

    found: dict[str, list[str]] = {"construction": [], "settext": [], "copy": []}
    for path in sorted(gui.rglob("*.py")):
        if path == icons_path:
            continue
        source = path.read_text()
        try:
            module = ast.parse(source)
        except SyntaxError:  # pragma: no cover - a syntax error is its own failure
            continue
        lines = source.splitlines()
        rel = path.relative_to(root or _REPO_ROOT)
        buttons = _button_names(module)

        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue

            # (a) QPushButton("✕")
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in _BUTTON_TYPES
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and _is_bare_glyph(node.args[0].value)
            ):
                found["construction"].append(
                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()[:88]}"
                )

            # (b) btn.setText("⌄")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "setText"
                and _target_name(node.func.value) in buttons
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and _is_bare_glyph(node.args[0].value)
            ):
                found["settext"].append(
                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()[:88]}"
                )

            # (c) a hand-typed copy of a glyph icons.py already names
            for const in _label_constants(node):
                glyph = const.value.strip()
                if glyph in glyphs and _is_pictographic(glyph):
                    found["copy"].append(
                        f"{rel}:{const.lineno}: {glyph!r} is icons.{glyphs[glyph]} — "
                        f"{lines[const.lineno - 1].strip()[:70]}"
                    )
    for key in found:
        found[key] = sorted(set(found[key]))
    return found


# ---------------------------------------------------------------------------
# The live guard
# ---------------------------------------------------------------------------


def test_no_button_is_constructed_from_a_bare_glyph_literal() -> None:
    """Rule (a). ``main_window.py`` shipped ``QPushButton("✕")`` this way."""
    allowed = _load_allowlist()
    offenders = [v for v in scan()["construction"] if v.split(":")[0] not in allowed]
    assert not offenders, (
        "a button's label is a hand-typed glyph — build it with "
        "icon_utils.icon_button(role, tooltip) instead:\n  " + "\n  ".join(offenders)
    )


def test_no_button_swaps_its_glyph_with_a_setText_literal() -> None:
    """Rule (b). A toggle swaps its ICON now: ``set_button_icon(btn, role)``."""
    allowed = _load_allowlist()
    offenders = [v for v in scan()["settext"] if v.split(":")[0] not in allowed]
    assert not offenders, (
        "a button's glyph is swapped by setText() with a literal — use "
        "icon_utils.set_button_icon(btn, role):\n  " + "\n  ".join(offenders)
    )


def test_no_label_hand_types_a_glyph_icons_py_already_names() -> None:
    """Rule (c). Two spellings of one icon is how the second close glyph shipped."""
    allowed = _load_allowlist()
    offenders = [v for v in scan()["copy"] if v.split(":")[0] not in allowed]
    assert not offenders, (
        "a visible label hand-types a glyph icons.py already defines — read the "
        "constant so there is one spelling:\n  " + "\n  ".join(offenders)
    )


def test_the_allowlist_only_shrinks() -> None:
    """An append must be a reviewed edit to ``_ALLOWLIST_CEILING``, not a habit."""
    entries = _load_allowlist()
    assert len(entries) <= _ALLOWLIST_CEILING, (
        f"{len(entries)} allowlist entries against a ceiling of "
        f"{_ALLOWLIST_CEILING} — this list is shrink-only"
    )
    for key, reason in entries.items():
        assert reason.strip(), f"allowlist entry {key!r} has no reason"


# ---------------------------------------------------------------------------
# The detector itself — a matcher that finds nothing reads as a clean tree
# ---------------------------------------------------------------------------


def test_icons_py_defines_a_real_glyph_table() -> None:
    """Rule (c) is only worth anything if the reference set is populated."""
    glyphs = _defined_glyphs()
    assert len(glyphs) >= 80, f"only {len(glyphs)} icon glyphs parsed out of icons.py"
    assert glyphs.get("×") == "close_icon"


def test_the_bare_glyph_predicate_matches_what_it_should() -> None:
    """A glyph is the label; a word is not."""
    for glyph in ("✕", "×", "…", "⌄", "▲", "-"):
        assert _is_bare_glyph(glyph), glyph
    for text in ("Play", "▶ Play", "OK", "", "   ", "← Back"):
        assert not _is_bare_glyph(text), text


def test_the_pictograph_filter_keeps_typography_out() -> None:
    """The 130-hit sweep the module docstring describes, held at bay."""
    for glyph in ("✓", "✗", "●", "▼", "📌", "🚫"):
        assert _is_pictographic(glyph), glyph
    for typography in ("·", "—", "•", "×", "+", ">", "‹"):
        assert not _is_pictographic(typography), typography


def test_the_scan_recognises_all_three_pre_fix_shapes(tmp_path) -> None:
    """Point the real scanner at a synthetic pre-fix tree; it must flag all three.

    This is what stops the guard rotting into a function that always returns
    an empty list — the live tests above are all assertions that nothing was
    found, which a broken detector satisfies perfectly.
    """
    gui = tmp_path / "metatv" / "gui"
    gui.mkdir(parents=True)
    (gui / "icons.py").write_text('close_icon: str = "×"\nwatched_icon: str = "✓"\n')
    (gui / "widget.py").write_text(
        "def build(self):\n"
        '    dismiss = QPushButton("✕")\n'          # (a)
        '    dismiss.setText("⌄")\n'                 # (b)
        '    self.badge.setText(f"✓ {count}")\n'     # (c)
        "    return dismiss\n"
    )
    found = scan(tmp_path)
    assert found["construction"], "rule (a) missed QPushButton('✕')"
    assert found["settext"], "rule (b) missed a setText glyph swap on a button"
    assert found["copy"], "rule (c) missed a hand-typed copy of icons.watched_icon"
