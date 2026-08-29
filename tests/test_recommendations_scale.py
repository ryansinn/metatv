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

def test_score_candidates_chunks_its_metadata_lookup():
    """Derived from the source: the crash site must go through the helper."""
    import inspect

    from metatv.core import preference_engine

    src = inspect.getsource(preference_engine.score_candidates)
    assert "fetch_in_chunks" in src, (
        "the metadata lookup binds every candidate id in one IN (...) again"
    )


def test_score_candidates_does_not_select_raw_data():
    """raw_data is ~half the channels table and nothing here reads it.

    The only mention of it in this module or content_dedup is a comment saying
    a column-only query avoids loading it — every candidate was carrying and
    JSON-decoding the blob for nothing.
    """
    import inspect

    from metatv.core import preference_engine

    src = inspect.getsource(preference_engine.score_candidates)
    assert "defer(ChannelDB.raw_data)" in src, (
        "candidates are loaded with raw_data, which the scoring path never reads"
    )
