"""Behavioral tests for content-identity Slice 1 + QA fix 10bc0a7.

Guards five invariants:

1. ``content_key_for`` groups variants correctly:
   - Same title + media_type → SAME key for series/live regardless of year.
   - Same title + media_type + year → SAME key for movies.
   - Different year → different key for MOVIES (remake discriminator).
   - Series with year vs without year → SAME key (year omitted for series).
   - Movie year ranges normalised to start-year (``"2015-2018"`` → ``"2015"``).
   - Different media_type → different key.
   - Empty/None detected_title → falls back to channel id (unique, no collapse).

2. ``update_detected_prefixes`` writes ``content_key`` onto every touched channel
   and the value survives session close (no DetachedInstanceError).

3. ``backfill_content_keys`` populates NULL rows and is idempotent:
   - NULL rows before backfill → populated after.
   - Running again → 0 rows updated (no-op).
   - ``recompute_all=True`` updates every row (formula-change path).

4. ``ContentKeyBackfillTask`` integrates end-to-end: ``needs_run`` is True before
   completion, and False after ``on_completed``.

5. Regression: cross-source series with inconsistent year labelling collapse to
   the same key (e.g. "3 Body Problem 4K (2024)" vs "|ES| 3 Body Problem").

All tests use file-backed (tmp_path) SQLite DBs per CLAUDE.md rule — not
:memory:, whose pooled connections each get an empty schema.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(
    session,
    *,
    name: str = "Test Channel",
    provider_id: str = "p1",
    media_type: str = "movie",
    detected_title: str | None = None,
    detected_year: str | None = None,
    detected_prefix: str | None = None,
    detected_quality: str | None = None,
    detected_region: str | None = None,
) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            media_type=media_type,
            detected_title=detected_title,
            detected_year=detected_year,
            detected_prefix=detected_prefix,
            detected_quality=detected_quality,
            detected_region=detected_region,
        )
    )
    return cid


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables and migrations applied."""
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# 1. content_key_for — grouping semantics
# ---------------------------------------------------------------------------


