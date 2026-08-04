"""A filtered-variant chip was a dead button (#294).

Owner: "why can't I click on a filtered variant chip in the details panel? I
should be able to click on them, they're just hidden to reduce clutter or
distraction, but they still should be clickable when Filtered Variants is
expanded."

``_make_greyed_chip`` wired a right-click context menu and nothing else — no
``clicked`` connection at all, while ``_make_active_chip`` has connected
``version_selected`` since it was written. So left-clicking a filtered variant
did nothing, silently.

The styling had been making the same promise the wiring broke: ``COLOR_BORDER``
text is ~1.4:1 against the pane and there was no hover rule, which is precisely
how a control signals "disabled, don't bother". These are DE-EMPHASIZED, not
disabled — you had to expand the section on purpose to reach them.

Asserts the rendered appearance too (CLAUDE.md: UI slices assert appearance):
the chip's own foreground must clear the 3:1 chrome floor against the pane it
sits on, so "looks clickable" is measured rather than asserted by eye.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _version(cid, *, filtered, hidden_cat=False):
    from metatv.gui.details_versions import ChannelVersion
    return ChannelVersion(
        channel_id=cid, name=f"Variant {cid}", in_queue=False,
        detected_prefix="FR" if filtered else "US",
        is_filtered=filtered, is_hidden_category=hidden_cat,
    )


@pytest.fixture()
def section(qapp):
    from metatv.core.config import Config
    from metatv.gui.details_versions import _VersionSection

    sec = _VersionSection(Config())
    sec.load([
        _version("active-1", filtered=False),
        _version("filt-1", filtered=True),
        _version("filt-2", filtered=True, hidden_cat=True),
    ])
    QApplication.processEvents()
    yield sec
    sec.deleteLater()


def _filtered_chips(section):
    layout = section._filtered_chips_layout
    return [
        layout.itemAt(i).widget() for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]


def test_the_chips_exist_at_all(section):
    assert len(_filtered_chips(section)) == 2


def test_clicking_one_switches_to_that_version(section):
    """The defect, exactly as reported."""
    seen: list[str] = []
    section.version_selected.connect(seen.append)

    _filtered_chips(section)[0].click()
    QApplication.processEvents()

    assert seen, "left-clicking a filtered variant chip did nothing"
    assert seen == ["filt-1"]


def test_a_hidden_category_variant_is_clickable_too(section):
    """Struck-through (hidden-category) chips are still reachable.

    They are the ones a user most often wants to jump to — that is why the
    section can be expanded at all.
    """
    seen: list[str] = []
    section.version_selected.connect(seen.append)

    _filtered_chips(section)[1].click()
    QApplication.processEvents()

    assert seen == ["filt-2"]


def test_it_uses_the_same_signal_as_an_active_chip(section):
    """One switch path, not a parallel one (single-chokepoint rule)."""
    seen: list[str] = []
    section.version_selected.connect(seen.append)

    section._chips_layout.itemAt(0).widget().click()   # an ACTIVE chip
    _filtered_chips(section)[0].click()                # a FILTERED chip
    QApplication.processEvents()

    assert seen == ["active-1", "filt-1"], (
        "both chip kinds must switch through version_selected"
    )


def test_the_chip_says_it_is_clickable(section):
    """Tooltip rule: the affordance has to be discoverable."""
    tip = _filtered_chips(section)[0].toolTip().lower()
    assert "click" in tip and "right-click" in tip


def test_it_no_longer_renders_as_a_disabled_control(section):
    """Rendered appearance: measured contrast, not "looks better".

    ``COLOR_BORDER`` (#444) on the pane is ~1.4:1 — below any legibility floor
    and the visual language of a disabled widget. A chip the user is expected
    to click must clear the 3:1 chrome floor.
    """
    from metatv.gui import theme as _theme

    sheet = _filtered_chips(section)[0].styleSheet()
    assert f"color: {_theme.COLOR_BORDER}" not in sheet, (
        "chip still paints its label in the border colour — reads as disabled"
    )
    assert _contrast(_fg(sheet), _theme.COLOR_BG_SECTION) >= 3.0, (
        f"filtered chip label is {_contrast(_fg(sheet), _theme.COLOR_BG_SECTION):.2f}:1 "
        f"against the pane — below the 3:1 floor for an interactive control"
    )
    assert ":hover" in sheet, (
        "no hover state — a control that does not respond to the pointer reads "
        "as dead even when it is wired"
    )


def test_a_hidden_category_chip_keeps_its_strikethrough(section):
    """Making them clickable must not erase WHY they are set apart."""
    assert "line-through" in _filtered_chips(section)[1].styleSheet()
    assert "line-through" not in _filtered_chips(section)[0].styleSheet()


# --- contrast helpers -------------------------------------------------------

def _fg(sheet: str) -> str:
    """First `color: X;` in the base (non-hover) rule."""
    base = sheet.split(":hover")[0]
    return base.split("color:")[1].split(";")[0].strip()


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexstr: str) -> float:
    h = hexstr.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
