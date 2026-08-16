"""Episodes could not fail over to a source's alternate hosts at all — only
channels/movies (via ``validate_and_failover_stream_url``) could (#308).

The fix: ``launch_player_for_episode`` (main_window_series.py) now routes its
pre-flight check through the same ``validate_and_failover_stream_url``
chokepoint the channel path uses, and — mirroring #306's channel fix — a
successful failover to a different host is written back to the episode's own
row (``EpisodeRepository.update_stream_url``) so the next play of the same
episode doesn't re-pay the dead-host stall.

All DB tests use file-backed SQLite (tmp_path), per CLAUDE.md rule — never
``:memory:``, and the isolated-user-config fixture (autouse, conftest.py)
keeps this away from any real ``~/.config/metatv``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ImmediateFuture:
    """A future-like object that is already done: .result()/.add_done_callback()
    both work synchronously, so the test doesn't need a real thread pool."""

    def __init__(self):
        self._result = None
        self._exc = None

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._result

    def add_done_callback(self, cb):
        cb(self)


class _ImmediateExecutor:
    """A fake ThreadPoolExecutor whose submit() runs the callable immediately
    on the calling thread and returns an already-done future."""

    def submit(self, fn, *args, **kwargs):
        fut = _ImmediateFuture()
        try:
            fut._result = fn(*args, **kwargs)
        except Exception as e:  # pragma: no cover - defensive, mirrors real executor
            fut._exc = e
        return fut


def _make_mixin(db=None, failover_return=None):
    """A bare ``_SeriesMixin`` instance wired for launch_player_for_episode.

    ``failover_return`` is the ``(final_url, err)`` tuple
    ``validate_and_failover_stream_url`` should return — assigned directly as
    an instance attribute (a lambda), since ``_SeriesMixin`` alone (without
    ``_StreamingMixin`` composed in, as ``MainWindow`` does for real) doesn't
    define that method itself.
    """
    from metatv.gui.main_window_series import _SeriesMixin
    obj = _SeriesMixin.__new__(_SeriesMixin)
    obj.db = db
    obj.executor = _ImmediateExecutor()
    obj.player_manager = MagicMock()
    obj.player_manager.is_available.return_value = True
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-123"
    obj.status_bar = MagicMock()
    obj._episode_ready = MagicMock()
    obj._episode_failed = MagicMock()
    if failover_return is not None:
        obj.validate_and_failover_stream_url = MagicMock(return_value=failover_return)
    return obj


def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    return d


def _insert_episode(session, episode_id: str, provider_id: str, stream_url: str,
                     title: str = "Test Episode"):
    from metatv.core.database import EpisodeDB
    ep = EpisodeDB(
        id=episode_id,
        season_id=str(uuid.uuid4()),
        series_id=str(uuid.uuid4()),
        provider_id=provider_id,
        episode_id=episode_id,
        episode_num=1,
        season_num=1,
        title=title,
        stream_url=stream_url,
    )
    session.add(ep)
    session.flush()
    return ep


def _read_stream_url(db, episode_id: str) -> str:
    """Re-read an episode's stored stream_url from a FRESH session."""
    from metatv.core.database import EpisodeDB
    with db.session_scope(commit=False) as session:
        row = session.get(EpisodeDB, episode_id)
        return row.stream_url


# ---------------------------------------------------------------------------
# 1. A successful failover to a DIFFERENT host emits the NEW url, not the
#    original — the whole point of routing through validate_and_failover.
# ---------------------------------------------------------------------------

def test_episode_ready_carries_failover_url_not_original():
    original_url = "http://deadhost.example/ep.mp4"
    alt_url = "http://alt/ep.mp4"

    obj = _make_mixin(db=None, failover_return=(alt_url, None))

    obj.launch_player_for_episode(original_url, "Test Episode", provider_id="prov-1")

    obj._episode_ready.emit.assert_called_once()
    args = obj._episode_ready.emit.call_args[0]
    # (notif_id, stream_url, title, queue_episodes, provider_id, start_seconds)
    emitted_url = args[1]
    assert emitted_url == alt_url
    assert emitted_url != original_url
    obj._episode_failed.emit.assert_not_called()


# ---------------------------------------------------------------------------
# 2. A successful failover to a different host WRITES BACK to the episode's
#    row, via a real Database on a tmp_path file.
# ---------------------------------------------------------------------------

def test_failover_persists_new_url_on_change(tmp_path):
    db = _make_db(tmp_path)
    episode_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    original_url = "http://deadhost.example/ep.mp4"
    alt_url = "http://goodhost.example/ep.mp4"

    with db.session_scope() as session:
        _insert_episode(session, episode_id, provider_id, original_url)

    obj = _make_mixin(db=db, failover_return=(alt_url, None))

    obj.launch_player_for_episode(
        original_url, "Test Episode", provider_id=provider_id, episode_id=episode_id,
    )

    assert _read_stream_url(db, episode_id) == alt_url
    args = obj._episode_ready.emit.call_args[0]
    assert args[1] == alt_url


# ---------------------------------------------------------------------------
# 3. No write occurs when the failover returns the SAME url (primary worked).
# ---------------------------------------------------------------------------

def test_no_write_when_url_unchanged(tmp_path):
    from metatv.core.repositories.episode import EpisodeRepository

    db = _make_db(tmp_path)
    episode_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    original_url = "http://workinghost.example/ep.mp4"

    with db.session_scope() as session:
        _insert_episode(session, episode_id, provider_id, original_url)

    obj = _make_mixin(db=db, failover_return=(original_url, None))

    with patch.object(EpisodeRepository, "update_stream_url") as mock_update:
        obj.launch_player_for_episode(
            original_url, "Test Episode", provider_id=provider_id, episode_id=episode_id,
        )

    mock_update.assert_not_called()
    assert _read_stream_url(db, episode_id) == original_url


# ---------------------------------------------------------------------------
# 4. No write occurs when episode_id is "" (default) — even though the url
#    changed — because there's no row to write to.
# ---------------------------------------------------------------------------

def test_no_write_when_episode_id_blank(tmp_path):
    db = _make_db(tmp_path)
    episode_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    original_url = "http://deadhost.example/ep.mp4"
    alt_url = "http://goodhost.example/ep.mp4"

    with db.session_scope() as session:
        _insert_episode(session, episode_id, provider_id, original_url)

    obj = _make_mixin(db=db, failover_return=(alt_url, None))

    # episode_id NOT passed — defaults to "".
    obj.launch_player_for_episode(original_url, "Test Episode", provider_id=provider_id)

    # The row is untouched — write-back was skipped because episode_id was blank.
    assert _read_stream_url(db, episode_id) == original_url
    args = obj._episode_ready.emit.call_args[0]
    assert args[1] == alt_url  # playback still uses the failover URL


# ---------------------------------------------------------------------------
# 5. Total failure (("", "some error")) still emits _episode_failed with the
#    ORIGINAL url, not the (empty) failover result.
# ---------------------------------------------------------------------------

def test_total_failure_emits_original_url():
    original_url = "http://deadhost.example/ep.mp4"

    obj = _make_mixin(db=None, failover_return=("", "some error"))

    obj.launch_player_for_episode(original_url, "Test Episode", provider_id="prov-1")

    obj._episode_ready.emit.assert_not_called()
    obj._episode_failed.emit.assert_called_once()
    args = obj._episode_failed.emit.call_args[0]
    # (notif_id, title, detail, stream_url)
    assert args[2] == "some error"
    assert args[3] == original_url
