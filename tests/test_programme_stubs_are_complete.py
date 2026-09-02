"""Every fake EPG programme in the suite carries the fields render actually reads.

This exact miss cost two CI rounds in one session. WL-1 slice 2 made the render
path read ``prog.description``; four test files carry their own programme stub,
and each round found only the stubs that happened to be in the selection I ran
— ``-k "epg or watchlist"`` does not match
``test_quality_display_translation.py``.

So: stop finding them by running things. A stub is discovered by SHAPE (a class
with ``title`` and ``start_time``), not by a name list someone maintains — that
is the enumeration failure this repo keeps paying for, and a list here would go
stale the first time somebody adds a fifth stub.
"""
from __future__ import annotations

import ast
import pathlib

_TESTS = pathlib.Path(__file__).resolve().parent

#: What the render path reads off a programme. Add to this when render does.
_REQUIRED = ("title", "start_time", "description")


def _class_attribute_names(node: ast.ClassDef) -> set[str]:
    """Attributes a class assigns, at class level or in ``__init__``."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    names.add(target.attr)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            names.add(child.target.id)
    for arg in ():
        names.add(arg)
    return names


def _looks_like_a_programme(node: ast.ClassDef) -> bool:
    """A stub standing in for ``EpgProgramDB``: it has a title and a start time."""
    attrs = _class_attribute_names(node)
    init = next((n for n in node.body
                 if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
    if init is not None:
        attrs |= {a.arg for a in init.args.args if a.arg != "self"}
        attrs |= {a.arg for a in init.args.kwonlyargs}
    return {"title", "start_time"} <= attrs


def test_every_programme_stub_declares_what_render_reads():
    offenders = []
    for path in sorted(_TESTS.glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        decorated = "with_programme_render_fields" in source
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not _looks_like_a_programme(node):
                continue
            if decorated:
                continue  # the conftest factory supplies the defaults
            attrs = _class_attribute_names(node)
            init = next((n for n in node.body if isinstance(n, ast.FunctionDef)
                         and n.name == "__init__"), None)
            if init is not None:
                attrs |= {a.arg for a in init.args.args if a.arg != "self"}
                attrs |= {a.arg for a in init.args.kwonlyargs}
            missing = [f for f in _REQUIRED if f not in attrs]
            if missing:
                offenders.append(
                    f"{path.name}:{node.lineno} {node.name} is missing {missing}")

    assert not offenders, (
        "programme stubs that render will raise AttributeError on. Decorate the "
        "class with @with_programme_render_fields (tests/conftest.py) rather "
        "than adding the field by hand — the point is one definition:\n  "
        + "\n  ".join(offenders))
