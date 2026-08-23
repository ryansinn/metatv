"""The legacy appearance-named greys may no longer paint TEXT.

The DTCG token layer declares exactly two text roles — ``on-surface.strong``
(``COLOR_TEXT_HI``) and ``on-surface.default`` (``COLOR_TEXT``) — plus
``.disabled`` and ``.placeholder`` for states. ``COLOR_FAINT``/``COLOR_MUTED``/
``COLOR_DIM`` are pre-token greys named by appearance, and **none of them clears
4.5:1 against any app surface in any palette** (36/36 combinations failed before
this migration). They survive only for non-text use — borders, backgrounds — which
the token spec exempts from the text floor by definition.

FAILS against the pre-migration tree with ~94 offending sites.
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

_GUI = Path(__file__).resolve().parents[1] / "metatv" / "gui"
_LEGACY = ("COLOR_FAINT", "COLOR_MUTED", "COLOR_DIM")

# A CSS `color:` declaration — inside a string literal, so a Python parameter
# annotation (``color: str = ...``) is not mistaken for one — fed by a legacy
# grey, in either an f-string hole or a `" + TOKEN + "` concatenation.
_GREY = r"(?:_theme\.|theme\.)?(?:COLOR_FAINT|COLOR_MUTED|COLOR_DIM)\b"
_TEXT_USE = re.compile(
    r"[\"']"                       # we are inside a string literal
    r"[^\"']*?"
    r"(?<![-a-z])color\s*:\s*"
    r"(?:[^;{}]{0,40}?)"            # quotes/+ allowed: the concatenation form
    r"(?:\{\s*" + _GREY + r"\s*\}|" + _GREY + r")"
)


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Source lines with comments and docstrings stripped, so prose explaining
    the migration is never itself flagged."""
    text = path.read_text()
    drop: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                drop.add(tok.start[0])
            elif tok.type == tokenize.STRING:
                stripped = tok.line.lstrip()
                if stripped[:3] in ('"""', "'''") or stripped[:4] in ('r"""', "r'''"):
                    for ln in range(tok.start[0], tok.end[0] + 1):
                        drop.add(ln)
    except tokenize.TokenError:
        pass
    return [(i, l) for i, l in enumerate(text.splitlines(), 1) if i not in drop]


def _sources() -> list[Path]:
    return [p for p in sorted(_GUI.rglob("*.py")) if p.name != "theme_palettes.py"]


def test_legacy_greys_never_paint_text() -> None:
    offenders: list[str] = []
    for path in _sources():
        for lineno, line in _code_lines(path):
            if _TEXT_USE.search(line):
                rel = path.relative_to(_GUI.parents[1])
                offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    assert not offenders, (
        "COLOR_FAINT/MUTED/DIM cannot clear 4.5:1 on any surface — use "
        "COLOR_TEXT for body text, COLOR_TEXT_HI for titles, or COLOR_DISABLED "
        "for a deliberately dimmed state:\n  " + "\n  ".join(offenders)
    )


def test_the_matcher_can_actually_fail() -> None:
    """A matcher that never matches reads as a clean codebase forever."""
    assert _TEXT_USE.search('f"color: {_theme.COLOR_FAINT};"')
    assert _TEXT_USE.search('"color: " + COLOR_MUTED + ";"')
    assert _TEXT_USE.search('f"font-size: 11px; color: {_theme.COLOR_DIM};"')
    # ...and leaves the legitimate non-text uses alone
    assert not _TEXT_USE.search('f"border: 1px solid {_theme.COLOR_FAINT};"')
    assert not _TEXT_USE.search('f"background-color: {_theme.COLOR_MUTED};"')
    assert not _TEXT_USE.search('f"color: {_theme.COLOR_TEXT};"')
    assert not _TEXT_USE.search('f"color: {_theme.COLOR_DISABLED};"')


def test_the_two_text_roles_clear_aa_on_every_surface() -> None:
    """The roles the migration points at must actually be legible."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from metatv.gui import theme as _theme

    def _lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def _lum(h: str) -> float:
        h = h.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)

    def _cr(a: str, b: str) -> float:
        la, lb = _lum(a), _lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    surfaces = ("COLOR_BG_SECTION", "COLOR_BG_CARD", "COLOR_BG_BAR", "COLOR_BG_DEEP")
    failures: list[str] = []
    for palette in ("Midnight", "Graphite", "Daylight"):
        _theme.apply_theme(palette)
        for role in ("COLOR_TEXT", "COLOR_TEXT_HI"):
            fg = getattr(_theme, role)
            for surf in surfaces:
                bg = getattr(_theme, surf, None)
                if not bg:
                    continue
                ratio = _cr(fg, bg)
                if ratio < 4.5:
                    failures.append(f"{palette} {role} on {surf}: {ratio:.2f}:1")
    assert not failures, "text roles below AA:\n  " + "\n  ".join(failures)
