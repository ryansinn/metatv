"""The typefaces the build loads are in the repository, and they work.

These assets were once produced in a session scratchpad, reported as prepared,
and lost when the temp directory was swept — leaving a settled decision (Inter
as the UI face) with nothing behind it. Anything the build loads belongs in the
tree; these tests are what stop it drifting back out.

Every assertion is on the real file and the real Qt font database, not on a
path existing.
"""

from __future__ import annotations

import json

import pytest
from PyQt6.QtGui import QFont, QFontDatabase, QFontMetrics

from metatv.gui import fonts


# ---------------------------------------------------------------------------
# 1. The files are here.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "Inter-Regular.ttf", "Inter-SemiBold.ttf", "MetaTVIcons.ttf",
    "material_symbols_codepoints.json",
    "LICENSE-Inter-OFL.txt", "LICENSE-MaterialSymbols-Apache-2.0.txt",
])
def test_the_asset_is_committed(filename):
    """Including the licences — both fonts are redistributable only with them."""
    path = fonts.ASSET_DIR / filename
    assert path.is_file(), f"{filename} is missing from {fonts.ASSET_DIR}"
    assert path.stat().st_size > 0


def test_the_icon_subset_stayed_small():
    """7 KB by codepoint. Subsetting by LIGATURE instead pulls the layout
    closure — 3,621 glyphs and 765 KB — which is the mistake that made this
    worth measuring."""
    size = (fonts.ASSET_DIR / "MetaTVIcons.ttf").stat().st_size
    assert size < 64 * 1024, (
        f"the icon subset is {size // 1024} KB — it was 7 KB; something is "
        f"subsetting by ligature or keeping layout tables"
    )


# ---------------------------------------------------------------------------
# 2. Qt actually loads them.
# ---------------------------------------------------------------------------

def test_every_bundled_face_registers_with_qt(qapp):
    loaded = fonts.load_bundled_fonts()
    assert loaded.get("ui") == fonts.UI_FAMILY
    assert loaded.get("ui-semibold")
    assert loaded.get("icons")


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
# 3. Every icon the map names is really in the font.
# ---------------------------------------------------------------------------

def test_the_codepoint_map_and_the_font_agree(qapp):
    """Both are emitted by one run of the build script, so a disagreement means
    one of them was edited by hand."""
    fonts.load_bundled_fonts()
    codepoints = fonts.icon_codepoints()
    assert codepoints, "the codepoint map is empty"

    metrics = QFontMetrics(QFont(fonts.load_bundled_fonts()["icons"]))
    missing = [name for name, cp in codepoints.items()
               if not metrics.inFont(chr(int(cp, 16)))]
    assert not missing, f"named in the map but absent from the font: {missing}"


def test_icon_char_is_a_single_character(qapp):
    assert len(fonts.icon_char("movie")) == 1


def test_an_unknown_icon_raises_rather_than_rendering_a_blank(qapp):
    """Same contract as ``icons.vector_key`` — a typo surfaces at the call site
    instead of painting an empty box."""
    with pytest.raises(KeyError):
        fonts.icon_char("no_such_icon")


def test_the_three_kind_marks_are_present(qapp):
    """The spec chose these by rendering candidates at row size: ``live_tv``
    and ``smart_display`` both carry a play triangle and read as a play button;
    ``satellite_alt`` collapses into scribble at 15px."""
    for name in ("movie", "tv", "sensors"):
        assert name in fonts.icon_codepoints()


# ---------------------------------------------------------------------------
# 4. The packaged build ships them.
# ---------------------------------------------------------------------------

def test_the_spec_bundles_the_asset_directory():
    """``fonts.py`` resolves the directory relative to the package, so a frozen
    build that omits it falls back to the platform face with no error."""
    spec = (fonts.ASSET_DIR.parent.parent.parent
            / "packaging" / "metatv.spec").read_text()
    assert '"assets", "fonts"' in spec, (
        "packaging/metatv.spec does not ship metatv/assets/fonts"
    )


def test_the_generator_is_committed_beside_what_it_generates():
    """Anything in the tree that was generated needs its generator in the tree."""
    script = (fonts.ASSET_DIR.parent.parent.parent
              / "scripts" / "build_font_assets.py")
    assert script.is_file()


def test_the_codepoint_map_is_valid_json_and_hex():
    raw = json.loads((fonts.ASSET_DIR / "material_symbols_codepoints.json").read_text())
    assert len(raw) >= 40
    for name, value in raw.items():
        assert int(value, 16) > 0, f"{name} has a bad codepoint {value!r}"
