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
from metatv.gui.sidebar.base import CollapsibleSection


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
    """A config with the row budget switched ON.

    Budgeting is opt-in now: by default a sidebar section shows every row and
    scrolls, like any other list. The "Show N more" mode this fixture used to
    switch on was removed 2026-09-02 — see
    tests/test_sidebar_scrolls_by_default.py for why it is not coming back.
    """
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














# ---------------------------------------------------------------------------
# 2. News boost — bounded, and it relaxes.
# ---------------------------------------------------------------------------

def test_a_section_with_news_earns_more_room(qapp, config):
    quiet = _Section(config, news_text="")
    loud = _Section(config, news_text="3 new")
    assert loud.preferred_expanded_height() > quiet.preferred_expanded_height()


def test_the_boost_is_bounded(qapp, config):
    """"A section widens when it has something to say" must not become "the
    section with news takes the sidebar"."""
    quiet = _Section(config, news_text="")
    loud = _Section(config, news_text="3 new")
    extra = loud.preferred_expanded_height() - quiet.preferred_expanded_height()
    # CONTENT_ROW_H, not ROW_H: the boost buys ROWS OF CONTENT, and the two
    # constants parted company when the V3 row grew a second line (ROW_H is now
    # the simple "+N more" tail row).
    assert extra == _Section.NEWS_BOOST_ROWS * _Section.CONTENT_ROW_H
    assert extra <= 3 * _Section.CONTENT_ROW_H


def test_the_boost_relaxes_when_the_news_goes_quiet(qapp, config):
    """The preferred height follows the news at the REFRESH seam, not on every
    read.

    ``preferred_expanded_height`` is called with the class as ``self`` in places
    ("this type's floor, no instance needed"), so it reads plain state rather
    than asking a live question. ``refresh_header_status`` is what re-reads
    the news — which is also the one call a section makes when its contents
    change.
    """
    section = _Section(config, news_text="3 new")
    boosted = section.preferred_expanded_height()
    section._news_text = ""
    section.refresh_header_status()
    assert section.preferred_expanded_height() < boosted


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


def test_news_is_painted_louder_than_a_plain_count(qapp, config):
    """It is the one thing in a collapsed sidebar worth looking at.

    This asserted ``COLOR_ACCENT`` — and that token was the bug. It is the
    accent as a FILL; as text it is a midtone, 2.61:1 in Graphite against plain
    MUTED's 3.76:1, so a section WITH news read QUIETER than one without. The
    property was always "louder", and pinning the token instead is what let the
    inversion ship.
    """
    def _contrast(a, b):
        def lin(c):
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        def lum(h):
            h = h.lstrip("#")
            r, g, bl = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(bl)

        hi, lo = max(lum(a), lum(b)), min(lum(a), lum(b))
        return (hi + 0.05) / (lo + 0.05)

    loud = _Section(config, news_text="1 new")
    quiet = _Section(config)
    quiet._count = 9

    loud_sheet = loud._status_label.styleSheet()
    quiet_sheet = quiet._status_label.styleSheet()

    # News is a FILLED pill now, so "louder" is measured, not pinned to a
    # token — which is the mistake this test's own history records.
    assert "background: " in loud_sheet and _theme.COLOR_OK in loud_sheet, loud_sheet
    assert "background: transparent" in quiet_sheet, quiet_sheet

    ground = _theme.COLOR_BG_DEEP
    assert _contrast(_theme.COLOR_OK, ground) > _contrast(_theme.COLOR_MUTED, ground), (
        "a section WITH news must read louder than one without"
    )


def test_refreshing_the_status_updates_text_and_floor(qapp, config):
    """One call keeps the header and the allocation in step — gaining news
    changes both."""
    section = _Section(config)
    before = section.preferred_expanded_height()
    floor_before = section.minimumHeight()
    section._news_text = "5 new"
    section.refresh_header_status()
    assert section._status_label.text() == "5 new"
    assert section.preferred_expanded_height() > before
    # ...and the HARD floor does not move with the news. It is the header, so a
    # section with something to say still drags down to nothing if you want it
    # to; what news buys is a bigger share when the space is being shared out.
    assert section.minimumHeight() == floor_before

# ---------------------------------------------------------------------------
# 4. The mechanism is REACHABLE from the paths the app actually takes.
#
# The first version of this feature shipped with every test above passing and
# nothing visible in the app, because `apply_row_budget` had exactly one class
# of caller: these tests. A mechanism that is only ever invoked by its own
# tests is not a feature. These assert the wiring, not the arithmetic.
# ---------------------------------------------------------------------------

def test_populating_a_section_fits_its_rows(qapp, config):
    """The shared post-load hook must call the budget.

    Drives ``_on_data_ready`` — the real completion path every
    BackgroundRefreshMixin section takes — rather than calling the budget by
    hand.
    """
    from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin

    calls = []

    class _Wired(_Section):
        def budgeted_list(self):
            return self.list

        def reapply_row_budget(self):
            calls.append(True)
            super().reapply_row_budget()

        def _refresh_list(self):
            return self.list

        def _populate_rows(self, rows):
            _fill(self, rows)

    section = _Wired(config)
    section._capture_scroll(section.list)
    BackgroundRefreshMixin._on_data_ready(section, 30)
    qapp.processEvents()
    assert calls, (
        "populating a section never fit its rows — apply_row_budget is not "
        "reachable from the load path, only from tests"
    )


