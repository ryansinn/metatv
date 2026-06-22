"""Behavioral tests for Slice 3b-4 — smart resume + "Still here?" prompt.

Covered behaviors:
1. get_last_engaged returns the most-recent manual episode and ignores later queue ones.
2. get_resume_dto returns the engaged episode itself when it is not completed.
3. get_resume_dto returns the next episode after the engaged one when it is completed.
4. get_resume_dto falls back to get_last_played_dto when no manual episode exists.
5. get_resume_dto returns None when the engaged episode is the series finale (completed).
6. mark_episodes_as_engaged flips last_played_via to 'manual' for given ids.
7. _watch_checkpoint_tick emits _queue_end_detected only when auto-advance happened
   (last_seen_pos > 0) and prompt_after_autoplay is True.
8. _watch_checkpoint_tick does NOT emit when last_seen_pos == 0 (no auto-advance).
9. _watch_checkpoint_tick does NOT emit when prompt_after_autoplay is False.
10. _on_queue_end_detected with Yes → calls _bg_promote_queue_episodes with correct ids.
11. _bg_promote_queue_episodes writes manual via to DB; rows are readable after session close.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'smart_resume.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_episodes(db, ep_specs: list[tuple[str, int, int, str | None, bool]]) -> None:
    """Insert EpisodeDB rows.

    ep_specs items: (id, season_num, episode_num, last_played_via, watch_completed)
    """
    from metatv.core.database import EpisodeDB
    with db.session_scope() as session:
        for i, (ep_id, sn, en, via, completed) in enumerate(ep_specs):
            session.add(EpisodeDB(
                id=ep_id,
                series_id="ser1",
                season_id="seas1",
                provider_id="p1",
                episode_id=f"orig_{i}",
                season_num=sn,
                episode_num=en,
                title=f"S{sn:02d}E{en:02d}",
                stream_url=f"http://example.com/{ep_id}.mp4",
                last_played=datetime(2026, 1, en, 12, 0, 0) if via else None,
                last_played_via=via,
                watch_completed=completed,
                watch_progress=0 if completed else 300,
            ))


def _read_via(db, ep_id: str) -> str | None:
    """Read last_played_via for an episode."""
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ep = RepositoryFactory(session).episodes.get_by_id(ep_id)
        return ep.last_played_via if ep else None


# ---------------------------------------------------------------------------
# 1. get_last_engaged ignores queue episodes
# ---------------------------------------------------------------------------

def test_get_last_engaged_ignores_queue(db):
    """get_last_engaged returns the manual episode even when a later queue one exists."""
    _seed_episodes(db, [
        ("ep1", 1, 1, "manual",  True),
        ("ep2", 1, 2, "queue",   True),   # played later (datetime uses episode_num as hour)
        ("ep3", 1, 3, "queue",   True),
    ])
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ep = RepositoryFactory(session).episodes.get_last_engaged("ser1", "p1")
        assert ep is not None
        assert ep.id == "ep1"


def test_get_last_engaged_returns_none_when_no_manual(db):
    """get_last_engaged returns None when all episodes were queue-played."""
    _seed_episodes(db, [
        ("ep1", 1, 1, "queue", True),
        ("ep2", 1, 2, "queue", True),
    ])
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ep = RepositoryFactory(session).episodes.get_last_engaged("ser1", "p1")
        assert ep is None


def test_get_last_engaged_returns_none_when_no_plays(db):
    """get_last_engaged returns None when no episodes have been played at all."""
    _seed_episodes(db, [
        ("ep1", 1, 1, None, False),
    ])
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ep = RepositoryFactory(session).episodes.get_last_engaged("ser1", "p1")
        assert ep is None


# ---------------------------------------------------------------------------
# 2. get_resume_dto — engaged episode not completed → resume inside it
# ---------------------------------------------------------------------------

def test_get_resume_dto_resumes_in_engaged_episode(db):
    """When the last engaged episode is not completed, resume_dto returns it."""
    _seed_episodes(db, [
        ("ep1", 1, 1, "manual", False),   # in-progress
        ("ep2", 1, 2, "queue",  True),
    ])
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dto = RepositoryFactory(session).episodes.get_resume_dto("ser1", "p1")
    assert dto is not None
    assert dto.id == "ep1"
    assert dto.episode_num == 1


# ---------------------------------------------------------------------------
# 3. get_resume_dto — engaged episode completed → return the next one
# ---------------------------------------------------------------------------

def test_get_resume_dto_returns_next_after_completed_engaged(db):
    """When the last engaged episode is completed, resume_dto returns the next one."""
    _seed_episodes(db, [
        ("ep1", 1, 1, "manual", True),    # completed
        ("ep2", 1, 2, "queue",  True),    # queue-watched
        ("ep3", 1, 3, None,     False),   # not played — should be returned as next
    ])
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dto = RepositoryFactory(session).episodes.get_resume_dto("ser1", "p1")
    assert dto is not None
    assert dto.id == "ep2"  # next in air order after ep1 (S01E02)


# ---------------------------------------------------------------------------
# 4. get_resume_dto falls back to get_last_played when no manual episode exists
# ---------------------------------------------------------------------------

def test_get_resume_dto_fallback_to_last_played(db):
    """When no manually-played episode exists, resume_dto falls back to get_last_played_dto."""
    _seed_episodes(db, [
        ("ep1", 1, 1, "queue", True),
        ("ep2", 1, 2, "queue", True),
    ])
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dto = RepositoryFactory(session).episodes.get_resume_dto("ser1", "p1")
    # ep2 was played most recently (hour=2 in timestamp)
    assert dto is not None
    assert dto.id == "ep2"


# ---------------------------------------------------------------------------
# 5. get_resume_dto returns None when series is complete (no episode after engaged)
# ---------------------------------------------------------------------------

def test_get_resume_dto_returns_none_when_series_complete(db):
    """When the engaged episode is the series finale and is completed, return None."""
    _seed_episodes(db, [
        ("ep1", 1, 1, "manual", True),  # only episode; completed
    ])
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dto = RepositoryFactory(session).episodes.get_resume_dto("ser1", "p1")
    assert dto is None


# ---------------------------------------------------------------------------
# 6. mark_episodes_as_engaged — flips via to manual; readable after session close
# ---------------------------------------------------------------------------

def test_mark_episodes_as_engaged_flips_via(db):
    """mark_episodes_as_engaged sets last_played_via='manual'; readable outside session."""
    _seed_episodes(db, [
        ("ep1", 1, 1, "queue", True),
        ("ep2", 1, 2, "queue", True),
        ("ep3", 1, 3, "queue", True),
    ])
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        updated = RepositoryFactory(session).episodes.mark_episodes_as_engaged(["ep1", "ep2"])
    assert updated == 2
    assert _read_via(db, "ep1") == "manual"
    assert _read_via(db, "ep2") == "manual"
    assert _read_via(db, "ep3") == "queue"  # untouched


def test_mark_episodes_as_engaged_empty_list(db):
    """mark_episodes_as_engaged is a no-op for an empty list."""
    _seed_episodes(db, [("ep1", 1, 1, "queue", True)])
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        updated = RepositoryFactory(session).episodes.mark_episodes_as_engaged([])
    assert updated == 0
    assert _read_via(db, "ep1") == "queue"


# ---------------------------------------------------------------------------
# 7. _watch_checkpoint_tick emits _queue_end_detected when auto-advance happened
# ---------------------------------------------------------------------------

def _make_streaming_host(prompt_after: bool = True):
    """Build a minimal _StreamingMixin host for tick tests."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.config = MagicMock(prompt_after_autoplay=prompt_after)
    host.player_manager = MagicMock()
    host.executor = MagicMock()
    host._queue_end_detected = MagicMock()
    host._watch_checkpoint_timer = MagicMock()
    return host


