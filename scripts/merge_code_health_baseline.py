#!/usr/bin/env python3
"""Git merge driver for ``tests/code_health_baseline.json``.

The baseline is DERIVED data — a snapshot of per-file line counts and the
``get_session()`` call count — so every branch that touches a tracked file
rewrites it, and any two such branches conflict on merge or rebase.  The
resolution was always mechanical (regenerate, never hand-merge the JSON), but
it had to be done by hand: five rebases in one evening, each discarding a green
CI run and restarting a ten-minute gate.

**Resolution: per-key maximum of both sides.**

Regenerating from the working tree looks more correct — it is the file's own
definition — but a merge driver runs *during* the merge, when the tree is not
guaranteed to hold the final content of every path.  A regenerated value that
was too low would reintroduce exactly the false ratchet failure this exists to
remove.  The maximum needs no tree access, is order-independent, and is safe by
construction: the ratchet is ``limit = max(1000, baseline)``, and each side's
recorded value already passed on its own branch, so the larger of the two
cannot fail either.

The cost is that it is slightly LAX: a shrink recorded on one branch is lost
when the other side kept a higher number.  Nothing breaks — the ratchet's
direction still holds — and the next ``scripts/rebaseline_code_health.py`` run
re-tightens every entry to its true value.  A driver that never blocks and is
occasionally loose beats one that is exact and stops the merge.

Registered by ``scripts/setup_merge_drivers.sh``; bound to the path by
``.gitattributes``.  Git calls it as::

    merge_code_health_baseline.py %O %A %B

writing the resolved content back to %A and exiting 0 on success.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _load(path: str) -> dict[str, Any]:
    """Return the JSON at *path*, or ``{}`` when it is missing or unparseable.

    The ancestor side is legitimately absent the first time the file appears on
    a branch, and a half-written side should degrade to "contributes nothing"
    rather than abort the merge.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_baselines(ours: dict[str, Any], theirs: dict[str, Any]) -> dict[str, Any]:
    """Combine two baselines by taking the larger limit for every entry.

    Args:
        ours:   The baseline from the current branch.
        theirs: The baseline from the branch being merged in.

    Returns:
        A baseline holding the union of both sides' files, each at the higher
        of the two recorded line counts, and the higher ``get_session_calls``.
    """
    merged: dict[str, Any] = dict(ours) or dict(theirs)

    our_files = ours.get("file_lines") or {}
    their_files = theirs.get("file_lines") or {}
    if our_files or their_files:
        merged["file_lines"] = {
            path: max(our_files.get(path, 0), their_files.get(path, 0))
            for path in sorted(set(our_files) | set(their_files))
        }

    calls = [
        side["get_session_calls"]
        for side in (ours, theirs)
        if isinstance(side.get("get_session_calls"), int)
    ]
    if calls:
        merged["get_session_calls"] = max(calls)

    # Keep whichever side still carries the explanatory comment.
    comment = ours.get("_comment") or theirs.get("_comment")
    if comment:
        merged["_comment"] = comment

    return merged


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(
            "usage: merge_code_health_baseline.py <ancestor> <ours> <theirs>",
            file=sys.stderr,
        )
        return 2

    _ancestor, ours_path, theirs_path = argv[1], argv[2], argv[3]
    merged = merge_baselines(_load(ours_path), _load(theirs_path))
    if not merged:
        print("baseline merge: both sides unreadable, leaving conflict",
              file=sys.stderr)
        return 1

    ordered = {k: merged[k] for k in ("_comment", "file_lines", "get_session_calls")
               if k in merged}
    ordered.update({k: v for k, v in merged.items() if k not in ordered})

    with open(ours_path, "w", encoding="utf-8") as fh:
        json.dump(ordered, fh, indent=2)
        fh.write("\n")

    print(
        "baseline merge: resolved by per-key maximum — run "
        "scripts/rebaseline_code_health.py to re-tighten.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
