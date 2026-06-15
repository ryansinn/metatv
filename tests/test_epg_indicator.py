"""Behavior tests for the sidebar per-source EPG freshness indicator.

A small colored, clickable button on each provider row: green=current, amber=soon,
red=stale, faint=none; tooltip shows the guide date range; clicking refreshes that
source's EPG. These execute the real widget, not source-string checks.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from metatv.gui import theme as _theme
from metatv.gui import icons as _icons


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_epg_indicator_color_per_state(qapp):
    from metatv.gui.sidebar.sources import ProviderItemWidget
    w = ProviderItemWidget("p", "P", epg_state="current", epg_tooltip="EPG current: a – b")
    assert _theme.COLOR_OK in w._epg_btn.styleSheet()
    assert w._epg_btn.toolTip() == "EPG current: a – b"

    w.set_epg_state("stale", "EPG stale: a – b")
    assert _theme.COLOR_ERR_2 in w._epg_btn.styleSheet()

    w.set_epg_state("soon", "EPG ending soon: a – b")
    assert _theme.COLOR_WARN in w._epg_btn.styleSheet()

    w.set_epg_state("none", "No EPG Available")
    assert _theme.COLOR_FAINT in w._epg_btn.styleSheet()
    assert w._epg_btn.toolTip() == "No EPG Available"


def test_epg_indicator_refreshing_spinner(qapp):
    from metatv.gui.sidebar.sources import ProviderItemWidget
    w = ProviderItemWidget("p", "P", epg_state="current", epg_tooltip="t")
    w.set_epg_refreshing(True)
    assert w._epg_btn.text() == _icons.loading_icon
    assert not w._epg_btn.isEnabled()
    # Clearing restores the state glyph + re-enables.
    w.set_epg_refreshing(False)
    assert w._epg_btn.text() == _icons.epg_indicator_icon
    assert w._epg_btn.isEnabled()


def test_epg_indicator_click_emits_refresh(qapp):
    from metatv.gui.sidebar.sources import ProviderItemWidget
    w = ProviderItemWidget("prov-9", "P")
    got: list[str] = []
    w.epgRefreshClicked.connect(got.append)
    w._epg_btn.click()
    assert got == ["prov-9"]


def test_epg_tooltip_helper():
    from metatv.gui.sidebar.sources import _epg_tooltip
    assert _epg_tooltip("none", None, None) == "No EPG Available"
    t = _epg_tooltip("current", datetime(2026, 6, 12), datetime(2026, 6, 19))
    assert "click to refresh" in t
    assert "Jun 2026" in t
    # Missing start renders gracefully (provider not re-fetched yet).
    assert "?" in _epg_tooltip("stale", None, datetime(2025, 2, 2))
