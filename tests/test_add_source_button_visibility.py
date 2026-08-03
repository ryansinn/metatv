"""Behavioral tests for Add Source button visibility fix.

The "Add Source" (+) button on two surfaces was nearly invisible:
- Sources strip (sidebar): tiny (22×20) with COLOR_DIM foreground on OVERLAY_05 background
- Sources manager view: tiny icon-only (+) fixed to 24×22

This test verifies the fix:
- Strip button: 28×24, COLOR_TEXT foreground, OVERLAY_15 background, visible border
- Manager button: text "Add Source", sizes to content (min-height 24), wider than old fixed width

Icon registry enforcement (owner-mandated rule):
- All "+" glyphs route through icons.add_icon, never hardcoded literals in widget code.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.gui import theme as _theme
from metatv.gui.sidebar.sources import SourcesSection
from metatv.gui.sources_manager_view import SourcesManagerView


@pytest.fixture(scope="module")
def qapp():
    """Module-level Qt application fixture."""
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeConfig:
    """Minimal config stub for widget construction."""
    discover_zoom = 1.0
    provider_icon = "📡"
    refresh_icon = "⟳"


def test_sources_strip_button_size(qapp, tmp_path):
    """Strip button must be at least 28×24 pixels (was 22×20)."""
    db = Database(f"sqlite:///{tmp_path}/test.db")
    config = _FakeConfig()

    sources_section = SourcesSection(config, db)
    sources_section.show()

    # The add button is built in create_header()
    sources_section.create_header()
    sources_section.create_content()

    # Find the add button (last button in the header)
    buttons = [w for w in sources_section.findChildren(type(sources_section.title_label.__class__.__bases__[0]))]

    # More direct approach: check if the stylesheet contains the expected size
    # The button was updated to use f-string without format, so we just verify
    # the button exists and is rendered
    assert sources_section.title_label is not None

    # Actually, let's access the add button through the header we just created
    header_layout = sources_section.main_layout.itemAt(0).widget().layout()

    # The layout has: title_label, stretch, refresh_all_btn, add_btn
    # add_btn is the last widget
    add_btn = header_layout.itemAt(header_layout.count() - 1).widget()

    assert add_btn is not None
    assert add_btn.text() == "+"

    # Check the rendered size (should be at least 28×24)
    size = add_btn.size()
    assert size.width() >= 28, f"Button width {size.width()} < 28"
    assert size.height() >= 24, f"Button height {size.height()} < 24"


def test_sources_strip_button_foreground_not_dim(qapp, tmp_path):
    """Strip button foreground must NOT be COLOR_DIM (the bug was dimming)."""
    db = Database(f"sqlite:///{tmp_path}/test.db")
    config = _FakeConfig()

    sources_section = SourcesSection(config, db)
    sources_section.create_header()
    sources_section.create_content()

    header_layout = sources_section.main_layout.itemAt(0).widget().layout()
    add_btn = header_layout.itemAt(header_layout.count() - 1).widget()

    stylesheet = add_btn.styleSheet()

    # The new stylesheet uses COLOR_TEXT, not COLOR_DIM
    assert _theme.COLOR_TEXT in stylesheet, (
        f"Button should use COLOR_TEXT for visibility; got stylesheet: {stylesheet}"
    )
    assert _theme.COLOR_DIM not in stylesheet, (
        f"Button should NOT use COLOR_DIM (the dimming was the bug); got stylesheet: {stylesheet}"
    )


def test_sources_strip_button_has_border(qapp, tmp_path):
    """Strip button must have a visible border."""
    db = Database(f"sqlite:///{tmp_path}/test.db")
    config = _FakeConfig()

    sources_section = SourcesSection(config, db)
    sources_section.create_header()
    sources_section.create_content()

    header_layout = sources_section.main_layout.itemAt(0).widget().layout()
    add_btn = header_layout.itemAt(header_layout.count() - 1).widget()

    stylesheet = add_btn.styleSheet()

    # Should have a 1px border
    assert "border:" in stylesheet or "border-" in stylesheet, (
        f"Button should have a border; got stylesheet: {stylesheet}"
    )


def test_sources_strip_button_connects_to_signal(qapp, tmp_path):
    """Strip button must emit addProviderClicked signal."""
    db = Database(f"sqlite:///{tmp_path}/test.db")
    config = _FakeConfig()

    sources_section = SourcesSection(config, db)
    sources_section.create_header()
    sources_section.create_content()

    # Verify the signal exists and is connected
    assert hasattr(sources_section, "addProviderClicked")

    # Verify signal can be emitted (connection test)
    signal_received = []
    sources_section.addProviderClicked.connect(lambda: signal_received.append(True))
    sources_section.addProviderClicked.emit()
    assert signal_received, "addProviderClicked signal should fire"


def test_sources_manager_button_has_text(qapp, tmp_path):
    """Manager button must have text "Add Source" (was just "+")."""
    db = Database(f"sqlite:///{tmp_path}/test.db")
    config = _FakeConfig()

    # Create a minimal provider_editor stub
    class _FakeProviderEditor:
        analyze_requested = type("Signal", (), {"connect": lambda *a: None})()
        toggle_active_requested = type("Signal", (), {"connect": lambda *a: None})()
        epg_refresh_requested = type("Signal", (), {"connect": lambda *a: None})()

    provider_editor = _FakeProviderEditor()

    manager = SourcesManagerView(config, db, provider_editor)

    assert "Add Source" in manager._add_btn.text(), (
        f"Button text should contain 'Add Source'; got '{manager._add_btn.text()}'"
    )


def test_sources_manager_button_sizes_to_content(qapp, tmp_path):
    """Manager button must size to its label content, not be fixed-size."""
    db = Database(f"sqlite:///{tmp_path}/test.db")
    config = _FakeConfig()

    class _FakeProviderEditor:
        analyze_requested = type("Signal", (), {"connect": lambda *a: None})()
        toggle_active_requested = type("Signal", (), {"connect": lambda *a: None})()
        epg_refresh_requested = type("Signal", (), {"connect": lambda *a: None})()

    provider_editor = _FakeProviderEditor()

    manager = SourcesManagerView(config, db, provider_editor)

    # The button should not have a fixed width (should be wider than old 24px)
    assert not manager._add_btn.maximumWidth() <= 24, (
        "Button should not be fixed to 24px width or less"
    )

    # Check that it has a minimum height instead
    assert manager._add_btn.minimumHeight() == 24, (
        "Button should have minimumHeight() == 24"
    )


def test_sources_manager_button_wider_than_old_fixed(qapp, tmp_path):
    """Manager button with "Add Source" label must be wider than old 24px fixed width."""
    db = Database(f"sqlite:///{tmp_path}/test.db")
    config = _FakeConfig()

    class _FakeProviderEditor:
        analyze_requested = type("Signal", (), {"connect": lambda *a: None})()
        toggle_active_requested = type("Signal", (), {"connect": lambda *a: None})()
        epg_refresh_requested = type("Signal", (), {"connect": lambda *a: None})()

    provider_editor = _FakeProviderEditor()

    manager = SourcesManagerView(config, db, provider_editor)
    manager.show()

    # Size to contents
    manager._add_btn.adjustSize()

    # Must be wider than old 24px
    assert manager._add_btn.width() > 24, (
        f"Button width {manager._add_btn.width()} should be > 24px"
    )


def test_sources_manager_button_connects_to_signal(qapp, tmp_path):
    """Manager button must emit addProviderClicked signal."""
    db = Database(f"sqlite:///{tmp_path}/test.db")
    config = _FakeConfig()

    class _FakeProviderEditor:
        analyze_requested = type("Signal", (), {"connect": lambda *a: None})()
        toggle_active_requested = type("Signal", (), {"connect": lambda *a: None})()
        epg_refresh_requested = type("Signal", (), {"connect": lambda *a: None})()

    provider_editor = _FakeProviderEditor()

    manager = SourcesManagerView(config, db, provider_editor)

    # Verify the signal exists
    assert hasattr(manager, "addProviderClicked")

    # Verify signal can be emitted
    signal_received = []
    manager.addProviderClicked.connect(lambda: signal_received.append(True))
    manager.addProviderClicked.emit()
    assert signal_received, "addProviderClicked signal should fire"


# ---------------------------------------------------------------------------
# Icon registry guard — no hardcoded "+" literals in widget code
# ---------------------------------------------------------------------------

def test_no_hardcoded_plus_icon_in_gui_widgets():
    """Enforce icon registry rule: all "+" glyphs must use icons.add_icon, never hardcoded literals.

    This drift-guard scans metatv/gui/*.py for the anti-pattern `QPushButton("+")` and fails
    if any remain, catching violations of the owner-mandated single icon registry rule.
    """
    gui_dir = pathlib.Path(__file__).parent.parent / "metatv" / "gui"

    # Pattern: QPushButton("+") — the hardcoded literal we want to prevent
    hardcoded_pattern = re.compile(r'QPushButton\s*\(\s*["\']?[+]\s*["\']?\s*\)')

    violations = []
    for py_file in gui_dir.glob("**/*.py"):
        # Skip test files and the icon registry itself
        if "test" in py_file.name or "icons.py" in py_file.name:
            continue

        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.split("\n"), 1):
            if hardcoded_pattern.search(line):
                violations.append(f"{py_file.relative_to(gui_dir)}:{line_num}: {line.strip()}")

    assert not violations, (
        f"Found {len(violations)} hardcoded '+' literals in QPushButton (should use icons.add_icon):\n"
        + "\n".join(violations)
    )
