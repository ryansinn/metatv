"""Behavioral tests for the Watch Alerts polish batch (id=156).

Each test executes a changed path and asserts the outcome that would break if the
change regressed:

A. ``&&`` escaping in the "Movies & Series" toggle label.
B. (covered by test_watch_alerts_consolidation) — the "Watching for" group label.
C. ``series_alert_identity`` — collision disambiguator suffixes + identity tooltip,
   and the sidebar/manage-dialog rendering that reads them.
F. ``update_new_match_badge`` total-vs-clearable split — the header dot reflects the
   TOTAL firing count while "Clear all" tracks keyword rules only.
"""

from __future__ import annotations

from types import SimpleNamespace

import metatv.gui.theme as _theme
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ===========================================================================
# C. series_alert_identity — pure disambiguation + identity helpers
# ===========================================================================

class TestDisambiguationSuffixes:

    def _entry(self, display, *, title="", region="", language="", source=""):
        return {
            "display_title": display,
            "title": title or display,
            "region": region,
            "language": language,
            "source": source,
        }

    def test_unique_title_gets_no_suffix(self):
        from metatv.gui.series_alert_identity import disambiguation_suffixes
        entries = [self._entry("Severance", region="US")]
        assert disambiguation_suffixes(entries) == [""]

    def test_collision_region_differs_first(self):
        from metatv.gui.series_alert_identity import disambiguation_suffixes
        entries = [
            self._entry("Fallout", region="US", language="EN", source="P1"),
            self._entry("Fallout", region="FR", language="FR", source="P1"),
        ]
        suffixes = disambiguation_suffixes(entries)
        # Non-empty AND differ; region is the first differing attribute.
        assert suffixes == ["US", "FR"], suffixes
        assert all(suffixes)
        assert suffixes[0] != suffixes[1]

    def test_collision_falls_through_to_language(self):
        from metatv.gui.series_alert_identity import disambiguation_suffixes
        entries = [
            self._entry("Fallout", region="US", language="EN", source="P"),
            self._entry("Fallout", region="US", language="ES", source="P"),
        ]
        # Region is identical → language is the first differing attribute.
        assert disambiguation_suffixes(entries) == ["EN", "ES"]

    def test_collision_falls_through_to_source(self):
        from metatv.gui.series_alert_identity import disambiguation_suffixes
        entries = [
            self._entry("Fallout", region="US", language="EN", source="Alpha"),
            self._entry("Fallout", region="US", language="EN", source="Beta"),
        ]
        assert disambiguation_suffixes(entries) == ["Alpha", "Beta"]

    def test_collision_none_differ_falls_back_to_raw_title(self):
        from metatv.gui.series_alert_identity import disambiguation_suffixes
        entries = [
            self._entry("Fallout", title="Fallout One", region="US", language="EN", source="P"),
            self._entry("Fallout", title="Fallout Two", region="US", language="EN", source="P"),
        ]
        assert disambiguation_suffixes(entries) == ["Fallout One", "Fallout Two"]

    def test_case_insensitive_collision(self):
        from metatv.gui.series_alert_identity import disambiguation_suffixes
        entries = [
            self._entry("Fallout", region="US"),
            self._entry("fallout", region="FR"),
        ]
        assert disambiguation_suffixes(entries) == ["US", "FR"]

    def test_unique_among_collision_stays_clean(self):
        from metatv.gui.series_alert_identity import disambiguation_suffixes
        entries = [
            self._entry("Severance", region="US"),
            self._entry("Fallout", region="US"),
            self._entry("Fallout", region="FR"),
        ]
        # Only the two colliding "Fallout" rows get a suffix.
        assert disambiguation_suffixes(entries) == ["", "US", "FR"]


class TestIdentityLines:

    def test_all_present(self):
        from metatv.gui.series_alert_identity import identity_lines
        assert identity_lines(language="EN", region="US", source="MyProv") == (
            "Language: EN\nRegion: US\nSource: MyProv"
        )

    def test_empty_render_em_dash(self):
        from metatv.gui.series_alert_identity import identity_lines
        assert identity_lines(language="", region="", source="") == (
            "Language: —\nRegion: —\nSource: —"
        )


