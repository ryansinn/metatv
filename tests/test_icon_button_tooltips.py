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

ICON-1 added two more shapes the original sweep could not see, because the
shared ``icon_utils`` factory moved the glyph OFF the constructor call:

- ``icon_button(role, tooltip, ...)`` — the tooltip is a direct positional
  argument now, not something to hunt for in the surrounding source.
- ``QPushButton()``/``QToolButton()`` built bare, with the glyph applied a few
  lines later via ``setIcon(...)``/``set_button_icon(...)`` **in the same
  function**. This is exactly the shape a naive migration off the OLD
  ``QPushButton(icons.x_icon)`` form produces, and it is invisible to the
  constructor-argument sweep above: the constructor call itself carries no
  icon-ish literal any more, so a button that lost its tooltip in the same
  edit that moved the icon off the constructor would silently drop out of
  this sweep entirely, rather than failing it.

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


def _name_of(node: ast.AST) -> str | None:
    """The attribute/variable name a target expression refers to."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _is_icon_button_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == "icon_button")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "icon_button")
    )


def _is_set_icon_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr == "setIcon":
        return True
    if (
        (isinstance(node.func, ast.Name) and node.func.id == "set_button_icon")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "set_button_icon")
    ):
        return True
    return False


def _set_icon_target(node: ast.Call) -> str | None:
    """The button name a setIcon()/set_button_icon() call paints, or None."""
    if isinstance(node.func, ast.Attribute) and node.func.attr == "setIcon":
        return _name_of(node.func.value)
    # set_button_icon(btn, role, ...) / _icon_utils.set_button_icon(btn, role, ...)
    if node.args:
        return _name_of(node.args[0])
    return None


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


def _button_names_constructed_in(fn: ast.AST) -> set[str]:
    """Names/attrs assigned a bare ``QPushButton()``/``QToolButton()`` inside *fn*."""
    names: set[str] = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _BUTTON_TYPES
        ):
            name = _assigned_name(fn, node)
            if name:
                names.add(name)
    return names


def _icon_only_buttons() -> list[tuple[Path, int, str | None, str]]:
    """(path, lineno, assigned name, source line) for each icon-only button.

    Three shapes feed this, all described in the module docstring: a
    constructor-argument glyph (the original sweep), a bare construction
    whose icon is painted via setIcon()/set_button_icon() in the SAME
    function, and an ``icon_button(role, tooltip, ...)`` factory call.
    """
    out: list[tuple[Path, int, str | None, str]] = []
    for path in sorted(_GUI.rglob("*.py")):
        if path.name == "icon_utils.py":
            continue  # the factory's own definitions, not a call site
        source = path.read_text()
        tree = ast.parse(source)
        lines = source.splitlines()

        # Shape 1: QPushButton(<icon-ish literal>)
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

        # Shape 2: bare QPushButton()/QToolButton(), icon painted later via
        # setIcon()/set_button_icon() in the SAME function.
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            button_names = _button_names_constructed_in(fn)
            if not button_names:
                continue
            for node in ast.walk(fn):
                if not _is_set_icon_call(node):
                    continue
                target = _set_icon_target(node)
                if target and target in button_names:
                    out.append((
                        path, node.lineno, target, lines[node.lineno - 1].strip(),
                    ))

        # Shape 3: icon_button(role, tooltip, ...) — tooltip is checked
        # directly against the call, not via a whole-file name search, in
        # test_icon_button_factory_calls_pass_a_real_tooltip() below.

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


def test_icon_button_factory_calls_pass_a_real_tooltip() -> None:
    """``icon_button(role, tooltip, ...)``'s tooltip is a direct argument.

    The factory itself raises ValueError on an empty literal at runtime; this
    is the static half — it catches a missing/empty tooltip argument across
    the whole tree without constructing every widget, and it is what makes
    ``icon_button(`` sites count as icon-only buttons per the module docstring.
    """
    offenders = []
    for path in sorted(_GUI.rglob("*.py")):
        if path.name == "icon_utils.py":
            continue
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not _is_icon_button_call(node):
                continue
            tooltip_arg = node.args[1] if len(node.args) >= 2 else None
            if tooltip_arg is None:
                for kw in node.keywords:
                    if kw.arg == "tooltip":
                        tooltip_arg = kw.value
            ok = False
            if isinstance(tooltip_arg, ast.Constant) and isinstance(tooltip_arg.value, str):
                ok = bool(tooltip_arg.value)
            elif isinstance(tooltip_arg, (ast.JoinedStr, ast.Name, ast.Attribute, ast.Call)):
                # A dynamic value — can't prove non-empty statically; the
                # factory's own ValueError guard covers it at runtime.
                ok = True
            if not ok:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    assert not offenders, (
        "icon_button() called without a real tooltip literal:\n  " + "\n  ".join(offenders)
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


def test_the_setIcon_pattern_is_swept_and_needs_a_tooltip() -> None:
    """Proves shape 2 (module docstring) on a minimal synthetic sample.

    A bare ``QPushButton()`` whose icon is painted via ``set_button_icon()``
    in the SAME function, with no ``setToolTip()`` anywhere in the file, must
    be flagged — this is what a naive migration off ``QPushButton(icons.x)``
    produces if the tooltip is dropped in the same edit that moves the icon
    off the constructor.
    """
    bad_source = (
        "def build(self):\n"
        "    self._btn = QPushButton()\n"
        "    set_button_icon(self._btn, 'close')\n"
    )
    tree = ast.parse(bad_source)
    fn = tree.body[0]
    names = _button_names_constructed_in(fn)
    assert "_btn" in names
    hits = [
        node for node in ast.walk(fn)
        if _is_set_icon_call(node) and _set_icon_target(node) in names
    ]
    assert hits, "the bare-construction + set_button_icon() shape was not recognised"

    good_source = bad_source + "    self._btn.setToolTip('Close')\n"
    assert re.search(r"self\._btn\.setToolTip\(", good_source)
    assert not re.search(r"self\._btn\.setToolTip\(", bad_source)


def test_a_collapse_toggle_keeps_its_tooltip_truthful(qapp_free=None) -> None:
    """A toggle's tooltip must be set where the GLYPH flips, not once at build.

    A tip reading "Collapse this section" under an expand arrow is worse than
    none — it is confidently wrong half the time. Asserted on the source
    because the alternative (constructing three details-pane sections) buys no
    extra confidence about where the call sits.
    """
    # The four hand-rolled ``_apply`` methods this used to scan are gone: all
    # six details sections now share one CollapsibleHeader, and the glyph flips
    # in its ``_sync``. That is the same assertion against one implementation
    # instead of four — and it now covers Overview and Also-available too,
    # which never had a caret to get wrong. ICON-1 moved the flip from
    # ``_chevron.setText(...)`` to ``icon_utils.set_button_icon(...)``.
    source = (_GUI / "details_section_header.py").read_text()
    tree = ast.parse(source)
    syncs = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_sync"
    ]
    toggling = [
        fn for fn in syncs
        if "set_button_icon" in (ast.get_source_segment(source, fn) or "")
        and "_chevron" in (ast.get_source_segment(source, fn) or "")
    ]
    assert toggling, "no glyph-flipping _sync() found — has the shape changed?"
    for fn in toggling:
        body = ast.get_source_segment(source, fn) or ""
        assert "setToolTip" in body, (
            f"_sync() at line {fn.lineno} flips the chevron without updating "
            f"its tooltip — the tip will contradict the arrow"
        )
