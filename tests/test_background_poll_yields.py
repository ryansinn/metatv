"""A background poll must never outrank work the user asked for.

Root cause, owner log 2026-08-31.  ``get_series_info`` on the owner's provider
slowed from ~300ms to ~11s (``latency=10787ms``).  Nothing about the code or the
write sizes changed -- both bulk writers were already chunked (500 rows/commit
in ``provider_loader``, one commit per 2000-row page in the tmdb sweep), and the
app had run for months against a 1M+ row database.  What changed was DURATION:
21 monitored series x 3 mirrors x 11s stretched one pass from ~20 seconds to
~11 minutes, so a poll that used to finish in a gap now overlapped everything.

Two faces, one cause:

1. **Playback died silently.**  The provider account allows ONE connection.  The
   poll held it continuously while mpv streamed from the same host; the provider
   dropped the STREAM and mpv (``--keep-open=no --idle=once``) exited with no
   error surfaced -- the window opened and vanished.  The poll was invisible to
   :class:`ConnectionAccountant`, the component that exists to arbitrate exactly
   this, so nothing could intervene.

2. **A refresh lost its data.**  The bulk catalogue INSERT waited the full
   ``busy_timeout`` (params stamped 22:22:54.968, failed 22:23:25.010 = 30.04s)
   and the source reported ``success=False``.

These tests pin the arbitration, and each FAILS on the pre-fix tree: before this
change ``MONITOR_KIND`` did not exist and the poll took no slot at all.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_file_backed_db(tmp_path: Path):
    """Create a file-backed Database with tables (NOT :memory:)."""
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_tables()
    return db


def _make_provider_db(session, provider_id: str = "p1", name: str = "ProSat"):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id, name=name, type="xtream",
        url="http://test.example.com",
        urls='[{"url": "http://test.example.com", "primary": true}]',
        username="user", password="pass", is_active=True,
    )
    session.add(p)
    session.flush()
    return p


class TestEveryRealConsumerOutranksAPoll:
    """The poll yields to playback, downloads and recordings -- never the reverse."""

    def test_playback_evicts_a_poll_holding_the_only_connection(self):
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.player_manager import PLAYBACK_PREEMPTS
        from metatv.core.series_monitor import MONITOR_KIND, MONITOR_PREEMPTS

        acct = ConnectionAccountant(capacity_resolver=lambda pid: 1)
        assert acct.acquire("p1", MONITOR_KIND, "poll-1",
                            preempt_kinds=MONITOR_PREEMPTS).granted

        # This is the exact moment that failed: mpv asks while the poll holds.
        assert acct.acquire("p1", "playback", "play-1",
                            preempt_kinds=PLAYBACK_PREEMPTS).granted, \
            "playback must evict a background poll, not lose the stream to it"

    def test_download_evicts_a_poll(self):
        """Guards the regression enrolling the poll nearly introduced.

        ``download_manager`` acquired with NO ``preempt_kinds``, so making the
        poll a first-class holder without also giving downloads a preempt list
        would have let a catch-up poll block a download the user asked for.
        """
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.download_manager import DOWNLOAD_PREEMPTS
        from metatv.core.series_monitor import MONITOR_KIND, MONITOR_PREEMPTS

        acct = ConnectionAccountant(capacity_resolver=lambda pid: 1)
        acct.acquire("p1", MONITOR_KIND, "poll-1", preempt_kinds=MONITOR_PREEMPTS)
        assert acct.acquire("p1", "download", "dl-1",
                            preempt_kinds=DOWNLOAD_PREEMPTS).granted

    def test_recording_evicts_a_poll_even_when_polite(self):
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.recording_manager import (
            RECORDING_PREEMPTS, _POLITE_PREEMPTS)
        from metatv.core.series_monitor import MONITOR_KIND, MONITOR_PREEMPTS

        for preempts in (RECORDING_PREEMPTS, _POLITE_PREEMPTS):
            acct = ConnectionAccountant(capacity_resolver=lambda pid: 1)
            acct.acquire("p1", MONITOR_KIND, "poll-1",
                         preempt_kinds=MONITOR_PREEMPTS)
            assert acct.acquire("p1", "recording", "rec-1",
                                preempt_kinds=preempts).granted, \
                f"a recording must outrank a poll (preempts={preempts})"

    def test_a_poll_displaces_nothing(self):
        """``MONITOR_PREEMPTS`` is empty by design: a poll is always the loser."""
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.player_manager import PLAYBACK_PREEMPTS
        from metatv.core.series_monitor import MONITOR_KIND, MONITOR_PREEMPTS

        assert MONITOR_PREEMPTS == ()
        acct = ConnectionAccountant(capacity_resolver=lambda pid: 1)
        acct.acquire("p1", "playback", "play-1", preempt_kinds=PLAYBACK_PREEMPTS)
        assert not acct.acquire("p1", MONITOR_KIND, "poll-1",
                                preempt_kinds=MONITOR_PREEMPTS).granted, \
            "a poll must never evict a stream"


class TestPollSkipsTheFetchWhenTheConnectionIsBusy:
    """The behavioural case: no HTTP is issued while playback holds the slot.

    Asserting the accountant's bookkeeping alone would pass even if the poll
    ignored the verdict and fetched anyway -- which is precisely the bug.  This
    drives the real worker and asserts the fetch never happened.
    """

    def _entry(self):
        return [{
            "series_channel_id": "ch1", "source_id": "s1", "provider_id": "p1",
            "title": "EN - Dan Da Dan (2024)", "baselines": {}, "unseen_new": 0,
            "last_checked": None,
        }]

    def test_no_fetch_is_issued_while_playback_holds_the_connection(
            self, tmp_path, qapp):
        from metatv.core.config import Config
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.player_manager import PLAYBACK_PREEMPTS
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = Config(config_dir=tmp_path / "cfg")
        with db.session_scope() as session:
            _make_provider_db(session, "p1")

        acct = ConnectionAccountant(capacity_resolver=lambda pid: 1)
        # mpv is streaming: it owns the account's only connection.
        assert acct.acquire("p1", "playback", "play-1",
                            preempt_kinds=PLAYBACK_PREEMPTS).granted

        mgr = SeriesMonitorManager(db, cfg, notifications=None,
                                   connection_accountant=acct)
        with patch("metatv.providers.factory.get_provider") as get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as run:
            get_provider.return_value = MagicMock()
            run.return_value = {"episodes": {"1": [{"info": {}}]}}
            mgr._worker_check_entries(self._entry())

        assert run.call_count == 0, (
            "the poll issued a live fetch while playback held the provider's "
            "only connection -- this is what killed the stream")

    def test_the_fetch_does_happen_once_the_connection_is_free(
            self, tmp_path, qapp):
        """The mirror of the above: the guard must not simply disable polling."""
        from metatv.core.config import Config
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = Config(config_dir=tmp_path / "cfg")
        with db.session_scope() as session:
            _make_provider_db(session, "p1")

        mgr = SeriesMonitorManager(
            db, cfg, notifications=None,
            connection_accountant=ConnectionAccountant(
                capacity_resolver=lambda pid: 1),
        )
        with patch("metatv.providers.factory.get_provider") as get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as run:
            get_provider.return_value = MagicMock()
            run.return_value = {"episodes": {"1": [{"info": {}}]}}
            mgr._worker_check_entries(self._entry())

        assert run.call_count == 1, "an idle provider must still be polled"

    def test_the_slot_is_released_so_the_next_pass_can_run(self, tmp_path, qapp):
        """A leaked slot would silently stop all future polling."""
        from metatv.core.config import Config
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = Config(config_dir=tmp_path / "cfg")
        with db.session_scope() as session:
            _make_provider_db(session, "p1")

        acct = ConnectionAccountant(capacity_resolver=lambda pid: 1)
        mgr = SeriesMonitorManager(db, cfg, notifications=None,
                                   connection_accountant=acct)
        with patch("metatv.providers.factory.get_provider") as get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as run:
            get_provider.return_value = MagicMock()
            run.return_value = {"episodes": {"1": [{"info": {}}]}}
            mgr._worker_check_entries(self._entry())

        assert acct.in_use("p1") == 0, "poll leaked its connection slot"

    def test_a_raising_fetch_still_releases_the_slot(self, tmp_path, qapp):
        """The release lives in a ``finally`` -- prove it, don't assume it."""
        from metatv.core.config import Config
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = Config(config_dir=tmp_path / "cfg")
        with db.session_scope() as session:
            _make_provider_db(session, "p1")

        acct = ConnectionAccountant(capacity_resolver=lambda pid: 1)
        mgr = SeriesMonitorManager(db, cfg, notifications=None,
                                   connection_accountant=acct)
        with patch("metatv.providers.factory.get_provider") as get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as run:
            get_provider.return_value = MagicMock()
            run.side_effect = OSError("provider timed out")
            mgr._worker_check_entries(self._entry())

        assert acct.in_use("p1") == 0, \
            "a failed fetch leaked the slot -- one bad host would end all polling"

    def test_an_unwired_monitor_still_polls(self, tmp_path, qapp):
        """No accountant (headless/unit) must not turn the poll into a no-op."""
        from metatv.core.config import Config
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = Config(config_dir=tmp_path / "cfg")
        with db.session_scope() as session:
            _make_provider_db(session, "p1")

        mgr = SeriesMonitorManager(db, cfg, notifications=None)
        with patch("metatv.providers.factory.get_provider") as get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as run:
            get_provider.return_value = MagicMock()
            run.return_value = {"episodes": {"1": [{"info": {}}]}}
            mgr._worker_check_entries(self._entry())

        assert run.call_count == 1
