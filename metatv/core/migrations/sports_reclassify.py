"""Migration task: re-run the sports/PPV/event classifier over existing rows.

#587 fixed ``parse_sports_channel`` to match league keywords as whole words —
``co-NFL-ict`` was an NFL channel, ``GREE-NBA-Y`` an NBA one, ``T-F1`` Formula 1.
It fixed nothing the owner can see, because **the classifier only ever runs on a
row that has never been classified.** ``ProviderLoader`` filters
``special_view IS NULL``, deliberately: re-deriving 300k rows on every refresh is
not free, and the classification does not change between refreshes.

It changes when the CLASSIFIER changes, and nothing was watching for that. So a
correctness fix landed in code and the stored data stayed exactly as wrong as it
was — 729 channels still filed under Premier League, 467 under the NBA, 446
under the NFL, each on a keyword buried inside an unrelated word. Wiring the
Sports view over that data would have shipped a view where the NBA lists Green
Bay local stations.

Measured over all 785,163 rows with the current classifier:

    rows whose classification changes ....... 9,825
      special_view ......................... 7,438   (35,181 -> 28,018 sports,
                                                       408 -> 510 ppv)
      sport_type ........................... 8,195
      league_name .......................... 2,874
      team_name ............................ 2,845

    biggest league corrections
      729  Premier League -> (none)      275  (none) -> Formula 1
      467  NBA            -> (none)      113  Europa League -> (none)
      446  NFL            -> (none)      102  NHL           -> (none)

Where the 7,163 rows leaving the sports view go: 6,561 were never sports at all,
142 move to PPV (they are dated events), and 132 are TREX ``#####`` section
headers that a later guard already excludes but that nothing had re-evaluated.

The gate had the same bug, and it does not take the same fix
------------------------------------------------------------
``detect_sports_channel`` — the question of whether a channel is in the sports
view AT ALL — was still on plain substrings, so "4K - Conflict (2024)" lost its
bogus NFL label and stayed in the sports view regardless, labelled
``sport_type`` "unknown".

Making it whole-token to match was measured before it shipped and was **worse
than the bug**: ``sport`` under a whole-token rule matches "SPORT TV" and misses
"SPORTSNET 360", "SPECTRUM SPORTS 1" and "CBS SPORTS NETWORK" — **11,451 real
sports channels out of the view**, against the ~2,000 false ones the change was
meant to remove.

The rule is per-KEYWORD, not per-call-site, and it is now written down as two
named sets. ``SPORTS_GATE_STEMS`` match at the start of a word, because their
whole value is that they compound (``sport`` → SPORTSNET, ``moto`` → MOTOGP,
``fight`` → FIGHTING, and never "firefighter", which is what the left-edge guard
is for). ``SPORTS_GATE_TOKENS`` match whole, because they hide inside unrelated
words (``nba`` in GREENBAY, ``f1`` in TF1, ``bein`` in "being").

Reset, then recompute
---------------------
``update_channel_special_content`` returns early and writes NOTHING when the
channel no longer matches anything, so recomputing in place would leave every
false positive exactly where it is — the 7,163 rows that stop being sports are
the whole point. ``DERIVED_FIELDS`` — now eight, since SPORT-4 added the
fixture-opponent columns — are cleared first and then recomputed. All are
machine-derived; no user state is touched (CLAUDE.md: migrations rewrite
only generated data).

CLASSIFIER_VERSION
------------------
``CURRENT_VERSION`` is the executable statement of "the classifier changed".
**A future change to** ``special_content.py`` **must bump it**, or that fix will
reach new rows only and the stored data will drift again in the same way. There
is no cheaper signal: the alternative is a per-row stamp of the classifier
version, which is a column and a write on 785k rows to save a migration that
runs once.

Reading and writing are separate transactions
---------------------------------------------
The v3 run over the owner's 785,489 rows died at its own flush with
``sqlite3.OperationalError: database is locked``, having waited out the whole
30 s ``busy_timeout``, and four other writers failed the same way inside that
two-minute window — the watch-list DELETE on the UI thread,
``persist_url_stats``, ``apply_metadata_harvest`` and ``record_impressions``.
SQLite has ONE writer, and this pass was the loudest one on the database.

The shape that caused it: **one ``session_scope()`` per page, wrapped around a
full ORM flush of up to 2,000 modified rows.** Measured with a listener timing
each transaction from its first DML to the COMMIT returning (60,000 rows,
154 MB, otherwise idle):

    ==========================================  ========  =======
                                                  before    after
    ==========================================  ========  =======
    statements inside the longest transaction       13         1
    longest transaction, first DML -> COMMIT      18.8 ms   1.1 ms
    total time any write lock was held             0.42s    0.02s
    ==========================================  ========  =======

Thirteen statements for twenty-four rows, because a flush emits one UPDATE per
distinct *changed-column combination* and every one of them is a round trip
taken while holding the lock. A bulk update of the same rows is a single
``executemany``. Nothing about that is specific to a busy machine — it is 21x
more lock time for the identical result, always.

The other half is the page query. It loaded whole ORM rows, ``raw_data`` blob
included, to read three strings off each one.

So the pass now does what ``epg.delete_programmes_chunked`` does for the other
big writer on this database (#601): bounded rows per transaction, committed per
chunk. Concretely — a read-only scope loads a page of the **ten columns the
classifier actually touches** (``CLASSIFIER_INPUTS`` + ``DERIVED_FIELDS``, not
the ~45-column row), the scope closes, the page is classified against transient
throwaway instances that are never attached to a session, and only the rows
that CHANGED are written, ``WRITE_CHUNK`` at a time, each its own short
transaction. Rows that do not change — 98.75% of the catalog, 9,825 of 785,489
— now reach no write transaction at all.

End to end, on a synthetic 515 MB / 200,000-row database with the production
pragmas, 1.25% of rows changed, one probe running the small
``UPDATE channels SET rec_shown_count=…`` from the crash log every 100 ms and a
second holding ``busy_timeout=0`` to time the lock directly (worst of two runs
each way):

    ============================  ============  ===========
                                        before        after
    ============================  ============  ===========
    longest single lock hold           90 ms         6 ms
    total time the lock is held     2.88s (15%)  0.14s (1%)
    concurrent writer, slowest        207 ms        36 ms
    migration wall time               18.8s         12.0s
    ============================  ============  ===========

Scaled to the owner's 785k rows: roughly half a second of write lock across the
whole pass, in 6 ms pieces, instead of eleven seconds in 90 ms pieces.

The narrowed column list is not a hand-maintained guess:
``tests/test_sports_reclassify.py`` AST-walks ``special_content.py`` for every
``channel.<attr>`` it reads and fails if one escapes ``CLASSIFIER_INPUTS`` —
so a classifier that starts reading ``raw_data`` is a red test, not a silently
wrong migration.

A crash still re-runs from the top, and that is correct rather than merely
tolerable: ``MigrationManager._run_all`` skips ``on_completed`` on an
exception, so the version stays unbumped, and the re-run writes NOTHING for the
rows the first attempt already fixed — their ``before`` now equals their
``after``. A stored resume watermark would save re-READING those rows and
nothing else, at the cost of a persisted field that has to be invalidated
whenever ``CURRENT_VERSION`` moves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.config import Config
    from metatv.core.database import Database

#: Bump when special_content.py's classification changes. See the module note.
#: v9 (2026-09-03): two independent fixes, one shared bump —
#:   1. SPORT-5: the FLSP/flolive idiom's paren-timestamp clock is US
#:      Eastern, not UTC (owner-observed, two live observations — the cross-
#:      grammar anchor that decides every other zone in this module found no
#:      second listing of these synthetic timestamps to check against).
#:      Scoped strictly to the FLSP idiom; every other platform sharing the
#:      same paren-timestamp grammar stays UTC. event_start_time/
#:      event_stop_time are already reset-and-recomputed by this pass, so
#:      the corrected reading reaches existing rows automatically.
#:   2. SPORT-8: fixture rows derive a display title from their parsed
#:      matchup (``fixture_titles.fixture_display_title``) instead of
#:      showing the raw provider slot string — see ``TITLE_FIELD`` below for
#:      why this is handled separately from ``DERIVED_FIELDS``.
#: v8 (2026-09-02): fixture opponents parsed and stored (SPORT-4 — the
#: four-feature blocker: Team facet, team identity, reliable LIVE state, and
#: live status all need event_team_a/event_team_b, which no row carried
#: before this version). Every dated fixture re-derives to acquire them.
#: v7 (2026-09-02): slot-form start:/stop: times are UTC, not machine-local —
#: stored event windows were +machine-offset (owner: +6h, so "On now" landed
#: at 3 AM and baseball never showed live). Every v6 row must be recomputed to
#: correct its stored hour.
#: v6 (2026-09-02): the slot form's "stop:" half is stored. The 56 rows that
#: carry it already had a start, so nothing looked broken — but "still on" was
#: a fixed 4h guess and their real windows are 3.00h to 7.22h. 32 ran long
#: (median 3.22h of every slot filed "Finished" while the game was on: the
#: owner's "Nothing is ever On Now") and 24 ran short (listed as on-now after
#: they ended, and the provider recycles the stream id, so the row played a
#: different game). Every v5 row must be recomputed to acquire the end time.
#: v5 (2026-09-01): the event-slot form is LOCAL wall-clock, not UTC. v4 stored
#: it as UTC and put a game the owner was actively watching into "Finished" —
#: worse than the empty lane it replaced. Every v4 row must be recomputed.
#: v4 (2026-09-01): the provider's event-slot form, "start:2026-08-31 23:45:00
#: stop:…", which no pattern matched because both ISO and DMY require the date
#: to sit between pipes. 56 rows carried it and ALL stored nothing, which is
#: why "On now" and "Upcoming" were permanently empty and every dated game fell
#: through to the "Channels" lane — with no start time a row cannot be sorted
#: live, upcoming or finished. Owner: "Nothing is ever On Now".
#: v3 (2026-08-31): two more date forms — a trailing parenthesised timestamp
#: (842 rows stored nothing, 603 of them on the 'sports' branch) and the
#: '@ Aug 27 11:00 AM' form (205 rows). Corpus coverage 1,527 -> 4,205.
#: v2 (2026-08-31): event_start_time now parses all three provider date forms and
#: converts from the zone named in the string, and the 'sports' branch extracts a
#: time at all — 927 rows carry a parseable date and stored nothing before.
#: v10 (2026-09-03): repairs rows renamed before ingestion enrolled the
#: classification columns in the rename-clear — their stored sport/event columns
#: are stale on disk.
CURRENT_VERSION = 10

#: Fields the classifier owns end-to-end. Cleared before each recompute so a row
#: that stops matching loses its stale label instead of keeping it.
DERIVED_FIELDS = (
    "special_view", "sport_type", "league_name", "team_name",
    "event_start_time", "event_stop_time", "event_metadata",
    "event_team_a", "event_team_b",
)

#: ``detected_title`` is DIFFERENT from every field above: most rows' title
#: comes from a completely different chokepoint (``update_detected_prefixes``'s
#: ``parse_channel_name`` pass, which this migration never runs) —
#: ``special_content.py`` only ever CONDITIONALLY overwrites it, for a fixture
#: row whose matchup resolves (``fixture_titles.fixture_display_title``). A
#: reset-then-recompute pass, applied the same way as ``DERIVED_FIELDS``,
#: would write None over the real title of every one of the ~750k rows this
#: pass ALSO scans that are not sports/PPV fixtures. So this is SEEDED from
#: its current value in ``_reclassify`` (never reset to None) and only
#: written back when it actually changes — see ``_reclassify``'s comment.
#: Registered as its own name (not folded into ``DERIVED_FIELDS``) so
#: ``test_every_derived_field_is_reset`` keeps meaning what it says, and
#: separately declared to the AST guard test
#: (``test_the_classifier_reads_no_column_the_page_query_omits``) so it
#: still accounts for the write.
TITLE_FIELD = "detected_title"

#: Read alongside ``TITLE_FIELD`` purely to recompute ``content_key`` through
#: its OWN single chokepoint (``content_identity.content_key_for``) on the
#: rows where ``TITLE_FIELD`` actually changes — a re-titled fixture must not
#: orphan its collapse key. Never reset; only read.
TITLE_KEY_FIELDS = ("content_key", "media_type", "detected_year", "detected_tmdb_id")

#: Every channel attribute ``special_content.update_channel_special_content``
#: READS. The page query loads these and ``DERIVED_FIELDS`` and nothing else,
#: which is what keeps the 2 KB ``raw_data`` blob off the wire for 785k rows.
#: Drift guard: ``test_the_classifier_reads_no_column_the_page_query_omits``
#: AST-walks ``special_content.py`` and fails if a read escapes this tuple.
CLASSIFIER_INPUTS = ("name", "category", "stream_url")

#: Rows per page READ. Matches ProviderLoader's own categorize batch. Only ever
#: a read now, in its own read-only scope, so it bounds memory rather than a
#: lock hold.
_BATCH = 2000

#: Changed rows per write TRANSACTION — the number that bounds the lock hold,
#: the same knob (and the same reason) as ``epg.DELETE_CHUNK``. Deliberately
#: separate from ``_BATCH``: a page of 2,000 yields ~25 changed rows at the
#: measured 1.25% change rate, so this caps the outlier page, not the typical
#: one.
WRITE_CHUNK = 500


class _TitleKeyInputs:
    """Minimal duck-typed row for ``content_key_for`` (SPORT-8's title recompute).

    ``content_key_for`` reads its inputs via ``getattr(..., default)`` off any
    object carrying ``detected_title``/``media_type``/``detected_year``/
    ``detected_tmdb_id``/``id`` — this is the four-value read
    ``_reclassify`` already has in hand from the page query, without pulling
    in a real ``ChannelDB`` sibling class from another module (CLAUDE.md:
    import a private name from where it is defined, never a re-export).
    """

    __slots__ = ("detected_title", "media_type", "detected_year", "detected_tmdb_id", "id")

    def __init__(self, title, media_type, year, tmdb_id, id_) -> None:
        self.detected_title = title
        self.media_type = media_type
        self.detected_year = year
        self.detected_tmdb_id = tmdb_id
        self.id = id_


class SportsReclassifyTask:
    """Recompute special_view/sport/league/team for every existing channel."""

    id: str = "sports_reclassify"
    label: str = "Re-sorting sports and events"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """True when the stored data predates the current classifier."""
        return getattr(config, "sports_reclassify_version", 0) < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Reset and recompute the classifier's fields across all channels.

        Runs on a worker thread. Reads and writes are separate transactions —
        see the module note. A page is read in a read-only scope which then
        CLOSES; the classify loop runs against transient instances outside any
        transaction; only the rows whose labels actually changed are written,
        ``WRITE_CHUNK`` at a time, each chunk its own short commit.

        Exceptions propagate: the manager leaves the version unbumped on a
        crash, which is what makes the retry correct (#364).

        Args:
            progress_cb: ``(done, total)`` after each page.
            is_cancelled: True when the manager has been asked to stop.
            config: Passed through to the classifier for user keyword maps.
        """
        from metatv.core.database import ChannelDB

        logger.info("SportsReclassifyTask: starting (version={})", CURRENT_VERSION)

        with self._db.session_scope(commit=False) as session:
            total = session.query(ChannelDB.id).count()
        logger.info("SportsReclassifyTask: {:,} channels to re-classify", total)

        columns = tuple(
            getattr(ChannelDB, name)
            for name in ("id",) + CLASSIFIER_INPUTS + DERIVED_FIELDS
                       + (TITLE_FIELD,) + TITLE_KEY_FIELDS
        )

        # Keyset pagination on the primary key. Not an id list + ``IN (...)``:
        # that materialises 785k ids in Python and binds 2,000 parameters per
        # batch, and an oversized IN is the failure ledger F16 records SQLite
        # RAISING on rather than degrading. Paging on the last id seen needs
        # neither.
        done = changed = 0
        last_id = ""
        while True:
            if is_cancelled():
                logger.info(
                    "SportsReclassifyTask: cancelled at {:,}/{:,}", done, total)
                return
            with self._db.session_scope(commit=False) as session:
                page = (
                    session.query(*columns)
                    .filter(ChannelDB.id > last_id)
                    .order_by(ChannelDB.id)
                    .limit(_BATCH)
                    .all()
                )
            if not page:
                break
            last_id = page[-1][0]
            done += len(page)
            changed += self._write_changes(self._reclassify(page, config))
            progress_cb(min(done, total), total)

        progress_cb(total, total)
        logger.info(
            "SportsReclassifyTask: complete — {:,} scanned, {:,} re-classified",
            done, changed,
        )

    def _reclassify(
        self, page: list, config: "Config | None"
    ) -> list[dict[str, Any]]:
        """Classify one page off-session; return an update mapping per CHANGED row.

        The row is rebuilt as a **transient** ``ChannelDB`` — constructed, never
        added to a session — so nothing here can hold a transaction open or
        leak a detached ORM object across a session boundary. It also makes the
        reset free: a fresh instance has ``None`` in every derived field, which
        is exactly what the old ``setattr(channel, field, None)`` sweep bought,
        and it is the load-bearing half of the pass (a row that stops matching
        must LOSE its label, and the classifier writes nothing in that case).

        ``TITLE_FIELD`` is the one exception to that reset: it is SEEDED from
        the row's current value instead, because ``update_channel_special_
        content`` only ever conditionally overwrites it (see ``TITLE_FIELD``'s
        module comment) — resetting it like the fields above would blank the
        real title of every row that is not a title-deriving fixture.

        Args:
            page: Rows from the page query, ``(id, *CLASSIFIER_INPUTS,
                *DERIVED_FIELDS, TITLE_FIELD, *TITLE_KEY_FIELDS)``.
            config: Passed to the classifier for user keyword maps.

        Returns:
            One ``{"id": …, **DERIVED_FIELDS, TITLE_FIELD: …}`` mapping per
            row whose labels (or title) changed — always the FULL
            ``DERIVED_FIELDS`` + ``TITLE_FIELD`` + ``content_key`` shape, so
            every update in a chunk shares one column set and the bulk write
            stays a single ``executemany`` (see ``_write_changes``). Unchanged
            rows are omitted, which is what keeps 98.75% of the catalog out
            of a write transaction entirely.
        """
        from metatv.core.content_identity import content_key_for
        from metatv.core.database import ChannelDB
        from metatv.core.special_content import update_channel_special_content

        split = 1 + len(CLASSIFIER_INPUTS)
        deriv_end = split + len(DERIVED_FIELDS)

        updates: list[dict[str, Any]] = []
        for row in page:
            scratch = ChannelDB(id=row[0], **dict(zip(CLASSIFIER_INPUTS, row[1:split])))
            before_derived = row[split:deriv_end]
            before_title = row[deriv_end]
            scratch.detected_title = before_title

            update_channel_special_content(scratch, config)

            after_derived = tuple(getattr(scratch, field) for field in DERIVED_FIELDS)
            title_changed = scratch.detected_title != before_title
            if after_derived == tuple(before_derived) and not title_changed:
                continue

            update = dict(zip(DERIVED_FIELDS, after_derived))
            update[TITLE_FIELD] = scratch.detected_title
            if title_changed:
                before_key, media_type, detected_year, detected_tmdb_id = row[deriv_end + 1:]
                update["content_key"] = content_key_for(_TitleKeyInputs(
                    scratch.detected_title, media_type, detected_year,
                    detected_tmdb_id, row[0],
                ))
            else:
                update["content_key"] = row[deriv_end + 1]  # pass-through: keeps chunk shape uniform
            updates.append({"id": row[0], **update})
        return updates

    def _write_changes(self, updates: list[dict[str, Any]]) -> int:
        """Persist *updates* in ``WRITE_CHUNK``-sized transactions.

        The commit per chunk IS the point — it is what releases the write lock,
        the same reason ``epg.delete_programmes_chunked`` commits per chunk.

        Args:
            updates: Mappings from :meth:`_reclassify`, each keyed by primary key.

        Returns:
            How many rows were written.
        """
        from sqlalchemy import update as sql_update

        from metatv.core.database import ChannelDB

        for start in range(0, len(updates), WRITE_CHUNK):
            chunk = updates[start:start + WRITE_CHUNK]
            with self._db.session_scope() as session:
                session.execute(sql_update(ChannelDB), chunk)
        return len(updates)

    def on_completed(self, config: "Config") -> None:
        """Record the version so this does not run again."""
        config.sports_reclassify_version = CURRENT_VERSION
        config.save()
