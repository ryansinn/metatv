"""Every collapse/expand caret comes from ``icons.py``, and says what it opens.

This started as a characterization test for P1-3: the carets had been hardcoded
'▶'/'▼' literals and were moved onto ``config.expand_icon``/``collapse_icon``.
``Config`` was the wrong home — CLAUDE.md: "Every icon/emoji/symbol comes from
``icons.py`` ... Never add glyphs to ``Config`` (settings, not presentation
constants)" — so the sites moved again, to ``icons.expand_icon`` /
``icons.collapse_icon``, and this file guards the destination rather than the
waypoint. A ``config`` whose glyphs are deliberately unusual is still passed in:
if a widget were still reading them, these assertions would see the odd values
instead of the real carets.

Where the caret sits on a BUTTON it is a real ``QIcon`` now, never button text
(ICON-1: a colour emoji drawn as text at the host font size crops inside a
fixed-size button), so those assertions read the rendered pixel bytes — "the
icon exists and repaints differently on toggle" — rather than a text value. The
caret that sits on a ``QLabel`` (``global_filter_dialog``) is still text, and is
still asserted as text.

The second half is the affordance the carets never had. A caret alone says
"something folds here" and not WHAT — so every toggle carries hover text that
names its section and flips with the state.

Uses pytest-qt (qtbot) for widget instantiation.
"""

from unittest.mock import MagicMock

from metatv.gui import icons as _icons


_EXPAND = _icons.expand_icon
_COLLAPSE = _icons.collapse_icon
_NOT_THE_ICONS = "CONFIG_GLYPH_THAT_MUST_NOT_APPEAR"


def _mock_config():
    """A config whose caret glyphs would be obvious if anything still read them."""
    c = MagicMock()
    c.expand_icon = _NOT_THE_ICONS
    c.collapse_icon = _NOT_THE_ICONS
    return c


def _icon_bytes(btn) -> bytes:
    """Raw pixel bytes of *btn*'s current icon, for "did it actually repaint"."""
    image = btn.icon().pixmap(btn.iconSize()).toImage()
    return image.bits().asstring(image.sizeInBytes())


# ---------------------------------------------------------------------------
# filter_group_row._GroupRow
# ---------------------------------------------------------------------------

def test_group_row_initial_shows_expand_icon(qtbot):
    from metatv.gui.filter_group_row import _GroupRow
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=_mock_config())
    qtbot.addWidget(widget)
    assert not widget._expand_btn.icon().isNull()
    assert widget._expand_btn.text() == ""
    assert widget._expand_btn.toolTip() == "Expand Group"


def test_group_row_toggle_shows_collapse_icon(qtbot):
    from metatv.gui.filter_group_row import _GroupRow
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=_mock_config())
    qtbot.addWidget(widget)
    before = _icon_bytes(widget._expand_btn)
    widget._toggle_expand()
    assert _icon_bytes(widget._expand_btn) != before, (
        "the icon must repaint on toggle, not just the tooltip"
    )
    assert widget._expand_btn.toolTip() == "Collapse Group"


def test_group_row_double_toggle_returns_expand_icon(qtbot):
    from metatv.gui.filter_group_row import _GroupRow
    widget = _GroupRow("Group", 3, [("a", "A", 1)], config=_mock_config())
    qtbot.addWidget(widget)
    original = _icon_bytes(widget._expand_btn)
    widget._toggle_expand()
    widget._toggle_expand()
    assert _icon_bytes(widget._expand_btn) == original
    assert widget._expand_btn.toolTip() == "Expand Group"


def test_group_row_tooltip_names_the_group_and_follows_the_state(qtbot):
    """"Show the codes in this group" was on every one of them at once."""
    from metatv.gui.filter_group_row import _GroupRow
    widget = _GroupRow("Nordic", 3, [("a", "A", 1)], config=_mock_config())
    qtbot.addWidget(widget)
    assert widget._expand_btn.toolTip() == "Expand Nordic"
    widget._toggle_expand()
    assert widget._expand_btn.toolTip() == "Collapse Nordic"


# ---------------------------------------------------------------------------
# filter_group_row._Section
# ---------------------------------------------------------------------------

def test_section_initially_collapsed_shows_expand_icon(qtbot):
    from metatv.gui.filter_group_row import _Section
    widget = _Section("media", "Media Types", config=_mock_config(),
                      initially_expanded=False)
    qtbot.addWidget(widget)
    assert not widget._collapse_btn.icon().isNull()
    assert widget._collapse_btn.text() == ""
    assert widget._collapse_btn.toolTip() == "Expand Media Types"


def test_section_initially_expanded_shows_collapse_icon(qtbot):
    from metatv.gui.filter_group_row import _Section
    widget = _Section("media", "Media Types", config=_mock_config(),
                      initially_expanded=True)
    qtbot.addWidget(widget)
    assert not widget._collapse_btn.icon().isNull()
    assert widget._collapse_btn.toolTip() == "Collapse Media Types"


