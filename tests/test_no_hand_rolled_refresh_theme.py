"""No widget re-grows a hand-maintained ``refresh_theme()`` sweep.

The rule (CLAUDE.md, "Styling a widget"): ``theme.style(w, "ROLE")`` /
``theme.style_fn(w, builder)`` register the widget, and ``theme.apply_theme()``
re-applies every live registration. A ``refresh_theme()`` override that walks
its own children and re-styles them is the mechanism that could not work —
~838 ``setStyleSheet`` call sites against 22 override methods, and an
enumeration never sees what nobody remembered to add. Two earlier slices
(#253, #261) each "completed" that sweep and each left it broken.

THEME-1 deleted all 22. This guard is what stops the twenty-third: it is an
AST walk over ``metatv/gui/**``, so it sees a definition whatever indentation,
decorator or docstring surrounds it — the thing a grep-shaped check misses.

Measured against the pre-migration tree it reports 22 definitions in 16 files;
against this one, none. Survivors, if a future slice ever earns one, go in
``tests/refresh_theme_allowlist.json`` with a one-line reason, and that file
may only SHRINK.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

GUI = pathlib.Path("metatv/gui")
ALLOWLIST = pathlib.Path("tests/refresh_theme_allowlist.json")


def _allowed() -> dict[str, str]:
    return json.loads(ALLOWLIST.read_text())["allowed"]


def _definitions(root: pathlib.Path) -> list[str]:
    """``file:line Class.refresh_theme`` for every definition under *root*."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if (
                    isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and member.name == "refresh_theme"
                ):
                    found.append(
                        f"{path}:{member.lineno} {node.name}.refresh_theme"
                    )
    return found


def test_no_hand_rolled_refresh_theme_in_gui():
    """Any ``def refresh_theme`` in metatv/gui/** outside the allowlist fails."""
    allowed = _allowed()
    offenders = [
        site for site in _definitions(GUI)
        if site.split(" ", 1)[1] not in allowed
    ]
    assert not offenders, (
        "these define a hand-maintained refresh_theme() sweep — register the "
        "widget at construction with theme.style(w, \"ROLE\") / "
        "theme.style_fn(w, builder) so apply_theme() re-applies it, or use "
        "theme.register_post_apply(bound) for work a stylesheet cannot "
        "express:\n  " + "\n  ".join(offenders)
    )


def test_the_allowlist_only_shrinks():
    """Seeded EMPTY by THEME-1. An entry appearing here is the regression."""
    allowed = _allowed()
    assert allowed == {}, (
        "refresh_theme_allowlist.json is shrink-only and was seeded empty; "
        f"someone added {sorted(allowed)}. A new survivor needs the owner's "
        "sign-off, not an allowlist edit."
    )


def test_every_allowlist_entry_carries_a_reason():
    """A bare name in the allowlist is an exemption nobody has to justify."""
    for name, reason in _allowed().items():
        assert isinstance(reason, str) and reason.strip(), (
            f"{name} is allowlisted with no reason"
        )


@pytest.mark.parametrize("snippet", [
    # The plain shape…
    "class W:\n    def refresh_theme(self):\n        pass\n",
    # …and the three a line-oriented grep for `    def refresh_theme` misses.
    "class W:\n    @staticmethod\n    def refresh_theme():\n        pass\n",
    "class W:\n    async def refresh_theme(self):\n        pass\n",
    "class Outer:\n    class Inner:\n            def refresh_theme(self):\n"
    "                pass\n",
])
def test_the_collector_sees_every_definition_shape(snippet, tmp_path):
    """Proven against the shapes, not just the one that exists today."""
    (tmp_path / "w.py").write_text(snippet)

    assert _definitions(tmp_path), f"collector missed:\n{snippet}"


def test_the_collector_ignores_a_plain_function(tmp_path):
    """Only a CLASS member is a widget sweep; a module function is not."""
    (tmp_path / "w.py").write_text("def refresh_theme():\n    pass\n")

    assert _definitions(tmp_path) == []
