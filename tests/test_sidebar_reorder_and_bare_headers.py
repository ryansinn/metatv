"""Sidebar headers lose their icons; the ⋯ menu gains Move up / Move down.

The icons were decoration — "Watch Queue" beside the words "Watch Queue" — kept
on the theory that they might become the drag handle for reordering. Reordering
went to the ⋯ menu instead: five sections is a short list, a menu is
discoverable where a drag gesture is not, and a drag on the header would have
collided with click-to-collapse on the same widget. Owner: "it might be time to
ditch the icons ... unless they're allowed to be used to drag and drop their
positioning" — they are not, so they went.

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
    from metatv.gui.main_window import MainWindow
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

    class _Host:
        pass

    host = _Host()
    host.sidebar_splitter = splitter
    host.sidebar_sections = built
    host.config = config
    move = MainWindow._move_sidebar_section.__get__(host, _Host)
    for section in built.values():
        section.move_request = move
    splitter.resize(330, 600)
    splitter.show()
    qtbot.waitExposed(splitter)
    return host, splitter, built


def _order(splitter, built):
    return [next(sid for sid, sec in built.items() if sec is splitter.widget(i))
            for i in range(splitter.count())]


class TestTheHeadersAreBare:

    def test_no_section_draws_a_glyph_beside_its_title(self, qtbot, tmp_path):
        _host, _splitter, built = _sections(qtbot, tmp_path)
        for sid, section in built.items():
            assert section._title_html() == f"<b>{section.title}</b>", sid

    def test_the_title_label_is_no_wider_than_its_words(self, qtbot, tmp_path):
        """RENDERED, and the assertion that fails against the icons.

        A glyph inside the label's rich text contributes real pixels, so the
        label's own size hint is what tells you whether one is there — a string
        check would pass on a label that still painted an <img>.
        """
        _host, _splitter, built = _sections(qtbot, tmp_path)
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


class TestMovingSections:

    def test_the_first_section_cannot_move_up(self, qtbot, tmp_path):
        _host, _splitter, built = _sections(qtbot, tmp_path)
        labels = [a.label for a in built["recommended"].reorder_actions()]
        assert labels == ["Move down"], labels

    def test_the_last_section_cannot_move_down(self, qtbot, tmp_path):
        _host, _splitter, built = _sections(qtbot, tmp_path)
        labels = [a.label for a in built["history"].reorder_actions()]
        assert labels == ["Move up"], labels

    def test_a_middle_section_can_go_either_way(self, qtbot, tmp_path):
        _host, _splitter, built = _sections(qtbot, tmp_path)
        labels = [a.label for a in built["favorites"].reorder_actions()]
        assert labels == ["Move up", "Move down"], labels

    def test_running_the_action_reorders_the_rail(self, qtbot, tmp_path):
        _host, splitter, built = _sections(qtbot, tmp_path)
        before = _order(splitter, built)
        down = next(a for a in built["recommended"].reorder_actions()
                    if a.label == "Move down")
        down.run()
        assert _order(splitter, built) == ["favorites", "recommended", "history"]
        assert _order(splitter, built) != before

    def test_the_new_order_is_persisted(self, qtbot, tmp_path):
        host, splitter, built = _sections(qtbot, tmp_path)
        next(a for a in built["history"].reorder_actions()
             if a.label == "Move up").run()
        assert host.config.sidebar_sections == _order(splitter, built)
        assert host.config.sidebar_sections == ["recommended", "history", "favorites"]

    def test_a_hidden_neighbour_is_stepped_over(self, qtbot, tmp_path):
        """Hidden sections stay in the splitter so unhiding keeps their place.
        Stepping one INDEX at a time would spend a click doing nothing visible."""
        host, splitter, built = _sections(qtbot, tmp_path)
        built["favorites"].setVisible(False)
        next(a for a in built["recommended"].reorder_actions()
             if a.label == "Move down").run()
        # Past the hidden Favorites, landing after History — not before it.
        assert _order(splitter, built) == ["favorites", "history", "recommended"]

    def test_a_move_never_collapses_a_section(self, qtbot, tmp_path):
        """``insertWidget`` re-parents, which drops the widget's size.

        Exact preservation is NOT the contract and asserting it was wrong: the
        content cap (#487) already bounds each section at its own content, so
        the splitter is entitled to re-split within those caps. What must never
        happen is a section landing at zero — reordering the rail is not
        permission to close something.
        """
        _host, splitter, built = _sections(qtbot, tmp_path)
        splitter.setSizes([300, 150, 150])
        qtbot.wait(1)
        next(a for a in built["recommended"].reorder_actions()
             if a.label == "Move down").run()
        qtbot.wait(1)
        assert all(size > 0 for size in splitter.sizes()), splitter.sizes()

    def test_a_section_with_no_host_offers_nothing(self, qtbot, tmp_path):
        """A bare double has no seam, and must not grow a dead menu entry."""
        from metatv.gui.sidebar.history import HistorySection

        section = HistorySection(Config(config_dir=tmp_path), MagicMock())
        qtbot.addWidget(section)
        assert section.reorder_actions() == []


def test_a_promoted_action_survives_the_new_entries(qtbot, tmp_path):
    """Recommended's one-click refresh must not be demoted into the menu.

    Promotion asks "does this section have exactly ONE action?", and two
    reorder entries made the answer no everywhere. Owner: "since there's only
    one item under the ... it should just be the refresh icon and function
    instead ... otherwise it's just a wasted click."
    """
    _host, _splitter, built = _sections(qtbot, tmp_path)
    section = built["recommended"]
    assert len(section.overflow_actions()) == 1, "premise changed — retarget this"
    button = section._overflow_btn
    assert button.toolTip().startswith(section.overflow_actions()[0].tooltip), (
        "the button stopped advertising its promoted action"
    )
    # ...and the reorder entries still have somewhere to go, without the
    # promoted action appearing a second time inside its own menu.
    labels = [a.label for a in section._menu_actions()]
    assert labels == ["Move down"], labels


def test_the_menu_is_rebuilt_from_a_fresh_read(qtbot, tmp_path):
    """Built once, it would offer "Move up" on whatever section happened to be
    first when the window opened — forever, however much the rail moved."""
    _host, splitter, built = _sections(qtbot, tmp_path)
    assert [a.label for a in built["recommended"]._menu_actions()] == ["Move down"]
    next(a for a in built["recommended"].reorder_actions()
         if a.label == "Move down").run()
    assert "Move up" in [a.label for a in built["recommended"]._menu_actions()], (
        "after moving down it still cannot move back up"
    )


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
