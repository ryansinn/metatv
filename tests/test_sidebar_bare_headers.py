"""Sidebar headers are their names, and nothing else.

The icons were decoration — "Watch Queue" beside the words "Watch Queue" — kept
on the theory that they might become the drag handle for reordering the rail.
Reordering is parked (see ROADMAP, "Reorder the sidebar sections"), and an icon
waiting for a job it may never get is decoration with a story attached. Owner:
"do we even need the icons at all?"

Watch Alerts' leading DOT went with them, for a reason of its own: the header
already carries the filled "+N" pill, and a dot that means "something is new"
beside a pill that means "2 things are new" is one fact drawn twice. Owner:
"watch alerts icon could probably go as well, since we have the +1 or whatever
filled chip in the header." All five sections now share one title builder.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QLabel, QSplitter

from metatv.core.config import Config


def _sections(qtbot, tmp_path):
    """The three plainest sections, in a real splitter, wired as the host wires them."""
    from metatv.gui.sidebar.favorites import FavoritesSection
    from metatv.gui.sidebar.history import HistorySection
    from metatv.gui.sidebar.recommended import RecommendedSection

    config = Config(config_dir=tmp_path)
    splitter = QSplitter(Qt.Orientation.Vertical)
    qtbot.addWidget(splitter)
    built = {}
    for sid, cls in (("recommended", RecommendedSection),
                     ("favorites", FavoritesSection),
                     ("history", HistorySection)):
        section = cls(config, MagicMock())
        built[sid] = section
        splitter.addWidget(section)

    splitter.resize(330, 600)
    splitter.show()
    qtbot.waitExposed(splitter)
    return splitter, built


class TestTheHeadersAreBare:

    def test_no_section_draws_a_glyph_beside_its_title(self, qtbot, tmp_path):
        _splitter, built = _sections(qtbot, tmp_path)
        for sid, section in built.items():
            assert section._title_html() == f"<b>{section.title}</b>", sid

    def test_the_title_label_is_no_wider_than_its_words(self, qtbot, tmp_path):
        """RENDERED, and the assertion that fails against the icons.

        A glyph inside the label's rich text contributes real pixels, so the
        label's own size hint is what tells you whether one is there — a string
        check would pass on a label that still painted an <img>.
        """
        _splitter, built = _sections(qtbot, tmp_path)
        for sid, section in built.items():
            probe = QLabel()
            qtbot.addWidget(probe)
            probe.setTextFormat(Qt.TextFormat.RichText)
            probe.setText(f"<b>{section.title}</b>")
            probe.ensurePolished()
            assert section.title_label.sizeHint().width() <= probe.sizeHint().width(), (
                f"{sid}: the header label is wider than its own words, so "
                "something is still drawn beside them"
            )

    def test_watch_alerts_keeps_the_pill_and_loses_the_dot(self, qtbot, tmp_path):
        """The pill is the state now. The dot said the same thing, quieter."""
        from metatv.gui import theme as _theme
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        class _Cfg:
            def __init__(self, base):
                self.__dict__["_b"] = base
                self.get_vod_watch_alerts = lambda: []
                self.get_monitored_series = lambda: []
                self.get_vod_rule_unviewed_count = lambda _c: 0
                self.get_rules_with_new_matches_count = lambda: 2
                self.get_unviewed_vod_match_count = lambda: 2

            def __getattr__(self, name):
                return getattr(self.__dict__["_b"], name)

        section = WatchAlertsSection(_Cfg(Config(config_dir=tmp_path)), MagicMock())
        qtbot.addWidget(section)
        section.update_new_match_badge(2)

        html = section.title_label.text()
        assert html == "<b>Watch Alerts</b>", html
        assert _theme.COLOR_OK not in html, "the green state dot is back in the title"
        assert "2" in section._status_label.text(), "the count lost its pill"

    def test_the_dot_builder_is_gone_entirely(self):
        """Not merely unused — a second title builder is how the five drifted."""
        import metatv.gui.sidebar.alerts_common as common

        assert not hasattr(common, "_alerts_title_html")


def test_the_play_next_button_sits_inside_the_time(qtbot):
    """RENDERED. The tail is a column and an optional button outside it moves
    that column on the few rows that have one."""
    from PyQt6.QtWidgets import QPushButton

    from metatv.gui.chip_row import CHIP_YEAR, build_chip_row

    button = QPushButton("N")
    row = build_chip_row(title="Forever Knight", chips=((CHIP_YEAR, "S01E17"),),
                         tail="1d", trailing_button=button)
    qtbot.addWidget(row)
    row.resize(320, 22)
    row.show()
    qtbot.waitExposed(row)
    row.layout().activate()

    tail = next(w for w in row.findChildren(QLabel) if w.text() == "1d")
    assert tail.mapTo(row, QPoint(0, 0)).x() > button.mapTo(row, QPoint(0, 0)).x(), (
        "the play-next button is outside the time, so the time column breaks "
        "on every row that has one"
    )
