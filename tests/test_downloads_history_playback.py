"""Downloads: history segments with Undo, and playing a finished download.

*Catch, Keep, Record* settled the row grammar (``test_transfer_sections.py``);
this file covers what got built ON it in the next slice — the per-group
"forget" (immediate hide + Undo toast, mirroring
``_HistoryMixin.clear_history_group`` in shape, but flipping
``DownloadDB.history_cleared`` rather than deleting the row — the Downloaded
scope reads the same rows' ``state``, so a cleared row must keep making its
channel "downloaded" while the file exists; Undo clears the flag) and DL-4
(double-click plays a finished download through
``PlayerManager.play_local_file``: no accountant slot, no URL probe, own
window under Split Streams).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from metatv.core.config import Config
from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.database import Database, DownloadDB
from metatv.core.download_manager import DownloadManager
from metatv.core.history_buckets import bucket_for
from metatv.core.repositories import RepositoryFactory
from tests.conftest import make_channel, make_downloads_mixin_host


@pytest.fixture
def env(tmp_path):
    config = Config(config_dir=tmp_path / "config")
    config.download_dir = str(tmp_path / "library")
    db = Database(f"sqlite:///{tmp_path / 'dl.db'}")
    db.create_tables()
    accountant = ConnectionAccountant(lambda _p: 1)
    manager = DownloadManager(db, config, accountant)
    return manager, db, config, accountant


def _seed_completed_download(db, *, dest, provider_id="p1") -> "tuple[str, str]":
    """Insert a matching ChannelDB + completed DownloadDB row directly.

    No real HTTP transfer needed — ``play_downloaded``/history-clear only
    read the ledger, so seeding it straight is faithful and fast.

    Returns:
        ``(download_id, channel_id)``.
    """
    with db.session_scope() as session:
        ch = make_channel(session, "Ghostbusters", provider_id=provider_id)
        channel_id = ch.id
        download_id = str(uuid.uuid4())
        session.add(DownloadDB(
            id=download_id, channel_id=channel_id, provider_id=provider_id,
            channel_name="Ghostbusters", source_url="http://x/gb.mkv",
            dest_path=str(dest), state="completed",
            downloaded_bytes=1000, total_bytes=1000,
            updated_at=datetime.utcnow(),
        ))
    return download_id, channel_id


class _FakePlayerManager:
    """Records ``play_local_file`` calls; ``connection_accountant`` is a spy."""

    def __init__(self, *, succeed: bool = True):
        self.calls: list[dict] = []
        self.connection_accountant = MagicMock()
        self._succeed = succeed

    def play_local_file(self, path, title, *, own_window):
        self.calls.append({"path": path, "title": title, "own_window": own_window})
        return self._succeed


# ── play_downloaded (DL-4) ──────────────────────────────────────────────────


@pytest.mark.parametrize("split_streams", [True, False])
def test_play_downloaded_plays_the_file_keyed_by_split_streams(env, tmp_path, split_streams):
    manager, db, config, _accountant = env
    config.split_streams_by_source = split_streams
    dest = tmp_path / "gb.mkv"
    dest.write_bytes(b"a finished film")
    download_id, channel_id = _seed_completed_download(db, dest=dest)

    player = _FakePlayerManager()
    host = make_downloads_mixin_host(
        db, config, download_manager=manager, player_manager=player)

    host.play_downloaded(download_id)

    assert player.calls == [
        {"path": str(dest), "title": "Ghostbusters", "own_window": split_streams}]
    player.connection_accountant.acquire.assert_not_called()

    with db.session_scope(commit=False) as session:
        channel = RepositoryFactory(session).channels.get_by_id(channel_id)
        assert channel.last_played is not None, "the play never reached History"


def test_play_downloaded_with_a_missing_file_shows_a_message_and_plays_nothing(env, tmp_path):
    manager, db, config, _accountant = env
    missing = tmp_path / "gone.mkv"  # never written
    download_id, channel_id = _seed_completed_download(db, dest=missing)

    player = _FakePlayerManager()
    host = make_downloads_mixin_host(
        db, config, download_manager=manager, player_manager=player)

    host.play_downloaded(download_id)

    assert player.calls == [], "a missing file must never reach the player"
    assert any("no longer on disk" in m for m in host.status_bar.messages)

    with db.session_scope(commit=False) as session:
        channel = RepositoryFactory(session).channels.get_by_id(channel_id)
        assert channel.last_played is None, "a play that never happened is not History"


def test_play_downloaded_ignores_a_row_that_is_not_yet_finished(env, tmp_path):
    """Queued/running/paused rows have no finished file to play."""
    manager, db, config, _accountant = env
    dest = tmp_path / "gb.mkv"
    dest.write_bytes(b"still downloading")
    download_id, _channel_id = _seed_completed_download(db, dest=dest)
    with db.session_scope() as session:
        session.query(DownloadDB).filter_by(id=download_id).update({"state": "running"})

    player = _FakePlayerManager()
    host = make_downloads_mixin_host(
        db, config, download_manager=manager, player_manager=player)

    host.play_downloaded(download_id)

    assert player.calls == []


# ── history group clear + Undo ──────────────────────────────────────────────


def test_clear_history_group_hides_rows_then_undo_restores_them(env, tmp_path):
    manager, db, config, _accountant = env
    dest = tmp_path / "gb.mkv"
    dest.write_bytes(b"a finished film")
    download_id, _channel_id = _seed_completed_download(db, dest=dest)

    host = make_downloads_mixin_host(db, config, download_manager=manager)

    # The row was stamped "now" — bucket_for(now) against itself always lands
    # in "hour" (open-ended upper bound), so this needs no wall-clock timing.
    bucket_key = bucket_for(datetime.now())
    host._clear_download_history_group(bucket_key)

    rows = manager.progress()
    assert len(rows) == 1 and rows[0].history_cleared is True, (
        "the group clear must hide the row from history, never delete it")
    assert dest.exists(), "clearing HISTORY must never touch the file"

    title, kwargs = host.notification_manager.show.call_args
    assert "Undo" in dict(kwargs["actions"])
    undo = dict(kwargs["actions"])["Undo"]
    undo()

    rows = manager.progress()
    assert len(rows) == 1 and rows[0].id == download_id and rows[0].history_cleared is False, (
        "Undo must bring the row back to history")
    assert dest.exists()


def test_clear_history_group_does_not_remove_the_channel_from_the_downloaded_scope(
        env, tmp_path):
    """DL-2/DL-5: a history-cleared row must still make its channel
    "Downloaded" while the file exists — clearing HISTORY must never look
    like deleting the download to the Downloaded scope
    (``channel_downloads.predicate``), which reads the same rows' ``state``
    and never ``history_cleared``.
    """
    manager, db, config, _accountant = env
    dest = tmp_path / "gb.mkv"
    dest.write_bytes(b"a finished film")
    _download_id, channel_id = _seed_completed_download(db, dest=dest)

    host = make_downloads_mixin_host(db, config, download_manager=manager)
    bucket_key = bucket_for(datetime.now())
    host._clear_download_history_group(bucket_key)

    with db.session_scope(commit=False) as session:
        ids = {c.id for c in
               RepositoryFactory(session).channels.get_all(downloaded_only=True)}
    assert channel_id in ids, "a cleared history row must still count as downloaded"
    assert dest.exists()

    _title, kwargs = host.notification_manager.show.call_args
    undo = dict(kwargs["actions"])["Undo"]
    undo()

    rows = manager.progress()
    assert len(rows) == 1 and rows[0].history_cleared is False, (
        "Undo must restore the row to the section's history")


def test_clear_history_group_on_an_empty_group_reports_nothing_to_forget(env):
    manager, db, config, _accountant = env
    host = make_downloads_mixin_host(db, config, download_manager=manager)

    host._clear_download_history_group("today")

    assert any("Nothing to forget" in m for m in host.status_bar.messages)
    host.notification_manager.show.assert_not_called()


def test_clear_download_history_bulk_action_hides_every_terminal_row(env, tmp_path, monkeypatch):
    """The overflow's "Clear download history" — confirmed, not offered Undo."""
    from PyQt6.QtWidgets import QMessageBox

    manager, db, config, _accountant = env
    dest = tmp_path / "gb.mkv"
    dest.write_bytes(b"a finished film")
    _seed_completed_download(db, dest=dest)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    host = make_downloads_mixin_host(db, config, download_manager=manager)
    host._clear_download_history()

    rows = manager.progress()
    assert len(rows) == 1 and rows[0].history_cleared is True, "hidden, never deleted"
    assert dest.exists(), "the bulk clear must never touch the file either"
