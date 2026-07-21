"""Behavioral tests for the Alerts/Queue UX cleanup (feat/alerts-queue-ux).

Covers:
- ``Config.mark_vod_rule_viewed``: acknowledges just one rule's matches, returns
  the cleared count, and leaves other rules unviewed (real Config on tmp_path).
- ``alerts._vod_count_label``: the "N of M" / "· M" / "" count-text formatter.
- ``alerts._alerts_title_html``: recolorable header dot + title + count states.

The formatter/HTML helpers are pure functions, so they are exercised directly
without any Qt widget construction.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_config(tmp_path: Path):
    """Real Config backed by an isolated on-disk config dir."""
    from metatv.core.config import Config
    return Config(config_dir=tmp_path / "cfg")


class TestMarkVodRuleViewed:
    """Config.mark_vod_rule_viewed — per-rule 'Clear this alert'."""

    def _two_rules_with_matches(self, cfg):
        cfg.add_vod_watch_alert({"text": "Dune", "match_type": "movie", "created": "rule-1"})
        cfg.add_vod_watch_alert({"text": "Arrival", "match_type": "movie", "created": "rule-2"})
        cfg.record_vod_alert_match("rule-1", "chA")
        cfg.record_vod_alert_match("rule-1", "chB")
        cfg.record_vod_alert_match("rule-1", "chA")  # duplicate — must not double-count
        cfg.record_vod_alert_match("rule-2", "chC")

    def test_marks_only_target_rule_and_returns_cleared_count(self, tmp_path):
        cfg = _make_config(tmp_path)
        self._two_rules_with_matches(cfg)
        assert cfg.get_vod_rule_unviewed_count("rule-1") == 2
        assert cfg.get_vod_rule_unviewed_count("rule-2") == 1

        cleared = cfg.mark_vod_rule_viewed("rule-1")
        assert cleared == 2, "returns the count of newly-acknowledged channels"

        # rule-1: viewed_ids == its alerted_ids (order-preserving dedup); now clear.
        r1 = next(r for r in cfg.get_vod_watch_alerts() if r["created"] == "rule-1")
        assert r1["viewed_ids"] == ["chA", "chB"]
        assert cfg.get_vod_rule_unviewed_count("rule-1") == 0

        # rule-2 is untouched — still unviewed.
        assert cfg.get_vod_rule_unviewed_count("rule-2") == 1
        r2 = next(r for r in cfg.get_vod_watch_alerts() if r["created"] == "rule-2")
        assert list(r2.get("viewed_ids") or []) == []

    def test_already_fully_viewed_returns_zero(self, tmp_path):
        cfg = _make_config(tmp_path)
        self._two_rules_with_matches(cfg)
        cfg.mark_vod_rule_viewed("rule-1")
        assert cfg.mark_vod_rule_viewed("rule-1") == 0

    def test_unknown_rule_returns_zero(self, tmp_path):
        cfg = _make_config(tmp_path)
        assert cfg.mark_vod_rule_viewed("does-not-exist") == 0


class TestRulesWithNewMatchesCount:
    """Config.get_rules_with_new_matches_count — the header 'firing alerts' glance."""

    def test_counts_rules_not_items(self, tmp_path):
        cfg = _make_config(tmp_path)
        for rid in ("r1", "r2", "r3"):
            cfg.add_vod_watch_alert({"text": rid, "match_type": "movie", "created": rid})
        # r1 fires with 2 items, r2 fires with 1, r3 has none.
        cfg.record_vod_alert_match("r1", "a")
        cfg.record_vod_alert_match("r1", "b")
        cfg.record_vod_alert_match("r2", "c")
        # 2 rules firing even though there are 3 matched items total.
        assert cfg.get_rules_with_new_matches_count() == 2
        assert cfg.get_unviewed_vod_match_count() == 3

    def test_zero_when_none_firing(self, tmp_path):
        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "r1", "match_type": "movie", "created": "r1"})
        cfg.record_vod_alert_match("r1", "a")
        cfg.mark_vod_rule_viewed("r1")  # acknowledged → no longer firing
        assert cfg.get_rules_with_new_matches_count() == 0


class TestHeaderShowsRuleCount:
    """The Alerts header label reflects the firing-rule count, not item totals."""

    def test_header_label_shows_rule_count(self, qapp):
        from PyQt6.QtWidgets import QLabel, QPushButton
        from metatv.gui.sidebar.alerts import WatchAlertsSection
        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.title = "Alerts"
        section.title_label = QLabel()
        section._clear_all_btn = QPushButton()
        # 2 firing alerts, 73 matched items → header shows "(2)", tooltip clarifies both.
        section.update_new_match_badge(2, 73)
        assert "Alerts (2)" in section.title_label.text()
        assert "73" not in section.title_label.text()  # item total never in the header
        assert "73" in section.title_label.toolTip()
        assert "2 alerts" in section.title_label.toolTip()


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestVodCountLabel:
    """alerts._vod_count_label — the right-aligned count text."""

    def test_unviewed_reads_n_of_m(self):
        from metatv.gui.sidebar.alerts import _vod_count_label
        assert _vod_count_label(5, 20) == "5 of 20"
        assert _vod_count_label(17, 17) == "17 of 17"

    def test_all_viewed_reads_dot_total(self):
        from metatv.gui.sidebar.alerts import _vod_count_label
        assert _vod_count_label(0, 31) == "· 31"

    def test_no_matches_is_empty(self):
        from metatv.gui.sidebar.alerts import _vod_count_label
        assert _vod_count_label(0, 0) == ""


class TestAlertsTitleHtml:
    """alerts._alerts_title_html — recolorable header dot + title + count."""

    def test_quiet_state_gray_dot_no_count(self):
        from metatv.gui import theme as _theme
        from metatv.gui.sidebar.alerts import _alerts_title_html
        html = _alerts_title_html("Alerts", 0)
        assert "Alerts" in html
        assert "(" not in html                 # no count suffix
        assert _theme.COLOR_MUTED in html      # gray dot
        assert _theme.COLOR_OK not in html     # nothing green

    def test_active_state_green_dot_and_count(self):
        from metatv.gui import theme as _theme
        from metatv.gui.sidebar.alerts import _alerts_title_html
        html = _alerts_title_html("Alerts", 3)
        assert "Alerts (3)" in html
        assert _theme.COLOR_OK in html         # green dot + green title


class TestShowMatchesHandler:
    """MainWindow._on_vod_rule_show_matches routes to a rule's STORED alerted_ids."""

    def _stub(self, cfg, **extra):
        import types
        from unittest.mock import MagicMock
        base = dict(
            config=cfg,
            _details_id_filter=None,
            _reset_context_filters=MagicMock(),
            _resolve_vod_rule=MagicMock(return_value=("Odyssey", "movie")),
            _context_filter_label=MagicMock(),
            _context_filter_chip=MagicMock(),
            search_input=MagicMock(),
            _set_search_text_silently=MagicMock(),
            switch_to_list_view=MagicMock(),
            load_channels=MagicMock(),
        )
        base.update(extra)
        return types.SimpleNamespace(**base)

    def test_sets_id_filter_to_alerted_ids_and_loads(self, tmp_path, qapp):
        from metatv.gui.main_window import MainWindow
        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "Odyssey", "match_type": "movie", "created": "r1"})
        cfg.record_vod_alert_match("r1", "chA")
        cfg.record_vod_alert_match("r1", "chB")

        stub = self._stub(cfg)
        MainWindow._on_vod_rule_show_matches(stub, "r1")

        # The exact stored matched ids are handed to the load path — not a keyword.
        assert stub._details_id_filter == set(cfg.get_vod_alert_matches("r1")) == {"chA", "chB"}
        stub._reset_context_filters.assert_called_once()
        stub.load_channels.assert_called_once()

    def test_falls_back_to_keyword_when_no_stored_matches(self, tmp_path, qapp):
        from unittest.mock import MagicMock
        from metatv.gui.main_window import MainWindow
        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "Dune", "match_type": "movie", "created": "r1"})
        # No matches recorded → keyword fallback, id-filter left unset.
        stub = self._stub(
            cfg,
            _resolve_vod_rule=MagicMock(return_value=("Dune", "movie")),
            _on_vod_rule_view_matches=MagicMock(),
        )
        MainWindow._on_vod_rule_show_matches(stub, "r1")

        stub._on_vod_rule_view_matches.assert_called_once_with("Dune", "movie")
        assert stub._details_id_filter is None
        stub.load_channels.assert_not_called()
