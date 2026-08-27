"""A destructive action is never one click away.

The header now shows a section's only action directly instead of hiding it
behind a ⋯ — which is right for Refresh and wrong for Clear History. Promoting
it put a data-destroying button a quarter-inch from the count, and the count is
something you click. Owner: "wouldn't be hard to accidently click it ... that
delete history should be behind the ... like the watch queue history."

So ``SectionAction.destructive`` is never promoted, whatever else is true. The
⋯ is the deliberate step; the confirmation dialog is the second.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.config import Config
from metatv.gui.sidebar.base import SectionAction


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class TestWhatGetsPromoted:

    def _button(self, qapp, tmp_path, actions):
        from metatv.gui.sidebar.recommended import RecommendedSection

        sec = RecommendedSection(Config(config_dir=tmp_path), MagicMock())
        return sec, sec.build_overflow_button(actions)

    def test_a_lone_safe_action_is_shown_directly(self, qapp, tmp_path):
        sec, btn = self._button(qapp, tmp_path, [
            SectionAction("Refresh", "Recompute", lambda: None, icon="refresh"),
        ])
        assert sec._overflow_menu is None, "a single safe action should not need a menu"
        assert not btn.icon().isNull()
        assert btn.toolTip() == "Recompute"

    def test_a_lone_DESTRUCTIVE_action_is_not(self, qapp, tmp_path):
        """The whole point."""
        sec, btn = self._button(qapp, tmp_path, [
            SectionAction("Clear all history", "Remove everything",
                          lambda: None, icon="clear_all", destructive=True),
        ])
        assert sec._overflow_menu is not None, (
            "a destructive action was promoted to a one-click header button"
        )
        assert len(sec._overflow_menu.actions()) == 1
        assert btn.toolTip() == "More…"

    def test_two_actions_always_get_the_menu(self, qapp, tmp_path):
        sec, _ = self._button(qapp, tmp_path, [
            SectionAction("A", "a", lambda: None, icon="refresh"),
            SectionAction("B", "b", lambda: None, icon="refresh"),
        ])
        assert sec._overflow_menu is not None
        assert len(sec._overflow_menu.actions()) == 2

    def test_an_action_without_an_icon_is_not_promoted(self, qapp, tmp_path):
        """Declaring an icon is how a section opts IN to promotion."""
        sec, _ = self._button(qapp, tmp_path, [
            SectionAction("Something", "does a thing", lambda: None),
        ])
        assert sec._overflow_menu is not None


class TestTheRealSectionsDeclareThemselvesHonestly:

    def test_history_keeps_both_clears_behind_the_menu(self, qapp, tmp_path):
        from metatv.gui.sidebar.history import HistorySection

        sec = HistorySection(Config(config_dir=tmp_path), MagicMock())
        actions = sec.overflow_actions()
        assert len(actions) == 2
        assert all(a.destructive for a in actions), (
            "a history clear that is not marked destructive can be promoted"
        )
        assert sec._overflow_menu is not None

    def test_the_queue_clears_are_destructive_too(self, qapp, tmp_path):
        from metatv.gui.sidebar.queue import WatchQueueSection

        sec = WatchQueueSection(Config(config_dir=tmp_path), MagicMock())
        assert all(a.destructive for a in sec.overflow_actions())

    def test_refresh_is_not_destructive(self, qapp, tmp_path):
        from metatv.gui.sidebar.recommended import RecommendedSection

        sec = RecommendedSection(Config(config_dir=tmp_path), MagicMock())
        actions = sec.overflow_actions()
        assert len(actions) == 1
        assert not actions[0].destructive and actions[0].icon


class TestClearingOnlyTheOldEntries:
    """Owner: "people aren't wiping history daily ... add a second wipe history
    option that wipes history older than a month"."""

    @staticmethod
    def _db(tmp_path):
        from metatv.core.database import Database

        db = Database(f"sqlite:///{tmp_path / 'hist.db'}")   # a real file, not :memory:
        db.create_tables()
        return db

    @staticmethod
    def _channel(session, cid, days_ago):
        from metatv.core.database import ChannelDB

        session.add(ChannelDB(
            id=cid, provider_id="p1", name=cid, source_id="s1",
            last_played=datetime.utcnow() - timedelta(days=days_ago),
            play_count=3,
        ))

    def test_it_keeps_what_is_newer_and_forgets_what_is_older(self, tmp_path):
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        db = self._db(tmp_path)
        with db.session_scope() as s:
            self._channel(s, "old", 90)
            self._channel(s, "borderline", 31)
            self._channel(s, "recent", 3)

        with db.session_scope() as s:
            cleared = RepositoryFactory(s).channels.clear_history_older_than(30)
        assert cleared == 2, cleared

        with db.session_scope(commit=False) as s:
            rows = {c.id: c for c in s.query(ChannelDB).all()}
            assert rows["old"].last_played is None
            assert rows["borderline"].last_played is None
            assert rows["recent"].last_played is not None, (
                "it cleared something inside the window it promised to keep"
            )
            assert rows["recent"].play_count == 3

    def test_untouched_when_nothing_is_old_enough(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory

        db = self._db(tmp_path)
        with db.session_scope() as s:
            self._channel(s, "recent", 2)
        with db.session_scope() as s:
            assert RepositoryFactory(s).channels.clear_history_older_than(30) == 0

    def test_a_channel_never_played_is_ignored(self, tmp_path):
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        db = self._db(tmp_path)
        with db.session_scope() as s:
            s.add(ChannelDB(id="never", provider_id="p1", name="never",
                            source_id="s1"))
        with db.session_scope() as s:
            assert RepositoryFactory(s).channels.clear_history_older_than(30) == 0