class TestContentKeyFor:
    """Pure-function tests for content_key_for."""

    def _channel(self, **kwargs):
        """Build a duck-typed channel proxy."""
        defaults = dict(
            id=str(uuid.uuid4()),
            detected_title="Dark Star",
            media_type="movie",
            detected_year="2017",
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_same_title_media_year_produce_same_key(self):
        """Two movie variants with identical title/media/year share a key."""
        from metatv.core.content_identity import content_key_for

        en = self._channel(id="en-1", detected_title="Dark Star")
        fr = self._channel(id="fr-1", detected_title="Dark Star")
        assert content_key_for(en) == content_key_for(fr)

    def test_different_year_produces_different_key_for_movies(self):
        """Two movies with the same title but different years are distinct (remakes)."""
        from metatv.core.content_identity import content_key_for

        original = self._channel(media_type="movie", detected_year="1974")
        remake = self._channel(media_type="movie", detected_year="2017")
        assert content_key_for(original) != content_key_for(remake)

    def test_no_year_vs_year_produces_different_key_for_movies(self):
        """A movie without a year and one with a year are distinct."""
        from metatv.core.content_identity import content_key_for

        no_year = self._channel(media_type="movie", detected_year=None)
        with_year = self._channel(media_type="movie", detected_year="2017")
        assert content_key_for(no_year) != content_key_for(with_year)

    def test_series_with_year_and_without_year_produce_same_key(self):
        """Series: year is omitted from the key — with/without year collapse together.

        This is the QA regression (10bc0a7 Fix A): cross-source providers label
        the same series inconsistently (some add a year, some don't), so the key
        must not include year for series.
        """
        from metatv.core.content_identity import content_key_for

        with_year = self._channel(media_type="series", detected_year="2024")
        no_year = self._channel(media_type="series", detected_year=None)
        assert content_key_for(with_year) == content_key_for(no_year), (
            "Series key must not include year; same-title series from "
            "different providers should share a content_key"
        )

    def test_series_year_range_and_year_and_no_year_all_collapse(self):
        """Series: year range, single year, and no year all collapse to the same key."""
        from metatv.core.content_identity import content_key_for

        range_year = self._channel(media_type="series", detected_year="2015-2018")
        single_year = self._channel(media_type="series", detected_year="2015")
        no_year = self._channel(media_type="series", detected_year=None)
        assert content_key_for(range_year) == content_key_for(single_year)
        assert content_key_for(single_year) == content_key_for(no_year)

    def test_different_media_type_produces_different_key(self):
        """Movie and series with the same title are distinct productions."""
        from metatv.core.content_identity import content_key_for

        movie = self._channel(media_type="movie")
        series = self._channel(media_type="series")
        assert content_key_for(movie) != content_key_for(series)

    def test_empty_detected_title_falls_back_to_id(self):
        """Channels with empty/None detected_title get a unique key based on id."""
        from metatv.core.content_identity import content_key_for

        ch1 = self._channel(id="id-aaa", detected_title=None)
        ch2 = self._channel(id="id-bbb", detected_title=None)
        k1 = content_key_for(ch1)
        k2 = content_key_for(ch2)
        # Each gets its own unique key — no spurious grouping.
        assert k1 != k2
        # Key is non-empty.
        assert k1
        assert k2

    def test_punctuation_only_detected_title_falls_back_to_id(self):
        """A detected_title that normalises to empty also falls back to id."""
        from metatv.core.content_identity import content_key_for

        ch = self._channel(id="id-xyz", detected_title="---")
        key = content_key_for(ch)
        assert key  # non-empty
        # The id-based fallback means the key contains the channel id
        assert "id-xyz" in key

    def test_title_normalisation_strips_punctuation(self):
        """Two detected_titles that differ only in punctuation yield the same key."""
        from metatv.core.content_identity import content_key_for

        # "Dark Star" and "Dark. Star" should collapse to the same norm.
        ch1 = self._channel(detected_title="Dark Star")
        ch2 = self._channel(detected_title="Dark. Star")
        assert content_key_for(ch1) == content_key_for(ch2)

    def test_title_normalisation_is_case_insensitive(self):
        """Case differences are collapsed before keying."""
        from metatv.core.content_identity import content_key_for

        ch1 = self._channel(detected_title="dark star")
        ch2 = self._channel(detected_title="DARK STAR")
        assert content_key_for(ch1) == content_key_for(ch2)

    def test_key_format_movie_with_year(self):
        """Movie key uses pipe-delimited format with start year."""
        from metatv.core.content_identity import content_key_for

        ch = self._channel(detected_title="Dark Star", media_type="movie", detected_year="2017")
        key = content_key_for(ch)
        assert key == "dark star|movie|2017"

    def test_key_format_movie_year_range_normalised(self):
        """Movie year range is normalised to start year in the key."""
        from metatv.core.content_identity import content_key_for

        ch = self._channel(detected_title="Dark Star", media_type="movie", detected_year="2015-2018")
        key = content_key_for(ch)
        assert key == "dark star|movie|2015"

    def test_key_format_movie_no_year(self):
        """Movie with no year omits the year component (empty trailing segment)."""
        from metatv.core.content_identity import content_key_for

        ch = self._channel(detected_title="Dark Star", media_type="movie", detected_year=None)
        key = content_key_for(ch)
        assert key == "dark star|movie|"

    def test_key_format_series_omits_year(self):
        """Series key has only two pipe segments (title and media_type; no year)."""
        from metatv.core.content_identity import content_key_for

        ch = self._channel(detected_title="Dark Star", media_type="series", detected_year="2024")
        key = content_key_for(ch)
        assert key == "dark star|series"

    def test_key_format_series_no_year_matches_with_year(self):
        """Series key is the same whether detected_year is set or not."""
        from metatv.core.content_identity import content_key_for

        with_year = self._channel(detected_title="Dark Star", media_type="series", detected_year="2024")
        no_year = self._channel(detected_title="Dark Star", media_type="series", detected_year=None)
        assert content_key_for(with_year) == content_key_for(no_year) == "dark star|series"

    def test_key_format_live_omits_year(self):
        """Live key also omits year (same rule as series)."""
        from metatv.core.content_identity import content_key_for

        ch = self._channel(detected_title="BBC News", media_type="live", detected_year=None)
        key = content_key_for(ch)
        assert key == "bbc news|live"


# ---------------------------------------------------------------------------
# 2. update_detected_prefixes writes content_key; survives session close
# ---------------------------------------------------------------------------


def test_update_detected_prefixes_writes_content_key(db):
    """update_detected_prefixes populates content_key; readable after session close."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    # Seed two channels that should share a key (same title/type/year after stripping).
    with db.session_scope() as session:
        cid_en = _make_channel(
            session,
            name="EN - Dark Star (2017)",
            media_type="movie",
        )
        cid_fr = _make_channel(
            session,
            name="FR - Dark Star (2017)",
            media_type="movie",
        )

    # Run update_detected_prefixes to populate detected_* and content_key.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    # Read back AFTER the session closes — must not raise DetachedInstanceError.
    with db.session_scope(commit=False) as session:
        ch_en = session.query(ChannelDB).filter_by(id=cid_en).one()
        ch_fr = session.query(ChannelDB).filter_by(id=cid_fr).one()
        key_en = ch_en.content_key
        key_fr = ch_fr.content_key

    # Keys must be set and equal (same production, different-language variants).
    assert key_en is not None, "EN channel content_key must be populated"
    assert key_fr is not None, "FR channel content_key must be populated"
    assert key_en == key_fr, (
        f"EN and FR variants of same title should share content_key; "
        f"got {key_en!r} vs {key_fr!r}"
    )


def test_update_detected_prefixes_different_years_different_keys_for_movies(db):
    """update_detected_prefixes produces different keys for movies with different years."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid_old = _make_channel(session, name="Dark Star (1974)", media_type="movie")
        cid_new = _make_channel(session, name="Dark Star (2017)", media_type="movie")

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        key_old = session.query(ChannelDB.content_key).filter_by(id=cid_old).scalar()
        key_new = session.query(ChannelDB.content_key).filter_by(id=cid_new).scalar()

    assert key_old is not None
    assert key_new is not None
    assert key_old != key_new, "Different movie years must produce different content_keys"


def test_update_detected_prefixes_series_year_vs_no_year_collapse(db):
    """Series from different providers: one has a year in the name, one doesn't — same key.

    Regression for QA bug 10bc0a7 Fix A: '3 Body Problem (2024)' from source A and
    '|ES| 3 Body Problem' from source B must collapse to the same content_key.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid_with_year = _make_channel(
            session,
            name="EN - 3 Body Problem 4K (2024)",
            media_type="series",
        )
        cid_no_year = _make_channel(
            session,
            name="|ES| 3 Body Problem",
            media_type="series",
        )

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        key_with = session.query(ChannelDB.content_key).filter_by(id=cid_with_year).scalar()
        key_without = session.query(ChannelDB.content_key).filter_by(id=cid_no_year).scalar()

    assert key_with is not None
    assert key_without is not None
    assert key_with == key_without, (
        f"Cross-source series variants with/without year must share content_key; "
        f"got {key_with!r} vs {key_without!r}"
    )


def test_update_detected_prefixes_series_year_range_collapses(db):
    """Series with a year range (e.g. '12 Monkeys (2015-2018)') collapses with no-year variant.

    Regression for QA bug 10bc0a7 Fix A.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid_range = _make_channel(
            session,
            name="12 Monkeys (2015-2018)",
            media_type="series",
        )
        cid_bare = _make_channel(
            session,
            name="|EN| 12 Monkeys",
            media_type="series",
        )

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        key_range = session.query(ChannelDB.content_key).filter_by(id=cid_range).scalar()
        key_bare = session.query(ChannelDB.content_key).filter_by(id=cid_bare).scalar()

    assert key_range is not None
    assert key_bare is not None
    assert key_range == key_bare, (
        f"Series year-range and no-year variants must share content_key; "
        f"got {key_range!r} vs {key_bare!r}"
    )


def test_update_detected_prefixes_different_titles_different_keys(db):
    """Two series with genuinely different titles (e.g. '12 Monkeys' vs '12 Monos') stay separate."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid_en = _make_channel(session, name="12 Monkeys", media_type="series")
        cid_es = _make_channel(session, name="ES - 12 Monos", media_type="series")

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        key_en = session.query(ChannelDB.content_key).filter_by(id=cid_en).scalar()
        key_es = session.query(ChannelDB.content_key).filter_by(id=cid_es).scalar()

    assert key_en is not None
    assert key_es is not None
    assert key_en != key_es, "Different titles must produce different keys (no false collapse)"


# ---------------------------------------------------------------------------
# 3. backfill_content_keys — NULL → populated; second run is a no-op
# ---------------------------------------------------------------------------


def test_backfill_populates_null_rows(db):
    """backfill_content_keys writes content_key for rows that have NULL."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    # Seed rows WITH detected_title already set but WITHOUT content_key
    # (simulates pre-Slice-1 rows that have gone through prefix detection
    # but haven't had content_key computed yet).
    with db.session_scope() as session:
        cid_a = _make_channel(
            session,
            name="EN - The Crown (2016)",
            media_type="series",
            detected_title="The Crown",
            detected_year="2016",
        )
        cid_b = _make_channel(
            session,
            name="The Crown (2016)",
            media_type="series",
            detected_title="The Crown",
            detected_year="2016",
        )

    # Verify content_key starts NULL (no update_detected_prefixes was called).
    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.content_key).filter_by(id=cid_a).scalar() is None
        assert session.query(ChannelDB.content_key).filter_by(id=cid_b).scalar() is None

    # Run the backfill.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        filled = repos.channels.backfill_content_keys()

    assert filled == 2

    # Keys must now be set.
    with db.session_scope(commit=False) as session:
        key_a = session.query(ChannelDB.content_key).filter_by(id=cid_a).scalar()
        key_b = session.query(ChannelDB.content_key).filter_by(id=cid_b).scalar()

    assert key_a is not None, "Row A content_key must be populated after backfill"
    assert key_b is not None, "Row B content_key must be populated after backfill"
    # Same title/media/year → same key.
    assert key_a == key_b


