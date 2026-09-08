#!/usr/bin/env python3
"""Measure derived-field coverage against a REAL database — the numbers half
of W-0's guard, since CI has no real library to measure against.

``tests/test_derived_field_coverage.py`` proves the shape of the bug (one
representative row per media_type, run through the real ingestion +
metadata-backfill pipeline) but cannot tell you the RATE on a real 785k-row
library — a non-null-rate assertion in CI would prove nothing there. This
script is what re-measures the owner's library after a fix (W-1/W-2) lands:
run it, confirm the field's percentage moved, and confirm nothing else
regressed.

Read-only, always. Opens the database with SQLite's own ``mode=ro`` URI flag
(the same guarantee ``sqlite3 'file:...?mode=ro'`` gives on the command
line) — never through ``metatv.core.database.Database``, which runs pragmas
and one-time migrations as a side effect of opening. This script only ever
reads.

Usage
-----
    scripts/derived_field_coverage.py                  # ~/.local/share/metatv/metatv.db
    scripts/derived_field_coverage.py /path/to/other.db

Exits non-zero if any field is >95% empty for a population that has at least
one row — same floor CLAUDE.md's audit language uses ("failing when a field
is >95% empty for a population whose source key exists"). A population with
zero rows (e.g. no live channels in this library) is reported, not flagged —
100% of zero is not evidence of anything.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from metatv.core.derived_field_coverage import (  # noqa: E402
    CHANNEL_FIELDS,
    CHANNEL_MEDIA_TYPES,
    METADATA_FIELDS,
    METADATA_MEDIA_TYPES,
)

#: Same three columns censused in tests/test_derived_field_coverage.py — the
#: shrink-only guard's flagship-failure floor, applied to a real library
#: instead of one synthetic row.
_EMPTY_FAIL_THRESHOLD = 0.95

_DEFAULT_DB = Path.home() / ".local" / "share" / "metatv" / "metatv.db"


def _empty_predicate(column: str) -> str:
    """SQL predicate matching ``derived_field_coverage.is_empty`` in Python.

    A JSONEncoded column (``detected_genres``, ``genres``, ``cast``, ...)
    stores an empty list/dict as the literal text ``'[]'``/``'{}'`` — NOT
    NULL — so a bare ``COUNT(column)`` would misreport those rows as
    populated. Mirrors ``is_empty``'s sentinel set exactly so the two never
    disagree about what "empty" means.

    The column name is double-quoted as an SQL identifier — ``cast`` (a real
    MetadataDB column) is also a SQL keyword, and an unquoted ``cast IS
    NULL`` is a syntax error (SQLite parses it as the start of a ``CAST(...)``
    expression).
    """
    col = f'"{column}"'
    return f"({col} IS NULL OR {col} = '' OR {col} = '[]' OR {col} = '{{}}')"


def _row_counts(conn: sqlite3.Connection, table: str, media_type_col: str,
                 field: str, media_type: str) -> tuple[int, int]:
    """Return ``(total, populated)`` for *field* within *media_type*."""
    query = (
        f"SELECT COUNT(*), "
        f"SUM(CASE WHEN {_empty_predicate(field)} THEN 0 ELSE 1 END) "
        f'FROM "{table}" WHERE "{media_type_col}" = ?'
    )
    total, populated = conn.execute(query, (media_type,)).fetchone()
    return total or 0, populated or 0


def measure(db_path: Path) -> tuple[list[dict], bool]:
    """Return ``(rows, any_over_threshold)`` for every censused combo.

    Args:
        db_path: Path to the SQLite database file, opened read-only.

    Returns:
        ``rows`` — one dict per (field, media_type) combo with
        ``table``/``field``/``media_type``/``total``/``populated``/``pct_empty``.
        ``any_over_threshold`` — True if any combo with >=1 row is more than
        ``_EMPTY_FAIL_THRESHOLD`` empty.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    rows: list[dict] = []
    any_over = False
    try:
        for field in CHANNEL_FIELDS:
            for media_type in CHANNEL_MEDIA_TYPES:
                total, populated = _row_counts(conn, "channels", "media_type", field, media_type)
                pct_empty = 1.0 if total == 0 else (total - populated) / total
                over = total > 0 and pct_empty > _EMPTY_FAIL_THRESHOLD
                any_over = any_over or over
                rows.append({
                    "table": "channels", "field": field, "media_type": media_type,
                    "total": total, "populated": populated, "pct_empty": pct_empty,
                    "over_threshold": over,
                })
        for field in METADATA_FIELDS:
            for media_type in METADATA_MEDIA_TYPES:
                total, populated = _row_counts(conn, "metadata", "media_type", field, media_type)
                pct_empty = 1.0 if total == 0 else (total - populated) / total
                over = total > 0 and pct_empty > _EMPTY_FAIL_THRESHOLD
                any_over = any_over or over
                rows.append({
                    "table": "metadata", "field": field, "media_type": media_type,
                    "total": total, "populated": populated, "pct_empty": pct_empty,
                    "over_threshold": over,
                })
    finally:
        conn.close()
    return rows, any_over


def _print_table(rows: list[dict]) -> None:
    header = f"{'table':<10} {'field':<20} {'media_type':<8} {'total':>9} {'populated':>10} {'% empty':>8}"
    print(header)
    print("-" * len(header))
    for r in rows:
        flag = " <-- >95% empty" if r["over_threshold"] else ""
        if r["total"] == 0:
            pct = "n/a (0 rows)"
        else:
            pct = f"{r['pct_empty'] * 100:.1f}%"
        print(
            f"{r['table']:<10} {r['field']:<20} {r['media_type']:<8} "
            f"{r['total']:>9,} {r['populated']:>10,} {pct:>8}{flag}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "db_path", nargs="?", default=str(_DEFAULT_DB),
        help=f"SQLite database path (default: {_DEFAULT_DB})",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"No database at {db_path} — nothing to measure.", file=sys.stderr)
        return 1

    rows, any_over = measure(db_path)
    _print_table(rows)
    print()

    flagged = [r for r in rows if r["over_threshold"]]
    if flagged:
        print(f"{len(flagged)} field/media_type combo(s) are >{_EMPTY_FAIL_THRESHOLD:.0%} empty:")
        for r in flagged:
            print(f"  {r['table']}.{r['field']} | {r['media_type']}"
                  f" — {r['pct_empty'] * 100:.1f}% empty of {r['total']:,} rows")
        return 1

    print("No field/media_type combo exceeds the "
          f"{_EMPTY_FAIL_THRESHOLD:.0%}-empty floor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
