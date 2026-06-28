"""Behavioral tests for WeightedTagCloud widget.

Tests pin the concrete behaviors that would break on regression:
- Correct number of tag buttons rendered (with cap)
- Log-bucketed font sizing: higher count → larger token
- Sort toggle changes displayed order
- Filter hides non-matching tags
- "+N more" cap expands to reveal all tags
- Clicking a tag emits tag_clicked with the value
- State marks: include shows ✓, exclude shows ⊘
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.weighted_tag_cloud import WeightedTagCloud, _count_to_font_token, _fmt_count


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ── unit tests for pure helpers ───────────────────────────────────────────────────

def test_fmt_count_compact():
    assert _fmt_count(240)    == "240"
    assert _fmt_count(1100)   == "1.1k"
    assert _fmt_count(2000)   == "2k"
    assert _fmt_count(286000) == "286k"
    assert _fmt_count(1_500_000) == "1.5m"


def test_count_to_font_token_flat_distribution():
    """Flat distribution (all equal) → middle tier."""
    token = _count_to_font_token(100, 100, 100)
    assert token in (_theme.FONT_CLOUD_3, _theme.FONT_CLOUD_4)   # middle of 6 tiers


def test_count_to_font_token_min_is_smallest():
    token_low  = _count_to_font_token(1,    1, 10000)
    token_high = _count_to_font_token(10000, 1, 10000)
    # Extract px values to compare numerically
    px_low  = int(token_low.replace("px", ""))
    px_high = int(token_high.replace("px", ""))
    assert px_high > px_low, "Higher count must produce a larger font token"


# ── widget behavioral tests ───────────────────────────────────────────────────────

def _make_items(n: int, state: str = "none") -> list[tuple[str, int, str]]:
    """Generate n dummy tag items with descending counts."""
    return [(f"Tag{i}", (n - i) * 10, state) for i in range(n)]


def test_set_tags_renders_tag_widgets(qapp):
    """After set_tags with 10 items, _tag_buttons contains exactly 10 buttons."""
    cloud = WeightedTagCloud()
    items = _make_items(10)
    cloud.set_tags(items, facet_color=_theme.COLOR_ACCENT_TEAL, facet_name="Genre")
    assert len(cloud._tag_buttons) == 10


def test_set_tags_capped_at_40(qapp):
    """With 60 items, only 40 are logically visible initially; _tag_buttons has all 60.

    Uses cloud_visible (not isVisible()) because headless Qt widgets always
    report isVisible()==False regardless of show()/hide() calls on children.
    """
    cloud = WeightedTagCloud()
    items = _make_items(60)
    cloud.set_tags(items, facet_color=_theme.COLOR_ACCENT_TEAL)
    assert len(cloud._tag_buttons) == 60
    visible = [b for b in cloud._tag_buttons if b.cloud_visible]
    assert len(visible) == 40


def test_higher_count_gets_larger_font_token(qapp):
    """A tag with count=10000 must render at a larger font size than count=10."""
    cloud = WeightedTagCloud()
    cloud.set_tags(
        [("Big", 10000, "none"), ("Small", 10, "none")],
        facet_color=_theme.COLOR_ACCENT,
    )
    big_btn   = cloud._tag_buttons[0]   # Big (sorted by weight: highest first)
    small_btn = cloud._tag_buttons[1]

    # Extract font size from stylesheet
    def _px(btn) -> int:
        ss = btn.styleSheet()
        # Find "font-size: NNpx" in the stylesheet
        import re
        m = re.search(r"font-size:\s*(\d+)px", ss)
        assert m, f"No font-size found in stylesheet: {ss}"
        return int(m.group(1))

    assert _px(big_btn) > _px(small_btn), (
        f"Big tag ({_px(big_btn)}px) should be larger than Small ({_px(small_btn)}px)"
    )


def test_weight_az_toggle_reorders(qapp):
    """Toggling sort from Weight to A-Z changes the order of tag buttons."""
    cloud = WeightedTagCloud()
    items = [
        ("Zebra", 100, "none"),
        ("Apple", 50,  "none"),
        ("Mango", 200, "none"),
    ]
    cloud.set_tags(items, facet_color=_theme.COLOR_ACCENT)

    # Default: weight sort → Mango (200), Zebra (100), Apple (50)
    values_weight = [b.value() for b in cloud._tag_buttons]
    assert values_weight == ["Mango", "Zebra", "Apple"], (
        f"Weight sort order wrong: {values_weight}"
    )

    # After toggle: A-Z → Apple, Mango, Zebra
    cloud._sort_btn.setChecked(True)
    values_az = [b.value() for b in cloud._tag_buttons]
    assert values_az == ["Apple", "Mango", "Zebra"], (
        f"A-Z sort order wrong: {values_az}"
    )


def test_filter_hides_nonmatching(qapp):
    """Setting filter text hides tags that don't match the substring.

    Uses cloud_visible (not isVisible()) because headless Qt widgets always
    report isVisible()==False.
    """
    cloud = WeightedTagCloud()
    items = [
        ("Action", 100, "none"),
        ("Drama",  80,  "none"),
        ("Documentary", 60, "none"),
        ("Comedy", 40, "none"),
    ]
    cloud.set_tags(items, facet_color=_theme.COLOR_ACCENT_TEAL)

    # Type "do" → matches Documentary only (Drama has no 'o' after 'd', Comedy no match)
    # "Documentary" = doc... "Drama" = no 'do'   "Action" = no 'do'   "Comedy" = no 'do'
    cloud._filter_edit.setText("do")

    visible_values = [b.value() for b in cloud._tag_buttons if b.cloud_visible]
    assert set(visible_values) == {"Documentary"}, (
        f"Filter 'do' should show only Documentary, got: {visible_values}"
    )

    hidden_values = [b.value() for b in cloud._tag_buttons if not b.cloud_visible]
    assert set(hidden_values) == {"Action", "Drama", "Comedy"}, (
        f"Filter 'do' should hide Action, Drama, Comedy, got: {hidden_values}"
    )


def test_filter_clear_shows_all(qapp):
    """Clearing the filter text restores all visible tags (subject to cap)."""
    cloud = WeightedTagCloud()
    items = _make_items(5)
    cloud.set_tags(items, facet_color=_theme.COLOR_ACCENT)
    cloud._filter_edit.setText("Tag0")
    assert sum(1 for b in cloud._tag_buttons if b.cloud_visible) == 1
    cloud._filter_edit.clear()
    assert sum(1 for b in cloud._tag_buttons if b.cloud_visible) == 5


def test_plus_n_more_expands(qapp):
    """With >40 items, the cap button exists and clicking it reveals all tags.

    Uses cloud_visible (not isVisible()) because headless Qt widgets always
    report isVisible()==False.
    """
    cloud = WeightedTagCloud()
    items = _make_items(55)
    cloud.set_tags(items, facet_color=_theme.COLOR_ACCENT)

    # Initially: 40 visible, cap button shown
    assert cloud._more_btn.cloud_visible, "+N more button should be cloud_visible"
    assert sum(1 for b in cloud._tag_buttons if b.cloud_visible) == 40

    # Click the expand button
    cloud._more_btn.click()

    # After expand: all 55 visible, cap button gone
    assert not cloud._more_btn.cloud_visible, "+N more button should be hidden after expand"
    assert sum(1 for b in cloud._tag_buttons if b.cloud_visible) == 55


def test_plus_n_more_not_shown_for_small_sets(qapp):
    """With ≤40 items, the +N more button stays logically hidden."""
    cloud = WeightedTagCloud()
    cloud.set_tags(_make_items(40), facet_color=_theme.COLOR_ACCENT)
    assert not cloud._more_btn.cloud_visible


def test_click_emits_tag_clicked(qapp):
    """Clicking a tag button emits tag_clicked with the tag's value string."""
    cloud = WeightedTagCloud()
    cloud.set_tags([("Action", 100, "none")], facet_color=_theme.COLOR_ACCENT_TEAL)

    captured: list[str] = []
    cloud.tag_clicked.connect(captured.append)

    # Simulate click on the first (and only) button
    cloud._tag_buttons[0].click()

    assert captured == ["Action"], f"Expected ['Action'], got {captured}"


