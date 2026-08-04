"""Removing one sidebar row must not rebuild the whole section (#292).

Owner: "the entire watch queue still refreshes when a single line is removed…
should be in place removal for all sections of the side panel."

Every sidebar mutation funnelled into ``section.refresh()``: an off-thread
re-read of the whole table, then every row's widget destroyed and rebuilt. On
the owner's 612-entry queue that is ~600 chip rows torn down to delete one.
Preserving the scroll position (#290) hid the jump; it did not remove the work.

``InPlaceRowMixin`` (``sidebar/base.py``) now takes the row out directly, and is
deliberately narrow: it only removes rows the caller has ALREADY deleted from
the DB, and returns False when it cannot find them so the host falls back to a
full refresh rather than leave the sidebar disagreeing with the database.

Asserts the row is GONE FROM THE PAINTED LIST and that the surviving rows kept
their identity — a test that only counted rows would pass on a silent full
rebuild, which is the thing being removed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.core.config import Config
from metatv.core.repositories.queue import QueueEntry
from metatv.gui.chip_row import MiddleElideLabel
from metatv.gui.sidebar.queue import WatchQueueSection


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


_BASE = datetime(2026, 5, 1, 12, 0, 0)


def _entry(name, *, days=0, played=None, available=True, episode=None):
    return QueueEntry(
        queue_id=abs(hash(name)) % 100000,
        channel_id=f"ch-{name}",
        channel_name=name,
        media_type="series" if episode else "movie",
        last_played=played,
        channel=None,
        available=available,
        search_title=name,
        added_at=_BASE + timedelta(days=days),
        episode_id=episode,
        season_num=1 if episode else None,
        episode_num=2 if episode else None,
    )


@pytest.fixture()
def queue(qapp):
    sec = WatchQueueSection(Config(), db=None)
    sec.resize(260, 320)
    sec.show()
    QApplication.processEvents()
    yield sec
    sec.hide()


def _titles(section, lst=None):
    lst = lst if lst is not None else section._list
    out = []
    for i in range(lst.count()):
        item = lst.item(i)
        widget = lst.itemWidget(item)
        if widget is None:
            out.append(item.text())
        else:
            label = widget.findChild(MiddleElideLabel)
            out.append(label.text() if label else "")
    return out


def _widgets(section):
    return [
        section._list.itemWidget(section._list.item(i))
        for i in range(section._list.count())
    ]


class TestTheQueue:

    def test_the_row_leaves_and_the_others_are_not_rebuilt(self, queue):
        """The whole point: same widget objects before and after.

        Identity is the assertion that matters. A full refresh would produce a
        list with the same TITLES but every widget newly constructed, which a
        count- or text-based check cannot tell apart.
        """
        queue._populate_rows([
            _entry("Keep One", days=1), _entry("Delete Me", days=2),
            _entry("Keep Two", days=3),
        ])
        QApplication.processEvents()
        survivors = {id(w) for w in _widgets(queue) if w is not None}

        assert queue.remove_row("ch-Delete Me") is True
        QApplication.processEvents()

        titles = _titles(queue)
        assert "Delete Me" not in titles
        assert "Keep One" in titles and "Keep Two" in titles
        still_there = {id(w) for w in _widgets(queue) if w is not None}
        assert still_there < survivors, "the list was rebuilt, not edited"
        assert len(still_there) == 2

    def test_the_header_count_follows_the_row_out(self, queue):
        """A header claiming (3) over two rows misstates the list."""
        queue._populate_rows([
            _entry("A", days=1), _entry("B", days=2), _entry("C", days=3),
        ])
        assert "Never Watched (3)" in _titles(queue)

        queue.remove_row("ch-B")
        QApplication.processEvents()

        assert "Never Watched (2)" in _titles(queue)

    def test_emptying_a_group_takes_its_header_too(self, queue):
        """The last row of a group leaves — no header standing over nothing."""
        queue._populate_rows([
            _entry("Watched One", days=1, played=_BASE),
            _entry("Queued One", days=2),
        ])
        assert "Continue Watching" in _titles(queue)

        queue.remove_row("ch-Watched One")
        QApplication.processEvents()

        titles = _titles(queue)
        assert "Continue Watching" not in titles
        assert "Never Watched (1)" in titles

    def test_an_unknown_id_reports_false_so_the_host_can_refresh(self, queue):
        """False is load-bearing: it is what stops a stale row surviving.

        A no-op that returned True would leave a deleted item on screen.
        """
        queue._populate_rows([_entry("Only", days=1)])
        assert queue.remove_row("ch-not-rendered") is False
        assert "Only" in _titles(queue)

    def test_unqueuing_a_series_leaves_its_queued_episode_alone(self, queue):
        """Channel- and episode-grain rows are independent entries.

        Both carry the same ``channel_id`` (an episode row's channel_id is its
        PARENT series), so matching on that alone would delete both.
        """
        series = _entry("Show", days=1)
        episode = _entry("Show", days=2, episode="ep-77")
        episode.channel_id = series.channel_id       # same parent, as in production
        queue._populate_rows([series, episode])
        QApplication.processEvents()
        assert len(_widgets(queue)) - _titles(queue).count("Never Watched (2)") == 2

        queue.remove_row(series.channel_id)          # unqueue the series root
        QApplication.processEvents()

        remaining = [t for t in _titles(queue) if t and not t.startswith("Never")]
        assert len(remaining) == 1, remaining
        assert "S01E02" in remaining[0], "the queued EPISODE was removed too"

    def test_an_active_filter_survives_and_stays_honest(self, queue):
        """Removing a row while filtering must not drop or misreport the filter."""
        queue._populate_rows([
            _entry("Blade Runner", days=1), _entry("Blade Runner 2049", days=2),
            _entry("The Lobster", days=3),
        ])
        queue._set_filter_visible(True, save=False)
        queue._filter.setText("blade")
        QApplication.processEvents()

        queue.remove_row("ch-Blade Runner 2049")
        QApplication.processEvents()

        assert queue._filter.text() == "blade"
        painted = [
            _titles(queue)[i] for i in range(queue._list.count())
            if queue._list.visualItemRect(queue._list.item(i)).height() > 0
        ]
        assert "Never Watched (1 of 2)" in painted, painted
        assert not any("2049" in p for p in painted)

    def test_removing_the_last_row_empties_the_section(self, queue):
        queue._populate_rows([_entry("Solo", days=1)])
        queue.remove_row("ch-Solo")
        QApplication.processEvents()

        assert queue.is_empty


class TestTheOtherSections:
    """Favorites, History and Recommended get it from the same mixin."""

    def _favorites(self, qapp):
        from metatv.gui.sidebar.favorites import FavoritesSection
        sec = FavoritesSection(Config(), db=None)
        sec.resize(260, 320)
        sec.show()
        QApplication.processEvents()
        return sec

    def _fav_dto(self, i, played=None):
        return SimpleNamespace(
            id=f"f{i}", name=f"Fav {i}", detected_title=f"Fav {i}",
            media_type="movie", detected_year="2024", detected_quality="",
            detected_prefix="EN", last_played=played, available=True,
            search_title=f"Fav {i}", is_episode=False,
        )

    def test_favorites_removes_in_place(self, qapp):
        sec = self._favorites(qapp)
        sec._populate_rows(([self._fav_dto(1), self._fav_dto(2)], []))
        QApplication.processEvents()

        assert sec.remove_row("f1") is True
        QApplication.processEvents()

        titles = _titles(sec, sec.favorites_list)
        assert "Fav 1" not in titles and "Fav 2" in titles
        sec.hide()

    def test_favorites_drops_an_emptied_group_header(self, qapp):
        sec = self._favorites(qapp)
        sec._populate_rows((
            [self._fav_dto(1, played=_BASE), self._fav_dto(2)], [],
        ))
        QApplication.processEvents()
        assert "Continue Watching" in _titles(sec, sec.favorites_list)

        sec.remove_row("f1")
        QApplication.processEvents()

        assert "Continue Watching" not in _titles(sec, sec.favorites_list)
        sec.hide()

    def test_recommended_removes_in_place(self, qapp):
        from metatv.gui.sidebar.recommended import RecommendedSection

        def rec(i):
            return SimpleNamespace(
                channel_id=f"r{i}", channel_name=f"Rec {i}", detected_title=f"Rec {i}",
                media_type="movie", reason="because", variant_count=1,
                metadata_rating=7.0, rec_shown_count=0, matching_genres=["Drama"],
                already_liked=False, detected_year="2024", detected_quality="",
                detected_prefix="EN",
            )

        sec = RecommendedSection(Config(), db=None)
        sec.resize(260, 320)
        sec.show()
        sec._on_rec_data_ready(([rec(1), rec(2), rec(3)], {}))
        QApplication.processEvents()

        assert sec.remove_row("r2") is True
        QApplication.processEvents()

        titles = _titles(sec)
        assert "Rec 2" not in titles
        assert "Rec 1" in titles and "Rec 3" in titles
        sec.hide()
