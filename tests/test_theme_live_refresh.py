"""Behavioral tests for the live theme-switch gaps closed in this slice
(What's New #251): the sidebar Settings button / bottom nav bar background /
"showing hidden" label / context-filter-chip dismiss button promoted from
``setup_ui()`` locals to ``self.*`` attrs, and ``FilterPanel`` (the middle
filter column) gaining its own ``refresh_theme()`` that recurses into every
``_Section``/``_GroupRow``/``_ItemRow``/``_TriCheckbox`` it built.

Also covers What's New #261: the six persistent, ``setVisible()``-toggled
content views (EPG, Discover, Recipe, Preferences/Recommended, Provider
editor, Sources manager) that used to need an app restart to re-theme. A
QPalette floor landed on ``main`` first (``theme.qt_palette()``, pushed by
``theme.apply_theme()``) and gives every UNSTYLED widget a themed floor for
free, but every widget in these six views that calls ``setStyleSheet()``
explicitly still bakes a string that doesn't track a token live — verified
empirically (none of the six were fixed "for free" by the palette). Each view
gained its own ``refresh_theme()`` covering the chrome it styles once at
construction, following the same pattern as ``details_pane.py``/
``filter_panel.py``/``filter_group_row.py``.

Covers:
1. ``FilterPanel.refresh_theme()`` actually changes the panel's own cached
   stylesheet AND a static section's row-level widgets (checkbox, label,
   "Only" button) after a live palette switch — proving the recursion reaches
   real row objects, not just the panel's own chrome.
2. ``MainWindow.refresh_theme()`` sweeps the 4 promoted widgets + calls
   ``filter_panel.refresh_theme()`` — extends the existing fake-``self``
   pattern from ``test_theme_palettes.py``.
3. Each of the six views' ``refresh_theme()`` actually changes a real,
   constructed widget's resolved stylesheet after a live palette switch —
   and, for the views with child widgets exposing their own
   ``refresh_theme()`` (Recipe → recipe bar / tag cloud; Provider editor →
   icon picker; Sources manager → embedded provider editor), that the
   recursion reaches those children too.
4. ``MainWindow.refresh_theme()``'s sweep calls each of the six views'
   ``refresh_theme()`` when present.

Every test executes the changed path and asserts an outcome that would break
if the sweep regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.gui import theme
from metatv.gui import theme_palettes as tp
from metatv.gui.filter_panel import FilterPanel
from metatv.gui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _reset_active_theme():
    """Same isolation as test_theme_palettes.py — theme.py's active palette
    is process-global module state."""
    theme.apply_theme("Midnight")
    yield
    theme.apply_theme("Midnight")


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config() -> SimpleNamespace:
    """Minimal config for FilterPanel — no save(), no filesystem, no
    persisted selections (every ``filter_known_*``/``filter_included_*``
    stays None so restore_state()/save_state() are no-ops)."""
    cfg = SimpleNamespace(
        filter_known_languages=None, filter_known_regions=None,
        filter_known_qualities=None, filter_known_platforms=None,
        filter_known_genres=None, filter_known_categories=None,
        filter_known_subtitles=None, filter_known_dubs=None,
        filter_known_formats=None,
        info_icon="i", expand_icon=">", collapse_icon="v",
        filter_language_groups={}, filter_regional_groups={},
        filter_platform_groups={}, filter_quality_groups={},
        filter_included_languages=None, filter_included_regions=None,
        filter_included_qualities=None, filter_included_platforms=None,
        filter_included_categories=None, filter_included_genres=None,
        filter_included_subtitles=None, filter_included_dubs=None,
        filter_included_formats=None,
        filter_untagged_selected=None, filter_enabled_media_types=None,
        filter_section_states={}, filter_hide_watched=False,
        filter_adult_mode="hide",
    )
    cfg.save = lambda: None
    return cfg


class TestFilterPanelRefreshTheme:
    def test_refresh_theme_restyles_panel_chrome(self, qapp):
        panel = FilterPanel(_make_config())
        midnight_style = panel.styleSheet()
        assert theme.COLOR_BG_SECTION in midnight_style

        theme.apply_theme("Daylight")
        panel.refresh_theme()

        assert theme.COLOR_BG_SECTION in panel.styleSheet()
        assert panel.styleSheet() != midnight_style
        # Daylight's COLOR_BG_SECTION differs from Midnight's — prove the
        # cached stylesheet string actually picked up the NEW value, not
        # just that setStyleSheet() was called again with the same text.
        from metatv.gui import theme_palettes as tp
        assert tp.DAYLIGHT["COLOR_BG_SECTION"] in panel.styleSheet()
        assert tp.MIDNIGHT["COLOR_BG_SECTION"] not in panel.styleSheet()

    def test_refresh_theme_recurses_into_static_section_rows(self, qapp):
        """The Media section is populated in __init__ (set_flat_items), so
        its _ItemRow children exist before any update_data() call — proving
        refresh_theme()'s recursion reaches real row widgets, not just the
        section header, without needing to fake a stats query.
        """
        panel = FilterPanel(_make_config())
        row = panel._media_sec._rows[0]
        midnight_label_style = row._label.styleSheet()
        assert theme.COLOR_TEXT in midnight_label_style

        theme.apply_theme("Daylight")
        panel.refresh_theme()

        from metatv.gui import theme_palettes as tp
        assert tp.DAYLIGHT["COLOR_TEXT"] in row._label.styleSheet()
        assert row._label.styleSheet() != midnight_label_style
        # The checkbox and "Only" button (theme.FILTER_CHECKBOX /
        # theme.FILTER_ONLY_BTN semantic constants) were also re-applied.
        assert row._cb.styleSheet() == theme.FILTER_CHECKBOX
        assert row._only_btn.styleSheet() == theme.FILTER_ONLY_BTN


class TestMainWindowRefreshThemeSweepsPromotedWidgets:
    """Mirrors test_theme_palettes.py's fake-``self`` pattern — a bound
    method invoked against a SimpleNamespace standing in for MainWindow, so
    no real window/DB/EPG machinery has to be constructed.
    """

    def test_sweeps_promoted_locals_and_filter_panel(self, qapp):
        settings_btn = MagicMock()
        bottom_nav_bar = MagicMock()
        hidden_banner_lbl = MagicMock()
        context_filter_dismiss_btn = MagicMock()
        filter_panel = MagicMock()

        fake_self = SimpleNamespace(
            config=SimpleNamespace(theme_name="Daylight"),
            _settings_btn=settings_btn,
            _bottom_nav_bar=bottom_nav_bar,
            _hidden_banner_lbl=hidden_banner_lbl,
            _context_filter_dismiss_btn=context_filter_dismiss_btn,
            filter_panel=filter_panel,
        )

        MainWindow.refresh_theme(fake_self)

        settings_btn.setStyleSheet.assert_called_once_with(theme.FLAT_NAV_BTN)
        bottom_nav_bar.setStyleSheet.assert_called_once()
        hidden_banner_lbl.setStyleSheet.assert_called_once()
        context_filter_dismiss_btn.setStyleSheet.assert_called_once_with(
            theme.CONTEXT_FILTER_CHIP_BTN
        )
        filter_panel.refresh_theme.assert_called_once()

    def test_tolerates_missing_promoted_attrs(self, qapp):
        """A fake_self with none of the new attrs must not raise — every
        new sweep block is hasattr-gated, same as the pre-existing ones."""
        fake_self = SimpleNamespace(config=SimpleNamespace(theme_name="Graphite"))

        MainWindow.refresh_theme(fake_self)  # must not raise

        assert theme.current_theme() == "Graphite"

    def test_sweeps_the_six_content_views(self, qapp):
        """#261: the six persistent content views (EPG/Preferences/Discover/
        Recipe/Provider-editor/Sources-manager) each get their
        ``refresh_theme()`` called by the sweep when present — proving the
        wiring MainWindow.refresh_theme() added, not just that the views'
        own refresh_theme() methods exist (covered per-view below)."""
        epg_view = MagicMock()
        preferences_view = MagicMock()
        discover_view = MagicMock()
        recipe_view = MagicMock()
        provider_editor = MagicMock()
        sources_manager_view = MagicMock()

        fake_self = SimpleNamespace(
            config=SimpleNamespace(theme_name="Daylight"),
            epg_view=epg_view,
            preferences_view=preferences_view,
            discover_view=discover_view,
            recipe_view=recipe_view,
            provider_editor=provider_editor,
            sources_manager_view=sources_manager_view,
        )

        MainWindow.refresh_theme(fake_self)

        epg_view.refresh_theme.assert_called_once()
        preferences_view.refresh_theme.assert_called_once()
        discover_view.refresh_theme.assert_called_once()
        recipe_view.refresh_theme.assert_called_once()
        provider_editor.refresh_theme.assert_called_once()
        sources_manager_view.refresh_theme.assert_called_once()

    def test_tolerates_missing_content_views(self, qapp):
        """A fake_self with none of the six content-view attrs must not
        raise — the new sweep loop uses ``getattr(..., None)`` + a
        ``hasattr(view, "refresh_theme")`` guard, same defensive shape as
        every other hasattr-gated block in this method."""
        fake_self = SimpleNamespace(config=SimpleNamespace(theme_name="Midnight"))

        MainWindow.refresh_theme(fake_self)  # must not raise


# ---------------------------------------------------------------------------
# #261 — per-view refresh_theme() on the six previously-restart-only views.
# Each test builds the REAL view, switches the palette, calls the view's own
# refresh_theme() directly (not through MainWindow — that wiring is covered
# above), and asserts a real constructed widget's resolved stylesheet picked
# up the NEW palette's token value and no longer carries the OLD one.
# ---------------------------------------------------------------------------

class TestDiscoverViewRefreshTheme:
    def test_refresh_theme_restyles_loading_label(self, qapp, tmp_path):
        from metatv.core.config import Config
        from metatv.gui.discover_view import DiscoverView
        from PyQt6.QtCore import QObject, pyqtSignal

        class _FakeImageCache(QObject):
            image_loaded = pyqtSignal(str, object)
            image_failed = pyqtSignal(str, str)

            def get_image_async(self, url):
                pass

        config = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                         cache_dir=tmp_path / "cache")
        theme.apply_theme("Midnight")
        view = DiscoverView(MagicMock(), config, _FakeImageCache(), None)
        midnight_style = view._loading_lbl.styleSheet()
        assert tp.MIDNIGHT["COLOR_MUTED_2"] in midnight_style

        theme.apply_theme("Daylight")
        view.refresh_theme()

        after = view._loading_lbl.styleSheet()
        assert tp.DAYLIGHT["COLOR_MUTED_2"] in after
        assert tp.MIDNIGHT["COLOR_MUTED_2"] not in after
        assert after != midnight_style


class TestEpgViewRefreshTheme:
    def test_refresh_theme_restyles_stale_notice(self, qapp, tmp_path):
        from metatv.core.config import Config
        from metatv.gui.epg_view import EpgView

        config = Config(config_dir=tmp_path)
        theme.apply_theme("Midnight")
        view = EpgView(config, db=MagicMock(), epg_manager=MagicMock())
        try:
            midnight_style = view._stale_epg_notice.styleSheet()
            assert midnight_style == theme.EPG_STALE_NOTICE

            theme.apply_theme("Daylight")
            view.refresh_theme()

            after = view._stale_epg_notice.styleSheet()
            assert after == theme.EPG_STALE_NOTICE
            assert after != midnight_style
            # Also proves the Browse-tab scrubber label (a promoted local var,
            # epg_browse_mixin.py) is reached by the same call.
            assert view._anchor_label.styleSheet() == theme.LABEL_MUTED
        finally:
            view._executor.shutdown(wait=False)


class TestRecipeViewRefreshTheme:
    def _make_view(self, qapp):
        from metatv.gui.recipe_view import RecipeView
        from PyQt6.QtCore import QObject, pyqtSignal

        class _FakeSeam:
            def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
                pass

        class _FakeConfig:
            discover_zoom = 1.0
            global_filter_paused = True
            saved_recipes: list = []
            movie_icon = "M"
            series_icon = "S"
            rating_star_icon = "*"
            like_icon = "L"
            favorite_icon = "F"
            queue_icon = "Q"
            watched_icon = "W"
            list_view_icon = "="
            grid_view_icon = "#"

            def save(self):
                pass

        class _FakeImageCache(QObject):
            image_loaded = pyqtSignal(str, object)
            image_failed = pyqtSignal(str, str)

            def get_image_async(self, url):
                pass

        return RecipeView(
            db=object(), config=_FakeConfig(), run_query_fn=_FakeSeam()._run_query,
            image_cache=_FakeImageCache(), parent=None,
        )

    def test_refresh_theme_restyles_own_chrome_and_recurses_into_children(self, qapp):
        theme.apply_theme("Midnight")
        view = self._make_view(qapp)
        midnight_back_btn = view._back_to_clusters_btn.styleSheet()
        midnight_save_btn = view._recipe_bar.save_btn.styleSheet()
        midnight_cloud_hdr = view._cloud._header_lbl.styleSheet()
        assert midnight_back_btn == theme.RECIPE_BACK_TO_GRID_BTN
        assert midnight_save_btn == theme.RECIPE_BAR_SAVE_BTN
        assert midnight_cloud_hdr == theme.CLOUD_HEADER_LABEL

        theme.apply_theme("Daylight")
        view.refresh_theme()

        # Own chrome, styled once in RecipeView._build_recipe_tab.
        after_back_btn = view._back_to_clusters_btn.styleSheet()
        assert after_back_btn == theme.RECIPE_BACK_TO_GRID_BTN
        assert after_back_btn != midnight_back_btn

        # Recurses into _RecipeBar (recipe_bar_widgets.py) — a sibling module,
        # not RecipeView itself, proving the recursion reaches real children.
        after_save_btn = view._recipe_bar.save_btn.styleSheet()
        assert after_save_btn == theme.RECIPE_BAR_SAVE_BTN
        assert after_save_btn != midnight_save_btn

        # Recurses into WeightedTagCloud (weighted_tag_cloud.py) too.
        after_cloud_hdr = view._cloud._header_lbl.styleSheet()
        assert after_cloud_hdr == theme.CLOUD_HEADER_LABEL
        assert after_cloud_hdr != midnight_cloud_hdr


class TestProviderEditorViewRefreshTheme:
    @pytest.fixture()
    def file_db(self, tmp_path):
        from metatv.core.database import Database
        d = Database(f"sqlite:///{tmp_path / 'provider_editor_theme.db'}")
        d.create_tables()
        yield d
        d.close()

    def test_refresh_theme_restyles_own_chrome_and_recurses_into_icon_picker(
        self, qapp, tmp_path, file_db
    ):
        from metatv.core.config import Config
        from metatv.gui.provider_editor import ProviderEditorView

        config = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                         cache_dir=tmp_path / "cache")
        theme.apply_theme("Midnight")
        view = ProviderEditorView(file_db, config, MagicMock())
        midnight_action_btn = view._action_refresh_btn.styleSheet()
        midnight_icon_btn = view._icon_picker._btn.styleSheet()
        assert midnight_action_btn == theme.PANEL_BTN
        assert midnight_icon_btn == theme.ICON_PICK_MAIN_BTN

        theme.apply_theme("Daylight")
        view.refresh_theme()

        after_action_btn = view._action_refresh_btn.styleSheet()
        assert after_action_btn == theme.PANEL_BTN
        assert after_action_btn != midnight_action_btn

        # Recurses into ProviderIconPicker's own refresh_theme().
        after_icon_btn = view._icon_picker._btn.styleSheet()
        assert after_icon_btn == theme.ICON_PICK_MAIN_BTN
        assert after_icon_btn != midnight_icon_btn


class TestSourcesManagerViewRefreshTheme:
    @pytest.fixture()
    def file_db(self, tmp_path):
        from metatv.core.database import Database
        d = Database(f"sqlite:///{tmp_path / 'sources_manager_theme.db'}")
        d.create_tables()
        yield d
        d.close()

    def test_refresh_theme_restyles_own_chrome_and_forwards_to_provider_editor(
        self, qapp, tmp_path, file_db
    ):
        from metatv.core.config import Config
        from metatv.gui.provider_editor import ProviderEditorView
        from metatv.gui.sources_manager_view import SourcesManagerView

        config = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                         cache_dir=tmp_path / "cache")
        theme.apply_theme("Midnight")
        provider_editor = ProviderEditorView(file_db, config, MagicMock())
        view = SourcesManagerView(config, file_db, provider_editor, None)
        midnight_empty = view._empty_label.styleSheet()
        midnight_editor_btn = provider_editor._action_refresh_btn.styleSheet()
        assert midnight_empty == theme.EXPLORE_STATUS
        assert midnight_editor_btn == theme.PANEL_BTN

        theme.apply_theme("Daylight")
        view.refresh_theme()

        after_empty = view._empty_label.styleSheet()
        assert after_empty == theme.EXPLORE_STATUS
        # NOT asserted: that this string CHANGED. EXPLORE_STATUS paints on the
        # fixed-dark cinema shell (EXPLORE_VIEW_BG == COLOR_LIGHTBOX_BG), so it
        # is deliberately identical in every palette — a palette-tuned colour
        # there is the bug (Daylight's muted grey measured 4.33:1 on that dark
        # shell). "The string differs" was only ever a proxy for "refresh_theme
        # re-applied it"; the editor button below is a theme-VARYING role and
        # proves that directly.

        # Forwards to the embedded ProviderEditorView instance.
        after_editor_btn = provider_editor._action_refresh_btn.styleSheet()
        assert after_editor_btn == theme.PANEL_BTN
        assert after_editor_btn != midnight_editor_btn


class TestPreferencesViewRefreshTheme:
    @pytest.fixture()
    def file_db(self, tmp_path):
        from metatv.core.database import Database
        d = Database(f"sqlite:///{tmp_path / 'preferences_theme.db'}")
        d.create_tables()
        yield d
        d.close()

    def test_refresh_theme_restyles_mix_controls(self, qapp, tmp_path, file_db):
        from metatv.core.config import Config
        from metatv.gui.preferences_view import PreferencesView

        config = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                         cache_dir=tmp_path / "cache")
        theme.apply_theme("Midnight")
        view = PreferencesView(file_db, config, None)
        # COLOR_TEXT, not a hardcoded hex: this test is about refresh_theme()
        # re-applying the sheet, so it must track whichever token the widget
        # reads rather than pin a value a palette change would move.
        midnight_mix_label = view._mix_label.styleSheet()
        assert tp.MIDNIGHT["COLOR_TEXT"] in midnight_mix_label

        theme.apply_theme("Daylight")
        view.refresh_theme()

        after = view._mix_label.styleSheet()
        assert tp.DAYLIGHT["COLOR_TEXT"] in after
        assert tp.MIDNIGHT["COLOR_TEXT"] not in after
        assert after != midnight_mix_label
        # The Excluded/Version-Preferences collapsible toggles share one style
        # string — proves both were re-applied, not just the mix label.
        assert view._excl_toggle_btn.styleSheet() == view._ver_prefs_toggle_btn.styleSheet()
        assert tp.DAYLIGHT["COLOR_TEXT"] in view._excl_toggle_btn.styleSheet()
