"""A sidebar section shrinks to its header, folding its groups on the way.

The bug: ``min_expanded_height()`` returned a MIN_ROWS-derived preference and
the splitter enforced it as a wall. Watch Alerts declares ``MIN_ROWS = 7`` and
earns ``NEWS_BOOST_ROWS = 2`` more while it has news, so it could not be dragged
below **367px** — by far the tallest floor in the sidebar, and every other
section had to live around it. Owner: "watch alerts still doesn't reduce
vertically less than this ... the vertical resize should be standardized and
allow to collapse down to nothing except the resize row".

Two limits now, where there was one:

* ``preferred_expanded_height()`` — what the section WANTS. Automatic
  redistribution respects it, so growing one section never starves a neighbour.
* ``min_expanded_height()`` — the hard floor, now just the header. Only the
  user dragging a handle goes here.

On the way down a section folds its groups to their headings, and unfolds them
again when the space comes back. The single thing this must never get wrong is
re-opening a group the USER closed, which is what ``_auto_folded`` is for.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QSplitter, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt

from metatv.core.config import Config
from metatv.gui.sidebar.base import CollapsibleSection


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _series(cid, title, unseen):
    return {"cid": cid, "channel_id": cid, "title": title, "display_title": title,
            "unseen": unseen, "unseen_new": unseen, "language": "EN",
            "region": "US", "source": "TREX"}


class _Cfg:
    """A real Config with the section's data accessors bolted on.

    Config is a pydantic model and rejects new attributes, so it is wrapped
    rather than subclassed.
    """

    def __init__(self, base, rules, series):
        self.__dict__["_b"] = base
        self.get_vod_watch_alerts = lambda: rules
        self.get_monitored_series = lambda: series
        self.get_vod_rule_unviewed_count = lambda _c: 0
        self.get_rules_with_new_matches_count = lambda: 0
        self.get_unviewed_vod_match_count = lambda: 0

    def __getattr__(self, n):
        return getattr(self.__dict__["_b"], n)


def _alerts(qapp, tmp_path, *, series_n=7):
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    cfg = _Cfg(
        Config(config_dir=tmp_path),
        [{"text": "Neighborhood Watch", "match_type": "any", "created": "r1",
          "alerted_ids": ["1"]}],
        [_series(f"s{i}", f"Series {i}", 1 if i < 2 else 0) for i in range(series_n)],
    )
    sec = WatchAlertsSection(cfg, MagicMock())
    sec.refresh_vod_rules()
    sec.refresh_retry([])
    qapp.processEvents()
    return sec


def _at(qapp, sec, height):
    """Put the section at an exact height and run the pressure pass.

    The pass is debounced, so a test drives it directly rather than sleeping —
    the debounce is a cost control, not part of the behaviour under test.
    """
    host = QWidget()
    host.setFixedSize(300, height)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(sec)
    host.show()
    qapp.processEvents()
    sec._apply_pressure()
    qapp.processEvents()
    return host


class TestTheFloorIsTheHeader:
    """The wall comes down, for every section."""

    def test_the_hard_floor_is_just_the_header(self, qapp, tmp_path):
        """The header and the card's border — room for no content at all.

        Asserted as a RANGE, not as ``== HEADER_H``: the floor has to count the
        frame or the title clips, and an exact-equality assertion would turn
        that correction into a failure while the behaviour improved.
        """
        sec = _alerts(qapp, tmp_path)
        floor = sec.min_expanded_height()
        assert sec.HEADER_H <= floor < sec.HEADER_H + sec.CONTENT_ROW_H, floor
        assert sec.minimumHeight() == floor

    def test_the_preference_still_reflects_min_rows(self, qapp, tmp_path):
        """The MIN_ROWS knob keeps meaning something — it just is not a wall."""
        sec = _alerts(qapp, tmp_path)
        expected = sec.HEADER_H + sec.MIN_ROWS * sec.CONTENT_ROW_H + 8
        assert sec.preferred_expanded_height() >= expected
        assert sec.preferred_expanded_height() > sec.min_expanded_height()

    def test_a_section_can_actually_be_drawn_at_its_header(self, qapp, tmp_path):
        """Geometry, not just the declared minimum: the old floor was enforced
        by the LAYOUT, so a test asserting only minimumHeight would pass while
        the section still refused to shrink."""
        sec = _alerts(qapp, tmp_path)
        floor = sec.min_expanded_height()
        host = _at(qapp, sec, floor)
        assert sec.height() <= floor, (
            f"the section drew {sec.height()}px in a {floor}px host"
        )
        # ...and the header is fully drawn there, not split with the content.
        assert sec._header.height() >= sec.HEADER_H, (
            f"the header got {sec._header.height()}px of {floor} — the title "
            "will be clipped"
        )
        host.deleteLater()

    def test_every_section_type_has_a_header_floor(self, qapp, tmp_path):
        """Standardised, per the owner — not a Watch Alerts special case."""
        from metatv.gui.sidebar.favorites import FavoritesSection
        from metatv.gui.sidebar.history import HistorySection
        from metatv.gui.sidebar.queue import WatchQueueSection
        from metatv.gui.sidebar.recommended import RecommendedSection

        cfg = Config(config_dir=tmp_path)
        for cls in (FavoritesSection, HistorySection, WatchQueueSection,
                    RecommendedSection):
            sec = cls(cfg, MagicMock())
            assert sec.HEADER_H <= sec.min_expanded_height() \
                < sec.HEADER_H + sec.CONTENT_ROW_H, cls.__name__
            assert sec.preferred_expanded_height() > sec.HEADER_H, cls.__name__
            sec.deleteLater()


class TestGroupsFoldUnderPressure:
    """Shrinking degrades; it does not clip."""

    def test_a_shorter_section_folds_at_least_as_much(self, qapp, tmp_path):
        """Monotonic. A non-monotonic rule is what a naive fit test produces,
        and it reads as the panel making decisions at random."""
        counts = []
        for h in (560, 400, 300, 200, 120):
            sec = _alerts(qapp, tmp_path)
            host = _at(qapp, sec, h)
            counts.append(len(sec._auto_folded))
            host.deleteLater()
            qapp.processEvents()
        assert counts == sorted(counts), counts
        assert counts[0] == 0, "a tall section should fold nothing"
        assert counts[-1] > 0, "a short section should fold something"

    def test_the_last_group_is_never_folded(self, qapp, tmp_path):
        """It absorbs the leftover space by scrolling.

        Folding everything leaves a stack of headings with dead space beneath
        — strictly less information than the same headings plus a scrolling
        group.
        """
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 120)
        groups = sec.pressure_groups()
        assert groups[-1].key not in sec._auto_folded
        assert len(sec._auto_folded) == len(groups) - 1
        host.deleteLater()

    def test_an_empty_group_folds_before_one_with_rows(self, qapp, tmp_path):
        """Stream Monitoring is empty here, so it goes first whatever its
        place in the base order — folding a heading with nothing under it
        costs nothing."""
        sec = _alerts(qapp, tmp_path)
        order = [g.key for g in sec.pressure_groups()]
        assert order[0] == "monitor", order

    def test_folding_frees_real_height(self, qapp, tmp_path):
        """The point of folding, measured: the content actually gets shorter."""
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 560)
        tall = sec._content_height()
        host.deleteLater()

        sec2 = _alerts(qapp, tmp_path)
        host2 = _at(qapp, sec2, 200)
        short = sec2._content_height()
        host2.deleteLater()
        assert short < tall, (tall, short)


class TestSpaceComingBackReopensThem:
    """The half the owner asked for by name."""

    def test_growing_again_unfolds_what_shrinking_folded(self, qapp, tmp_path):
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 200)
        assert sec._auto_folded, "nothing folded, so nothing to re-open"

        host.setFixedHeight(600)
        qapp.processEvents()
        sec._apply_pressure()
        qapp.processEvents()
        assert not sec._auto_folded, (
            f"still folded after the space came back: {sec._auto_folded}"
        )
        host.deleteLater()

    def test_a_group_the_user_closed_is_never_re_opened(self, qapp, tmp_path):
        """The one thing this mechanism must not get wrong.

        Auto-unfold may only re-open what auto-fold closed. Without the
        distinction, freeing space anywhere in the sidebar would silently undo
        a deliberate collapse.
        """
        sec = _alerts(qapp, tmp_path)
        sec._toggle_series_group()                 # the user collapses Series
        assert sec._series_collapsed
        qapp.processEvents()

        host = _at(qapp, sec, 200)                 # squeeze...
        assert "series" not in sec._auto_folded, (
            "a user-collapsed group was claimed as ours to re-open"
        )
        host.setFixedHeight(600)                   # ...and give it all back
        qapp.processEvents()
        sec._apply_pressure()
        qapp.processEvents()

        assert sec._series_collapsed, (
            "the user's collapse was undone when space came back"
        )
        host.deleteLater()

    def test_a_group_re_opens_with_slack_not_on_a_bare_fit(self, qapp, tmp_path):
        """What ``PRESSURE_HYSTERESIS`` buys, measured at the boundary.

        A group that re-opens the instant it *just* fits will fold again on the
        next pixel of drag, because opening it is what changes the height being
        measured. So the moment one comes back there must be real slack.

        Measured by walking the height up until a group actually re-opens —
        the first version of this test asserted "re-running the pass at a fixed
        height is stable", which passed with the hysteresis removed, because a
        fixed height is a fixed point either way. The flicker lives at the
        boundary, so the test has to stand on it.
        """
        STEP = 4
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 200)
        folded = len(sec._auto_folded)
        assert folded, "nothing folded, so nothing can re-open"

        slack_at_reopen = None
        for height in range(200, 900, STEP):
            host.setFixedHeight(height)
            qapp.processEvents()
            sec._apply_pressure()
            qapp.processEvents()
            if len(sec._auto_folded) < folded:
                slack_at_reopen = (sec.height() - sec.HEADER_H) - sec._content_height()
                break
            folded = len(sec._auto_folded)
        host.deleteLater()

        assert slack_at_reopen is not None, "no group ever re-opened"
        assert slack_at_reopen >= sec.PRESSURE_HYSTERESIS - STEP, (
            f"a group re-opened with only {slack_at_reopen}px to spare; it "
            f"needs {sec.PRESSURE_HYSTERESIS}px or it will fold straight back"
        )

    def test_the_fold_set_is_a_fixed_point_at_one_height(self, qapp, tmp_path):
        """No drift from simply re-running the pass."""
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 330)
        first = set(sec._auto_folded)
        for _ in range(6):
            sec._apply_pressure()
            qapp.processEvents()
            assert set(sec._auto_folded) == first, (
                f"the fold set moved without a resize: {first} -> {sec._auto_folded}"
            )
        host.deleteLater()

    def test_the_pass_does_not_re_enter(self, qapp, tmp_path):
        """Folding a group resizes the section, which would re-enter the pass."""
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 200)
        calls = []
        real = sec._apply_pressure

        def counting():
            calls.append(1)
            assert len(calls) < 20, "runaway re-entry"
            real()

        sec._apply_pressure = counting
        sec.resize(300, 150)
        qapp.processEvents()
        host.deleteLater()


class TestAutomaticSharingStillRespectsPreferences:
    """Only the user may take a section below what it says it needs."""

    def test_a_growing_section_does_not_squash_a_neighbour_to_its_header(
            self, qapp, tmp_path):
        from metatv.gui.sidebar.history import HistorySection

        splitter = QSplitter(Qt.Orientation.Vertical)
        a = _alerts(qapp, tmp_path)
        b = HistorySection(Config(config_dir=tmp_path), MagicMock())
        splitter.addWidget(a)
        splitter.addWidget(b)
        splitter.resize(300, 900)
        splitter.setSizes([450, 450])
        splitter.show()
        qapp.processEvents()

        a._expanded_height = 880
        a._grow_in_splitter()
        qapp.processEvents()

        sizes = splitter.sizes()
        assert sizes[1] >= b.preferred_expanded_height(), (
            f"History was squashed to {sizes[1]}px, below the "
            f"{b.preferred_expanded_height()}px it asks for"
        )
        splitter.deleteLater()
