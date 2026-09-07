"""Drift guard: every ``_run_query(...)`` call must pass ``on_error=``.

The audit that produced this test (2026-09-07): centre panels had no shared
way to say "this failed to load", and 11 of the 37 ``_run_query`` call sites
in ``metatv/gui`` had no ``on_error`` at all — a failed READ left a spinner
forever (nothing ever cleared the "Loading…" placeholder) and a failed WRITE
left the UI showing the old state with no explanation (nothing told the user
the click didn't take). ``ToolView.show_panel_error`` (reads) and
``_FavoritesMixin._write_failed`` (writes) exist so every call site has
somewhere to route the failure — this test is what keeps the next one wired.

Matching is done over the parsed AST, not line text (same reasoning as
``test_url_cycle.py``'s ``ordered_urls`` chokepoint guard): a call missing
``on_error=`` is a real ``ast.Call`` node with no matching ``ast.keyword``,
never a grep for the substring, so a comment or docstring that merely
*mentions* ``_run_query`` can never trip it.

``_KNOWN_BARE_RUN_QUERY_CALLS`` is a SHRINK-ONLY allowlist (mirrors
``tests/code_health_baseline.json``'s ratchet) for a call whose failure is
genuinely harmless to ignore — seeded empty, because the 2026-09-07 audit
found none: every one of the 11 bare calls got an ``on_error``, not a
listing. A new bare call must justify itself with a comment IN THE ALLOWLIST
entry below, not just land here silently.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GUI_ROOT = _REPO_ROOT / "metatv" / "gui"

# Shrink-only. Format: "relpath:lineno" (the line the `_run_query(` call
# itself starts on). Empty on purpose — see module docstring.
_KNOWN_BARE_RUN_QUERY_CALLS: set[str] = set()


def _find_run_query_calls(root: Path) -> list[tuple[str, int, bool]]:
    """Return (relpath, lineno, has_on_error) for every ``_run_query(`` call
    under *root*."""
    results: list[tuple[str, int, bool]] = []
    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(_REPO_ROOT))
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError:  # pragma: no cover - not our concern here
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_run_query"
            ):
                has_on_error = any(kw.arg == "on_error" for kw in node.keywords)
                results.append((rel, node.lineno, has_on_error))
    return results


def test_every_run_query_call_passes_on_error() -> None:
    """Every ``_run_query(...)`` call site under ``metatv/gui`` must pass
    ``on_error=`` — a failed read must clear its "Loading…" placeholder (or
    paint the panel it feeds) and a failed write must tell the user, never
    leave stale state with no explanation.
    """
    calls = _find_run_query_calls(_GUI_ROOT)
    assert calls, "found zero _run_query call sites — the AST walk itself is broken"

    violations = []
    for rel, lineno, has_on_error in calls:
        key = f"{rel}:{lineno}"
        if has_on_error:
            continue
        if key in _KNOWN_BARE_RUN_QUERY_CALLS:
            continue
        violations.append(key)

    if violations:
        report = "\n".join(f"  {v}" for v in sorted(violations))
        pytest.fail(
            f"Found {len(violations)} _run_query(...) call(s) with no on_error=:\n"
            f"{report}\n"
            "Pass on_error= (a panel error row for a read, self._write_failed(...) "
            "for a write), or add a justified entry to "
            "_KNOWN_BARE_RUN_QUERY_CALLS if this one's failure is genuinely "
            "harmless to ignore."
        )


def test_known_bare_call_allowlist_entries_are_still_bare() -> None:
    """The allowlist may only SHRINK: an entry for a call that now HAS
    on_error is stale and must be removed, exactly like
    ``code_health_baseline.json``'s ratchet."""
    calls = {
        f"{rel}:{lineno}": has_on_error
        for rel, lineno, has_on_error in _find_run_query_calls(_GUI_ROOT)
    }
    stale = [
        key for key in _KNOWN_BARE_RUN_QUERY_CALLS
        if calls.get(key) is not False
    ]
    assert not stale, (
        f"Stale _KNOWN_BARE_RUN_QUERY_CALLS entries (already fixed or moved — "
        f"remove them): {sorted(stale)}"
    )
