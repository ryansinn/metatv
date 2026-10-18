"""Every helper-program launch passes ``**NO_WINDOW`` (``core/child_process.py``).

Without it, the Windows build flashes a console window for each mpv start,
probe and version check. The flag is empty on Linux and macOS, so nothing there
can notice a missing one — hence a scan rather than a behaviour test. It walks
the AST, so a call wrapped across lines or written in any style is still seen.
"""

from __future__ import annotations

import ast
from pathlib import Path

_LAUNCHERS = {"Popen", "run", "call", "check_call", "check_output"}
_PACKAGE = Path(__file__).resolve().parents[1] / "metatv"


def _launches_without_no_window(tree: ast.AST):
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        func = node.func
        if not (func.attr in _LAUNCHERS and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"):
            continue
        if not any(kw.arg is None and isinstance(kw.value, ast.Name)
                   and kw.value.id == "NO_WINDOW" for kw in node.keywords):
            yield node.lineno


def test_every_subprocess_launch_passes_no_window():
    offenders = [
        f"{path.relative_to(_PACKAGE.parent)}:{line}"
        for path in sorted(_PACKAGE.rglob("*.py"))
        for line in _launches_without_no_window(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not offenders, (
        "subprocess launch without **NO_WINDOW (metatv/core/child_process.py) — "
        f"flashes a console window on Windows: {offenders}")


def test_the_scan_sees_a_missing_flag():
    """The guard must be able to fail, or it proves nothing."""
    bad = ast.parse("import subprocess\nsubprocess.run(['x'], text=True)\n")
    good = ast.parse("subprocess.Popen(['x'], **NO_WINDOW)\n")
    assert list(_launches_without_no_window(bad)) == [2]
    assert list(_launches_without_no_window(good)) == []
