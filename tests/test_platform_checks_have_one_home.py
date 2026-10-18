"""``sys.platform`` / ``os.name`` / ``platform.system()`` are read only in
``metatv/core/runtime_env.py``.

Every other module asks ``runtime_env.is_windows()`` / ``is_macos()``, and each
platform difference is handled once, in the module that owns the concern (see
``runtime_env``'s docstring). A stray ``sys.platform`` check is how a second,
slightly different answer starts — this branch removed two identical
``_is_windows()`` copies. It walks the AST, so comments and strings that
mention the names are fine.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parents[1] / "metatv"
_HOME = _PACKAGE / "core" / "runtime_env.py"
_READS = {("sys", "platform"), ("os", "name"), ("platform", "system")}


def _platform_reads(tree: ast.AST):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and (node.value.id, node.attr) in _READS):
            yield node.lineno


def test_only_runtime_env_reads_the_platform():
    offenders = [
        f"{path.relative_to(_PACKAGE.parent)}:{line}"
        for path in sorted(_PACKAGE.rglob("*.py")) if path != _HOME
        for line in _platform_reads(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not offenders, (
        "platform check outside metatv/core/runtime_env.py — call "
        f"runtime_env.is_windows()/is_macos() instead: {offenders}")


def test_the_scan_sees_one():
    assert list(_platform_reads(ast.parse("if sys.platform == 'win32': pass\n"))) == [1]
    assert list(_platform_reads(ast.parse("x = platform.release()\n"))) == []
