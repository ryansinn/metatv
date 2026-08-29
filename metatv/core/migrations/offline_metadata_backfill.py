"""Migration task: build a metadata baseline from data already on disk.

Measured on the owner's library:

    movie/series titles                    417,003
      with a metadata row                    2,100  (0.50%)
    series carrying a plot in raw_data      72,619

Metadata is fetched lazily, per title you open, so after months the table
covers half a percent of the catalogue — and anything that queries it in BULK
sees an almost-empty table. That is the same defect the channel-list posters
had, one column over: the list's plot line reads ``MetadataDB.plot`` and is
blank for 99.5% of rows.

Meanwhile the provider already shipped the answer. A series record carries
plot, cast, director, genre, rating, release date, backdrop and a TMDb id, and
``ProviderMetadataProvider`` has always been able to read it — it is just wired
to run on demand. This runs it over the whole catalogue, once, with no network.

WHY ``fetched_at`` STAYS NULL
-----------------------------
``ChannelRepository._metadata_enrichment_filter`` treats a row as a candidate
while ``metadata_id IS NULL OR fetched_at IS NULL OR fetched_at < stale_before``.
Stamping ``fetched_at`` here would mark 400,000 titles as fetched and
PERMANENTLY stop the network pass ever adding what only it can: director for
the 66% of series without one, runtime, content rating, character names, actor
photos.

So the row is written unstamped. The list and the details pane get a baseline
immediately; the enrichment queue still sees every title as owed a visit and
upgrades it in place. ``MetadataManager._save_metadata_cache`` fills only empty
fields, so nothing written here is overwritten by a later fetch that knows less.
That is also why this does not reuse that method — it stamps ``fetched_at``,
which is exactly the thing that must not happen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger
from sqlalchemy import bindparam, text

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

_BATCH = 1_000

# Value-aware, not key-aware: raw_data very often carries a key with an empty
# value, and counting those as pending leaves needs_run permanently True (the
# lesson from the poster backfill, which aborted after one batch because of it).
# A row is worth visiting when the blob holds at least one field we would store.
_HAS_SOMETHING = " OR ".join(
    f"TRIM(COALESCE(json_extract(raw_data, '$.{k}'), '')) != ''"
    for k in ("plot", "cast", "genre", "director", "rating", "releaseDate",
              "release_date", "cover", "stream_icon", "backdrop_path")
)

# ``run`` writes nothing for a result with no title, so a row with no usable
# title is a candidate the task can never satisfy — and because needs_run reads
# the data rather than a stamp, it re-arms on EVERY launch forever. One row in
# the owner's 417k-title library did exactly that (name '', rating '0', which
# _HAS_SOMETHING accepts), announcing "migration in progress" at every start.
#
# The predicate below is not a patch for that row: it is the SQL half of the
# same question ``run`` asks in Python. metadata_from_raw resolves the title as
# ``info.name`` when it differs from the channel name, else ``detected_title or
# name`` — so a title exists exactly when one of those three is non-blank.
# test_migration_predicate_matches_acceptance.py pins the two halves together.
_HAS_TITLE = (
    "TRIM(COALESCE(json_extract(raw_data, '$.info.name'), '')) != '' "
    "OR TRIM(COALESCE(detected_title, '')) != '' "
    "OR TRIM(COALESCE(name, '')) != ''"
)

_CANDIDATES = (
    "SELECT id FROM channels "
    "WHERE metadata_id IS NULL AND is_hidden = 0 "
    "AND media_type IN ('movie', 'series') "
    "AND raw_data IS NOT NULL AND json_valid(raw_data) "
    f"AND ({_HAS_SOMETHING}) "
    f"AND ({_HAS_TITLE})"
)
_PAGE = _CANDIDATES + " AND id > :after ORDER BY id LIMIT :n"


class OfflineMetadataBackfillTask:
    """Give every title a metadata row from its own stored provider record."""

    id: str = "offline_metadata_backfill"
    label: str = "Reading title details already on disk"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def _pending(self) -> int:
        with self._db.engine.connect() as conn:
            return conn.execute(text(f"SELECT count(*) FROM ({_CANDIDATES})")).scalar() or 0

    def needs_run(self, config: "Config") -> bool:
        """Return True while a title has usable details and no metadata row.

        Args:
            config: Unused; the data is the source of truth.

        Returns:
            True when there is work to do.
        """
        try:
            return self._pending() > 0
        except Exception:
            logger.exception("OfflineMetadataBackfillTask: could not count candidates; skipping")
            return False

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Parse each candidate's ``raw_data`` and store the result, unstamped.

        Runs on a **worker thread** (called by ``MigrationManager``).

        Args:
            progress_cb: ``(done, total)`` after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for the manager's keyword call.
        """
        from metatv.core.database import ChannelDB, MetadataDB
        from metatv.metadata_providers.provider_metadata import metadata_from_raw

        total = self._pending()
        if not total:
            return
        logger.info(
            "OfflineMetadataBackfillTask: {:,} titles have details on disk and no "
            "metadata row", total,
        )

        done = written = 0
        after = ""
        progress_cb(0, total)
        while not is_cancelled():
            with self._db.session_scope() as session:
                ids = [
                    r[0] for r in
                    session.execute(text(_PAGE), {"after": after, "n": _BATCH}).all()
                ]
                if not ids:
                    break
                channels = (
                    session.query(ChannelDB).filter(ChannelDB.id.in_(ids)).all()
                )
                unstamp: list[str] = []
                for channel in channels:
                    result = metadata_from_raw(
                        channel.raw_data,
                        name=channel.name,
                        detected_title=channel.detected_title,
                        logo_url=channel.logo_url,
                    )
                    if result is None or not result.title:
                        continue
                    meta_id = f"meta_{channel.id}"
                    # A row can already exist ORPHANED — 13 of them in the
                    # owner's library, from links cleared without deleting the
                    # row — and inserting over one is a UNIQUE violation that
                    # takes the whole batch down.
                    existing = session.get(MetadataDB, meta_id)
                    meta = existing or MetadataDB(id=meta_id)

                    # FILL ONLY EMPTY on an existing row. 13 rows in the owner's
                    # library are orphaned — real, enriched, but with no channel
                    # pointing at them — and blindly assigning would replace a
                    # fetched plot or poster with whatever raw_data happens to
                    # hold. Same rule MetadataManager._save_metadata_cache uses:
                    # a source that knows less does not get to erase what is
                    # already known.
                    def _fill(field: str, value) -> None:
                        if value in (None, "", [], {}):
                            return
                        if existing is not None and getattr(meta, field, None):
                            return
                        setattr(meta, field, value)

                    _fill("title", result.title)
                    _fill("plot", result.plot)
                    _fill("genres", result.genres)
                    _fill("cast", result.cast)
                    _fill("director", result.director)
                    _fill("rating", result.rating)
                    _fill("release_date", result.release_date)
                    _fill("poster_url", result.poster_url)
                    _fill("backdrop_url", result.backdrop_url)
                    _fill("trailer_url", result.trailer_url)
                    _fill("media_type", channel.media_type)
                    if existing is None:
                        meta.source = "provider-raw"
                    session.add(meta)
                    channel.metadata_id = meta.id
                    # Only a row THIS task created may be unstamped. An adopted
                    # row was genuinely fetched, and clearing its fetched_at
                    # would send it back through the network queue for nothing.
                    if existing is None:
                        unstamp.append(meta.id)
                    written += 1

                # fetched_at CANNOT be left unset: the column carries
                # ``default=datetime.now`` (database.py:302), so omitting it
                # stamps it — which would mark every one of these titles as
                # fetched and permanently stop the network pass upgrading them.
                # Cleared explicitly, after the flush, which is the only point
                # the default has already been applied.
                if unstamp:
                    session.flush()
                    session.execute(
                        text("UPDATE metadata SET fetched_at = NULL WHERE id IN :ids")
                        .bindparams(bindparam("ids", expanding=True)),
                        {"ids": unstamp},
                    )
                # Advance past everything EXAMINED, not everything written: a
                # blob that parses to nothing stays a candidate for the SQL
                # filter, so a cursor-less page would return it forever.
                after = ids[-1]
                done += len(ids)
            progress_cb(min(done, total), total)

        logger.info(
            "OfflineMetadataBackfillTask: complete — {:,} rows written from {:,} examined",
            written, done,
        )

    def on_completed(self, config: "Config") -> None:
        """No bookkeeping — ``needs_run`` reads the data itself.

        Args:
            config: Unused.
        """
        return
