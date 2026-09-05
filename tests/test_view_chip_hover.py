"""Hovering a view chip must read as "you can click this", not as a hole.

Owner, 2026-08-27, across several themes: "hovering over a menu basically makes
it blend into the background, removes the outline and background color matches
larger ui background color."

Measured, and it was literal. The unselected hover set the fill to
``COLOR_BG_BAR`` — the surrounding header background — so the chip dissolved
into it. And on every dark palette that fill is DARKER than the track it sits
on, so the chip receded on hover instead of lighting up:

    Midnight   #1c222b -> #151a21   DARKER
    Slate      #212225 -> #18191b   DARKER
    Graphite   #2a2a2a -> #222222   DARKER
    Gruvbox    #242424 -> #1d2021   DARKER
    Daylight   #e8e8ec -> #f0f0f3   brighter (the only one)

The text never changed at all, which is why it also read as disabled rather
than hoverable — and Gruvbox has no room to fade: COLOR_TEXT, COLOR_TEXT_2 and
COLOR_TEXT_LOW are all #bdae93, so an unselected chip cannot be "quieter but
present" there. Only COLOR_TEXT_HI is brighter.

The treatment is the owner's: an accent outline, an accent-tinted fill, and
text partway to the selected state — "not as bright as the currently selected
menu option, but maybe 50% of the way, meet in the middle".
"""

from __future__ import annotations

import pytest

from tests.conftest import destroy_widget
from metatv.gui import theme as _theme
from metatv.gui import theme_palettes as tp
from metatv.gui.filter_bar import ToggleChip

PALETTES = list(tp.PALETTES)


def _sheet(palette: str, *, selected: bool) -> str:
    """The stylesheet a segmented view chip actually renders under *palette*."""
    _theme.apply_theme(palette)
    chip = ToggleChip("Discover", segment="middle")
    chip.set_enabled(selected)
    sheet = chip.styleSheet()
    destroy_widget(chip)
    return sheet


@pytest.mark.parametrize("palette", PALETTES)
def test_hover_does_not_paint_the_chip_the_background_colour(qapp, palette):
    """The dissolve, stated exactly: hover must not use the header's own fill."""
    sheet = _sheet(palette, selected=False)
    hover = sheet.split("QPushButton:hover")[1]

    assert _theme.COLOR_BG_BAR not in hover, (
        f"{palette}: hover fills the chip with COLOR_BG_BAR "
        f"({_theme.COLOR_BG_BAR}), which is the surrounding background — the "
        "chip disappears into it"
    )


@pytest.mark.parametrize("palette", PALETTES)
def test_hover_draws_an_accent_outline(qapp, palette):
    """"it should get a slightly accented glowing outline around it"."""
    hover = _sheet(palette, selected=False).split("QPushButton:hover")[1]

    assert "border-color" in hover and _theme.COLOR_ACCENT in hover, (
        f"{palette}: hover draws no accent outline"
    )


@pytest.mark.parametrize("palette", PALETTES)
def test_hover_brightens_the_label_toward_the_selected_state(qapp, palette):
    """"maybe 50% of the way, meet in the middle" — brighter, not full accent."""
    resting = _sheet(palette, selected=False)
    hover = resting.split("QPushButton:hover")[1]

    assert _theme.COLOR_TEXT_HI in hover, (
        f"{palette}: hover leaves the label at its resting colour, so hover "
        "reads as disabled rather than interactive"
    )
    # "Not the whole way" is about the FILL, not the foreground token. In
    # Graphite COLOR_TEXT_HI and COLOR_ON_ACCENT are the same value (#eeeeee),
    # because that palette's accent is dark enough for one colour to serve
    # both — so comparing foreground hex would fail there for no real reason.
    # What actually distinguishes hover from selected is that hover does not
    # take the solid accent fill.
    assert f"background-color: {_theme.COLOR_ACCENT};" not in hover, (
        f"{palette}: hover takes the SELECTED accent fill — that is the whole "
        "way, not the middle"
    )


@pytest.mark.parametrize("palette", PALETTES)
def test_the_hover_ring_is_reserved_so_the_label_never_shifts(qapp, palette):
    """A border that appears only on hover moves the text 1px under the pointer.

    The resting state carries a transparent 1px border for exactly this reason;
    hover only recolours it.
    """
    resting = _sheet(palette, selected=False).split("QPushButton:hover")[0]

    assert "border: 1px solid transparent" in resting, (
        f"{palette}: the resting chip reserves no ring, so the hover outline "
        "will nudge the label as the pointer crosses it"
    )
