"""Tests for ChannelStateBus — the one publish point for per-channel user-state
changes (metatv/gui/channel_state_bus.py).

Owner bug: dislike something from the Watch Queue while it's open in the
details pane, and the pane's buttons never update. Writes were already
chokepointed; reads were never invalidated — the details pane's action state
is written in exactly one place (``apply_action_state``) and nothing after a
mutation ever called back into it.

Per CLAUDE.md: tests 5-6 use a REAL ``Database`` on a ``tmp_path`` file, never
``:memory:``. Tests 1-4 are pure-bus unit tests needing no DB/Qt at all.
"""

from __future__ import annotations

import gc
from pathlib import Path

import pytest

from metatv.gui.channel_state_bus import ChannelStateBus


# ---------------------------------------------------------------------------
# Pure-bus unit tests (no MainWindow, no DB, no Qt)
# ---------------------------------------------------------------------------


def test_publish_calls_subscribers_then_reread():
    """Tier 1 (echo) must run for every live subscriber BEFORE tier 2 (reread)."""
    log = []
    bus = ChannelStateBus(reread=lambda channel_id: log.append(("reread", channel_id)))

    class _Sub:
        def on_event(self, channel_id, delta):
            log.append(("echo", channel_id, delta))

    sub = _Sub()
    bus.subscribe(sub.on_event)

    bus.publish("ch1", rating=1)

    assert log == [
        ("echo", "ch1", {"rating": 1}),
        ("reread", "ch1"),
    ]


def test_publish_multiple_subscribers_all_echoed_before_reread():
    """Multiple subscribers all get the echo, in subscription order, before reread."""
    log = []
    bus = ChannelStateBus(reread=lambda channel_id: log.append(("reread", channel_id)))

    class _Sub:
        def __init__(self, tag):
            self.tag = tag

        def on_event(self, channel_id, delta):
            log.append((self.tag, channel_id, delta))

    a, b = _Sub("a"), _Sub("b")
    bus.subscribe(a.on_event)
    bus.subscribe(b.on_event)

    bus.publish("ch1", is_favorite=True)

    assert log == [
        ("a", "ch1", {"is_favorite": True}),
        ("b", "ch1", {"is_favorite": True}),
        ("reread", "ch1"),
    ]


def test_publish_subscriber_raises_does_not_stop_others_or_reread():
    """A raising subscriber is logged and swallowed; other subscribers and
    reread still run."""
    log = []
    bus = ChannelStateBus(reread=lambda channel_id: log.append(("reread", channel_id)))

    class _Bad:
        def on_event(self, channel_id, delta):
            raise RuntimeError("boom")

    class _Good:
        def on_event(self, channel_id, delta):
            log.append(("good", channel_id, delta))

    bad, good = _Bad(), _Good()
    # Subscribe the raiser FIRST so a bug that stops iteration on the first
    # exception would hide the good subscriber's call.
    bus.subscribe(bad.on_event)
    bus.subscribe(good.on_event)

    bus.publish("ch2", rating=-1)  # must not raise

    assert ("good", "ch2", {"rating": -1}) in log
    assert ("reread", "ch2") in log


def test_dead_subscriber_pruned_and_never_called():
    """A subscriber held via WeakMethod silently drops out once its owner is
    garbage-collected — never resurrected, never raises."""
    log = []
    bus = ChannelStateBus(reread=lambda channel_id: log.append(("reread", channel_id)))

    class _Sub:
        def on_event(self, channel_id, delta):
            log.append(("echo", channel_id, delta))

    sub = _Sub()
    bus.subscribe(sub.on_event)
    del sub
    gc.collect()

    bus.publish("ch3", rating=1)  # must not raise

    assert log == [("reread", "ch3")]
    assert len(bus._subscribers) == 0  # pruned, not just skipped


def test_reread_fires_with_zero_subscribers():
    """The authoritative reread still runs even when nobody subscribed."""
    log = []
    bus = ChannelStateBus(reread=lambda channel_id: log.append(channel_id))

    bus.publish("ch4")

    assert log == ["ch4"]


# ---------------------------------------------------------------------------
# Integration: the owner's actual bug, driven through the real seam
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'channel_state_bus.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(db_obj, channel_id: str, *, is_favorite: bool = False) -> None:
    from metatv.core.database import ChannelDB

    with db_obj.session_scope() as session:
        session.add(ChannelDB(
            id=channel_id, source_id=channel_id, provider_id="prov1",
            name="Test Movie", media_type="movie", is_favorite=is_favorite,
        ))


def test_toggle_rating_refreshes_details_pane_for_shown_channel(db):
    """The owner's bug, reproduced and fixed: calling _toggle_rating (as the
    Watch Queue's dislike action does) must drive the SAME authoritative
    re-read the details pane's own selection path uses, for the channel
    currently shown — proving the pane's buttons update without re-selecting.
    """
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-shown-in-pane"
    _make_channel(db, channel_id)

    host = make_channel_state_bus_host(db)

    host._toggle_rating(channel_id, -1)  # dislike, from a different surface

    assert len(host.details_pane.applied_states) == 1
    state = host.details_pane.applied_states[0]
    assert state.channel_id == channel_id
    assert state.rating == -1


def test_toggle_rating_clear_reflects_in_reread_state(db):
    """Clicking the already-active rating clears it — the re-read must reflect 0."""
    from tests.conftest import make_channel_state_bus_host

    channel_id = "ch-clear-rating"
    _make_channel(db, channel_id)

    host = make_channel_state_bus_host(db)
    host._toggle_rating(channel_id, 1)  # like
    host._toggle_rating(channel_id, 1)  # click again -> clears

    state = host.details_pane.applied_states[-1]
    assert state.channel_id == channel_id
    assert state.rating == 0


def test_bg_fetch_action_state_populates_is_favorite(db):
    """is_favorite survives the DTO round-trip: _bg_fetch_action_state on a
    favorited channel produces state.is_favorite is True."""
    from metatv.gui.main_window_metadata import _MetadataMixin
    from types import SimpleNamespace

    channel_id = "ch-fav"
    _make_channel(db, channel_id, is_favorite=True)

    captured = []
    host = SimpleNamespace()
    host.db = db
    host.config = SimpleNamespace(epg_link_blocklist=[])
    host._action_state_loaded = SimpleNamespace(emit=lambda state: captured.append(state))

    _MetadataMixin._bg_fetch_action_state(host, channel_id)

    assert len(captured) == 1
    assert captured[0].is_favorite is True


def test_bg_fetch_action_state_not_favorite(db):
    """Sanity check the flag isn't just always True."""
    from metatv.gui.main_window_metadata import _MetadataMixin
    from types import SimpleNamespace

    channel_id = "ch-not-fav"
    _make_channel(db, channel_id, is_favorite=False)

    captured = []
    host = SimpleNamespace()
    host.db = db
    host.config = SimpleNamespace(epg_link_blocklist=[])
    host._action_state_loaded = SimpleNamespace(emit=lambda state: captured.append(state))

    _MetadataMixin._bg_fetch_action_state(host, channel_id)

    assert captured[0].is_favorite is False
