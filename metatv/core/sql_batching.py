"""Splitting an ``IN (...)`` list that SQLite will not accept whole.

SQLite compiles a bound-parameter limit into the library —
``SQLITE_LIMIT_VARIABLE_NUMBER`` — and a query with more placeholders than that
does not run slowly, it **raises**::

    OperationalError: too many SQL variables

Measured on this machine at 250,000 (SQLite 3.53.4). It is a COMPILE-TIME
constant of whatever SQLite the interpreter is linked against, so the threshold
differs between the developer's Python 3.14 and CI's 3.12, and between either
of those and a packaged build. That is exactly the shape of divergence that
makes a limit like this ship undetected: it is not reproducible on the machine
where the code is written.

The chunk size here is far below every plausible ceiling, because the cost of
chunking is one extra query per chunk and the cost of not chunking is an
exception the caller renders as "couldn't load".

There are 147 ``.in_()`` call sites in this package. This helper exists so the
next one that grows unbounded has somewhere to go rather than growing its own
loop — ``provider_loader.py`` already grew one (``_CHUNK = 500``), which is
recorded in the duplication ledger.
"""

from __future__ import annotations

from typing import Callable, Iterable, Iterator, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

#: Placeholders per query. Comfortably under SQLite's compiled limit on every
#: build this ships against, and small enough that a chunk's own query plan
#: stays cheap. Not tuned to any measured ceiling on purpose: a size chosen to
#: sit just under one build's limit is a size that breaks on the next build.
CHUNK_SIZE = 500


def chunked(items: "Sequence[T]", size: int = CHUNK_SIZE) -> "Iterator[Sequence[T]]":
    """Yield *items* in slices of at most *size*.

    Args:
        items: The sequence to split. Empty yields nothing.
        size: Maximum slice length.

    Yields:
        Consecutive slices covering *items* in order.

    Raises:
        ValueError: If *size* is not positive.
    """
    if size <= 0:
        raise ValueError(f"chunk size must be positive, got {size}")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def fetch_in_chunks(
    fetch: "Callable[[Sequence[T]], Iterable[R]]",
    items: "Sequence[T]",
    size: int = CHUNK_SIZE,
) -> "list[R]":
    """Run *fetch* over *items* in chunks and concatenate the results.

    ``fetch`` receives one chunk and returns that chunk's rows::

        rows = fetch_in_chunks(
            lambda ids: session.query(MetadataDB)
                               .filter(MetadataDB.id.in_(ids)).all(),
            metadata_ids,
        )

    Args:
        fetch: Called once per chunk with that chunk's items.
        items: The full list of values to bind. Empty means no call at all —
            ``IN ()`` is not valid SQL, and an empty result needs no query.
        size: Maximum values bound per call.

    Returns:
        Every row from every chunk, in chunk order.
    """
    if not items:
        return []
    out: list[R] = []
    for chunk in chunked(items, size):
        out.extend(fetch(chunk))
    return out
