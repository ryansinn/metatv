"""Watch Alerts is a noticeboard, not the watchlist.

Two owner requests, one idea between them: the sidebar section reports what has
ARRIVED. The standing list of things you are waiting for is a different
question, answered in Manage Watch Alerts (and, for EPG keywords, in the EPG
view's Watch tab).

* Entries with nothing new are not listed, unless
  ``config.alerts_show_idle_items`` is on. The switch appears in Settings AND in
  Manage Watch Alerts, and they are one setting seen twice — same config key,
  so they cannot disagree.
* A COLLAPSED group carries a solid ``+N`` pill. Expanded, each firing row has
  its own green marker and a pill on the heading would say it twice; collapsed,
  the rows are gone and the heading is the only thing left that can tell you
  something arrived.
"""

from __future__ import annotations


import pytest

from metatv.core.config import Config


RULES = [
    {"text": "Neighborhood Watch", "match_type": "any", "created": "r1",
     "alerted_ids": ["a", "b", "c", "d"]},
    {"text": "Dune", "match_type": "movie", "created": "r2", "alerted_ids": []},
    {"text": "Blade Runner", "match_type": "movie", "created": "r3", "alerted_ids": []},
]
UNVIEWED = {"r1": 4, "r2": 0, "r3": 0}
SERIES = [("Sunny", 1), ("President Curtis", 12), ("Animal Control", 0),
          ("Dan Da Dan", 0), ("Fallout", 0)]


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _Cfg:
    """A real Config with the section's accessors attached.

    Config is a pydantic model and rejects new attributes, so it is wrapped.
    """

    def __init__(self, base, *, show_idle=False, firing=True):
        self.__dict__["_b"] = base
        self.__dict__["_idle"] = show_idle
        unviewed = UNVIEWED if firing else dict.fromkeys(UNVIEWED, 0)
        self.get_vod_watch_alerts = lambda: [dict(r) for r in RULES]
        self.get_monitored_series = lambda: [
            {"cid": f"s{i}", "channel_id": f"s{i}", "title": t,
             "display_title": t, "unseen": (u if firing else 0),
             "unseen_new": (u if firing else 0), "language": "EN",
             "region": "US", "source": "TREX"}
            for i, (t, u) in enumerate(SERIES)
        ]
        self.get_vod_rule_unviewed_count = lambda c: unviewed.get(c, 0)
        self.get_rules_with_new_matches_count = lambda: sum(
            1 for v in unviewed.values() if v)
        self.get_unviewed_vod_match_count = lambda: sum(unviewed.values())

    def __getattr__(self, n):
        if n == "alerts_show_idle_items":
            return self.__dict__["_idle"]
        return getattr(self.__dict__["_b"], n)


def _section(qapp, tmp_path, **kw):
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    # db=None, not a MagicMock: _compute_alert_availability returns a MOCK for
    # a mock db, so every `avail.per_rule_unviewed.get(...) > 0` answers with a
    # truthy Mock and the config counts this fixture sets are never consulted.
    sec = WatchAlertsSection(_Cfg(Config(config_dir=tmp_path), **kw), db=None)
    # SHOWN: isVisible() is false for every child of an unshown widget, so an
    # unshown section reports "no pill" whether or not one is there.
    sec.resize(300, 700)
    sec.show()
    sec.refresh_vod_rules()
    sec.refresh_retry([])
    for _ in range(3):
        qapp.processEvents()
    return sec


def _titles(sec):
    """Every row title currently listed under Movies & Series."""
    from metatv.gui.chip_row import row_title_label

    out = []
    lst = sec._vod_list
    for i in range(lst.count()):
        widget = lst.itemWidget(lst.item(i))
        label = row_title_label(widget) if widget is not None else None
        if label is not None:
            out.append(label.text())
    return out


def _headings(sec):
    """{group name: (count text, news text)} for the headings on screen."""
    from metatv.gui.sidebar.base import GroupHeading

    out = {}
    lst = sec._vod_list
    for i in range(lst.count()):
        widget = lst.itemWidget(lst.item(i))
        if isinstance(widget, GroupHeading):
            out[widget.label.text()] = (
                widget.count_label.text().strip(),
                widget.news_chip.text() if widget.news_chip.isVisible() else "",
            )
    return out


