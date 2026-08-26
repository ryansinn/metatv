"""Behavioral tests for Wave 3 "queue click semantics" — owner-reported fix:

    "double clicking on a series does not browse the series it just loads the
    series information into the details panel [...] Double left click should
    browse the content in the case of series or items that have layers, and
    for movies double left click should play the content. Movies definitely
    should have a right click context menu as well [under Alerts Matched]."

Covers:
- WatchQueueSection UserRole payload harmonization: every row kind (channel,
  episode, matched_channel, matched_series) carries the SAME grain-dict
  shape — ``{"grain": ..., "channel_id": ...}`` (+ ``episode_id`` for
  episode-grain rows). Previously matched rows carried a bare id plus a
  separate ``_ROLE_ROW_KIND`` data role — a known trap flagged in review.
- Double-click routing: matched_channel rows both ack (mark viewed, same as
  single-click) AND now ALSO navigate/play through the same
  ``itemDoubleClicked`` chokepoint a plain queue row already uses; matched_
  series rows navigate only (drilling in is itself the "seen" ack).
- Context menu: matched_channel rows now get the standard "queue" surface
  registry menu (previously none at all); matched_series rows get a small
  hand-rolled Open series / Mark seen menu, built (never exec'd, so no
  mark-viewed side effect) via ``_build_matched_series_menu``.
- ``MainWindow.play_queue_item_id``: the shared chokepoint both plain queue
  rows and (now) Alerts Matched rows double-click through — a series drills
  in (``drill_into_series``), a movie/live leaf plays (``play_media``), with
  the channel's real ``provider_id`` threaded through via the DB-resolved DTO.
- ``MainWindow._on_mark_series_seen``: uses the composite
  ``_refresh_alert_visibility`` chokepoint (not the narrower
  ``_refresh_vod_alerts_section``) so the Watch Queue's own Alerts Matched
  matched-series badge clears too, not just the separate Watch Alerts
  section's list.
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tests.conftest import sidebar_config


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# DB helpers (file-backed — a :memory: DB is a fresh empty DB per connection)
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_tables()
    return db


def _make_provider(session, provider_id: str = "p1"):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id, name="Test", type="xtream",
        url="http://test.example.com",
        urls='[{"url": "http://test.example.com", "primary": true}]',
        username="u", password="pw", is_active=True,
    )
    p_session = session
    p_session.add(p)
    p_session.flush()
    return p


def _make_channel(session, channel_id: str, name: str, media_type: str = "movie",
                   provider_id: str = "p1", stream_url: str = "http://s.example.com/x.m3u8"):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=channel_id, source_id=channel_id, provider_id=provider_id,
        name=name, detected_title=name, media_type=media_type,
        stream_url=stream_url,
    )
    session.add(ch)
    session.flush()
    return ch


def _section_stub():
    """A bare WatchQueueSection with just the list widget + a stub config —
    the same technique tests/test_alerts_matched_queue.py already uses."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.queue import WatchQueueSection
    from types import SimpleNamespace

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = sidebar_config()
    obj._has_unavailable = False
    obj.alertsMatchedClicked = MagicMock()
    obj.alertsMatchedSeriesClicked = MagicMock()
    obj.alertsMatchedSeriesMarkSeenRequested = MagicMock()
    obj.itemSelected = MagicMock()
    obj.itemDoubleClicked = MagicMock()
    obj.episodeActivated = MagicMock()
    obj.searchRequested = MagicMock()
    obj.channelContextMenuRequested = MagicMock()
    return obj


def _entry(**over):
    """One queue entry stub, with EVERY field ``_add_entry_item`` reads.

    Seven inline ``SimpleNamespace``s said the same thing seven ways, and five
    of them omitted ``season_num``/``episode_num`` — which was fine right up
    until the row builder started reading them, at which point all five raised
    ``AttributeError`` at once. A real ``QueueEntry`` defaults them to None;
    this stub does too, so the double and the thing it stands for agree.
    """
    base = dict(
        is_episode=False, episode_id=None, channel_id="c1", channel_name="Movie",
        media_type="movie", available=True, search_title="Movie",
        season_num=None, episode_num=None, episode_title=None,
        detected_year="", detected_quality="", detected_prefix="",
    )
    base.update(over)
    return types.SimpleNamespace(**base)


# ===========================================================================
# Part 1: UserRole payload harmonization — one shape, every row kind
# ===========================================================================

