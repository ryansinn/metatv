"""The sidebar's allocation fix — R13's three mechanisms, plus news headers.

**The sidebar keeps everything; the bug is allocation.** Q7 proposed moving
heavy content to the main pane and was withdrawn: *"Honestly: only vertical
space. That is not worth what it costs."* The measured saved layout was the
real problem —

    Watch Alerts 173px   four sub-groups, each with its own scrollbar, ~35px apiece
    Recommended  113px   ~5 rows          "OK"
    Watch Queue  403px                    "looks great"
    Favorites     26px   collapsed to its header
    History       91px   ~2 rows          "doesn't have enough space"

Queue got 4.4× History. Three mechanisms, no metaphor change:

1. **No nested scrollbars** — a section shows the rows that fit and ends with
   ``+N more →``. *This alone recovers most of the jam.*
2. **Content-aware minimums** — already shipped (#329, ``MIN_ROWS``).
3. **News boost** — a section holding something new gets a *bounded* extra
   allowance.

Plus Q21: a collapsed section carries **news rather than a bare count**,
because *a count is inventory and ``+9 eps`` is news*.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget, QListWidgetItem

from metatv.gui import theme as _theme
from metatv.gui.sidebar.base import _MORE_ROW, CollapsibleSection


class _Section(CollapsibleSection):
    """A minimal real section — enough to exercise the base mechanisms."""

    MIN_ROWS = 3

    def __init__(self, config, news_text=""):
        self._news_text = news_text
        self._count = None
        super().__init__("Test", "T", config)

    def get_section_id(self):
        return "test"

    def create_content(self):
        self.list = QListWidget()
        self.content_layout.addWidget(self.list)

    def news(self):
        return self._news_text

    def item_count(self):
        return self._count


@pytest.fixture
def config():
    from types import SimpleNamespace
    return SimpleNamespace(expand_icon="v", collapse_icon=">",
                           sidebar_sections=[], sidebar_visible_sections=[])


def _fill(section, n, row_h=20):
    from PyQt6.QtCore import QSize

    for i in range(n):
        item = QListWidgetItem(f"row {i}")
        item.setSizeHint(QSize(100, row_h))
        section.list.addItem(item)


def _lay_out(qapp, section, height):
    """Give the list a REAL viewport height.

    ``setFixedHeight`` alone is not enough: an unshown widget never lays out,
    so ``viewport().height()`` stays at its default and every budget comes out
    identical — which looks exactly like the tail behaving as a cap.
    """
    section.list.setFixedHeight(height)
    section.resize(240, height + section.HEADER_H)
    section.show()
    qapp.processEvents()
    assert section.list.viewport().height() > 0


# ---------------------------------------------------------------------------
# 1. No nested scrollbars — the rows that fit, then "+N more".
# ---------------------------------------------------------------------------

def test_the_section_list_never_grows_its_own_scrollbar(qapp, config):
    section = _Section(config)
    _fill(section, 40)
    _lay_out(qapp, section, 100)
    section.apply_row_budget(section.list)
    assert (section.list.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


def test_surplus_rows_are_hidden_behind_a_more_tail(qapp, config):
    """A scrollbar inside a scrollbar is replaced by one honest row."""
    section = _Section(config)
    _fill(section, 40, row_h=20)
    _lay_out(qapp, section, 100)
    hidden = section.apply_row_budget(section.list)

    assert hidden > 0
    visible = [i for i in range(section.list.count())
               if not section.list.item(i).isHidden()]
    assert len(visible) < 40, "everything was left visible — the budget did nothing"

    tail = section.list.item(section.list.count() - 1)
    assert tail.data(Qt.ItemDataRole.UserRole) == _MORE_ROW
    assert str(hidden) in tail.text()


def test_everything_fitting_means_no_tail(qapp, config):
    """``+N more`` appears only when there IS more."""
    section = _Section(config)
    _fill(section, 2, row_h=20)
    _lay_out(qapp, section, 400)
    assert section.apply_row_budget(section.list) == 0
    assert section.list.item(section.list.count() - 1).data(
        Qt.ItemDataRole.UserRole) != _MORE_ROW


def test_more_is_a_consequence_of_height_not_a_cap(qapp, config):
    """*"``+N more`` is not a cap. Drag a section taller and it renders more
    rows. The minimum is a floor, never a ceiling."* — the callout, asserted."""
    def hidden_at(height):
        section = _Section(config)
        _fill(section, 40, row_h=20)
        _lay_out(qapp, section, height)
        return section.apply_row_budget(section.list)

    tight, roomy = hidden_at(100), hidden_at(300)
    assert roomy < tight, (
        f"a taller section hid {roomy} rows against {tight} in a shorter one — "
        f"the tail is behaving as a cap, not as an allocation consequence"
    )


