"""Every migration task class is in the registry (ledger F29).

A task file that is never registered never runs, and nothing else fails: the
hand-written list in main_window.py let exactly that happen. This walks the
package and checks the registry names every ``*Task`` class defined in it.
"""

import ast
from pathlib import Path

from metatv.core.migrations import registry

_PKG = Path(registry.__file__).parent
#: Defined in the package but not startup tasks: bases and helpers.
_NOT_STARTUP_TASKS = {"VersionGatedTask", "MigrationTask"}


def _task_classes() -> set[str]:
    found = set()
    for path in _PKG.glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and node.name.endswith("Task"):
                found.add(node.name)
    return found - _NOT_STARTUP_TASKS


def test_every_task_class_is_registered():
    registered = {name for _module, name, _extra in registry.TASKS}
    missing = _task_classes() - registered
    assert not missing, f"never registered, so they never run: {sorted(missing)}"


def test_the_registry_names_no_task_twice():
    names = [name for _module, name, _extra in registry.TASKS]
    assert len(names) == len(set(names))


def test_order_constraints_hold():
    names = [name for _module, name, _extra in registry.TASKS]
    assert names[0] == "QueryIndexTask"
    assert names.index("DetectedTitleReparseTask") < names.index("TagBackfillTask")
    assert names.index("TmdbIdBackfillTask") < names.index("ContentKeyBackfillTask")
    assert names.index("ContentKeyBackfillTask") < names.index("TmdbSiblingPropagationTask")
