"""Debt ratchet: file-size and legacy get_session() guards.

docs/AUDIT_2026-08-16.md re-measured the 2026-06-19 audit two months later and
found one clean signal: every finding that shipped with a mechanical guard
stayed at zero; every finding that relied on discipline alone regressed
(files over 1000 lines went 4 -> 24; ``core/repositories/channel.py`` went
1016 -> 4129; ``get_session()`` sites went 76 -> 79). This test is that
guard, mechanically enforced instead of relied on.

Two tiers, same shape as ``test_no_stray_color_literals.py``:

1. Unit tests against ``check_sizes``/``check_session_calls`` (pure functions
   imported from ``scripts/rebaseline_code_health.py``, the single source of
   truth for both the live guard here and the regeneration script) with
   synthetic input — these never depend on the real tree, so they can't break
   just because a real file changed size.
2. One integration test (``test_real_tree_passes_the_ratchet``) that runs the
   real scan against the real, checked-in baseline — that is what makes the
   guard live rather than merely plausible.

The ratchet: for every ``*.py`` under ``metatv/``, ``limit = max(1000,
baseline.get(path, 0))``. A file may shrink freely; it may never grow past
its recorded baseline (or the flat 1000-line floor, for a file not yet in the
baseline). A single ``get_session()`` call count may not increase either
(CLAUDE.md: new code uses ``Database.session_scope()``).

On a violation: split the file (or route new code through
``session_scope()``), or — if the growth is a deliberate, reviewed increase —
re-run ``scripts/rebaseline_code_health.py`` and commit the updated baseline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.rebaseline_code_health import (  # noqa: E402
    BASELINE_PATH,
    check_session_calls,
    check_sizes,
    load_baseline,
    measure_file_lines,
    measure_get_session_calls,
)

# ---------------------------------------------------------------------------
# Unit tests: check_sizes against synthetic input
# ---------------------------------------------------------------------------


def test_grown_file_over_baseline_is_a_violation() -> None:
    """A file over 1000 that grew past its recorded baseline must be flagged."""
    violations = check_sizes({"a.py": 1200}, {"a.py": 1100})
    assert len(violations) == 1
    assert "a.py" in violations[0]
    assert "1200" in violations[0]
    assert "1100" in violations[0]


def test_shrunk_file_is_not_a_violation() -> None:
    """A file over 1000 that shrank must never be flagged."""
    assert check_sizes({"a.py": 1050}, {"a.py": 1100}) == []


def test_file_exactly_at_baseline_is_not_a_violation() -> None:
    """Boundary: measured == baseline must not trip the guard (no off-by-one)."""
    assert check_sizes({"a.py": 1100}, {"a.py": 1100}) == []


def test_small_file_with_no_baseline_is_not_a_violation() -> None:
    """A file under 1000 with no baseline entry is unconstrained up to 1000."""
    assert check_sizes({"a.py": 500}, {}) == []


def test_new_file_over_flat_cap_is_a_violation() -> None:
    """A brand-new file with no baseline is still capped at the flat 1000-line floor."""
    violations = check_sizes({"new.py": 1001}, {})
    assert len(violations) == 1
    assert "new.py" in violations[0]


def test_new_file_exactly_at_flat_cap_is_not_a_violation() -> None:
    """Boundary: a new file at exactly 1000 lines must not trip the flat cap."""
    assert check_sizes({"new.py": 1000}, {}) == []


def test_multiple_violations_are_all_reported() -> None:
    """Someone touching several files must see every violation, not just the first."""
    measured = {"a.py": 1200, "b.py": 1300, "c.py": 500}
    baseline = {"a.py": 1100, "b.py": 1100}
    violations = check_sizes(measured, baseline)
    assert len(violations) == 2
    joined = "\n".join(violations)
    assert "a.py" in joined
    assert "b.py" in joined
    assert "c.py" not in joined


def test_violation_message_names_both_remediation_options() -> None:
    """A guard message that doesn't say how to proceed gets deleted by the next dev."""
    message = check_sizes({"a.py": 1200}, {"a.py": 1100})[0]
    assert "split" in message.lower()
    assert "rebaseline_code_health.py" in message


# ---------------------------------------------------------------------------
# Unit tests: check_session_calls against synthetic input
# ---------------------------------------------------------------------------


def test_get_session_count_above_baseline_is_a_violation() -> None:
    violations = check_session_calls(80, 79)
    assert len(violations) == 1
    assert "80" in violations[0]
    assert "79" in violations[0]


def test_get_session_count_equal_to_baseline_is_not_a_violation() -> None:
    assert check_session_calls(79, 79) == []


def test_get_session_count_below_baseline_is_not_a_violation() -> None:
    assert check_session_calls(70, 79) == []


# ---------------------------------------------------------------------------
# Integration test: the real scan against the real, checked-in baseline
# ---------------------------------------------------------------------------


def test_real_tree_passes_the_ratchet() -> None:
    """Run the live scan against the committed baseline — the guard, for real.

    The unit tests above only prove the comparison logic is correct against
    synthetic input; this is what makes the guard live. A failure here means
    a real file grew past its ratchet limit, or ``get_session()`` calls grew
    past the recorded count — split the offending file / use
    ``session_scope()``, or re-run ``scripts/rebaseline_code_health.py`` for
    a deliberate, reviewed increase.
    """
    baseline = load_baseline(BASELINE_PATH)
    measured_lines = measure_file_lines()
    measured_sessions = measure_get_session_calls()

    violations = check_sizes(
        measured_lines, baseline.get("file_lines", {})
    ) + check_session_calls(measured_sessions, baseline.get("get_session_calls", 0))

    if violations:
        pytest.fail(
            f"Code-health ratchet violated ({len(violations)} issue(s)):\n\n"
            + "\n\n".join(violations)
        )
