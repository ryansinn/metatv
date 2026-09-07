"""One progress-bar sheet, and the filled part is visible against the trough.

Seven ``QProgressBar``s, five of which composed their own
``QProgressBar::chunk`` rule. They disagreed on the trough, the border, the
radius and the height — 6px via ``setFixedHeight``, 4px scaled by the card
zoom, and four that took Qt's default — none of which was a decision. The only
difference that means anything is the CHUNK colour, which says what is
progressing.

The assertion that matters is not "a builder exists": it is that a bar drawn
with a runtime chunk colour is still *visible* against its own trough in every
palette. A bar whose chunk matches its trough is a bar that reads as empty at
100%, and no token-existence check can tell those apart.
"""

from __future__ import annotations

import re

import pytest

from metatv.gui import theme as _theme
from metatv.gui.theme import _relative_luminance
from metatv.gui import theme_palettes


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _trough(sheet: str) -> str:
    """The ``background:`` of the ``QProgressBar`` rule — the empty part."""
    match = re.search(r"QProgressBar \{[^}]*background:\s*(#[0-9a-fA-F]{6})", sheet)
    assert match, f"no trough colour in {sheet!r}"
    return match.group(1)


def _chunk(sheet: str) -> str:
    """The ``background:`` of the ``::chunk`` rule — the filled part."""
    match = re.search(
        r"QProgressBar::chunk \{[^}]*background:\s*(#[0-9a-fA-F]{6})", sheet)
    assert match, f"no chunk colour in {sheet!r}"
    return match.group(1)


def _px(value: str) -> int:
    return int(value.replace("px", ""))


@pytest.fixture(autouse=True)
def _restore_theme():
    before = _theme.current_theme()
    yield
    _theme.apply_theme(before)


# ── rendered appearance ─────────────────────────────────────────────────────

@pytest.mark.parametrize("palette", sorted(theme_palettes.PALETTES))
def test_the_filled_part_reads_against_the_trough_in_every_palette(palette):
    """A chunk that matches its trough is a bar that looks empty when full.

    Proven to fail against the trough being swapped in for the chunk — the
    exact shape of the bug a per-widget composed sheet can introduce silently,
    because the two colours came from two different token families.
    """
    _theme.apply_theme(palette)
    sheet = _theme.progress_bar(_theme.COLOR_ACCENT_ORANGE)

    trough, chunk = _trough(sheet), _chunk(sheet)
    assert _contrast(chunk, trough) >= 3.0, (
        f"{palette}: the resume bar's fill is {_contrast(chunk, trough):.2f}:1 "
        f"against its own trough ({chunk} on {trough}) — it reads as empty"
    )
    # The guard has teeth: the same measurement with the trough colour standing
    # in for the chunk must FAIL, or the threshold above is passing on anything.
    assert _contrast(trough, trough) < 3.0


@pytest.mark.parametrize("palette", sorted(theme_palettes.PALETTES))
def test_every_runtime_chunk_colour_the_app_actually_passes_is_legible(palette):
    """The colours real call sites hand it, not a token sweep.

    Preferences paints attribute weight green above the line and red below;
    Discover paints resume-orange; the provider editor paints the subscription
    hue. Each of those is chosen for its MEANING, and nothing checked whether
    it could be seen on the trough it lands on.
    """
    _theme.apply_theme(palette)
    for name in ("COLOR_OK", "COLOR_ERR", "COLOR_ACCENT_ORANGE",
                 "COLOR_ACCENT_BLUE"):
        sheet = _theme.progress_bar(getattr(_theme, name))
        ratio = _contrast(_chunk(sheet), _trough(sheet))
        assert ratio >= 3.0, f"{palette}: {name} chunk is {ratio:.2f}:1 on the trough"