class TestPayloadHarmonization:

    def test_channel_grain_movie_payload_and_tooltip(self, qapp):
        from PyQt6.QtCore import Qt
        obj = _section_stub()
        entry = _entry(channel_id="c1")
        obj._add_entry_item(entry)
        item = obj._list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == {
            "grain": "channel", "channel_id": "c1",
        }
        assert item.toolTip() == "Double-click to play"

    def test_channel_grain_series_payload_and_tooltip(self, qapp):
        from PyQt6.QtCore import Qt
        obj = _section_stub()
        entry = _entry(channel_id="s1", channel_name="Show",
                       media_type="series", search_title="Show")
        obj._add_entry_item(entry)
        item = obj._list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == {
            "grain": "channel", "channel_id": "s1",
        }
        assert item.toolTip() == "Double-click to browse the series"

    def test_unavailable_row_keeps_recovery_tooltip_not_the_hint(self, qapp):
        """Unavailable rows keep the existing recovery tooltip — the new
        double-click hint must not clobber it."""
        from PyQt6.QtCore import Qt
        obj = _section_stub()
        entry = _entry(channel_id="c1", available=False)
        obj._add_entry_item(entry)
        item = obj._list.item(0)
        assert "another source" in item.toolTip()
        assert "Double-click to" not in item.toolTip()

    def test_episode_grain_payload_and_tooltip_says_play(self, qapp):
        """Episode rows always say 'play' — double-click plays the specific
        queued episode directly, never drills further (there is no further
        layer under an episode)."""
        from PyQt6.QtCore import Qt
        obj = _section_stub()
        entry = _entry(is_episode=True, episode_id="e1", channel_id="s1",
                       channel_name="Show", media_type="series",
                       search_title="Show", season_num=1, episode_num=2,
                       episode_title="Pilot")
        obj._add_entry_item(entry)
        item = obj._list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == {
            "grain": "episode", "episode_id": "e1", "channel_id": "s1",
        }
        assert item.toolTip() == "Double-click to play"

    def test_matched_channel_payload_shape(self, qapp):
        from PyQt6.QtCore import Qt
        from metatv.core.vod_alert_availability import MatchedAlertEntry
        obj = _section_stub()
        m = MatchedAlertEntry(
            channel_id="c2", title="Dune", media_type="movie",
            detected_year="2021", detected_quality="4K", detected_prefix="EN",
            rule_texts=("Dune",),
        )
        obj._add_matched_channel_item(m)
        item = obj._list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == {
            "grain": "matched_channel", "channel_id": "c2",
        }
        assert "double-click to play" in item.toolTip()

    def test_matched_channel_series_payload_tooltip_says_browse(self, qapp):
        from metatv.core.vod_alert_availability import MatchedAlertEntry
        obj = _section_stub()
        m = MatchedAlertEntry(
            channel_id="c3", title="Severance", media_type="series",
            detected_year="2022", detected_quality="4K", detected_prefix="EN",
            rule_texts=("Severance",),
        )
        obj._add_matched_channel_item(m)
        item = obj._list.item(0)
        assert "double-click to browse the series" in item.toolTip()

    def test_matched_series_payload_shape(self, qapp):
        from PyQt6.QtCore import Qt
        obj = _section_stub()
        obj._add_matched_series_item({
            "series_channel_id": "s2", "display_title": "My Show", "unseen_new": 2,
        })
        item = obj._list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == {
            "grain": "matched_series", "channel_id": "s2",
        }
        assert "double-click to browse the series" in item.toolTip()


# ===========================================================================
# Part 2: Double-click routing
# ===========================================================================

