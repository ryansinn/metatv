"""The app ships an icon, and the app actually sets it.

There was none until 2026-08-27. ``packaging/metatv.spec:153`` read
``icon=None,  # placeholder omitted for the MVP; add packaging/metatv.icns
later``, nothing called ``setWindowIcon``, and a ``feat/app-icon`` branch
existed with zero commits — so every surface fell back to the window manager's
generic square. Owner: "what ever happened to the app icon? Shouldn't that be
displaying?"

These assert the two halves that were missing: the files exist, and the startup
path reads them. A rendered icon nobody sets is the state we just left.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ICON_DIR = REPO_ROOT / "packaging" / "icon"

# 16 is the size that decides an icon — dock, taskbar, alt-tab. 1024 is what
# the macOS iconset needs for its 512@2x slot.
REQUIRED = (16, 32, 64, 128, 256, 512, 1024)


@pytest.mark.parametrize("size", REQUIRED)
def test_every_required_size_is_present(size):
    """A missing size silently degrades to a scaled neighbour, or to nothing."""
    png = ICON_DIR / f"metatv-{size}.png"
    assert png.exists(), f"{png.name} is missing"
    assert png.stat().st_size > 100, f"{png.name} is suspiciously small"


def test_the_source_svg_is_committed():
    """PNGs regenerated from nothing are unmaintainable."""
    assert (ICON_DIR / "metatv.svg").exists()


def test_the_pngs_are_the_size_they_claim():
    """A 16px file that is really 512 scaled down defeats the point of the set."""
    from PyQt6.QtGui import QImage

    for size in REQUIRED:
        img = QImage(str(ICON_DIR / f"metatv-{size}.png"))
        assert (img.width(), img.height()) == (size, size), (
            f"metatv-{size}.png is {img.width()}x{img.height()}"
        )


def test_startup_sets_the_window_icon():
    """Rendering an icon nobody sets is exactly the state this replaced."""
    src = (REPO_ROOT / "metatv" / "__main__.py").read_text()

    assert "setWindowIcon" in src, (
        "__main__ never calls setWindowIcon, so the window and the task "
        "switcher keep the system default however many PNGs are committed"
    )
    assert "bundle_resource_path" in src, (
        "the icon path must resolve through bundle_resource_path, or it will "
        "be found in a checkout and missing inside the packaged app"
    )


def test_the_spec_no_longer_hardcodes_no_icon():
    """`icon=None` was the original defect, in one line."""
    spec = (REPO_ROOT / "packaging" / "metatv.spec").read_text()

    assert not re.search(r"^\s*icon=None,\s*$", spec, re.M), (
        "packaging/metatv.spec still passes icon=None"
    )
    assert "metatv-256.png" in spec, (
        "the PNG is not in `datas`, so bundle_resource_path will not find it "
        "inside the frozen app — the icon would work in a checkout only"
    )