# ===========================================================================
# A. "Movies & Series" toggle label escapes the ampersand as "&&"
# ===========================================================================

class TestAmpersandEscaping:

    def test_new_totals_combine_rules_and_series(self, qapp):
        """The section badge's total, recomputed after a VOD refresh.

        Replaces two tests that asserted the "Movies && Series" ampersand
        escape. That escape existed because the label was a QPushButton, which
        eats a lone "&" as a keyboard mnemonic; the heading is a QLabel now and
        the wrapper it labelled has been dissolved, so the whole concern is
        gone rather than merely renamed.
        """
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.config = SimpleNamespace(
            get_rules_with_new_matches_count=lambda: 2
        )
        section._firing_count = 4
        section._series_new_count = 3

        section._update_vod_toggle_label(13)
        assert section._new_total == 7, (
            "the badge total must combine firing keyword rules with series "
            "holding unseen episodes"
        )

    def test_new_totals_fall_back_to_the_config_count(self, qapp):
        """Before a refresh has stashed one, the config's count stands in."""
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.config = SimpleNamespace(
            get_rules_with_new_matches_count=lambda: 5
        )
        section._update_vod_toggle_label(0)
        assert section._new_total == 5


# ===========================================================================
# F. update_new_match_badge — dot from TOTAL, "Clear all" from clearable only
# ===========================================================================

class TestHeaderBadgeSplit:

    def _section(self):
        from PyQt6.QtWidgets import QLabel, QPushButton
        from metatv.gui.sidebar.alerts import WatchAlertsSection
        section = WatchAlertsSection.__new__(WatchAlertsSection)
        section.title = "Alerts"
        section.title_label = QLabel()
        section._clear_all_btn = QPushButton()
        section._clear_all_btn.hide()
        return section

    def test_total_drives_dot_clearable_drives_button(self, qapp):
        section = self._section()
        # 3 keyword rules firing + 2 series with new episodes = 5 total.
        section.update_new_match_badge(5, 10, clearable_count=3)
        assert _theme.COLOR_OK in section.title_label.text()  # green dot; the count is the header pill            # dot/(N) = TOTAL
        assert not section._clear_all_btn.isHidden()          # keyword rules → shown
        tip = section.title_label.toolTip()
        assert "3 keyword matches" in tip, tip
        assert "2 series with new episodes" in tip, tip

    def test_series_only_lights_dot_but_hides_clear_all(self, qapp):
        section = self._section()
        # A collapsed section with ONLY a series new episode: dot glows, but
        # "Clear all" must stay hidden (series are cleared via "Mark seen").
        section.update_new_match_badge(1, clearable_count=0)
        assert _theme.COLOR_OK in section.title_label.text()  # green dot; the count is the header pill
        assert section._clear_all_btn.isHidden()
        assert "1 series with new episode" in section.title_label.toolTip()

    def test_backcompat_keyword_only_keeps_item_total(self, qapp):
        section = self._section()
        # Legacy call shape (no clearable_count): clearable defaults to count, and
        # the tooltip keeps the matched-item total.
        section.update_new_match_badge(2, 73)
        assert _theme.COLOR_OK in section.title_label.text()  # green dot; the count is the header pill
        assert not section._clear_all_btn.isHidden()
        assert "73" in section.title_label.toolTip()
        assert "2 alerts" in section.title_label.toolTip()


# ===========================================================================
# C (render). Sidebar renders the disambiguator suffix + identity tooltip.
# ===========================================================================

class _FakeConfig:
    expand_icon = ">"
    collapse_icon = "v"

    #: These tests assert how a row RENDERS and how a click routes, not
    #: which entries are eligible to be listed. The section now lists only
    #: firing entries by default, so they opt into the full list — the
    #: filter itself is covered by tests/test_alerts_new_only.py.
    alerts_show_idle_items = True

    def __init__(self, series):
        self._series = series

    def get_monitored_series(self):
        return list(self._series)

    def get_vod_watch_alerts(self):
        return []

    def get_rules_with_new_matches_count(self):
        return 0

    def get_unviewed_vod_match_count(self):
        return 0

    def get_vod_rule_unviewed_count(self, _c):
        return 0


