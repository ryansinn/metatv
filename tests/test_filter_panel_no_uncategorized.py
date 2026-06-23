"""Behavioral tests: Uncategorized (unidentified-prefix) section removed from FilterPanel.

The tag model no longer produces an "unknown prefix" facet type — every prefix is
either classified (language/region/platform) or omitted from tags.  The Uncategorized
section was always empty; this test suite proves it has been fully removed without
breaking the remaining sections.

Regressions guarded:
  1. FilterPanel has no _unid_sec attribute.
  2. _all_sections() no longer includes the unidentified section.
  3. update_data() + get_filter_state() complete without error.
  4. The functional Unknown catch-all (_untagged_sec) is still present and works.
  5. select_all_sections() + clear_all() operate on the surviving sections only.
  6. The "Only" action (select_only_group) still works for remaining sections.
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


def _make_stats() -> dict:
    """Tag-counts dict for FilterPanel.update_data() (Slice B format)."""
    return {
        "language": {"EN": 100, "FR": 50},
        "region":   {"US": 80, "CA": 20},
        "platform": {"Netflix": 30},
        "quality":  {"HD": 70, "SD": 40},
        "genre":    {"Action": 10, "Drama": 5},
    }


def _build_panel(qapp, config=None):
    from metatv.gui.filter_panel import FilterPanel
    return FilterPanel(config or _make_config())


# ---------------------------------------------------------------------------
# 1. Uncategorized section is gone
# ---------------------------------------------------------------------------

def test_unid_sec_attribute_does_not_exist(qapp):
    """FilterPanel must not expose _unid_sec — the attribute is deleted."""
    panel = _build_panel(qapp)
    assert not hasattr(panel, "_unid_sec"), (
        "_unid_sec must not exist; the Uncategorized section was removed"
    )


def test_all_sections_excludes_unidentified(qapp):
    """_all_sections() must not contain any section with key 'unidentified'."""
    panel = _build_panel(qapp)
    keys = [s.section_key() for s in panel._all_sections()]
    assert "unidentified" not in keys, (
        f"'unidentified' key must not appear in _all_sections(); got {keys}"
    )


# ---------------------------------------------------------------------------
# 2. update_data + get_filter_state complete without error
# ---------------------------------------------------------------------------

def test_update_data_runs_without_error(qapp):
    """update_data() must complete without raising after _unid_sec removal."""
    panel = _build_panel(qapp)
    # Should not raise
    panel.update_data(_make_stats())


def test_get_filter_state_returns_expected_keys(qapp):
    """get_filter_state() must return the required keys and no unidentified residue."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())

    state = panel.get_filter_state()

    # Required keys present
    for key in ("media_types", "language_groups", "region_groups",
                "quality_groups", "platform_groups", "genre_filters",
                "include_untagged", "include_untagged_quality",
                "tag_includes"):
        assert key in state, f"get_filter_state() missing key '{key}'"

    # No stray unidentified data
    assert "unidentified_groups" not in state, (
        "get_filter_state() must not contain 'unidentified_groups'"
    )


# ---------------------------------------------------------------------------
# 3. Unknown catch-all (_untagged_sec) is still functional
# ---------------------------------------------------------------------------

def test_untagged_sec_still_exists(qapp):
    """The Unknown catch-all section (_untagged_sec) must still be present."""
    panel = _build_panel(qapp)
    assert hasattr(panel, "_untagged_sec"), "_untagged_sec must exist"


def test_untagged_sec_has_both_items(qapp):
    """_untagged_sec must have 'no_prefix' and 'no_quality' items."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())

    keys = set(panel._untagged_sec.get_all_keys())
    assert "no_prefix" in keys, "untagged section must contain 'no_prefix'"
    assert "no_quality" in keys, "untagged section must contain 'no_quality'"


def test_untagged_sec_appears_in_all_sections(qapp):
    """_untagged_sec must appear in _all_sections()."""
    panel = _build_panel(qapp)
    keys = [s.section_key() for s in panel._all_sections()]
    assert "untagged" in keys, f"'untagged' key must appear in _all_sections(); got {keys}"


def test_untagged_deselect_no_prefix_affects_filter_state(qapp):
    """Deselecting 'no_prefix' in Unknown section sets include_untagged=False."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())

    # Deselect no_prefix
    panel._untagged_sec.restore_selection({"no_quality"})

    state = panel.get_filter_state()
    assert state["include_untagged"] is False, (
        "deselecting 'no_prefix' must set include_untagged=False"
    )
    assert state["include_untagged_quality"] is True, (
        "'no_quality' still selected must keep include_untagged_quality=True"
    )


# ---------------------------------------------------------------------------
# 4. Surviving sections still populate, filter, and persist
# ---------------------------------------------------------------------------

def test_language_section_populates_from_update_data(qapp):
    """Language section must be populated from tag counts after removal of unid section."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())

    keys = set(panel._lang_sec.get_all_keys())
    assert "EN" in keys and "FR" in keys, (
        f"language section must contain EN and FR; got {keys}"
    )


def test_genre_section_populates_from_update_data(qapp):
    """Genre section must still receive tag counts after removal of unid section."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())

    keys = set(panel._genre_sec.get_all_keys())
    assert "Action" in keys and "Drama" in keys, (
        f"genre section must contain Action and Drama; got {keys}"
    )


# ---------------------------------------------------------------------------
# 5. select_all_sections + clear_all operate cleanly
# ---------------------------------------------------------------------------

def test_select_all_does_not_raise(qapp):
    """select_all_sections() must work without error after section removal."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())
    panel.select_all_sections()  # must not raise


def test_clear_all_does_not_raise(qapp):
    """clear_all() must work without error after section removal."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())
    panel.clear_all()  # must not raise


# ---------------------------------------------------------------------------
# 6. "Only" action still works for the remaining sections
# ---------------------------------------------------------------------------

def test_select_only_group_on_language_still_works(qapp):
    """select_only_group on language clears all other sections and selects only EN."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())

    emitted: list[None] = []
    panel.filter_changed.connect(lambda: emitted.append(None))
    startup_count = 0  # filter_changed already emitted in update_data; connect after

    panel.select_only_group("EN", "language")

    lang_sel = set(panel._lang_sec.get_selected_keys())
    assert lang_sel == {"EN"}, f"expected only EN; got {lang_sel!r}"
    assert panel._platform_sec.get_selected_keys() == [], "platform must be cleared"
    assert panel._quality_sec.get_selected_keys() == [], "quality must be cleared"
    assert len(emitted) == 1, f"Only action must emit filter_changed once; got {len(emitted)}"
