"""Behavioral tests for FilterPanel startup persistence fix.

Regression being guarded:
  - On startup, update_data() was called AFTER restore_state() ran on empty sections.
  - Because the in-memory ``prev`` snapshot was empty, the ``if prev: restore`` branch
    was skipped, silently discarding the persisted config selections for Language,
    Region, Quality, Platform, and Genre.  Media and Untagged survived because they
    are static sections populated at __init__ time (before update_data).
  - The fix: when ``prev`` is empty, fall back to ``config.filter_included_*``
    (the same attrs that restore_state writes from), using a shared
    ``_persisted_section_attrs()`` helper so the attr names are never duplicated.

Tests:
  1. Startup path: saved Language/Region/Quality/Platform/Genre selections are applied
     by update_data when the sections are empty (no prior items).
  2. Live-refresh path: an in-memory selection survives a second update_data call
     (the refresh / source-added case) — saved config must NOT override it.
  3. Genre fresh-install: when no genre selection is persisted, update_data selects
     all genres (previous behaviour).
  4. Startup Untagged: persisted filter_untagged_selected is applied on first
     update_data (was also empty-prev).

All tests build a real FilterPanel via __init__ + QApplication so the Qt widget
machinery (set_flat_items, restore_selection, get_selected_keys) executes for real —
this is the half that would regress.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# QApplication fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Fake Config builder
# ---------------------------------------------------------------------------

def _make_config(
    *,
    filter_included_languages: list[str] | None = None,
    filter_included_regions: list[str] | None = None,
    filter_included_qualities: list[str] | None = None,
    filter_included_platforms: list[str] | None = None,
    filter_included_genres: list[str] | None = None,
    filter_untagged_selected: list[str] | None = None,
) -> SimpleNamespace:
    """Minimal config for FilterPanel — no save(), no filesystem."""
    cfg = SimpleNamespace(
        # Icons (used by _Section / _GroupRow)
        info_icon="ℹ",
        expand_icon="▶",
        collapse_icon="▼",
        # Group dicts (used by get_filter_state resolution)
        filter_language_groups={"EN": ["EN"], "FR": ["FR"]},
        filter_regional_groups={"North America": ["US", "CA"]},
        filter_platform_groups={"Netflix": ["NF"]},
        filter_quality_groups={"HD": ["HD"], "SD": ["SD"]},
        # Persisted selections — the values under test
        filter_included_languages=filter_included_languages or [],
        filter_included_regions=filter_included_regions or [],
        filter_included_qualities=filter_included_qualities or [],
        filter_included_platforms=filter_included_platforms or [],
        filter_included_genres=filter_included_genres or [],
        filter_section_states={},
        filter_enabled_media_types=["live", "movie", "series"],
        filter_untagged_selected=(
            filter_untagged_selected
            if filter_untagged_selected is not None
            else ["no_prefix", "no_quality"]
        ),
        filter_adult_mode="hide",
        global_filter_excluded_prefixes=[],
        global_filter_excluded_user_categories=[],
    )
    # save() must be a no-op so tests don't write to disk
    cfg.save = lambda: None
    return cfg


# ---------------------------------------------------------------------------
# Stats dict builder
# ---------------------------------------------------------------------------

def _make_stats(
    *,
    lang_groups: dict | None = None,
    region_groups: dict | None = None,
    platform_groups: dict | None = None,
    quality_groups: dict | None = None,
    genre_counts: dict | None = None,
) -> dict:
    """Minimal stats dict for FilterPanel.update_data()."""
    return {
        "prefix_counts": {"EN": 100, "FR": 50, "US": 80, "CA": 20, "NF": 30,
                          "HD": 70, "SD": 40},
        "language_groups": lang_groups or {"EN": 100, "FR": 50},
        "region_groups": region_groups or {"North America": 100},
        "platform_groups": platform_groups or {"Netflix": 30},
        "quality_groups": quality_groups or {"HD": 70, "SD": 40},
        "genre_counts": genre_counts or {"Action": 10, "Drama": 5},
        "unmapped_prefixes": [],
        "channels_without_prefix": 5,
        "channels_without_quality": 3,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_panel(qapp, config):
    """Build a real FilterPanel (requires qapp so Qt widgets initialise)."""
    from metatv.gui.filter_panel import FilterPanel
    return FilterPanel(config)


# ---------------------------------------------------------------------------
# 1. Startup path — persisted selections applied by update_data
# ---------------------------------------------------------------------------

def test_startup_language_selection_applied(qapp):
    """On first update_data, saved language selection is restored from config."""
    cfg = _make_config(filter_included_languages=["FR"])  # only French saved
    panel = _build_panel(qapp, cfg)

    panel.update_data(_make_stats())

    selected = set(panel._lang_sec.get_selected_keys())
    assert selected == {"FR"}, (
        "startup: only the saved language 'FR' should be selected; "
        f"got {selected!r}"
    )


def test_startup_region_selection_applied(qapp):
    """On first update_data, saved region (individual prefix codes) is restored."""
    cfg = _make_config(filter_included_regions=["CA"])  # only Canada saved
    panel = _build_panel(qapp, cfg)

    panel.update_data(_make_stats())

    selected = set(panel._region_sec.get_selected_keys())
    assert selected == {"CA"}, (
        "startup: only the saved region code 'CA' should be selected; "
        f"got {selected!r}"
    )


def test_startup_quality_selection_applied(qapp):
    """On first update_data, saved quality selection is restored from config."""
    cfg = _make_config(filter_included_qualities=["HD"])  # only HD saved
    panel = _build_panel(qapp, cfg)

    panel.update_data(_make_stats())

    selected = set(panel._quality_sec.get_selected_keys())
    assert selected == {"HD"}, (
        "startup: only the saved quality 'HD' should be selected; "
        f"got {selected!r}"
    )


def test_startup_platform_selection_applied(qapp):
    """On first update_data, saved platform selection is restored from config."""
    cfg = _make_config(filter_included_platforms=["Netflix"])
    panel = _build_panel(qapp, cfg)

    panel.update_data(_make_stats())

    selected = set(panel._platform_sec.get_selected_keys())
    assert selected == {"Netflix"}, (
        "startup: only the saved platform 'Netflix' should be selected; "
        f"got {selected!r}"
    )


def test_startup_genre_selection_applied(qapp):
    """On first update_data, saved genre selection is restored from config."""
    cfg = _make_config(filter_included_genres=["Drama"])  # only Drama saved
    panel = _build_panel(qapp, cfg)

    panel.update_data(_make_stats())

    selected = set(panel._genre_sec.get_selected_keys())
    assert selected == {"Drama"}, (
        "startup: only the saved genre 'Drama' should be selected; "
        f"got {selected!r}"
    )


# ---------------------------------------------------------------------------
# 2. Live-refresh path — in-memory selection survives a second update_data
# ---------------------------------------------------------------------------

def test_live_refresh_preserves_in_memory_language(qapp):
    """A second update_data (source refresh) must keep the user's current selection."""
    cfg = _make_config(filter_included_languages=["EN"])
    panel = _build_panel(qapp, cfg)

    # First call — startup, applies saved "EN"
    panel.update_data(_make_stats())
    assert "EN" in panel._lang_sec.get_selected_keys()

    # User manually changes to "FR" only
    panel._lang_sec.restore_selection({"FR"})

    # Second call (e.g. after a source refresh) — must preserve "FR", not revert to "EN"
    panel.update_data(_make_stats())

    selected = set(panel._lang_sec.get_selected_keys())
    assert selected == {"FR"}, (
        "live-refresh: in-memory 'FR' selection must survive update_data; "
        f"got {selected!r}"
    )


