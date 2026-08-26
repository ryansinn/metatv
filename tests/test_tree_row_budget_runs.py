"""``apply_tree_row_budget`` must actually run, in both of its branches.

A crash shipped here: gating the budget on the "Show N more" setting inserted an
early return that read ``groups`` before the line defining it. ``UnboundLocalError``
— accepted by ``ast.parse``, accepted by an import check, and raised only once a
tree genuinely had groups in it. It took the app down with SIGABRT.

Sibling of ``test_epg_agenda_paint.py``: the guard for a runtime-only error is to
CALL the thing, with each branch exercised.
"""

import pathlib
import tempfile

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from metatv.core.config import Config
from metatv.gui.sidebar.alerts import WatchAlertsSection


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


def test_it_runs_with_the_setting_off(qapp, tmp_path):
    """The branch that crashed."""
    section, tree = _section(tmp_path)
    assert section.config.sidebar_show_more_row is False

    assert section.apply_tree_row_budget(tree) == 0
    assert tree.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    for i in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(i)
        for j in range(group.childCount()):
            assert not group.child(j).isHidden(), "a child stayed hidden with a scrollbar"


def test_it_runs_with_the_setting_on(qapp, tmp_path):
    section, tree = _section(tmp_path)
    section.config.sidebar_show_more_row = True

    section.apply_tree_row_budget(tree)     # must not raise
    assert tree.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_an_empty_tree_is_handled(qapp, tmp_path):
    """No groups at all — the early-out that runs before either branch."""
    section, _tree = _section(tmp_path, groups=0)
    assert section.apply_tree_row_budget(QTreeWidget()) == 0


def test_switching_the_setting_back_and_forth_never_raises(qapp, tmp_path):
    """The real sequence: a viewer toggles it, and the budget re-runs."""
    section, tree = _section(tmp_path)
    for enabled in (True, False, True, False):
        section.config.sidebar_show_more_row = enabled
        section.apply_tree_row_budget(tree)


def test_reapply_walks_every_budgeted_surface(qapp, tmp_path):
    """The crash arrived via reapply_row_budget, not via a direct call."""
    section, _tree = _section(tmp_path)
    section.reapply_row_budget()            # must not raise
