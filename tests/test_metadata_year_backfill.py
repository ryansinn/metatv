"""``metadata.year`` must actually be populated, not merely derivable.

CLAUDE.md says to read ``metadata.year`` everywhere because ``_derive_year``
"populates it at write from ``release_date``, backfills pre-fix rows on read".
Measured on the owner's library: **437 of 101,896** rows with a release_date
had a year. 0.4%.

Both halves of the claim were true and neither reached the column. The write
path does derive — those 437 rows. The read path derives into the returned
``MetadataResult`` and never writes back, so the stored column stayed NULL.

It matters because SQL reads the column. ``content_dedup.extract_year`` asks
``meta.year`` first and otherwise parses the CHANNEL NAME for "(2004)":

    fell back to parsing the channel name ....  40,994
    got no year at all ......................  60,465
      ...release_date could have supplied one   60,448
    name-parsed year DISAGREED with the date .     622

An external audit reported this as C6 and it had **no test of any kind** —
nothing in the suite touched ``_derive_year``.
"""

import pytest
from sqlalchemy import text

from metatv.core.database import Database, MetadataDB
from metatv.core.metadata_manager import MetadataManager
from metatv.core.migrations.metadata_year_backfill import (
    CURRENT_VERSION, MetadataYearBackfillTask,
)


@pytest.fixture
def db(tmp_path):
    """A real file-backed database — this migration is one UPDATE statement."""
    database = Database(f"sqlite:///{tmp_path / 'meta.db'}")
    database.create_tables()
    return database


def _add(db, rows):
    with db.session_scope() as s:
        for i, (release_date, year) in enumerate(rows):
            s.add(MetadataDB(id=f"m{i}", title=f"T{i}",
                             release_date=release_date, year=year))


def _years(db):
    with db.session_scope() as s:
        return {r[0]: r[1] for r in s.execute(
            text("SELECT release_date, year FROM metadata")).all()}


class _Cfg:
    metadata_year_backfill_version = 0
    def save(self):  # noqa: D102 - test double
        pass


# ── the fix ─────────────────────────────────────────────────────────────────

def test_a_derivable_year_is_written_to_the_column(db) -> None:
    """The whole defect: the date was there and the column stayed NULL."""
    _add(db, [("2019-07-25", None), ("2014-01-02", None)])

    MetadataYearBackfillTask(db).run(lambda d, t: None, lambda: False)

    assert _years(db) == {"2019-07-25": 2019, "2014-01-02": 2014}


def test_an_existing_year_is_not_overwritten(db) -> None:
    """A stored year wins — ``_derive_year`` returns it untouched too."""
    _add(db, [("2019-07-25", 1998)])
    MetadataYearBackfillTask(db).run(lambda d, t: None, lambda: False)
    assert _years(db)["2019-07-25"] == 1998


@pytest.mark.parametrize("junk", [".", "Rambod Javan", "(1939-1946)", "", "N/A"])
def test_an_unparseable_date_is_left_alone(db, junk: str) -> None:
    """SQLite's ``CAST('abcd' AS INTEGER)`` is 0, not NULL.

    Without the digit guard these would each be stored as year 0 — a value
    that looks real to every consumer and is wrong. 18 such rows exist in the
    owner's library.
    """
    _add(db, [(junk, None)])
    MetadataYearBackfillTask(db).run(lambda d, t: None, lambda: False)

    with db.session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM metadata WHERE year = 0")).scalar() == 0
        assert s.execute(text("SELECT year FROM metadata")).scalar() is None


def test_a_null_release_date_is_left_alone(db) -> None:
    _add(db, [(None, None)])
    MetadataYearBackfillTask(db).run(lambda d, t: None, lambda: False)
    with db.session_scope() as s:
        assert s.execute(text("SELECT year FROM metadata")).scalar() is None


# ── it must agree with the function it is standing in for ───────────────────

@pytest.mark.parametrize("release_date", [
    "2019-07-25", "1975-01-01", "2024", "2024-12", "1394-05-05", "0001-01-01",
])
def test_the_migration_writes_exactly_what_derive_year_returns(db, release_date: str) -> None:
    """One definition of "the year", not two.

    ``_derive_year`` applies no plausibility bound — it returns
    ``int(release_date[:4])`` for anything parseable. If this migration second-
    guessed that (rejecting 1394 as implausible, say) the stored column and the
    value computed at read time would disagree, which is a worse failure than
    an odd year: two sources of truth for the same field.
    """
    _add(db, [(release_date, None)])
    MetadataYearBackfillTask(db).run(lambda d, t: None, lambda: False)

    assert _years(db)[release_date] == MetadataManager._derive_year(None, release_date)


# ── the migration's own contract ────────────────────────────────────────────

def test_it_reports_work_while_a_row_still_needs_it(db) -> None:
    _add(db, [("2019-07-25", None)])
    assert MetadataYearBackfillTask(db).needs_run(_Cfg()) is True


def test_it_reports_no_work_once_every_row_is_done(db) -> None:
    _add(db, [("2019-07-25", None)])
    task = MetadataYearBackfillTask(db)
    task.run(lambda d, t: None, lambda: False)
    assert task.needs_run(_Cfg()) is False


def test_a_stamped_config_stops_it_rescanning(db) -> None:
    """Reading the DATA every launch on a 650k-row table is the cost avoided."""
    _add(db, [("2019-07-25", None)])
    cfg = _Cfg()
    cfg.metadata_year_backfill_version = CURRENT_VERSION
    assert MetadataYearBackfillTask(db).needs_run(cfg) is False


def test_running_twice_changes_nothing(db) -> None:
    """Re-running must be a no-op — the WHERE clause excludes finished rows."""
    _add(db, [("2019-07-25", None), (".", None)])
    task = MetadataYearBackfillTask(db)
    task.run(lambda d, t: None, lambda: False)
    first = _years(db)
    task.run(lambda d, t: None, lambda: False)
    assert _years(db) == first


def test_completion_stamps_the_version(db) -> None:
    cfg = _Cfg()
    MetadataYearBackfillTask(db).on_completed(cfg)
    assert cfg.metadata_year_backfill_version == CURRENT_VERSION