def test_live_refresh_preserves_in_memory_quality(qapp):
    """In-memory quality selection survives a second update_data call."""
    cfg = _make_config(filter_included_qualities=["HD", "SD"])
    panel = _build_panel(qapp, cfg)

    panel.update_data(_make_stats())

    # User narrows to SD only
    panel._quality_sec.restore_selection({"SD"})

    panel.update_data(_make_stats())

    selected = set(panel._quality_sec.get_selected_keys())
    assert selected == {"SD"}, (
        "live-refresh: in-memory 'SD' selection must survive update_data; "
        f"got {selected!r}"
    )


# ---------------------------------------------------------------------------
# 3. Genre fresh-install: no saved selection → select all
# ---------------------------------------------------------------------------

def test_genre_fresh_install_selects_all(qapp):
    """When no genre selection is persisted, update_data must select all genres."""
    cfg = _make_config(filter_included_genres=[])  # nothing saved
    panel = _build_panel(qapp, cfg)

    panel.update_data(_make_stats(genre_counts={"Action": 10, "Drama": 5, "Comedy": 3}))

    selected = set(panel._genre_sec.get_selected_keys())
    assert selected == {"Action", "Drama", "Comedy"}, (
        "fresh install: all genres should be selected when nothing is persisted; "
        f"got {selected!r}"
    )


