"""Discover shelf filter — 1,882 shelves are unnavigable without one (#284).

The roadmap's proposed fix was to raise ``MIN_COLLECTION_SHELF_MEMBERS``.
Measured against the owner's library, that does not work: the floor is already
2, and the shelf count barely moves as it rises —

    >= 2 members : 1882 shelves     (today)
    >= 5         : 1848
    >= 10        : 1714
    >= 20        : 1440

There is no long tail to trim. There are genuinely that many collections, so a
cutoff would hide real ones arbitrarily while leaving the surface just as
unusable. Being able to type a name is the fix; a threshold is not.

These tests assert what is actually VISIBLE after filtering — not the contents
of a list, not the order of a dict. A filter that computes the right set and
leaves every widget on screen is the exact failure the UI-test rule exists for.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from metatv.gui.discover_view import DiscoverView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeShelf(QWidget):
    """Stands in for _Shelf — the filter only needs a title and visibility."""

    def __init__(self, title: str):
        super().__init__()
        self._title = title


@pytest.fixture()
def view(qapp):
    """A DiscoverView skeleton wired with the real filter method and 4 shelves.

    Built with ``__new__`` + the real handler rather than a full construction:
    the method under test touches only the widget registry and the three zone
    containers, and booting the whole view would drag in the DB and loader
    threads for no added coverage.
    """
    v = DiscoverView.__new__(DiscoverView)
    QWidget.__init__(v)

    v._shelf_widgets = {}
    outer = QVBoxLayout(v)
    zones = {}
    for name in ("pinned", "expanded", "collapsed"):
        container = QWidget()
        layout = QVBoxLayout(container)
        # Parented into the view: an unparented container never becomes
        # visible, so isVisible() would be False for every shelf and the
        # filter tests would all "pass" against a blank screen.
        outer.addWidget(container)
        setattr(v, f"_{name}_zone", container)
        setattr(v, f"_{name}_layout", layout)
        zones[name] = layout

    for key, title, zone in [
        ("collection:Apple+ Kids", "Apple+ Kids", "expanded"),
        ("collection:Hindu Subs",  "Hindu Subs",  "collapsed"),
        ("genre:Comedy",           "Comedy",      "collapsed"),
        ("decade:1990",            "1990s",       "pinned"),
    ]:
        shelf = _FakeShelf(title)
        v._shelf_widgets[key] = shelf
        zones[zone].addWidget(shelf)

    v.show()
    QApplication.processEvents()
    return v


def _visible(view) -> set[str]:
    return {
        s._title for s in view._shelf_widgets.values() if s.isVisible()
    }


class TestFiltering:

    def test_typing_hides_the_shelves_that_do_not_match(self, view):
        view._on_shelf_filter_changed("kids")
        QApplication.processEvents()

        assert _visible(view) == {"Apple+ Kids"}, (
            "non-matching shelves are still on screen — computing the right "
            "set is not the same as rendering it"
        )

    def test_matching_is_case_insensitive(self, view):
        view._on_shelf_filter_changed("APPLE")
        QApplication.processEvents()
        assert _visible(view) == {"Apple+ Kids"}

    def test_it_matches_the_visible_title_not_the_internal_key(self, view):
        """"collection:" is an implementation detail; typing it must not work
        while typing what the user can read must."""
        view._on_shelf_filter_changed("collection")
        QApplication.processEvents()
        assert _visible(view) == set()

        view._on_shelf_filter_changed("Hindu")
        QApplication.processEvents()
        assert _visible(view) == {"Hindu Subs"}

    def test_a_substring_matches_mid_title(self, view):
        view._on_shelf_filter_changed("ubs")
        QApplication.processEvents()
        assert _visible(view) == {"Hindu Subs"}

    def test_it_filters_every_shelf_kind_not_just_collections(self, view):
        """Genre and decade shelves are shelves too — a collection-only filter
        would be a surprise."""
        view._on_shelf_filter_changed("1990")
        QApplication.processEvents()
        assert _visible(view) == {"1990s"}

    def test_clearing_restores_every_shelf(self, view):
        view._on_shelf_filter_changed("kids")
        QApplication.processEvents()
        view._on_shelf_filter_changed("")
        QApplication.processEvents()

        assert _visible(view) == {"Apple+ Kids", "Hindu Subs", "Comedy", "1990s"}

    def test_whitespace_only_counts_as_cleared(self, view):
        view._on_shelf_filter_changed("   ")
        QApplication.processEvents()
        assert len(_visible(view)) == 4

    def test_no_match_hides_everything_without_crashing(self, view):
        view._on_shelf_filter_changed("zzzznope")
        QApplication.processEvents()
        assert _visible(view) == set()


class TestItDoesNotDamageState:

    def test_filtering_never_moves_a_shelf_between_zones(self, view):
        """A pinned shelf must still be pinned after filtering it out and back.

        Visibility and zone membership are different things; conflating them
        would silently unpin shelves as a side effect of typing.
        """
        before = [
            view._pinned_layout.itemAt(i).widget()
            for i in range(view._pinned_layout.count())
        ]

        view._on_shelf_filter_changed("comedy")
        QApplication.processEvents()
        view._on_shelf_filter_changed("")
        QApplication.processEvents()

        after = [
            view._pinned_layout.itemAt(i).widget()
            for i in range(view._pinned_layout.count())
        ]
        assert before == after

    def test_a_zone_with_a_match_stays_on_screen(self, view):
        view._on_shelf_filter_changed("1990")
        QApplication.processEvents()
        assert view._pinned_zone.isVisible(), (
            "hid the container of the only matching shelf — the match would be "
            "invisible despite matching"
        )


class TestTheControlIsUsable:
    """Project UI conventions, which exist because their absence is a papercut."""

    def test_it_has_a_clear_button_and_a_tooltip(self, qapp, tmp_path):
        from unittest.mock import MagicMock

        v = DiscoverView.__new__(DiscoverView)
        QWidget.__init__(v)
        v._config = MagicMock()
        v._config.discover_zoom = 1.0
        v._config.discover_hidden_shelves = []
        v._image_cache = MagicMock()
        v._db = MagicMock()
        v._shelf_widgets = {}
        v._setup_ui()

        assert v._shelf_filter.isClearButtonEnabled(), (
            "filter inputs use setClearButtonEnabled(True) — project standard"
        )
        assert v._shelf_filter.toolTip(), "every control needs a tooltip"
        assert v._shelf_filter.placeholderText()

    def test_the_filter_is_not_persisted(self):
        """A filter restored at launch shows a near-empty Discover with no
        visible cause, which reads as a broken app rather than a preference."""
        import inspect

        src = inspect.getsource(DiscoverView._on_shelf_filter_changed)
        assert "config" not in src and "save" not in src
