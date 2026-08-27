"""Behavioral tests for the Alerts/Queue UX cleanup (feat/alerts-queue-ux).

Covers:
- ``Config.mark_vod_rule_viewed``: acknowledges just one rule's matches, returns
  the cleared count, and leaves other rules unviewed (real Config on tmp_path).
- ``alerts._vod_count_label``: the "N of M" / "· M" / "" count-text formatter.

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

    def test_the_badge_updates_the_tooltip_and_leaves_the_title_alone(self, qapp):
        """The title is a constant now; the count lives on the header pill.

        It used to be rewritten here — the label carried a recolorable state
        dot and the title together — which is why this asserted the title's
        TEXT. The dot went when the filled "+N" pill made it a second drawing
        of one fact, so the title is set once at construction and the count
        reaches the header through the pill. What this method still owns is
        the tooltip, which is the only place the item TOTAL is stated.
        """
        from PyQt6.QtWidgets import QLabel, QPushButton
        from metatv.gui.sidebar.alerts import WatchAlertsSection
        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.title = "Alerts"
        section.title_label = QLabel("<b>Alerts</b>")
        section._clear_all_btn = QPushButton()
        # 2 firing alerts, 73 matched items.
        section.update_new_match_badge(2, 73)
        assert section.title_label.text() == "<b>Alerts</b>", (
            "the badge update rewrote the title"
        )
        assert "73" not in section.title_label.text()  # item total never in the title
        assert "73" in section.title_label.toolTip()
        assert "2 alerts" in section.title_label.toolTip()


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestVodCountLabel:
    """alerts._vod_count_label — the right-aligned count text."""

    def test_unviewed_reads_plus_n(self):
        from metatv.gui.sidebar.alerts_common import _vod_count_label
        # "+5", not "5 of 20": the count is a narrow CHIP now, and how many
        # are NEW is what earns the space. The total is in the tooltip.
        assert _vod_count_label(5, 20) == "+5"
        assert _vod_count_label(17, 17) == "+17"

    def test_all_viewed_reads_the_bare_total(self):
        from metatv.gui.sidebar.alerts_common import _vod_count_label
        # No leading "·": inside a chip the dot reads as part of the number.
        assert _vod_count_label(0, 31) == "31"

    def test_no_matches_is_empty(self):
        from metatv.gui.sidebar.alerts_common import _vod_count_label
        assert _vod_count_label(0, 0) == ""


class TestShowMatchesHandler:
    """MainWindow._on_vod_rule_show_matches seeds a live, editable keyword search
    (B1) — a transparent view whose visible config produces the results — rather
    than the opaque stored-id filter. The #293 id-filter path is left dormant."""

    def _stub(self, cfg, **extra):
        import types
        from unittest.mock import MagicMock
        base = dict(
            config=cfg,
            _details_id_filter=None,
            # Pass-through availability filter (all stored ids treated as available);
            # the real hidden-source gating is covered by filter_available_ids +
            # the reveal tests. This test verifies routing to the stored id-set.
            _filter_available_ids=lambda ids: set(ids),
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

    def test_seeds_live_keyword_search_not_id_filter(self, tmp_path, qapp):
        from unittest.mock import MagicMock
        from metatv.gui.main_window import MainWindow
        cfg = _make_config(tmp_path)
        cfg.add_vod_watch_alert({"text": "Odyssey", "match_type": "movie", "created": "r1"})
        cfg.record_vod_alert_match("r1", "chA")
        cfg.record_vod_alert_match("r1", "chB")

        stub = self._stub(
            cfg, _on_vod_rule_view_matches=MagicMock(), _clear_id_filter=MagicMock()
        )
        MainWindow._on_vod_rule_show_matches(stub, "r1")

        # B1: the alert seeds a live, editable keyword search (the rule's text + type),
        # NOT an opaque frozen id-set.  The id-filter is left dormant (never set).
        stub._on_vod_rule_view_matches.assert_called_once_with("Odyssey", "movie")
        assert stub._details_id_filter is None
        stub._clear_id_filter.assert_called_once()

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
