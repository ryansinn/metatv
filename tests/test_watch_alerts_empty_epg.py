"""A configured watch alert must never render as an absent feature.

The bug the owner hit: "epg section is totally missing from alert watch now",
then "it appears when making changes to epg watch items and then disappears
immediately". Seven alerts were configured and working. What had happened is
that the provider's guide ran out of programmes to START — the last one began
at 10:38 and the watchlist query correctly returned nothing — and
``_populate_rows`` responded by hiding the EPG group outright. The loading row
revealed the group, the empty result hid it again, and a healthy watchlist was
indistinguishable from a broken one.

So the group now disappears ONLY when there is nothing to hold a place for (no
patterns / no EPG source). A configured watchlist keeps its heading and says
which nothing it is looking at.

Each test targets one leg: restore ``_hide_epg_subsection()`` on the populated-
but-empty branch and the first class goes red; drop ``has_future_programmes``
and the last class does.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from metatv.gui.sidebar.alerts import WatchAlertsSection


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _section(qapp, tmp_path, patterns):
    """A real section, SHOWN — ``isVisible()`` is false for any unshown widget,
    so an unshown section would pass every assertion here for the wrong reason.
    """
    from metatv.core.config import Config

    cfg = Config(config_dir=tmp_path)
    cfg.epg_watchlist_patterns = list(patterns)
    section = WatchAlertsSection(cfg, MagicMock())
    section.resize(300, 240)
    section.show()
    qapp.processEvents()
    return section


def _empty(reason):
    return {"live_groups": {}, "upcoming_only": {}, "empty_reason": reason}


class TestConfiguredWatchlistHoldsItsPlace:
    """Seven alerts and nothing airing is a state, not an absence."""

    @pytest.mark.parametrize(
        "reason",
        [WatchAlertsSection.EPG_EMPTY_NO_MATCHES,
         WatchAlertsSection.EPG_EMPTY_GUIDE_ENDED],
    )
    def test_heading_and_tree_stay_on_screen(self, qapp, tmp_path, reason):
        section = _section(qapp, tmp_path, ["Stargate SG-1"] * 7)
        try:
            # The app's real order: the loading row reveals the group, THEN the
            # empty payload lands. This is the flash the owner described.
            section.show_loading(section.alerts_tree, "Loading alerts…")
            qapp.processEvents()
            section._populate_rows(_empty(reason))
            qapp.processEvents()

            assert section._epg_hdr_container.isVisible(), (
                "the EPG heading vanished on an empty-but-configured watchlist"
            )
            assert section.alerts_tree.isVisible()
            assert section.alerts_tree.topLevelItemCount() == 1
        finally:
            section.setParent(None)
            section.deleteLater()
            qapp.processEvents()

    def test_the_notice_explains_itself_on_hover(self, qapp, tmp_path):
        section = _section(qapp, tmp_path, ["Stargate SG-1"] * 7)
        try:
            section._populate_rows(_empty(WatchAlertsSection.EPG_EMPTY_GUIDE_ENDED))
            item = section.alerts_tree.topLevelItem(0)
            assert item.toolTip(0), "the notice row carries no explanation"
            # Not selectable: it is a sentence, not a programme.
            from PyQt6.QtCore import Qt
            assert item.flags() == Qt.ItemFlag.NoItemFlags
        finally:
            section.setParent(None)
            section.deleteLater()
            qapp.processEvents()

    def test_a_notice_is_not_counted_as_a_programme(self, qapp, tmp_path):
        """The heading chip must stay empty — "EPG 1 / Nothing airing" is a lie.

        And it must stay empty across a collapse, which is where re-deriving the
        count from ``topLevelItemCount()`` would resurrect the 1.
        """
        section = _section(qapp, tmp_path, ["Stargate SG-1"] * 7)
        try:
            section._populate_rows(_empty(WatchAlertsSection.EPG_EMPTY_NO_MATCHES))
            qapp.processEvents()
            assert section._epg_toggle.count_label.text() == ""
            section._toggle_epg()          # collapse
            qapp.processEvents()
            assert section._epg_toggle.count_label.text() == ""
        finally:
            section.setParent(None)
            section.deleteLater()
            qapp.processEvents()


class TestNothingConfiguredStaysSilent:
    """No alerts set up means no promise outstanding — say nothing."""

    @pytest.mark.parametrize(
        "reason",
        [WatchAlertsSection.EPG_EMPTY_NO_PATTERNS,
         WatchAlertsSection.EPG_EMPTY_NO_SOURCE],
    )
    def test_heading_is_hidden(self, qapp, tmp_path, reason):
        section = _section(qapp, tmp_path, [])
        try:
            section.show_loading(section.alerts_tree, "Loading alerts…")
            qapp.processEvents()
            section._populate_rows(_empty(reason))
            qapp.processEvents()
            assert not section._epg_hdr_container.isVisible()
            assert not section.alerts_tree.isVisible()
        finally:
            section.setParent(None)
            section.deleteLater()
            qapp.processEvents()

    def test_both_silent_reasons_are_declared_silent(self):
        assert WatchAlertsSection.EPG_EMPTY_SILENT == frozenset(
            {WatchAlertsSection.EPG_EMPTY_NO_PATTERNS,
             WatchAlertsSection.EPG_EMPTY_NO_SOURCE}
        )


class TestTheTwoNothingsReadDifferently:
    """A quiet watchlist and a dead guide need different words."""

    def test_messages_differ_and_the_quiet_one_names_the_count(self, tmp_path):
        from metatv.core.config import Config

        cfg = Config(config_dir=tmp_path)
        cfg.epg_watchlist_patterns = ["a", "b", "c"]
        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.config = cfg

        quiet_icon, quiet, quiet_tip = section._epg_empty_notice(
            WatchAlertsSection.EPG_EMPTY_NO_MATCHES)
        dead_icon, dead, dead_tip = section._epg_empty_notice(
            WatchAlertsSection.EPG_EMPTY_GUIDE_ENDED)

        assert quiet != dead
        assert "3" in quiet, "a quiet watchlist should show its rules are loaded"
        assert quiet_tip and dead_tip and quiet_tip != dead_tip

        # Both glyphs come from icons.py — not a literal, and not a key that
        # already belongs to another role (``epg_indicator_icon`` is the
        # freshness square). The dead guide takes the warning glyph because it
        # is the actionable one; a quiet watchlist must NOT, or a working
        # feature looks like a fault.
        from metatv.gui import icons as _icons

        assert dead_icon == _icons.notification_warning_icon
        assert quiet_icon == _icons.info_icon
        assert quiet_icon != dead_icon
        assert _icons.epg_indicator_icon not in (quiet_icon, dead_icon)


class TestGuideCoverageIsMeasuredByStarts:
    """A long final programme is not the same as remaining coverage."""

    @staticmethod
    def _db(tmp_path):
        # A real file DB, not :memory: — session_scope work needs one.
        from metatv.core.database import Database
        db = Database(f"sqlite:///{tmp_path / 'epg.db'}")
        db.create_tables()
        return db

    @staticmethod
    def _add(session, *, start, stop, pid="p1"):
        from metatv.core.database import EpgProgramDB
        session.add(EpgProgramDB(
            provider_id=pid, channel_epg_id="c.epg", channel_db_id="c1",
            channel_name="Chan", title="Something",
            start_time=start, stop_time=stop,
        ))

    def test_a_programme_still_running_is_not_future_coverage(self, tmp_path):
        """The owner's exact state: the guide's last entry started this morning
        and runs for hours, so max(stop_time) sits in the future while nothing
        new can begin. That gap is what let a dead guide look healthy.
        """
        from metatv.core.repositories.epg import EpgRepository
        from metatv.core.epg_utils import now_utc

        db = self._db(tmp_path)
        now = now_utc()
        with db.session_scope() as s:
            self._add(s, start=now - timedelta(hours=1), stop=now + timedelta(hours=9))
        with db.session_scope(commit=False) as s:
            assert EpgRepository(s).has_future_programmes(["p1"]) is False

    def test_a_programme_yet_to_start_is(self, tmp_path):
        from metatv.core.repositories.epg import EpgRepository
        from metatv.core.epg_utils import now_utc

        db = self._db(tmp_path)
        now = now_utc()
        with db.session_scope() as s:
            self._add(s, start=now + timedelta(minutes=20), stop=now + timedelta(hours=1))
        with db.session_scope(commit=False) as s:
            assert EpgRepository(s).has_future_programmes(["p1"]) is True

    def test_another_source_does_not_count_as_coverage(self, tmp_path):
        from metatv.core.repositories.epg import EpgRepository
        from metatv.core.epg_utils import now_utc

        db = self._db(tmp_path)
        now = now_utc()
        with db.session_scope() as s:
            self._add(s, start=now + timedelta(hours=2), stop=now + timedelta(hours=3),
                      pid="other")
        with db.session_scope(commit=False) as s:
            repo = EpgRepository(s)
            assert repo.has_future_programmes(["p1"]) is False
            assert repo.has_future_programmes([]) is False
