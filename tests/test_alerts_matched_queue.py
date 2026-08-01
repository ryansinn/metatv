"""Behavioral tests for Slice 2C: the sidebar Watch Queue's "Alerts Matched"
section (topmost group) and its click-to-view-and-ack behavior.

Covers:
- ``vod_alert_availability.get_unviewed_matched_entries``: unions unviewed
  matches across rules (a channel matched by >1 rule counts once, with every
  matching keyword folded in), gates out disabled-source/hidden/orphaned ids,
  and resolves display fields from the stored ``detected_*`` columns.
- ``WatchQueueSection``: the Alerts Matched header + rows render as the
  TOPMOST group (ahead of Continue Watching/Never Watched); clicking a
  matched-channel row emits ``alertsMatchedClicked`` (not the plain
  ``itemSelected``); clicking a matched-series row emits
  ``alertsMatchedSeriesClicked``; the section does not fall back to the
  "Queue is empty" placeholder when only Alerts Matched has content.
- ``MainWindow._on_alerts_matched_clicked``: opens details AND marks the
  channel viewed across every alerting rule, then refreshes alert visibility
  once (reusing the existing chokepoint) — banner count and section can't
  disagree.
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


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


def _make_provider(session, provider_id: str = "p1", is_active: bool = True):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id, name="Test", type="xtream",
        url="http://test.example.com",
        urls='[{"url": "http://test.example.com", "primary": true}]',
        username="u", password="pw", is_active=is_active,
    )
    session.add(p)
    session.flush()
    return p


def _make_channel(session, channel_id: str, name: str, detected_title: str,
                   media_type: str = "movie", provider_id: str = "p1",
                   detected_year: str = "", detected_quality: str = "",
                   detected_prefix: str = "", is_hidden: bool = False):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=channel_id, source_id=channel_id, provider_id=provider_id,
        name=name, detected_title=detected_title, media_type=media_type,
        detected_year=detected_year, detected_quality=detected_quality,
        detected_prefix=detected_prefix, is_hidden=is_hidden,
    )
    session.add(ch)
    session.flush()
    return ch


def _make_config(tmp_path: Path):
    from metatv.core.config import Config
    return Config(config_dir=tmp_path / "cfg")


# ===========================================================================
# Part 1: get_unviewed_matched_entries
# ===========================================================================

class TestGetUnviewedMatchedEntries:

    def test_multi_rule_overlap_counted_once(self, tmp_path):
        """A channel matched by two rules yields ONE entry with both keywords."""
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.vod_alert_availability import get_unviewed_matched_entries

        db = _make_db(tmp_path)
        with db.session_scope() as s:
            _make_provider(s, "p1")
            _make_channel(s, "c1", "EN - Dune (2021)", "Dune", "movie", "p1")

        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "Dune", "match_type": "movie", "created": "r1"})
        cfg.add_vod_watch_alert({"text": "Denis", "match_type": "movie", "created": "r2"})
        cfg.record_vod_alert_match("r1", "c1")
        cfg.record_vod_alert_match("r2", "c1")

        with db.session_scope(commit=False) as s:
            entries = get_unviewed_matched_entries(cfg, RepositoryFactory(s))

        assert len(entries) == 1, "same channel matched by 2 rules must dedupe to one entry"
        e = entries[0]
        assert e.channel_id == "c1"
        assert set(e.rule_texts) == {"Dune", "Denis"}
        assert e.title == "Dune"
        assert e.media_type == "movie"

    def test_viewed_ids_excluded(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.vod_alert_availability import get_unviewed_matched_entries

        db = _make_db(tmp_path)
        with db.session_scope() as s:
            _make_provider(s, "p1")
            _make_channel(s, "c1", "Dune", "Dune", "movie", "p1")
            _make_channel(s, "c2", "Arrival", "Arrival", "movie", "p1")

        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "movie", "match_type": "any", "created": "r1"})
        cfg.record_vod_alert_match("r1", "c1")
        cfg.record_vod_alert_match("r1", "c2")
        cfg.mark_vod_alert_match_viewed("c1")  # c1 acknowledged — must drop out

        with db.session_scope(commit=False) as s:
            entries = get_unviewed_matched_entries(cfg, RepositoryFactory(s))

        ids = {e.channel_id for e in entries}
        assert ids == {"c2"}, "viewed channel must not appear in the unviewed set"

    def test_disabled_source_gated_out(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.vod_alert_availability import get_unviewed_matched_entries

        db = _make_db(tmp_path)
        with db.session_scope() as s:
            _make_provider(s, "pA", is_active=True)
            _make_provider(s, "pB", is_active=False)
            _make_channel(s, "c1", "Dune", "Dune", "movie", "pA")
            _make_channel(s, "c2", "Ghost", "Ghost", "movie", "pB")

        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "movie", "match_type": "any", "created": "r1"})
        cfg.record_vod_alert_match("r1", "c1")
        cfg.record_vod_alert_match("r1", "c2")

        with db.session_scope(commit=False) as s:
            entries = get_unviewed_matched_entries(cfg, RepositoryFactory(s))

        ids = {e.channel_id for e in entries}
        assert ids == {"c1"}, "match on a disabled-source channel must be gated out"

    def test_orphaned_id_skipped(self, tmp_path):
        """A stored match whose channel row no longer exists is silently dropped."""
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.vod_alert_availability import get_unviewed_matched_entries

        db = _make_db(tmp_path)
        with db.session_scope() as s:
            _make_provider(s, "p1")
            _make_channel(s, "c1", "Dune", "Dune", "movie", "p1")

        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "movie", "match_type": "any", "created": "r1"})
        cfg.record_vod_alert_match("r1", "c1")
        cfg.record_vod_alert_match("r1", "does-not-exist")

        with db.session_scope(commit=False) as s:
            entries = get_unviewed_matched_entries(cfg, RepositoryFactory(s))

        assert {e.channel_id for e in entries} == {"c1"}

    def test_no_rules_returns_empty(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.vod_alert_availability import get_unviewed_matched_entries

        db = _make_db(tmp_path)
        cfg = _make_config(tmp_path)
        with db.session_scope(commit=False) as s:
            assert get_unviewed_matched_entries(cfg, RepositoryFactory(s)) == []

    def test_fields_resolved_from_stored_detected_columns(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.vod_alert_availability import get_unviewed_matched_entries

        db = _make_db(tmp_path)
        with db.session_scope() as s:
            _make_provider(s, "p1")
            _make_channel(
                s, "c1", "EN - Severance (2022) 4K", "Severance", "series", "p1",
                detected_year="2022", detected_quality="4K", detected_prefix="EN",
            )

        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "Severance", "match_type": "series", "created": "r1"})
        cfg.record_vod_alert_match("r1", "c1")

        with db.session_scope(commit=False) as s:
            entries = get_unviewed_matched_entries(cfg, RepositoryFactory(s))

        assert len(entries) == 1
        e = entries[0]
        assert e.title == "Severance"
        assert e.media_type == "series"
        assert e.detected_year == "2022"
        assert e.detected_quality == "4K"
        assert e.detected_prefix == "EN"


# ===========================================================================
# Part 2: WatchQueueSection — Alerts Matched rendering + click routing
# ===========================================================================

class TestAlertsMatchedSectionRendering:

    def _make_matched_entry(self, channel_id="c1", title="Dune", media_type="movie",
                             rule_texts=("Dune",)):
        from metatv.core.vod_alert_availability import MatchedAlertEntry
        return MatchedAlertEntry(
            channel_id=channel_id, title=title, media_type=media_type,
            detected_year="2021", detected_quality="4K", detected_prefix="EN",
            rule_texts=tuple(rule_texts),
        )

    def _make_section(self):
        from PyQt6.QtWidgets import QListWidget
        from metatv.gui.sidebar.queue import WatchQueueSection
        from types import SimpleNamespace

        obj = WatchQueueSection.__new__(WatchQueueSection)
        obj._list = QListWidget()
        obj.config = SimpleNamespace(
            live_icon="L", movie_icon="M", series_icon="S", unknown_icon="?",
        )
        obj.set_empty = MagicMock()
        obj._has_unavailable = False
        obj.alertsMatchedClicked = MagicMock()
        obj.alertsMatchedSeriesClicked = MagicMock()
        obj.itemSelected = MagicMock()
        obj.itemDoubleClicked = MagicMock()
        obj.searchRequested = MagicMock()
        return obj

    def test_matched_section_is_topmost_group(self, qapp):
        obj = self._make_section()
        obj._alerts_matched = [self._make_matched_entry()]
        obj._alerts_matched_series = []
        obj._populate_rows([])  # empty queue — matched rows must still render

        texts = [obj._list.item(i).text() for i in range(obj._list.count())]
        assert any("Alerts Matched" in t for t in texts), texts
        # "Queue is empty" placeholder must NOT show — the matched rows ARE the surface.
        assert not any("Queue is empty" in t for t in texts), texts
        obj.set_empty.assert_called_with(False)

    def test_matched_channel_row_carries_role_and_tooltip(self, qapp):
        from PyQt6.QtCore import Qt
        from metatv.gui.sidebar.queue import _ROLE_ROW_KIND, _KIND_MATCHED_CHANNEL

        obj = self._make_section()
        obj._alerts_matched = [self._make_matched_entry(rule_texts=("masters",))]
        obj._alerts_matched_series = []
        obj._populate_rows([])

        # item(0) is the "Alerts Matched" header; item(1) is the matched row.
        item = obj._list.item(1)
        assert item.data(_ROLE_ROW_KIND) == _KIND_MATCHED_CHANNEL
        assert item.data(Qt.ItemDataRole.UserRole) == "c1"
        assert "masters" in item.toolTip()

    def test_click_on_matched_channel_emits_alertsMatchedClicked_not_itemSelected(self, qapp):
        obj = self._make_section()
        obj._alerts_matched = [self._make_matched_entry()]
        obj._alerts_matched_series = []
        obj._populate_rows([])

        item = obj._list.item(1)
        obj._on_selection_changed(item, None)

        obj.alertsMatchedClicked.emit.assert_called_once_with("c1")
        obj.itemSelected.emit.assert_not_called()

    def test_click_on_matched_series_emits_alertsMatchedSeriesClicked(self, qapp):
        obj = self._make_section()
        obj._alerts_matched = []
        obj._alerts_matched_series = [{
            "series_channel_id": "s1", "display_title": "My Show", "unseen_new": 3,
        }]
        obj._populate_rows([])

        item = obj._list.item(1)  # header, then the series row
        obj._on_selection_changed(item, None)

        obj.alertsMatchedSeriesClicked.emit.assert_called_once_with("s1")
        obj.itemSelected.emit.assert_not_called()

    def test_double_click_on_matched_row_does_not_play(self, qapp):
        obj = self._make_section()
        obj._alerts_matched = [self._make_matched_entry()]
        obj._alerts_matched_series = []
        obj._populate_rows([])

        item = obj._list.item(1)
        obj._on_double_click(item)

        obj.alertsMatchedClicked.emit.assert_called_once_with("c1")
        obj.itemDoubleClicked.emit.assert_not_called()
        obj.searchRequested.emit.assert_not_called()

    def test_no_matched_content_leaves_existing_behavior_unchanged(self, qapp):
        """Regression guard: no _alerts_matched/_alerts_matched_series set at all
        (legacy direct _populate_rows caller) must behave exactly as before."""
        obj = self._make_section()
        obj._populate_rows([])

        texts = [obj._list.item(i).text() for i in range(obj._list.count())]
        assert any("Queue is empty" in t for t in texts), texts
        assert not any("Alerts Matched" in t for t in texts), texts


# ===========================================================================
# Part 3: MainWindow._on_alerts_matched_clicked
# ===========================================================================

class TestOnAlertsMatchedClicked:

    def _stub(self, cfg, **extra):
        base = dict(
            config=cfg,
            show_channel_details_by_id=MagicMock(),
            _refresh_alert_visibility=MagicMock(),
        )
        base.update(extra)
        return types.SimpleNamespace(**base)

    def test_opens_details_and_marks_viewed_and_refreshes(self, tmp_path, qapp):
        from metatv.gui.main_window import MainWindow

        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "Dune", "match_type": "movie", "created": "r1"})
        cfg.record_vod_alert_match("r1", "c1")

        stub = self._stub(cfg)
        MainWindow._on_alerts_matched_clicked(stub, "c1")

        stub.show_channel_details_by_id.assert_called_once_with("c1")
        assert cfg.is_vod_match_unviewed("c1") is False, "must mark the match viewed"
        stub._refresh_alert_visibility.assert_called_once()

    def test_already_viewed_still_opens_details_but_skips_refresh(self, tmp_path, qapp):
        from metatv.gui.main_window import MainWindow

        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "Dune", "match_type": "movie", "created": "r1"})
        cfg.record_vod_alert_match("r1", "c1")
        cfg.mark_vod_alert_match_viewed("c1")  # already viewed

        stub = self._stub(cfg)
        MainWindow._on_alerts_matched_clicked(stub, "c1")

        stub.show_channel_details_by_id.assert_called_once_with("c1")
        stub._refresh_alert_visibility.assert_not_called()