class TestDoubleClickRouting:

    def _matched_channel_item(self, obj, media_type="movie"):
        from metatv.core.vod_alert_availability import MatchedAlertEntry
        m = MatchedAlertEntry(
            channel_id="c1", title="Dune", media_type=media_type,
            detected_year="2021", detected_quality="4K", detected_prefix="EN",
            rule_texts=("Dune",),
        )
        obj._add_matched_channel_item(m)
        return obj._list.item(0)

    def test_matched_channel_movie_double_click_acks_and_navigates(self, qapp):
        obj = _section_stub()
        item = self._matched_channel_item(obj, media_type="movie")

        obj._on_double_click(item)

        # Ack (mark viewed, same effect as single-click) ...
        obj.alertsMatchedClicked.emit.assert_called_once_with("c1")
        # ... AND now also routes through the play/navigate chokepoint.
        obj.itemDoubleClicked.emit.assert_called_once_with("c1")

    def test_matched_channel_series_double_click_acks_and_navigates(self, qapp):
        """A matched CHANNEL row can itself be a series (a keyword match on a
        show title) — double-click must still both ack and route through the
        same chokepoint; the host (play_queue_item_id) is what resolves
        movie-vs-series, not the sidebar section."""
        obj = _section_stub()
        item = self._matched_channel_item(obj, media_type="series")

        obj._on_double_click(item)

        obj.alertsMatchedClicked.emit.assert_called_once_with("c1")
        obj.itemDoubleClicked.emit.assert_called_once_with("c1")

    def test_matched_series_double_click_navigates_no_separate_ack(self, qapp):
        """A matched_series (monitored-series) row: double-click routes through
        the navigate chokepoint only — no alertsMatchedSeriesClicked emission,
        since drilling in itself clears unseen_new (host-side)."""
        obj = _section_stub()
        obj._add_matched_series_item({
            "series_channel_id": "s1", "display_title": "My Show", "unseen_new": 3,
        })
        item = obj._list.item(0)

        obj._on_double_click(item)

        obj.itemDoubleClicked.emit.assert_called_once_with("s1")
        obj.alertsMatchedSeriesClicked.emit.assert_not_called()
        obj.alertsMatchedSeriesMarkSeenRequested.emit.assert_not_called()

    def test_plain_channel_row_double_click_unchanged(self, qapp):
        """Regression guard: plain (non-matched) queue channel rows keep their
        existing single-signal double-click behavior — no ack signal exists
        for them, so only itemDoubleClicked should fire."""
        obj = _section_stub()
        entry = _entry(channel_id="c9")
        obj._add_entry_item(entry)
        item = obj._list.item(0)

        obj._on_double_click(item)

        obj.itemDoubleClicked.emit.assert_called_once_with("c9")
        obj.alertsMatchedClicked.emit.assert_not_called()

    def test_plain_episode_row_double_click_plays_episode(self, qapp):
        obj = _section_stub()
        entry = _entry(is_episode=True, episode_id="e1", channel_id="s1",
                       channel_name="Show", media_type="series",
                       search_title="Show", season_num=1, episode_num=2,
                       episode_title="Pilot")
        obj._add_entry_item(entry)
        item = obj._list.item(0)

        obj._on_double_click(item)

        obj.episodeActivated.emit.assert_called_once_with("e1")
        obj.itemDoubleClicked.emit.assert_not_called()

    def test_unavailable_row_double_click_still_searches(self, qapp):
        """Regression guard: unavailable-row recovery search must still work
        after the payload-harmonization rewrite."""
        obj = _section_stub()
        entry = _entry(channel_id="c1", available=False,
                       search_title="Movie Title")
        obj._add_entry_item(entry)
        item = obj._list.item(0)

        obj._on_double_click(item)

        obj.searchRequested.emit.assert_called_once_with("Movie Title")
        obj.itemDoubleClicked.emit.assert_not_called()


# ===========================================================================
# Part 3: Context menu
# ===========================================================================

class TestContextMenu:

    def test_matched_channel_row_gets_registry_menu(self, qapp):
        """Matched CHANNEL rows now reach _show_channel_menu via the same
        channelContextMenuRequested signal a plain queue row uses (previously:
        an early return, no menu at all)."""
        from PyQt6.QtCore import QPoint
        from metatv.core.vod_alert_availability import MatchedAlertEntry

        obj = _section_stub()
        m = MatchedAlertEntry(
            channel_id="c1", title="Dune", media_type="movie",
            detected_year="2021", detected_quality="4K", detected_prefix="EN",
            rule_texts=("Dune",),
        )
        obj._add_matched_channel_item(m)
        item = obj._list.item(0)
        rect = obj._list.visualItemRect(item)

        obj._on_context_menu(rect.center())

        assert obj.channelContextMenuRequested.emit.call_count == 1
        args = obj.channelContextMenuRequested.emit.call_args[0]
        assert args[0] == "c1"

    def test_matched_series_row_gets_open_and_mark_seen_menu(self, qapp):
        """Matched SERIES rows get a dedicated (non-registry) menu with at
        least Open series + Mark seen — never the empty early-return, and
        never a registry channelContextMenuRequested emission (a monitored
        series entry isn't a ChannelDB-row-shaped context)."""
        obj = _section_stub()
        obj._add_matched_series_item({
            "series_channel_id": "s1", "display_title": "My Show", "unseen_new": 3,
        })
        item = obj._list.item(0)

        menu = obj._build_matched_series_menu("s1")
        labels = [a.text() for a in menu.actions()]

        assert any("Open series" in t for t in labels)
        assert any("Mark seen" in t for t in labels)
        obj.channelContextMenuRequested.emit.assert_not_called()

    def test_matched_series_menu_open_action_navigates(self, qapp):
        """Triggering "Open series" reuses the SAME navigate chokepoint as
        double-click — no parallel play/drill path."""
        obj = _section_stub()
        menu = obj._build_matched_series_menu("s1")
        open_action = next(a for a in menu.actions() if "Open series" in a.text())

        open_action.trigger()

        obj.itemDoubleClicked.emit.assert_called_once_with("s1")

    def test_matched_series_menu_mark_seen_action_emits_request(self, qapp):
        obj = _section_stub()
        menu = obj._build_matched_series_menu("s1")
        seen_action = next(a for a in menu.actions() if "Mark seen" in a.text())

        seen_action.trigger()

        obj.alertsMatchedSeriesMarkSeenRequested.emit.assert_called_once_with("s1")

    def test_building_matched_series_menu_never_marks_viewed(self, qapp):
        """Merely building (opening) the menu must not mark anything viewed —
        only an explicit action does."""
        obj = _section_stub()
        obj._build_matched_series_menu("s1")

        obj.alertsMatchedSeriesMarkSeenRequested.emit.assert_not_called()
        obj.itemDoubleClicked.emit.assert_not_called()


