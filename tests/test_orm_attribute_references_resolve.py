"""Every ``<Model>DB.<attr>`` written in production code must actually exist.

Why this is a test and not a review habit: ``RecordingManager.progress()``
shipped ``order_by(RecordingDB.starts_at.desc())`` — and ``starts_at`` is not a
column. The column is ``programme_start``; ``starts_at`` is what the *DTO*
calls the padded start, so the name was real four lines further down and wrong
on that line. Python raises only when the expression is evaluated, the sidebar
refresh catches and logs, so it failed once a second in the owner's running app
while the Recordings section simply stayed empty.

A unit suite cannot cover this by enumeration — the point of the class of bug is
that it lives on the one query nobody executed. So the check is DERIVED: walk
every ``metatv/`` module's AST, find every attribute access whose base is a name
bound to a declarative model in ``core.database``, and ask the model. A new
model and a new column are both covered the moment they exist, and no one has
to remember this file.

Deliberately narrow: only ``Name.attr`` where ``Name`` is a model class. An
instance (``row.starts_at``) is out of scope — that is a property lookup on a
loaded row and hasattr cannot tell a typo from a hybrid — and false positives in
a guard are how guards get deleted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import metatv.core.database as database

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "metatv"


def _model_classes() -> dict:
    """Declarative models exported by ``core.database``, keyed by class name."""
    return {
        name: obj
        for name in dir(database)
        if name.endswith("DB")
        and isinstance(obj := getattr(database, name), type)
        and hasattr(obj, "__tablename__")
    }


def test_every_model_attribute_reference_resolves():
    models = _model_classes()
    assert len(models) >= 10, (
        "the sweep found almost no models — the naming convention moved and "
        "this guard is now vacuously green, which is worse than absent"
    )

    unresolved = []
    scanned = 0
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in models
            ):
                scanned += 1
                if not hasattr(models[node.value.id], node.attr):
                    rel = path.relative_to(SOURCE_ROOT.parent)
                    unresolved.append(
                        f"{rel}:{node.lineno}  {node.value.id}.{node.attr}"
                    )

    assert scanned > 100, (
        f"only {scanned} model attribute references found; the walk is not "
        "reaching the query code it exists to check"
    )
    assert not unresolved, "attribute(s) that do not exist on the model:\n  " + \
        "\n  ".join(unresolved)
