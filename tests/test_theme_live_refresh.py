"""Behavioral tests for the live theme-switch gaps closed in this slice
(What's New #251): the sidebar Settings button / bottom nav bar background /
"showing hidden" label / context-filter-chip dismiss button promoted from
``setup_ui()`` locals to ``self.*`` attrs, and ``FilterPanel`` (the middle
filter column) gaining its own ``refresh_theme()`` that recurses into every
``_Section``/``_GroupRow``/``_ItemRow``/``_TriCheckbox`` it built.

Covers:
1. ``FilterPanel.refresh_theme()`` actually changes the panel's own cached
   stylesheet AND a static section's row-level widgets (checkbox, label,
   "Only" button) after a live palette switch — proving the recursion reaches
   real row objects, not just the panel's own chrome.
2. ``MainWindow.refresh_theme()`` sweeps the 4 promoted widgets + calls
   ``filter_panel.refresh_theme()`` — extends the existing fake-``self``
   pattern from ``test_theme_palettes.py``.

Every test executes the changed path and asserts an outcome that would break
if the sweep regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.gui import theme
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
