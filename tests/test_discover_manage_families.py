"""PLAT-2: the Manage-shelves dialog groups its rows by family.

The owner's framing is the whole point of the slice: this is a MANAGEMENT
change. In the manage dialog — where shelves are positioned, hidden and
restored — a long run of collections or platforms has to be scannable and
skippable. In the Discover strip itself, where content is browsed, a platform
shelf behaves like every other shelf and nothing is grouped at all. The last
test in this file is the guard on that second half.

What is asserted here is what would break:

  * headings render in the table's order, with the counts they claim, and their
    RENDERED y-positions stack in that order (order is not position);
  * a family with no rows in a section renders no heading;
  * folding a family shrinks the group's rendered height to the heading alone,
    and survives a close/reopen through config;
  * hiding a shelf moves its row under the destination's family heading and
    prunes the emptied one, without rebuilding a single sibling row (asserted
    on widget IDENTITY, which a rebuild would not preserve);
  * the Discover strip holds ``_Shelf`` widgets and nothing else.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config(tmp_path):
    """Isolated config that writes to tmp_path, not ~/.config/metatv."""
    from metatv.core.config import Config
    return Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                  cache_dir=tmp_path / "cache")


#: Four families in one Active zone, deliberately interleaved so a grouping
#: that merely preserved list order would fail every ordering assertion below.
_FOUR_FAMILIES = [
    "genre:Action",
    "platform:Netflix",
    "recently_added",
    "collection:Marvel",
    "genre:Drama",
    "platform:Max",
    "collection:Bond",
    "collection:Pixar",
]


def _groups(container):
    """Every ``_FamilyGroup`` in *container*, in layout (i.e. render) order."""
    from metatv.gui.discover_filter_dialog import _FamilyGroup
    vl = container.layout()
    out = []
    for i in range(vl.count()):
        widget = vl.itemAt(i).widget()
        if isinstance(widget, _FamilyGroup):
            out.append(widget)
    return out


def _dialog(config, owned_widgets, **over):
    from tests.conftest import make_discover_manage_dialog
    return owned_widgets.own(make_discover_manage_dialog(config, **over))


# ---------------------------------------------------------------------------
# 1. Headings: table order, real counts, real positions
# ---------------------------------------------------------------------------

class TestFamilyHeadings:

    def test_active_section_headings_render_in_table_order_with_counts(
            self, qapp, config, owned_widgets):
        """Four families group under headings ordered by SHELF_FAMILIES."""
        from metatv.gui.discover_workers import SHELF_FAMILY_ORDER

        config.discover_expanded_shelves = list(_FOUR_FAMILIES)
        dlg = _dialog(config, owned_widgets)

        groups = _groups(dlg._expanded_list)
        labels = [g.family for g in groups]
        assert labels == ["Discover", "Platforms", "Collections", "Genres"], (
            f"families must render in the SHELF_FAMILIES order "
            f"{SHELF_FAMILY_ORDER}, got {labels}"
        )
        counts = {g.family: g.row_count() for g in groups}
        assert counts == {"Discover": 1, "Platforms": 2,
                          "Collections": 3, "Genres": 2}, counts
        for group in groups:
            assert f"({group.row_count()})" in group.heading.text(), (
                f"a disclosure states its count: {group.heading.text()!r}"
            )

    def test_headings_stack_in_table_order_on_screen(
            self, qapp, config, owned_widgets):
        """Rendered geometry, not list order: each heading sits below the last.

        Layout ORDER is not layout POSITION — a section could hold the groups
        in the right sequence and still paint them anywhere. This lays the
        section out for real and reads the y-coordinates back.
        """
        config.discover_expanded_shelves = list(_FOUR_FAMILIES)
        dlg = _dialog(config, owned_widgets)

        container = dlg._expanded_list
        container.resize(480, container.sizeHint().height())
        container.layout().activate()

        groups = _groups(container)
        tops = [g.y() for g in groups]
        assert tops == sorted(tops) and len(set(tops)) == len(tops), (
            f"family headings must stack top-to-bottom in table order, y={tops}"
        )
        for group in groups:
            assert group.height() > 0, f"{group.family} rendered with no height"
            # The heading is drawn ABOVE its rows, inside the group.
            assert group.heading.y() == 0, (
                f"{group.family}: heading must lead its rows, "
                f"y={group.heading.y()}"
            )

    def test_family_with_no_members_shows_no_heading(
            self, qapp, config, owned_widgets):
        """Only families that actually have rows in a section get a heading."""
        config.discover_expanded_shelves = ["genre:Action", "genre:Drama"]
        config.discover_hidden_shelves = ["platform:Netflix"]
        dlg = _dialog(config, owned_widgets)

        assert [g.family for g in _groups(dlg._expanded_list)] == ["Genres"], (
            "a section with only genre shelves must show one heading"
        )
        assert [g.family for g in _groups(dlg._hidden_list)] == ["Platforms"]
        assert _groups(dlg._pinned_list) == [], (
            "an empty section must show no family headings at all"
        )


# ---------------------------------------------------------------------------
# 2. Folding — rendered height, and a config round-trip
# ---------------------------------------------------------------------------

class TestFolding:

    def test_folding_a_family_collapses_it_to_its_heading(
            self, qapp, config, owned_widgets):
        """Clicking a heading removes its rows' height from the rendering."""
        config.discover_expanded_shelves = list(_FOUR_FAMILIES)
        dlg = _dialog(config, owned_widgets)

        collections = next(g for g in _groups(dlg._expanded_list)
                           if g.family == "Collections")
        open_h = collections.sizeHint().height()
        heading_h = collections.heading.sizeHint().height()
        assert open_h > heading_h, (
            "three collection rows must add height over the bare heading"
        )

        collections.heading.click()

        folded_h = collections.sizeHint().height()
        assert folded_h < open_h, (
            f"folding must shrink the group: {folded_h} not < {open_h}"
        )
        assert folded_h >= heading_h > 0, (
            "the heading itself must survive the fold, so it can be reopened"
        )
        assert collections.is_folded()

    def test_fold_survives_a_close_and_reopen(
            self, qapp, config, owned_widgets):
        """The folded set round-trips through config, restored on next open."""
        config.discover_expanded_shelves = list(_FOUR_FAMILIES)
        dlg = _dialog(config, owned_widgets)

        next(g for g in _groups(dlg._expanded_list)
             if g.family == "Collections").heading.click()

        assert config.discover_manage_folded_families == ["Collections"], (
            f"the fold must be stored, got "
            f"{config.discover_manage_folded_families!r}"
        )

        reopened = _dialog(config, owned_widgets)
        restored = {g.family: g.is_folded()
                    for g in _groups(reopened._expanded_list)}
        assert restored["Collections"] is True, "the fold must be restored"
        assert restored["Genres"] is False, (
            "only the folded family may come back folded"
        )
        folded = next(g for g in _groups(reopened._expanded_list)
                      if g.family == "Collections")
        assert folded.sizeHint().height() <= folded.heading.sizeHint().height(), (
            "a restored fold must render as the heading alone"
        )

    def test_folding_never_touches_a_zone_or_forces_a_refresh(
            self, qapp, config, owned_widgets):
        """Fold is dialog state: no zone list moves, no shelf refresh is asked for."""
        config.discover_expanded_shelves = list(_FOUR_FAMILIES)
        dlg = _dialog(config, owned_widgets)
        before = list(config.discover_expanded_shelves)

        next(g for g in _groups(dlg._expanded_list)
             if g.family == "Collections").heading.click()

        assert config.discover_expanded_shelves == before, (
            "folding a heading must not move a shelf between zones"
        )
        assert config.discover_collapsed_shelves == []
        assert config.discover_hidden_shelves == []
        assert dlg._changed is False, (
            "a fold changes nothing Discover renders, so it must not trigger "
            "DiscoverView.refresh() on close"
        )


