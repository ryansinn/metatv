"""Characterization test for filter_group_row's expand/collapse buttons.

Was P1-3 ("icons must come from Config"): ``config.expand_icon``/
``config.collapse_icon`` reads have since been retired (ICON-1 — migration
debt per CLAUDE.md's "Migration Status": ``config.<name>_icon`` -> ``icons.*``)
in favour of the shared ``icon_utils`` factory (``icons.VECTOR_KEYS``
"expand"/"collapse"). These buttons render a ``QIcon`` now, never text, so the
guard is "the icon exists and repaints differently on toggle" plus the
tooltip — not a text value read from a mocked config.

Uses pytest-qt (qtbot) for widget instantiation.
"""

from unittest.mock import MagicMock


def _mock_config():
    c = MagicMock()
    # _GroupRow/_Section (filter_group_row.py) no longer read these — they go
    # through icon_utils/icons.VECTOR_KEYS. global_filter_dialog._GroupSection
    # (below) is untouched by ICON-1 and still needs real strings here.
    c.expand_icon = ">"
    c.collapse_icon = "⌄"
    return c


def _icon_bytes(btn) -> bytes:
    """Raw pixel bytes of *btn*'s current icon, for "did it actually repaint"."""
    image = btn.icon().pixmap(btn.iconSize()).toImage()
    return image.bits().asstring(image.sizeInBytes())


# ---------------------------------------------------------------------------
# filter_panel._GroupRow
# ---------------------------------------------------------------------------

def test_group_row_initial_shows_expand_icon(qtbot):
    from metatv.gui.filter_group_row import _GroupRow
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=_mock_config())
    qtbot.addWidget(widget)
    assert not widget._expand_btn.icon().isNull()
    assert widget._expand_btn.text() == ""
    assert widget._expand_btn.toolTip() == "Show the codes in this group"


def test_group_row_toggle_shows_collapse_icon(qtbot):
    from metatv.gui.filter_group_row import _GroupRow
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=_mock_config())
    qtbot.addWidget(widget)
    before = _icon_bytes(widget._expand_btn)
    widget._toggle_expand()
    assert _icon_bytes(widget._expand_btn) != before, (
        "the icon must repaint on toggle, not just the tooltip"
    )
    assert widget._expand_btn.toolTip() == "Hide the codes in this group"


def test_group_row_double_toggle_returns_expand_icon(qtbot):
    from metatv.gui.filter_group_row import _GroupRow
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=_mock_config())
    qtbot.addWidget(widget)
    original = _icon_bytes(widget._expand_btn)
    widget._toggle_expand()
    widget._toggle_expand()
    assert _icon_bytes(widget._expand_btn) == original
    assert widget._expand_btn.toolTip() == "Show the codes in this group"


# ---------------------------------------------------------------------------
# filter_panel._Section
# ---------------------------------------------------------------------------

def test_section_initially_collapsed_shows_expand_icon(qtbot):
    from metatv.gui.filter_group_row import _Section
    widget = _Section("media", "Media Types", config=_mock_config(), initially_expanded=False)
    qtbot.addWidget(widget)
    assert not widget._collapse_btn.icon().isNull()
    assert widget._collapse_btn.toolTip() == "Expand this section"


def test_section_initially_expanded_shows_collapse_icon(qtbot):
    from metatv.gui.filter_group_row import _Section
    widget = _Section("media", "Media Types", config=_mock_config(), initially_expanded=True)
    qtbot.addWidget(widget)
    assert not widget._collapse_btn.icon().isNull()
    assert widget._collapse_btn.toolTip() == "Collapse this section"


def test_section_set_expanded_updates_icon(qtbot):
    from metatv.gui.filter_group_row import _Section
    widget = _Section("media", "Media Types", config=_mock_config(), initially_expanded=False)
    qtbot.addWidget(widget)
    collapsed_bytes = _icon_bytes(widget._collapse_btn)
    widget.set_expanded(True)
    expanded_bytes = _icon_bytes(widget._collapse_btn)
    assert expanded_bytes != collapsed_bytes
    assert widget._collapse_btn.toolTip() == "Collapse this section"
    widget.set_expanded(False)
    assert _icon_bytes(widget._collapse_btn) == collapsed_bytes
    assert widget._collapse_btn.toolTip() == "Expand this section"


# ---------------------------------------------------------------------------
# global_filter_dialog._GroupSection
# ---------------------------------------------------------------------------

def test_group_section_initial_shows_expand_icon(qtbot):
    from metatv.gui.global_filter_dialog import _GroupSection
    cfg = _mock_config()
    widget = _GroupSection("EN", [], set(), config=cfg)
    qtbot.addWidget(widget)
    assert widget._expand_lbl.text() == ">"


def test_group_section_toggle_shows_collapse_icon(qtbot):
    from metatv.gui.global_filter_dialog import _GroupSection
    cfg = _mock_config()
    widget = _GroupSection("EN", [], set(), config=cfg)
    qtbot.addWidget(widget)
    widget._toggle_expand()
    assert widget._expand_lbl.text() == "⌄"
