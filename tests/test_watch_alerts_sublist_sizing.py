"""Sizing/layout regression tests for WatchAlertsSection's three sub-lists.

Bug: the EPG ``alerts_tree`` (a ``QTreeWidget``) had NO height cap, so with its
default Expanding vertical policy it absorbed ALL of the section's leftover vertical
space and starved the two capped sibling lists below it (Movies & Series capped at
200, Stream Monitoring at 120). Expanding the section only grew the EPG list.

Fix under test:
- ``_fit_alerts_tree_to_content()`` caps the tree to its visible-row content height,
  clamped to ``_ALERTS_TREE_MAX_HEIGHT`` (so a long list scrolls, not balloons).
- ``create_content()`` adds a trailing stretch so surplus space collects at the
  bottom instead of flowing into any one list.

These assert the observable outcome (a bounded ``maximumHeight`` + a trailing
stretch), so they fail if the cap or the stretch is reverted.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# Qt's default (uncapped) maximumHeight — QWIDGETSIZE_MAX. A widget at this value is
# effectively unbounded, i.e. free to balloon.
QWIDGETSIZE_MAX = 16777215


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _stub_section_with_tree(n_rows: int):
    """A WatchAlertsSection stub carrying only a populated real ``alerts_tree``.

    Follows the ``__new__`` harness style in ``test_vod_watch_alerts.py``: we exercise
    the sizing helper in isolation (the full section needs a DB) — the helper reads
    ``self.__dict__.get("alerts_tree")``, so nothing else is required.
    """
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection.__new__(WatchAlertsSection)
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setColumnCount(1)
    for i in range(n_rows):
        tree.addTopLevelItem(QTreeWidgetItem([f"Programme {i}"]))
    section.alerts_tree = tree
    return section, tree


class TestFitAlertsTreeToContent:
    """`_fit_alerts_tree_to_content` caps the tree so it can no longer balloon."""

    def test_uncapped_tree_starts_effectively_unbounded(self, qapp):
        # Precondition (documents the bug): a fresh tree is uncapped and would expand.
        _section, tree = _stub_section_with_tree(3)
        assert tree.maximumHeight() == QWIDGETSIZE_MAX

    def test_fit_caps_below_qwidgetsize_max(self, qapp):
        section, tree = _stub_section_with_tree(3)
        section._fit_alerts_tree_to_content()
        assert tree.maximumHeight() < QWIDGETSIZE_MAX, (
            "fit must cap the tree so it no longer uses the default unbounded height"
        )

    def test_fit_bounds_to_roughly_content_height(self, qapp):
        section, tree = _stub_section_with_tree(3)
        section._fit_alerts_tree_to_content()

        row_h = tree.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 22  # same fallback the helper uses
        cap = tree.maximumHeight()
        # <= rows*row_h + a generous slack for frame/padding — clearly content-sized,
        # not the huge default.
        assert cap <= 3 * row_h + 40, f"cap {cap} exceeds ~3 rows of content"
        # ...and it still leaves room for at least a row (not collapsed to nothing).
        assert cap >= row_h

    def test_long_list_clamps_to_max_and_scrolls(self, qapp):
        from metatv.gui.sidebar.alerts import _ALERTS_TREE_MAX_HEIGHT

        section, tree = _stub_section_with_tree(200)
        section._fit_alerts_tree_to_content()
        assert tree.maximumHeight() == _ALERTS_TREE_MAX_HEIGHT, (
            "a list longer than the cap must clamp to _ALERTS_TREE_MAX_HEIGHT so the "
            "tree scrolls internally instead of growing the section unboundedly"
        )

    def test_few_rows_yield_space_below_the_cap(self, qapp):
        """A short list must NOT claim the whole budget — that space is for siblings."""
        from metatv.gui.sidebar.alerts import _ALERTS_TREE_MAX_HEIGHT

        section, tree = _stub_section_with_tree(2)
        section._fit_alerts_tree_to_content()
        assert tree.maximumHeight() < _ALERTS_TREE_MAX_HEIGHT, (
            "with few rows the tree must stay small so Movies & Series / Stream "
            "Monitoring are not starved of the section's space"
        )

    def test_empty_tree_is_left_untouched(self, qapp):
        section, tree = _stub_section_with_tree(0)
        section._fit_alerts_tree_to_content()
        # Nothing to size — must not crash; cap stays at the default.
        assert tree.maximumHeight() == QWIDGETSIZE_MAX


def _stub_section_with_groups(n_groups: int, children_per_group: int):
    """Stub section whose ``alerts_tree`` holds ``n_groups`` expandable groups."""
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection.__new__(WatchAlertsSection)
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setColumnCount(1)
    groups = []
    for g in range(n_groups):
        parent = QTreeWidgetItem([f"Group {g}"])
        tree.addTopLevelItem(parent)
        for c in range(children_per_group):
            parent.addChild(QTreeWidgetItem([f"Ch {g}.{c}"]))
        groups.append(parent)
    section.alerts_tree = tree
    return section, tree, groups


class TestApplyExpansion:
    """`_apply_expansion` still expands when it fits, and always re-caps the tree.

    Guards the wiring (the fix routes the cap through _apply_expansion) AND the
    budget-based expand decision that replaced the self-referential viewport read.
    """

    def test_small_group_set_expands_and_tree_is_capped(self, qapp):
        # 1 group * 3 children = 4 rows, well under the ~14-row budget → expand-all.
        section, tree, groups = _stub_section_with_groups(1, 3)
        section._apply_expansion()
        assert groups[0].isExpanded(), (
            "a group set that fits the budget must expand so children are revealed"
        )
        assert tree.maximumHeight() < QWIDGETSIZE_MAX, (
            "_apply_expansion must leave the tree capped (not ballooning)"
        )

    def test_overflowing_group_set_collapses_and_scrolls(self, qapp):
        from metatv.gui.sidebar.alerts import _ALERTS_TREE_MAX_HEIGHT

        # 8 groups * 4 children = 8 + 32 = 40 rows, far over the budget → collapse-all,
        # and the collapsed top-level list itself exceeds the cap → clamp (scrolls).
        section, tree, groups = _stub_section_with_groups(8, 4)
        section._apply_expansion()
        assert not any(g.isExpanded() for g in groups), (
            "a group set that would overflow the cap must stay collapsed (list scrolls)"
        )
        assert tree.maximumHeight() <= _ALERTS_TREE_MAX_HEIGHT


class TestContentLayoutTrailingStretch:
    """The section adds a trailing stretch so surplus space collects at the bottom."""

    def _make_full_section(self, tmp_path: Path):
        from metatv.core.config import Config
        from metatv.gui.sidebar.alerts import WatchAlertsSection

        cfg = Config(config_dir=tmp_path / "cfg")
        # No DB session work happens during construction/layout — a stub db suffices.
        return WatchAlertsSection(cfg, MagicMock())

    def test_last_content_item_is_a_stretch(self, qapp, tmp_path):
        section = self._make_full_section(tmp_path)
        layout = section.content_layout
        last = layout.itemAt(layout.count() - 1)
        # A stretch/spacer item has no widget and no child layout — it exists purely to
        # absorb leftover space. Without it, that space would flow into the Expanding
        # alerts_tree and balloon it.
        assert last is not None
        assert last.widget() is None and last.layout() is None, (
            "the last content_layout item must be a trailing stretch (spacer), so "
            "surplus vertical space collects at the bottom rather than in a sub-list"
        )
        assert last.spacerItem() is not None
