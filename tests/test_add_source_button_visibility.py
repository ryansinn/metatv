"""Behavioral tests for Add Source button visibility fix.

The "Add Source" (+) button on two surfaces was nearly invisible:
- Sources strip (sidebar): tiny (22×20) with COLOR_DIM foreground on OVERLAY_05 background
- Sources manager view: tiny icon-only (+) fixed to 24×22

This test verifies the fix:
- Strip button: 28×24, COLOR_TEXT foreground, OVERLAY_15 background, visible border
- Manager button: text "Add Source", sizes to content (min-height 24), wider than old fixed width

Icon registry enforcement (owner-mandated rule):
- All "+" glyphs route through icons.add_icon, never hardcoded literals in widget code.

Harness notes:
- ``SourcesSection.__init__`` already builds the header/content itself (via its own
  ``create_header()``/``create_content()`` calls) — tests must NOT call those again,
  or the header gets built twice and stacks a stale duplicate onto ``main_layout``.
  ``_make_sources_section`` below constructs the section exactly once and reads back
  what ``__init__`` already built.
- ``SourcesManagerView`` only stores ``config``/``db`` (never queries them) and embeds
  ``provider_editor`` via ``addWidget()``, which requires a real ``QWidget`` — so the
  stand-in below is a trivial ``QWidget`` subclass carrying just the three signals
  ``__init__`` connects (``analyze_requested``/``toggle_active_requested``/
  ``epg_refresh_requested``), not a hand-rolled non-widget fake.
- Both surfaces get a real ``Config()`` (all icon attributes are real defaults — no
  need for a fake config that can drift out of sync with what the widgets read) and a
  real file-backed ``Database`` per the project's tmp_path convention (never
  ``:memory:``), even though neither constructor path touches it.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

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


class _FakeProviderEditor(QWidget):
    """Minimal real QWidget stand-in for ``ProviderEditorView``.

    ``SourcesManagerView.__init__`` embeds this via ``QVBoxLayout.addWidget()``
    (requires an actual ``QWidget``, not an arbitrary object) and connects three of
    its signals. Nothing else about the real editor is exercised by these tests.
    """

    analyze_requested = pyqtSignal(str)
    toggle_active_requested = pyqtSignal(str)
    epg_refresh_requested = pyqtSignal(str)


def _make_sources_section(tmp_path) -> SourcesSection:
    """Construct a real ``SourcesSection`` against a real file-backed DB.

    ``db`` is never queried by ``__init__`` (only ``refresh()`` touches it, and
    these tests never call ``refresh()``), but the project convention is a real
    ``Database`` on a ``tmp_path`` file rather than a mock.
    """
    db = Database(f"sqlite:///{tmp_path}/sources_visibility.db")
    config = Config()
    return SourcesSection(config, db)


def _strip_add_btn(section: SourcesSection) -> QPushButton:
    """Return the Add-Source button built by ``SourcesSection.create_header()``.

    ``main_layout`` item 0 is the header built once during ``__init__``; its layout
    is: toggle_btn, title_label, stretch, refresh_all_btn, add_btn (last item).
    """
    header_layout = section.main_layout.itemAt(0).widget().layout()
    btn = header_layout.itemAt(header_layout.count() - 1).widget()
    assert isinstance(btn, QPushButton)
    return btn


def _make_sources_manager(tmp_path) -> SourcesManagerView:
    """Construct a real ``SourcesManagerView`` with a real DB/config and the
    minimal ``_FakeProviderEditor`` stand-in."""
    db = Database(f"sqlite:///{tmp_path}/sources_manager_visibility.db")
    config = Config()
    return SourcesManagerView(config, db, _FakeProviderEditor())


# ---------------------------------------------------------------------------
# Sources strip (sidebar) button
# ---------------------------------------------------------------------------

def test_sources_strip_button_size(qapp, tmp_path):
    """Strip button must be at least 28×24 pixels (was 22×20)."""
    section = _make_sources_section(tmp_path)
    add_btn = _strip_add_btn(section)
    section.show()
    QApplication.processEvents()

    size = add_btn.size()
    assert size.width() >= 28, f"Button width {size.width()} < 28"
    assert size.height() >= 24, f"Button height {size.height()} < 24"


def test_sources_strip_button_foreground_not_dim(qapp, tmp_path):
    """Strip button foreground must NOT be COLOR_DIM (the bug was dimming)."""
    section = _make_sources_section(tmp_path)
    add_btn = _strip_add_btn(section)

    stylesheet = add_btn.styleSheet()

    # The new stylesheet uses COLOR_TEXT, not COLOR_DIM.
    assert _theme.COLOR_TEXT in stylesheet, (
        f"Button should use COLOR_TEXT for visibility; got stylesheet: {stylesheet}"
    )
    assert _theme.COLOR_DIM not in stylesheet, (
        f"Button should NOT use COLOR_DIM (the dimming was the bug); got stylesheet: {stylesheet}"
    )


def test_sources_strip_button_has_border(qapp, tmp_path):
    """Strip button must have a visible border."""
    section = _make_sources_section(tmp_path)
    add_btn = _strip_add_btn(section)

    stylesheet = add_btn.styleSheet()

    assert "border:" in stylesheet or "border-" in stylesheet, (
        f"Button should have a border; got stylesheet: {stylesheet}"
    )


def test_sources_strip_button_connects_to_signal(qapp, tmp_path):
    """Strip button click must emit addProviderClicked signal."""
    section = _make_sources_section(tmp_path)
    add_btn = _strip_add_btn(section)

    signal_received = []
    section.addProviderClicked.connect(lambda: signal_received.append(True))
    add_btn.click()

    assert signal_received, "Clicking the Add-Source button should fire addProviderClicked"


# ---------------------------------------------------------------------------
# Sources manager view button
# ---------------------------------------------------------------------------

def test_sources_manager_button_has_text(qapp, tmp_path):
    """Manager button must have text "Add Source" (was just "+")."""
    manager = _make_sources_manager(tmp_path)

    assert "Add Source" in manager._add_btn.text(), (
        f"Button text should contain 'Add Source'; got '{manager._add_btn.text()}'"
    )


def test_sources_manager_button_sizes_to_content(qapp, tmp_path):
    """Manager button must size to its label content, not be fixed-size."""
    manager = _make_sources_manager(tmp_path)

    # The button should not have a fixed (small) maximum width.
    assert manager._add_btn.maximumWidth() > 24, (
        "Button should not be fixed to 24px width or less"
    )

    # Check that it has a minimum height instead.
    assert manager._add_btn.minimumHeight() == 24, (
        "Button should have minimumHeight() == 24"
    )


def test_sources_manager_button_wider_than_old_fixed(qapp, tmp_path):
    """Manager button with "Add Source" label must be wider than old 24px fixed width."""
    manager = _make_sources_manager(tmp_path)
    manager.show()

    manager._add_btn.adjustSize()
    QApplication.processEvents()

    assert manager._add_btn.width() > 24, (
        f"Button width {manager._add_btn.width()} should be > 24px"
    )


def test_sources_manager_button_connects_to_signal(qapp, tmp_path):
    """Manager button click must emit addProviderClicked signal."""
    manager = _make_sources_manager(tmp_path)

    signal_received = []
    manager.addProviderClicked.connect(lambda: signal_received.append(True))
    manager._add_btn.click()

    assert signal_received, "Clicking the Add-Source button should fire addProviderClicked"


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
