"""The details pane's Resume button follows the saved position (RESUME-1).

Owner, 2026-09-11: "even though I'd watched 5 minutes of a show it didn't
create the resume button". The position WAS stored (``watch_progress=234`` on
the last-played movie). The pane drew Resume once, from the DTO it was handed,
and the ``channel_state_bus`` re-read that follows every progress write
(``_bg_fetch_action_state`` → ``ChannelActionState`` → ``_ActionBar.load``)
carried queue/rating/hidden/favourite — and no progress — so nothing could
move the button afterwards. ``ChannelActionState`` now carries
``media_type``/``watch_progress``/``watch_completed`` and ``load()`` applies
them through ``resume_state()``, the one predicate ``show_channel`` uses too.

These assert the BUTTON (visible / hidden / its M:SS label), not a mocked
``set_resume`` call — a mocked call passes for a ``load()`` that calls it with
the wrong arguments in the wrong mode.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from metatv.core.database import ChannelDB
from metatv.core.models import MediaType
from metatv.core.repositories import RepositoryFactory
from metatv.gui.details_actions import ChannelActionState, _ActionBar, resume_state


def _bar(qtbot) -> _ActionBar:
    from metatv.core.config import Config
    bar = _ActionBar(Config())
    qtbot.addWidget(bar)          # the leak guard wants every top-level owned
    return bar


def test_load_shows_resume_for_a_part_watched_movie(qapp, qtbot):
    bar = _bar(qtbot)
    bar.load(ChannelActionState(channel_id="c", media_type=MediaType.MOVIE,
                                watch_progress=234, watch_completed=False))
    assert not bar.resume_button.isHidden(), "a saved position must offer Resume"
    assert "3:54" in bar.resume_button.text()
    assert "3:54" in bar.resume_button.toolTip()


def test_load_hides_resume_once_completed(qapp, qtbot):
    bar = _bar(qtbot)
    bar.set_resume(True, 120)                                   # was offered…
    bar.load(ChannelActionState(channel_id="c", media_type=MediaType.MOVIE,
                                watch_progress=0, watch_completed=True))
    assert bar.resume_button.isHidden(), "a completed title has nothing to resume"


def test_load_never_shows_resume_for_live(qapp, qtbot):
    bar = _bar(qtbot)
    bar.load(ChannelActionState(channel_id="c", media_type=MediaType.LIVE,
                                watch_progress=50, watch_completed=False))
    assert bar.resume_button.isHidden()


def test_load_in_episode_mode_leaves_the_episode_resume_alone(qapp, qtbot):
    """A late series-level fetch must not clobber the episode's own Resume —
    the same race ``load()`` already guards for queue/favourite."""
    bar = _bar(qtbot)
    bar.enter_episode_mode("S01E02")
    bar.set_resume(True, 120)
    bar.load(ChannelActionState(channel_id="c", media_type=MediaType.MOVIE,
                                watch_progress=0, watch_completed=False))
    assert not bar.resume_button.isHidden()
    assert "2:00" in bar.resume_button.text()


def test_resume_state_is_the_one_predicate():
    assert resume_state(MediaType.MOVIE, 234, False) == (True, 234)
    assert resume_state(MediaType.MOVIE, 0, False) == (False, 0)
    assert resume_state(MediaType.LIVE, 50, False) == (False, 50)
    assert resume_state(MediaType.MOVIE, 100, True) == (False, 100)
    assert resume_state(None, None, None) == (False, 0)


def test_the_fetch_carries_progress(db):
    """``_bg_fetch_action_state`` — the bus's tier-2 re-read — now reads the
    position back from the row, on a real file-backed Database."""
    from metatv.gui.main_window_metadata import _MetadataMixin

    cid = "movie-1"
    s = db.get_session()
    try:
        s.add(ChannelDB(id=cid, source_id=cid, provider_id="p", name="Some Film",
                        media_type=MediaType.MOVIE))
        s.commit()
    finally:
        s.close()
    with db.session_scope() as session:
        RepositoryFactory(session).channels.record_watch_progress(cid, 234, 5000)

    host = _MetadataMixin.__new__(_MetadataMixin)
    host.db = db
    host.config = MagicMock(epg_link_blocklist=[])
    host._action_state_loaded = MagicMock()

    host._bg_fetch_action_state(cid)

    host._action_state_loaded.emit.assert_called_once()
    state = host._action_state_loaded.emit.call_args[0][0]
    assert state.channel_id == cid
    assert state.media_type == MediaType.MOVIE
    assert state.watch_progress == 234
    assert state.watch_completed is False
    assert resume_state(state.media_type, state.watch_progress, state.watch_completed) == (True, 234)
