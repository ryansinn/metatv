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
the whole point. The six derived fields are cleared first and then recomputed.
All six are machine-derived; no user state is touched (CLAUDE.md: migrations
rewrite only generated data).

CLASSIFIER_VERSION
------------------
``CURRENT_VERSION`` is the executable statement of "the classifier changed".
**A future change to** ``special_content.py`` **must bump it**, or that fix will
reach new rows only and the stored data will drift again in the same way. There
is no cheaper signal: the alternative is a per-row stamp of the classifier
version, which is a column and a write on 785k rows to save a migration that
runs once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:                                    # pragma: no cover
    from metatv.core.config import Config
    from metatv.core.database import Database

#: Bump when special_content.py's classification changes. See the module note.
#: v3 (2026-08-31): two more date forms — a trailing parenthesised timestamp
#: (842 rows stored nothing, 603 of them on the 'sports' branch) and the
#: '@ Aug 27 11:00 AM' form (205 rows). Corpus coverage 1,527 -> 4,205.
#: v2 (2026-08-31): event_start_time now parses all three provider date forms and
#: converts from the zone named in the string, and the 'sports' branch extracts a
#: time at all — 927 rows carry a parseable date and stored nothing before.
CURRENT_VERSION = 3

#: Fields the classifier owns end-to-end. Cleared before each recompute so a row
#: that stops matching loses its stale label instead of keeping it.
DERIVED_FIELDS = (
    "special_view", "sport_type", "league_name", "team_name",
    "event_start_time", "event_metadata",
)

#: Rows per commit. Matches ProviderLoader's own categorize batch, and bounds
#: how many full ORM objects (raw_data included) are resident at once.
_BATCH = 2000


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

        Runs on a worker thread. Ids are collected first and the rows loaded in
        batches, so ``raw_data`` for 785k channels is never resident at once —
        the same shape ``ProviderLoader._categorize_special_content`` uses.

        Exceptions propagate: the manager leaves the version unbumped on a
        crash, which is what makes the retry correct (#364).

        Args:
            progress_cb: ``(done, total)`` after each batch commit.
            is_cancelled: True when the manager has been asked to stop.
            config: Passed through to the classifier for user keyword maps.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.special_content import update_channel_special_content

        logger.info("SportsReclassifyTask: starting (version={})", CURRENT_VERSION)

        with self._db.session_scope(commit=False) as session:
            total = session.query(ChannelDB.id).count()
        logger.info("SportsReclassifyTask: {:,} channels to re-classify", total)

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
            with self._db.session_scope() as session:
                batch = (
                    session.query(ChannelDB)
                    .filter(ChannelDB.id > last_id)
                    .order_by(ChannelDB.id)
                    .limit(_BATCH)
                    .all()
                )
                if not batch:
                    break
                for channel in batch:
                    before = tuple(getattr(channel, f) for f in DERIVED_FIELDS)
                    for field in DERIVED_FIELDS:
                        setattr(channel, field, None)
                    update_channel_special_content(channel, config)
                    if before != tuple(getattr(channel, f) for f in DERIVED_FIELDS):
                        changed += 1
                done += len(batch)
                last_id = batch[-1].id
            progress_cb(min(done, total), total)

        progress_cb(total, total)
        logger.info(
            "SportsReclassifyTask: complete — {:,} scanned, {:,} re-classified",
            done, changed,
        )

    def on_completed(self, config: "Config") -> None:
        """Record the version so this does not run again."""
        config.sports_reclassify_version = CURRENT_VERSION
        config.save()
