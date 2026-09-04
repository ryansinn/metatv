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
from tests.conftest import drain_chunked_build


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
    drain_chunked_build(panel._update_handle)


def test_get_filter_state_returns_expected_keys(qapp):
    """get_filter_state() must return the required keys and no unidentified residue."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())
    drain_chunked_build(panel._update_handle)

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

def test_every_facet_section_has_an_untagged_row(qapp):
    """The retired "Unknown" section is replaced by a per-facet footer row.

    That section offered two toggles (``no_prefix``/``no_quality``), covered 2
    of 9 facets — both LEGACY COLUMN axes, neither of them a tag facet — and
    displayed a hardcoded count of 0 for both. Coverage and freshness had each
    drifted, which is the failure mode a separate section invites: it has to be
    hand-extended per facet. The rows are now generated from the same
    ``_facet_sections()`` map the filter itself reads, so they cannot cover a
    different set than the thing they describe (#299).
    """
    panel = _build_panel(qapp)
    panel.update_data(_make_stats(), {"language": 5, "region": 7, "genre": 11})
    drain_chunked_build(panel._update_handle)

    for facet, section in panel._facet_sections().items():
        assert section.has_untagged_row(), f"{facet} section has no untagged row"


def test_untagged_row_is_not_a_facet_value(qapp):
    """It must stay out of every value-set API.

    If it counted as a value, ticking all values would no longer read as "no
    constraint" — the section would look partially-selected and silently
    activate a filter.
    """
    panel = _build_panel(qapp)
    panel.update_data(_make_stats(), {"language": 5})
    drain_chunked_build(panel._update_handle)

    from metatv.gui.filter_group_row import UNTAGGED_KEY
    sec = panel._lang_sec
    assert UNTAGGED_KEY not in sec.get_all_keys()
    assert UNTAGGED_KEY not in sec.get_selected_keys()
    assert sec.is_all_selected(), "all values ticked must still read as unconstrained"


def test_unticking_untagged_row_reaches_the_filter_state(qapp):
    """Switching the row off names that facet in ``facets_hiding_untagged`` —
    the strict opt-in that replaces the old ``include_untagged=False``."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats(), {"language": 5})
    drain_chunked_build(panel._update_handle)

    panel._lang_sec._untagged_row.set_checked(False)

    state = panel.get_filter_state()
    assert state["facets_hiding_untagged"] == {"language"}


def test_untagged_rows_default_to_included(qapp):
    """Default is inclusive, and a facet the user has never touched stays that
    way — the config stores the EXCEPTIONS, so a facet added later starts
    included rather than silently hidden."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats(), {"language": 5, "genre": 3})
    drain_chunked_build(panel._update_handle)

    state = panel.get_filter_state()
    assert state["facets_hiding_untagged"] is None
    assert panel._lang_sec.untagged_included() is True


# ---------------------------------------------------------------------------
# 4. Surviving sections still populate, filter, and persist
# ---------------------------------------------------------------------------

def test_language_section_populates_from_update_data(qapp):
    """Language section must be populated from tag counts after removal of unid section."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())
    drain_chunked_build(panel._update_handle)

    keys = set(panel._lang_sec.get_all_keys())
    assert "EN" in keys and "FR" in keys, (
        f"language section must contain EN and FR; got {keys}"
    )


def test_genre_section_populates_from_update_data(qapp):
    """Genre section must still receive tag counts after removal of unid section."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())
    drain_chunked_build(panel._update_handle)

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
    drain_chunked_build(panel._update_handle)
    panel.select_all_sections()  # must not raise


def test_clear_all_does_not_raise(qapp):
    """clear_all() must work without error after section removal."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())
    drain_chunked_build(panel._update_handle)
    panel.clear_all()  # must not raise


# ---------------------------------------------------------------------------
# 6. "Only" action still works for the remaining sections
# ---------------------------------------------------------------------------

def test_select_only_group_on_language_still_works(qapp):
    """select_only_group on language clears all other sections and selects only EN."""
    panel = _build_panel(qapp)
    panel.update_data(_make_stats())
    drain_chunked_build(panel._update_handle)

    emitted: list[None] = []
    panel.filter_changed.connect(lambda: emitted.append(None))
    startup_count = 0  # filter_changed already emitted in update_data; connect after

    panel.select_only_group("EN", "language")

    lang_sel = set(panel._lang_sec.get_selected_keys())
    assert lang_sel == {"EN"}, f"expected only EN; got {lang_sel!r}"
    assert panel._platform_sec.get_selected_keys() == [], "platform must be cleared"
    assert panel._quality_sec.get_selected_keys() == [], "quality must be cleared"
    assert len(emitted) == 1, f"Only action must emit filter_changed once; got {len(emitted)}"
