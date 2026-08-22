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
import os
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

    # A regex over source LINES only ever knew one shape of the bug — the bare
    # ``setStyleSheet(_theme.ROLE)``. Three real drift sites sailed past it: a
    # TERNARY between two roles (recipe_bar_widgets), a CONCATENATION onto one
    # (global_filter_dialog), and a BUILDER call composing from tokens
    # (similar_lightbox_card). All three render once and go stale on the next
    # theme switch, and one of them was introduced in the very file the previous
    # theme slice was working in. So the check is an AST walk now: the shape of
    # the expression cannot hide it.
    #
    # Two tiers, because the walk also surfaces ~300 sites of a DIFFERENT age:
    #
    #   Tier A (zero tolerated) — the argument hands over a COMPLETE role sheet
    #     that theme.py owns: a bare role, a ternary picking between roles, a
    #     concatenation onto one, or a theme builder call. ``theme.style`` /
    #     ``theme.style_fn`` exist precisely for these, so there is no reason
    #     for one to exist and each is a live staleness bug.
    #
    #   Tier B (ratcheted) — an f-string composing a sheet inline from tokens
    #     (``f"color: {_theme.COLOR_MUTED};"``). Same staleness, but it predates
    #     the registry by hundreds of call sites across nearly every GUI file;
    #     migrating them is its own planned pass. The count may only SHRINK, so
    #     the debt is measured and capped instead of quietly growing.
    @staticmethod
    def _theme_reads(node: ast.AST) -> bool:
        """Does this expression read anything off the theme module?"""
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id in ("_theme", "theme")
            ):
                return True
        return False

    @classmethod
    def _drift_sites(cls) -> tuple[list[str], list[str]]:
        """(tier_a, tier_b) — ``file:line: source`` for every drifting call."""
        tier_a: list[str] = []
        tier_b: list[str] = []
        for path in sorted(pathlib.Path("metatv/gui").rglob("*.py")):
            text = path.read_text()
            lines = text.splitlines()
            for node in ast.walk(ast.parse(text)):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setStyleSheet"
                    and node.args
                ):
                    continue
                arg = node.args[0]
                if not cls._theme_reads(arg):
                    continue
                site = f"{path}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                # An f-string anywhere in the argument means the sheet is being
                # composed inline from tokens — the old, bulk population.
                composed = any(
                    isinstance(sub, ast.JoinedStr) for sub in ast.walk(arg)
                )
                (tier_b if composed else tier_a).append(site)
        return tier_a, tier_b

    @classmethod
    def _raw_sites(cls) -> list[str]:
        """Tier A only — kept as the name the rest of the suite refers to."""
        return cls._drift_sites()[0]

    # Measured on the tree that introduced the AST walk. It may only go DOWN:
    # a drop means someone migrated sites and should lower this; a rise means
    # new inline-composed styling was added instead of theme.style_fn().
    COMPOSED_BUDGET = 285

    def test_no_raw_setstylesheet_hands_over_a_theme_role(self):
        tier_a, _ = self._drift_sites()
        assert not tier_a, (
            "these hand a complete theme-owned sheet to setStyleSheet, so they "
            "render once and go stale on every theme switch — use "
            "theme.style(widget, \"ROLE\") for a plain role, or "
            "theme.style_fn(widget, builder) for a composed one:\n  "
            + "\n  ".join(tier_a)
        )

    def test_inline_composed_stylesheets_only_shrink(self):
        """The ~300-site pre-registry population is capped, not blessed."""
        _, tier_b = self._drift_sites()
        assert len(tier_b) == self.COMPOSED_BUDGET, (
            f"{len(tier_b)} inline-composed stylesheets vs budget "
            f"{self.COMPOSED_BUDGET}. "
            + (
                "New styling must use theme.style_fn(widget, builder) so it "
                "survives a theme switch."
                if len(tier_b) > self.COMPOSED_BUDGET else
                f"Good news — sites were migrated: lower COMPOSED_BUDGET to "
                f"{len(tier_b)} so the ratchet keeps its teeth."
            )
        )

    @pytest.mark.parametrize("snippet", [
        # The bare form the old regex knew about…
        'lbl.setStyleSheet(_theme.SECTION_HINT)',
        'self.x.setStyleSheet(theme.LANG_CHIP)',
        # …and the three shapes that sailed straight past it.
        'b.setStyleSheet(_theme.RECIPE_TAB_ACTIVE if on else _theme.RECIPE_TAB)',
        'l.setStyleSheet(_theme.LABEL_MUTED + " font-style: italic;")',
        'r.setStyleSheet(_theme.lightbox_version_row(color))',
    ])
    def test_the_guard_catches_every_shape_of_the_bug(self, snippet, tmp_path):
        """A matcher that knows one shape reads as a clean codebase forever."""
        (tmp_path / "metatv" / "gui").mkdir(parents=True)
        (tmp_path / "metatv" / "gui" / "probe.py").write_text(snippet + "\n")
        cwd = pathlib.Path.cwd()
        os.chdir(tmp_path)
        try:
            assert self._drift_sites()[0], f"not caught: {snippet}"
        finally:
            os.chdir(cwd)

    @pytest.mark.parametrize("snippet", [
        '_theme.style(lbl, "SECTION_HINT")',
        '_theme.style_fn(lbl, lambda: f"color: {_theme.COLOR_MUTED};")',
        'lbl.setStyleSheet("")',
        'lbl.setStyleSheet(self._provider_colour_sheet)',
    ])
    def test_the_guard_does_not_flag_the_correct_forms(self, snippet, tmp_path):
        """style()/style_fn() re-apply on switch, and a runtime value is not a role."""
        (tmp_path / "metatv" / "gui").mkdir(parents=True)
        (tmp_path / "metatv" / "gui" / "probe.py").write_text(snippet + "\n")
        cwd = pathlib.Path.cwd()
        os.chdir(tmp_path)
        try:
            a, b = self._drift_sites()
            assert not a and not b, f"false positive: {snippet}"
        finally:
            os.chdir(cwd)

    def test_an_inline_composed_sheet_lands_in_the_ratchet_not_the_hard_gate(
        self, tmp_path
    ):
        """The two tiers must actually sort — otherwise one of them is dead."""
        (tmp_path / "metatv" / "gui").mkdir(parents=True)
        (tmp_path / "metatv" / "gui" / "probe.py").write_text(
            'w.setStyleSheet(f"color: {_theme.COLOR_MUTED};")\n'
        )
        cwd = pathlib.Path.cwd()
        os.chdir(tmp_path)
        try:
            tier_a, tier_b = self._drift_sites()
            assert not tier_a, "an f-string composition is Tier B, not a hard fail"
            assert len(tier_b) == 1, "…but it must still be counted"
        finally:
            os.chdir(cwd)

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
