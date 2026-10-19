"""No ``strftime`` format with ``%-X`` outside ``time_display.local_strftime``.

``%-I`` / ``%-d`` (no leading zero) are a glibc/BSD extension; on Windows
``strftime`` raises ``ValueError`` on them. Linux and macOS accept them, so no
behaviour test on those platforms can notice a new one — hence a scan. Use
``time_display.local_strftime(dt, fmt)``, which strips the zero itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parents[1] / "metatv"


def _platform_formats(tree: ast.AST):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "strftime" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str) and "%-" in node.args[0].value):
            yield node.lineno


def test_no_strftime_uses_a_platform_only_directive():
    offenders = [
        f"{path.relative_to(_PACKAGE.parent)}:{line}"
        for path in sorted(_PACKAGE.rglob("*.py"))
        for line in _platform_formats(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not offenders, (
        "strftime with %-X raises ValueError on Windows — use "
        f"time_display.local_strftime: {offenders}")


def test_the_scan_sees_one():
    assert list(_platform_formats(ast.parse("x.strftime('%-I:%M')\n"))) == [1]
    assert list(_platform_formats(ast.parse("x.strftime('%I:%M')\n"))) == []


def test_local_strftime_strips_the_zero_without_the_platform_directive():
    from datetime import datetime

    from metatv.core.time_display import local_strftime

    assert local_strftime(datetime(2026, 8, 4, 9, 5), "%a %b %-d %-I:%M %p") == "Tue Aug 4 9:05 AM"
    assert local_strftime(datetime(2026, 8, 14, 12, 0), "%-d %-I") == "14 12"
    assert local_strftime(datetime(2026, 8, 4, 0, 30), "%-H:%M") == "0:30"
