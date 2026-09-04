"""Behavioral tests for FilterPanel.update_data building its facet sections
in chunks (PERF-17).

``update_data`` used to rebuild all nine dynamic facet sections in one
synchronous pass — measured a 2,037ms main-thread stall at launch (watchdog:
``update_data -> FilterGroupRow.set_flat_items -> row __init__``). It now
schedules each section's rebuild recipe (``filter_panel_sections.py``) through
``build_chunked`` (``chunked_construction.py``), one section per event-loop
turn, first section synchronous. These tests drive the REAL ``FilterPanel``
(construction pattern reused from ``test_filter_only_and_none.py`` /
``test_filter_opt_out.py`` — a ``SimpleNamespace`` config, a module-scoped
``qapp``) and assert the outcome that would break if chunking dropped a
section, duplicated rows on a superseding call, or ran ``_finish`` twice.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from metatv.gui.filter_panel import FilterPanel


# ---------------------------------------------------------------------------
# QApplication fixture (module-scoped for speed — matches the sibling files)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Minimal config builder — SimpleNamespace, no save(), no filesystem
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> SimpleNamespace:
    """Minimal FilterPanel config — mirrors the pattern in the sibling
    filter-panel test files (SimpleNamespace, no save(), no filesystem).

    ``filter_known_*`` is the opt-out baseline: ``None`` means "first run for
    this facet" (un-hide everything present); a list means "already
    established", so a value in the data but not in the list is NEW.
    """
    cfg = SimpleNamespace(
        info_icon="ℹ",
        expand_icon="▶",
        collapse_icon="▼",
        filter_language_groups={},
        filter_regional_groups={"North America": ["US", "CA", "MX"]},
        filter_platform_groups={},
        filter_quality_groups={},
        filter_known_languages=None,
        filter_known_regions=None,
        filter_known_platforms=None,
        filter_known_qualities=None,
        filter_known_categories=None,
        filter_known_genres=None,
        filter_known_subtitles=None,
        filter_known_dubs=None,
        filter_known_formats=None,
        filter_included_languages=None,
        filter_included_regions=None,
        filter_included_qualities=None,
        filter_included_platforms=None,
        filter_included_categories=None,
        filter_included_genres=None,
        filter_included_subtitles=None,
        filter_included_dubs=None,
        filter_included_formats=None,
        filter_section_states={},
        filter_enabled_media_types=["live", "movie", "series"],
        filter_untagged_selected=["no_prefix", "no_quality"],
        filter_hide_watched=False,
        filter_adult_mode="hide",
        global_filter_excluded_prefixes=[],
        global_filter_excluded_user_categories=[],
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    cfg.save = lambda: None
    return cfg


def _build_panel(config) -> FilterPanel:
    return FilterPanel(config)


# ---------------------------------------------------------------------------
# 1. First section builds synchronously; the rest arrive across the event
#    loop; the restore (opt-out) contract holds once everything is built.
# ---------------------------------------------------------------------------

def test_update_data_populates_all_sections_across_event_loop(qapp, qtbot):
    # "English" is the established baseline for language; "French"/"German"
    # are NEW in the data below, so they must default INCLUDED (opt-out).
    cfg = _make_config(
        filter_known_languages=["English"],
        filter_included_languages=["English"],
    )
    panel = _build_panel(cfg)

    tag_counts = {
        "language": {"English": 100, "French": 50, "German": 20},
        "region":   {"US": 80, "CA": 20, "MX": 10},
        "platform": {"Netflix": 30},
        "quality":  {"HD": 70, "SD": 40, "4K / UHD": 10},
        "genre":    {"Action": 10, "Drama": 5, "Comedy": 3},
    }
    panel.update_data(tag_counts)

    # Section grain: build_chunked's first batch (batch_size=1) runs
    # synchronously, so the FIRST section (language, display order) is
    # already fully built the instant update_data() returns...
    assert set(panel._lang_sec.get_all_keys()) == {"English", "French", "German"}, (
        "the first section must be completely built synchronously"
    )
    # ...but nothing scheduled after it has run yet, and the handle is not done.
    assert not panel._update_handle.done, "later sections must still be pending"
    assert panel._region_sec.get_all_keys() == [], "region (2nd section) must not be built yet"
    assert panel._genre_sec.get_all_keys() == [], "genre (6th section) must not be built yet"

    qtbot.waitUntil(lambda: panel._update_handle.done, timeout=2000)

    # Every fed section is now fully populated, one event-loop turn each.
    assert set(panel._lang_sec.get_all_keys()) == {"English", "French", "German"}
    assert set(panel._region_sec.get_all_keys()) == {"US", "CA", "MX"}
    assert set(panel._platform_sec.get_all_keys()) == {"Netflix"}
    assert set(panel._quality_sec.get_all_keys()) == {"HD", "SD", "4K / UHD"}
    assert set(panel._genre_sec.get_all_keys()) == {"Action", "Drama", "Comedy"}

    # Restore contract (opt-out model): new/unseen language values default
    # INCLUDED, and the persisted subset survives alongside them.
    lang_selected = set(panel._lang_sec.get_selected_keys())
    assert lang_selected == {"English", "French", "German"}, (
        f"new language values must default included; got {lang_selected!r}"
    )
    # Genre/quality never had a baseline recorded (filter_known_* is None) ->
    # first-run baseline un-hides everything present.
    assert panel._genre_sec.is_all_selected(), "genre must be all-selected on first run"
    assert panel._quality_sec.is_all_selected(), "quality must be all-selected on first run"


# ---------------------------------------------------------------------------
# 2. A second update_data() call before the first has finished cancels it —
#    only the second data set's rows survive, nowhere duplicated or stale.
# ---------------------------------------------------------------------------

def test_second_update_data_supersedes_first(qapp, qtbot):
    cfg = _make_config()
    panel = _build_panel(cfg)

    first_counts = {
        "language": {"English": 10, "French": 5},
        "region":   {"US": 10},
        "platform": {"Netflix": 5},
        "quality":  {"HD": 10},
        "genre":    {"Action": 10},
    }
    panel.update_data(first_counts)
    first_handle = panel._update_handle
    # Only the first section (language) has run; region/platform/quality/genre
    # are still scheduled on the event loop when the second call supersedes it.
    assert not first_handle.done

    second_counts = {
        "language": {"Spanish": 20, "Portuguese": 15},
        "region":   {"MX": 12},
        "platform": {"Disney+": 8},
        "quality":  {"SD": 9},
        "genre":    {"Comedy": 7},
    }
    panel.update_data(second_counts)  # must cancel first_handle before doing anything else
    second_handle = panel._update_handle
    assert second_handle is not first_handle

    qtbot.waitUntil(lambda: second_handle.done, timeout=2000)

    # The superseded run must never complete, no matter how long we wait —
    # cancel() only flips a flag, it never marks a run done.
    assert not first_handle.done, "the superseded (first) handle must never report done"
    assert first_handle._cancelled, "the superseded (first) handle must be cancelled"

    # Every section reflects ONLY the second data set — no first-call rows
    # left behind, and nothing duplicated.
    assert set(panel._lang_sec.get_all_keys()) == {"Spanish", "Portuguese"}, (
        "language must show only the second call's values"
    )
    assert set(panel._region_sec.get_all_keys()) == {"MX"}
    assert set(panel._platform_sec.get_all_keys()) == {"Disney+"}
    assert set(panel._quality_sec.get_all_keys()) == {"SD"}
    assert set(panel._genre_sec.get_all_keys()) == {"Comedy"}

    # And nothing from the cancelled first run leaked into the selection either.
    assert "English" not in panel._lang_sec.get_all_keys()
    assert "French" not in panel._lang_sec.get_all_keys()