# ---------------------------------------------------------------------------
# 3. Transfers stay O(1) and land under the right heading
# ---------------------------------------------------------------------------

class TestTransferKeepsFamilies:

    def test_hiding_a_shelf_lands_under_the_hidden_family_heading(
            self, qapp, config, owned_widgets):
        """Hide moves the row under Hidden ▸ Platforms, prunes the emptied one,
        and rebuilds nothing else."""
        config.discover_collapsed_shelves = [
            "platform:Netflix", "genre:Action", "genre:Drama",
        ]
        dlg = _dialog(config, owned_widgets)

        untouched = {k: dlg._row_widgets[k]
                     for k in ("genre:Action", "genre:Drama")}
        assert [g.family for g in _groups(dlg._collapsed_list)] == [
            "Platforms", "Genres"]

        dlg._transfer("platform:Netflix",
                      dlg._collapsed, dlg._collapsed_list,
                      dlg._hidden, dlg._hidden_list,
                      dlg._build_hidden_row)

        hidden_groups = _groups(dlg._hidden_list)
        assert [g.family for g in hidden_groups] == ["Platforms"], (
            "the moved row must create its family heading in the destination"
        )
        assert hidden_groups[0].row_count() == 1
        assert "(1)" in hidden_groups[0].heading.text()

        assert [g.family for g in _groups(dlg._collapsed_list)] == ["Genres"], (
            "the emptied Platforms heading must go with its last row"
        )
        for key, widget in untouched.items():
            assert dlg._row_widgets[key] is widget, (
                f"{key} was rebuilt — the transfer is no longer O(1)"
            )

    def test_restoring_into_an_existing_family_reuses_its_heading(
            self, qapp, config, owned_widgets):
        """A second platform lands under the heading the first one created."""
        config.discover_collapsed_shelves = ["platform:Netflix"]
        config.discover_hidden_shelves = ["platform:Max", "genre:Action"]
        dlg = _dialog(config, owned_widgets)

        platforms = next(g for g in _groups(dlg._collapsed_list)
                         if g.family == "Platforms")

        dlg._transfer("platform:Max",
                      dlg._hidden, dlg._hidden_list,
                      dlg._collapsed, dlg._collapsed_list,
                      dlg._build_collapsed_row)

        groups = _groups(dlg._collapsed_list)
        assert [g.family for g in groups] == ["Platforms"], (
            "a second platform must not open a second Platforms heading"
        )
        assert groups[0] is platforms, "the existing heading must be reused"
        assert groups[0].row_count() == 2
        assert "(2)" in groups[0].heading.text(), groups[0].heading.text()

    def test_a_new_family_is_inserted_at_its_table_rank(
            self, qapp, config, owned_widgets):
        """Pinning a genre into a section holding a platform keeps table order."""
        config.discover_pinned_shelves = ["collection:Bond"]
        config.discover_collapsed_shelves = ["platform:Netflix"]
        dlg = _dialog(config, owned_widgets)

        dlg._transfer("platform:Netflix",
                      dlg._collapsed, dlg._collapsed_list,
                      dlg._pinned, dlg._pinned_list,
                      dlg._build_pinned_row)

        assert [g.family for g in _groups(dlg._pinned_list)] == [
            "Platforms", "Collections"], (
            "Platforms outranks Collections in SHELF_FAMILIES, so a heading "
            "created by a transfer must be inserted above it"
        )


