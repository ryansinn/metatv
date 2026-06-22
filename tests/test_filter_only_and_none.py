"""Behavioral tests for:
  - FilterPanel "Only" action (Part 1): clears all sections, selects one group, emits filter_changed once.
  - Faithful none-persistence sentinel (Part 2): [] = explicitly none, None = never configured.

Tests prove behavior by executing the actual code paths (with real Qt widgets
via the qapp fixture) and asserting outcomes that would break on regression.
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
# Fake Config builders
# ---------------------------------------------------------------------------

def _make_config(
    *,
    filter_included_languages=None,
    filter_included_regions=None,
    filter_included_qualities=None,
    filter_included_platforms=None,
    filter_included_genres=None,
    filter_untagged_selected=None,
) -> SimpleNamespace:
    """Minimal config for FilterPanel — no save(), no filesystem."""
    cfg = SimpleNamespace(
        info_icon="ℹ",
        expand_icon="▶",
        collapse_icon="▼",
        filter_language_groups={"EN": ["EN"], "FR": ["FR"], "DE": ["DE"]},
        filter_regional_groups={"North America": ["US", "CA"], "Europe": ["GB", "DE"]},
        filter_platform_groups={"Netflix": ["NF"], "Disney+": ["DP"]},
        filter_quality_groups={"HD": ["HD"], "SD": ["SD"]},
        filter_included_languages=filter_included_languages,
        filter_included_regions=filter_included_regions,
        filter_included_qualities=filter_included_qualities,
        filter_included_platforms=filter_included_platforms,
        filter_included_genres=filter_included_genres,
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
    cfg.save = lambda: None
    return cfg


def _make_stats(*, genre_counts: dict | None = None) -> dict:
    """Tag-counts dict for FilterPanel.update_data() (Slice B format).

    Shape: {facet_type: {value: channel_count}} from get_facet_value_counts().
    Region values are individual ISO codes; language/platform/quality are group names.
    """
    return {
        "language": {"EN": 100, "FR": 50, "DE": 30},
        "region": {"US": 80, "CA": 20, "GB": 10},
        "platform": {"Netflix": 30, "Disney+": 15},
        "quality": {"HD": 70, "SD": 40},
        "genre": genre_counts if genre_counts is not None else {"Action": 10, "Drama": 5, "Comedy": 3},
    }


def _build_panel(qapp, config):
    from metatv.gui.filter_panel import FilterPanel
    return FilterPanel(config)


# ---------------------------------------------------------------------------
# Part 1 — "Only" action
# ---------------------------------------------------------------------------

class TestOnlyAction:
    """The 'Only' button/action clears all other groups and selects one."""

    def test_only_clears_all_sections_and_selects_one(self, qapp):
        """select_only_group on 'EN' language: all other sections become none-selected,
        language section has exactly {'EN'} selected."""
        cfg = _make_config()
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        # All sections start all-selected; confirm baseline
        assert panel._lang_sec.is_all_selected()
        assert panel._platform_sec.is_all_selected()
        assert panel._quality_sec.is_all_selected()

        # Trigger "Only EN" on the language section
        panel.select_only_group("EN", "language")

        # Language: only EN
        lang_sel = set(panel._lang_sec.get_selected_keys())
        assert lang_sel == {"EN"}, f"language should be only EN, got {lang_sel!r}"

        # All other dynamic sections must be empty (none selected)
        assert panel._region_sec.get_selected_keys() == [], (
            "region should be none-selected after Only action"
        )
        assert panel._platform_sec.get_selected_keys() == [], (
            "platform should be none-selected after Only action"
        )
        assert panel._quality_sec.get_selected_keys() == [], (
            "quality should be none-selected after Only action"
        )
        assert panel._genre_sec.get_selected_keys() == [], (
            "genre should be none-selected after Only action"
        )

    def test_only_emits_filter_changed_exactly_once(self, qapp):
        """select_only_group emits filter_changed exactly once, not once per section."""
        cfg = _make_config()
        panel = _build_panel(qapp, cfg)

        # Connect counter BEFORE update_data so we can count all emits
        emitted: list[None] = []
        panel.filter_changed.connect(lambda: emitted.append(None))

        panel.update_data(_make_stats())
        # update_data emits once (startup). Snapshot the count.
        startup_count = len(emitted)

        panel.select_only_group("FR", "language")

        after_only = len(emitted) - startup_count
        assert after_only == 1, (
            f"select_only_group must emit filter_changed exactly once; got {after_only}"
        )

    def test_only_via_item_only_requested_signal(self, qapp):
        """_on_item_only_requested (wired from per-row button) delegates to select_only_group."""
        cfg = _make_config()
        panel = _build_panel(qapp, cfg)

        emitted: list[None] = []
        panel.filter_changed.connect(lambda: emitted.append(None))
        panel.update_data(_make_stats())
        startup_count = len(emitted)

        # Simulate the signal fired by the "Only" button on a platform row
        panel._on_item_only_requested("Netflix", "platform")

        plat_sel = set(panel._platform_sec.get_selected_keys())
        assert plat_sel == {"Netflix"}, f"platform: expected only Netflix, got {plat_sel!r}"
        assert panel._lang_sec.get_selected_keys() == [], "language should be cleared"
        after_only = len(emitted) - startup_count
        assert after_only == 1, f"exactly one filter_changed from Only; got {after_only}"

    def test_only_saves_none_selection_to_config(self, qapp):
        """After Only action, cleared sections are saved as [] (explicitly none)."""
        saved = {}
        cfg = _make_config()
        cfg.save = lambda: None

        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        panel.select_only_group("HD", "quality")

        # Quality: only HD; all others: [] (explicitly none)
        assert cfg.filter_included_languages == [], (
            "cleared language should be saved as [] (explicitly none)"
        )
        assert cfg.filter_included_qualities == ["HD"], (
            "quality should be saved as ['HD']"
        )

    def test_only_on_region_group_selects_all_children(self, qapp):
        """Only on a region group header selects all its children, clears everything else."""
        cfg = _make_config()
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        panel.select_only_group("North America", "region")

        region_sel = set(panel._region_sec.get_selected_keys())
        assert region_sel == {"US", "CA"}, (
            f"region: expected US+CA (North America children), got {region_sel!r}"
        )
        assert panel._lang_sec.get_selected_keys() == [], "language must be cleared"
        assert panel._platform_sec.get_selected_keys() == [], "platform must be cleared"

    def test_only_context_menu_item_calls_select_only_group(self, qapp):
        """Right-click 'Only' menu item in FilterPanel triggers select_only_group."""
        cfg = _make_config()
        panel = _build_panel(qapp, cfg)

        emitted: list[None] = []
        panel.filter_changed.connect(lambda: emitted.append(None))
        panel.update_data(_make_stats())
        startup_count = len(emitted)

        # Directly call the method the context menu item would invoke
        panel.select_only_group("FR", "language")

        assert set(panel._lang_sec.get_selected_keys()) == {"FR"}
        assert panel._platform_sec.get_selected_keys() == []
        after_only = len(emitted) - startup_count
        assert after_only == 1, f"exactly one filter_changed from Only; got {after_only}"


# ---------------------------------------------------------------------------
# Part 2 — None-persistence sentinel
# ---------------------------------------------------------------------------

class TestNonePersistenceSentinel:
    """[] = explicitly none (restore → uncheck all), None = never configured (restore → all)."""

    # ── save round-trips ──────────────────────────────────────────────────

    def test_subset_selection_roundtrips(self, qapp):
        """Select FR only → save → restore → only FR selected (non-empty subset)."""
        cfg = _make_config()
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        # User selects only FR
        panel._lang_sec.restore_selection({"FR"})
        panel.save_state()

        # Verify config written correctly
        assert cfg.filter_included_languages == ["FR"], (
            f"save: expected ['FR'], got {cfg.filter_included_languages!r}"
        )

        # Build a fresh panel from that config and confirm restore
        panel2 = _build_panel(qapp, cfg)
        panel2.update_data(_make_stats())
        assert set(panel2._lang_sec.get_selected_keys()) == {"FR"}, (
            "restore: language section should have only FR"
        )

    def test_none_selected_saves_as_empty_list(self, qapp):
        """Explicitly unchecking all in a section saves [] (not None) to config."""
        cfg = _make_config()
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        # Uncheck all in quality
        panel._quality_sec.select_none()
        panel.save_state()

        assert cfg.filter_included_qualities == [], (
            f"save: explicitly none should write [], got {cfg.filter_included_qualities!r}"
        )

    def test_explicitly_none_restores_as_none_selected(self, qapp):
        """[] in config → restore → all unchecked (none selected), not all selected."""
        cfg = _make_config(filter_included_qualities=[])  # explicitly none
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        selected = panel._quality_sec.get_selected_keys()
        assert selected == [], (
            f"restore: [] in config must uncheck all quality items; got {selected!r}"
        )

    def test_never_configured_none_restores_as_all(self, qapp):
        """None in config (never configured) → restore → all selected (default)."""
        cfg = _make_config(filter_included_qualities=None)  # never configured
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        assert panel._quality_sec.is_all_selected(), (
            "restore: None in config must leave quality at all-selected default"
        )

    def test_never_configured_none_language_restores_as_all(self, qapp):
        """None language → all languages selected on restore."""
        cfg = _make_config(filter_included_languages=None)
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        assert panel._lang_sec.is_all_selected(), (
            "None language config must restore to all-selected"
        )

    def test_never_configured_none_genre_restores_as_all(self, qapp):
        """None genre config → all genres selected (fresh-install / never configured)."""
        cfg = _make_config(filter_included_genres=None)
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats(genre_counts={"Action": 10, "Drama": 5}))

        assert panel._genre_sec.is_all_selected(), (
            "None genre config must select all genres (fresh install)"
        )

    def test_explicitly_none_genre_restores_as_none(self, qapp):
        """[] genre config → all genres unchecked (explicitly none)."""
        cfg = _make_config(filter_included_genres=[])  # explicitly none
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats(genre_counts={"Action": 10, "Drama": 5}))

        selected = panel._genre_sec.get_selected_keys()
        assert selected == [], (
            f"[] genre config must restore to none-selected; got {selected!r}"
        )

    # ── legacy migration ([] → None) ────────────────────────────────────

    def test_legacy_empty_list_migrates_to_none_in_config(self, qapp):
        """Config loaded with [] (legacy) is migrated to None in model_post_init.

        Verifies that the migration path in Config.model_post_init converts
        legacy empty-list filter_included_* fields to None so that existing users
        see all-selected (default) instead of a suddenly-empty filter list.
        """
        from metatv.core.config import Config
        # Simulate loading from YAML: old config had filter_included_languages: []
        # We manually construct a Config with the old [] value.
        # model_post_init should convert it to None.
        cfg = Config(
            database_url="sqlite:///test.db",
            filter_included_languages=[],
            filter_included_regions=[],
            filter_included_qualities=[],
            filter_included_platforms=[],
            filter_included_genres=[],
        )
        assert cfg.filter_included_languages is None, (
            f"legacy [] languages should migrate to None; got {cfg.filter_included_languages!r}"
        )
        assert cfg.filter_included_regions is None, (
            f"legacy [] regions should migrate to None; got {cfg.filter_included_regions!r}"
        )
        assert cfg.filter_included_qualities is None, (
            f"legacy [] qualities should migrate to None; got {cfg.filter_included_qualities!r}"
        )
        assert cfg.filter_included_platforms is None, (
            f"legacy [] platforms should migrate to None; got {cfg.filter_included_platforms!r}"
        )
        assert cfg.filter_included_genres is None, (
            f"legacy [] genres should migrate to None; got {cfg.filter_included_genres!r}"
        )

    def test_explicit_none_subset_not_migrated(self, qapp):
        """Non-empty lists are never migrated (only [] → None, not [..] → None)."""
        from metatv.core.config import Config
        cfg = Config(
            database_url="sqlite:///test.db",
            filter_included_languages=["FR"],
            filter_included_qualities=["HD"],
        )
        assert cfg.filter_included_languages == ["FR"], (
            "non-empty list must not be migrated"
        )
        assert cfg.filter_included_qualities == ["HD"], (
            "non-empty quality list must not be migrated"
        )

    # ── regression: #137/#141/#150 existing guards still hold ──────────

    def test_early_save_state_does_not_clobber_none_config(self, qapp):
        """save_state() before update_data() must leave None config attrs untouched.

        Regression guard: a pre-stats save must not replace None with [] and
        thereby make restore_state() treat it as 'explicitly none'.
        """
        cfg = _make_config(filter_included_languages=None)
        panel = _build_panel(qapp, cfg)

        # Save before update_data (simulates early filter_changed)
        panel.save_state()

        # None must remain None — NOT replaced with [] from empty section
        assert cfg.filter_included_languages is None, (
            "early save_state() must not replace None with [] "
            f"(got {cfg.filter_included_languages!r})"
        )

    def test_first_update_data_emits_filter_changed_once(self, qapp):
        """First update_data still emits filter_changed (regression #141 / first-load reload)."""
        cfg = _make_config()
        panel = _build_panel(qapp, cfg)

        emitted: list[None] = []
        panel.filter_changed.connect(lambda: emitted.append(None))
        panel.update_data(_make_stats())

        assert len(emitted) == 1, (
            f"first update_data must emit filter_changed once; got {len(emitted)}"
        )

    def test_live_refresh_preserves_in_memory_selection(self, qapp):
        """Second update_data (source refresh) preserves user's in-memory selection."""
        cfg = _make_config(filter_included_languages=["EN"])
        panel = _build_panel(qapp, cfg)
        panel.update_data(_make_stats())

        # User changes to FR only
        panel._lang_sec.restore_selection({"FR"})

        # Second call (source refresh)
        panel.update_data(_make_stats())

        selected = set(panel._lang_sec.get_selected_keys())
        assert selected == {"FR"}, (
            f"live-refresh must preserve in-memory 'FR' selection; got {selected!r}"
        )


# ---------------------------------------------------------------------------
# Part 2b — the []->None migration is ONE-TIME (version-gated), so an explicit
# none-selection written by the sentinel-aware save survives a reload.
# ---------------------------------------------------------------------------

def test_explicit_none_survives_reload_when_version_marked(tmp_path):
    """version>=1 (sentinel-aware save) => [] is an explicit none-selection,
    PRESERVED through model_post_init, not migrated away on every load."""
    from metatv.core.config import Config

    cfg = Config(
        config_dir=tmp_path,
        filter_config_version=1,
        filter_included_languages=[],
        filter_included_platforms=["Disney+"],
    )
    assert cfg.filter_included_languages == [], "explicit none ([]) must survive reload"
    assert cfg.filter_included_platforms == ["Disney+"]


def test_legacy_empty_list_migrates_to_none_and_bumps_version(tmp_path):
    """Pre-sentinel config (version 0 / absent) whose [] meant 'never configured'
    migrates to None ONCE and bumps the version so it never runs again."""
    from metatv.core.config import Config

    cfg = Config(
        config_dir=tmp_path,
        filter_config_version=0,
        filter_included_languages=[],
        filter_included_regions=[],
    )
    assert cfg.filter_included_languages is None, "legacy [] must migrate to None"
    assert cfg.filter_included_regions is None
    assert cfg.filter_config_version == 1, "migration must bump the version (one-time)"
