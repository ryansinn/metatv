"""Zero-caller guard for ``core/discovery_engine.py`` (What's New #618).

The audit that drove #618 found three module-level helpers —
``_apply_content_type_exclusion``, ``_apply_keyword_exclusion``,
``_apply_user_category_exclusion`` — with ZERO ``ast.Call`` sites anywhere in
the repository; every shelf query had already migrated onto the combined
``_apply_prefix_filter`` chokepoint, and the three siblings survived only as
names in docstrings (which a text grep for the identifier finds, but which
prove nothing about whether the function actually runs). That is exactly the
gap a prose "grep for it first" habit cannot close: a docstring mention reads
identically to a real call site until you check whether the reference is
inside a ``Call`` node.

This test is that check, scoped to this one module (rather than a repo-wide
sweep) per the audit's own method: every top-level function
``discovery_engine.py`` defines must be the target of at least one
``ast.Call`` node somewhere under ``metatv/`` or ``tests/`` — a docstring/
comment mention does not count, and neither does the function's own ``def``
line. A function called only from tests (e.g. ``_primary_genre``, kept as a
documented pure helper — see its own docstring) still counts as "called";
this guard's job is to catch a helper nothing calls at all, not to demand a
production caller specifically.
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "metatv" / "core" / "discovery_engine.py"


def _module_level_function_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not (node.name.startswith("__") and node.name.endswith("__"))
    }


def _called_names(path: pathlib.Path) -> set[str]:
    """Every name that appears as a ``Call`` target in *path* — bare
    ``func(...)`` and ``obj.func(...)`` / ``module.func(...)`` alike."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            names.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            names.add(fn.attr)
    return names


def test_every_discovery_engine_function_has_at_least_one_caller():
    defined = _module_level_function_names(TARGET)
    assert defined, "sweep found no functions — it is looking in the wrong place"

    called: set[str] = set()
    for path in sorted((REPO_ROOT / "metatv").rglob("*.py")) + sorted(
        (REPO_ROOT / "tests").rglob("*.py")
    ):
        called |= _called_names(path)

    dead = sorted(defined - called)
    assert not dead, (
        f"discovery_engine.py defines but nothing calls: {dead}\n\n"
        "A docstring/comment mention is not a call — check for a real "
        "ast.Call site, or delete the function (What's New #618 precedent)."
    )
