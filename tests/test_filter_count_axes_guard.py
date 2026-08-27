"""The transparency diffs must be derived from one axes dict, not hand-copied.

``_query_channels`` reports what each filter layer hides by re-running its own
query with exactly ONE axis lifted and subtracting. That only means anything if
every other axis is held equal — and for a while it was not: four hand-copied
argument lists of ~28 entries, and the tag-filter one omitted nine of them, so
rows removed by a prefix filter were reported as removed by the tag filter.

The fix builds ``_axes`` once and overrides a single key per diff. This guard is
what stops someone expanding one back into a literal list, which is how the
divergence arrived the first time and would look perfectly reasonable in review.

An AST walk, so a comment mentioning ``get_all`` cannot trip it.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from metatv.gui.main_window_channels import _ChannelListMixin

# The three transparency diffs. Each subtracts its result from the visible set,
# so each must differ from the main query in exactly one axis.
DIFF_TARGETS = {
    "unfiltered": "tag_includes",
    "with_dead": "include_dead",
    "with_keywords": "excluded_keywords",
}


def _query_channels_tree() -> ast.AST:
    src = textwrap.dedent(inspect.getsource(_ChannelListMixin._query_channels))
    return ast.parse(src)


def _get_all_assignments() -> dict[str, ast.Call]:
    """Return ``{assigned name: the get_all Call node}`` for every assignment."""
    found: dict[str, ast.Call] = {}
    for node in ast.walk(_query_channels_tree()):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not (isinstance(call.func, ast.Attribute) and call.func.attr == "get_all"):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = call
    return found


def test_every_diff_query_is_built_from_the_shared_axes():
    """Each diff must be ``get_all(**{**_axes, '<one axis>': ...})`` — nothing else."""
    assignments = _get_all_assignments()

    missing = sorted(set(DIFF_TARGETS) - set(assignments))
    assert not missing, (
        f"transparency diffs no longer assign to {missing}; if they were renamed, "
        "rename them here too — do not delete this guard"
    )

    for name, axis in DIFF_TARGETS.items():
        call = assignments[name]
        assert not call.args, f"{name}: get_all takes keywords, not positionals"

        starstar = [kw for kw in call.keywords if kw.arg is None]
        named = [kw.arg for kw in call.keywords if kw.arg is not None]
        assert not named, (
            f"{name} passes {named} as literal keyword arguments. Every axis it does "
            "not name silently differs from the main query, which is exactly the bug "
            "this guard exists for. Use **{**_axes, '<axis>': ...} instead."
        )
        assert len(starstar) == 1, f"{name}: expected a single ** unpacking"

        merged = starstar[0].value
        assert isinstance(merged, ast.Dict), (
            f"{name}: expected a dict literal merging _axes with one override"
        )
        # {**_axes, 'axis': value} → keys [None, Constant('axis')]
        assert merged.keys and merged.keys[0] is None, (
            f"{name}: the dict must start by unpacking _axes"
        )
        assert isinstance(merged.values[0], ast.Name) and merged.values[0].id == "_axes", (
            f"{name}: the unpacked base must be _axes, not something else"
        )

        overrides = [
            k.value for k in merged.keys[1:] if isinstance(k, ast.Constant)
        ]
        assert overrides == [axis], (
            f"{name} overrides {overrides}; a diff that changes more than "
            f"{axis!r} is not measuring one axis"
        )


def test_the_main_query_uses_the_axes_unmodified():
    """The set every diff is subtracted from must be _axes itself, not a variant."""
    call = _get_all_assignments()["channels"]

    starstar = [kw for kw in call.keywords if kw.arg is None]
    named = [kw.arg for kw in call.keywords if kw.arg is not None]
    assert not named, f"the main query names {named}; those axes would not reach the diffs"
    assert len(starstar) == 1 and isinstance(starstar[0].value, ast.Name), (
        "the main query must be get_all(**_axes)"
    )
    assert starstar[0].value.id == "_axes"
