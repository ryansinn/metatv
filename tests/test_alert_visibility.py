"""Behavioral tests for the alert-visibility system (new matched content is
VISIBLE & PERSISTENT).

The single source of truth is the per-match "viewed" flag stored in
``Config.vod_watch_alerts`` as ``viewed_ids`` (subset of ``alerted_ids``).  A
channel is an UNVIEWED match iff it is alerted but not yet viewed; clearing it
(per-item or bulk) flips viewed → green-off on every surface.

Covers:
- Config source of truth: a new match is unviewed; mark-viewed (single + bulk)
  clears it; the count reflects unviewed only; the pre-feature migration seeds
  existing matches as viewed.
- Details Alert button greens for an unviewed match and clears when viewed.
- Channel-list rows get the 🚨 marker + green title for unviewed matches, and
  drop them when the match is cleared.
- The channel-menu registry shows "Clear alert" only for an unviewed match.
- Sidebar Alerts header badge + Watch Queue pinned line reflect the count.
"""

from __future__ import annotations

import pytest

from metatv.core.config import Config
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _rule(created: str, *, text: str = "Dune", match_type: str = "any",
          alerted=None, viewed=None) -> dict:
    r = {"text": text, "match_type": match_type, "created": created,
         "alerted_ids": list(alerted or [])}
    if viewed is not None:
        r["viewed_ids"] = list(viewed)
    return r


# ===========================================================================
# Part 1: Config — per-match "viewed" source of truth
# ===========================================================================

class TestViewedSourceOfTruth:

    def test_new_match_is_unviewed(self):
        cfg = Config()
        cfg.add_vod_watch_alert(_rule("t1"))
        cfg.record_vod_alert_match("t1", "chA")
        assert cfg.is_vod_match_unviewed("chA")
        assert cfg.get_unviewed_vod_match_ids() == {"chA"}
        assert cfg.get_unviewed_vod_match_count() == 1

    def test_mark_single_viewed_clears_green(self):
        cfg = Config()
        cfg.add_vod_watch_alert(_rule("t1"))
        cfg.record_vod_alert_match("t1", "chA")
        changed = cfg.mark_vod_alert_match_viewed("chA")
        assert changed is True
        assert not cfg.is_vod_match_unviewed("chA")
        assert cfg.get_unviewed_vod_match_count() == 0
        # idempotent — already-viewed is a no-op
        assert cfg.mark_vod_alert_match_viewed("chA") is False

    def test_count_reflects_unviewed_only(self):
        cfg = Config()
        cfg.add_vod_watch_alert(_rule("t1"))
        for cid in ("chA", "chB", "chC"):
            cfg.record_vod_alert_match("t1", cid)
        assert cfg.get_unviewed_vod_match_count() == 3
        cfg.mark_vod_alert_match_viewed("chB")
        assert cfg.get_unviewed_vod_match_count() == 2
        assert cfg.get_unviewed_vod_match_ids() == {"chA", "chC"}

    def test_bulk_clear_returns_count_and_clears_all(self):
        cfg = Config()
        cfg.add_vod_watch_alert(_rule("t1", text="Dune"))
        cfg.add_vod_watch_alert(_rule("t2", text="Severance"))
        cfg.record_vod_alert_match("t1", "chA")
        cfg.record_vod_alert_match("t2", "chB")
        cleared = cfg.mark_all_vod_alerts_viewed()
        assert cleared == 2
        assert cfg.get_unviewed_vod_match_count() == 0
        # nothing left to clear
        assert cfg.mark_all_vod_alerts_viewed() == 0

    def test_per_rule_unviewed_count(self):
        cfg = Config()
        cfg.add_vod_watch_alert(_rule("t1"))
        cfg.record_vod_alert_match("t1", "chA")
        cfg.record_vod_alert_match("t1", "chB")
        assert cfg.get_vod_rule_unviewed_count("t1") == 2
        cfg.mark_vod_alert_match_viewed("chA")
        assert cfg.get_vod_rule_unviewed_count("t1") == 1

    def test_add_rule_carries_viewed_ids_key(self):
        cfg = Config()
        cfg.add_vod_watch_alert(_rule("t1"))
        rule = cfg.get_vod_watch_alerts()[0]
        assert "viewed_ids" in rule

    def test_migration_seeds_pre_feature_rule_as_viewed(self):
        # A pre-feature rule has alerted_ids but NO viewed_ids key. model_post_init
        # must seed viewed = alerted so existing matches don't flood green.
        cfg = Config(vod_watch_alerts=[
            {"text": "Dune", "match_type": "any", "created": "t1",
             "alerted_ids": ["chA", "chB"]},  # no viewed_ids → pre-feature
        ])
        assert cfg.get_unviewed_vod_match_count() == 0
        # A NEW match recorded after the upgrade lights up.
        cfg.record_vod_alert_match("t1", "chC")
        assert cfg.is_vod_match_unviewed("chC")
        assert cfg.get_unviewed_vod_match_count() == 1


# ===========================================================================
# Part 2: Details Alert button — greens for unviewed, clears on view
# ===========================================================================