class TestOnlyWhatIsNewByDefault:

    def test_idle_rules_and_series_are_not_listed(self, qapp, tmp_path):
        sec = _section(qapp, tmp_path)
        titles = _titles(sec)
        assert "Neighborhood Watch" in titles
        assert "Sunny" in titles and "President Curtis" in titles
        for idle in ("Dune", "Blade Runner", "Animal Control", "Fallout"):
            assert idle not in titles, f"{idle} has nothing new and was listed"

    def test_turning_the_setting_on_lists_everything(self, qapp, tmp_path):
        sec = _section(qapp, tmp_path, show_idle=True)
        titles = _titles(sec)
        for name in ("Neighborhood Watch", "Dune", "Blade Runner",
                     "Sunny", "Animal Control", "Fallout"):
            assert name in titles, name

    def test_the_counts_describe_what_is_shown(self, qapp, tmp_path):
        """A heading counts its rows. What is filtered out goes in the tooltip,
        where it can say what to do about it."""
        sec = _section(qapp, tmp_path)
        headings = _headings(sec)
        assert headings["Movies"][0] == "1"          # 1 of 3 firing
        assert headings["Series"][0] == "2"          # 2 of 5 firing
        assert sec._idle_hidden == 5

    def test_the_hidden_ones_are_named_in_the_tooltip(self, qapp, tmp_path):
        from metatv.gui.sidebar.base import GroupHeading

        sec = _section(qapp, tmp_path)
        lst = sec._vod_list
        headings = [lst.itemWidget(lst.item(i)) for i in range(lst.count())]
        headings = [h for h in headings if isinstance(h, GroupHeading)]
        assert headings
        for h in headings:
            assert "not shown" in h.toolTip(), h.toolTip()

    def test_a_badge_still_counts_everything(self, qapp, tmp_path):
        """Filtering changes what is LISTED, never what is counted as new."""
        sec = _section(qapp, tmp_path)
        assert sec._firing_count == 1
        assert sec._series_new_count == 2

    def test_alerts_configured_but_none_firing_says_so(self, qapp, tmp_path):
        """The #480 lesson: an empty section is indistinguishable from a broken
        one, so a configured-but-quiet watchlist keeps its place and explains."""
        sec = _section(qapp, tmp_path, firing=False)
        assert sec._vod_list.isVisible()
        assert sec._vod_list.count() == 1
        text = sec._vod_list.item(0).text()
        assert "Nothing new" in text and "8" in text, text

    def test_nothing_configured_at_all_still_hides(self, qapp, tmp_path):
        """No alerts set up is a different nothing — there is no promise to keep
        a place for."""
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        cfg = _Cfg(Config(config_dir=tmp_path))
        cfg.get_vod_watch_alerts = lambda: []
        cfg.get_monitored_series = lambda: []
        sec = WatchAlertsSection(cfg, db=None)
        sec.resize(300, 700)
        sec.show()
        sec.refresh_vod_rules()
        for _ in range(3):
            qapp.processEvents()
        assert not sec._vod_list.isVisible()


class TestACollapsedGroupWearsItsNewCount:

    def test_collapsed_group_shows_a_solid_pill(self, qapp, tmp_path):
        sec = _section(qapp, tmp_path, show_idle=True)
        assert _headings(sec)["Series"][1] == "", "expanded groups need no pill"

        sec._toggle_series_group()
        qapp.processEvents()
        assert _headings(sec)["Series"][1] == "+2", _headings(sec)

    def test_the_pill_is_filled_and_takes_its_foreground_from_the_fill(
            self, qapp, tmp_path):
        """The same pill as the section header, from the same one definition —
        not a second sheet that drifts."""
        from metatv.gui import theme as _theme
        from metatv.gui.sidebar.base import GroupHeading

        sec = _section(qapp, tmp_path, show_idle=True)
        sec._toggle_series_group()
        qapp.processEvents()
        lst = sec._vod_list
        pill = None
        for i in range(lst.count()):
            w = lst.itemWidget(lst.item(i))
            if isinstance(w, GroupHeading) and w.news_chip.isVisible():
                pill = w.news_chip
        assert pill is not None
        sheet = pill.styleSheet()
        assert "background" in sheet and _theme.COLOR_OK in sheet
        assert _theme.on_fill(_theme.COLOR_OK) in sheet, (
            "the pill's foreground must come from on_fill, not a literal"
        )

    def test_a_collapsed_group_with_nothing_new_gets_no_pill(self, qapp, tmp_path):
        sec = _section(qapp, tmp_path, show_idle=True, firing=False)
        sec._toggle_series_group()
        qapp.processEvents()
        assert _headings(sec)["Series"][1] == ""

    def test_the_pill_sits_after_the_count(self, qapp, tmp_path):
        """Rendered order, not just presence: label, then how many, then how
        many of those are new."""
        from metatv.gui.sidebar.base import GroupHeading

        heading = GroupHeading("Series", 7, news=2)
        heading.setFixedWidth(280)
        heading.show()
        qapp.processEvents()
        assert heading.label.x() < heading.count_label.x() < heading.news_chip.x()
        heading.deleteLater()


class TestTheTwoSwitchesAreOneSetting:

    def test_the_manage_dialog_writes_the_shared_key_and_signals(self, qapp, tmp_path):
        from metatv.gui.vod_watch_alert_dialog import ManageVodAlertsDialog

        cfg = Config(config_dir=tmp_path)
        dlg = ManageVodAlertsDialog(cfg)
        assert dlg._show_idle_check.isChecked() is False

        fired = []
        dlg.changed.connect(lambda: fired.append(1))
        dlg._show_idle_check.setChecked(True)
        assert cfg.alerts_show_idle_items is True
        assert fired, "the sidebar was never told to re-render"

        # A dialog opened afterwards agrees — they read one key, not two.
        # Bound to a name: an unreferenced QDialog is collected before the
        # attribute lookup and PyQt raises on the dead C++ object.
        later = ManageVodAlertsDialog(cfg)
        assert later._show_idle_check.isChecked() is True

    def test_the_settings_dialog_round_trips_the_same_key(self, qapp, tmp_path):
        from metatv.gui.settings_dialog import SettingsDialog

        cfg = Config(config_dir=tmp_path)
        cfg.alerts_show_idle_items = True
        dlg = SettingsDialog(cfg)
        assert dlg._alerts_show_idle_check.isChecked() is True

        dlg._alerts_show_idle_check.setChecked(False)
        dlg._save_values()
        assert cfg.alerts_show_idle_items is False

    def test_applying_settings_re_renders_the_section(self):
        """The setting changes WHICH rows exist, so OK/Apply must re-render —
        the hook has to be in the list conftest asserts MainWindow implements."""
        from tests.conftest import _SETTINGS_APPLIED_HOOKS
        from metatv.gui.main_window import MainWindow

        assert "_refresh_vod_alerts_section" in _SETTINGS_APPLIED_HOOKS
        assert hasattr(MainWindow, "_refresh_vod_alerts_section")