# ---------------------------------------------------------------------------
# 4. Reorder moves a row inside the group it is DRAWN in
# ---------------------------------------------------------------------------

class TestReorderWithinFamily:

    def test_move_up_swaps_with_the_same_family_neighbour(
            self, qapp, config, owned_widgets):
        """Up must move the row visibly, not past a row in another family."""
        config.discover_expanded_shelves = [
            "genre:Action", "platform:Netflix", "genre:Drama",
        ]
        dlg = _dialog(config, owned_widgets)

        dlg._move_up(dlg._expanded, "genre:Drama",
                     dlg._expanded_list, dlg._build_expanded_row)

        genres = next(g for g in _groups(dlg._expanded_list)
                      if g.family == "Genres")
        rows = genres._rows.layout()
        drawn = [rows.itemAt(i).widget().shelf_key for i in range(rows.count())]
        assert drawn == ["genre:Drama", "genre:Action"], (
            f"Drama must rise above Action inside Genres, got {drawn}"
        )
        assert "platform:Netflix" in config.discover_expanded_shelves, (
            "the other family's shelf must be left alone"
        )


# ---------------------------------------------------------------------------
# 5. The family table itself
# ---------------------------------------------------------------------------

class TestFamilyTable:

    @pytest.mark.parametrize("key,family", [
        ("user_cat:Kids", "Your categories"),
        ("recipe:Friday night", "Saved recipes"),
        ("platform:Netflix", "Platforms"),
        ("collection:Marvel", "Collections"),
        ("genre:Action", "Genres"),
        ("decade:1990", "Decades"),
        ("actor:Tom Hanks", "Featuring"),
        ("recently_added", "Discover"),
        ("top_movies", "Discover"),
        ("top_series", "Discover"),
    ])
    def test_family_of(self, key, family):
        from metatv.gui.discover_workers import family_of
        assert family_of(key) == family

    def test_every_family_label_is_in_the_render_order(self):
        """One table: the order is derived from it, never hand-listed beside it."""
        from metatv.gui.discover_workers import (
            FIXED_SHELF_FAMILY, SHELF_FAMILIES, SHELF_FAMILY_ORDER,
        )
        assert SHELF_FAMILY_ORDER == (
            (FIXED_SHELF_FAMILY,) + tuple(label for _p, label in SHELF_FAMILIES)
        )
        assert len(set(SHELF_FAMILY_ORDER)) == len(SHELF_FAMILY_ORDER), (
            "two families sharing a label would collapse into one heading"
        )


