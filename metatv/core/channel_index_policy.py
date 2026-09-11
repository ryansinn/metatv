"""ChannelDB's STORAGE-1a index-diet policy — which indexes get dropped, and
which get rebuilt as PARTIAL instead of FULL.

Pure declarative data, no dependencies — ``database.py``'s ``ChannelDB``
imports :data:`CHANNEL_PARTIAL_INDEX_SPECS` for its ``__table_args__`` and
``Database._migrate()`` calls :func:`legacy_index_drop_sql` for its
``DROP INDEX`` list, so the drop names and their replacement shapes can never
drift apart into two hand-typed lists that silently disagree
(docs/REFACTOR_PLAN.md D55/D56/D58 has the full measured case;
core/migrations/query_indexes.py has the mechanism — ``QueryIndexTask`` —
these drive).

``is_favorite`` is deliberately NOT one of the 24 partial conversions below,
even though it looked like an obvious one — see :data:`CHANNEL_DEAD_INDEX_NAMES`'s
docstring for why a first version of this policy shipped it as a conversion
and CI caught the planner regression that proved it wrong.

Why a partial index at all
---------------------------
SQLite indexes NULLs. A column that is 99%+ NULL still costs a full index
entry per row: ``last_played`` measured 7.4 MiB indexing 25 non-NULL rows out
of 786,324 on the owner's library. ``sqlite_where=text("<col> IS NOT NULL")``
(or ``= 1`` for a boolean flag column, ``> 0`` for the one counter,
``rec_shown_count``) makes SQLite store only the rows that actually have a
value.

Safe for ``col = ?``, not for ``col IS NULL``
------------------------------------------------
``WHERE col = 'x'`` implies ``col IS NOT NULL``, so SQLite's partial-index
analysis still chooses the (now much smaller) index for an equality lookup
on the SAME column — re-verified per column with EXPLAIN QUERY PLAN rather
than trusted from citation (``tests/test_query_indexes.py``, and the PR body
has before/after plans for the three busiest). It does NOT serve an
``IS NULL`` filter on that column — every one of these 24 was checked against
its own ``IS NULL`` call sites, and in each case NULL is itself the vast
majority of rows (as low as 0.02% non-NULL), a selectivity no b-tree index —
partial or not — ever served anyway.

The naming trap (#616)
------------------------
Each partial index's NAME is unchanged from its old ``ix_channels_<col>``
form, on purpose: :func:`legacy_index_drop_sql` drops the OLD full-shape
index by that name, and ``QueryIndexTask`` (core/migrations/query_indexes.py)
then builds the declared-but-missing index in ITS new partial shape — the
same DB-6 mechanism every other declared index already uses, no new
machinery. A column here must NEVER also carry ``index=True`` on its
``Column(...)`` declaration in ``database.py``, or the generated sweep
recreates exactly the full shape the drop just removed.

The drop runs SHAPE-conditional, not name-conditional (#831/DB-11): it fires
only for an index whose ``sqlite_master`` definition carries no ``WHERE`` —
the old full shape. Dropping unconditionally by name shipped for two days
and re-dropped the PARTIAL index ``QueryIndexTask`` had just rebuilt on the
PREVIOUS launch — the drop and the rebuild share a name — so every single
launch rebuilt all 23 conversions plus a full ``ANALYZE`` (~12-15s on the
owner's 786k-row table). Checking the stored shape first means the drop
fires once per upgrading library and never again once a column is partial.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

#: (column, sqlite_where) for the 24 columns converted from a FULL
#: ``index=True`` index to a PARTIAL one — see the module docstring for the
#: full safety argument and the naming trap.
CHANNEL_PARTIAL_INDEX_SPECS: tuple[tuple[str, str], ...] = (
    ("detected_quality", "detected_quality IS NOT NULL"),
    ("is_adult", "is_adult = 1"),
    ("is_rec_suppressed", "is_rec_suppressed = 1"),
    ("last_played", "last_played IS NOT NULL"),
    ("watch_completed", "watch_completed = 1"),
    ("special_view", "special_view IS NOT NULL"),
    ("event_start_time", "event_start_time IS NOT NULL"),
    ("event_stop_time", "event_stop_time IS NOT NULL"),
    ("sport_type", "sport_type IS NOT NULL"),
    ("signal_verdict", "signal_verdict IS NOT NULL"),
    ("signal_checked_at", "signal_checked_at IS NOT NULL"),
    ("league_name", "league_name IS NOT NULL"),
    ("team_name", "team_name IS NOT NULL"),
    ("rec_shown_count", "rec_shown_count > 0"),
    ("tmdb_enrich_state", "tmdb_enrich_state IS NOT NULL"),
    ("genre_enrich_state", "genre_enrich_state IS NOT NULL"),
    ("metadata_enrich_state", "metadata_enrich_state IS NOT NULL"),
    ("detected_genre", "detected_genre IS NOT NULL"),
    ("detected_restricted", "detected_restricted = 1"),
    ("detected_name_collection", "detected_name_collection IS NOT NULL"),
    ("detected_episode", "detected_episode IS NOT NULL"),
    ("source_category", "source_category IS NOT NULL"),
    ("user_category", "user_category IS NOT NULL"),
)

#: Four STORAGE-1a drops, NO replacement (docs/REFACTOR_PLAN.md D55/D58):
#: ``idx_channels_detected_prefix`` is an exact duplicate of the ORM-declared
#: ``ix_channels_detected_prefix`` (``detected_prefix``'s own ``index=True``)
#: and is declared nowhere else in the codebase — an orphan from a removed
#: migration. ``ix_channels_is_hidden`` is a strict left-prefix of
#: ``ix_channels_hidden_name`` (is_hidden, name), which already serves
#: ``WHERE is_hidden = ?`` alone from its leading column. ``ix_channels_language``
#: indexes ``ChannelDB.language``, which is 786,324/786,324 NULL with zero
#: readers anywhere in ``metatv/`` or ``tests/`` (not in
#: ``provider_loader._CATALOG_COLS``, so the catalog upsert never even writes
#: it). None of ``is_hidden``/``language``/``is_favorite`` carries ``index=True``
#: on its ``Column(...)`` any more, so these stay dropped — the columns
#: themselves stay (dropping one needs a table rebuild, Slice B's territory).
#:
#: ``ix_channels_is_favorite`` (D58, found by CI, not by design) is
#: SUBSUMED by ``ChannelDB.__table_args__``'s ``ix_channels_favorite_hidden_name``
#: — ``(is_hidden, name) WHERE is_favorite = 1`` — even though it is not a
#: literal column-list left-prefix of it (``is_favorite`` is not one of that
#: composite's indexed columns, only its WHERE). The two indexes cover the
#: EXACT SAME 28-row set (both are gated by the identical ``is_favorite = 1``
#: predicate), so the standalone index buys nothing a scan of the composite
#: doesn't already give for free, and having two candidates gave the planner
#: a genuine choice it sometimes got wrong: a first version of this policy
#: shipped ``is_favorite`` as a 25th PARTIAL conversion, and CI (whose SQLite
#: is built without STAT4, unlike this repo's local Python 3.14 — see
#: query_indexes.py's module docstring) chose the narrower standalone index
#: for the channel list's own Favorites query and paid for it with an added
#: ``USE TEMP B-TREE FOR ORDER BY`` the composite would have avoided — the
#: exact 1.8x-regression shape that index's OWN docstring already warns
#: about. Verified with real EXPLAIN QUERY PLAN probes against every genuine
#: ``is_favorite`` call site in ``metatv/`` (``media_mix.py``,
#: ``channel_provider_ops.py``'s engaged-OR-clause, ``discovery_engine.py``,
#: ``preference_engine.py`` x2): dropping the standalone index never makes
#: any of them worse — the OR-clause site was already a full ``SCAN`` with or
#: without it, and the bare ``WHERE is_favorite = 1`` sites still touch
#: exactly 28 rows via the composite (a ``SCAN`` of a 28-row partial index
#: instead of a ``SEARCH``, a distinction with no measurable cost at this
#: cardinality). Census over the other 23 partial conversions: NONE of them
#: share a ``sqlite_where`` with any pre-existing composite (the only other
#: two composites, ``ix_channels_hidden_type_name``/``ix_channels_hidden_name``,
#: carry no WHERE clause at all) — ``grep -n "sqlite_where"
#: metatv/core/database.py`` finds exactly one hand-written composite,
#: ``ix_channels_favorite_hidden_name``, confirming ``is_favorite`` is the
#: only collision in the population, not the first of one.
CHANNEL_DEAD_INDEX_NAMES: tuple[str, ...] = (
    "idx_channels_detected_prefix",
    "ix_channels_is_hidden",
    "ix_channels_language",
    "ix_channels_is_favorite",
)

#: The 24 partial ``Index`` objects themselves, ready to splice straight into
#: ``ChannelDB.__table_args__`` (``... ) + CHANNEL_PARTIAL_INDEXES`` — built
#: here, not in ``database.py``, so that file need only import and concatenate.
CHANNEL_PARTIAL_INDEXES: tuple[Index, ...] = tuple(
    Index(f"ix_channels_{col}", col, sqlite_where=text(where))
    for col, where in CHANNEL_PARTIAL_INDEX_SPECS
)

#: All 27 STORAGE-1a drop names — the 3 dead ones plus each partial
#: conversion's old full-index name. Kept for reference/other readers even
#: though :func:`legacy_index_drop_sql` (below) is what ``_migrate()`` calls —
#: that name set is exactly the population it checks the SHAPE of before
#: acting (DB-11: an unconditional-by-name drop of this same set is the bug).
CHANNEL_DROPPED_INDEX_NAMES: tuple[str, ...] = CHANNEL_DEAD_INDEX_NAMES + tuple(
    f"ix_channels_{col}" for col, _where in CHANNEL_PARTIAL_INDEX_SPECS
)


def legacy_index_drop_sql(conn: "Connection") -> list[str]:
    """``DROP INDEX`` statements for ``channels`` indexes still in their OLD shape.

    Reads ``sqlite_master`` once (``name``, ``sql`` for every index on
    ``channels``) and returns a drop ONLY for an index that currently exists
    in the shape the drop exists to remove:

    * a name in :data:`CHANNEL_DEAD_INDEX_NAMES`, present at all — these have
      no replacement, so existing is the only test; or
    * a partial-conversion name (``ix_channels_<col>`` for a column in
      :data:`CHANNEL_PARTIAL_INDEX_SPECS`) whose stored ``sql`` carries no
      ``WHERE`` — the pre-STORAGE-1a FULL shape.

    An index already in its PARTIAL shape (its ``sql`` has a ``WHERE``) is
    left alone, and a name that does not exist at all is left alone too — so
    a fresh install, where ``create_all()`` already built the partial shape,
    returns an empty list. See "The naming trap" above for why the dropped
    and rebuilt names are identical, and why that makes the shape check (not
    a name check) the thing that stops this from firing on every launch.
    """
    existing = {
        row[0]: (row[1] or "")
        for row in conn.execute(text(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'channels'"
        ))
    }
    drops = [
        f"DROP INDEX IF EXISTS {name}"
        for name in CHANNEL_DEAD_INDEX_NAMES
        if name in existing
    ]
    drops += [
        f"DROP INDEX IF EXISTS ix_channels_{col}"
        for col, _where in CHANNEL_PARTIAL_INDEX_SPECS
        if f"ix_channels_{col}" in existing
        and "WHERE" not in existing[f"ix_channels_{col}"].upper()
    ]
    return drops
