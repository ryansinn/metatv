"""Behavioral tests for the theme system (wave7/theme-system): named palettes
in ``theme_palettes.py``, live ``theme.apply_theme()`` re-binding of BOTH the
raw design tokens and every composed semantic constant, the "every palette
defines the same token key set" contract, the import-time-capture guard (no
consumer froze a token's value at import instead of reading it at use time),
and the Settings dialog round-trip + live-reapply wiring.

Covers:
1. Midnight's values equal the pre-wave7 hardcoded constants exactly, on a
   representative sample spanning every token category — the "no visual
   regression" guard for the shipped default palette.
2. Every palette in ``theme_palettes.PALETTES`` defines exactly the same key
   set as Midnight (parametrized) — a palette missing a key would leave a
   stale/undefined attribute on ``theme`` after switching to it.
3. ``theme.apply_theme()`` actually rebinds BOTH raw tokens and composed
   semantic constants (not just the former — semantic constants are plain
   strings built once by concatenation, so they'd otherwise go stale), swaps
   back cleanly, and reports changed/no-op/unknown-name correctly.
4. No module outside theme.py/theme_palettes.py captures a `theme`/`_theme`
   token into a module- or class-level constant (which would freeze it at
   import time instead of re-reading it after a live theme switch) — an AST
   scan across metatv/, mirroring the manual audit that found and fixed 14
   such files before this PR.
5. The Settings → Interface → Appearance combo's load/save helpers round-trip
   through a fake config (mirrors ``test_channel_row_density.py``'s density
   round-trip tests) and fall back to Midnight on an unknown/stale value.
6. ``MainWindow.refresh_theme()`` calls ``theme.apply_theme()`` and sweeps the
   sidebar sections / details pane / channel-list repaint — and skips the
   sweep entirely when the palette didn't actually change (no-op short
   circuit), exercised against a fake ``self`` (mirrors
   ``test_apply_channel_list_density_updates_delegate_and_emits_layout_changed``).

Every test executes the changed path and asserts an outcome that would break
if the theme-swap logic regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QComboBox

from metatv.gui import theme
from metatv.gui import theme_palettes
from metatv.gui.main_window import MainWindow
from metatv.gui.settings_dialog import _load_theme_combo, _save_theme_combo

_GUI_ROOT = Path(__file__).resolve().parent.parent / "metatv"


@pytest.fixture(autouse=True)
def _reset_active_theme():
    """``theme.py``'s active palette is process-global module state — leaving
    it on anything but Midnight after this file's tests run would silently
    change every OTHER test file's expected colours for the rest of the
    pytest session. Force Midnight before AND after every test here.
    """
    theme.apply_theme("Midnight")
    yield
    theme.apply_theme("Midnight")


# ---------------------------------------------------------------------------
# 1. Midnight == the pre-wave7 hardcoded constants (representative sample)
# ---------------------------------------------------------------------------

# One or more tokens from every category in theme_palettes.py's MIDNIGHT dict,
# with the EXACT values theme.py hardcoded before this PR — not exhaustive
# (150+ tokens), but broad enough that a regression in any category trips it.
_MIDNIGHT_PIN: dict[str, object] = {
    # Text ramp
    "COLOR_TEXT_HI": "#fff",
    "COLOR_TEXT": "#ccc",
    "COLOR_MUTED": "#888",
    "COLOR_FAINT": "#555",
    "COLOR_GRAY": "gray",
    "COLOR_LIGHTGRAY": "lightgray",
    # Structural
    "COLOR_BORDER": "#444",
    "COLOR_LINE": "#333",
    "COLOR_BG_BAR": "#1e1e1e",
    "COLOR_BG_CARD": "#252525",
    # Accent + status
    "COLOR_ACCENT": "#2288dd",
    "COLOR_OK": "#4CAF50",
    "COLOR_WARN": "#FFC107",
    "COLOR_ERR": "#F44336",
    "COLOR_GOLD": "gold",
    # Overlays
    "OVERLAY_05": "rgba(255,255,255,0.05)",
    "OVERLAY_POPUP": "rgba(40,40,50,0.97)",
    "OVERLAY_SELECTION": "rgba(68,136,255,0.16)",
    # Badge/mood/notify/banner/facet/recipe families (theme-invariant by design)
    "COLOR_QUALITY_UHD": "#7755cc",
    "COLOR_MOOD_LIKE_BG": "#2ecc71",
    "COLOR_NOTIFY_ERR_BG": "#2c1515",
    "COLOR_BANNER_YEL_FG": "#e8d44d",
    "COLOR_FACET_GENRE": "#7bd88f",
    "COLOR_RECIPE_TEXT": "#edeae0",
    "COLOR_BG_DEEP": "#111111",
    "COLOR_LIGHTBOX_BG": "#1e1e2e",
    "BACKDROP_TINTS": ["#1a3a5c", "#2d4a1e", "#4a1e2d", "#2d1e4a", "#1e4a3a", "#3a2d1e"],
    # Type scale (never varies by palette)
    "FONT_MD": "11px",
    "FONT_CLOUD_1": "11px",
    "FONT_4XL": "20px",
}


class TestMidnightIsThePreChangeConstants:
    """Both the raw palette dict AND theme.py's resting module globals (with
    Midnight active, the default) must equal the old hardcoded values."""

    @pytest.mark.parametrize("name,expected", sorted(_MIDNIGHT_PIN.items(), key=str))
    def test_midnight_palette_dict_value(self, name, expected):
        assert theme_palettes.MIDNIGHT[name] == expected

    @pytest.mark.parametrize("name,expected", sorted(_MIDNIGHT_PIN.items(), key=str))
    def test_midnight_is_the_resting_module_global(self, name, expected):
        assert getattr(theme, name) == expected

    def test_midnight_is_the_default_palette(self):
        assert theme_palettes.DEFAULT_PALETTE == "Midnight"
        assert theme.current_theme() == "Midnight"

    def test_derived_tokens_track_their_source_token(self):
        """COLOR_SPLITTER_GRIP/COLOR_FACET_CATEGORY/COLOR_LINK aren't stored in
        the palette dicts — they're recomputed FROM another token every time
        tokens are (re)bound, same as before this PR."""
        assert theme.COLOR_SPLITTER_GRIP == theme.COLOR_MUTED_2
        assert theme.COLOR_FACET_CATEGORY == theme.COLOR_ACCENT_ORANGE
        assert theme.COLOR_LINK == theme.COLOR_ACCENT_BLUE


# ---------------------------------------------------------------------------
# 2. Every palette defines exactly the same token key set
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", list(theme_palettes.PALETTES.keys()))
def test_palette_key_set_matches_midnight(palette_name):
    palette = theme_palettes.PALETTES[palette_name]
    assert set(palette.keys()) == set(theme_palettes.MIDNIGHT.keys()), (
        f"{palette_name} is missing or has extra keys vs Midnight — every "
        f"palette must define the exact same token names "
        f"(missing: {set(theme_palettes.MIDNIGHT) - set(palette)}, "
        f"extra: {set(palette) - set(theme_palettes.MIDNIGHT)})"
    )


def test_at_least_midnight_graphite_daylight_shipped():
    assert {"Midnight", "Graphite", "Daylight"} <= set(theme_palettes.PALETTES.keys())


def test_available_themes_matches_palettes():
    assert theme.available_themes() == list(theme_palettes.PALETTES.keys())


# ---------------------------------------------------------------------------
# 3. apply_theme() rebinds tokens AND semantic constants, swaps back cleanly
# ---------------------------------------------------------------------------

def test_apply_theme_rebinds_raw_tokens():
    before = theme.COLOR_TEXT_HI
    changed = theme.apply_theme("Daylight")
    assert changed is True
    assert theme.COLOR_TEXT_HI == theme_palettes.DAYLIGHT["COLOR_TEXT_HI"]
    assert theme.COLOR_TEXT_HI != before
    assert theme.current_theme() == "Daylight"


def test_apply_theme_rebinds_composed_semantic_constants():
    """The critical live-reapply mechanism: semantic constants (PLAY_BTN,
    PANEL_BTN, ...) are plain strings concatenated ONCE from tokens — proving
    a themed one (built from a token whose VALUE differs across palettes)
    actually changes confirms _build_semantic_constants() really re-runs,
    not just the raw token layer."""
    midnight_panel_btn = theme.PANEL_BTN
    assert theme_palettes.MIDNIGHT["COLOR_LINE"] != theme_palettes.DAYLIGHT["COLOR_LINE"]

    theme.apply_theme("Daylight")

    assert theme.PANEL_BTN != midnight_panel_btn
    assert theme_palettes.DAYLIGHT["COLOR_LINE"] in theme.PANEL_BTN


def test_apply_theme_swap_back_restores_exact_original_values():
    originals = {name: getattr(theme, name) for name in _MIDNIGHT_PIN}
    original_panel_btn = theme.PANEL_BTN

    theme.apply_theme("Graphite")
    theme.apply_theme("Daylight")
    changed_back = theme.apply_theme("Midnight")

    assert changed_back is True
    assert theme.PANEL_BTN == original_panel_btn
    for name, value in originals.items():
        assert getattr(theme, name) == value


def test_apply_theme_same_name_is_a_noop():
    theme.apply_theme("Daylight")
    assert theme.apply_theme("Daylight") is False  # already active


def test_apply_theme_unknown_name_is_a_noop():
    before = theme.COLOR_TEXT_HI
    assert theme.apply_theme("Nonexistent Palette") is False
    assert theme.COLOR_TEXT_HI == before
    assert theme.current_theme() == "Midnight"


def test_fixed_dark_lightbox_family_is_theme_invariant():
    """COLOR_LIGHTBOX_TEXT_HI/COLOR_LIGHTBOX_TEXT (and the fixed dark
    COLOR_LIGHTBOX_BG/COLOR_BG_DEEP backdrop they sit on) never change —
    Similar-Titles/Explore trail-map stays a dark "cinema" surface regardless
    of the active app palette, so its own text tokens must too."""
    midnight_title = theme.LIGHTBOX_TITLE
    theme.apply_theme("Daylight")
    assert theme.LIGHTBOX_TITLE == midnight_title
    assert theme.COLOR_LIGHTBOX_TEXT_HI == "#fff"
    assert theme.COLOR_LIGHTBOX_BG == theme_palettes.MIDNIGHT["COLOR_LIGHTBOX_BG"]


# ---------------------------------------------------------------------------
# 4. No consumer captures a theme token at import time
# ---------------------------------------------------------------------------

def _find_import_time_theme_captures(root: Path) -> list[str]:
    """AST scan: module-level or class-level (never inside a function/method
    body — those read at call time already) assignments whose value
    expression references a `theme`/`_theme` attribute. Mirrors the manual
    audit that found (and this PR's authors fixed) 14 such files.
    """

    class _RefFinder(ast.NodeVisitor):
        def __init__(self):
            self.found = False

        def visit_Attribute(self, node):
            base = node.value
            if isinstance(base, ast.Name) and base.id in ("theme", "_theme"):
                self.found = True
            self.generic_visit(node)

    def references_theme(expr) -> bool:
        f = _RefFinder()
        f.visit(expr)
        return f.found

    hits: list[str] = []

    for path in sorted(root.rglob("*.py")):
        if path.name in ("theme.py", "theme_palettes.py"):
            continue  # theme.py IS the token layer; theme_palettes.py is its data
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue

        def check_body(body, scope_label):
            for stmt in body:
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    if stmt.value is not None and references_theme(stmt.value):
                        hits.append(f"{path}:{stmt.lineno} [{scope_label}]")
                elif isinstance(stmt, ast.ClassDef):
                    check_body(stmt.body, f"class {stmt.name}")
                    # NOTE: intentionally does not descend into ast.FunctionDef —
                    # assignments inside a function/method body execute at CALL
                    # time, which is exactly what we want.

        check_body(tree.body, "module")

    return hits


def test_no_module_or_class_level_theme_token_capture():
    hits = _find_import_time_theme_captures(_GUI_ROOT)
    assert hits == [], (
        "Found module/class-level constant(s) built from a theme token at "
        "IMPORT time — these freeze whatever palette was active when the "
        "module first loaded and go stale after theme.apply_theme(). Convert "
        "to a function (or read the theme.* attribute directly at the use "
        "site) instead:\n" + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# 5. Settings dialog Appearance combo round-trips through config
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_settings_dialog_theme_helpers_round_trip(qapp):
    combo = QComboBox()
    for palette_name in theme_palettes.PALETTES:
        combo.addItem(palette_name, palette_name)
    cfg = SimpleNamespace(theme_name="Daylight")

    _load_theme_combo(combo, cfg)
    assert combo.currentData() == "Daylight"

    combo.setCurrentIndex(combo.findData("Graphite"))
    _save_theme_combo(combo, cfg)
    assert cfg.theme_name == "Graphite"


def test_settings_dialog_theme_load_unknown_falls_back_to_midnight(qapp):
    combo = QComboBox()
    for palette_name in theme_palettes.PALETTES:
        combo.addItem(palette_name, palette_name)
    cfg = SimpleNamespace(theme_name="a-removed-palette-name")

    _load_theme_combo(combo, cfg)
    assert combo.currentData() == "Midnight"


def test_config_theme_name_defaults_to_midnight():
    from metatv.core.config import Config
    cfg, _ = Config.load()
    assert cfg.theme_name == "Midnight"


def test_config_theme_name_persists_through_save_and_reload():
    from metatv.core.config import Config
    cfg, _ = Config.load()
    cfg.theme_name = "Daylight"
    cfg.save()

    reloaded, _ = Config.load()
    assert reloaded.theme_name == "Daylight"


# ---------------------------------------------------------------------------
# 6. MainWindow.refresh_theme() sweeps the live surfaces, no-ops when unchanged
# ---------------------------------------------------------------------------

_REFRESH_THEME = MainWindow.refresh_theme


def test_refresh_theme_applies_palette_and_sweeps_live_surfaces(qapp):
    section = MagicMock()
    details_pane = MagicMock()
    channels_list = MagicMock()

    fake_self = SimpleNamespace(
        config=SimpleNamespace(theme_name="Daylight"),
        sidebar_sections={"favorites": section},
        details_pane=details_pane,
        channels_list=channels_list,
    )

    _REFRESH_THEME(fake_self)

    assert theme.current_theme() == "Daylight"
    section.refresh_theme.assert_called_once()
    details_pane.refresh_theme.assert_called_once()
    channels_list.viewport.return_value.update.assert_called_once()


def test_refresh_theme_is_a_noop_when_palette_unchanged(qapp):
    theme.apply_theme("Midnight")  # already active — matches fake_self below

    section = MagicMock()
    details_pane = MagicMock()
    channels_list = MagicMock()

    fake_self = SimpleNamespace(
        config=SimpleNamespace(theme_name="Midnight"),
        sidebar_sections={"favorites": section},
        details_pane=details_pane,
        channels_list=channels_list,
    )

    _REFRESH_THEME(fake_self)

    section.refresh_theme.assert_not_called()
    details_pane.refresh_theme.assert_not_called()
    channels_list.viewport.assert_not_called()


def test_refresh_theme_tolerates_missing_optional_attrs(qapp):
    """A fake_self with none of the guarded self.* chrome attrs must not
    raise — every widget-sweep block is hasattr-gated (mirrors
    _apply_channel_list_density's own hasattr guard for _split_toggle_btn)."""
    fake_self = SimpleNamespace(config=SimpleNamespace(theme_name="Graphite"))

    _REFRESH_THEME(fake_self)  # must not raise

    assert theme.current_theme() == "Graphite"