def test_backfill_is_idempotent(db):
    """A second backfill run on fully-populated rows returns 0 (no-op)."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        _make_channel(
            session,
            name="The Crown (2016)",
            media_type="series",
            detected_title="The Crown",
            detected_year="2016",
        )

    # First run — populates.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        first = repos.channels.backfill_content_keys()

    assert first == 1

    # Second run — no-op.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        second = repos.channels.backfill_content_keys()

    assert second == 0, f"Second backfill run should fill 0 rows; filled {second}"


def test_backfill_recompute_all_updates_existing_keys(db):
    """backfill_content_keys(recompute_all=True) updates rows that already have a key.

    Simulates the formula-change path (version bump): existing non-NULL keys
    are stale and must be recomputed even though they are not NULL.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    # Seed one row with detected_title already set (content_key will be NULL initially).
    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="The Crown (2016)",
            media_type="series",
            detected_title="The Crown",
            detected_year="2016",
        )

    # Manually set a stale (old-formula) key that includes year.
    stale_key = "the crown|series|2016"
    with db.session_scope() as session:
        session.query(ChannelDB).filter_by(id=cid).update({"content_key": stale_key})

    # Verify stale key is in place.
    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.content_key).filter_by(id=cid).scalar() == stale_key

    # Run backfill with recompute_all=True — must overwrite the stale key.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        filled = repos.channels.backfill_content_keys(recompute_all=True)

    assert filled == 1, "recompute_all=True must update the row even though it had a key"

    with db.session_scope(commit=False) as session:
        new_key = session.query(ChannelDB.content_key).filter_by(id=cid).scalar()

    # New formula: series drop year → "the crown|series"
    assert new_key == "the crown|series", (
        f"Recomputed key should omit year for series; got {new_key!r}"
    )
    assert new_key != stale_key, "Stale key must have been replaced"


