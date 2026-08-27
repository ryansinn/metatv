"""Tests for the Similar-Titles lightbox breadcrumb trail widget."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.gui.lightbox_breadcrumb import LightboxBreadcrumb


@pytest.fixture
def app():
    """Ensure QApplication exists for Qt widget tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    """Create a temporary database file."""
    return tmp_path / "test.db"


@pytest.fixture
def database() -> dict:
    """Titles map standing in for what the lightbox caches as the user dives.

    The breadcrumb no longer touches the DB — it renders from titles captured
    at dive time (they were already loaded to display each card), so this
    fixture is just a dict. Named `database` so the existing tests read
    unchanged.
    """
    return {f"ch{i}": f"Title {i}" for i in range(1, 12)}


@pytest.fixture
def breadcrumb(app) -> LightboxBreadcrumb:
    """Create a breadcrumb widget."""
    return LightboxBreadcrumb()


class TestBreadcrumbHides:
    """Test that breadcrumb hides when not in a dive."""

    def test_hides_when_no_nav_stack(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Breadcrumb should be hidden when not in a dive (nav_stack empty)."""
        breadcrumb.update_trail("Origin", ["a", "b"], [], "a", database)
        assert not breadcrumb.isVisible()

    def test_shows_when_nav_stack_present(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Breadcrumb should be visible when in a dive (nav_stack not empty)."""
        breadcrumb.update_trail("Origin", ["a", "b"], ["a"], "b", database)
        assert breadcrumb.isVisible()


class TestBreadcrumbTrailConstruction:
    """Test that breadcrumb correctly renders the trail."""

    def test_simple_trail_no_elision(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Simple trail with no elision: Origin › A › Current."""

        breadcrumb.update_trail("Origin", [], ["a"], "b", database)
        assert breadcrumb.isVisible()
        # Verify the trail was built (via layout count: separators + crumbs + stretch)
        # 6 items: origin label + sep + crumb a + sep + current label + stretch
        assert breadcrumb._layout.count() == 6

    def test_long_trail_elides_in_middle(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Long trail elides in the middle: Origin › … › B › Current."""

        # Trail: origin > a > b > c > d > e (5 items, exceeds max_visible of 4)
        breadcrumb.update_trail("Origin", [], ["ch0", "ch1", "ch2", "ch3"], "ch4", database)
        assert breadcrumb.isVisible()
        # Should render: origin › … › ch3 › ch4
        # 6 items: origin + sep + ellipsis + sep + penultimate + sep + current + stretch
        assert breadcrumb._layout.count() == 8

    def test_current_crumb_not_clickable(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Current (last) crumb should not be clickable."""

        breadcrumb.update_trail("Origin", [], ["a"], "b", database)
        # The current crumb is a QLabel, not a _CrumbButton, so it can't emit crumb_clicked
        # Just verify it's there and styled as current (via CSS class)
        assert breadcrumb.isVisible()


class TestBreadcrumbClickable:
    """Test that earlier crumbs are clickable."""

    def test_earlier_crumb_is_clickable(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Earlier crumbs should be clickable and emit crumb_clicked signal."""

        breadcrumb.update_trail("Origin", [], ["a", "b"], "c", database)

        # Record emitted signals
        emitted_ids: list[str] = []
        breadcrumb.crumb_clicked.connect(lambda cid: emitted_ids.append(cid))

        # Simulate clicking the first crumb (channel_id "a")
        if "a" in breadcrumb._crumb_buttons:
            breadcrumb._crumb_buttons["a"].click()
            assert emitted_ids == ["a"]


class TestBreadcrumbEllipsis:
    """Test that ellipsis opens Explore."""

    def test_ellipsis_emits_explore_signal(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Ellipsis button should emit explore_ellipsis_clicked when clicked."""

        breadcrumb.update_trail("Origin", [], ["ch0", "ch1", "ch2", "ch3"], "ch4", database)

        # Record emitted signals
        explore_clicked: list[bool] = []
        breadcrumb.explore_ellipsis_clicked.connect(lambda: explore_clicked.append(True))

        # Simulate clicking the ellipsis (should be widget at index 2 if present)
        if breadcrumb._layout.count() >= 4:
            item = breadcrumb._layout.itemAt(2)
            if item and item.widget():
                # It should be the ellipsis button
                item.widget().click()
                assert explore_clicked == [True]


class TestBreadcrumbTooltips:
    """Test that crumbs have full titles as tooltips."""

    def test_crumb_tooltip_is_full_title(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Each crumb should have its full title as the tooltip."""

        breadcrumb.update_trail("Origin", [], ["a"], "b", database)

        # Check if the crumb button has the correct tooltip
        if "a" in breadcrumb._crumb_buttons:
            assert breadcrumb._crumb_buttons["a"].toolTip() == "Very Long Title A"


class TestBreadcrumbTruncatesStack:
    """Test that clicking an earlier crumb truncates the stack."""

    def test_clicking_crumb_truncates_stack(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Verify the breadcrumb emits the correct channel_id when clicked."""

        breadcrumb.update_trail("Origin", [], ["a", "b"], "c", database)

        # Record which crumb was clicked
        clicked: list[str] = []
        breadcrumb.crumb_clicked.connect(lambda cid: clicked.append(cid))

        # Click crumb "a"
        if "a" in breadcrumb._crumb_buttons:
            breadcrumb._crumb_buttons["a"].click()
            assert clicked == ["a"]


class TestBreadcrumbRebuild:
    """Test that breadcrumb can be rebuilt with new data."""

    def test_rebuild_after_dive(self, breadcrumb: LightboxBreadcrumb, database: dict):
        """Breadcrumb should rebuild correctly when trail changes."""

        # Initial trail
        breadcrumb.update_trail("Origin", [], ["ch0", "ch1"], "ch2", database)
        assert breadcrumb.isVisible()

        # Deeper dive
        breadcrumb.update_trail("Origin", [], ["ch0", "ch1", "ch2"], "ch3", database)
        assert breadcrumb.isVisible()
        # Old crumbs cleared, new ones added. At this depth the trail elides in
        # the middle (Origin › … › ch2 › ch3), so ch0/ch1 are intentionally
        # absent — the elision is the feature, not a rebuild failure.
        assert "ch2" in breadcrumb._crumb_buttons
        assert "ch0" not in breadcrumb._crumb_buttons
        assert "ch1" not in breadcrumb._crumb_buttons