# ===========================================================================
# Part 4: MainWindow.play_queue_item_id — the shared navigate/play chokepoint
# ===========================================================================

class TestPlayQueueItemIdBranching:
    """This is the SAME chokepoint a plain queue row's double-click already
    used (main_window.py: section.itemDoubleClicked.connect(play_queue_item_id))
    — Alerts Matched rows now double-click through it too, so its branching
    behavior is exactly what the owner-reported fix depends on."""

    def _stub(self, db):
        from metatv.gui.main_window_favorites import _FavoritesMixin
        host = types.SimpleNamespace(
            db=db,
            drill_into_series=MagicMock(),
            play_media=MagicMock(),
        )
        # Bind the real unbound method so `self` resolves via the stub.
        host.play_queue_item_id = types.MethodType(
            _FavoritesMixin.play_queue_item_id, host
        )
        return host

    def test_movie_channel_plays_with_real_provider_id(self, tmp_path, qapp):
        db = _make_db(tmp_path)
        with db.session_scope() as s:
            _make_provider(s, "pA")
            _make_channel(s, "c1", "Dune", media_type="movie", provider_id="pA")

        host = self._stub(db)
        host.play_queue_item_id("c1")

        host.drill_into_series.assert_not_called()
        host.play_media.assert_called_once()
        played = host.play_media.call_args[0][0]
        assert played.id == "c1"
        assert played.provider_id == "pA", "provider_id must thread through for Split Streams keying"

    def test_series_channel_drills_in_instead_of_playing(self, tmp_path, qapp):
        db = _make_db(tmp_path)
        with db.session_scope() as s:
            _make_provider(s, "pB")
            _make_channel(s, "s1", "Severance", media_type="series", provider_id="pB")

        host = self._stub(db)
        host.play_queue_item_id("s1")

        host.play_media.assert_not_called()
        host.drill_into_series.assert_called_once()
        drilled = host.drill_into_series.call_args[0][0]
        assert drilled.id == "s1"
        assert drilled.provider_id == "pB"

    def test_missing_channel_is_a_noop(self, tmp_path, qapp):
        db = _make_db(tmp_path)
        host = self._stub(db)

        host.play_queue_item_id("does-not-exist")

        host.play_media.assert_not_called()
        host.drill_into_series.assert_not_called()


# ===========================================================================
# Part 5: MainWindow._on_mark_series_seen — composite refresh chokepoint
# ===========================================================================

class TestOnMarkSeriesSeen:

    def _make_config(self, tmp_path):
        from metatv.core.config import Config
        return Config(config_dir=tmp_path / "cfg")

    def test_clears_unseen_and_uses_composite_refresh(self, tmp_path, qapp):
        from metatv.gui.main_window import MainWindow

        cfg = self._make_config(tmp_path)
        cfg.add_monitored_series({
            "series_channel_id": "s1", "source_id": "src1", "provider_id": "p1",
            "title": "Show", "baselines": {}, "unseen_new": 3, "last_checked": None,
        })

        stub = types.SimpleNamespace(
            config=cfg,
            _refresh_alert_visibility=MagicMock(),
        )
        MainWindow._on_mark_series_seen(stub, "s1")

        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 0
        stub._refresh_alert_visibility.assert_called_once()
