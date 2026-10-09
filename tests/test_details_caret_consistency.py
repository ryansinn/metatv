"""Every collapsible details section uses the SAME header, not a copy of it.

The original of this file asserted that each section's caret was a non-flat
20×20 QPushButton, because two sections had drifted — Similar Titles was flat,
Filtered Variants was flat *and* 16×16. That test was right about the symptom
and could only ever chase it: four sections each built their own caret, so
"they all match" had to be re-checked per section, and a fifth section would
have drifted before anyone noticed.

They now share one ``CollapsibleHeader``. So the assertion changes from *do
these four look alike* to *is there one of them* — which is the property that
makes drift impossible rather than merely currently-absent.

The size and flatness checks survive on the shared component, because those are
still the thing a future edit could break for everybody at once.
"""
from __future__ import annotations

import pytest

from metatv.gui import icons as _icons
from metatv.gui.details_section_header import CollapsibleHeader


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _Cfg:
    """Minimal Config stand-in providing the icon attrs the sections read."""

    collapse_icon = _icons.collapse_icon
    expand_icon = _icons.expand_icon
    details_pane_collapsed_sections: list[str] = []


def _sections(cfg):
    """Every section that owns a shared ``CollapsibleHeader``.

    "Also available" (``_VersionSection``) is deliberately NOT one of these
    since DETAILS-3c: "Available in" is never collapsible — the copy you are
    on plus every sibling, always visible — so it never had the shared header
    to drift away from in the first place.
    """
    from metatv.gui.details_sections import (
        _CastSection, _PlotSection, _TagsSection, _TechnicalSection,
    )
    from metatv.gui.details_similar import _SimilarSection

    return {
        "Overview": _PlotSection(),
        "Cast": _CastSection(cfg),
        "Technical": _TechnicalSection(cfg),
        "Tags": _TagsSection(cfg),
        "Similar": _SimilarSection(cfg),
    }


def test_every_collapsible_section_uses_the_shared_header(qapp):
    """The property that retires the drift, rather than re-checking for it."""
    for name, section in _sections(_Cfg()).items():
        assert isinstance(section._header, CollapsibleHeader), (
            f"{name} builds its own header instead of using the shared one — "
            f"that is how Similar Titles and Filtered Variants drifted before"
        )


def test_every_section_declares_a_persistence_key(qapp):
    """A section that collapses but has no key forgets on every restart."""
    keys = {}
    for name, section in _sections(_Cfg()).items():
        key = section.COLLAPSE_KEY
        assert key, f"{name} has no COLLAPSE_KEY — its state cannot persist"
        assert key not in keys, (
            f"{name} and {keys[key]} both claim the key {key!r}; collapsing one "
            f"would collapse the other on restart"
        )
        keys[key] = name


def test_the_shared_caret_is_the_reference_shape(qapp):
    """20×20 and flat — checked once, where all six now get it from."""
    header = CollapsibleHeader("Anything")
    caret = header._chevron
    assert caret.minimumWidth() == caret.maximumWidth() == 20
    assert caret.minimumHeight() == caret.maximumHeight() == 20


def test_the_title_toggles_too_not_just_the_caret(qapp):
    """A 20px target for a full-width header is a needlessly small target.

    Q21 settled that a section header toggles and never navigates, which is
    what makes it safe to widen the target to the words.
    """
    header = CollapsibleHeader("Cast")
    assert header.is_collapsed() is False
    header._title.click()
    assert header.is_collapsed() is True, "clicking the title did not toggle"


def _icon_bytes(btn) -> bytes:
    """Raw pixel bytes of *btn*'s current icon, for "did it actually repaint"."""
    image = btn.icon().pixmap(btn.iconSize()).toImage()
    return image.bits().asstring(image.sizeInBytes())


def test_the_caret_glyph_and_tooltip_always_agree(qapp):
    """A fixed tooltip contradicts the arrow half the time.

    ICON-1: the caret is a QIcon (icon_utils.set_button_icon), never text, so
    "the glyph flipped" is asserted by the rendered pixmap changing, not by a
    text value that is now always "".
    """
    header = CollapsibleHeader("Cast")
    assert header._chevron.text() == ""
    collapsed_bytes = _icon_bytes(header._chevron)
    assert "Collapse" in header._chevron.toolTip()

    header.toggle()
    expanded_bytes = _icon_bytes(header._chevron)
    assert expanded_bytes != collapsed_bytes, "the caret must repaint on toggle"
    assert "Expand" in header._chevron.toolTip()


def _expected_chevron_bytes(icon_key: str, size) -> bytes:
    from metatv.gui import icon_utils as _icon_utils
    from metatv.gui import theme as _theme
    icon = _icon_utils.resolve_icon(icon_key, color=_theme.COLOR_TEXT)
    image = icon.pixmap(size).toImage()
    return image.bits().asstring(image.sizeInBytes())


def test_every_section_header_points_the_right_direction(qapp, owned_widgets):
    """CHV-2: all six shared headers start OPEN (down chevron) and must flip
    to a RIGHT chevron once collapsed — never the reverse.

    ``test_the_caret_glyph_and_tooltip_always_agree`` above only proves the
    caret repaints to *something* on toggle — that passed against the
    inverted ``icons.VECTOR_KEYS`` map too. This checks the actual resolved
    glyph, per real section instance, so a section that somehow grew its own
    "expand"/"collapse" string off to the side would still be caught here.
    """
    for name, section in _sections(_Cfg()).items():
        owned_widgets.own(section)
        chevron = section._header._chevron
        size = chevron.iconSize()
        assert not section._header.is_collapsed(), (
            f"{name}: test assumes the default open state"
        )
        assert _icon_bytes(chevron) == _expected_chevron_bytes("mdi6.chevron-down", size), (
            f"{name}: an OPEN section's chevron must point down"
        )
        section._header.toggle()
        assert _icon_bytes(chevron) == _expected_chevron_bytes("mdi6.chevron-right", size), (
            f"{name}: a CLOSED section's chevron must point right"
        )


#
# test_filtered_variants_is_the_shared_header_one_step_down used to live
# here: "Filtered variants"/"Offline sources" were nested CollapsibleHeaders
# at a one-step-down DETAIL_SUBSECTION_TITLE scale. DETAILS-3c removed both
# nested sub-sections (and the "Also available" CollapsibleHeader itself —
# see _sections() above) in favour of an always-visible "Available in" grid
# row plus a dashed "+N …" disclosure chip; there is no nested header left to
# test, and DETAIL_SUBSECTION_TITLE was removed from tokens/detail_roles.py
# as the role only that mechanism used (test_theme_role_duplication.py's
# _SHAPE_CLUSTER_BUDGET moved 44 -> 43 accordingly).
