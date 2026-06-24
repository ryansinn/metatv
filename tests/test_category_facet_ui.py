"""Behavioral tests for the `category:` facet UI surface (Commit 2).

Tests:
1. FilterPanel: "category" is in _SECTION_KEYS and a _category_sec attribute
   exists with the correct section key.
2. FilterPanel.update_data: category counts from tag_counts['category'] populate
   the Category section.
3. FilterPanel.get_filter_state: when a category subset is selected, it is
   present in tag_includes['category'].
4. Recipe view _FACET_META: "category" is registered with the correct display
   name, color, and role.
5. details_sections: "category" appears in _FACET_DISPLAY_ORDER before "genre",
   and in _FACET_LABELS as "Category".

All widget tests construct via normal instantiation on a headless QApplication
(module-scoped qapp fixture) with a minimal config SimpleNamespace so no real
~/.config/metatv paths are written.
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
# Minimal config stub (no filesystem writes)
# ---------------------------------------------------------------------------

def _make_config() -> SimpleNamespace:
    """Minimal config for FilterPanel — no save(), no filesystem."""
    cfg = SimpleNamespace(
        info_icon="ℹ",
        expand_icon="▶",
        collapse_icon="▼",
        filter_language_groups={"EN": ["EN"], "FR": ["FR"]},
        filter_regional_groups={"North America": ["US", "CA"]},
        filter_platform_groups={"Netflix": ["NF"]},
        filter_quality_groups={"HD": ["HD"], "SD": ["SD"]},
        filter_included_languages=None,
        filter_included_regions=None,
        filter_included_qualities=None,
        filter_included_platforms=None,
        filter_included_categories=None,
        filter_included_genres=None,
        filter_section_states={},
        filter_enabled_media_types=["live", "movie", "series"],
        filter_untagged_selected=["no_prefix", "no_quality"],
        filter_adult_mode="hide",
        global_filter_excluded_prefixes=[],
        global_filter_excluded_user_categories=[],
    )
    cfg.save = lambda: None
    return cfg


def _make_tag_counts() -> dict:
    """Tag-counts dict matching the tag-model format expected by update_data()."""
    return {
        "language": {"English": 100, "French": 50},
        "region":   {"US": 80, "CA": 20},
        "platform": {"Netflix": 30},
        "quality":  {"HD": 70, "SD": 40},
        "category": {"Sports": 45, "News": 30, "Kids": 20},
        "genre":    {"Action": 10, "Drama": 5},
    }


# ---------------------------------------------------------------------------
# 1.  FilterPanel structure
# ---------------------------------------------------------------------------

class TestFilterPanelCategorySection:
    """FilterPanel must expose a _category_sec section with key 'category'."""

    def test_section_key_in_SECTION_KEYS(self, qapp):
        """'category' must be listed in _SECTION_KEYS."""
        from metatv.gui.filter_panel import FilterPanel
        assert "category" in FilterPanel._SECTION_KEYS

    def test_category_sec_attribute_exists(self, qapp):
        """FilterPanel must have a _category_sec attribute."""
        from metatv.gui.filter_panel import FilterPanel
        panel = FilterPanel(_make_config())
        assert hasattr(panel, "_category_sec"), "_category_sec attribute must exist"

    def test_category_section_key_is_category(self, qapp):
        """_category_sec.section_key() must return 'category'."""
        from metatv.gui.filter_panel import FilterPanel
        panel = FilterPanel(_make_config())
        assert panel._category_sec.section_key() == "category"

    def test_category_appears_in_all_sections(self, qapp):
        """_all_sections() must include the category section."""
        from metatv.gui.filter_panel import FilterPanel
        panel = FilterPanel(_make_config())
        keys = [s.section_key() for s in panel._all_sections()]
        assert "category" in keys, f"'category' not in _all_sections() keys: {keys}"

    def test_category_before_genre_in_SECTION_KEYS(self, qapp):
        """'category' must appear immediately before 'genre' in _SECTION_KEYS."""
        from metatv.gui.filter_panel import FilterPanel
        keys = FilterPanel._SECTION_KEYS
        cat_idx = keys.index("category")
        genre_idx = keys.index("genre")
        assert cat_idx < genre_idx, (
            f"'category' (idx {cat_idx}) must be before 'genre' (idx {genre_idx})"
        )


# ---------------------------------------------------------------------------
# 2.  FilterPanel.update_data populates category section
# ---------------------------------------------------------------------------

class TestFilterPanelCategoryUpdateData:
    """update_data() must populate _category_sec from tag_counts['category']."""

    def test_category_items_populated_from_tag_counts(self, qapp):
        """Category section must list Sports/News/Kids after update_data()."""
        from metatv.gui.filter_panel import FilterPanel
        panel = FilterPanel(_make_config())
        panel.update_data(_make_tag_counts())

        keys = set(panel._category_sec.get_all_keys())
        assert "Sports" in keys, f"Sports must be in category section; got {keys}"
        assert "News" in keys, f"News must be in category section; got {keys}"
        assert "Kids" in keys, f"Kids must be in category section; got {keys}"

    def test_category_section_all_selected_by_default(self, qapp):
        """On fresh load (None persisted), category section starts all-selected."""
        from metatv.gui.filter_panel import FilterPanel
        panel = FilterPanel(_make_config())
        panel.update_data(_make_tag_counts())
        assert panel._category_sec.is_all_selected(), (
            "category section must be all-selected on first load"
        )

    def test_get_filter_state_includes_category_key(self, qapp):
        """get_filter_state() must return a 'category_filters' key."""
        from metatv.gui.filter_panel import FilterPanel
        panel = FilterPanel(_make_config())
        panel.update_data(_make_tag_counts())

        state = panel.get_filter_state()
        assert "category_filters" in state, (
            "'category_filters' key missing from get_filter_state()"
        )

    def test_constrained_category_selection_in_tag_includes(self, qapp):
        """When only Sports is selected, tag_includes must contain category:{'Sports'}."""
        from metatv.gui.filter_panel import FilterPanel
        panel = FilterPanel(_make_config())
        panel.update_data(_make_tag_counts())

        # Deselect everything, then select only Sports
        panel._category_sec.restore_selection({"Sports"})

        state = panel.get_filter_state()
        tag_includes = state.get("tag_includes") or {}
        assert "category" in tag_includes, (
            "tag_includes must contain 'category' key when selection is constrained"
        )
        assert tag_includes["category"] == {"Sports"}, (
            f"tag_includes['category'] must be {{'Sports'}}; got {tag_includes.get('category')}"
        )

    def test_all_selected_category_absent_from_tag_includes(self, qapp):
        """When all category values are selected, tag_includes must NOT constrain category."""
        from metatv.gui.filter_panel import FilterPanel
        panel = FilterPanel(_make_config())
        panel.update_data(_make_tag_counts())

        # All selected = no constraint
        panel._category_sec.select_all()
        state = panel.get_filter_state()
        tag_includes = state.get("tag_includes") or {}
        assert "category" not in tag_includes, (
            "tag_includes must NOT contain 'category' when all values are selected"
        )


# ---------------------------------------------------------------------------
# 3.  category NOT in _GLOBALLY_EXCLUDABLE
# ---------------------------------------------------------------------------

def test_category_not_globally_excludable(qapp):
    """'category' must NOT be in _GLOBALLY_EXCLUDABLE (it's content, not scoping)."""
    from metatv.gui.filter_panel import FilterPanel
    assert "category" not in FilterPanel._GLOBALLY_EXCLUDABLE, (
        "'category' must not be globally excludable — it is a content facet, not a scoping axis"
    )


# ---------------------------------------------------------------------------
# 4.  Recipe view _FACET_META
# ---------------------------------------------------------------------------

class TestRecipeFacetMeta:
    """_FACET_META in recipe_view must include 'category' with the correct values."""

    def test_category_in_facet_meta(self):
        """'category' must be a key in _FACET_META."""
        from metatv.gui.recipe_view import _FACET_META
        assert "category" in _FACET_META, "'category' must be in recipe_view._FACET_META"

    def test_category_display_name(self):
        """_FACET_META['category'][0] (display name) must be 'Category'."""
        from metatv.gui.recipe_view import _FACET_META
        display_name = _FACET_META["category"][0]
        assert display_name == "Category", (
            f"display name must be 'Category'; got {display_name!r}"
        )

    def test_category_color_is_theme_token(self):
        """_FACET_META['category'][1] must equal theme.COLOR_FACET_CATEGORY."""
        from metatv.gui import theme as _theme
        from metatv.gui.recipe_view import _FACET_META
        color = _FACET_META["category"][1]
        assert color == _theme.COLOR_FACET_CATEGORY, (
            f"category color must be COLOR_FACET_CATEGORY; got {color!r}"
        )

    def test_category_role_label_is_kind(self):
        """_FACET_META['category'][2] (role label) must be 'KIND'."""
        from metatv.gui.recipe_view import _FACET_META
        role = _FACET_META["category"][2]
        assert role == "KIND", f"role label must be 'KIND'; got {role!r}"

    def test_kind_in_role_order(self):
        """'KIND' must be in _ROLE_ORDER (before 'BASE')."""
        from metatv.gui.recipe_view import _ROLE_ORDER
        assert "KIND" in _ROLE_ORDER, "'KIND' must appear in _ROLE_ORDER"
        assert _ROLE_ORDER.index("KIND") < _ROLE_ORDER.index("BASE"), (
            "'KIND' must precede 'BASE' in _ROLE_ORDER"
        )


# ---------------------------------------------------------------------------
# 5.  details_sections facet display order and labels
# ---------------------------------------------------------------------------

class TestDetailsSectionsCategoryFacet:
    """details_sections must register 'category' in display order and labels."""

    def test_category_in_facet_display_order(self):
        """'category' must be in _FACET_DISPLAY_ORDER."""
        from metatv.gui.details_sections import _FACET_DISPLAY_ORDER
        assert "category" in _FACET_DISPLAY_ORDER, (
            "'category' must be in _FACET_DISPLAY_ORDER"
        )

    def test_category_before_genre_in_display_order(self):
        """'category' must appear before 'genre' in _FACET_DISPLAY_ORDER."""
        from metatv.gui.details_sections import _FACET_DISPLAY_ORDER
        cat_idx = _FACET_DISPLAY_ORDER.index("category")
        genre_idx = _FACET_DISPLAY_ORDER.index("genre")
        assert cat_idx < genre_idx, (
            f"'category' (idx {cat_idx}) must precede 'genre' (idx {genre_idx})"
        )

    def test_category_label_in_facet_labels(self):
        """_FACET_LABELS must map 'category' → 'Category'."""
        from metatv.gui.details_sections import _FACET_LABELS
        assert _FACET_LABELS.get("category") == "Category", (
            f"_FACET_LABELS['category'] must be 'Category'; got {_FACET_LABELS.get('category')!r}"
        )


# ---------------------------------------------------------------------------
# 6.  Theme token exists
# ---------------------------------------------------------------------------

def test_color_facet_category_token_exists():
    """theme.COLOR_FACET_CATEGORY must be defined and non-empty."""
    from metatv.gui import theme as _theme
    assert hasattr(_theme, "COLOR_FACET_CATEGORY"), (
        "theme.COLOR_FACET_CATEGORY token must be defined"
    )
    assert _theme.COLOR_FACET_CATEGORY, "COLOR_FACET_CATEGORY must be a non-empty string"