def _series(cid, display, *, region="", language="", source="", unseen=0, title=None):
    return {
        "series_channel_id": cid,
        "display_title": display,
        "title": title or display,
        "region": region,
        "language": language,
        "source": source,
        "unseen_new": unseen,
    }


def _render_section(cfg, qapp):
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.alerts import WatchAlertsSection
    section = WatchAlertsSection.__new__(WatchAlertsSection)
    section.config = cfg
    from tests.conftest import wire_watch_alerts_group_state
    wire_watch_alerts_group_state(section)
    section._series_collapsed = False
    section._vod_list = QListWidget()
    section._update_vod_toggle_label = MagicMock()
    section.update_new_match_badge = MagicMock()
    section.refresh_vod_rules()
    return section


class TestSidebarDisambiguationRender:

    def test_colliding_series_show_dim_suffix_and_identity_tooltip(self, qapp):
        from metatv.gui.sidebar.alerts import _ROLE_KIND

        cfg = _FakeConfig([
            _series("a", "Fallout", region="US", language="EN", source="P1"),
            _series("b", "Fallout", region="FR", language="FR", source="P2"),
        ])
        section = _render_section(cfg, qapp)
        lst = section._vod_list

        series_idxs = [
            i for i in range(lst.count())
            if lst.item(i).data(_ROLE_KIND) == "series"
        ]
        assert len(series_idxs) == 2

        # Every colliding row carries a disambiguator (its region) in a row label
        # AND an identity tooltip listing Language / Region / Source.
        seen_suffix = set()
        for i in series_idxs:
            item = lst.item(i)
            tip = item.toolTip()
            assert "Language:" in tip and "Region:" in tip and "Source:" in tip, tip
            row = lst.itemWidget(item)
            from PyQt6.QtWidgets import QLabel
            label_html = " ".join(w.text() for w in row.findChildren(QLabel))
            for token in ("US", "FR"):
                if token in label_html:
                    seen_suffix.add(token)
        assert seen_suffix == {"US", "FR"}, seen_suffix

    def test_unique_series_has_no_suffix(self, qapp):
        from metatv.gui.sidebar.alerts import _ROLE_KIND
        from PyQt6.QtWidgets import QLabel

        cfg = _FakeConfig([
            _series("a", "Severance", region="US", language="EN", source="P1"),
        ])
        section = _render_section(cfg, qapp)
        lst = section._vod_list
        (i,) = [
            j for j in range(lst.count())
            if lst.item(j).data(_ROLE_KIND) == "series"
        ]
        row = lst.itemWidget(lst.item(i))
        labels = row.findChildren(QLabel)
        # Name label is plain "Severance" — no dim span, region not appended inline.
        name_texts = [w.text() for w in labels]
        assert any(t == "Severance" for t in name_texts), name_texts
        # Tooltip still carries full identity even without a collision.
        assert "Region: US" in lst.item(i).toolTip()


# ===========================================================================
# C (dialog). ManageVodAlertsDialog disambiguates colliding series too.
# ===========================================================================

class TestManageDialogDisambiguation:

    def test_colliding_series_get_suffix_and_tooltip(self, qapp):
        from PyQt6.QtWidgets import QLabel
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog

        cfg = SimpleNamespace(
            get_vod_watch_alerts=lambda: [],
            get_monitored_series=lambda: [
                _series("a", "Fallout", region="US", language="EN", source="P1"),
                _series("b", "Fallout", region="FR", language="FR", source="P2"),
            ],
        )
        dlg = ManageVodAlertsDialog(cfg)
        all_html = " ".join(
            w.text() for w in dlg._scroll_content.findChildren(QLabel)
        )
        # Both region disambiguators appear somewhere in the series rows.
        assert "US" in all_html and "FR" in all_html, all_html
