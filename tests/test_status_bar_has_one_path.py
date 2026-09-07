"""STATUS-1 drift guard: ``status_bar.showMessage()`` has exactly one path.

95 raw ``self.status_bar.showMessage(...)`` calls used to sit across a dozen
``main_window_*.py`` mixins — 64 persistent, the rest split across five
different ad-hoc timeouts, an error and a hint indistinguishable from each
other, and nothing able to route an error anywhere else. ``main_window_status.py``
collapsed all of it into one ``MainWindow.status(text, *, ms=4000,
level="info")`` method; every mixin now calls ``self.status(...)`` instead.

Nothing stops a LATER PR from hand-rolling ``self.status_bar.showMessage(...)``
again in some new call site — exactly how the original 95-site drift
happened, one showMessage() at a time. This test closes that hole: any call
to ``.showMessage(...)`` on a ``status_bar``-named target (``self.status_bar``,
``host.status_bar``, a bare ``status_bar`` parameter, or ``self.statusBar()``)
anywhere under ``metatv/`` outside ``main_window_status.py`` fails the suite.

Matching is done over the parsed AST, not line text — a regex over source
lines also fires on a docstring or comment that only MENTIONS
``status_bar.showMessage`` (this module's own docstring above is exactly such
a case), which is the wrong reason to fail and the kind of guard that gets
deleted the first time it cries wolf on prose. Mirrors
``tests/test_url_cycle.py``'s ``ordered_urls()`` chokepoint guard and
``tests/test_stored_fields_have_readers.py``'s allowlist shape.

``clearMessage()`` is deliberately NOT covered — CLAUDE.md/the STATUS-1 brief
call out clearing as a separate, already-single-path concern
(``_NavMixin._hide_all_content_views()``; see
``tests/test_status_line_follows_the_view.py``).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_METATV_ROOT = _REPO_ROOT / "metatv"
_CHOKEPOINT = _METATV_ROOT / "gui" / "main_window_status.py"
_ALLOWLIST_PATH = Path(__file__).resolve().parent / "status_bar_allowlist.json"


def _load_allowlist() -> dict:
    with open(_ALLOWLIST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _allowlisted_files() -> set[str]:
    return {entry["file"] for entry in _load_allowlist()["entries"]}


def _is_status_bar_showmessage(node: ast.Call) -> bool:
    """True for ``<expr>.showMessage(...)`` where ``<expr>`` is a status-bar target.

    Covers ``self.status_bar.showMessage(...)``/``host.status_bar.showMessage(...)``
    (an ``Attribute`` node whose own attr is ``status_bar``), a bare
    ``status_bar.showMessage(...)`` (a local/parameter named ``status_bar``,
    e.g. ``downloaded_scope.show_empty``'s pre-fix signature), and
    ``self.statusBar().showMessage(...)``.
    """
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "showMessage"):
        return False
    target = func.value
    if isinstance(target, ast.Attribute) and target.attr == "status_bar":
        return True
    if isinstance(target, ast.Name) and target.id == "status_bar":
        return True
    if (
        isinstance(target, ast.Call)
        and isinstance(target.func, ast.Attribute)
        and target.func.attr == "statusBar"
    ):
        return True
    return False


def _violations_in(path: Path) -> list[int]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:  # pragma: no cover - not our concern here
        return []
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_status_bar_showmessage(node)
    ]


def _all_violations() -> dict[str, list[int]]:
    allowlisted = _allowlisted_files()
    found: dict[str, list[int]] = {}
    for path in sorted(_METATV_ROOT.rglob("*.py")):
        if path == _CHOKEPOINT:
            continue
        rel = str(path.relative_to(_REPO_ROOT))
        if rel in allowlisted:
            continue
        hits = _violations_in(path)
        if hits:
            found[rel] = hits
    return found


def test_status_bar_showmessage_has_one_path() -> None:
    """Every ``status_bar.showMessage(...)`` call lives in ``main_window_status.py``.

    If this fires: replace the direct call with ``self.status(text, ms=...,
    level=...)``, or — for a genuine non-host status bar — add a one-line
    reason to ``tests/status_bar_allowlist.json``.
    """
    violations = _all_violations()
    if not violations:
        return

    report = "\n".join(
        f"  {rel}:{lines}" for rel, lines in violations.items()
    )
    pytest.fail(
        f"Found status_bar.showMessage() call(s) outside "
        f"metatv/gui/main_window_status.py:\n{report}"
    )


def test_the_allowlist_only_shrinks() -> None:
    """An allowlisted file that no longer calls ``status_bar.showMessage()``
    at all (e.g. it was refactored to route through ``self.status(...)``)
    must be REMOVED from ``status_bar_allowlist.json``, never left there as
    dead weight — same rule as ``tests/unwired_stored_fields_allowlist.json``'s
    companion test. Trivially satisfied today: the allowlist is seeded empty,
    since the app has exactly one QStatusBar."""
    stale = []
    for entry in _load_allowlist()["entries"]:
        path = _REPO_ROOT / entry["file"]
        if not path.exists() or not _violations_in(path):
            stale.append(entry["file"])
    assert not stale, (
        "these are allowlisted but no longer call status_bar.showMessage() — "
        "remove them from tests/status_bar_allowlist.json:\n  "
        + "\n  ".join(stale)
    )
