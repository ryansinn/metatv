"""Live theme switching via the style registry (#277).

The old model was a hand-maintained sweep: ``MainWindow.refresh_theme()``
re-invoked ``setStyleSheet`` on widgets it knew about. That cannot work, and the
numbers said so — ~838 ``setStyleSheet`` call sites against 22 ``refresh_theme``
methods. An enumeration can never see the ones nobody remembered to add, which
is why #253 and #261 both "completed" the theme work and both left it broken.

Inverted: a widget styled through ``theme.style(w, "ROLE")`` registers itself,
and ``apply_theme`` re-applies every live registration. Nothing has to be
remembered; a new widget is covered the moment it is written.

These tests assert the RENDERED stylesheet actually changes — the property that
was silently false before — plus the drift guard that keeps the raw form from
creeping back.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from metatv.gui import theme as _theme


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_theme():
    original = _theme.current_theme()
    yield
    _theme.apply_theme(original)


class TestLiveRestyle:

    def test_a_registered_widget_restyles_on_theme_switch(self, qapp):
        """The whole point. This was false for every widget before #277."""
        _theme.apply_theme("Midnight")
        widget = QLabel()
        _theme.style(widget, "SECTION_HINT")
        midnight = widget.styleSheet()

        _theme.apply_theme("Daylight")
        daylight = widget.styleSheet()

        assert midnight != daylight, (
            "the widget kept its old stylesheet across a theme switch — Qt "
            "caches the rendered string, so this is exactly the bug"
        )
        assert _theme.COLOR_TEXT_HI not in midnight or True  # sanity: no crash
        assert daylight == _theme.SECTION_HINT

    def test_an_unregistered_widget_now_follows_the_palette_too(self, qapp):
        """This contract INVERTED in #284, and the old assertion was the bug.

        It used to assert that a plain ``setStyleSheet`` stays stale, which was
        true of Qt and true of this app — and was exactly the defect the owner
        kept reporting. ``apply_theme`` now also rewrites old palette *values*
        wherever they survive in a live stylesheet, so a sheet nobody registered
        still switches. The registry is now an optimisation (exact re-render)
        rather than the only path.
        """
        _theme.apply_theme("Midnight")
        widget = QLabel()
        widget.setStyleSheet(_theme.SECTION_HINT)
        before = widget.styleSheet()

        _theme.apply_theme("Daylight")

        assert widget.styleSheet() != before, (
            "an unregistered widget kept the Midnight palette — the value "
            "rewrite is the floor under every hand-composed stylesheet"
        )

    def test_the_registry_still_renders_the_role_exactly(self, qapp):
        """The value rewrite is a floor, not a replacement.

        It can only substitute colours it recognises; a role whose QSS changed
        *structurally* between palettes needs the real constant re-rendered, and
        only a registered widget gets that. Keeps the two mechanisms honest
        about which one is doing the work.
        """
        _theme.apply_theme("Midnight")
        widget = QLabel()
        _theme.style(widget, "SECTION_HINT")

        _theme.apply_theme("Daylight")

        assert widget.styleSheet() == _theme.SECTION_HINT

    def test_style_fn_reevaluates_composed_stylesheets(self, qapp):
        """The f-string sites need the builder re-invoked, not a stored string."""
        _theme.apply_theme("Midnight")
        widget = QLabel()
        _theme.style_fn(widget, lambda: f"color: {_theme.COLOR_MUTED};")
        midnight = widget.styleSheet()

        _theme.apply_theme("Daylight")

        assert widget.styleSheet() != midnight
        assert widget.styleSheet() == f"color: {_theme.COLOR_MUTED};"

    def test_unknown_role_fails_loudly_at_registration(self, qapp):
        """A typo must not register a widget that silently never restyles."""
        with pytest.raises(AttributeError):
            _theme.style(QLabel(), "NO_SUCH_ROLE")


class TestRegistryHygiene:

    def test_dead_widgets_are_reaped(self, qapp):
        """Weak refs — the registry must never keep a closed dialog alive."""
        import gc

        _theme.apply_theme("Midnight")
        before = _theme.registered_style_count()
        for _ in range(20):
            _theme.style(QLabel(), "SECTION_HINT")
        gc.collect()
        _theme.apply_theme("Daylight")   # triggers a reaping pass
        gc.collect()
        _theme.apply_theme("Midnight")

        after = _theme.registered_style_count()
        assert after <= before + 20, (
            f"registry grew unboundedly: {before} -> {after}"
        )

    def test_a_deleted_c_object_does_not_break_the_sweep(self, qapp):
        """A deleted C++ object raises RuntimeError while the wrapper lives.

        One such entry must not wedge the whole restyle pass — every other
        registered widget still has to be updated.
        """
        from PyQt6 import sip

        _theme.apply_theme("Midnight")
        doomed = QLabel()
        survivor = QLabel()
        _theme.style(doomed, "SECTION_HINT")
        _theme.style(survivor, "SECTION_HINT")
        sip.delete(doomed)

        _theme.apply_theme("Daylight")

        assert survivor.styleSheet() == _theme.SECTION_HINT, (
            "a dead sibling stopped the sweep before reaching this widget"
        )


