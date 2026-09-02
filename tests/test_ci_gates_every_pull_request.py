"""CI must gate EVERY pull request, including one stacked on another.

The hole this closes: ``pull_request.branches`` filters on the BASE branch, so
``branches: [main]`` meant a PR whose base was another feature branch got **no
checks at all** — not slow, not pending, zero, silently, by configuration.

That is the same failure the workflow itself was created to fix, wearing
different clothes. Its own header records the first one: before 2026-08-27 the
suite ran only AFTER merge, and 58 failures accumulated across five merges
before anyone noticed. "Runs unless you stack" is the second, and it is worse
in one specific way — a PR with zero checks reads as "nothing has failed"
rather than "nothing has run".

Asserted against the file rather than trusted to review, because a
``branches:`` filter is one line, looks like tidy hygiene, and its cost is
invisible until someone stacks a PR.
"""
from __future__ import annotations

import pathlib

import yaml

_WORKFLOW = pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml"


def _triggers(doc: dict) -> dict:
    """The ``on:`` block.

    YAML 1.1 reads a bare ``on`` key as the BOOLEAN True, so ``doc["on"]``
    is a ``KeyError`` and a test that used it would fail for a reason that has
    nothing to do with CI. Handle both spellings.
    """
    for key in (True, "on"):
        if key in doc:
            return doc[key] or {}
    raise AssertionError("ci.yml has no `on:` block")


def _load() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def test_the_pull_request_trigger_has_no_base_branch_filter():
    triggers = _triggers(_load())
    assert "pull_request" in triggers, "CI no longer runs on pull requests at all"

    config = triggers["pull_request"] or {}
    assert "branches" not in config, (
        "ci.yml restricts the PR gate by base branch again. `branches:` filters "
        "on the BASE, so this gives a stacked PR zero checks — which reads as "
        f"'nothing failed' rather than 'nothing ran'. Found: {config['branches']!r}"
    )
    assert "branches-ignore" not in config, (
        "a branches-ignore filter has the same effect for whatever it excludes")


def test_the_gate_still_covers_both_platforms():
    """Removing one filter must not quietly remove the reason the gate exists.

    The nine failures that hid for three weeks were macOS-only (a system menu
    bar, a font rasterizer painting the same token at a different size). A
    Linux-only gate would have caught none of them.
    """
    jobs = _load()["jobs"]
    runners = yaml.dump(jobs)
    assert "ubuntu-latest" in runners and "macos" in runners, (
        "the suite no longer runs on both platforms")


def test_concurrency_is_keyed_per_pull_request():
    """Every PR now runs, so the cancel key has to be per-PR or one PR's push
    would cancel another's in-flight gate.

    ``github.ref`` is ``refs/pull/<n>/merge`` on a pull_request event, which is
    unique per PR. A key that dropped it — grouping by workflow alone — would
    turn "every PR is gated" into "the most recent PR is gated".
    """
    group = _load().get("concurrency", {}).get("group", "")
    assert "github.ref" in group or "github.head_ref" in group, (
        f"concurrency group {group!r} is not per-PR; with the base-branch "
        "filter gone this would let one PR cancel another's gate")