def test_exclude_state_shows_exclude_mark(qapp):
    """An exclude-state tag's button text contains the ⊘ exclude icon."""
    cloud = WeightedTagCloud()
    cloud.set_tags([("Horror", 50, "exclude")], facet_color=_theme.COLOR_ACCENT)
    btn = cloud._tag_buttons[0]
    assert _icons.tag_exclude_icon in btn.text(), (
        f"Exclude-state button should contain '{_icons.tag_exclude_icon}', got: {btn.text()!r}"
    )


def test_include_state_shows_include_mark(qapp):
    """An include-state tag's button text contains the ✓ include icon."""
    cloud = WeightedTagCloud()
    cloud.set_tags([("Comedy", 120, "include")], facet_color=_theme.COLOR_ACCENT_TEAL)
    btn = cloud._tag_buttons[0]
    assert _icons.tag_include_icon in btn.text(), (
        f"Include-state button should contain '{_icons.tag_include_icon}', got: {btn.text()!r}"
    )


def test_none_state_has_no_mark(qapp):
    """A none-state tag has no state-mark prefix."""
    cloud = WeightedTagCloud()
    cloud.set_tags([("Thriller", 80, "none")], facet_color=_theme.COLOR_ACCENT)
    btn = cloud._tag_buttons[0]
    assert _icons.tag_include_icon not in btn.text()
    assert _icons.tag_exclude_icon not in btn.text()


