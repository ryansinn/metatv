"""Sizing/layout regression tests for WatchAlertsSection's three sub-lists.

Rework of PR #340.

ORIGINAL bug: the EPG ``alerts_tree`` (a ``QTreeWidget``) kept its default Expanding
vertical policy while its two sibling ``QListWidget``s were hard-capped (Movies & Series
at 200px, Stream Monitoring at 120px). So ALL of the section's surplus vertical space
funnelled into the one uncapped list — the EPG tree ballooned and starved the siblings.

PR #340's first attempt capped the tree too AND added a trailing ``content_layout``
stretch. That traded the balloon for a large BLANK GAP at the bottom of the section: all
surplus now pooled in the trailing spacer instead of a sub-list.

Fix under test (the rework):
- The three sub-lists carry EQUAL, non-zero layout stretch and an Expanding vertical
  size policy, so the section's surplus height is DISTRIBUTED among the visible lists.
  No single list balloons, none is starved, and there is no dead trailing gap.
- The hard ``maximumHeight`` caps and the trailing stretch are removed. The EPG tree is
  bounded by its stretch share of the splitter pane (not a hard cap, which would strand
  surplus as a gap); a long watchlist stays collapsed via ``_apply_expansion`` and
  scrolls compactly.

Each assertion targets an observable leg of the fix, so reverting any leg (re-adding a
hard cap, dropping the shared stretch, or re-adding the trailing spacer) fails a test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# Qt's default (uncapped) maximumHeight — QWIDGETSIZE_MAX. A widget at this value has no
# hard height cap, i.e. it is free to shrink/grow to its layout (stretch) share.
QWIDGETSIZE_MAX = 16777215


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _index_of(layout, widget) -> int:
    """Return the ``content_layout`` index carrying ``widget`` (or -1)."""
    for i in range(layout.count()):
        if layout.itemAt(i).widget() is widget:
            return i
    return -1


@pytest.fixture(scope="module")
def full_section(qapp, tmp_path_factory):
    """A fully-constructed WatchAlertsSection (real ``create_content`` layout).

    ``create_content`` does no DB work, so a stub db suffices; this exercises the real
    size policies / stretch factors the fix sets. Built once (module scope) since every
    test here only READS the layout — this keeps a single widget rather than one per
    test. Torn down at module end so it does not leak.
    """
    from metatv.core.config import Config
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    cfg = Config(config_dir=tmp_path_factory.mktemp("cfg"))
    section = WatchAlertsSection(cfg, MagicMock())
    yield section
    section.setParent(None)
    section.deleteLater()
    qapp.processEvents()


class TestSubListStretchSharing:
    """The three sub-lists share the section's surplus via equal, Expanding stretch."""

    def test_no_trailing_dead_stretch(self, full_section):
        """The last content item is a real widget, never a bare trailing spacer.

        PR #340 added a trailing ``content_layout.addStretch()`` that pooled ALL surplus
        space into a blank gap at the bottom. Re-adding it makes the last layout item a
        spacer and fails this test.
        """
        layout = full_section.content_layout
        last = layout.itemAt(layout.count() - 1)
        assert last is not None
        assert last.spacerItem() is None, (
            "the last content_layout item must NOT be a trailing stretch/spacer — that "
            "pools the section's surplus space into a dead gap at the bottom"
        )
        assert last.widget() is full_section._retry_list, (
            "the last content item should be a sub-list (the retry list), so surplus "
            "space is shared by the lists, not stranded below them"
        )

    def test_three_sublists_share_equal_nonzero_stretch(self, full_section):
        """EPG tree, Movies & Series and Stream Monitoring all carry the same stretch>0.

        Equal, non-zero stretch is what distributes the section's surplus height evenly
        instead of funnelling it into one ballooning list. On ``main`` all three had the
        default stretch 0 (surplus funnelled to the uncapped EPG tree); this fails then.
        """
        layout = full_section.content_layout

        s_tree = layout.stretch(_index_of(layout, full_section.alerts_tree))
        s_vod = layout.stretch(_index_of(layout, full_section._vod_list))
        s_retry = layout.stretch(_index_of(layout, full_section._retry_list))

        assert s_tree > 0, "the EPG tree must carry a non-zero stretch to share the pane"
        assert s_tree == s_vod == s_retry, (
            f"all three sub-lists must share equally (tree={s_tree}, vod={s_vod}, "
            f"retry={s_retry}) so none balloons and none is starved"
        )

    def test_headers_do_not_take_stretch(self, full_section):
        """The sub-section header rows carry no stretch, so surplus goes to the lists."""
        layout = full_section.content_layout
        for hdr in (full_section._epg_hdr_container,
                    full_section._retry_hdr_container):
            assert layout.stretch(_index_of(layout, hdr)) == 0

    def test_sublists_are_expanding_vertically(self, full_section):
        """Each sub-list has an Expanding vertical policy so it grows to fill/share."""
        from PyQt6.QtWidgets import QSizePolicy

        for w in (full_section.alerts_tree,
                  full_section._vod_list,
                  full_section._retry_list):
            assert w.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding, (
                f"{w} must be vertically Expanding to participate in surplus sharing"
            )

    def test_epg_tree_is_bounded_by_stretch_not_a_hard_cap(self, full_section):
        """The EPG tree has NO hard maximumHeight — its bound is its stretch share.

        A hard cap (PR #340's ``_fit_alerts_tree_to_content``) sized the tree to its
        content, which stranded the section's surplus as a blank gap. Boundedness now
        comes from the equal stretch share of the splitter pane, so the tree must be
        left uncapped (free to shrink to its share). Re-adding a hard cap fails this.
        """
        assert full_section.alerts_tree.maximumHeight() == QWIDGETSIZE_MAX, (
            "the EPG tree must not be hard-capped; a content-sized cap strands surplus "
            "space as a dead gap — its bound is the shared stretch share of the pane"
        )

    def test_movies_series_not_hard_capped_so_it_is_not_cramped(self, full_section):
        """Movies & Series lost its 200px cap so it can grow to its fair share.

        The old 200px cap prevented Movies & Series from ever taking more than a sliver
        of a tall pane (and starved it when space was tight). Re-adding it fails here.
        """
        assert full_section._vod_list.maximumHeight() == QWIDGETSIZE_MAX, (
            "Movies & Series must not be hard-capped — it grows to its equal share so "
            "it is never cramped to a sliver"
        )

    def test_stream_monitoring_not_hard_capped(self, full_section):
        """Stream Monitoring lost its 120px cap and shares on the same footing."""
        assert full_section._retry_list.maximumHeight() == QWIDGETSIZE_MAX


