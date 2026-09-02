"""History group clear: instant delete + Undo toast, never a confirmation dialog.

The per-group History trash used to route through ``_confirm_and_clear_history``
— a QMessageBox "Are you sure?" — the same as the two big clears. The owner
settled: for the PER-GROUP clear only, drop the confirmation entirely. It
purges at once and offers Undo in a toast instead; the two big clears
("older than 30 days", "clear all") are untouched and keep asking.

This file covers two layers:

* ``core/repositories/channel_history.py`` — ``clear_history_in_range`` now
  snapshots the rows it is about to clear, and ``restore_history_snapshot``
  undoes that, but ONLY for rows nobody has re-played since (the hard
  requirement: Undo must never move history backwards).
* ``gui/main_window_history.py`` — ``clear_history_group`` shows no dialog,
  clears immediately, and the toast's Undo action really restores.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories.channel import ChannelRepository

NOW = datetime(2026, 9, 2, 20, 0, 0)


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'history_undo.db'}")
    d.create_tables()
    with d.session_scope() as s:
        s.add(ProviderDB(id="p", name="P", type="xtream",
                         url="http://example.invalid", is_active=True))
    yield d
    d.close()


def _seed_channel(session, cid: str, played, play_count: int = 3) -> None:
    session.add(ChannelDB(
        id=cid, source_id=cid, provider_id="p", name=cid,
        media_type="movie", detected_title=cid,
        last_played=played, play_count=play_count,
    ))


# ---------------------------------------------------------------------------
# 1. clear_history_in_range returns the snapshot of exactly the cleared rows
# ---------------------------------------------------------------------------

class TestSnapshotOnClear:

    def test_snapshot_covers_exactly_the_cleared_rows(self, db):
        window_start = NOW - timedelta(hours=1)
        window_end = NOW
        with db.session_scope() as s:
            _seed_channel(s, "in1", NOW - timedelta(minutes=10), play_count=5)
            _seed_channel(s, "in2", NOW - timedelta(minutes=20), play_count=2)
            _seed_channel(s, "in3", NOW - timedelta(minutes=30), play_count=1)
            _seed_channel(s, "outside", NOW - timedelta(days=2), play_count=9)

        with db.session_scope() as s:
            count, snapshot = ChannelRepository(s).clear_history_in_range(
                window_start, window_end
            )

        assert count == 3
        snap = {row[0]: row for row in snapshot}
        assert set(snap) == {"in1", "in2", "in3"}, (
            "snapshot must cover exactly the cleared rows, no more, no less"
        )
        assert snap["in1"][1] == NOW - timedelta(minutes=10)
        assert snap["in1"][2] == 5
        assert snap["in2"][2] == 2
        assert snap["in3"][2] == 1

        with db.session_scope(commit=False) as s:
            outside = s.query(ChannelDB).filter_by(id="outside").one()
            assert outside.last_played == NOW - timedelta(days=2), (
                "the row outside the window was untouched"
            )
            assert outside.play_count == 9

            for cid in ("in1", "in2", "in3"):
                row = s.query(ChannelDB).filter_by(id=cid).one()
                assert row.last_played is None
                assert row.play_count == 0


# ---------------------------------------------------------------------------
# 2 + 3. restore_history_snapshot, and the re-play guard
# ---------------------------------------------------------------------------

class TestRestoreSnapshot:

    def test_restore_puts_last_played_and_play_count_back(self, db):
        with db.session_scope() as s:
            _seed_channel(s, "a", NOW - timedelta(minutes=5), play_count=4)

        with db.session_scope() as s:
            count, snapshot = ChannelRepository(s).clear_history_in_range(
                NOW - timedelta(hours=1), NOW
            )
        assert count == 1

        with db.session_scope() as s:
            restored = ChannelRepository(s).restore_history_snapshot(snapshot)
        assert restored == 1

        with db.session_scope(commit=False) as s:
            row = s.query(ChannelDB).filter_by(id="a").one()
            assert row.last_played == NOW - timedelta(minutes=5)
            assert row.play_count == 4

    def test_a_replay_during_the_toast_is_never_overwritten(self, db):
        """The hard requirement: Undo must never move history backwards.

        A channel re-played while the toast is still on screen already has a
        newer ``last_played`` than the snapshot remembers. Restoring it
        anyway would silently erase the re-play, which is worse than doing
        nothing — so that row must be skipped, and only the untouched row
        counted as restored.
        """
        with db.session_scope() as s:
            _seed_channel(s, "replayed", NOW - timedelta(minutes=5), play_count=4)
            _seed_channel(s, "untouched", NOW - timedelta(minutes=8), play_count=2)

        with db.session_scope() as s:
            count, snapshot = ChannelRepository(s).clear_history_in_range(
                NOW - timedelta(hours=1), NOW
            )
        assert count == 2

        # Simulate a re-play during the toast's lifetime.
        replay_time = NOW + timedelta(minutes=1)
        with db.session_scope() as s:
            row = s.query(ChannelDB).filter_by(id="replayed").one()
            row.last_played = replay_time
            row.play_count = 1

        with db.session_scope() as s:
            restored = ChannelRepository(s).restore_history_snapshot(snapshot)

        assert restored == 1, (
            "only the untouched row should be counted as restored"
        )

        with db.session_scope(commit=False) as s:
            replayed = s.query(ChannelDB).filter_by(id="replayed").one()
            untouched = s.query(ChannelDB).filter_by(id="untouched").one()

            assert replayed.last_played == replay_time, (
                "the re-play was overwritten by the older snapshot value"
            )
            assert replayed.play_count == 1
            assert untouched.last_played == NOW - timedelta(minutes=8)
            assert untouched.play_count == 2


# ---------------------------------------------------------------------------
# 4. clear_history_group: no dialog, toast with a working Undo
# ---------------------------------------------------------------------------

def _history_mixin_host(db_obj):
    """A bare, non-Qt host with the real ``_HistoryMixin`` methods bound.

    Same shape as ``tests/conftest.py``'s ``make_channel_state_bus_host``: a
    plain class instance (never ``MainWindow.__new__()``, never a
    ``SimpleNamespace``) carrying only what ``_HistoryMixin`` actually
    touches — ``db``, ``status_bar``, ``notification_manager``,
    ``load_history``/``load_favorites``. No ``ChannelStateBus`` involvement
    here (history clears are list-membership refreshes, not per-channel
    ``publish()`` calls), so no weak-reference requirement applies.
    """
    from metatv.gui.main_window_history import _HistoryMixin

    class _Host(_HistoryMixin):
        def __init__(self, db_obj):
            self.db = db_obj
            self.status_bar = MagicMock()
            self.notification_manager = MagicMock()
            self.sidebar_sections = {}
            self.load_history = MagicMock()
            self.load_favorites = MagicMock()

    return _Host(db_obj)


class TestClearHistoryGroupInstantWithUndo:

    def test_no_confirmation_dialog_is_shown(self, db, monkeypatch):
        """A per-group clear must never call QMessageBox.question."""
        from PyQt6.QtWidgets import QMessageBox

        def _boom(*args, **kwargs):
            raise AssertionError(
                "QMessageBox.question must not be called for a per-group clear"
            )

        monkeypatch.setattr(QMessageBox, "question", _boom)

        with db.session_scope() as s:
            _seed_channel(s, "recent", datetime.now() - timedelta(minutes=5))

        host = _history_mixin_host(db)
        host.clear_history_group("hour")

        # No exception was raised above, proving QMessageBox.question was
        # never reached — and the clear still ran to completion regardless.
        with db.session_scope(commit=False) as s:
            assert s.query(ChannelDB).filter_by(id="recent").one().last_played is None

    def test_clearing_a_group_shows_a_toast_with_undo(self, db):
        with db.session_scope() as s:
            _seed_channel(s, "recent", datetime.now() - timedelta(minutes=5))

        host = _history_mixin_host(db)
        host.clear_history_group("hour")

        assert host.notification_manager.show.called, "no toast was shown"
        _, kwargs = host.notification_manager.show.call_args
        actions = kwargs.get("actions", [])
        assert any(label == "Undo" and callable(cb) for label, cb in actions), (
            "the toast has no Undo action"
        )
        assert host.load_history.called
        assert host.load_favorites.called

    def test_undo_action_restores_and_reloads(self, db):
        played_at = datetime.now() - timedelta(minutes=5)
        with db.session_scope() as s:
            _seed_channel(s, "recent", played_at, play_count=7)

        host = _history_mixin_host(db)
        host.clear_history_group("hour")

        with db.session_scope(commit=False) as s:
            assert s.query(ChannelDB).filter_by(id="recent").one().last_played is None

        _, kwargs = host.notification_manager.show.call_args
        undo_label, undo_cb = kwargs["actions"][0]
        assert undo_label == "Undo"

        host.load_history.reset_mock()
        host.load_favorites.reset_mock()
        undo_cb()

        with db.session_scope(commit=False) as s:
            row = s.query(ChannelDB).filter_by(id="recent").one()
            assert row.last_played == played_at
            assert row.play_count == 7
        assert host.load_history.called, "undo must reload history"
        assert host.load_favorites.called, "undo must reload favorites"

    def test_nothing_to_clear_shows_no_toast(self, db):
        host = _history_mixin_host(db)
        host.clear_history_group("hour")
        assert not host.notification_manager.show.called
        assert host.status_bar.showMessage.called