class TestDetailsAlertButton:

    def test_alert_button_greens_for_unviewed_and_clears(self, qapp):
        from metatv.gui.details_actions import _ActionBar
        ab = _ActionBar(Config())
        ab.set_monitorable(True, False)  # series → button visible

        ab.set_new_match(True)
        assert ab.monitor_button.styleSheet() == _theme.DETAIL_RAIL_BTN_NEW_MATCH

        ab.set_new_match(False)
        assert ab.monitor_button.styleSheet() == _theme.DETAIL_RAIL_BTN_ALERT

    def test_clear_resets_new_match_flag(self, qapp):
        from metatv.gui.details_actions import _ActionBar
        ab = _ActionBar(Config())
        ab.set_monitorable(True, False)
        ab.set_new_match(True)
        ab.clear()
        assert ab._has_new_match is False


# ===========================================================================
# Part 3: Channel-list rows — 🚨 marker + green title
# ===========================================================================

def _dto(cid: str, *, title: str = "Dune", media_type: str = "movie"):
    from metatv.core.repositories.dtos import ChannelListDTO
    return ChannelListDTO(
        id=cid, name=title, media_type=media_type, provider_id="p1",
        is_favorite=False, category=None, quality=None,
        detected_prefix=None, detected_region=None, detected_quality=None,
        detected_year=None, detected_title=title,
    )


class TestChannelListRows:

    def _model_with(self, new_match_ids):
        from metatv.gui.channel_list_model import ChannelListModel
        m = ChannelListModel()
        m.set_channels(
            [_dto("chA", title="Dune"), _dto("chB", title="Arrival")],
            provider_icon_map={}, show_provider_icon=False,
            has_more=False, query_params={},
            new_match_ids=new_match_ids,
        )
        return m

    def test_unviewed_row_gets_marker_and_green(self, qapp):
        from metatv.gui.channel_list_model import CHANNEL_HTML_ROLE
        m = self._model_with({"chA"})
        html_a = m.data(m.index(0), CHANNEL_HTML_ROLE)
        html_b = m.data(m.index(1), CHANNEL_HTML_ROLE)
        assert _icons.new_match_icon in html_a
        assert _theme.COLOR_OK in html_a
        # The non-matched row carries neither cue.
        assert _icons.new_match_icon not in html_b
        assert _theme.COLOR_OK not in html_b

    def test_clearing_match_drops_marker_live(self, qapp):
        from metatv.gui.channel_list_model import CHANNEL_HTML_ROLE
        m = self._model_with({"chA"})
        m.update_new_match_ids(set())
        html_a = m.data(m.index(0), CHANNEL_HTML_ROLE)
        assert _icons.new_match_icon not in html_a
        assert _theme.COLOR_OK not in html_a


# ===========================================================================
# Part 4: Channel-menu registry — "Clear alert" gated on unviewed match
# ===========================================================================

class TestClearAlertMenuAction:

    def _labels(self, *, has_unviewed: bool, qapp) -> list[str]:
        from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu
        ctx = ChannelMenuContext(
            channel_ids=["chA"], surface="channel", media_type="movie",
            channel_found=True, has_unviewed_match=has_unviewed,
        )
        handlers = {"play": lambda: None, "clear_alert": lambda: None}
        menu = build_channel_menu(ctx, handlers)
        return [a.text() for a in menu.actions() if not a.isSeparator()]

    def test_shown_only_when_unviewed(self, qapp):
        shown = self._labels(has_unviewed=True, qapp=qapp)
        assert any("Clear alert" in t for t in shown)

    def test_hidden_when_no_unviewed_match(self, qapp):
        hidden = self._labels(has_unviewed=False, qapp=qapp)
        assert not any("Clear alert" in t for t in hidden)


# ===========================================================================
# Part 5: Sidebar badge + Watch Queue pinned line reflect the count
# ===========================================================================

class TestSidebarAndQueueGlance:

    def test_alerts_header_badge_shows_count(self, qapp):
        from PyQt6.QtWidgets import QLabel, QPushButton
        from metatv.gui.sidebar.alerts import WatchAlertsSection
        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.title = "Alerts"
        section.title_label = QLabel()
        section._clear_all_btn = QPushButton()
        section._clear_all_btn.hide()

        # Active: green dot + green "Alerts (3)" title; "Clear all" shows.
        section.update_new_match_badge(3)
        assert "(3)" in section.title_label.text()
        assert _theme.COLOR_OK in section.title_label.text()
        assert not section._clear_all_btn.isHidden()

        # Quiet: no count suffix, gray dot, no green; "Clear all" hides.
        section.update_new_match_badge(0)
        assert "(3)" not in section.title_label.text()
        assert _theme.COLOR_MUTED in section.title_label.text()
        assert _theme.COLOR_OK not in section.title_label.text()
        assert section._clear_all_btn.isHidden()

    def test_queue_line_shows_and_hides(self, qapp):
        from PyQt6.QtWidgets import QPushButton
        from metatv.gui.sidebar.queue import WatchQueueSection
        section = WatchQueueSection.__new__(WatchQueueSection)
        section._new_matches_btn = QPushButton()
        section._new_matches_btn.hide()

        section.update_new_match_count(2)
        assert not section._new_matches_btn.isHidden()
        assert "2" in section._new_matches_btn.text()

        section.update_new_match_count(0)
        assert section._new_matches_btn.isHidden()
