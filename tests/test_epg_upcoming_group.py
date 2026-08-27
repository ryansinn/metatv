"""The EPG group's "Upcoming" sub-group: what is not on yet, foldable.

What is on NOW is two or three rows; what is on LATER is a dozen. The dozen
sat directly under the two with nothing between them, so Watch Alerts was
mostly a list of programmes the owner had not asked to see yet and could not
put away: "the upcoming shows take over the entire array and maybe I don't care
what's on next ... so I can see the alerts and what's currently on, or collapse
the dozen upcoming entries and keep the Watch Alerts smaller most of the time."

Three decisions worth stating because the tests encode them:

* It is a ``GroupHeading``, not a divider bar. That widget exists BECAUSE this
  section had grown three ways of drawing the same thing; a rule would be a
  fourth.
* No caret. The heading has been the control since #329 — a caret beside a
  clickable title is a second affordance for one action — and the count is what
  says something is inside while it is closed.
* No matching "On now" heading. Owner: "We don't have to have a header for
  what's on now."
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QPoint

from metatv.core.config import Config
from metatv.gui.sidebar.alerts_common import _Airing
from metatv.gui.sidebar.base import GroupHeading

NOW = datetime(2026, 8, 26, 20, 0, 0)


class _Cfg:
    """A real Config with the section's data accessors bolted on.

    Writes fall THROUGH to the real Config, so ``config.save()`` and the
    persisted flag behave as they do in the app — a wrapper that swallowed
    writes would make the persistence test meaningless.
    """

    def __init__(self, base):
        self.__dict__["_b"] = base
        self.get_vod_watch_alerts = lambda: []
        self.get_monitored_series = lambda: []
        self.get_vod_rule_unviewed_count = lambda _c: 0
        self.get_rules_with_new_matches_count = lambda: 0
        self.get_unviewed_vod_match_count = lambda: 0

    def __getattr__(self, name):
        if name == "alerts_show_idle_items":
            return True
        return getattr(self.__dict__["_b"], name)

    def __setattr__(self, name, value):
        if name.startswith("get_"):
            self.__dict__[name] = value
        else:
            setattr(self.__dict__["_b"], name, value)


def _payload(live=2, upcoming=6):
    live_groups = {
        f"L{i}": {"title": f"On Now {i}", "upcoming": [],
                  "live": [_Airing(3, "3m left", f"CH{i}", f"l{i}",
                                   NOW + timedelta(minutes=20),
                                   NOW - timedelta(minutes=27), "")]}
        for i in range(live)
    }
    upcoming_only = {
        f"u{i}": {"title": f"Later {i}",
                  "airings": [_Airing(i, "9:00 PM", f"CH{i}", f"c{i}",
                                      NOW + timedelta(hours=i + 1), None, "")]}
        for i in range(upcoming)
    }
    return {"empty_reason": "", "live_groups": live_groups,
            "upcoming_only": upcoming_only}


@pytest.fixture
def section(qtbot, tmp_path):
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    sec = WatchAlertsSection(_Cfg(Config(config_dir=tmp_path)), MagicMock())
    qtbot.addWidget(sec)
    sec.resize(330, 460)
    sec.show()
    qtbot.waitExposed(sec)
    sec._populate_rows(_payload())
    _settle(qtbot, sec)
    return sec


def _settle(qtbot, sec):
    for _ in range(8):
        qtbot.wait(1)


def _tops(sec):
    tree = sec.alerts_tree
    return [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]


def _heading(sec) -> GroupHeading | None:
    """The Upcoming heading widget, or None if the tree has no such row."""
    tree = sec.alerts_tree
    for item in _tops(sec):
        widget = tree.itemWidget(item, 0)
        if isinstance(widget, GroupHeading):
            return widget
    return None


def _visible(sec) -> int:
    return sum(1 for item in _tops(sec) if not item.isHidden())


class TestTheHeadingIsThere:

    def test_it_names_the_group_and_counts_it(self, section):
        heading = _heading(section)
        assert heading is not None, "no Upcoming heading in the tree"
        assert heading.label.text() == "Upcoming"
        assert heading.count_label.text().strip() == "6"

    def test_it_is_the_only_one(self, section):
        """No "On now" heading — the rows at the top need no label."""
        tree = section.alerts_tree
        headings = [tree.itemWidget(i, 0) for i in _tops(section)]
        assert sum(isinstance(w, GroupHeading) for w in headings) == 1

    def test_it_carries_no_caret(self, section):
        """The heading IS the control. A caret would be a second affordance
        for one action, which this section dropped in #329."""
        from metatv.gui import icons as _icons

        heading = _heading(section)
        text = heading.label.text() + heading.count_label.text()
        for glyph in (_icons.expand_icon, _icons.collapse_icon):
            assert glyph not in text, f"a caret ({glyph!r}) came back"

    def test_it_sits_below_what_is_on_now_and_above_what_is_not(self, section):
        """RENDERED order, by painted y — the split is the whole point, and a
        heading in the wrong place labels the wrong rows."""
        tree = section.alerts_tree
        tops = _tops(section)
        heading_index = next(i for i, item in enumerate(tops)
                             if isinstance(tree.itemWidget(item, 0), GroupHeading))
        y = [tree.visualItemRect(item).top() for item in tops]
        assert all(y[i] < y[heading_index] for i in range(heading_index)), y
        assert all(y[i] > y[heading_index]
                   for i in range(heading_index + 1, len(tops))), y

    def test_it_is_indented_under_epg_not_beside_it(self, section):
        """Rendered x, not a margin constant.

        At zero inset it lines up with the EPG heading above and reads as its
        sibling rather than as the heading for the rows below it.
        """
        upcoming = _heading(section)
        epg_x = section._epg_toggle.label.mapTo(section, QPoint(0, 0)).x()
        up_x = upcoming.label.mapTo(section, QPoint(0, 0)).x()
        assert up_x > epg_x, (
            f"Upcoming paints at x={up_x}, EPG at x={epg_x} — it reads as a "
            "peer of EPG rather than a group inside it"
        )


