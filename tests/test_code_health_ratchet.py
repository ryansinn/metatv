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
    SIZE_EXEMPT,
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


# ---------------------------------------------------------------------------
# Stale-entry check: a baseline pin above the file's current size
# ---------------------------------------------------------------------------

#: Per-file "unclaimed slack" (baseline pin minus current measured lines),
#: recorded as of GUARD-5 (2026-09-08) — 317 lines the audit found nothing
#: was ever checking: ``check_sizes`` above is one-directional by design (a
#: file may shrink freely), so a file that drops below its pin leaves that
#: much headroom for silent regrowth all the way back up to the old ceiling
#: without ever tripping the ratchet. Two of these (``discover_view.py``,
#: ``provider_editor.py``) have fallen entirely below ``SIZE_FLOOR`` and so
#: carry no legitimate reason to have a nonzero pin at all —
#: ``scripts/rebaseline_code_health.py``'s own ``main()`` would drop them on
#: the next regeneration. Fixing any of this (tightening a pin, dropping a
#: dead entry) is the owner's call, not this guard's; its only job is to
#: stop the untracked headroom from growing past what is recorded here.
#:
#: Shrink-only in the SAME one-directional shape as ``check_sizes`` itself
#: (never the two-directional "must also shrink" shape of
#: ``tests/test_local_gates_have_one_path.py``'s boolean known-sets — slack
#: legitimately drifts by a line or two on any unrelated edit to a huge
#: file, and requiring an exact match on decrease would fail the suite on
#: every such improvement): a recorded amount may go unused (file regrows
#: partway, using up its own slack) without complaint, but a path not listed
#: here has ZERO known slack, so any new gap must be added explicitly.
_KNOWN_SLACK: dict[str, int] = {
    "metatv/core/channel_name_utils.py": 1,
    "metatv/core/filter_utils.py": 25,
    "metatv/core/repositories/channel.py": 53,
    "metatv/core/repositories/channel_ingestion.py": 3,
    "metatv/core/repositories/tag.py": 5,
    "metatv/gui/details_sections.py": 4,
    "metatv/gui/discover_view.py": 47,
    "metatv/gui/epg_watchlist_mixin.py": 1,
    "metatv/gui/global_filter_dialog.py": 3,
    "metatv/gui/main_window.py": 98,
    "metatv/gui/main_window_streaming.py": 1,
    "metatv/gui/provider_editor.py": 45,
    "metatv/gui/settings_dialog_tabs.py": 1,
    "metatv/gui/sidebar/base.py": 26,
    "metatv/gui/theme.py": 4,
}


def test_baseline_has_no_new_stale_entries() -> None:
    """A baseline pin sitting above the file's current size is stale RIGHT
    NOW — unlike ``tests/conftest.py``'s ``_leak_allowlist_freshness_check``,
    a file's line count is one deterministic number, not a behavior that can
    vary between test-run orders (a leak allowlist entry can reproduce in
    CI's shard order and not in a local full run; a line count cannot), so
    there is no "a single run can't prove staleness" caveat here and this
    can hard-fail directly instead of only reporting a candidate.

    A file that no longer exists at all is the same dead-weight case taken
    to its limit, and gets zero tolerance: nothing currently references a
    deleted file's baseline entry, so any occurrence is new.
    """
    baseline = load_baseline(BASELINE_PATH)
    measured = measure_file_lines()
    file_lines = baseline.get("file_lines", {})
    assert file_lines, (
        "the baseline's file_lines section is empty — this guard has "
        "nothing to check and must not report a false pass"
    )

    deleted: list[str] = []
    slack: dict[str, int] = {}
    for path, recorded in file_lines.items():
        if path in SIZE_EXEMPT:
            continue
        cur = measured.get(path)
        if cur is None:
            deleted.append(path)
            continue
        if cur < recorded:
            slack[path] = recorded - cur

    assert not deleted, (
        "these baseline entries reference files that no longer exist in the "
        "tree — re-run scripts/rebaseline_code_health.py to drop them: "
        f"{sorted(deleted)}"
    )

    grown = {
        path: (amount, _KNOWN_SLACK.get(path, 0))
        for path, amount in slack.items()
        if amount > _KNOWN_SLACK.get(path, 0)
    }
    assert not grown, (
        "unclaimed slack grew past what GUARD-5 recorded — one of these "
        "files shrank further with nothing tightening its pin to match "
        f"(path: (new slack, known slack)): {grown}. Either record the new "
        "amount in _KNOWN_SLACK above, or re-run "
        "scripts/rebaseline_code_health.py to close the gap."
    )

    # Sanity: every recorded amount is real slack against SIZE_FLOOR/the
    # exemption set, not a leftover for a path that has since been dropped
    # from the baseline entirely (which would silently stop this guard from
    # ever checking it again).
    missing = set(_KNOWN_SLACK) - set(file_lines)
    assert not missing, (
        "these paths carry known slack but are no longer in the baseline at "
        f"all — remove them from _KNOWN_SLACK: {sorted(missing)}"
    )
