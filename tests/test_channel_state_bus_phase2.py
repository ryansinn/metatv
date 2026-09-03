"""Tests for ChannelStateBus phase 2 (#312) — the remaining per-channel state axes.

Two defects fixed here:

**Defect 1 (headline).** ``ChannelActionState`` has an ``is_favorite`` field,
populated at the authoritative re-read (``_bg_fetch_action_state``), but
``_ActionBar.load()`` never applied it — the favorite star was only ever
painted by ``show_channel()``'s tier-1 instant display. Favoriting a title
from the channel list while it was open in the details pane left the star
unfilled, even though #311's own What's New claimed this worked.

**Defect 2.** Several per-channel mutation handlers changed an axis the
details pane's action bar renders (hidden, queue) but never published to
``ChannelStateBus``, so the pane stayed stale exactly as it did before #311.

Per CLAUDE.md: appearance tests (1-2) need no DB/Qt beyond a real ``_ActionBar``
widget; publish tests (3+) use a real ``Database`` on a ``tmp_path`` file, never
``:memory:``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metatv.core.config import Config
from metatv.gui import theme as _theme
from metatv.gui.details_actions import ChannelActionState, _ActionBar


# ---------------------------------------------------------------------------
# Appearance tests — real _ActionBar, real theme roles, real Qt widget state
# ---------------------------------------------------------------------------


def test_action_bar_load_applies_favorite_star(qtbot):
    """load() must paint the favorite star from state.is_favorite (Defect 1).

    Proven to fail pre-fix: before this change, load() never touched
    favorite_button at all, so a freshly-built _ActionBar's un-favorited
    glyph/tooltip/style would survive load(is_favorite=True) unchanged.
    """
    cfg = Config()
    ab = _ActionBar(cfg)
    qtbot.addWidget(ab)

    ab.load(ChannelActionState(channel_id="c1", is_favorite=True))
    fav_text = ab.favorite_button.text()
    fav_tooltip = ab.favorite_button.toolTip()
    fav_style = ab.favorite_button.styleSheet()

    assert fav_text == cfg.favorite_icon
    assert "Remove" in fav_tooltip and "Favorites" in fav_tooltip
    assert fav_style == _theme.DETAIL_RAIL_BTN_FAV

    ab.load(ChannelActionState(channel_id="c1", is_favorite=False))
    unfav_text = ab.favorite_button.text()
    unfav_tooltip = ab.favorite_button.toolTip()
    unfav_style = ab.favorite_button.styleSheet()

    assert unfav_text == cfg.unfavorite_icon
    assert "Add" in unfav_tooltip and "Favorites" in unfav_tooltip
    assert unfav_style == _theme.DETAIL_RAIL_BTN

    # The two states must be genuinely distinct — a rendering where both
    # states look identical must not satisfy this test.
    assert fav_text != unfav_text
    assert fav_style != unfav_style


def test_action_bar_load_does_not_clobber_episode_favorite(qtbot):
    """In episode mode, load() must not touch the favorite star — the episode
    grain (set via set_episode_queue_favorite) owns it, same as it already
    owns queue state.
    """
    cfg = Config()
    ab = _ActionBar(cfg)
    qtbot.addWidget(ab)

    ab.set_primary_mode("episode")
    ab.set_episode_queue_favorite(in_queue=False, is_favorite=True)
    assert ab.favorite_button.text() == cfg.favorite_icon

    # A late-arriving SERIES-level fetch with is_favorite=False races in —
    # must not clobber the episode-scoped star.
    ab.load(ChannelActionState(channel_id="series-1", is_favorite=False))

    assert ab.favorite_button.text() == cfg.favorite_icon  # unchanged
    assert ab.favorite_button.styleSheet() == _theme.DETAIL_RAIL_BTN_FAV  # unchanged


# ---------------------------------------------------------------------------
# Publish tests — real Database on tmp_path, real mutation handlers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'bus_phase2.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(db_obj, channel_id: str, **kw) -> None:
    from metatv.core.database import ChannelDB

    with db_obj.session_scope() as session:
        session.add(ChannelDB(
            id=channel_id, source_id=channel_id, provider_id="prov1",
            name="Test Movie", media_type="movie", **kw,
        ))


class _Recorder:
    """A bound-method target for ChannelStateBus.subscribe (WeakMethod needs one)."""

    def __init__(self):
        self.received: list[tuple[str, dict]] = []

    def on_event(self, channel_id: str, delta: dict) -> None:
        self.received.append((channel_id, delta))


def test_apply_favorite_toggle_publishes_and_rereads(db):
    """Defect 1's other half: the entry points that share _apply_favorite_toggle
    (toggle_favorite / toggle_favorite_by_id) must publish is_favorite, and the
    authoritative re-read must actually reach the details pane.
    """
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-fav-1"
    _make_channel(db, channel_id, is_favorite=False)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._apply_favorite_toggle(channel_id)

    assert recorder.received == [(channel_id, {"is_favorite": True})]
    assert len(host.details_pane.applied_states) == 1
    state = host.details_pane.applied_states[0]
    assert state.channel_id == channel_id
    assert state.is_favorite is True


def test_toggle_favorite_by_id_publishes_via_apply_favorite_toggle(db):
    """The public entry point (details-pane Favorite button) reaches the bus
    through _apply_favorite_toggle — no hand-rolled refresh tail."""
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-fav-2"
    _make_channel(db, channel_id, is_favorite=False)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host.toggle_favorite_by_id(channel_id)

    assert recorder.received == [(channel_id, {"is_favorite": True})]
    assert host.details_pane.applied_states[-1].is_favorite is True


def test_hide_channel_from_history_publishes_and_rereads(db):
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-hide-hist"
    _make_channel(db, channel_id)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._hide_channel_from_history(channel_id)

    assert recorder.received == [(channel_id, {"is_hidden": True})]
    assert len(host.details_pane.applied_states) == 1
    state = host.details_pane.applied_states[0]
    assert state.channel_id == channel_id
    assert state.is_hidden is True


def test_hide_channel_from_alerts_publishes_and_rereads(db):
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-hide-alerts"
    _make_channel(db, channel_id)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._hide_channel_from_alerts(channel_id)

    assert recorder.received == [(channel_id, {"is_hidden": True})]
    assert host.details_pane.applied_states[-1].is_hidden is True


def test_hide_channel_from_recommendations_publishes_and_rereads(db):
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-hide-recs"
    _make_channel(db, channel_id)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._hide_channel_from_recommendations(channel_id)

    assert recorder.received == [(channel_id, {"is_hidden": True})]
    assert len(host.details_pane.applied_states) == 1
    state = host.details_pane.applied_states[0]
    assert state.channel_id == channel_id
    assert state.is_hidden is True


def test_hide_channel_from_recommendations_refreshes_synchronously(db):
    """RefreshCoalescer (REC-LAG) only sits on the enrichment-driven trigger —
    a user-initiated hide must still refresh its dependent views instantly,
    with no debounce leaked onto this path.

    No Qt event loop is spun here at all (no qtbot.wait / processEvents): the
    recorders below are asserted called immediately, in the same call stack as
    ``_hide_channel_from_recommendations`` — proof nothing deferred them
    behind a QTimer.
    """
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-hide-recs-sync"
    _make_channel(db, channel_id)
    host = make_channel_state_bus_host(db)
    refreshed: list = []
    host._refresh_recommended_section = lambda: refreshed.append("recommended")
    host.load_channels = lambda: refreshed.append("channels")
    host.preferences_view = type("_P", (), {"refresh": staticmethod(
        lambda: refreshed.append("preferences"))})()

    host._hide_channel_from_recommendations(channel_id)

    assert refreshed == ["preferences", "recommended", "channels"]


def test_unhide_channel_publishes_after_deferred_reload(db, qtbot):
    """_unhide_channel's DB write is off-thread and its reload is deferred via
    QTimer.singleShot — the publish must run AFTER that deferred reload, not
    before it (the reload and the publish are both in the same _after callback).
    """
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-unhide-1"
    _make_channel(db, channel_id, is_hidden=True)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._unhide_channel(channel_id)
    qtbot.wait(250)  # let QTimer.singleShot(150, _after) fire

    assert recorder.received == [(channel_id, {"is_hidden": False})]
    assert len(host.details_pane.applied_states) == 1
    state = host.details_pane.applied_states[0]
    assert state.channel_id == channel_id
    assert state.is_hidden is False


def test_add_to_queue_publishes_in_queue_true(db):
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-queue-1"
    _make_channel(db, channel_id)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._add_to_queue(channel_id)

    assert recorder.received == [(channel_id, {"in_queue": True})]
    assert host.details_pane.applied_states[-1].in_queue is True


def test_remove_from_queue_publishes_in_queue_false(db):
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-queue-2"
    _make_channel(db, channel_id)
    host = make_channel_state_bus_host(db)
    host._add_to_queue(channel_id)  # seed queue membership
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._remove_from_queue(channel_id)

    assert recorder.received == [(channel_id, {"in_queue": False})]
    assert host.details_pane.applied_states[-1].in_queue is False


def test_on_details_queue_toggle_publishes_correct_direction(db):
    """The details pane's own Watch Later button toggles both ways from one seam."""
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-queue-3"
    _make_channel(db, channel_id)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._on_details_queue_toggle(channel_id)  # not queued -> adds
    assert recorder.received[-1] == (channel_id, {"in_queue": True})
    assert host.details_pane.applied_states[-1].in_queue is True

    host._on_details_queue_toggle(channel_id)  # queued -> removes
    assert recorder.received[-1] == (channel_id, {"in_queue": False})
    assert host.details_pane.applied_states[-1].in_queue is False
