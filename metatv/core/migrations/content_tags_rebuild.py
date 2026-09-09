"""DB-9: rebuild ``content_tags`` on an integer ``channel_key`` FK.

**Not a MigrationTask.** Every other module in this package registers with
``MigrationManager`` and runs off-thread, gated on ``needs_run()``. This one is
called directly and synchronously from ``Database._migrate()`` (see that
method) and blocks the first query of the process — required because the
moment ``ContentTagDB.channel_key`` exists on the ORM model, every tag query
fails with "no such column" until the table actually has it, so this cannot be
deferred to a background task the way every other migration in this package
is.

``content_tags.channel_id`` (a 43-byte string, ``ChannelDB.id``) is replaced
by ``channel_key`` (a small int, ``ChannelDB.channel_key``, which has zero
readers outside this join table).  ``ALTER TABLE`` cannot change a column's
identity, only add one, so this REBUILDS the table: CREATE the new shape,
copy every row through a JOIN to ``channels``, DROP the old table, RENAME the
new one into place. Measured on the owner's real 3.14M-row content_tags:
13.6s total, ``PRAGMA integrity_check`` ``ok``, tag sets md5-identical
before/after, frees ~475 MB (content_tags + its two indexes shrink from
~775 MB to ~279 MB, after adding the new ``channels.channel_key`` column and
index).

**Guarded on the actual on-disk shape** (``PRAGMA table_info``), never a
``PRAGMA user_version``/config counter — the db file (``~/.local/share/metatv``)
and the config file (``~/.config/metatv``) live in different directories, so a
version counter living in either one could desync from what the OTHER file
actually contains (e.g. a restored db without a matching restored config).
Re-probing the real schema on every launch is cheap and can never be wrong
about it.

**Atomic, not resumable — deliberately.** SQLite DDL is transactional, so
CREATE -> INSERT...SELECT -> DROP -> RENAME -> CREATE INDEX either all commit
or none do; a crash mid-rebuild leaves the original content_tags completely
untouched and the guard simply fires again next launch. There is no partial
state to resume from, so atomic-and-blocking is simpler than a resumable
background form — and a nullable-column / dual-read compatibility layer would
fork ~50 query sites into 100 and buy nothing until the rebuild happens anyway
(rejected in the DB-9 design pass).

Also installs ``channels_assign_channel_key`` — an ``AFTER INSERT`` trigger
that stamps every newly-inserted channel with a ``channel_key`` — so no insert
call site (present or future) can silently forget to assign one and lose that
channel's tags. Measured at +284ms on a 240k-row catalog refresh.
"""

from __future__ import annotations

import os
import shutil
import time

from loguru import logger
from sqlalchemy import text

#: Minimum free disk space (bytes) required to attempt the rebuild — it peaks
#: around 4.1-4.2 GB of transient WAL for a database the owner's size
#: (measured 954 MB WAL for a 943 MB DB). Refuse rather than risk running the
#: disk out from under a live transaction; the guard fires again next launch
#: since nothing was written.
_MIN_FREE_BYTES = 3 * 1024 ** 3


def _ensure_channel_key_trigger(conn) -> None:
    """Create the AFTER INSERT trigger that assigns ``channels.channel_key``.

    Idempotent (``IF NOT EXISTS``) so it is safe to call on every startup, both
    right after the one-time rebuild and on every subsequent launch that skips
    the rebuild because it already happened. Without this, a channel inserted
    by any path — including a future importer nobody remembered to update —
    would silently never get a ``channel_key``, and its tags would never
    write (Risk #1, DB-9 design pass): capturing this as a trigger removes the
    "remember to call it" seam entirely, rather than requiring every insert
    call site to opt in.

    Uses ``MAX(channel_key)+1``, never ``NEW.rowid`` — a future "Compact
    database" VACUUM may renumber ChannelDB rowids (it has no explicit INTEGER
    PRIMARY KEY), and a key that tracked rowid could then collide with one
    already stored in content_tags.

    Executes via ``exec_driver_sql`` and does NOT commit — this is called both
    from an ordinary transactional connection (caller commits) and from
    inside the AUTOCOMMIT rebuild transaction (the surrounding explicit
    ``COMMIT`` covers it); committing here would be a no-op in the first case
    and would prematurely end the caller's transaction in the second.
    """
    conn.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS channels_assign_channel_key "
        "AFTER INSERT ON channels WHEN NEW.channel_key IS NULL "
        "BEGIN "
        "UPDATE channels SET channel_key = "
        "(SELECT IFNULL(MAX(channel_key), 0) + 1 FROM channels) "
        "WHERE rowid = NEW.rowid; "
        "END"
    )


def rebuild_content_tags_int_key(engine) -> None:
    """Entry point called from ``Database._migrate()``. Never raises.

    An unexpected failure here (beyond the disk-space / rebuild-transaction
    cases already handled explicitly below) is logged rather than allowed to
    crash startup, matching every other one-time migration in ``database.py``.
    A tag query will then fail loudly with "no such column" until a later
    launch's retry succeeds — worse than crashing cleanly, but the app still
    opens.
    """
    try:
        _rebuild_impl(engine)
    except Exception:
        logger.exception("DB-9: content_tags rebuild failed unexpectedly (startup unblocked)")