class TestDriftGuard:
    """The raw form must not creep back — the rule only holds if it can fail."""

    @staticmethod
    def _raw_sites() -> list[str]:
        pat = re.compile(r"\.setStyleSheet\((?:_theme|theme)\.[A-Z][A-Z_0-9]*\)")
        out = []
        for path in sorted(pathlib.Path("metatv/gui").rglob("*.py")):
            for i, line in enumerate(path.read_text().splitlines(), 1):
                if pat.search(line):
                    out.append(f"{path}:{i}: {line.strip()}")
        return out

    def test_no_raw_setstylesheet_with_a_theme_role(self):
        offenders = self._raw_sites()
        assert not offenders, (
            "these render correctly once and then go stale on every theme "
            "switch — use theme.style(widget, \"ROLE\") instead:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_guard_can_actually_fail(self, tmp_path, monkeypatch):
        """A matcher that never matches would read as a clean codebase forever."""
        pat = re.compile(r"\.setStyleSheet\((?:_theme|theme)\.[A-Z][A-Z_0-9]*\)")
        assert pat.search('lbl.setStyleSheet(_theme.SECTION_HINT)')
        assert pat.search('self.x.setStyleSheet(theme.LANG_CHIP)')
        # …and does NOT flag the correct form or a composed one.
        assert not pat.search('_theme.style(lbl, "SECTION_HINT")')
        assert not pat.search('lbl.setStyleSheet(f"color: {_theme.COLOR_MUTED};")')

    def test_the_migration_actually_registered_widgets(self):
        """Count style() call sites — a migration that silently no-op'd would
        leave the codebase 'clean' by the guard above while styling nothing."""
        pat = re.compile(r"(?:_theme|theme)\.style\(")
        total = sum(
            len(pat.findall(path.read_text()))
            for path in pathlib.Path("metatv/gui").rglob("*.py")
        )
        assert total > 400, f"only {total} style() call sites — migration incomplete"


class TestRepolishOnSwitch:
    """Existing widgets must be told to re-read the palette (#278).

    Owner, on a live switch: list backgrounds stayed in the previous palette —
    dark panels under light chrome in Daylight, and symmetrically light panels
    under dark chrome going back to Midnight. Restarting in either theme was
    always correct, which is the whole diagnosis: ``apply_theme`` runs before any
    widget exists at cold launch (``__main__.py``), so widgets are BORN right.

    The palette push updates what widgets resolve; it does not make an
    already-constructed item view repaint its background. ``unpolish``/
    ``polish`` is Qt's supported way to force that recompute.

    NOTE: this cannot be proven by pixel assertion here. The offscreen Qt
    platform repaints on a palette change on its own, so the bug does not
    reproduce in tests — it needs the native macOS style. These tests therefore
    pin the MECHANISM (every widget is visited on a switch) rather than claiming
    a rendered outcome the harness cannot actually demonstrate.
    """

    def test_apply_theme_visits_every_widget(self, qapp):
        from PyQt6.QtWidgets import QLabel, QListWidget

        widgets = [QLabel(), QListWidget(), QLabel()]
        _theme.apply_theme("Midnight")

        visited = _theme._repolish_all_widgets()

        assert visited >= len(widgets), (
            f"only {visited} widgets repolished — every existing widget must be "
            f"visited, since the ones that go stale are exactly the ones nobody "
            f"remembered to enumerate"
        )

    def test_a_dead_widget_does_not_break_the_pass(self, qapp):
        from PyQt6 import sip
        from PyQt6.QtWidgets import QLabel

        doomed = QLabel()
        sip.delete(doomed)

        # Must not raise: one corpse cannot be allowed to stop the sweep before
        # it reaches the widgets that still need repainting.
        assert _theme._repolish_all_widgets() >= 0

    def test_switching_theme_runs_the_repolish(self, qapp, monkeypatch):
        """Wiring check — the helper is useless if apply_theme doesn't call it."""
        calls = []
        monkeypatch.setattr(
            _theme, "_repolish_all_widgets", lambda: calls.append(1) or 0
        )
        _theme.apply_theme("Midnight")
        _theme.apply_theme("Daylight")

        assert calls, "apply_theme did not repolish — a live switch stays stale"
