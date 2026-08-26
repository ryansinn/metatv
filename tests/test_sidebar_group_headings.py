"""One group-heading grammar across Watch Alerts.

The defect: that section drew sub-group headings THREE different ways — styled
tree items for the EPG groups, em-dash divider rows in the VOD list, and those
two divider rows behaving differently despite looking identical (the Series one
collapsed on click; the "Watching for" one was ``NoItemFlags`` and inert).
"""

from PyQt6.QtCore import Qt, QEvent, QPointF
from PyQt6.QtGui import QMouseEvent

from metatv.core.config import Config
from metatv.gui import theme as _theme
from metatv.gui.sidebar.base import GroupHeading


def _click(widget) -> None:
    widget.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(4, 4), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))


# ── rendered appearance ─────────────────────────────────────────────────
def test_the_count_is_rendered_with_more_emphasis_than_the_label(qapp):
    """The label is the constant, the count is the variable.

    Asserts the RENDERED type, not that two roles exist: a heading whose count
    matched its label would satisfy any token-existence check while looking
    exactly like the plain-inline version this replaced, where the digit read
    as part of the label.
    """
    _theme.apply_theme("Midnight")
    heading = GroupHeading("Series", 10)

    label_px = heading.label.fontMetrics().height()
    count_px = heading.count_label.fontMetrics().height()
    assert count_px > label_px, (
        f"the count must be visibly larger than its label "
        f"(count {count_px}px vs label {label_px}px)"
    )
    assert heading.count_label.font().bold() or "bold" in heading.count_label.styleSheet()

    # ...and brighter. COLOR_TEXT_HI on COLOR_MUTED, read off the applied sheets.
    assert _theme.COLOR_TEXT_HI in heading.count_label.styleSheet()
    assert _theme.COLOR_MUTED in heading.label.styleSheet()


def test_the_label_renders_uppercase_without_changing_its_text(qapp):
    """Capitalisation is a FONT property, so the string stays readable to code."""
    heading = GroupHeading("Watching for", 4)
    assert heading.label.text() == "Watching for"
    assert heading.label.font().capitalization().name == "AllUppercase"


def test_a_count_of_none_renders_nothing(qapp):
    heading = GroupHeading("Series")
    assert heading.count_label.text() == ""
    assert not heading.count_label.isVisibleTo(heading)


def test_the_count_shows_even_at_zero(qapp):
    """0 is a fact about the group; blank is the absence of one."""
    heading = GroupHeading("Series", 0)
    assert heading.count_label.text().strip() == "0"


# ── the interaction that used to differ ─────────────────────────────────
def test_an_interactive_heading_emits_and_carries_the_hand_cursor(qapp):
    heading = GroupHeading("Series", 10, interactive=True)
    fired = []
    heading.clicked.connect(lambda: fired.append(1))
    _click(heading)
    assert fired, "an interactive heading did not emit clicked"
    assert heading.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert heading.toolTip(), "an interactive heading must say it is clickable"


def test_a_non_interactive_heading_stays_silent(qapp):
    heading = GroupHeading("Watch now", 6)
    fired = []
    heading.clicked.connect(lambda: fired.append(1))
    _click(heading)
    assert not fired


# ── the section wires all four the same way ─────────────────────────────
def test_both_vod_group_headings_collapse(qapp, tmp_path):
    """The old bug, directly: two identical-looking dividers, one inert.

    "Watching for" was NoItemFlags and did nothing; "Series" collapsed. Both
    now toggle, and the section holds a collapse flag for each.
    """
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    assert section._series_collapsed is False
    assert section._keyword_collapsed is False

    section._toggle_series_group()
    assert section._series_collapsed is True
    section._toggle_keyword_group()
    assert section._keyword_collapsed is True

    section._toggle_series_group()
    assert section._series_collapsed is False


def test_heading_items_are_chrome_not_content(qapp, tmp_path):
    """A heading must never be selectable, and the row budget must skip it.

    ``row_budget`` treats anything whose ``flags()`` are not ``NoItemFlags`` as
    content, so a selectable heading would eat a row of a section's allowance
    and could be the row a "+N more" tail lands on.
    """
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    section._add_group_heading("Series", 10, on_click=lambda: None)

    item = section._vod_list.item(section._vod_list.count() - 1)
    assert item.flags() == Qt.ItemFlag.NoItemFlags, (
        "a heading must not be selectable even when it is clickable — the click "
        "belongs to its widget, not to the item"
    )
    widget = section._vod_list.itemWidget(item)
    assert isinstance(widget, GroupHeading)


def test_every_group_heading_is_the_same_widget(qapp, tmp_path):
    """Three mechanisms became one; nothing may quietly grow a fourth."""
    import inspect

    from metatv.gui.sidebar import alerts as mod

    src = inspect.getsource(mod)
    # The two literal divider strings this replaced. Matched exactly rather than
    # by a bare em-dash run, which the file's own comment separators contain.
    for gone in ('"──── Watching for ────"', '──── Series ('):
        assert gone not in src, (
            f"an em-dash divider row is back ({gone!r}) — headings go through "
            f"GroupHeading"
        )
    assert "style_group_heading" not in src, (
        "Watch Alerts is styling heading ITEMS again; that cannot render a "
        "muted label beside a bright count"
    )
