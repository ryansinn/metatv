"""The typefaces the build loads are in the repository, and they work.

These assets were once produced in a session scratchpad, reported as prepared,
and lost when the temp directory was swept — leaving a settled decision (Inter
as the UI face) with nothing behind it. Anything the build loads belongs in the
tree; these tests are what stop it drifting back out.

Every assertion is on the real file and the real Qt font database, not on a
path existing.
"""

from __future__ import annotations


import pytest
from PyQt6.QtGui import QFontDatabase

from metatv.gui import fonts


# ---------------------------------------------------------------------------
# 1. The files are here.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "Inter-Regular.ttf", "Inter-SemiBold.ttf", "LICENSE-Inter-OFL.txt",
])
def test_the_asset_is_committed(filename):
    """Including the licence — Inter is redistributable only with it."""
    path = fonts.ASSET_DIR / filename
    assert path.is_file(), f"{filename} is missing from {fonts.ASSET_DIR}"
    assert path.stat().st_size > 0


# ---------------------------------------------------------------------------
# 2. Qt actually loads them.
# ---------------------------------------------------------------------------

def test_every_bundled_face_registers_with_qt(qapp):
    loaded = fonts.load_bundled_fonts()
    assert loaded.get("ui") == fonts.UI_FAMILY
    assert loaded.get("ui-semibold")
    assert "icons" not in loaded, "the Material Symbols subset was removed (one icon set: mdi6)"


def test_loading_twice_does_not_duplicate_a_family(qapp):
    """``addApplicationFont`` returns a NEW id for the same file each call, so
    an uncached loader leaves duplicate families in the database."""
    fonts.load_bundled_fonts.cache_clear()
    first = fonts.load_bundled_fonts()
    before = len(QFontDatabase.families())
    second = fonts.load_bundled_fonts()
    assert first == second
    assert len(QFontDatabase.families()) == before


def test_apply_ui_font_sets_the_application_face(qapp):
    original = qapp.font()
    try:
        assert fonts.apply_ui_font(qapp) is True
        assert qapp.font().family() == fonts.UI_FAMILY
    finally:
        qapp.setFont(original)


def test_apply_ui_font_keeps_the_platform_size(qapp):
    """The type scale sets pixel sizes per role; overriding the base size here
    would silently rescale anything not yet given a token."""
    original = qapp.font()
    try:
        before = qapp.font().pointSizeF()
        fonts.apply_ui_font(qapp)
        assert qapp.font().pointSizeF() == before
    finally:
        qapp.setFont(original)


# ---------------------------------------------------------------------------
# 4. The packaged build ships them.
# ---------------------------------------------------------------------------

def test_the_build_bundles_the_asset_directory():
    """``fonts.py`` resolves the directory relative to the package, so a frozen
    build that omits it falls back to the platform face with no error."""
    build = (fonts.ASSET_DIR.parent.parent.parent
             / "packaging" / "build_nuitka.sh").read_text()
    assert "--include-data-dir=metatv/assets/fonts=metatv/assets/fonts" in build, (
        "packaging/build_nuitka.sh does not ship metatv/assets/fonts"
    )


def test_the_generator_is_committed_beside_what_it_generates():
    """Anything in the tree that was generated needs its generator in the tree."""
    script = (fonts.ASSET_DIR.parent.parent.parent
              / "scripts" / "build_font_assets.py")
    assert script.is_file()
