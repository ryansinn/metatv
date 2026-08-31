#!/usr/bin/env python3
"""Split the test files across N CI shards, balanced, with no plugin.

Why not a plugin
----------------
``requirements.txt`` is installed by the RELEASE build too
(``.github/workflows/release.yml``), so a test-only sharding plugin added there
ships inside the packaged app. Installing one just for the test job would work,
but this is twenty lines and has no version to track.

Why not round-robin
-------------------
Test files here are wildly uneven — the biggest is orders of magnitude slower
than the median — so ``NR % 4`` produces one shard that finishes in two minutes
and one that takes twelve, and the job is as slow as its slowest shard. This
does a greedy longest-first bin-pack instead: sort by size descending, and put
each file in whichever shard is currently smallest.

Size is a proxy for duration, not a measurement. It is a good enough one — the
alternative is committing a durations file and keeping it fresh, which is a
maintenance burden for a second-order improvement. If shards drift badly out of
balance, that is the point to reach for real timings.

The split is deterministic: same tree, same assignment, on every runner. Each
shard prints its own files, and every file lands in exactly one shard.

Usage:
    python scripts/ci_shard.py --shard 1 --of 4
"""

from __future__ import annotations

import argparse
import pathlib
import sys


def shard_files(root: pathlib.Path, shard: int, of: int) -> list[pathlib.Path]:
    """Return the test files belonging to *shard* (1-based) of *of*."""
    if not 1 <= shard <= of:
        raise SystemExit(f"shard {shard} out of range 1..{of}")

    files = sorted(root.glob("test_*.py"))
    if not files:
        raise SystemExit(f"no test files found under {root}")

    # Greedy longest-processing-time: biggest first into the emptiest bin.
    bins: list[list[pathlib.Path]] = [[] for _ in range(of)]
    sizes = [0] * of
    for path in sorted(files, key=lambda p: p.stat().st_size, reverse=True):
        target = sizes.index(min(sizes))
        bins[target].append(path)
        sizes[target] += path.stat().st_size

    return sorted(bins[shard - 1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard", type=int, required=True, help="1-based shard index")
    ap.add_argument("--of", type=int, required=True, help="total shards")
    ap.add_argument("--tests-dir", default="tests", help="directory to split")
    args = ap.parse_args()

    root = pathlib.Path(args.tests_dir)
    for path in shard_files(root, args.shard, args.of):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
