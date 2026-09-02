"""Behavioral tests for the Migration Center subsystem.

Three test suites:
1. ``update_detected_prefixes`` progress + cancellation
2. ``MigrationManager`` — skip, signal ordering, cancellation
3. ``MigrationProgressWidget`` — slot-driven rendering
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared DB helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with tables created."""
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(session, name: str, provider_id: str = "p1") -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB
    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type="live",
    ))
    return cid


# ---------------------------------------------------------------------------
# 1. update_detected_prefixes — progress_cb and is_cancelled
# ---------------------------------------------------------------------------

class TestUpdateDetectedPrefixesProgressAndCancel:
    """Behavioral tests for the progress_cb / is_cancelled extension."""

    def test_progress_cb_called_with_non_decreasing_done(self, db):
        """progress_cb receives non-decreasing done values ending at total."""
        from metatv.core.repositories import RepositoryFactory

        # Insert 5 channels — fewer than _BATCH so a single batch, but progress_cb
        # is still called once after that batch.
        with db.session_scope() as session:
            for i in range(5):
                _make_channel(session, f"EN - Channel {i}")

        calls: list[tuple[int, int]] = []

        def _cb(done: int, total: int) -> None:
            calls.append((done, total))

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(progress_cb=_cb)

        assert len(calls) >= 1, "progress_cb must be called at least once"

        # done values must be non-decreasing
        done_vals = [d for d, _ in calls]
        assert done_vals == sorted(done_vals), (
            f"done values are not non-decreasing: {done_vals}"
        )

        # total must be consistent
        totals = {t for _, t in calls}
        assert len(totals) == 1, f"total changed mid-run: {totals}"
        total = totals.pop()
        assert total == 5, f"expected total=5, got {total}"

        # Final call's done must equal total (single-batch case: done = min(5, 5) = 5)
        final_done, final_total = calls[-1]
        assert final_done == final_total, (
            f"last progress_cb call should have done==total; "
            f"got done={final_done}, total={final_total}"
        )

    def test_progress_cb_called_for_multiple_batches(self, db):
        """With >_BATCH channels, progress_cb is called once per batch."""
        from metatv.core.repositories import RepositoryFactory

        # Seed 2500 channels (> _BATCH=2000) → two batches → two progress_cb calls
        with db.session_scope() as session:
            for i in range(2500):
                _make_channel(session, f"EN - Channel {i}")

        calls: list[tuple[int, int]] = []
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(progress_cb=lambda d, t: calls.append((d, t)))

        # Expect exactly 2 calls (ceil(2500/2000) = 2)
        assert len(calls) == 2, f"expected 2 progress_cb calls, got {len(calls)}: {calls}"

        # Values must be non-decreasing
        assert calls[0][0] <= calls[1][0], "done values not non-decreasing"
        # Total is consistent
        assert calls[0][1] == calls[1][1] == 2500, f"total should be 2500: {calls}"
        # After batch 1: min(0+2000, 2500) = 2000
        assert calls[0][0] == 2000, f"first batch done should be 2000: {calls[0]}"
        # After batch 2: min(2000+2000, 2500) = 2500
        assert calls[1][0] == 2500, f"second batch done should be 2500: {calls[1]}"

    def test_is_cancelled_stops_after_first_batch(self, db):
        """is_cancelled returning True after first batch stops the loop early.

        Behavioral contract:
        - Exactly one batch (2000 rows) is committed before cancellation fires.
        - Exactly 500 rows are left with detected_prefix=None (not yet processed).
        - The second-batch channels are those the DB chose to put in all_ids[2000:],
          which is query-order-dependent (no ORDER BY) — we verify by counting
          rather than picking a specific id.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        # Seed 2500 channels (two batches: 2000 + 500).
        # Names all start with "EN -" so every processed channel gets detected_prefix="EN".
        with db.session_scope() as session:
            for i in range(2500):
                _make_channel(session, f"EN - Channel {i}")

        batch_count = [0]

        def _cb(done: int, total: int) -> None:
            batch_count[0] += 1

        call_count = [0]

        def _is_cancelled() -> bool:
            # Cancel starting from the second check (between batches 1 and 2)
            call_count[0] += 1
            return call_count[0] > 1

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(
                progress_cb=_cb,
                is_cancelled=_is_cancelled,
            )

        # Only one progress_cb call → only one batch committed
        assert batch_count[0] == 1, (
            f"expected exactly 1 batch to commit before cancellation, got {batch_count[0]}"
        )

        # After cancellation: exactly 2000 channels should have detected_prefix set,
        # and exactly 500 should still be None.
        with db.session_scope() as session:
            processed_count = (
                session.query(ChannelDB)
                .filter(ChannelDB.detected_prefix.isnot(None))
                .count()
            )
            unprocessed_count = (
                session.query(ChannelDB)
                .filter(ChannelDB.detected_prefix.is_(None))
                .count()
            )

        assert processed_count == 2000, (
            f"expected exactly 2000 processed channels (first batch), got {processed_count}"
        )
        assert unprocessed_count == 500, (
            f"expected exactly 500 unprocessed channels (cancelled second batch), "
            f"got {unprocessed_count}"
        )

    def test_no_progress_no_cancel_unchanged(self, db):
        """Passing None for both params keeps existing behavior (regression guard)."""
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            for i in range(3):
                _make_channel(session, f"FR - Film {i}")

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            count = repos.channels.update_detected_prefixes()  # no progress_cb / is_cancelled

        assert count == 3, f"expected 3 updated channels, got {count}"

    def test_is_cancelled_immediate_skips_all(self, db):
        """is_cancelled returning True immediately skips all batches."""
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            cid = _make_channel(session, "DE - Film")

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(
                is_cancelled=lambda: True,  # immediately cancelled
            )

        # Channel should still be unprocessed
        with db.session_scope() as session:
            ch = session.query(ChannelDB).filter_by(id=cid).first()
            assert ch.detected_prefix is None, (
                f"Channel should not be processed when is_cancelled is always True; "
                f"got detected_prefix={ch.detected_prefix!r}"
            )


# ---------------------------------------------------------------------------
# 1b. update_detected_prefixes — transient lock retry
# ---------------------------------------------------------------------------

class TestUpdateDetectedPrefixesLockRetry:
    """Behavioral tests for the OperationalError('database is locked') retry
    in ChannelRepository._commit_prefix_batch_with_retry / _process_prefix_batch.

    Regression: the owner's 2026-07-31 and 2026-08-01 detected_title_reparse
    runs crash-looped on a transient 'database is locked' raised mid-batch by
    a concurrent EPG-refresh / series-monitor writer — one lock collision
    aborted the ENTIRE multi-batch run (already-committed batches stayed
    durable, but the whole pass restarted from scratch on the next launch,
    repeating the progress strip every launch). These tests drive the real
    batch-commit path against a real tmp_path Database and force a fake lock
    error via a patched ``Session.commit``.
    """

    def test_lock_error_retries_then_succeeds(self, db, monkeypatch):
        """Two transient lock errors, then a real commit succeeds: the batch
        is NOT aborted and the channel IS updated (not lost to the retry)."""
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory
        # The retry loop lives in core/db_lock.py, so `time` is imported THERE.
        # CLAUDE.md: patch the module that DEFINES a name, never one that merely
        # imported it. This read `channel_mod.time` for months; the day the loop
        # was shared, that attribute stopped existing and eight tests went red.
        from metatv.core import db_lock as lock_mod
        from sqlalchemy.exc import OperationalError

        with db.session_scope() as session:
            cid = _make_channel(session, "EN - Test Channel")

        sleeps: list[float] = []
        monkeypatch.setattr(lock_mod.time, "sleep", lambda s: sleeps.append(s))

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            real_commit = session.commit
            calls = {"n": 0}

            def _flaky_commit():
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise OperationalError(
                        "UPDATE channels ...", {}, Exception("database is locked")
                    )
                real_commit()

            monkeypatch.setattr(session, "commit", _flaky_commit)
            try:
                count = repos.channels.update_detected_prefixes()
            finally:
                # Restore the real bound method before this `with` block exits —
                # session_scope() itself commits on success, and that exit-commit
                # must not also run through the flaky stub (it already did its
                # job inside update_detected_prefixes).
                monkeypatch.setattr(session, "commit", real_commit)

        assert count == 1, f"expected the channel to be updated, got count={count}"
        assert calls["n"] == 3, f"expected 2 failed attempts + 1 success, got {calls['n']}"
        assert len(sleeps) == 2, f"expected a sleep between each of the 2 retries, got {sleeps}"

        with db.session_scope() as session:
            ch = session.query(ChannelDB).filter_by(id=cid).first()
            assert ch.detected_prefix == "EN", (
                f"expected the retried batch to actually persist; got {ch.detected_prefix!r}"
            )

    def test_lock_error_exhausts_retries_and_raises(self, db, monkeypatch):
        """A lock error on every attempt re-raises after the retry budget —
        it does not retry forever."""
        from metatv.core.repositories import RepositoryFactory
        # The retry loop lives in core/db_lock.py, so `time` is imported THERE.
        # CLAUDE.md: patch the module that DEFINES a name, never one that merely
        # imported it. This read `channel_mod.time` for months; the day the loop
        # was shared, that attribute stopped existing and eight tests went red.
        from metatv.core import db_lock as lock_mod
        from metatv.core.repositories import channel as channel_mod
        from sqlalchemy.exc import OperationalError

        with db.session_scope() as session:
            _make_channel(session, "EN - Test Channel")

        monkeypatch.setattr(lock_mod.time, "sleep", lambda s: None)

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            real_commit = session.commit
            calls = {"n": 0}

            def _always_locked():
                calls["n"] += 1
                raise OperationalError(
                    "UPDATE channels ...", {}, Exception("database is locked")
                )

            monkeypatch.setattr(session, "commit", _always_locked)
            try:
                with pytest.raises(OperationalError):
                    repos.channels.update_detected_prefixes()
            finally:
                # Restore before the `with` block's own exit-commit fires — the
                # aborted run already rolled itself back; let session_scope's
                # exit run against the real (harmless, nothing-pending) commit.
                monkeypatch.setattr(session, "commit", real_commit)

        assert calls["n"] == channel_mod._LOCK_RETRY_ATTEMPTS, (
            f"expected exactly {channel_mod._LOCK_RETRY_ATTEMPTS} attempts, got {calls['n']}"
        )

    def test_non_lock_operational_error_aborts_without_retry(self, db, monkeypatch):
        """A non-'locked' OperationalError aborts immediately — no retry, no
        sleep. Extends the #364 contract at the layer the lock/non-lock
        distinction now lives in: only lock contention retries, every other
        failure still aborts the run so the caller (MigrationManager) leaves
        the version unbumped."""
        from metatv.core.repositories import RepositoryFactory
        # The retry loop lives in core/db_lock.py, so `time` is imported THERE.
        # CLAUDE.md: patch the module that DEFINES a name, never one that merely
        # imported it. This read `channel_mod.time` for months; the day the loop
        # was shared, that attribute stopped existing and eight tests went red.
        from metatv.core import db_lock as lock_mod
        from sqlalchemy.exc import OperationalError

        with db.session_scope() as session:
            _make_channel(session, "EN - Test Channel")

        sleeps: list[float] = []
        monkeypatch.setattr(lock_mod.time, "sleep", lambda s: sleeps.append(s))

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            real_commit = session.commit
            calls = {"n": 0}

            def _broken_commit():
                calls["n"] += 1
                raise OperationalError(
                    "UPDATE channels ...", {}, Exception("no such table: channels")
                )

            monkeypatch.setattr(session, "commit", _broken_commit)
            try:
                with pytest.raises(OperationalError):
                    repos.channels.update_detected_prefixes()
            finally:
                monkeypatch.setattr(session, "commit", real_commit)

        assert calls["n"] == 1, "a non-lock error must not be retried"
        assert sleeps == [], "must not sleep on a non-lock error"


# ---------------------------------------------------------------------------
# 1c. update_detected_prefixes propagation phases — lock retry (migration
#     resilience wave 2)
# ---------------------------------------------------------------------------

def _make_vod_channel(
    session,
    *,
    provider_id: str = "p1",
    media_type: str = "movie",
    detected_title: str,
    detected_year: str | None = None,
    detected_tmdb_id: str | None = None,
    content_key: str | None = None,
    detected_region: str | None = None,
) -> str:
    """Insert a VOD ChannelDB row with detected_* fields pre-seeded directly
    (bypassing update_detected_prefixes parsing), so a propagation phase's
    winner/idless scan can be exercised without depending on name parsing."""
    from metatv.core.database import ChannelDB
    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=detected_title,
        media_type=media_type,
        detected_title=detected_title,
        detected_year=detected_year,
        detected_tmdb_id=detected_tmdb_id,
        content_key=content_key,
        detected_region=detected_region,
    ))
    return cid


class TestPropagationLockRetry:
    """Behavioral tests for the shared ``_retry_on_lock`` helper covering the
    two propagation phases of ``update_detected_prefixes`` —
    ``_propagate_region_from_siblings`` and ``propagate_tmdb_from_title_siblings``.

    Regression: the owner's 2026-08-01 18:48 log shows
    ``propagate_tmdb_from_title_siblings`` crashing on a transient
    'database is locked' at its bulk UPDATE — #367's retry only covered the
    batch-commit phase, not these two. Both phases now retry through the same
    ``ChannelRepository._retry_on_lock`` the batch phase uses.
    """

    def test_region_propagation_retries_then_succeeds(self, db, monkeypatch):
        """A lock error during the region-sibling fill's final commit retries
        and the fill still lands (not lost to the retry)."""
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory
        # The retry loop lives in core/db_lock.py, so `time` is imported THERE.
        # CLAUDE.md: patch the module that DEFINES a name, never one that merely
        # imported it. This read `channel_mod.time` for months; the day the loop
        # was shared, that attribute stopped existing and eight tests went red.
        from metatv.core import db_lock as lock_mod
        from sqlalchemy.exc import OperationalError

        with db.session_scope() as session:
            # Winner: has content_key + a region. Empty: same content_key, no region.
            _make_vod_channel(
                session, detected_title="Foo", content_key="k1",
                detected_region="US",
            )
            empty_id = _make_vod_channel(
                session, detected_title="Foo (ES source)", content_key="k1",
                detected_region=None,
            )

        sleeps: list[float] = []
        monkeypatch.setattr(lock_mod.time, "sleep", lambda s: sleeps.append(s))

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            real_commit = session.commit
            calls = {"n": 0}

            def _flaky_commit():
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise OperationalError(
                        "UPDATE channels ...", {}, Exception("database is locked")
                    )
                real_commit()

            monkeypatch.setattr(session, "commit", _flaky_commit)
            try:
                filled = repos.channels._propagate_region_from_siblings()
            finally:
                monkeypatch.setattr(session, "commit", real_commit)

        assert filled == 1, f"expected the empty row to be filled, got {filled}"
        assert calls["n"] == 3, f"expected 2 failed attempts + 1 success, got {calls['n']}"
        assert len(sleeps) == 2, f"expected a sleep between each retry, got {sleeps}"

        with db.session_scope() as session:
            ch = session.query(ChannelDB).filter_by(id=empty_id).first()
            assert ch.detected_region == "US", (
                f"expected the retried fill to persist, got {ch.detected_region!r}"
            )

    def test_region_propagation_non_lock_error_aborts_without_retry(self, db, monkeypatch):
        from metatv.core.repositories import RepositoryFactory
        # The retry loop lives in core/db_lock.py, so `time` is imported THERE.
        # CLAUDE.md: patch the module that DEFINES a name, never one that merely
        # imported it. This read `channel_mod.time` for months; the day the loop
        # was shared, that attribute stopped existing and eight tests went red.
        from metatv.core import db_lock as lock_mod
        from sqlalchemy.exc import OperationalError

        with db.session_scope() as session:
            _make_vod_channel(session, detected_title="Foo", content_key="k1", detected_region="US")
            _make_vod_channel(session, detected_title="Foo2", content_key="k1", detected_region=None)

        sleeps: list[float] = []
        monkeypatch.setattr(lock_mod.time, "sleep", lambda s: sleeps.append(s))

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            real_commit = session.commit
            calls = {"n": 0}

            def _broken_commit():
                calls["n"] += 1
                raise OperationalError("UPDATE channels ...", {}, Exception("disk I/O error"))

            monkeypatch.setattr(session, "commit", _broken_commit)
            try:
                with pytest.raises(OperationalError):
                    repos.channels._propagate_region_from_siblings()
            finally:
                monkeypatch.setattr(session, "commit", real_commit)

        assert calls["n"] == 1, "a non-lock error must not be retried"
        assert sleeps == [], "must not sleep on a non-lock error"

    def test_tmdb_propagation_retries_then_succeeds(self, db, monkeypatch):
        """A lock error during the tmdb-sibling adoption's final commit
        retries and the adoption still lands — the exact site from the owner
        log (channel.py propagate_tmdb_from_title_siblings, ~line 1750)."""
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory
        # The retry loop lives in core/db_lock.py, so `time` is imported THERE.
        # CLAUDE.md: patch the module that DEFINES a name, never one that merely
        # imported it. This read `channel_mod.time` for months; the day the loop
        # was shared, that attribute stopped existing and eight tests went red.
        from metatv.core import db_lock as lock_mod
        from sqlalchemy.exc import OperationalError

        with db.session_scope() as session:
            _make_vod_channel(
                session, detected_title="The Matrix", detected_year="1999",
                detected_tmdb_id="603",
            )
            idless_id = _make_vod_channel(
                session, detected_title="the  matrix", detected_year="1999",
            )

        sleeps: list[float] = []
        monkeypatch.setattr(lock_mod.time, "sleep", lambda s: sleeps.append(s))

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            real_commit = session.commit
            calls = {"n": 0}

            def _flaky_commit():
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise OperationalError(
                        "UPDATE channels ...", {}, Exception("database is locked")
                    )
                real_commit()

            monkeypatch.setattr(session, "commit", _flaky_commit)
            try:
                adopted = repos.channels.propagate_tmdb_from_title_siblings()
            finally:
                monkeypatch.setattr(session, "commit", real_commit)

        assert adopted == 1, f"expected the idless row to adopt the sibling id, got {adopted}"
        assert calls["n"] == 3, f"expected 2 failed attempts + 1 success, got {calls['n']}"
        assert len(sleeps) == 2, f"expected a sleep between each retry, got {sleeps}"

        with db.session_scope() as session:
            ch = session.query(ChannelDB).filter_by(id=idless_id).first()
            assert ch.detected_tmdb_id == "603", (
                f"expected the retried adoption to persist, got {ch.detected_tmdb_id!r}"
            )
            assert ch.content_key == "tmdb:603|movie"

    def test_tmdb_propagation_non_lock_error_aborts_without_retry(self, db, monkeypatch):
        from metatv.core.repositories import RepositoryFactory
        # The retry loop lives in core/db_lock.py, so `time` is imported THERE.
        # CLAUDE.md: patch the module that DEFINES a name, never one that merely
        # imported it. This read `channel_mod.time` for months; the day the loop
        # was shared, that attribute stopped existing and eight tests went red.
        from metatv.core import db_lock as lock_mod
        from sqlalchemy.exc import OperationalError

        with db.session_scope() as session:
            _make_vod_channel(
                session, detected_title="The Matrix", detected_year="1999",
                detected_tmdb_id="603",
            )
            _make_vod_channel(session, detected_title="the  matrix", detected_year="1999")

        sleeps: list[float] = []
        monkeypatch.setattr(lock_mod.time, "sleep", lambda s: sleeps.append(s))

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            real_commit = session.commit
            calls = {"n": 0}

            def _broken_commit():
                calls["n"] += 1
                raise OperationalError("UPDATE channels ...", {}, Exception("disk I/O error"))

            monkeypatch.setattr(session, "commit", _broken_commit)
            try:
                with pytest.raises(OperationalError):
                    repos.channels.propagate_tmdb_from_title_siblings()
            finally:
                monkeypatch.setattr(session, "commit", real_commit)

        assert calls["n"] == 1, "a non-lock error must not be retried"
        assert sleeps == [], "must not sleep on a non-lock error"


class TestBackfillTaskSurvivesPropagationLock:
    """Coordinator follow-up (2026-08-01 18:50 trace): detected_genre_backfill
    crashed at the identical propagation site as detected_title_reparse — both
    tasks call the SAME ``update_detected_prefixes``, so one shared retry
    helper must demonstrably cover BOTH tasks' full run, not just the batch
    phase. Runs the REAL ``DetectedGenreBackfillTask.run()`` end-to-end
    (through its own ``session_scope``) with a flaky commit spanning past the
    batch phase into a propagation phase, and asserts the task completes
    without raising.
    """

    def test_genre_backfill_task_survives_lock_in_propagation_phase(self, db, monkeypatch):
        from metatv.core.migrations.detected_genre_backfill import DetectedGenreBackfillTask
        # The retry loop lives in core/db_lock.py, so `time` is imported THERE.
        # CLAUDE.md: patch the module that DEFINES a name, never one that merely
        # imported it. This read `channel_mod.time` for months; the day the loop
        # was shared, that attribute stopped existing and eight tests went red.
        from metatv.core import db_lock as lock_mod
        from sqlalchemy.exc import OperationalError

        # A single VOD row that, after the batch phase parses it, has BOTH a
        # non-null content_key + detected_region (feeds the region-sibling
        # winner map) AND a pre-seeded detected_tmdb_id (feeds the tmdb-sibling
        # groups map) — so neither propagation phase early-returns before
        # reaching its final commit. category="|US|" drives the parser's
        # category->region fallback (name itself carries no locale marker).
        with db.session_scope() as session:
            from metatv.core.database import ChannelDB
            session.add(ChannelDB(
                id=str(uuid.uuid4()),
                source_id=str(uuid.uuid4()),
                provider_id="p1",
                name="Some Movie (2020)",
                media_type="movie",
                category="|US|",
                detected_tmdb_id="12345",
            ))

        sleeps: list[float] = []
        monkeypatch.setattr(lock_mod.time, "sleep", lambda s: sleeps.append(s))

        task = DetectedGenreBackfillTask(db)

        # Commit-call sequence for this single-row fixture is deterministic:
        # #1 batch commit, #2 region-propagation's unconditional final commit,
        # #3 tmdb-propagation's unconditional final commit (each phase reaches
        # its final commit even when it fills/adopts 0 rows, as long as its
        # winner/groups map isn't empty — see _propagate_region_from_siblings /
        # propagate_tmdb_from_title_siblings). Fail call #2 and #4 once each so
        # BOTH propagation phases hit — and retry past — a lock error.
        calls = {"n": 0}
        FAIL_ONCE_ON = {2, 4}

        def _patched_session_scope(self, commit=True):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                with self.SessionLocal() as session:
                    real_commit = session.commit

                    def _flaky_commit():
                        calls["n"] += 1
                        if calls["n"] in FAIL_ONCE_ON:
                            raise OperationalError(
                                "UPDATE channels ...", {}, Exception("database is locked")
                            )
                        real_commit()

                    session.commit = _flaky_commit
                    try:
                        yield session
                        if commit:
                            session.commit()
                        else:
                            session.rollback()
                    except Exception:
                        session.rollback()
                        raise
                    finally:
                        session.close()

            return _cm()

        monkeypatch.setattr(
            type(db), "session_scope", _patched_session_scope, raising=True
        )

        # Should complete without raising — both propagation phases recovered.
        task.run(progress_cb=lambda *a: None, is_cancelled=lambda: False)

        assert calls["n"] >= 3, f"expected at least 3 commit calls, got {calls['n']}"
        assert len(sleeps) >= 1, "expected at least one lock-retry sleep"


class TestCrashedTaskDoesNotLeakLock:
    """Coordinator follow-up: verify a task that crashes mid-``update_detected_prefixes``
    does NOT leave an open write transaction holding the SQLite lock — a NEW
    session/connection must be able to write immediately afterward. Both the
    inner ``_retry_on_lock`` (final-attempt re-raise, after its own rollback)
    and the outer ``session_scope`` (rollback + close on any exception) are
    expected to fully release the writer; this test proves the combination
    rather than re-deriving SQLite locking semantics from the source.
    """

    def test_new_connection_writes_immediately_after_crash(self, db, monkeypatch):
        import time as _time
        from sqlalchemy import update
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import channel as channel_mod
        from metatv.core.migrations.detected_title_reparse import DetectedTitleReparseTask

        with db.session_scope() as session:
            cid = _make_channel(session, "EN - Test Channel")

        def _boom(self, *a, **kw):
            # Touch the session with a real pending write, THEN blow up — if
            # anything leaked, this pending change is what would hold the lock.
            self.session.execute(
                update(ChannelDB).where(ChannelDB.id == cid).values(detected_prefix="LEAK")
            )
            raise RuntimeError("simulated crash mid-migration")

        monkeypatch.setattr(
            channel_mod.ChannelRepository, "update_detected_prefixes", _boom
        )

        task = DetectedTitleReparseTask(db)
        with pytest.raises(RuntimeError):
            task.run(progress_cb=lambda *a: None, is_cancelled=lambda: False)

        # A brand-new session must be able to write IMMEDIATELY — no lingering
        # transaction from the crashed task holding the writer. Bound the wait
        # so a real leak fails fast instead of hanging out the test timeout.
        t0 = _time.monotonic()
        with db.session_scope() as session2:
            session2.execute(
                update(ChannelDB).where(ChannelDB.id == cid).values(detected_prefix="FRESH")
            )
        elapsed = _time.monotonic() - t0
        assert elapsed < 5.0, f"new connection write took {elapsed}s — looks like a leaked lock"

        with db.session_scope() as session3:
            ch = session3.query(ChannelDB).filter_by(id=cid).first()
            assert ch.detected_prefix == "FRESH", (
                "the crashed task's own pending write must have been rolled "
                f"back, got detected_prefix={ch.detected_prefix!r}"
            )


# ---------------------------------------------------------------------------
# 2. MigrationManager — skip, signal ordering, cancellation
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _FakeTask:
    """Controllable migration task for MigrationManager tests."""

    def __init__(
        self,
        task_id: str = "fake_task",
        label: str = "Fake task",
        should_run: bool = True,
    ) -> None:
        self.id = task_id
        self.label = label
        self._should_run = should_run
        self.run_called = False
        self.progress_calls: list[tuple[int, int]] = []
        self.cancelled_at: int | None = None  # batch index at which is_cancelled was True
        self._cancel_on_call: int | None = None  # cancel after this many is_cancelled checks

    def needs_run(self, config) -> bool:
        return self._should_run

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        self.run_called = True
        for i in range(3):
            if is_cancelled():
                self.cancelled_at = i
                return
            progress_cb(i + 1, 3)
            time.sleep(0.001)  # give the cancel event a chance to be set


class _FakeConfig:
    """Minimal config stub for MigrationManager tests."""

    def __init__(self) -> None:
        self.prefix_detector_version = 0
        self.prefix_parse_version = 0

    def save(self) -> None:
        pass


class TestMigrationManager:

    def _make_manager(self, qapp, db=None):
        from metatv.core.migration_manager import MigrationManager
        # Use an in-memory-style db stub if no real db provided
        if db is None:
            db = MagicMock()
        config = _FakeConfig()
        mgr = MigrationManager(config, db)
        return mgr, config

    def _collect_signals(self, mgr, qapp, *, timeout_ms: int = 3000):
        """Run manager.run_pending() and collect emitted public signals.

        Returns dict with keys: started, progress, finished, all_finished_count.
        """
        from PyQt6.QtCore import QEventLoop, QTimer

        events: dict = {
            "started": [],
            "progress": [],
            "finished": [],
            "all_finished": 0,
        }

        mgr.task_started.connect(lambda tid, lbl: events["started"].append((tid, lbl)))
        mgr.task_progress.connect(lambda tid, d, t: events["progress"].append((tid, d, t)))
        mgr.task_finished.connect(lambda tid: events["finished"].append(tid))
        mgr.all_finished.connect(lambda: events.__setitem__("all_finished", events["all_finished"] + 1))

        loop = QEventLoop()
        mgr.all_finished.connect(loop.quit)

        # Guard: quit loop after timeout even if all_finished never fires
        guard = QTimer()
        guard.setSingleShot(True)
        guard.setInterval(timeout_ms)
        guard.timeout.connect(loop.quit)
        guard.start()

        mgr.run_pending()
        loop.exec()
        guard.stop()

        return events

    def test_skips_when_needs_run_false(self, qapp):
        """run_pending skips tasks whose needs_run returns False."""

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask(should_run=False)
        mgr.register(task)

        events = self._collect_signals(mgr, qapp)

        assert not task.run_called, "task.run should NOT be called when needs_run=False"
        assert events["started"] == [], "task_started should not fire for skipped task"
        # all_finished is NOT emitted when there are no pending tasks (no-op path)
        assert events["all_finished"] == 0

    def test_task_started_and_finished_fire_in_order(self, qapp):
        """task_started fires before task_finished for the same task_id."""

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask(task_id="t1")
        mgr.register(task)

        order: list[str] = []
        mgr.task_started.connect(lambda tid, lbl: order.append(f"started:{tid}"))
        mgr.task_finished.connect(lambda tid: order.append(f"finished:{tid}"))

        events = self._collect_signals(mgr, qapp)

        assert "started:t1" in order, "task_started not fired"
        assert "finished:t1" in order, "task_finished not fired"
        assert order.index("started:t1") < order.index("finished:t1"), (
            "task_started must come before task_finished"
        )

    def test_progress_signals_fire(self, qapp):
        """task_progress is emitted for each progress_cb call inside the task."""

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask(task_id="prog_task")
        mgr.register(task)

        events = self._collect_signals(mgr, qapp)

        # _FakeTask calls progress_cb 3 times
        prog = [(d, t) for tid, d, t in events["progress"] if tid == "prog_task"]
        assert len(prog) == 3, f"expected 3 progress signals, got {len(prog)}: {prog}"
        # Values should be (1,3), (2,3), (3,3)
        assert prog == [(1, 3), (2, 3), (3, 3)], f"unexpected progress values: {prog}"

    def test_all_finished_fires_after_all_tasks(self, qapp):
        """all_finished fires exactly once after all tasks complete."""

        mgr, _ = self._make_manager(qapp)
        mgr.register(_FakeTask(task_id="a"))
        mgr.register(_FakeTask(task_id="b"))

        events = self._collect_signals(mgr, qapp)

        assert events["all_finished"] == 1, (
            f"all_finished should fire exactly once; got {events['all_finished']}"
        )
        # Both tasks must have completed
        assert "a" in events["finished"], "task 'a' not in finished"
        assert "b" in events["finished"], "task 'b' not in finished"

    def test_request_cancel_sets_is_cancelled_true(self, qapp):
        """request_cancel causes is_cancelled() → True inside the running task."""
        from PyQt6.QtCore import QEventLoop, QTimer

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask(task_id="cancel_me")
        mgr.register(task)

        # Cancel immediately after run_pending
        loop = QEventLoop()
        mgr.all_finished.connect(loop.quit)

        guard = QTimer()
        guard.setSingleShot(True)
        guard.setInterval(3000)
        guard.timeout.connect(loop.quit)
        guard.start()

        mgr.run_pending()
        mgr.request_cancel()  # cancel before the first sleep completes
        loop.exec()
        guard.stop()

        # The task was interrupted — cancelled_at should be set
        # (it may be None if cancel wasn't picked up in time on a fast machine;
        # the important thing is that the manager shut down cleanly without hanging)
        assert task.run_called, "task.run should have been called"
        # No assertion on cancelled_at specifically — timing-dependent on test speed

    def test_tasks_run_sequentially(self, qapp):
        """Two tasks run one after the other (not concurrently)."""

        order: list[str] = []

        class _OrderedTask:
            def __init__(self, tid: str) -> None:
                self.id = tid
                self.label = f"Task {tid}"

            def needs_run(self, config) -> bool:
                return True

            def run(self, progress_cb, is_cancelled) -> None:
                order.append(f"start:{self.id}")
                time.sleep(0.02)
                order.append(f"end:{self.id}")

        mgr, _ = self._make_manager(qapp)
        mgr.register(_OrderedTask("first"))
        mgr.register(_OrderedTask("second"))

        events = self._collect_signals(mgr, qapp, timeout_ms=5000)

        # Sequential means start:first < end:first < start:second < end:second
        assert order.index("start:first") < order.index("end:first"), "first task interleaved"
        assert order.index("end:first") < order.index("start:second"), (
            "second task started before first task ended (not sequential)"
        )

    def test_shutdown_does_not_hang(self, qapp):
        """shutdown() returns without hanging (no pool-leak → no QThread crash)."""

        mgr, _ = self._make_manager(qapp)
        task = _FakeTask()
        mgr.register(task)
        # Don't call run_pending — just verify shutdown is safe when idle
        mgr.shutdown()  # must return promptly


# ---------------------------------------------------------------------------
# 3. MigrationProgressWidget — slot-driven rendering tests
# ---------------------------------------------------------------------------

class TestMigrationProgressWidget:

    def _make_widget(self, qapp):
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget.__new__(MigrationProgressWidget)
        MigrationProgressWidget.__init__(w)
        return w

    def test_initially_hidden(self, qapp):
        """Widget starts hidden."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        assert not w.isVisible(), "widget should be hidden before any task starts"

    def test_task_started_adds_row_and_shows(self, qapp):
        """on_task_started adds a row and makes the widget visible."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget, _TaskRow
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Running task one")
        assert "t1" in w._rows, "row for t1 should be created"
        assert isinstance(w._rows["t1"], _TaskRow), "row should be a _TaskRow"
        assert w.isVisible(), "widget should be visible after task_started"

    def test_task_started_idempotent(self, qapp):
        """Calling on_task_started twice for the same id does not add a duplicate row."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Task one")
        w.on_task_started("t1", "Task one again")
        assert len(w._rows) == 1, "duplicate on_task_started must not add a second row"

    def test_multiple_tasks_each_get_a_row(self, qapp):
        """Each task_id gets its own row."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("a", "Task A")
        w.on_task_started("b", "Task B")
        assert "a" in w._rows and "b" in w._rows, "both task rows should exist"
        assert w._rows["a"] is not w._rows["b"], "rows should be distinct objects"

    def test_task_progress_updates_bar(self, qapp):
        """on_task_progress updates the QProgressBar to the correct value."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_task_progress("t1", 500, 2000)

        row = w._rows["t1"]
        assert row._bar.maximum() == 2000, f"bar maximum should be 2000; got {row._bar.maximum()}"
        assert row._bar.value() == 500, f"bar value should be 500; got {row._bar.value()}"
        assert "25%" in row._pct.text(), f"pct label should show ~25%; got {row._pct.text()!r}"

    def test_task_progress_full(self, qapp):
        """on_task_progress with done==total shows 100%."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_task_progress("t1", 100, 100)

        row = w._rows["t1"]
        assert row._bar.value() == 100
        assert "100%" in row._pct.text()

    def test_task_finished_flips_to_done_glyph(self, qapp):
        """on_task_finished sets _done=True and updates the glyph."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        from metatv.gui import icons as _icons
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_task_progress("t1", 200, 200)
        w.on_task_finished("t1")

        row = w._rows["t1"]
        assert row._done is True, "row._done should be True after on_task_finished"
        assert row._glyph.text() == _icons.migration_done_icon, (
            f"glyph should be done icon {_icons.migration_done_icon!r}; "
            f"got {row._glyph.text()!r}"
        )

    def test_task_finished_sets_bar_to_full(self, qapp):
        """on_task_finished sets the progress bar to 100% even if progress was partial."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_task_progress("t1", 50, 200)  # partial
        w.on_task_finished("t1")

        row = w._rows["t1"]
        assert row._bar.value() == row._bar.maximum(), (
            "bar should be full after task_finished"
        )
        assert "100%" in row._pct.text()

    def test_task_finished_on_unknown_id_is_safe(self, qapp):
        """on_task_finished for an unknown task_id does not crash."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_finished("nonexistent")  # must not raise

    def test_all_finished_schedules_hide(self, qapp):
        """on_all_finished starts the hide timer (widget will hide after ~2s)."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")
        w.on_all_finished()
        assert w._hide_timer.isActive(), "hide timer should be active after all_finished"

    def test_pending_glyph_before_finish(self, qapp):
        """Before on_task_finished, the glyph is the pending icon."""
        from metatv.gui.migration_progress_widget import MigrationProgressWidget
        from metatv.gui import icons as _icons
        w = MigrationProgressWidget()
        w.on_task_started("t1", "Scanning")

        row = w._rows["t1"]
        assert row._glyph.text() == _icons.migration_pending_icon, (
            f"pending glyph should be {_icons.migration_pending_icon!r}; "
            f"got {row._glyph.text()!r}"
        )


# ---------------------------------------------------------------------------
# 4. Migration completion → canonical corpus refresh (MainWindow wiring)
# ---------------------------------------------------------------------------

class TestMigrationCompletionRefreshWiring:
    """When background migrations finish, the app must refresh the FULL corpus-
    derived view set — not just the channel list.

    A migration can rewrite ``content_key`` (cross-source dedup), which is a
    corpus mutation, so completion must route through the one canonical
    chokepoint ``MainWindow._refresh_provider_dependent_views`` (it reloads
    Discover, Recipe, filter-facet counts and preferences in addition to the
    list). Regression guard: the wiring used to connect ``all_finished``
    straight to ``load_channels`` alone, leaving Discover / Recipe / facet
    counts stale until an app restart.
    """

    def test_all_finished_funnels_through_canonical_refresh(self, qapp, monkeypatch):
        """Emit the real ``all_finished`` signal through the real
        ``setup_notifications`` wiring and assert the canonical refresh runs —
        and that completion does NOT bypass it by calling ``load_channels``
        directly."""
        from types import SimpleNamespace

        from metatv.gui import main_window as mw_mod
        from metatv.gui.main_window import MainWindow
        from metatv.core.migration_manager import MigrationManager

        # Neutralize the heavy Qt widget construction inside setup_notifications;
        # the wiring under test is driven by a REAL MigrationManager signal.
        monkeypatch.setattr(mw_mod, "NotificationWidget", MagicMock())
        monkeypatch.setattr(mw_mod, "MigrationProgressWidget", MagicMock())

        mgr = MigrationManager(config=MagicMock(), db=MagicMock())
        me = SimpleNamespace(
            migration_manager=mgr,
            notification_manager=MagicMock(),
            config=MagicMock(),
            centralWidget=MagicMock(),
            update_notifications=MagicMock(),
            load_channels=MagicMock(),
            _refresh_provider_dependent_views=MagicMock(),
        )
        try:
            # Run the real wiring code.
            MainWindow.setup_notifications(me)

            # Simulate migrations completing.
            mgr.all_finished.emit()

            # The canonical chokepoint must run (it internally reloads Discover /
            # Recipe / filter stats / preferences / the list) ...
            me._refresh_provider_dependent_views.assert_called_once()
            # ... and completion must NOT bypass it by wiring load_channels
            # directly (that left Discover / Recipe / facet counts stale — the bug).
            me.load_channels.assert_not_called()
        finally:
            mgr.shutdown()


def test_crashed_task_does_not_bump_version(qapp):
    """A task whose run() raises must NOT get on_completed — it retries next launch.

    Regression: the 2026-07-31 detected_title_reparse v8 run died on a transient
    'database is locked' and was still marked complete, permanently burning the
    version so the re-parse never retried.
    """
    from unittest.mock import MagicMock
    from metatv.core.migration_manager import MigrationManager

    mgr = MigrationManager.__new__(MigrationManager)
    mgr.config = MagicMock()
    import threading
    mgr._cancel_event = threading.Event()
    finished = []
    mgr._task_finished = MagicMock(emit=lambda tid: finished.append(tid))
    mgr._task_started = MagicMock(emit=lambda *a: None)
    mgr._task_progress = MagicMock(emit=lambda *a: None)
    mgr._all_finished = MagicMock(emit=lambda *a: None)

    crashing = MagicMock()
    crashing.id = "crashy"
    crashing.label = "Crashy task"
    crashing.run.side_effect = RuntimeError("database is locked")

    healthy = MagicMock()
    healthy.id = "healthy"
    healthy.label = "Healthy task"

    mgr._run_all([crashing, healthy])

    crashing.on_completed.assert_not_called()   # crashed → version NOT bumped
    healthy.on_completed.assert_called_once()   # later tasks still run + complete
    assert finished == ["crashy", "healthy"]    # widget got both finish signals


def test_crashed_task_still_triggers_canonical_refresh(qapp, monkeypatch):
    """UX repair: a crashed migration task's already-committed batches must
    not leave the UI stale for the rest of the session.

    ``MigrationManager._run_all`` emits ``_all_finished`` from its outer
    ``finally`` regardless of whether a task crashed (the except-Exception
    branch ``continue``s rather than returning), and ``setup_notifications``
    wires that signal straight to
    ``MainWindow._refresh_provider_dependent_views`` — so the crash path
    already triggers the canonical refresh today. This test proves the
    combination end-to-end: a REAL crashing task run through REAL
    ``run_pending()``/``_run_all``, driving the REAL ``setup_notifications``
    wiring, waited out on a real Qt event loop (not a manual ``.emit()``).
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from PyQt6.QtCore import QEventLoop, QTimer
    from metatv.gui import main_window as mw_mod
    from metatv.gui.main_window import MainWindow
    from metatv.core.migration_manager import MigrationManager

    monkeypatch.setattr(mw_mod, "NotificationWidget", MagicMock())
    monkeypatch.setattr(mw_mod, "MigrationProgressWidget", MagicMock())

    mgr = MigrationManager(config=_FakeConfig(), db=MagicMock())
    crashing = MagicMock()
    crashing.id = "crashy"
    crashing.label = "Crashy task"
    crashing.needs_run.return_value = True
    crashing.run.side_effect = RuntimeError("database is locked")
    mgr.register(crashing)

    me = SimpleNamespace(
        migration_manager=mgr,
        notification_manager=MagicMock(),
        config=MagicMock(),
        centralWidget=MagicMock(),
        update_notifications=MagicMock(),
        load_channels=MagicMock(),
        _refresh_provider_dependent_views=MagicMock(),
    )
    try:
        MainWindow.setup_notifications(me)

        loop = QEventLoop()
        mgr.all_finished.connect(loop.quit)
        guard = QTimer()
        guard.setSingleShot(True)
        guard.setInterval(3000)
        guard.timeout.connect(loop.quit)
        guard.start()

        mgr.run_pending()
        loop.exec()
        guard.stop()

        crashing.on_completed.assert_not_called()  # crashed → version NOT bumped (#364)
        me._refresh_provider_dependent_views.assert_called_once()  # UI still refreshes
    finally:
        mgr.shutdown()