@pytest.mark.parametrize("palette", sorted(theme_palettes.PALETTES))
def test_the_muted_bar_is_quiet_on_purpose_but_not_gone(palette):
    """``COLOR_FAINT`` is the ONE chunk colour held below the 3:1 floor above.

    A muted attribute is one the user excluded from recommendations, and the
    whole row dims with it — label, value and bar together. Holding that bar to
    the same contrast as an active one would defeat what it is saying. It still
    has to be *there*, though: a chunk at its trough's own colour is a bar that
    reads as empty, which is a different statement from "quiet".
    """
    _theme.apply_theme(palette)
    muted = _theme.progress_bar(_theme.COLOR_FAINT)
    active = _theme.progress_bar(_theme.COLOR_OK)

    muted_ratio = _contrast(_chunk(muted), _trough(muted))
    assert muted_ratio >= 1.5, (
        f"{palette}: the muted bar is {muted_ratio:.2f}:1 — indistinguishable "
        f"from an empty one"
    )
    assert muted_ratio < _contrast(_chunk(active), _trough(active)), (
        f"{palette}: the muted bar is no quieter than an active one"
    )


def test_the_two_heights_are_tokens_and_the_thin_one_is_thinner():
    """Five heights shipped because the height lived at the call site."""
    assert _px(_theme.PROGRESS_H_THIN) < _px(_theme.PROGRESS_H)
    assert _px(_theme.PROGRESS_H_THIN) >= 3, (
        "a hairline under 3px disappears on a non-HiDPI display"
    )

    fat = _theme.progress_bar()
    thin = _theme.progress_bar(thin=True)
    assert f"max-height: {_theme.PROGRESS_H}" in fat
    assert f"max-height: {_theme.PROGRESS_H_THIN}" in thin
    assert "border: none" in thin, (
        "the overlay form sits ON a poster — a 1px border round it is a frame"
    )


def test_no_override_returns_the_role_itself():
    """``theme.style(bar, \"PROGRESS_BAR\")`` and ``progress_bar()`` must agree,
    or the four bars that take the default look different from the three that
    do not."""
    assert _theme.progress_bar().startswith(_theme.PROGRESS_BAR)
    assert _chunk(_theme.progress_bar()) == _chunk(_theme.PROGRESS_BAR)


def test_recolouring_the_chunk_leaves_the_trough_alone():
    """Both rules set a ``background:``; a bare colour swap hits the first."""
    sheet = _theme.progress_bar(_theme.COLOR_ERR)
    assert _chunk(sheet) == _theme.COLOR_ERR
    assert _trough(sheet) == _trough(_theme.PROGRESS_BAR)


def test_the_builder_follows_a_palette_switch():
    """It is rebuilt with the roles, not frozen at import — a bar styled through
    ``style_fn`` re-reads ``theme.progress_bar`` on every switch."""
    _theme.apply_theme("Midnight")
    midnight = _trough(_theme.progress_bar())
    _theme.apply_theme("Daylight")
    daylight = _trough(_theme.progress_bar())
    assert midnight != daylight, "the builder is still bound to the old palette"


# ── the drift guard ─────────────────────────────────────────────────────────

def test_no_widget_composes_its_own_chunk_rule():
    """Five did. A sixth would look like the others until the palette moved."""
    import pathlib

    offenders = [
        str(path)
        for path in sorted(pathlib.Path("metatv").rglob("*.py"))
        if path.name != "progress_roles.py"
        and "QProgressBar::chunk" in path.read_text()
    ]
    assert offenders == [], (
        f"these build a progress-bar sheet by hand instead of going through "
        f"theme.progress_bar()/PROGRESS_BAR: {offenders}"
    )


def test_no_widget_sets_its_own_bar_height():
    """The height is the sheet's, so it cannot disagree with the sheet."""
    import pathlib
    import re as _re

    offenders = []
    for path in sorted(pathlib.Path("metatv").rglob("*.py")):
        text = path.read_text()
        if "QProgressBar" not in text:
            continue
        for match in _re.finditer(r"(\w+)\.setFixedHeight\(", text):
            name = match.group(1)
            if "progress" in name.lower() or name in {"_bar", "bar"}:
                offenders.append(f"{path}:{name}.setFixedHeight")
    assert offenders == [], (
        f"a progress bar's height belongs to theme.progress_bar(): {offenders}"
    )
