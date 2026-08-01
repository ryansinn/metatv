"""Behavioral tests for Browse's "Hide Filler" toggle persistence (Wave 3 slice 3A).

Ground truth: ``epg_hide_filler`` (config.py:891) seeded the Browse "Hide Filler ✓"
button's INITIAL checked state at build time, but a click never wrote the new
state back to config — so the toggle reverted to the config default on every
relaunch/re-activation. The button's label was also a hardcoded "Hide Filler ✓"
that never reflected whether hiding was actually on. This adds
``_on_hide_filler_toggled`` (persists + relabels + reloads) and
``_update_hide_filler_btn_label`` (adopts the On Now "Hide"/"Show All" label
idiom — here: "Hide Filler ✓" when active, "Hide Filler" when not).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.gui.epg_browse_mixin import _EpgBrowseMixin


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_browse_host(qapp, *, initial_hide_filler: bool):
    """Bare QWidget host with a real _build_browse_tab, wiring
    _on_hide_filler_toggled / _update_hide_filler_btn_label to the REAL mixin
    methods under test (everything else stubbed, mirroring the pattern in
    test_epg_browse_fixes.py::_make_browse_tab_host)."""
    from PyQt6.QtWidgets import QWidget, QStackedWidget
    from metatv.gui.epg_view import EpgView

    config = SimpleNamespace(
        epg_hide_filler=initial_hide_filler,
        epg_filter_state={},
        save=MagicMock(),
    )
    host = QWidget.__new__(QWidget)
    QWidget.__init__(host, None)
    host.config = config
    host.stack = QStackedWidget(host)
    host._build_browse_tab = lambda: EpgView._build_browse_tab(host)
    host._refresh_browse_anchors = lambda: EpgView._refresh_browse_anchors(host)
    host._on_search_changed = lambda *_: None
    host._reload_browse = MagicMock()
    host._load_more_browse = lambda *_: None
    host._on_browse_scroll = lambda *_: None
    host._browse_double_click = lambda *_: None
    host._browse_selection_changed = lambda *_: None
    host._on_browse_context_menu = lambda *_: None
    host._save_epg_sort = lambda *a: None
    host._on_anchor_selected = lambda *_: None
    host._on_scrubber_value_changed = lambda *_: None
    host._scrubber_seek = lambda *_: None
    # post-merge (wave3/browse-makeover): build wires header persistence
    host._save_browse_header_state = MagicMock()
    host._on_browse_sort_changed = MagicMock()
    # The methods under test — bound to the real mixin implementation.
    host._on_hide_filler_toggled = lambda: _EpgBrowseMixin._on_hide_filler_toggled(host)
    host._update_hide_filler_btn_label = lambda: _EpgBrowseMixin._update_hide_filler_btn_label(host)
    host._build_browse_tab()
    # Build-time one-shots (3D's sort-col migration) also call config.save —
    # reset so tests count only the toggle-path saves they assert on.
    host.config.save.reset_mock()
    return host


def test_button_seeds_checked_state_and_label_from_config(qapp):
    """Build time: the button's checked state AND label both reflect config.epg_hide_filler."""
    host = _make_browse_host(qapp, initial_hide_filler=True)
    assert host.hide_filler_btn.isChecked() is True
    assert host.hide_filler_btn.text() == "Hide Filler ✓"


def test_button_label_when_off_at_build(qapp):
    host = _make_browse_host(qapp, initial_hide_filler=False)
    assert host.hide_filler_btn.isChecked() is False
    assert host.hide_filler_btn.text() == "Hide Filler"


def test_click_persists_toggle_to_config(qapp):
    """Clicking the button writes the NEW state to config.epg_hide_filler and calls save()."""
    host = _make_browse_host(qapp, initial_hide_filler=False)
    assert host.config.epg_hide_filler is False

    host.hide_filler_btn.click()

    assert host.config.epg_hide_filler is True, (
        "clicking Hide Filler must persist the new checked state to config"
    )
    host.config.save.assert_called_once()


def test_click_updates_label_to_reflect_new_state(qapp):
    """After a click, the button's own text reflects the new state (not stuck)."""
    host = _make_browse_host(qapp, initial_hide_filler=False)
    host.hide_filler_btn.click()
    assert host.hide_filler_btn.text() == "Hide Filler ✓"

    host.hide_filler_btn.click()
    assert host.hide_filler_btn.text() == "Hide Filler"
    assert host.config.epg_hide_filler is False


def test_click_reloads_browse(qapp):
    """A toggle must still trigger a Browse reload (existing behavior, must not regress)."""
    host = _make_browse_host(qapp, initial_hide_filler=False)
    host.hide_filler_btn.click()
    host._reload_browse.assert_called_once()


def test_repeated_toggles_persist_each_time(qapp):
    """Two round-trip toggles each independently persist (not just the first)."""
    host = _make_browse_host(qapp, initial_hide_filler=False)
    host.hide_filler_btn.click()  # -> True
    host.hide_filler_btn.click()  # -> False
    host.hide_filler_btn.click()  # -> True

    assert host.config.epg_hide_filler is True
    assert host.config.save.call_count == 3
