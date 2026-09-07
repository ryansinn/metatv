"""A theme switch re-themes every view in place — asserted as an OUTCOME.

History, compressed, because this file has been rewritten twice for the same
reason:

* **#251** promoted four ``setup_ui()`` locals to ``self.*`` and gave
  ``FilterPanel`` its own ``refresh_theme()`` recursing into every
  ``_Section``/``_GroupRow``/``_ItemRow``/``_TriCheckbox``.
* **#261** gave each of the six persistent, ``setVisible()``-toggled content
  views (EPG, Discover, Recipe, Preferences, Provider editor, Sources manager)
  its own ``refresh_theme()`` too — a QPalette floor had landed on ``main``
  first and did NOT fix them, since every widget that calls ``setStyleSheet``
  bakes a string no token tracks.

Both were the same enumeration, and both left it broken: ~838 ``setStyleSheet``
call sites behind 22 ``refresh_theme()`` methods, and an enumeration never sees
what nobody remembered to add. **THEME-1 deleted all 22.** A widget styled
through ``theme.style``/``theme.style_fn`` registers itself at construction and
``theme.apply_theme()`` re-applies every live registration.

So these tests no longer call ``refresh_theme()`` — there is nothing to call.
They build the real view, switch the palette, and assert the widget now carries
the NEW palette's token value and no longer carries the old one. A test that
asserted ``hasattr(view, "refresh_theme")``, or patched it to prove it was
called, would be a shape test for a mechanism that is gone; those are deleted.
The last two tests assert RENDERED APPEARANCE — real painted pixels off
``QWidget.grab()`` — and were proven to fail with the registration suppressed.
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtGui import QColor

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


def _painted_colours(widget) -> Counter:
    """Every colour actually painted by *widget*, by pixel count.

    ``grab()`` runs the real paint path, so this is rendered appearance — not
    a parsed stylesheet, which passes for infinitely many wrong renderings.
    """
    image = widget.grab().toImage()
    tally: Counter = Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            tally[QColor(image.pixel(x, y)).name()] += 1
    return tally


def _icon_bytes(btn) -> bytes:
    """The raw ARGB bytes of a button's rendered icon — a QIcon bakes its
    colour, so this is the only evidence it was actually re-rendered."""
    image = btn.icon().pixmap(btn.iconSize()).toImage()
    return image.convertToFormat(image.Format.Format_ARGB32).bits().asstring(
        image.sizeInBytes()
    )


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


class TestFilterPanelFollowsAPaletteSwitch:
    def test_the_panel_chrome_carries_the_new_palette(self, qapp):
        panel = FilterPanel(_make_config())
        midnight_style = panel.styleSheet()
        assert tp.MIDNIGHT["COLOR_BG_SECTION"] in midnight_style

        theme.apply_theme("Daylight")

        assert tp.DAYLIGHT["COLOR_BG_SECTION"] in panel.styleSheet()
        assert tp.MIDNIGHT["COLOR_BG_SECTION"] not in panel.styleSheet()

    def test_it_reaches_row_widgets_the_panel_never_lists(self, qapp):
        """The Media section is populated in ``__init__`` (set_flat_items), so
        its ``_ItemRow`` children exist before any ``update_data()`` call.

        Nothing in ``FilterPanel`` knows these rows exist for styling purposes
        — that is the whole point. Each row registered itself when it was
        built, so the switch reaches it with no list anywhere.
        """
        panel = FilterPanel(_make_config())
        row = panel._media_sec._rows[0]
        assert tp.MIDNIGHT["COLOR_TEXT"] in row._label.styleSheet()

        theme.apply_theme("Daylight")

        assert tp.DAYLIGHT["COLOR_TEXT"] in row._label.styleSheet()
        assert tp.MIDNIGHT["COLOR_TEXT"] not in row._label.styleSheet()
        # The checkbox and "Only" button are whole role constants, so they
        # must equal the RECOMPOSED constant, not merely differ.
        assert row._cb.styleSheet() == theme.FILTER_CHECKBOX
        assert row._only_btn.styleSheet() == theme.FILTER_ONLY_BTN


class TestMainWindowAppliesTheConfiguredTheme:
    """``MainWindow.apply_configured_theme`` is all that is left of the sweep:
    it reads the name off ``config`` and repaints the channel list, whose row
    delegate reads ``theme.COLOR_*`` inside ``paint()``.

    Mirrors test_theme_palettes.py's fake-``self`` pattern — a bound method
    invoked against a SimpleNamespace, so no real window has to be built.
    """

    def test_it_applies_the_configured_palette(self, qapp):
        channels_list = MagicMock()
        fake_self = SimpleNamespace(
            config=SimpleNamespace(theme_name="Daylight"),
            channels_list=channels_list,
        )

        MainWindow.apply_configured_theme(fake_self)

        assert theme.current_theme() == "Daylight"
        assert theme.COLOR_TEXT == tp.DAYLIGHT["COLOR_TEXT"]
        channels_list.viewport.return_value.update.assert_called_once()

    def test_it_is_a_noop_when_the_palette_is_unchanged(self, qapp):
        """No repaint for a switch that isn't one — the channel list is the
        most expensive surface in the app to repaint."""
        channels_list = MagicMock()
        fake_self = SimpleNamespace(
            config=SimpleNamespace(theme_name="Midnight"),  # already active
            channels_list=channels_list,
        )

        MainWindow.apply_configured_theme(fake_self)

        channels_list.viewport.assert_not_called()

    def test_it_tolerates_a_window_with_no_channel_list_yet(self, qapp):
        fake_self = SimpleNamespace(config=SimpleNamespace(theme_name="Graphite"))

        MainWindow.apply_configured_theme(fake_self)  # must not raise

        assert theme.current_theme() == "Graphite"


# ---------------------------------------------------------------------------
# The six persistent content views (#261). Each builds the REAL view, switches
# the palette, and asserts a real constructed widget picked up the NEW value —
# with no refresh_theme() call anywhere, because there is none.
# ---------------------------------------------------------------------------

class TestDiscoverViewFollowsThePalette:
    def test_the_loading_label_restyles_on_a_switch(self, qapp, tmp_path):
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
        view = DiscoverView(MagicMock(), config, _FakeImageCache(), None)
        assert tp.MIDNIGHT["COLOR_MUTED_2"] in view._loading_lbl.styleSheet()

        theme.apply_theme("Daylight")

        after = view._loading_lbl.styleSheet()
        assert tp.DAYLIGHT["COLOR_MUTED_2"] in after
        assert tp.MIDNIGHT["COLOR_MUTED_2"] not in after


class TestEpgViewFollowsThePalette:
    def test_the_stale_notice_and_browse_labels_restyle_on_a_switch(
        self, qapp, tmp_path
    ):
        from metatv.core.config import Config
        from metatv.gui.epg_view import EpgView

        config = Config(config_dir=tmp_path)
        view = EpgView(config, db=MagicMock(), epg_manager=MagicMock())
        try:
            midnight_notice = view._stale_epg_notice.styleSheet()
            assert midnight_notice == theme.EPG_STALE_NOTICE

            theme.apply_theme("Daylight")

            assert view._stale_epg_notice.styleSheet() == theme.EPG_STALE_NOTICE
            assert view._stale_epg_notice.styleSheet() != midnight_notice
            # A label built in epg_browse_mixin.py, a different module the view
            # never enumerates — it registered itself where it was created.
            assert view._anchor_label.styleSheet() == theme.LABEL_MUTED
        finally:
            view._executor.shutdown(wait=False)


class TestRecipeViewFollowsThePalette:
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

    def test_its_own_chrome_and_its_children_restyle_on_a_switch(self, qapp):
        """The children live in three sibling MODULES (recipe_bar_widgets.py,
        weighted_tag_cloud.py) that ``RecipeView`` used to forward to by hand.
        Nothing forwards now; each widget registered itself."""
        view = self._make_view(qapp)
        midnight_back = view._back_to_clusters_btn.styleSheet()
        midnight_save = view._recipe_bar.save_btn.styleSheet()
        midnight_hdr = view._cloud._header_lbl.styleSheet()
        assert midnight_back == theme.RECIPE_BACK_TO_GRID_BTN
        assert midnight_save == theme.RECIPE_BAR_SAVE_BTN
        assert midnight_hdr == theme.CLOUD_HEADER_LABEL

        theme.apply_theme("Daylight")

        assert view._back_to_clusters_btn.styleSheet() == theme.RECIPE_BACK_TO_GRID_BTN
        assert view._back_to_clusters_btn.styleSheet() != midnight_back
        assert view._recipe_bar.save_btn.styleSheet() == theme.RECIPE_BAR_SAVE_BTN
        assert view._recipe_bar.save_btn.styleSheet() != midnight_save
        assert view._cloud._header_lbl.styleSheet() == theme.CLOUD_HEADER_LABEL
        assert view._cloud._header_lbl.styleSheet() != midnight_hdr

    def test_the_tab_bar_keeps_its_active_pill_across_a_switch(self, qapp):
        """``_RecipeTabBar._apply`` styles the active pill with a DIFFERENT
        role from the inactive one. Re-registration must not lose which is
        which — the last registration for a widget is the one that wins."""
        view = self._make_view(qapp)
        bar = view._tab_bar
        bar.set_index(1)

        theme.apply_theme("Daylight")

        assert bar._saved_btn.styleSheet() == theme.RECIPE_TAB_ACTIVE
        assert bar._recipe_btn.styleSheet() == theme.RECIPE_TAB


class TestProviderEditorFollowsThePalette:
    @pytest.fixture()
    def file_db(self, tmp_path):
        from metatv.core.database import Database
        d = Database(f"sqlite:///{tmp_path / 'provider_editor_theme.db'}")
        d.create_tables()
        yield d
        d.close()

    def test_the_editor_and_its_icon_picker_restyle_on_a_switch(
        self, qapp, tmp_path, file_db
    ):
        from metatv.core.config import Config
        from metatv.gui.provider_editor import ProviderEditorView

        config = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                        cache_dir=tmp_path / "cache")
        view = ProviderEditorView(file_db, config, MagicMock())
        midnight_action = view._action_refresh_btn.styleSheet()
        midnight_icon = view._icon_picker._btn.styleSheet()
        assert midnight_action == theme.PANEL_BTN
        assert midnight_icon == theme.ICON_PICK_MAIN_BTN

        theme.apply_theme("Daylight")

        assert view._action_refresh_btn.styleSheet() == theme.PANEL_BTN
        assert view._action_refresh_btn.styleSheet() != midnight_action
        # The icon picker is a nested widget the editor used to forward to.
        assert view._icon_picker._btn.styleSheet() == theme.ICON_PICK_MAIN_BTN
        assert view._icon_picker._btn.styleSheet() != midnight_icon


class TestSourcesManagerFollowsThePalette:
    @pytest.fixture()
    def file_db(self, tmp_path):
        from metatv.core.database import Database
        d = Database(f"sqlite:///{tmp_path / 'sources_manager_theme.db'}")
        d.create_tables()
        yield d
        d.close()

    def test_its_chrome_and_the_embedded_editor_restyle_on_a_switch(
        self, qapp, tmp_path, file_db
    ):
        from metatv.core.config import Config
        from metatv.gui.provider_editor import ProviderEditorView
        from metatv.gui.sources_manager_view import SourcesManagerView

        config = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                        cache_dir=tmp_path / "cache")
        provider_editor = ProviderEditorView(file_db, config, MagicMock())
        view = SourcesManagerView(config, file_db, provider_editor, None)
        midnight_editor_btn = provider_editor._action_refresh_btn.styleSheet()
        assert view._empty_label.styleSheet() == theme.EXPLORE_STATUS
        assert midnight_editor_btn == theme.PANEL_BTN

        theme.apply_theme("Daylight")

        assert view._empty_label.styleSheet() == theme.EXPLORE_STATUS
        # NOT asserted: that this string CHANGED. EXPLORE_STATUS paints on the
        # fixed-dark cinema shell (EXPLORE_VIEW_BG == COLOR_LIGHTBOX_BG), so it
        # is deliberately identical in every palette — a palette-tuned colour
        # there is the bug (Daylight's muted grey measured 4.33:1 on that dark
        # shell). The editor button below is a theme-VARYING role and proves
        # the switch reached the embedded view directly.
        assert provider_editor._action_refresh_btn.styleSheet() == theme.PANEL_BTN
        assert provider_editor._action_refresh_btn.styleSheet() != midnight_editor_btn


class TestPreferencesViewFollowsThePalette:
    @pytest.fixture()
    def file_db(self, tmp_path):
        from metatv.core.database import Database
        d = Database(f"sqlite:///{tmp_path / 'preferences_theme.db'}")
        d.create_tables()
        yield d
        d.close()

    def test_the_mix_controls_restyle_on_a_switch(self, qapp, tmp_path, file_db):
        from metatv.core.config import Config
        from metatv.gui.preferences_view import PreferencesView

        config = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                        cache_dir=tmp_path / "cache")
        view = PreferencesView(file_db, config, None)
        assert tp.MIDNIGHT["COLOR_TEXT"] in view._mix_label.styleSheet()

        theme.apply_theme("Daylight")

        after = view._mix_label.styleSheet()
        assert tp.DAYLIGHT["COLOR_TEXT"] in after
        assert tp.MIDNIGHT["COLOR_TEXT"] not in after
        # The Excluded/Version-Preferences collapsible toggles share one
        # builder — proves both were re-applied, not just the mix label. They
        # used to be re-applied by a raw setStyleSheet inside the sweep.
        assert view._excl_toggle_btn.styleSheet() == view._ver_prefs_toggle_btn.styleSheet()
        assert tp.DAYLIGHT["COLOR_TEXT"] in view._excl_toggle_btn.styleSheet()


# ---------------------------------------------------------------------------
# Rendered appearance. A stylesheet string passes for infinitely many wrong
# renderings, so these read real painted pixels. Both were run with the
# registration suppressed and both failed: the header kept painting Midnight's
# #151a21 under the Daylight palette, and the row label kept Midnight's ink.
# ---------------------------------------------------------------------------

class TestTheSwitchIsVisibleInPaintedPixels:
    @pytest.fixture()
    def section(self, qapp):
        """A real, populated facet section — freed via conftest's shared
        ``destroy_widget``, since a leaked parentless top-level is repainted
        by every later ``apply_theme()``."""
        from tests.conftest import destroy_widget
        from metatv.gui.filter_group_row import _Section

        config = SimpleNamespace(info_icon="i", expand_icon=">", collapse_icon="v")
        widget = _Section(
            "media", "Media", initially_expanded=True, config=config,
        )
        widget.set_flat_items([("movie", "Movies", 5), ("series", "Series", 3)])
        widget.resize(300, 90)
        yield widget
        destroy_widget(widget)

    def test_the_section_header_paints_the_new_palette(self, section):
        """The header's sheet is the one composed sheet the deleted sweep set
        by hand (``setStyleSheet`` with an f-string). It is now a
        ``style_fn`` builder bound to the section KEY by value — a lambda
        closing over ``self`` would pin the section behind the registry's
        weak reference to the widget."""
        theme.apply_theme("Daylight")
        painted = _painted_colours(section._header)

        assert tp.DAYLIGHT["COLOR_BG_SECTION"] in painted, (
            "the header did not repaint in the Daylight panel colour; painted "
            f"instead: {painted.most_common(4)}"
        )
        # The 3px accent border is the per-section colour the builder re-reads.
        assert tp.DAYLIGHT["COLOR_ACCENT_BLUE"] in painted
        assert tp.MIDNIGHT["COLOR_BG_SECTION"] not in painted

    def test_the_group_expander_icon_repaints_in_the_new_palette(self, qapp):
        """The one piece of NON-stylesheet work the deleted sweep did.

        ``_GroupRow``'s expander is a vector glyph baked into a QIcon at a
        colour, so no stylesheet registration can carry it — that is what
        ``icon_utils.refresh_icon_buttons`` (a ``theme.register_post_apply``
        hook) is for. It replays the colour it was HANDED, so this site passes
        a builder; with the pre-rebase ``color=_theme.COLOR_MUTED_2`` string
        the icon keeps the Midnight grey and this fails.
        """
        from tests.conftest import destroy_widget
        from metatv.gui.filter_group_row import _GroupRow

        config = SimpleNamespace(info_icon="i", expand_icon=">", collapse_icon="v")
        group = _GroupRow(
            "Nordic", 4, [("no", "Norwegian", 2), ("se", "Swedish", 2)],
            config=config,
        )
        try:
            before = _icon_bytes(group._expand_btn)

            theme.apply_theme("Daylight")

            assert _icon_bytes(group._expand_btn) != before, (
                "the group expander glyph kept the previous palette's colour"
            )
        finally:
            destroy_widget(group)

    def test_a_row_label_paints_the_new_ink(self, section):
        label = section._rows[0]._label

        theme.apply_theme("Daylight")
        painted = _painted_colours(label)

        assert tp.DAYLIGHT["COLOR_TEXT"] in painted, (
            "the row label's glyphs were not repainted in the Daylight ink; "
            f"painted instead: {painted.most_common(4)}"
        )
        assert tp.MIDNIGHT["COLOR_TEXT"] not in painted
