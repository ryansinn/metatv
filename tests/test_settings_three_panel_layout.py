"""Behavioral tests for the Settings dialog's three-panel rework.

Wave 6 replaced the flat ``QTabWidget`` with a
``ThreePanelSectionNav`` (``metatv/gui/three_panel_section_nav.py``): a
left-nav ``QListWidget`` (``_nav.section_list``), a center ``QStackedWidget``
(``_nav.stack``) holding the same five unchanged ``_build_*_tab()`` widgets
(now living in ``SettingsTabsMixin``, ``metatv/gui/settings_dialog_tabs.py``),
and a right-hand contextual-help ``QTextBrowser`` (``_nav.help_panel``) whose
text follows the selected section. These tests pin the new container's
behavior:

1. Five sections, in order, no "Sidebar" section.
2. Selecting a left-nav row switches the center stack to the matching page.
3. The tripwire: the ``settings:<tab>`` deep link must keep resolving by label
   substring against the new left-nav — both shipped spellings
   ("settings:Interface" in entries/0111_qa_checklist_navigation.py and
   "settings:interface" in entries/0158_update_checker.py) must still land on
   Interface. Proven both directly (``SettingsDialog.select_section_by_label``)
   and end-to-end through the real, unbound ``MainWindow.open_settings``.
4. The right-hand help text changes per selected section and is never empty.
5. Dialog size + selected section round-trip through config across two dialog
   instances (persist on close — OK *or* Cancel — restore on next open).
6. Apply still emits ``settings_applied`` (unaffected by the layout swap).

Constructed via the real ``SettingsDialog(config, parent=None)`` (not the
``__new__`` skeleton pattern the individual-widget tests use) because these
tests exercise ``_setup_ui`` itself — the very code being reworked — plus a
real ``Config`` on a ``tmp_path`` so the persistence round-trip proves the
literal config keys, not a hand-stubbed fake.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from metatv.core.config import Config
from metatv.gui.settings_dialog import SettingsDialog, _SECTIONS


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_config(tmp_path) -> Config:
    """A real Config on a throwaway tmp_path (autouse _isolate_user_config in
    conftest.py also patches Path.home, but pinning explicit dirs here matches
    the existing SettingsDialog test precedent, e.g. test_graduated_watch_progress.py)."""
    config = Config(
        config_dir=tmp_path / "cfg",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    config.config_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    return config


_LABELS = [label for _section_id, label, _builder in _SECTIONS]
_INTERFACE_ROW = _LABELS.index("Interface")


# --------------------------------------------------------------------------- #
# 1. Every declared section, in order, no "Sidebar" section
# --------------------------------------------------------------------------- #

def test_every_declared_section_renders_in_order(qapp, tmp_path):
    """Counted against ``_SECTIONS``, not a copy of its labels.

    ``_SECTIONS`` now carries its own builder name, so the old hazard this
    guarded — a section zipped against a shorter ``builders`` tuple, truncating
    SILENTLY — cannot happen any more. The check is still worth keeping: it is
    what proves a declared section actually renders, and that the nav and the
    stack agree on how many there are.

    A literal list of labels is deliberately NOT used: it cannot tell a missing
    page from someone legitimately adding one, so it goes red and gets bumped,
    which is how a check stops meaning anything.
    """
    dlg = SettingsDialog(_make_config(tmp_path), parent=None)

    labels = [dlg._nav.section_list.item(i).text()
              for i in range(dlg._nav.section_list.count())]
    assert labels == [label for _sid, label, _builder in _SECTIONS]
    assert len(labels) >= 6
    assert dlg._nav.stack.count() == len(_SECTIONS)

    dlg.reject()


# --------------------------------------------------------------------------- #
# 2. Selecting a left-nav row switches the center stack
# --------------------------------------------------------------------------- #

def test_selecting_section_switches_stack(qapp, tmp_path):
    dlg = SettingsDialog(_make_config(tmp_path), parent=None)

    for row in range(len(_SECTIONS)):
        dlg._nav.section_list.setCurrentRow(row)
        assert dlg._nav.stack.currentIndex() == row

    dlg.reject()


# --------------------------------------------------------------------------- #
# 3. Tripwire — settings:<tab> deep link keeps resolving to Interface
# --------------------------------------------------------------------------- #

def test_select_section_by_label_tripwire_both_spellings(qapp, tmp_path):
    """Both shipped deep-link spellings must still select Interface."""
    dlg_lower = SettingsDialog(_make_config(tmp_path), parent=None)
    assert dlg_lower.select_section_by_label("interface") is True
    assert dlg_lower._nav.section_list.currentRow() == _INTERFACE_ROW
    assert dlg_lower._nav.stack.currentIndex() == _INTERFACE_ROW
    dlg_lower.reject()

    dlg_exact = SettingsDialog(_make_config(tmp_path), parent=None)
    assert dlg_exact.select_section_by_label("Interface") is True
    assert dlg_exact._nav.section_list.currentRow() == _INTERFACE_ROW
    assert dlg_exact._nav.stack.currentIndex() == _INTERFACE_ROW
    dlg_exact.reject()


def test_open_settings_tab_selects_interface_section(qapp, tmp_path, monkeypatch):
    """End-to-end through the real, unbound ``MainWindow.open_settings`` — the
    exact code path the shipped deep links hit — proving the QTabWidget → left-nav
    rework didn't break it (CRITICAL_RULES tripwire).

    Booting a full ``MainWindow`` (DB/providers/etc.) is out of scope for this
    layout-only slice, so a minimal ``QWidget`` host supplies just the attributes
    ``open_settings`` touches; ``SettingsDialog.exec`` is stubbed to a no-op so the
    modal event loop never actually blocks the test, and ``SettingsDialog.__init__``
    is wrapped to capture the constructed instance for assertions.
    """
    from metatv.gui.main_window import MainWindow

    class _MinimalHost(QWidget):
        def __init__(self, config):
            super().__init__()
            self.config = config
            # #395 passes executor= into SettingsDialog so the TMDb/OMDb
            # "Test" buttons can call test_connection() off the UI thread.
            from concurrent.futures import ThreadPoolExecutor
            self.executor = ThreadPoolExecutor(max_workers=1)

        def _manual_update_check(self):
            pass

    from tests.conftest import wire_settings_dialog_hooks

    host = _MinimalHost(_make_config(tmp_path))
    # Every settings_applied handler, from the shared factory. This class used
    # to hand-list them and went red once per slice that added one.
    wire_settings_dialog_hooks(host)

    captured: dict[str, SettingsDialog] = {}
    original_init = SettingsDialog.__init__

    def _capturing_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured["dlg"] = self

    monkeypatch.setattr(SettingsDialog, "__init__", _capturing_init)
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: None)

    MainWindow.open_settings(host, tab="interface")

    dlg = captured["dlg"]
    assert dlg._nav.section_list.currentRow() == _INTERFACE_ROW
    assert dlg._nav.stack.currentIndex() == _INTERFACE_ROW
    dlg.reject()


# --------------------------------------------------------------------------- #
# 4. Right-hand help text changes per section
# --------------------------------------------------------------------------- #

def test_help_text_changes_per_section(qapp, tmp_path):
    dlg = SettingsDialog(_make_config(tmp_path), parent=None)

    seen_texts = set()
    for row in range(dlg._nav.section_list.count()):
        dlg._nav.section_list.setCurrentRow(row)
        text = dlg._nav.help_panel.toPlainText()
        assert text, f"section row {row} ({_LABELS[row]}) has empty help text"
        seen_texts.add(text)

    assert len(seen_texts) == len(_SECTIONS)  # every section's help text is distinct

    dlg.reject()


# --------------------------------------------------------------------------- #
# 5. Size + selected section persist across dialog instances
# --------------------------------------------------------------------------- #

def test_dialog_size_and_section_persist_across_instances(qapp, tmp_path):
    config = _make_config(tmp_path)

    dlg1 = SettingsDialog(config, parent=None)
    dlg1.resize(950, 640)
    dlg1._nav.section_list.setCurrentRow(3)  # "Metadata & API Keys"
    dlg1.reject()  # Cancel path — UI state (size/section) still must persist

    assert config.settings_dialog_width == 950
    assert config.settings_dialog_height == 640
    assert config.settings_dialog_section == 3

    dlg2 = SettingsDialog(config, parent=None)
    assert dlg2.width() == 950
    assert dlg2.height() == 640
    assert dlg2._nav.section_list.currentRow() == 3
    assert dlg2._nav.stack.currentIndex() == 3

    dlg2.reject()


# --------------------------------------------------------------------------- #
# 6. Apply still emits settings_applied
# --------------------------------------------------------------------------- #

def test_apply_emits_settings_applied(qapp, tmp_path):
    dlg = SettingsDialog(_make_config(tmp_path), parent=None)

    received = []
    dlg.settings_applied.connect(lambda: received.append(True))
    dlg._apply()

    assert received == [True]

    dlg.reject()
