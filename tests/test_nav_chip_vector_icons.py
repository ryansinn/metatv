"""The primary view chips carry an icon that actually tracks the palette.

Emoji baked into a button label cannot take a colour: those five icons ignored
the theme entirely and rendered differently on every platform. These assert
rendered PIXELS — an icon that is present but never repaints would pass a
key-presence check and still be the original bug.
"""
from __future__ import annotations

import os
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("qtawesome")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def _app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pixels(chip):
    img = chip.icon().pixmap(14, 14).toImage()
    return bytes(img.constBits().asstring(img.sizeInBytes()))


def test_chip_with_a_role_gets_an_icon(_app) -> None:
    from metatv.gui.filter_bar import ToggleChip
    assert not ToggleChip("Search", True, vector_role="search").icon().isNull()


def test_chip_without_a_role_is_unchanged(_app) -> None:
    from metatv.gui.filter_bar import ToggleChip
    assert ToggleChip("Plain", True).icon().isNull(), "role-less chip grew an icon"


def test_the_label_no_longer_carries_an_emoji(_app) -> None:
    from metatv.gui.filter_bar import ToggleChip
    chip = ToggleChip("Search", True, vector_role="search")
    stray = [c for c in chip.text() if ord(c) > 0x2600]
    assert not stray, f"emoji left in the chip label: {stray}"


def test_the_icon_repaints_on_a_palette_switch(_app) -> None:
    """The regression this slice exists to prevent.

    A first attempt re-tinted from ``update_appearance``, beside the builder
    rather than inside it. ``theme._reapply_registered_styles()`` re-invokes the
    builder and nothing else, so the icon kept its old colour forever. This is
    the assertion that caught it.
    """
    from metatv.gui import theme as _theme
    from metatv.gui.filter_bar import ToggleChip

    _theme.apply_theme("Midnight")
    chip = ToggleChip("Search", True, vector_role="search")
    midnight = _pixels(chip)

    _theme.apply_theme("Daylight")
    _theme._reapply_registered_styles()
    daylight = _pixels(chip)
    _theme.apply_theme("Midnight")

    assert midnight != daylight, "icon did not repaint — it is not tracking the theme"


def test_active_and_inactive_use_different_foregrounds(_app) -> None:
    from metatv.gui import theme as _theme
    from metatv.gui.filter_bar import ToggleChip

    _theme.apply_theme("Midnight")
    on = ToggleChip("Search", True, vector_role="search")
    off = ToggleChip("Search", False, vector_role="search")
    assert _pixels(on) != _pixels(off), (
        "an active chip sits on a solid accent fill and must take COLOR_ON_ACCENT, "
        "not the on-background text ramp"
    )
