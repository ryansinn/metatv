"""Find-in-queue: a 600-entry Watch Queue has to be navigable (#291).

Measured on the owner's install before choosing a remedy — 612 entries, 597 of
them never watched, oldest 2026-05-22, and NOTHING older than three months:

    last 7d   74      1-3mo    436
    7-30d    102      >3mo       0

So the roadmap's own suggestion (age the queue out, archive the tail) had no
tail to work with: a three-month cutoff would archive zero rows and a one-month
cutoff would archive 436 of 612. That is not a stale backlog, it is a queue
filled faster than it is drained, every entry added deliberately — hiding 71% of
it would be censorial, and the counts #289 added tell you the size without
making it findable. A filter hides nothing and finds one title in 600.

Asserts PAINTED geometry, not ``isHidden()`` (CLAUDE.md: UI slices assert
rendered appearance): a row can carry the right hidden flag and still occupy
space in the viewport, which is the failure a flag check cannot see.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.core.config import Config
from metatv.core.repositories.queue import QueueEntry
from metatv.gui.chip_row import row_title_label
from metatv.gui.sidebar.queue import WatchQueueSection


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


_BASE = datetime(2026, 5, 1, 12, 0, 0)


def _entry(name, *, days=0, played=None, available=True, year=""):
    return QueueEntry(
        queue_id=abs(hash(name)) % 100000,
        channel_id=f"ch-{name}",
        channel_name=name,
        media_type="movie",
        last_played=played,
        channel=None,
        available=available,
        search_title=name,
        detected_year=year,
        added_at=_BASE + timedelta(days=days),
    )


ENTRIES = [
    _entry("Blade Runner", days=1, year="1982"),
    _entry("Blade Runner 2049", days=2, year="2017"),
    _entry("The Lobster", days=3, year="2015"),
    _entry("Arrival", days=4, played=_BASE),           # Continue Watching
    _entry("Dune", days=5, available=False),           # Unavailable
]


@pytest.fixture()
def section(qapp):
    """A REAL WatchQueueSection rendering into a REAL QListWidget."""
    sec = WatchQueueSection(Config(), db=None)
    sec.resize(260, 320)
    sec.show()
    QApplication.processEvents()
    sec._populate_rows(list(ENTRIES))
    QApplication.processEvents()
    yield sec
    sec.hide()


def _row_title(section, item) -> str:
    """The title a row renders — the chip row's label, or a header's own text."""
    widget = section._list.itemWidget(item)
    if widget is None:
        return item.text()
    label = row_title_label(widget)
    return label.text() if label is not None else ""


def _painted_titles(section) -> list[str]:
    """Titles of the rows that actually occupy space in the list.

    ``visualItemRect`` of a hidden row is empty — this is the rendered truth,
    independent of how the row was hidden.
    """
    return [
        _row_title(section, section._list.item(i))
        for i in range(section._list.count())
        if section._list.visualItemRect(section._list.item(i)).height() > 0
    ]


def _type_filter(section, text: str) -> None:
    section._filter.setText(text)
    QApplication.processEvents()


def test_the_box_exists_and_is_clearable(section):
    """Project standard: filter/search line edits carry a clear button."""
    assert section._filter.isClearButtonEnabled()
    assert section._filter.toolTip()
    assert section._filter.placeholderText()


class TestTheHeaderToggle:
    """The box is revealed by a 🔍 in the section's title bar, not always present.

    Owner: "shouldn't the search field be exposed or hidden with a search button
    so that it's not just wasted real estate if the user never needs it" — right
    call. The sidebar's scarcest resource is vertical space, and a permanent
    line edit charges every session for a control most of them never touch.
    """

    def test_it_is_put_away_by_default(self, section):
        assert not section._filter.isVisible()
        assert section._filter_btn.toolTip()
        assert not section._filter_btn.isChecked()

    def test_putting_it_away_gives_the_space_to_the_list(self, section):
        """The point of the toggle, measured in pixels of list.

        A hidden widget still in the layout would keep its row and prove
        nothing — so this asserts the LIST actually got taller.
        """
        section._set_filter_visible(True, save=False)
        QApplication.processEvents()
        with_box = section._list.height()

        section._set_filter_visible(False, save=False)
        QApplication.processEvents()
        without_box = section._list.height()

        assert without_box > with_box, (
            f"hiding the filter freed no space: list is {without_box}px either "
            f"way, so the box is still occupying its row"
        )

    def test_revealing_it_focuses_it_so_you_can_just_type(self, section):
        section._filter_btn.click()
        QApplication.processEvents()

        assert section._filter.isVisible()
        assert section._filter_btn.isChecked()
        assert section._filter.hasFocus(), "revealed the box but you have to click it"

    def test_hiding_it_never_leaves_an_invisible_filter(self, section):
        """The trap this control could create, closed.

        A filter still applied behind a hidden box means the queue shows 12 of
        612 rows with nothing on screen explaining why — which reads as the
        queue having lost things, the exact misreading #289 fixed.
        """
        section._set_filter_visible(True, save=False)
        _type_filter(section, "blade")
        assert len(_painted_titles(section)) < len(ENTRIES)

        section._filter_btn.click()          # put it away
        QApplication.processEvents()

        assert not section._filter.isVisible()
        assert section._filter.text() == ""
        painted = _painted_titles(section)
        assert any("Lobster" in p for p in painted), (
            f"rows are still filtered out with no filter box on screen: {painted}"
        )

    def test_escape_puts_it_away_too(self, section):
        section._set_filter_visible(True, save=False)
        _type_filter(section, "blade")

        section._hide_filter_box()
        QApplication.processEvents()

        assert not section._filter.isVisible()
        assert any("Lobster" in p for p in _painted_titles(section))

    def test_the_choice_is_remembered(self, section):
        """UI-state rule: sections save on change and restore on startup."""
        section._filter_btn.click()
        assert section.config.queue_filter_visible is True

        section._filter_btn.click()
        assert section.config.queue_filter_visible is False

    def test_a_remembered_open_box_comes_back_empty(self, qapp):
        """Restoring the BOX is right; restoring a filter is not.

        A queue that opens showing 12 of 612 rows because of text typed days ago
        is indistinguishable from a broken queue.
        """
        config = Config()
        config.queue_filter_visible = True
        sec = WatchQueueSection(config, db=None)
        sec.resize(260, 320)
        sec.show()
        QApplication.processEvents()

        assert sec._filter.isVisible()
        assert sec._filter.text() == ""
        sec.hide()


def test_filtering_paints_only_the_matches(section):
    """The point of the feature, measured on what is on screen."""
    _type_filter(section, "blade")

    painted = _painted_titles(section)
    assert any("Blade Runner" in p for p in painted)
    assert not any("Lobster" in p for p in painted), (
        f"a non-matching row is still taking up space: {painted}"
    )


def test_a_hidden_row_occupies_no_space(section):
    """Geometry, not the flag: the list must actually close up.

    A row left painted at zero opacity or simply flagged hidden without a
    layout pass would pass ``isHidden()`` and still push the matches off-screen.
    """
    _type_filter(section, "lobster")

    lobster = _item_for(section, "The Lobster")
    arrival = _item_for(section, "Arrival")
    assert section._list.visualItemRect(lobster).height() > 0
    assert section._list.visualItemRect(arrival).height() == 0
    assert section._list.visualItemRect(lobster).top() < 40, (
        "the only match is not near the top — hidden rows are still reserving "
        "their space"
    )


def test_an_empty_group_takes_its_header_with_it(section):
    """A "Continue Watching" header over nothing is a lie about the list."""
    _type_filter(section, "blade")

    painted = _painted_titles(section)
    assert not any(p.startswith("Continue Watching") for p in painted)
    assert not any(p.startswith("Unavailable") for p in painted)
    assert any(p.startswith("Never Watched") for p in painted)


def test_headers_report_what_they_are_showing(section):
    """A header still claiming (597) above 12 rows misstates the list."""
    _type_filter(section, "blade")

    header = next(p for p in _painted_titles(section) if p.startswith("Never Watched"))
    assert header == "Never Watched (2 of 3)", header


def test_clearing_restores_every_row_and_the_original_headers(section):
    """The filter is a view, never a deletion — nothing is lost by using it."""
    before = _painted_titles(section)
    _type_filter(section, "blade")
    _type_filter(section, "")

    assert _painted_titles(section) == before
    assert "Never Watched (3)" in before, before


def test_no_matches_says_so_rather_than_going_blank(section):
    """An all-hidden list reads as breakage, not as a filter with no hits."""
    _type_filter(section, "zzzznope")

    painted = _painted_titles(section)
    assert len(painted) == 1, painted
    assert "zzzznope" in painted[0]
    assert section._list.visualItemRect(section._no_match_item).height() > 0


def test_the_filter_survives_a_refresh(section):
    """A refresh is usually the side effect of acting on ONE row.

    Dropping the filter there would dump all 600 entries back on the user
    mid-triage — the same class of interruption as the scroll reset.
    """
    _type_filter(section, "blade")
    section._populate_rows(list(ENTRIES))       # e.g. after marking one watched
    QApplication.processEvents()

    painted = _painted_titles(section)
    assert not any("Lobster" in p for p in painted), (
        "the filter was silently dropped by the refresh"
    )


def test_year_and_provider_name_are_both_searchable(section):
    """Two names can differ (cleaned title vs the provider's), plus the year."""
    _type_filter(section, "2049")
    assert [p for p in _painted_titles(section) if "Blade Runner 2049" in p]

    _type_filter(section, "1982")
    painted = _painted_titles(section)
    assert any(p == "Blade Runner" for p in painted)
    assert not any("2049" in p for p in painted)


def _item_for(section, title: str):
    for i in range(section._list.count()):
        item = section._list.item(i)
        if _row_title(section, item) == title:
            return item
    raise AssertionError(f"no row rendered for {title!r}")
