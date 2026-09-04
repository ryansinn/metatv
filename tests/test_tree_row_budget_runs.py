"""``apply_tree_row_budget`` must actually run — the guard for a runtime error.

A crash shipped here once: gating the sizing on the "Show N more" setting
inserted an early return that read ``groups`` before the line defining it.
``UnboundLocalError`` — accepted by ``ast.parse``, accepted by an import check,
and raised only once a tree genuinely had groups in it. It took the app down
with SIGABRT.

That setting is gone (2026-09-02) and with it the second branch, but the reason
this file exists is not: a runtime-only error is caught by CALLING the thing,
never by reading it. Sibling of ``test_epg_agenda_paint.py``.
"""


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from metatv.core.config import Config
from metatv.gui.sidebar.alerts import WatchAlertsSection
from tests.conftest import destroy_widget


def _section(tmp_path, *, groups=3, children=6):
    section = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    tree = section.alerts_tree
    for g in range(groups):
        group = QTreeWidgetItem([f"group {g}"])
        tree.addTopLevelItem(group)
        for c in range(children):
            group.addChild(QTreeWidgetItem([f"child {c}"]))
        group.setExpanded(True)
    return section, tree


def test_the_tree_shows_everything_and_lets_the_section_scroll(qapp, tmp_path):
    """Watch Alerts splits its panel three ways, so its views cannot scroll.

    A scrollbar inside one of them would be ~35px tall — the R13 jam. The
    SECTION owns the one scroll area, so every child stays visible and the
    surplus becomes the section's scroll range.
    """
    section, tree = _section(tmp_path)

    section.apply_tree_row_budget(tree)      # must not raise

    # The tree never scrolls itself — one scrolling surface, at the section.
    assert tree.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    for i in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(i)
        for j in range(group.childCount()):
            assert not group.child(j).isHidden(), "a child was hidden with nothing to reveal it"
    # ...and it is tall enough to draw them, or the rows overlap.
    assert tree.height() > 0
    destroy_widget(section)


def test_a_group_the_user_folded_stays_folded(qapp, tmp_path):
    """Sizing must never re-open what a person closed.

    ``section_cap``'s docstring records four separate defects of exactly this
    shape — the app closing, or opening, something the user had set.
    """
    section, tree = _section(tmp_path)
    tree.topLevelItem(1).setHidden(True)

    section.apply_tree_row_budget(tree)

    assert tree.topLevelItem(1).isHidden(), "sizing re-opened a folded group"
    destroy_widget(section)


def test_an_empty_tree_gets_no_height(qapp, tmp_path):
    """No groups at all — and an unsized empty view reports a DEFAULT viewport.

    That fabricated measurement is what made an empty Recordings section 108px
    tall; the tree has the same trap and must answer zero.
    """
    section, _tree = _section(tmp_path, groups=0)
    empty = QTreeWidget()

    section.apply_tree_row_budget(empty)

    assert empty.height() == 0
    destroy_widget(section, empty)


def test_reapply_walks_every_budgeted_surface(qapp, tmp_path):
    """The crash arrived via reapply_row_budget, not via a direct call."""
    section, _tree = _section(tmp_path)
    section.reapply_row_budget()            # must not raise
    destroy_widget(section)


def test_a_hidden_child_under_a_visible_group_stays_hidden(qapp, tmp_path):
    """HIDE-1: a child row hidden by something else (a filter, a fold) must
    stay hidden through ``apply_tree_row_budget`` — not only a folded
    TOP-LEVEL group, which the loop already skipped before this fix.

    The tree budget used to un-hide every child of every visible group
    unconditionally, a leftover of the removed "Show N more" mode that had
    nothing left to reveal once that mode stopped hiding rows itself. It kept
    running anyway, which is exactly the mechanism that resurrected the Watch
    Queue's find-in-queue filter results on a mere splitter drag — this is
    the tree-shaped sibling of that same bug.
    """
    section, tree = _section(tmp_path)
    group = tree.topLevelItem(0)
    group.child(2).setHidden(True)

    section.apply_tree_row_budget(tree)

    assert group.child(2).isHidden(), (
        "a child hidden by something else was resurrected by the row budget"
    )
    for j in range(group.childCount()):
        if j != 2:
            assert not group.child(j).isHidden(), (
                f"child {j} was hidden but nothing hid it"
            )
    destroy_widget(section)


def test_fixed_height_tracks_only_the_visible_rows(qapp, tmp_path):
    """The tree's fitted height must fall when rows leave the visible set —
    proof that ``fit_to_rows`` (not a stale figure) is what governs the height,
    and that hiding a row is not silently undone before that measurement.

    A relationship, not a pinned pixel count: an improvement to row height or
    spacing must not turn this into a red gate.
    """
    section, tree = _section(tmp_path)
    section.apply_tree_row_budget(tree)
    full_height = tree.height()
    assert full_height > 0

    group = tree.topLevelItem(0)
    for j in range(group.childCount() - 2):
        group.child(j).setHidden(True)

    section.apply_tree_row_budget(tree)

    assert tree.height() < full_height, (
        f"hiding all but two children left the tree at {tree.height()}px, "
        f"same as the full {full_height}px — the budget is not measuring "
        "what is actually visible"
    )
    for j in range(group.childCount() - 2):
        assert group.child(j).isHidden(), (
            f"child {j} was revealed by the very budget pass whose height "
            "this test measured"
        )
    destroy_widget(section)