def test_backfill_skips_rows_with_existing_content_key(db):
    """backfill_content_keys only touches NULL rows; pre-populated rows are untouched."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    # Seed one row with content_key already set, one with NULL.
    with db.session_scope() as session:
        # Row with pre-existing content_key (set manually to simulate a
        # row that went through update_detected_prefixes already).
        cid_existing = _make_channel(
            session,
            name="Pre-existing",
            media_type="movie",
            detected_title="Pre-existing",
        )
        cid_null = _make_channel(
            session,
            name="Needs Backfill",
            media_type="movie",
            detected_title="Needs Backfill",
        )

    # Manually set content_key on cid_existing to simulate it being pre-populated.
    with db.session_scope() as session:
        ch = session.query(ChannelDB).filter_by(id=cid_existing).one()
        ch.content_key = "pre existing|movie|"

    # Run backfill.
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        filled = repos.channels.backfill_content_keys()

    # Only the NULL row should have been filled.
    assert filled == 1

    with db.session_scope(commit=False) as session:
        k_existing = session.query(ChannelDB.content_key).filter_by(id=cid_existing).scalar()
        k_null = session.query(ChannelDB.content_key).filter_by(id=cid_null).scalar()

    assert k_existing == "pre existing|movie|", "Pre-existing content_key must not change"
    assert k_null is not None, "NULL row must now have a content_key"


# ---------------------------------------------------------------------------
# 4. ContentKeyBackfillTask integration
# ---------------------------------------------------------------------------


def test_content_key_backfill_task_needs_run_and_completion(tmp_path):
    """ContentKeyBackfillTask.needs_run honours version field; on_completed bumps it."""
    from metatv.core.config import Config
    from metatv.core.migrations.content_key_backfill import (
        ContentKeyBackfillTask,
        CURRENT_VERSION,
    )

    config = Config(config_dir=tmp_path / "config")
    config.content_key_backfill_version = 0

    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path / 'task_test.db'}")
    db.create_tables()

    task = ContentKeyBackfillTask(db)

    # Before completion: needs_run should be True.
    assert task.needs_run(config) is True

    # Simulate on_completed.
    task.on_completed(config)

    # After completion: needs_run should be False.
    assert task.needs_run(config) is False
    assert config.content_key_backfill_version == CURRENT_VERSION

    db.close()


def test_content_key_backfill_task_run_populates_rows(tmp_path):
    """ContentKeyBackfillTask.run() fills all NULL rows in the DB."""
    from metatv.core.database import ChannelDB, Database
    from metatv.core.migrations.content_key_backfill import ContentKeyBackfillTask
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'task_run.db'}")
    db.create_tables()

    # Seed rows with detected_title set, content_key NULL.
    cids = []
    with db.session_scope() as session:
        for i in range(5):
            cid = _make_channel(
                session,
                name=f"Show {i}",
                media_type="series",
                detected_title=f"Show {i}",
                detected_year="2020",
            )
            cids.append(cid)

    task = ContentKeyBackfillTask(db)
    task.run(progress_cb=lambda d, t: None, is_cancelled=lambda: False)

    # All rows must now have a content_key.
    with db.session_scope(commit=False) as session:
        for cid in cids:
            key = session.query(ChannelDB.content_key).filter_by(id=cid).scalar()
            assert key is not None, f"Channel {cid} should have content_key after task.run()"

    db.close()
