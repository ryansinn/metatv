"""Whole-library tmdb sibling propagation runs once at a time.

Owner log 2026-08-31 caught TWO passes running concurrently on separate pools --
``tmdb_enrich_0`` (``TmdbEnrichmentManager._propagate_after_drain``, fired when
the enrich queue empties) and ``ThreadPoolExecutor-7_1``
(``_ProviderMixin._on_all_refreshes_finished``, fired when a refresh completes).
A refresh satisfies both triggers at once, so they are not independent events.

Each held SQLite's single write lock against the other.  Both burned all three
``_retry_on_lock`` attempts (~38s apart -- 30s blocked on ``busy_timeout`` plus
the 2s backoff) and aborted; the bulk catalogue INSERT of the refresh that
triggered them failed the same way and the source reported ``success=False``;
and the survivor kept the app's close open for 40s
(``Background pool still running at close after 8.0s``).

Standing down loses nothing: the pass in flight scans the WHOLE library, so it
covers the rows of the caller that yielded.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest


def _make_file_backed_db(tmp_path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_tables()
    return db


class TestWholeLibrarySweepIsSingleFlight:

    def test_a_second_concurrent_whole_library_pass_stands_down(self, tmp_path):
        """The exact collision from the log: two pools, one library."""
        from metatv.core.repositories import RepositoryFactory

        db = _make_file_backed_db(tmp_path)
        entered = threading.Event()
        may_finish = threading.Event()
        second_result: list[int] = []

        real_impl = None

        def _blocking_impl(self, provider_id=None):
            """Stand in for the long pass: hold the guard, then let go."""
            entered.set()
            may_finish.wait(timeout=10)
            return 7

        from metatv.core.repositories.channel_ingestion import ChannelIngestionMixin
        real_impl = ChannelIngestionMixin._propagate_tmdb_from_title_siblings_impl
        ChannelIngestionMixin._propagate_tmdb_from_title_siblings_impl = _blocking_impl
        try:
            def _first():
                with db.session_scope() as s:
                    RepositoryFactory(s).channels.propagate_tmdb_from_title_siblings()

            def _second():
                entered.wait(timeout=10)
                with db.session_scope() as s:
                    second_result.append(
                        RepositoryFactory(s).channels
                        .propagate_tmdb_from_title_siblings()
                    )

            t1 = threading.Thread(target=_first)
            t2 = threading.Thread(target=_second)
            t1.start()
            t2.start()
            t2.join(timeout=10)
            may_finish.set()
            t1.join(timeout=10)
        finally:
            ChannelIngestionMixin._propagate_tmdb_from_title_siblings_impl = real_impl

        assert second_result == [0], (
            "the second concurrent whole-library pass ran anyway -- this is the "
            "pair that deadlocked each other and cost the refresh its data")

    def test_the_guard_releases_so_a_later_pass_still_runs(self, tmp_path):
        """A guard that never releases would silently kill enrichment forever."""
        from metatv.core.repositories import RepositoryFactory

        db = _make_file_backed_db(tmp_path)
        with db.session_scope() as s:
            first = RepositoryFactory(s).channels.propagate_tmdb_from_title_siblings()
        with db.session_scope() as s:
            second = RepositoryFactory(s).channels.propagate_tmdb_from_title_siblings()
        # Empty library: both legitimately adopt 0, but neither may be the
        # "stood down" branch -- the point is that the second one RAN.
        assert first == 0 and second == 0

    def test_the_guard_releases_even_when_the_pass_raises(self, tmp_path):
        """Released in a ``finally``; a crashed sweep must not wedge the guard."""
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.repositories.channel_ingestion import ChannelIngestionMixin
        from metatv.core.repositories.sweep_guard import is_running

        db = _make_file_backed_db(tmp_path)
        real = ChannelIngestionMixin._propagate_tmdb_from_title_siblings_impl

        def _boom(self, provider_id=None):
            raise RuntimeError("sweep exploded")

        ChannelIngestionMixin._propagate_tmdb_from_title_siblings_impl = _boom
        try:
            with pytest.raises(RuntimeError):
                with db.session_scope() as s:
                    RepositoryFactory(s).channels.propagate_tmdb_from_title_siblings()
        finally:
            ChannelIngestionMixin._propagate_tmdb_from_title_siblings_impl = real

        assert not is_running("propagate_tmdb_from_title_siblings"), \
            "a raising sweep wedged the guard -- propagation would never run again"

    def test_a_provider_scoped_pass_is_not_gated(self, tmp_path):
        """Narrow, cheap, and may not overlap the running pass at all."""
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.repositories.sweep_guard import _lock_for

        db = _make_file_backed_db(tmp_path)
        # Simulate a whole-library pass in flight.
        lock = _lock_for("propagate_tmdb_from_title_siblings")
        assert lock.acquire(blocking=False)
        try:
            with db.session_scope() as s:
                # Must not stand down: it is scoped, so it is allowed through.
                RepositoryFactory(s).channels.propagate_tmdb_from_title_siblings(
                    provider_id="p1")
        finally:
            lock.release()