# ---------------------------------------------------------------------------
# 4. Startup Untagged: persisted filter_untagged_selected applied by update_data
# ---------------------------------------------------------------------------

def test_startup_untagged_selection_applied(qapp):
    """On first update_data, saved untagged selection is restored from config."""
    # Save only "no_prefix" (hide unknowns for quality)
    cfg = _make_config(filter_untagged_selected=["no_prefix"])
    panel = _build_panel(qapp, cfg)

    panel.update_data(_make_stats())

    selected = set(panel._untagged_sec.get_selected_keys())
    assert selected == {"no_prefix"}, (
        "startup: only the saved untagged key 'no_prefix' should be selected; "
        f"got {selected!r}"
    )


# ---------------------------------------------------------------------------
# 5. Clobber regression — save_state() before update_data() must NOT wipe
#    persisted dynamic-section config attrs with empty selections.
# ---------------------------------------------------------------------------

def test_early_save_state_does_not_clobber_language(qapp):
    """save_state() called before update_data() must leave filter_included_languages intact.

    Regression: MainWindow.restore_search_state() (and any early filter_changed) could
    fire _on_changed → save_state() while Language/Region/etc. had no items yet.
    get_selected_keys() returns [] for empty sections, so config.filter_included_languages
    would be overwritten with [] before update_data() ran — silently wiping the saved
    subset.  The _stats_loaded guard prevents this.
    """
    cfg = _make_config(filter_included_languages=["FR"])  # persisted subset
    panel = _build_panel(qapp, cfg)

    # Simulate an early filter_changed → save_state() before update_data()
    panel.save_state()

    # The persisted value must be untouched — NOT emptied
    assert cfg.filter_included_languages == ["FR"], (
        "early save_state() must not clobber filter_included_languages; "
        f"got {cfg.filter_included_languages!r}"
    )


def test_early_save_state_does_not_clobber_regions(qapp):
    """save_state() before update_data() must leave filter_included_regions intact."""
    cfg = _make_config(filter_included_regions=["CA"])
    panel = _build_panel(qapp, cfg)

    panel.save_state()

    assert cfg.filter_included_regions == ["CA"], (
        "early save_state() must not clobber filter_included_regions; "
        f"got {cfg.filter_included_regions!r}"
    )


def test_early_save_state_does_not_clobber_qualities(qapp):
    """save_state() before update_data() must leave filter_included_qualities intact."""
    cfg = _make_config(filter_included_qualities=["HD"])
    panel = _build_panel(qapp, cfg)

    panel.save_state()

    assert cfg.filter_included_qualities == ["HD"], (
        "early save_state() must not clobber filter_included_qualities; "
        f"got {cfg.filter_included_qualities!r}"
    )


def test_early_save_state_does_not_clobber_platforms(qapp):
    """save_state() before update_data() must leave filter_included_platforms intact."""
    cfg = _make_config(filter_included_platforms=["Netflix"])
    panel = _build_panel(qapp, cfg)

    panel.save_state()

    assert cfg.filter_included_platforms == ["Netflix"], (
        "early save_state() must not clobber filter_included_platforms; "
        f"got {cfg.filter_included_platforms!r}"
    )


def test_early_save_state_does_not_clobber_genres(qapp):
    """save_state() before update_data() must leave filter_included_genres intact."""
    cfg = _make_config(filter_included_genres=["Drama"])
    panel = _build_panel(qapp, cfg)

    panel.save_state()

    assert cfg.filter_included_genres == ["Drama"], (
        "early save_state() must not clobber filter_included_genres; "
        f"got {cfg.filter_included_genres!r}"
    )


