#!/usr/bin/env python3
"""Roadmap reconciliation audit — the mechanical half of the Session Wrap SOP.

Two failure modes burned a full ten-release run (v0.16.0 → v0.23.0) and this
script exists to make both of them impossible to pass silently.

**Forward drift.**  59 What's New entries shipped; not one ROADMAP.md checkbox
was ticked.  "Update stale docs" was a judgment call with no mechanism, so
skipping it looked exactly like doing it.  Fixed here by a *watermark*:
``docs/ROADMAP_RECONCILED`` records the last What's New id that was actually
reconciled against ROADMAP.md.  Anything newer is reported and the script exits
non-zero, so a wrap cannot complete on vibes.

**Reverse fiction** (the worse one).  Wave scope lists recorded items as
*shipped* that were never built — "Similar Content sibling", "preference-scored
Explore columns" and "Discover pre-warm setting" were all logged as the
spec-locked Wave 7 build list, and none of the three exist in code.  That got
written into project memory as fact.  The guard: CLAUDE.md already requires a
What's New entry for every PR with user-visible behavior, so a scope item with
**no What's New entry is a fiction, not a feature**.  ``--version`` prints the
entries a release actually shipped, so the claimed scope can be mapped against
it line by line.

Usage
-----
    scripts/roadmap_audit.py                 # report unreconciled entries (exit 1 if any)
    scripts/roadmap_audit.py --version 0.24.0  # entries a given release shipped
    scripts/roadmap_audit.py --accept        # bump the watermark, AFTER reconciling

``--accept`` is not a way to silence the report.  Run it only once ROADMAP.md
has genuinely been updated in the same commit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WATERMARK = REPO_ROOT / "docs" / "ROADMAP_RECONCILED"

sys.path.insert(0, str(REPO_ROOT))

from metatv.whats_new import WHATS_NEW, latest_id  # noqa: E402


def read_watermark() -> int:
    """Return the last reconciled What's New id, or 0 if never reconciled."""
    if not WATERMARK.exists():
        return 0
    for line in WATERMARK.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            return int(line)
    return 0


def write_watermark(value: int) -> None:
    """Persist the reconciliation watermark with an explanatory header."""
    WATERMARK.write_text(
        "# Last What's New id reconciled against ROADMAP.md.\n"
        "# Bumped by scripts/roadmap_audit.py --accept, only in the same commit\n"
        "# as the ROADMAP.md edit it certifies. See docs/SESSION_WRAP.md step 3.\n"
        f"{value}\n"
    )


def unreconciled(since: int) -> list:
    """Return What's New entries newer than the watermark, oldest first."""
    return [e for e in WHATS_NEW if e.id > since]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--accept", action="store_true",
                        help="bump the watermark to the latest entry (after reconciling)")
    parser.add_argument("--version", metavar="X.Y.Z",
                        help="list the What's New entries a given release shipped")
    args = parser.parse_args()

    if args.version:
        matches = [e for e in WHATS_NEW if e.version == args.version]
        if not matches:
            print(f"No What's New entries for version {args.version}.")
            print("If a wave claimed scope for this release, every item is UNBUILT "
                  "until proven otherwise.")
            return 1
        print(f"What's New entries shipped in {args.version} ({len(matches)}):\n")
        for e in matches:
            print(f"  #{e.id:<4} {e.title}")
        print("\nMap the release's claimed scope against this list. Any claimed item")
        print("with no entry here did NOT ship — record it as NOT BUILT, never as done.")
        return 0

    mark = read_watermark()
    pending = unreconciled(mark)

    if args.accept:
        write_watermark(latest_id())
        print(f"Watermark bumped {mark} → {latest_id()}.")
        print("This certifies ROADMAP.md now reflects every entry above. Commit it "
              "together with the ROADMAP.md edit.")
        return 0

    if not pending:
        print(f"ROADMAP.md reconciled through #{mark} — nothing pending. ✓")
        return 0

    print(f"{len(pending)} What's New entries have shipped since ROADMAP.md was last")
    print(f"reconciled (watermark #{mark}). Tick or amend each one, then re-run with")
    print("--accept in the same commit as the ROADMAP.md edit.\n")
    for e in pending:
        print(f"  #{e.id:<4} [{e.version:<7}] {e.title}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
