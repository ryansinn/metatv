"""Every icon-only button says what it does.

The rule ("all clickable/icon-only controls need ``setToolTip()``") had no
mechanical check, so it held only as well as anyone remembered it. Sweeping for
it turned up five controls with no tooltip at all — a button whose entire label
is a glyph and which offers no other explanation:

- the three collapse toggles in the details pane (Plot, Cast & Crew, Tags),
- the group expander in the filter panel,
- the notification dismiss ✕,
- the two URL reorder arrows in the source editor, where the order IS the
  failover priority and the arrow alone does not say that.

What counts as icon-only
------------------------
A ``QPushButton``/``QToolButton`` whose label argument is an ``icons.*`` read, a
``config.*_icon`` read, or a short string with no alphanumerics (a bare glyph).
A button labelled ``f"{icon} Play"`` is NOT icon-only — it already says what it
does — so it is not swept. The point is controls where the glyph is the only
information the user gets.

Sibling of ``test_cursor_affordance.py``: same class of rule (an affordance
every clickable owes the user), same mechanical treatment.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GUI = _REPO_ROOT / "metatv" / "gui"

_BUTTON_TYPES = {"QPushButton", "QToolButton"}

# A control that is genuinely unlabelled-but-obvious, or whose tooltip is set by
# a shared factory the AST cannot follow to its construction site.
_EXEMPT: dict[tuple[str, str], str] = {}


def _is_icon_only(node: ast.AST) -> bool:
    """Is this label argument a bare glyph, with no words in it?"""
    if isinstance(node, ast.Attribute):
        base = node.value
        if isinstance(base, ast.Name) and base.id in ("_icons", "icons"):
            return True
        if node.attr.endswith("_icon"):
            return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value.strip()
        return bool(text) and len(text) <= 3 and not re.search(r"[A-Za-z0-9]", text)
    return False


def _assigned_name(tree: ast.AST, call: ast.Call) -> str | None:
    """The attribute/variable a construction is assigned to, if any."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.value is call:
            target = node.targets[0]
            if isinstance(target, ast.Attribute):
                return target.attr
            if isinstance(target, ast.Name):
                return target.id
    return None


def _icon_only_buttons() -> list[tuple[Path, int, str | None, str]]:
    """(path, lineno, assigned name, source line) for each icon-only button."""
    out = []
    for path in sorted(_GUI.rglob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _BUTTON_TYPES
                and node.args
                and _is_icon_only(node.args[0])
            ):
                continue
            out.append((
                path, node.lineno, _assigned_name(tree, node),
                lines[node.lineno - 1].strip(),
            ))
    return out


def test_every_icon_only_button_has_a_tooltip() -> None:
    """FAILS against the pre-fix tree with the five controls listed above."""
    offenders = []
    for path, lineno, name, line in _icon_only_buttons():
        key = (path.name, name or "")
        if key in _EXEMPT:
            continue
        source = path.read_text()
        if name:
            # Set anywhere in the file, on that name — construction and the
            # tooltip are often a few lines apart, and for a TOGGLE the tooltip
            # is deliberately set in the handler that flips the glyph.
            found = re.search(
                rf"(self\.)?{re.escape(name)}\.setToolTip\(", source
            )
        else:
            window = "\n".join(source.splitlines()[lineno - 1: lineno + 8])
            found = "setToolTip" in window
        if not found:
            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line[:88]}")
    assert not offenders, (
        "an icon-only button gives the user nothing but a glyph — add "
        "setToolTip() saying what it does:\n  " + "\n  ".join(sorted(set(offenders)))
    )


def test_the_sweep_actually_finds_icon_only_buttons() -> None:
    """A matcher that finds nothing reads as a clean codebase forever."""
    found = _icon_only_buttons()
    assert len(found) >= 15, (
        f"only {len(found)} icon-only buttons matched — the detector has "
        f"probably stopped recognising how they are constructed"
    )


def test_a_labelled_button_is_not_swept() -> None:
    """``f"{icon} Play"`` already says what it does; only bare glyphs are owed
    a tooltip, and over-sweeping would push people to add noise."""
    labelled = ast.parse('b = QPushButton(f"{_icons.play_icon} Play")')
    call = labelled.body[0].value
    assert not _is_icon_only(call.args[0])

    glyph = ast.parse("b = QPushButton(_icons.close_icon)")
    assert _is_icon_only(glyph.body[0].value.args[0])

    bare = ast.parse('b = QPushButton("✕")')
    assert _is_icon_only(bare.body[0].value.args[0])


def test_a_collapse_toggle_keeps_its_tooltip_truthful(qapp_free=None) -> None:
    """A toggle's tooltip must be set where the GLYPH flips, not once at build.

    A tip reading "Collapse this section" under an expand arrow is worse than
    none — it is confidently wrong half the time. Asserted on the source
    because the alternative (constructing three details-pane sections) buys no
    extra confidence about where the call sits.
    """
    source = (_GUI / "details_sections.py").read_text()
    tree = ast.parse(source)
    applies = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_apply"
    ]
    toggling = [
        fn for fn in applies
        if "_toggle_btn.setText" in (ast.get_source_segment(source, fn) or "")
    ]
    assert toggling, "no glyph-flipping _apply() found — has the shape changed?"
    for fn in toggling:
        body = ast.get_source_segment(source, fn) or ""
        assert "_toggle_btn.setToolTip" in body, (
            f"_apply() at line {fn.lineno} flips the toggle glyph without "
            f"updating its tooltip — the tip will contradict the arrow"
        )