def test_clobber_then_update_data_restores_language(qapp):
    """After an early save_state() (would have clobbered), update_data() still restores the saved subset.

    The full clobber scenario end-to-end: construct panel (empty dynamic sections),
    call save_state() (simulating early filter_changed), then call update_data().
    The language section must end up with the persisted subset, not all items selected.
    """
    cfg = _make_config(filter_included_languages=["FR"])
    panel = _build_panel(qapp, cfg)

    # Simulate early save (before update_data)
    panel.save_state()

    # Now update_data runs (as it does at startup after the channel load finishes)
    panel.update_data(_make_stats())

    selected = set(panel._lang_sec.get_selected_keys())
    assert selected == {"FR"}, (
        "after early save_state() + update_data(), language section must restore "
        f"the persisted 'FR' subset; got {selected!r}"
    )


def test_normal_save_after_update_data_writes_correctly(qapp):
    """After update_data() populates sections, save_state() must write the current selection.

    Verifies the happy path is unaffected by the clobber guard: once _stats_loaded
    is True, save_state() must update config attrs normally.
    """
    cfg = _make_config(filter_included_languages=["EN", "FR"])
    panel = _build_panel(qapp, cfg)
    panel.update_data(_make_stats())

    # User narrows to FR only
    panel._lang_sec.restore_selection({"FR"})
    panel.save_state()

    assert cfg.filter_included_languages == ["FR"], (
        "after update_data(), save_state() must write the current selection; "
        f"got {cfg.filter_included_languages!r}"
    )


# ---------------------------------------------------------------------------
# 6. Startup reload signal — update_data emits filter_changed on first call only
# ---------------------------------------------------------------------------

def test_update_data_emits_filter_changed_on_first_call(qapp):
    """First update_data() call emits filter_changed exactly once.

    Regression being guarded: restore_search_state fires load_channels BEFORE
    update_data() has populated and restored the dynamic sections, so the initial
    channel list has no dynamic filters applied even though the chips show the
    correct state.  The fix emits filter_changed at the end of the first
    update_data() so MainWindow re-runs load_channels with restored filters.
    """
    cfg = _make_config(filter_included_languages=["FR"])
    panel = _build_panel(qapp, cfg)

    emitted: list[None] = []
    panel.filter_changed.connect(lambda: emitted.append(None))

    panel.update_data(_make_stats())

    assert len(emitted) == 1, (
        "first update_data() must emit filter_changed exactly once; "
        f"emitted {len(emitted)} time(s)"
    )
    # Also verify the language section was actually restored to the saved subset
    selected = set(panel._lang_sec.get_selected_keys())
    assert selected == {"FR"}, (
        "language section must reflect the saved subset when filter_changed fires; "
        f"got {selected!r}"
    )


def test_update_data_does_not_emit_filter_changed_on_second_call(qapp):
    """Second update_data() call (e.g. source refresh) must NOT emit filter_changed.

    A spurious reload on refresh would discard any context-filter chip the user had
    active, and the list already reflects the live in-memory selection.
    """
    cfg = _make_config(filter_included_languages=["EN"])
    panel = _build_panel(qapp, cfg)

    # First call — startup; expected to emit once
    first_emitted: list[None] = []
    panel.filter_changed.connect(lambda: first_emitted.append(None))
    panel.update_data(_make_stats())
    assert len(first_emitted) == 1, "sanity: first call must emit"

    # Disconnect and wire a new counter for the second call
    panel.filter_changed.disconnect()
    second_emitted: list[None] = []
    panel.filter_changed.connect(lambda: second_emitted.append(None))

    # User changed selection since first call
    panel._lang_sec.restore_selection({"FR"})

    # Second call — source refresh
    panel.update_data(_make_stats())

    assert len(second_emitted) == 0, (
        "second update_data() must NOT emit filter_changed; "
        f"emitted {len(second_emitted)} time(s)"
    )
    # In-memory selection must be preserved
    selected = set(panel._lang_sec.get_selected_keys())
    assert selected == {"FR"}, (
        "in-memory 'FR' selection must survive second update_data; "
        f"got {selected!r}"
    )
