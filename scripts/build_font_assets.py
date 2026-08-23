#!/usr/bin/env python3
"""Regenerate metatv/assets/fonts/ from upstream. Run it, commit the output.

Why this is a script and not a note
-----------------------------------
These files were once produced by hand in a session scratchpad, reported as
prepared, and lost when the temp directory was swept — so a settled decision
(Inter as the UI face) had nothing behind it and the work had to be redone.
Anything the build loads belongs in the tree, and anything in the tree that was
generated needs the generator beside it.

    venv/bin/python scripts/build_font_assets.py

Needs network and ``fonttools``. Writes into ``metatv/assets/fonts/``.

What it produces
----------------
``Inter-Regular.ttf`` / ``Inter-SemiBold.ttf``  (~47 KB each)
    Latin subset plus the handful of symbols the interface actually paints —
    ``⋯`` U+22EF (the row's overflow glyph, and NOT U+2026), ``·`` U+00B7 (the
    meta-line separator), the arrows and the checks.

``MetaTVIcons.ttf``  (~7 KB)
    Material Symbols Outlined, instantiated at ``FILL 0 / GRAD 0 / opsz 24 /
    wght 400`` and subset to :data:`ICON_NAMES`.

    Subset **by codepoint, not by ligature.** The ligature route needs the
    ``liga`` feature plus every latin letter, and fontTools' layout closure
    then keeps every icon reachable from those letters: 3,621 glyphs, 765 KB.
    By codepoint it is 49 glyphs and 7 KB. ``material_symbols_codepoints.json``
    is emitted alongside so the name→codepoint map cannot drift from the font
    — the same run produces both.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "metatv" / "assets" / "fonts"

INTER_URL = "https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip"
MS_URL = (
    "https://raw.githubusercontent.com/google/material-design-icons/master/"
    "variablefont/MaterialSymbolsOutlined%5BFILL%2CGRAD%2Copsz%2Cwght%5D.ttf"
)
MS_LICENSE_URL = (
    "https://raw.githubusercontent.com/google/material-design-icons/master/LICENSE"
)

#: Latin-1 plus the symbols this interface paints. Keep U+22EF: the row's
#: overflow glyph is ⋯, never … (U+2026), and losing it from the subset would
#: fall the row back to a substituted face mid-string.
INTER_UNICODES = (
    "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
    "U+2000-206F,U+2074,U+20AC,U+2122,U+2190,U+2191,U+2192,U+2193,U+2212,"
    "U+2215,U+22EF,U+25B6,U+2713,U+2714,U+FEFF,U+FFFD"
)

#: One entry per semantic role in metatv/gui/icons.py. The three kind marks are
#: the spec's own choices, made by rendering candidates at row size: `movie`,
#: `tv` (NOT live_tv/smart_display — both carry a play triangle and read as a
#: play button), and `sensors` (NOT satellite_alt, which is scribble at 15px).
ICON_NAMES = [
    "sensors", "movie", "tv", "folder", "play_circle",
    "star", "thumb_up", "thumb_down", "block", "check", "circle",
    "notifications", "notifications_off", "visibility_off", "playlist_add",
    "visibility",
    "search", "calendar_month", "star_half", "auto_awesome", "tune",
    "arrow_forward", "open_in_full", "settings", "build", "splitscreen",
    "expand_more", "chevron_right", "more_horiz", "close", "add", "refresh",
    "warning", "history", "inventory_2", "play_arrow", "grid_view", "view_list",
    "arrow_back", "filter_alt", "info", "delete", "edit", "download",
    "fullscreen", "keyboard_arrow_down", "keyboard_arrow_up", "menu",
]


def _fetch(url: str) -> bytes:
    print(f"  fetching {url.split('/')[-1][:60]}…")
    with urllib.request.urlopen(url, timeout=180) as response:
        return response.read()


def _subset(src: Path, dst: Path, *, unicodes: str, features: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "fontTools.subset", str(src),
         f"--output-file={dst}", f"--unicodes={unicodes}",
         f"--layout-features={features}", "--no-hinting", "--desubroutinize",
         "--drop-tables+=DSIG"],
        check=True, capture_output=True,
    )


def build_inter(work: Path) -> None:
    archive = zipfile.ZipFile(io.BytesIO(_fetch(INTER_URL)))
    archive.extractall(work / "inter")
    (OUT / "LICENSE-Inter-OFL.txt").write_bytes(
        (work / "inter" / "LICENSE.txt").read_bytes()
    )
    for weight in ("Regular", "SemiBold"):
        src = work / "inter" / "extras" / "ttf" / f"Inter-{weight}.ttf"
        dst = OUT / f"Inter-{weight}.ttf"
        _subset(src, dst, unicodes=INTER_UNICODES, features="kern,liga,calt,tnum")
        print(f"  {dst.name}: {dst.stat().st_size // 1024} KB")


def build_icons(work: Path) -> None:
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    raw = work / "ms.ttf"
    raw.write_bytes(_fetch(MS_URL))
    (OUT / "LICENSE-MaterialSymbols-Apache-2.0.txt").write_bytes(_fetch(MS_LICENSE_URL))

    font = instancer.instantiateVariableFont(
        TTFont(raw), {"FILL": 0, "GRAD": 0, "opsz": 24, "wght": 400}, inplace=True
    )
    static = work / "ms_static.ttf"
    font.save(static)

    # Material Symbols names each icon's glyph after its ligature, so the
    # codepoint is a reverse cmap lookup rather than anything to hand-maintain.
    by_name: dict[str, int] = {}
    for codepoint, glyph in TTFont(static).getBestCmap().items():
        by_name.setdefault(glyph, codepoint)

    resolved, missing = {}, []
    for name in ICON_NAMES:
        codepoint = by_name.get(name)
        (missing.append(name) if codepoint is None
         else resolved.__setitem__(name, codepoint))
    if missing:
        raise SystemExit(f"upstream no longer provides: {missing}")

    dst = OUT / "MetaTVIcons.ttf"
    _subset(static, dst,
            unicodes=",".join(f"U+{cp:04X}" for cp in sorted(resolved.values())),
            features="")
    (OUT / "material_symbols_codepoints.json").write_text(
        json.dumps({k: f"{v:04x}" for k, v in sorted(resolved.items())}, indent=1)
    )
    print(f"  {dst.name}: {dst.stat().st_size // 1024} KB, {len(resolved)} icons")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        print("Inter (OFL-1.1):")
        build_inter(work)
        print("Material Symbols Outlined (Apache-2.0):")
        build_icons(work)
    print(f"\nWrote {OUT.relative_to(REPO)} — commit the result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
