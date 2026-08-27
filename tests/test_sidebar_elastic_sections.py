"""A sidebar section shrinks to its header, and scrolls on the way.

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

On the way down it SCROLLS. It used to fold its groups to their headings and
unfold them when space came back; that is gone (see :mod:`section_cap` for the
four defects it caused), and these tests now hold the opposite line — a resize
never touches a group. What does survive the shrink is the cap: the section
still refuses to claim more height than its content can fill.
"""

from __future__ import annotations

import time
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
        # The full list, so there is something to fold: these tests are about
        # VERTICAL space, not about which entries are eligible.
        if n == "alerts_show_idle_items":
            return True
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


def _settle(qapp, sec):
    """Spin until anything the resize SCHEDULED has had its chance to run.

    Not a nicety. These tests assert that a resize leaves the groups alone,
    and the pass that used to close them was debounced — so a test that only
    calls ``processEvents`` in a tight loop never lets the timer fire and
    passes against the very code it was written to reject. Driving the cap
    directly has the same blind spot from the other side.
    """
    deadline = time.monotonic() + (sec.CAP_DEBOUNCE_MS / 1000) * 4
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


def _at(qapp, sec, height):
    """Put the section at an exact height and let it react."""
    host = QWidget()
    host.setFixedSize(300, height)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(sec)
    host.show()
    qapp.processEvents()
    sec._apply_content_cap()
    _settle(qapp, sec)
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


#: Every group's "am I closed?" flag, by the name the section keeps it under.
_GROUP_FLAGS = ("_retry_collapsed", "_epg_collapsed",
                "_keyword_collapsed", "_series_collapsed")


def _open_groups(sec) -> set[str]:
    """The groups currently showing their rows."""
    return {f for f in _GROUP_FLAGS if not getattr(sec, f)}


class TestShrinkingNeverClosesAGroup:
    """The behaviour that replaced folding, and the reason it replaced it.

    Under pressure the section used to close its own groups, least important
    first. Every one of these assertions is RED against that code, which is
    the point: the fold was not a bug in need of tuning, it was the wrong
    answer, and the tests that guarded it were guarding the defect.
    """

    def test_a_hard_squeeze_leaves_every_group_open(self, qapp, tmp_path):
        """120px — barely the header — and all four groups are still open.

        Owner, on EPG closing itself when the section was dragged down:
        "Maybe I wanted to see just the epg, now I have to reopen it."
        """
        sec = _alerts(qapp, tmp_path)
        before = _open_groups(sec)
        assert before, "nothing was open, so nothing could be closed"

        host = _at(qapp, sec, 120)
        assert _open_groups(sec) == before, (
            f"the section closed its own groups under pressure: "
            f"{sorted(before - _open_groups(sec))}"
        )
        host.deleteLater()

    def test_no_height_closes_a_group(self, qapp, tmp_path):
        """Swept, not sampled — the fold had a threshold, and a single height
        can sit on either side of it."""
        sec = _alerts(qapp, tmp_path)
        before = _open_groups(sec)
        host = _at(qapp, sec, 600)
        for height in range(600, 100, -40):
            host.setFixedHeight(height)
            sec._apply_content_cap()
            _settle(qapp, sec)
            assert _open_groups(sec) == before, f"a group closed at {height}px"
        host.deleteLater()

    def test_the_content_still_scrolls_when_it_does_not_fit(self, qapp, tmp_path):
        """Nothing is CLIPPED by refusing to fold — the scroll area takes it.

        This is what makes the removal safe rather than merely simpler: the
        rows a fold would have hidden are still reachable.
        """
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 120)
        area = sec.content_scroll
        assert area.verticalScrollBar().maximum() > 0, (
            "content taller than the section, but nothing to scroll to"
        )
        host.deleteLater()


class TestTheCapTracksTheContent:
    """The half of the pressure pass that was doing real work."""

    def test_the_cap_is_the_content_at_every_height(self, qapp, tmp_path):
        """Never QWIDGETSIZE_MAX.

        The old pass stood the cap DOWN whenever anything was auto-folded, so
        a folded Watch Alerts advertised an unlimited maximum and kept the
        height it had been given — 600px of headings, with Recommended unable
        to grow into it. Owner: "when recommendations load, shouldn't they
        push up and expand up into the empty space of Watch Alert? because
        they don't."
        """
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 600)
        for height in (600, 400, 300, 200, 120):
            host.setFixedHeight(height)
            sec._apply_content_cap()
            _settle(qapp, sec)
            assert sec.maximumHeight() == sec.max_useful_height(), height
            assert sec.maximumHeight() < 16777215, (
                f"the cap stood down at {height}px, so the splitter may hand "
                f"this section more height than it can fill"
            )
        host.deleteLater()

    def test_the_cap_pass_does_not_re_enter(self, qapp, tmp_path):
        """Measuring the content runs the row budget, which lands back here."""
        sec = _alerts(qapp, tmp_path)
        host = _at(qapp, sec, 200)
        calls = []
        real = sec._apply_content_cap

        def counting():
            calls.append(1)
            assert len(calls) < 20, "runaway re-entry"
            real()

        sec._apply_content_cap = counting
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
        # min(preference, its own content cap). A section that HAS no content
        # to show is not being starved by being small — that is the cap doing
        # its job, and asserting the raw preference here would demand dead
        # space be reserved for an empty section.
        floor = min(b.preferred_expanded_height(), b.max_useful_height())
        assert sizes[1] >= floor - 4, (
            f"History was squashed to {sizes[1]}px, below the {floor}px it "
            "asks for and can actually fill"
        )
        splitter.deleteLater()