def test_clicking_the_tail_opens_the_full_view(qapp, config):
    section = _Section(config)
    _fill(section, 40)
    _lay_out(qapp, section, 100)
    section.apply_row_budget(section.list)

    seen = []
    section.exploreClicked.connect(lambda: seen.append(True))
    section._on_more_row_clicked(section.list.item(section.list.count() - 1))
    assert seen == [True]


def test_clicking_a_content_row_does_not_open_the_full_view(qapp, config):
    """The tail is told apart by a sentinel, not by matching its text — the
    label carries a live count."""
    section = _Section(config)
    _fill(section, 40)
    _lay_out(qapp, section, 100)
    section.apply_row_budget(section.list)

    seen = []
    section.exploreClicked.connect(lambda: seen.append(True))
    section._on_more_row_clicked(section.list.item(0))
    assert seen == []


def test_an_unlaid_out_list_keeps_every_row(qapp, config):
    """A zero-height viewport is "not laid out yet", not "nothing fits" —
    guessing a budget from it would hide the whole list on first paint."""
    section = _Section(config)
    _fill(section, 10)
    assert section.apply_row_budget(section.list) == 0
    assert all(not section.list.item(i).isHidden() for i in range(10))


# ---------------------------------------------------------------------------
# 2. News boost — bounded, and it relaxes.
# ---------------------------------------------------------------------------

def test_a_section_with_news_earns_more_room(qapp, config):
    quiet = _Section(config, news_text="")
    loud = _Section(config, news_text="3 new")
    assert loud.min_expanded_height() > quiet.min_expanded_height()


def test_the_boost_is_bounded(qapp, config):
    """"A section widens when it has something to say" must not become "the
    section with news takes the sidebar"."""
    quiet = _Section(config, news_text="")
    loud = _Section(config, news_text="3 new")
    extra = loud.min_expanded_height() - quiet.min_expanded_height()
    assert extra == _Section.NEWS_BOOST_ROWS * _Section.ROW_H
    assert extra <= 3 * _Section.ROW_H


def test_the_boost_relaxes_when_the_news_goes_quiet(qapp, config):
    """The floor follows the news at the REFRESH seam, not on every read.

    ``min_expanded_height`` is called with the class as ``self`` in places
    ("this type's floor, no instance needed"), so it reads plain state rather
    than asking a live question. ``refresh_header_status`` is what re-reads
    the news — which is also the one call a section makes when its contents
    change.
    """
    section = _Section(config, news_text="3 new")
    boosted = section.min_expanded_height()
    section._news_text = ""
    section.refresh_header_status()
    assert section.min_expanded_height() < boosted


# ---------------------------------------------------------------------------
# 3. Headers carry news, not counts.
# ---------------------------------------------------------------------------

def test_news_replaces_the_count_rather_than_joining_it(qapp, config):
    """They are alternatives, not a pair — a header reading ``1 new · 13`` is
    inventory again with a decoration on it."""
    section = _Section(config, news_text="1 new")
    section._count = 13
    assert section.header_status() == "1 new"


def test_a_quiet_section_shows_its_count(qapp, config):
    section = _Section(config)
    section._count = 13
    assert section.header_status() == "13"


def test_a_section_with_neither_shows_nothing(qapp, config):
    assert _Section(config).header_status() == ""


def test_the_header_slot_renders_the_news(qapp, config):
    section = _Section(config, news_text="2 expiring")
    assert section._status_label.text() == "2 expiring"
    assert section._status_label.isVisible() or not section.isVisible()


def test_news_is_painted_in_the_accent(qapp, config):
    """It is the one thing in a collapsed sidebar worth looking at."""
    loud = _Section(config, news_text="1 new")
    quiet = _Section(config)
    quiet._count = 9
    assert _theme.COLOR_ACCENT in loud._status_label.styleSheet()
    assert _theme.COLOR_ACCENT not in quiet._status_label.styleSheet()


def test_refreshing_the_status_updates_text_and_floor(qapp, config):
    """One call keeps the header and the allocation in step — gaining news
    changes both."""
    section = _Section(config)
    before = section.min_expanded_height()
    section._news_text = "5 new"
    section.refresh_header_status()
    assert section._status_label.text() == "5 new"
    assert section.minimumHeight() > before
