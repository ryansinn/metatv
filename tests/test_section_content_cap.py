"""A section cannot be taller than what it has to show.

``fit_to_rows`` pins each view to exactly its rows, so a section handed more
height than that pads the surplus around its content — nothing left in the
layout can absorb it. Measured on Recommended: a 420px section around a 160px
list, the gap split above and below. Owner: "recommended should never really be
able to go beyond the length of the list ... otherwise it's just dead space."

The rule, in the owner's words: "it should remember/hold the user assigned size
but then if there's less, it should be less, but if there's more, the height
should regress ... to the value the user manually sized it to" — ``min(remembered,
content)``.

Completes the set: a section declares a FLOOR (its header), a PREFERENCE
(``MIN_ROWS``, honoured when space is shared out) and now a MAXIMUM.

**Every test here drives a real QSplitter.** The first version put the section
in a fixed-height host and asserted its height came back to 260 — which it did,
because the HOST was 260. Three of four mutations passed against that, including
"never restore the user's size" and "no cap at all in the restore path". A
container that constrains the thing under test measures the container.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem, QSplitter

from metatv.core.config import Config
from metatv.gui.chip_row import build_chip_row

TALL = 900          # room for the section to exceed its content if uncapped


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _rig(qapp, tmp_path):
    """Recommended above History in a splitter with room to spare."""
    from metatv.gui.sidebar.history import HistorySection
    from metatv.gui.sidebar.recommended import RecommendedSection

    splitter = QSplitter(Qt.Orientation.Vertical)
    sec = RecommendedSection(Config(config_dir=tmp_path), MagicMock())
    other = HistorySection(Config(config_dir=tmp_path), MagicMock())
    splitter.addWidget(sec)
    splitter.addWidget(other)
    splitter.resize(300, TALL)
    splitter.show()
    qapp.processEvents()
    return splitter, sec


def _fill(qapp, sec, n):
    sec._list.clear()
    for i in range(n):
        item = QListWidgetItem()
        row = build_chip_row(title=f"Title {i}")
        item.setSizeHint(row.sizeHint())
        sec._list.addItem(item)
        sec._list.setItemWidget(item, row)
    sec.set_empty(n == 0)
    sec.reapply_row_budget()
    for _ in range(3):
        qapp.processEvents()
    sec._apply_pressure()          # debounced in the app; driven here
    for _ in range(3):
        qapp.processEvents()


def _drag(qapp, splitter, sec, height):
    """What a user dragging the handle does."""
    splitter.setSizes([height, TALL - height])
    qapp.processEvents()
    sec._apply_pressure()
    for _ in range(3):
        qapp.processEvents()


class TestASectionStopsAtItsContent:

    def test_the_splitter_cannot_hand_it_more_than_it_can_fill(
            self, qapp, tmp_path):
        """The reported bug: offered 700px for four rows, it took 700."""
        splitter, sec = _rig(qapp, tmp_path)
        try:
            _fill(qapp, sec, 4)
            _drag(qapp, splitter, sec, 700)
            assert sec.height() < 300, (
                f"section took {sec.height()}px for 4 rows — the surplus is "
                "dead space"
            )
            assert sec.height() <= sec.max_useful_height() + 4
        finally:
            splitter.deleteLater()
            qapp.processEvents()

    def test_a_long_list_may_still_be_tall(self, qapp, tmp_path):
        """The cap is content, not a constant — it must not clamp a full list."""
        splitter, sec = _rig(qapp, tmp_path)
        try:
            _fill(qapp, sec, 30)
            _drag(qapp, splitter, sec, 700)
            assert sec.height() > 400, sec.height()
        finally:
            splitter.deleteLater()
            qapp.processEvents()

    def test_it_never_caps_below_the_floor(self, qapp, tmp_path):
        splitter, sec = _rig(qapp, tmp_path)
        try:
            _fill(qapp, sec, 0)
            assert sec.max_useful_height() >= sec.min_expanded_height()
        finally:
            splitter.deleteLater()
            qapp.processEvents()


class TestTheUserSizeSurvivesContentChanges:
    """The half that is easy to get wrong: the remembered value has to survive
    the shrink it exists to undo."""

    def test_shrink_then_grow_returns_to_the_users_size(self, qapp, tmp_path):
        splitter, sec = _rig(qapp, tmp_path)
        try:
            _fill(qapp, sec, 30)
            _drag(qapp, splitter, sec, 300)
            chosen = sec.height()
            assert 250 < chosen < 350, chosen

            _fill(qapp, sec, 3)
            assert sec.height() < chosen - 50, (
                f"still {sec.height()}px with 3 rows — it did not shrink"
            )

            _fill(qapp, sec, 30)
            assert abs(sec.height() - chosen) < 25, (
                f"came back to {sec.height()}, not the {chosen} the user chose"
            )
        finally:
            splitter.deleteLater()
            qapp.processEvents()

    def test_the_cycle_is_stable(self, qapp, tmp_path):
        splitter, sec = _rig(qapp, tmp_path)
        try:
            _fill(qapp, sec, 30)
            _drag(qapp, splitter, sec, 300)
            chosen = sec.height()
            for _ in range(3):
                _fill(qapp, sec, 3)
                _fill(qapp, sec, 30)
                assert abs(sec.height() - chosen) < 25, (
                    f"drifted to {sec.height()} from {chosen}"
                )
        finally:
            splitter.deleteLater()
            qapp.processEvents()

    # test_a_deliberate_resize_is_adopted lived here. It asserted that the
    # section RECORDED the user's height — and it was testing machinery that
    # turned out to do nothing: QSplitter already returns a widget's share when
    # its maximum lifts, so the bookkeeping was removed. What the owner asked
    # for ("hold the user assigned size ... regress to the value the user
    # manually sized it to") is covered above, as behaviour, by
    # test_shrink_then_grow_returns_to_the_users_size.


class TestTheCapAndTheFoldPassDoNotFight:
    """Two features that meet badly if the cap is applied blindly.

    The cap is measured AFTER the fold pass, so capping a section that has
    folded its own groups would pin it at its FOLDED height — and then there is
    never room for those groups to come back. Folding becomes a one-way
    ratchet: shrink the sidebar once and Watch Alerts stays collapsed forever,
    however much space you give it back.

    A section that has hidden some of its own content is by definition not
    showing dead space, so the cap has nothing to say about it.
    """

    def _alerts(self, qapp, tmp_path):
        from unittest.mock import MagicMock

        from metatv.gui.sidebar.alerts import WatchAlertsSection

        class _Cfg:
            def __init__(self, base):
                self.__dict__["_b"] = base
                self.get_vod_watch_alerts = lambda: [
                    {"text": "Rule", "match_type": "any", "created": "r1",
                     "alerted_ids": ["a"]}]
                self.get_monitored_series = lambda: [
                    {"cid": f"s{i}", "channel_id": f"s{i}", "title": f"S{i}",
                     "display_title": f"S{i}", "unseen": 1, "unseen_new": 1,
                     "language": "EN", "region": "US", "source": "TREX"}
                    for i in range(8)]
                self.get_vod_rule_unviewed_count = lambda _c: 2
                self.get_rules_with_new_matches_count = lambda: 1
                self.get_unviewed_vod_match_count = lambda: 2

            def __getattr__(self, n):
                if n == "alerts_show_idle_items":
                    return True
                return getattr(self.__dict__["_b"], n)

        sec = WatchAlertsSection(_Cfg(Config(config_dir=tmp_path)), MagicMock())
        sec.refresh_vod_rules()
        sec.refresh_retry([])
        qapp.processEvents()
        return sec

    def test_a_folded_section_is_not_capped_at_its_folded_size(
            self, qapp, tmp_path):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QSplitter

        from metatv.gui.sidebar.history import HistorySection

        splitter = QSplitter(Qt.Orientation.Vertical)
        sec = self._alerts(qapp, tmp_path)
        splitter.addWidget(sec)
        splitter.addWidget(HistorySection(Config(config_dir=tmp_path),
                                          MagicMock()))
        splitter.resize(300, TALL)
        splitter.show()
        qapp.processEvents()

        splitter.setSizes([200, TALL - 200])      # squeeze until it folds
        qapp.processEvents()
        sec._apply_pressure()
        for _ in range(3):
            qapp.processEvents()
        assert sec._auto_folded, "nothing folded, so there is nothing to test"

        assert sec.maximumHeight() > 400, (
            f"a folded section is capped at {sec.maximumHeight()}px — its "
            "groups can never get the room to come back"
        )

        splitter.setSizes([700, TALL - 700])      # give it all back
        qapp.processEvents()
        sec._apply_pressure()
        for _ in range(3):
            qapp.processEvents()
        assert not sec._auto_folded, (
            f"still folded with 700px available: {sec._auto_folded}"
        )
        splitter.deleteLater()
        qapp.processEvents()
