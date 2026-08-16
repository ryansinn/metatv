#!/usr/bin/env python3
"""Regenerate the code-health debt-ratchet baseline (tests/code_health_baseline.json).

Why this exists
----------------
docs/AUDIT_2026-08-16.md re-measured the 2026-06-19 audit two months later and
found one clean signal: every finding that shipped with a mechanical guard
stayed at zero; every finding that relied on discipline alone regressed.
Files over 1000 lines went 4 -> 24 and ``core/repositories/channel.py`` went
1016 -> 4129 with nothing stopping it. This module is the guard:
``tests/test_code_health_ratchet.py`` fails the suite the moment either
number moves the wrong way.

The ratchet
-----------
For every ``*.py`` under ``metatv/``, the allowed line count is::

    limit = max(1000, baseline.get(path, 0))

A file under 1000 lines is unconstrained up to 1000 (CLAUDE.md's "Files under
1000 lines" rule, now with teeth for new files). A file already over 1000 is
frozen at its recorded baseline: it may shrink freely, never grow. Alongside
that, a single count of legacy ``get_session()`` call sites may not increase
(CLAUDE.md: new code uses ``Database.session_scope()``).

Usage
-----
    venv/bin/python scripts/rebaseline_code_health.py

Recomputes both numbers from the current tree, rewrites
``tests/code_health_baseline.json``, and prints a diff of what changed (which
files moved in/out of the >=1000 set, old -> new sizes, old -> new
``get_session()`` count).

Run this ONLY for a deliberate, reviewed increase — e.g. a split that leaves
one file still over 1000 but smaller, or an intentional new large file. Never
run it just to silence a red guard for an accidental regression; fix the
regression instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
METATV_ROOT = REPO_ROOT / "metatv"
BASELINE_PATH = REPO_ROOT / "tests" / "code_health_baseline.json"

# CLAUDE.md coding standard: "Files under 1000 lines."
SIZE_FLOOR = 1000

_GET_SESSION_CALL = re.compile(r"\bget_session\(\)")


def iter_python_files(root: Path = METATV_ROOT) -> list[Path]:
    """Return every ``*.py`` file under ``root``, sorted for stable output."""
    return sorted(root.rglob("*.py"))


def measure_file_lines(root: Path = METATV_ROOT) -> dict[str, int]:
    """Return ``{repo-relative path: raw line count}`` for every ``.py`` file.

    Raw line count, not blank/comment-stripped — this matches how
    docs/AUDIT_2026-08-16.md measured, and keeps the guard simple.
    """
    result: dict[str, int] = {}
    for path in iter_python_files(root):
        rel = str(path.relative_to(REPO_ROOT))
        result[rel] = len(path.read_text(encoding="utf-8").splitlines())
    return result


def measure_get_session_calls(root: Path = METATV_ROOT) -> int:
    """Return the total count of literal ``get_session()`` calls under ``root``."""
    total = 0
    for path in iter_python_files(root):
        total += len(_GET_SESSION_CALL.findall(path.read_text(encoding="utf-8")))
    return total


def check_sizes(measured: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """Return one actionable violation message per file over its ratchet limit.

    ``limit = max(SIZE_FLOOR, baseline.get(path, 0))``: a file may shrink
    freely; it may never grow past its recorded baseline, and a file absent
    from the baseline is capped at the flat floor. Every violation is
    reported (not just the first), and each message names the file, its
    baseline, its current size, the overage, and both remediation options.
    """
    violations: list[str] = []
    for path, lines in sorted(measured.items()):
        recorded = baseline.get(path, 0)
        limit = max(SIZE_FLOOR, recorded)
        if lines > limit:
            over = lines - limit
            basis = (
                f"baseline {recorded}"
                if path in baseline
                else f"no baseline entry, flat {SIZE_FLOOR}-line cap for new files"
            )
            violations.append(
                f"{path}: {lines} lines exceeds its ratchet limit of {limit} "
                f"({basis}), over by {over} line(s). Split the file, or — if "
                "this is a deliberate, reviewed increase — re-run "
                "scripts/rebaseline_code_health.py."
            )
    return violations


def check_session_calls(measured: int, baseline: int) -> list[str]:
    """Return a violation message if ``measured`` exceeds the ``get_session()`` baseline."""
    if measured > baseline:
        return [
            f"get_session() call count grew from {baseline} to {measured} "
            f"(+{measured - baseline}). New code should use "
            "Database.session_scope() instead (CLAUDE.md: 'Database "
            "sessions'). If this growth is a deliberate, reviewed exception, "
            "re-run scripts/rebaseline_code_health.py."
        ]
    return []


def load_baseline(path: Path = BASELINE_PATH) -> dict:
    """Load and return the baseline JSON as a dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def _write_baseline(
    file_lines: dict[str, int], get_session_calls: int, path: Path = BASELINE_PATH
) -> None:
    """Serialize the recomputed baseline to ``path``."""
    data = {
        "_comment": (
            "Debt ratchet baseline — see docs/AUDIT_2026-08-16.md. Regenerate "
            "with scripts/rebaseline_code_health.py ONLY for a deliberate, "
            "reviewed increase."
        ),
        "file_lines": dict(sorted(file_lines.items())),
        "get_session_calls": get_session_calls,
    }
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> int:
    """Recompute the baseline, write it, and print what changed."""
    old = load_baseline() if BASELINE_PATH.exists() else {}
    old_files: dict[str, int] = old.get("file_lines", {})
    old_sessions: int = old.get("get_session_calls", 0)

    all_lines = measure_file_lines()
    new_files = {path: n for path, n in all_lines.items() if n >= SIZE_FLOOR}
    new_sessions = measure_get_session_calls()

    _write_baseline(new_files, new_sessions)

    added = sorted(set(new_files) - set(old_files))
    removed = sorted(set(old_files) - set(new_files))
    changed = sorted(
        p for p in (set(new_files) & set(old_files)) if new_files[p] != old_files[p]
    )

    rel_baseline = BASELINE_PATH.relative_to(REPO_ROOT)
    print(f"Baseline written to {rel_baseline}")
    print(f"Files at/over {SIZE_FLOOR} lines: {len(old_files)} -> {len(new_files)}")

    if added:
        print("\nNewly at/over the floor:")
        for p in added:
            print(f"  + {p}: {new_files[p]}")
    if removed:
        print("\nDropped back under the floor (or deleted):")
        for p in removed:
            print(f"  - {p}: was {old_files[p]}")
    if changed:
        print("\nSize changed:")
        for p in changed:
            direction = "grew" if new_files[p] > old_files[p] else "shrank"
            print(f"  ~ {p}: {old_files[p]} -> {new_files[p]} ({direction})")
    if not (added or removed or changed):
        print("\nNo file-size changes.")

    if new_sessions != old_sessions:
        print(f"\nget_session() calls: {old_sessions} -> {new_sessions}")
    else:
        print(f"\nget_session() calls: {new_sessions} (unchanged)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
