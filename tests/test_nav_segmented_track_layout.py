"""The five primary views render as one segmented track, measured in pixels.

They used to be five pills with 30px of nothing between them: no shared edge,
no grouping, and an active view that read as a small filled lozenge rather than
the current tab. Option A of the V3 pass makes them a track — one outline, one
hairline per boundary, and the active view filling its whole cell.

Every assertion here is on **painted QRect geometry**, because that is the only
thing that distinguishes this from the old layout. A test that checked "the
chips exist in order" passes just as happily on five scattered pills: order is
not position. The two properties that actually changed are contiguity (zero gap
between neighbours) and full-cell fill (each chip as tall as the track).

Run in a SUBPROCESS for the same reason as the launch smoke: real geometry
requires the real MainWindow laid out and shown, which spins up ~20 managers
and destabilises the shared pytest QApplication. HOME is redirected so the
child never touches the real user config.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

_REPO_ROOT = Path(__file__).resolve().parents[1]

_CHILD = r"""
import json, os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from unittest.mock import MagicMock

for sub in (".config/metatv", ".local/share/metatv", ".cache/metatv/images"):
    (Path.home() / sub).mkdir(parents=True, exist_ok=True)

from PyQt6.QtWidgets import QApplication
import metatv.gui.main_window as mw

mw.PlayerManager = lambda *a, **k: MagicMock()
mw.MainWindow._run_query = lambda self, *a, **k: None

from metatv.core.config import Config
from metatv.gui import theme as _theme

app = QApplication([])
config, _ = Config.load()
# The QPalette floor, exactly as __main__.py applies it. Without this the
# window boots on Qt's default LIGHT palette and every colour read below is a
# measurement of the wrong app.
_theme.apply_theme(config.theme_name)
win = mw.MainWindow(config)
win.resize(1400, 900)
win.show()
app.processEvents()
win.layout().activate()
app.processEvents()

# Derived, not hand-listed. This was the THIRD copy of the switcher's chip
# list (the builder and _deactivate_view_chips had the other two), and a stale
# copy here measures five cells against a six-cell track — which reads as a
# layout regression rather than as the list being out of date.
from metatv.gui.app_header import NAV_CHIP_SPECS
chips = [getattr(win, attr) for attr, *_ in NAV_CHIP_SPECS]
track = win._nav_track

def rect(w):
    # Map into the track's coordinate space so the numbers are comparable
    # regardless of where the track itself sits in the window.
    tl = w.mapTo(track, w.rect().topLeft())
    return {"x": tl.x(), "y": tl.y(), "w": w.width(), "h": w.height()}

print("GEOM " + json.dumps({
    "chips": [rect(c) for c in chips],
    "labels": [c.text() for c in chips],
    "checked": [c.isChecked() for c in chips],
    "track": {"w": track.width(), "h": track.height()},
}))
"""


@pytest.fixture(scope="module")
def geometry(tmp_path_factory):
    """Boot the real window once and hand every test the measured rects."""
    home = tmp_path_factory.mktemp("home")
    result = subprocess.run(
        [sys.executable, "-c", _CHILD],
        env={
            "HOME": str(home),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(_REPO_ROOT),
            "QT_QPA_PLATFORM": "offscreen",
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    line = next((ln for ln in result.stdout.splitlines()
                 if ln.startswith("GEOM ")), None)
    assert line, (
        f"the window did not report nav geometry (rc={result.returncode}).\n"
        f"--- stdout ---\n{result.stdout[-2000:]}\n"
        f"--- stderr ---\n{result.stderr[-3000:]}"
    )
    return json.loads(line[len("GEOM "):])


def test_neighbouring_cells_share_an_edge(geometry):
    """Zero gap: the defining property of a track versus loose pills.

    Pre-fix this was a 30px spacing, so each pair here was 30px apart.
    """
    chips = geometry["chips"]
    gaps = [
        (geometry["labels"][i], geometry["labels"][i + 1],
         chips[i + 1]["x"] - (chips[i]["x"] + chips[i]["w"]))
        for i in range(len(chips) - 1)
    ]
    bad = [f"{a}|{b} separated by {g}px" for a, b, g in gaps if g != 0]
    assert not bad, "; ".join(bad)


def test_every_cell_fills_the_track_height(geometry):
    """The active view fills its whole cell — the point of Option A.

    A pill sits inset inside its row; a segment is the row. Allowing 2px for
    the track's own 1px border top and bottom.
    """
    track_h = geometry["track"]["h"]
    short = [
        f"{lbl} is {c['h']}px inside a {track_h}px track"
        for lbl, c in zip(geometry["labels"], geometry["chips"])
        if c["h"] < track_h - 2
    ]
    assert not short, "; ".join(short)


def test_all_five_cells_are_the_same_height(geometry):
    """A track reads as a track only if its cells line up."""
    heights = {c["h"] for c in geometry["chips"]}
    assert len(heights) == 1, (
        f"cells are staggered: "
        f"{dict(zip(geometry['labels'], (c['h'] for c in geometry['chips'])))}"
    )


def test_the_cells_are_top_aligned(geometry):
    """Equal heights alone would still allow a vertically-offset cell."""
    tops = {c["y"] for c in geometry["chips"]}
    assert len(tops) == 1, (
        f"cells do not share a baseline: "
        f"{dict(zip(geometry['labels'], (c['y'] for c in geometry['chips'])))}"
    )


def test_the_cells_span_the_whole_track(geometry):
    """No dead strip at either end — the outline must contain only cells."""
    chips = geometry["chips"]
    covered = sum(c["w"] for c in chips)
    assert chips[0]["x"] <= 1, f"the track opens with a {chips[0]['x']}px gap"
    assert covered >= geometry["track"]["w"] - 2, (
        f"cells cover {covered}px of a {geometry['track']['w']}px track"
    )


def test_the_active_view_is_marked_without_the_pill_dot(geometry):
    """The fill is the state cue now, so the dot would be redundant noise.

    Still an explicitly non-colour cue — a filled cell is a shape difference,
    which is what the colour-never-alone rule asks for.
    """
    assert geometry["checked"][0], "Search should start as the active view"
    dotted = [lbl for lbl in geometry["labels"] if "●" in lbl or "○" in lbl]
    assert not dotted, f"segmented cells still carry the pill dot: {dotted}"
