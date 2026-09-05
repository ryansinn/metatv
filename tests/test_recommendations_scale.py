"""Recommendations must survive a library nobody has curated yet.

The owner, of a fresh test machine: *"recommended doesn't populate either."*

``score_candidates`` collected every candidate's ``metadata_id`` and bound them
all into one ``IN (...)``. SQLite compiles a bound-parameter ceiling into the
library, and past it the query does not degrade — it **raises**::

    OperationalError: too many SQL variables

``sidebar/recommended.py`` catches that and renders "Couldn't load
recommendations", so the failure looks like an empty rail rather than a crash.

Measured on the owner's library:

    with his 158 prefix exclusions      106,918 candidates   works
    with no exclusions at all           414,759 candidates   raises

The second is a **new install** — which is also the "good on raw, messy data"
case the product thesis names. Curating your way past a hard limit is not a
feature.

Why it shipped unseen: the ceiling is a compile-time constant of whatever
SQLite the interpreter is linked against — 250,000 here on 3.53.4, a different
number under CI's Python 3.12, a third in a packaged build. It is not
reproducible on the machine where the code is written.

These tests bind past the real ceiling rather than mocking it, so they fail for
the reason production fails.
"""

from __future__ import annotations

import sqlite3

import pytest

from metatv.core.sql_batching import CHUNK_SIZE, chunked, fetch_in_chunks


def _variable_ceiling() -> int:
    """Return this build's SQLITE_LIMIT_VARIABLE_NUMBER.

    Asked directly (``Connection.getlimit``, 3 microseconds) rather than found
    by binary search. The search version bound up to two million parameters per
    probe across ~21 probes, which is minutes and gigabytes on a CI runner —
    the first version of this file failed macOS CI for that reason alone, with
    nothing wrong in the code it was testing.

    The point stands either way: this is a COMPILE-TIME constant of whatever
    SQLite the interpreter links against, so the test adapts to the build it
    runs on instead of hardcoding a number that is only true here.
    """
    conn = sqlite3.connect(":memory:")
    try:
        return conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    finally:
        conn.close()


def test_a_single_in_past_the_ceiling_really_does_raise():
    """The premise. If this ever stops raising, the rest of the file is moot."""
    conn = sqlite3.connect(":memory:")
    n = _variable_ceiling() + 1
    with pytest.raises(sqlite3.OperationalError, match="too many SQL variables"):
        conn.execute("SELECT 1 WHERE 1 IN (%s)" % ",".join("?" * n), [0] * n)
    conn.close()


def test_chunking_binds_the_same_ids_without_raising():
    """THE assertion. Same ids, past the ceiling, through the helper."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE metadata (id INTEGER PRIMARY KEY)")
    ids = list(range(_variable_ceiling() + 5_000))
    # Derived from the id list, never a fixed number. The first version
    # asserted 50,000 rows while inserting ids[:50_000] from a list only as
    # long as the ceiling — so on macOS, where SQLite ships a SMALLER variable
    # limit, the list was shorter than the slice and 37,766 rows came back
    # against an expected 50,000. The test failed for its own arithmetic, on a
    # platform difference it exists to be robust to.
    present = min(10_000, len(ids))
    conn.executemany("INSERT INTO metadata VALUES (?)", [(i,) for i in ids[:present]])

    rows = fetch_in_chunks(
        lambda chunk: conn.execute(
            "SELECT id FROM metadata WHERE id IN (%s)" % ",".join("?" * len(chunk)),
            list(chunk),
        ).fetchall(),
        ids,
    )
    conn.close()

    assert len(rows) == present, (
        "chunking lost or duplicated rows; it must be a pure regrouping"
    )


def test_the_chunk_size_is_far_below_every_plausible_ceiling():
    """A size tuned to sit just under one build's limit breaks on the next."""
    assert CHUNK_SIZE <= 999, (
        f"CHUNK_SIZE={CHUNK_SIZE} is near limits real SQLite builds ship with"
    )


# ── the helper's own contract ───────────────────────────────────────────────

def test_chunks_cover_everything_in_order():
    items = list(range(1_007))
    out = [x for chunk in chunked(items, 100) for x in chunk]
    assert out == items, "chunking reordered or dropped items"


def test_a_short_list_is_one_chunk():
    assert [list(c) for c in chunked([1, 2, 3], 100)] == [[1, 2, 3]]


def test_an_empty_list_runs_no_query_at_all():
    """``IN ()`` is not valid SQL, and an empty result needs no round trip."""
    calls = []
    assert fetch_in_chunks(lambda ids: calls.append(ids) or [], []) == []
    assert calls == [], "an empty id list still issued a query"


def test_a_nonpositive_chunk_size_is_refused():
    """Silently looping forever is worse than saying no."""
    with pytest.raises(ValueError):
        list(chunked([1, 2, 3], 0))


# ── the scoring path uses it, and does not load raw_data ────────────────────
#
# PERF-21a moved the candidate fetch out of ``score_candidates`` entirely, into
# ``metatv.core.preference_candidates.fetch_candidates`` — a column-only
# statement that joins straight to ``MetadataDB`` (1:1 on ``metadata_id ==
# MetadataDB.id``, so it cannot fan out rows) instead of running a second query
# with a per-candidate ``metadata_id`` ``IN (...)`` list. That removes the
# crash site this file exists to guard: there is no longer an ``IN (...)``
# whose length scales with the candidate count, so
# ``test_a_single_in_past_the_ceiling_really_does_raise``'s premise can no
# longer reach this path at all — the two tests below moved with the code they
# describe and were rewritten for the new shape rather than deleted.

def test_fetch_candidates_joins_metadata_instead_of_a_chunked_lookup():
    """Derived from the source: no per-candidate IN (...) list survives.

    ``fetch_in_chunks`` existed ONLY because the old second query bound one
    placeholder per candidate metadata_id. Folding the join into the same
    column-only statement removes that list outright, so this asserts the
    NEW shape (a JOIN) rather than re-asserting the old chunking mechanism,
    which no longer has anything left to chunk.
    """
    import inspect

    from metatv.core import preference_candidates

    src = inspect.getsource(preference_candidates._build_candidates_query)
    assert ".join(MetadataDB" in src, (
        "the metadata fetch is not joined into the candidate statement — "
        "a second per-candidate IN (...) query would reintroduce the "
        "SQLite bound-parameter ceiling this file guards"
    )
    assert "fetch_in_chunks" not in src, (
        "a chunked metadata IN (...) reappeared; the JOIN was supposed to "
        "remove the reason it existed"
    )


def test_fetch_candidates_does_not_select_raw_data():
    """raw_data is ~half the channels table and nothing here reads it.

    Every candidate used to carry and JSON-decode that blob for nothing
    (measured at -29% wall clock / -25% peak memory when it was fixed to a
    ``defer()``); PERF-21a's column-only statement never names the column
    at all, so this checks the explicit column list instead of a ``defer()``
    call that no longer exists.
    """
    import inspect

    from metatv.core import preference_candidates

    src = inspect.getsource(preference_candidates._build_candidates_query)
    assert "raw_data" not in src, (
        "candidates are loaded with raw_data, which the scoring path never reads"
    )
