"""Rendered-appearance tests for ``metatv.gui.detail_chips`` (DETAILS-3a).

Per CLAUDE.md's "UI slices must assert rendered appearance" rule, these check
the EFFECTIVE stylesheet/geometry Qt actually applies — never just that a
token or a code path exists. Covers:

* :func:`chip_sheet` / :func:`make_chip` — dashed vs solid border, the
  selected state's accent border + bold weight, and that its geometry
  (radius/padding/font-size) is the SAME fragment ``DETAIL_REGION_CHIP``
  composes from (``tokens/detail_roles.chip_geometry`` — the shared-geometry
  fix from the reuse-check correction, not a second chip shape).
* :func:`add_quality_badge` — splits a trailing quality token into the app's
  ONE quality chip (``chip_row.chip_widget(chip_row.CHIP_QUALITY, ...)``,
  verified against ``chip_row.quality_chip_style`` byte-for-byte), leaves a
  chip with no quality token untouched.
* :func:`make_key` / :func:`make_label_grid` — geometry only (fixed height
  matching a chip, the one key-column width).
* :func:`display_code` — the resolved "Full (CODE)" display form.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from metatv.gui import theme
from metatv.gui.badge_utils import quality_outline_color
from metatv.gui.chip_row import CHIP_QUALITY, quality_chip_style
from metatv.gui.detail_chips import (
    KEY_COL,
    SECTION_INDENT,
    add_quality_badge,
    chip_sheet,
    display_code,
    make_chip,
    make_flow,
    make_key,
    make_label_grid,
)
from metatv.gui.tokens.detail_roles import chip_geometry


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# chip_sheet / make_chip
# ---------------------------------------------------------------------------

def test_dashed_chip_sheet_is_dashed(qapp):
    sheet = chip_sheet("COLOR_TEXT", dashed=True)
    assert "dashed" in sheet
    assert "solid" not in sheet


def test_plain_chip_sheet_is_solid(qapp):
    sheet = chip_sheet("COLOR_TEXT", dashed=False)
    assert "solid" in sheet
    assert "dashed" not in sheet


def test_selected_chip_uses_accent_border_and_bold(qapp):
    sheet = chip_sheet("COLOR_TEXT", selected=True, bold=True)
    assert theme.COLOR_ACCENT in sheet
    assert "font-weight: bold" in sheet
    assert theme.COLOR_BG_CARD in sheet  # selected fills with the card colour


def test_unselected_chip_does_not_use_accent_border():
    sheet = chip_sheet("COLOR_TEXT", selected=False)
    # The border colour is COLOR_BORDER, not COLOR_ACCENT, when not selected
    # (COLOR_ACCENT still appears in the :hover rule, so check the border line).
    border_line = next(line for line in sheet.split(";") if "border:" in line)
    assert theme.COLOR_BORDER in border_line
    assert theme.COLOR_ACCENT not in border_line


def test_make_chip_effective_stylesheet_matches_chip_sheet(qapp):
    btn = make_chip("English (EN)", "COLOR_TEXT_HI", dashed=True, bold=True)
    assert btn.styleSheet() == chip_sheet("COLOR_TEXT_HI", dashed=True, bold=True)
    assert btn.text() == "English (EN)"


def test_make_chip_escapes_ampersand(qapp):
    btn = make_chip("Action & Adventure")
    assert btn.text() == "Action && Adventure"


def test_chip_sheet_shares_geometry_with_detail_region_chip(qapp):
    """The chip toolkit and ``DETAIL_REGION_CHIP`` must not carry two copies
    of one chip's metrics — both compose from the same
    ``detail_roles.chip_geometry`` fragment."""
    geometry = chip_geometry(theme.FONT_MD, theme.RADIUS_SM)
    assert geometry in chip_sheet("COLOR_TEXT")
    assert geometry in theme.DETAIL_REGION_CHIP


# ---------------------------------------------------------------------------
# add_quality_badge
# ---------------------------------------------------------------------------

def test_add_quality_badge_splits_trailing_quality_token(qapp):
    chip = make_chip("English (EN) 4K")
    result = add_quality_badge(chip, "COLOR_TEXT")
    assert result is chip

    labels = chip.findChildren(QLabel)
    assert any(label.text() == "English (EN)" for label in labels)

    # The badge is the app's ONE quality chip (chip_row.chip_widget), not a
    # hand-rolled QLabel — a nested QPushButton, found among chip's children.
    badges = [w for w in chip.findChildren(QPushButton) if w is not chip]
    assert len(badges) == 1
    badge = badges[0]
    assert badge.text() == "4K"
    # Byte-identical to the sidebar's own quality chip sheet — the ONE
    # quality-chip look, not a second ring-style sheet.
    assert badge.styleSheet() == quality_chip_style("4K")
    assert quality_outline_color("4K") in badge.styleSheet()


def test_add_quality_badge_with_count(qapp):
    chip = make_chip("Spain (ES) HD ×3")
    add_quality_badge(chip, "COLOR_TEXT")
    labels = chip.findChildren(QLabel)
    assert any(label.text() == "Spain (ES)" for label in labels)
    assert any(label.text() == "×3" for label in labels)
    badges = [w for w in chip.findChildren(QPushButton) if w is not chip]
    assert len(badges) == 1
    assert badges[0].text() == "HD"


def test_add_quality_badge_no_quality_token_returned_unchanged(qapp):
    chip = make_chip("Spain (ES) ×3")
    original_text = chip.text()
    result = add_quality_badge(chip, "COLOR_TEXT")
    assert result is chip
    assert chip.text() == original_text
    assert chip.layout() is None
    assert chip.findChildren(QPushButton) == []


# ---------------------------------------------------------------------------
# make_key / make_flow / make_label_grid
# ---------------------------------------------------------------------------

def test_make_key_height_matches_chip_height(qapp):
    key = make_key("Available")
    chip = make_chip("x")
    assert key.height() == chip.sizeHint().height()


def test_make_flow_adds_every_widget(qapp):
    a, b = make_chip("a"), make_chip("b")
    flow_widget = make_flow([a, b])
    assert flow_widget.layout().count() == 2


def test_make_label_grid_key_column_width(qapp):
    _widget, grid = make_label_grid()
    assert grid.columnMinimumWidth(0) == 92
    assert KEY_COL == 92


def test_make_label_grid_custom_key_column_width(qapp):
    _widget, grid = make_label_grid(key_col=KEY_COL - SECTION_INDENT)
    assert grid.columnMinimumWidth(0) == KEY_COL - SECTION_INDENT


# ---------------------------------------------------------------------------
# display_code
# ---------------------------------------------------------------------------

def test_display_code_known_region():
    assert display_code("SE") == "Sweden (SE)"


def test_display_code_unknown_code_returns_bare():
    assert display_code("ZZZZ-NOT-A-CODE") == "ZZZZ-NOT-A-CODE"
