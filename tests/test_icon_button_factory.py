"""The icon-button factory renders something, and re-renders on a theme switch.

Icon-only buttons had been built ~37 different ways across ``metatv/gui/``. The
most common shape — ``QPushButton(icons.x_icon)`` — puts a colour EMOJI in the
button as its TEXT, drawn at the host font size inside a fixed-size button, so
it crops (the owner, of the Watch Queue's find toggle: *"it should be using the
material icon and not be cropped to shit like this"*). ``icon_utils.icon_button``
is the one path that replaces all of them.

These assertions are about what is PAINTED, not about which tokens exist:

- a real (non-null) icon, at the requested :class:`QSize`, whose rendered
  pixmap actually has ink in it — a null icon and a fully transparent one both
  pass ``setIcon()`` silently and leave the user an empty box;
- a minimum size hint that can actually hold the icon — the "cropped" defect;
- **different pixel bytes after a theme switch**, which is the only evidence
  that :func:`icon_utils.refresh_icon_buttons` is really wired into
  ``theme.apply_theme``'s post-apply hooks. A QIcon bakes its colour at build
  time, so unlike a stylesheet role it cannot re-resolve a token on its own;
  if the hook were dropped, every icon button would keep the previous palette's
  colour and nothing else in the suite would notice.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QSize  # noqa: E402

from metatv.gui import icon_utils as _icon_utils  # noqa: E402
from metatv.gui import theme as _theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _ink_pixels(btn) -> int:
    """How many non-transparent pixels the button's icon actually paints."""
    image = btn.icon().pixmap(btn.iconSize()).toImage()
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    )


def _icon_bytes(btn) -> bytes:
    """The raw ARGB bytes of the button's rendered icon."""
    image = btn.icon().pixmap(btn.iconSize()).toImage()
    return image.convertToFormat(image.Format.Format_ARGB32).bits().asstring(
        image.sizeInBytes()
    )


def test_icon_button_renders_a_real_icon_at_the_requested_size(qapp) -> None:
    """The factory produces a visible, correctly sized, non-empty icon."""
    btn = _icon_utils.icon_button("close", "Close", px=16)

    assert not btn.icon().isNull(), "the factory built a button with no icon at all"
    assert btn.iconSize() == QSize(16, 16)
    assert _ink_pixels(btn) > 0, (
        "the icon rendered fully transparent — a button that paints nothing "
        "looks identical to one with no icon"
    )
    # The cropping defect: a button whose minimum size cannot hold its own icon.
    assert btn.minimumSizeHint().width() >= 16
    assert btn.minimumSizeHint().height() >= 16
    # Icon-only: the glyph is in the icon, never in the label.
    assert btn.text() == ""
    assert btn.toolTip() == "Close"
    assert btn.accessibleName() == "Close"


def test_a_theme_switch_repaints_registered_icon_buttons(qapp) -> None:
    """The post-apply hook actually re-renders the icon in the new palette.

    Proven on pixel bytes rather than on "a hook is registered": the hook list
    could contain the function and still not be called, and the function could
    be called and still paint the same colour (that is exactly what happens if
    the default colour is captured at import instead of read per call).
    """
    before_theme = _theme.current_theme()
    try:
        _theme.apply_theme("Graphite")
        btn = _icon_utils.icon_button("close", "Close", px=16)
        graphite_bytes = _icon_bytes(btn)
        graphite_ink = _ink_pixels(btn)

        assert _theme.apply_theme("Daylight"), "Daylight is not a known palette"
        daylight_bytes = _icon_bytes(btn)

        assert daylight_bytes != graphite_bytes, (
            "the icon looks identical after switching to a light palette — "
            "icon_utils.refresh_icon_buttons() is not reaching this button"
        )
        # Still an icon, not a blank square: a "difference" that erased the
        # glyph would satisfy the inequality above while looking broken.
        assert _ink_pixels(btn) > 0
        assert abs(_ink_pixels(btn) - graphite_ink) <= max(4, graphite_ink // 4), (
            "the repaint changed the glyph's SHAPE, not just its colour"
        )
    finally:
        _theme.apply_theme(before_theme)


def test_a_swapped_role_survives_a_theme_switch(qapp) -> None:
    """A toggle badge re-registers, so a repaint reproduces what is on screen.

    ``set_button_icon`` is how a toggle flips its glyph (watched/unwatched,
    pin/unpin). If the registry kept the CONSTRUCTION role, a theme switch
    would silently revert a toggled button to its original glyph.
    """
    before_theme = _theme.current_theme()
    try:
        _theme.apply_theme("Graphite")
        btn = _icon_utils.icon_button("favorite", "Remove from favorites", px=16)
        _icon_utils.set_button_icon(btn, "unfavorite")
        swapped_ink = _ink_pixels(btn)

        _theme.apply_theme("Daylight")
        after_ink = _ink_pixels(btn)
        assert abs(after_ink - swapped_ink) <= max(4, swapped_ink // 4), (
            "the theme switch reverted the toggle to its construction glyph"
        )
    finally:
        _theme.apply_theme(before_theme)


def test_an_unknown_role_names_both_lookups(qapp) -> None:
    """A typo surfaces at the call site, not as a silently iconless button."""
    from PyQt6.QtWidgets import QPushButton

    # Not ``pytest.raises``: its ExceptionInfo keeps the raising frame — and so
    # the button — alive past teardown, which trips the top-level-widget leak
    # guard. The message is copied out and the exception dropped instead.
    message = ""
    btn = QPushButton()
    try:
        _icon_utils.set_button_icon(btn, "definitely_not_a_role")
    except KeyError as exc:
        message = str(exc)
    assert "VECTOR_KEYS" in message
    assert "definitely_not_a_role_icon" in message


def test_an_empty_tooltip_is_refused(qapp) -> None:
    """The tooltip rule is firm: an icon-only control must say what it does."""
    with pytest.raises(ValueError):
        _icon_utils.icon_button("close", "")


def test_the_registry_does_not_keep_dead_buttons_alive(qapp) -> None:
    """A closed dialog's buttons must not be retained by the repaint registry."""
    import gc

    btn = _icon_utils.icon_button("close", "Close")
    assert btn in _icon_utils._registered_icon_buttons
    del btn
    gc.collect()
    # Nothing to assert about the count (other tests populate it); the point is
    # that a WeakKeyDictionary is what is used, so the entry can go.
    assert isinstance(
        _icon_utils._registered_icon_buttons.data, dict
    ), "the icon-button registry is no longer weak — closed dialogs will leak"
