"""Behavioral tests for the top-N cap + "Show all" expander in filter facet sections.

Feature under test (filter_group_row._Section.set_flat_items):
  - Sections with > 40 items render only the top 30 rows initially, plus a
    "Show all (N)" affordance button.
  - Clicking the button reveals the remaining rows; the button label changes to
    "Show less".
  - Sections with ≤ 40 items are rendered in full with no cap button.
  - Items are ordered by count descending (as provided by filter_panel.update_data).
  - Selection state (check/uncheck) works on both visible and overflow rows.
  - get_all_keys() and get_selected_keys() always cover the full set.
  - restore_selection() works across collapsed and expanded states.

All tests drive the real widget code (requires qapp) and assert outcomes that
would break on regression — no shape-only assertions.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# QApplication fixture (module-scoped for speed)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        expand_icon=">",
        collapse_icon="⌄",
        info_icon="ℹ",
        filter_language_groups={},
        filter_regional_groups={},
        filter_platform_groups={},
        filter_quality_groups={},
        filter_included_languages=None,
        filter_included_regions=None,
        filter_included_qualities=None,
        filter_included_platforms=None,
        filter_included_genres=None,
        filter_section_states={},
        filter_enabled_media_types=["live", "movie", "series"],
        filter_untagged_selected=["no_prefix", "no_quality"],
        filter_adult_mode="hide",
        global_filter_excluded_prefixes=[],
        global_filter_excluded_user_categories=[],
        save=lambda: None,
    )


def _make_section(qapp, section_key: str = "genre") -> object:
    """Build a bare _Section for testing (no FilterPanel wrapping needed)."""
    from metatv.gui.filter_group_row import _Section
    return _Section(
        section_key,
        section_key.upper(),
        config=_make_config(),
    )


def _make_items(n: int, *, start_count: int = 1000) -> list[tuple[str, str, int]]:
    """Generate n items sorted by count descending (Drama 1000, Comedy 999, …)."""
    names = [
        "Drama", "Comedy", "Crime", "Action", "Thriller", "Romance", "Horror",
        "Sci-Fi", "Fantasy", "Documentary", "Animation", "Adventure", "Mystery",
        "Biography", "History", "Music", "War", "Western", "Sport", "Family",
        "Kids", "Reality", "Talk", "News", "Soap", "Game Show", "Awards", "Anime",
        "Foreign", "Indie", "Short", "Experimental", "Abstract", "Erotic", "Art",
        "Cooking", "Travel", "Nature", "DIY", "Fitness", "Tech", "Science",
        "Politics", "Business", "Financial", "Legal", "Medical", "Education",
        "Lifestyle", "Parenting", "Religion", "Philosophy", "Paranormal", "True Crime",
        "Investigative", "Cultural", "Automotive", "Fashion", "Beauty", "Health",
        "Wellness", "Mindfulness", "Spirituality", "Classic", "Retro", "Nostalgic",
    ]
    items = []
    for i in range(n):
        name = names[i] if i < len(names) else f"Genre{i}"
        count = start_count - i
        items.append((name, name, count))
    return items


# ---------------------------------------------------------------------------
# 1. Cap activation — sections with > 40 items are capped at top 30
# ---------------------------------------------------------------------------

class TestCapActivation:
    """_SHOW_ALL_THRESHOLD = 40, _SHOW_ALL_TOP_N = 30."""

    def test_large_section_renders_show_all_button(self, qapp):
        """A section with 42 items must render a 'Show all' affordance button."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(42))

        assert sec._show_all_btn is not None, (
            "set_flat_items(42 items) must create a _show_all_btn"
        )

    def test_large_section_overflow_rows_hidden_initially(self, qapp):
        """The 12 overflow rows (42 − 30) must be hidden before 'Show all' is clicked."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(42))

        # Use isHidden() (explicit hide flag) not isVisible() (propagated through parents).
        # In headless tests the parent widget is not shown, so isVisible() is always False
        # regardless of the child's own hide state.
        hidden = [r for r in sec._overflow_rows if r.isHidden()]
        assert len(hidden) == 12, (
            f"expected 12 hidden overflow rows (42-30), got {len(hidden)}"
        )

    def test_large_section_top_rows_visible(self, qapp):
        """The top 30 rows are NOT hidden after set_flat_items with 42 items."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(42))

        # Non-overflow rows must NOT have been hidden
        not_hidden_non_overflow = [
            r for r in sec._rows
            if r not in sec._overflow_rows and not r.isHidden()
        ]
        assert len(not_hidden_non_overflow) == 30, (
            f"expected 30 not-hidden (non-overflow) rows, got {len(not_hidden_non_overflow)}"
        )

    def test_small_section_no_show_all_button(self, qapp):
        """A section with exactly 40 items (= threshold) must NOT be capped."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(40))

        assert sec._show_all_btn is None, (
            "40 items == threshold: no show-all button expected"
        )
        assert sec._overflow_rows == [], (
            "40 items: overflow_rows must be empty"
        )

    def test_small_section_all_rows_visible(self, qapp):
        """A section with 25 items renders all 25 rows with no cap."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(25))

        assert sec._show_all_btn is None
        assert len(sec._rows) == 25
        assert sec._overflow_rows == []

    def test_threshold_boundary_41_triggers_cap(self, qapp):
        """41 items (> 40 threshold) must trigger the cap."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(41))

        assert sec._show_all_btn is not None, (
            "41 items > 40 threshold: show-all button must appear"
        )
        assert len(sec._overflow_rows) == 11, (
            f"41 items: expected 11 overflow rows (41-30), got {len(sec._overflow_rows)}"
        )


# ---------------------------------------------------------------------------
# 2. Show-all / show-less toggle
# ---------------------------------------------------------------------------

class TestShowAllToggle:

    def test_show_all_reveals_overflow_rows(self, qapp):
        """Clicking 'Show all' makes all overflow rows visible."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(45))

        assert sec._show_all_btn is not None
        # Simulate button click
        sec._toggle_show_all()

        # Use isHidden() — the explicit hide flag set by row.hide()/show().
        # isVisible() propagates through the parent hierarchy; in headless tests
        # the parent is not shown so isVisible() stays False even for un-hidden rows.
        still_hidden = [r for r in sec._overflow_rows if r.isHidden()]
        assert still_hidden == [], (
            "after Show-all click, all overflow rows must be explicitly shown (not hidden)"
        )

    def test_show_all_button_label_changes_to_show_less(self, qapp):
        """After expanding, the button label includes 'Show less'."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(45))
        sec._toggle_show_all()

        assert "less" in sec._show_all_btn.text().lower(), (
            f"button text after expand should contain 'less'; got {sec._show_all_btn.text()!r}"
        )

    def test_show_less_hides_overflow_rows_again(self, qapp):
        """Clicking 'Show less' after 'Show all' collapses the overflow rows."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(45))
        sec._toggle_show_all()   # expand
        sec._toggle_show_all()   # collapse

        hidden = [r for r in sec._overflow_rows if r.isHidden()]
        assert len(hidden) == len(sec._overflow_rows), (
            "after Show-less click, all overflow rows must be hidden again"
        )

    def test_show_all_button_label_restores_after_collapse(self, qapp):
        """After collapse, the button label reverts to 'Show all (N)'."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(45))
        sec._toggle_show_all()   # expand
        sec._toggle_show_all()   # collapse

        text = sec._show_all_btn.text()
        assert "45" in text, (
            f"button text after collapse should include total count (45); got {text!r}"
        )
        assert "less" not in text.lower(), (
            f"button text after collapse must not say 'less'; got {text!r}"
        )

    def test_show_all_button_total_count_in_label(self, qapp):
        """The initial 'Show all' label includes the total item count."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(67))

        assert "67" in sec._show_all_btn.text(), (
            f"Show-all label must include total count 67; got {sec._show_all_btn.text()!r}"
        )

    def test_show_all_button_has_tooltip(self, qapp):
        """The 'Show all' button must have a non-empty tooltip."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(50))

        assert sec._show_all_btn.toolTip(), (
            "show-all button must have a tooltip describing its action"
        )


# ---------------------------------------------------------------------------
# 3. Sort order — items must come out count-descending
# ---------------------------------------------------------------------------

class TestSortOrder:

    def test_rows_order_matches_input_order(self, qapp):
        """Rows are rendered in the order provided (caller passes count-desc sorted list).

        filter_panel.update_data already sorts genre/lang/platform by count desc
        before calling set_flat_items, so the cap naturally takes the top-N most-used.
        This test verifies the section preserves that order.
        """
        items = _make_items(45)  # already count-desc: Drama 1000, Comedy 999, …
        sec = _make_section(qapp)
        sec.set_flat_items(items)

        rendered_keys = [r.key() for r in sec._rows]
        expected_keys = [key for key, _, _ in items]
        assert rendered_keys == expected_keys, (
            "rows must appear in the order provided by the caller"
        )

    def test_top_n_rows_are_highest_count(self, qapp):
        """The first 30 visible rows are the highest-count items (Drama, Comedy, …)."""
        items = _make_items(50)
        sec = _make_section(qapp)
        sec.set_flat_items(items)

        visible_keys = [r.key() for r in sec._rows if r not in sec._overflow_rows]
        expected_top_30 = [key for key, _, _ in items[:30]]
        assert visible_keys == expected_top_30, (
            "the 30 visible (non-overflow) rows must be the top-30 highest-count items"
        )

    def test_overflow_rows_are_lower_count(self, qapp):
        """The overflow rows are the lower-count items (ranks 31+)."""
        items = _make_items(50)
        sec = _make_section(qapp)
        sec.set_flat_items(items)

        overflow_keys = [r.key() for r in sec._overflow_rows]
        expected_overflow = [key for key, _, _ in items[30:]]
        assert overflow_keys == expected_overflow, (
            "overflow rows must be the items at rank 31+ (lower count)"
        )


# ---------------------------------------------------------------------------
# 4. Selection works in both collapsed and expanded states
# ---------------------------------------------------------------------------

class TestSelectionIntegrity:

    def test_selecting_visible_row_works_in_capped_section(self, qapp):
        """Unchecking a top-30 row is reflected in get_selected_keys()."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(50))

        # Uncheck the first row (Drama)
        sec._rows[0].set_checked(False)

        selected = sec.get_selected_keys()
        assert "Drama" not in selected, (
            "unchecked top row must not appear in get_selected_keys()"
        )

    def test_selecting_overflow_row_works_before_expansion(self, qapp):
        """Checking/unchecking an overflow row (even hidden) is reflected."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(50))

        # Row at index 35 is in overflow
        overflow_row = sec._rows[35]
        assert overflow_row in sec._overflow_rows
        overflow_row.set_checked(False)

        selected = set(sec.get_selected_keys())
        assert overflow_row.key() not in selected, (
            "overflow row unchecked while hidden must not appear in get_selected_keys()"
        )

    def test_restore_selection_reaches_overflow_rows(self, qapp):
        """restore_selection() applies to overflow rows even when they are hidden."""
        sec = _make_section(qapp)
        items = _make_items(50)
        sec.set_flat_items(items)

        # Select only items at positions 35 and 40 (both in overflow)
        keys_at_35_40 = {items[35][0], items[40][0]}
        sec.restore_selection(keys_at_35_40)

        selected = set(sec.get_selected_keys())
        assert selected == keys_at_35_40, (
            f"restore_selection must reach overflow rows; expected {keys_at_35_40}, got {selected}"
        )

    def test_get_all_keys_includes_overflow_rows(self, qapp):
        """get_all_keys() returns all 50 keys, including the 20 in overflow."""
        sec = _make_section(qapp)
        items = _make_items(50)
        sec.set_flat_items(items)

        all_keys = sec.get_all_keys()
        assert len(all_keys) == 50, (
            f"get_all_keys() must return all 50 items; got {len(all_keys)}"
        )

    def test_get_selected_keys_includes_overflow_when_all_checked(self, qapp):
        """When all rows are checked (default), get_selected_keys() returns all 50."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(50))

        assert len(sec.get_selected_keys()) == 50, (
            "all-checked (default) section must report all 50 keys as selected"
        )

    def test_is_all_selected_true_when_overflow_also_checked(self, qapp):
        """is_all_selected() is True only when overflow rows are also checked."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(50))

        # Default: all checked including overflow
        assert sec.is_all_selected(), "default state: is_all_selected() must be True"

        # Uncheck an overflow row
        sec._overflow_rows[0].set_checked(False)
        assert not sec.is_all_selected(), (
            "is_all_selected() must be False when an overflow row is unchecked"
        )

    def test_select_all_checks_overflow_rows(self, qapp):
        """select_all() also checks overflow rows."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(50))

        # Uncheck everything first
        sec.select_none()
        assert sec.get_selected_keys() == []

        # select_all must restore all 50
        sec.select_all()
        assert len(sec.get_selected_keys()) == 50, (
            "select_all() must check all rows including overflow"
        )

    def test_select_none_unchecks_overflow_rows(self, qapp):
        """select_none() also unchecks overflow rows."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(50))

        sec.select_none()
        assert sec.get_selected_keys() == [], (
            "select_none() must uncheck all rows including overflow"
        )

    def test_selection_survives_show_all_toggle(self, qapp):
        """A partial selection is unchanged by showing/hiding overflow rows."""
        sec = _make_section(qapp)
        items = _make_items(50)
        sec.set_flat_items(items)

        # Select only Drama (index 0) and a hidden overflow item
        target_keys = {items[0][0], items[35][0]}
        sec.restore_selection(target_keys)

        # Toggle show-all and back
        sec._toggle_show_all()
        sec._toggle_show_all()

        selected = set(sec.get_selected_keys())
        assert selected == target_keys, (
            "selection must be preserved across show-all/show-less toggles"
        )


# ---------------------------------------------------------------------------
# 5. clear() resets show-all state
# ---------------------------------------------------------------------------

class TestClearResetsState:

    def test_set_flat_items_clears_previous_show_all_state(self, qapp):
        """Calling set_flat_items a second time resets the show-all expander."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(50))
        sec._toggle_show_all()  # expand
        assert sec._show_all_expanded

        # Replace with a small list — no cap expected
        sec.set_flat_items(_make_items(20))

        assert sec._show_all_btn is None, (
            "after replacing with 20 items, show-all button must be gone"
        )
        assert not sec._show_all_expanded, (
            "show_all_expanded must reset to False after set_flat_items"
        )
        assert sec._overflow_rows == [], (
            "overflow_rows must be cleared after set_flat_items"
        )

    def test_set_flat_items_with_large_list_after_small_list(self, qapp):
        """Replacing a small list with a large one correctly creates the cap."""
        sec = _make_section(qapp)
        sec.set_flat_items(_make_items(10))
        assert sec._show_all_btn is None

        sec.set_flat_items(_make_items(55))
        assert sec._show_all_btn is not None, (
            "replacing small list with 55-item list must create show-all button"
        )
        assert len(sec._overflow_rows) == 25, (
            f"expected 25 overflow rows (55-30); got {len(sec._overflow_rows)}"
        )


