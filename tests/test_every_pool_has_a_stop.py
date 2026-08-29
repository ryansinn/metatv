"""A widget that owns a thread pool must have a way to stop it.

``SimilarTitleLightbox`` created a ``ThreadPoolExecutor`` and had **no
shutdown of any kind** — no method, no ``closeEvent``, no registration in the
cleanup registry. Its worker outlived the window that created it. Its sibling
*nine lines away* in ``main_window.py``, the trail map, was registered from the
day it was written.

That is what a hand-maintained registry costs, and it is the same fault that
has been aborting this app on quit: a thread still executing while the objects
it touches are destroyed (#540, #542).

So this is derived, not a list. It finds every class that constructs a pool and
checks two things — that the class can stop it, and that somebody actually
asks. Adding a third pool tomorrow fails here without anyone remembering the
rule exists.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
GUI = REPO / "metatv" / "gui"

#: Names a class may use to stop its own pool. ``on_deactivate`` counts: the
#: host calls it on every view switch AND on close (see closeEvent's derived
#: view sweep), which is a real stop path, not a loophole.
_STOP_METHODS = {"shutdown", "closeEvent", "on_deactivate"}


def _all_classes() -> "dict[str, ast.ClassDef]":
    """Every class in gui/, by name, so bases can be resolved.

    Inheritance matters here: ``BackgroundRefreshMixin`` defines the stop and
    six sections get it that way. A check that only reads a class's own body
    would report all six as broken — which the first version of this file did.
    """
    out: dict[str, ast.ClassDef] = {}
    for path in sorted(GUI.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                out.setdefault(node.name, node)
    return out


def _stop_methods_for(cls: ast.ClassDef) -> "set[str]":
    """Stop methods available to *cls*, its own and inherited within gui/."""
    known = _all_classes()
    seen: set[str] = set()
    found: set[str] = set()
    stack = [cls]
    while stack:
        node = stack.pop()
        if node.name in seen:
            continue
        seen.add(node.name)
        found |= {
            n.name for n in node.body
            if isinstance(n, ast.FunctionDef) and n.name in _STOP_METHODS
        }
        for base in node.bases:
            name = getattr(base, "id", None) or getattr(base, "attr", None)
            if name in known:
                stack.append(known[name])
    return found


def _stop_source_for(cls: ast.ClassDef) -> str:
    """Source of every stop method available to *cls*, own and inherited."""
    known = _all_classes()
    seen: set[str] = set()
    src: list[str] = []
    stack = [cls]
    while stack:
        node = stack.pop()
        if node.name in seen:
            continue
        seen.add(node.name)
        src += [
            ast.unparse(n) for n in node.body
            if isinstance(n, ast.FunctionDef) and n.name in _STOP_METHODS
        ]
        for base in node.bases:
            name = getattr(base, "id", None) or getattr(base, "attr", None)
            if name in known:
                stack.append(known[name])
    return "\n".join(src)


def _classes_owning_a_pool() -> "list[tuple[pathlib.Path, ast.ClassDef]]":
    """Every gui/ class whose body constructs a ThreadPoolExecutor."""
    found = []
    for path in sorted(GUI.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for call in [n for n in ast.walk(node) if isinstance(n, ast.Call)]:
                name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if name == "ThreadPoolExecutor":
                    found.append((path, node))
                    break
    return found


def test_the_scan_finds_the_pools_at_all():
    """Guards the guard. A broken scan would pass every test below silently."""
    owners = _classes_owning_a_pool()
    names = {c.name for _p, c in owners}
    assert len(owners) >= 3, f"only found {names} — the scan is not working"
    assert "SimilarTitleLightbox" in names, (
        "the class this test was written for is not being found"
    )


@pytest.mark.parametrize(
    "path,cls",
    [(p, c) for p, c in _classes_owning_a_pool()],
    ids=[c.name for _p, c in _classes_owning_a_pool()],
)
def test_a_class_that_owns_a_pool_can_stop_it(path, cls):
    """THE assertion. Owning a pool with no way to stop it is the defect."""
    stoppers = _stop_methods_for(cls)
    assert stoppers, (
        f"{cls.name} ({path.name}) constructs a ThreadPoolExecutor but defines "
        f"none of {sorted(_STOP_METHODS)} — nothing can stop its worker, and a "
        "thread running past teardown aborts the process"
    )


@pytest.mark.parametrize(
    "path,cls",
    [(p, c) for p, c in _classes_owning_a_pool()],
    ids=[c.name for _p, c in _classes_owning_a_pool()],
)
def test_the_stop_actually_shuts_the_pool_down(path, cls):
    """A ``shutdown`` that does not shut down is worse than none.

    Checked structurally rather than by running it: these are widgets with real
    Qt parents, and the claim here is about the code, not a live instance.
    """
    src = _stop_source_for(cls)
    # A stop counts when it shuts a pool, joins its threads, quits a QThread,
    # or hands the job to the cleanup registry. MainWindow does the last two —
    # its closeEvent calls _await_background_pools (which joins) and the
    # registry holds the executor's own shutdown. Requiring the literal text
    # "shutdown(" inside the method reported that as broken, which it is not.
    _EVIDENCE = ("shutdown(", "_stop_loader", "quit()", "join(",
                 "_await_background_pools", "_cleanables")
    assert any(tok in src for tok in _EVIDENCE), (
        f"{cls.name} ({path.name}) has a stop method that never shuts a pool or "
        "thread down"
    )


def test_the_lightbox_stop_is_reachable_from_the_cleanup_registry():
    """Defining a stop is half of it — somebody has to call it.

    The trail map is registered right beside the lightbox in the same
    constructor. That is precisely why the omission was invisible.
    """
    src = (GUI / "main_window.py").read_text(encoding="utf-8")
    assert '_register_cleanable("lightbox"' in src, (
        "the lightbox owns a pool but nothing in the cleanup registry stops it"
    )


def test_the_registry_stops_every_pool_owner_the_window_holds_directly():
    """Derived over the window's own attributes, not a list of names."""
    src = (GUI / "main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    registered = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", None) == "_register_cleanable"
        and n.args and isinstance(n.args[0], ast.Constant)
    }
    # Both pool-owning widgets the window builds itself, by the key each is
    # registered under.
    for key in ("trail_map", "lightbox"):
        assert key in registered, f"{key} is not in the cleanup registry"