def test_resizing_a_section_refits_its_rows(qapp, config):
    """Dragging the splitter is what makes ``+N more`` an allocation
    consequence instead of a cap. Without a resize hook the budget is computed
    once, at load, and a taller section keeps showing its old row count."""
    calls = []

    class _Wired(_Section):
        def budgeted_list(self):
            return self.list

        def reapply_row_budget(self):
            calls.append(True)

    section = _Wired(config)
    # Shown first: Qt delivers a resize event to a hidden widget only once it
    # is polished, so a resize on an unshown section produces nothing and the
    # test would fail for a reason the app never experiences.
    section.show()
    qapp.processEvents()
    calls.clear()
    section.resize(240, 320)
    qapp.processEvents()
    assert calls, "resizing a section never refit its rows"




@pytest.mark.parametrize("module,cls", [
    ("history", "HistorySection"),
    ("favorites", "FavoritesSection"),
    ("recommended", "RecommendedSection"),
    ("queue", "WatchQueueSection"),
])
def test_every_flat_list_section_declares_its_list(module, cls):
    """A section that does not name its list silently opts out of the whole
    mechanism — which is exactly how this shipped inert the first time."""
    import importlib

    section_cls = getattr(importlib.import_module(f"metatv.gui.sidebar.{module}"), cls)
    assert "budgeted_list" in vars(section_cls), (
        f"{cls} does not declare budgeted_list, so its rows are never fitted"
    )


# ---------------------------------------------------------------------------
# 5. Sub-grouped sections budget WITHIN each group.
#
# Watch Alerts is the section R13 names directly — 173px subdivided four ways,
# each sub-group scrolling in ~35px. The fix it asks for is "three readable
# groups", so every group stays on screen and each truncates its own children.
# A first attempt budgeted the TOP-LEVEL rows instead and hid four of five
# groups outright, which is the opposite of the thing being fixed.
# ---------------------------------------------------------------------------

from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem  # noqa: E402


class _TreeSection(CollapsibleSection):
    def __init__(self, config):
        super().__init__("Tree", "T", config)

    def get_section_id(self):
        return "tree"

    def create_content(self):
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.content_layout.addWidget(self.tree)

    def budgeted_tree(self):
        return self.tree


def _tree_section(qapp, config, groups, children, height=200):
    section = _TreeSection(config)
    for g in range(groups):
        group = QTreeWidgetItem([f"group {g}"])
        for c in range(children):
            group.addChild(QTreeWidgetItem([f"child {c}"]))
        section.tree.addTopLevelItem(group)
        group.setExpanded(True)
    section.tree.setFixedHeight(height - section.HEADER_H)
    section.resize(240, height)
    section.show()
    qapp.processEvents()
    return section


def _visible_children(group):
    return [group.child(i) for i in range(group.childCount())
            if not group.child(i).isHidden()]


def test_every_group_header_stays_on_screen(qapp, config):
    """"Three readable groups" — a budget that hides whole groups is the
    problem, not the fix."""
    section = _tree_section(qapp, config, groups=4, children=10)
    section.apply_tree_row_budget(section.tree)
    hidden = [i for i in range(section.tree.topLevelItemCount())
              if section.tree.topLevelItem(i).isHidden()]
    assert hidden == [], f"groups {hidden} were hidden — budget the children instead"




def test_the_tree_never_grows_its_own_scrollbar(qapp, config):
    section = _tree_section(qapp, config, groups=4, children=10)
    section.apply_tree_row_budget(section.tree)
    assert (section.tree.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


def test_a_group_that_fits_keeps_every_child(qapp, config):
    section = _tree_section(qapp, config, groups=1, children=2, height=400)
    section.apply_tree_row_budget(section.tree)
    group = section.tree.topLevelItem(0)
    assert len(_visible_children(group)) == 2
    assert group.childCount() == 2, "a marker row was added to the group"




def test_the_alerts_section_declares_its_tree():
    """The section R13 names is the one a list-shaped budget could not reach.

    Asserted as "the section RESOLVES to an override", not as
    ``"budgeted_tree" in vars(...)``: ``vars`` reads one class's own dict, so
    that version broke the moment the method moved to a mixin — while the
    behaviour it was written to protect had not changed at all. What matters is
    that the section does not fall through to the base's ``None``.
    """
    from metatv.gui.sidebar.alerts import WatchAlertsSection
    from metatv.gui.sidebar.row_budget import RowBudgetMixin

    assert WatchAlertsSection.budgeted_tree is not RowBudgetMixin.budgeted_tree, (
        "the section inherits the base's tree-less budget"
    )
    assert callable(WatchAlertsSection.budgeted_tree)


# ---------------------------------------------------------------------------
# 6. The tail must not poison the payload every section reads.
#
# It did. The marker lived in UserRole, which is where each section stores its
# OWN payload — a channel id, or in Watch Queue a dict. Selecting the tail row
# handed _on_selection_changed a string where it expected a dict and took the
# app down:
#
#     AttributeError: 'str' object has no attribute 'get'
#
# Twelve handlers read that role. These drive the REAL ones with a tail
# present, which is the check that was missing — every test above exercised the
# budget and none of them exercised what the budget leaves behind.
# ---------------------------------------------------------------------------











