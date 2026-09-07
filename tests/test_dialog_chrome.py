"""One button row for every dialog — and it behaves the way each one did.

Sixteen dialogs built the row at the bottom sixteen ways: twelve assembled a
``QDialogButtonBox`` by hand, three laid out ``QPushButton``s in a
``QHBoxLayout`` (so their Close button sat wherever the layout put it rather
than where the platform puts a Close button), and one built a
``QDialogButtonBox``, never added it to a layout, and hand-rolled a row beside
it.

The risk in unifying them is not that the row looks wrong — it is that a dialog
quietly changes what Enter does, what Escape does, or which exit code it
returns, and none of those show up in a screenshot. So the parity assertions
here drive the real dialogs: Escape rejects, the primary button is the default
(Enter's target), and the four dialogs whose Close historically *rejected* still
reject.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QVBoxLayout
from PyQt6.QtTest import QTest

from metatv.gui.dialog_chrome import action_button, dialog_buttons
from tests.conftest import destroy_widget

_OK = QDialogButtonBox.StandardButton.Ok
_CANCEL = QDialogButtonBox.StandardButton.Cancel
_APPLY = QDialogButtonBox.StandardButton.Apply


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _dialog(qapp, **kwargs):
    """A bare dialog carrying nothing but the shared button row."""
    dlg = QDialog()
    layout = QVBoxLayout(dlg)
    box = dialog_buttons(dlg, **kwargs)
    layout.addWidget(box)
    return dlg, box


# ── the builder itself ──────────────────────────────────────────────────────

def test_the_primary_button_is_the_default_whatever_it_is_called(qapp):
    """Enter presses this one. Left to Qt the choice follows focus order, and
    two dialogs that look identical got different answers."""
    _dlg, box = _dialog(qapp, ok="Add to Category")

    primary = box.button(_OK)
    assert primary.text() == "Add to Category"
    assert primary.isDefault(), "Enter would land on whatever Qt guessed"
    assert not box.button(_CANCEL).isDefault(), "two default buttons is no default"


def test_the_primary_button_keeps_its_standard_identity_under_a_new_label(qapp):
    """The label is cosmetic; the handle must not move with it.

    Half the callers reach for their primary button again later (to disable it
    until a name is typed, to paint it accent). If relabelling it changed how
    it is found, every one of those lookups would be a positional guess.
    """
    _dlg, box = _dialog(qapp, ok="Close", cancel=False)

    assert box.button(_OK) is not None
    assert box.button(_OK).text() == "Close"
    assert box.button(_CANCEL) is None


def test_ok_none_builds_no_primary_button(qapp):
    _dlg, box = _dialog(qapp, ok=None, cancel=True)
    assert box.button(_OK) is None
    assert box.button(_CANCEL) is not None


def test_accepted_runs_on_ok_instead_of_accept_when_given(qapp):
    """The validating dialogs (`_try_accept`, `_save_and_accept`) depend on it."""
    seen = []
    dlg, box = _dialog(qapp, on_ok=lambda: seen.append("ran"))

    box.button(_OK).click()

    assert seen == ["ran"]
    assert dlg.result() != QDialog.DialogCode.Accepted, (
        "on_ok must REPLACE accept(), not run alongside it — a dialog that "
        "validates first must be able to refuse to close"
    )


def test_the_default_primary_accepts_and_cancel_rejects(qapp):
    dlg, box = _dialog(qapp)
    box.button(_OK).click()
    assert dlg.result() == QDialog.DialogCode.Accepted

    dlg2, box2 = _dialog(qapp)
    box2.button(_CANCEL).click()
    assert dlg2.result() == QDialog.DialogCode.Rejected


def test_apply_is_a_real_apply_button_not_an_action(qapp):
    """ApplyRole sits with OK/Cancel; ActionRole sits away from them.

    Passing Settings' Apply through ``extra`` would have MOVED it across the
    row — a silent layout change dressed as a refactor.
    """
    applied = []
    _dlg, box = _dialog(qapp, apply=lambda: applied.append(1))

    apply_btn = box.button(_APPLY)
    assert apply_btn is not None, "Apply must be a standard button"
    assert box.buttonRole(apply_btn) == QDialogButtonBox.ButtonRole.ApplyRole

    apply_btn.click()
    assert applied == [1]


def test_extra_buttons_act_without_closing_and_are_found_by_label(qapp):
    """``buttons()`` order is not part of Qt's contract — the label is."""
    fired = []
    dlg, box = _dialog(qapp, extra=(("Test Connection", lambda: fired.append(1)),))

    button = action_button(box, "Test Connection")
    assert button is not None
    assert box.buttonRole(button) == QDialogButtonBox.ButtonRole.ActionRole

    button.click()
    assert fired == [1]
    assert dlg.result() == 0, "an action button must not close the dialog"
    assert action_button(box, "No Such Button") is None


# ── parity, driven through the real dialogs ────────────────────────────────