def _rebuild_impl(engine) -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(
            text("PRAGMA table_info(content_tags)")
        ).fetchall()}

        if "channel_key" in cols:
            # Already rebuilt (or this is a fresh DB that create_all() built
            # directly in the final shape) — just make sure the trigger
            # exists, in case this code shipped after the rebuild already ran.
            _ensure_channel_key_trigger(conn)
            conn.commit()
            return

        if "channel_id" not in cols:
            # Fresh database: create_all() already built content_tags in the
            # final int-keyed shape from the ORM model. Nothing to migrate.
            _ensure_channel_key_trigger(conn)
            conn.commit()
            return

        # ── An old-shaped database. Refuse if disk is too tight to risk it —
        # the transaction's WAL peaks well above the final on-disk size.
        db_path = engine.url.database
        if db_path and db_path not in (":memory:", ""):
            try:
                free = shutil.disk_usage(os.path.dirname(db_path) or ".").free
            except OSError:
                free = None
            if free is not None and free < _MIN_FREE_BYTES:
                logger.error(
                    "DB-9: content_tags rebuild needs ~{:.0f} GB free disk "
                    "space (only {:.1f} GB available) — skipping this "
                    "launch, will retry next start.",
                    _MIN_FREE_BYTES / 1024 ** 3,
                    free / 1024 ** 3,
                )
                return

        started = time.perf_counter()
        row_count = conn.execute(text("SELECT COUNT(*) FROM content_tags")).scalar() or 0
        logger.info(
            "DB-9: rebuilding content_tags ({:,} rows) on an integer channel "
            "key — one-time, may take up to a minute on a large library.",
            row_count,
        )

        # ── Seed + index channels.channel_key. Idempotent on its own
        # (WHERE channel_key IS NULL / IF NOT EXISTS), so an interruption
        # here simply resumes on the next launch.
        conn.execute(text(
            "UPDATE channels SET channel_key = rowid WHERE channel_key IS NULL"
        ))
        conn.commit()
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_channels_channel_key "
            "ON channels (channel_key)"
        ))
        conn.commit()

        # Same policy OrphanSweepTask already applies (orphan_sweep.py) —
        # never a NEW deletion policy, just visible when this rebuild is the
        # one to apply it.
        orphaned = conn.execute(text(
            "SELECT COUNT(*) FROM content_tags ct "
            "LEFT JOIN channels c ON c.id = ct.channel_id "
            "WHERE c.id IS NULL"
        )).scalar() or 0
        if orphaned:
            logger.warning(
                "DB-9: {} content_tags row(s) reference a channel that no "
                "longer exists — dropped during the rebuild (same policy "
                "as OrphanSweepTask).",
                orphaned,
            )

        unexpected_sources = conn.execute(text(
            "SELECT DISTINCT source FROM content_tags "
            "WHERE source NOT IN ('generated', 'user')"
        )).fetchall()
        if unexpected_sources:
            logger.warning(
                "DB-9: content_tags has source value(s) other than "
                "'generated'/'user': {} — mapped to 'generated' (0) during "
                "the rebuild.",
                [r[0] for r in unexpected_sources],
            )

    # ── The atomic rebuild itself. AUTOCOMMIT isolation so the explicit BEGIN
    # IMMEDIATE / COMMIT below govern the transaction directly — pysqlite's
    # own implicit-transaction handling around DDL statements (it silently
    # COMMITs a pending transaction before some DDL forms) would otherwise
    # fight an ordinary SQLAlchemy-managed transaction here.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        try:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            conn.exec_driver_sql(
                "CREATE TABLE content_tags_new ("
                "channel_key INTEGER NOT NULL REFERENCES channels(channel_key), "
                "tag_id INTEGER NOT NULL REFERENCES tags(id), "
                "source INTEGER NOT NULL DEFAULT 0, "
                "feeders TEXT, "
                "PRIMARY KEY (channel_key, tag_id, source)"
                ") WITHOUT ROWID"
            )
            conn.exec_driver_sql(
                "INSERT INTO content_tags_new (channel_key, tag_id, source, feeders) "
                "SELECT c.channel_key, ct.tag_id, "
                "CASE ct.source WHEN 'user' THEN 1 ELSE 0 END, "
                "ct.feeders "
                "FROM content_tags ct JOIN channels c ON c.id = ct.channel_id"
            )
            conn.exec_driver_sql("DROP TABLE content_tags")
            conn.exec_driver_sql("ALTER TABLE content_tags_new RENAME TO content_tags")
            conn.exec_driver_sql(
                "CREATE INDEX ix_content_tags_tag_channel "
                "ON content_tags (tag_id, channel_key)"
            )
            _ensure_channel_key_trigger(conn)
            conn.exec_driver_sql("COMMIT")
        except Exception:
            try:
                conn.exec_driver_sql("ROLLBACK")
            except Exception:
                pass  # silent: nothing to roll back (e.g. BEGIN itself failed)
            logger.exception(
                "DB-9: content_tags rebuild failed — original table "
                "untouched, will retry next launch."
            )
            return

    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    elapsed = time.perf_counter() - started
    logger.info("DB-9: content_tags rebuild complete in {:.1f}s", elapsed)
