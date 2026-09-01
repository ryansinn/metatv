"""The caret must report the row's real state, and a collapse must survive a refresh.

Owner, 2026-09-01, on the EPG watchlist: *"the keyword matches with more than one
concurrent source show that they're NOT expanded, but they are expanded, look at
Stargate SG-1"* — a row showing three CTV SCIFI airings under a closed caret.
And then: *"they don't stay collapsed."*

Two defects in ``_apply_expansion``, one cause each:

1. It called ``_sync_carets()`` **before** the loop that changes expansion, so every
   caret it drew described the state the loop was about to replace. One refresh stale,
   for ever.

2. It re-applied its automatic budget decision on every refresh — and the tree is
   rebuilt on every refresh — so a group the user had just collapsed was re-opened by
   the next repaint. Same rule as the sidebar's ``_auto_folded``: automatic behaviour
   may only undo what automatic behaviour did.

The assertions are on the **tooltip**, not on ``_expanded``: it is what the user
actually reads off the control, and it flips with the caret pixmap in the same method.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


_OPEN_TIP = "Hide the other sources"
_SHUT_TIP = "Several sources — click to show them"


def _section_with_rows(n_groups: int, children_per_group: int, config=None):
    """A section whose tree carries real ``_AlertRow`` widgets, as the app builds it."""
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
    from metatv.gui.sidebar.alerts import WatchAlertsSection
    from metatv.gui.sidebar.alerts_common import _ROLE_GROUP_KEY
    from metatv.gui.sidebar.alerts_rows import _AlertRow
    from types import SimpleNamespace

    section = WatchAlertsSection.__new__(WatchAlertsSection)
    section._user_expansion = {}
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setColumnCount(1)
    cfg = config or SimpleNamespace()
    rows, groups = [], []
    for g in range(n_groups):
        title = f"Group {g}"
        parent = QTreeWidgetItem()
        tree.addTopLevelItem(parent)
        parent.setData(0, _ROLE_GROUP_KEY, title)
        for c in range(children_per_group):
            parent.addChild(QTreeWidgetItem([f"Ch {g}.{c}"]))
        # expanded=False is what the app passes: the row is built before
        # expansion is decided, so the caret at construction is a guess.
        row = _AlertRow(title, "", cfg, expandable=True, expanded=False)
        tree.setItemWidget(parent, 0, row)
        rows.append(row)
        groups.append(parent)
    section.alerts_tree = tree
    return section, tree, groups, rows


def _tip(row) -> str:
    return row._marker.toolTip()


# ---------------------------------------------------------------------------
# 1. The Stargate SG-1 row: children shown, caret closed
# ---------------------------------------------------------------------------


def test_the_caret_reports_the_state_the_row_is_actually_in(qapp):
    """One small group → the budget expands it → the caret must say so.

    Pre-fix the caret was synced BEFORE the expansion loop, so it still read
    "click to show them" over three visible airings.
    """
    section, _tree, groups, rows = _section_with_rows(1, 3)
    section._apply_expansion()

    assert groups[0].isExpanded(), "precondition: the budget should expand one small group"
    assert _tip(rows[0]) == _OPEN_TIP, (
        "the row is expanded and its children are on screen, but the caret still "
        "offers to show them — this is the Stargate SG-1 row")


def test_the_caret_reports_collapse_too(qapp):
    """The other direction: an over-budget set stays shut and says so."""
    section, _tree, groups, rows = _section_with_rows(8, 4)
    section._apply_expansion()

    assert not any(g.isExpanded() for g in groups), "precondition: over budget"
    assert all(_tip(r) == _SHUT_TIP for r in rows)


# ---------------------------------------------------------------------------
# 2. "They don't stay collapsed"
# ---------------------------------------------------------------------------


def test_a_group_the_user_collapsed_stays_collapsed_through_a_refresh(qapp):
    """The budget wanted it open; the user said no. The user wins.

    Pre-fix ``_apply_expansion`` set every group to the budget's answer on every
    refresh, and the EPG section refreshes on a repaint tick — so a collapse
    survived until the next repaint and no longer.
    """
    section, _tree, groups, rows = _section_with_rows(1, 3)
    section._user_expansion["Group 0"] = False      # the user shut it

    section._apply_expansion()                       # a later refresh

    assert not groups[0].isExpanded(), (
        "the automatic pass re-opened a group the user had collapsed")
    assert _tip(rows[0]) == _SHUT_TIP, "and the caret must agree with it"


def test_a_group_the_user_opened_stays_open_when_the_budget_says_collapse(qapp):
    """Symmetry: an explicit open survives an over-budget list too."""
    section, _tree, groups, rows = _section_with_rows(8, 4)
    section._user_expansion["Group 3"] = True

    section._apply_expansion()

    assert groups[3].isExpanded(), "the automatic pass shut a group the user had opened"
    assert _tip(rows[3]) == _OPEN_TIP
    assert not groups[0].isExpanded(), "untouched groups must still follow the budget"


def test_an_untouched_group_still_follows_the_budget(qapp):
    """Non-degeneracy: remembering choices must not disable the budget.

    If every group were treated as user-chosen, a long watchlist would expand
    and the tree would balloon — the thing _apply_expansion exists to prevent.
    """
    section, _tree, groups, _rows = _section_with_rows(8, 4)
    section._user_expansion["Group 1"] = True        # exactly one choice

    section._apply_expansion()

    assert groups[1].isExpanded()
    assert not any(g.isExpanded() for i, g in enumerate(groups) if i != 1), (
        "an unrelated group was expanded — the budget stopped applying")


def test_clicking_records_the_choice(qapp):
    """The memory is only ever written by a click; nothing else may seed it."""
    section, _tree, groups, rows = _section_with_rows(1, 3)
    section._apply_expansion()
    assert section._user_expansion == {}, (
        "the automatic pass recorded a choice the user never made — that would "
        "freeze the budget out on the very first refresh")