def test_escape_still_rejects_every_dialog(qapp, tmp_path):
    """Escape is ``QDialog``'s own, not the button row's — but a builder that
    re-parented or swallowed the row could break it, and nothing would say so.
    """
    from metatv.core.config import Config
    from metatv.gui.about_dialog import AboutDialog
    from metatv.gui.epg_widgets import _AssignCategoryDialog, _DismissedDialog
    from metatv.gui.new_facet_values_dialog import NewFacetValuesDialog

    config = Config(config_dir=tmp_path)
    dialogs = [
        AboutDialog(),
        _AssignCategoryDialog(["US", "UK"]),
        _DismissedDialog(config),
        NewFacetValuesDialog({"region": {"FR"}}, {"region": "Region"}),
    ]
    for dlg in dialogs:
        dlg.show()
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        assert dlg.result() == QDialog.DialogCode.Rejected, (
            f"{type(dlg).__name__} no longer closes on Escape"
        )
    destroy_widget(*dialogs)


def test_about_dialog_has_a_close_button_and_keeps_its_copy_action(qapp):
    """It had no button box at all — a hand-laid row with the Close button
    wherever that layout left it."""
    from metatv.gui.about_dialog import AboutDialog

    dlg = AboutDialog()
    box = dlg.findChild(QDialogButtonBox)
    assert box is not None, "About still has no button row"
    assert box.button(_OK).text() == "Close"
    assert box.button(_OK).isDefault()
    assert dlg._copy_btn is not None and dlg._copy_btn.toolTip()
    assert box.buttonRole(dlg._copy_btn) == QDialogButtonBox.ButtonRole.ActionRole
    destroy_widget(dlg)


def test_the_close_only_dialogs_kept_the_exit_code_they_had(qapp, tmp_path):
    """Four Close buttons rejected and one accepted, for no reason that
    survives reading both — but the exit code is the dialog's own, and a
    caller may read it. Parity, not tidiness.
    """
    from metatv.core.config import Config
    from metatv.gui.discover_filter_dialog import DiscoverManageDialog
    from metatv.gui.epg_widgets import _DismissedDialog

    config = Config(config_dir=tmp_path)

    rejecting = _DismissedDialog(config)
    box = rejecting.findChild(QDialogButtonBox)
    box.button(_OK).click()
    assert rejecting.result() == QDialog.DialogCode.Rejected, (
        "_DismissedDialog's Close used to reject"
    )

    accepting = DiscoverManageDialog(None, config, {}, {})
    box = accepting.findChild(QDialogButtonBox)
    box.button(_OK).click()
    assert accepting.result() == QDialog.DialogCode.Accepted, (
        "DiscoverManageDialog's Close used to accept — its caller reads that"
    )
    destroy_widget(rejecting, accepting)


def test_both_diagnostics_dialogs_actually_construct(qapp, tmp_path):
    """Constructed, not inspected — this exact file shipped a NameError.

    ``diagnostics_dialog.py`` used the shared builder without importing it, and
    nothing caught it: ruff's F821 is not in this project's selected rules, the
    module still imports fine (the name is only read when a dialog is built),
    and no test built either dialog. The failure would have been a traceback
    the first time someone opened Stream Diagnostics.
    """
    from concurrent.futures import ThreadPoolExecutor

    from metatv.core.config import Config
    from metatv.core.stream_diagnostics import DiagnosticResult
    from metatv.gui.diagnostics_dialog import (
        StreamDiagnosticsDialog, _TechnicalDetailsDialog,
    )

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        dlg = StreamDiagnosticsDialog(
            channel_name="BBC One", stream_url="http://example/1.ts",
            config=Config(config_dir=tmp_path), executor=executor,
        )
        box = dlg.findChild(QDialogButtonBox)
        assert box.button(_OK).text() == "Close"
        assert dlg._apply_button is not None and not dlg._apply_button.isEnabled()

        child = _TechnicalDetailsDialog(
            DiagnosticResult(reachable=True, verdict="ok", summary="fine"))
        assert child.findChild(QDialogButtonBox).button(_OK).text() == "Close"
        destroy_widget(dlg, child)
    finally:
        executor.shutdown(wait=False)


def test_settings_dialog_still_has_ok_cancel_and_apply(qapp, tmp_path):
    """The one dialog with a third standard button."""
    from metatv.core.config import Config
    from metatv.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(Config(config_dir=tmp_path))
    box = dlg.findChild(QDialogButtonBox)
    assert box.button(_OK) is not None
    assert box.button(_CANCEL) is not None
    assert box.button(_APPLY) is not None
    assert box.buttonRole(box.button(_APPLY)) == QDialogButtonBox.ButtonRole.ApplyRole
    assert box.button(_OK).isDefault()
    destroy_widget(dlg)


def test_every_dialog_module_routes_through_the_builder():
    """The drift guard: a new dialog must not hand-assemble its own row.

    Source-level because the alternative — constructing all sixteen against a
    database — tests the dialogs rather than the thing that drifted.
    """
    import pathlib

    offenders = []
    for path in sorted(pathlib.Path("metatv").rglob("*.py")):
        if path.name == "dialog_chrome.py":
            continue
        text = path.read_text()
        if "QDialogButtonBox(" in text:
            offenders.append(str(path))
    assert offenders == [], (
        f"these build a button box by hand instead of dialog_buttons(): {offenders}"
    )
