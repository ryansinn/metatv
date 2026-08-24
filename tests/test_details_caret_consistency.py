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
    from metatv.gui.details_sections import (
        _CastSection, _PlotSection, _TagsSection, _TechnicalSection,
    )
    from metatv.gui.details_similar import _SimilarSection
    from metatv.gui.details_versions import _VersionSection

    return {
        "Overview": _PlotSection(),
        "Also available": _VersionSection(cfg),
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


def test_the_caret_glyph_and_tooltip_always_agree(qapp):
    """A fixed tooltip contradicts the arrow half the time."""
    header = CollapsibleHeader("Cast")
    assert header._chevron.text() == _icons.collapse_icon
    assert "Collapse" in header._chevron.toolTip()

    header.toggle()
    assert header._chevron.text() == _icons.expand_icon
    assert "Expand" in header._chevron.toolTip()


def test_filtered_variants_caret_matches_reference(qapp):
    """Not on the shared header — it is a sub-section inside Also-available.

    Left as its own control deliberately: it discloses filtered variants
    *within* a section, so promoting it to a section header would put two
    section headers in one section.
    """
    from metatv.gui.details_versions import _VersionSection
    section = _VersionSection(_Cfg())
    btn = section._filtered_toggle_btn
    assert btn.isFlat() is False
    assert btn.minimumWidth() == btn.maximumWidth() == 20
    assert btn.minimumHeight() == btn.maximumHeight() == 20