def _stub_section_with_groups(n_groups: int, children_per_group: int):
    """Stub section whose ``alerts_tree`` holds ``n_groups`` expandable groups.

    Follows the ``__new__`` harness style in ``test_vod_watch_alerts.py``: we exercise
    ``_apply_expansion`` in isolation (it reads ``self.alerts_tree`` only).
    """
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
    """`_apply_expansion` keeps a long watchlist compact (scrolls) and expands a short one.

    This is the CONTENT-level "not unbounded" guarantee: a long EPG list stays collapsed
    and scrolls within the auto-expand budget rather than trying to reveal every row.
    """

    def test_short_group_set_expands_to_reveal_children(self, qapp):
        # 1 group * 3 children = 4 rows, well under the ~14-row budget → expand-all.
        section, _tree, groups = _stub_section_with_groups(1, 3)
        section._apply_expansion()
        assert groups[0].isExpanded(), (
            "a group set that fits the auto-expand budget must expand to reveal children"
        )

    def test_long_group_set_stays_collapsed_so_it_scrolls(self, qapp):
        # 8 groups * 4 children = 8 + 32 = 40 rows, far over the budget → collapse-all,
        # so the tree shows compact top-level rows and scrolls (never balloons).
        section, _tree, groups = _stub_section_with_groups(8, 4)
        section._apply_expansion()
        assert not any(g.isExpanded() for g in groups), (
            "a group set that would overflow the budget must stay collapsed so the tree "
            "scrolls compactly instead of trying to grow unbounded"
        )

    def test_apply_expansion_never_sets_a_hard_cap(self, qapp):
        """_apply_expansion must not pin the tree's maximumHeight (that stranded surplus)."""
        section, tree, _groups = _stub_section_with_groups(1, 3)
        section._apply_expansion()
        assert tree.maximumHeight() == QWIDGETSIZE_MAX
