"""DERIVE-1/DB-7: diff an incoming batch against its stored rows, one query.

The catalog upsert (``provider_loader.py``'s ``_store_channels``/``_flush_batch``)
deliberately preserves name-derived ``detected_*`` fields across a refresh (see
``_CATALOG_UPDATE_COLS``) — correct for a row whose ``name``/``category``/
``raw_data`` didn't change, but it leaves a row that DID change carrying its
OLD derivation until some later sweep happens to re-touch it. Two functions
close that gap:

* :func:`diff_batch_for_upsert` — ONE query per ``_store_channels`` batch
  (scoped to that batch's ids, never a full-table scan) answering TWO
  different questions from the same fetched rows:

  * ``changed_ids`` — existing rows whose ``name``/``category``/``raw_data``
    differ from the incoming row (DERIVE-1's original scope — those three
    columns are what feed ``detected_*`` derivation, so this stays scoped to
    exactly them regardless of what else the caller asks to compare).
  * ``unchanged_ids`` (DB-7) — existing rows where EVERY *catalog_cols*
    column already matches the incoming row, so the full multi-column upsert
    (including the rename/metadata-invalidation ``CASE`` logic in
    ``_flush_batch``, which this identity check already proves is a no-op
    for them) would write nothing new. ``detected_tmdb_id`` is compared
    COALESCE-aware: ``_flush_batch`` never overwrites a stored id with an
    incoming NULL, so an incoming NULL against a populated stored id is not
    a difference here either.

  DB-7's premise: a change gate only pays if it stops doing the EXPENSIVE
  write for unchanged rows while something else keeps the cheap
  presence-stamp (``last_seen_at``) moving — the pruner
  (``channel_pruning.py``) still diffs on it, and this module does not touch
  that file. See ``_flush_batch`` for the two write paths this feeds.

* :func:`force_recompute_for_changed_ids` — runs ``update_detected_prefixes``'s
  ``channel_ids`` filter over exactly ``changed_ids``, right after the
  refresh's existing whole-provider pass, and logs the count either way.

A brand-new row (no existing match) is in neither set — new rows always take
the full insert path, and the existing missing-field recompute already
covers their ``detected_*`` derivation.
"""

from __future__ import annotations

from typing import Any, Collection

from loguru import logger

from metatv.core.database import ChannelDB

#: Column whose ON-CONFLICT write is a COALESCE, not a plain overwrite (see
#: ``_flush_batch``) — an incoming NULL never differs from a populated stored
#: value for gating purposes, because the upsert would keep the stored value
#: either way.
_COALESCED_COL = "detected_tmdb_id"


def diff_batch_for_upsert(
    session, batch: list[dict], catalog_cols: Collection[str],
) -> tuple[set[str], set[str]]:
    """Return ``(changed_ids, unchanged_ids)`` for one ``_store_channels`` batch.

    Args:
        session: An active database session (queried before the batch's
            upsert flushes, so this reads the PRE-refresh stored values).
        batch: This batch's incoming row dicts, each carrying at least ``id``
            plus every key named in *catalog_cols*.
        catalog_cols: The full set of columns the caller's upsert would SET
            on conflict (``provider_loader._CATALOG_UPDATE_COLS``) — what
            "unchanged" is measured against. Must include ``name`` and
            ``category`` (``raw_data`` too — DERIVE-1's fixed three).

    Returns:
        ``changed_ids`` — ids whose stored ``name``/``category``/``raw_data``
        differ from the incoming row. ``unchanged_ids`` — ids whose stored
        row already matches the incoming row across every column in
        *catalog_cols*. The two sets are disjoint; a brand-new id (no stored
        row) is in neither.
    """
    catalog_cols = tuple(catalog_cols)
    ids = [row["id"] for row in batch]
    col_attrs = [getattr(ChannelDB, c) for c in catalog_cols]
    existing = {
        r[0]: dict(zip(catalog_cols, r[1:]))
        for r in session.query(ChannelDB.id, *col_attrs).filter(ChannelDB.id.in_(ids)).all()
    }

    changed: set[str] = set()
    unchanged: set[str] = set()
    for row in batch:
        prior = existing.get(row["id"])
        if prior is None:
            continue  # brand-new row — always a full insert, never "changed" or "unchanged"

        if (prior["name"], prior["category"], prior["raw_data"]) != (
            row["name"], row["category"], row["raw_data"]
        ):
            changed.add(row["id"])

        identical = True
        for col in catalog_cols:
            incoming = row.get(col)
            if col == _COALESCED_COL and incoming is None:
                continue  # COALESCE keeps the stored value; never a difference
            if incoming != prior[col]:
                identical = False
                break
        if identical:
            unchanged.add(row["id"])

    return changed, unchanged


def touch_last_seen_at(session, ids: Collection[str], seen_at) -> None:
    """DB-7: bulk-stamp presence on rows the gate skipped, no other column.

    The single-column counterpart to the full upsert's ``last_seen_at``
    stamping (``_flush_batch``) — same guarantee (the pruner diffs on this
    column so it has to move on every row, gated or not), none of the cost
    (no ``raw_data`` re-serialization, no CASE evaluation). A no-op on an
    empty *ids*.
    """
    if not ids:
        return
    session.query(ChannelDB).filter(ChannelDB.id.in_(ids)).update(
        {"last_seen_at": seen_at}, synchronize_session=False,
    )


def force_recompute_for_changed_ids(
    channels_repo: Any,
    provider_id: str,
    separators: list[str] | None,
    changed_ids: Collection[str],
) -> None:
    """Force ``detected_*`` recomputation for exactly *changed_ids*; always logs the count.

    Args:
        channels_repo: A ``ChannelRepository`` (or duck-typed equivalent)
            exposing ``update_detected_prefixes(..., channel_ids=...)``.
        provider_id: The provider this refresh belongs to.
        separators: Prefix separators, forwarded unchanged.
        changed_ids: Ids to force-recompute. No query runs when empty.
    """
    if changed_ids:
        channels_repo.update_detected_prefixes(
            provider_id=provider_id, separators=separators, channel_ids=changed_ids,
        )
    logger.info(
        "detected_* recomputed for {:,} rows whose name/category/raw_data changed",
        len(changed_ids),
    )
