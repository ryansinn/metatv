"""Display times and dates are formatted only in ``core/time_display``.

A surface that writes its own ``strftime("%H:%M")`` ignores the user's Time /
Date setting — exactly how recordings showed 24-hour times beside a 12-hour
guide. Log lines and file names are not display text and keep sortable ISO
stamps; they are the listed exceptions. Weekday names alone (``%a``/``%A``) are
not a date format and pass.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parents[1] / "metatv"
_HOME = _PACKAGE / "core" / "time_display.py"
_DATE_OR_CLOCK = re.compile(r"%-?[HIMdmbBYyp]")

#: file -> why its stamp is not display text.
_NOT_DISPLAY = {
    "core/epg_fetch.py": "log line",
    "core/epg_manager.py": "log line (UTC cutoff)",
    "core/recording_manager.py": "recording file name, sortable",
    "gui/log_viewer_window.py": "saved-log file name",
}


def _formats(tree: ast.AST):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "strftime" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            yield node.lineno, node.args[0].value
        elif isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            spec = "".join(v.value for v in node.format_spec.values
                           if isinstance(v, ast.Constant) and isinstance(v.value, str))
            yield node.lineno, spec


def test_only_time_display_formats_display_times_and_dates():
    offenders = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        rel = path.relative_to(_PACKAGE).as_posix()
        if path == _HOME or rel in _NOT_DISPLAY:
            continue
        for line, fmt in _formats(ast.parse(path.read_text(encoding="utf-8"))):
            if _DATE_OR_CLOCK.search(fmt):
                offenders.append(f"{rel}:{line} {fmt!r}")
    assert not offenders, (
        "a display time/date formatted outside core/time_display ignores the "
        f"user's Time/Date setting — use clock_text/date_text/…: {offenders}")


def test_the_scan_sees_both_spellings():
    tree = ast.parse("a = x.strftime('%H:%M')\nb = f'{x:%d %b}'\nc = f'{n:.1f}'\n")
    assert [line for line, fmt in _formats(tree) if _DATE_OR_CLOCK.search(fmt)] == [1, 2]