def _queue_tracking(ep_ids: list[str], last_seen_pos: int) -> dict:
    """Build a tracking entry for a queued episode run."""
    return {
        "media_type": "episode",
        "played_via": "manual",
        "queue": [{"content_id": eid} for eid in ep_ids],
        "last_seen_pos": last_seen_pos,
    }


def test_tick_emits_queue_end_when_auto_advanced():
    """Tick emits _queue_end_detected with queue ids 1..last_seen_pos when window closes."""
    host = _make_streaming_host(prompt_after=True)
    ep_ids = ["ep1", "ep2", "ep3"]
    host._watch_tracking = {"__shared__": _queue_tracking(ep_ids, last_seen_pos=2)}
    # active_keys returns [] → window closed
    host.player_manager.active_keys.return_value = []

    host._watch_checkpoint_tick()

    host._queue_end_detected.emit.assert_called_once_with(["ep2", "ep3"])


def test_tick_does_not_emit_when_no_auto_advance():
    """Tick does NOT emit _queue_end_detected when last_seen_pos == 0 (only manual play)."""
    host = _make_streaming_host(prompt_after=True)
    ep_ids = ["ep1", "ep2"]
    host._watch_tracking = {"__shared__": _queue_tracking(ep_ids, last_seen_pos=0)}
    host.player_manager.active_keys.return_value = []

    host._watch_checkpoint_tick()

    host._queue_end_detected.emit.assert_not_called()


