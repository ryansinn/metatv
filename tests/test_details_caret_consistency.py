"""Behavioral tests: details-pane collapse carets share one visual style.

Every collapsible section in the details pane builds its caret/toggle the same
way as the reference sections (Tags / Technical Details / Cast & Crew): a
non-flat ``QPushButton`` pinned to 20×20 via ``setFixedSize``. Two sections had
drifted — Similar Titles was flat, Filtered Variants was flat *and* 16×16.

These instantiate the real section widgets (headless Qt) and assert the caret's
flatness and fixed size, so the test fails on the pre-fix code (flat=True /
size 16) and passes after.
"""
from __future__ import annotations

import pytest

from metatv.gui import icons as _icons


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _Cfg:
    """Minimal Config stand-in providing the icon attrs the sections read."""

    collapse_icon = _icons.collapse_icon
    expand_icon = _icons.expand_icon


def _assert_reference_caret(btn) -> None:
    """A caret matches the reference style: non-flat, fixed 20×20."""
    assert btn.isFlat() is False
    assert btn.minimumWidth() == btn.maximumWidth() == 20
    assert btn.minimumHeight() == btn.maximumHeight() == 20


def test_tags_section_caret_is_reference(qapp):
    from metatv.gui.details_sections import _TagsSection
    section = _TagsSection(_Cfg())
    _assert_reference_caret(section._toggle_btn)


def test_technical_section_caret_is_reference(qapp):
    from metatv.gui.details_sections import _TechnicalSection
    section = _TechnicalSection(_Cfg())
    _assert_reference_caret(section._toggle_btn)


def test_cast_section_caret_is_reference(qapp):
    from metatv.gui.details_sections import _CastSection
    section = _CastSection(_Cfg())
    _assert_reference_caret(section._toggle_btn)


def test_similar_section_caret_matches_reference(qapp):
    """Similar Titles caret must be non-flat 20×20 (was setFlat(True))."""
    from metatv.gui.details_similar import _SimilarSection
    section = _SimilarSection(_Cfg())
    _assert_reference_caret(section._toggle_btn)


def test_filtered_variants_caret_matches_reference(qapp):
    """Filtered Variants caret must be non-flat 20×20 (was flat 16×16)."""
    from metatv.gui.details_versions import _VersionSection
    section = _VersionSection(_Cfg())
    _assert_reference_caret(section._filtered_toggle_btn)