class TestFoldingIt:

    def test_collapsing_hides_the_upcoming_rows_and_keeps_the_rest(
            self, qtbot, section):
        before = _visible(section)
        section._toggle_epg_upcoming()
        _settle(qtbot, section)
        after = _visible(section)
        # 2 live rows + the heading itself survive; the 6 upcoming ones go.
        assert after == before - 6, (before, after)
        assert _heading(section) is not None, "the heading hid itself"

    def test_collapsing_actually_shortens_the_section(self, qtbot, section):
        """The reason it exists. A fold that hides rows without releasing the
        height gives the owner nothing — that is the whole complaint."""
        tall = section.max_useful_height()
        section._toggle_epg_upcoming()
        _settle(qtbot, section)
        short = section.max_useful_height()
        assert short < tall * 0.75, (
            f"collapsing 6 of 8 rows only took the section from {tall}px to "
            f"{short}px"
        )

    def test_the_choice_is_remembered(self, qtbot, section):
        assert section.config.alerts_epg_upcoming_collapsed is False
        section._toggle_epg_upcoming()
        _settle(qtbot, section)
        assert section.config.alerts_epg_upcoming_collapsed is True

    def test_a_refresh_does_not_re_open_it(self, qtbot, section):
        """The EPG group repopulates on a clock tick and on every refresh. If
        that re-opened the block, collapsing it would last seconds."""
        section._toggle_epg_upcoming()
        _settle(qtbot, section)
        collapsed = _visible(section)

        section.alerts_tree.clear()          # what the refresh path does first
        section._populate_rows(_payload())
        _settle(qtbot, section)
        assert _visible(section) == collapsed

    def test_expanding_brings_them_all_back(self, qtbot, section):
        before = _visible(section)
        section._toggle_epg_upcoming()
        _settle(qtbot, section)
        section._toggle_epg_upcoming()
        _settle(qtbot, section)
        assert _visible(section) == before


def test_an_empty_refresh_then_a_toggle_does_not_crash(qtbot, section):
    """Found by running the code rather than by reading it.

    The tracked items are the tree's own ``QTreeWidgetItem`` objects. A refresh
    clears the tree, which DELETES them on the C++ side, and an empty payload
    returns before the block that would rebuild the list — so the next toggle
    reached into a list of dead pointers and Qt raised ``RuntimeError``. The
    list is dropped before every early return now.
    """
    section._toggle_epg_upcoming()            # something to restore
    _settle(qtbot, section)
    section.alerts_tree.clear()
    section._populate_rows({"empty_reason": "", "live_groups": {},
                            "upcoming_only": {}})
    _settle(qtbot, section)
    section._toggle_epg_upcoming()            # RuntimeError before the fix
    _settle(qtbot, section)
