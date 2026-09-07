"""Behavioral tests for Add Source button visibility fix.

The "Add Source" (+) button was tiny icon-only (+) fixed to 24×22 on the
Sources manager view — the only surface that carries it today.

This test verifies the fix:
- Manager button: text "Add Source", sizes to content (min-height 24), wider than old fixed width

Icon registry enforcement (owner-mandated rule):
- All "+" glyphs route through icons.add_icon, never hardcoded literals in widget code.

Harness notes:
- ``SourcesManagerView`` only stores ``config``/``db`` (never queries them) and embeds
  ``provider_editor`` via ``addWidget()``, which requires a real ``QWidget`` — so the
  stand-in below is a trivial ``QWidget`` subclass carrying just the three signals
  ``__init__`` connects (``analyze_requested``/``toggle_active_requested``/
  ``epg_refresh_requested``), not a hand-rolled non-widget fake.
- Gets a real ``Config()`` (all icon attributes are real defaults — no need for a
  fake config that can drift out of sync with what the widget reads) and a real
  file-backed ``Database`` per the project's tmp_path convention (never
  ``:memory:``), even though the constructor path doesn't touch it.

Former "Sources strip (sidebar)" coverage removed (audit slice 4, 2026-09-07):
those four tests exercised ``SourcesSection``'s add button, a dead class never
instantiated in production and deleted in this slice. The live sidebar strip
(``SourcesStatusStrip``) carries no add button at all — only a summary label
and Refresh All; the Add Source affordance lives solely on
``SourcesManagerView``, already covered below.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from metatv.core.config import Config
from metatv.core.database import Database
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


def _make_sources_manager(tmp_path) -> SourcesManagerView:
    """Construct a real ``SourcesManagerView`` with a real DB/config and the
    minimal ``_FakeProviderEditor`` stand-in."""
    db = Database(f"sqlite:///{tmp_path}/sources_manager_visibility.db")
    config = Config()
    return SourcesManagerView(config, db, _FakeProviderEditor())


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

    # Check that it has a minimum height instead. Asserted as a FLOOR, not an
    # exact px: the specific value is a design detail that has already moved
    # once (24 -> 28 when the CTA was restyled, #266), and pinning it makes a
    # deliberate improvement look like a regression.
    assert manager._add_btn.minimumHeight() >= 24, (
        "Button should have a minimum height of at least 24px"
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


# ---------------------------------------------------------------------------
# Rendered appearance — the owner reported the CTA still read as disabled
# ---------------------------------------------------------------------------

def test_add_source_cta_is_a_filled_accent_button_not_a_ghost(tmp_path):
    """The button must render as a solid, legible button — not faint text.

    Owner report (2026-08-03, with a screenshot): "+ Add Source is still not
    very visible". It was styled with ``RECIPE_SAVED_ICON_BTN``, whose role is a
    de-emphasised icon button — ``background: transparent`` plus ``COLOR_FAINT``
    text. Correct for a small delete glyph on a card; for the one control a
    person with zero sources has to find, it rendered as dim grey text with no
    button shape.

    Asserts the RENDERED style, not merely that some token was referenced: a
    fill that is present but transparent, or a foreground that is technically a
    token but still ``COLOR_FAINT``, both pass a token-existence check and still
    look broken.
    """
    from metatv.gui import theme as _theme
    from tests.test_palette_completeness import _contrast

    manager = _make_sources_manager(tmp_path)
    qss = manager._add_btn.styleSheet()

    assert "transparent" not in qss, (
        f"Add Source CTA still has a transparent background — it reads as a "
        f"label, not a button: {qss!r}"
    )
    assert _theme.COLOR_FAINT not in qss, (
        f"Add Source CTA still uses the faint/de-emphasised text token: {qss!r}"
    )
    assert _theme.COLOR_ACCENT in qss, (
        f"Add Source CTA should be filled with the accent: {qss!r}"
    )

    # Text on a solid accent fill takes the on-accent token, and must clear the
    # readability floor — the same rule the selection highlight needed (#265).
    assert _theme.COLOR_ON_ACCENT in qss, (
        f"Add Source CTA draws on a solid accent fill, so its foreground must "
        f"be COLOR_ON_ACCENT rather than the on-background text ramp: {qss!r}"
    )
    ratio = _contrast(_theme.COLOR_ON_ACCENT, _theme.COLOR_ACCENT)
    assert ratio >= 4.5, (
        f"Add Source CTA label contrast is {ratio:.2f}:1 against its own fill, "
        f"below the 4.5:1 minimum"
    )