# ---------------------------------------------------------------------------
# 6. The BROWSING view is untouched — a platform shelf is an ordinary shelf
# ---------------------------------------------------------------------------

class TestBrowsingStripIsNotGrouped:

    def _view(self, config, owned_widgets):
        """A DiscoverView with only its three zone containers wired.

        Everything hangs off ONE owned parent, so ``_add_to_zone``'s
        ``setVisible(True)`` marks a child visible instead of popping a
        top-level window open mid-suite.
        """
        from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget
        from metatv.gui.discover_view import DiscoverView

        host = owned_widgets.own(QWidget())
        view = DiscoverView.__new__(DiscoverView)
        view._config = config
        view._pending_collapsed = []
        view._more_expanded = False
        for zone in ("pinned", "expanded", "collapsed"):
            widget = QWidget(host)
            layout = QVBoxLayout(widget)
            setattr(view, f"_{zone}_zone", widget)
            setattr(view, f"_{zone}_layout", layout)
        view._more_btn = QPushButton(host)
        return view

    def test_zone_layouts_hold_only_shelves(self, qapp, config, owned_widgets):
        """Four families go into the strip; four plain shelves come out.

        No heading widget, no extra layout item — a platform shelf browses
        exactly like a genre shelf, which is the half of PLAT-2 that must NOT
        change.
        """
        from unittest.mock import MagicMock

        from metatv.gui.discover_filter_dialog import _FamilyGroup
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_view import _ZONE_EXPANDED

        view = self._view(config, owned_widgets)
        keys = ["platform:Netflix", "platform:Max",
                "collection:Marvel", "genre:Action", "recently_added"]
        for key in keys:
            shelf = _Shelf(key, key, [], MagicMock(), config)
            view._add_to_zone(shelf, _ZONE_EXPANDED)

        layout = view._expanded_layout
        assert layout.count() == len(keys), (
            f"the strip must hold one item per shelf and nothing else, "
            f"got {layout.count()} for {len(keys)} shelves"
        )
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        assert all(isinstance(w, _Shelf) for w in widgets), (
            f"every strip item must be a _Shelf, got "
            f"{[type(w).__name__ for w in widgets]}"
        )
        assert not any(isinstance(w, _FamilyGroup) for w in widgets)
        assert [w._shelf_key for w in widgets] == keys, (
            "the strip must keep the order it was given — grouping would "
            "reorder a platform shelf away from its neighbours"
        )