def test_header_shows_facet_name_and_count(qapp):
    """Header label includes the facet name and value count."""
    cloud = WeightedTagCloud()
    cloud.set_tags(_make_items(7), facet_color=_theme.COLOR_ACCENT, facet_name="Language")
    text = cloud._header_lbl.text()
    assert "Language" in text, f"Header should include facet name, got: {text!r}"
    assert "7" in text, f"Header should show count 7, got: {text!r}"


def test_set_tags_resets_cap_on_new_data(qapp):
    """Calling set_tags again after expanding resets the cap for the new data."""
    cloud = WeightedTagCloud()
    # First call — expand
    cloud.set_tags(_make_items(60), facet_color=_theme.COLOR_ACCENT)
    cloud._more_btn.click()   # expand
    assert not cloud._more_btn.cloud_visible

    # Second call with new data — cap should reset
    cloud.set_tags(_make_items(50), facet_color=_theme.COLOR_ACCENT)
    assert cloud._more_btn.cloud_visible, "Cap button should reappear after set_tags with 50 items"
    assert sum(1 for b in cloud._tag_buttons if b.cloud_visible) == 40


def test_clear_filter_empties_text_and_restores_tags(qapp):
    """clear_filter() empties the filter field and all previously hidden tags are visible again.

    Uses cloud_visible (not isVisible()) because headless Qt widgets always
    report isVisible()==False regardless of show()/hide() calls on children.
    """
    cloud = WeightedTagCloud()
    items = [
        ("Action", 100, "none"),
        ("Drama", 80, "none"),
        ("Documentary", 60, "none"),
    ]
    cloud.set_tags(items, facet_color=_theme.COLOR_ACCENT_TEAL, facet_name="Genre")

    # Apply a filter that hides Action and Drama
    cloud._filter_edit.setText("doc")
    hidden_before = [b.value() for b in cloud._tag_buttons if not b.cloud_visible]
    assert set(hidden_before) == {"Action", "Drama"}, (
        f"Filter 'doc' should hide Action and Drama, got: {hidden_before}"
    )

    # Call the public clear_filter method
    cloud.clear_filter()

    assert cloud._filter_edit.text() == "", "Filter text must be empty after clear_filter()"
    visible_after = [b.value() for b in cloud._tag_buttons if b.cloud_visible]
    assert set(visible_after) == {"Action", "Drama", "Documentary"}, (
        f"All tags must be visible after clear_filter(), got: {visible_after}"
    )