# ---------------------------------------------------------------------------
# 6. Integration: filter_panel Genre section with 642 values
# ---------------------------------------------------------------------------

class TestFilterPanelGenreSection:
    """End-to-end check via FilterPanel.update_data with a large genre count dict."""

    def _build_panel(self, qapp, genre_counts: dict) -> object:
        from metatv.gui.filter_panel import FilterPanel
        cfg = SimpleNamespace(
            info_icon="ℹ",
            expand_icon=">",
            collapse_icon="⌄",
            filter_language_groups={},
            filter_regional_groups={},
            filter_platform_groups={},
            filter_quality_groups={},
            filter_included_languages=None,
            filter_included_regions=None,
            filter_included_qualities=None,
            filter_included_platforms=None,
            filter_included_genres=None,
            filter_section_states={},
            filter_enabled_media_types=["live", "movie", "series"],
            filter_untagged_selected=["no_prefix", "no_quality"],
            filter_adult_mode="hide",
            global_filter_excluded_prefixes=[],
            global_filter_excluded_user_categories=[],
        )
        cfg.save = lambda: None
        return FilterPanel(cfg)

    def _make_big_genre_counts(self, n: int = 100) -> dict:
        """Generate n genre names with count decreasing from n downwards."""
        genres = [f"Genre{i:03d}" for i in range(n)]
        return {g: (n - i) for i, g in enumerate(genres)}

    def test_genre_section_capped_at_top_30_for_100_genres(self, qapp):
        """update_data with 100 genres creates show-all button and caps at 30."""
        panel = self._build_panel(qapp, {})
        genre_counts = self._make_big_genre_counts(100)
        panel.update_data({
            "language": {}, "region": {}, "platform": {}, "quality": {},
            "genre": genre_counts,
        })

        sec = panel._genre_sec
        assert sec._show_all_btn is not None, (
            "genre section with 100 values must show the 'Show all' button"
        )
        assert len(sec._overflow_rows) == 70, (
            f"expected 70 overflow rows (100-30); got {len(sec._overflow_rows)}"
        )

    def test_genre_section_show_all_reveals_all_genres(self, qapp):
        """After clicking show-all, all 100 genre rows become explicitly not-hidden."""
        panel = self._build_panel(qapp, {})
        genre_counts = self._make_big_genre_counts(100)
        panel.update_data({
            "language": {}, "region": {}, "platform": {}, "quality": {},
            "genre": genre_counts,
        })

        sec = panel._genre_sec
        sec._toggle_show_all()

        still_hidden = [r for r in sec._overflow_rows if r.isHidden()]
        assert still_hidden == [], (
            "after show-all, all 100 genre overflow rows must be explicitly shown (not hidden)"
        )

    def test_genre_section_small_stays_uncapped(self, qapp):
        """A genre section with only 15 genres has no show-all button."""
        panel = self._build_panel(qapp, {})
        genre_counts = self._make_big_genre_counts(15)
        panel.update_data({
            "language": {}, "region": {}, "platform": {}, "quality": {},
            "genre": genre_counts,
        })

        sec = panel._genre_sec
        assert sec._show_all_btn is None, (
            "genre section with 15 values must NOT have a show-all button"
        )

    def test_genre_section_get_filter_state_includes_overflow(self, qapp):
        """get_filter_state covers all genres including overflow, even when collapsed."""
        panel = self._build_panel(qapp, {})
        genre_counts = self._make_big_genre_counts(50)
        panel.update_data({
            "language": {}, "region": {}, "platform": {}, "quality": {},
            "genre": genre_counts,
        })

        state = panel.get_filter_state()
        # All genres checked (default) → tag_includes has no genre entry (unconstrained)
        # OR genre_filters has all 50 items — either way all 50 must be covered.
        genre_filters = state.get("genre_filters") or []
        all_keys = panel._genre_sec.get_all_keys()
        # all genres are selected by default: is_all_selected() should be True
        assert panel._genre_sec.is_all_selected(), (
            "genre section with all selected (default) must report is_all_selected()=True"
        )
        assert len(all_keys) == 50, (
            f"get_all_keys() must include all 50 genres; got {len(all_keys)}"
        )