def test_section_set_expanded_updates_icon(qtbot):
    from metatv.gui.filter_group_row import _Section
    widget = _Section("media", "Media Types", config=_mock_config(),
                      initially_expanded=False)
    qtbot.addWidget(widget)
    collapsed_bytes = _icon_bytes(widget._collapse_btn)
    widget.set_expanded(True)
    expanded_bytes = _icon_bytes(widget._collapse_btn)
    assert expanded_bytes != collapsed_bytes
    assert widget._collapse_btn.toolTip() == "Collapse Media Types"
    widget.set_expanded(False)
    assert _icon_bytes(widget._collapse_btn) == collapsed_bytes
    assert widget._collapse_btn.toolTip() == "Expand Media Types"


def test_section_tooltip_names_the_section_on_the_button_and_the_header(qtbot):
    """The header row is the wider click target and had no hover text at all."""
    from metatv.gui.filter_group_row import _Section
    widget = _Section("media", "Media Types", config=_mock_config(),
                      initially_expanded=False)
    qtbot.addWidget(widget)
    assert widget._collapse_btn.toolTip() == "Expand Media Types"
    assert widget._header.toolTip() == "Expand Media Types"
    widget.set_expanded(True)
    assert widget._collapse_btn.toolTip() == "Collapse Media Types"
    assert widget._header.toolTip() == "Collapse Media Types"


# ---------------------------------------------------------------------------
# global_filter_dialog._GroupSection
# ---------------------------------------------------------------------------

def test_group_section_initial_shows_expand_icon(qtbot):
    from metatv.gui.global_filter_dialog import _GroupSection
    widget = _GroupSection("EN", [], set(), config=_mock_config())
    qtbot.addWidget(widget)
    assert widget._expand_lbl.text() == _EXPAND


def test_group_section_toggle_shows_collapse_icon(qtbot):
    from metatv.gui.global_filter_dialog import _GroupSection
    widget = _GroupSection("EN", [], set(), config=_mock_config())
    qtbot.addWidget(widget)
    widget._toggle_expand()
    assert widget._expand_lbl.text() == _COLLAPSE


def test_group_section_header_tooltip_names_the_group(qtbot):
    """The caret here is a 12px QLabel; the whole header row is what you click,
    and it carried no hover text saying what the click does."""
    from metatv.gui.global_filter_dialog import _GroupSection
    widget = _GroupSection("EN", [], set(), config=_mock_config())
    qtbot.addWidget(widget)
    assert widget._header.toolTip() == "Expand EN"
    widget._toggle_expand()
    assert widget._header.toolTip() == "Collapse EN"


# ---------------------------------------------------------------------------
# details_section_header.CollapsibleHeader — the details pane's one header
# ---------------------------------------------------------------------------

def test_collapsible_header_tooltip_names_the_section(qtbot):
    """"Expand this section" is true of all seven and identifies none."""
    from metatv.gui.details_section_header import CollapsibleHeader
    header = CollapsibleHeader("Plot", collapsed=True)
    qtbot.addWidget(header)
    assert header._chevron.toolTip() == "Expand Plot"
    assert header._title.toolTip() == "Expand Plot"
    header.toggle()
    assert header._chevron.toolTip() == "Collapse Plot"


def test_collapsible_header_hint_explains_a_bucket_the_name_does_not(qtbot):
    from metatv.gui.details_section_header import CollapsibleHeader
    header = CollapsibleHeader("OFFLINE SOURCES", collapsed=True,
                               hint="variants on a source you have turned off")
    qtbot.addWidget(header)
    assert header._chevron.toolTip() == (
        "Expand OFFLINE SOURCES — variants on a source you have turned off")


def test_collapsible_header_tooltip_follows_a_rename(qtbot):
    """The tooltip is built from the title, so it has to be rebuilt with it."""
    from metatv.gui.details_section_header import CollapsibleHeader
    header = CollapsibleHeader("Cast", collapsed=True)
    qtbot.addWidget(header)
    header.set_title("Cast & Crew")
    assert header._chevron.toolTip() == "Expand Cast & Crew"


# ---------------------------------------------------------------------------
# The channel-list section band paints its caret from icons.py too
# ---------------------------------------------------------------------------

def test_section_band_carets_come_from_icons():
    """Two bare glyph literals sat here, invisible to any grep for the names.

    The band PAINTS its caret with ``QPainter.drawText`` — no ``QIcon`` — and
    its small triangles are deliberately their own shape, so ``icons.py`` names
    that pair rather than folding it into the chevrons the buttons carry.
    """
    from metatv.gui import channel_list_section_band as band
    assert band.CARET_OPEN == _icons.search_band_caret_open_icon
    assert band.CARET_SHUT == _icons.search_band_caret_shut_icon