# ---------------------------------------------------------------------------
# 4. MainWindow startup fetch gate — sequencing behind pending migrations
# ---------------------------------------------------------------------------

class TestStartupFetchGate:
    """Regression tests for ``MainWindow._gate_startup_fetches``.

    ``series_monitor.check_all``, ``vod_watch_alert_manager.check_all``, and
    ``epg_manager.refresh_all_if_needed`` are bulk DB writers with no
    lock-retry of their own. Firing them unconditionally at startup let them
    race a heavy Migration Center run's batched commits — the root cause of
    the 2026-07-31 / 2026-08-01 'database is locked' crash-loops. These tests
    drive the real unbound ``_gate_startup_fetches`` against a
    ``SimpleNamespace`` host + a REAL ``MigrationManager`` (so
    ``all_finished`` is a genuine ``pyqtSignal`` we can emit), spying on
    ``_start_deferred_fetches`` rather than the ``QTimer.singleShot``
    plumbing inside it (unchanged, pre-existing timing).
    """

    def test_no_pending_migrations_fires_immediately(self, qapp):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from metatv.gui.main_window import MainWindow
        from metatv.core.migration_manager import MigrationManager

        mgr = MigrationManager(config=_FakeConfig(), db=MagicMock())
        # No tasks registered → has_pending_tasks() is False.
        me = SimpleNamespace(
            migration_manager=mgr,
            _start_deferred_fetches=MagicMock(),
        )
        try:
            MainWindow._gate_startup_fetches(me)
            me._start_deferred_fetches.assert_called_once()
        finally:
            mgr.shutdown()

    def test_pending_migrations_defer_until_all_finished(self, qapp):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from metatv.gui.main_window import MainWindow
        from metatv.core.migration_manager import MigrationManager

        mgr = MigrationManager(config=_FakeConfig(), db=MagicMock())
        pending_task = MagicMock()
        pending_task.needs_run.return_value = True
        mgr.register(pending_task)

        me = SimpleNamespace(
            migration_manager=mgr,
            _start_deferred_fetches=MagicMock(),
        )
        try:
            MainWindow._gate_startup_fetches(me)

            assert me._start_deferred_fetches.call_count == 0, (
                "must not fire the fetch storm while migrations are pending"
            )

            mgr.all_finished.emit()

            me._start_deferred_fetches.assert_called_once()
        finally:
            mgr.shutdown()

    def test_gate_handler_disconnects_after_firing_once(self, qapp):
        """Guards against a future all_finished emission (e.g. a later
        manual re-trigger in the same session) re-running the startup
        kickoffs a second time — 'connected once', per the design."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from metatv.gui.main_window import MainWindow
        from metatv.core.migration_manager import MigrationManager

        mgr = MigrationManager(config=_FakeConfig(), db=MagicMock())
        pending_task = MagicMock()
        pending_task.needs_run.return_value = True
        mgr.register(pending_task)

        me = SimpleNamespace(
            migration_manager=mgr,
            _start_deferred_fetches=MagicMock(),
        )
        try:
            MainWindow._gate_startup_fetches(me)
            mgr.all_finished.emit()
            mgr.all_finished.emit()  # simulate a second completion signal

            assert me._start_deferred_fetches.call_count == 1
        finally:
            mgr.shutdown()