def test_tick_does_not_emit_when_prompt_disabled():
    """Tick does NOT emit _queue_end_detected when prompt_after_autoplay is False."""
    host = _make_streaming_host(prompt_after=False)
    ep_ids = ["ep1", "ep2", "ep3"]
    host._watch_tracking = {"__shared__": _queue_tracking(ep_ids, last_seen_pos=2)}
    host.player_manager.active_keys.return_value = []

    host._watch_checkpoint_tick()

    host._queue_end_detected.emit.assert_not_called()


def test_tick_no_emit_for_non_episode_tracking():
    """Tick does NOT emit when the closed window was tracking a movie (non-queue)."""
    host = _make_streaming_host(prompt_after=True)
    host._watch_tracking = {
        "__shared__": {"media_type": "movie", "content_id": "m1", "played_via": "manual"}
    }
    host.player_manager.active_keys.return_value = []

    host._watch_checkpoint_tick()

    host._queue_end_detected.emit.assert_not_called()


# ---------------------------------------------------------------------------
# 10. _on_queue_end_detected Yes → submits _bg_promote_queue_episodes
# ---------------------------------------------------------------------------

def _patch_dialog(accepted: bool):
    """Return a context-manager stack that makes the QDialog a no-op mock.

    We need to preserve the real QDialog.DialogCode enum so the method's
    ``result == QDialog.DialogCode.Accepted`` comparison works correctly.  We
    achieve this by patching only the Qt widget-construction calls while letting
    the real ``QDialog`` class — and thus ``QDialog.DialogCode.Accepted`` — be
    imported from the real module at call time.
    """
    from contextlib import ExitStack
    from PyQt6.QtWidgets import QDialog

    # exec() return value must match the *real* enum for the comparison to fire.
    exec_return = QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    stack = ExitStack()
    mock_dlg_class = MagicMock()
    mock_dlg_instance = MagicMock()
    mock_dlg_instance.exec.return_value = exec_return
    # Preserve the real enum on the mock class so ``QDialog.DialogCode.Accepted``
    # still resolves to the real value inside _on_queue_end_detected.
    mock_dlg_class.return_value = mock_dlg_instance
    mock_dlg_class.DialogCode = QDialog.DialogCode

    stack.enter_context(
        patch("metatv.gui.main_window_streaming.QDialog", mock_dlg_class)
    )
    stack.enter_context(patch("metatv.gui.main_window_streaming.QVBoxLayout"))
    stack.enter_context(patch("metatv.gui.main_window_streaming.QLabel"))
    stack.enter_context(patch("metatv.gui.main_window_streaming.QDialogButtonBox"))
    return stack


def test_on_queue_end_yes_submits_promote():
    """_on_queue_end_detected: when user clicks Yes, submits promote worker with correct ids."""
    from metatv.gui.main_window_streaming import _StreamingMixin

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.config = MagicMock(prompt_after_autoplay=True)
    host.executor = MagicMock()

    auto_ids = ["ep2", "ep3"]
    with _patch_dialog(accepted=True):
        host._on_queue_end_detected(auto_ids)

    host.executor.submit.assert_called_once_with(
        host._bg_promote_queue_episodes, auto_ids
    )


def test_on_queue_end_no_does_not_submit():
    """_on_queue_end_detected: when user clicks No, does NOT submit promote worker."""
    from metatv.gui.main_window_streaming import _StreamingMixin

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.config = MagicMock(prompt_after_autoplay=True)
    host.executor = MagicMock()

    auto_ids = ["ep2", "ep3"]
    with _patch_dialog(accepted=False):
        host._on_queue_end_detected(auto_ids)

    host.executor.submit.assert_not_called()


def test_on_queue_end_skips_when_prompt_disabled():
    """_on_queue_end_detected is a no-op when prompt_after_autoplay is False."""
    from metatv.gui.main_window_streaming import _StreamingMixin

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.config = MagicMock(prompt_after_autoplay=False)
    host.executor = MagicMock()

    host._on_queue_end_detected(["ep2"])

    host.executor.submit.assert_not_called()


# ---------------------------------------------------------------------------
# 11. _bg_promote_queue_episodes writes to DB; readable after session close
# ---------------------------------------------------------------------------

def test_bg_promote_writes_to_db(db):
    """_bg_promote_queue_episodes flips last_played_via; change persists after session."""
    _seed_episodes(db, [
        ("ep1", 1, 1, "queue", True),
        ("ep2", 1, 2, "queue", True),
    ])

    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db

    host._bg_promote_queue_episodes(["ep1", "ep2"])

    assert _read_via(db, "ep1") == "manual"
    assert _read_via(db, "ep2") == "manual"
