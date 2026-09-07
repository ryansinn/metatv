"""DERIVE-1: detect rows whose catalog payload changed, force their re-derivation.

The catalog upsert (``provider_loader.py``'s ``_store_channels``/``_flush_batch``)
deliberately preserves name-derived ``detected_*`` fields across a refresh (see
``_CATALOG_UPDATE_COLS``) — correct for a row whose ``name``/``category``/
``raw_data`` didn't change, but it leaves a row that DID change carrying its
OLD derivation until some later sweep happens to re-touch it. Two functions
close that gap:

* :func:`detect_changed_channel_ids` — the SELECT that finds which ids in one
  ``_store_channels`` batch actually changed (scoped to that batch's ids only,
  never a full-table scan).
* :func:`force_recompute_for_changed_ids` — runs ``update_detected_prefixes``'s
  ``channel_ids`` filter over exactly that set, right after the refresh's
  existing whole-provider pass, and logs the count either way.

A brand-new row (no existing match) is not a "change" here — the existing
missing-field recompute already covers it.
"""

from __future__ import annotations

from typing import Any, Collection

from loguru import logger

from metatv.core.database import ChannelDB


def detect_changed_channel_ids(session, batch: list[dict]) -> set[str]:
    """Return ids in *batch* whose stored name/category/raw_data differ.

    Args:
        session: An active database session (queried before the batch's
            upsert flushes, so this reads the PRE-refresh stored values).
        batch: This batch's incoming row dicts, each carrying at least
            ``id``, ``name``, ``category`` and ``raw_data``.

    Returns:
        The subset of ``batch`` ids whose existing row differs from the
        incoming one. Empty when every id is new or unchanged.
    """
    ids = [row["id"] for row in batch]
    existing = {
        row.id: (row.name, row.category, row.raw_data)
        for row in session.query(
            ChannelDB.id, ChannelDB.name, ChannelDB.category, ChannelDB.raw_data
        ).filter(ChannelDB.id.in_(ids)).all()
    }
    changed: set[str] = set()
    for row in batch:
        prior = existing.get(row["id"])
        if prior is not None and prior != (row["name"], row["category"], row["raw_data"]):
            changed.add(row["id"])
    return changed


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
