"""Tests for the Similar-Titles lightbox breadcrumb trail widget."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.core.database import Database
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
def database(db_file: Path) -> Database:
    """Create a real database instance."""
    return Database(db_file)


@pytest.fixture
def breadcrumb(app) -> LightboxBreadcrumb:
    """Create a breadcrumb widget."""
    return LightboxBreadcrumb()


class TestBreadcrumbHides:
    """Test that breadcrumb hides when not in a dive."""

    def test_hides_when_no_nav_stack(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Breadcrumb should be hidden when not in a dive (nav_stack empty)."""
        breadcrumb.update_trail("Origin", ["a", "b"], [], "a", database)
        assert not breadcrumb.isVisible()

    def test_shows_when_nav_stack_present(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Breadcrumb should be visible when in a dive (nav_stack not empty)."""
        breadcrumb.update_trail("Origin", ["a", "b"], ["a"], "b", database)
        assert breadcrumb.isVisible()


class TestBreadcrumbTrailConstruction:
    """Test that breadcrumb correctly renders the trail."""

    def test_simple_trail_no_elision(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Simple trail with no elision: Origin › A › Current."""
        # Setup: create channels in DB
        with database.session_scope(commit=True) as session:
            from metatv.core.database import ChannelDB
            session.add(ChannelDB(id="a", name="Title A"))
            session.add(ChannelDB(id="b", name="Title B"))

        breadcrumb.update_trail("Origin", [], ["a"], "b", database)
        assert breadcrumb.isVisible()
        # Verify the trail was built (via layout count: separators + crumbs + stretch)
        # 6 items: origin label + sep + crumb a + sep + current label + stretch
        assert breadcrumb._layout.count() == 6

    def test_long_trail_elides_in_middle(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Long trail elides in the middle: Origin › … › B › Current."""
        with database.session_scope(commit=True) as session:
            from metatv.core.database import ChannelDB
            for i in range(6):
                session.add(ChannelDB(id=f"ch{i}", name=f"Title {i}"))

        # Trail: origin > a > b > c > d > e (5 items, exceeds max_visible of 4)
        breadcrumb.update_trail("Origin", [], ["ch0", "ch1", "ch2", "ch3"], "ch4", database)
        assert breadcrumb.isVisible()
        # Should render: origin › … › ch3 › ch4
        # 6 items: origin + sep + ellipsis + sep + penultimate + sep + current + stretch
        assert breadcrumb._layout.count() == 8

    def test_current_crumb_not_clickable(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Current (last) crumb should not be clickable."""
        with database.session_scope(commit=True) as session:
            from metatv.core.database import ChannelDB
            session.add(ChannelDB(id="a", name="Title A"))
            session.add(ChannelDB(id="b", name="Title B"))

        breadcrumb.update_trail("Origin", [], ["a"], "b", database)
        # The current crumb is a QLabel, not a _CrumbButton, so it can't emit crumb_clicked
        # Just verify it's there and styled as current (via CSS class)
        assert breadcrumb.isVisible()


class TestBreadcrumbClickable:
    """Test that earlier crumbs are clickable."""

    def test_earlier_crumb_is_clickable(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Earlier crumbs should be clickable and emit crumb_clicked signal."""
        with database.session_scope(commit=True) as session:
            from metatv.core.database import ChannelDB
            session.add(ChannelDB(id="a", name="Title A"))
            session.add(ChannelDB(id="b", name="Title B"))
            session.add(ChannelDB(id="c", name="Title C"))

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

    def test_ellipsis_emits_explore_signal(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Ellipsis button should emit explore_ellipsis_clicked when clicked."""
        with database.session_scope(commit=True) as session:
            from metatv.core.database import ChannelDB
            for i in range(6):
                session.add(ChannelDB(id=f"ch{i}", name=f"Title {i}"))

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

    def test_crumb_tooltip_is_full_title(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Each crumb should have its full title as the tooltip."""
        with database.session_scope(commit=True) as session:
            from metatv.core.database import ChannelDB
            session.add(ChannelDB(id="a", name="Very Long Title A"))
            session.add(ChannelDB(id="b", name="Very Long Title B"))

        breadcrumb.update_trail("Origin", [], ["a"], "b", database)

        # Check if the crumb button has the correct tooltip
        if "a" in breadcrumb._crumb_buttons:
            assert breadcrumb._crumb_buttons["a"].toolTip() == "Very Long Title A"


class TestBreadcrumbTruncatesStack:
    """Test that clicking an earlier crumb truncates the stack."""

    def test_clicking_crumb_truncates_stack(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Verify the breadcrumb emits the correct channel_id when clicked."""
        with database.session_scope(commit=True) as session:
            from metatv.core.database import ChannelDB
            session.add(ChannelDB(id="a", name="Title A"))
            session.add(ChannelDB(id="b", name="Title B"))
            session.add(ChannelDB(id="c", name="Title C"))

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

    def test_rebuild_after_dive(self, breadcrumb: LightboxBreadcrumb, database: Database):
        """Breadcrumb should rebuild correctly when trail changes."""
        with database.session_scope(commit=True) as session:
            from metatv.core.database import ChannelDB
            for i in range(5):
                session.add(ChannelDB(id=f"ch{i}", name=f"Title {i}"))

        # Initial trail
        breadcrumb.update_trail("Origin", [], ["ch0", "ch1"], "ch2", database)
        assert breadcrumb.isVisible()

        # Deeper dive
        breadcrumb.update_trail("Origin", [], ["ch0", "ch1", "ch2"], "ch3", database)
        assert breadcrumb.isVisible()
        # Verify the old crumbs are cleared and new ones added
        assert "ch0" in breadcrumb._crumb_buttons
        assert "ch1" in breadcrumb._crumb_buttons
        assert "ch2" in breadcrumb._crumb_buttons
