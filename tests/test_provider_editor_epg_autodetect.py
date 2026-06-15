"""EPG auto-detect badge + refresh-button enablement in the provider editor.

PR-2 follow-up. Two regressions are pinned here:

1. ``EpgManager.build_epg_url`` derives the Xtream XMLTV URL from credentials, so the
   editor can show the auto-detected feed and enable "Refresh EPG now" *before* the
   first fetch has stored ``epg_url``.
2. The refresh button must enable when there is an effective URL — the override OR the
   auto-detected URL — not only when the override box has text (the original bug). The
   auto-detect badge reads AUTODETECTED (green) / NOT FOUND (red) accordingly, and the
   click-to-copy URL line shows only when a URL was detected.

The widget-level tests construct the editor via ``__new__`` and hand it real Qt
sub-widgets (headless ``qapp``), then call the real handlers and assert the rendered
state — no shape assertions.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QCheckBox, QLineEdit, QPushButton, QLabel

from metatv.core.epg_manager import EpgManager
from metatv.gui.provider_editor import ProviderEditorView, _CopyableLabel


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── build_epg_url (pure deriver) ─────────────────────────────────────────────── #

def test_build_epg_url_from_credentials():
    prov = SimpleNamespace(
        urls=[{"url": "http://host.example:8080/"}],
        username="user1",
        password="pass1",
    )
    assert EpgManager.build_epg_url(prov) == (
        "http://host.example:8080/xmltv.php?username=user1&password=pass1"
    )


def test_build_epg_url_without_credentials():
    prov = SimpleNamespace(urls=[{"url": "http://host.example:8080"}], username="", password="")
    assert EpgManager.build_epg_url(prov) == "http://host.example:8080/xmltv.php"


def test_build_epg_url_none_when_no_server():
    prov = SimpleNamespace(urls=[], username="u", password="p")
    assert EpgManager.build_epg_url(prov) is None


# ── editor badge + refresh-button enablement ─────────────────────────────────── #

def _editor(qapp) -> ProviderEditorView:
    """A bare editor with just the EPG sub-widgets the handlers touch."""
    ed = ProviderEditorView.__new__(ProviderEditorView)
    ed._provider_id = "p1"
    ed._epg_enabled_check = QCheckBox()
    ed._epg_enabled_check.setChecked(True)
    ed._epg_url_override_input = QLineEdit()
    ed._epg_refresh_btn = QPushButton()
    ed._epg_detect_badge = QLabel()
    ed._epg_autodetected_lbl = _CopyableLabel()
    return ed


def test_autodetected_url_enables_refresh_without_override(qapp):
    """The core bug: refresh must work off the auto-detected URL with an empty override."""
    ed = _editor(qapp)
    ed._loaded_epg_url = "http://host/xmltv.php?username=u&password=p"
    ed._update_epg_autodetected_display()
    ed._update_epg_refresh_btn_state()

    assert "AUTODETECTED" in ed._epg_detect_badge.text()
    assert ed._epg_autodetected_lbl.isVisible()
    assert ed._epg_autodetected_lbl._full_text == ed._loaded_epg_url
    assert ed._epg_refresh_btn.isEnabled()          # enabled despite empty override


def test_no_autodetected_url_shows_not_found_and_disables(qapp):
    ed = _editor(qapp)
    ed._loaded_epg_url = ""
    ed._update_epg_autodetected_display()
    ed._update_epg_refresh_btn_state()

    assert "NOT FOUND" in ed._epg_detect_badge.text()
    assert not ed._epg_autodetected_lbl.isVisible()
    assert not ed._epg_refresh_btn.isEnabled()       # no override, no auto URL


def test_override_alone_enables_refresh(qapp):
    ed = _editor(qapp)
    ed._loaded_epg_url = ""
    ed._epg_url_override_input.setText("http://custom/guide.xml")
    ed._update_epg_refresh_btn_state()
    assert ed._epg_refresh_btn.isEnabled()


def test_disabled_epg_keeps_refresh_off_even_with_url(qapp):
    ed = _editor(qapp)
    ed._loaded_epg_url = "http://host/xmltv.php"
    ed._epg_enabled_check.setChecked(False)
    ed._update_epg_refresh_btn_state()
    assert not ed._epg_refresh_btn.isEnabled()


def test_copyable_label_copies_full_url(qapp):
    from PyQt6.QtWidgets import QApplication
    lbl = _CopyableLabel()
    url = "http://host/xmltv.php?username=u&password=p"
    lbl.set_url(url)
    lbl._copy()
    assert QApplication.clipboard().text() == url
