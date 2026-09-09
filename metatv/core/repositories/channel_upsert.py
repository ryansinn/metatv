"""The catalog batch upsert itself — split out of ``provider_loader.py``.

``ProviderLoadThread._flush_batch`` was a ``@staticmethod`` that never
touched ``self`` — organizationally grouped with the thread class but
already a pure function of its arguments. DB-7's change gate (splitting the
batch into a full-upsert path and a presence-only touch path) grew it enough
to push ``provider_loader.py`` — pinned at its code-health baseline — over
the ratchet; per CLAUDE.md, "a pinned file at its ceiling means extract to a
cohesive new module, not rebaseline." This IS that cohesive unit: the whole
upsert-composition mechanism (INSERT..ON CONFLICT DO UPDATE, the stream-ID
reuse CASE logic, the DB-7 gate split) with no dependency on
``ProviderLoadThread`` state. ``_flush_batch`` stays on the class as a thin
delegating staticmethod so the existing direct-call test surface
(``ProviderLoadThread._flush_batch(...)`` in
``test_stale_metadata_stream_id_reuse.py``/``test_tmdb_enrichment.py``)
doesn't churn.
"""

from __future__ import annotations

from sqlalchemy import case, func, literal
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert

from metatv.core.database import ChannelDB
from metatv.core.migrations.sports_reclassify import DERIVED_FIELDS
from metatv.core.repositories.channel_change_detection import touch_last_seen_at


def flush_channel_batch(
    session, batch: list[dict], catalog_update_cols: tuple[str, ...], *,
    seen_at=None, unchanged_ids: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Execute one bulk upsert for *batch* and commit the transaction.

    Uses SQLite's ``INSERT INTO ... ON CONFLICT(id) DO UPDATE SET ...`` to
    insert new rows and update only catalog columns on conflict.
    Derived/user columns (``is_favorite``, ``play_count``, ``detected_*``,
    ``user_category``, etc.) are NOT in the SET clause and are preserved.

    **Stream-ID reuse guard:** IPTV providers occasionally recycle stream IDs
    for completely different content. When the incoming ``name`` differs from
    the stored row's ``name``, the linked ``MetadataDB`` row belongs to the
    previous occupant and must be invalidated so it re-derives from the new
    ``raw_data``. This is expressed as a CASE in the DO UPDATE clause so it
    happens atomically inside the same bulk upsert — no extra query needed.

    **DB-7 change gate:** *unchanged_ids* (see
    ``channel_change_detection.diff_batch_for_upsert``) are existing rows
    whose full catalog payload already matches what's stored — the
    multi-column upsert below (and every CASE inside it) would write back
    exactly what's already there. Those ids skip it entirely and only get
    ``last_seen_at`` touched (``touch_last_seen_at``) — cheap because it
    never re-serializes ``raw_data`` or evaluates a single CASE. Callers that
    never pass *unchanged_ids* get today's pre-DB-7 behaviour: every row in
    ``batch`` takes the full upsert path.

    Args:
        session: An active database session.
        batch: This batch's incoming row dicts, each carrying at least ``id``
            plus every key in *catalog_update_cols*.
        catalog_update_cols: The catalog columns to SET on conflict
            (``provider_loader._CATALOG_UPDATE_COLS``).
        seen_at: Presence-stamp instant for this refresh pass, or ``None`` to
            skip presence stamping entirely (direct-call tests only).
        unchanged_ids: Ids within *batch* to gate — see above.
    """
    to_touch = [row["id"] for row in batch if row["id"] in unchanged_ids]
    to_upsert = [row for row in batch if row["id"] not in unchanged_ids]

    if seen_at is not None:
        touch_last_seen_at(session, to_touch, seen_at)

    if to_upsert:
        # Stamp presence on every row in this batch, inserted or updated.
        #
        # Deliberately NOT part of _CATALOG_COLS: that tuple is checked against
        # the Channel model by test_catalog_columns_cover_the_channel, and this
        # is loader bookkeeping rather than anything the source sends.
        #
        # It has to be set on the DO UPDATE branch too, which is the whole point
        # — a channel the source still lists but has not edited takes that branch
        # and changes nothing else. Stamping only on insert would mark every
        # unchanged channel as vanished on the very next refresh.
        if seen_at is not None:
            to_upsert = [dict(row, last_seen_at=seen_at) for row in to_upsert]

        stmt = _sqlite_insert(ChannelDB).values(to_upsert)
        update_set = {col: getattr(stmt.excluded, col) for col in catalog_update_cols}
        if seen_at is not None:
            update_set["last_seen_at"] = stmt.excluded.last_seen_at
        # Preserve provider-native / propagated tmdb enrichment across refreshes.
        # detected_tmdb_id is a catalog column, but the enrichment layer writes ids the
        # provider LIST row still omits (from the detail endpoint or a title sibling).
        # A plain overwrite would wipe those back to NULL every refresh, undoing the
        # collapse; COALESCE keeps the stored id whenever the incoming payload carries
        # none, and only overwrites when the refresh actually ships a real id.
        update_set["detected_tmdb_id"] = func.coalesce(
            stmt.excluded.detected_tmdb_id, ChannelDB.detected_tmdb_id
        )
        # Clear stale metadata when the channel name changes (stream-ID reuse).
        # new rows (INSERT path) have metadata_id=NULL by default — this only fires
        # for the DO UPDATE branch (existing rows), and only when the name actually changed.
        update_set["metadata_id"] = case(
            (stmt.excluded.name != ChannelDB.name, literal(None)),
            else_=ChannelDB.metadata_id,
        )
        # ...and NAME-DERIVED fields, for exactly the same reason. Also clear
        # sports/event classification columns so _categorize_special_content
        # (which runs after _store_channels and processes special_view IS NULL rows)
        # reclassifies a renamed slot from its new name in the same pass.
        # detected_tmdb_id is deliberately NOT cleared: the enrichment layer owns
        # it and COALESCEs it above, so clearing here would undo that.
        for _derived in ("detected_title", "detected_prefix", "detected_quality",
                         "detected_region", "detected_year", "content_key") + DERIVED_FIELDS:
            update_set[_derived] = case(
                (stmt.excluded.name != ChannelDB.name, literal(None)),
                else_=getattr(ChannelDB, _derived),
            )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_=update_set,
        )
        session.execute(stmt)

    session.commit()
