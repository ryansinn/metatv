"""Behavior tests for the sidebar per-source EPG freshness indicator.

A small colored, clickable button on each provider row: green=current, amber=soon,
red=stale, faint=none; tooltip shows the guide date range; clicking refreshes that
source's EPG. These execute the real widget, not source-string checks.
"""

from __future__ import annotations

from datetime import datetime

import pytest

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _icon_bytes(btn) -> bytes:
    """Raw pixel bytes of *btn*'s current icon, for "did it actually repaint"."""
    image = btn.icon().pixmap(btn.iconSize()).toImage()
    return image.bits().asstring(image.sizeInBytes())


def test_epg_indicator_color_per_state(qapp):
    # ICON-1: the freshness colour lives on the painted QIcon (icon_utils.
    # set_button_icon), not in the stylesheet text — asserted here on the
    # rendered pixel bytes, which is what actually proves the four states
    # look different rather than merely carrying four different strings.
    from metatv.gui.sidebar.sources import ProviderItemWidget
    w = ProviderItemWidget("p", "P", epg_state="current", epg_tooltip="EPG current: a – b")
    assert not w._epg_btn.icon().isNull()
    assert w._epg_btn.toolTip() == "EPG current: a – b"
    current_bytes = _icon_bytes(w._epg_btn)

    w.set_epg_state("stale", "EPG stale: a – b")
    stale_bytes = _icon_bytes(w._epg_btn)
    assert stale_bytes != current_bytes, "stale must repaint a different colour than current"

    w.set_epg_state("soon", "EPG ending soon: a – b")
    soon_bytes = _icon_bytes(w._epg_btn)
    assert soon_bytes not in (current_bytes, stale_bytes)

    w.set_epg_state("none", "No EPG Available")
    none_bytes = _icon_bytes(w._epg_btn)
    assert none_bytes not in (current_bytes, stale_bytes, soon_bytes)
    assert w._epg_btn.toolTip() == "No EPG Available"


def test_epg_indicator_refreshing_spinner(qapp):
    from metatv.gui.sidebar.sources import ProviderItemWidget
    w = ProviderItemWidget("p", "P", epg_state="current", epg_tooltip="t")
    resting_bytes = _icon_bytes(w._epg_btn)

    w.set_epg_refreshing(True)
    assert w._epg_btn.text() == ""
    assert _icon_bytes(w._epg_btn) != resting_bytes, "the spinner glyph must repaint"
    assert not w._epg_btn.isEnabled()
    # Clearing restores the state glyph + re-enables.
    w.set_epg_refreshing(False)
    assert _icon_bytes(w._epg_btn) == resting_bytes
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
