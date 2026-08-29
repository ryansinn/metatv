"""Help ▸ About must open something, and say what this build is.

The menu item has existed for a long time. Its handler was::

    def show_about(self):
        \"\"\"Show about dialog\"\"\"
        logger.info("Show about")

A discoverable entry point that did nothing. Nothing tested it, so nothing
said so — the same shape as the guards this audit has been finding, one level
up: the feature was *listed* rather than *executed*.

The licence notice is not decoration. CI vendors mpv, with its dylibs, into
``MetaTV.app/Contents/Resources/mpv/`` (``.github/workflows/release.yml``), so
a packaged build REDISTRIBUTES a GPL binary and owes a notice pointing at the
source.
"""

import pytest

from metatv.core.component_versions import ComponentVersions, collect
from metatv.gui.about_dialog import BUNDLED_COMPONENTS, AboutDialog, describe


def _versions(**over) -> ComponentVersions:
    base = {
        "app": "1.2.3", "build_id": None, "python": "3.12.0", "qt": "6.7.0",
        "pyqt": "6.7.0", "platform_name": "Linux 6.0", "mpv": "0.38.0",
        "mpv_path": "/usr/bin/mpv",
    }
    base.update(over)
    return ComponentVersions(**base)


# ── the dialog opens and is not empty ───────────────────────────────────────

def test_the_dialog_opens_and_names_the_build(qtbot) -> None:
    """Pre-fix, show_about logged a line and no window existed at all."""
    dlg = AboutDialog()
    qtbot.addWidget(dlg)

    shown = dlg._details.text()
    assert "MetaTV" in shown
    assert shown.count("\n") >= 2, f"the version block is nearly empty: {shown!r}"


def test_show_about_actually_opens_the_dialog(monkeypatch) -> None:
    """The wiring, not just the widget.

    Asserts through MainWindow.show_about — the thing the menu calls — because
    a perfectly good dialog nobody opens is exactly the state this fixes.
    """
    from metatv.gui import main_window as mw

    opened: list[object] = []

    class _FakeDialog:
        def __init__(self, parent=None):
            opened.append(parent)

        def exec(self):
            return 0

    monkeypatch.setattr("metatv.gui.about_dialog.AboutDialog", _FakeDialog)

    host = mw.MainWindow.__new__(mw.MainWindow)
    mw.MainWindow.show_about(host)

    assert opened == [host], "show_about did not open the About dialog"


# ── it says what is actually running ────────────────────────────────────────

def test_every_component_appears_in_the_block() -> None:
    text = describe(_versions())
    for expected in ("1.2.3", "3.12.0", "6.7.0", "Linux 6.0", "0.38.0", "/usr/bin/mpv"):
        assert expected in text, f"{expected!r} missing from:\n{text}"


def test_a_source_checkout_says_so_rather_than_showing_nothing() -> None:
    """build_id is generated at package time and absent in a checkout."""
    assert "source checkout" in describe(_versions(build_id=None))


def test_a_packaged_build_shows_its_build_id() -> None:
    text = describe(_versions(build_id="1.2.3+20260829.abc1234"))
    assert "1.2.3+20260829.abc1234" in text
    assert "source checkout" not in text


@pytest.mark.parametrize("mpv,path,expected", [
    (None, "/usr/bin/mpv", "could not read version"),
    (None, None, "not found"),
])
def test_a_missing_mpv_is_reported_not_hidden(mpv, path, expected) -> None:
    """A broken mpv is the thing the dialog should REPORT.

    Falling back to silence here would mean the one screen built to answer
    "what is it running" is quietest exactly when the answer matters.
    """
    assert expected in describe(_versions(mpv=mpv, mpv_path=path))


# ── the licence obligation ──────────────────────────────────────────────────

def test_the_bundled_gpl_component_is_disclosed(qtbot) -> None:
    """A packaged build ships mpv, so the notice is owed, not optional."""
    names = {name for name, _licence, _where in BUNDLED_COMPONENTS}
    assert "mpv" in names, "mpv is vendored into the app bundle and must be listed"

    text = AboutDialog._licence_text()
    assert "GPL" in text, f"no licence named for a redistributed binary:\n{text}"
    assert "github.com/mpv-player/mpv" in text, "GPL notice must point at the source"


def test_every_bundled_component_names_a_licence_and_a_source() -> None:
    """Derived from the tuple, so a component added tomorrow is checked then."""
    for name, licence, where in BUNDLED_COMPONENTS:
        assert licence.strip(), f"{name} has no licence"
        assert "http" in where, f"{name} has no source link"


# ── the copy button ─────────────────────────────────────────────────────────

def test_copy_puts_the_same_text_on_the_clipboard(qtbot) -> None:
    from PyQt6.QtWidgets import QApplication

    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    dlg._copy_details()

    assert QApplication.clipboard().text() == describe(collect())
    assert dlg._copy_btn.text() == "Copied", "no feedback that anything happened"
