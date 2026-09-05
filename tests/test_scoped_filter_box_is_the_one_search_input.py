"""Drift guard — ScopedFilterBox is the ONE search/filter QLineEdit (SEARCH-10).

Before this, a dozen views each hand-rolled the same shape: a bare
``QLineEdit`` with its own placeholder, its own (often absent) debounce
timer, and its own clear/Escape wiring. ``metatv/gui/scoped_filter_box.py``
consolidated all eleven into one widget; this guard is what keeps the next
one from creeping back in unnoticed, the same way ``test_theme_style_registry``
guards ``theme.style()`` against a raw ``setStyleSheet``.

An AST walk (not a line regex, for the same reason the styling guard is an
AST walk — a regex only ever knows the shapes it was written against) scans
every function in ``metatv/gui/**/*.py`` for a ``QLineEdit(...)`` construction
(or a construction of any OTHER class that subclasses ``QLineEdit`` directly —
discovered dynamically per file, so a future shadow subclass is covered
without anyone updating this test) whose ``setPlaceholderText`` call in the
SAME function reads like a search/filter box ("search"/"filter"/"find",
case-insensitive, anywhere in the placeholder).

Two sites are legitimately excluded — different semantics, not duplication:

    * ``category_picker_dialog.py:_setup_ui`` — search-OR-CREATE: typing a
      name that doesn't exist composes a brand-new category rather than
      narrowing an existing list.
    * ``global_filter_dialog.py:_populate_keywords`` — an ADD field
      (``returnPressed`` -> ``_add_keyword``), not a filter/search box.

``_KNOWN_HAND_ROLLED_SEARCH_INPUTS`` is shrink-only: an entry is stale (and
fails the suite, exactly like an unlisted violation) once its file:function no
longer constructs a bare QLineEdit-shaped widget there at all — i.e. the site
was converted to ``ScopedFilterBox``, renamed, or deleted — regardless of
whether ITS OWN placeholder happens to contain a trigger word (the keyword-add
field's "Add a keyword…" never did; it is listed anyway because it is the
other real exception this guard would otherwise need updating for). That
keeps the allowlist from quietly widening into a dumping ground for future
exceptions instead of new hand-rolled boxes actually getting fixed.
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUI_ROOT = _REPO_ROOT / "metatv" / "gui"

_SEARCH_WORDS = ("search", "filter", "find")

# file:function -> why this one is allowed to hand-roll a QLineEdit placeholdered
# like a search/filter box. Shrink-only: see module docstring.
_KNOWN_HAND_ROLLED_SEARCH_INPUTS: dict[str, str] = {
    "metatv/gui/category_picker_dialog.py:_setup_ui": (
        "search-or-create — typing a name that doesn't exist composes a NEW "
        "category rather than narrowing an existing list"
    ),
    "metatv/gui/global_filter_dialog.py:_populate_keywords": (
        "an ADD field (returnPressed -> _add_keyword), not a filter/search box"
    ),
}


def _var_key(node: ast.AST) -> str | None:
    """Canonical dotted-name key for a bare name or an attribute chain —
    e.g. ``self._filter`` for ``Attribute(attr='_filter', value=Name('self'))``.
    ``None`` for anything else (subscripts, calls, …), which this guard
    simply cannot key on and does not need to.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _var_key(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _literal_text(node: ast.AST) -> str | None:
    """Best-effort literal text of *node* — a plain string, or the static
    (non-interpolated) parts of an f-string joined together. ``None`` if it
    resolves to no literal text at all (e.g. a bare variable)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
        return "".join(parts) if parts else None
    return None


def _qlineedit_subclass_names(tree: ast.Module) -> set[str]:
    """Class names in *tree* that subclass ``QLineEdit`` directly, other than
    ``ScopedFilterBox`` itself — so a future shadow subclass is covered
    without this test needing an update."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name != "ScopedFilterBox":
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "QLineEdit":
                    names.add(node.name)
    return names


def _callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _placeholder_in_function(func: ast.AST, varname: str) -> str | None:
    """The literal placeholder text set on *varname* anywhere inside *func*
    (whatever it says) — ``None`` if none is found or it isn't a literal."""
    for sub in ast.walk(func):
        if not (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "setPlaceholderText"
            and sub.args
        ):
            continue
        if _var_key(sub.func.value) != varname:
            continue
        text = _literal_text(sub.args[0])
        if text is not None:
            return text
    return None


def _qlineedit_construction_sites() -> dict[str, str]:
    """``{"path/to/file.py:function_name": placeholder_text}`` for every
    function in metatv/gui/ that constructs a bare QLineEdit-shaped widget
    (any placeholder, or "" if it never sets one) — the population BOTH other
    functions in this module filter down from."""
    sites: dict[str, str] = {}
    for path in sorted(_GUI_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        disallowed = {"QLineEdit"} | _qlineedit_subclass_names(tree)
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(func):
                if not (
                    isinstance(sub, (ast.Assign, ast.AnnAssign))
                    and isinstance(sub.value, ast.Call)
                ):
                    continue
                call = sub.value
                if _callee_name(call) not in disallowed:
                    continue
                targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                for tgt in targets:
                    varname = _var_key(tgt)
                    if varname is None:
                        continue
                    placeholder = _placeholder_in_function(func, varname) or ""
                    sites[f"{rel}:{func.name}"] = placeholder
    return sites


def _hand_rolled_matches() -> dict[str, str]:
    """The subset of :func:`_qlineedit_construction_sites` whose placeholder
    reads like a search/filter box — the population this guard actually cares
    about flagging."""
    return {
        key: placeholder for key, placeholder in _qlineedit_construction_sites().items()
        if any(word in placeholder.lower() for word in _SEARCH_WORDS)
    }


def test_no_new_hand_rolled_search_inputs():
    """Every match must be one of the two documented, differently-semantic
    exceptions — anything else is the next dozen-boxes regression starting."""
    matches = _hand_rolled_matches()
    unexpected = {
        key: placeholder for key, placeholder in matches.items()
        if key not in _KNOWN_HAND_ROLLED_SEARCH_INPUTS
    }
    assert not unexpected, (
        "these hand-roll a QLineEdit placeholdered like a search/filter box "
        "instead of metatv.gui.scoped_filter_box.ScopedFilterBox:\n  "
        + "\n  ".join(f"{k} ({v!r})" for k, v in unexpected.items())
    )


def test_the_allowlist_has_no_stale_entries():
    """A ``_KNOWN_HAND_ROLLED_SEARCH_INPUTS`` entry whose file:function no
    longer constructs a bare QLineEdit-shaped widget at all is dead weight
    that could silently cover for a real regression later — the allowlist is
    shrink-only, never a place to accumulate stale exemptions."""
    sites = _qlineedit_construction_sites()
    stale = [key for key in _KNOWN_HAND_ROLLED_SEARCH_INPUTS if key not in sites]
    assert not stale, (
        "these allowlist entries no longer correspond to a hand-rolled "
        "QLineEdit construction — remove them (or fix the entry) rather than "
        "leaving dead rows behind:\n  " + "\n  ".join(stale)
    )
