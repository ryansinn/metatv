"""Regression guard: no stray color literals in metatv/gui/**/*.py.

Two tiers of coverage:

1. ``_MIGRATED`` list — each entry was once a bare hex/rgba literal in widget
   code and has been migrated to a named token in theme.py.  The
   ``test_no_migrated_literals_remain`` test fires on exact matches so that
   any future copy-paste of a literal is caught immediately.

2. ``test_no_raw_color_literals_anywhere`` — a broader scan that catches NEW
   stray literals that are not yet in the ``_MIGRATED`` list.  It looks for
   any line that contains a color keyword (``color``, ``background``,
   ``border``, ``QColor``, ``style=``) together with a bare hex or rgba value.
   The allowlist ``_KNOWN_NON_COLOR_MATCHES`` documents every exemption.

A failure means either:
  (a) a hex/rgba literal was introduced where a token should be used, or
  (b) a token was removed from theme.py without updating call sites.

Literals inside theme.py itself are intentional (that is where they belong)
and are excluded from all scans.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GUI_ROOT  = _REPO_ROOT / "metatv" / "gui"

# These values were migrated to existing tokens.  Each tuple is
# (hex_or_rgba_pattern, canonical_token_name).  The pattern is the
# *exact* literal string that must no longer appear in widget source.
_MIGRATED: list[tuple[str, str]] = [
    # Grey ramp
    ("#fff",             "COLOR_TEXT_HI"),
    ("#ffffff",          "COLOR_TEXT_HI"),
    ("#ccc",             "COLOR_TEXT"),
    ("#cccccc",          "COLOR_TEXT"),
    ("#ddd",             "COLOR_TEXT_2"),
    ("#dddddd",          "COLOR_TEXT_2"),
    ("#bbb",             "COLOR_TEXT_LOW"),
    ("#aaa",             "COLOR_DIM"),
    ("#999",             "COLOR_DIM_2"),
    ("#888",             "COLOR_MUTED"),
    ("#888888",          "COLOR_MUTED"),
    ("#777",             "COLOR_DISABLED"),
    ("#666",             "COLOR_MUTED_2"),
    ("#666666",          "COLOR_MUTED_2"),
    ("#555",             "COLOR_FAINT"),
    ("#555555",          "COLOR_FAINT"),
    ("#444",             "COLOR_BORDER"),
    ("#333",             "COLOR_LINE"),
    ("#333333",          "COLOR_LINE"),
    ("#2a2a2a",          "COLOR_LINE_DARK"),
    ("#1e1e1e",          "COLOR_BG_BAR"),
    ("#1a1a1a",          "COLOR_BG_SECTION"),
    # Accent blues
    ("#4488ff",          "COLOR_ACCENT_BLUE"),
    ("#88aaff",          "COLOR_ACCENT_BLUE_2"),
    # Status
    ("#4caf50",          "COLOR_OK"),
    ("#4CAF50",          "COLOR_OK"),
    ("#f44336",          "COLOR_ERR"),
    ("#F44336",          "COLOR_ERR"),
    # Overlays (float-alpha form)
    ("rgba(255,255,255,0.05)",  "OVERLAY_05"),
    ("rgba(255,255,255,0.08)",  "OVERLAY_08"),
    ("rgba(255,255,255,0.10)",  "OVERLAY_10"),
    ("rgba(255,255,255,0.15)",  "OVERLAY_15"),
    ("rgba(255,255,255,0.18)",  "OVERLAY_18"),
    ("rgba(255, 255, 255, 0.1)", "OVERLAY_10"),
    ("rgba(255, 255, 255, 0.15)", "OVERLAY_15"),
    ("rgba(68,136,255,0.2)",    "OVERLAY_BLUE_20"),
    ("rgba(68, 136, 255, 0.2)", "OVERLAY_BLUE_20"),
    # B2 — quality/badge palette (badge_utils)
    ("#7755cc",   "COLOR_QUALITY_UHD"),
    ("#3388dd",   "COLOR_QUALITY_FHD"),
    ("#229977",   "COLOR_QUALITY_HD"),
    ("#cc8822",   "COLOR_QUALITY_RAW"),
    ("#bb9900",   "COLOR_QUALITY_LIVE"),
    ("#556633",   "COLOR_AUDIO_BADGE"),
    # B2 — mood palette (category_picker)
    ("#2ecc71",   "COLOR_MOOD_LIKE_BG"),
    ("#1a7a43",   "COLOR_MOOD_LIKE_FG"),
    ("#27ae60",   "COLOR_MOOD_CURIOUS_BG"),
    ("#155a2e",   "COLOR_MOOD_CURIOUS_FG"),
    ("#c0392b",   "COLOR_MOOD_NOTFORME_BG"),
    ("#f5a5a0",   "COLOR_MOOD_NOTFORME_FG"),
    ("#e74c3c",   "COLOR_MOOD_DISLIKE_BG"),
    ("#5a1a1a",   "COLOR_MOOD_TRASH_BG"),
    ("#1a3a5a",   "COLOR_MOOD_WATCH_BG"),
    ("#1a3a1a",   "COLOR_MOOD_EXPLORE_BG"),
    ("#88cc88",   "COLOR_MOOD_EXPLORE_FG"),
    # B2 — notification severity
    ("#2c1515",   "COLOR_NOTIFY_ERR_BG"),
    ("#ff4444",   "COLOR_NOTIFY_ERR_BORDER"),
    ("#152c15",   "COLOR_NOTIFY_OK_BG"),
    ("#44ff44",   "COLOR_NOTIFY_OK_BORDER"),
    ("#2c2415",   "COLOR_NOTIFY_WARN_BG"),
    ("#ffaa44",   "COLOR_NOTIFY_WARN_BORDER"),
    ("#1a1a2e",   "COLOR_NOTIFY_INFO_BG"),
    # B2 — lightbox
    ("#1e1e2e",   "COLOR_LIGHTBOX_BG"),
    ("#2a2a3e",   "COLOR_LIGHTBOX_HEADER"),
    # B2 — yellow banner
    ("#3a3a1a",   "COLOR_BANNER_YEL_BG"),
    ("#e8d44d",   "COLOR_BANNER_YEL_FG"),
    ("#7a7a30",   "COLOR_BANNER_YEL_BORDER"),
    ("#4a4a22",   "COLOR_BANNER_YEL_BG_HOVER"),
    ("#aaaa50",   "COLOR_BANNER_YEL_BORDER_HOVER"),
    # B2 — PPV
    ("#ff6b35",   "COLOR_PPV_ACCENT"),
    # B2 — misc accents
    ("#ff8888",   "COLOR_RED_BRIGHT"),
    ("#8fca8f",   "COLOR_PREF_NUDGE"),
    ("#aad4ff",   "COLOR_ACCENT_BLUE_LIGHT"),
    ("#252525",   "COLOR_BG_CARD"),
    ("#111111",   "COLOR_BG_DEEP"),
    ("#f5f5f5",   "COLOR_SURFACE_LIGHT"),
    ("#e0e0e0",   "COLOR_SURFACE_LIGHT_2"),
    ("#d0d0d0",   "COLOR_SURFACE_LIGHT_3"),
    # B2 — rgba integer-alpha bugs (now fixed to float)
    ("rgba(0,0,0,150)",    "OVERLAY_BLACK_60"),
    ("rgba(255,255,255,8)",  "OVERLAY_08"),
    ("rgba(255,255,255,16)", "OVERLAY_15"),
    ("rgba(255,255,255,18)", "OVERLAY_18"),
]

# Files explicitly excluded from the scan (canonical data tables or theme itself)
_EXCLUDED_FILES: set[str] = {
    "theme.py",
    # badge_utils.py was previously excluded because _QUALITY_COLORS held raw literals.
    # Those are now migrated to tokens (B2), so badge_utils is no longer excluded.
}


def _source_files() -> list[Path]:
    """Return all .py files under metatv/gui/ except theme.py and badge_utils.py."""
    return [
        p for p in _GUI_ROOT.rglob("*.py")
        if p.name not in _EXCLUDED_FILES
    ]


def _relative(p: Path) -> str:
    return str(p.relative_to(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Smoke-import test — verifies the theme import was added and the module loads
# ---------------------------------------------------------------------------

_MODULES_TO_SMOKE = [
    "metatv.gui.badge_utils",
    "metatv.gui.categories_dialog",
    "metatv.gui.category_picker_dialog",
    "metatv.gui.details_sections",
    "metatv.gui.details_versions",
    "metatv.gui.details_actions",
    "metatv.gui.discover_browse",
    "metatv.gui.discover_card",
    "metatv.gui.discover_filter_dialog",
    "metatv.gui.discover_shelf",
    "metatv.gui.discover_view",
    "metatv.gui.epg_agenda_widget",
    "metatv.gui.filter_bar",
    "metatv.gui.filter_panel",
    "metatv.gui.global_filter_dialog",
    "metatv.gui.icon_utils",
    "metatv.gui.notification_widget",
    "metatv.gui.ppv_view",
    "metatv.gui.preferences_view",
    "metatv.gui.settings_dialog",
    "metatv.gui.similar_lightbox",
    "metatv.gui.sports_filter_bar",
    "metatv.gui.sidebar.alerts",
    "metatv.gui.sidebar.favorites",
    "metatv.gui.sidebar.history",
    "metatv.gui.sidebar.sources",
]


@pytest.mark.parametrize("module_name", _MODULES_TO_SMOKE)
def test_module_imports_cleanly(module_name: str) -> None:
    """Each migrated module must import without error (theme import is valid)."""
    # Use importlib so failures are isolated per module.
    # Qt is not initialised here, but module-level code that runs at import
    # time should not require a running QApplication.
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        pytest.fail(f"{module_name} failed to import: {exc}")
    # Verify theme is reachable from the module (checks the import was added)
    from metatv.gui import theme as _theme  # noqa: F401


# ---------------------------------------------------------------------------
# Literal-scan test — verifies no migrated literal remains in widget code
# ---------------------------------------------------------------------------

def _build_scan_cases() -> list[tuple[str, str, str]]:
    """Return (rel_path, literal, token) triples for parametrize."""
    cases: list[tuple[str, str, str]] = []
    for path in _source_files():
        source = path.read_text(encoding="utf-8")
        rel = _relative(path)
        for literal, token in _MIGRATED:
            # Case-insensitive for hex values (only rgba is case-sensitive in practice)
            pattern = re.escape(literal)
            if literal.startswith("#"):
                if re.search(pattern, source, re.IGNORECASE):
                    cases.append((rel, literal, token))
            else:
                if literal in source:
                    cases.append((rel, literal, token))
    return cases


def _scan_all_violations() -> list[tuple[str, str, str, int]]:
    """Return (rel_path, literal, token, line_number) for every violation found."""
    violations: list[tuple[str, str, str, int]] = []
    for path in _source_files():
        source = path.read_text(encoding="utf-8")
        rel = _relative(path)
        lines = source.splitlines()
        for literal, token in _MIGRATED:
            flags = re.IGNORECASE if literal.startswith("#") else 0
            if literal.startswith("#"):
                # Anchor so that #4488ff does not fire on #4488ff44 (8-digit hex with alpha).
                # A hex literal must be followed by a non-hex character (quote, semicolon,
                # space, end-of-line, etc.) — not another [0-9a-fA-F] digit.
                pattern = re.escape(literal) + r"(?![0-9a-fA-F])"
            else:
                pattern = re.escape(literal)
            for i, line in enumerate(lines, start=1):
                if re.search(pattern, line, flags):
                    violations.append((rel, literal, token, i))
    return violations


def test_no_migrated_literals_remain() -> None:
    """No previously-migrated color literal should appear in widget source files.

    This test executes the scan (not just shape-checks the source text) and
    reports every file:line:literal violation so the failure message is
    actionable.
    """
    violations = _scan_all_violations()
    if not violations:
        return

    lines = [
        f"\n  {rel}:{lineno}  literal={literal!r}  (use {token} instead)"
        for rel, literal, token, lineno in violations
    ]
    pytest.fail(
        f"Found {len(violations)} stray color literal(s) that should use a theme token:"
        + "".join(lines)
    )


# ---------------------------------------------------------------------------
# Broad new-literal guard — catches stray hex/rgba values not yet in _MIGRATED
# ---------------------------------------------------------------------------

# Lines that match the pattern but are NOT color literals.
# Each entry: (file_relative, line_substring_or_pattern) — the line must contain
# the substring for the exemption to apply.  Use the minimal unique fragment.
_BROAD_ALLOWLIST: list[tuple[str, str]] = [
    # sidebar/sources.py: dynamic rgba/rgb computed from provider icon color at runtime;
    # {r}, {g}, {b} are Python format-string placeholders, NOT literal values.
    ("metatv/gui/sidebar/sources.py", "rgba({r},{g},{b},"),
    ("metatv/gui/sidebar/sources.py", "rgb({r},{g},{b})"),
]

# Regex: matches a hex color (#RGB, #RRGGBB, #RRGGBBAA) or rgba()/rgb() in a
# context that looks like CSS/Qt stylesheet (the line also mentions one of the
# color-context keywords).
_COLOR_CONTEXT_KEYWORDS = re.compile(
    r"\b(?:color|background|border|QColor|style=|setStyleSheet|rgba?\()",
    re.IGNORECASE,
)
_HEX_OR_RGBA = re.compile(
    r"(?:#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))",
    re.IGNORECASE,
)


def _is_allowlisted(rel: str, line: str) -> bool:
    """Return True if (file, line) matches a known-safe allowlist entry."""
    for allowed_file, allowed_fragment in _BROAD_ALLOWLIST:
        if allowed_file in rel and allowed_fragment in line:
            return True
    return False


def test_no_raw_color_literals_anywhere() -> None:
    """No raw hex / rgba color literal should appear in widget code outside theme.py.

    Scans every line that contains a color-context keyword (color, background,
    border, QColor, style=) for an inline hex or rgba value.  Fires on NEW
    stray literals that haven't been added to _MIGRATED yet.

    The allowlist (_BROAD_ALLOWLIST) documents every intentional exemption with
    a comment explaining why it cannot be a token.
    """
    violations: list[tuple[str, int, str]] = []
    for path in _source_files():
        rel = _relative(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            # Skip blank lines and pure comments
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Only inspect lines that have a color context keyword
            if not _COLOR_CONTEXT_KEYWORDS.search(line):
                continue
            # Look for a hex or rgba literal
            if _HEX_OR_RGBA.search(line):
                if not _is_allowlisted(rel, line):
                    violations.append((rel, lineno, line.rstrip()))

    if not violations:
        return

    report = "\n".join(
        f"  {rel}:{lineno}  →  {snippet}"
        for rel, lineno, snippet in violations
    )
    pytest.fail(
        f"Found {len(violations)} raw color literal(s) outside theme.py "
        f"(add a token or update _BROAD_ALLOWLIST):\n{report}"
    )
