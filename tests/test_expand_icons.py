"""Characterization test for P1-3: expand/collapse icons must come from Config.

T1-3 from REFACTOR_PLAN. Guards that filter_panel and global_filter_dialog use
config.expand_icon (collapsed) and config.collapse_icon (expanded) instead of
hardcoded '▶'/'▼' literals.

Uses pytest-qt (qtbot) for widget instantiation. Config is mocked with
deliberately unusual values so tests distinguish "came from config" vs "hardcoded".
"""

import pytest
from unittest.mock import MagicMock


_EXPAND  = "EXPAND_TEST"   # unusual value — can't be a hardcoded literal
_COLLAPSE = "COLLAPSE_TEST"


def _mock_config():
    c = MagicMock()
    c.expand_icon   = _EXPAND
    c.collapse_icon = _COLLAPSE
    return c


# ---------------------------------------------------------------------------
# filter_panel._GroupRow
# ---------------------------------------------------------------------------

def test_group_row_initial_shows_expand_icon(qtbot):
    from metatv.gui.filter_panel import _GroupRow
    cfg = _mock_config()
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=cfg)
    qtbot.addWidget(widget)
    assert widget._expand_btn.text() == _EXPAND, (
        f"Expected expand_icon '{_EXPAND}' when collapsed, got '{widget._expand_btn.text()}'"
    )


def test_group_row_toggle_shows_collapse_icon(qtbot):
    from metatv.gui.filter_panel import _GroupRow
    cfg = _mock_config()
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=cfg)
    qtbot.addWidget(widget)
    widget._toggle_expand()
    assert widget._expand_btn.text() == _COLLAPSE, (
        f"Expected collapse_icon '{_COLLAPSE}' when expanded, got '{widget._expand_btn.text()}'"
    )


def test_group_row_double_toggle_returns_expand_icon(qtbot):
    from metatv.gui.filter_panel import _GroupRow
    cfg = _mock_config()
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=cfg)
    qtbot.addWidget(widget)
    widget._toggle_expand()
    widget._toggle_expand()
    assert widget._expand_btn.text() == _EXPAND


# ---------------------------------------------------------------------------
# filter_panel._Section
# ---------------------------------------------------------------------------

def test_section_initially_collapsed_shows_expand_icon(qtbot):
    from metatv.gui.filter_panel import _Section
    cfg = _mock_config()
    widget = _Section("media", "Media Types", config=cfg, initially_expanded=False)
    qtbot.addWidget(widget)
    assert widget._collapse_btn.text() == _EXPAND


def test_section_initially_expanded_shows_collapse_icon(qtbot):
    from metatv.gui.filter_panel import _Section
    cfg = _mock_config()
    widget = _Section("media", "Media Types", config=cfg, initially_expanded=True)
    qtbot.addWidget(widget)
    assert widget._collapse_btn.text() == _COLLAPSE


def test_section_set_expanded_updates_icon(qtbot):
    from metatv.gui.filter_panel import _Section
    cfg = _mock_config()
    widget = _Section("media", "Media Types", config=cfg, initially_expanded=False)
    qtbot.addWidget(widget)
    widget.set_expanded(True)
    assert widget._collapse_btn.text() == _COLLAPSE
    widget.set_expanded(False)
    assert widget._collapse_btn.text() == _EXPAND


# ---------------------------------------------------------------------------
# global_filter_dialog._GroupSection
# ---------------------------------------------------------------------------

def test_group_section_initial_shows_expand_icon(qtbot):
    from metatv.gui.global_filter_dialog import _GroupSection
    cfg = _mock_config()
    widget = _GroupSection("EN", [], set(), config=cfg)
    qtbot.addWidget(widget)
    assert widget._expand_lbl.text() == _EXPAND


def test_group_section_toggle_shows_collapse_icon(qtbot):
    from metatv.gui.global_filter_dialog import _GroupSection
    cfg = _mock_config()
    widget = _GroupSection("EN", [], set(), config=cfg)
    qtbot.addWidget(widget)
    widget._toggle_expand()
    assert widget._expand_lbl.text() == _COLLAPSE
